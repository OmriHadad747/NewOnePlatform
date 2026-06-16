"""Backend API: wraps ai-engine and owns the event log.

Project / event endpoints:
  POST /project -- define the project (name, description, team); writes a
                   project_initialized event that frames later extraction.
  GET  /project -- the current project metadata
  POST /events  -- append a new event (validated against current state). If
                   AIPM_AUTO_EXTRACT is on (default) and the event is a
                   raw-input event with text, extraction runs in the same
                   request and its result is returned under `extraction`.
  GET  /events  -- list the full event log, in order
  GET  /state   -- the current projected project state

Extraction / approval flow (Step 3):
  POST /review-state               -- scan current state for issues (open
                                      questions, blocked tasks, unowned high
                                      risks, overdue deadlines) and emit
                                      follow-up actions: info_request ones
                                      auto-execute (email_sent/reminder_sent);
                                      consequential ones go into a proposal.
                                      Returns: {issues, executed, proposal}
  POST /extract                    -- run extraction on a raw event, write an
                                      agent_proposal (no state change).
                                      info_request actions execute (stub)
                                      immediately and log an outbound event
                                      (email_sent/reminder_sent); only
                                      consequential actions stay in the
                                      proposal, awaiting approval.
                                      Returns: {proposal, dropped, executed,
                                      conflicts} -- conflicts are semantic
                                      warnings (deadline regression, task done
                                      with open deps, risk downgraded) for the
                                      human reviewer; advisory only, never block.
  GET  /proposals                  -- proposals still awaiting approval
  POST /proposals/{id}/approve     -- approve a proposal: write a
                                      human_approval that applies its
                                      deltas/actions to state, then execute
                                      (stub) its consequential actions and
                                      log their outbound events
                                      (ticket_opened/flag_raised/
                                      report_to_management)
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException

from aipm.approval import PendingProposal, build_approval_prompt
from aipm.conflicts import detect_conflicts
from aipm.entities import outbound_event_type
from aipm.events import RAW_INPUT_TYPES, Event
from aipm.extraction import build_prompt, filter_grounded
from aipm.extraction.providers import ExtractionProvider
from aipm.projection import ProjectionError, apply_event, project
from aipm.review import review_state as _review_state

from aipm_backend import config, storage
from aipm_backend.extraction import get_provider, get_provider_optional
from aipm_backend.models import EventIn, ExtractRequest, ProjectIn, serialize_state

app = FastAPI(title="AI PM Backend")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_outbound_event(action: dict, source: str, source_event_id: str) -> dict:
    """Record an action's (stubbed) execution as an outbound event.

    Returns the written event as a dict.
    """
    event = Event(
        id=f"out_{uuid.uuid4().hex[:12]}",
        type=outbound_event_type(action["type"], action["category"]),
        timestamp=_now(),
        source=source,
        payload={**action, "source_event_id": source_event_id},
    )
    storage.write_event(event)
    return asdict(event)


def _summarize_proposal_payload(payload: dict) -> str:
    """A short, human-readable description of what a proposal would do.

    Used both in the approval-request email the agent sends and as context the
    resolver sees when mapping a reply onto pending proposals.
    """
    parts: list[str] = []
    for action in payload.get("actions", []):
        ap = action.get("payload", {})
        label = ap.get("title") or ap.get("subject") or ap.get("reason") or action.get("type")
        parts.append(f"{action.get('type')} ({label})")
    for delta in payload.get("deltas", []):
        parts.append(f"{delta.get('op')} {delta.get('entity_type')} '{delta.get('entity_id')}'")
    return "; ".join(parts) if parts else "(empty proposal)"


def _pending_proposals(events: list[Event]) -> list[Event]:
    """Proposals that are neither approved nor rejected yet."""
    resolved = {
        e.payload.get("approves") for e in events if e.type == "human_approval"
    } | {
        e.payload.get("rejects") for e in events if e.type == "proposal_rejected"
    }
    return [e for e in events if e.type == "agent_proposal" and e.id not in resolved]


def _approval_recipient(events: list[Event], payload: dict) -> str:
    """Who to ask for sign-off: an action's named owner, else the project team."""
    for action in payload.get("actions", []):
        to = action.get("payload", {}).get("to")
        if to:
            return to
    team = project(events).meta.get("team") or []
    return ", ".join(team) if team else "team"


def _ask_for_approval(proposal: Event, events: list[Event]) -> dict:
    """Send (stub) an email asking a human to authorize a pending proposal."""
    summary = _summarize_proposal_payload(proposal.payload)
    action = {
        "type": "send_email",
        "category": "info_request",
        "payload": {
            "to": _approval_recipient(events, proposal.payload),
            "subject": f"Approval needed: {summary}",
            "body": (
                f"I'd like to proceed with: {summary}. "
                f"Reply to this email to approve or decline."
            ),
            "proposal_id": proposal.id,
        },
    }
    return _write_outbound_event(action, source="agent:approval-request", source_event_id=proposal.id)


