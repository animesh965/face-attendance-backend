from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.core.database import get_database
from app.dependencies.roles import require_roles
from app.models.designation_model import DesignationModel
from app.schemas.auth import UserRole
from app.schemas.designation import DesignationResponse

router = APIRouter(prefix="/api/v1/designations", tags=["Designations"])
admin_roles = (UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)


class DesignationCreateUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    department_id: str = Field(min_length=24, max_length=24)


@router.get("", response_model=list[DesignationResponse])
async def get_designations(
    department_id: str = Query(...),
    current_user=Depends(require_roles(*admin_roles)),
):
    try:
        designations = await DesignationModel.get_by_department(department_id)
    except (ValueError, InvalidId):
        raise HTTPException(status_code=400, detail="Invalid department ID")
    return [
        DesignationResponse(id=str(d["_id"]), name=d["name"], department_id=str(d["department_id"]))
        for d in designations
    ]


@router.put("/{designation_id}", response_model=DesignationResponse)
async def update_designation(
    designation_id: str,
    data: DesignationCreateUpdate,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    if not ObjectId.is_valid(designation_id) or not ObjectId.is_valid(data.department_id):
        raise HTTPException(status_code=400, detail="Invalid designation or department ID")
    designation = await db.designations.find_one({"_id": ObjectId(designation_id), "is_active": True})
    if not designation:
        raise HTTPException(status_code=404, detail="Designation not found")
    department = await db.departments.find_one({"_id": ObjectId(data.department_id), "is_active": True})
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    clean_name = data.name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Designation name is required")
    duplicate = await db.designations.find_one({
        "_id": {"$ne": ObjectId(designation_id)},
        "department_id": ObjectId(data.department_id),
        "normalized_name": clean_name.lower(),
        "is_active": True,
    })
    if duplicate:
        raise HTTPException(status_code=409, detail="This designation already exists in the department")

    await db.designations.update_one(
        {"_id": ObjectId(designation_id)},
        {"$set": {
            "name": clean_name,
            "normalized_name": clean_name.lower(),
            "department_id": ObjectId(data.department_id),
            "updated_at": datetime.now(timezone.utc),
            "updated_by": admin["_id"],
        }},
    )
    updated = await db.designations.find_one({"_id": ObjectId(designation_id)})
    return DesignationResponse(id=str(updated["_id"]), name=updated["name"], department_id=str(updated["department_id"]))


@router.delete("/{designation_id}")
async def delete_designation(
    designation_id: str,
    admin=Depends(require_roles(*admin_roles)),
    db=Depends(get_database),
):
    if not ObjectId.is_valid(designation_id):
        raise HTTPException(status_code=400, detail="Invalid designation ID")
    oid = ObjectId(designation_id)
    designation = await db.designations.find_one({"_id": oid, "is_active": True})
    if not designation:
        raise HTTPException(status_code=404, detail="Designation not found")

    # Preserve employee history and references; inactive designations disappear from active lists.
    assigned_count = await db.users.count_documents({"designation_id": oid, "is_active": True})
    if assigned_count:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete this designation because it is assigned to {assigned_count} active user(s). Reassign them first.",
        )

    await db.designations.update_one(
        {"_id": oid},
        {"$set": {"is_active": False, "deleted_at": datetime.now(timezone.utc), "deleted_by": admin["_id"]}},
    )
    return {"message": "Designation deleted successfully"}
