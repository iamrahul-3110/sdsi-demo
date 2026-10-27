# Meeting Room Booking Engine

Production-grade, highly testable room reservation API built with **FastAPI** and **Pydantic v2**.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
uvicorn app.main:app --reload

# 3. Open Swagger UI
# http://localhost:8000/docs
```

### Docker

```bash
docker build -t booking-engine .
docker run -p 8000:8000 booking-engine
```

---

## Architecture

```
app/
├── main.py                  # FastAPI app, routes, exception handlers
├── config.py                # Business constants (hours, error codes)
├── models/
│   ├── booking.py           # Pydantic schemas for all booking operations
│   └── room.py              # Room domain model
├── services/
│   ├── booking_service.py   # M1–M5 business logic orchestrator
│   └── slot_finder.py       # M4 interval search & best-fit heuristic
└── storage/
    ├── repository.py        # Thread-safe in-memory store with RLock
    └── rooms.json           # Conference room seed data (10 rooms)
tests/
├── conftest.py              # Fixtures: isolated repo, TestClient, factories
├── test_crud.py             # M1 — Create, Read, Update, Delete
├── test_conflicts.py        # M2 — Overlap detection & back-to-back
├── test_capacity.py         # M3 — Room listing & capacity validation
├── test_find_slot.py        # M4 — Slot search, best-fit, edge cases
├── test_recurring.py        # M5 — Weekly recurrences, partial conflicts
└── test_edge_cases.py       # Concurrency, time ranges, business hours
```

### Design Decisions

| Concern | Choice | Rationale |
|---|---|---|
| **Framework** | FastAPI + Pydantic v2 | Auto-generated OpenAPI/Swagger docs, fast validation, async-native |
| **Storage** | In-memory with `threading.RLock` | Thread-safe without external DB; pluggable for SQLite later |
| **Conflict formula** | `S1 < E2 AND E1 > S2` | Standard interval overlap; back-to-back allowed when `E1 == S2` |
| **Find-slot tie-breaker** | Best-fit capacity (smallest room first) | Minimises capacity waste; resorts to next room when full |
| **Recurring strategy** | Independent per-occurrence evaluation | Not all-or-nothing — partial conflicts reported alongside successes |
| **Error responses** | `{ detail, error_code }` JSON | Machine-readable error codes for client handling |

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

### Rooms (M3)

| Method | Path | Description |
|---|---|---|
| `GET` | `/rooms` | List all rooms |
| `GET` | `/rooms/{room_id}` | Get room details |

### Bookings (M1)

| Method | Path | Description |
|---|---|---|
| `POST` | `/bookings` | Create a booking |
| `GET` | `/bookings` | List bookings (`?room_id=`, `?date=`, `?organiser=`) |
| `GET` | `/bookings/{id}` | Get single booking |
| `PUT` | `/bookings/{id}` | Update booking (partial) |
| `DELETE` | `/bookings/{id}` | Cancel booking |

### Find Slot (M4)

| Method | Path | Description |
|---|---|---|
| `POST` | `/bookings/find-slot` | Find earliest available time slot |

### Recurring (M5)

| Method | Path | Description |
|---|---|---|
| `POST` | `/bookings/recurring` | Create weekly recurring bookings |

---

## Example Requests

### Create a Booking

```bash
curl -X POST http://localhost:8000/api/v1/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Sprint Planning",
    "room_id": "room-001",
    "date": "2026-11-01",
    "start_time": "10:00",
    "end_time": "11:00",
    "organiser": "alice@example.com",
    "attendees": ["bob@example.com", "carol@example.com"]
  }'
```

Response (201):
```json
{
  "id": "b-a1b2c3d4e5f6",
  "title": "Sprint Planning",
  "room_id": "room-001",
  "date": "2026-11-01",
  "start_time": "10:00",
  "end_time": "11:00",
  "organiser": "alice@example.com",
  "attendees": ["bob@example.com", "carol@example.com"],
  "created_at": "2026-10-27T12:00:00Z",
  "updated_at": "2026-10-27T12:00:00Z"
}
```

### Find a Slot

```bash
curl -X POST http://localhost:8000/api/v1/bookings/find-slot \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-11-01",
    "duration_minutes": 60,
    "attendee_count": 5
  }'
```

Response (200):
```json
{
  "date": "2026-11-01",
  "start_time": "09:00",
  "end_time": "10:00",
  "duration_minutes": 60,
  "room": {
    "id": "room-001",
    "name": "Alpha",
    "capacity": 10
  }
}
```

### Recurring Booking

```bash
curl -X POST http://localhost:8000/api/v1/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Weekly Sync",
    "room_id": "room-001",
    "start_date": "2026-11-01",
    "start_time": "14:00",
    "end_time": "15:00",
    "organiser": "eve@example.com",
    "attendees": ["frank@example.com"],
    "recurrence_weeks": 4
  }'
```

Response (201):
```json
{
  "successful_bookings": [
    { "id": "b-...", "date": "2026-11-01", ... },
    { "id": "b-...", "date": "2026-11-08", ... },
    { "id": "b-...", "date": "2026-11-15", ... },
    { "id": "b-...", "date": "2026-11-22", ... }
  ],
  "conflicts": []
}
```

---

## Error Response Format

All errors follow:
```json
{
  "detail": "Human-readable description",
  "error_code": "MACHINE_READABLE_CODE"
}
```

| Code | HTTP Status | Meaning |
|---|---|---|
| `ROOM_NOT_FOUND` | 404 | Room ID does not exist |
| `BOOKING_NOT_FOUND` | 404 | Booking ID does not exist |
| `OVERLAP` | 409 | Time slot conflicts with existing booking |
| `CAPACITY_EXCEEDED` | 422 | Attendees exceed room capacity |
| `INVALID_TIME_RANGE` | 422 | start_time >= end_time |
| `OUTSIDE_BUSINESS_HOURS` | 422 | Outside 09:00–18:00 window |
| `NO_SLOT_AVAILABLE` | 404 | No room+time fits the request |

---

## Testing

```bash
# Run all tests with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run a specific milestone
pytest tests/test_crud.py -v
pytest tests/test_conflicts.py -v
pytest tests/test_capacity.py -v
pytest tests/test_find_slot.py -v
pytest tests/test_recurring.py -v
pytest tests/test_edge_cases.py -v
```

### Test Coverage Summary

| Module | Tests | Coverage |
|---|---|---|
| M1 — CRUD | Create, list, get, update, delete, filters | ✓ |
| M2 — Overlap | 5 overlap patterns, 2 non-conflict, 3 back-to-back | ✓ |
| M3 — Capacity | Room listing, capacity limits, dedup-aware | ✓ |
| M4 — Find Slot | Basic, best-fit, full day, no slot, edge boundaries | ✓ |
| M5 — Recurring | All success, partial conflict, all conflict, validation | ✓ |
| Edge Cases | Concurrency, time ranges, business hours, self-collision | ✓ |

---

## Constraints & Business Rules

- **Business hours**: 09:00 – 18:00 (configurable in `app/config.py`)
- **Max meeting duration**: 540 minutes (9 hours)
- **Max recurrence**: 12 weeks
- **Back-to-back**: Allowed (bookings that touch at the boundary are not conflicts)
- **Capacity**: Enforced post deduplication of attendee emails
- **Thread safety**: All mutations go through `Repository` which uses `threading.RLock`