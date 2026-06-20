"""Unit tests for the deterministic state review scanner."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aipm.entities import Entity
from aipm.review import ReviewResult, review_state
from aipm.state import ProjectState


def _state_with(**tables: dict) -> ProjectState:
    state = ProjectState.empty()
    for entity_type, entities in tables.items():
        state.entities[entity_type] = entities
    return state


def _entity(entity_type: str, entity_id: str, **fields) -> Entity:
    return Entity(entity_type=entity_type, id=entity_id, fields=dict(fields))


def _past(days: int = 10) -> datetime:
    from datetime import timedelta
    return datetime(2025, 6, 1, tzinfo=timezone.utc) + timedelta(days=days)


_NOW = datetime(2025, 6, 16, tzinfo=timezone.utc)


# --- clean state ---------------------------------------------------------------


def test_no_issues_empty_state():
    result = review_state(ProjectState.empty(), now=_NOW)
    assert result.issues == []
    assert result.actions == []


# --- open questions -------------------------------------------------------------


def test_open_question_triggers_send_message():
    state = _state_with(OpenQuestion={
        "api-access": _entity("OpenQuestion", "api-access",
                               description="Who owns API access?", status="open"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "open_question"
    assert result.issues[0].entity_id == "api-access"
    action = result.actions[0]
    assert action["type"] == "send_message"
    assert action["category"] == "info_request"
    assert "api-access" in action["payload"]["subject"]


def test_resolved_question_not_flagged():
    state = _state_with(OpenQuestion={
        "q1": _entity("OpenQuestion", "q1", status="resolved"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


@pytest.mark.parametrize("status", ["closed", "answered", "decided", "DONE", "Resolved"])
def test_terminal_question_statuses_not_flagged(status):
    # vocabulary-tolerant: the LLM may answer a question as "closed"/"answered"
    state = _state_with(OpenQuestion={"q1": _entity("OpenQuestion", "q1", status=status)})
    assert review_state(state, now=_NOW).issues == []


def test_open_question_without_status_is_flagged():
    state = _state_with(OpenQuestion={
        "q1": _entity("OpenQuestion", "q1", description="pending question"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "open_question"


# --- blocked / stuck tasks -----------------------------------------------------


def test_blocked_task_triggers_send_message():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", title="Deploy service", status="blocked"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "blocked_task"
    assert result.actions[0]["type"] == "send_message"
    assert result.actions[0]["category"] == "info_request"


def test_stuck_task_also_triggers():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="stuck"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues[0].rule == "blocked_task"


def test_done_task_not_flagged():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="done"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_open_task_not_flagged():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="open"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


# --- in-progress tasks ---------------------------------------------------------


def test_in_progress_task_triggers_reminder_message():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="in_progress", owner="alice"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "in_progress_task"
    action = result.actions[0]
    assert action["type"] == "send_message"
    assert action["category"] == "info_request"
    assert action["payload"]["purpose"] == "reminder"
    assert action["payload"]["to"] == "alice"


def test_in_progress_uses_assignee_as_fallback():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="in_progress", assignee="bob"),
    })
    result = review_state(state, now=_NOW)
    assert result.actions[0]["payload"]["to"] == "bob"


def test_in_progress_falls_back_to_team():
    state = _state_with(Task={
        "t1": _entity("Task", "t1", status="in_progress"),
    })
    result = review_state(state, now=_NOW)
    assert result.actions[0]["payload"]["to"] == "team"


# --- unowned high risks --------------------------------------------------------


def test_unowned_high_risk_triggers_raise_flag():
    state = _state_with(Risk={
        "vendor-delay": _entity("Risk", "vendor-delay", severity="high", status="open"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "unowned_high_risk"
    action = result.actions[0]
    assert action["type"] == "raise_flag"
    assert action["category"] == "consequential"
    assert action["payload"]["entity_id"] == "vendor-delay"


def test_owned_high_risk_not_flagged():
    state = _state_with(Risk={
        "r1": _entity("Risk", "r1", severity="high", status="open", owner="alice"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_low_severity_risk_not_flagged():
    state = _state_with(Risk={
        "r1": _entity("Risk", "r1", severity="low", status="open"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_resolved_high_risk_not_flagged():
    state = _state_with(Risk={
        "r1": _entity("Risk", "r1", severity="high", status="resolved"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_high_risk_without_status_is_flagged():
    # a high risk that was never explicitly resolved should still be chased
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="high")})
    result = review_state(state, now=_NOW)
    assert result.issues[0].rule == "unowned_high_risk"


def test_critical_severity_is_flagged():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="critical", status="open")})
    result = review_state(state, now=_NOW)
    assert result.issues[0].rule == "unowned_high_risk"


def test_mitigated_high_risk_not_flagged():
    state = _state_with(Risk={"r1": _entity("Risk", "r1", severity="high", status="mitigated")})
    assert review_state(state, now=_NOW).issues == []


# --- overdue deadlines ---------------------------------------------------------


def test_overdue_deadline_triggers_escalation():
    state = _state_with(Deadline={
        "sprint-end": _entity("Deadline", "sprint-end", due_date="2025-06-01"),
    })
    result = review_state(state, now=_NOW)
    assert len(result.issues) == 1
    assert result.issues[0].rule == "overdue_deadline"
    action = result.actions[0]
    assert action["type"] == "escalate_to_management"
    assert action["category"] == "consequential"
    assert action["payload"]["due_date"] == "2025-06-01"


def test_future_deadline_not_flagged():
    state = _state_with(Deadline={
        "d1": _entity("Deadline", "d1", due_date="2025-12-31"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_deadline_today_not_flagged():
    today_str = _NOW.date().isoformat()
    state = _state_with(Deadline={
        "d1": _entity("Deadline", "d1", due_date=today_str),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


def test_deadline_without_due_date_skipped():
    state = _state_with(Deadline={
        "d1": _entity("Deadline", "d1", description="some deadline"),
    })
    result = review_state(state, now=_NOW)
    assert result.issues == []


# --- multiple issues -----------------------------------------------------------


def test_multiple_rules_all_fire():
    state = _state_with(
        OpenQuestion={"q1": _entity("OpenQuestion", "q1", status="open")},
        Task={"t1": _entity("Task", "t1", status="blocked")},
        Risk={"r1": _entity("Risk", "r1", severity="high", status="open")},
        Deadline={"d1": _entity("Deadline", "d1", due_date="2025-01-01")},
    )
    result = review_state(state, now=_NOW)
    rules = {i.rule for i in result.issues}
    assert rules == {"open_question", "blocked_task", "unowned_high_risk", "overdue_deadline"}
    assert len(result.actions) == 4
    cats = {a["category"] for a in result.actions}
    assert "info_request" in cats
    assert "consequential" in cats
