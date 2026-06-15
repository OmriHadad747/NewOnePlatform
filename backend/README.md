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
`deltas` (entity creates/updates) and `actions` (`consequential` actions
that were approved). Other event types (`transcript_ingested`,
`email_reply_received`, `manual_note`, `agent_proposal`, and the outbound
types `email_sent`, `reminder_sent`, `ticket_opened`, `flag_raised`,
`report_to_management`) are stored as-is but have no effect on the
projection.

## Extraction / approval flow (Step 3)

The LLM proposes; only a human approval applies. The flow never lets the
model mutate state directly:

- `POST /extract` -- body `{"source_event_id": "<id>"}`. Runs the configured
  provider over a raw-input event's text plus the current state, and drops
  any proposal whose `source_span` isn't grounded in the raw text. Any
  `info_request` actions (routine info-gathering, e.g. `send_email`,
  `send_reminder`) execute immediately (stub) and are logged as
  `email_sent`/`reminder_sent` events -- **no approval needed**. The
  remaining `deltas` and `consequential` actions become a single
  `agent_proposal` event (**no state change**), or no proposal at all if
  nothing is left. Returns `{"proposal": ... | null, "dropped": [...],
  "executed": [...]}` -- the proposal (if any), the dropped (ungrounded)
  items, and the outbound events written for auto-executed actions.
- `GET /proposals` -- the `agent_proposal` events that have no matching
  approval yet.
- `POST /proposals/{id}/approve` -- writes a `human_approval` event carrying
  the proposal's `deltas`/`actions` (and `approves: <id>`). This is validated
  against current state and then applied -- the one place text becomes fact.
  Each approved (`consequential`) action then executes (stub) and is logged
  as a `ticket_opened`/`flag_raised`/`report_to_management` event.

The pure parts of extraction (prompt, schema, span-grounding, provider
protocol, routing policy, action-to-outbound-event mapping) live in
`ai-engine`; the backend only adds the concrete network providers and these
endpoints.

## Configuration (extraction)

Two providers ship today, both behind the same `ExtractionProvider` contract:

- **`claude`** -- Anthropic Claude (default model `claude-haiku-4-5`). Needs
  `ANTHROPIC_API_KEY`; override the model with `AIPM_CLAUDE_MODEL`.
- **`gemini`** -- Google Gemini (default model `gemini-2.5-flash`). Needs
  `GEMINI_API_KEY` (or `GOOGLE_API_KEY`); override with `AIPM_GEMINI_MODEL`.

`AIPM_EXTRACTION_PROVIDER` chooses which one `/extract` uses; it defaults to
the cheapest in the catalog (`gemini`). Set it to `claude` to extract via
Claude Haiku. Each provider sends the stable prompt prefix in its own cache
channel (Claude: a `cache_control` system block; Gemini: implicit prefix
caching) so the instructions are billed once.

Copy `.env.example` to `.env` (loaded automatically if `python-dotenv` is
installed) and fill in the key for whichever provider you're using.

Tests never hit the network: they inject a `StaticProvider` via FastAPI's
dependency override, so the extract/approve flow is covered deterministically,
and the provider layer's own logic (JSON parsing, provider selection) is
unit-tested without a model call.

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
