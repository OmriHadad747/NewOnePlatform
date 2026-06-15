# AI Project-Manager Agent

An AI agent that acts as a project manager's force-multiplier: it ingests
project events (transcripts, emails, manual edits) and maintains one
accurate, conflict-aware picture of project state, proposing actions for a
human to approve.

This is a monorepo. Each top-level directory is a separate component with
its own setup/build:

- **`ai-engine/`** -- the horizontal reconciliation engine (event log,
  deterministic state projection, replay/eval harness). This is where
  Phase 1 lives. See [`ai-engine/README.md`](ai-engine/README.md).
- **`backend/`** -- API/service layer (not yet started).
- **`frontend/`** -- dashboard UI (not yet started).

## Phase 1

Phase 1's goal is to validate the AI engine's "memory" -- does it keep an
accurate, conflict-aware project state across a long sequence of events --
before any LLM/extraction work is built. See `ai-engine/README.md` for
details.
