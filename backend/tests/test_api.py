"""API tests against an isolated, temporary event log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aipm.approval import ApprovalResolution, ApprovalResult
from aipm.conversation import ComposedMessage
from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta

from aipm_backend.extraction import StaticProvider, get_provider, get_provider_optional
from aipm_backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPM_EVENT_LOG", str(tmp_path / "events.jsonl"))
    # Auto-extraction off by default in tests, so POST /events behaves
    # deterministically regardless of any API keys in the environment. Tests
    # that exercise the auto path turn it on explicitly.
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "0")
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return TestClient(app)


def _use_provider(result: ExtractionResult):
    """Override the manual /extract provider with a fixed-result fake."""
    app.dependency_overrides[get_provider] = lambda: StaticProvider(result)


def _use_auto_provider(
    result: ExtractionResult,
    approval_result: ApprovalResult | None = None,
    composed_message: ComposedMessage | None = None,
):
    """Override the auto-extraction (POST /events) provider with a fixed fake.

    The same provider serves extraction, approval resolution, and message
    composition; tests re-call this between steps to swap what the fake returns.
    """
    app.dependency_overrides[get_provider_optional] = lambda: StaticProvider(
        result, approval_result, composed_message
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _delta(op, entity_type, entity_id, fields, **prov):
    return {
        "op": op,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "fields": fields,
        "provenance": {"asserted_by": "tester", **prov},
    }


def _event(event_id, *deltas):
    return {
        "id": event_id,
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {"deltas": list(deltas)},
    }


def test_empty_state(client):
    response = client.get("/state")
    assert response.status_code == 200
    state = response.json()
    assert state["Task"] == {}


def test_create_event_updates_state(client):
    event = _event(
        "evt_1",
        _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
    )

    response = client.post("/events", json=event)
    assert response.status_code == 201

    state = client.get("/state").json()
    assert state["Task"]["t1"]["fields"] == {"title": "Do thing", "status": "open"}
    assert len(state["Task"]["t1"]["history"]) == 1


def test_events_are_persisted_in_order(client):
    client.post(
        "/events",
        json=_event("evt_1", _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"})),
    )
    client.post(
        "/events",
        json=_event("evt_2", _delta("update", "Task", "t1", {"status": "done"})),
    )

    events = client.get("/events").json()
    assert [e["id"] for e in events] == ["evt_1", "evt_2"]

    state = client.get("/state").json()
    assert state["Task"]["t1"]["fields"]["status"] == "done"
    assert len(state["Task"]["t1"]["history"]) == 2


def test_invalid_delta_is_rejected_and_not_persisted(client):
    response = client.post(
        "/events",
        json=_event("evt_1", _delta("update", "Task", "missing", {"status": "done"})),
    )

    assert response.status_code == 400
    assert client.get("/events").json() == []


def test_unknown_event_type_is_rejected(client):
    bad_event = _event("evt_1")
    bad_event["type"] = "not_a_real_type"

    response = client.post("/events", json=bad_event)

    assert response.status_code == 400


# --- extraction / approval flow ------------------------------------------


def _raw_event(event_id, text):
    return {
        "id": event_id,
        "type": "manual_note",
        "timestamp": "2025-02-03T09:00:00Z",
        "source": "pm_note",
        "raw_text": text,
        "payload": {},
    }


def test_extract_writes_proposal_without_changing_state(client):
    raw = "The vendor API access is delayed again."
    client.post("/events", json=_raw_event("raw_1", raw))

    _use_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Risk", "vendor-delay",
                    {"description": "Vendor API delayed", "severity": "high"},
                    source_span="The vendor API access is delayed again",
                )
            ]
        )
    )

    response = client.post("/extract", json={"source_event_id": "raw_1"})
    assert response.status_code == 201
    body = response.json()
    assert body["proposal"]["type"] == "agent_proposal"
    assert body["proposal"]["payload"]["deltas"][0]["entity_id"] == "vendor-delay"

    # proposal does NOT change state
    assert client.get("/state").json()["Risk"] == {}


def test_extract_drops_ungrounded_proposals(client):
    client.post("/events", json=_raw_event("raw_1", "The vendor API is delayed."))

    _use_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta("create", "Risk", "real", {}, source_span="The vendor API is delayed"),
                ProposedDelta("create", "Risk", "fake", {}, source_span="completely invented text"),
            ]
        )
    )

    body = client.post("/extract", json={"source_event_id": "raw_1"}).json()
    kept = [d["entity_id"] for d in body["proposal"]["payload"]["deltas"]]
    assert kept == ["real"]
    assert len(body["dropped"]) == 1


def test_extract_unknown_source_event_is_404(client):
    _use_provider(ExtractionResult())
    response = client.post("/extract", json={"source_event_id": "nope"})
    assert response.status_code == 404


def test_proposals_then_approve_applies_to_state(client):
    raw = "The vendor API access is delayed again."
    client.post("/events", json=_raw_event("raw_1", raw))
    _use_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Risk", "vendor-delay",
                    {"severity": "high", "status": "open"},
                    source_span="The vendor API access is delayed again",
                )
            ],
            actions=[
                ProposedAction(
                    "escalate_to_management", "consequential", {"to": "director"},
                    source_span="The vendor API access is delayed again",
                )
            ],
        )
    )

    proposal = client.post("/extract", json={"source_event_id": "raw_1"}).json()["proposal"]
    proposal_id = proposal["id"]
    assert proposal["payload"]["actions"][0]["category"] == "consequential"

    pending = client.get("/proposals").json()
    assert [p["id"] for p in pending] == [proposal_id]

    approve = client.post(f"/proposals/{proposal_id}/approve")
    assert approve.status_code == 201
    assert approve.json()["payload"]["approves"] == proposal_id

    state = client.get("/state").json()
    assert state["Risk"]["vendor-delay"]["fields"]["severity"] == "high"
    assert len(state["actions"]) == 1
    assert state["actions"][0]["category"] == "consequential"

    # approving a consequential action logs its (stubbed) outbound event
    events = client.get("/events").json()
    assert any(e["type"] == "report_to_management" for e in events)

    # once approved it no longer shows as pending
    assert client.get("/proposals").json() == []


def test_extract_auto_executes_info_request_actions(client):
    raw = "Bob mentioned the vendor API access is delayed again."
    client.post("/events", json=_raw_event("raw_1", raw))
    _use_provider(
        ExtractionResult(
            actions=[
                ProposedAction(
                    "send_message", "info_request", {"to": "bob", "subject": "Update?"},
                    source_span="the vendor API access is delayed again",
                )
            ],
        )
    )

    body = client.post("/extract", json={"source_event_id": "raw_1"}).json()

    # info_request actions execute immediately, leaving nothing for a human
    # to review -- no agent_proposal is written
    assert body["proposal"] is None
    assert len(body["executed"]) == 1
    assert body["executed"][0]["type"] == "message_sent"
    assert body["executed"][0]["payload"]["payload"]["to"] == "bob"

    events = client.get("/events").json()
    assert any(e["type"] == "message_sent" for e in events)

    # no human_approval needed -- nothing pending, and state.actions is empty
    assert client.get("/proposals").json() == []
    assert client.get("/state").json()["actions"] == []


def test_extract_returns_no_conflicts_when_clean(client):
    client.post("/events", json=_raw_event("raw_1", "The vendor API is delayed."))
    _use_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Risk", "vendor-delay",
                    {"severity": "high", "status": "open"},
                    source_span="The vendor API is delayed",
                )
            ]
        )
    )
    body = client.post("/extract", json={"source_event_id": "raw_1"}).json()
    assert body["conflicts"] == []


def test_extract_detects_deadline_regression(client):
    # First establish a deadline in state via human_approval
    setup = {
        "id": "evt_setup",
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {
            "deltas": [
                {
                    "op": "create",
                    "entity_type": "Deadline",
                    "entity_id": "sprint-end",
                    "fields": {"due_date": "2025-03-01", "status": "committed"},
                    "provenance": {"asserted_by": "PM"},
                }
            ],
            "actions": [],
        },
    }
    client.post("/events", json=setup)

    client.post("/events", json=_raw_event("raw_1", "We need to move the deadline to Feb 10."))
    _use_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "update", "Deadline", "sprint-end",
                    {"due_date": "2025-02-10"},
                    source_span="We need to move the deadline to Feb 10",
                )
            ]
        )
    )

    body = client.post("/extract", json={"source_event_id": "raw_1"}).json()
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["type"] == "deadline_regression"
    assert body["conflicts"][0]["entity_id"] == "sprint-end"


def test_approve_unknown_proposal_is_404(client):
    assert client.post("/proposals/nope/approve").status_code == 404


# --- /review-state ------------------------------------------------------------


def _human_approval(event_id, *deltas, actions=None):
    return {
        "id": event_id,
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {"deltas": list(deltas), "actions": actions or []},
    }


def test_review_state_clean_returns_no_issues(client):
    body = client.post("/review-state").json()
    assert body["issues"] == []
    assert body["executed"] == []
    assert body["proposal"] is None


def test_review_state_open_question_auto_sends_email(client):
    client.post("/events", json=_human_approval(
        "evt_1",
        _delta("create", "OpenQuestion", "api-access",
               {"description": "Who owns API access?", "status": "open"}),
    ))

    body = client.post("/review-state").json()

    assert len(body["issues"]) == 1
    assert body["issues"][0]["rule"] == "open_question"
    assert len(body["executed"]) == 1
    assert body["executed"][0]["type"] == "message_sent"
    assert body["proposal"] is None

    events = client.get("/events").json()
    assert any(e["type"] == "message_sent" for e in events)


def test_review_state_blocked_task_auto_sends_email(client):
    client.post("/events", json=_human_approval(
        "evt_1",
        _delta("create", "Task", "deploy-service",
               {"title": "Deploy", "status": "blocked", "owner": "alice"}),
    ))

    body = client.post("/review-state").json()

    assert body["issues"][0]["rule"] == "blocked_task"
    assert body["executed"][0]["type"] == "message_sent"
    assert body["executed"][0]["payload"]["payload"]["to"] == "alice"


def test_review_state_high_risk_no_owner_creates_proposal(client):
    client.post("/events", json=_human_approval(
        "evt_1",
        _delta("create", "Risk", "vendor-delay",
               {"severity": "high", "status": "open"}),
    ))

    body = client.post("/review-state").json()

    assert body["issues"][0]["rule"] == "unowned_high_risk"
    assert body["executed"] == []
    proposal = body["proposal"]
    assert proposal is not None
    assert proposal["type"] == "agent_proposal"
    actions = proposal["payload"]["actions"]
    assert len(actions) == 1
    assert actions[0]["type"] == "raise_flag"
    assert actions[0]["category"] == "consequential"

    pending = client.get("/proposals").json()
    assert any(p["id"] == proposal["id"] for p in pending)


def test_review_state_proposal_can_be_approved(client):
    client.post("/events", json=_human_approval(
        "evt_1",
        _delta("create", "Risk", "vendor-delay", {"severity": "high", "status": "open"}),
    ))

    proposal_id = client.post("/review-state").json()["proposal"]["id"]
    approve = client.post(f"/proposals/{proposal_id}/approve")
    assert approve.status_code == 201

    events = client.get("/events").json()
    assert any(e["type"] == "flag_raised" for e in events)


# --- project definition --------------------------------------------------------


def test_init_project_sets_meta(client):
    response = client.post(
        "/project",
        json={"name": "Apollo", "description": "Launch the lander", "team": ["alice", "bob"]},
    )
    assert response.status_code == 201
    assert response.json()["type"] == "project_initialized"

    assert client.get("/project").json()["name"] == "Apollo"

    state = client.get("/state").json()
    assert state["meta"]["name"] == "Apollo"
    assert state["meta"]["team"] == ["alice", "bob"]


def test_get_project_empty_before_init(client):
    assert client.get("/project").json() == {}


def test_reinit_project_merges_meta(client):
    client.post("/project", json={"name": "Apollo", "team": ["alice"]})
    client.post("/project", json={"name": "Apollo 2", "description": "Now with rovers"})

    meta = client.get("/project").json()
    assert meta["name"] == "Apollo 2"
    assert meta["description"] == "Now with rovers"
    assert meta["team"] == ["alice"]  # preserved from the first init


# --- auto-extraction on POST /events ------------------------------------------


def test_auto_extract_runs_on_raw_event(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Risk", "vendor-delay", {"severity": "high", "status": "open"},
                    source_span="The vendor API access is delayed",
                )
            ]
        )
    )

    response = client.post("/events", json=_raw_event("raw_1", "The vendor API access is delayed."))
    assert response.status_code == 201

    extraction = response.json()["extraction"]
    assert extraction is not None
    assert extraction["proposal"]["payload"]["deltas"][0]["entity_id"] == "vendor-delay"

    # the proposal is now pending, exactly as if /extract had been called
    assert len(client.get("/proposals").json()) == 1


def test_auto_extract_auto_sends_info_request(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _use_auto_provider(
        ExtractionResult(
            actions=[
                ProposedAction(
                    "send_message", "info_request", {"to": "bob", "subject": "Update?"},
                    source_span="ask Bob for an update",
                )
            ]
        )
    )

    response = client.post(
        "/events", json=_raw_event("raw_1", "Someone should ask Bob for an update.")
    )
    extraction = response.json()["extraction"]
    assert extraction["proposal"] is None
    assert extraction["executed"][0]["type"] == "message_sent"
    assert any(e["type"] == "message_sent" for e in client.get("/events").json())


def test_auto_extract_off_returns_null(client):
    # fixture leaves AIPM_AUTO_EXTRACT=0
    _use_auto_provider(ExtractionResult())
    response = client.post("/events", json=_raw_event("raw_1", "anything"))
    assert response.json()["extraction"] is None
    assert client.get("/proposals").json() == []


def test_auto_extract_skipped_without_provider(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    # no provider override and no API key -> get_provider_optional returns None
    response = client.post("/events", json=_raw_event("raw_1", "anything"))
    assert response.json()["extraction"] == {"skipped": "no extraction provider configured"}


def test_auto_extract_skips_non_raw_events(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _use_auto_provider(
        ExtractionResult(
            deltas=[ProposedDelta("create", "Risk", "x", {}, source_span="would fire if it ran")]
        )
    )
    response = client.post(
        "/events", json=_human_approval("evt_1", _delta("create", "Task", "t1", {"status": "open"})),
    )
    assert response.json()["extraction"] is None


# --- approval by email reply --------------------------------------------------


def _email_reply(event_id, text, source="maya@orion.com"):
    return {
        "id": event_id,
        "type": "message_received",
        "timestamp": "2025-02-03T10:00:00Z",
        "source": source,
        "raw_text": text,
        "payload": {},
    }


def _pending_consequential_proposal(client):
    """Create a pending proposal via auto-extraction; return its id."""
    _use_auto_provider(
        ExtractionResult(
            actions=[
                ProposedAction(
                    "open_ticket", "consequential", {"title": "Resolve PayPal support"},
                    source_span="open a ticket about PayPal",
                )
            ]
        )
    )
    note = client.post("/events", json=_raw_event("raw_1", "Someone should open a ticket about PayPal."))
    return note.json()["extraction"]["proposal"]["id"]


def test_consequential_proposal_sends_approval_request_email(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    # the agent reaches out (stub) to ask a human to authorize the proposal
    asks = [
        e for e in client.get("/events").json()
        if e["type"] == "message_sent" and e["payload"]["payload"].get("proposal_id") == proposal_id
    ]
    assert len(asks) == 1


def test_email_reply_approves_pending_proposal(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    # the human replies; the resolver approves that specific proposal
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(proposal_id, "approve", "yes, go ahead")]),
    )
    reply = client.post("/events", json=_email_reply("raw_2", "Yes, go ahead and open the ticket."))

    approvals = reply.json()["approvals"]
    assert len(approvals["approved"]) == 1
    assert approvals["approved"][0]["payload"]["approves"] == proposal_id

    # the consequential action executed (stub) and the proposal is resolved
    assert any(e["type"] == "ticket_opened" for e in client.get("/events").json())
    assert client.get("/proposals").json() == []
    assert client.get("/state").json()["actions"][0]["type"] == "open_ticket"


def test_email_reply_defer_leaves_proposal_pending(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    # a reply that addresses nothing -> no resolutions, nothing approved
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply = client.post("/events", json=_email_reply("raw_2", "Thanks for the update!"))

    approvals = reply.json()["approvals"]
    assert approvals["approved"] == []
    assert approvals["rejected"] == []
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]
    assert client.get("/state").json()["actions"] == []


def test_email_reply_rejects_pending_proposal(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(proposal_id, "reject", "no, hold off")]),
    )
    reply = client.post("/events", json=_email_reply("raw_2", "No, don't open that ticket."))

    approvals = reply.json()["approvals"]
    assert len(approvals["rejected"]) == 1
    # taken out of the pending set, state never changed, no outbound action
    assert client.get("/proposals").json() == []
    assert client.get("/state").json()["actions"] == []
    assert any(e["type"] == "proposal_rejected" for e in client.get("/events").json())
    assert not any(e["type"] == "ticket_opened" for e in client.get("/events").json())


def test_email_reply_with_no_pending_proposals_is_noop(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _use_auto_provider(ExtractionResult())  # nothing pending, nothing extracted
    reply = client.post("/events", json=_email_reply("raw_1", "Just an FYI, no action needed."))
    assert reply.json()["approvals"] is None


def test_email_approval_off_requires_explicit_approve(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    monkeypatch.setenv("AIPM_EMAIL_APPROVAL", "0")
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(proposal_id, "approve")]),
    )
    reply = client.post("/events", json=_email_reply("raw_2", "Yes, go ahead."))

    assert reply.json()["approvals"] is None
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]


# --- project dates & deadline conflict ----------------------------------------


def test_init_project_with_dates(client):
    response = client.post(
        "/project",
        json={"name": "Apollo", "start_date": "2026-01-01", "end_date": "2026-11-28"},
    )
    assert response.status_code == 201
    meta = client.get("/project").json()
    assert meta["start_date"] == "2026-01-01"
    assert meta["end_date"] == "2026-11-28"


def test_project_deadline_exceeded_creates_raise_flag_proposal(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Apollo", "start_date": "2026-01-01", "end_date": "2026-11-28"})

    # Claude proposes a deadline past the project end
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Deadline", "launch",
                    {"due_date": "2027-01-15", "title": "Product launch"},
                    source_span="launch scheduled for January 15 next year",
                )
            ]
        )
    )
    response = client.post(
        "/events", json=_raw_event("raw_1", "launch scheduled for January 15 next year.")
    )
    extraction = response.json()["extraction"]

    # conflict is reported ...
    assert any(c["type"] == "project_deadline_exceeded" for c in extraction["conflicts"])

    # ... and a consequential raise_flag is injected alongside the delta (Option A)
    proposal = extraction["proposal"]
    assert proposal is not None
    actions = proposal["payload"]["actions"]
    assert any(
        a["type"] == "raise_flag" and a["payload"]["review_rule"] == "project_deadline_exceeded"
        for a in actions
    )
    assert any(d["entity_id"] == "launch" for d in proposal["payload"]["deltas"])


def test_no_deadline_conflict_without_project_end_date(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "create", "Deadline", "d1", {"due_date": "2099-01-01"},
                    source_span="some far future date",
                )
            ]
        )
    )
    response = client.post("/events", json=_raw_event("raw_1", "some far future date"))
    conflicts = response.json()["extraction"]["conflicts"]
    assert not any(c["type"] == "project_deadline_exceeded" for c in conflicts)


# --- nudge / escalation -------------------------------------------------------


def test_deferred_reply_sends_nudge(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply = client.post("/events", json=_email_reply("raw_2", "Thanks for the update!"))

    approvals = reply.json()["approvals"]
    assert [n["proposal_id"] for n in approvals["nudged"]] == [proposal_id]
    assert approvals["escalated"] == []
    assert approvals["approved"] == []
    assert any(
        e["type"] == "message_sent" and e["source"] == "agent:approval-nudge"
        for e in client.get("/events").json()
    )
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]


def test_second_deferred_reply_sends_escalation(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_2", "Not relevant."))      # nudge
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply2 = client.post("/events", json=_email_reply("raw_3", "Still not relevant."))  # escalate

    approvals = reply2.json()["approvals"]
    assert approvals["nudged"] == []
    assert [e["proposal_id"] for e in approvals["escalated"]] == [proposal_id]
    assert any(
        e["type"] == "message_sent" and e["source"] == "agent:approval-escalation"
        for e in client.get("/events").json()
    )
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]


def test_third_deferred_reply_silently_ignored(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)

    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_2", "nope"))   # nudge
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_3", "nope"))   # escalation
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply3 = client.post("/events", json=_email_reply("raw_4", "nope"))  # quiet

    approvals = reply3.json()["approvals"]
    assert approvals["nudged"] == []
    assert approvals["escalated"] == []
    # exactly one nudge and one escalation across the whole exchange
    events = client.get("/events").json()
    assert sum(1 for e in events if e["source"] == "agent:approval-nudge") == 1
    assert sum(1 for e in events if e["source"] == "agent:approval-escalation") == 1
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]


def test_no_nudge_without_prior_approval_request(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    # A proposal that never had an approval-request email sent (hand-posted,
    # bypassing _run_extraction) must not be nudged on a deferred reply.
    client.post("/events", json={
        "id": "prop_manual",
        "type": "agent_proposal",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {
            "deltas": [],
            "actions": [{
                "type": "raise_flag", "category": "consequential",
                "payload": {"title": "Vendor delay"},
                "provenance": {"asserted_by": "test"},
            }],
            "source_event_id": "x", "provider": "test",
        },
    })
    assert [p["id"] for p in client.get("/proposals").json()] == ["prop_manual"]

    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply = client.post("/events", json=_email_reply("raw_2", "Just checking in."))
    assert reply.json()["approvals"]["nudged"] == []


def test_escalation_goes_to_pm_when_set(client, monkeypatch):
    """Escalation email is addressed to the project PM, not the original action target."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Apollo", "pm": "pm@company.com", "tech_lead": "tl@company.com"})
    proposal_id = _pending_consequential_proposal(client)

    # first deferred reply -> nudge (still goes to original recipient, not PM)
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_2", "Not relevant."))

    # second deferred reply -> escalation
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    reply2 = client.post("/events", json=_email_reply("raw_3", "Still not relevant."))

    assert [e["proposal_id"] for e in reply2.json()["approvals"]["escalated"]] == [proposal_id]

    # escalation email must be addressed to the PM
    events = client.get("/events").json()
    esc = next(e for e in events if e["source"] == "agent:approval-escalation")
    assert esc["payload"]["payload"]["to"] == "pm@company.com"


