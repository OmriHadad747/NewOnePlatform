# Frontend

A production-quality web UI for the AI project-manager platform — the
browser surface that sits alongside `cli/`, talking to `backend/`'s HTTP API.
The agent is presented as a named teammate, **Shlomi**.

It is a thin rendering layer (like the CLI): no business logic lives here. All
truth comes from the backend, which derives state from the append-only event
log. Approval still happens the one true way — a **reply on a thread**, never a
command.

## Design language

Warm and approachable: a cream/amber palette with teal/green/red/violet status
accents, rounded cards, friendly copy. Every colour is a **semantic token**
(`--surface`, `--ink`, `--accent`, `--green-soft`, …) defined once in
`src/index.css` for both **light and dark**, so the two themes stay in lockstep
and the whole app shares one palette, one set of status colours, one shadow
scale. Theme is class-driven (`.dark` on `<html>`) with a pre-paint script so
there's no flash on load.

## Roles (no login)

A persona switcher (top-right) puts on any hat instantly — ideal for demoing:

| Role | Route | What it's for |
|------|-------|---------------|
| **Team member** | `/worker` | My tasks + what Shlomi needs me to answer; reply inline |
| **Manager** | `/manager` | The approvals inbox — review/approve/decline what Shlomi proposes |
| **Executive** | `/exec` | Health at a glance + **Ask Shlomi** (free-language Q&A) |
| **Demo console** | `/demo` | God mode: init a project, feed work as anyone, reply as anyone, watch it react live |

Shared read surfaces: **Tasks & risks** (`/board`, with an entity drawer that
shows each fact's provenance — "how Shlomi knows this"), **Timeline**
(`/timeline`, the event log), **Threads** (`/threads`, conversations).

## Stack

React 19 · Vite · TypeScript · Tailwind v4 (CSS-variable tokens) · React Query
(caching + resilient retry/backoff) · framer-motion · lucide-react.

Resilience is a first-class concern: the platform calls a live LLM, so every
model-dependent action has a friendly error state and one-tap retry — it never
fakes success. 4xx are never retried; network/5xx are, with backoff.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api -> backend
```

The dev server proxies `/api` to `AIPM_BACKEND_URL` (default
`http://localhost:8000`). Run the backend separately (see `../backend`). For the
exec **Ask Shlomi** chat and live extraction/approval, the backend needs an LLM
provider key configured; without one the UI degrades gracefully.

## Test / build

```bash
npm test             # vitest — unit tests for the pure view-model helpers
npm run build        # tsc -b && vite build
```

## Layout

```
src/
  lib/        api client, typed backend shapes, React Query hooks, and the pure
              view-model helpers (format, health, board, proposal, approvals,
              events, threads) — all unit-tested in lib/logic.test.ts
  components/ ui primitives (one definition each: Button, Card, Tag, Avatar,
              status chips, loading/empty/error), Modal, Drawer, Toast,
              ErrorBoundary, layout/ (AppShell, Sidebar, PersonaSwitcher, …)
  routes/     one file per screen (Worker, Manager, Exec, Demo, Board,
              Timeline, Threads)
```
