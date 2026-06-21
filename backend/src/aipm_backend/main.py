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
                                      auto-execute (message_sent);
                                      consequential ones go into a proposal.
                                      Returns: {issues, executed, proposal}
  POST /extract                    -- run extraction on a raw event, write an
                                      agent_proposal (no state change).
                                      info_request actions execute (stub)
                                      immediately and log an outbound event
                                      (message_sent); only consequential
                                      actions stay in the proposal, awaiting
                                      approval.
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
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException

from aipm.approval import PendingProposal, build_approval_prompt
from aipm.conflicts import (
    ConflictWarning,
    author_clarifiable,
    detect_conflicts,
    state_inconsistencies,
)
from aipm.conversation import build_message_prompt
from aipm.entities import outbound_event_type
from aipm.events import RAW_INPUT_TYPES, Event
from aipm.extraction import build_prompt, filter_grounded
from aipm.extraction.providers import ExtractionProvider
from aipm.projection import ProjectionError, apply_event, project
from aipm.review import review_state as _review_state
from aipm.revision import build_revision_prompt
from aipm.schema import normalize_payload

from aipm_backend import config, storage
from aipm_backend.channels import get_channel
from aipm_backend.extraction import get_provider, get_provider_optional
from aipm_backend.models import EventIn, ExtractRequest, ProjectIn, serialize_state

app = FastAPI(title="AI PM Backend")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_thread_id() -> str:
    """Mint a conversation id. One thread per outreach; reused for follow-ups."""
    return f"thr_{uuid.uuid4().hex[:12]}"


def _write_outbound_event(
    action: dict, source: str, source_event_id: str, thread_id: str | None = None
) -> dict:
    """Record an action's (stubbed) execution as an outbound event.

    Communications (those that resolve to `message_sent`) are delivered through
    the configured `Channel` and stamped with `channel`, `thread_id`, and the
    channel-side `message_id`, so the conversation can be reconstructed by
    `thread_id`. World-effects (ticket/flag/escalation) are logged as-is.
    Returns the written event as a dict.
    """
    out_type = outbound_event_type(action["type"], action["category"])
    payload = {**action, "source_event_id": source_event_id}

    if out_type == "message_sent":
        inner = dict(action.get("payload", {}))
        tid = thread_id or inner.get("thread_id") or _new_thread_id()
        channel = get_channel()
        message_id = channel.send(
            thread_id=tid,
            recipient=inner.get("to"),
            text=inner.get("body", ""),
            subject=inner.get("subject"),
        )
        inner.update({"channel": channel.name, "thread_id": tid, "message_id": message_id})
        payload = {**action, "payload": inner, "source_event_id": source_event_id}

    event = Event(
        id=f"out_{uuid.uuid4().hex[:12]}",
        type=out_type,
        timestamp=_now(),
        source=source,
        payload=payload,
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
        f = delta.get("fields", {})
        # Prefer a human label (title/description/name) over the internal id, so
        # both the human reading the request and the resolver matching a reply
        # see plain words, not entity ids.
        label = f.get("title") or f.get("description") or f.get("name") or delta.get("entity_id")
        parts.append(f"{delta.get('op')} {delta.get('entity_type')} '{label}'")
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
    """Who to ask for sign-off -- always ONE person, never the whole team.

    A proposal may name its own approver (`payload["approver"]`) -- used for the
    owner-confirmation stage, where each task owner signs off on their own
    ticket. Absent that, approval is a project-manager decision: PM, then tech
    lead, then a single team member. We never fan an approval out to the team.
    """
    if payload.get("approver"):
        return payload["approver"]
    meta = project(events).meta
    return (
        meta.get("pm")
        or meta.get("tech_lead")
        or (meta.get("team") or ["team"])[0]
    )


def _ask_for_approval(proposal: Event, events: list[Event]) -> dict:
    """Open a thread (stub) asking a human to authorize a pending proposal.

    The proposal carries a `thread_id`; the request and any later follow-ups or
    composed replies all ride that same thread, so a reply on it maps straight
    back to this proposal.
    """
    summary = _summarize_proposal_payload(proposal.payload)
    thread_id = proposal.payload.get("thread_id")
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": _approval_recipient(events, proposal.payload),
            "subject": f"Approval needed: {summary}",
            "body": (
                f"I'd like to proceed with: {summary}. "
                f"Reply to approve or decline."
            ),
            "proposal_id": proposal.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source="agent:approval-request", source_event_id=proposal.id, thread_id=thread_id
    )


def _ask_author_to_clarify(
    proposal: Event, conflicts: list[ConflictWarning], events: list[Event]
) -> dict:
    """Ask the message author to resolve a claim that contradicts known state,
    before the proposal ever escalates to the PM.

    The proposal's `approver` is the author, so their reply resolves against it
    through the normal reply path, and the nudge/escalation ladder still
    backstops to the PM if they go quiet. Worded as a question, not an approval
    -- the point is to dig into the contradiction, not rubber-stamp it. Uses the
    `agent:approval-request` source so the follow-up ladder recognizes that
    we've already reached out about this proposal.
    """
    summary = _summarize_proposal_payload(proposal.payload)
    thread_id = proposal.payload.get("thread_id")
    detail = " ".join(w.detail for w in conflicts)
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": _approval_recipient(events, proposal.payload),
            "subject": f"Quick check before I record this: {summary[:50]}",
            "body": (
                f"I picked up from your update: {summary}. Before I record it, "
                f"something doesn't line up -- {detail} "
                "Is this genuinely complete, or is there still a piece pending? "
                "Reply and I'll capture it correctly."
            ),
            "proposal_id": proposal.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source="agent:approval-request", source_event_id=proposal.id, thread_id=thread_id
    )


