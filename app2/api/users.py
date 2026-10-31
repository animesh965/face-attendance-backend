from fastapi import APIRouter, Depends
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.utils.serializers import user_response
router=APIRouter(prefix="/api/v1/users",tags=["Users"])
@router.get("/for-registration")
async def users(user=Depends(require_permission("employees.read")),db=Depends(get_database)):
    rows=await db.users.find({"role":"user","is_active":True}).sort("name",1).to_list(length=5000)
    return [{"id":str(x["_id"]),"name":x.get("name"),"email":x.get("email"),"face_registered":x.get("face_registered",False)} for x in rows]