def _apply_approval(proposal: Event, events: list[Event], source: str) -> Event:
    """Write a human_approval that applies a proposal's deltas/actions to state,
    then execute (stub) its consequential actions. Shared by the explicit
    approve endpoint and the email-reply approval path."""
    approval = Event(
        id=f"appr_{uuid.uuid4().hex[:12]}",
        type="human_approval",
        timestamp=_now(),
        source=source,
        payload={
            "deltas": proposal.payload.get("deltas", []),
            "actions": proposal.payload.get("actions", []),
            "approves": proposal.id,
        },
    )

    state = project(events)
    apply_event(state, approval)  # raises ProjectionError on a bad payload
    storage.write_event(approval)

    for action in approval.payload["actions"]:
        _write_outbound_event(action, source="agent:approved", source_event_id=approval.id)
    return approval


def _reject_proposal(proposal: Event, source: str, reason: str = "") -> Event:
    """Record that a human declined a proposal -- takes it out of the pending set."""
    event = Event(
        id=f"rej_{uuid.uuid4().hex[:12]}",
        type="proposal_rejected",
        timestamp=_now(),
        source=source,
        payload={"rejects": proposal.id, "reason": reason},
    )
    storage.write_event(event)
    return event


def _has_approval_request(proposal_id: str, events: list[Event]) -> bool:
    """True if an approval-request email was already sent for this proposal."""
    return any(
        e.type == "email_sent"
        and e.source == "agent:approval-request"
        and e.payload.get("payload", {}).get("proposal_id") == proposal_id
        for e in events
    )


# Follow-ups after the initial approval request, in order. The reply state
# machine uses how many have already gone out to decide the next step:
# 0 sent -> nudge, 1 sent -> escalate, >=2 -> go quiet.
_FOLLOWUP_SOURCES = ("agent:approval-nudge", "agent:approval-escalation")


def _followup_count(proposal_id: str, events: list[Event]) -> int:
    """How many follow-up emails (nudge + escalation) were sent for this proposal."""
    return sum(
        1 for e in events
        if e.type == "email_sent"
        and e.source in _FOLLOWUP_SOURCES
        and e.payload.get("payload", {}).get("proposal_id") == proposal_id
    )


def _escalation_recipient(events: list[Event]) -> str | None:
    """The PM or tech lead stored in project meta, if set -- escalation target."""
    meta = project(events).meta
    return meta.get("pm") or meta.get("tech_lead")


def _send_followup(
    proposal: Event,
    events: list[Event],
    *,
    source: str,
    subject: str,
    body: str,
    to: str | None = None,
) -> dict:
    """Send (stub) a follow-up email about an unaddressed pending proposal.

    `to` overrides the default recipient (used for escalations that must go to
    PM/tech lead rather than the original action target).
    """
    action = {
        "type": "send_email",
        "category": "info_request",
        "payload": {
            "to": to or _approval_recipient(events, proposal.payload),
            "subject": subject,
            "body": body,
            "proposal_id": proposal.id,
        },
    }
    return _write_outbound_event(action, source=source, source_event_id=proposal.id)


