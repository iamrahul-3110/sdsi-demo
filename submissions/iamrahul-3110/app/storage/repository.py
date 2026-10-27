"""Thread-safe in-memory repository for rooms and bookings.

Provides pluggable storage with mutex-based locking and optional
SQLite persistence (future extension point).
"""

import json
import threading
from datetime import date, datetime, time
from typing import Dict, List, Optional

from app.models.booking import BookingResponse
from app.models.room import Room

# ---------------------------------------------------------------------------
# Internal domain record (what we store)
# ---------------------------------------------------------------------------

class _BookingRecord:
    """Internal booking representation with metadata."""
    __slots__ = (
        "id", "title", "room_id", "date", "start_time", "end_time",
        "organiser", "attendees", "created_at", "updated_at",
    )

    def __init__(
        self,
        id: str,
        title: str,
        room_id: str,
        date: date,
        start_time: time,
        end_time: time,
        organiser: str,
        attendees: List[str],
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.title = title
        self.room_id = room_id
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.organiser = organiser
        self.attendees = attendees
        now = datetime.utcnow()
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_response(self) -> BookingResponse:
        return BookingResponse(
            id=self.id,
            title=self.title,
            room_id=self.room_id,
            date=self.date,
            start_time=self.start_time,
            end_time=self.end_time,
            organiser=self.organiser,
            attendees=list(self.attendees),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "room_id": self.room_id,
            "date": self.date.isoformat(),
            "start_time": self.start_time.strftime("%H:%M"),
            "end_time": self.end_time.strftime("%H:%M"),
            "organiser": self.organiser,
            "attendees": list(self.attendees),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

ROOMS_JSON_PATH = __file__.rstrip(".py").removesuffix("repository").rstrip("/\\") + "rooms.json"


class Repository:
    """Thread-safe in-memory store for rooms and bookings.

    All mutation methods acquire a re-entrant lock so concurrent
    FastAPI threads cannot produce race conditions during booking
    overlap checks and inserts.
    """

    def __init__(self, seed_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._rooms: Dict[str, Room] = {}
        self._bookings: Dict[str, _BookingRecord] = {}
        self._seed_rooms(seed_path or ROOMS_JSON_PATH)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    def _seed_rooms(self, path: str) -> None:
        """Load room definitions from a JSON seed file."""
        with open(path, "r") as fh:
            raw = json.load(fh)
        for obj in raw:
            room = Room(**obj)
            self._rooms[room.id] = room

    def get_rooms(self) -> List[Room]:
        """Return all available rooms, sorted by id."""
        with self._lock:
            return sorted(self._rooms.values(), key=lambda r: r.id)

    def get_room(self, room_id: str) -> Optional[Room]:
        with self._lock:
            return self._rooms.get(room_id)

    def room_exists(self, room_id: str) -> bool:
        with self._lock:
            return room_id in self._rooms

    # ------------------------------------------------------------------
    # Bookings — CRUD
    # ------------------------------------------------------------------

    def create_booking(self, record: _BookingRecord) -> _BookingRecord:
        with self._lock:
            self._bookings[record.id] = record
            return record

    def get_booking(self, booking_id: str) -> Optional[BookingResponse]:
        with self._lock:
            rec = self._bookings.get(booking_id)
            return rec.to_response() if rec else None

    def get_booking_record(self, booking_id: str) -> Optional[_BookingRecord]:
        """Return internal record (for conflict checks during updates)."""
        with self._lock:
            return self._bookings.get(booking_id)

    def list_bookings(
        self,
        room_id: Optional[str] = None,
        date_filter: Optional[date] = None,
        organiser: Optional[str] = None,
    ) -> List[BookingResponse]:
        with self._lock:
            result = self._bookings.values()
            if room_id:
                result = [r for r in result if r.room_id == room_id]
            if date_filter:
                result = [r for r in result if r.date == date_filter]
            if organiser:
                norm = organiser.strip().lower()
                result = [r for r in result if r.organiser.strip().lower() == norm]
            return sorted(
                [r.to_response() for r in result],
                key=lambda b: (b.date, b.start_time),
            )

    def list_booking_records_for_date(
        self, room_id: str, d: date
    ) -> List[_BookingRecord]:
        """Return all *internal records* for a room on a given date."""
        with self._lock:
            return [
                r for r in self._bookings.values()
                if r.room_id == room_id and r.date == d
            ]

    def update_booking(
        self, booking_id: str, updates: dict
    ) -> Optional[_BookingRecord]:
        with self._lock:
            rec = self._bookings.get(booking_id)
            if rec is None:
                return None
            for field, value in updates.items():
                if field.endswith("_time") and isinstance(value, str):
                    value = time.fromisoformat(value)
                elif field == "date" and isinstance(value, str):
                    value = date.fromisoformat(value)
                setattr(rec, field, value)
            rec.updated_at = datetime.utcnow()
            return rec

    def delete_booking(self, booking_id: str) -> bool:
        with self._lock:
            if booking_id in self._bookings:
                del self._bookings[booking_id]
                return True
            return False

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def find_conflicts(
        self,
        room_id: str,
        d: date,
        start: time,
        end: time,
        exclude_id: Optional[str] = None,
    ) -> List[_BookingRecord]:
        """Return bookings on the same room+date that overlap [start, end).

        Back-to-back (E1 == S2) is allowed.
        """
        with self._lock:
            candidates = [
                r for r in self._bookings.values()
                if r.room_id == room_id and r.date == d
            ]
            conflicts: List[_BookingRecord] = []
            for rec in candidates:
                if exclude_id and rec.id == exclude_id:
                    continue
                # Strict overlap: S1 < E2 AND E1 > S2
                if rec.start_time < end and rec.end_time > start:
                    conflicts.append(rec)
            return conflicts

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict:
        """Return a deep copy of all data (for testing/diagnostics)."""
        with self._lock:
            return {
                "rooms": [r.model_dump() for r in self._rooms.values()],
                "bookings": [b.to_dict() for b in self._bookings.values()],
            }


# ---------------------------------------------------------------------------
# Singleton (replace via DI in tests)
# ---------------------------------------------------------------------------

_repo_instance: Optional[Repository] = None
_repo_lock = threading.Lock()


def get_repository() -> Repository:
    """Return the singleton Repository, creating it on first access."""
    global _repo_instance
    if _repo_instance is None:
        with _repo_lock:
            if _repo_instance is None:
                _repo_instance = Repository()
    return _repo_instance


def set_repository(repo: Repository) -> None:
    """Replace the global repository (used in tests for isolation)."""
    global _repo_instance
    with _repo_lock:
        _repo_instance = repo