def test_escalation_falls_back_to_tech_lead_when_no_pm(client, monkeypatch):
    """When no PM is set, escalation falls back to tech_lead."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Apollo", "tech_lead": "tl@company.com"})
    proposal_id = _pending_consequential_proposal(client)

    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_2", "Not relevant."))
    _use_auto_provider(ExtractionResult(), ApprovalResult([]))
    client.post("/events", json=_email_reply("raw_3", "Still not relevant."))

    events = client.get("/events").json()
    esc = next(e for e in events if e["source"] == "agent:approval-escalation")
    assert esc["payload"]["payload"]["to"] == "tl@company.com"


def test_init_project_with_pm_and_tech_lead(client):
    client.post(
        "/project",
        json={"name": "Apollo", "pm": "pm@company.com", "tech_lead": "tl@company.com"},
    )
    meta = client.get("/project").json()
    assert meta["pm"] == "pm@company.com"
    assert meta["tech_lead"] == "tl@company.com"


def test_approval_request_goes_to_pm_not_team(client, monkeypatch):
    """A consequential proposal's approval email goes to the PM alone."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Apollo", "team": ["dana", "eran"], "pm": "pm@company.com"})
    proposal_id = _pending_consequential_proposal(client)

    ask = next(
        e for e in client.get("/events").json()
        if e["type"] == "message_sent" and e["payload"]["payload"].get("proposal_id") == proposal_id
    )
    assert ask["payload"]["payload"]["to"] == "pm@company.com"


