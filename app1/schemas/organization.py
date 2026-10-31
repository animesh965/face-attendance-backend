from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=20,
    )


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: str


class DesignationCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )
    department_id: str


class DesignationResponse(BaseModel):
    id: str
    name: str
    department_id: str