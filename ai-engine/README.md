# AI Engine

The horizontal reconciliation engine: event log, deterministic state
projection, and the replay/eval harness. See the root [README](../README.md)
for how this fits into the rest of the project.

Phase 1 validates this engine's "memory": does it keep an accurate,
conflict-aware picture of a project across a long sequence of events?
This component currently implements the foundation that makes that
question testable -- no LLM yet.

## Architecture spine

- **Event log** -- the append-only source of truth. Every event log is a
  JSONL file (one JSON object per line). Events are never edited or
  removed.
- **Projection** -- `aipm.projection.project()` is a pure, deterministic
  function: `events -> ProjectState`. The current project state can always
  be re-derived from the event log.
- **Entities** -- Decisions, Tasks, Owners, Deadlines, Risks, Dependencies
  and OpenQuestions. Each entity has a set of current fields plus a
  `history` of provenance records (who said what, when, citing which
  source).

Event types:

- `transcript_ingested`, `email_reply_received`, `manual_note` -- raw
  input: a meeting transcript, an email reply, or a note typed directly
  into the platform by a participant. All three are extraction input for
  a later phase; none of them carry deltas and none affect state.
- `agent_proposal` -- an LLM-proposed set of deltas/actions, awaiting human
  review. Logged for provenance; has no effect on the projection.
- `human_approval` -- the **only** event type whose payload changes state.
  This is the single gate where proposed facts/actions become fact: the
  agent never mutates state directly, only an approved `human_approval`
  event does.
- `email_sent`, `reminder_sent`, `ticket_opened`, `flag_raised`,
  `report_to_management` -- outbound events: a record of the agent acting
  on the world. Execution is a stub in Phase 1, so these just log what
  would be sent/opened/raised, with no effect on the projection. See the
  auto vs. gated split below.

A `human_approval` payload has two parts, both optional:

- `deltas: []` -- `create`/`update` operations against entity tables, each
  `{op, entity_type, entity_id, fields, provenance}`.
- `actions: []` -- approved `consequential` actions, each `{type, category,
  payload, provenance}` (`type` one of `open_ticket`, `raise_flag`,
  `escalate_to_management`). Recorded in `ProjectState.actions` for an
  audit trail, and -- in the backend -- executed (stub) and logged as a
  `ticket_opened`/`flag_raised`/`report_to_management` event.

`info_request` actions (`send_email`, `send_reminder`) never go through
`human_approval`: the agent sends these routine info-gathering messages on
its own as soon as they're proposed, logging an `email_sent`/
`reminder_sent` event immediately. `aipm.entities.outbound_event_type()`
maps an action's `type` to its outbound event type; this routing (and the
auto vs. gated split) is applied by the backend's `/extract` and
`/proposals/{id}/approve` endpoints -- see `backend/README.md`.

## Extraction core (Step 3)

The first place the LLM enters. This package holds only the **pure,
deterministic** parts of extraction -- no network, no model calls. Concrete
providers (Gemini, Claude) that actually call a model live in `backend/`,
keeping this library's "no network surface" contract intact.

- **types** -- `ProposedDelta`, `ProposedAction`, `ExtractionResult`. What a
  provider proposes from a raw event. `to_payload()` renders a result into
  the exact `{deltas, actions}` event-payload shape the projection expects,
  so an approved proposal applies with no translation.
- **prompt** -- builds the prompt in two parts: a stable, cacheable **prefix**
  (instructions + output schema + vocabulary) and a per-call **suffix**
  (current-state summary + raw event text). Provider-agnostic; each provider
  decides how to cache the prefix.
- **grounding** -- the safety net. Every proposal must cite a verbatim
  `source_span` from the raw text; `check_grounding()` / `filter_grounded()`
  verify that in plain Python (no model) and drop anything ungrounded. This is
  what stops the model from inventing facts.
- **providers** -- the `ExtractionProvider` protocol plus the routing seam: a
  `CATALOG` of provider descriptors and a pure `select_provider()` policy
  ("which provider should the agent use?"). Today it's "cheapest available";
  a future agent can make it smarter without touching network code.

## Project layout

```
src/aipm/
  events.py       # Event model, JSONL event log read/append
  entities.py      # Entity, ProvenanceRecord, Action models
  state.py          # ProjectState (entity tables + actions)
  projection.py     # apply_event(), project()
  extraction/       # pure extraction core: types, prompt, grounding, providers
scenarios/          # replay scenarios (fixed event sequences + checkpoints)
tests/               # unit tests + the replay/eval harness
```

This is a pure library with no I/O beyond reading/writing JSONL event
logs, and no network surface. `backend/` depends on it directly (in
process) and exposes it over HTTP.

## Running the tests

```
cd ai-engine
pip install -e ".[dev]"
pytest
```

The eval harness (`tests/test_replay.py`) replays each scenario in
`scenarios/` and, at each checkpoint, asserts that the projected state
matches the expected values. This is the validation harness referenced in
the project goal -- later phases swap the hand-written deltas for
AI-generated ones and run the same scenarios.
