"""CLI client for the backend API.

Setup:
  init <name>              -- define the project (--description, --team)

Input (mint a raw-input event; with auto-extraction on, the agent extracts,
proposes, and auto-sends info_request emails in the same step):
  note <text>              -- append a manual_note event
  message-in <text>        -- append a message_received event (--from, --channel,
                              --thread). If proposals are pending, the reply is
                              also read as an approval: "yes, go ahead" authorizes
                              them. This is the ONLY way to approve -- approving
                              happens in the channel, never via a command. With
                              --thread, it's scoped to that conversation's proposal
                              (and the agent may reply in the thread if the message
                              is ambiguous).
  transcript <text>        -- append a transcript_ingested event
  append <event.json>      -- POST a hand-written event JSON to the backend

Inspect / drive the loop:
  events                    -- the full event log (outbound events flagged
                               [SIMULATED] -- execution is a Phase 1 stub)
  state                     -- the current projected state
  extract <event_id>        -- run extraction on a raw event: writes a proposal
                               for anything needing approval, auto-executes
                               info_request emails (logged, not really sent),
                               and surfaces conflict warnings
  proposals                 -- proposals awaiting approval (approve by replying
                               with message-in on the proposal's thread)
  replay <scenario.yaml>   -- post a scenario's events in order and check its
                               checkpoints against the live backend
  review                    -- scan current state for issues and emit follow-up
                               actions (open questions, blocked tasks, unowned
                               high risks, overdue deadlines)

Add --json before any command to print the raw API JSON instead of the
human-readable rendering.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

DEFAULT_BASE_URL = "http://localhost:8000"

# Maps the table names used in scenario assertions to entity types.
TABLES = {
    "decisions": "Decision",
    "tasks": "Task",
    "owners": "Owner",
    "deadlines": "Deadline",
    "risks": "Risk",
    "dependencies": "Dependency",
    "open_questions": "OpenQuestion",
}

# Entity tables in the order we render them in `state`.
ENTITY_TABLES = [
    "Decision", "Task", "Owner", "Deadline", "Risk", "Dependency", "OpenQuestion",
]

# Outbound event types are records of the agent acting on the world. In
# Phase 1 execution is a stub, so we flag them [SIMULATED] when rendering.
OUTBOUND_EVENT_TYPES = {
    "message_sent", "ticket_opened", "flag_raised", "report_to_management",
}


# --- rendering helpers --------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fields(d: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in d.items()) if d else "(none)"


def render_extract(body: dict) -> str:
    """Human-readable view of an /extract response."""
    proposal = body.get("proposal")
    executed = body.get("executed", [])
    conflicts = body.get("conflicts", [])
    dropped = body.get("dropped", [])

    lines = ["Extraction result", "================="]

    if proposal:
        payload = proposal["payload"]
        lines.append(
            f"Proposal {proposal['id']}  "
            f"(provider: {payload.get('provider', '?')}, "
            f"from: {payload.get('source_event_id', '?')})  -- awaiting approval"
        )
        deltas = payload.get("deltas", [])
        if deltas:
            lines.append("  Facts to record (deltas):")
            for d in deltas:
                mark = "+" if d["op"] == "create" else "~"
                lines.append(
                    f"    {mark} {d['op']} {d['entity_type']} {d['entity_id']!r}: {_fields(d.get('fields', {}))}"
                )
        actions = payload.get("actions", [])
        if actions:
            lines.append("  Actions needing sign-off (consequential):")
            for a in actions:
                lines.append(f"    ! {a['type']}: {_fields(a.get('payload', {}))}")
    else:
        lines.append("Proposal: none -- nothing here needs human approval.")

    lines.append("")
    if executed:
        lines.append("Auto-executed (info_request -- no approval needed):")
        for ev in executed:
            action = ev.get("payload", {})
            inner = action.get("payload", {})
            lines.append(f"  >> [SIMULATED] {ev['type']}: {_fields(inner)}")
        lines.append("     (Phase 1 stub -- nothing was actually sent.)")
    else:
        lines.append("Auto-executed: none.")

    if conflicts:
        lines.append("")
        lines.append("Conflict warnings (advisory -- review before approving):")
        for c in conflicts:
            lines.append(f"  ! {c['type']} on {c['entity_id']}: {c['detail']}")

    clarifications = body.get("clarifications", [])
    if clarifications:
        lines.append("")
        lines.append("Couldn't reconcile -- asked the author to clarify (info_request):")
        for c in clarifications:
            lines.append(f"  ? {c['entity_type']} '{c['entity_id']}': {c['reason']}")
        lines.append("     (these were held out of the proposal until answered.)")

    if dropped:
        lines.append("")
        lines.append("Dropped (ungrounded -- not in the raw text, ignored):")
        for problem in dropped:
            lines.append(f"  x {problem}")

    request = body.get("approval_request")
    if request:
        inner = request.get("payload", {}).get("payload", {})
        lines.append("")
        lines.append("Approval request sent (info_request -- the agent is asking a human):")
        lines.append(f"  >> [SIMULATED] message_sent → {inner.get('to', '?')}: {inner.get('subject', '')}")

    if proposal:
        lines.append("")
        lines.append(f"Next: reply to approve, e.g.  aipm message-in \"yes, go ahead\" --thread {proposal['payload'].get('thread_id', '<thread>')}")

    return "\n".join(lines)


def render_message_approvals(approvals: dict) -> str:
    """Human-readable view of how an inbound reply resolved pending proposals."""
    if approvals.get("error"):
        return f"Approval resolution did not run: {approvals['error']}"

    approved = approvals.get("approved", [])
    rejected = approvals.get("rejected", [])
    fanned_out = approvals.get("fanned_out", [])
    composed = approvals.get("composed", [])
    nudged = approvals.get("nudged", [])
    escalated = approvals.get("escalated", [])
    if not approved and not rejected and not fanned_out and not composed and not nudged and not escalated:
        return "Approval check: your reply did not authorize any pending request."

    lines = ["Approval resolved from your reply", "================================="]
    for appr in approved:
        payload = appr.get("payload", {})
        lines.append(f"  ✓ Approved {payload.get('approves', '?')}")
        for d in payload.get("deltas", []):
            mark = "+" if d["op"] == "create" else "~"
            lines.append(f"      {mark} {d['op']} {d['entity_type']} {d['entity_id']!r}")
        for a in payload.get("actions", []):
            lines.append(f"      >> [SIMULATED] {a['type']}: {_fields(a.get('payload', {}))}")
    for rej in rejected:
        payload = rej.get("payload", {})
        reason = payload.get("reason")
        suffix = f" ({reason})" if reason else ""
        lines.append(f"  ✗ Rejected {payload.get('rejects', '?')}{suffix}")

    if fanned_out:
        lines.append("")
        lines.append("Batch approved -- now asking each owner to confirm their own ticket:")
        for f in fanned_out:
            tickets = ", ".join(f.get("tickets", []))
            lines.append(f"  >> [SIMULATED] message_sent → {f['owner']}: confirm '{tickets}'  ({f['proposal_id']})")

    if composed:
        lines.append("")
        lines.append("Reply was ambiguous -- the agent replied in the thread (info_request):")
        for item in composed:
            lines.append(f"  >> [SIMULATED] message_sent: replied on '{item['summary'][:60]}'")
    if nudged:
        lines.append("")
        lines.append("Reply didn't address these -- sent a reminder (info_request):")
        for item in nudged:
            lines.append(f"  >> [SIMULATED] message_sent: still waiting on '{item['summary'][:60]}'")
    if escalated:
        lines.append("")
        lines.append("No response after 2 attempts -- escalated (proposal stays pending):")
        for item in escalated:
            lines.append(f"  >> [SIMULATED] message_sent: escalating '{item['summary'][:60]}'")
    return "\n".join(lines)


def render_events(events: list[dict]) -> str:
    """One line per event; outbound events flagged [SIMULATED]."""
    if not events:
        return "(no events yet)"
    lines = []
    for e in events:
        tag = " [SIMULATED]" if e["type"] in OUTBOUND_EVENT_TYPES else ""
        line = f"[{e['id']:<14}] {e['type']}{tag}  (source: {e.get('source', '?')})"
        detail = _event_detail(e)
        if detail:
            line += f"\n    {detail}"
        lines.append(line)
    return "\n".join(lines)


def _event_detail(e: dict) -> str:
    """A short, type-appropriate summary line for an event."""
    if e["type"] in OUTBOUND_EVENT_TYPES:
        return _fields(e.get("payload", {}).get("payload", {}))
    if e.get("raw_text"):
        text = e["raw_text"]
        return f'"{text[:80]}{"..." if len(text) > 80 else ""}"'
    if e["type"] == "human_approval":
        payload = e.get("payload", {})
        return (
            f"approves {payload.get('approves', '?')}  "
            f"({len(payload.get('deltas', []))} delta(s), {len(payload.get('actions', []))} action(s))"
        )
    if e["type"] == "agent_proposal":
        payload = e.get("payload", {})
        return f"{len(payload.get('deltas', []))} delta(s), {len(payload.get('actions', []))} action(s)"
    return ""


def render_state(state: dict) -> str:
    """Entity tables (with current fields) plus the approved-action audit trail."""
    lines = ["Project state", "============="]
    meta = state.get("meta") or {}
    if meta.get("name"):
        lines.append(f"Project: {meta['name']}")
        if meta.get("description"):
            lines.append(f"  {meta['description']}")
        if meta.get("team"):
            lines.append(f"  team: {', '.join(meta['team'])}")
        lines.append("")
    any_entities = False
    for entity_type in ENTITY_TABLES:
        table = state.get(entity_type, {})
        if not table:
            continue
        any_entities = True
        lines.append(f"{entity_type}:")
        for entity_id, entity in table.items():
            n = len(entity.get("history", []))
            lines.append(f"  {entity_id}: {_fields(entity.get('fields', {}))}  [{n} update(s)]")
    if not any_entities:
        lines.append("(no entities yet)")

    actions = state.get("actions", [])
    lines.append("")
    if actions:
        lines.append("Approved actions:")
        for a in actions:
            lines.append(f"  ! {a['type']} [{a.get('category', '?')}]: {_fields(a.get('payload', {}))}")
    else:
        lines.append("Approved actions: none")
    return "\n".join(lines)


def render_proposals(proposals: list[dict]) -> str:
    if not proposals:
        return "(no proposals awaiting approval)"
    lines = ["Proposals awaiting approval", "==========================="]
    for p in proposals:
        payload = p["payload"]
        lines.append(
            f"{p['id']}  (from: {payload.get('source_event_id', '?')}, "
            f"provider: {payload.get('provider', '?')})"
        )
        for d in payload.get("deltas", []):
            lines.append(f"    delta: {d['op']} {d['entity_type']} {d['entity_id']!r}")
        for a in payload.get("actions", []):
            lines.append(f"    action: {a['type']} [{a.get('category', '?')}]")
        thread = p.get("payload", {}).get("thread_id", "<thread>")
        lines.append(f"    approve by replying: aipm message-in \"yes, go ahead\" --thread {thread}")
    return "\n".join(lines)


def render_review(body: dict) -> str:
    """Human-readable view of a /review-state response."""
    issues = body.get("issues", [])
    executed = body.get("executed", [])
    proposal = body.get("proposal")

    lines = ["State review", "============"]

    if not issues:
        lines.append("Nothing to follow up -- project looks clean.")
        return "\n".join(lines)

    lines.append(f"Found {len(issues)} issue(s):")
    for iss in issues:
        lines.append(
            f"  ! [{iss['rule']}] {iss['entity_type']} '{iss['entity_id']}': {iss['detail']}"
        )

    lines.append("")
    if executed:
        lines.append("Auto-sent (info_request -- no approval needed):")
        for ev in executed:
            inner = ev.get("payload", {}).get("payload", {})
            lines.append(f"  >> [SIMULATED] {ev['type']}: {_fields(inner)}")
        lines.append("   (Phase 1 stub -- nothing was actually sent.)")
    else:
        lines.append("Auto-sent: none.")

    if proposal:
        payload = proposal["payload"]
        lines.append("")
        lines.append(f"Proposal {proposal['id']} -- needs your approval:")
        for a in payload.get("actions", []):
            lines.append(f"  ! {a['type']}: {_fields(a.get('payload', {}))}")
        thread = payload.get("thread_id", "<thread>")
        lines.append(f"Next: reply to approve, e.g.  aipm message-in \"yes, go ahead\" --thread {thread}")

    return "\n".join(lines)


# --- commands -----------------------------------------------------------------


def _error(response: httpx.Response) -> int:
    print(f"Error: {response.json().get('detail')}", file=sys.stderr)
    return 1


def cmd_init(
    client: httpx.Client,
    name: str,
    description: str | None,
    team: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    pm: str | None = None,
    tech_lead: str | None = None,
    as_json: bool = False,
) -> int:
    """Define the project so later extraction has framing.

    Only sends the fields actually provided, so re-running `init` with a
    single flag updates just that field (the backend merges). A brand-new
    project should carry start/end dates (tentative is fine); they anchor the
    extractor's date resolution and the project-deadline conflict check.
    --pm / --tech-lead set the escalation email target for unaddressed approvals.
    """
    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description
    if team:
        payload["team"] = team
    if start_date is not None:
        payload["start_date"] = start_date
    if end_date is not None:
        payload["end_date"] = end_date
    if pm is not None:
        payload["pm"] = pm
    if tech_lead is not None:
        payload["tech_lead"] = tech_lead
    response = client.post("/project", json=payload)
    if response.status_code >= 400:
        return _error(response)
    if as_json:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Initialized project: {name}")
        if description:
            print(f"  {description}")
        if team:
            print(f"  team: {', '.join(team)}")
        if start_date:
            print(f"  start: {start_date}")
        if end_date:
            print(f"  end:   {end_date}")
        if pm:
            print(f"  pm:    {pm}")
        if tech_lead:
            print(f"  tech-lead: {tech_lead}")
        if not start_date and not end_date:
            print("  (tip: set --start/--end so dates and deadlines stay anchored)")
        if not pm and not tech_lead:
            print("  (tip: set --pm / --tech-lead so escalation emails reach the right person)")
        print("Next: stream events with aipm note / email-in / transcript")
    return 0


def cmd_add_raw(
    client: httpx.Client,
    event_type: str,
    text: str,
    source: str,
    as_json: bool = False,
    payload: dict | None = None,
) -> int:
    """Mint a raw-input event from text and POST it.

    With auto-extraction on (the backend default), the response carries the
    extraction result, which we render inline -- so a single `message-in`/`note`/
    `transcript` shows what the agent extracted, proposed, and auto-sent. A
    `payload` (e.g. {channel, thread_id} for a message-in) ties the event to its
    conversation; a reply on a thread is resolved against that thread's proposal.
    """
    event = {
        "id": f"raw_{uuid.uuid4().hex[:8]}",
        "type": event_type,
        "timestamp": _now(),
        "source": source,
        "raw_text": text,
        "payload": payload or {},
    }
    response = client.post("/events", json=event)
    if response.status_code >= 400:
        return _error(response)
    body = response.json()
    if as_json:
        print(json.dumps(body, indent=2))
        return 0

    print(f"Added {event_type} [{event['id']}]")

    # An inbound reply may resolve pending approval requests -- show that first.
    approvals = body.get("approvals")
    if approvals:
        print()
        print(render_message_approvals(approvals))

    extraction = body.get("extraction")
    if not extraction:
        # auto-extraction disabled -- drive it manually
        print(f"Next: aipm extract {event['id']}")
    elif extraction.get("skipped") or extraction.get("error"):
        print(f"  (auto-extraction did not run: {extraction.get('skipped') or extraction.get('error')})")
        print(f"Next: aipm extract {event['id']}")
    else:
        print()
        print(render_extract(extraction))
    return 0


def cmd_append(client: httpx.Client, event_file: str, as_json: bool = False) -> int:
    event = json.loads(Path(event_file).read_text())
    response = client.post("/events", json=event)
    if response.status_code >= 400:
        return _error(response)
    if as_json:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Added {event.get('type')} [{event.get('id')}]")
    return 0


def cmd_events(client: httpx.Client, as_json: bool = False) -> int:
    response = client.get("/events")
    response.raise_for_status()
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_events(body))
    return 0


def cmd_state(client: httpx.Client, as_json: bool = False) -> int:
    response = client.get("/state")
    response.raise_for_status()
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_state(body))
    return 0


def cmd_extract(client: httpx.Client, source_event_id: str, as_json: bool = False) -> int:
    response = client.post("/extract", json={"source_event_id": source_event_id})
    if response.status_code >= 400:
        return _error(response)
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_extract(body))
    return 0


def cmd_proposals(client: httpx.Client, as_json: bool = False) -> int:
    response = client.get("/proposals")
    response.raise_for_status()
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_proposals(body))
    return 0


def cmd_review(client: httpx.Client, as_json: bool = False) -> int:
    """Scan current state for issues and emit follow-up actions."""
    response = client.post("/review-state")
    if response.status_code >= 400:
        return _error(response)
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_review(body))
    return 0


def render_open_tickets(body: dict) -> str:
    """Human-readable view of an /open-tickets response (the batch proposal)."""
    proposal = body.get("proposal")
    if not proposal:
        return body.get("message", "Nothing to do.")
    actions = proposal["payload"].get("actions", [])
    lines = [
        "Ticket batch proposed",
        "=====================",
        f"Proposal {proposal['id']} -- {len(actions)} ticket(s), one per task:",
    ]
    for a in actions:
        p = a.get("payload", {})
        lines.append(f"  - {p.get('title', p.get('task_id', '?'))}  → owner: {p.get('owner', '?')}")
    request = body.get("approval_request")
    if request:
        inner = request.get("payload", {}).get("payload", {})
        lines.append("")
        lines.append("Sent ONE approval message to the PM (not the whole team):")
        lines.append(f"  >> [SIMULATED] message_sent → {inner.get('to', '?')}: {inner.get('subject', '')}")
    lines.append("")
    lines.append("Flow: PM approves the batch → each owner gets a final confirm message")
    lines.append("      → only the owner's reply opens their ticket.")
    lines.append(f"Next: PM replies, e.g.  aipm message-in \"yes, open them\" --from <pm>")
    return "\n".join(lines)


def cmd_open_tickets(client: httpx.Client, as_json: bool = False) -> int:
    """Propose opening a ticket for every task that doesn't have one yet."""
    response = client.post("/open-tickets")
    if response.status_code >= 400:
        return _error(response)
    body = response.json()
    print(json.dumps(body, indent=2) if as_json else render_open_tickets(body))
    return 0


