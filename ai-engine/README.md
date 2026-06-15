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

Event types: `transcript_ingested`, `email_reply_received`, `manual_edit`,
`agent_proposal`, `human_approval`. In Phase 1, only `manual_edit` and
`human_approval` events carry deltas that change state -- the other types
are logged for provenance but have no effect on the projection yet (they
become extraction input in a later phase).

## Project layout

```
src/aipm/
  events.py       # Event model, JSONL event log read/append
  entities.py      # Entity + ProvenanceRecord models
  state.py          # ProjectState
  projection.py     # apply_event(), project()
  cli.py            # inspect the projected state of an event log
scenarios/          # replay scenarios (fixed event sequences + checkpoints)
tests/               # unit tests + the replay/eval harness
```

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

## Inspecting state

```
cd ai-engine
python -m aipm.cli path/to/events.jsonl
```

Prints the current projected state as JSON.
