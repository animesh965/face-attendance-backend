from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator


class HolidayCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    from_date: date
    to_date: date
    description: str | None = Field(default=None, max_length=500)
    holiday_type: str = Field(default="public", min_length=2, max_length=40)
    # Empty lists mean the holiday applies to everyone.
    employee_type_ids: list[str] = Field(default_factory=list, max_length=100)
    department_ids: list[str] = Field(default_factory=list, max_length=200)
    locations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.to_date < self.from_date:
            raise ValueError("To date must be on or after from date")
        return self


class HolidayUpdate(HolidayCreate):
    pass


class HolidayResponse(BaseModel):
    id: str
    name: str
    from_date: date
    to_date: date
    description: str | None = None
    holiday_type: str
    employee_type_ids: list[str] = []
    department_ids: list[str] = []
    locations: list[str] = []
    created_at: datetime
    updated_at: datetime
















# from datetime import date, datetime
# from pydantic import BaseModel, Field


# class HolidayCreate(BaseModel):
#     name: str = Field(min_length=2, max_length=120)
#     date: date
#     description: str | None = Field(default=None, max_length=500)
#     holiday_type: str = Field(default="public", min_length=2, max_length=40)


# class HolidayUpdate(BaseModel):
#     name: str = Field(min_length=2, max_length=120)
#     date: date
#     description: str | None = Field(default=None, max_length=500)
#     holiday_type: str = Field(default="public", min_length=2, max_length=40)


# class HolidayResponse(BaseModel):
#     id: str
#     name: str
#     date: date
#     description: str | None = None
#     holiday_type: str
#     created_at: datetime
#     updated_at: datetime