def cmd_close(client: httpx.Client, reason: str | None, as_json: bool = False) -> int:
    """Close the project. Extraction is rejected after this point."""
    body = {"reason": reason} if reason else {}
    response = client.post("/project/close", json=body)
    if response.status_code >= 400:
        return _error(response)
    if as_json:
        print(json.dumps(response.json(), indent=2))
    else:
        print("Project closed.")
        if reason:
            print(f"  Reason: {reason}")
        print("  The event log is preserved. Run `aipm events` or `aipm state` to review.")
    return 0


def cmd_replay(client: httpx.Client, scenario_file: str) -> int:
    scenario = yaml.safe_load(Path(scenario_file).read_text())
    checkpoints_by_event = {c["after_event"]: c["assert"] for c in scenario["checkpoints"]}

    failures = 0
    for event in scenario["events"]:
        response = client.post("/events", json=event)
        if response.status_code >= 400:
            print(f"FAIL: {event['id']} rejected by backend: {response.json().get('detail')}")
            failures += 1
            continue

        checks = checkpoints_by_event.get(event["id"])
        if checks is None:
            continue

        state = client.get("/state").json()
        for path, expected in checks.items():
            actual = _resolve(state, path)
            status = "PASS" if actual == expected else "FAIL"
            if status == "FAIL":
                failures += 1
            print(f"{status} @ {event['id']}: {path} = {actual!r} (expected {expected!r})")

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print("\nAll checkpoints passed")
    return 0


