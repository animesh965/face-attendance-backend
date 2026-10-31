from typing import Optional

from pydantic import BaseModel


class AttendanceRecord(BaseModel):

    id: Optional[str] = None

    user_id: str

    name: str

    date: str

    check_in: Optional[str] = None

    check_out: Optional[str] = None

    status: str

    duration_seconds: Optional[int] = None


class AttendanceTodayResponse(BaseModel):

    date: str

    attendance: Optional[AttendanceRecord] = None


class AttendanceMonthlyResponse(BaseModel):

    month: str

    summary: dict

    records: list[AttendanceRecord]
