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

    def open_flags(self) -> list[Action]:
        """Flags that were raised but not yet resolved.

        Timeline-aware: walks actions in order so a raise→resolve→re-raise
        correctly shows the re-raised flag as open.
        """
        open_by_entity: dict[str, Action] = {}
        for a in self.actions:
            eid = a.payload.get("entity_id")
            if not eid:
                continue
            if a.type == "raise_flag":
                open_by_entity[eid] = a
            elif a.type == "resolve_flag" and eid in open_by_entity:
                del open_by_entity[eid]
        return list(open_by_entity.values())
