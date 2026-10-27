"""
M1 — CRUD API tests.

Covers:
- Create booking (POST /api/v1/bookings)
- List bookings with filters (GET /api/v1/bookings)
- Get single booking (GET /api/v1/bookings/{id})
- Update booking (PUT /api/v1/bookings/{id})
- Delete booking (DELETE /api/v1/bookings/{id})
"""

from datetime import date, time

from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX


class TestCreateBooking:
    """POST /api/v1/bookings — Create booking endpoint."""

    def test_create_valid_booking(self, client: TestClient):
        payload = {
            "title": "Team Standup",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": ["bob@example.com", "carol@example.com"],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == payload["title"]
        assert data["room_id"] == "room-001"
        assert data["id"].startswith("b-")
        assert "created_at" in data

    def test_create_booking_deduplicates_attendees(self, client: TestClient):
        payload = {
            "title": "Dedup Test",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "organiser": "alice@example.com",
            "attendees": [
                "BOB@example.com",
                "bob@example.com",
                "  carol@example.com ",
            ],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["attendees"]) == 2
        assert "bob@example.com" in data["attendees"]
        assert "carol@example.com" in data["attendees"]

    def test_create_booking_nonexistent_room(self, client: TestClient):
        payload = {
            "title": "Ghost Room",
            "room_id": "room-999",
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": [],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "ROOM_NOT_FOUND"


class TestListBookings:
    """GET /api/v1/bookings — List & filter bookings."""

    def test_list_empty(self, client: TestClient):
        resp = client.get(f"{PREFIX}/bookings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bookings"] == []
        assert data["count"] == 0

    def test_list_all(self, client: TestClient):
        # Create two bookings
        for i in range(2):
            client.post(f"{PREFIX}/bookings", json={
                "title": f"Meeting {i}",
                "room_id": "room-001",
                "date": f"2026-11-0{i+1}",
                "start_time": "10:00",
                "end_time": "11:00",
                "organiser": "alice@example.com",
                "attendees": [],
            })
        resp = client.get(f"{PREFIX}/bookings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_filter_by_room_id(self, client: TestClient):
        client.post(f"{PREFIX}/bookings", json={
            "title": "Room 1", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        client.post(f"{PREFIX}/bookings", json={
            "title": "Room 2", "room_id": "room-002",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        resp = client.get(f"{PREFIX}/bookings?room_id=room-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["bookings"][0]["room_id"] == "room-001"

    def test_filter_by_date(self, client: TestClient):
        client.post(f"{PREFIX}/bookings", json={
            "title": "Nov 1", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        client.post(f"{PREFIX}/bookings", json={
            "title": "Nov 2", "room_id": "room-001",
            "date": "2026-11-02", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        resp = client.get(f"{PREFIX}/bookings?date=2026-11-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_filter_by_organiser(self, client: TestClient):
        client.post(f"{PREFIX}/bookings", json={
            "title": "A", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        client.post(f"{PREFIX}/bookings", json={
            "title": "B", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "12:00", "end_time": "13:00",
            "organiser": "bob@example.com", "attendees": [],
        })
        resp = client.get(f"{PREFIX}/bookings?organiser=alice@example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["bookings"][0]["organiser"] == "alice@example.com"


class TestGetBooking:
    """GET /api/v1/bookings/{id} — Retrieve single booking."""

    def test_get_existing(self, client: TestClient):
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Get Me", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        bid = created.json()["id"]
        resp = client.get(f"{PREFIX}/bookings/{bid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == bid

    def test_get_nonexistent(self, client: TestClient):
        resp = client.get(f"{PREFIX}/bookings/b-deadbeef1234")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "BOOKING_NOT_FOUND"


class TestUpdateBooking:
    """PUT /api/v1/bookings/{id} — Update booking."""

    def test_update_title(self, client: TestClient):
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Old Title", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        bid = created.json()["id"]
        resp = client.put(f"{PREFIX}/bookings/{bid}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_update_self_no_conflict(self, client: TestClient):
        """Updating your own booking should not conflict with itself."""
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Self", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        bid = created.json()["id"]
        # Change end_time without changing room/date/start — should succeed
        resp = client.put(f"{PREFIX}/bookings/{bid}", json={"end_time": "11:30"})
        assert resp.status_code == 200
        assert resp.json()["end_time"] == "11:30"

    def test_update_nonexistent(self, client: TestClient):
        resp = client.put(f"{PREFIX}/bookings/b-deadbeef1234", json={"title": "Nope"})
        assert resp.status_code == 404

    def test_update_invalid_time_range(self, client: TestClient):
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Time Test", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        bid = created.json()["id"]
        resp = client.put(f"{PREFIX}/bookings/{bid}", json={
            "start_time": "12:00", "end_time": "11:00",
        })
        assert resp.status_code == 422


class TestDeleteBooking:
    """DELETE /api/v1/bookings/{id} — Cancel booking."""

    def test_delete_existing(self, client: TestClient):
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Delete Me", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com", "attendees": [],
        })
        bid = created.json()["id"]
        resp = client.delete(f"{PREFIX}/bookings/{bid}")
        assert resp.status_code == 204
        # Verify it's gone
        resp = client.get(f"{PREFIX}/bookings/{bid}")
        assert resp.status_code == 404

    def test_delete_nonexistent(self, client: TestClient):
        resp = client.delete(f"{PREFIX}/bookings/b-deadbeef1234")
        assert resp.status_code == 404