# --- project close ------------------------------------------------------------


def test_close_project_blocks_extraction(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Apollo"})
    _use_auto_provider(
        ExtractionResult(
            deltas=[ProposedDelta("create", "Risk", "r1", {}, source_span="the vendor API is delayed")]
        )
    )

    close = client.post("/project/close", json={"reason": "shipped"})
    assert close.status_code == 201
    assert client.get("/project").json()["status"] == "closed"

    # extraction is now refused on raw input ...
    resp = client.post("/events", json=_raw_event("raw_1", "the vendor API is delayed"))
    assert resp.json()["extraction"] == {"skipped": "project is closed"}
    # ... and the explicit /extract path 409s (provider present, still refused)
    _use_provider(ExtractionResult())
    assert client.post("/extract", json={"source_event_id": "raw_1"}).status_code == 409


def test_close_twice_is_conflict(client):
    client.post("/project", json={"name": "Apollo"})
    assert client.post("/project/close").status_code == 201
    assert client.post("/project/close").status_code == 409


# --- two-gate ticket opening --------------------------------------------------


def _project_with_tasks(client):
    """Seed a project with two tasks owned by different people."""
    client.post("/project", json={"name": "Apollo", "team": ["dana", "eran"], "pm": "pm@company.com"})
    client.post("/events", json=_human_approval(
        "evt_tasks",
        _delta("create", "Task", "api-scaffold", {"title": "API scaffold", "owner": "dana"}),
        _delta("create", "Task", "quota-request", {"title": "Quota request", "owner": "eran"}),
    ))


def test_open_tickets_proposes_batch_to_pm(client):
    _project_with_tasks(client)
    body = client.post("/open-tickets").json()

    actions = body["proposal"]["payload"]["actions"]
    assert len(actions) == 2
    assert all(a["payload"]["requires_owner_confirmation"] for a in actions)
    # one approval email, to the PM
    assert body["approval_request"]["payload"]["payload"]["to"] == "pm@company.com"
    # nothing opened yet
    assert not any(e["type"] == "ticket_opened" for e in client.get("/events").json())


def test_open_tickets_is_idempotent(client):
    _project_with_tasks(client)
    client.post("/open-tickets")
    # second call: both tasks already have a (pending) ticket
    second = client.post("/open-tickets").json()
    assert second["proposal"] is None


def test_batch_approval_fans_out_to_owners_without_opening(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _project_with_tasks(client)
    batch_id = client.post("/open-tickets").json()["proposal"]["id"]

    # PM approves the batch by email
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(batch_id, "approve", "yes, open them")]),
    )
    reply = client.post("/events", json=_email_reply("raw_pm", "Yes, go ahead.", source="pm@company.com"))

    approvals = reply.json()["approvals"]
    # batch is approved but fans out -- still no ticket opened
    assert len(approvals["fanned_out"]) == 2
    owners = {f["owner"] for f in approvals["fanned_out"]}
    assert owners == {"dana", "eran"}
    assert not any(e["type"] == "ticket_opened" for e in client.get("/events").json())

    # each owner now has a pending confirmation proposal, addressed to them
    pending = client.get("/proposals").json()
    assert {p["payload"]["approver"] for p in pending} == {"dana", "eran"}
    asks = [
        e["payload"]["payload"]["to"] for e in client.get("/events").json()
        if e["type"] == "message_sent" and e["source"] == "agent:approval-request"
        and e["payload"]["payload"].get("proposal_id") in {p["id"] for p in pending}
    ]
    assert set(asks) == {"dana", "eran"}


