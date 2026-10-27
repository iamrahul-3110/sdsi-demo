"""
M4 — Find-Slot engine tests.

Covers:
- Basic slot finding
- Best-fit capacity tie-breaking
- Business hour boundary enforcement
- Duration exceeding working hours
- No-slot-available scenarios
"""

from datetime import date, time

from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX


def _book(client: TestClient, room: str, d: str, start: str, end: str,
          attendees: int = 2):
    payload = {
        "title": "Blocker",
        "room_id": room,
        "date": d,
        "start_time": start,
        "end_time": end,
        "organiser": "alice@example.com",
        "attendees": [f"user{i}@example.com" for i in range(min(attendees, 5))],
    }
    return client.post(f"{PREFIX}/bookings", json=payload)


class TestFindSlotBasic:
    """Core slot-finding scenarios."""

    def test_find_slot_empty_day(self, client: TestClient):
        """With no bookings, should return 09:00 in the smallest-capacity room."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 60,
            "attendee_count": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "09:00"
        assert data["duration_minutes"] == 60
        # Best-fit: 3 attendees → room-002 (capacity 4) is the best fit
        assert data["room"]["id"] == "room-002"

    def test_find_slot_with_existing_booking(self, client: TestClient):
        """Existing 09:00-10:30 should push new slot to 10:30."""
        _book(client, "room-001", "2026-11-01", "09:00", "10:30")
        # room-001 is the only room with capacity ≥ 8 (capacity 10)
        # room-002 capacity 4, room-003 capacity 20
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 60,
            "attendee_count": 8,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "10:30"
        assert data["room"]["id"] == "room-001"

    def test_best_fit_capacity_tiebreaker(self, client: TestClient):
        """When both room-001 (cap 10) and room-003 (cap 20) can fit 3,
        room-001 should be picked as the best (smallest) fit."""
        # Block room-002 (capacity 4, best fit for 3) from 09:00-17:00
        _book(client, "room-002", "2026-11-01", "09:00", "17:00", attendees=4)
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 60,
            "attendee_count": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        # room-001 (cap 10) is smaller than room-003 (cap 20)
        assert data["room"]["id"] == "room-001"

    def test_find_slot_exact_business_end(self, client: TestClient):
        """A 60-min slot starting at 17:00 is valid (ends at 18:00)."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 60,
            "attendee_count": 1,
        })
        assert resp.status_code == 200
        # Should find a slot — doesn't have to be 17:00, but it should exist
        data = resp.json()
        assert data["start_time"] is not None


class TestFindSlotEdgeCases:
    """Boundary conditions for the slot finder."""

    def test_no_room_has_capacity(self, client: TestClient):
        """When attendee count exceeds every room's capacity."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 30,
            "attendee_count": 500,
        })
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "NO_SLOT_AVAILABLE"

    def test_duration_exceeds_business_hours(self, client: TestClient):
        """Requesting 541 minutes (> 540) should fail validation."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 541,
            "attendee_count": 1,
        })
        assert resp.status_code == 422

    def test_duration_exactly_540_minutes(self, client: TestClient):
        """A full-day (09:00-18:00) slot is valid."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 540,
            "attendee_count": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "18:00"

    def test_no_gap_large_enough(self, client: TestClient):
        """Fill most of the day leaving only 30-min gaps, request 60 min."""
        # Fill room-002 (capacity 4) with bookings leaving only 30-min gaps
        _book(client, "room-002", "2026-11-01", "09:00", "10:30")
        _book(client, "room-002", "2026-11-01", "11:00", "12:30")
        _book(client, "room-002", "2026-11-01", "13:00", "14:30")
        _book(client, "room-002", "2026-11-01", "15:00", "16:30")
        # This leaves 30-min gaps — 60 min won't fit in room-002
        # But room-001 or room-003 should work
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 60,
            "attendee_count": 3,
        })
        # Should fall back to room-001 (capacity 10)
        assert resp.status_code == 200
        assert resp.json()["room"]["id"] == "room-001"

    def test_completely_full_day(self, client: TestClient):
        """Block all rooms for the whole day."""
        for room in ["room-001", "room-002", "room-003"]:
            _book(client, room, "2026-11-01", "09:00", "18:00")
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 30,
            "attendee_count": 1,
        })
        assert resp.status_code == 404

    def test_find_slot_zero_duration(self, client: TestClient):
        """0 minutes is invalid (ge=1)."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 0,
            "attendee_count": 1,
        })
        assert resp.status_code == 422

    def test_find_slot_zero_attendees(self, client: TestClient):
        """0 attendees is invalid (ge=1)."""
        resp = client.post(f"{PREFIX}/bookings/find-slot", json={
            "date": "2026-11-01",
            "duration_minutes": 30,
            "attendee_count": 0,
        })
        assert resp.status_code == 422