def _resolve_approvals_from_reply(
    reply: Event, provider: ExtractionProvider
) -> dict | None:
    """Map a human's email reply onto pending proposals and act on it.

    Runs only when proposals are actually pending. The resolver distinguishes a
    real authorization ("yes, open the ticket") from merely answering a question
    ("yes, we need PayPal"), so a stray "yes" never fires an action.

    Proposals this reply did not address (and that we already asked about) are
    chased: a nudge on the first miss, an escalation on the second; after that
    we stop emailing but leave the proposal pending.
    """
    pending = _pending_proposals(storage.read_events())
    if not pending:
        return None

    prompt = build_approval_prompt(
        reply.raw_text,
        [PendingProposal(id=p.id, summary=_summarize_proposal_payload(p.payload)) for p in pending],
    )
    result = provider.resolve_approvals(prompt)

    by_id = {p.id: p for p in pending}
    approved: list[dict] = []
    rejected: list[dict] = []
    resolved_ids: set[str] = set()
    for res in result.resolutions:
        target = by_id.get(res.proposal_id)
        if target is None:
            continue
        if res.decision == "approve":
            approval = _apply_approval(target, storage.read_events(), source=f"email:{reply.source}")
            approved.append(asdict(approval))
            resolved_ids.add(res.proposal_id)
        elif res.decision == "reject":
            rejection = _reject_proposal(target, source=f"email:{reply.source}", reason=res.reason_span)
            rejected.append(asdict(rejection))
            resolved_ids.add(res.proposal_id)
        # "defer" leaves the proposal pending -- handled by the chase loop below.

    # Chase the proposals this reply ignored: nudge once, escalate on the
    # second miss, then go quiet (proposal stays pending, visible in /proposals).
    nudged: list[dict] = []
    escalated: list[dict] = []
    current = storage.read_events()
    for proposal in pending:
        if proposal.id in resolved_ids:
            continue
        if not _has_approval_request(proposal.id, current):
            continue  # never asked about this one yet -- nothing to follow up on
        summary = _summarize_proposal_payload(proposal.payload)
        count = _followup_count(proposal.id, current)
        if count == 0:
            _send_followup(
                proposal, current, source="agent:approval-nudge",
                subject=f"Still waiting for your response: {summary[:60]}",
                body=(
                    "We received your reply but it didn't address our pending request. "
                    f"We still need your approval on: {summary}. "
                    "Please reply to approve or decline."
                ),
            )
            nudged.append({"proposal_id": proposal.id, "summary": summary})
        elif count == 1:
            esc_to = _escalation_recipient(current)
            _send_followup(
                proposal, current, source="agent:approval-escalation",
                subject=f"Escalation: no response after 2 attempts -- {summary[:50]}",
                body=(
                    f"Two approval requests for '{summary}' went unaddressed. "
                    f"Flagging this. Proposal {proposal.id} stays pending until "
                    "explicitly approved or declined."
                ),
                to=esc_to,
            )
            escalated.append({"proposal_id": proposal.id, "summary": summary})
        # count >= 2: already escalated -- stay quiet.

    return {
        "approved": approved,
        "rejected": rejected,
        "nudged": nudged,
        "escalated": escalated,
        "resolutions": result.to_dict()["resolutions"],
    }


def _run_extraction(source: Event, events: list[Event], provider: ExtractionProvider) -> dict:
    """Extract from one raw event: write a proposal for anything needing
    approval, auto-execute info_request actions, and surface conflicts.

    Pure of HTTP concerns -- callers (POST /extract, the POST /events auto
    path) decide how to handle a provider failure (it propagates here).
    Returns: {proposal, dropped, executed, conflicts}.
    """
    state = project(events)
    prompt = build_prompt(source.raw_text, state)
    result = provider.extract(prompt)

    grounded, dropped = filter_grounded(result, source.raw_text)
    payload = grounded.to_payload(asserted_by=provider.name)

    raw_conflicts = detect_conflicts(payload["deltas"], state)
    conflicts = [
        {"type": w.type, "entity_id": w.entity_id, "detail": w.detail}
        for w in raw_conflicts
    ]

    # `info_request` actions are routine info-gathering the agent does on its
    # own -- execute (stub) them immediately and log the outbound event, with
    # no human_approval. `consequential` actions stay in the proposal,
    # awaiting approval.
    auto_actions = [a for a in payload["actions"] if a["category"] == "info_request"]
    payload["actions"] = [a for a in payload["actions"] if a["category"] == "consequential"]
    payload["source_event_id"] = source.id
    payload["provider"] = provider.name

    # A date past the project end is not just advisory: attach a consequential
    # raise_flag so the PM must explicitly acknowledge the timeline breach when
    # they approve. Option A -- the offending delta stays in the proposal; the
    # flag rides alongside it.
    for w in raw_conflicts:
        if w.type == "project_deadline_exceeded":
            payload["actions"].append({
                "type": "raise_flag",
                "category": "consequential",
                "payload": {
                    "entity_id": w.entity_id,
                    "reason": w.detail,
                    "review_rule": "project_deadline_exceeded",
                },
                "provenance": {"asserted_by": "conflict-detector"},
            })

    proposal = None
    approval_request = None
    if payload["deltas"] or payload["actions"]:
        proposal_event = Event(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            type="agent_proposal",
            timestamp=_now(),
            source=f"extraction:{provider.name}",
            payload=payload,
        )
        storage.write_event(proposal_event)
        proposal = asdict(proposal_event)
        # The agent reaches out (stub) to ask a human to authorize the proposal;
        # that person approves by replying -- see the email-reply approval path.
        approval_request = _ask_for_approval(proposal_event, storage.read_events())

    executed = [
        _write_outbound_event(action, source=f"agent:{provider.name}", source_event_id=source.id)
        for action in auto_actions
    ]

    return {
        "proposal": proposal,
        "approval_request": approval_request,
        "dropped": dropped,
        "executed": executed,
        "conflicts": conflicts,
    }


@app.post("/project", status_code=201)
def init_project(project_in: ProjectIn) -> dict:
    event = Event(
        id=f"proj_{uuid.uuid4().hex[:12]}",
        type="project_initialized",
        timestamp=_now(),
        source="cli:init",
        # exclude_unset so a re-init only overwrites the fields actually
        # provided -- omitted fields keep their previous value (merge semantics).
        payload=project_in.model_dump(exclude_unset=True),
    )
    storage.write_event(event)
    return asdict(event)


