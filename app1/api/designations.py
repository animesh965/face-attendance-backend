from fastapi import APIRouter, Depends, Query

from app.dependencies.roles import require_roles
from app.models.designation_model import DesignationModel
from app.schemas.auth import UserRole
from app.schemas.designation import DesignationResponse


router = APIRouter(
    prefix="/api/v1/designations",
    tags=["Designations"],
)


@router.get(
    "",
    response_model=list[DesignationResponse],
)
async def get_designations(
    department_id: str = Query(...),
    current_user=Depends(
        require_roles(
            UserRole.ADMIN.value,
            UserRole.SUPER_ADMIN.value,
        )
    ),
):
    designations = await DesignationModel.get_by_department(
        department_id
    )

    return [
        DesignationResponse(
            id=str(designation["_id"]),
            name=designation["name"],
            department_id=str(
                designation["department_id"]
            ),
        )
        for designation in designations
    ]
