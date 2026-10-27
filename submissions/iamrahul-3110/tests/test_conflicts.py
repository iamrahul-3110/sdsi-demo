"""
M2 — Overlap detection & back-to-back booking tests.

Core logic:  S1 < E2 AND E1 > S2  → conflict
Back-to-back: E1 == S2 or E2 == S1 → allowed (no conflict)
"""

from datetime import date, time

from fastapi.testclient import TestClient

from app.config import API_PREFIX

PREFIX = API_PREFIX


class TestOverlapDetection:
    """Verify the overlap algorithm rejects overlapping bookings."""

    def _book(self, client: TestClient, title: str, room: str, d: str,
              start: str, end: str, **kwargs) -> dict:
        payload = {
            "title": title,
            "room_id": room,
            "date": d,
            "start_time": start,
            "end_time": end,
            "organiser": kwargs.get("organiser", "alice@example.com"),
            "attendees": kwargs.get("attendees", []),
        }
        return client.post(f"{PREFIX}/bookings", json=payload)

    # ---- Overlap cases ----

    def test_exact_overlap_rejected(self, client: TestClient):
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "11:00")
        resp = self._book(client, "B2", "room-001", "2026-11-01", "10:00", "11:00")
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "OVERLAP"

    def test_partial_overlap_start_inside(self, client: TestClient):
        """Existing 10:00-12:00, new 11:00-13:00 — should conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "12:00")
        resp = self._book(client, "B2", "room-001", "2026-11-01", "11:00", "13:00")
        assert resp.status_code == 409

    def test_partial_overlap_end_inside(self, client: TestClient):
        """Existing 10:00-12:00, new 09:00-10:30 — should conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "12:00")
        resp = self._book(client, "B2", "room-001", "2026-11-01", "09:00", "10:30")
        assert resp.status_code == 409

    def test_containment_new_inside_existing(self, client: TestClient):
        """Existing 09:00-17:00, new 10:00-11:00 — should conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "09:00", "17:00")
        resp = self._book(client, "B2", "room-001", "2026-11-01", "10:00", "11:00")
        assert resp.status_code == 409

    def test_containment_existing_inside_new(self, client: TestClient):
        """Existing 10:00-11:00, new 09:00-12:00 — should conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "11:00")
        resp = self._book(client, "B2", "room-001", "2026-11-01", "09:00", "12:00")
        assert resp.status_code == 409

    def test_different_room_no_conflict(self, client: TestClient):
        """Same time, different room — no conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "11:00")
        resp = self._book(client, "B2", "room-002", "2026-11-01", "10:00", "11:00")
        assert resp.status_code == 201

    def test_different_date_no_conflict(self, client: TestClient):
        """Same room+time, different date — no conflict."""
        self._book(client, "B1", "room-001", "2026-11-01", "10:00", "11:00")
        resp = self._book(client, "B2", "room-001", "2026-11-02", "10:00", "11:00")
        assert resp.status_code == 201


class TestBackToBack:
    """Back-to-back bookings (E1 == S2) are allowed."""

    def _book(self, client, title, room, d, start, end):
        return client.post(f"{PREFIX}/bookings", json={
            "title": title, "room_id": room, "date": d,
            "start_time": start, "end_time": end,
            "organiser": "alice@example.com", "attendees": [],
        })

    def test_back_to_back_after(self, client: TestClient):
        """10:00-11:00 then 11:00-12:00 — allowed."""
        r1 = self._book(client, "B1", "room-001", "2026-11-01", "10:00", "11:00")
        assert r1.status_code == 201
        r2 = self._book(client, "B2", "room-001", "2026-11-01", "11:00", "12:00")
        assert r2.status_code == 201

    def test_back_to_back_before(self, client: TestClient):
        """11:00-12:00 exists, then 10:00-11:00 — allowed."""
        r1 = self._book(client, "B1", "room-001", "2026-11-01", "11:00", "12:00")
        assert r1.status_code == 201
        r2 = self._book(client, "B2", "room-001", "2026-11-01", "10:00", "11:00")
        assert r2.status_code == 201

    def test_one_minute_gap_no_conflict(self, client: TestClient):
        """10:00-10:59 then 11:00-12:00 — no overlap, allowed."""
        r1 = self._book(client, "B1", "room-001", "2026-11-01", "10:00", "10:59")
        assert r1.status_code == 201
        r2 = self._book(client, "B2", "room-001", "2026-11-01", "11:00", "12:00")
        assert r2.status_code == 201