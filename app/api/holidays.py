from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_database
from app.dependencies.auth import get_current_user
from app.dependencies.roles import require_roles
from app.schemas.auth import UserRole
from app.schemas.holiday import HolidayCreate, HolidayUpdate, HolidayResponse

router = APIRouter(prefix="/api/v1/holidays", tags=["Holidays"])
admin_roles = (UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)


def date_to_utc_midnight(value: date):
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def as_response(row):
    from_date = row.get("from_date") or row.get("date")
    to_date = row.get("to_date") or row.get("date")
    if isinstance(from_date, datetime):
        from_date = from_date.date()
    if isinstance(to_date, datetime):
        to_date = to_date.date()
    return HolidayResponse(
        id=str(row["_id"]),
        name=row["name"],
        from_date=from_date,
        to_date=to_date,
        description=row.get("description"),
        holiday_type=row.get("holiday_type", "public"),
        employee_type_ids=[str(x) for x in row.get("employee_type_ids") or []],
        department_ids=[str(x) for x in row.get("department_ids") or []],
        locations=row.get("locations") or [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def applicability(data, only_sent: bool = False) -> dict:
    """Validate the optional employee type / department / location scope of a holiday.
    With only_sent, fields the client did not send are left untouched (older clients)."""
    def oids(values, label):
        out = []
        for value in dict.fromkeys(values):
            if not ObjectId.is_valid(value):
                raise HTTPException(status_code=400, detail=f"Invalid {label}")
            out.append(ObjectId(value))
        return out
    scope = {
        "employee_type_ids": oids(data.employee_type_ids, "employee type id"),
        "department_ids": oids(data.department_ids, "department id"),
        "locations": sorted({x.strip() for x in data.locations if x and x.strip()}),
    }
    if only_sent:
        scope = {k: v for k, v in scope.items() if k in data.model_fields_set}
    return scope


@router.get("", response_model=list[HolidayResponse])
async def list_holidays(
    upcoming_only: bool = Query(default=False),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    user=Depends(get_current_user),
    db=Depends(get_database),
):
    query = {"is_active": True}
    today = datetime.now(timezone.utc).date()
    if upcoming_only:
        today_start = date_to_utc_midnight(today)
        query["$or"] = [
            {"to_date": {"$gte": today_start}},
            {"to_date": {"$exists": False}, "date": {"$gte": today_start}},
        ]
    if from_date or to_date:
        range_start = from_date or today
        range_end = to_date or date.max
        # Return every holiday whose date range overlaps the requested range.
        query["from_date"] = {"$lte": date_to_utc_midnight(range_end)}
        query["to_date"] = {"$gte": date_to_utc_midnight(range_start)}
    cursor = db.holidays.find(query).sort("from_date", 1)
    rows = await cursor.to_list(length=1000)
    return [as_response(row) for row in rows]


@router.post("", response_model=HolidayResponse, status_code=201)
async def create_holiday(
    data: HolidayCreate,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    clean_name = data.name.strip()
    start = date_to_utc_midnight(data.from_date)
    end = date_to_utc_midnight(data.to_date)
    duplicate = await db.holidays.find_one({
        "name": clean_name,
        "from_date": start,
        "to_date": end,
        "is_active": True,
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="This holiday already exists for that date range")
    now = datetime.now(timezone.utc)
    row = {
        "name": clean_name,
        "from_date": start,
        "to_date": end,
        "description": data.description.strip() if data.description else None,
        "holiday_type": data.holiday_type.strip().lower(),
        **applicability(data),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": admin["_id"],
    }
    result = await db.holidays.insert_one(row)
    row["_id"] = result.inserted_id
    return as_response(row)


@router.put("/{holiday_id}", response_model=HolidayResponse)
async def update_holiday(
    holiday_id: str,
    data: HolidayUpdate,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    if not ObjectId.is_valid(holiday_id):
        raise HTTPException(status_code=400, detail="Invalid holiday ID")
    oid = ObjectId(holiday_id)
    current = await db.holidays.find_one({"_id": oid, "is_active": True})
    if not current:
        raise HTTPException(status_code=404, detail="Holiday not found")
    start = date_to_utc_midnight(data.from_date)
    end = date_to_utc_midnight(data.to_date)
    duplicate = await db.holidays.find_one({
        "_id": {"$ne": oid},
        "name": data.name.strip(),
        "from_date": start,
        "to_date": end,
        "is_active": True,
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="This holiday already exists for that date range")
    now = datetime.now(timezone.utc)
    await db.holidays.update_one({"_id": oid}, {"$set": {
        "name": data.name.strip(),
        "from_date": start,
        "to_date": end,
        "description": data.description.strip() if data.description else None,
        "holiday_type": data.holiday_type.strip().lower(),
        **applicability(data, only_sent=True),
        "updated_at": now,
        "updated_by": admin["_id"],
    }})
    return as_response(await db.holidays.find_one({"_id": oid}))


@router.delete("/{holiday_id}")
async def delete_holiday(
    holiday_id: str,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    if not ObjectId.is_valid(holiday_id):
        raise HTTPException(status_code=400, detail="Invalid holiday ID")
    result = await db.holidays.update_one(
        {"_id": ObjectId(holiday_id), "is_active": True},
        {"$set": {"is_active": False, "deleted_at": datetime.now(timezone.utc), "deleted_by": admin["_id"]}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Holiday not found")
    return {"message": "Holiday deleted successfully"}




















# from datetime import date, datetime, time, timezone

# from bson import ObjectId
# from fastapi import APIRouter, Depends, HTTPException, Query
# from pymongo.errors import DuplicateKeyError

# from app.core.database import get_database
# from app.dependencies.auth import get_current_user
# from app.dependencies.roles import require_roles
# from app.schemas.auth import UserRole
# from app.schemas.holiday import HolidayCreate, HolidayUpdate, HolidayResponse

# router = APIRouter(prefix="/api/v1/holidays", tags=["Holidays"])
# admin_roles = (UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)


# def as_response(row):
#     stored_date = row["date"]
#     if isinstance(stored_date, datetime):
#         stored_date = stored_date.date()
#     return HolidayResponse(
#         id=str(row["_id"]),
#         name=row["name"],
#         date=stored_date,
#         description=row.get("description"),
#         holiday_type=row.get("holiday_type", "public"),
#         created_at=row["created_at"],
#         updated_at=row["updated_at"],
#     )


# def date_to_utc_midnight(value: date):
#     return datetime.combine(value, time.min, tzinfo=timezone.utc)


# @router.get("", response_model=list[HolidayResponse])
# async def list_holidays(
#     upcoming_only: bool = Query(default=False),
#     from_date: date | None = Query(default=None),
#     to_date: date | None = Query(default=None),
#     user=Depends(get_current_user),
#     db=Depends(get_database),
# ):
#     query = {"is_active": True}
#     if upcoming_only:
#         query["date"] = {"$gte": date_to_utc_midnight(datetime.now(timezone.utc).date())}
#     else:
#         bounds = {}
#         if from_date:
#             bounds["$gte"] = date_to_utc_midnight(from_date)
#         if to_date:
#             bounds["$lt"] = date_to_utc_midnight(to_date.fromordinal(to_date.toordinal() + 1))
#         if bounds:
#             query["date"] = bounds
#     cursor = db.holidays.find(query).sort("date", 1)
#     return [as_response(row) for row in await cursor.to_list(length=1000)]


# @router.post("", response_model=HolidayResponse, status_code=201)
# async def create_holiday(
#     data: HolidayCreate,
#     admin=Depends(require_roles(*admin_roles)),
#     db=Depends(get_database),
# ):
#     clean_name = data.name.strip()
#     holiday_date = date_to_utc_midnight(data.date)
#     duplicate = await db.holidays.find_one({"date": holiday_date, "name": clean_name, "is_active": True})
#     if duplicate:
#         raise HTTPException(status_code=409, detail="This holiday already exists for that date")
#     now = datetime.now(timezone.utc)
#     row = {
#         "name": clean_name,
#         "date": holiday_date,
#         "description": data.description.strip() if data.description else None,
#         "holiday_type": data.holiday_type.strip().lower(),
#         "is_active": True,
#         "created_at": now,
#         "updated_at": now,
#         "created_by": admin["_id"],
#     }
#     result = await db.holidays.insert_one(row)
#     row["_id"] = result.inserted_id
#     return as_response(row)


# @router.put("/{holiday_id}", response_model=HolidayResponse)
# async def update_holiday(
#     holiday_id: str,
#     data: HolidayUpdate,
#     admin=Depends(require_roles(*admin_roles)),
#     db=Depends(get_database),
# ):
#     if not ObjectId.is_valid(holiday_id):
#         raise HTTPException(status_code=400, detail="Invalid holiday ID")
#     oid = ObjectId(holiday_id)
#     current = await db.holidays.find_one({"_id": oid, "is_active": True})
#     if not current:
#         raise HTTPException(status_code=404, detail="Holiday not found")
#     holiday_date = date_to_utc_midnight(data.date)
#     duplicate = await db.holidays.find_one({
#         "_id": {"$ne": oid}, "date": holiday_date, "name": data.name.strip(), "is_active": True
#     })
#     if duplicate:
#         raise HTTPException(status_code=409, detail="This holiday already exists for that date")
#     now = datetime.now(timezone.utc)
#     await db.holidays.update_one({"_id": oid}, {"$set": {
#         "name": data.name.strip(),
#         "date": holiday_date,
#         "description": data.description.strip() if data.description else None,
#         "holiday_type": data.holiday_type.strip().lower(),
#         "updated_at": now,
#         "updated_by": admin["_id"],
#     }})
#     return as_response(await db.holidays.find_one({"_id": oid}))


# @router.delete("/{holiday_id}")
# async def delete_holiday(
#     holiday_id: str,
#     admin=Depends(require_roles(*admin_roles)),
#     db=Depends(get_database),
# ):
#     if not ObjectId.is_valid(holiday_id):
#         raise HTTPException(status_code=400, detail="Invalid holiday ID")
#     result = await db.holidays.update_one(
#         {"_id": ObjectId(holiday_id), "is_active": True},
#         {"$set": {"is_active": False, "deleted_at": datetime.now(timezone.utc), "deleted_by": admin["_id"]}},
#     )
#     if result.matched_count == 0:
#         raise HTTPException(status_code=404, detail="Holiday not found")
#     return {"message": "Holiday deleted successfully"}
