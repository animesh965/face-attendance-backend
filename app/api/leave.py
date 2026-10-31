"""Leave tracker APIs for employees and managers (My Data, Team, Holidays, Calendar, Notifications).

Managers are regular employees with reportees: they can view team leave data but every
approve/reject endpoint lives in leave_admin.py behind admin-only permissions."""
import re
import uuid
from datetime import date, timedelta
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.config import settings as app_settings
from app.core.database import get_database
from app.core.time import now_utc
from app.dependencies.permissions import require_permission
from app.schemas.leave import CommentIn, DecisionIn, LeaveApplyIn, SavedViewIn
from app.services import leave_service as ls

router = APIRouter(prefix="/api/v1/leave", tags=["Leave Tracker"])

ALLOWED_DOC_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}
SORT_FIELDS = {"applied_at", "from_date", "to_date", "days", "status"}


def page_params(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)):
    return page, page_size


async def paginate(db, query: dict, sort_by: str, sort_dir: int, page: int, page_size: int) -> dict:
    total = await db.leave_requests.count_documents(query)
    rows = await (db.leave_requests.find(query).sort([(sort_by, sort_dir), ("_id", -1)])
                  .skip((page - 1) * page_size).limit(page_size).to_list(length=page_size))
    return {"items": await ls.hydrate_requests(db, rows), "total": total, "page": page, "page_size": page_size}


def apply_request_filters(query: dict, status: str | None, leave_type_id: str | None,
                          from_date: date | None, to_date: date | None):
    if status:
        statuses = [s for s in status.split(",") if s]
        query["status"] = {"$in": statuses}
    if leave_type_id:
        query["leave_type_id"] = ls.to_oid(leave_type_id, "leave type")
    if from_date:
        query["to_date"] = {"$gte": from_date.isoformat()}
    if to_date:
        query["from_date"] = {"$lte": to_date.isoformat()}


async def save_document(file: UploadFile | None) -> dict | None:
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_DOC_EXT:
        raise HTTPException(400, "Supporting document must be a PDF, image (JPG/PNG) or Word file")
    content = await file.read()
    if len(content) > app_settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"Supporting document must be under {app_settings.MAX_UPLOAD_MB} MB")
    if not content:
        raise HTTPException(400, "Supporting document is empty")
    folder = Path(app_settings.UPLOAD_DIR) / "leave_documents"
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (folder / stored).write_bytes(content)
    safe_name = re.sub(r"[^\w.\- ]", "_", Path(file.filename).name)[:120]
    return {"filename": safe_name, "stored_name": stored, "content_type": file.content_type, "size": len(content)}


def form_to_apply(leave_type_id: str, from_date: str, to_date: str, half_day: bool,
                  half_day_session: str | None, team_email: str | None, reason: str | None) -> LeaveApplyIn:
    try:
        return LeaveApplyIn(leave_type_id=leave_type_id, from_date=from_date, to_date=to_date, half_day=half_day,
                            half_day_session=half_day_session or None, team_email=team_email, reason=reason)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()))


