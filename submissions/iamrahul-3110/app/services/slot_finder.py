"""
M4 — Find-Slot engine.

Given a date, duration, and attendee count, returns the earliest available
start time and the best-fit room (smallest room that can hold the group).
"""

from datetime import date, time
from typing import List, Optional, Tuple

from app.config import BUSINESS_HOURS_END, BUSINESS_HOURS_START
from app.models.room import Room
from app.storage.repository import _BookingRecord, Repository


class SlotFinder:
    """Interval-search engine with best-fit capacity tie-breaker."""

    def __init__(self, repo: Repository):
        self._repo = repo

    def find_earliest_slot(
        self,
        d: date,
        duration_minutes: int,
        attendee_count: int,
    ) -> Optional[Tuple[time, Room]]:
        """Return (start_time, room) or None if no slot fits.

        Algorithm:
        1. Filter rooms by capacity.
        2. Sort rooms by capacity ascending (best-fit first).
        3. For each room, collect existing bookings on that date.
        4. Compress those bookings into busy-intervals, then walk from
           09:00 looking for the first gap ≥ duration_minutes.
        5. Track the earliest start across all rooms; if tied, the
           smaller-capacity room wins.
        """
        # Capacity-filtered rooms, sorted best-fit (smallest first)
        candidates: List[Room] = sorted(
            [r for r in self._repo.get_rooms() if r.capacity >= attendee_count],
            key=lambda r: r.capacity,
        )
        if not candidates:
            return None

        best_start: Optional[time] = None
        best_room: Optional[Room] = None

        max_end_ts = self._time_to_minutes(BUSINESS_HOURS_END)

        for room in candidates:
            start = self._first_gap_for_room(
                room_id=room.id,
                d=d,
                duration_min=duration_minutes,
                max_end_min=max_end_ts,
            )
            if start is None:
                continue
            if best_start is None or start < best_start:
                best_start = start
                best_room = room
                # Early exit: if we found a slot starting at 09:00 in the
                # smallest room, it cannot be improved.
                if best_start == BUSINESS_HOURS_START and room.capacity == candidates[0].capacity:
                    break

        if best_start is None or best_room is None:
            return None
        return best_start, best_room

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _time_to_minutes(t: time) -> int:
        return t.hour * 60 + t.minute

    @staticmethod
    def _minutes_to_time(m: int) -> time:
        h, mi = divmod(m, 60)
        return time(h, mi)

    def _first_gap_for_room(
        self,
        room_id: str,
        d: date,
        duration_min: int,
        max_end_min: int,
    ) -> Optional[time]:
        records: List[_BookingRecord] = self._repo.list_booking_records_for_date(
            room_id, d
        )
        # Build sorted busy intervals as (start_min, end_min)
        busy: List[Tuple[int, int]] = sorted(
            (SlotFinder._time_to_minutes(r.start_time),
             SlotFinder._time_to_minutes(r.end_time))
            for r in records
        )
        cursor = SlotFinder._time_to_minutes(BUSINESS_HOURS_START)
        for b_start, b_end in busy:
            gap = b_start - cursor
            if gap >= duration_min and cursor + duration_min <= max_end_min:
                return SlotFinder._minutes_to_time(cursor)
            cursor = max(cursor, b_end)
        # Check after last busy interval
        if max_end_min - cursor >= duration_min:
            return SlotFinder._minutes_to_time(cursor)
        return None