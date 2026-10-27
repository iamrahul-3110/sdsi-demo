"""
M3 — Room capacity tests.

Covers:
- GET /api/v1/rooms — list rooms
- Capacity validation on create
- Capacity validation on update
"""

from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX


class TestListRooms:
    """GET /api/v1/rooms — Room listing."""

    def test_list_returns_all_rooms(self, client: TestClient):
        resp = client.get(f"{PREFIX}/rooms")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3
        room_ids = {r["id"] for r in data}
        assert room_ids == {"room-001", "room-002", "room-003"}

    def test_get_single_room(self, client: TestClient):
        resp = client.get(f"{PREFIX}/rooms/room-001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "room-001"
        assert resp.json()["capacity"] == 10

    def test_get_nonexistent_room(self, client: TestClient):
        resp = client.get(f"{PREFIX}/rooms/room-999")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "ROOM_NOT_FOUND"


class TestCapacityValidation:
    """Reject bookings where attendee count exceeds room capacity."""

    def test_capacity_exceeded_on_create(self, client: TestClient):
        """room-001 has capacity 10, sending 11 attendees."""
        payload = {
            "title": "Overflow",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": [f"user{i}@example.com" for i in range(11)],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "CAPACITY_EXCEEDED"

    def test_capacity_exactly_at_limit(self, client: TestClient):
        """room-001 capacity 10, exactly 10 attendees — allowed."""
        payload = {
            "title": "Full House",
            "room_id": "room-001",
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": [f"user{i}@example.com" for i in range(10)],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 201

    def test_capacity_exceeded_after_dedup(self, client: TestClient):
        """Duplicate attendees should not circumvent capacity check."""
        payload = {
            "title": "Dedup Sneak",
            "room_id": "room-002",  # capacity 4
            "date": "2026-11-01",
            "start_time": "10:00",
            "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": [
                "a@example.com", "a@example.com", "a@example.com",
                "b@example.com", "b@example.com",
            ],
        }
        resp = client.post(f"{PREFIX}/bookings", json=payload)
        assert resp.status_code == 201
        # Should have only 2 unique attendees
        assert len(resp.json()["attendees"]) == 2

    def test_capacity_exceeded_on_update(self, client: TestClient):
        """Update that increases attendees beyond capacity should fail."""
        created = client.post(f"{PREFIX}/bookings", json={
            "title": "Small", "room_id": "room-001",
            "date": "2026-11-01", "start_time": "10:00", "end_time": "11:00",
            "organiser": "alice@example.com",
            "attendees": ["a@example.com"],
        })
        bid = created.json()["id"]
        resp = client.put(f"{PREFIX}/bookings/{bid}", json={
            "attendees": [f"user{i}@example.com" for i in range(15)],
        })
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "CAPACITY_EXCEEDED"