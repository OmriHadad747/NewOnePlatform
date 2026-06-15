"""Deterministic projection: event log -> ProjectState.

`project()` folds over the event log in order, applying each event's
deltas to a fresh ProjectState. Running it over the same events always
produces the same state -- this is what makes replay testing possible.
"""

from __future__ import annotations

from aipm.entities import ENTITY_TYPES, Entity, ProvenanceRecord
from aipm.events import Event
from aipm.state import ProjectState

# Event types whose deltas mutate state. The others (transcript_ingested,
# email_reply_received, agent_proposal) are logged for provenance but have
# no effect on the projection in Phase 1.
DELTA_EVENT_TYPES = {"manual_edit", "human_approval"}

DELTA_OPS = {"create", "update"}


class ProjectionError(Exception):
    """Raised when an event log contains a delta that cannot be applied."""


def project(events: list[Event]) -> ProjectState:
    state = ProjectState.empty()
    for event in events:
        apply_event(state, event)
    return state


def apply_event(state: ProjectState, event: Event) -> None:
    if event.type in DELTA_EVENT_TYPES:
        for delta in event.payload.get("deltas", []):
            apply_delta(state, delta, event)


def apply_delta(state: ProjectState, delta: dict, event: Event) -> None:
    entity_type = delta["entity_type"]
    entity_id = delta["entity_id"]
    op = delta["op"]
    fields = delta.get("fields", {})

    if entity_type not in ENTITY_TYPES:
        raise ProjectionError(f"{event.id}: unknown entity_type {entity_type!r}")
    if op not in DELTA_OPS:
        raise ProjectionError(f"{event.id}: unknown op {op!r}")

    table = state.entities[entity_type]
    provenance = _build_provenance(delta, fields, event)

    if op == "create":
        if entity_id in table:
            raise ProjectionError(
                f"{event.id}: cannot create {entity_type} {entity_id!r}, already exists"
            )
        table[entity_id] = Entity(entity_type, entity_id, dict(fields), [provenance])
    else:  # update
        if entity_id not in table:
            raise ProjectionError(
                f"{event.id}: cannot update {entity_type} {entity_id!r}, does not exist"
            )
        entity = table[entity_id]
        entity.fields.update(fields)
        entity.history.append(provenance)


def _build_provenance(delta: dict, fields: dict, event: Event) -> ProvenanceRecord:
    prov = delta.get("provenance", {})
    if "asserted_by" not in prov:
        raise ProjectionError(
            f"{event.id}: delta for {delta.get('entity_id')!r} missing provenance.asserted_by"
        )
    return ProvenanceRecord(
        fields_changed=dict(fields),
        source_event_id=event.id,
        asserted_by=prov["asserted_by"],
        asserted_at=prov.get("asserted_at", event.timestamp),
        confidence=prov.get("confidence", 1.0),
        source_span=prov.get("source_span"),
    )