async def absent_days(db, user: dict, ctx: ls.LeaveContext) -> int:
    """Past working days this leave year with no attendance record and no approved leave."""
    start = ctx.year_start
    joined = ls.parse_day(user.get("date_of_joining")) or (user.get("created_at") and user["created_at"].date())
    if joined and joined > start:
        start = joined
    end = min(ctx.year_end, ls.today() - timedelta(days=1))
    if end < start:
        return 0
    present = {row["date"] for row in await db.attendance.find(
        {"user_id": {"$in": [user["_id"], str(user["_id"])]}, "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}},
        {"date": 1}).to_list(length=None)}
    on_leave = set()
    for req in await db.leave_requests.find({"employee_id": user["_id"], "status": {"$in": ["approved", "cancellation_pending"]},
                                             "from_date": {"$lte": end.isoformat()}, "to_date": {"$gte": start.isoformat()}}).to_list(length=None):
        on_leave.update(d.isoformat() for d in ls.date_range(ls.parse_day(req["from_date"]), ls.parse_day(req["to_date"])))
    weekly_offs = set(ctx.settings.get("weekly_offs", []))
    count = 0
    for day in ls.date_range(start, end):
        key = day.isoformat()
        if day.weekday() in weekly_offs or key in present or key in on_leave or ctx.holiday_on(user, day):
            continue
        count += 1
    return count


def holiday_view(row: dict) -> dict:
    return {"id": str(row["_id"]), "name": row["name"], "from_date": ls.iso(row["_from"]), "to_date": ls.iso(row["_to"]),
            "description": row.get("description"), "holiday_type": row.get("holiday_type", "public"),
            "days": (row["_to"] - row["_from"]).days + 1}


# ---------------------------------------------------------------------------
# My Data
# ---------------------------------------------------------------------------

@router.get("/settings")
async def leave_settings(user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    settings = await ls.get_settings(db)
    year = ls.leave_year_of(ls.today(), settings)
    start, end = ls.leave_year_bounds(year, settings)
    return {**settings, "current_year": year, "current_year_start": start.isoformat(), "current_year_end": end.isoformat()}


@router.get("/me/profile")
async def my_profile(user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    departments, types = await ls.employee_lookup(db)
    policies, standard = await ls.load_shift_context(db)
    manager = await db.users.find_one({"_id": user.get("reporting_manager_id")}, {"name": 1, "employee_id": 1}) if user.get("reporting_manager_id") else None
    return {**ls.employee_brief(user, departments, types), "shift": ls.shift_for(user, policies, standard),
            "reporting_manager": {"id": str(manager["_id"]), "name": manager.get("name"), "employee_id": manager.get("employee_id")} if manager else None,
            "is_manager": bool(await db.users.count_documents({"reporting_manager_id": user["_id"], "is_active": {"$ne": False}}, limit=1))}


@router.get("/me/eligible-types")
async def my_eligible_types(on_date: date | None = None, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    settings = await ls.get_settings(db)
    on_date = on_date or ls.today()
    ctx = await ls.LeaveContext.load(db, ls.leave_year_of(on_date, settings), [user["_id"]], settings)
    elig = ctx.eligibility(user, on_date)
    return [ctx.card(user, lt_id, e) for lt_id, e in elig.items() if e["eligible"]]


@router.get("/me/summary")
async def my_summary(year: int | None = Query(None, ge=2000, le=2100), user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    ctx = await ls.LeaveContext.load(db, year, [user["_id"]])
    now = ls.today()
    elig = ctx.eligibility(user, min(max(now, ctx.year_start), ctx.year_end))
    cards = []
    for lt_id, e in elig.items():
        card = ctx.card(user, lt_id, e)
        # Keep a no-longer-eligible type visible if it already has bookings this year.
        if e["eligible"] or card["booked"] or card["pending"]:
            cards.append(card)
    reqs = await db.leave_requests.find({"employee_id": user["_id"], "year": ctx.year}).sort("from_date", 1).to_list(length=None)
    views = await ls.hydrate_requests(db, reqs)
    holidays = [holiday_view(h) for h in sorted(ctx.holidays, key=lambda h: h["_from"]) if ls.holiday_applies(h, user)]
    today_iso = now.isoformat()
    upcoming_leaves = [v for v in views if v["to_date"] >= today_iso and v["status"] in ls.ACTIVE_STATUSES]
    past_leaves = [v for v in views if v["to_date"] < today_iso or v["status"] in ("rejected", "cancelled")]
    return {
        "year": ctx.year, "period": {"start": ctx.year_start.isoformat(), "end": ctx.year_end.isoformat()},
        "weekly_offs": ctx.settings["weekly_offs"],
        "booked_total": sum(c["booked"] for c in cards),
        "pending_total": sum(c["pending"] for c in cards),
        "absent_days": await absent_days(db, user, ctx),
        "cards": cards,
        "upcoming": {"leaves": upcoming_leaves, "holidays": [h for h in holidays if h["to_date"] >= today_iso]},
        "past": {"leaves": list(reversed(past_leaves)), "holidays": list(reversed([h for h in holidays if h["to_date"] < today_iso]))},
    }


@router.post("/me/preview")
async def preview_leave(data: LeaveApplyIn, request_id: str | None = None,
                        user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    """Validate an application without saving it, so the form can show the exact duration and balance.
    Pass request_id when editing so the request does not overlap with itself."""
    exclude = ls.to_oid(request_id, "request id") if request_id else None
    result = await ls.validate_application(db, user, data, has_attachment=True, exclude_request_id=exclude)
    lt = result["leave_type"]
    return {"days": result["days"], "counted_dates": result["calc"]["counted_dates"],
            "excluded_dates": result["calc"]["excluded_dates"], "balance": result["balance"],
            "requires_document": bool(lt.get("requires_document") and result["days"] > float(lt.get("document_required_after_days") or 0))}


@router.post("/requests", status_code=201)
async def apply_leave(
    leave_type_id: str = Form(...), from_date: str = Form(...), to_date: str = Form(...),
    half_day: bool = Form(False), half_day_session: str | None = Form(None),
    team_email: str | None = Form(None), reason: str | None = Form(None),
    document: UploadFile | None = File(None),
    user=Depends(require_permission("leave.self")), db=Depends(get_database),
):
    data = form_to_apply(leave_type_id, from_date, to_date, half_day, half_day_session, team_email, reason)
    await ls.acquire_lock(db, user["_id"])
    try:
        result = await ls.validate_application(db, user, data, has_attachment=bool(document and document.filename))
        attachment = await save_document(document)
        now = now_utc()
        doc = {
            "request_no": await ls.next_request_no(db),
            "employee_id": user["_id"], "leave_type_id": result["leave_type"]["_id"], "year": result["year"],
            "from_date": data.from_date.isoformat(), "to_date": data.to_date.isoformat(),
            "half_day": data.half_day, "half_day_session": data.half_day_session,
            "days": result["days"], "excluded_dates": result["calc"]["excluded_dates"],
            "team_email": data.team_email, "reason": data.reason, "attachment": attachment,
            "status": "pending", "version": 0, "booked_days": 0,
            "employee_type_id": user.get("employee_type_id"), "department_id": user.get("department_id"),
            "applied_at": now, "updated_at": now, "comments": [],
            "history": [ls.history_entry("applied", user, None, "pending", data.reason)],
        }
        res = await db.leave_requests.insert_one(doc)
        doc["_id"] = res.inserted_id
    finally:
        await ls.release_lock(db, user["_id"])
    await ls.notify(db, await ls.admin_ids(db), "New leave request",
                    f"{user.get('name')} applied for {result['days']:g} day(s) of {result['leave_type']['name']} "
                    f"({doc['from_date']} to {doc['to_date']}).", "/leave/admin/approvals")
    await ls.audit(db, user, "leave.applied", "leave_request", doc["_id"], {"request_no": doc["request_no"], "days": doc["days"]})
    return (await ls.hydrate_requests(db, [doc]))[0]


@router.put("/requests/{request_id}")
async def edit_leave(
    request_id: str,
    leave_type_id: str = Form(...), from_date: str = Form(...), to_date: str = Form(...),
    half_day: bool = Form(False), half_day_session: str | None = Form(None),
    team_email: str | None = Form(None), reason: str | None = Form(None),
    remove_document: bool = Form(False), document: UploadFile | None = File(None),
    user=Depends(require_permission("leave.self")), db=Depends(get_database),
):
    req = await ls.get_request(db, request_id)
    if req["employee_id"] != user["_id"]:
        raise HTTPException(403, "You can only edit your own leave requests")
    if req["status"] != "pending":
        raise HTTPException(409, "Only pending requests can be edited")
    data = form_to_apply(leave_type_id, from_date, to_date, half_day, half_day_session, team_email, reason)
    keep_existing = req.get("attachment") and not remove_document
    await ls.acquire_lock(db, user["_id"])
    try:
        result = await ls.validate_application(db, user, data, exclude_request_id=req["_id"],
                                               has_attachment=bool((document and document.filename) or keep_existing))
        attachment = await save_document(document) or (req.get("attachment") if keep_existing else None)
        updated = await db.leave_requests.find_one_and_update(
            {"_id": req["_id"], "status": "pending", "version": req.get("version", 0)},
            {"$set": {"leave_type_id": result["leave_type"]["_id"], "year": result["year"],
                      "from_date": data.from_date.isoformat(), "to_date": data.to_date.isoformat(),
                      "half_day": data.half_day, "half_day_session": data.half_day_session, "days": result["days"],
                      "excluded_dates": result["calc"]["excluded_dates"], "team_email": data.team_email,
                      "reason": data.reason, "attachment": attachment, "updated_at": now_utc()},
             "$inc": {"version": 1},
             "$push": {"history": ls.history_entry("edited", user, "pending", "pending")}},
            return_document=True)
    finally:
        await ls.release_lock(db, user["_id"])
    if not updated:
        raise HTTPException(409, "This request was decided while you were editing it. Refresh to see its status.")
    return (await ls.hydrate_requests(db, [updated]))[0]


@router.get("/me/requests")
async def my_requests(
    status: str | None = None, leave_type_id: str | None = None,
    from_date: date | None = None, to_date: date | None = None, search: str | None = None,
    sort_by: str = "applied_at", sort_dir: int = Query(-1, ge=-1, le=1),
    paging=Depends(page_params), user=Depends(require_permission("leave.self")), db=Depends(get_database),
):
    query: dict = {"employee_id": user["_id"]}
    apply_request_filters(query, status, leave_type_id, from_date, to_date)
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        lt_ids = [x["_id"] for x in await db.leave_types.find({"name": pattern}, {"_id": 1}).to_list(length=None)]
        query["$or"] = [{"request_no": pattern}, {"reason": pattern}, {"leave_type_id": {"$in": lt_ids}}]
    if sort_by not in SORT_FIELDS:
        raise HTTPException(400, "Invalid sort field")
    return await paginate(db, query, sort_by, sort_dir or -1, *paging)


@router.get("/requests/{request_id}")
async def request_detail(request_id: str, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    if not await ls.can_view_employee(db, user, req["employee_id"]):
        raise HTTPException(403, "You cannot view this leave request")
    view = (await ls.hydrate_requests(db, [req]))[0]
    if not ls.is_admin(user) and req["employee_id"] != user["_id"]:
        # Managers see team leave but not attachments or private comments.
        view["attachment"] = None
        view["comments"] = []
    return view


@router.post("/requests/{request_id}/cancel")
async def cancel_leave(request_id: str, data: DecisionIn, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    if req["employee_id"] != user["_id"]:
        raise HTTPException(403, "You can only cancel your own leave requests")
    if req["status"] == "pending":
        updated = await ls.transition(db, req, user, action="cancelled", to_status="cancelled", comment=data.comment)
        message = "Leave request cancelled"
    elif req["status"] == "approved":
        if ls.parse_day(req["from_date"]) <= ls.today():
            raise HTTPException(409, "Leave that has already started can only be cancelled by an administrator")
        updated = await ls.transition(db, req, user, action="cancellation_requested", to_status="cancellation_pending", comment=data.comment)
        await ls.notify(db, await ls.admin_ids(db), "Leave cancellation requested",
                        f"{user.get('name')} asked to cancel approved leave {req.get('request_no')} ({req['from_date']} to {req['to_date']}).",
                        "/leave/admin/approvals")
        message = "Cancellation requested. An administrator must approve it before the balance is restored."
    else:
        raise HTTPException(409, f"A {req['status'].replace('_', ' ')} request cannot be cancelled")
    await ls.audit(db, user, "leave.cancel", "leave_request", req["_id"], {"to": updated["status"]})
    return {"message": message, "request": (await ls.hydrate_requests(db, [updated]))[0]}


@router.post("/requests/{request_id}/comments")
async def add_comment(request_id: str, data: CommentIn, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    if req["employee_id"] != user["_id"] and not ls.is_admin(user):
        raise HTTPException(403, "Only the employee and administrators can comment on this request")
    comment = {"id": uuid.uuid4().hex, "by": user["_id"], "by_name": user.get("name"), "role": user.get("role"),
               "comment": data.comment.strip(), "at": now_utc()}
    await db.leave_requests.update_one({"_id": req["_id"]}, {"$push": {"comments": comment}})
    target = await ls.admin_ids(db) if req["employee_id"] == user["_id"] else [req["employee_id"]]
    await ls.notify(db, [t for t in target if t != user["_id"]], "New comment on leave request",
                    f"{user.get('name')} commented on {req.get('request_no')}: {comment['comment'][:120]}",
                    "/leave/requests" if req["employee_id"] != user["_id"] else "/leave/admin/approvals")
    return {**comment, "by": str(user["_id"])}


@router.get("/requests/{request_id}/attachment")
async def download_attachment(request_id: str, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    req = await ls.get_request(db, request_id)
    if req["employee_id"] != user["_id"] and not ls.is_admin(user):
        raise HTTPException(403, "You cannot download this document")
    attachment = req.get("attachment")
    if not attachment:
        raise HTTPException(404, "No document attached")
    root = (Path(app_settings.UPLOAD_DIR) / "leave_documents").resolve()
    target = (root / attachment["stored_name"]).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "Document not found")
    return FileResponse(target, filename=attachment["filename"], headers={"Cache-Control": "private, no-store"})


@router.get("/me/views")
async def my_views(user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    rows = await db.leave_saved_views.find({"user_id": user["_id"]}).sort("name", 1).to_list(length=100)
    return [{"id": str(r["_id"]), "name": r["name"], "filters": r.get("filters", {})} for r in rows]


@router.post("/me/views", status_code=201)
async def create_view(data: SavedViewIn, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    allowed = {"status", "leave_type_id", "from_date", "to_date", "search", "sort_by", "sort_dir"}
    filters = {k: v for k, v in data.filters.items() if k in allowed and isinstance(v, (str, int)) and len(str(v)) <= 100}
    res = await db.leave_saved_views.update_one(
        {"user_id": user["_id"], "name": data.name.strip()},
        {"$set": {"filters": filters, "updated_at": now_utc()}, "$setOnInsert": {"created_at": now_utc()}}, upsert=True)
    row = await db.leave_saved_views.find_one({"user_id": user["_id"], "name": data.name.strip()})
    return {"id": str(row["_id"]), "name": row["name"], "filters": row["filters"], "created": bool(res.upserted_id)}


@router.delete("/me/views/{view_id}")
async def delete_view(view_id: str, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    res = await db.leave_saved_views.delete_one({"_id": ls.to_oid(view_id), "user_id": user["_id"]})
    if not res.deleted_count:
        raise HTTPException(404, "View not found")
    return {"success": True}


# ---------------------------------------------------------------------------
# Holidays and calendar
# ---------------------------------------------------------------------------

@router.get("/holidays")
async def my_holidays(year: int | None = Query(None, ge=2000, le=2100), user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    settings = await ls.get_settings(db)
    year = year or ls.leave_year_of(ls.today(), settings)
    start, end = ls.leave_year_bounds(year, settings)
    rows = await ls.load_holidays(db, start, end)
    if not ls.is_admin(user):
        rows = [r for r in rows if ls.holiday_applies(r, user)]
    return {"year": year, "start": start.isoformat(), "end": end.isoformat(), "weekly_offs": settings["weekly_offs"],
            "holidays": [holiday_view(r) for r in sorted(rows, key=lambda r: r["_from"])]}


@router.get("/calendar")
async def leave_calendar(
    from_date: date, to_date: date,
    employee_id: str | None = None, department_id: str | None = None,
    employee_type_id: str | None = None, leave_type_id: str | None = None,
    user=Depends(require_permission("leave.self")), db=Depends(get_database),
):
    if to_date < from_date or (to_date - from_date).days > 400:
        raise HTTPException(400, "Choose a calendar range of up to 400 days")
    query: dict = {"from_date": {"$lte": to_date.isoformat()}, "to_date": {"$gte": from_date.isoformat()}}
    if ls.is_admin(user):
        query["status"] = {"$in": list(ls.ACTIVE_STATUSES)}
    else:
        team = await ls.team_member_ids(db, user["_id"], recursive=True)
        query["$or"] = [
            {"employee_id": user["_id"], "status": {"$in": list(ls.ACTIVE_STATUSES)}},
            {"employee_id": {"$in": team}, "status": {"$in": ["approved", "cancellation_pending"]}},
        ]
    if employee_id:
        query["employee_id"] = ls.to_oid(employee_id, "employee id")
    if department_id:
        query["department_id"] = ls.to_oid(department_id, "department id")
    if employee_type_id:
        query["employee_type_id"] = ls.to_oid(employee_type_id, "employee type id")
    if leave_type_id:
        query["leave_type_id"] = ls.to_oid(leave_type_id, "leave type id")
    rows = await db.leave_requests.find(query).sort("from_date", 1).to_list(length=5000)
    leaves = await ls.hydrate_requests(db, rows)
    holidays = await ls.load_holidays(db, from_date, to_date)
    if not ls.is_admin(user):
        holidays = [h for h in holidays if ls.holiday_applies(h, user)]
    settings = await ls.get_settings(db)
    return {"weekly_offs": settings["weekly_offs"], "leaves": leaves, "holidays": [holiday_view(h) for h in holidays]}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@router.get("/notifications")
async def my_notifications(unread_only: bool = False, limit: int = Query(20, ge=1, le=100),
                           user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    query: dict = {"user_id": user["_id"]}
    if unread_only:
        query["read"] = False
    rows = await db.notifications.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    unread = await db.notifications.count_documents({"user_id": user["_id"], "read": False})
    return {"unread": unread, "items": [{"id": str(r["_id"]), "title": r["title"], "message": r["message"], "link": r.get("link"),
                                         "read": r.get("read", False), "created_at": r["created_at"]} for r in rows]}


@router.post("/notifications/read-all")
async def read_all(user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    await db.notifications.update_many({"user_id": user["_id"], "read": False}, {"$set": {"read": True}})
    return {"success": True}


@router.post("/notifications/{notification_id}/read")
async def read_one(notification_id: str, user=Depends(require_permission("leave.self")), db=Depends(get_database)):
    await db.notifications.update_one({"_id": ls.to_oid(notification_id), "user_id": user["_id"]}, {"$set": {"read": True}})
    return {"success": True}


# ---------------------------------------------------------------------------
# Team (view only)
# ---------------------------------------------------------------------------

async def team_scope(db, user: dict, scope: str) -> list[ObjectId]:
    if ls.is_admin(user) and scope == "all":
        rows = await db.users.find(ls.employee_filter(), {"_id": 1}).to_list(length=None)
        return [r["_id"] for r in rows if r["_id"] != user["_id"]]
    return await ls.team_member_ids(db, user["_id"], recursive=(scope == "all"))


async def day_status(db, users: list[dict], ctx: ls.LeaveContext, day: date) -> dict:
    key = day.isoformat()
    ids = [u["_id"] for u in users]
    leaves = {r["employee_id"]: r for r in await db.leave_requests.find({
        "employee_id": {"$in": ids}, "status": {"$in": ["approved", "cancellation_pending"]},
        "from_date": {"$lte": key}, "to_date": {"$gte": key}}).to_list(length=None)}
    attendance = {str(r["user_id"]): r for r in await db.attendance.find(
        {"user_id": {"$in": ids + [str(i) for i in ids]}, "date": key}).to_list(length=None)}
    lt_names = {k: v["name"] for k, v in ctx.leave_types.items()}
    weekly_off = day.weekday() in set(ctx.settings.get("weekly_offs", []))
    out = {}
    for u in users:
        leave = leaves.get(u["_id"])
        holiday = ctx.holiday_on(u, day)
        record = attendance.get(str(u["_id"]))
        if leave:
            half = " (half day)" if leave.get("half_day") else ""
            status, tone = f"On Leave - {lt_names.get(leave['leave_type_id'], 'Leave')}{half}", "leave"
        elif holiday:
            status, tone = f"Holiday - {holiday['name']}", "holiday"
        elif weekly_off:
            status, tone = "Weekend", "weekend"
        elif record:
            status, tone = ("Checked in" if record.get("current_state") == "IN" else "Present"), "present"
        else:
            status, tone = "Yet to check-in", "absent"
        out[u["_id"]] = {"status": status, "tone": tone}
    return out


@router.get("/team/reportees")
async def reportees(scope: str = Query("direct", pattern="^(direct|all)$"), search: str | None = None,
                    user=Depends(require_permission("leave.team")), db=Depends(get_database)):
    direct = await ls.team_member_ids(db, user["_id"], recursive=False)
    all_ids = await team_scope(db, user, "all")
    ids = direct if scope == "direct" else all_ids
    query: dict = {"_id": {"$in": ids}}
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"name": pattern}, {"employee_id": pattern}, {"email": pattern}]
    members = await db.users.find(query).sort("name", 1).to_list(length=None)
    departments, types = await ls.employee_lookup(db)
    policies, standard = await ls.load_shift_context(db)
    ctx = await ls.LeaveContext.load(db, None, [m["_id"] for m in members])
    statuses = await day_status(db, members, ctx, ls.today())
    return {
        "manager": ls.employee_brief(user, departments, types),
        "direct_count": len(direct), "all_count": len(all_ids),
        "members": [{**ls.employee_brief(m, departments, types), "shift": ls.shift_for(m, policies, standard),
                     "is_direct": m["_id"] in set(direct), **statuses[m["_id"]]} for m in members],
    }


@router.get("/team/members/{employee_id}")
async def team_member(employee_id: str, user=Depends(require_permission("leave.team")), db=Depends(get_database)):
    emp_id = ls.to_oid(employee_id, "employee id")
    if not await ls.can_view_employee(db, user, emp_id):
        raise HTTPException(403, "This employee is not in your team")
    emp = await db.users.find_one({"_id": emp_id})
    if not emp:
        raise HTTPException(404, "Employee not found")
    departments, types = await ls.employee_lookup(db)
    policies, standard = await ls.load_shift_context(db)
    ctx = await ls.LeaveContext.load(db, None, [emp_id])
    now = ls.today()
    elig = ctx.eligibility(emp, now)
    reqs = await db.leave_requests.find({"employee_id": emp_id}).sort("from_date", -1).limit(100).to_list(length=100)
    views = await ls.hydrate_requests(db, reqs)
    for v in views:
        if not ls.is_admin(user):
            v["attachment"], v["comments"] = None, []
    month_start = now.replace(day=1)
    att = await db.attendance.find({"user_id": {"$in": [emp_id, str(emp_id)]}, "date": {"$gte": month_start.isoformat(), "$lte": now.isoformat()}},
                                   {"date": 1, "current_state": 1, "total_work_minutes": 1}).to_list(length=None)
    status = (await day_status(db, [emp], ctx, now))[emp_id]
    return {
        **ls.employee_brief(emp, departments, types),
        "shift": ls.shift_for(emp, policies, standard), **status,
        "eligibility": [{**ls.leave_type_brief(ctx.leave_types[k]), **{x: e[x] for x in ("eligible", "source", "type_enabled")}}
                        for k, e in elig.items() if ctx.leave_types[k].get("is_active", True)],
        "balances": [ctx.card(emp, k, e) for k, e in elig.items() if e["eligible"]],
        "upcoming": [v for v in views if v["to_date"] >= now.isoformat() and v["status"] in ls.ACTIVE_STATUSES][::-1],
        "history": views,
        "attendance": {"month": month_start.strftime("%B %Y"), "present_days": len({a["date"] for a in att}),
                       "today": status["status"]},
    }


@router.get("/team/on-leave")
async def team_on_leave(
    from_date: date | None = None, to_date: date | None = None,
    employee_id: str | None = None, department_id: str | None = None,
    employee_type_id: str | None = None, leave_type_id: str | None = None,
    user=Depends(require_permission("leave.team")), db=Depends(get_database),
):
    from_date = from_date or ls.today()
    to_date = to_date or from_date
    if to_date < from_date:
        raise HTTPException(400, "To date must be on or after From date")
    query: dict = {"status": {"$in": ["approved", "cancellation_pending"]},
                   "from_date": {"$lte": to_date.isoformat()}, "to_date": {"$gte": from_date.isoformat()}}
    if not ls.is_admin(user):
        query["employee_id"] = {"$in": await ls.team_member_ids(db, user["_id"], recursive=True)}
    if employee_id:
        emp = ls.to_oid(employee_id, "employee id")
        if not await ls.can_view_employee(db, user, emp):
            raise HTTPException(403, "This employee is not in your team")
        query["employee_id"] = emp
    if department_id:
        query["department_id"] = ls.to_oid(department_id, "department id")
    if employee_type_id:
        query["employee_type_id"] = ls.to_oid(employee_type_id, "employee type id")
    if leave_type_id:
        query["leave_type_id"] = ls.to_oid(leave_type_id, "leave type id")
    rows = await db.leave_requests.find(query).sort("from_date", 1).to_list(length=2000)
    items = await ls.hydrate_requests(db, rows)
    for v in items:
        v["attachment"], v["comments"] = None, []
    return {"from_date": from_date.isoformat(), "to_date": to_date.isoformat(), "items": items}


@router.get("/team/requests")
async def team_requests(
    status: str | None = None, leave_type_id: str | None = None,
    from_date: date | None = None, to_date: date | None = None, search: str | None = None,
    paging=Depends(page_params), user=Depends(require_permission("leave.team")), db=Depends(get_database),
):
    team = await ls.team_member_ids(db, user["_id"], recursive=True)
    query: dict = {"employee_id": {"$in": team}}
    apply_request_filters(query, status, leave_type_id, from_date, to_date)
    if search:
        pattern = {"$regex": re.escape(search.strip()), "$options": "i"}
        ids = [u["_id"] for u in await db.users.find({"_id": {"$in": team}, "$or": [{"name": pattern}, {"employee_id": pattern}]}, {"_id": 1}).to_list(length=None)]
        query["employee_id"] = {"$in": ids}
    result = await paginate(db, query, "applied_at", -1, *paging)
    for v in result["items"]:
        v["attachment"], v["comments"] = None, []
    return result