def test_owner_confirmation_opens_only_their_ticket(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    _project_with_tasks(client)
    batch_id = client.post("/open-tickets").json()["proposal"]["id"]

    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(batch_id, "approve", "yes")]),
    )
    client.post("/events", json=_email_reply("raw_pm", "Yes.", source="pm@company.com"))

    # find dana's confirmation proposal
    pending = client.get("/proposals").json()
    dana_prop = next(p for p in pending if p["payload"]["approver"] == "dana")

    # dana confirms -> her ticket opens, eran's does not
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(dana_prop["id"], "approve", "yes open mine")]),
    )
    client.post("/events", json=_email_reply("raw_dana", "Yes, open it.", source="dana"))

    opened = [
        e for e in client.get("/events").json() if e["type"] == "ticket_opened"
    ]
    assert len(opened) == 1
    assert opened[0]["payload"]["payload"]["owner"] == "dana"
    # eran's confirmation is still pending
    assert any(p["payload"]["approver"] == "eran" for p in client.get("/proposals").json())


# --- clarification on unreconcilable deltas -----------------------------------


def test_proposal_summary_uses_human_titles_not_ids():
    """The request summary (shown to the human and the resolver) reads in plain
    words -- the entity's title/description -- not its internal id."""
    from aipm_backend.main import _summarize_proposal_payload

    payload = {
        "deltas": [
            {"op": "create", "entity_type": "Task", "entity_id": "dana-mock-data-setup",
             "fields": {"title": "Set up mock transaction data"}},
        ],
        "actions": [],
    }
    summary = _summarize_proposal_payload(payload)
    assert "Set up mock transaction data" in summary
    assert "dana-mock-data-setup" not in summary


