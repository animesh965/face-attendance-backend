"""Centralized leave calculation engine.

Every leave screen (summary, apply, approvals, team, calendar, reports) reads its numbers
from here so eligibility, durations and balances are computed one way only.

Concepts are kept separate on purpose:
  * Mapping    - which leave types an employee may use (employee-type mapping + individual overrides).
  * Allocation - how many days an employee receives in a leave year.
  * Balance    - what is left: accrued allocation + opening + carry forward + adjustments - booked.
  * Booking    - days deducted by approved requests, recorded in the leave_transactions ledger.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.logger import logger
from app.core.time import now_local, now_utc
from app.schemas.leave import LeaveRules
from app.services.policy_service import DEFAULT_POLICY

RULE_FIELDS = list(LeaveRules.model_fields)
DEFAULT_SETTINGS = {"weekly_offs": [5, 6], "leave_year_start_month": 1, "count_pending_against_balance": True}
ACTIVE_STATUSES = ("pending", "approved", "cancellation_pending")
ADMIN_ROLES = ("admin", "super_admin")
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def to_oid(value: Any, label: str = "id") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not value or not ObjectId.is_valid(str(value)):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return ObjectId(str(value))


def oid_list(values: Iterable[Any], label: str = "id") -> list[ObjectId]:
    return list(dict.fromkeys(to_oid(v, label) for v in values))


def sid(value: Any) -> str | None:
    return str(value) if value is not None else None


def parse_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def today() -> date:
    return now_local().date()


def utc_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def half_round(value: float) -> float:
    return round(value * 2) / 2


def is_admin(user: dict) -> bool:
    return user.get("role") in ADMIN_ROLES


def employee_filter() -> dict:
    """Users that take part in leave management: registered employees and employee accounts."""
    return {"is_active": {"$ne": False}, "$or": [{"employee_id": {"$exists": True}}, {"role": "user"}]}


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


async def get_settings(db) -> dict:
    row = await db.leave_settings.find_one({"_id": "global"}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in row.items() if k in DEFAULT_SETTINGS}}


def leave_year_bounds(year: int, settings: dict) -> tuple[date, date]:
    month = int(settings.get("leave_year_start_month", 1))
    start = date(year, month, 1)
    end = date(year + 1, month, 1) - timedelta(days=1)
    return start, end


def leave_year_of(day: date, settings: dict) -> int:
    month = int(settings.get("leave_year_start_month", 1))
    return day.year if day.month >= month else day.year - 1


def holiday_applies(holiday: dict, user: dict) -> bool:
    types = holiday.get("employee_type_ids") or []
    depts = holiday.get("department_ids") or []
    locations = [x.lower() for x in holiday.get("locations") or []]
    if types and user.get("employee_type_id") not in types:
        return False
    if depts and user.get("department_id") not in depts:
        return False
    if locations and (user.get("location") or "").lower() not in locations:
        return False
    return True


async def load_holidays(db, start: date, end: date) -> list[dict]:
    rows = await db.holidays.find({
        "is_active": True,
        "from_date": {"$lte": utc_midnight(end)},
        "to_date": {"$gte": utc_midnight(start)},
    }).to_list(length=None)
    for row in rows:
        row["_from"] = parse_day(row.get("from_date") or row.get("date"))
        row["_to"] = parse_day(row.get("to_date") or row.get("date"))
    return rows


def in_window(doc: dict, day: date) -> bool:
    start = parse_day(doc.get("effective_from"))
    end = parse_day(doc.get("effective_to"))
    return (start is None or start <= day) and (end is None or day <= end)


def shift_for(user: dict, policies_by_id: dict, standard: dict | None) -> dict:
    policy = policies_by_id.get(user.get("policy_id")) or standard or DEFAULT_POLICY
    start = policy.get("start_time", "09:45")
    try:
        h, m = (int(x) for x in start.split(":"))
        total = h * 60 + m + int(policy.get("required_work_minutes", 585))
        end = f"{(total // 60) % 24:02d}:{total % 60:02d}"
    except ValueError:
        end = ""
    return {"name": policy.get("name", "Standard"), "start_time": start, "end_time": end}


async def load_shift_context(db) -> tuple[dict, dict | None]:
    rows = await db.policies.find({"is_active": {"$ne": False}}).to_list(length=None)
    by_id = {row["_id"]: row for row in rows}
    standard = next((row for row in rows if row.get("name") == "Standard"), None)
    return by_id, standard


# ---------------------------------------------------------------------------
# Context: everything needed to evaluate leave for a set of employees in one year
# ---------------------------------------------------------------------------

@dataclass
class LeaveContext:
    year: int
    settings: dict
    leave_types: dict[ObjectId, dict]
    employee_types: dict[ObjectId, dict]
    policies: dict[tuple, dict]
    type_mappings: dict[ObjectId, dict[ObjectId, dict]]
    overrides: dict[ObjectId, dict[ObjectId, dict]]
    type_allocations: dict[tuple, dict]
    employee_allocations: dict[tuple, dict]
    balances: dict[tuple, dict]
    pending: dict[tuple, float]
    holidays: list[dict]
    year_start: date = field(init=False)
    year_end: date = field(init=False)

    def __post_init__(self):
        self.year_start, self.year_end = leave_year_bounds(self.year, self.settings)

    @classmethod
    async def load(cls, db, year: int | None = None, employee_ids: list[ObjectId] | None = None,
                   settings: dict | None = None, exclude_request_id: ObjectId | None = None) -> "LeaveContext":
        settings = settings or await get_settings(db)
        if year is None:
            year = leave_year_of(today(), settings)
        start, end = leave_year_bounds(year, settings)
        emp_q = {"employee_id": {"$in": employee_ids}} if employee_ids is not None else {}

        leave_types = {x["_id"]: x for x in await db.leave_types.find({}).sort([("sort_order", 1), ("name", 1)]).to_list(length=None)}
        employee_types = {x["_id"]: x for x in await db.employee_types.find({}).to_list(length=None)}
        policies = {}
        for row in await db.leave_policies.find({"is_active": True}).to_list(length=None):
            policies[(row["leave_type_id"], row.get("employee_type_id"))] = row
        type_mappings: dict = defaultdict(dict)
        for row in await db.employee_type_leave_mappings.find({"is_current": True}).to_list(length=None):
            type_mappings[row["employee_type_id"]][row["leave_type_id"]] = row
        overrides: dict = defaultdict(dict)
        for row in await db.employee_leave_mappings.find({"is_current": True, **emp_q}).to_list(length=None):
            overrides[row["employee_id"]][row["leave_type_id"]] = row
        type_allocations = {
            (row["employee_type_id"], row["leave_type_id"]): row
            for row in await db.leave_allocations.find({"is_current": True, "year": year, "employee_type_id": {"$ne": None}}).to_list(length=None)
        }
        alloc_q = {"is_current": True, "year": year, "employee_id": {"$ne": None}}
        if employee_ids is not None:
            alloc_q["employee_id"] = {"$in": employee_ids}
        employee_allocations = {
            (row["employee_id"], row["leave_type_id"]): row
            for row in await db.leave_allocations.find(alloc_q).to_list(length=None)
        }
        balances = {
            (row["employee_id"], row["leave_type_id"]): row
            for row in await db.leave_balances.find({"year": year, **emp_q}).to_list(length=None)
        }
        pending_match: dict = {"status": "pending", "year": year, **emp_q}
        if exclude_request_id is not None:
            pending_match["_id"] = {"$ne": exclude_request_id}
        pending: dict = defaultdict(float)
        async for row in db.leave_requests.aggregate([
            {"$match": pending_match},
            {"$group": {"_id": {"e": "$employee_id", "l": "$leave_type_id"}, "days": {"$sum": "$days"}}},
        ]):
            pending[(row["_id"]["e"], row["_id"]["l"])] = float(row["days"])
        holidays = await load_holidays(db, start, end)
        return cls(year, settings, leave_types, employee_types, policies, type_mappings, overrides,
                   type_allocations, employee_allocations, balances, pending, holidays)

    # -- rules ---------------------------------------------------------------

    def rules(self, leave_type_id: ObjectId, employee_type_id: ObjectId | None) -> dict:
        """Leave-type defaults, overlaid by the all-types policy, then the employee-type policy."""
        lt = self.leave_types.get(leave_type_id, {})
        merged = {k: lt.get(k, LeaveRules.model_fields[k].default) for k in RULE_FIELDS}
        merged["policy_source"] = "leave_type"
        layers = [((leave_type_id, None), "global_policy")]
        if employee_type_id:
            layers.append(((leave_type_id, employee_type_id), "employee_type_policy"))
        for key, source in layers:
            policy = self.policies.get(key)
            if policy:
                merged.update({k: policy[k] for k in RULE_FIELDS if k in policy})
                merged["policy_source"] = source
                merged["policy_id"] = str(policy["_id"])
        return merged

    # -- eligibility (mapping) -------------------------------------------------

    def eligibility(self, user: dict, on_date: date | None = None) -> dict[ObjectId, dict]:
        """Resolve which leave types an employee may use on a date.

        Individual overrides win over the employee-type mapping; with neither, the type is not allowed."""
        on_date = on_date or today()
        et_id = user.get("employee_type_id")
        et_maps = self.type_mappings.get(et_id, {}) if et_id else {}
        emp_maps = self.overrides.get(user["_id"], {})
        out = {}
        for lt_id, lt in self.leave_types.items():
            type_row = et_maps.get(lt_id)
            type_enabled = bool(type_row and type_row.get("enabled") and in_window(type_row, on_date))
            override = emp_maps.get(lt_id)
            if override and in_window(override, on_date):
                eligible, source = bool(override.get("enabled")), "employee"
            else:
                eligible, source = type_enabled, "employee_type" if type_enabled else "none"
            if not lt.get("is_active", True):
                eligible = False
            out[lt_id] = {
                "eligible": eligible,
                "source": source,
                "type_enabled": type_enabled,
                "override": None if not override else {
                    "id": str(override["_id"]),
                    "enabled": bool(override.get("enabled")),
                    "effective_from": override.get("effective_from"),
                    "effective_to": override.get("effective_to"),
                    "in_effect": in_window(override, on_date),
                },
            }
        return out

    # -- allocation and balance ------------------------------------------------

    def entitlement(self, user: dict, leave_type_id: ObjectId, rules: dict) -> tuple[float, str]:
        row = self.employee_allocations.get((user["_id"], leave_type_id))
        if row:
            return float(row["days"]), "employee_allocation"
        et_id = user.get("employee_type_id")
        row = self.type_allocations.get((et_id, leave_type_id)) if et_id else None
        if row:
            return float(row["days"]), "employee_type_allocation"
        return float(rules.get("annual_entitlement") or 0), rules.get("policy_source", "leave_type")

    def accrued(self, user: dict, annual: float, rules: dict, as_of: date | None = None) -> float:
        """Credit earned so far this leave year, pro-rated from the joining date."""
        if annual <= 0:
            return 0.0
        as_of = as_of or today()
        joined = parse_day(user.get("date_of_joining"))
        first_month = 0
        if joined and joined > self.year_end:
            return 0.0
        if joined and joined > self.year_start:
            first_month = (joined.year - self.year_start.year) * 12 + joined.month - self.year_start.month
        if rules.get("accrual_frequency") == "monthly":
            if as_of < self.year_start:
                return 0.0
            if as_of > self.year_end:
                months_started = 12
            else:
                months_started = (as_of.year - self.year_start.year) * 12 + as_of.month - self.year_start.month + 1
            months = max(0, min(12, months_started) - first_month)
        else:
            months = 12 - first_month
        return half_round(annual * months / 12)

    def balance(self, user: dict, leave_type_id: ObjectId, rules: dict | None = None) -> dict:
        lt = self.leave_types[leave_type_id]
        rules = rules or self.rules(leave_type_id, user.get("employee_type_id"))
        ledger = self.balances.get((user["_id"], leave_type_id), {})
        booked = float(ledger.get("booked", 0))
        pending = float(self.pending.get((user["_id"], leave_type_id), 0))
        if lt.get("is_lwp"):
            return {"is_lwp": True, "entitlement": 0, "accrued": 0, "opening": 0, "carry_forward": 0, "adjusted": 0,
                    "booked": booked, "pending": pending, "available": None, "applicable": None,
                    "allocation_source": None}
        annual, source = self.entitlement(user, leave_type_id, rules)
        accrued = self.accrued(user, annual, rules)
        opening = float(ledger.get("opening", 0))
        carry = float(ledger.get("carry_forward", 0))
        adjusted = float(ledger.get("adjusted", 0))
        available = accrued + opening + carry + adjusted - booked
        applicable = available - (pending if self.settings.get("count_pending_against_balance", True) else 0)
        if rules.get("allow_negative_balance"):
            applicable += float(rules.get("negative_balance_limit") or 0)
        return {"is_lwp": False, "entitlement": annual, "accrued": accrued, "opening": opening, "carry_forward": carry,
                "adjusted": adjusted, "booked": booked, "pending": pending, "available": round(available, 2),
                "applicable": round(applicable, 2), "allocation_source": source}

    # -- duration --------------------------------------------------------------

    def holiday_on(self, user: dict, day: date) -> dict | None:
        for holiday in self.holidays:
            if holiday["_from"] <= day <= holiday["_to"] and holiday_applies(holiday, user):
                return holiday
        return None

    def duration(self, user: dict, start: date, end: date, half_day: bool, rules: dict) -> dict:
        weekly_offs = set(self.settings.get("weekly_offs", []))
        counted, excluded = [], []
        for day in date_range(start, end):
            if rules.get("exclude_weekly_offs", True) and day.weekday() in weekly_offs:
                excluded.append({"date": iso(day), "reason": f"Weekly off ({WEEKDAY_NAMES[day.weekday()]})"})
                continue
            holiday = self.holiday_on(user, day) if rules.get("exclude_holidays", True) else None
            if holiday:
                excluded.append({"date": iso(day), "reason": f"Holiday: {holiday['name']}"})
                continue
            counted.append(iso(day))
        days = 0.5 if (half_day and counted) else float(len(counted))
        return {"days": days, "counted_dates": counted, "excluded_dates": excluded}

    # -- card for one leave type --------------------------------------------------

    def card(self, user: dict, leave_type_id: ObjectId, elig: dict | None = None) -> dict:
        lt = self.leave_types[leave_type_id]
        rules = self.rules(leave_type_id, user.get("employee_type_id"))
        return {
            **leave_type_brief(lt),
            "eligible": bool(elig and elig["eligible"]),
            "eligibility_source": elig["source"] if elig else "none",
            "allow_half_day": rules["allow_half_day"],
            "requires_document": lt.get("requires_document", False),
            "document_required_after_days": lt.get("document_required_after_days", 0),
            "min_days": rules["min_days"],
            "max_days": rules["max_days"],
            "accrual_frequency": rules["accrual_frequency"],
            "policy_source": rules["policy_source"],
            **self.balance(user, leave_type_id, rules),
        }


def leave_type_brief(lt: dict) -> dict:
    return {
        "leave_type_id": str(lt["_id"]),
        "name": lt.get("name"),
        "code": lt.get("code"),
        "color": lt.get("color", "#3b82f6"),
        "icon": lt.get("icon", "calendar"),
        "is_paid": lt.get("is_paid", True),
        "is_lwp": lt.get("is_lwp", False),
        "is_active": lt.get("is_active", True),
    }


# ---------------------------------------------------------------------------
# employees
# ---------------------------------------------------------------------------

async def employee_lookup(db) -> tuple[dict, dict]:
    departments = {x["_id"]: x for x in await db.departments.find({}, {"name": 1, "code": 1}).to_list(length=None)}
    types = {x["_id"]: x for x in await db.employee_types.find({}).to_list(length=None)}
    return departments, types


def employee_brief(user: dict, departments: dict | None = None, types: dict | None = None) -> dict:
    dept = (departments or {}).get(user.get("department_id")) or {}
    et = (types or {}).get(user.get("employee_type_id")) or {}
    return {
        "id": str(user["_id"]),
        "employee_id": user.get("employee_id") or "",
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "user"),
        "photo": user.get("photo") or "",
        "department_id": sid(user.get("department_id")),
        "department": dept.get("name", ""),
        "employee_type_id": sid(user.get("employee_type_id")),
        "employee_type": et.get("name", ""),
        "reporting_manager_id": sid(user.get("reporting_manager_id")),
        "date_of_joining": user.get("date_of_joining"),
        "probation_end_date": user.get("probation_end_date"),
        "location": user.get("location") or "",
        "gender": user.get("gender") or "",
    }


async def team_member_ids(db, manager_id: ObjectId, recursive: bool) -> list[ObjectId]:
    found: list[ObjectId] = []
    seen = {manager_id}
    frontier = [manager_id]
    while frontier:
        rows = await db.users.find({"reporting_manager_id": {"$in": frontier}, "is_active": {"$ne": False}}, {"_id": 1}).to_list(length=None)
        frontier = [r["_id"] for r in rows if r["_id"] not in seen]
        seen.update(frontier)
        found.extend(frontier)
        if not recursive:
            break
    return found


async def can_view_employee(db, viewer: dict, employee_id: ObjectId) -> bool:
    if is_admin(viewer) or viewer["_id"] == employee_id:
        return True
    return employee_id in set(await team_member_ids(db, viewer["_id"], recursive=True))


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

LEDGER_FIELD = {"booking": "booked", "reversal": "booked", "opening": "opening",
                "carry_forward": "carry_forward", "adjustment": "adjusted", "lapse": "carry_forward"}


async def post_transaction(db, *, employee_id: ObjectId, leave_type_id: ObjectId, year: int, kind: str,
                           days: float, key: str, actor: dict | None = None, request_id: ObjectId | None = None,
                           note: str | None = None) -> bool:
    """Append a ledger entry and update the cached balance. `key` makes the posting idempotent,
    so a retried or concurrent approval can never deduct the same request twice."""
    now = now_utc()
    try:
        await db.leave_transactions.insert_one({
            "employee_id": employee_id, "leave_type_id": leave_type_id, "year": year, "kind": kind,
            "days": float(days), "idempotency_key": key, "request_id": request_id, "note": note,
            "created_by": actor["_id"] if actor else None, "created_at": now,
        })
    except DuplicateKeyError:
        logger.info("Leave ledger entry %s already posted", key)
        return False
    ledger_field = LEDGER_FIELD[kind]
    # Bookings are stored as negative balance effects; the cached "booked" counter is positive.
    inc = -float(days) if ledger_field == "booked" else float(days)
    await db.leave_balances.update_one(
        {"employee_id": employee_id, "leave_type_id": leave_type_id, "year": year},
        {"$inc": {ledger_field: inc}, "$set": {"updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return True


# ---------------------------------------------------------------------------
# audit + notifications
# ---------------------------------------------------------------------------

async def audit(db, actor: dict, action: str, entity: str, entity_id: Any = None, details: dict | None = None):
    await db.audit_logs.insert_one({
        "module": "leave", "action": action, "entity": entity, "entity_id": sid(entity_id),
        "actor_id": actor.get("_id"), "actor_name": actor.get("name"), "actor_role": actor.get("role"),
        "details": details or {}, "created_at": now_utc(),
    })


async def notify(db, user_ids: Iterable[ObjectId], title: str, message: str, link: str = "", kind: str = "leave"):
    now = now_utc()
    docs = [{"user_id": uid, "title": title, "message": message, "link": link, "kind": kind,
             "read": False, "created_at": now} for uid in dict.fromkeys(user_ids)]
    if docs:
        await db.notifications.insert_many(docs)


async def admin_ids(db) -> list[ObjectId]:
    rows = await db.users.find({"role": {"$in": list(ADMIN_ROLES)}, "is_active": {"$ne": False}}, {"_id": 1}).to_list(length=None)
    return [r["_id"] for r in rows]


# ---------------------------------------------------------------------------
# request views
# ---------------------------------------------------------------------------

def request_view(req: dict, leave_types: dict, users: dict, departments: dict | None = None, types: dict | None = None) -> dict:
    lt = leave_types.get(req["leave_type_id"], {})
    emp = users.get(req["employee_id"], {"_id": req["employee_id"]})
    decided = users.get(req.get("decided_by")) if req.get("decided_by") else None
    attachment = req.get("attachment")
    return {
        "id": str(req["_id"]),
        "request_no": req.get("request_no"),
        "employee": employee_brief(emp, departments, types),
        "leave_type": leave_type_brief(lt) if lt else {"leave_type_id": str(req["leave_type_id"]), "name": "Unknown"},
        "from_date": req["from_date"],
        "to_date": req["to_date"],
        "half_day": req.get("half_day", False),
        "half_day_session": req.get("half_day_session"),
        "days": req.get("days", 0),
        "excluded_dates": req.get("excluded_dates", []),
        "team_email": req.get("team_email"),
        "reason": req.get("reason"),
        "attachment": {"name": attachment["filename"], "size": attachment.get("size")} if attachment else None,
        "status": req["status"],
        "applied_at": req.get("applied_at"),
        "updated_at": req.get("updated_at"),
        "decided_by": decided.get("name") if decided else None,
        "decided_by_role": req.get("decided_by_role"),
        "decided_at": req.get("decided_at"),
        "decision_comment": req.get("decision_comment"),
        "comments": [{**c, "by": sid(c.get("by"))} for c in req.get("comments", [])],
        "history": [{**h, "by": sid(h.get("by"))} for h in req.get("history", [])],
        "year": req.get("year"),
    }


async def users_by_id(db, ids: Iterable[ObjectId]) -> dict:
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    return {u["_id"]: u for u in await db.users.find({"_id": {"$in": ids}}).to_list(length=None)}


async def hydrate_requests(db, rows: list[dict]) -> list[dict]:
    leave_types = {x["_id"]: x for x in await db.leave_types.find({}).to_list(length=None)}
    users = await users_by_id(db, [r["employee_id"] for r in rows] + [r.get("decided_by") for r in rows])
    departments, types = await employee_lookup(db)
    return [request_view(r, leave_types, users, departments, types) for r in rows]


# ---------------------------------------------------------------------------
# application validation
# ---------------------------------------------------------------------------

async def validate_application(db, user: dict, data, *, exclude_request_id: ObjectId | None = None,
                               has_attachment: bool = False) -> dict:
    """Run every eligibility, policy, overlap and balance rule. Returns the computed booking."""
    leave_type_id = to_oid(data.leave_type_id, "leave type")
    settings = await get_settings(db)
    year = leave_year_of(data.from_date, settings)
    if leave_year_of(data.to_date, settings) != year:
        raise HTTPException(400, "A leave application cannot span two leave years. Apply separately for each year.")
    ctx = await LeaveContext.load(db, year, [user["_id"]], settings, exclude_request_id)
    lt = ctx.leave_types.get(leave_type_id)
    if not lt or not lt.get("is_active", True):
        raise HTTPException(404, "Leave type not found or inactive")
    elig = ctx.eligibility(user, data.from_date).get(leave_type_id)
    if not elig or not elig["eligible"]:
        raise HTTPException(403, f"You are not eligible for {lt['name']}")
    rules = ctx.rules(leave_type_id, user.get("employee_type_id"))
    now = today()

    if data.half_day and not rules["allow_half_day"]:
        raise HTTPException(400, f"Half-day applications are not allowed for {lt['name']}")
    if data.from_date < now:
        if not rules["allow_past_dates"]:
            raise HTTPException(400, f"{lt['name']} cannot be applied for past dates")
        if (now - data.from_date).days > rules["max_past_days"]:
            raise HTTPException(400, f"Past-dated leave can only be applied within {rules['max_past_days']} days")
    elif rules["advance_notice_days"] and (data.from_date - now).days < rules["advance_notice_days"]:
        raise HTTPException(400, f"{lt['name']} must be applied at least {rules['advance_notice_days']} day(s) in advance")
    probation_end = parse_day(user.get("probation_end_date"))
    if not rules["allow_during_probation"] and probation_end and data.from_date <= probation_end:
        raise HTTPException(400, f"{lt['name']} is not available during probation (ends {iso(probation_end)})")
    if rules["min_service_days"]:
        joined = parse_day(user.get("date_of_joining")) or (user.get("created_at") and user["created_at"].date())
        if joined and (data.from_date - joined).days < rules["min_service_days"]:
            raise HTTPException(400, f"{lt['name']} requires {rules['min_service_days']} days of service")

    calc = ctx.duration(user, data.from_date, data.to_date, data.half_day, rules)
    days = calc["days"]
    if days <= 0:
        raise HTTPException(400, "The selected dates fall entirely on weekly offs or holidays")
    if days < rules["min_days"]:
        raise HTTPException(400, f"Minimum duration for {lt['name']} is {rules['min_days']} day(s)")
    if rules["max_days"] and days > rules["max_days"]:
        raise HTTPException(400, f"Maximum duration for {lt['name']} is {rules['max_days']} day(s) per application")
    needs_doc = lt.get("requires_document") and days > float(lt.get("document_required_after_days") or 0)
    if needs_doc and not has_attachment:
        raise HTTPException(400, f"A supporting document is required for {lt['name']}"
                                 + (f" longer than {lt['document_required_after_days']} day(s)" if lt.get("document_required_after_days") else ""))

    overlap_q = {
        "employee_id": user["_id"], "status": {"$in": list(ACTIVE_STATUSES)},
        "from_date": {"$lte": iso(data.to_date)}, "to_date": {"$gte": iso(data.from_date)},
    }
    if exclude_request_id:
        overlap_q["_id"] = {"$ne": exclude_request_id}
    for other in await db.leave_requests.find(overlap_q).to_list(length=50):
        both_half = data.half_day and other.get("half_day") and other["from_date"] == iso(data.from_date)
        if both_half and other.get("half_day_session") != data.half_day_session:
            continue
        raise HTTPException(409, f"Overlaps with your {other['status'].replace('_', ' ')} request "
                                 f"{other.get('request_no', '')} ({other['from_date']} to {other['to_date']})")

    bal = ctx.balance(user, leave_type_id, rules)
    if not bal["is_lwp"] and days > bal["applicable"]:
        lwp = next((x for x_id, x in ctx.leave_types.items() if x.get("is_lwp") and x.get("is_active", True)
                    and ctx.eligibility(user, data.from_date)[x_id]["eligible"]), None)
        hint = f" You can apply for {lwp['name']} instead." if lwp else ""
        raise HTTPException(400, f"Insufficient {lt['name']} balance: {max(bal['applicable'], 0):g} day(s) can be "
                                 f"applied, {days:g} requested.{hint}")
    return {"leave_type": lt, "year": year, "days": days, "calc": calc, "balance": bal, "rules": rules}


# ---------------------------------------------------------------------------
# workflow
# ---------------------------------------------------------------------------

async def next_request_no(db) -> str:
    counter = await db.counters.find_one_and_update(
        {"_id": "leave_request_no"}, {"$inc": {"sequence": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return f"LR-{counter['sequence']:06d}"


async def acquire_lock(db, user_id: ObjectId):
    """Serialise applications per employee so two concurrent submissions cannot both pass the overlap check."""
    now = now_utc()
    await db.leave_locks.delete_one({"_id": user_id, "expires_at": {"$lt": now}})
    try:
        await db.leave_locks.insert_one({"_id": user_id, "expires_at": now + timedelta(seconds=30)})
    except DuplicateKeyError:
        raise HTTPException(409, "Another leave application is being processed. Please retry in a moment.")


async def release_lock(db, user_id: ObjectId):
    await db.leave_locks.delete_one({"_id": user_id})


def history_entry(action: str, actor: dict, from_status: str | None, to_status: str, comment: str | None = None) -> dict:
    return {"action": action, "by": actor["_id"], "by_name": actor.get("name"), "role": actor.get("role"),
            "from_status": from_status, "to_status": to_status, "comment": comment, "at": now_utc()}


async def record_approval(db, req: dict, actor: dict, action: str, from_status: str, to_status: str, comment: str | None):
    await db.leave_approvals.insert_one({
        "request_id": req["_id"], "request_no": req.get("request_no"), "employee_id": req["employee_id"],
        "leave_type_id": req["leave_type_id"], "action": action, "from_status": from_status, "to_status": to_status,
        "actor_id": actor["_id"], "actor_name": actor.get("name"), "actor_role": actor.get("role"),
        "comment": comment, "created_at": now_utc(),
    })


async def transition(db, req: dict, actor: dict, *, action: str, to_status: str, comment: str | None,
                     extra: dict | None = None) -> dict:
    """Atomically move a request from the status it was read in. If another administrator acted first,
    the version check fails and the caller gets a conflict instead of a second decision."""
    from_status = req["status"]
    update = {
        "$set": {"status": to_status, "updated_at": now_utc(), **(extra or {})},
        "$inc": {"version": 1},
        "$push": {"history": history_entry(action, actor, from_status, to_status, comment)},
    }
    updated = await db.leave_requests.find_one_and_update(
        {"_id": req["_id"], "status": from_status, "version": req.get("version", 0)},
        update, return_document=ReturnDocument.AFTER)
    if not updated:
        current = await db.leave_requests.find_one({"_id": req["_id"]})
        who = ""
        if current and current.get("decided_by"):
            decider = await db.users.find_one({"_id": current["decided_by"]}, {"name": 1})
            who = f" by {decider.get('name')}" if decider else ""
        state = current["status"].replace("_", " ") if current else "removed"
        raise HTTPException(409, f"This request was already updated{who} and is now {state}. Refresh to see the latest status.")
    await record_approval(db, updated, actor, action, from_status, to_status, comment)
    return updated


async def book(db, req: dict, actor: dict):
    if req.get("booked_days"):
        return
    await post_transaction(db, employee_id=req["employee_id"], leave_type_id=req["leave_type_id"], year=req["year"],
                           kind="booking", days=-float(req["days"]), key=f"{req['_id']}:booking:{req['version']}",
                           actor=actor, request_id=req["_id"], note=f"Approved {req.get('request_no')}")
    await db.leave_requests.update_one({"_id": req["_id"]}, {"$set": {"booked_days": float(req["days"])}})


async def unbook(db, req: dict, actor: dict, note: str):
    booked = float(req.get("booked_days") or 0)
    if not booked:
        return
    await post_transaction(db, employee_id=req["employee_id"], leave_type_id=req["leave_type_id"], year=req["year"],
                           kind="reversal", days=booked, key=f"{req['_id']}:reversal:{req['version']}",
                           actor=actor, request_id=req["_id"], note=note)
    await db.leave_requests.update_one({"_id": req["_id"]}, {"$set": {"booked_days": 0}})


async def get_request(db, request_id: str) -> dict:
    req = await db.leave_requests.find_one({"_id": to_oid(request_id, "request id")})
    if not req:
        raise HTTPException(404, "Leave request not found")
    return req


async def recheck_balance(db, req: dict):
    employee = await db.users.find_one({"_id": req["employee_id"]})
    if not employee:
        raise HTTPException(404, "Employee no longer exists")
    ctx = await LeaveContext.load(db, req["year"], [employee["_id"]], exclude_request_id=req["_id"])
    lt = ctx.leave_types.get(req["leave_type_id"])
    if not lt:
        raise HTTPException(409, "Leave type no longer exists")
    bal = ctx.balance(employee, req["leave_type_id"])
    if not bal["is_lwp"] and float(req["days"]) > bal["applicable"] + 1e-9:
        raise HTTPException(409, f"{employee.get('name')} no longer has enough {lt['name']} balance "
                                 f"({max(bal['applicable'], 0):g} available, {req['days']:g} requested)")
