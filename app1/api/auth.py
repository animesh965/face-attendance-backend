from fastapi import APIRouter, Depends, HTTPException, status, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from pymongo.errors import DuplicateKeyError
from app.core.database import get_database
from app.core.security import hash_password, verify_password, create_access_token
from app.core.permissions import permissions_for_role
from app.dependencies.auth import get_current_user
from app.schemas.auth import LoginRequest, SignupRequest, LoginResponse, UserResponse, UserRole
from app.utils.serializers import user_response
from datetime import datetime, timezone

router=APIRouter(prefix="/api/v1/auth",tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)

@router.post("/signup",response_model=UserResponse,status_code=201)
async def signup(data: SignupRequest, db=Depends(get_database)):
    now=datetime.now(timezone.utc)
    doc={"name":data.name.strip(),"email":data.email.lower(),"password_hash":hash_password(data.password),"role":"user","permissions":permissions_for_role("user"),"is_active":True,"face_registered":False,"created_at":now,"updated_at":now}
    try: r=await db.users.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,"Email already registered")
    doc["_id"]=r.inserted_id
    return user_response(doc)

@router.post("/login",response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, db=Depends(get_database)):
    user=await db.users.find_one({"email":data.email.lower()})
    if not user or not verify_password(data.password,user.get("password_hash","")):
        raise HTTPException(401,"Invalid email or password",headers={"WWW-Authenticate":"Bearer"})
    if not user.get("is_active",True): raise HTTPException(403,"User account is disabled")
    token=create_access_token({"sub":str(user["_id"]),"role":user.get("role","user")})
    return {"access_token":token,"token_type":"bearer","user":user_response(user)}

@router.get("/me",response_model=UserResponse)
async def me(user=Depends(get_current_user)): return user_response(user)
