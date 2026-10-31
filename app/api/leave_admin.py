"""Leave administration APIs: employee types, leave types, policies, mappings, allocations,
approvals and reports. Only Admin and Super Admin hold these permissions; overriding a final
decision additionally requires Super Admin."""
import re
from collections import defaultdict
from datetime import date, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.core.database import get_database
from app.core.time import now_utc
from app.dependencies.permissions import require_permission
from app.schemas.leave import (
    AdjustmentIn, AllocationIn, CarryForwardIn, DecisionIn, EmployeeLeaveProfileIn, EmployeeMappingSaveIn,
    EmployeeTypeIn, LeavePolicyIn, LeaveSettingsIn, LeaveTypeIn, OverrideIn, RejectIn, TypeMappingSaveIn,
)
from app.services import leave_service as ls
from app.api.leave import apply_request_filters, page_params, paginate, SORT_FIELDS

router = APIRouter(prefix="/api/v1/leave/admin", tags=["Leave Administration"])
manage = require_permission("leave.manage")
approve = require_permission("leave.approve")


def name_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


async def actor_names(db, ids) -> dict:
    users = await ls.users_by_id(db, ids)
    return {k: v.get("name") for k, v in users.items()}


# ---------------------------------------------------------------------------
# Employee types and employee leave profiles
# ---------------------------------------------------------------------------

def employee_type_view(row: dict, counts: dict | None = None) -> dict:
    return {"id": str(row["_id"]), "name": row["name"], "code": row.get("code"), "description": row.get("description"),
            "is_active": row.get("is_active", True), "employee_count": (counts or {}).get(row["_id"], 0),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}


@router.get("/employee-types")
async def list_employee_types(include_inactive: bool = True, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    query = {} if include_inactive else {"is_active": True}
    rows = await db.employee_types.find(query).sort("name", 1).to_list(length=None)
    counts = {r["_id"]: r["n"] async for r in db.users.aggregate([
        {"$match": {"employee_type_id": {"$ne": None}, "is_active": {"$ne": False}}},
        {"$group": {"_id": "$employee_type_id", "n": {"$sum": 1}}}])}
    return [employee_type_view(r, counts) for r in rows]


@router.post("/employee-types", status_code=201)
async def create_employee_type(data: EmployeeTypeIn, user=Depends(manage), db=Depends(get_database)):
    now = now_utc()
    doc = {**data.model_dump(), "name_key": name_key(data.name), "created_by": user["_id"], "updated_by": user["_id"],
           "created_at": now, "updated_at": now}
    try:
        res = await db.employee_types.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "An employee type with this name already exists")
    doc["_id"] = res.inserted_id
    await ls.audit(db, user, "employee_type.created", "employee_type", res.inserted_id, {"name": data.name})
    return employee_type_view(doc)


