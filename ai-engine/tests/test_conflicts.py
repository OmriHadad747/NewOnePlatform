"""Unit tests for semantic conflict detection."""

from __future__ import annotations

from aipm.conflicts import ConflictWarning, detect_conflicts
from aipm.entities import Entity
from aipm.projection import project
from aipm.state import ProjectState


def _state_with(**tables: dict) -> ProjectState:
    """Build a ProjectState with specific entity table contents."""
    state = ProjectState.empty()
    for entity_type, entities in tables.items():
        state.entities[entity_type] = entities
    return state


def _entity(entity_type: str, entity_id: str, **fields) -> Entity:
    return Entity(entity_type=entity_type, id=entity_id, fields=dict(fields))


def _delta(op: str, entity_type: str, entity_id: str, **fields) -> dict:
    return {"op": op, "entity_type": entity_type, "entity_id": entity_id, "fields": fields}


# --- deadline regression -------------------------------------------------------


def test_no_conflict_when_deadline_moves_later():
    state = _state_with(Deadline={
        "d1": _entity("Deadline", "d1", due_date="2025-02-01", status="committed")
    })
    delta = _delta("update", "Deadline", "d1", due_date="2025-02-10")
    assert detect_conflicts([delta], state) == []


def test_deadline_regression_detected():
    state = _state_with(Deadline={
        "d1": _entity("Deadline", "d1", due_date="2025-02-10", status="slipped")
    })
    delta = _delta("update", "Deadline", "d1", due_date="2025-01-20")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "deadline_regression"
    assert warnings[0].entity_id == "d1"
    assert "2025-02-10" in warnings[0].detail
    assert "2025-01-20" in warnings[0].detail


def test_no_conflict_for_new_deadline_creation():
    state = _state_with(Deadline={})
    delta = _delta("create", "Deadline", "d1", due_date="2025-01-15")
    assert detect_conflicts([delta], state) == []


def test_deadline_regression_only_on_update_with_existing_entity():
    state = _state_with(Deadline={})  # entity doesn't exist yet
    delta = _delta("update", "Deadline", "d1", due_date="2025-01-15")
    assert detect_conflicts([delta], state) == []


# --- task done with open dependency -------------------------------------------


def test_no_conflict_task_done_no_dependencies():
    state = _state_with(Task={"t1": _entity("Task", "t1", status="in_progress")}, Dependency={})
    delta = _delta("update", "Task", "t1", status="done")
    assert detect_conflicts([delta], state) == []


def test_no_conflict_task_done_upstream_also_done():
    state = _state_with(
        Task={
            "t1": _entity("Task", "t1", status="in_progress"),
            "t2": _entity("Task", "t2", status="done"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="t1", to_entity_id="t2", status="active"),
        },
    )
    delta = _delta("update", "Task", "t1", status="done")
    assert detect_conflicts([delta], state) == []


def test_task_done_with_open_dep_detected():
    state = _state_with(
        Task={
            "integrate-sso": _entity("Task", "integrate-sso", status="open"),
            "build-auth": _entity("Task", "build-auth", status="in_progress"),
        },
        Dependency={
            "sso-needs-auth": _entity("Dependency", "sso-needs-auth",
                                      from_entity_id="integrate-sso",
                                      to_entity_id="build-auth",
                                      status="active"),
        },
    )
    delta = _delta("update", "Task", "integrate-sso", status="done")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "task_done_with_open_dep"
    assert warnings[0].entity_id == "integrate-sso"
    assert "build-auth" in warnings[0].detail
    assert "sso-needs-auth" in warnings[0].detail


def test_no_conflict_task_done_dep_broken():
    state = _state_with(
        Task={
            "t1": _entity("Task", "t1", status="open"),
            "t2": _entity("Task", "t2", status="blocked"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="t1", to_entity_id="t2", status="broken"),
        },
    )
    delta = _delta("update", "Task", "t1", status="done")
    assert detect_conflicts([delta], state) == []


def test_completed_status_also_triggers_check():
    state = _state_with(
        Task={
            "t1": _entity("Task", "t1", status="open"),
            "t2": _entity("Task", "t2", status="open"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="t1", to_entity_id="t2", status="active"),
        },
    )
    delta = _delta("update", "Task", "t1", status="completed")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "task_done_with_open_dep"


# --- risk severity downgrade ---------------------------------------------------


def test_no_conflict_risk_severity_stays_same():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="high", status="open")})
    delta = _delta("update", "Risk", "r1", severity="high")
    assert detect_conflicts([delta], state) == []


def test_no_conflict_risk_severity_increases():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="low", status="open")})
    delta = _delta("update", "Risk", "r1", severity="high")
    assert detect_conflicts([delta], state) == []


def test_risk_downgraded_detected():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="high", status="open")})
    delta = _delta("update", "Risk", "r1", severity="medium")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "risk_downgraded"
    assert warnings[0].entity_id == "r1"
    assert "high" in warnings[0].detail
    assert "medium" in warnings[0].detail


def test_no_conflict_risk_downgraded_with_resolved_status():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="high", status="open")})
    delta = _delta("update", "Risk", "r1", severity="low", status="resolved")
    assert detect_conflicts([delta], state) == []


def test_risk_downgrade_requires_existing_entity():
    state = _state_with(Risk={})
    delta = _delta("update", "Risk", "r1", severity="low")
    assert detect_conflicts([delta], state) == []


# --- multiple conflicts in one batch ------------------------------------------


