from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Attendance(BaseModel):
    user_id: str
    name: str
    date: str

    check_in: datetime
    check_out: Optional[datetime] = None

    status: str = "present"
