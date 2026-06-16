"""ProjectState: the deterministic projection of an event log.

State is organized as one table per entity type, keyed by entity id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aipm.entities import ENTITY_TYPES, Action, Entity


@dataclass
class ProjectState:
    entities: dict[str, dict[str, Entity]] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    # Project-level context (name, description, team), set by a
    # `project_initialized` event. Fed into the extraction prompt so the
    # model has framing; never affects entity/action projection.
    meta: dict = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ProjectState:
        return cls(entities={entity_type: {} for entity_type in ENTITY_TYPES}, meta={})

    def get(self, entity_type: str, entity_id: str) -> Entity | None:
        return self.entities.get(entity_type, {}).get(entity_id)
