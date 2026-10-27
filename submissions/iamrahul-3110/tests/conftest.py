"""Pytest fixtures and shared utilities for the booking engine test suite."""

import json
import os
import tempfile
from datetime import date, time
from typing import List

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_booking_service
from app.models.booking import (
    BookingCreate,
    BookingRecurring,
    BookingUpdate,
    FindSlotRequest,
)
from app.services.booking_service import BookingService
from app.storage.repository import Repository, set_repository


# ---------------------------------------------------------------------------
# Seed data helper
# ---------------------------------------------------------------------------

@pytest.fixture
def seed_rooms_json() -> str:
    """Return a temp path containing the standard room seed data."""
    rooms = [
        {"id": "room-001", "name": "Alpha", "capacity": 10, "floor": 1,
         "amenities": ["projector"], "description": "Room Alpha"},
        {"id": "room-002", "name": "Beta", "capacity": 4, "floor": 1,
         "amenities": [], "description": "Room Beta"},
        {"id": "room-003", "name": "Gamma", "capacity": 20, "floor": 2,
         "amenities": ["whiteboard"], "description": "Room Gamma"},
    ]
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(rooms, fh)
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# Repository fixture — isolated per test
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(seed_rooms_json: str) -> Repository:
    """Provide a fresh Repository instance for every test."""
    r = Repository(seed_path=seed_rooms_json)
    set_repository(r)
    return r


# ---------------------------------------------------------------------------
# FastAPI TestClient with dependency override
# ---------------------------------------------------------------------------

@pytest.fixture
def client(repo: Repository) -> TestClient:
    """Return a TestClient with the isolated repository injected."""
    set_repository(repo)

    # Override the dependency so every request uses our test service
    def _override() -> BookingService:
        return BookingService(repo)

    app.dependency_overrides[get_booking_service] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------

SAMPLE_DATE = date(2026, 11, 1)  # Sunday
SAMPLE_DATE_2 = date(2026, 11, 2)


def make_booking_create(
    title: str = "Standup",
    room_id: str = "room-001",
    date_val: date = SAMPLE_DATE,
    start: time = time(10, 0),
    end: time = time(11, 0),
    organiser: str = "alice@example.com",
    attendees: List[str] | None = None,
) -> BookingCreate:
    return BookingCreate(
        title=title,
        room_id=room_id,
        date=date_val,
        start_time=start,
        end_time=end,
        organiser=organiser,
        attendees=attendees or ["bob@example.com"],
    )


def make_booking_update(
    title: str | None = None,
    room_id: str | None = None,
    date_val: date | None = None,
    start: time | None = None,
    end: time | None = None,
    organiser: str | None = None,
    attendees: List[str] | None = None,
) -> BookingUpdate:
    return BookingUpdate(
        title=title,
        room_id=room_id,
        date=date_val,
        start_time=start,
        end_time=end,
        organiser=organiser,
        attendees=attendees,
    )


def make_find_slot_request(
    date_val: date = SAMPLE_DATE,
    duration: int = 60,
    attendees: int = 3,
) -> FindSlotRequest:
    return FindSlotRequest(
        date=date_val,
        duration_minutes=duration,
        attendee_count=attendees,
    )


def make_recurring(
    title: str = "Weekly Sync",
    room_id: str = "room-001",
    start_date: date = SAMPLE_DATE,
    start: time = time(14, 0),
    end: time = time(15, 0),
    organiser: str = "eve@example.com",
    attendees: List[str] | None = None,
    weeks: int = 4,
) -> BookingRecurring:
    return BookingRecurring(
        title=title,
        room_id=room_id,
        start_date=start_date,
        start_time=start,
        end_time=end,
        organiser=organiser,
        attendees=attendees or ["frank@example.com"],
        recurrence_weeks=weeks,
    )