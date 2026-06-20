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

from aipm_cli.main import (
    cmd_add_raw,
    cmd_append,
    cmd_approve,
    cmd_events,
    cmd_extract,
    cmd_init,
    cmd_proposals,
    cmd_replay,
    cmd_review,
    cmd_state,
    render_approval,
    render_events,
    render_extract,
    render_proposals,
    render_review,
    render_state,
    _resolve,
)

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
        result = {
            entity_type: {
                entity_id: {"fields": entity.fields, "history": [{}] * len(entity.history)}
                for entity_id, entity in table.items()
            }
            for entity_type, table in state.entities.items()
        }
        result["actions"] = [
            {"type": a.type, "category": a.category, "payload": a.payload, "asserted_by": a.asserted_by}
            for a in state.actions
        ]
        return result


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_resolve_reads_fields_and_history_length():
    state = {"Decision": {"db-choice": {"fields": {"description": "X"}, "history": [{}, {}]}}}

    assert _resolve(state, "decisions.db-choice.description") == "X"
    assert _resolve(state, "decisions.db-choice.history_length") == 2


def test_cmd_state_prints_response_json(capsys):
    client = _client(lambda r: httpx.Response(200, json={"Task": {}}))

    assert cmd_state(client, as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == {"Task": {}}


def test_cmd_events_prints_response_json(capsys):
    client = _client(lambda r: httpx.Response(200, json=[{"id": "evt_1"}]))

    assert cmd_events(client, as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "evt_1"}]


def test_cmd_append_success(tmp_path, capsys):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps({"id": "evt_1"}))
    client = _client(lambda r: httpx.Response(201, json={"id": "evt_1"}))

    assert cmd_append(client, str(event_file), as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == {"id": "evt_1"}


def test_cmd_append_error(tmp_path, capsys):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps({"id": "evt_1"}))
    client = _client(lambda r: httpx.Response(400, json={"detail": "boom"}))

    assert cmd_append(client, str(event_file)) == 1
    assert "boom" in capsys.readouterr().err


def test_cmd_extract_posts_source_event_and_prints(capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"proposal": {"id": "prop_1"}, "dropped": []})

    assert cmd_extract(_client(handler), "raw_1", as_json=True) == 0
    assert seen["path"] == "/extract"
    assert seen["body"] == {"source_event_id": "raw_1"}
    assert json.loads(capsys.readouterr().out)["proposal"]["id"] == "prop_1"


def test_cmd_extract_error(capsys):
    client = _client(lambda r: httpx.Response(404, json={"detail": "not found"}))
    assert cmd_extract(client, "nope") == 1
    assert "not found" in capsys.readouterr().err


def test_cmd_proposals_prints_list(capsys):
    client = _client(lambda r: httpx.Response(200, json=[{"id": "prop_1"}]))
    assert cmd_proposals(client, as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "prop_1"}]


def test_cmd_approve_posts_and_prints(capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(201, json={"id": "appr_1", "payload": {"approves": "prop_1"}})

    assert cmd_approve(_client(handler), "prop_1", as_json=True) == 0
    assert seen["path"] == "/proposals/prop_1/approve"
    assert json.loads(capsys.readouterr().out)["payload"]["approves"] == "prop_1"


# --- project init -------------------------------------------------------------


def test_cmd_init_posts_project(capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "proj_1", "type": "project_initialized"})

    assert cmd_init(_client(handler), "Apollo", "Launch the lander", ["alice", "bob"]) == 0
    assert seen["path"] == "/project"
    assert seen["body"] == {"name": "Apollo", "description": "Launch the lander", "team": ["alice", "bob"]}
    out = capsys.readouterr().out
    assert "Apollo" in out
    assert "alice, bob" in out


def test_cmd_init_error(capsys):
    client = _client(lambda r: httpx.Response(400, json={"detail": "bad project"}))
    assert cmd_init(client, "X", None, []) == 1
    assert "bad project" in capsys.readouterr().err


# --- input commands -----------------------------------------------------------


