"""CLI tests against a mocked backend.

`test_replay_*` exercises the CLI against a small in-memory fake backend
built on the real `aipm` projection logic, replaying the same scenarios
used by ai-engine's own eval harness -- this is the "simulate a project
end-to-end" path.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aipm.events import Event
from aipm.projection import ProjectionError, apply_event, project

from aipm_cli.main import cmd_append, cmd_events, cmd_replay, cmd_state, _resolve

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "ai-engine" / "scenarios"


class FakeBackend:
    """In-memory stand-in for the backend API, backed by real aipm projection."""

    def __init__(self):
        self.events: list[Event] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/events":
            return self._create_event(json.loads(request.content))
        if request.method == "GET" and request.url.path == "/events":
            return httpx.Response(200, json=[e.__dict__ for e in self.events])
        if request.method == "GET" and request.url.path == "/state":
            return httpx.Response(200, json=self._serialize_state())
        return httpx.Response(404)

    def _create_event(self, payload: dict) -> httpx.Response:
        event = Event(**payload)
        state = project(self.events)
        try:
            apply_event(state, event)
        except ProjectionError as exc:
            return httpx.Response(400, json={"detail": str(exc)})
        self.events.append(event)
        return httpx.Response(201, json={"id": event.id})

    def _serialize_state(self) -> dict:
        state = project(self.events)
        return {
            entity_type: {
                entity_id: {"fields": entity.fields, "history": [{}] * len(entity.history)}
                for entity_id, entity in table.items()
            }
            for entity_type, table in state.entities.items()
        }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_resolve_reads_fields_and_history_length():
    state = {"Decision": {"db-choice": {"fields": {"description": "X"}, "history": [{}, {}]}}}

    assert _resolve(state, "decisions.db-choice.description") == "X"
    assert _resolve(state, "decisions.db-choice.history_length") == 2


def test_cmd_state_prints_response_json(capsys):
    client = _client(lambda r: httpx.Response(200, json={"Task": {}}))

    assert cmd_state(client) == 0
    assert json.loads(capsys.readouterr().out) == {"Task": {}}


def test_cmd_events_prints_response_json(capsys):
    client = _client(lambda r: httpx.Response(200, json=[{"id": "evt_1"}]))

    assert cmd_events(client) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "evt_1"}]


def test_cmd_append_success(tmp_path, capsys):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps({"id": "evt_1"}))
    client = _client(lambda r: httpx.Response(201, json={"id": "evt_1"}))

    assert cmd_append(client, str(event_file)) == 0
    assert json.loads(capsys.readouterr().out) == {"id": "evt_1"}


def test_cmd_append_error(tmp_path, capsys):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps({"id": "evt_1"}))
    client = _client(lambda r: httpx.Response(400, json={"detail": "boom"}))

    assert cmd_append(client, str(event_file)) == 1
    assert "boom" in capsys.readouterr().err


@pytest.mark.parametrize("scenario_path", sorted(SCENARIOS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_replay_scenarios_against_fake_backend(scenario_path, capsys):
    client = _client(FakeBackend().handle)

    assert cmd_replay(client, str(scenario_path)) == 0
    assert "All checkpoints passed" in capsys.readouterr().out
