"""Owns the location and access to the event log file.

The backend is the only component that reads/writes the event log
directly -- ai-engine just provides the model and projection.
"""

from __future__ import annotations

import os
from pathlib import Path

from aipm.events import Event, append_event, load_events

DEFAULT_EVENT_LOG = Path("data/events.jsonl")


def event_log_path() -> Path:
    return Path(os.environ.get("AIPM_EVENT_LOG", str(DEFAULT_EVENT_LOG)))


def read_events() -> list[Event]:
    return load_events(event_log_path())


def write_event(event: Event) -> None:
    path = event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    append_event(path, event)
