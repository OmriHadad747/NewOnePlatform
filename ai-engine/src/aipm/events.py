"""Event log: the append-only source of truth.

An event log is a JSONL file -- one JSON object per line. Events are never
edited or removed; the current project state is always derived from this
log by `aipm.projection.project()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# transcript_ingested, email_reply_received, manual_edit: raw input -- a
#   transcript, an email reply, or a note typed directly into the platform
#   by a participant. All three are extraction input; none of them carry
#   deltas and none affect the projection.
# agent_proposal: an LLM-proposed set of deltas/actions, awaiting human
#   review. Logged for provenance; has no effect on the projection.
# human_approval: the only event type whose payload (`deltas`, `actions`)
#   affects the projection -- the single gate where proposed facts/actions
#   become state.
EVENT_TYPES = {
    "transcript_ingested",
    "email_reply_received",
    "manual_edit",
    "agent_proposal",
    "human_approval",
}

# Raw-input event types: text added to the log by a person or integration
# (a transcript, an email reply, a typed note). These are the events the
# extraction step reads from; none of them affect the projection.
RAW_INPUT_TYPES = {"transcript_ingested", "email_reply_received", "manual_edit"}


@dataclass
class Event:
    id: str
    type: str
    timestamp: str
    source: str
    raw_text: str | None = None
    payload: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {self.type!r}")


def load_events(path: Path) -> list[Event]:
    """Read all events from a JSONL event log, in order."""
    if not path.exists():
        return []
    events = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(Event(**json.loads(line)))
    return events


def append_event(path: Path, event: Event) -> None:
    """Append a single event to the log. The log is never rewritten."""
    with path.open("a") as f:
        f.write(json.dumps(event.__dict__) + "\n")