@app.get("/project")
def get_project() -> dict:
    return project(storage.read_events()).meta


@app.post("/events", status_code=201)
def create_event(
    event_in: EventIn,
    provider: ExtractionProvider | None = Depends(get_provider_optional),
) -> dict:
    try:
        new_event = Event(**event_in.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    events = storage.read_events()
    state = project(events)

    try:
        apply_event(state, new_event)
    except ProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.write_event(new_event)

    # Email-reply approval: an inbound reply is the channel a human approves in.
    # If proposals are pending, resolve the reply against them first (so any
    # approved facts are already applied before we extract new facts from the
    # same reply). Degrades gracefully -- no provider or a failure just skips it.
    approvals = None
    if (
        config.email_approval()
        and new_event.type == "email_reply_received"
        and new_event.raw_text
        and provider is not None
    ):
        try:
            approvals = _resolve_approvals_from_reply(new_event, provider)
        except Exception as exc:  # provider/network failure -- don't fail the append
            approvals = {"error": f"approval resolution failed: {exc}"}

    # Auto-extraction: when a raw-input event lands, run extraction in the same
    # request so the system advances on its own. Degrades gracefully -- if no
    # provider is configured, or the provider fails, the event is still
    # appended and `extraction` reports why nothing ran.
    extraction = None
    if (
        config.auto_extract()
        and new_event.type in RAW_INPUT_TYPES
        and new_event.raw_text
    ):
        if provider is None:
            extraction = {"skipped": "no extraction provider configured"}
        else:
            try:
                extraction = _run_extraction(new_event, storage.read_events(), provider)
            except Exception as exc:  # provider/network failure -- don't fail the append
                extraction = {"error": f"auto-extraction failed: {exc}"}

    return {**asdict(new_event), "approvals": approvals, "extraction": extraction}


@app.get("/events")
def list_events() -> list[dict]:
    return [asdict(event) for event in storage.read_events()]


@app.get("/state")
def get_state() -> dict:
    events = storage.read_events()
    state = project(events)
    return serialize_state(state)


@app.post("/extract", status_code=201)
def extract(
    req: ExtractRequest,
    provider: ExtractionProvider = Depends(get_provider),
) -> dict:
    events = storage.read_events()

    source = next((e for e in events if e.id == req.source_event_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"event {req.source_event_id!r} not found")
    if source.type not in RAW_INPUT_TYPES or not source.raw_text:
        raise HTTPException(
            status_code=400,
            detail=f"event {req.source_event_id!r} is not a raw-input event with text",
        )

    try:
        return _run_extraction(source, events, provider)
    except HTTPException:
        raise
    except Exception as exc:  # provider/network failure -> 502
        raise HTTPException(status_code=502, detail=f"extraction failed: {exc}") from exc


@app.post("/review-state")
def review_state_endpoint() -> dict:
    events = storage.read_events()
    state = project(events)
    result = _review_state(state)

    issues = [
        {"rule": i.rule, "entity_type": i.entity_type, "entity_id": i.entity_id, "detail": i.detail}
        for i in result.issues
    ]

    if not result.actions:
        return {"issues": issues, "executed": [], "proposal": None}

    auto_actions = [a for a in result.actions if a["category"] == "info_request"]
    consequential_actions = [a for a in result.actions if a["category"] == "consequential"]

    executed = [
        _write_outbound_event(a, source="agent:review", source_event_id="review-state")
        for a in auto_actions
    ]

    proposal = None
    if consequential_actions:
        actions_with_prov = [
            {**a, "provenance": {"asserted_by": "review:rules"}}
            for a in consequential_actions
        ]
        proposal_event = Event(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            type="agent_proposal",
            timestamp=_now(),
            source="review:rules",
            payload={
                "provider": "review:rules",
                "source_event_id": "review-state",
                "deltas": [],
                "actions": actions_with_prov,
            },
        )
        storage.write_event(proposal_event)
        proposal = asdict(proposal_event)
        _ask_for_approval(proposal_event, storage.read_events())

    return {"issues": issues, "executed": executed, "proposal": proposal}


@app.get("/proposals")
def list_proposals() -> list[dict]:
    return [asdict(e) for e in _pending_proposals(storage.read_events())]


@app.post("/proposals/{proposal_id}/approve", status_code=201)
def approve_proposal(proposal_id: str) -> dict:
    events = storage.read_events()

    proposal = next(
        (e for e in events if e.type == "agent_proposal" and e.id == proposal_id), None
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")

    try:
        approval = _apply_approval(proposal, events, source="approval")
    except ProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return asdict(approval)
