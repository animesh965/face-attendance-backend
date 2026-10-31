from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.core.time import now_utc

router=APIRouter(prefix="/api/v1/organization",tags=["Organization"])
@router.get("/departments")
async def departments(user=Depends(require_permission("employees.read")),db=Depends(get_database)):
    rows=await db.departments.find().sort("name",1).to_list(length=None)
    return [{"id":str(x["_id"]),"name":x["name"],"code":x["code"]} for x in rows]
@router.post("/departments",status_code=201)
async def create_department(name:str,code:str,user=Depends(require_permission("organization.manage")),db=Depends(get_database)):
    try:
        r=await db.departments.insert_one({"name":name.strip(),"code":code.strip().upper(),"created_at":now_utc()})
    except DuplicateKeyError: raise HTTPException(409,"Department already exists")
    return {"id":str(r.inserted_id),"name":name.strip(),"code":code.strip().upper()}
@router.get("/designations")
async def designations(department_id:str,user=Depends(require_permission("employees.read")),db=Depends(get_database)):
    if not ObjectId.is_valid(department_id): raise HTTPException(400,"Invalid department_id")
    rows=await db.designations.find({"department_id":ObjectId(department_id)}).sort("name",1).to_list(length=None)
    return [{"id":str(x["_id"]),"name":x["name"],"department_id":str(x["department_id"])} for x in rows]
@router.post("/designations",status_code=201)
async def create_designation(name:str,department_id:str,user=Depends(require_permission("organization.manage")),db=Depends(get_database)):
    if not ObjectId.is_valid(department_id): raise HTTPException(400,"Invalid department_id")
    if not await db.departments.find_one({"_id":ObjectId(department_id)}): raise HTTPException(404,"Department not found")
    try:r=await db.designations.insert_one({"name":name.strip(),"department_id":ObjectId(department_id),"created_at":now_utc()})
    except DuplicateKeyError: raise HTTPException(409,"Designation already exists")
    return {"id":str(r.inserted_id),"name":name.strip(),"department_id":department_id}
