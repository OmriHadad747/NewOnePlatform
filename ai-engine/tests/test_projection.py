"""Unit tests for the deterministic projection function."""

from __future__ import annotations

import pytest

from aipm.events import Event
from aipm.projection import ProjectionError, project


def _human_approval(event_id: str, *deltas: dict, actions: list[dict] | None = None) -> Event:
    return Event(
        id=event_id,
        type="human_approval",
        timestamp="2025-01-01T00:00:00Z",
        source="test",
        payload={"deltas": list(deltas), **({"actions": actions} if actions else {})},
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
        _human_approval(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        )
    ]

    state = project(events)

    task = state.get("Task", "t1")
    assert task.fields == {"title": "Do thing", "status": "open"}
    assert len(task.history) == 1
    assert task.history[0].asserted_by == "tester"


def _project_initialized(event_id: str, **meta) -> Event:
    return Event(
        id=event_id,
        type="project_initialized",
        timestamp="2025-01-01T00:00:00Z",
        source="cli:init",
        payload=dict(meta),
    )


def test_empty_state_has_empty_meta():
    assert project([]).meta == {}


def test_project_initialized_sets_meta():
    state = project([_project_initialized("p1", name="Apollo", team=["alice", "bob"])])
    assert state.meta == {"name": "Apollo", "team": ["alice", "bob"]}


def test_project_initialized_merges_on_reinit():
    state = project([
        _project_initialized("p1", name="Apollo", team=["alice"]),
        _project_initialized("p2", name="Apollo 2", description="now with rovers"),
    ])
    assert state.meta == {"name": "Apollo 2", "team": ["alice"], "description": "now with rovers"}


def test_project_initialized_does_not_touch_entities():
    state = project([_project_initialized("p1", name="Apollo")])
    assert all(table == {} for table in state.entities.values())
    assert state.actions == []


def test_update_merges_fields_and_records_history():
    events = [
        _human_approval(
            "evt_1",
            _delta("create", "Decision", "d1", {"description": "Use Postgres", "status": "decided"}),
        ),
        _human_approval(
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
        _human_approval(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        ),
        _human_approval(
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
        _human_approval(
            "evt_1",
            _delta("create", "Task", "t1", {"title": "Do thing", "status": "open"}),
        ),
        _human_approval(
            "evt_2",
            _delta("create", "Task", "t1", {"title": "Duplicate", "status": "open"}),
        ),
    ]

    with pytest.raises(ProjectionError, match="already exists"):
        project(events)


def test_update_on_missing_entity_raises():
    events = [
        _human_approval(
            "evt_1",
            _delta("update", "Task", "t1", {"status": "done"}),
        )
    ]

    with pytest.raises(ProjectionError, match="does not exist"):
        project(events)


def test_delete_removes_entity():
    events = [
        _human_approval(
            "evt_1",
            _delta(
                "create", "Dependency", "dep1",
                {"from_entity_id": "a", "to_entity_id": "b", "status": "active"},
            ),
        ),
        _human_approval(
            "evt_2",
            _delta("delete", "Dependency", "dep1", {}),
        ),
    ]

    state = project(events)
    assert "dep1" not in state.entities["Dependency"]


def test_delete_on_missing_entity_raises():
    events = [
        _human_approval("evt_1", _delta("delete", "Task", "ghost", {})),
    ]

    with pytest.raises(ProjectionError, match="cannot delete"):
        project(events)


def test_delete_then_recreate_is_allowed():
    """A delete clears the id, so a later create of the same id is not a clash."""
    events = [
        _human_approval("evt_1", _delta("create", "Task", "t1", {"status": "open"})),
        _human_approval("evt_2", _delta("delete", "Task", "t1", {})),
        _human_approval("evt_3", _delta("create", "Task", "t1", {"status": "done"})),
    ]

    state = project(events)
    assert state.entities["Task"]["t1"].fields["status"] == "done"


def test_delta_without_asserted_by_raises():
    events = [
        Event(
            id="evt_1",
            type="human_approval",
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


def test_manual_note_with_deltas_has_no_effect_on_state():
    """manual_note is raw input (a person typing a new note into the
    platform), not an approval -- its deltas, if any, must be ignored."""
    events = [
        Event(
            id="evt_1",
            type="manual_note",
            timestamp="2025-01-01T00:00:00Z",
            source="note",
            raw_text="Decided to use Postgres.",
            payload={
                "deltas": [
                    _delta("create", "Decision", "db-choice", {"description": "Use Postgres"})
                ]
            },
        )
    ]

    state = project(events)

    assert all(table == {} for table in state.entities.values())
    assert state.actions == []


def test_action_is_recorded_with_provenance():
    events = [
        _human_approval(
            "evt_1",
            actions=[
                {
                    "type": "send_message",
                    "category": "info_request",
                    "payload": {"to": "bob", "body": "Can you share an update?"},
                    "provenance": {"asserted_by": "agent", "source_span": "ask bob for an update"},
                }
            ],
        )
    ]

    state = project(events)

    assert len(state.actions) == 1
    action = state.actions[0]
    assert action.type == "send_message"
    assert action.category == "info_request"
    assert action.payload == {"to": "bob", "body": "Can you share an update?"}
    assert action.asserted_by == "agent"
    assert action.source_event_id == "evt_1"


def test_action_with_unknown_category_raises():
    events = [
        _human_approval(
            "evt_1",
            actions=[
                {
                    "type": "send_message",
                    "category": "urgent",
                    "payload": {},
                    "provenance": {"asserted_by": "agent"},
                }
            ],
        )
    ]

    with pytest.raises(ProjectionError, match="category"):
        project(events)


def test_action_without_asserted_by_raises():
    events = [
        _human_approval(
            "evt_1",
            actions=[
                {
                    "type": "send_message",
                    "category": "info_request",
                    "payload": {},
                    "provenance": {},
                }
            ],
        )
    ]

    with pytest.raises(ProjectionError, match="asserted_by"):
        project(events)
