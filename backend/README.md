# Backend

A thin API service that wraps `ai-engine` and owns the event log storage.
This is the only thing `cli/` (and later `frontend/`) talk to.

## Endpoints

- `POST /events` -- append a new event. The event is projected against the
  current state first; if it would produce an invalid delta (e.g. update
  to a non-existent entity), it's rejected with `400` and never written to
  the log.
- `GET /events` -- the full event log, in order.
- `GET /state` -- the current projected project state: one table per
  entity type (each entity with its current `fields` and `history`), plus
  an `actions` list of approved actions (`{type, category, payload,
  source_event_id, asserted_by, asserted_at, source_span}`).

Only `human_approval` events carry a payload that affects `/state` --
`deltas` (entity creates/updates) and `actions` (proposed
`info_request`/`consequential` actions). Other event types
(`transcript_ingested`, `email_reply_received`, `manual_edit`,
`agent_proposal`) are stored as-is but have no effect on the projection.

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
