from pydantic import BaseModel


class DesignationResponse(BaseModel):
    id: str
    name: str
    department_id: str
