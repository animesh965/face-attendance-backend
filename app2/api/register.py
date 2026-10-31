from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.services.face_service import FaceService
from app.core.time import now_utc
from app.core.config import settings

router=APIRouter(prefix="/register",tags=["Face Registration"])

@router.get("/users")
async def users_for_registration(user=Depends(require_permission("face.register")),db=Depends(get_database)):
    rows=await db.users.find({"role":"user","is_active":True}).sort("name",1).to_list(length=None)
    return [{"id":str(x["_id"]),"name":x.get("name"),"email":x.get("email"),"face_registered":x.get("face_registered",False)} for x in rows]

@router.post("/register-employee")
async def register_employee(user_id:str=Form(...),phone:str=Form(""),gender:str=Form(""),department_id:str=Form(...),designation_id:str=Form(...),images:List[UploadFile]=File(...),admin=Depends(require_permission("face.register")),db=Depends(get_database)):
    if len(images)<settings.MIN_FACE_IMAGES or len(images)>settings.MAX_FACE_IMAGES: raise HTTPException(400,f"Upload between {settings.MIN_FACE_IMAGES} and {settings.MAX_FACE_IMAGES} face images")
    if not ObjectId.is_valid(user_id): raise HTTPException(400,"Invalid user_id")
    user=await db.users.find_one({"_id":ObjectId(user_id)})
    if not user: raise HTTPException(404,"User not found")
    if user.get("face_registered"): raise HTTPException(409,"Employee is already registered")
    dept=await db.departments.find_one({"_id":ObjectId(department_id)}) if ObjectId.is_valid(department_id) else None
    des=await db.designations.find_one({"_id":ObjectId(designation_id)}) if ObjectId.is_valid(designation_id) else None
    if not dept or not des: raise HTTPException(404,"Department or designation not found")
    if str(des.get("department_id"))!=str(dept["_id"]): raise HTTPException(400,"Designation does not belong to department")
    existing=await db.users.count_documents({"employee_id":{"$exists":True}}); employee_id=f"EMP{existing+1:05d}"
    faces=[]
    for idx,file in enumerate(images,1):
        if file.content_type and not file.content_type.startswith("image/"): raise HTTPException(400,f"Image {idx} is not an image")
        item=await FaceService.extract_and_store(await file.read(),True)
        # Duplicate face check against stored embeddings.
        import numpy as np
        q=np.asarray(item["embedding"],dtype=np.float32); q/=max(np.linalg.norm(q),1e-8)
        all_faces=await db.faces.find({"active":True,"user_id":{"$ne":user["_id"]}},{"embedding":1,"user_id":1}).to_list(length=None)
        for old in all_faces:
            v=np.asarray(old.get("embedding",[]),dtype=np.float32)
            if v.size==q.size:
                v/=max(np.linalg.norm(v),1e-8)
                if float(np.dot(q,v))>=0.80: raise HTTPException(409,"This face is already registered")
        item.update({"user_id":user["_id"],"employee_id":employee_id,"image_number":idx,"active":True,"created_at":now_utc()})
        r=await db.faces.insert_one(item); item["_id"]=r.inserted_id; faces.append(item)
    await db.users.update_one({"_id":user["_id"]},{"$set":{"employee_id":employee_id,"phone":phone.strip(),"gender":gender.strip().lower(),"department_id":dept["_id"],"designation_id":des["_id"],"face_registered":True,"updated_at":now_utc()}})
    return {"message":"Employee registered successfully","user":{"id":str(user["_id"]),"name":user["name"],"email":user["email"],"employee_id":employee_id,"phone":phone,"gender":gender},"department":{"id":str(dept["_id"]),"name":dept["name"]},"designation":{"id":str(des["_id"]),"name":des["name"]},"face":{"image_count":len(faces),"images":[{"id":str(x["_id"]),"image_number":x["image_number"],"confidence":x["confidence"],"image_path":x["image_path"],"crop_path":x["crop_path"]} for x in faces]}}
