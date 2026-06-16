# CLAUDE.md

AI project-manager agent. Read [`README.md`](README.md) for the product story
and per-component detail. This file is only what an agent needs to work here
safely and fast — it does not repeat the READMEs.

## Mental model (hold this before editing anything)

- **Event-sourced.** The append-only event log (JSONL) is the only source of
  truth. State is *derived*, never stored. `aipm.projection.project()` folds
  the log into a `ProjectState`. It is pure and deterministic — same events in,
  same state out. Don't add side effects or persistence to it.
- **One state-changing event.** `human_approval` is the ONLY event whose
  payload mutates entity/action state. The agent *proposes* (`agent_proposal`);
  a human *approves*; approval applies. `project_initialized` sets project meta.
  Everything else (raw input, outbound events, `proposal_rejected`) is audit
  trail with no projection effect.
- **Approval flows through the channel, not a command.** A human approves by
  replying via email (`email-in`) — the model resolves the reply against
  pending proposals (`aipm.approval`). `aipm approve` is a dev-only fallback.

## Layout (one line each; see each dir's README)

| Dir | What | Rule |
|-----|------|------|
| `ai-engine/` | pure library: event model, projection, extraction *prompt*, review, conflicts, approval | **NO I/O or network.** Deterministic + testable. |
| `backend/`   | FastAPI service: owns storage, calls the LLM providers, the HTTP API | I/O lives here. Concrete providers (Claude/Gemini) live here, not in ai-engine. |
| `cli/`       | thin HTTP client for the backend | rendering only; no business logic. |

## Commands

```bash
# install (each package; backend & cli depend on ai-engine)
pip install -e "ai-engine/.[dev]" && pip install -e "backend/.[dev]" && pip install -e "cli/.[dev]"

# tests — run PER PACKAGE (see gotcha below), from inside each dir
cd ai-engine && pytest -q
cd backend  && pytest -q

# run the backend
uvicorn aipm_backend.main:app --reload      # needs an API key for live extraction

# drive it
aipm init "Project" --start 2026-06-01 --end 2026-11-28 --team alice bob
aipm transcript "..."   # or: note / email-in --from x@y.com
aipm state | events | proposals | review
```

## Conventions

- Match the surrounding style: dense, purposeful comments that explain *why*,
  module docstrings that state the contract. Mirror existing naming.
- Provider seam: anything that calls a model implements `ExtractionProvider`
  (`extract`, `resolve_approvals`) and lives in `backend/extraction.py`.
- New behavior ships with tests in the owning package.

## Env vars (defaults are sane; all optional)

| Var | Default | Purpose |
|-----|---------|---------|
| `AIPM_EVENT_LOG` | `events.jsonl` | event log path |
| `AIPM_EXTRACTION_PROVIDER` | cheapest (`gemini`) | `claude` or `gemini` |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | — | provider keys |
| `AIPM_AUTO_EXTRACT` | `1` | extract inline when a raw event lands |
| `AIPM_EMAIL_APPROVAL` | `1` | let an email reply approve pending proposals |

## Gotchas

- **Tests collide across packages.** `ai-engine` and `backend` both have a
  `tests/test_extraction.py`; a single root `pytest` errors on import-file
  mismatch. Run pytest from inside each package.
- **Never commit secrets.** API keys go in the environment only — never in a
  tracked file.
- **Known limitation:** deterministic checks (review, conflicts) look for
  canonical field names (`due_date`, `status`, `owner`, `severity`), but the
  LLM picks field names freely (e.g. `date`). Constrain the extraction
  vocabulary before relying on those safety-net rules.
