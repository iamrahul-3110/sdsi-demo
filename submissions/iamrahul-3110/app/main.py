"""
FastAPI Meeting Room Booking Engine.

Start with:
    uvicorn app.main:app --reload

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""

from datetime import date
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.config import API_PREFIX, ERR_INVALID_TIME_RANGE, ERR_OUTSIDE_BUSINESS_HOURS
from app.models.booking import (
    BookingCreate,
    BookingListResponse,
    BookingRecurring,
    BookingResponse,
    BookingUpdate,
    ErrorDetail,
    FindSlotRequest,
    RecurringResponse,
)
from app.models.room import Room
from app.services.booking_service import BookingError, BookingService
from app.storage.repository import get_repository

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Meeting Room Booking Engine",
    description=(
        "Production-grade room reservation API with CRUD, conflict detection, "
        "capacity validation, intelligent slot-finding, and recurring bookings."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Dependency (overridden in tests via app.dependency_overrides)
# ---------------------------------------------------------------------------

def get_booking_service() -> BookingService:
    """FastAPI dependency that provides a BookingService instance."""
    return BookingService(get_repository())


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(BookingError)
async def booking_error_handler(request: Request, exc: BookingError) -> JSONResponse:
    status_code = {
        "ROOM_NOT_FOUND": 404,
        "BOOKING_NOT_FOUND": 404,
        "OVERLAP": 409,
        "CAPACITY_EXCEEDED": 422,
        "INVALID_TIME_RANGE": 422,
        "OUTSIDE_BUSINESS_HOURS": 422,
        "DURATION_EXCEEDS_MAX": 422,
        "PAST_DATE": 422,
    }.get(exc.error_code, 400)
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    detail = "Invalid request"
    if exc.errors():
        err = exc.errors()[0]
        field = " → ".join(str(loc) for loc in err["loc"])
        detail = f"{field}: {err['msg']}"
    error_code = ERR_INVALID_TIME_RANGE
    detail_lower = detail.lower()
    if "business hour" in detail_lower:
        error_code = ERR_OUTSIDE_BUSINESS_HOURS
    elif "start_time must be before end_time" in detail_lower:
        error_code = ERR_INVALID_TIME_RANGE
    return JSONResponse(
        status_code=422,
        content={"detail": detail, "error_code": error_code},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": "HTTP_ERROR"},
    )


# ---------------------------------------------------------------------------
# M3 — Rooms
# ---------------------------------------------------------------------------

@app.get(
    f"{API_PREFIX}/rooms",
    response_model=List[Room],
    tags=["Rooms"],
    summary="List all available rooms",
)
async def list_rooms(svc: BookingService = Depends(get_booking_service)):
    """Return every conference room loaded from the seed data."""
    return svc.list_rooms()


@app.get(
    f"{API_PREFIX}/rooms/{{room_id}}",
    response_model=Room,
    tags=["Rooms"],
    summary="Get a single room by ID",
    responses={404: {"model": ErrorDetail}},
)
async def get_room(
    room_id: str,
    svc: BookingService = Depends(get_booking_service),
):
    """Retrieve details for a specific room."""
    return svc.get_room(room_id)


# ---------------------------------------------------------------------------
# M1 — Bookings CRUD
# ---------------------------------------------------------------------------

@app.post(
    f"{API_PREFIX}/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Bookings"],
    summary="Create a new booking (M1)",
    responses={
        409: {"model": ErrorDetail, "description": "Time slot overlap"},
        422: {"model": ErrorDetail, "description": "Capacity exceeded or invalid time"},
        404: {"model": ErrorDetail, "description": "Room not found"},
    },
)
async def create_booking(
    body: BookingCreate,
    svc: BookingService = Depends(get_booking_service),
):
    """Book a room for a given date and time range.

    Validates:
    - Room exists
    - Attendee count ≤ room capacity (after deduplication)
    - No overlapping bookings on the same room+date
    - Back-to-back bookings (E1 == S2) are allowed
    """
    return svc.create_booking(body)


@app.get(
    f"{API_PREFIX}/bookings",
    response_model=BookingListResponse,
    tags=["Bookings"],
    summary="List bookings (filterable)",
)
async def list_bookings(
    room_id: Optional[str] = Query(None, description="Filter by room ID"),
    date: Optional[date] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    organiser: Optional[str] = Query(None, description="Filter by organiser"),
    svc: BookingService = Depends(get_booking_service),
):
    """List all bookings, optionally filtered by room, date, or organiser."""
    bookings = svc.list_bookings(room_id, date, organiser)
    return BookingListResponse(bookings=bookings, count=len(bookings))


@app.get(
    f"{API_PREFIX}/bookings/{{booking_id}}",
    response_model=BookingResponse,
    tags=["Bookings"],
    summary="Retrieve a single booking (M1)",
    responses={404: {"model": ErrorDetail}},
)
async def get_booking(
    booking_id: str,
    svc: BookingService = Depends(get_booking_service),
):
    """Get a booking by its unique ID."""
    return svc.get_booking(booking_id)


@app.put(
    f"{API_PREFIX}/bookings/{{booking_id}}",
    response_model=BookingResponse,
    tags=["Bookings"],
    summary="Update an existing booking (M1)",
    responses={
        404: {"model": ErrorDetail},
        409: {"model": ErrorDetail},
        422: {"model": ErrorDetail},
    },
)
async def update_booking(
    booking_id: str,
    body: BookingUpdate,
    svc: BookingService = Depends(get_booking_service),
):
    """Update a booking's fields.

    Partial updates are supported — omitted fields keep their current values.
    Re-validates conflicts (excluding self) and capacity on the merged result.
    """
    return svc.update_booking(booking_id, body)


@app.delete(
    f"{API_PREFIX}/bookings/{{booking_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Bookings"],
    summary="Cancel/delete a booking (M1)",
    responses={404: {"model": ErrorDetail}},
)
async def delete_booking(
    booking_id: str,
    svc: BookingService = Depends(get_booking_service),
):
    """Remove a booking permanently."""
    svc.delete_booking(booking_id)


# ---------------------------------------------------------------------------
# M4 — Find Slot
# ---------------------------------------------------------------------------

@app.post(
    f"{API_PREFIX}/bookings/find-slot",
    tags=["Slot Finder"],
    summary="Find the earliest available time slot (M4)",
    responses={
        200: {
            "description": "Slot found",
            "content": {
                "application/json": {
                    "example": {
                        "date": "2026-10-28",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "duration_minutes": 60,
                        "room": {"id": "room-003", "name": "The Fishbowl", "capacity": 4},
                    }
                }
            },
        },
        404: {"model": ErrorDetail, "description": "No slot available"},
    },
)
async def find_slot(
    body: FindSlotRequest,
    svc: BookingService = Depends(get_booking_service),
):
    """Search for the earliest time slot that fits the group.

    Uses **best-fit capacity** tie-breaking: when multiple rooms can hold
    the group, the *smallest* room wins to minimise capacity waste.

    Constraints:
    - Business hours: 09:00 – 18:00
    - Duration: 1 – 540 minutes
    """
    result = svc.find_slot(body)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "detail": (
                    f"No available slot found for {body.attendee_count} attendees "
                    f"on {body.date} ({body.duration_minutes} min)"
                ),
                "error_code": "NO_SLOT_AVAILABLE",
            },
        )
    return result


# ---------------------------------------------------------------------------
# M5 — Recurring
# ---------------------------------------------------------------------------

@app.post(
    f"{API_PREFIX}/bookings/recurring",
    response_model=RecurringResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Bookings"],
    summary="Create weekly recurring bookings (M5)",
    responses={
        404: {"model": ErrorDetail},
        422: {"model": ErrorDetail},
    },
)
async def create_recurring(
    body: BookingRecurring,
    svc: BookingService = Depends(get_booking_service),
):
    """Schedule the same booking across multiple weeks.

    Each occurrence is evaluated independently:
    - Successful bookings are returned in `successful_bookings`.
    - Conflicting dates are reported in `conflicts` with the reason
      and conflicting booking IDs.

    This is *not* all-or-nothing — conflicts on some weeks do not
    prevent successful bookings on other weeks.
    """
    return svc.create_recurring(body)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"], summary="Health check")
async def health():
    return {"status": "ok", "service": "meeting-room-booking-engine"}