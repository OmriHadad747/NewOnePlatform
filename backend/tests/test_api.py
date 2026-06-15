"""API tests against an isolated, temporary event log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aipm_backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPM_EVENT_LOG", str(tmp_path / "events.jsonl"))
    return TestClient(app)


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
        "type": "manual_edit",
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
