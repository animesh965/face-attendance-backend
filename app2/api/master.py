from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from app.dependencies.roles import require_roles
from app.schemas.auth import UserRole
from app.schemas.master import (
    DepartmentResponse,
    DesignationResponse,
)
from app.models.department_model import (
    DepartmentModel,
)
from app.models.designation_model import (
    DesignationModel,
)


router = APIRouter(
    prefix="/api/v1/master",
    tags=["Master Data"],
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN.value,
                UserRole.SUPER_ADMIN.value,
            )
        )
    ],
)


@router.get(
    "/departments",
    response_model=list[DepartmentResponse],
)
async def get_departments():

    departments = (
        await DepartmentModel.get_all()
    )

    return [
        DepartmentResponse(
            id=str(department["_id"]),
            name=department["name"],
        )
        for department in departments
    ]


@router.get(
    "/designations",
    response_model=list[DesignationResponse],
)
async def get_designations(
    department_id: str,
):

    try:
        designations = (
            await DesignationModel
            .get_by_department(
                department_id
            )
        )

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid department ID",
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
