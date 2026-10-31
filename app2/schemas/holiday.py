from datetime import date, datetime
from pydantic import BaseModel, Field


class HolidayCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    date: date
    description: str | None = Field(default=None, max_length=500)
    holiday_type: str = Field(default="public", min_length=2, max_length=40)


class HolidayUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    date: date
    description: str | None = Field(default=None, max_length=500)
    holiday_type: str = Field(default="public", min_length=2, max_length=40)


class HolidayResponse(BaseModel):
    id: str
    name: str
    date: date
    description: str | None = None
    holiday_type: str
    created_at: datetime
    updated_at: datetime