def _apply_approval(
    proposal: Event,
    events: list[Event],
    source: str,
    apply_only: list[str] | None = None,
    acknowledged_conflicts: list[dict] | None = None,
) -> Event:
    """Write a human_approval that applies a proposal's deltas/actions to state,
    then execute (stub) its consequential actions. Shared by the explicit
    approve endpoint and the email-reply approval path.

    `apply_only` (a list of entity ids) authorizes a SUBSET of a bundled
    proposal's deltas -- the human approved some changes and declined others
    (e.g. "yes it's done, but keep that dependency"). Empty/None applies the
    whole proposal, the normal case. The deltas it drops are simply not applied;
    the human_approval records exactly what was applied.

    `acknowledged_conflicts`, when set, records that the human knowingly signed
    off on an inconsistency the agent flagged (e.g. a task done while it keeps an
    active dependency). It is stamped on the event so the log shows the
    contradiction was accepted on purpose, never committed silently.
    """
    deltas = proposal.payload.get("deltas", [])
    if apply_only:
        deltas = [d for d in deltas if d.get("entity_id") in apply_only]
    approval = Event(
        id=f"appr_{uuid.uuid4().hex[:12]}",
        type="human_approval",
        timestamp=_now(),
        source=source,
        payload={
            "deltas": deltas,
            "actions": proposal.payload.get("actions", []),
            "approves": proposal.id,
            **({"partial": True} if apply_only else {}),
            **({"acknowledged_conflicts": acknowledged_conflicts} if acknowledged_conflicts else {}),
        },
    )

    state = project(events)
    apply_event(state, approval)  # raises ProjectionError on a bad payload
    storage.write_event(approval)

    for action in approval.payload["actions"]:
        _write_outbound_event(action, source="agent:approved", source_event_id=approval.id)
    return approval


def _is_ticket_batch(proposal: Event) -> bool:
    """True if this proposal's actions still need a per-owner confirmation.

    A ticket batch is the first gate: the PM authorizes opening tickets, but
    each ticket carries `requires_owner_confirmation`, so approving the batch
    does NOT open anything -- it fans out to the owners for the final say.
    """
    return any(
        a.get("payload", {}).get("requires_owner_confirmation")
        for a in proposal.payload.get("actions", [])
    )


def _approve_ticket_batch(batch: Event, source: str) -> dict:
    """PM signs off on the batch -> fan out one confirmation proposal per owner.

    The batch itself is recorded as approved (so it leaves the pending set) but
    applies nothing: no ticket opens yet. For each owner we mint a fresh
    proposal carrying just their ticket(s) and email THEM for the final
    confirmation -- their reply (a normal email approval) is what opens it,
    so the nudge/escalation ladder covers them too.
    """
    # Record the batch as approved, but with empty payload: nothing applied,
    # nothing executed -- the tickets are deferred to owner confirmation.
    approval = Event(
        id=f"appr_{uuid.uuid4().hex[:12]}",
        type="human_approval",
        timestamp=_now(),
        source=source,
        payload={"deltas": [], "actions": [], "approves": batch.id},
    )
    storage.write_event(approval)

    by_owner: dict[str, list[dict]] = defaultdict(list)
    for action in batch.payload.get("actions", []):
        owner = action.get("payload", {}).get("owner") or "team"
        clean = deepcopy(action)
        clean["payload"].pop("requires_owner_confirmation", None)
        by_owner[owner].append(clean)

    fanned: list[dict] = []
    for owner, actions in by_owner.items():
        proposal = Event(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            type="agent_proposal",
            timestamp=_now(),
            source="agent:ticket-confirm",
            payload={
                "deltas": [],
                "actions": actions,
                "approver": owner,  # the owner has the final say on their ticket(s)
                "provider": "ticket-planner",
                "source_event_id": batch.id,
                "thread_id": _new_thread_id(),  # each owner gets their own thread
            },
        )
        storage.write_event(proposal)
        request = _ask_for_approval(proposal, storage.read_events())
        fanned.append({
            "proposal_id": proposal.id,
            "owner": owner,
            "tickets": [a.get("payload", {}).get("title", a["type"]) for a in actions],
            "request": request,
        })

    return {"approval": asdict(approval), "fanned_out": fanned}


def _resolve_proposal_approval(
    proposal: Event,
    events: list[Event],
    source: str,
    apply_only: list[str] | None = None,
    acknowledged_conflicts: list[dict] | None = None,
):
    """Approve a proposal: fan out if it's a ticket batch, else apply it.

    Returns the human_approval Event for a normal approval, or a fan-out dict
    `{approval, fanned_out}` for a ticket batch. `apply_only` authorizes a subset
    of a bundled proposal's deltas (ignored for ticket batches, which fan out);
    `acknowledged_conflicts` records an inconsistency the human signed off on.
    """
    if _is_ticket_batch(proposal):
        return _approve_ticket_batch(proposal, source)
    return _apply_approval(
        proposal, events, source,
        apply_only=apply_only, acknowledged_conflicts=acknowledged_conflicts,
    )


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


