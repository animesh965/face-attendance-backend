from bson import ObjectId
from app.core.permissions import permissions_for_role

def oid(value):
    return str(value) if isinstance(value, ObjectId) else value

def user_response(user: dict) -> dict:
    role = user.get("role", "user")
    return {
        "id": oid(user["_id"]), "name": user.get("name", ""), "email": user.get("email", ""),
        "role": role, "is_active": user.get("is_active", True), "employee_id": user.get("employee_id"),
        "phone": user.get("phone"), "gender": user.get("gender"), "department_id": oid(user.get("department_id")),
        "designation_id": oid(user.get("designation_id")), "face_registered": user.get("face_registered", False),
        "permissions": sorted(user.get("permissions") or permissions_for_role(role)), "created_at": user.get("created_at"),
    }
