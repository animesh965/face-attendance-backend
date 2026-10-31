from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.utils.serializers import oid

router=APIRouter(tags=["Employees"])

def employee_view(u,dept=None,des=None):
    return {"id":str(u["_id"]),"name":u.get("name",""),"employeeId":u.get("employee_id",str(u["_id"])),"email":u.get("email",""),"phone":u.get("phone","") or "","department":(dept or {}).get("name",""),"designation":(des or {}).get("name",""),"photo":u.get("photo",""),"registeredAt":u.get("created_at"),"status":"active" if u.get("is_active",True) else "inactive","faceImages":u.get("face_images",[]),"embedding":{"dimensions":512,"model":"buffalo_l","quality":u.get("face_quality",0),"vectors":u.get("face_count",0)}}

@router.get("/employees")
async def list_employees(user=Depends(require_permission("employees.read")),db=Depends(get_database)):
    users=await db.users.find({"employee_id":{"$exists":True}}).sort("name",1).to_list(length=None); out=[]
    for u in users:
        dept=await db.departments.find_one({"_id":u.get("department_id")}) if u.get("department_id") else None
        des=await db.designations.find_one({"_id":u.get("designation_id")}) if u.get("designation_id") else None
        out.append(employee_view(u,dept,des))
    return out

@router.get("/employees/{employee_id}")
async def get_employee(employee_id:str,user=Depends(require_permission("employees.read")),db=Depends(get_database)):
    q={"_id":ObjectId(employee_id)} if ObjectId.is_valid(employee_id) else {"employee_id":employee_id}
    u=await db.users.find_one(q)
    if not u: raise HTTPException(404,"Employee not found")
    dept=await db.departments.find_one({"_id":u.get("department_id")}) if u.get("department_id") else None
    des=await db.designations.find_one({"_id":u.get("designation_id")}) if u.get("designation_id") else None
    return employee_view(u,dept,des)

@router.delete("/employees/{employee_id}")
async def delete_employee(employee_id:str,user=Depends(require_permission("employees.delete")),db=Depends(get_database)):
    q={"_id":ObjectId(employee_id)} if ObjectId.is_valid(employee_id) else {"employee_id":employee_id}
    target=await db.users.find_one(q)
    if not target: raise HTTPException(404,"Employee not found")
    await db.users.update_one({"_id":target["_id"]},{"$set":{"is_active":False}})
    await db.faces.update_many({"user_id":target["_id"]},{"$set":{"active":False}})
    return {"success":True,"message":"Employee deactivated"}