def _apply_amendment(proposal: Event, amended_status: str, source: str) -> Event:
    """Record a corrected, partial outcome instead of the proposal's optimistic claim.

    Used when the author clarifies that a "done" claim is only partially true:
    we keep the truthful status (`amended_status`) on the Task(s) the proposal
    targeted, and DROP its side-effects -- e.g. resolving dependencies -- which
    only held if the work were really finished. Leaving those dependencies
    active keeps the project state honest. The proposal leaves the pending set.
    """
    corrected = [
        {**d, "fields": {**d.get("fields", {}), "status": amended_status}}
        for d in proposal.payload.get("deltas", [])
        if d.get("entity_type") == "Task"
    ]
    approval = Event(
        id=f"appr_{uuid.uuid4().hex[:12]}",
        type="human_approval",
        timestamp=_now(),
        source=source,
        # No actions: the optimistic action set doesn't hold for a partial done.
        payload={"deltas": corrected, "actions": [], "approves": proposal.id, "amended": True},
    )
    storage.write_event(approval)
    return approval


def _ask_for_revision_approval(proposal: Event, events: list[Event]) -> dict:
    """Ask the PM to approve a structural correction the agent now believes is right.

    Unlike a routine approval, this is the agent admitting its own model was
    wrong: it leads with the contradiction (`rationale`) and proposes the fix.
    No `approver` is set on a revision, so `_approval_recipient` routes it to the
    project manager -- the owner of the project model -- not the author.
    """
    summary = _summarize_proposal_payload(proposal.payload)
    rationale = proposal.payload.get("rationale", "")
    thread_id = proposal.payload.get("thread_id")
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": _approval_recipient(events, proposal.payload),
            "subject": f"I think I modeled this wrong -- proposed correction: {summary[:50]}",
            "body": (
                "New information suggests the project model I recorded is wrong"
                + (f": {rationale} " if rationale else ". ")
                + f"I'd like to correct it: {summary}. Reply to approve or decline."
            ),
            "proposal_id": proposal.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source="agent:approval-request", source_event_id=proposal.id, thread_id=thread_id
    )


def _propose_model_revision(
    original: Event, reply: Event, provider: ExtractionProvider, events: list[Event], reason: str
) -> dict | None:
    """Draft a structural correction from a reply that contradicts the model.

    The resolver flagged this reply as `revise`: it says the recorded model
    itself is wrong (a dependency that shouldn't exist, a fact wired up wrongly),
    which no status change can fix. We ask the model for corrective deltas
    (`create`/`update`/`delete`) grounded in the reply, wrap them in a
    `model_revision` proposal routed to the PM, and supersede the original.
    Returns a summary dict, or None if no concrete correction could be drafted.
    """
    state = project(events)
    original_summary = _summarize_proposal_payload(original.payload)
    prompt = build_revision_prompt(reply.raw_text, original_summary, state)
    result = provider.extract(prompt)  # same JSON shape as extraction

    grounded, _dropped = filter_grounded(result, reply.raw_text)
    payload = normalize_payload(grounded.to_payload(asserted_by=f"{provider.name}:revision"))
    # Only keep deltas we can actually apply (delete/update need the entity to
    # exist); a revision that reconciles to nothing is not worth bothering the PM.
    payload["deltas"], _unclear = _unapplicable_deltas(payload["deltas"], state)
    if not payload["deltas"]:
        return None

    thread_id = _new_thread_id()
    proposal = Event(
        id=f"prop_{uuid.uuid4().hex[:12]}",
        type="agent_proposal",
        timestamp=_now(),
        source=f"revision:{provider.name}",
        payload={
            "deltas": payload["deltas"],
            "actions": [],  # a revision only corrects state; it takes no side-effects
            "kind": "model_revision",
            "supersedes": original.id,
            "rationale": reason,
            "source_event_id": reply.id,
            "provider": provider.name,
            "thread_id": thread_id,
            # Who flagged the contradiction, and the thread they're reachable on,
            # so we can close the loop with them once the PM decides.
            "raised_by": reply.source,
            "raised_thread_id": original.payload.get("thread_id"),
            # No "approver": routes to the PM, the owner of the project model.
        },
    )
    storage.write_event(proposal)
    # The original claim was based on the now-corrected model; retire it so it
    # leaves the pending set, pointing at the revision that replaces it.
    _reject_proposal(original, source=f"email:{reply.source}", reason=f"superseded by revision {proposal.id}")
    request = _ask_for_revision_approval(proposal, storage.read_events())
    return {
        "proposal_id": proposal.id,
        "supersedes": original.id,
        "summary": _summarize_proposal_payload(proposal.payload),
        "request": request,
    }


def _describe_deltas(deltas: list[dict]) -> str:
    """Plain-words description of a set of deltas, for a message to a human."""
    parts: list[str] = []
    for d in deltas:
        f = d.get("fields", {})
        label = f.get("title") or f.get("description") or f.get("name") or d.get("entity_id")
        parts.append(f"{d.get('op')} {d.get('entity_type')} '{label}'")
    return "; ".join(parts)


