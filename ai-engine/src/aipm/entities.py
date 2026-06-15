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
