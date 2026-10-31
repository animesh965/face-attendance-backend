from fastapi import Depends, HTTPException

from app.dependencies.auth import get_current_user


async def get_current_admin(
    current_user=Depends(get_current_user)
):

    if current_user.get("role") != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )

    return current_user
