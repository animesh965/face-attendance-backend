from pydantic import BaseModel


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: str
