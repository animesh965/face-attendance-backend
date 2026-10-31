from pathlib import Path
import hashlib
import secrets
from datetime import timedelta

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.core.config import settings
from app.core.time import now_utc
from app.utils.validation import normalize_indian_mobile
from app.services.email_service import send_email

router = APIRouter(tags=["Employees"])


class EmployeeUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    phone: str = Field(default="", max_length=25)
    gender: str = Field(default="", max_length=20)
    department_id: str | None = None
    designation_id: str | None = None
    email_otp: str | None = Field(default=None, min_length=6, max_length=6)


def employee_view(u, dept=None, des=None):
    return {
        "id": str(u["_id"]),
        "name": u.get("name", ""),
        "employeeId": u.get("employee_id", str(u["_id"])),
        "email": u.get("email", ""),
        "phone": u.get("phone", "") or "",
        "gender": u.get("gender", "") or "",
        "department": (dept or {}).get("name", ""),
        "departmentId": str(u["department_id"]) if u.get("department_id") else None,
        "designation": (des or {}).get("name", ""),
        "designationId": str(u["designation_id"]) if u.get("designation_id") else None,
        "photo": u.get("photo", ""),
        "registeredAt": u.get("created_at"),
        "status": "active" if u.get("is_active", True) else "inactive",
        "faceImages": u.get("face_images", []),
        "embedding": {
            "dimensions": 512,
            "model": "buffalo_l",
            "quality": u.get("face_quality", 0),
            "vectors": u.get("face_count", 0),
        },
    }


async def find_employee(employee_id: str, db):
    if ObjectId.is_valid(employee_id):
        target = await db.users.find_one({"_id": ObjectId(employee_id), "employee_id": {"$exists": True}})
    else:
        target = await db.users.find_one({"employee_id": employee_id})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    return target


async def employee_related_data(user, db):
    dept = await db.departments.find_one({"_id": user.get("department_id")}) if user.get("department_id") else None
    des = await db.designations.find_one({"_id": user.get("designation_id")}) if user.get("designation_id") else None
    return dept, des


@router.get("/employees")
async def list_employees(user=Depends(require_permission("employees.read")), db=Depends(get_database)):
    users = await db.users.find({"employee_id": {"$exists": True}}).sort("name", 1).to_list(length=None)
    out = []
    for employee in users:
        dept, des = await employee_related_data(employee, db)
        out.append(employee_view(employee, dept, des))
    return out


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, user=Depends(require_permission("employees.read")), db=Depends(get_database)):
    employee = await find_employee(employee_id, db)
    dept, des = await employee_related_data(employee, db)
    return employee_view(employee, dept, des)


@router.post("/employees/{employee_id}/request-email-otp")
async def request_employee_email_otp(
    employee_id: str,
    data: dict,
    admin=Depends(require_permission("employees.update")),
    db=Depends(get_database),
):
    employee = await find_employee(employee_id, db)
    new_email = str(data.get("email", "")).strip().lower()
    from pydantic import TypeAdapter, EmailStr, ValidationError
    try:
        new_email = str(TypeAdapter(EmailStr).validate_python(new_email)).lower()
    except ValidationError:
        raise HTTPException(status_code=422, detail="Enter a valid email address")

    duplicate = await db.users.find_one({"email": new_email, "_id": {"$ne": employee["_id"]}})
    if duplicate:
        raise HTTPException(status_code=409, detail="This email address is already used by another account")
    if new_email == employee.get("email", "").lower():
        raise HTTPException(status_code=400, detail="New email is the same as the current email")

    otp = f"{secrets.randbelow(1_000_000):06d}"
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    now = now_utc()
    await db.employee_email_otps.update_many(
        {"employee_id": employee["_id"], "used_at": None},
        {"$set": {"used_at": now}},
    )
    await db.employee_email_otps.insert_one({
        "employee_id": employee["_id"],
        "new_email": new_email,
        "otp_hash": otp_hash,
        "created_at": now,
        "expires_at": now + timedelta(minutes=10),
        "used_at": None,
    })
    try:
        await send_email(
            new_email,
            "Verify your new attendance app email",
            f"Your email verification OTP is {otp}. It expires in 10 minutes. If you did not request this, ignore this email.",
        )
    except Exception:
        await db.employee_email_otps.update_one(
            {"employee_id": employee["_id"], "otp_hash": otp_hash, "used_at": None},
            {"$set": {"used_at": now_utc()}},
        )
        raise HTTPException(status_code=502, detail="Unable to send verification email")
    return {"message": "Verification OTP sent to the new email address", "expires_in_minutes": 10}


