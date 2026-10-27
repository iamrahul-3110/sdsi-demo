"""
Core booking service.

Orchestrates M1–M5 business logic:
  M1 — CRUD operations
  M2 — Overlap detection
  M3 — Capacity validation
  M4 — Delegates to SlotFinder
  M5 — Weekly recurring bookings with per-occurrence conflict reporting
"""

from datetime import date, datetime, time, timedelta
from typing import List, Optional

from app.config import (
    ERR_BOOKING_NOT_FOUND,
    ERR_CAPACITY_EXCEEDED,
    ERR_INVALID_TIME_RANGE,
    ERR_OVERLAP,
    ERR_ROOM_NOT_FOUND,
)
from app.models.booking import (
    BookingCreate,
    BookingRecurring,
    BookingResponse,
    BookingUpdate,
    FindSlotRequest,
    RecurringResponse,
    _generate_booking_id,
)
from app.models.room import Room
from app.services.slot_finder import SlotFinder
from app.storage.repository import Repository, _BookingRecord


class BookingError(ValueError):
    """Domain-level error with an error_code for the API layer."""

    def __init__(self, detail: str, error_code: str):
        super().__init__(detail)
        self.detail = detail
        self.error_code = error_code


class BookingService:
    """Stateless booking orchestrator.

    All mutations flow through the Repository, which handles thread-safety.
    """

    def __init__(self, repo: Repository):
        self._repo = repo
        self._slot_finder = SlotFinder(repo)

    # ------------------------------------------------------------------
    # M1 — CRUD
    # ------------------------------------------------------------------

    def create_booking(self, data: BookingCreate) -> BookingResponse:
        """Create a new booking after validating conflicts & capacity."""
        self._validate_room(data.room_id)
        self._validate_capacity(data.room_id, len(data.attendees))
        self._check_conflicts(data.room_id, data.date, data.start_time, data.end_time)

        record = _BookingRecord(
            id=_generate_booking_id(),
            title=data.title,
            room_id=data.room_id,
            date=data.date,
            start_time=data.start_time,
            end_time=data.end_time,
            organiser=data.organiser,
            attendees=data.attendees,
        )
        self._repo.create_booking(record)
        return record.to_response()

    def get_booking(self, booking_id: str) -> BookingResponse:
        resp = self._repo.get_booking(booking_id)
        if resp is None:
            raise BookingError(
                f"Booking '{booking_id}' not found", ERR_BOOKING_NOT_FOUND,
            )
        return resp

    def list_bookings(
        self,
        room_id: Optional[str] = None,
        date_filter: Optional[date] = None,
        organiser: Optional[str] = None,
    ) -> List[BookingResponse]:
        return self._repo.list_bookings(room_id, date_filter, organiser)

    def update_booking(self, booking_id: str, data: BookingUpdate) -> BookingResponse:
        existing = self._repo.get_booking_record(booking_id)
        if existing is None:
            raise BookingError(
                f"Booking '{booking_id}' not found", ERR_BOOKING_NOT_FOUND,
            )

        # Merge updates with existing values
        merged_room_id = data.room_id or existing.room_id
        merged_date = data.date or existing.date
        merged_start = data.start_time or existing.start_time
        merged_end = data.end_time or existing.end_time

        # Validate business logic on merged fields
        if merged_start >= merged_end:
            raise BookingError(
                "start_time must be before end_time", ERR_INVALID_TIME_RANGE,
            )
        self._validate_room(merged_room_id)

        attendee_count = (
            len(data.attendees)
            if data.attendees is not None
            else len(existing.attendees)
        )
        self._validate_capacity(merged_room_id, attendee_count)

        self._check_conflicts(
            merged_room_id, merged_date, merged_start, merged_end,
            exclude_id=booking_id,
        )

        updates: dict = {}
        for field in ("title", "room_id", "date", "start_time", "end_time",
                       "organiser", "attendees"):
            val = getattr(data, field)
            if val is not None:
                updates[field] = val

        updated = self._repo.update_booking(booking_id, updates)
        assert updated is not None
        return updated.to_response()

    def delete_booking(self, booking_id: str) -> None:
        if not self._repo.delete_booking(booking_id):
            raise BookingError(
                f"Booking '{booking_id}' not found", ERR_BOOKING_NOT_FOUND,
            )

    # ------------------------------------------------------------------
    # M4 — Find Slot
    # ------------------------------------------------------------------

    def find_slot(self, req: FindSlotRequest) -> Optional[dict]:
        """Find the best available time slot and room."""
        result = self._slot_finder.find_earliest_slot(
            d=req.date,
            duration_minutes=req.duration_minutes,
            attendee_count=req.attendee_count,
        )
        if result is None:
            return None
        start, room = result
        h, m = divmod(req.duration_minutes, 60)
        end = (
            datetime.combine(req.date, start) + timedelta(hours=h, minutes=m)
        ).time()
        return {
            "date": req.date.isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M"),
            "duration_minutes": req.duration_minutes,
            "room": room.model_dump(),
        }

    # ------------------------------------------------------------------
    # M5 — Recurring
    # ------------------------------------------------------------------

    def create_recurring(self, data: BookingRecurring) -> RecurringResponse:
        """Create weekly recurring bookings.

        Each occurrence is evaluated independently. Conflicts do not block
        successful bookings — they are reported alongside.
        """
        self._validate_room(data.room_id)
        self._validate_capacity(data.room_id, len(data.attendees))

        successful: list[BookingResponse] = []
        conflicts: list[dict] = []

        for week in range(data.recurrence_weeks):
            occ_date = data.start_date + timedelta(weeks=week)
            conflict_list = self._repo.find_conflicts(
                data.room_id, occ_date, data.start_time, data.end_time,
            )
            if conflict_list:
                conflicts.append({
                    "occurrence_date": occ_date.isoformat(),
                    "reason": (
                        f"Overlap with booking(s): "
                        f"{', '.join(c.id for c in conflict_list)}"
                    ),
                    "conflicting_booking_ids": [c.id for c in conflict_list],
                })
                continue

            record = _BookingRecord(
                id=_generate_booking_id(),
                title=data.title,
                room_id=data.room_id,
                date=occ_date,
                start_time=data.start_time,
                end_time=data.end_time,
                organiser=data.organiser,
                attendees=data.attendees,
            )
            self._repo.create_booking(record)
            successful.append(record.to_response())

        return RecurringResponse(
            successful_bookings=successful,
            conflicts=conflicts,
        )

    # ------------------------------------------------------------------
    # M3 — Rooms
    # ------------------------------------------------------------------

    def list_rooms(self) -> list[Room]:
        return self._repo.get_rooms()

    def get_room(self, room_id: str) -> Room:
        room = self._repo.get_room(room_id)
        if room is None:
            raise BookingError(
                f"Room '{room_id}' not found", ERR_ROOM_NOT_FOUND,
            )
        return room

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_room(self, room_id: str) -> None:
        if not self._repo.room_exists(room_id):
            raise BookingError(
                f"Room '{room_id}' does not exist", ERR_ROOM_NOT_FOUND,
            )

    def _validate_capacity(self, room_id: str, attendee_count: int) -> None:
        room = self._repo.get_room(room_id)
        if room and attendee_count > room.capacity:
            raise BookingError(
                f"Room '{room.name}' (capacity {room.capacity}) cannot hold "
                f"{attendee_count} attendees",
                ERR_CAPACITY_EXCEEDED,
            )

    def _check_conflicts(
        self,
        room_id: str,
        d: date,
        start: time,
        end: time,
        exclude_id: Optional[str] = None,
    ) -> None:
        conflicts = self._repo.find_conflicts(room_id, d, start, end, exclude_id)
        if conflicts:
            raise BookingError(
                f"Time slot overlaps with existing booking(s): "
                f"{', '.join(c.id for c in conflicts)}",
                ERR_OVERLAP,
            )