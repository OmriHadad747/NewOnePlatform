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

## Extraction / approval flow (Step 3)

The LLM proposes; only a human approval applies. The flow never lets the
model mutate state directly:

- `POST /extract` -- body `{"source_event_id": "<id>"}`. Runs the configured
  provider over a raw-input event's text plus the current state, drops any
  proposal whose `source_span` isn't grounded in the raw text, and writes a
  single `agent_proposal` event. **No state change.** Returns the proposal and
  the list of dropped (ungrounded) items.
- `GET /proposals` -- the `agent_proposal` events that have no matching
  approval yet.
- `POST /proposals/{id}/approve` -- writes a `human_approval` event carrying
  the proposal's `deltas`/`actions` (and `approves: <id>`). This is validated
  against current state and then applied -- the one place text becomes fact.

The pure parts of extraction (prompt, schema, span-grounding, provider
protocol, routing policy) live in `ai-engine`; the backend only adds the
concrete network providers and these endpoints.

## Configuration (extraction)

Copy `.env.example` to `.env` (loaded automatically if `python-dotenv` is
installed) and set:

- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) -- required for live extraction.
- `AIPM_GEMINI_MODEL` -- defaults to `gemini-2.5-flash`.
- `AIPM_EXTRACTION_PROVIDER` -- defaults to the cheapest in the catalog
  (`gemini`).

Tests never hit the network: they inject a `StaticProvider` via FastAPI's
dependency override, so the extract/approve flow is covered deterministically.

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
