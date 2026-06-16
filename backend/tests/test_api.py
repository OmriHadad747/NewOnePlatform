"""API tests against an isolated, temporary event log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aipm.approval import ApprovalResolution, ApprovalResult
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


def _use_auto_provider(result: ExtractionResult, approval_result: ApprovalResult | None = None):
    """Override the auto-extraction (POST /events) provider with a fixed fake.

    The same provider serves both extraction and approval resolution; tests
    re-call this between steps to swap what the fake returns.
    """
    app.dependency_overrides[get_provider_optional] = lambda: StaticProvider(result, approval_result)


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
                    "send_email", "info_request", {"to": "bob", "subject": "Update?"},
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
    assert body["executed"][0]["type"] == "email_sent"
    assert body["executed"][0]["payload"]["payload"]["to"] == "bob"

    events = client.get("/events").json()
    assert any(e["type"] == "email_sent" for e in events)

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
    assert body["executed"][0]["type"] == "email_sent"
    assert body["proposal"] is None

    events = client.get("/events").json()
    assert any(e["type"] == "email_sent" for e in events)


def test_review_state_blocked_task_auto_sends_email(client):
    client.post("/events", json=_human_approval(
        "evt_1",
        _delta("create", "Task", "deploy-service",
               {"title": "Deploy", "status": "blocked", "owner": "alice"}),
    ))

    body = client.post("/review-state").json()

    assert body["issues"][0]["rule"] == "blocked_task"
    assert body["executed"][0]["type"] == "email_sent"
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
                    "send_email", "info_request", {"to": "bob", "subject": "Update?"},
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
    assert extraction["executed"][0]["type"] == "email_sent"
    assert any(e["type"] == "email_sent" for e in client.get("/events").json())


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
        "type": "email_reply_received",
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
        if e["type"] == "email_sent" and e["payload"]["payload"].get("proposal_id") == proposal_id
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
        e["type"] == "email_sent" and e["source"] == "agent:approval-nudge"
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
        e["type"] == "email_sent" and e["source"] == "agent:approval-escalation"
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
