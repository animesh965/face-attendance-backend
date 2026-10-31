from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.core.time import now_utc

router=APIRouter(prefix="/api/v1/policies",tags=["Attendance Policies"])
@router.get("")
async def list_policies(user=Depends(require_permission("policies.manage")),db=Depends(get_database)):
    rows=await db.policies.find().sort("name",1).to_list(length=100); return [{**x,"id":str(x.pop("_id"))} for x in rows]
@router.post("",status_code=201)
async def create_policy(payload:dict,user=Depends(require_permission("policies.manage")),db=Depends(get_database)):
    doc={"name":payload.get("name","Standard"),"start_time":payload.get("start_time","09:45"),"required_work_minutes":int(payload.get("required_work_minutes",585)),"daily_break_minutes":int(payload.get("daily_break_minutes",45)),"carry_forward":bool(payload.get("carry_forward",True)),"monthly_expiry":bool(payload.get("monthly_expiry",True)),"created_at":now_utc()}
    try:r=await db.policies.insert_one(doc)
    except DuplicateKeyError:raise HTTPException(409,"Policy already exists")
    return {"id":str(r.inserted_id),**{k:v for k,v in doc.items() if k!="_id"}}
@router.put("/{policy_id}/assign/{user_id}")
async def assign_policy(policy_id:str,user_id:str,user=Depends(require_permission("policies.manage")),db=Depends(get_database)):
    if not ObjectId.is_valid(policy_id) or not ObjectId.is_valid(user_id):raise HTTPException(400,"Invalid id")
    await db.users.update_one({"_id":ObjectId(user_id)},{"$set":{"policy_id":ObjectId(policy_id)}}); return {"success":True}
