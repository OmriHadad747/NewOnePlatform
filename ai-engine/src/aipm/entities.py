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
