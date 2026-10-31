from datetime import date, datetime, time, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.core.database import get_database
from app.dependencies.auth import get_current_user
from app.dependencies.roles import require_roles
from app.schemas.auth import UserRole
from app.schemas.holiday import HolidayCreate, HolidayUpdate, HolidayResponse

router = APIRouter(prefix="/api/v1/holidays", tags=["Holidays"])
admin_roles = (UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)


def as_response(row):
    stored_date = row["date"]
    if isinstance(stored_date, datetime):
        stored_date = stored_date.date()
    return HolidayResponse(
        id=str(row["_id"]),
        name=row["name"],
        date=stored_date,
        description=row.get("description"),
        holiday_type=row.get("holiday_type", "public"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def date_to_utc_midnight(value: date):
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


@router.get("", response_model=list[HolidayResponse])
async def list_holidays(
    upcoming_only: bool = Query(default=False),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    user=Depends(get_current_user),
    db=Depends(get_database),
):
    query = {"is_active": True}
    if upcoming_only:
        query["date"] = {"$gte": date_to_utc_midnight(datetime.now(timezone.utc).date())}
    else:
        bounds = {}
        if from_date:
            bounds["$gte"] = date_to_utc_midnight(from_date)
        if to_date:
            bounds["$lt"] = date_to_utc_midnight(to_date.fromordinal(to_date.toordinal() + 1))
        if bounds:
            query["date"] = bounds
    cursor = db.holidays.find(query).sort("date", 1)
    return [as_response(row) for row in await cursor.to_list(length=1000)]


@router.post("", response_model=HolidayResponse, status_code=201)
async def create_holiday(
    data: HolidayCreate,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    clean_name = data.name.strip()
    holiday_date = date_to_utc_midnight(data.date)
    duplicate = await db.holidays.find_one({"date": holiday_date, "name": clean_name, "is_active": True})
    if duplicate:
        raise HTTPException(status_code=409, detail="This holiday already exists for that date")
    now = datetime.now(timezone.utc)
    row = {
        "name": clean_name,
        "date": holiday_date,
        "description": data.description.strip() if data.description else None,
        "holiday_type": data.holiday_type.strip().lower(),
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
    holiday_date = date_to_utc_midnight(data.date)
    duplicate = await db.holidays.find_one({
        "_id": {"$ne": oid}, "date": holiday_date, "name": data.name.strip(), "is_active": True
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="This holiday already exists for that date")
    now = datetime.now(timezone.utc)
    await db.holidays.update_one({"_id": oid}, {"$set": {
        "name": data.name.strip(),
        "date": holiday_date,
        "description": data.description.strip() if data.description else None,
        "holiday_type": data.holiday_type.strip().lower(),
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
