# AI Project-Manager Agent

An AI agent that acts as a project manager's force-multiplier: it ingests
project events (transcripts, emails, manual notes) and maintains one
accurate, conflict-aware picture of project state. It never mutates that
state directly -- it proposes changes and actions, and only a human
approval applies them.

This is a monorepo. Each component lives in its own top-level directory
with its own setup/build:

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
- **`frontend/`** -- dashboard UI (planned, no directory yet; will talk to
  `backend` the same way `cli/` does).

## Phase 1

Phase 1 first validates the AI engine's "memory" -- does it keep an
accurate, conflict-aware project state across a long sequence of events --
using a deterministic event log, projection, and replay/eval harness (no
LLM). On that foundation it then layers **extraction** (Step 3): an LLM
reads a raw event plus the current state and *proposes* grounded
deltas/actions, which become an `agent_proposal` and only change state once
a human approves. See `ai-engine/README.md` and `backend/README.md` for
details.
