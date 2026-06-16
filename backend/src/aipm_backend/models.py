"""Pydantic models for the API and JSON serialization helpers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from aipm.state import ProjectState


class EventIn(BaseModel):
    id: str
    type: str
    timestamp: str
    source: str
    raw_text: str | None = None
    payload: dict = Field(default_factory=dict)


class ExtractRequest(BaseModel):
    # The id of a raw-input event already in the log to extract from.
    source_event_id: str


class ProjectIn(BaseModel):
    name: str
    description: str | None = None
    team: list[str] = Field(default_factory=list)


def serialize_state(state: ProjectState) -> dict[str, Any]:
    """Render a ProjectState as JSON: one table per entity type, plus actions."""
    result: dict[str, Any] = {
        entity_type: {
            entity_id: {
                "fields": entity.fields,
                "history": [asdict(record) for record in entity.history],
            }
            for entity_id, entity in table.items()
        }
        for entity_type, table in state.entities.items()
    }
    result["actions"] = [asdict(action) for action in state.actions]
    result["meta"] = dict(state.meta)
    return result
