"""Unit tests for the deterministic projection function."""

from __future__ import annotations

import pytest

from aipm.events import Event
from aipm.projection import ProjectionError, project


def _manual_edit(event_id: str, *deltas: dict) -> Event:
    return Event(
        id=event_id,
        type="manual_edit",
        timestamp="2025-01-01T00:00:00Z",
        source="test",
        payload={"deltas": list(deltas)},
    )


def _delta(op: str, entity_type: str, entity_id: str, fields: dict, **prov) -> dict:
    return {
        "op": op,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "fields": fields,
        "provenance": {"asserted_by": "tester", **prov},
    }


def test_create_then_read_back():
    events = [
        _manual_edit(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        )
    ]

    state = project(events)

    task = state.get("Task", "t1")
    assert task.fields == {"title": "Do thing", "status": "open"}
    assert len(task.history) == 1
    assert task.history[0].asserted_by == "tester"


def test_update_merges_fields_and_records_history():
    events = [
        _manual_edit(
            "evt_1",
            _delta("create", "Decision", "d1", {"description": "Use Postgres", "status": "decided"}),
        ),
        _manual_edit(
            "evt_2",
            _delta("update", "Decision", "d1", {"description": "Use MySQL"}),
        ),
    ]

    state = project(events)

    decision = state.get("Decision", "d1")
    assert decision.fields == {"description": "Use MySQL", "status": "decided"}
    assert len(decision.history) == 2


def test_replaying_same_events_is_deterministic():
    events = [
        _manual_edit(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        ),
        _manual_edit(
            "evt_2",
            _delta("update", "Task", "t1", {"status": "done"}),
        ),
    ]

    state_a = project(events)
    state_b = project(events)

    assert state_a.get("Task", "t1").fields == state_b.get("Task", "t1").fields
    assert len(state_a.get("Task", "t1").history) == len(state_b.get("Task", "t1").history)


def test_create_on_existing_entity_raises():
    events = [
        _manual_edit(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        ),
        _manual_edit(
            "evt_2",
            _delta("create", "Task", "t1", {"title": "Duplicate", "status": "open"}),
        ),
    ]

    with pytest.raises(ProjectionError, match="already exists"):
        project(events)


def test_update_on_missing_entity_raises():
    events = [
        _manual_edit(
            "evt_1",
            _delta("update", "Task", "t1", {"status": "done"}),
        )
    ]

    with pytest.raises(ProjectionError, match="does not exist"):
        project(events)


def test_delta_without_asserted_by_raises():
    events = [
        Event(
            id="evt_1",
            type="manual_edit",
            timestamp="2025-01-01T00:00:00Z",
            source="test",
            payload={
                "deltas": [
                    {
                        "op": "create",
                        "entity_type": "Task",
                        "entity_id": "t1",
                        "fields": {"title": "Do thing"},
                        "provenance": {},
                    }
                ]
            },
        )
    ]

    with pytest.raises(ProjectionError, match="asserted_by"):
        project(events)


def test_non_delta_events_have_no_effect_on_state():
    events = [
        Event(
            id="evt_1",
            type="transcript_ingested",
            timestamp="2025-01-01T00:00:00Z",
            source="meeting",
            raw_text="We discussed many things.",
            payload={},
        )
    ]

    state = project(events)

    assert all(table == {} for table in state.entities.values())