def _resolve(state: dict, path: str):
    """Resolve a dotted assertion path.

    Entity paths look like 'decisions.db-choice.description' or
    '....history_length'. Action paths look like 'actions.count' or
    'actions.0.type' / 'actions.0.payload.<key>'.
    """
    table_name, rest = path.split(".", 1)

    if table_name == "actions":
        actions = state.get("actions", [])
        if rest == "count":
            return len(actions)
        index, attr = rest.split(".", 1)
        action = actions[int(index)]
        if attr.startswith("payload."):
            return action["payload"].get(attr.removeprefix("payload."))
        return action.get(attr)

    entity_id, attr = rest.split(".", 1)
    entity_type = TABLES[table_name]
    entity = state.get(entity_type, {}).get(entity_id)
    if entity is None:
        raise AssertionError(f"{entity_type} {entity_id!r} not found in state")
    if attr == "history_length":
        return len(entity["history"])
    return entity["fields"].get(attr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aipm")
    parser.add_argument(
        "--json", action="store_true", help="print raw API JSON instead of a human-readable view"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="define/initialize the project")
    init_parser.add_argument("name")
    init_parser.add_argument("--description", default=None)
    init_parser.add_argument("--team", nargs="*", default=[], help="team member names")
    init_parser.add_argument(
        "--start", dest="start_date", default=None, metavar="YYYY-MM-DD",
        help="project start date (tentative is fine; update anytime with aipm init)",
    )
    init_parser.add_argument(
        "--end", dest="end_date", default=None, metavar="YYYY-MM-DD",
        help="project end / target deadline (tentative is fine; anchors date checks)",
    )
    init_parser.add_argument(
        "--pm", default=None, metavar="EMAIL",
        help="project manager email -- receives escalation emails when approvals go unanswered",
    )
    init_parser.add_argument(
        "--tech-lead", dest="tech_lead", default=None, metavar="EMAIL",
        help="tech lead email -- fallback escalation target if no PM is set",
    )

    note_parser = subparsers.add_parser("note", help="append a manual_note raw event")
    note_parser.add_argument("text")
    note_parser.add_argument("--source", default="pm_note")

    message_parser = subparsers.add_parser("message-in", help="append a message_received raw event")
    message_parser.add_argument("text")
    message_parser.add_argument("--from", dest="sender", default="message", help="sender (recorded as source)")
    message_parser.add_argument("--channel", default="email", help="channel the message arrived on (email, slack, ...)")
    message_parser.add_argument(
        "--thread", dest="thread_id", default=None,
        help="thread id this message replies on (ties it to that conversation's proposal)",
    )

    transcript_parser = subparsers.add_parser(
        "transcript", help="append a transcript_ingested raw event"
    )
    transcript_parser.add_argument("text")
    transcript_parser.add_argument("--source", default="meeting")

    append_parser = subparsers.add_parser("append", help="POST a hand-written event JSON to the backend")
    append_parser.add_argument("event_file")

    subparsers.add_parser("events", help="GET the full event log")
    subparsers.add_parser("state", help="GET the current projected state")

    replay_parser = subparsers.add_parser(
        "replay", help="replay a scenario against the backend and check its checkpoints"
    )
    replay_parser.add_argument("scenario_file")

    extract_parser = subparsers.add_parser(
        "extract", help="run extraction on a raw event (writes a proposal)"
    )
    extract_parser.add_argument("source_event_id")

    subparsers.add_parser("proposals", help="list proposals awaiting approval")

    subparsers.add_parser(
        "review",
        help="scan current state for issues (open questions, blocked tasks, etc.)",
    )

    subparsers.add_parser(
        "open-tickets",
        help="propose opening a ticket per task (PM approves the batch, owners confirm each)",
    )

    close_parser = subparsers.add_parser(
        "close", help="close the project -- stops further extraction"
    )
    close_parser.add_argument("--reason", default=None, help="optional close reason for the audit trail")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)
    base_url = os.environ.get("AIPM_BACKEND_URL", DEFAULT_BASE_URL)
    as_json = args.json

    # Generous timeout: with auto-extraction on, POST /events runs a real LLM
    # call synchronously, which easily exceeds httpx's 5s default. Overridable
    # via AIPM_TIMEOUT (seconds).
    timeout = float(os.environ.get("AIPM_TIMEOUT", "180"))

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        if args.command == "init":
            return cmd_init(
                client, args.name, args.description, args.team,
                args.start_date, args.end_date, args.pm, args.tech_lead, as_json,
            )
        if args.command == "note":
            return cmd_add_raw(client, "manual_note", args.text, args.source, as_json)
        if args.command == "message-in":
            payload: dict = {"channel": args.channel}
            if args.thread_id:
                payload["thread_id"] = args.thread_id
            return cmd_add_raw(
                client, "message_received", args.text, args.sender, as_json, payload=payload
            )
        if args.command == "transcript":
            return cmd_add_raw(client, "transcript_ingested", args.text, args.source, as_json)
        if args.command == "append":
            return cmd_append(client, args.event_file, as_json)
        if args.command == "events":
            return cmd_events(client, as_json)
        if args.command == "state":
            return cmd_state(client, as_json)
        if args.command == "replay":
            return cmd_replay(client, args.scenario_file)
        if args.command == "extract":
            return cmd_extract(client, args.source_event_id, as_json)
        if args.command == "proposals":
            return cmd_proposals(client, as_json)
        if args.command == "review":
            return cmd_review(client, as_json)
        if args.command == "open-tickets":
            return cmd_open_tickets(client, as_json)
        if args.command == "close":
            return cmd_close(client, args.reason, as_json)

    return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
