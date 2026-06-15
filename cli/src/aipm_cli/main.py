"""CLI client for the backend API.

Commands:
  append <event.json>     -- POST an event to the backend
  events                   -- GET the full event log
  state                    -- GET the current projected state
  replay <scenario.yaml>  -- post a scenario's events in order and check
                              its checkpoints against the live backend
                              (simulates a project end-to-end)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import yaml

DEFAULT_BASE_URL = "http://localhost:8000"

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


def cmd_append(client: httpx.Client, event_file: str) -> int:
    event = json.loads(Path(event_file).read_text())
    response = client.post("/events", json=event)
    if response.status_code >= 400:
        print(f"Error: {response.json().get('detail')}", file=sys.stderr)
        return 1
    print(json.dumps(response.json(), indent=2))
    return 0


def cmd_events(client: httpx.Client) -> int:
    response = client.get("/events")
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))
    return 0


def cmd_state(client: httpx.Client) -> int:
    response = client.get("/state")
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))
    return 0


def cmd_replay(client: httpx.Client, scenario_file: str) -> int:
    scenario = yaml.safe_load(Path(scenario_file).read_text())
    checkpoints_by_event = {c["after_event"]: c["assert"] for c in scenario["checkpoints"]}

    failures = 0
    for event in scenario["events"]:
        response = client.post("/events", json=event)
        if response.status_code >= 400:
            print(f"FAIL: {event['id']} rejected by backend: {response.json().get('detail')}")
            failures += 1
            continue

        checks = checkpoints_by_event.get(event["id"])
        if checks is None:
            continue

        state = client.get("/state").json()
        for path, expected in checks.items():
            actual = _resolve(state, path)
            status = "PASS" if actual == expected else "FAIL"
            if status == "FAIL":
                failures += 1
            print(f"{status} @ {event['id']}: {path} = {actual!r} (expected {expected!r})")

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print("\nAll checkpoints passed")
    return 0


def _resolve(state: dict, path: str):
    table_name, entity_id, attr = path.split(".", 2)
    entity_type = TABLES[table_name]
    entity = state.get(entity_type, {}).get(entity_id)
    if entity is None:
        raise AssertionError(f"{entity_type} {entity_id!r} not found in state")
    if attr == "history_length":
        return len(entity["history"])
    return entity["fields"].get(attr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aipm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append", help="POST an event to the backend")
    append_parser.add_argument("event_file")

    subparsers.add_parser("events", help="GET the full event log")
    subparsers.add_parser("state", help="GET the current projected state")

    replay_parser = subparsers.add_parser(
        "replay", help="replay a scenario against the backend and check its checkpoints"
    )
    replay_parser.add_argument("scenario_file")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)
    base_url = os.environ.get("AIPM_BACKEND_URL", DEFAULT_BASE_URL)

    with httpx.Client(base_url=base_url) as client:
        if args.command == "append":
            return cmd_append(client, args.event_file)
        if args.command == "events":
            return cmd_events(client)
        if args.command == "state":
            return cmd_state(client)
        if args.command == "replay":
            return cmd_replay(client, args.scenario_file)

    return 1


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
