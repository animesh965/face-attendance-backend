import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_database
from app.core.permissions import permissions_for_role
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password, create_access_token
from app.dependencies.auth import get_current_user
from app.dependencies.roles import require_roles
from app.schemas.auth import (
    ForgotPasswordRequest, LoginRequest, LoginResponse, ResetPasswordRequest,
    SignupRequest, UserResponse, UserRole,
)
from app.services.email_service import email_is_configured, send_password_reset_email
from app.utils.serializers import user_response

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/signup", response_model=UserResponse, status_code=201)
async def signup(
    data: SignupRequest,
    admin=Depends(require_roles(UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value)),
    db=Depends(get_database),
):
    """Create a standard employee/user account; role is always backend-controlled."""
    now = datetime.now(timezone.utc)
    email = str(data.email).lower().strip()
    doc = {
        "name": data.name.strip(),
        "email": email,
        "password_hash": hash_password(data.password),
        "role": UserRole.USER.value,
        "permissions": permissions_for_role(UserRole.USER.value),
        "is_active": True,
        "face_registered": False,
        "created_at": now,
        "updated_at": now,
        "created_by": admin["_id"],
    }
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Email already registered")
    doc["_id"] = result.inserted_id
    return user_response(doc)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, db=Depends(get_database)):
    user = await db.users.find_one({"email": str(data.email).lower().strip()})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User account is disabled")
    token = create_access_token({"sub": str(user["_id"]), "role": user.get("role", "user")})
    return {"access_token": token, "token_type": "bearer", "user": user_response(user)}


@router.get("/me", response_model=UserResponse)
async def me(user=Depends(get_current_user)):
    return user_response(user)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db=Depends(get_database)):
    # Fail clearly when deployment mail settings are missing; never silently pretend an email was sent.
    if not email_is_configured() or not settings.FRONTEND_RESET_PASSWORD_URL:
        raise HTTPException(
            status_code=503,
            detail="Password reset email is not configured. Set SMTP and frontend reset URL environment variables.",
        )

    email = str(data.email).lower().strip()
    user = await db.users.find_one({"email": email, "is_active": True})

    # Same response for existing and unknown accounts to reduce account enumeration.
    generic_response = {"message": "If an active account exists for this email, a password reset link will be sent."}
    if not user:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)

    await db.password_reset_tokens.update_many(
        {"user_id": user["_id"], "used_at": None},
        {"$set": {"used_at": now}},
    )
    await db.password_reset_tokens.insert_one({
        "user_id": user["_id"],
        "token_hash": token_hash,
        "created_at": now,
        "expires_at": expires_at,
        "used_at": None,
    })

    separator = "&" if "?" in settings.FRONTEND_RESET_PASSWORD_URL else "?"
    reset_url = settings.FRONTEND_RESET_PASSWORD_URL + separator + urlencode({"token": raw_token})
    try:
        await send_password_reset_email(
            email, reset_url, settings.PASSWORD_RESET_EXPIRE_MINUTES
        )
    except Exception:
        # Do not expose SMTP internals or reset tokens to API clients.
        await db.password_reset_tokens.update_one(
            {"token_hash": token_hash},
            {"$set": {"used_at": datetime.now(timezone.utc)}},
        )
        raise HTTPException(status_code=502, detail="Unable to send password reset email. Please try again later.")

    return generic_response


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password(request: Request, data: ResetPasswordRequest, db=Depends(get_database)):
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    reset_record = await db.password_reset_tokens.find_one({
        "token_hash": token_hash,
        "used_at": None,
        "expires_at": {"$gt": now},
    })
    if not reset_record:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")

    # Consume first, atomically, so concurrent requests cannot reuse the same token.
    consumed = await db.password_reset_tokens.update_one(
        {"_id": reset_record["_id"], "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}},
    )
    if consumed.modified_count == 0:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")

    result = await db.users.update_one(
        {"_id": reset_record["user_id"], "is_active": True},
        {"$set": {"password_hash": hash_password(data.new_password), "updated_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    return {"message": "Password has been reset successfully"}
