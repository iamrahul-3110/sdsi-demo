"""
M5 — Weekly recurring booking tests.

Covers:
- Successful full recurrence
- Partial conflicts (some weeks blocked)
- All-weeks-conflict scenario
- Per-occurrence independent evaluation
"""

from datetime import date, time

from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX


def _book(client: TestClient, title: str, room: str, d: str,
          start: str, end: str):
    return client.post(f"{PREFIX}/bookings", json={
        "title": title, "room_id": room, "date": d,
        "start_time": start, "end_time": end,
        "organiser": "blocker@example.com", "attendees": [],
    })


class TestRecurringBasic:
    """Basic recurring booking scenarios."""

    def test_all_occurrences_succeed(self, client: TestClient):
        """No conflicts → all 4 weeks should succeed."""
        payload = {
            "title": "Weekly Team Sync",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "organiser": "eve@example.com",
            "attendees": ["frank@example.com"],
            "recurrence_weeks": 4,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["successful_bookings"]) == 4
        assert len(data["conflicts"]) == 0

        # Verify dates are 1 week apart
        dates = [b["date"] for b in data["successful_bookings"]]
        assert dates == ["2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22"]

    def test_partial_conflicts(self, client: TestClient):
        """Block week 2 — weeks 1, 3, 4 should still succeed."""
        # Block 2026-11-08 (week 2)
        _book(client, "Blocker", "room-001", "2026-11-08", "14:00", "15:00")

        payload = {
            "title": "Weekly Sync",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "organiser": "eve@example.com",
            "attendees": ["frank@example.com"],
            "recurrence_weeks": 4,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["successful_bookings"]) == 3
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["occurrence_date"] == "2026-11-08"
        # Conflict reason includes the conflicting booking IDs (not title)

    def test_all_conflicts(self, client: TestClient):
        """Block every week — all should be reported as conflicts."""
        for w in range(4):
            d = date(2026, 11, 1 + w * 7).isoformat()
            _book(client, f"Blocker{w}", "room-001", d, "10:00", "11:00")

        payload = {
            "title": "All Blocked",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "eve@example.com",
            "attendees": [],
            "recurrence_weeks": 4,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["successful_bookings"]) == 0
        assert len(data["conflicts"]) == 4

    def test_capacity_violation_in_recurring(self, client: TestClient):
        """Capacity check applies to recurring bookings too."""
        payload = {
            "title": "Overflow Weekly",
            "room_id": "room-002",  # capacity 4
            "start_date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "eve@example.com",
            "attendees": [f"user{i}@example.com" for i in range(10)],
            "recurrence_weeks": 2,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "CAPACITY_EXCEEDED"

    def test_single_week_recurrence(self, client: TestClient):
        """recurrence_weeks=1 should create exactly 1 booking."""
        payload = {
            "title": "One-Off",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "09:00",
            "end_time": "10:00",
            "organiser": "eve@example.com",
            "attendees": [],
            "recurrence_weeks": 1,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["successful_bookings"]) == 1

    def test_invalid_time_range_in_recurring(self, client: TestClient):
        """start_time >= end_time should fail."""
        payload = {
            "title": "Bad Time",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "15:00",
            "end_time": "14:00",
            "organiser": "eve@example.com",
            "attendees": [],
            "recurrence_weeks": 3,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 422

    def test_outside_business_hours_recurring(self, client: TestClient):
        """Recurring booking outside 09:00-18:00 should fail."""
        payload = {
            "title": "After Hours",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "08:00",
            "end_time": "09:30",
            "organiser": "eve@example.com",
            "attendees": [],
            "recurrence_weeks": 2,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 422

    def test_deduplicate_attendees_in_recurring(self, client: TestClient):
        payload = {
            "title": "Dedup Recurring",
            "room_id": "room-001",
            "start_date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "eve@example.com",
            "attendees": ["A@example.com", "a@example.com", " B@EXAMPLE.COM "],
            "recurrence_weeks": 1,
        }
        resp = client.post(f"{PREFIX}/bookings/recurring", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["successful_bookings"][0]["attendees"]) == 2