def _notify_revision_outcome(revision: Event, applied_ids: list[str], reason: str) -> dict | None:
    """Close the loop with whoever raised a contradiction, once the PM has ruled.

    Splits the revision's deltas into what was applied vs. dropped and tells the
    original author which way it went and why. Sent on the author's existing
    thread; invites a fresh note (which re-enters extraction) if they still
    disagree -- so a declined correction is never a silent dead end.
    """
    raised_by = revision.payload.get("raised_by")
    if not raised_by:
        return None
    deltas = revision.payload.get("deltas", [])
    applied = [d for d in deltas if d.get("entity_id") in applied_ids]
    dropped = [d for d in deltas if d.get("entity_id") not in applied_ids]
    thread_id = revision.payload.get("raised_thread_id")

    if not dropped:  # fully applied -- a clean confirmation back to the author
        body = (
            f"Thanks for flagging this -- I've corrected the model as you described: "
            f"{_describe_deltas(applied)}."
        )
    else:
        kept = f"I applied: {_describe_deltas(applied)}. " if applied else ""
        why = reason.strip().rstrip(".") if reason else ""
        body = (
            f"I raised your correction with the project manager. {kept}"
            f"They decided to keep the existing model on: {_describe_deltas(dropped)}"
            + (f" -- {why}." if why else ".")
            + " If you still think that's wrong, send a new note and I'll take another look."
        )
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": raised_by,
            "subject": "Update on the correction you flagged",
            "body": body,
            "proposal_id": revision.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source="agent:revision-outcome", source_event_id=revision.id, thread_id=thread_id
    )


def _close_revision_loop(revision: Event, applied_ids: list[str], reason: str) -> dict | None:
    """Notify the author iff this proposal is a model_revision; else a no-op."""
    if revision.payload.get("kind") != "model_revision":
        return None
    return _notify_revision_outcome(revision, applied_ids, reason)


def _resolver_summary(payload: dict) -> str:
    """Like `_summarize_proposal_payload`, but tags each change with its entity-id
    [handle] so the resolver can authorize a subset via `apply_only`. Used only
    for the model's view; the human-facing approval emails stay clean."""
    parts: list[str] = []
    for action in payload.get("actions", []):
        ap = action.get("payload", {})
        label = ap.get("title") or ap.get("subject") or ap.get("reason") or action.get("type")
        handle = ap.get("entity_id") or ap.get("task_id") or action.get("type")
        parts.append(f"[{handle}] {action.get('type')} ({label})")
    for delta in payload.get("deltas", []):
        f = delta.get("fields", {})
        label = f.get("title") or f.get("description") or f.get("name") or delta.get("entity_id")
        parts.append(f"[{delta.get('entity_id')}] {delta.get('op')} {delta.get('entity_type')} '{label}'")
    return "; ".join(parts) if parts else "(empty proposal)"


def _has_approval_request(proposal_id: str, events: list[Event]) -> bool:
    """True if an approval-request message was already sent for this proposal."""
    return any(
        e.type == "message_sent"
        and e.source == "agent:approval-request"
        and e.payload.get("payload", {}).get("proposal_id") == proposal_id
        for e in events
    )


# Follow-ups after the initial approval request, in order. The reply state
# machine uses how many have already gone out to decide the next step:
# 0 sent -> nudge, 1 sent -> escalate, >=2 -> go quiet.
_FOLLOWUP_SOURCES = ("agent:approval-nudge", "agent:approval-escalation")


def _followup_count(proposal_id: str, events: list[Event]) -> int:
    """How many follow-up messages (nudge + escalation) were sent for this proposal."""
    return sum(
        1 for e in events
        if e.type == "message_sent"
        and e.source in _FOLLOWUP_SOURCES
        and e.payload.get("payload", {}).get("proposal_id") == proposal_id
    )


# Composed-reply source: model-authored, info_request-only messages the agent
# posts into a thread when a reply is ambiguous (capped per thread).
_COMPOSE_SOURCE = "agent:compose"


def _compose_count(proposal_id: str, events: list[Event]) -> int:
    """How many model-composed replies the agent has posted on this thread."""
    return sum(
        1 for e in events
        if e.type == "message_sent"
        and e.source == _COMPOSE_SOURCE
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
    """Send (stub) a follow-up message about an unaddressed pending proposal.

    `to` overrides the default recipient (used for escalations that must go to
    PM/tech lead rather than the original action target).
    """
    thread_id = proposal.payload.get("thread_id")
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": to or _approval_recipient(events, proposal.payload),
            "subject": subject,
            "body": body,
            "proposal_id": proposal.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source=source, source_event_id=proposal.id, thread_id=thread_id
    )


def _thread_history(thread_id: str, events: list[Event]) -> list[dict]:
    """Reconstruct a thread as a chronological list of {sender, text} messages."""
    history: list[dict] = []
    for e in events:
        if e.type == "message_sent":
            inner = e.payload.get("payload", {})
            if inner.get("thread_id") == thread_id:
                history.append({"sender": "agent", "text": inner.get("body", "")})
        elif e.type == "message_received":
            if e.payload.get("thread_id") == thread_id and e.raw_text:
                history.append({"sender": e.source, "text": e.raw_text})
    return history


def _compose_thread_reply(
    proposal: Event, reply: Event, provider: ExtractionProvider, events: list[Event]
) -> dict | None:
    """Let the model compose ONE short info_request reply in the proposal's thread.

    Returns the written message_sent event dict if the model chose to send, else
    None (model had nothing useful to add, or the provider failed). Never takes a
    consequential action -- this is conversation only.
    """
    thread_id = proposal.payload.get("thread_id")
    if not thread_id:
        return None
    summary = _summarize_proposal_payload(proposal.payload)
    prompt = build_message_prompt(summary, _thread_history(thread_id, events))
    try:
        composed = provider.compose_message(prompt)
    except Exception:  # provider/network failure -> fall back to the ladder
        return None
    if not composed.send or not composed.text.strip():
        return None
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": reply.source,
            "subject": f"Re: {summary[:60]}",
            "body": composed.text.strip(),
            "proposal_id": proposal.id,
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source=_COMPOSE_SOURCE, source_event_id=reply.id, thread_id=thread_id
    )


