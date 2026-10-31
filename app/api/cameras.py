from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.core.time import now_utc

router=APIRouter(prefix="/cameras",tags=["Cameras"])

def view(x): return {"id":str(x["_id"]),"name":x["name"],"rtspUrl":x.get("rtsp_url",""),"location":x.get("location",""),"status":x.get("status","offline"),"resolution":x.get("resolution","1280x720"),"fps":x.get("fps",25)}
@router.get("")
async def list_cameras(user=Depends(require_permission("cameras.manage")),db=Depends(get_database)):
    return [view(x) for x in await db.cameras.find().sort("name",1).to_list(length=100)]
@router.post("")
async def create_camera(payload:dict,user=Depends(require_permission("cameras.manage")),db=Depends(get_database)):
    doc={"name":payload.get("name","Camera"),"rtsp_url":payload.get("rtspUrl",payload.get("rtsp_url","")),"location":payload.get("location",""),"status":"offline","resolution":payload.get("resolution","1280x720"),"fps":int(payload.get("fps",25)),"created_at":now_utc()}
    try:r=await db.cameras.insert_one(doc)
    except DuplicateKeyError:raise HTTPException(409,"Camera name already exists")
    doc["_id"]=r.inserted_id; return view(doc)
@router.put("/{camera_id}")
async def update_camera(camera_id:str,payload:dict,user=Depends(require_permission("cameras.manage")),db=Depends(get_database)):
    if not ObjectId.is_valid(camera_id):raise HTTPException(400,"Invalid camera id")
    fields={"name":payload.get("name"),"rtsp_url":payload.get("rtspUrl",payload.get("rtsp_url")),"location":payload.get("location"),"resolution":payload.get("resolution"),"fps":payload.get("fps")}
    fields={k:v for k,v in fields.items() if v is not None}; await db.cameras.update_one({"_id":ObjectId(camera_id)},{"$set":fields}); x=await db.cameras.find_one({"_id":ObjectId(camera_id)}); return view(x)
@router.delete("/{camera_id}")
async def delete_camera(camera_id:str,user=Depends(require_permission("cameras.manage")),db=Depends(get_database)):
    await db.cameras.delete_one({"_id":ObjectId(camera_id)}); return {"success":True}