def test_unapplicable_update_triggers_clarification(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    # The model proposes updating a Decision that was never created.
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "update", "Decision", "ghost-decision", {"status": "decided"},
                    source_span="we decided on the schema",
                ),
                ProposedDelta(
                    "create", "Risk", "real-risk", {"severity": "high"},
                    source_span="the vendor API is delayed",
                ),
            ]
        )
    )
    resp = client.post("/events", json=_raw_event(
        "raw_1", "we decided on the schema; also the vendor API is delayed"
    ))
    extraction = resp.json()["extraction"]

    # the ghost update is held out and a clarification email goes to the author
    assert [c["entity_id"] for c in extraction["clarifications"]] == ["ghost-decision"]
    assert any(
        e["type"] == "message_sent" and e["source"] == "agent:clarification"
        for e in client.get("/events").json()
    )
    # the valid delta still made it into the proposal
    kept = [d["entity_id"] for d in extraction["proposal"]["payload"]["deltas"]]
    assert kept == ["real-risk"]


# --- threads, channel stamping, and model-composed replies --------------------


def _thread_id_of(client, proposal_id: str) -> str:
    """The thread_id the agent opened for a given pending proposal."""
    proposal = next(p for p in client.get("/proposals").json() if p["id"] == proposal_id)
    return proposal["payload"]["thread_id"]