def test_cmd_add_raw_posts_event_with_generated_id(capsys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": seen["body"]["id"]})

    assert cmd_add_raw(_client(handler), "message_received", "Vendor is late", "vendor@x.com") == 0
    assert seen["path"] == "/events"
    assert seen["body"]["type"] == "message_received"
    assert seen["body"]["raw_text"] == "Vendor is late"
    assert seen["body"]["source"] == "vendor@x.com"
    assert seen["body"]["id"].startswith("raw_")
    out = capsys.readouterr().out
    assert "message_received" in out
    assert "aipm extract" in out  # nudges the next step


def test_cmd_add_raw_reports_backend_error(capsys):
    client = _client(lambda r: httpx.Response(400, json={"detail": "bad event"}))
    assert cmd_add_raw(client, "manual_note", "x", "pm_note") == 1
    assert "bad event" in capsys.readouterr().err


def test_cmd_add_raw_renders_inline_extraction(capsys):
    extraction = {
        "proposal": {
            "id": "prop_1",
            "payload": {
                "provider": "claude", "source_event_id": "raw_x",
                "deltas": [{"op": "create", "entity_type": "Risk", "entity_id": "vendor-delay",
                            "fields": {"severity": "high"}}],
                "actions": [],
            },
        },
        "executed": [], "conflicts": [], "dropped": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(201, json={"id": body["id"], "extraction": extraction})

    assert cmd_add_raw(_client(handler), "message_received", "Vendor is late", "v@x.com") == 0
    out = capsys.readouterr().out
    assert "Added message_received" in out
    assert "prop_1" in out
    assert "vendor-delay" in out


def test_cmd_add_raw_reports_skipped_extraction(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(201, json={
            "id": body["id"],
            "extraction": {"skipped": "no extraction provider configured"},
        })

    assert cmd_add_raw(_client(handler), "manual_note", "x", "pm_note") == 0
    out = capsys.readouterr().out
    assert "auto-extraction did not run" in out
    assert "aipm extract" in out


# --- renderers ----------------------------------------------------------------


def test_render_extract_shows_simulated_outbound_and_conflicts():
    body = {
        "proposal": {
            "id": "prop_1",
            "payload": {
                "provider": "claude",
                "source_event_id": "raw_1",
                "deltas": [
                    {"op": "update", "entity_type": "Deadline", "entity_id": "sprint-end",
                     "fields": {"due_date": "2025-02-10"}},
                ],
                "actions": [
                    {"type": "escalate_to_management", "category": "consequential",
                     "payload": {"to": "director"}},
                ],
            },
        },
        "executed": [
            {"id": "out_1", "type": "message_sent",
             "payload": {"type": "send_message", "category": "info_request",
                         "payload": {"to": "bob", "subject": "Status?"}}},
        ],
        "conflicts": [
            {"type": "deadline_regression", "entity_id": "sprint-end",
             "detail": "due_date moves earlier 2025-03-01 -> 2025-02-10"},
        ],
        "dropped": ["dropped delta create Risk 'fake': ungrounded span 'made up'"],
    }
    out = render_extract(body)
    assert "prop_1" in out
    assert "[SIMULATED] message_sent" in out
    assert "to=bob" in out
    assert "deadline_regression on sprint-end" in out
    assert "ungrounded" in out
    assert "aipm approve prop_1" in out


def test_render_extract_no_proposal():
    body = {"proposal": None, "executed": [], "conflicts": [], "dropped": []}
    out = render_extract(body)
    assert "Proposal: none" in out
    assert "Auto-executed: none" in out


def test_render_events_flags_outbound_as_simulated():
    events = [
        {"id": "raw_1", "type": "message_received", "source": "vendor",
         "raw_text": "The vendor API is delayed.", "payload": {}},
        {"id": "out_1", "type": "message_sent", "source": "agent:claude",
         "payload": {"type": "send_message", "payload": {"to": "bob"}}},
    ]
    out = render_events(events)
    assert "message_received" in out
    assert "[SIMULATED]" in out
    assert "to=bob" in out
    assert '"The vendor API is delayed."' in out


def test_render_state_shows_entities_and_actions():
    state = {
        "Risk": {"vendor-delay": {"fields": {"severity": "high", "status": "open"},
                                  "history": [{}, {}]}},
        "actions": [{"type": "escalate_to_management", "category": "consequential",
                     "payload": {"to": "director"}}],
    }
    out = render_state(state)
    assert "Risk:" in out
    assert "vendor-delay: severity=high, status=open  [2 update(s)]" in out
    assert "escalate_to_management" in out


def test_render_state_empty():
    out = render_state({"actions": []})
    assert "(no entities yet)" in out
    assert "Approved actions: none" in out


def test_render_state_shows_project_meta():
    state = {
        "meta": {"name": "Apollo", "description": "Launch the lander", "team": ["alice", "bob"]},
        "actions": [],
    }
    out = render_state(state)
    assert "Project: Apollo" in out
    assert "Launch the lander" in out
    assert "team: alice, bob" in out


def test_render_proposals_lists_pending():
    proposals = [
        {"id": "prop_1", "payload": {"source_event_id": "raw_1", "provider": "claude",
                                     "deltas": [{"op": "create", "entity_type": "Risk", "entity_id": "r1"}],
                                     "actions": [{"type": "open_ticket", "category": "consequential"}]}},
    ]
    out = render_proposals(proposals)
    assert "prop_1" in out
    assert "create Risk 'r1'" in out
    assert "open_ticket" in out
    assert "aipm approve prop_1" in out


def test_render_approval_shows_simulated_actions():
    approval = {
        "id": "appr_1",
        "payload": {"approves": "prop_1",
                    "deltas": [{"op": "create"}],
                    "actions": [{"type": "open_ticket", "payload": {"system": "jira"}}]},
    }
    out = render_approval(approval)
    assert "Approved prop_1 -> appr_1" in out
    assert "[SIMULATED] open_ticket" in out
    assert "system=jira" in out


def test_cmd_approve_error(capsys):
    client = _client(lambda r: httpx.Response(404, json={"detail": "no proposal"}))
    assert cmd_approve(client, "nope") == 1
    assert "no proposal" in capsys.readouterr().err


# --- review -------------------------------------------------------------------


def test_cmd_review_clean_state(capsys):
    client = _client(lambda r: httpx.Response(200, json={"issues": [], "executed": [], "proposal": None}))
    assert cmd_review(client, as_json=False) == 0
    assert "clean" in capsys.readouterr().out


def test_cmd_review_returns_json(capsys):
    body = {"issues": [], "executed": [], "proposal": None}
    client = _client(lambda r: httpx.Response(200, json=body))
    assert cmd_review(client, as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == body


def test_cmd_review_error(capsys):
    client = _client(lambda r: httpx.Response(500, json={"detail": "oops"}))
    assert cmd_review(client) == 1
    assert "oops" in capsys.readouterr().err


def test_render_review_clean():
    body = {"issues": [], "executed": [], "proposal": None}
    out = render_review(body)
    assert "clean" in out


def test_render_review_with_info_request_auto_executed():
    body = {
        "issues": [
            {"rule": "open_question", "entity_type": "OpenQuestion",
             "entity_id": "api-access", "detail": "Open question has no answer: 'Who owns it?'"},
            {"rule": "blocked_task", "entity_type": "Task",
             "entity_id": "deploy", "detail": "Task 'deploy' is blocked"},
        ],
        "executed": [
            {"id": "out_1", "type": "message_sent",
             "payload": {"payload": {"to": "alice", "subject": "Follow-up?"}}},
            {"id": "out_2", "type": "message_sent",
             "payload": {"payload": {"to": "bob", "subject": "Task blocked"}}},
        ],
        "proposal": None,
    }
    out = render_review(body)
    assert "open_question" in out
    assert "blocked_task" in out
    assert "[SIMULATED] message_sent" in out
    assert "to=alice" in out
    assert "Auto-sent" in out


def test_render_review_with_consequential_proposal():
    body = {
        "issues": [
            {"rule": "unowned_high_risk", "entity_type": "Risk",
             "entity_id": "vendor-delay", "detail": "High-severity risk 'vendor-delay' is open with no owner"},
        ],
        "executed": [],
        "proposal": {
            "id": "prop_abc123",
            "type": "agent_proposal",
            "payload": {
                "actions": [
                    {"type": "raise_flag", "category": "consequential",
                     "payload": {"entity_id": "vendor-delay", "reason": "no owner"}},
                ],
            },
        },
    }
    out = render_review(body)
    assert "unowned_high_risk" in out
    assert "prop_abc123" in out
    assert "[SIMULATED]" not in out
    assert "raise_flag" in out
    assert "aipm approve prop_abc123" in out


@pytest.mark.parametrize("scenario_path", sorted(SCENARIOS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_replay_scenarios_against_fake_backend(scenario_path, capsys):
    client = _client(FakeBackend().handle)

    assert cmd_replay(client, str(scenario_path)) == 0
    assert "All checkpoints passed" in capsys.readouterr().out