# Reminder for a reply that lands on a thread whose conversation is already
# closed (nothing pending). We point the sender at the one channel that DOES
# reopen things -- a fresh note -- but only on a thread we actually used, and at
# most a couple of times, so a "thanks!" never turns into nagging.
_REOPEN_HINT_SOURCE = "agent:reopen-hint"
_MAX_REOPEN_HINTS = 2


def _maybe_remind_new_note(reply: Event, events: list[Event]) -> dict | None:
    """If a reply landed on a closed thread, remind the sender to open a new note.

    A reply on a thread with no pending request has nothing to resolve, so it
    would otherwise be dropped silently (threaded replies are never re-mined for
    new actions). We nudge the sender to send a fresh note -- which DOES re-enter
    extraction -- but stay quiet unless the agent actually used this thread, and
    never send more than `_MAX_REOPEN_HINTS` reminders on it.
    """
    thread_id = reply.payload.get("thread_id")
    agent_spoke = any(
        e.type == "message_sent" and e.payload.get("payload", {}).get("thread_id") == thread_id
        for e in events
    )
    if not agent_spoke:
        return None
    hints = sum(
        1 for e in events
        if e.type == "message_sent" and e.source == _REOPEN_HINT_SOURCE
        and e.payload.get("payload", {}).get("thread_id") == thread_id
    )
    if hints >= _MAX_REOPEN_HINTS:
        return None  # already reminded enough -- go quiet
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": reply.source,
            "subject": "This thread is closed -- send a new note to reopen",
            "body": (
                "Thanks for your message. This conversation is already closed, so "
                "there's nothing here for me to act on. If you'd like me to look "
                "into it, please send a NEW note (not a reply to this thread) and "
                "I'll take it from there."
            ),
            "thread_id": thread_id,
        },
    }
    return _write_outbound_event(
        action, source=_REOPEN_HINT_SOURCE, source_event_id=reply.id, thread_id=thread_id
    )


# Conflict-acknowledgment gate: before committing an approval, we check whether
# the resulting state would be inconsistent (e.g. a task done while it keeps an
# active dependency). If so, we don't apply silently -- we ask the approver to
# accept it explicitly, and only then record it with `acknowledged_conflicts`.
_CONFLICT_ACK_SOURCE = "agent:conflict-ack"


def _conflicts_payload(warnings: list[ConflictWarning]) -> list[dict]:
    return [{"type": w.type, "entity_id": w.entity_id, "detail": w.detail} for w in warnings]


def _approval_inconsistencies(
    proposal: Event, apply_only: list[str], state
) -> list[ConflictWarning]:
    """Inconsistencies the would-be state holds after applying this approval.

    Simulates the exact deltas to apply (respecting `apply_only`) on a copy of
    current state, then checks end-state invariants. Because it works on the
    RESULTING state, a full revision that deletes the offending dependency comes
    out clean, while a partial approval that keeps it does not.
    """
    deltas = [
        d for d in proposal.payload.get("deltas", [])
        if not apply_only or d.get("entity_id") in apply_only
    ]
    if not deltas:
        return []
    post = deepcopy(state)
    sim = Event(
        id="sim", type="human_approval", timestamp=_now(), source="sim",
        payload={"deltas": deltas, "actions": []},
    )
    try:
        apply_event(post, sim)
    except ProjectionError:
        return []  # a bad delta -- let the real apply surface it, don't gate here
    return state_inconsistencies(post)


def _ask_conflict_ack(
    proposal: Event, warnings: list[ConflictWarning], apply_only: list[str], to: str
) -> dict:
    """Ask the approver to knowingly accept (or fix) an inconsistency they'd commit.

    Stores the exact subset (`apply_only`) and the flagged conflicts on the
    request, so the follow-up confirmation applies precisely what was warned
    about and stamps it as acknowledged. Offers the coherent alternative too.
    """
    detail = " ".join(w.detail for w in warnings)
    thread_id = proposal.payload.get("thread_id")
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": to,
            "subject": "Before I record this -- a contradiction to confirm",
            "body": (
                f"Heads up: {detail} That's inconsistent -- a task can't be finished "
                "while it still depends on unfinished work. If it really is done, I "
                "can mark that dependency resolved instead. Reply 'record it anyway' "
                "to accept it as-is, or tell me how you'd like it fixed."
            ),
            "proposal_id": proposal.id,
            "thread_id": thread_id,
            # Remembered so the confirmation applies the same subset, acknowledged.
            "apply_only": apply_only or [],
            "ack_conflicts": _conflicts_payload(warnings),
        },
    }
    return _write_outbound_event(
        action, source=_CONFLICT_ACK_SOURCE, source_event_id=proposal.id, thread_id=thread_id
    )


def _pending_conflict_ack(proposal_id: str, events: list[Event]) -> dict | None:
    """The subset+conflicts we last asked this proposal's approver to confirm.

    Its presence means we've already gated this proposal once, so the next
    approve reply is the human's explicit acknowledgment -- apply it now.
    """
    for e in reversed(events):
        if e.type == "message_sent" and e.source == _CONFLICT_ACK_SOURCE:
            inner = e.payload.get("payload", {})
            if inner.get("proposal_id") == proposal_id:
                return {"apply_only": inner.get("apply_only", []),
                        "conflicts": inner.get("ack_conflicts", [])}
    return None