def _threaded_reply(event_id, text, thread_id, source="pm@company.com"):
    return {
        "id": event_id,
        "type": "message_received",
        "timestamp": "2025-02-03T10:00:00Z",
        "source": source,
        "raw_text": text,
        "payload": {"thread_id": thread_id},
    }


def test_outbound_message_is_stamped_with_channel_and_thread(client, monkeypatch):
    """Every message_sent carries channel + thread_id + a channel-side id."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)
    tid = _thread_id_of(client, proposal_id)

    ask = next(
        e for e in client.get("/events").json()
        if e["type"] == "message_sent" and e["source"] == "agent:approval-request"
    )
    inner = ask["payload"]["payload"]
    assert inner["channel"] == "stub"
    assert inner["thread_id"] == tid
    assert inner["message_id"].startswith("stub_")


def test_threaded_reply_approves_without_re_extracting(client, monkeypatch):
    """The duplicate-ticket bug is dissolved: an approval reply on a thread is
    consumed as an approval only and is NEVER re-mined for new actions."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)
    tid = _thread_id_of(client, proposal_id)

    # The provider WOULD re-propose the very same ticket if extraction ran on
    # the reply text -- exactly the old duplicate bug.
    _use_auto_provider(
        ExtractionResult(
            actions=[
                ProposedAction(
                    "open_ticket", "consequential", {"title": "Resolve PayPal support"},
                    source_span="open a ticket about PayPal",
                )
            ]
        ),
        ApprovalResult([ApprovalResolution(proposal_id, "approve", "yes, open it")]),
    )
    reply = client.post("/events", json=_threaded_reply("raw_reply", "Yes, go ahead.", tid))
    body = reply.json()

    # approved on the thread ...
    assert [a["payload"]["approves"] for a in body["approvals"]["approved"]] == [proposal_id]
    # ... and extraction was skipped because the reply is threaded -> no duplicate
    assert body["extraction"] is None
    assert client.get("/proposals").json() == []
    opened = [e for e in client.get("/events").json() if e["type"] == "ticket_opened"]
    assert len(opened) == 1


def test_threaded_ambiguous_reply_composes_message(client, monkeypatch):
    """A threaded reply that doesn't approve/reject lets the model say something
    short (info_request only) instead of a canned nudge."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    proposal_id = _pending_consequential_proposal(client)
    tid = _thread_id_of(client, proposal_id)

    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(proposal_id, "defer", "depends on legal")]),
        ComposedMessage(send=True, text="Understood -- should I wait for legal sign-off first?"),
    )
    reply = client.post(
        "/events", json=_threaded_reply("raw_reply", "Depends on whether legal signed off.", tid)
    )
    approvals = reply.json()["approvals"]

    # the agent composed a reply on the thread, and did NOT fall to the ladder
    assert [c["proposal_id"] for c in approvals["composed"]] == [proposal_id]
    assert approvals["nudged"] == []
    assert approvals["escalated"] == []

    composed = [e for e in client.get("/events").json() if e["source"] == "agent:compose"]
    assert len(composed) == 1
    assert composed[0]["type"] == "message_sent"
    assert composed[0]["payload"]["category"] == "info_request"  # never consequential
    assert composed[0]["payload"]["payload"]["thread_id"] == tid

    # nothing applied; the proposal is still pending its real decision
    assert [p["id"] for p in client.get("/proposals").json()] == [proposal_id]
    assert client.get("/state").json()["actions"] == []


def test_thread_turn_cap_falls_back_to_ladder(client, monkeypatch):
    """After the per-thread compose cap, ambiguous replies drop to the nudge ladder."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    monkeypatch.setenv("AIPM_MAX_THREAD_TURNS", "1")
    proposal_id = _pending_consequential_proposal(client)
    tid = _thread_id_of(client, proposal_id)

    msg = ComposedMessage(send=True, text="One more question to move this forward?")
    _use_auto_provider(
        ExtractionResult(), ApprovalResult([ApprovalResolution(proposal_id, "defer", "")]), msg
    )
    first = client.post("/events", json=_threaded_reply("raw_r1", "still thinking", tid))
    assert [c["proposal_id"] for c in first.json()["approvals"]["composed"]] == [proposal_id]

    # second ambiguous reply: cap (1) reached -> ladder nudges instead of composing
    _use_auto_provider(
        ExtractionResult(), ApprovalResult([ApprovalResolution(proposal_id, "defer", "")]), msg
    )
    second = client.post("/events", json=_threaded_reply("raw_r2", "still thinking more", tid))
    approvals = second.json()["approvals"]
    assert approvals["composed"] == []
    assert [n["proposal_id"] for n in approvals["nudged"]] == [proposal_id]


