# AI Project-Manager Agent

An AI agent that acts as a project manager's force-multiplier: it ingests
project events (transcripts, emails, manual edits) and maintains one
accurate, conflict-aware picture of project state, proposing actions for a
human to approve.

This is a monorepo. Each top-level directory is a separate component with
its own setup/build:

- **`ai-engine/`** -- the horizontal reconciliation engine: event log
  model, deterministic state projection, replay/eval harness. A pure
  library with no I/O/network surface. See
  [`ai-engine/README.md`](ai-engine/README.md).
- **`backend/`** -- API service that wraps `ai-engine` (in-process) and
  owns the event log storage. The only thing other components talk to.
  See [`backend/README.md`](backend/README.md).
- **`cli/`** -- thin client for `backend`'s API; the Phase 1 "surface" for
  feeding in events and inspecting/replaying project state. See
  [`cli/README.md`](cli/README.md).
- **`frontend/`** -- dashboard UI (not yet started; will talk to
  `backend` the same way `cli/` does).

## Phase 1

Phase 1's goal is to validate the AI engine's "memory" -- does it keep an
accurate, conflict-aware project state across a long sequence of events --
before any LLM/extraction work is built. See `ai-engine/README.md` for
details.