@router.put("/employee-types/{type_id}")
async def update_employee_type(type_id: str, data: EmployeeTypeIn, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(type_id, "employee type id")
    try:
        res = await db.employee_types.update_one({"_id": oid}, {"$set": {
            **data.model_dump(), "name_key": name_key(data.name), "updated_by": user["_id"], "updated_at": now_utc()}})
    except DuplicateKeyError:
        raise HTTPException(409, "An employee type with this name already exists")
    if not res.matched_count:
        raise HTTPException(404, "Employee type not found")
    await ls.audit(db, user, "employee_type.updated", "employee_type", oid, data.model_dump())
    return employee_type_view(await db.employee_types.find_one({"_id": oid}))


@router.get("/employees")
async def list_employees(
    search: str | None = None, employee_type_id: str | None = None, department_id: str | None = None,
    unassigned: bool = False, page: int = Query(1, ge=1), page_size: int = Query(500, ge=1, le=2000),
    user=Depends(require_permission("leave.approve")), db=Depends(get_database),
):
    query: dict = ls.employee_filter()
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        query = {"$and": [query, {"$or": [{"name": pattern}, {"employee_id": pattern}, {"email": pattern}]}]}
    if employee_type_id:
        query["employee_type_id"] = ls.to_oid(employee_type_id, "employee type id")
    elif unassigned:
        query["employee_type_id"] = None
    if department_id:
        query["department_id"] = ls.to_oid(department_id, "department id")
    total = await db.users.count_documents(query)
    rows = await db.users.find(query).sort("name", 1).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
    departments, types = await ls.employee_lookup(db)
    managers = await actor_names(db, [r.get("reporting_manager_id") for r in rows])
    items = [{**ls.employee_brief(r, departments, types), "reporting_manager": managers.get(r.get("reporting_manager_id")),
              "policy_id": ls.sid(r.get("policy_id"))} for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def validate_manager(db, employee_id: ObjectId, manager_id: ObjectId):
    if manager_id == employee_id:
        raise HTTPException(400, "An employee cannot report to themselves")
    manager = await db.users.find_one({"_id": manager_id, "is_active": {"$ne": False}})
    if not manager:
        raise HTTPException(404, "Reporting manager not found")
    # Walk up the manager's chain to block reporting cycles.
    seen, current = set(), manager
    while current and current.get("reporting_manager_id"):
        nxt = current["reporting_manager_id"]
        if nxt == employee_id:
            raise HTTPException(400, "This would create a reporting cycle")
        if nxt in seen:
            break
        seen.add(nxt)
        current = await db.users.find_one({"_id": nxt}, {"reporting_manager_id": 1})


async def set_employee_type(db, employee: dict, type_id: ObjectId | None, actor: dict):
    if employee.get("employee_type_id") == type_id:
        return
    await db.employee_type_history.insert_one({
        "employee_id": employee["_id"], "from_type_id": employee.get("employee_type_id"), "to_type_id": type_id,
        "changed_by": actor["_id"], "changed_at": now_utc()})


@router.put("/employees/{employee_id}/profile")
async def update_employee_profile(employee_id: str, data: EmployeeLeaveProfileIn, user=Depends(manage), db=Depends(get_database)):
    emp_id = ls.to_oid(employee_id, "employee id")
    employee = await db.users.find_one({"_id": emp_id})
    if not employee:
        raise HTTPException(404, "Employee not found")
    type_id = ls.to_oid(data.employee_type_id, "employee type id") if data.employee_type_id else None
    if type_id and not await db.employee_types.find_one({"_id": type_id, "is_active": True}):
        raise HTTPException(404, "Employee type not found or inactive")
    manager_id = ls.to_oid(data.reporting_manager_id, "reporting manager id") if data.reporting_manager_id else None
    if manager_id:
        await validate_manager(db, emp_id, manager_id)
    policy_id = ls.to_oid(data.policy_id, "shift policy id") if data.policy_id else None
    if policy_id and not await db.policies.find_one({"_id": policy_id}):
        raise HTTPException(404, "Shift / attendance policy not found")
    if data.date_of_joining and data.probation_end_date and data.probation_end_date < data.date_of_joining:
        raise HTTPException(400, "Probation end date must be after the joining date")
    await set_employee_type(db, employee, type_id, user)
    update = {"employee_type_id": type_id, "reporting_manager_id": manager_id,
              "date_of_joining": ls.iso(data.date_of_joining), "probation_end_date": ls.iso(data.probation_end_date),
              "location": data.location, "policy_id": policy_id, "updated_at": now_utc(), "updated_by": user["_id"]}
    await db.users.update_one({"_id": emp_id}, {"$set": update})
    await ls.audit(db, user, "employee.leave_profile_updated", "employee", emp_id,
                   {k: ls.sid(v) if isinstance(v, ObjectId) else v for k, v in update.items() if k not in ("updated_at", "updated_by")})
    departments, types = await ls.employee_lookup(db)
    return ls.employee_brief(await db.users.find_one({"_id": emp_id}), departments, types)


@router.post("/employees/assign-type")
async def bulk_assign_type(payload: dict, user=Depends(manage), db=Depends(get_database)):
    ids = ls.oid_list(payload.get("employee_ids") or [], "employee id")
    if not ids:
        raise HTTPException(400, "Select at least one employee")
    type_id = ls.to_oid(payload.get("employee_type_id"), "employee type id")
    if not await db.employee_types.find_one({"_id": type_id, "is_active": True}):
        raise HTTPException(404, "Employee type not found or inactive")
    for employee in await db.users.find({"_id": {"$in": ids}}).to_list(length=None):
        await set_employee_type(db, employee, type_id, user)
    res = await db.users.update_many({"_id": {"$in": ids}}, {"$set": {"employee_type_id": type_id, "updated_at": now_utc(), "updated_by": user["_id"]}})
    await ls.audit(db, user, "employee.type_bulk_assigned", "employee_type", type_id, {"count": res.modified_count})
    return {"updated": res.modified_count}


@router.get("/shift-policies")
async def shift_policies(user=Depends(manage), db=Depends(get_database)):
    rows = await db.policies.find({}).sort("name", 1).to_list(length=None)
    return [{"id": str(r["_id"]), **ls.shift_for({"policy_id": r["_id"]}, {r["_id"]: r}, None)} for r in rows]


# ---------------------------------------------------------------------------
# Leave types
# ---------------------------------------------------------------------------

def leave_type_view(row: dict) -> dict:
    return {"id": str(row["_id"]), **{k: v for k, v in row.items() if k not in ("_id", "name_key", "created_by", "updated_by")}}


@router.get("/leave-types")
async def list_leave_types(include_inactive: bool = True, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    query = {} if include_inactive else {"is_active": True}
    rows = await db.leave_types.find(query).sort([("sort_order", 1), ("name", 1)]).to_list(length=None)
    return [leave_type_view(r) for r in rows]


@router.post("/leave-types", status_code=201)
async def create_leave_type(data: LeaveTypeIn, user=Depends(manage), db=Depends(get_database)):
    now = now_utc()
    doc = {**data.model_dump(), "name_key": name_key(data.name), "created_by": user["_id"], "updated_by": user["_id"],
           "created_at": now, "updated_at": now}
    try:
        res = await db.leave_types.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "A leave type with this name or code already exists")
    doc["_id"] = res.inserted_id
    await ls.audit(db, user, "leave_type.created", "leave_type", res.inserted_id, {"name": data.name, "code": data.code})
    return leave_type_view(doc)


@router.put("/leave-types/{leave_type_id}")
async def update_leave_type(leave_type_id: str, data: LeaveTypeIn, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(leave_type_id, "leave type id")
    before = await db.leave_types.find_one({"_id": oid})
    if not before:
        raise HTTPException(404, "Leave type not found")
    try:
        await db.leave_types.update_one({"_id": oid}, {"$set": {
            **data.model_dump(), "name_key": name_key(data.name), "updated_by": user["_id"], "updated_at": now_utc()}})
    except DuplicateKeyError:
        raise HTTPException(409, "A leave type with this name or code already exists")
    changed = {k: v for k, v in data.model_dump().items() if before.get(k) != v}
    await ls.audit(db, user, "leave_type.updated", "leave_type", oid, changed)
    return leave_type_view(await db.leave_types.find_one({"_id": oid}))


@router.patch("/leave-types/{leave_type_id}/status")
async def set_leave_type_status(leave_type_id: str, payload: dict, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(leave_type_id, "leave type id")
    active = bool(payload.get("is_active"))
    res = await db.leave_types.update_one({"_id": oid}, {"$set": {"is_active": active, "updated_by": user["_id"], "updated_at": now_utc()}})
    if not res.matched_count:
        raise HTTPException(404, "Leave type not found")
    await ls.audit(db, user, "leave_type.activated" if active else "leave_type.deactivated", "leave_type", oid)
    return {"success": True, "is_active": active}


# ---------------------------------------------------------------------------
# Policies and global settings
# ---------------------------------------------------------------------------

async def policy_views(db, rows: list[dict]) -> list[dict]:
    lts = {x["_id"]: x["name"] for x in await db.leave_types.find({}, {"name": 1}).to_list(length=None)}
    ets = {x["_id"]: x["name"] for x in await db.employee_types.find({}, {"name": 1}).to_list(length=None)}
    return [{"id": str(r["_id"]), **{k: v for k, v in r.items() if k not in ("_id", "leave_type_id", "employee_type_id", "created_by", "updated_by")},
             "leave_type_id": str(r["leave_type_id"]), "leave_type": lts.get(r["leave_type_id"], "Unknown"),
             "employee_type_id": ls.sid(r.get("employee_type_id")), "employee_type": ets.get(r.get("employee_type_id"), "All employee types")}
            for r in rows]


async def validate_policy_refs(db, data: LeavePolicyIn) -> tuple[ObjectId, ObjectId | None]:
    lt_id = ls.to_oid(data.leave_type_id, "leave type id")
    if not await db.leave_types.find_one({"_id": lt_id}):
        raise HTTPException(404, "Leave type not found")
    et_id = ls.to_oid(data.employee_type_id, "employee type id") if data.employee_type_id else None
    if et_id and not await db.employee_types.find_one({"_id": et_id}):
        raise HTTPException(404, "Employee type not found")
    return lt_id, et_id


@router.get("/policies")
async def list_policies(include_inactive: bool = False, user=Depends(manage), db=Depends(get_database)):
    query = {} if include_inactive else {"is_active": True}
    return await policy_views(db, await db.leave_policies.find(query).sort("created_at", 1).to_list(length=None))


@router.post("/policies", status_code=201)
async def create_policy(data: LeavePolicyIn, user=Depends(manage), db=Depends(get_database)):
    lt_id, et_id = await validate_policy_refs(db, data)
    now = now_utc()
    doc = {**data.model_dump(exclude={"leave_type_id", "employee_type_id"}), "leave_type_id": lt_id, "employee_type_id": et_id,
           "created_by": user["_id"], "updated_by": user["_id"], "created_at": now, "updated_at": now}
    try:
        res = await db.leave_policies.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "An active policy already exists for this leave type and employee type. Edit it instead.")
    await ls.audit(db, user, "leave_policy.created", "leave_policy", res.inserted_id, {"leave_type_id": str(lt_id), "employee_type_id": ls.sid(et_id)})
    return (await policy_views(db, [await db.leave_policies.find_one({"_id": res.inserted_id})]))[0]


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, data: LeavePolicyIn, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(policy_id, "policy id")
    lt_id, et_id = await validate_policy_refs(db, data)
    try:
        res = await db.leave_policies.update_one({"_id": oid}, {"$set": {
            **data.model_dump(exclude={"leave_type_id", "employee_type_id"}), "leave_type_id": lt_id, "employee_type_id": et_id,
            "updated_by": user["_id"], "updated_at": now_utc()}})
    except DuplicateKeyError:
        raise HTTPException(409, "An active policy already exists for this leave type and employee type")
    if not res.matched_count:
        raise HTTPException(404, "Policy not found")
    await ls.audit(db, user, "leave_policy.updated", "leave_policy", oid, data.model_dump())
    return (await policy_views(db, [await db.leave_policies.find_one({"_id": oid})]))[0]


@router.delete("/policies/{policy_id}")
async def deactivate_policy(policy_id: str, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(policy_id, "policy id")
    res = await db.leave_policies.update_one({"_id": oid, "is_active": True}, {"$set": {"is_active": False, "updated_by": user["_id"], "updated_at": now_utc()}})
    if not res.matched_count:
        raise HTTPException(404, "Active policy not found")
    await ls.audit(db, user, "leave_policy.deactivated", "leave_policy", oid)
    return {"success": True}


@router.put("/settings")
async def update_settings(data: LeaveSettingsIn, user=Depends(manage), db=Depends(get_database)):
    await db.leave_settings.update_one({"_id": "global"}, {"$set": {**data.model_dump(), "updated_by": user["_id"], "updated_at": now_utc()}}, upsert=True)
    await ls.audit(db, user, "leave_settings.updated", "leave_settings", "global", data.model_dump())
    return await ls.get_settings(db)


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

def mapping_view(row: dict, names: dict) -> dict:
    return {"id": str(row["_id"]), "leave_type_id": str(row["leave_type_id"]),
            "employee_type_id": ls.sid(row.get("employee_type_id")), "employee_id": ls.sid(row.get("employee_id")),
            "enabled": row.get("enabled", False), "effective_from": row.get("effective_from"), "effective_to": row.get("effective_to"),
            "is_current": row.get("is_current", False), "note": row.get("note"),
            "created_by": names.get(row.get("created_by")), "updated_by": names.get(row.get("updated_by")),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}


@router.get("/mappings/employee-types")
async def get_type_mappings(user=Depends(manage), db=Depends(get_database)):
    rows = await db.employee_type_leave_mappings.find({"is_current": True}).to_list(length=None)
    names = await actor_names(db, [r.get("updated_by") for r in rows] + [r.get("created_by") for r in rows])
    return [mapping_view(r, names) for r in rows]


async def close_mapping(collection, row: dict, actor: dict, when: str):
    res = await collection.update_one({"_id": row["_id"], "is_current": True}, {"$set": {
        "is_current": False, "effective_to": row.get("effective_to") or when, "closed_at": now_utc(),
        "updated_by": actor["_id"], "updated_at": now_utc()}})
    if not res.modified_count:
        raise HTTPException(409, "These mappings were changed by someone else. Reload and try again.")


@router.post("/mappings/employee-types")
async def save_type_mappings(data: TypeMappingSaveIn, dry_run: bool = False, user=Depends(manage), db=Depends(get_database)):
    et_ids = ls.oid_list(data.employee_type_ids, "employee type id")
    wanted = set(ls.oid_list(data.leave_type_ids, "leave type id"))
    unchanged = set(ls.oid_list(data.unchanged_leave_type_ids, "leave type id"))
    ets = {x["_id"]: x for x in await db.employee_types.find({"_id": {"$in": et_ids}}).to_list(length=None)}
    if len(ets) != len(et_ids):
        raise HTTPException(404, "One or more employee types were not found")
    lts = {x["_id"]: x for x in await db.leave_types.find({}).to_list(length=None)}
    if not wanted <= set(lts):
        raise HTTPException(404, "One or more leave types were not found")
    current = {(r["employee_type_id"], r["leave_type_id"]): r for r in await db.employee_type_leave_mappings.find(
        {"is_current": True, "employee_type_id": {"$in": et_ids}}).to_list(length=None)}

    changes, empty_types = [], []
    for et_id in et_ids:
        enabled_after = 0
        for lt_id, lt in lts.items():
            row = current.get((et_id, lt_id))
            was = bool(row and row.get("enabled"))
            now_enabled = was if lt_id in unchanged else lt_id in wanted
            enabled_after += now_enabled and lt.get("is_active", True)
            if was != now_enabled:
                changes.append({"employee_type_id": str(et_id), "employee_type": ets[et_id]["name"], "leave_type_id": str(lt_id),
                                "leave_type": lt["name"], "change": "added" if now_enabled else "removed", "_row": row})
        if not enabled_after:
            empty_types.append(ets[et_id]["name"])
    summary = {"added": sum(c["change"] == "added" for c in changes), "removed": sum(c["change"] == "removed" for c in changes),
               "employee_types_without_leave": empty_types,
               "changes": [{k: v for k, v in c.items() if k != "_row"} for c in changes]}
    if dry_run or not changes:
        return {**summary, "saved": False}

    when = ls.today().isoformat()
    now = now_utc()
    for c in changes:
        if c["_row"]:
            await close_mapping(db.employee_type_leave_mappings, c["_row"], user, when)
        try:
            await db.employee_type_leave_mappings.insert_one({
                "employee_type_id": ObjectId(c["employee_type_id"]), "leave_type_id": ObjectId(c["leave_type_id"]),
                "enabled": c["change"] == "added", "effective_from": ls.iso(data.effective_from) if c["change"] == "added" else when,
                "effective_to": None, "is_current": True, "created_by": user["_id"], "updated_by": user["_id"],
                "created_at": now, "updated_at": now})
        except DuplicateKeyError:
            raise HTTPException(409, "These mappings were changed by someone else. Reload and try again.")
    await ls.audit(db, user, "mapping.employee_type.saved", "employee_type_leave_mapping", None,
                   {"added": summary["added"], "removed": summary["removed"], "changes": summary["changes"]})
    return {**summary, "saved": True}


@router.get("/mappings/employees")
async def get_employee_mappings(employee_id: str | None = None, user=Depends(manage), db=Depends(get_database)):
    query: dict = {"is_current": True}
    if employee_id:
        query["employee_id"] = ls.to_oid(employee_id, "employee id")
    rows = await db.employee_leave_mappings.find(query).sort("updated_at", -1).to_list(length=5000)
    users = await ls.users_by_id(db, [r["employee_id"] for r in rows])
    names = await actor_names(db, [r.get("updated_by") for r in rows] + [r.get("created_by") for r in rows])
    departments, types = await ls.employee_lookup(db)
    return [{**mapping_view(r, names), "employee": ls.employee_brief(users[r["employee_id"]], departments, types) if r["employee_id"] in users else None}
            for r in rows]


@router.post("/mappings/employees")
async def save_employee_mappings(data: EmployeeMappingSaveIn, user=Depends(manage), db=Depends(get_database)):
    emp_ids = ls.oid_list(data.employee_ids, "employee id")
    lt_ids = ls.oid_list(data.leave_type_ids, "leave type id")
    if await db.users.count_documents({"_id": {"$in": emp_ids}}) != len(emp_ids):
        raise HTTPException(404, "One or more employees were not found")
    if await db.leave_types.count_documents({"_id": {"$in": lt_ids}}) != len(lt_ids):
        raise HTTPException(404, "One or more leave types were not found")
    current = {(r["employee_id"], r["leave_type_id"]): r for r in await db.employee_leave_mappings.find(
        {"is_current": True, "employee_id": {"$in": emp_ids}, "leave_type_id": {"$in": lt_ids}}).to_list(length=None)}
    when = ls.today().isoformat()
    now = now_utc()
    eff_from, eff_to = ls.iso(data.effective_from), ls.iso(data.effective_to)
    created = closed = unchanged = 0
    for emp_id in emp_ids:
        for lt_id in lt_ids:
            row = current.get((emp_id, lt_id))
            if data.action == "inherit":
                if row:
                    await close_mapping(db.employee_leave_mappings, row, user, when)
                    closed += 1
                else:
                    unchanged += 1
                continue
            enabled = data.action == "enable"
            if row and row.get("enabled") == enabled and row.get("effective_from") == eff_from and row.get("effective_to") == eff_to:
                unchanged += 1
                continue
            if row:
                await close_mapping(db.employee_leave_mappings, row, user, when)
            try:
                await db.employee_leave_mappings.insert_one({
                    "employee_id": emp_id, "leave_type_id": lt_id, "enabled": enabled, "effective_from": eff_from,
                    "effective_to": eff_to, "note": data.note, "is_current": True, "created_by": user["_id"],
                    "updated_by": user["_id"], "created_at": now, "updated_at": now})
            except DuplicateKeyError:
                raise HTTPException(409, "These overrides were changed by someone else. Reload and try again.")
            created += 1
    await ls.audit(db, user, f"mapping.employee.{data.action}", "employee_leave_mapping", None,
                   {"employees": len(emp_ids), "leave_types": [str(x) for x in lt_ids], "created": created, "removed": closed})
    return {"created": created, "removed": closed, "unchanged": unchanged}


@router.get("/eligibility")
async def resolve_eligibility(employee_ids: str, on_date: date | None = None, user=Depends(approve), db=Depends(get_database)):
    ids = ls.oid_list([x for x in employee_ids.split(",") if x], "employee id")[:500]
    if not ids:
        raise HTTPException(400, "Provide at least one employee id")
    employees = await db.users.find({"_id": {"$in": ids}}).to_list(length=None)
    ctx = await ls.LeaveContext.load(db, None, ids)
    out = {}
    for emp in employees:
        elig = ctx.eligibility(emp, on_date)
        out[str(emp["_id"])] = {str(k): {"eligible": v["eligible"], "source": v["source"], "type_enabled": v["type_enabled"],
                                         "override": v["override"]} for k, v in elig.items()}
    return out


@router.get("/mappings/history")
async def mapping_history(employee_type_id: str | None = None, employee_id: str | None = None, limit: int = Query(200, le=1000),
                          user=Depends(manage), db=Depends(get_database)):
    if employee_id:
        coll, query = db.employee_leave_mappings, {"employee_id": ls.to_oid(employee_id, "employee id")}
    else:
        coll = db.employee_type_leave_mappings
        query = {"employee_type_id": ls.to_oid(employee_type_id, "employee type id")} if employee_type_id else {}
    rows = await coll.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    names = await actor_names(db, [r.get("updated_by") for r in rows] + [r.get("created_by") for r in rows])
    return [mapping_view(r, names) for r in rows]


# ---------------------------------------------------------------------------
# Allocation, adjustments, balances, carry forward
# ---------------------------------------------------------------------------

@router.get("/allocations")
async def list_allocations(year: int, leave_type_id: str | None = None, user=Depends(manage), db=Depends(get_database)):
    query: dict = {"is_current": True, "year": year}
    if leave_type_id:
        query["leave_type_id"] = ls.to_oid(leave_type_id, "leave type id")
    rows = await db.leave_allocations.find(query).sort("updated_at", -1).to_list(length=None)
    users = await ls.users_by_id(db, [r.get("employee_id") for r in rows])
    names = await actor_names(db, [r.get("updated_by") for r in rows])
    lts = {x["_id"]: x["name"] for x in await db.leave_types.find({}, {"name": 1}).to_list(length=None)}
    ets = {x["_id"]: x["name"] for x in await db.employee_types.find({}, {"name": 1}).to_list(length=None)}
    return [{"id": str(r["_id"]), "year": r["year"], "days": r["days"], "leave_type_id": str(r["leave_type_id"]),
             "leave_type": lts.get(r["leave_type_id"]), "employee_type_id": ls.sid(r.get("employee_type_id")),
             "employee_type": ets.get(r.get("employee_type_id")), "employee_id": ls.sid(r.get("employee_id")),
             "employee": users[r["employee_id"]].get("name") if r.get("employee_id") in users else None,
             "employee_code": users[r["employee_id"]].get("employee_id") if r.get("employee_id") in users else None,
             "scope": "employee" if r.get("employee_id") else "employee_type", "note": r.get("note"),
             "updated_by": names.get(r.get("updated_by")), "updated_at": r.get("updated_at")} for r in rows]


@router.post("/allocations")
async def save_allocation(data: AllocationIn, user=Depends(manage), db=Depends(get_database)):
    lt_id = ls.to_oid(data.leave_type_id, "leave type id")
    lt = await db.leave_types.find_one({"_id": lt_id})
    if not lt:
        raise HTTPException(404, "Leave type not found")
    if lt.get("is_lwp"):
        raise HTTPException(400, "Leave Without Pay types are not allocated; they have no balance")
    targets: list[dict] = []
    if data.employee_type_id:
        et_id = ls.to_oid(data.employee_type_id, "employee type id")
        if not await db.employee_types.find_one({"_id": et_id}):
            raise HTTPException(404, "Employee type not found")
        targets.append({"employee_type_id": et_id, "employee_id": None})
    else:
        ids = ls.oid_list(data.employee_ids, "employee id")
        if await db.users.count_documents({"_id": {"$in": ids}}) != len(ids):
            raise HTTPException(404, "One or more employees were not found")
        targets.extend({"employee_type_id": None, "employee_id": i} for i in ids)
    now = now_utc()
    for target in targets:
        key = {**target, "leave_type_id": lt_id, "year": data.year}
        await db.leave_allocations.update_many({**key, "is_current": True}, {"$set": {"is_current": False, "updated_at": now, "updated_by": user["_id"]}})
        await db.leave_allocations.insert_one({**key, "days": data.days, "note": data.note, "is_current": True,
                                               "source": "manual" if len(targets) == 1 else "bulk",
                                               "created_by": user["_id"], "updated_by": user["_id"], "created_at": now, "updated_at": now})
    await ls.audit(db, user, "allocation.saved", "leave_allocation", None,
                   {"leave_type": lt["name"], "year": data.year, "days": data.days, "targets": len(targets),
                    "employee_type_id": data.employee_type_id})
    return {"saved": len(targets)}


@router.delete("/allocations/{allocation_id}")
async def remove_allocation(allocation_id: str, user=Depends(manage), db=Depends(get_database)):
    oid = ls.to_oid(allocation_id, "allocation id")
    res = await db.leave_allocations.update_one({"_id": oid, "is_current": True}, {"$set": {"is_current": False, "updated_at": now_utc(), "updated_by": user["_id"]}})
    if not res.matched_count:
        raise HTTPException(404, "Allocation not found")
    await ls.audit(db, user, "allocation.removed", "leave_allocation", oid)
    return {"success": True}


@router.post("/adjustments")
async def adjust_balance(data: AdjustmentIn, user=Depends(manage), db=Depends(get_database)):
    lt_id = ls.to_oid(data.leave_type_id, "leave type id")
    lt = await db.leave_types.find_one({"_id": lt_id})
    if not lt:
        raise HTTPException(404, "Leave type not found")
    if lt.get("is_lwp"):
        raise HTTPException(400, "Leave Without Pay has no balance to adjust")
    ids = ls.oid_list(data.employee_ids, "employee id")
    if await db.users.count_documents({"_id": {"$in": ids}}) != len(ids):
        raise HTTPException(404, "One or more employees were not found")
    now = now_utc()
    for emp_id in ids:
        res = await db.leave_adjustments.insert_one({
            "employee_id": emp_id, "leave_type_id": lt_id, "year": data.year, "kind": data.kind, "days": data.days,
            "reason": data.reason, "created_by": user["_id"], "created_at": now})
        await ls.post_transaction(db, employee_id=emp_id, leave_type_id=lt_id, year=data.year, kind=data.kind, days=data.days,
                                  key=f"adjustment:{res.inserted_id}", actor=user, note=data.reason)
    await ls.audit(db, user, f"balance.{data.kind}", "leave_balance", None,
                   {"leave_type": lt["name"], "year": data.year, "days": data.days, "employees": len(ids), "reason": data.reason})
    await ls.notify(db, ids, "Leave balance updated", f"Your {lt['name']} balance for {data.year} was adjusted by {data.days:+g} day(s): {data.reason}",
                    "/leave/summary")
    return {"adjusted": len(ids)}


@router.get("/adjustments")
async def list_adjustments(year: int, employee_id: str | None = None, user=Depends(manage), db=Depends(get_database)):
    query: dict = {"year": year}
    if employee_id:
        query["employee_id"] = ls.to_oid(employee_id, "employee id")
    rows = await db.leave_adjustments.find(query).sort("created_at", -1).limit(1000).to_list(length=1000)
    users = await ls.users_by_id(db, [r["employee_id"] for r in rows] + [r.get("created_by") for r in rows])
    lts = {x["_id"]: x["name"] for x in await db.leave_types.find({}, {"name": 1}).to_list(length=None)}
    return [{"id": str(r["_id"]), "employee": users.get(r["employee_id"], {}).get("name"),
             "employee_code": users.get(r["employee_id"], {}).get("employee_id"), "leave_type": lts.get(r["leave_type_id"]),
             "year": r["year"], "kind": r["kind"], "days": r["days"], "reason": r["reason"],
             "created_by": users.get(r.get("created_by"), {}).get("name"), "created_at": r["created_at"]} for r in rows]


async def filtered_employees(db, employee_type_id=None, department_id=None, search=None, employee_id=None) -> list[dict]:
    query: dict = ls.employee_filter()
    if employee_type_id:
        query["employee_type_id"] = ls.to_oid(employee_type_id, "employee type id")
    if department_id:
        query["department_id"] = ls.to_oid(department_id, "department id")
    if employee_id:
        query["_id"] = ls.to_oid(employee_id, "employee id")
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        query = {"$and": [query, {"$or": [{"name": pattern}, {"employee_id": pattern}]}]}
    return await db.users.find(query).sort("name", 1).to_list(length=None)


@router.get("/balances")
async def balances(year: int | None = None, employee_type_id: str | None = None, department_id: str | None = None,
                   search: str | None = None, employee_id: str | None = None,
                   user=Depends(approve), db=Depends(get_database)):
    employees = await filtered_employees(db, employee_type_id, department_id, search, employee_id)
    ctx = await ls.LeaveContext.load(db, year, [e["_id"] for e in employees])
    departments, types = await ls.employee_lookup(db)
    out = []
    for emp in employees:
        elig = ctx.eligibility(emp, min(max(ls.today(), ctx.year_start), ctx.year_end))
        out.append({"employee": ls.employee_brief(emp, departments, types),
                    "balances": [ctx.card(emp, k, e) for k, e in elig.items() if e["eligible"]]})
    return {"year": ctx.year, "items": out}


@router.post("/carry-forward")
async def carry_forward(data: CarryForwardIn, dry_run: bool = True, user=Depends(manage), db=Depends(get_database)):
    """Carry unused balance from `from_year` into the next leave year, capped by each policy's limit
    (a limit of 0 means no cap). Safe to run more than once: each employee/type/year posts once."""
    employees = await filtered_employees(db)
    ctx = await ls.LeaveContext.load(db, data.from_year, [e["_id"] for e in employees])
    only = set(ls.oid_list(data.leave_type_ids, "leave type id"))
    rows = []
    for emp in employees:
        elig = ctx.eligibility(emp, ctx.year_end)
        for lt_id, lt in ctx.leave_types.items():
            if (only and lt_id not in only) or lt.get("is_lwp") or not elig[lt_id]["eligible"]:
                continue
            rules = ctx.rules(lt_id, emp.get("employee_type_id"))
            if not rules["carry_forward"]:
                continue
            bal = ctx.balance(emp, lt_id, rules)
            available = max(0.0, bal["available"] or 0)
            cap = float(rules["max_carry_forward"] or 0)
            days = ls.half_round(min(available, cap) if cap else available)
            if days <= 0:
                continue
            rows.append({"employee_id": emp["_id"], "employee": emp.get("name"), "employee_code": emp.get("employee_id"),
                         "leave_type_id": lt_id, "leave_type": lt["name"], "available": available, "carry_forward": days,
                         "expiry_months": rules["carry_forward_expiry_months"]})
    posted = 0
    if not dry_run:
        for r in rows:
            posted += await ls.post_transaction(
                db, employee_id=r["employee_id"], leave_type_id=r["leave_type_id"], year=data.from_year + 1, kind="carry_forward",
                days=r["carry_forward"], key=f"carry_forward:{r['employee_id']}:{r['leave_type_id']}:{data.from_year}",
                actor=user, note=f"Carried forward from {data.from_year}")
        await ls.audit(db, user, "balance.carry_forward", "leave_balance", None, {"from_year": data.from_year, "posted": posted})
    return {"from_year": data.from_year, "to_year": data.from_year + 1, "dry_run": dry_run, "posted": posted,
            "rows": [{**r, "employee_id": str(r["employee_id"]), "leave_type_id": str(r["leave_type_id"])} for r in rows]}


@router.post("/carry-forward/lapse")
async def lapse_carry_forward(year: int, dry_run: bool = True, user=Depends(manage), db=Depends(get_database)):
    """Expire carried-forward days that were not used within the policy's expiry window.
    Carried-forward days are treated as consumed first."""
    employees = await filtered_employees(db)
    ctx = await ls.LeaveContext.load(db, year, [e["_id"] for e in employees])
    rows = []
    for emp in employees:
        for lt_id, lt in ctx.leave_types.items():
            ledger = ctx.balances.get((emp["_id"], lt_id))
            if not ledger or float(ledger.get("carry_forward", 0)) <= 0:
                continue
            rules = ctx.rules(lt_id, emp.get("employee_type_id"))
            months = int(rules["carry_forward_expiry_months"] or 0)
            if not months:
                continue
            expiry_month = ctx.year_start.month - 1 + months
            expiry = date(ctx.year_start.year + expiry_month // 12, expiry_month % 12 + 1, 1) - timedelta(days=1)
            if ls.today() <= expiry:
                continue
            unused = float(ledger["carry_forward"]) - float(ledger.get("booked", 0))
            if unused > 0:
                rows.append({"employee_id": emp["_id"], "employee": emp.get("name"), "leave_type_id": lt_id,
                             "leave_type": lt["name"], "lapse": ls.half_round(unused), "expired_on": expiry.isoformat()})
    posted = 0
    if not dry_run:
        for r in rows:
            posted += await ls.post_transaction(
                db, employee_id=r["employee_id"], leave_type_id=r["leave_type_id"], year=year, kind="lapse", days=-r["lapse"],
                key=f"lapse:{r['employee_id']}:{r['leave_type_id']}:{year}", actor=user, note=f"Carry forward expired {r['expired_on']}")
        await ls.audit(db, user, "balance.lapse", "leave_balance", None, {"year": year, "posted": posted})
    return {"year": year, "dry_run": dry_run, "posted": posted,
            "rows": [{**r, "employee_id": str(r["employee_id"]), "leave_type_id": str(r["leave_type_id"])} for r in rows]}


@router.get("/transactions")
async def transactions(employee_id: str, year: int | None = None, user=Depends(approve), db=Depends(get_database)):
    query: dict = {"employee_id": ls.to_oid(employee_id, "employee id")}
    if year:
        query["year"] = year
    rows = await db.leave_transactions.find(query).sort("created_at", -1).limit(500).to_list(length=500)
    lts = {x["_id"]: x["name"] for x in await db.leave_types.find({}, {"name": 1}).to_list(length=None)}
    names = await actor_names(db, [r.get("created_by") for r in rows])
    return [{"id": str(r["_id"]), "leave_type": lts.get(r["leave_type_id"]), "year": r["year"], "kind": r["kind"],
             "days": r["days"], "note": r.get("note"), "created_by": names.get(r.get("created_by")), "created_at": r["created_at"]}
            for r in rows]


# ---------------------------------------------------------------------------
# Approvals (Admin and Super Admin only; no manager stage)
# ---------------------------------------------------------------------------

async def admin_request_query(db, status, search, employee_type_id, department_id, leave_type_id, from_date, to_date, year=None) -> dict:
    query: dict = {}
    apply_request_filters(query, status, leave_type_id, from_date, to_date)
    if year:
        query["year"] = year
    if employee_type_id:
        query["employee_type_id"] = ls.to_oid(employee_type_id, "employee type id")
    if department_id:
        query["department_id"] = ls.to_oid(department_id, "department id")
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        ids = [u["_id"] for u in await db.users.find({"$or": [{"name": pattern}, {"employee_id": pattern}]}, {"_id": 1}).to_list(length=None)]
        query["$or"] = [{"employee_id": {"$in": ids}}, {"request_no": pattern}]
    return query


@router.get("/requests")
async def all_requests(
    status: str | None = None, search: str | None = None, employee_type_id: str | None = None,
    department_id: str | None = None, leave_type_id: str | None = None,
    from_date: date | None = None, to_date: date | None = None,
    sort_by: str = "applied_at", sort_dir: int = Query(-1, ge=-1, le=1),
    paging=Depends(page_params), user=Depends(approve), db=Depends(get_database),
):
    if sort_by not in SORT_FIELDS:
        raise HTTPException(400, "Invalid sort field")
    query = await admin_request_query(db, status, search, employee_type_id, department_id, leave_type_id, from_date, to_date)
    result = await paginate(db, query, sort_by, sort_dir or -1, *paging)
    stats_query = await admin_request_query(db, None, search, employee_type_id, department_id, leave_type_id, from_date, to_date)
    counts = {r["_id"]: r["n"] async for r in db.leave_requests.aggregate([{"$match": stats_query}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    result["stats"] = {"total": sum(counts.values()), "pending": counts.get("pending", 0), "approved": counts.get("approved", 0),
                       "rejected": counts.get("rejected", 0), "cancelled": counts.get("cancelled", 0),
                       "cancellation_pending": counts.get("cancellation_pending", 0)}
    return result


def decision_fields(actor: dict, comment: str | None) -> dict:
    return {"decided_by": actor["_id"], "decided_by_role": actor.get("role"), "decided_at": now_utc(), "decision_comment": comment}


async def decision_result(db, req: dict, message: str) -> dict:
    return {"message": message, "request": (await ls.hydrate_requests(db, [req]))[0]}


@router.post("/requests/{request_id}/approve")
async def approve_request(request_id: str, data: DecisionIn, user=Depends(approve), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    lt = await db.leave_types.find_one({"_id": req["leave_type_id"]}) or {"name": "leave"}
    if req["status"] == "pending":
        await ls.recheck_balance(db, req)
        updated = await ls.transition(db, req, user, action="approved", to_status="approved", comment=data.comment,
                                      extra=decision_fields(user, data.comment))
        await ls.book(db, updated, user)
        await ls.notify(db, [req["employee_id"]], "Leave approved",
                        f"Your {lt['name']} request {req.get('request_no')} ({req['from_date']} to {req['to_date']}) was approved by {user.get('name')}.",
                        "/leave/requests")
        message = "Leave approved"
    elif req["status"] == "cancellation_pending":
        updated = await ls.transition(db, req, user, action="cancellation_approved", to_status="cancelled", comment=data.comment,
                                      extra=decision_fields(user, data.comment))
        await ls.unbook(db, updated, user, f"Cancellation approved {req.get('request_no')}")
        await ls.notify(db, [req["employee_id"]], "Leave cancellation approved",
                        f"Cancellation of {req.get('request_no')} was approved and {req['days']:g} day(s) restored.", "/leave/requests")
        message = "Cancellation approved and balance restored"
    else:
        raise HTTPException(409, f"This request is already {req['status'].replace('_', ' ')}")
    await ls.audit(db, user, "leave.approved" if updated["status"] == "approved" else "leave.cancellation_approved",
                   "leave_request", req["_id"], {"request_no": req.get("request_no"), "comment": data.comment})
    return await decision_result(db, await db.leave_requests.find_one({"_id": req["_id"]}), message)


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, data: RejectIn, user=Depends(approve), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    lt = await db.leave_types.find_one({"_id": req["leave_type_id"]}) or {"name": "leave"}
    comment = data.comment.strip()
    if req["status"] == "pending":
        updated = await ls.transition(db, req, user, action="rejected", to_status="rejected", comment=comment,
                                      extra=decision_fields(user, comment))
        await ls.notify(db, [req["employee_id"]], "Leave rejected",
                        f"Your {lt['name']} request {req.get('request_no')} was rejected by {user.get('name')}: {comment}", "/leave/requests")
        message = "Leave rejected"
    elif req["status"] == "cancellation_pending":
        updated = await ls.transition(db, req, user, action="cancellation_rejected", to_status="approved", comment=comment,
                                      extra=decision_fields(user, comment))
        await ls.notify(db, [req["employee_id"]], "Leave cancellation rejected",
                        f"Your request to cancel {req.get('request_no')} was rejected: {comment}. The leave remains approved.", "/leave/requests")
        message = "Cancellation rejected; leave remains approved"
    else:
        raise HTTPException(409, f"This request is already {req['status'].replace('_', ' ')}")
    await ls.audit(db, user, "leave.rejected" if req["status"] == "pending" else "leave.cancellation_rejected",
                   "leave_request", req["_id"], {"request_no": req.get("request_no"), "comment": comment})
    return await decision_result(db, updated, message)


@router.post("/requests/{request_id}/override")
async def override_request(request_id: str, data: OverrideIn, user=Depends(require_permission("leave.override")), db=Depends(get_database)):
    """Super Admin can change a final decision. The ledger is corrected to match the new status."""
    req = await ls.get_request(db, request_id)
    if req["status"] not in ("approved", "rejected", "cancelled"):
        raise HTTPException(409, "Only decided requests can be overridden; use approve/reject for pending ones")
    if req["status"] == data.status:
        raise HTTPException(400, f"The request is already {data.status}")
    updated = await ls.transition(db, req, user, action=f"override_{data.status}", to_status=data.status, comment=data.comment,
                                  extra=decision_fields(user, data.comment))
    if data.status == "approved":
        await ls.book(db, updated, user)
    else:
        await ls.unbook(db, updated, user, f"Override to {data.status} {req.get('request_no')}")
    await ls.notify(db, [req["employee_id"]], "Leave decision changed",
                    f"{user.get('name')} changed {req.get('request_no')} from {req['status']} to {data.status}: {data.comment}", "/leave/requests")
    await ls.audit(db, user, "leave.override", "leave_request", req["_id"],
                   {"request_no": req.get("request_no"), "from": req["status"], "to": data.status, "comment": data.comment})
    return await decision_result(db, await db.leave_requests.find_one({"_id": req["_id"]}), f"Decision overridden to {data.status}")


@router.get("/approvals")
async def approval_history(action: str | None = None, search: str | None = None,
                           from_date: date | None = None, to_date: date | None = None,
                           paging=Depends(page_params), user=Depends(approve), db=Depends(get_database)):
    page, page_size = paging
    query: dict = {}
    if action:
        query["action"] = action
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        ids = [u["_id"] for u in await db.users.find({"$or": [{"name": pattern}, {"employee_id": pattern}]}, {"_id": 1}).to_list(length=None)]
        query["$or"] = [{"employee_id": {"$in": ids}}, {"actor_id": {"$in": ids}}, {"request_no": pattern}]
    if from_date or to_date:
        query["created_at"] = {}
        if from_date:
            query["created_at"]["$gte"] = ls.utc_midnight(from_date)
        if to_date:
            query["created_at"]["$lt"] = ls.utc_midnight(to_date + timedelta(days=1))
    total = await db.leave_approvals.count_documents(query)
    rows = await db.leave_approvals.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
    users = await ls.users_by_id(db, [r["employee_id"] for r in rows])
    lts = {x["_id"]: x["name"] for x in await db.leave_types.find({}, {"name": 1}).to_list(length=None)}
    items = [{"id": str(r["_id"]), "request_id": str(r["request_id"]), "request_no": r.get("request_no"),
              "employee": users.get(r["employee_id"], {}).get("name"), "employee_code": users.get(r["employee_id"], {}).get("employee_id"),
              "leave_type": lts.get(r.get("leave_type_id")), "action": r["action"], "from_status": r.get("from_status"),
              "to_status": r.get("to_status"), "actor": r.get("actor_name"), "actor_role": r.get("actor_role"),
              "comment": r.get("comment"), "created_at": r["created_at"]} for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/audit")
async def audit_log(paging=Depends(page_params), user=Depends(manage), db=Depends(get_database)):
    page, page_size = paging
    query = {"module": "leave"}
    total = await db.audit_logs.count_documents(query)
    rows = await db.audit_logs.find(query).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
    return {"items": [{"id": str(r["_id"]), "action": r["action"], "entity": r.get("entity"), "entity_id": r.get("entity_id"),
                       "actor": r.get("actor_name"), "actor_role": r.get("actor_role"), "details": r.get("details"),
                       "created_at": r["created_at"]} for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/dashboard")
async def dashboard(year: int | None = None, user=Depends(approve), db=Depends(get_database)):
    settings = await ls.get_settings(db)
    year = year or ls.leave_year_of(ls.today(), settings)
    counts = {r["_id"]: r["n"] async for r in db.leave_requests.aggregate([{"$match": {"year": year}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    key = ls.today().isoformat()
    on_leave_today = await db.leave_requests.count_documents({"status": {"$in": ["approved", "cancellation_pending"]}, "from_date": {"$lte": key}, "to_date": {"$gte": key}})
    lts = {x["_id"]: x for x in await db.leave_types.find({}).to_list(length=None)}
    by_type = [{"leave_type": lts.get(r["_id"], {}).get("name", "Unknown"), "color": lts.get(r["_id"], {}).get("color", "#3b82f6"), "days": r["days"], "requests": r["n"]}
               async for r in db.leave_requests.aggregate([
                   {"$match": {"year": year, "status": {"$in": ["approved", "cancellation_pending"]}}},
                   {"$group": {"_id": "$leave_type_id", "days": {"$sum": "$days"}, "n": {"$sum": 1}}}, {"$sort": {"days": -1}}])]
    by_month: dict = defaultdict(float)
    async for r in db.leave_requests.aggregate([{"$match": {"year": year, "status": {"$in": ["approved", "cancellation_pending"]}}},
                                                {"$group": {"_id": {"$substr": ["$from_date", 0, 7]}, "days": {"$sum": "$days"}}}]):
        by_month[r["_id"]] += r["days"]
    pending = await db.leave_requests.find({"status": {"$in": ["pending", "cancellation_pending"]}}).sort("applied_at", 1).limit(8).to_list(length=8)
    unmapped = await db.users.count_documents({**ls.employee_filter(), "employee_type_id": None})
    return {"year": year, "stats": {"total": sum(counts.values()), "pending": counts.get("pending", 0), "approved": counts.get("approved", 0),
                                    "rejected": counts.get("rejected", 0), "cancelled": counts.get("cancelled", 0),
                                    "cancellation_pending": counts.get("cancellation_pending", 0), "on_leave_today": on_leave_today,
                                    "employees_without_type": unmapped},
            "by_leave_type": by_type, "by_month": [{"month": k, "days": v} for k, v in sorted(by_month.items())],
            "pending": await ls.hydrate_requests(db, pending)}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

REPORTS = {
    "employee-summary": "Employee-wise Leave Summary",
    "employee-type-summary": "Employee-type-wise Leave Summary",
    "department-summary": "Department-wise Leave Summary",
    "leave-type-utilization": "Leave-type-wise Utilization",
    "monthly": "Monthly Leave Report",
    "annual": "Annual Leave Report",
    "lwp": "Leave Without Pay Report",
    "pending": "Pending Applications",
    "allocation": "Leave Allocation Report",
    "balance": "Leave Balance Report",
}


def cols(*pairs) -> list[dict]:
    return [{"key": k, "label": label} for k, label in pairs]


@router.get("/reports")
async def report_catalog(user=Depends(require_permission("leave.reports"))):
    return [{"kind": k, "title": v} for k, v in REPORTS.items()]


@router.get("/reports/{kind}")
async def report(kind: str, year: int | None = None, month: int | None = Query(None, ge=1, le=12),
                 employee_type_id: str | None = None, department_id: str | None = None, leave_type_id: str | None = None,
                 user=Depends(require_permission("leave.reports")), db=Depends(get_database)):
    if kind not in REPORTS:
        raise HTTPException(404, "Unknown report")
    settings = await ls.get_settings(db)
    year = year or ls.leave_year_of(ls.today(), settings)
    employees = await filtered_employees(db, employee_type_id, department_id)
    emp_ids = [e["_id"] for e in employees]
    departments, types = await ls.employee_lookup(db)
    lt_filter = ls.to_oid(leave_type_id, "leave type id") if leave_type_id else None
    briefs = {e["_id"]: ls.employee_brief(e, departments, types) for e in employees}
    req_q: dict = {"year": year, "employee_id": {"$in": emp_ids}}
    if lt_filter:
        req_q["leave_type_id"] = lt_filter
    title = f"{REPORTS[kind]} - {year}"

    if kind in ("employee-summary", "employee-type-summary", "department-summary", "leave-type-utilization", "allocation", "balance"):
        ctx = await ls.LeaveContext.load(db, year, emp_ids, settings)
        cards = []
        for emp in employees:
            elig = ctx.eligibility(emp, min(max(ls.today(), ctx.year_start), ctx.year_end))
            for lt_id, e in elig.items():
                if (lt_filter and lt_id != lt_filter) or not e["eligible"]:
                    continue
                cards.append((emp, ctx.card(emp, lt_id, e)))

        if kind in ("allocation", "balance"):
            rows = []
            for emp, c in cards:
                b = briefs[emp["_id"]]
                base = {"employee_id": b["employee_id"], "name": b["name"], "employee_type": b["employee_type"], "department": b["department"], "leave_type": c["name"]}
                if kind == "allocation":
                    rows.append({**base, "entitlement": "LWP" if c["is_lwp"] else c["entitlement"], "source": (c["allocation_source"] or "-").replace("_", " "),
                                 "accrued": c["accrued"], "opening": c["opening"], "carry_forward": c["carry_forward"], "adjusted": c["adjusted"]})
                else:
                    rows.append({**base, "available": "-" if c["is_lwp"] else c["available"], "booked": c["booked"], "pending": c["pending"]})
            columns = cols(("employee_id", "Emp ID"), ("name", "Employee"), ("employee_type", "Employee Type"), ("department", "Department"), ("leave_type", "Leave Type"))
            columns += cols(("entitlement", "Annual Entitlement"), ("source", "Source"), ("accrued", "Accrued"), ("opening", "Opening"),
                            ("carry_forward", "Carry Forward"), ("adjusted", "Adjusted")) if kind == "allocation" else \
                cols(("available", "Available"), ("booked", "Booked"), ("pending", "Pending"))
            return {"title": title, "columns": columns, "rows": rows}

        groups: dict = defaultdict(lambda: {"employees": set(), "entitled": 0.0, "booked": 0.0, "pending": 0.0, "available": 0.0, "lwp": 0.0})
        for emp, c in cards:
            b = briefs[emp["_id"]]
            key = {"employee-summary": (b["employee_id"], b["name"], b["employee_type"], b["department"]),
                   "employee-type-summary": (b["employee_type"] or "Unassigned",),
                   "department-summary": (b["department"] or "Unassigned",),
                   "leave-type-utilization": (c["name"],)}[kind]
            g = groups[key]
            g["employees"].add(emp["_id"])
            g["booked"] += c["booked"]
            g["pending"] += c["pending"]
            if c["is_lwp"]:
                g["lwp"] += c["booked"]
            else:
                g["entitled"] += c["accrued"] + c["opening"] + c["carry_forward"] + c["adjusted"]
                g["available"] += c["available"]
        rows = []
        for key, g in sorted(groups.items()):
            metrics = {"entitled": g["entitled"], "booked": g["booked"], "pending": g["pending"], "available": round(g["available"], 2), "lwp": g["lwp"]}
            if kind == "employee-summary":
                rows.append({"employee_id": key[0], "name": key[1], "employee_type": key[2], "department": key[3], **metrics})
            else:
                util = round(100 * (g["booked"] - g["lwp"]) / g["entitled"], 1) if g["entitled"] else 0
                rows.append({"group": key[0], "employees": len(g["employees"]), **metrics, "utilization": util})
        metric_cols = cols(("entitled", "Credited"), ("booked", "Booked"), ("pending", "Pending"), ("available", "Available"), ("lwp", "LWP Days"))
        if kind == "employee-summary":
            columns = cols(("employee_id", "Emp ID"), ("name", "Employee"), ("employee_type", "Employee Type"), ("department", "Department")) + metric_cols
        else:
            label = {"employee-type-summary": "Employee Type", "department-summary": "Department", "leave-type-utilization": "Leave Type"}[kind]
            columns = cols(("group", label), ("employees", "Employees")) + metric_cols + cols(("utilization", "Utilization %"))
        return {"title": title, "columns": columns, "rows": rows}

    # request-based reports
    if kind == "pending":
        req_q = {"status": {"$in": ["pending", "cancellation_pending"]}, "employee_id": {"$in": emp_ids}}
        if lt_filter:
            req_q["leave_type_id"] = lt_filter
        title = REPORTS[kind]
    elif kind == "lwp":
        lwp_ids = [x["_id"] for x in await db.leave_types.find({"is_lwp": True}, {"_id": 1}).to_list(length=None)]
        req_q.update({"status": {"$in": ["approved", "cancellation_pending"]}, "leave_type_id": {"$in": lwp_ids}})
    else:
        req_q["status"] = {"$in": ["approved", "cancellation_pending"]}
        if kind == "monthly":
            month = month or ls.today().month
            first = date(year, month, 1)
            last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
            req_q.pop("year")
            req_q.update({"from_date": {"$lte": last.isoformat()}, "to_date": {"$gte": first.isoformat()}})
            title = f"{REPORTS[kind]} - {first.strftime('%B %Y')}"
    rows_raw = await db.leave_requests.find(req_q).sort([("from_date", 1)]).to_list(length=None)
    views = await ls.hydrate_requests(db, rows_raw)
    rows = [{"request_no": v["request_no"], "employee_id": v["employee"]["employee_id"], "name": v["employee"]["name"],
             "employee_type": v["employee"]["employee_type"], "department": v["employee"]["department"],
             "leave_type": v["leave_type"]["name"], "from_date": v["from_date"], "to_date": v["to_date"], "days": v["days"],
             "status": v["status"].replace("_", " "), "applied_at": v["applied_at"].strftime("%Y-%m-%d") if v["applied_at"] else "",
             "decided_by": v["decided_by"] or ""} for v in views]
    if kind == "monthly":
        # Count only the working days that fall inside the month for multi-month requests.
        for v, row in zip(views, rows):
            in_month = [d for d in (set(ls.date_range(ls.parse_day(v["from_date"]), ls.parse_day(v["to_date"]))))
                        if d.month == month and d.year == year]
            excluded = {e["date"] for e in v["excluded_dates"]}
            counted = [d for d in in_month if d.isoformat() not in excluded]
            row["days"] = 0.5 if v["half_day"] and counted else len(counted)
    columns = cols(("request_no", "Request"), ("employee_id", "Emp ID"), ("name", "Employee"), ("employee_type", "Employee Type"),
                   ("department", "Department"), ("leave_type", "Leave Type"), ("from_date", "From"), ("to_date", "To"),
                   ("days", "Days"), ("status", "Status"), ("applied_at", "Applied"), ("decided_by", "Decided By"))
    return {"title": title, "columns": columns, "rows": rows}
