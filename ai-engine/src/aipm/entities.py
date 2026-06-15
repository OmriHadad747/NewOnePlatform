"""Entity model: every tracked fact, with provenance.

All seven entity types (Decision, Task, Owner, Deadline, Risk, Dependency,
OpenQuestion) share the same shape: a set of current field values plus a
history of provenance records explaining how those values were reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ENTITY_TYPES = {
    "Decision",
    "Task",
    "Owner",
    "Deadline",
    "Risk",
    "Dependency",
    "OpenQuestion",
}

# Categories for proposed actions (see `Action` below). `info_request`
# actions are routine info-gathering communications the agent sends on its
# own (no approval needed); `consequential` actions (opening tickets,
# escalating to management, raising flags) require human approval.
ACTION_CATEGORIES = {"info_request", "consequential"}

# Action types the agent may propose, and the outbound event type that
# records each one's (stubbed) execution -- immediately for `info_request`
# actions, or once a `human_approval` applies a `consequential` one. See
# `aipm.events` for the outbound event types themselves.
ACTION_TYPE_OUTBOUND_EVENTS = {
    "send_email": "email_sent",
    "send_reminder": "reminder_sent",
    "open_ticket": "ticket_opened",
    "raise_flag": "flag_raised",
    "escalate_to_management": "report_to_management",
}

# Fallback outbound event type, by category, for an action `type` not in
# ACTION_TYPE_OUTBOUND_EVENTS above (e.g. a novel verb the model proposed).
_DEFAULT_OUTBOUND_EVENT_BY_CATEGORY = {
    "info_request": "email_sent",
    "consequential": "report_to_management",
}


def outbound_event_type(action_type: str, category: str) -> str:
    """The outbound event type that records an action's (stubbed) execution."""
    return ACTION_TYPE_OUTBOUND_EVENTS.get(
        action_type, _DEFAULT_OUTBOUND_EVENT_BY_CATEGORY[category]
    )


@dataclass
class ProvenanceRecord:
    """Records who asserted a set of field changes, when, and why."""

    fields_changed: dict
    source_event_id: str
    asserted_by: str
    asserted_at: str
    confidence: float = 1.0
    source_span: str | None = None


@dataclass
class Entity:
    entity_type: str
    id: str
    fields: dict = field(default_factory=dict)
    history: list[ProvenanceRecord] = field(default_factory=list)


@dataclass
class Action:
    """A proposed action approved as part of a `human_approval` event.

    Unlike entities, actions aren't keyed by id or merged over time -- each
    approved action is recorded once, in order, for a full audit trail of
    what the agent was told to do and why.
    """

    type: str
    category: str
    payload: dict
    source_event_id: str
    asserted_by: str
    asserted_at: str
    source_span: str | None = None
