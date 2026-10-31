from fastapi import Depends, HTTPException
from app.dependencies.auth import get_current_user
from app.core.permissions import ROLE_PERMISSIONS

def require_permission(permission: str):
    async def dependency(user=Depends(get_current_user)):
        allowed = set(user.get("permissions") or ROLE_PERMISSIONS.get(user.get("role"), set()))
        if permission not in allowed:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return dependency

def require_roles(*roles: str):
    async def dependency(user=Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return dependency
