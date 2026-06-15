"""Minimal CLI: print the projected state of an event log as JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from aipm.events import load_events
from aipm.projection import project


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m aipm.cli <events.jsonl>", file=sys.stderr)
        return 1

    events = load_events(Path(argv[0]))
    state = project(events)
    output = {
        table_name: {entity_id: entity.fields for entity_id, entity in entities.items()}
        for table_name, entities in state.entities.items()
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
