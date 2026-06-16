"""Semantic conflict detection: pure, deterministic, no network.

`detect_conflicts(deltas, state)` checks a list of proposed deltas against
the current ProjectState and returns a list of ConflictWarnings -- semantic
inconsistencies a human reviewer should know about before approving. Nothing
here blocks a proposal; conflicts are advisory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aipm.state import ProjectState

# How much worse each severity tier is relative to "low". Used to detect
# downgrade: if the proposed severity ranks lower than the current one,
# that's unusual without an accompanying resolution.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_DONE_STATUSES = {"done", "completed", "closed"}


@dataclass
class ConflictWarning:
    type: str       # "deadline_regression" | "task_done_with_open_dep" | "risk_downgraded"
    entity_id: str
    detail: str


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
