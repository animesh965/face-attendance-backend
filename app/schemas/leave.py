from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HalfDaySession = Literal["first_half", "second_half"]
AccrualFrequency = Literal["yearly", "monthly"]
MappingAction = Literal["enable", "disable", "inherit"]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class EmployeeTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool = True

    @field_validator("name", "code", "description")
    @classmethod
    def _strip(cls, value):
        return _clean(value)


class EmployeeLeaveProfileIn(BaseModel):
    employee_type_id: str | None = None
    reporting_manager_id: str | None = None
    date_of_joining: date | None = None
    probation_end_date: date | None = None
    location: str | None = Field(default=None, max_length=80)
    policy_id: str | None = None

    @field_validator("location")
    @classmethod
    def _strip(cls, value):
        return _clean(value)


class LeaveRules(BaseModel):
    """Rules shared by a leave type's defaults and an employee-type-specific policy."""
    annual_entitlement: float = Field(default=0, ge=0, le=366)
    accrual_frequency: AccrualFrequency = "yearly"
    carry_forward: bool = False
    max_carry_forward: float = Field(default=0, ge=0, le=366)
    carry_forward_expiry_months: int = Field(default=0, ge=0, le=24)
    allow_half_day: bool = True
    min_days: float = Field(default=0.5, ge=0.5, le=366)
    max_days: float = Field(default=0, ge=0, le=366)  # 0 = no maximum
    allow_during_probation: bool = True
    min_service_days: int = Field(default=0, ge=0, le=3650)
    allow_negative_balance: bool = False
    negative_balance_limit: float = Field(default=0, ge=0, le=366)
    exclude_weekly_offs: bool = True
    exclude_holidays: bool = True
    advance_notice_days: int = Field(default=0, ge=0, le=365)
    allow_past_dates: bool = True
    max_past_days: int = Field(default=30, ge=0, le=365)

    @model_validator(mode="after")
    def check_range(self):
        if self.max_days and self.max_days < self.min_days:
            raise ValueError("Maximum duration must be greater than or equal to minimum duration")
        return self


class LeaveTypeIn(LeaveRules):
    name: str = Field(min_length=2, max_length=60)
    code: str = Field(min_length=1, max_length=10)
    description: str | None = Field(default=None, max_length=500)
    color: str = Field(default="#3b82f6", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str = Field(default="calendar", max_length=30)
    is_paid: bool = True
    is_lwp: bool = False
    requires_document: bool = False
    document_required_after_days: float = Field(default=0, ge=0, le=366)
    encashable: bool = False
    max_encashable_days: float = Field(default=0, ge=0, le=366)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, value):
        return _clean(value)

    @field_validator("code")
    @classmethod
    def upper_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Code may only contain letters, digits, '-' and '_'")
        return value

    @model_validator(mode="after")
    def lwp_unpaid(self):
        if self.is_lwp:
            self.is_paid = False
        return self


class LeavePolicyIn(LeaveRules):
    leave_type_id: str
    employee_type_id: str | None = None  # None = applies to every employee type
    name: str | None = Field(default=None, max_length=80)
    is_active: bool = True


class LeaveSettingsIn(BaseModel):
    weekly_offs: list[int] = Field(default_factory=lambda: [5, 6])  # Python weekday(): Mon=0 .. Sun=6
    leave_year_start_month: int = Field(default=1, ge=1, le=12)
    count_pending_against_balance: bool = True

    @field_validator("weekly_offs")
    @classmethod
    def valid_days(cls, value: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in value):
            raise ValueError("Weekly offs must be weekday numbers 0 (Monday) to 6 (Sunday)")
        if len(set(value)) > 6:
            raise ValueError("At least one working day is required")
        return sorted(set(value))


class TypeMappingSaveIn(BaseModel):
    """Replace the mapped leave types of each selected employee type.

    Leave types listed in `unchanged_leave_type_ids` keep their current state
    (they are shown as indeterminate when the selected employee types differ)."""
    employee_type_ids: list[str] = Field(min_length=1, max_length=200)
    leave_type_ids: list[str] = Field(default_factory=list, max_length=500)
    unchanged_leave_type_ids: list[str] = Field(default_factory=list, max_length=500)
    effective_from: date | None = None


class EmployeeMappingSaveIn(BaseModel):
    employee_ids: list[str] = Field(min_length=1, max_length=5000)
    leave_type_ids: list[str] = Field(min_length=1, max_length=500)
    action: MappingAction
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def check_dates(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Effective end date must be on or after the start date")
        return self


class AllocationIn(BaseModel):
    """Allocate an annual number of days for a leave type and year.

    Exactly one target: an employee type (type-wise), or one or more employees (individual / bulk)."""
    leave_type_id: str
    year: int = Field(ge=2000, le=2100)
    days: float = Field(ge=0, le=366)
    employee_type_id: str | None = None
    employee_ids: list[str] = Field(default_factory=list, max_length=5000)
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.employee_type_id) == bool(self.employee_ids):
            raise ValueError("Choose either an employee type or one or more employees")
        return self


class AdjustmentIn(BaseModel):
    employee_ids: list[str] = Field(min_length=1, max_length=5000)
    leave_type_id: str
    year: int = Field(ge=2000, le=2100)
    kind: Literal["adjustment", "opening", "carry_forward"] = "adjustment"
    days: float = Field(ge=-366, le=366)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("days")
    @classmethod
    def non_zero(cls, value: float) -> float:
        if value == 0:
            raise ValueError("Days must not be zero")
        if round(value * 2) != value * 2:
            raise ValueError("Days must be in steps of 0.5")
        return value


class CarryForwardIn(BaseModel):
    from_year: int = Field(ge=2000, le=2100)
    leave_type_ids: list[str] = Field(default_factory=list)  # empty = every carry-forward-eligible type


class LeaveApplyIn(BaseModel):
    leave_type_id: str
    from_date: date
    to_date: date
    half_day: bool = False
    half_day_session: HalfDaySession | None = None
    team_email: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("team_email", "reason")
    @classmethod
    def _strip(cls, value):
        return _clean(value)

    @model_validator(mode="after")
    def check(self):
        if self.to_date < self.from_date:
            raise ValueError("To date must be on or after From date")
        if (self.to_date - self.from_date).days > 366:
            raise ValueError("A single application cannot exceed one year")
        if self.half_day:
            if self.from_date != self.to_date:
                raise ValueError("Half-day leave must start and end on the same date")
            if not self.half_day_session:
                raise ValueError("Choose the first or second half for a half-day leave")
        else:
            self.half_day_session = None
        return self


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _strip(cls, value):
        return _clean(value)


class RejectIn(BaseModel):
    comment: str = Field(min_length=3, max_length=1000)


class OverrideIn(BaseModel):
    status: Literal["approved", "rejected", "cancelled"]
    comment: str = Field(min_length=3, max_length=1000)


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    filters: dict = Field(default_factory=dict)