def _resolve_approvals_from_reply(
    reply: Event, provider: ExtractionProvider
) -> dict | None:
    """Map a human's email reply onto pending proposals and act on it.

    Runs only when proposals are actually pending. The resolver distinguishes a
    real authorization ("yes, open the ticket") from merely answering a question
    ("yes, we need PayPal"), so a stray "yes" never fires an action.

    A reply may arrive ON a thread (`thread_id` in its payload) -- the channel
    knows which conversation it belongs to. When it does, we scope resolution to
    that thread's proposal alone, so the model only judges the one request the
    person is actually answering (and the reply is never mined for new actions --
    see the auto-extraction guard in create_event).

    Proposals this reply did not address (and that we already asked about) are
    chased. On a thread, the agent first tries a short model-composed reply (up
    to the per-thread cap); off a thread, or once the cap is hit, it falls back
    to the templated ladder: a nudge on the first miss, an escalation on the
    second, then quiet.
    """
    thread_id = reply.payload.get("thread_id")
    pending = _pending_proposals(storage.read_events())
    if thread_id:
        pending = [p for p in pending if p.payload.get("thread_id") == thread_id]
    if not pending:
        return None

    prompt = build_approval_prompt(
        reply.raw_text,
        [PendingProposal(id=p.id, summary=_resolver_summary(p.payload)) for p in pending],
    )
    result = provider.resolve_approvals(prompt)

    by_id = {p.id: p for p in pending}
    approved: list[dict] = []
    rejected: list[dict] = []
    amended: list[dict] = []
    revised: list[dict] = []
    gated: list[dict] = []
    fanned_out: list[dict] = []
    resolved_ids: set[str] = set()
    for res in result.resolutions:
        target = by_id.get(res.proposal_id)
        if target is None:
            continue
        if res.decision == "approve":
            events_now = storage.read_events()
            prior = _pending_conflict_ack(target.id, events_now)
            if prior is None:
                # First approve: would committing this leave state inconsistent?
                warnings = _approval_inconsistencies(
                    target, res.apply_only, project(events_now)
                )
                if warnings:
                    # Gate: don't apply. Ask the approver to accept it knowingly.
                    # Stays pending; their next 'yes' is the acknowledgment.
                    _ask_conflict_ack(target, warnings, res.apply_only, to=reply.source)
                    gated.append({"proposal_id": target.id,
                                  "conflicts": _conflicts_payload(warnings)})
                    resolved_ids.add(res.proposal_id)  # handled now; suppress chase
                    continue
            apply_only = prior["apply_only"] if prior else res.apply_only
            acknowledged = prior["conflicts"] if prior else None
            outcome = _resolve_proposal_approval(
                target, events_now, source=f"email:{reply.source}",
                apply_only=apply_only, acknowledged_conflicts=acknowledged,
            )
            if isinstance(outcome, dict):  # ticket batch -> fanned out to owners
                approved.append(outcome["approval"])
                fanned_out.extend(outcome["fanned_out"])
            else:
                approved.append(asdict(outcome))
                # Close the loop with whoever raised a model revision: tell them
                # what the PM applied vs. kept (a partial approve drops some).
                all_ids = [d.get("entity_id") for d in target.payload.get("deltas", [])]
                applied_ids = apply_only or all_ids
                _close_revision_loop(target, applied_ids, res.reason_span)
            resolved_ids.add(res.proposal_id)
        elif res.decision == "reject":
            rejection = _reject_proposal(target, source=f"email:{reply.source}", reason=res.reason_span)
            rejected.append(asdict(rejection))
            # A declined revision is not a dead end: let the author know why.
            _close_revision_loop(target, applied_ids=[], reason=res.reason_span)
            resolved_ids.add(res.proposal_id)
        elif res.decision == "amend" and res.amended_status:
            amendment = _apply_amendment(
                target, res.amended_status, source=f"email:{reply.source}"
            )
            amended.append(asdict(amendment))
            resolved_ids.add(res.proposal_id)
        elif res.decision == "revise":
            # The reply says the model itself is wrong: draft a structural
            # correction for the PM. If we can't draft a concrete one, leave the
            # proposal pending so the chase loop still follows up.
            revision = _propose_model_revision(
                target, reply, provider, storage.read_events(), reason=res.reason_span
            )
            if revision is not None:
                revised.append(revision)
                resolved_ids.add(res.proposal_id)
        # "defer" leaves the proposal pending -- handled by the chase loop below.

    # Chase the proposals this reply ignored. On a thread, try a short
    # model-composed reply first (capped per thread); otherwise fall back to the
    # templated ladder: nudge once, escalate on the second miss, then go quiet
    # (proposal stays pending, visible in /proposals).
    composed: list[dict] = []
    nudged: list[dict] = []
    escalated: list[dict] = []
    threaded = bool(thread_id)
    for proposal in pending:
        if proposal.id in resolved_ids:
            continue
        current = storage.read_events()
        if not _has_approval_request(proposal.id, current):
            continue  # never asked about this one yet -- nothing to follow up on
        summary = _summarize_proposal_payload(proposal.payload)

        # In-thread, ambiguous reply: let the model say something short, as long
        # as we're under the per-thread turn cap. info_request only.
        if (
            threaded
            and config.model_messages()
            and _compose_count(proposal.id, current) < config.max_thread_turns()
        ):
            event = _compose_thread_reply(proposal, reply, provider, current)
            if event is not None:
                composed.append({"proposal_id": proposal.id, "summary": summary})
                continue  # said our piece; ladder waits for the next miss

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
        "amended": amended,
        "revised": revised,
        "gated": gated,
        "fanned_out": fanned_out,
        "composed": composed,
        "nudged": nudged,
        "escalated": escalated,
        "resolutions": result.to_dict()["resolutions"],
    }


