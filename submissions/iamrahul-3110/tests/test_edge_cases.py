"""
Edge-case and robustness tests.

Covers:
- Invalid time ranges (start >= end)
- Business hours boundary violations
- Concurrent booking attempts (thread safety smoke test)
- Past date handling
- Update self-collision
- Empty attendees
- Various validation edge cases
"""

import concurrent.futures
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX

# ---------------------------------------------------------------------------
# Invalid time ranges
# ---------------------------------------------------------------------------

class TestInvalidTimeRanges:
    def test_start_equals_end(self, client: TestClient):
        payload = {
            "title": "Zero Duration",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "10:00",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422

    def test_start_after_end(self, client: TestClient):
        payload = {
            "title": "Reverse Time",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "15:00",
            "end_time": "10:00",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Business hours
# ---------------------------------------------------------------------------

class TestBusinessHours:
    def test_before_business_hours(self, client: TestClient):
        payload = {
            "title": "Early Bird",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "08:00",
            "end_time": "09:30",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422

    def test_after_business_hours(self, client: TestClient):
        payload = {
            "title": "Night Owl",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "17:00",
            "end_time": "19:00",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422

    def test_exactly_business_hours(self, client: TestClient):
        """09:00-18:00 is valid."""
        payload = {
            "title": "Full Day",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "09:00",
            "end_time": "18:00",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 201

    def test_partially_outside_hours(self, client: TestClient):
        """Starts in-hours but ends after."""
        payload = {
            "title": "Runs Late",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "17:30",
            "end_time": "18:30",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Concurrency (thread safety smoke test)
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_bookings_same_slot(
        self, client: TestClient,
    ):
        """Multiple threads trying to book the same room+time should
        produce exactly one success — the rest should get OVERLAP."""
        def try_book(worker_id: int) -> int:
            payload = {
                "title": f"Concurrent {worker_id}",
                "room_id": "room-001",
                "date": "2026-11-01",
                "start_time": "10:00",
                "end_time": "11:00",
                "organiser": f"worker{worker_id}@example.com",
                "attendees": [],
            }
            resp = client.post(f"{PREFIX}/bookings", json=payload)
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(try_book, range(8)))

        # Exactly one should succeed (201), rest should conflict (409)
        assert results.count(201) == 1, (
            f"Expected exactly 1 success, got {results.count(201)}: {results}"
        )
        assert results.count(409) == 7

    def test_concurrent_bookings_different_rooms(
        self, client: TestClient,
    ):
        """Different rooms — all should succeed."""
        def try_book(worker_id: int) -> int:
            payload = {
                "title": f"Room {worker_id}",
                "room_id": f"room-00{worker_id % 3 + 1}",
                "date": "2026-11-01",
                "start_time": f"{10 + worker_id % 7:02d}:00",
                "end_time": f"{11 + worker_id % 7:02d}:00",
                "organiser": f"worker{worker_id}@example.com",
                "attendees": [],
            }
            resp = client.post(f"{PREFIX}/bookings", json=payload)
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(try_book, range(6)))

        assert all(s == 201 for s in results), f"Expected all 201, got {results}"


# ---------------------------------------------------------------------------
# Validation edge cases
# ---------------------------------------------------------------------------

class TestValidationEdgeCases:
    def test_missing_required_fields(self, client: TestClient):
        resp = client.post(f"{PREFIX}/bookings", json={})
        assert resp.status_code == 422

    def test_empty_title(self, client: TestClient):
        resp = client.post(f"{PREFIX}/bookings", json={
            "title": "", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        assert resp.status_code == 422

    def test_empty_organiser(self, client: TestClient):
        resp = client.post(f"{PREFIX}/bookings", json={
            "title": "Test", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "", "attendees": [],
        })
        assert resp.status_code == 422

    def test_empty_attendees_is_allowed(self, client: TestClient):
        """An empty attendee list is valid."""
        resp = client.post(f"{PREFIX}/bookings", json={
            "title": "Solo", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        assert resp.status_code == 201

    def test_health_check(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_invalid_booking_id_format(self, client: TestClient):
        """Any ID lookup returns 404 (not 422) for non-existent IDs."""
        resp = client.get(f"{PREFIX}/bookings/not-even-close")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update self-collision
# ---------------------------------------------------------------------------

class TestUpdateSelfCollision:
    def test_update_cannot_create_new_conflict(self, client: TestClient):
        """If two bookings exist, updating one to overlap the other should fail."""
        # Book 10:00-11:00
        b1 = client.post(f"{PREFIX}/bookings", json={
            "title": "First", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        # Book 12:00-13:00
        b2 = client.post(f"{PREFIX}/bookings", json={
            "title": "Second", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "12:00", "end_time": "13:00",
            "organiser": "bob@example.com", "attendees": [],
        })
        # Try to move b2 to overlap b1
        resp = client.put(
            f"{PREFIX}/bookings/{b2.json()['id']}",
            json={"start_time": "10:30"},
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "OVERLAP"

    def test_update_same_time_different_room(self, client: TestClient):
        """Moving a booking to a different room at the same time is fine."""
        b1 = client.post(f"{PREFIX}/bookings", json={
            "title": "Movable", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        resp = client.put(
            f"{PREFIX}/bookings/{b1.json()['id']}",
            json={"room_id": "room-002"},
        )
        assert resp.status_code == 200
        assert resp.json()["room_id"] == "room-002"