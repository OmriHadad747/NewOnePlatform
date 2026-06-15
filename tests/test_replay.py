"""Eval harness: replay each scenario and check state at every checkpoint.

This is the validation harness for Phase 1. Each scenario is a fixed
sequence of events plus checkpoints describing what the projected state
must look like after a given event. Later phases will swap the
hand-written deltas in these events for AI-generated ones and re-run the
same scenarios.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aipm.events import Event
from aipm.projection import project

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"

# Maps the table names used in scenario assertions to entity types.
TABLES = {
    "decisions": "Decision",
    "tasks": "Task",
    "owners": "Owner",
    "deadlines": "Deadline",
    "risks": "Risk",
    "dependencies": "Dependency",
    "open_questions": "OpenQuestion",
}


def _resolve(state, path: str):
    """Resolve a dotted assertion path like 'decisions.db-choice.description'."""
    table_name, entity_id, attr = path.split(".", 2)
    entity_type = TABLES[table_name]
    entity = state.get(entity_type, entity_id)
    if entity is None:
        raise AssertionError(f"{entity_type} {entity_id!r} not found in state")
    if attr == "history_length":
        return len(entity.history)
    return entity.fields.get(attr)


def _load_scenario(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize(
    "scenario_path", sorted(SCENARIOS_DIR.glob("*.yaml")), ids=lambda p: p.stem
)
def test_scenario_checkpoints(scenario_path: Path):
    scenario = _load_scenario(scenario_path)
    events = [Event(**e) for e in scenario["events"]]
    index_by_id = {event.id: i for i, event in enumerate(events)}

    for checkpoint in scenario["checkpoints"]:
        idx = index_by_id[checkpoint["after_event"]]
        state = project(events[: idx + 1])
        for path, expected in checkpoint["assert"].items():
            actual = _resolve(state, path)
            assert actual == expected, (
                f"{scenario_path.stem} @ {checkpoint['after_event']}: "
                f"{path} = {actual!r}, expected {expected!r}"
            )
