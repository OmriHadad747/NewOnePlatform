# Session primer — where things stand

Read `CLAUDE.md` first for the *working contract* (how to edit safely). This file
is the *current status and direction* — what to know when you pick the project up.

## What this is
An event-sourced AI project-manager agent. Raw work (transcripts / notes /
messages) → the model extracts facts → proposes changes → a human approves **by
replying** → approval applies to state. The append-only event log IS the state;
everything else is derived. Three packages: pure `ai-engine/`, I/O `backend/`,
thin `cli/`. It works end-to-end today against real Claude/Gemini.

## Recently shipped (this line of work)
- **Self-correcting model revisions.** When a reply reveals the *model itself* is
  wrong (a dependency that shouldn't exist), the agent drafts a structural fix
  (incl. a new `delete` delta op) and routes it to the PM. Approving it re-opens
  and corrects previously-approved state.
- **Partial approval (`apply_only`).** A reply can approve a subset ("keep the
  dependency, but it's done").
- **Conflict-acknowledgment gate.** An approval that would commit an inconsistent
  state (e.g. a task done while it keeps an active dependency) is not applied
  silently — the agent asks the approver to accept it knowingly, then records
  `acknowledged_conflicts` on the event.
- **Loop-closing.** Declined revisions notify whoever raised them; a reply on a
  closed thread gets a "send a new note" reminder (bounded).
- **One way to approve.** The `/proposals/{id}/approve` endpoint and `aipm approve`
  are gone — approval is *only* a channel reply.

## How to run / try it
Use the **`run-aipm` skill** (`.claude/skills/run-aipm/`). Two starts:
- **Mode A — baseline:** `cp baseline.jsonl "$AIPM_EVENT_LOG"` → a frozen,
  complication-rich graph, no model call. Good for testing one situation fast.
- **Mode B — from scratch:** feed `examples/score-kickoff.md` and let the model
  extract the whole graph. The full simulation.

Tests run **per package** (they collide at the root): `cd ai-engine && pytest -q`,
then `cd backend && pytest -q`, then `cd cli && pytest -q`. All green today.

## What's next (to actually use it at work, not just more tests)
It's still a "Phase 1 stub": outbound is `[SIMULATED]`, only the `stub` channel
exists, one JSONL = one project, identities are free text. Highest-leverage path,
in order:
1. **A real channel — inbound *and* outbound** behind the `Channel` seam (email or
   Slack). The inbound webhook (reply → `message_received`) is the #1 blocker for
   approvals flowing from real people.
2. **Time-driven follow-ups.** The nudge→escalation ladder only advances when a
   reply arrives; add a scheduler so it fires on elapsed time.
3. **Identity binding.** Tie senders to a verified channel identity; check approval
   authority.

Then (Tier 2): persistence + multi-project (sqlite/postgres, `project_id`); a
read-only PM UI. (Tier 3): more state invariants (dependency cycles), richer
review rules, idempotency on re-ingest, metrics over the existing trace files.
