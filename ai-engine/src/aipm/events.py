"""Event log: the append-only source of truth.

An event log is a JSONL file -- one JSON object per line. Events are never
edited or removed; the current project state is always derived from this
log by `aipm.projection.project()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

EVENT_TYPES = {
    "transcript_ingested",
    "email_reply_received",
    "manual_edit",
    "agent_proposal",
    "human_approval",
}


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