def test_multiple_conflicts_returned():
    state = _state_with(
        Deadline={"d1": _entity("Deadline", "d1", due_date="2025-03-01")},
        Risk={"r1": _entity("Risk", "r1", severity="high", status="open")},
        Task={},
        Dependency={},
    )
    deltas = [
        _delta("update", "Deadline", "d1", due_date="2025-01-01"),
        _delta("update", "Risk", "r1", severity="low"),
    ]
    warnings = detect_conflicts(deltas, state)
    assert len(warnings) == 2
    types = {w.type for w in warnings}
    assert "deadline_regression" in types
    assert "risk_downgraded" in types


def test_no_conflicts_empty_deltas():
    assert detect_conflicts([], ProjectState.empty()) == []


# --- project deadline exceeded ------------------------------------------------


def test_no_conflict_when_no_project_end_date():
    state = ProjectState.empty()
    delta = _delta("create", "Deadline", "d1", due_date="2099-12-31")
    assert detect_conflicts([delta], state) == []


def test_project_deadline_exceeded_detected():
    state = ProjectState.empty()
    state.meta["end_date"] = "2026-11-28"
    delta = _delta("create", "Deadline", "sprint-end", due_date="2026-12-15")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "project_deadline_exceeded"
    assert warnings[0].entity_id == "sprint-end"
    assert "2026-12-15" in warnings[0].detail
    assert "2026-11-28" in warnings[0].detail


def test_project_deadline_not_exceeded_on_same_day():
    state = ProjectState.empty()
    state.meta["end_date"] = "2026-11-28"
    delta = _delta("create", "Deadline", "d1", due_date="2026-11-28")
    assert detect_conflicts([delta], state) == []


def test_project_deadline_exceeded_on_any_entity_type():
    state = ProjectState.empty()
    state.meta["end_date"] = "2026-11-28"
    delta = _delta("create", "Task", "t1", due_date="2027-01-01")
    warnings = detect_conflicts([delta], state)
    assert len(warnings) == 1
    assert warnings[0].type == "project_deadline_exceeded"


def test_project_deadline_ignores_non_date_fields():
    state = ProjectState.empty()
    state.meta["end_date"] = "2026-11-28"
    delta = _delta("create", "Task", "t1", title="Launch by 2027 if possible", status="open")
    assert detect_conflicts([delta], state) == []


def test_project_deadline_exceeded_combined_with_other_conflicts():
    state = _state_with(
        Deadline={"d1": _entity("Deadline", "d1", due_date="2026-10-01")},
    )
    state.meta["end_date"] = "2026-11-28"
    deltas = [
        _delta("update", "Deadline", "d1", due_date="2026-09-01"),  # regression
        _delta("create", "Task", "t2", due_date="2027-03-01"),      # exceeds project end
    ]
    warnings = detect_conflicts(deltas, state)
    types = {w.type for w in warnings}
    assert "deadline_regression" in types
    assert "project_deadline_exceeded" in types


# --- author-clarifiable classification -----------------------------------------


def test_author_clarifiable_selects_author_claims():
    from aipm.conflicts import AUTHOR_CLARIFIABLE, author_clarifiable

    warnings = [
        ConflictWarning("task_done_with_open_dep", "t1", "done while blocked"),
        ConflictWarning("deadline_regression", "d1", "pulled earlier"),
        ConflictWarning("risk_downgraded", "r1", "quietly downgraded"),
        ConflictWarning("project_deadline_exceeded", "x1", "past project end"),
    ]
    picked = {w.type for w in author_clarifiable(warnings)}
    assert picked == {"task_done_with_open_dep", "deadline_regression", "risk_downgraded"}
    # a timeline breach is a PM acknowledgment, never an author "did you mean it"
    assert "project_deadline_exceeded" not in AUTHOR_CLARIFIABLE


def test_author_clarifiable_empty_when_no_author_conflicts():
    from aipm.conflicts import author_clarifiable

    assert author_clarifiable([]) == []
    assert author_clarifiable([ConflictWarning("project_deadline_exceeded", "x", "...")]) == []


# --- end-state inconsistencies (the approval gate) -----------------------------


def test_state_inconsistency_done_task_with_active_dep():
    from aipm.conflicts import state_inconsistencies

    state = _state_with(
        Task={
            "downstream": _entity("Task", "downstream", status="done"),
            "upstream": _entity("Task", "upstream", status="in_progress"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="downstream", to_entity_id="upstream", status="active"),
        },
    )
    warnings = state_inconsistencies(state)
    assert [w.type for w in warnings] == ["task_done_with_open_dep"]
    assert warnings[0].entity_id == "downstream"


def test_state_inconsistency_clear_when_dependency_removed():
    from aipm.conflicts import state_inconsistencies

    # same as above but the dependency is gone (the coherent full-revision case)
    state = _state_with(
        Task={
            "downstream": _entity("Task", "downstream", status="done"),
            "upstream": _entity("Task", "upstream", status="in_progress"),
        },
        Dependency={},
    )
    assert state_inconsistencies(state) == []


def test_state_inconsistency_clear_when_dependency_resolved():
    from aipm.conflicts import state_inconsistencies

    state = _state_with(
        Task={
            "downstream": _entity("Task", "downstream", status="done"),
            "upstream": _entity("Task", "upstream", status="in_progress"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="downstream", to_entity_id="upstream", status="resolved"),
        },
    )
    assert state_inconsistencies(state) == []


def test_state_inconsistency_clear_when_upstream_also_done():
    from aipm.conflicts import state_inconsistencies

    state = _state_with(
        Task={
            "downstream": _entity("Task", "downstream", status="done"),
            "upstream": _entity("Task", "upstream", status="done"),
        },
        Dependency={
            "dep1": _entity("Dependency", "dep1",
                            from_entity_id="downstream", to_entity_id="upstream", status="active"),
        },
    )
    assert state_inconsistencies(state) == []
