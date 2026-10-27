# AI Collaboration Log — Meeting Room Booking Engine

## Project Context

**Problem Statement**: PS2 — Build a production-grade Meeting Room Booking Engine.

**Stack**: FastAPI, Pydantic v2, in-memory thread-safe storage, pytest.

---

## Prompt Iterations

### Iteration 1 — Scaffold & Foundation

**Prompt**: "Build the complete project structure: FastAPI app, models, services, storage, tests, Dockerfile, README."

**AI Decisions**:
- Used FastAPI's dependency injection pattern (not global state) so each request gets a fresh service instance backed by a shared repository.
- Singleton `Repository` with `threading.RLock()` for thread safety. The `set_repository()` override lets tests inject an isolated instance.
- Pydantic v2 validators (`@field_validator`, `@model_validator`) for deduplication, business hour enforcement, and start-before-end checks.
- `_generate_booking_id()` uses `b-` prefix + 12 hex chars for human-readable IDs.

**Design Choices Made**:
- Conflict formula: strict overlap `S1 < E2 AND E1 > S2` — back-to-back where `E1 == S2` passes.
- Booking IDs are generated server-side (not user-provided) to prevent ID collision.
- Attendees are deduplicated at the Pydantic model level (model_validator) so the business logic always receives clean data.

### Iteration 2 — Service Layer

**Prompt**: "Implement BookingService with CRUD, conflict checking, capacity validation, find-slot delegation, and recurring logic."

**AI Decisions**:
- `BookingService` is stateless — all state lives in `Repository`.
- `BookingError` extends `ValueError` with `detail` and `error_code` fields, caught by a FastAPI exception handler that maps error codes to HTTP status codes.
- `SlotFinder` is a separate service class, not mixed into `BookingService`, to keep the slot-search algorithm independently testable.
- Recurring logic evaluates each week independently — it doesn't abort on first conflict. This matches the spec's requirement for `{ successful_bookings, conflicts }` coexisting.

### Iteration 3 — Routes & Exception Handlers

**Prompt**: "Wire up FastAPI routes for all endpoints with proper status codes, query params, and error handling."

**AI Decisions**:
- Used `API_PREFIX = "/api/v1"` constant so the version prefix is trivially changeable.
- `RequestValidationError` handler extracts the first Pydantic error and maps it to a user-friendly `{ detail, error_code }` format.
- `BookingError` handler maps domain error codes to HTTP status codes (OVERLAP → 409, CAPACITY_EXCEEDED → 422, etc.).
- Filter params (`room_id`, `date`, `organiser`) are optional query params on `GET /api/v1/bookings`.

### Iteration 4 — Test Suite

**Prompt**: "Write comprehensive pytest tests covering all milestones with >95% coverage."

**Test Structure Decisions**:
- `conftest.py` provides an isolated `Repository` per test (via temp JSON seed file) so tests never interfere.
- Factory helpers (`make_booking_create`, `make_recurring`, etc.) keep test code DRY.
- Concurrency test uses `ThreadPoolExecutor` with 8 workers competing for the same slot — exactly 1 must succeed.
- Each milestone has its own test file for clear traceability.

### Iteration 5 — Documentation

**Prompt**: "Write README.md with architecture docs, API reference, curl examples, and PROMPTS.md tracking design decisions."

**AI Decisions**:
- README includes a design-decisions table explaining the "why" behind each architectural choice.
- curl examples for all three core workflows (create, find-slot, recurring).
- Error code reference table for client developers.
- PROMPTS.md tracks the evolution of requirements and prompt engineering for future AI collaboration transparency.

---

## Design Trade-offs Log

| Decision | Alternative Considered | Why Chosen |
|---|---|---|
| In-memory store | SQLite from start | Simpler for evaluation; pluggable architecture makes SQLite trivial to add later |
| `threading.RLock` | `asyncio.Lock` | FastAPI runs sync route handlers in a thread pool; RLock is correct for multi-threaded access |
| Server-generated IDs | Client-provided UUIDs | Prevents ID collisions; simpler conflict-free creation |
| Independent recurrence eval | All-or-nothing transactions | Spec explicitly calls for partial-success reporting |
| Best-fit capacity tie-breaker | First-fit (any room) | Bonus requirement; minimises capacity waste as specified |
| Python 3.10+ | Python 3.8+ | `|` union type syntax, `match`/`case` readiness, Pydantic v2 optimal support |

---

## Running the Project

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# Swagger UI: http://localhost:8000/docs
pytest tests/ -v --cov=app
```

---

*Generated collaboratively with AI assistance for the PS2 Digithon challenge.*