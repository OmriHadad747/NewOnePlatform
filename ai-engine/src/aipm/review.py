"""Proactive state review: deterministic rule scanner, no LLM involved.

Scans the current ProjectState and returns action proposals for follow-up.
Info-request proposals (status pings, clarification asks) auto-execute like
/extract; consequential proposals (raise_flag, escalate) need human approval.

Status comparisons are case- and vocabulary-tolerant: the LLM picks the word,
so an answered question may read "closed"/"answered"/"resolved". Terminal
statuses (see the sets below) are treated as done and not chased again.

Rules:
- OpenQuestion whose status is not terminal -> send_message (info_request)
- Task where status in ("blocked", "stuck") -> send_message (info_request)
- Task where status is "in_progress" -> send_message, purpose=reminder (info_request)
- Risk of high/critical severity, status not terminal, no owner -> raise_flag (consequential)
- Deadline where due_date is in the past -> escalate_to_management (consequential)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from aipm.state import ProjectState

# Terminal statuses, kept vocabulary-tolerant because the LLM picks the word
# (an answered question may come back as "closed", "answered", "resolved", ...).
# Anything in these sets counts as "done" and is not chased again.
_RESOLVED_QUESTION_STATUSES = {"resolved", "closed", "answered", "decided", "done"}
_RESOLVED_RISK_STATUSES = {"resolved", "closed", "mitigated", "accepted", "retired"}
_HIGH_SEVERITIES = {"high", "critical"}


@dataclass
class ReviewIssue:
    rule: str
    entity_type: str
    entity_id: str
    detail: str


@dataclass
class ReviewResult:
    issues: list[ReviewIssue] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)


def review_state(state: ProjectState, now: datetime | None = None) -> ReviewResult:
    """Scan state and return action proposals for any issues found."""
    if now is None:
        now = datetime.now(timezone.utc)

    result = ReviewResult()
    _check_open_questions(state, result)
    _check_blocked_tasks(state, result)
    _check_in_progress_tasks(state, result)
    _check_unowned_high_risks(state, result)
    _check_overdue_deadlines(state, result, now)
    return result


def review_consequential_only(state: ProjectState, now: datetime | None = None) -> ReviewResult:
    """Only the checks that need PM approval (flags + escalation). Safe to auto-run."""
    if now is None:
        now = datetime.now(timezone.utc)

    result = ReviewResult()
    _check_unowned_high_risks(state, result)
    _check_overdue_deadlines(state, result, now)
    return result


def _owner(entity_fields: dict) -> str:
    return entity_fields.get("owner") or entity_fields.get("assignee") or "team"


def _check_open_questions(state: ProjectState, result: ReviewResult) -> None:
    for qid, entity in state.entities.get("OpenQuestion", {}).items():
        status = (entity.fields.get("status") or "").lower()
        if status in _RESOLVED_QUESTION_STATUSES:
            continue
        issue = ReviewIssue(
            rule="open_question",
            entity_type="OpenQuestion",
            entity_id=qid,
            detail=f"Open question has no answer: {entity.fields.get('description', qid)!r}",
        )
        result.issues.append(issue)
        result.actions.append({
            "type": "send_message",
            "category": "info_request",
            "payload": {
                "to": _owner(entity.fields),
                "subject": f"Follow-up: open question '{qid}'",
                "body": f"Still waiting for an answer on: {entity.fields.get('description', qid)}",
                "review_rule": issue.rule,
                "entity_id": qid,
            },
        })


def _check_blocked_tasks(state: ProjectState, result: ReviewResult) -> None:
    for tid, entity in state.entities.get("Task", {}).items():
        if (entity.fields.get("status") or "").lower() not in ("blocked", "stuck"):
            continue
        issue = ReviewIssue(
            rule="blocked_task",
            entity_type="Task",
            entity_id=tid,
            detail=f"Task '{tid}' is {entity.fields['status']}",
        )
        result.issues.append(issue)
        result.actions.append({
            "type": "send_message",
            "category": "info_request",
            "payload": {
                "to": _owner(entity.fields),
                "subject": f"Task '{tid}' is blocked -- what's needed?",
                "body": f"Task '{tid}' is currently {entity.fields['status']}. What is needed to unblock it?",
                "review_rule": issue.rule,
                "entity_id": tid,
            },
        })


def _check_in_progress_tasks(state: ProjectState, result: ReviewResult) -> None:
    for tid, entity in state.entities.get("Task", {}).items():
        if (entity.fields.get("status") or "").lower() not in ("in_progress", "in progress"):
            continue
        issue = ReviewIssue(
            rule="in_progress_task",
            entity_type="Task",
            entity_id=tid,
            detail=f"Task '{tid}' is in progress -- requesting status update",
        )
        result.issues.append(issue)
        result.actions.append({
            "type": "send_message",
            "category": "info_request",
            "payload": {
                "to": _owner(entity.fields),
                "subject": f"Status check: task '{tid}'",
                "body": f"Could you provide an update on task '{tid}'? Any blockers?",
                "purpose": "reminder",
                "review_rule": issue.rule,
                "entity_id": tid,
            },
        })


def _check_unowned_high_risks(state: ProjectState, result: ReviewResult) -> None:
    already_flagged = {a.payload.get("entity_id") for a in state.open_flags()}
    for rid, entity in state.entities.get("Risk", {}).items():
        if rid in already_flagged:
            continue
        status = (entity.fields.get("status") or "").lower()
        if status in _RESOLVED_RISK_STATUSES:
            continue
        if (entity.fields.get("severity") or "").lower() not in _HIGH_SEVERITIES:
            continue
        if entity.fields.get("owner") or entity.fields.get("assignee"):
            continue
        issue = ReviewIssue(
            rule="unowned_high_risk",
            entity_type="Risk",
            entity_id=rid,
            detail=f"High-severity risk '{rid}' is open with no owner",
        )
        result.issues.append(issue)
        result.actions.append({
            "type": "raise_flag",
            "category": "consequential",
            "payload": {
                "entity_type": "Risk",
                "entity_id": rid,
                "reason": f"High-severity risk '{rid}' is open with no assigned owner",
                "review_rule": issue.rule,
            },
        })


def _check_overdue_deadlines(state: ProjectState, result: ReviewResult, now: datetime) -> None:
    today = now.date()
    already_escalated = {
        a.payload.get("entity_id")
        for a in state.actions
        if a.type == "escalate_to_management"
    }
    for did, entity in state.entities.get("Deadline", {}).items():
        if did in already_escalated:
            continue
        due_date_str = entity.fields.get("due_date")
        if not due_date_str:
            continue
        try:
            due = date.fromisoformat(due_date_str)
        except ValueError:
            continue
        if due >= today:
            continue
        issue = ReviewIssue(
            rule="overdue_deadline",
            entity_type="Deadline",
            entity_id=did,
            detail=f"Deadline '{did}' was due {due_date_str} (overdue)",
        )
        result.issues.append(issue)
        result.actions.append({
            "type": "escalate_to_management",
            "category": "consequential",
            "payload": {
                "entity_type": "Deadline",
                "entity_id": did,
                "due_date": due_date_str,
                "reason": f"Deadline '{did}' ({due_date_str}) has passed with no resolution",
                "review_rule": issue.rule,
            },
        })