def _unapplicable_deltas(deltas: list[dict], state) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Split deltas into (applicable, unclear) against current state.

    Unclear = the model referenced something we can't reconcile: an `update` or
    `delete` of an entity that doesn't exist, or a `create` of one that already
    does. Rather than let it fail at approval time (or silently drop it), we pull
    it out so the caller can ask the author what they meant.
    """
    applicable: list[dict] = []
    unclear: list[tuple[dict, str]] = []
    for d in deltas:
        exists = d["entity_id"] in state.entities.get(d["entity_type"], {})
        if d["op"] in ("update", "delete") and not exists:
            unclear.append((d, f"no {d['entity_type']} '{d['entity_id']}' exists yet to {d['op']}"))
        elif d["op"] == "create" and exists:
            unclear.append((d, f"{d['entity_type']} '{d['entity_id']}' already exists"))
        else:
            applicable.append(d)
    return applicable, unclear


def _send_clarification(source: Event, delta: dict, reason: str) -> dict:
    """Message the author (stub) to ask what they meant by an unreconcilable delta."""
    action = {
        "type": "send_message",
        "category": "info_request",
        "payload": {
            "to": source.source,
            "subject": f"Quick clarification on {delta['entity_type']} '{delta['entity_id']}'",
            "body": (
                f"I couldn't record one change from your message -- {reason}. "
                "Could you confirm what you meant so I can capture it correctly?"
            ),
            "entity_id": delta["entity_id"],
        },
    }
    return _write_outbound_event(action, source="agent:clarification", source_event_id=source.id)


def _run_extraction(source: Event, events: list[Event], provider: ExtractionProvider) -> dict:
    """Extract from one raw event: write a proposal for anything needing
    approval, auto-execute info_request actions, and surface conflicts.

    Pure of HTTP concerns -- callers (POST /extract, the POST /events auto
    path) decide how to handle a provider failure (it propagates here).
    Returns: {proposal, dropped, executed, conflicts, clarifications}.
    """
    state = project(events)
    prompt = build_prompt(source.raw_text, state)
    result = provider.extract(prompt)

    grounded, dropped = filter_grounded(result, source.raw_text)
    payload = grounded.to_payload(asserted_by=provider.name)

    # Coerce the model's free-form field/payload names to the canonical schema so
    # the deterministic safety nets (review, conflicts) reliably engage -- the
    # model is told the canonical names in the prompt, this guarantees them.
    payload = normalize_payload(payload)

    # Deltas we can't reconcile against state become clarification emails to the
    # author, not silent failures -- the rest of the proposal proceeds normally.
    payload["deltas"], unclear = _unapplicable_deltas(payload["deltas"], state)
    clarifications = [
        {
            "entity_type": d["entity_type"],
            "entity_id": d["entity_id"],
            "reason": reason,
            "request": _send_clarification(source, d, reason),
        }
        for d, reason in unclear
    ]

    raw_conflicts = detect_conflicts(payload["deltas"], state)
    conflicts = [
        {"type": w.type, "entity_id": w.entity_id, "detail": w.detail}
        for w in raw_conflicts
    ]

    # When the author's own input contradicts known state ("done" while still
    # blocked, a deadline pulled earlier, a risk quietly downgraded), check back
    # with THEM before this ever reaches the PM. Setting the proposal's approver
    # to the author re-aims the request at them; the whole proposal rides along
    # (splitting off the contradicting delta would leave state half-applied),
    # and the nudge/escalation ladder still backstops to the PM if they go quiet.
    author_conflicts = author_clarifiable(raw_conflicts)
    if author_conflicts:
        payload["approver"] = source.source

    # `info_request` actions are routine info-gathering the agent does on its
    # own -- execute (stub) them immediately and log the outbound event, with
    # no human_approval. `consequential` actions stay in the proposal,
    # awaiting approval.
    auto_actions = [a for a in payload["actions"] if a["category"] == "info_request"]
    payload["actions"] = [a for a in payload["actions"] if a["category"] == "consequential"]
    payload["source_event_id"] = source.id
    payload["provider"] = provider.name
    payload["thread_id"] = _new_thread_id()  # the conversation this proposal owns

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
        # If the author contradicted state, ask THEM to clarify first instead.
        if author_conflicts:
            approval_request = _ask_author_to_clarify(
                proposal_event, author_conflicts, storage.read_events()
            )
        else:
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
        "clarifications": clarifications,
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


@app.post("/project/close", status_code=201)
def close_project(body: dict = {}) -> dict:
    """Mark the project as closed. Extraction is rejected on closed projects.

    Accepts an optional JSON body with a `reason` string for the audit trail.
    """
    events = storage.read_events()
    if project(events).meta.get("status") == "closed":
        raise HTTPException(status_code=409, detail="project is already closed")
    event = Event(
        id=f"close_{uuid.uuid4().hex[:12]}",
        type="project_closed",
        timestamp=_now(),
        source="cli:close",
        payload={"reason": body.get("reason", "")} if isinstance(body, dict) else {},
    )
    storage.write_event(event)
    return {"closed": True, "event_id": event.id}


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

    # Message-reply approval: an inbound reply is the channel a human approves
    # in. If proposals are pending, resolve the reply against them first (so any
    # approved facts are already applied before we extract new facts from the
    # same reply). Degrades gracefully -- no provider or a failure just skips it.
    approvals = None
    if (
        config.message_approval()
        and new_event.type == "message_received"
        and new_event.raw_text
        and provider is not None
    ):
        try:
            approvals = _resolve_approvals_from_reply(new_event, provider)
        except Exception as exc:  # provider/network failure -- don't fail the append
            approvals = {"error": f"approval resolution failed: {exc}"}

    # A reply that lands on a thread with no pending request has nothing to
    # resolve (`approvals is None`) and is never re-mined for new actions -- so
    # it would vanish silently. If the agent had a conversation on that thread,
    # remind the sender that a reply here won't reopen it; a fresh note will.
    reopen_hint = None
    reply_thread = (
        new_event.payload.get("thread_id")
        if new_event.type == "message_received" and new_event.raw_text
        else None
    )
    if config.message_approval() and reply_thread and approvals is None:
        events_now = storage.read_events()
        pending_here = [
            p for p in _pending_proposals(events_now)
            if p.payload.get("thread_id") == reply_thread
        ]
        if not pending_here:  # truly nothing open on this thread
            reopen_hint = _maybe_remind_new_note(new_event, events_now)

    # A reply that arrives ON a thread is consumed purely as an in-conversation
    # reply (handled above): it is NOT re-mined for new actions. This is what
    # keeps an approval ("yes, open it") from re-proposing the very ticket it
    # just approved -- the duplicate-ticket bug cannot form on a threaded reply.
    is_threaded_reply = bool(
        new_event.type == "message_received" and new_event.payload.get("thread_id")
    )

    # Auto-extraction: when a raw-input event lands, run extraction in the same
    # request so the system advances on its own. Degrades gracefully -- if no
    # provider is configured, or the provider fails, the event is still
    # appended and `extraction` reports why nothing ran.
    extraction = None
    if (
        config.auto_extract()
        and new_event.type in RAW_INPUT_TYPES
        and new_event.raw_text
        and not is_threaded_reply
    ):
        current_events = storage.read_events()
        if project(current_events).meta.get("status") == "closed":
            extraction = {"skipped": "project is closed"}
        elif provider is None:
            extraction = {"skipped": "no extraction provider configured"}
        else:
            try:
                extraction = _run_extraction(new_event, current_events, provider)
            except Exception as exc:  # provider/network failure -- don't fail the append
                extraction = {"error": f"auto-extraction failed: {exc}"}

    return {
        **asdict(new_event),
        "approvals": approvals,
        "extraction": extraction,
        "reopen_hint": reopen_hint,
    }


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

    if project(events).meta.get("status") == "closed":
        raise HTTPException(status_code=409, detail="project is closed -- no further extraction")

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
                "thread_id": _new_thread_id(),
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
        outcome = _resolve_proposal_approval(proposal, events, source="approval")
    except ProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # A ticket batch fans out to per-owner confirmation proposals instead of
    # applying anything; a normal approval returns the human_approval event.
    return outcome if isinstance(outcome, dict) else asdict(outcome)


def _tasks_with_tickets(events: list[Event]) -> set[str]:
    """Task ids that already have a ticket -- opened, or in a live proposal.

    Keeps `open-tickets` idempotent: re-running it never double-proposes a
    ticket for the same task. A ticket counts if its open_ticket carries the
    `task_id`, whether it's already executed (ticket_opened) or still sitting
    in a non-rejected proposal (batch or per-owner confirmation).
    """
    rejected = {e.payload.get("rejects") for e in events if e.type == "proposal_rejected"}
    ticketed: set[str] = set()
    for e in events:
        if e.type == "ticket_opened":
            tid = e.payload.get("payload", {}).get("task_id")
            if tid:
                ticketed.add(tid)
        elif e.type == "agent_proposal" and e.id not in rejected:
            for a in e.payload.get("actions", []):
                if a.get("type") == "open_ticket":
                    tid = a.get("payload", {}).get("task_id")
                    if tid:
                        ticketed.add(tid)
    return ticketed


@app.post("/open-tickets", status_code=201)
def open_tickets() -> dict:
    """Propose opening a ticket for every task that doesn't have one yet.

    Two-gate flow: this builds ONE batch proposal (all tickets) and emails the
    PM for sign-off. Approving the batch doesn't open anything -- it fans out a
    confirmation to each task's owner, and only that owner's reply opens their
    ticket. Skips tasks that already have a ticket; rejects a closed project.
    """
    events = storage.read_events()
    if project(events).meta.get("status") == "closed":
        raise HTTPException(status_code=409, detail="project is closed")

    state = project(events)
    already = _tasks_with_tickets(events)
    actions = []
    for tid, entity in state.entities.get("Task", {}).items():
        if tid in already:
            continue
        owner = entity.fields.get("owner") or entity.fields.get("assignee") or "team"
        actions.append({
            "type": "open_ticket",
            "category": "consequential",
            "payload": {
                "task_id": tid,
                "title": entity.fields.get("title", tid),
                "owner": owner,
                "requires_owner_confirmation": True,
            },
            "provenance": {"asserted_by": "ticket-planner"},
        })

    if not actions:
        return {"proposal": None, "message": "every task already has a ticket"}

    proposal = Event(
        id=f"prop_{uuid.uuid4().hex[:12]}",
        type="agent_proposal",
        timestamp=_now(),
        source="agent:ticket-batch",
        payload={
            "deltas": [],
            "actions": actions,
            "provider": "ticket-planner",
            "source_event_id": "open-tickets",
            "thread_id": _new_thread_id(),
        },
    )
    storage.write_event(proposal)
    approval_request = _ask_for_approval(proposal, storage.read_events())
    return {"proposal": asdict(proposal), "approval_request": approval_request}
