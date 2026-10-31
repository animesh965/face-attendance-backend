from pydantic import BaseModel


class DepartmentResponse(BaseModel):
    id: str
    name: str


class DesignationResponse(BaseModel):
    id: str
    name: str
    department_id: str
