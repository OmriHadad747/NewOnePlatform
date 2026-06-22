---
name: run-aipm
description: Operate this repo's AI project-manager platform, one step at a time.
  Start a project (from a frozen baseline, or from scratch by extracting a kickoff),
  feed in work (transcripts/notes/messages), then PAUSE and ask the operator which
  branch to take at each decision (approve / reject-with-reason / ask a question /
  revise / defer). Use when asked to run, drive, demo, or simulate the AIPM platform.
---

# Drive the AIPM platform — one step at a time

Event-sourced PM agent: the append-only event log IS the state. You feed in raw
work; the agent extracts facts, proposes changes, and messages people for sign-off.

**This is the whole point: operate it collaboratively.** After every platform
action, STOP and ask the operator which branch to take next — use AskUserQuestion,
and ALWAYS allow a free typed answer. Never auto-advance through an approval,
rejection, or revision. You drive the tool; the operator makes every call.

## Setup (once)
```bash
pip install -e "ai-engine/.[dev]" && pip install -e "backend/.[dev]" && pip install -e "cli/.[dev]"
export AIPM_EVENT_LOG=./project.jsonl     # the project's state lives here
export ANTHROPIC_API_KEY=...              # extraction needs a provider key
export AIPM_EXTRACTION_PROVIDER=claude     # omit for the cheaper gemini default
export AIPM_MODEL_MESSAGES=1               # let the platform answer a recipient's question in-thread
uvicorn aipm_backend.main:app             # backend on :8000, leave running
```

## Choose your start
**A — Frozen baseline (deterministic, no model call).** A known, complication-rich
graph; best for testing a specific situation fast.
```bash
cp .claude/skills/run-aipm/baseline.jsonl "$AIPM_EVENT_LOG"
aipm state    # sanity: 8 tasks, 8 dependencies, 6 risks
```

**B — From scratch / full simulation (the model extracts the graph).** Feed raw
kickoff material and let the platform build the project, then approve it interactively.
```bash
aipm init "Score model replacement" --start 2026-04-01 --end 2026-12-31 \
  --team data-scientist analytics-engineer data-engineer backend-engineer legacy-owner \
  --pm you@co.com
aipm transcript "$(cat .claude/skills/run-aipm/examples/score-kickoff.md)"
aipm proposals          # review the extracted owners/tasks/risks/deps, then approve
```
Refine iteratively — add detail as you learn it: `aipm note "..."`. Swap the
kickoff file for your own work material to simulate a real project.

## The loop
1. **Ingest ONE piece of work:** `aipm transcript "<meeting>"` · `aipm note "<text>"` ·
   `aipm message-in "<email/Slack>" --from x@co.com`. Then show the operator what the
   platform did (proposed changes, conflicts, clarifications it sent) and ASK what's next.
2. **A proposal is pending → ask, never assume.** The platform messaged someone for
   sign-off (`aipm --json proposals` → `payload.to`, `payload.thread_id`). Ask the
   operator how that person responds; offer the branches (operator answers in their
   OWN words — there are no magic phrases, the model resolves intent):
   - **Approve** · **Reject (with a reason)** · **Ask a question first** (the platform
     answers in-thread, then they decide) · **Propose a different structure** (agent
     drafts a revision for the PM) · **Leave it for now**

   Deliver their words AS that person, verbatim:
   ```bash
   aipm message-in "<operator's exact words>" --from <that-person> --thread <thread>
   ```
3. **The platform may ask THEM something back** — on an ambiguous reply, or before
   committing a contradictory state (e.g. a task done while it keeps an active
   dependency), it sends a question. Surface it and ask the operator how to answer.

## Inspect anytime
`aipm state` · `aipm proposals` · `aipm events`

## Gotchas
- Approval is ONLY a reply on the thread — there is no approve command/endpoint.
- Extraction needs a provider key; without one, events log but nothing extracts.
- State is derived from `$AIPM_EVENT_LOG` — point at that file to resume; delete it to reset.
- A reply ON a thread resolves that proposal only; it is never re-mined for new work.
- Depth: `CLAUDE.md`, `backend/README.md`.
