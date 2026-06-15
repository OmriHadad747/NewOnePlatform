"""API tests against an isolated, temporary event log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta

from aipm_backend.extraction import StaticProvider, get_provider
from aipm_backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPM_EVENT_LOG", str(tmp_path / "events.jsonl"))
    return TestClient(app)


def _use_provider(result: ExtractionResult):
    """Override the extraction provider with a fixed-result fake."""
    app.dependency_overrides[get_provider] = lambda: StaticProvider(result)


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


def test_approve_unknown_proposal_is_404(client):
    assert client.post("/proposals/nope/approve").status_code == 404