@router.put("/updateEmployee/{employee_id}")
async def update_employee(
    employee_id: str,
    data: EmployeeUpdateRequest,
    admin=Depends(require_permission("employees.update")),
    db=Depends(get_database),
):
    employee = await find_employee(employee_id, db)

    # Email is the login identifier. A new address must be verified by OTP first.
    email = str(data.email).lower().strip()
    if email != employee.get("email", "").lower():
        if not data.email_otp:
            raise HTTPException(status_code=400, detail="Request and verify an OTP for the new email before saving")
        otp_hash = hashlib.sha256(data.email_otp.encode()).hexdigest()
        otp_record = await db.employee_email_otps.find_one({
            "employee_id": employee["_id"],
            "new_email": email,
            "otp_hash": otp_hash,
            "used_at": None,
            "expires_at": {"$gt": now_utc()},
        })
        if not otp_record:
            raise HTTPException(status_code=400, detail="Email OTP is invalid or expired")
        consumed = await db.employee_email_otps.update_one(
            {"_id": otp_record["_id"], "used_at": None, "expires_at": {"$gt": now_utc()}},
            {"$set": {"used_at": now_utc()}},
        )
        if consumed.modified_count == 0:
            raise HTTPException(status_code=400, detail="Email OTP is invalid or expired")

    phone = normalize_indian_mobile(data.phone)
    duplicate = await db.users.find_one({"email": email, "_id": {"$ne": employee["_id"]}})
    if duplicate:
        raise HTTPException(status_code=409, detail="This email address is already used by another account")
    duplicate_phone = await db.users.find_one({"phone": phone, "_id": {"$ne": employee["_id"]}, "is_active": True})
    if duplicate_phone:
        raise HTTPException(status_code=409, detail="This phone number is already assigned to another employee")

    department_oid = None
    designation_oid = None
    if data.department_id:
        if not ObjectId.is_valid(data.department_id):
            raise HTTPException(status_code=400, detail="Invalid department_id")
        department_oid = ObjectId(data.department_id)
        department = await db.departments.find_one({"_id": department_oid, "is_active": {"$ne": False}})
        if not department:
            raise HTTPException(status_code=404, detail="Department not found")

    if data.designation_id:
        if not ObjectId.is_valid(data.designation_id):
            raise HTTPException(status_code=400, detail="Invalid designation_id")
        designation_oid = ObjectId(data.designation_id)
        designation = await db.designations.find_one({"_id": designation_oid, "is_active": {"$ne": False}})
        if not designation:
            raise HTTPException(status_code=404, detail="Designation not found")
        if not department_oid or str(designation.get("department_id")) != str(department_oid):
            raise HTTPException(status_code=400, detail="Designation must belong to the selected department")

    update_fields = {
        "name": data.name.strip(),
        "email": email,
        "phone": phone,
        "gender": data.gender.strip().lower(),
        "updated_at": now_utc(),
        "updated_by": admin["_id"],
        "department_id": department_oid,
        "designation_id": designation_oid,
    }
    try:
        await db.users.update_one({"_id": employee["_id"]}, {"$set": update_fields})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="This email address is already used by another account")

    updated = await db.users.find_one({"_id": employee["_id"]})
    dept, des = await employee_related_data(updated, db)
    return {"success": True, "message": "Employee updated successfully", "employee": employee_view(updated, dept, des)}


@router.delete("/employees/{employee_id}")
async def hard_delete_employee(
    employee_id: str,
    admin=Depends(require_permission("employees.delete")),
    db=Depends(get_database),
):
    """Permanently remove the employee and their dependent attendance/face records."""
    employee = await find_employee(employee_id, db)

    if employee["_id"] == admin["_id"]:
        raise HTTPException(status_code=400, detail="You cannot permanently delete your own account")

    if employee.get("role") == "super_admin":
        remaining = await db.users.count_documents({
            "role": "super_admin",
            "is_active": True,
            "_id": {"$ne": employee["_id"]},
        })
        if remaining == 0:
            raise HTTPException(status_code=409, detail="Cannot delete the last active super admin")

    # Remove stored face image files, but only paths located under the configured upload directory.
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    face_rows = await db.faces.find({"user_id": employee["_id"]}).to_list(length=None)
    for face in face_rows:
        for key in ("image_path", "crop_path"):
            value = face.get(key)
            if not value:
                continue
            candidate = Path(value)
            # FaceService stores paths relative to the working directory (e.g. "data/uploads/x.jpg");
            # fall back to treating a bare relative name as inside UPLOAD_DIR.
            if not candidate.is_absolute() and not candidate.exists():
                candidate = upload_root / candidate
            try:
                resolved = candidate.resolve()
                if resolved == upload_root or upload_root in resolved.parents:
                    if resolved.is_file():
                        resolved.unlink()
            except (OSError, ValueError):
                # Database deletion must not be blocked by a missing/unreadable old image.
                pass

    # Permanently delete dependent records first, then the employee account.
    await db.faces.delete_many({"user_id": employee["_id"]})
    related_user_ids = {"$in": [employee["_id"], str(employee["_id"])]}
    await db.attendance.delete_many({"user_id": related_user_ids})
    await db.recognition_events.delete_many({"user_id": related_user_ids})
    await db.break_wallets.delete_many({"user_id": related_user_ids})
    await db.password_reset_tokens.delete_many({"user_id": employee["_id"]})
    await db.users.delete_one({"_id": employee["_id"]})

    return {
        "success": True,
        "message": "Employee and related face, attendance, recognition, break-wallet, and password-reset records permanently deleted",
        "deleted_employee_id": str(employee["_id"]),
    }
