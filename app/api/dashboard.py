from fastapi import APIRouter, Depends
from app.dependencies.permissions import require_permission
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@router.get("/")
async def dashboard(user=Depends(require_permission("dashboard.read"))):
    return await DashboardService.get_dashboard(user)
