"""Booking domain model and Pydantic schemas."""

from datetime import date as dt_date, datetime as dt_datetime, time as dt_time
from typing import List, Optional
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.config import BUSINESS_HOURS_END, BUSINESS_HOURS_START


def _generate_booking_id() -> str:
    return f"b-{uuid4().hex[:12]}"


class BookingBase(BaseModel):
    """Shared fields for booking schemas."""
    title: str = Field(..., min_length=1, max_length=150, description="Meeting title")
    room_id: str = Field(..., description="ID of the room to book")
    date: dt_date = Field(..., description="Date of the booking (YYYY-MM-DD)")
    start_time: dt_time = Field(..., description="Meeting start time (HH:MM)")
    end_time: dt_time = Field(..., description="Meeting end time (HH:MM)")
    organiser: str = Field(..., min_length=1, max_length=100, description="Organiser name or email")
    attendees: List[str] = Field(
        default_factory=list,
        max_length=500,
        description="Attendee email addresses",
    )

    @field_validator("attendees", mode="after")
    @classmethod
    def deduplicate_attendees(cls, v: List[str]) -> List[str]:
        """Deduplicate attendee list, preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for email in v:
            normalized = email.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @model_validator(mode="after")
    def start_before_end(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self

    @model_validator(mode="after")
    def within_business_hours(self):
        if self.start_time < BUSINESS_HOURS_START or self.end_time > BUSINESS_HOURS_END:
            raise ValueError(
                f"Booking must be within business hours "
                f"({BUSINESS_HOURS_START.strftime('%H:%M')} - "
                f"{BUSINESS_HOURS_END.strftime('%H:%M')})"
            )
        return self


class BookingCreate(BookingBase):
    """Request schema for creating a new booking."""
    pass


class BookingUpdate(BaseModel):
    """Request schema for updating an existing booking. All fields optional."""
    title: Optional[str] = Field(None, min_length=1, max_length=150)
    room_id: Optional[str] = None
    date: Optional[dt_date] = None
    start_time: Optional[dt_time] = None
    end_time: Optional[dt_time] = None
    organiser: Optional[str] = Field(None, min_length=1, max_length=100)
    attendees: Optional[List[str]] = Field(None, max_length=500)

    @field_validator("attendees", mode="after")
    @classmethod
    def deduplicate_attendees(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        seen: set[str] = set()
        result: list[str] = []
        for email in v:
            normalized = email.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


class BookingResponse(BaseModel):
    """Response schema for a booking."""
    id: str
    title: str
    room_id: str
    date: dt_date
    start_time: dt_time
    end_time: dt_time
    organiser: str
    attendees: List[str]
    created_at: dt_datetime
    updated_at: dt_datetime


class BookingRecurring(BaseModel):
    """Request schema for creating weekly recurring bookings."""
    title: str = Field(..., min_length=1, max_length=150)
    room_id: str = Field(...)
    start_date: dt_date = Field(..., description="First occurrence date (YYYY-MM-DD)")
    start_time: dt_time = Field(...)
    end_time: dt_time = Field(...)
    organiser: str = Field(..., min_length=1, max_length=100)
    attendees: List[str] = Field(default_factory=list, max_length=500)
    recurrence_weeks: int = Field(
        ...,
        ge=1,
        le=12,
        description="Number of weekly repetitions (1-12)",
    )

    @field_validator("attendees", mode="after")
    @classmethod
    def deduplicate_attendees(cls, v: List[str]) -> List[str]:
        seen: set[str] = set()
        result: list[str] = []
        for email in v:
            normalized = email.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @model_validator(mode="after")
    def start_before_end(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self

    @model_validator(mode="after")
    def within_business_hours(self):
        if self.start_time < BUSINESS_HOURS_START or self.end_time > BUSINESS_HOURS_END:
            raise ValueError(
                f"Booking must be within business hours "
                f"({BUSINESS_HOURS_START.strftime('%H:%M')} - "
                f"{BUSINESS_HOURS_END.strftime('%H:%M')})"
            )
        return self


class FindSlotRequest(BaseModel):
    """Request schema for finding an available time slot."""
    date: dt_date = Field(..., description="Date to search (YYYY-MM-DD)")
    duration_minutes: int = Field(..., ge=1, le=540, description="Meeting duration in minutes")
    attendee_count: int = Field(..., ge=1, description="Number of attendees")

    @field_validator("duration_minutes")
    @classmethod
    def max_duration_check(cls, v: int) -> int:
        from app.config import MAX_SLOT_DURATION_MINUTES
        if v > MAX_SLOT_DURATION_MINUTES:
            raise ValueError(f"Duration cannot exceed {MAX_SLOT_DURATION_MINUTES} minutes")
        return v


class RecurringResponse(BaseModel):
    """Response for recurring booking creation."""
    successful_bookings: List[BookingResponse] = Field(default_factory=list)
    conflicts: List[dict] = Field(default_factory=list)


class BookingListResponse(BaseModel):
    """Paginated/filtered booking list."""
    bookings: List[BookingResponse]
    count: int


class ErrorDetail(BaseModel):
    """Standardized error response."""
    detail: str
    error_code: str