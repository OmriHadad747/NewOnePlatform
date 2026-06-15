# Backend

A thin API service that wraps `ai-engine` and owns the event log storage.
This is the only thing `cli/` (and later `frontend/`) talk to.

## Endpoints

- `POST /events` -- append a new event. The event is projected against the
  current state first; if it would produce an invalid delta (e.g. update
  to a non-existent entity), it's rejected with `400` and never written to
  the log.
- `GET /events` -- the full event log, in order.
- `GET /state` -- the current projected project state (one table per
  entity type, each entity with its current `fields` and `history`).

## Storage

Events are stored as a JSONL file. Path defaults to `data/events.jsonl`
(relative to where the server runs), overridable via `AIPM_EVENT_LOG`.

## Running

```
cd backend
pip install -e ../ai-engine
pip install -e ".[dev]"
uvicorn aipm_backend.main:app --reload
```

## Running the tests

```
cd backend
pip install -e ../ai-engine
pip install -e ".[dev]"
pytest
```
