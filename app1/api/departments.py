from fastapi import APIRouter, Depends

from app.dependencies.roles import require_roles
from app.models.department_model import DepartmentModel
from app.schemas.auth import UserRole
from app.schemas.department import DepartmentResponse


router = APIRouter(
    prefix="/api/v1/departments",
    tags=["Departments"],
)


@router.get(
    "",
    response_model=list[DepartmentResponse],
)
async def get_departments(
    current_user=Depends(
        require_roles(
            UserRole.ADMIN.value,
            UserRole.SUPER_ADMIN.value,
        )
    )
):
    departments = await DepartmentModel.get_all()

    return [
        DepartmentResponse(
            id=str(department["_id"]),
            name=department["name"],
            code=department["code"],
        )
        for department in departments
    ]