def test_model_messages_off_uses_ladder_on_thread(client, monkeypatch):
    """With AIPM_MODEL_MESSAGES=0 the agent never composes -- straight to the ladder."""
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    monkeypatch.setenv("AIPM_MODEL_MESSAGES", "0")
    proposal_id = _pending_consequential_proposal(client)
    tid = _thread_id_of(client, proposal_id)

    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(proposal_id, "defer", "")]),
        ComposedMessage(send=True, text="should not be sent"),
    )
    reply = client.post("/events", json=_threaded_reply("raw_r1", "hmm", tid))
    approvals = reply.json()["approvals"]
    assert approvals["composed"] == []
    assert [n["proposal_id"] for n in approvals["nudged"]] == [proposal_id]
    assert not any(e["source"] == "agent:compose" for e in client.get("/events").json())


# --- author-claim conflict routes to the author, not the PM --------------------


def test_author_claim_conflict_routes_clarification_to_author(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    # the project has a PM, so we can prove the clarification does NOT go to them
    client.post("/project", json={"name": "Helios", "pm": "pm@helios.com"})

    # state: a task that depends on a still-blocked upstream task
    setup = {
        "id": "evt_setup",
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {
            "deltas": [
                _delta("create", "Task", "upstream", {"status": "blocked"}),
                _delta("create", "Task", "downstream", {"status": "open"}),
                _delta(
                    "create", "Dependency", "dep1",
                    {"from_entity_id": "downstream", "to_entity_id": "upstream", "status": "active"},
                ),
            ],
            "actions": [],
        },
    }
    client.post("/events", json=setup)

    # the author claims their downstream task is done -- but it's still blocked
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta(
                    "update", "Task", "downstream", {"status": "done"},
                    source_span="downstream is done",
                )
            ]
        )
    )
    resp = client.post(
        "/events",
        json={
            "id": "raw_1",
            "type": "manual_note",
            "timestamp": "2025-02-03T09:00:00Z",
            "source": "yuki@helios.com",
            "raw_text": "downstream is done",
            "payload": {},
        },
    )

    extraction = resp.json()["extraction"]
    assert extraction["conflicts"][0]["type"] == "task_done_with_open_dep"

    # the proposal is re-aimed at the author for clarification, not the PM
    proposal = extraction["proposal"]
    assert proposal["payload"]["approver"] == "yuki@helios.com"

    # nothing applied yet -- the claim is still pending the author's answer
    assert client.get("/state").json()["Task"]["downstream"]["fields"]["status"] == "open"

    # exactly one outreach, and it went to the author rather than pm@helios.com
    asks = [
        e for e in client.get("/events").json()
        if e["type"] == "message_sent"
        and e["payload"]["payload"].get("proposal_id") == proposal["id"]
    ]
    assert len(asks) == 1
    assert asks[0]["payload"]["payload"]["to"] == "yuki@helios.com"


def test_clean_proposal_still_routes_to_pm(client, monkeypatch):
    # a non-conflicting proposal must keep going to the PM, unchanged
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Helios", "pm": "pm@helios.com"})
    _use_auto_provider(
        ExtractionResult(
            actions=[
                ProposedAction(
                    "open_ticket", "consequential", {"title": "Resolve PayPal support"},
                    source_span="open a ticket about PayPal",
                )
            ]
        )
    )
    resp = client.post(
        "/events",
        json={
            "id": "raw_1",
            "type": "manual_note",
            "timestamp": "2025-02-03T09:00:00Z",
            "source": "yuki@helios.com",
            "raw_text": "Someone should open a ticket about PayPal.",
            "payload": {},
        },
    )
    proposal = resp.json()["extraction"]["proposal"]
    assert "approver" not in proposal["payload"]

    asks = [
        e for e in client.get("/events").json()
        if e["type"] == "message_sent"
        and e["payload"]["payload"].get("proposal_id") == proposal["id"]
    ]
    assert len(asks) == 1
    assert asks[0]["payload"]["payload"]["to"] == "pm@helios.com"


# --- amend: an author's reply records a truthful partial status ----------------


def test_amend_reply_records_partial_status_and_keeps_dependencies(client, monkeypatch):
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Helios", "pm": "pm@helios.com"})

    # state: a task that depends on a still-blocked upstream task
    setup = {
        "id": "evt_setup",
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {
            "deltas": [
                _delta("create", "Task", "upstream", {"status": "blocked"}),
                _delta("create", "Task", "downstream", {"status": "open"}),
                _delta(
                    "create", "Dependency", "dep1",
                    {"from_entity_id": "downstream", "to_entity_id": "upstream", "status": "active"},
                ),
            ],
            "actions": [],
        },
    }
    client.post("/events", json=setup)

    # author claims done; the model also optimistically resolves the dependency
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta("update", "Task", "downstream", {"status": "done"},
                              source_span="downstream is done"),
                ProposedDelta("update", "Dependency", "dep1", {"status": "resolved"},
                              source_span="downstream is done"),
            ]
        )
    )
    resp = client.post(
        "/events",
        json={
            "id": "raw_1", "type": "manual_note", "timestamp": "2025-02-03T09:00:00Z",
            "source": "yuki@helios.com", "raw_text": "downstream is done", "payload": {},
        },
    )
    proposal_id = resp.json()["extraction"]["proposal"]["id"]

    # the author clarifies: not really done, a piece is left -> amend to in_progress
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([
            ApprovalResolution(proposal_id, "amend", "almost, small fix left", amended_status="in_progress"),
        ]),
    )
    reply = client.post(
        "/events",
        json={
            "id": "raw_2", "type": "message_received", "timestamp": "2025-02-03T10:00:00Z",
            "source": "yuki@helios.com", "raw_text": "Almost -- a small fix left once the pipeline clears.",
            "payload": {"thread_id": _thread_of(client, proposal_id)},
        },
    )

    approvals = reply.json()["approvals"]
    assert len(approvals["amended"]) == 1

    state = client.get("/state").json()
    # the task gets the truthful partial status, NOT "done"
    assert state["Task"]["downstream"]["fields"]["status"] == "in_progress"
    # the dependency stays active -- the optimistic "resolved" was dropped
    assert state["Dependency"]["dep1"]["fields"]["status"] == "active"
    # the proposal is resolved (no longer pending)
    assert client.get("/proposals").json() == []


