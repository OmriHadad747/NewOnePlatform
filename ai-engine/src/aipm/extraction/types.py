"""Data types for extraction: what a provider proposes, before approval.

A provider reads a raw event and the current project state and returns an
`ExtractionResult` -- proposed `deltas` and `actions`, each grounded in a
verbatim `source_span` quoted from the raw text. Nothing here touches state:
these are *proposals*. They become an `agent_proposal` event (no projection
effect); only a later `human_approval` applies them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ProposedDelta:
    """A proposed create/update against an entity table."""

    op: str  # "create" | "update" | "delete"
    entity_type: str
    entity_id: str
    fields: dict
    source_span: str  # verbatim quote from the raw text justifying this delta
    confidence: float = 1.0


@dataclass
class ProposedAction:
    """A proposed action (e.g. send an email, open a ticket, escalate)."""

    type: str
    category: str  # "info_request" | "consequential"
    payload: dict
    source_span: str
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    deltas: list[ProposedDelta] = field(default_factory=list)
    actions: list[ProposedAction] = field(default_factory=list)

    def to_payload(self, asserted_by: str) -> dict:
        """Render as an event payload matching the projection's delta/action schema.

        `asserted_by` is the originator recorded in provenance (e.g. the
        provider/agent name). The `source_span` and `confidence` carried on
        each proposal are folded into the provenance block the projection
        expects.
        """
        return {
            "deltas": [
                {
                    "op": d.op,
                    "entity_type": d.entity_type,
                    "entity_id": d.entity_id,
                    "fields": dict(d.fields),
                    "provenance": {
                        "asserted_by": asserted_by,
                        "source_span": d.source_span,
                        "confidence": d.confidence,
                    },
                }
                for d in self.deltas
            ],
            "actions": [
                {
                    "type": a.type,
                    "category": a.category,
                    "payload": dict(a.payload),
                    "provenance": {
                        "asserted_by": asserted_by,
                        "source_span": a.source_span,
                        "confidence": a.confidence,
                    },
                }
                for a in self.actions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionResult:
        """Build a result from a provider's parsed JSON output.

        Tolerant of the shapes a model actually emits: a `delete` delta carries no
        `fields` (there's nothing to set), and a provider may omit `confidence`.
        We fill those defaults rather than require every key, and ignore any
        extra keys the model adds.
        """
        return cls(
            deltas=[
                ProposedDelta(
                    op=d["op"],
                    entity_type=d["entity_type"],
                    entity_id=d["entity_id"],
                    fields=d.get("fields") or {},
                    source_span=d.get("source_span", ""),
                    confidence=d.get("confidence", 1.0),
                )
                for d in data.get("deltas", [])
            ],
            actions=[
                ProposedAction(
                    type=a["type"],
                    category=a["category"],
                    payload=a.get("payload") or {},
                    source_span=a.get("source_span", ""),
                    confidence=a.get("confidence", 1.0),
                )
                for a in data.get("actions", [])
            ],
        )

    def to_dict(self) -> dict:
        return {
            "deltas": [asdict(d) for d in self.deltas],
            "actions": [asdict(a) for a in self.actions],
        }
