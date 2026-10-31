from fastapi import APIRouter
from app.core.database import ping_database
router=APIRouter(tags=["Health"])
@router.get("/health")
async def health():
    ok = await ping_database()
    return {"status":"ok" if ok else "degraded", "database":ok}
@router.get("/ready")
async def ready():
    ok=await ping_database()
    return {"ready":ok}
