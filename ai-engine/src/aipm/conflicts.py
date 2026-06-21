"""Semantic conflict detection: pure, deterministic, no network.

`detect_conflicts(deltas, state)` checks a list of proposed deltas against
the current ProjectState and returns a list of ConflictWarnings -- semantic
inconsistencies a human reviewer should know about before approving. Nothing
here blocks a proposal; conflicts are advisory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from aipm.state import ProjectState

# How much worse each severity tier is relative to "low". Used to detect
# downgrade: if the proposed severity ranks lower than the current one,
# that's unusual without an accompanying resolution.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_DONE_STATUSES = {"done", "completed", "closed"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ConflictWarning:
    type: str       # "deadline_regression" | "task_done_with_open_dep" | "risk_downgraded" | "project_deadline_exceeded"
    entity_id: str
    detail: str


# Conflict types where the *author's own input* contradicts known state -- the
# kind of thing to check back with whoever said it ("did you really mean this?")
# before escalating to a project manager. `project_deadline_exceeded` is left
# out on purpose: a timeline breach is a PM acknowledgment, already surfaced as
# a consequential flag the PM must sign off on -- not a "did you mean it" for
# the author.
AUTHOR_CLARIFIABLE: frozenset[str] = frozenset({
    "task_done_with_open_dep",
    "deadline_regression",
    "risk_downgraded",
})


def author_clarifiable(warnings: list[ConflictWarning]) -> list[ConflictWarning]:
    """Subset of `warnings` the message author can clarify, vs. a PM decision.

    Lets the extraction flow route a contradicting claim back to whoever made
    it before it ever reaches a project manager. Pure: just a type filter.
    """
    return [w for w in warnings if w.type in AUTHOR_CLARIFIABLE]


def state_inconsistencies(state: ProjectState) -> list[ConflictWarning]:
    """End-state invariants a committed state should not silently violate.

    Unlike `detect_conflicts` (which judges a *transition* -- proposed deltas vs.
    current state), this judges a *resulting state* on its own. It is what an
    approval gate runs on the would-be state, so a partial approval can't quietly
    commit a contradiction the original proposal review never showed.

    Currently one invariant: a task marked done while it still has an ACTIVE
    dependency on an upstream task that is not done -- if it were truly finished,
    that dependency would be resolved or was never real. Pure and deterministic.
    """
    warnings: list[ConflictWarning] = []
    task_table = state.entities.get("Task", {})
    dep_table = state.entities.get("Dependency", {})
    for dep_id, dep in dep_table.items():
        if dep.fields.get("status") != "active":
            continue
        downstream = task_table.get(dep.fields.get("from_entity_id", ""))
        upstream = task_table.get(dep.fields.get("to_entity_id", ""))
        if not downstream or downstream.fields.get("status") not in _DONE_STATUSES:
            continue
        if upstream and upstream.fields.get("status") in _DONE_STATUSES:
            continue
        upstream_status = upstream.fields.get("status", "missing") if upstream else "missing"
        warnings.append(ConflictWarning(
            type="task_done_with_open_dep",
            entity_id=dep.fields.get("from_entity_id", ""),
            detail=(
                f"Task '{dep.fields.get('from_entity_id', '')}' is marked done but still "
                f"has an active dependency ({dep_id}) on '{dep.fields.get('to_entity_id', '')}' "
                f"(status: '{upstream_status}')."
            ),
        ))
    return warnings


def detect_conflicts(deltas: list[dict], state: ProjectState) -> list[ConflictWarning]:
    """Return semantic conflict warnings for the proposed deltas vs. current state.

    `deltas` is in the payload format (each dict has op/entity_type/entity_id/fields).
    Does not modify state.
    """
    warnings: list[ConflictWarning] = []
    for delta in deltas:
        entity_type = delta.get("entity_type", "")
        entity_id = delta.get("entity_id", "")
        fields = delta.get("fields", {})
        op = delta.get("op", "")

        if entity_type == "Deadline":
            w = _check_deadline(op, entity_id, fields, state)
            if w:
                warnings.append(w)

        elif entity_type == "Task":
            w = _check_task_done(op, entity_id, fields, state)
            if w:
                warnings.append(w)

        elif entity_type == "Risk":
            w = _check_risk_downgrade(op, entity_id, fields, state)
            if w:
                warnings.append(w)

        # Timeline breach applies to any entity type: if the project has a known
        # end date, any proposed date field beyond it is a conflict to surface.
        if project_end := state.meta.get("end_date"):
            w = _check_project_deadline(entity_type, entity_id, fields, project_end)
            if w:
                warnings.append(w)

    return warnings


def _check_deadline(op: str, entity_id: str, fields: dict, state: ProjectState) -> ConflictWarning | None:
    """Flag if due_date moves earlier than the current committed date."""
    new_date = fields.get("due_date")
    if not new_date:
        return None

    current = state.entities.get("Deadline", {}).get(entity_id)
    if op == "update" and current:
        cur_date = current.fields.get("due_date")
        if cur_date and new_date < cur_date:
            return ConflictWarning(
                type="deadline_regression",
                entity_id=entity_id,
                detail=(
                    f"due_date moving earlier: {cur_date} -> {new_date}. "
                    "Confirm this is intentional and not an accidental regression."
                ),
            )
    return None


def _check_task_done(op: str, entity_id: str, fields: dict, state: ProjectState) -> ConflictWarning | None:
    """Flag if a task is marked done while it has an active upstream dependency."""
    if fields.get("status") not in _DONE_STATUSES:
        return None

    dep_table = state.entities.get("Dependency", {})
    task_table = state.entities.get("Task", {})

    for dep_id, dep in dep_table.items():
        if dep.fields.get("from_entity_id") != entity_id:
            continue
        if dep.fields.get("status") != "active":
            continue
        upstream_id = dep.fields.get("to_entity_id", "")
        upstream = task_table.get(upstream_id)
        if upstream and upstream.fields.get("status") not in _DONE_STATUSES:
            return ConflictWarning(
                type="task_done_with_open_dep",
                entity_id=entity_id,
                detail=(
                    f"Task marked '{fields['status']}' but has an active dependency "
                    f"on '{upstream_id}' (current status: "
                    f"'{upstream.fields.get('status', 'unknown')}'). "
                    f"Dependency: {dep_id}."
                ),
            )
    return None


def _check_project_deadline(
    entity_type: str, entity_id: str, fields: dict, project_end: str
) -> ConflictWarning | None:
    """Flag any ISO date field that falls after the project end date.

    The LLM picks field names freely, so we scan all field values rather than a
    fixed field-name list. One warning per delta (the first offending field).
    """
    for field_name, value in fields.items():
        if isinstance(value, str) and _ISO_DATE_RE.match(value) and value > project_end:
            return ConflictWarning(
                type="project_deadline_exceeded",
                entity_id=entity_id,
                detail=(
                    f"{entity_type} '{entity_id}': {field_name}={value} is after "
                    f"project end date {project_end}."
                ),
            )
    return None


def _check_risk_downgrade(op: str, entity_id: str, fields: dict, state: ProjectState) -> ConflictWarning | None:
    """Flag if risk severity decreases without an accompanying status resolution."""
    new_sev = fields.get("severity")
    if not new_sev:
        return None

    new_status = fields.get("status", "")
    if new_status in {"resolved", "closed"}:
        return None  # explicit resolution, no conflict

    current = state.entities.get("Risk", {}).get(entity_id)
    if op == "update" and current:
        cur_sev = current.fields.get("severity", "")
        cur_rank = _SEVERITY_RANK.get(cur_sev, -1)
        new_rank = _SEVERITY_RANK.get(new_sev, -1)
        if cur_rank > new_rank >= 0:
            return ConflictWarning(
                type="risk_downgraded",
                entity_id=entity_id,
                detail=(
                    f"Risk severity lowered from '{cur_sev}' to '{new_sev}' "
                    f"without a status change to resolved/closed. "
                    "Confirm this reflects a genuine improvement."
                ),
            )
    return None