def test_revise_reply_proposes_model_revision_to_pm(client, monkeypatch):
    """A reply that says the MODEL is wrong spawns a structural revision for the PM.

    The author's reply contradicts a recorded dependency (not just a status), so
    the resolver returns `revise`. The agent drafts a correction -- here, deleting
    the bad dependency and marking the task done -- routed to the PM (not the
    author), and supersedes the original claim.
    """
    monkeypatch.setenv("AIPM_AUTO_EXTRACT", "1")
    client.post("/project", json={"name": "Helios", "pm": "pm@helios.com"})

    # state: downstream task depends on an upstream that is still in progress
    setup = {
        "id": "evt_setup",
        "type": "human_approval",
        "timestamp": "2025-01-01T00:00:00Z",
        "source": "test",
        "payload": {
            "deltas": [
                _delta("create", "Task", "upstream", {"status": "in_progress"}),
                _delta("create", "Task", "downstream", {"status": "open"}),
                _delta(
                    "create", "Dependency", "dep1",
                    {"from_entity_id": "downstream", "to_entity_id": "upstream", "status": "active"},
                ),
            ],
            "actions": [],
        },
    }
    client.post("/events", json=setup)

    # author claims downstream is done (the model also resolves the dependency)
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta("update", "Task", "downstream", {"status": "done"},
                              source_span="downstream is done"),
                ProposedDelta("update", "Dependency", "dep1", {"status": "resolved"},
                              source_span="downstream is done"),
            ]
        )
    )
    resp = client.post(
        "/events",
        json={
            "id": "raw_1", "type": "manual_note", "timestamp": "2025-02-03T09:00:00Z",
            "source": "dana@helios.com", "raw_text": "downstream is done", "payload": {},
        },
    )
    original_id = resp.json()["extraction"]["proposal"]["id"]

    # author clarifies: it's genuinely done, the dependency was never real ->
    # resolver returns `revise`, and the revision extraction deletes the dep and
    # marks the task done.
    _use_auto_provider(
        ExtractionResult(
            deltas=[
                ProposedDelta("delete", "Dependency", "dep1", {},
                              source_span="it never depended on upstream"),
                ProposedDelta("update", "Task", "downstream", {"status": "done"},
                              source_span="downstream is genuinely done"),
            ]
        ),
        ApprovalResult([
            ApprovalResolution(original_id, "revise", reason_span="it never depended on upstream"),
        ]),
    )
    reply = client.post(
        "/events",
        json={
            "id": "raw_2", "type": "message_received", "timestamp": "2025-02-03T10:00:00Z",
            "source": "dana@helios.com",
            "raw_text": "It's genuinely done -- it never depended on upstream, downstream is genuinely done.",
            "payload": {"thread_id": _thread_of(client, original_id)},
        },
    )

    approvals = reply.json()["approvals"]
    assert len(approvals["revised"]) == 1
    revision_id = approvals["revised"][0]["proposal_id"]
    assert approvals["revised"][0]["supersedes"] == original_id

    # The original claim is superseded; only the revision is pending now.
    pending = client.get("/proposals").json()
    assert [p["id"] for p in pending] == [revision_id]
    revision = pending[0]
    assert revision["payload"]["kind"] == "model_revision"
    # No approver set on the revision -> it routes to the PM, not the author.
    assert "approver" not in revision["payload"]

    # The revision approval request went to the PM.
    requests = [
        e for e in client.get("/events").json()
        if e["type"] == "message_sent"
        and e["payload"]["payload"].get("proposal_id") == revision_id
    ]
    assert requests and requests[0]["payload"]["payload"]["to"] == "pm@helios.com"

    # Nothing applied yet -- the dependency still exists, awaiting PM sign-off.
    state = client.get("/state").json()
    assert "dep1" in state["Dependency"]

    # PM approves the revision -> the bad dependency is deleted, task marked done.
    _use_auto_provider(
        ExtractionResult(),
        ApprovalResult([ApprovalResolution(revision_id, "approve", "go ahead")]),
    )
    client.post(
        "/events",
        json={
            "id": "raw_3", "type": "message_received", "timestamp": "2025-02-03T11:00:00Z",
            "source": "pm@helios.com", "raw_text": "Approved, go ahead.",
            "payload": {"thread_id": _thread_of(client, revision_id)},
        },
    )

    state = client.get("/state").json()
    assert "dep1" not in state["Dependency"]  # re-opened & corrected approved state
    assert state["Task"]["downstream"]["fields"]["status"] == "done"
    assert client.get("/proposals").json() == []


def _thread_of(client, proposal_id):
    """Find the thread_id the agent opened for a given proposal."""
    for e in client.get("/events").json():
        if e["type"] == "agent_proposal" and e["id"] == proposal_id:
            return e["payload"].get("thread_id")
    return None
