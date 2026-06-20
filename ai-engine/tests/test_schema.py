"""Canonical field normalization: alias coercion + prompt vocabulary."""

from __future__ import annotations

from aipm.schema import (
    fields_vocabulary,
    normalize_action_payload,
    normalize_fields,
    normalize_payload,
)


# --- field alias coercion (the bugs we saw live) ------------------------------


def test_deadline_date_aliases_become_due_date():
    assert normalize_fields("Deadline", {"target_date": "2026-09-30"}) == {"due_date": "2026-09-30"}
    assert normalize_fields("Deadline", {"date": "2026-09-30"}) == {"due_date": "2026-09-30"}


def test_task_owner_aliases_and_list_collapse():
    assert normalize_fields("Task", {"assignee": "alice"}) == {"owner": "alice"}
    # a list of owners collapses to the first
    assert normalize_fields("Task", {"owners": ["alice", "bob"]}) == {"owner": "alice"}


def test_dependency_aliases_become_from_to():
    out = normalize_fields("Dependency", {"dependent": "ui", "blocking_on": "api", "state": "active"})
    assert out == {"from_entity_id": "ui", "to_entity_id": "api", "status": "active"}


def test_risk_severity_alias():
    assert normalize_fields("Risk", {"priority": "high"}) == {"severity": "high"}


def test_canonical_wins_over_alias_regardless_of_order():
    # both a canonical key and an alias present -> canonical value is kept
    assert normalize_fields("Task", {"owner": "real", "assignee": "alias"}) == {"owner": "real"}
    assert normalize_fields("Task", {"assignee": "alias", "owner": "real"}) == {"owner": "real"}


def test_unknown_fields_pass_through_untouched():
    out = normalize_fields("Task", {"title": "x", "notes": "freeform", "weird": 1})
    assert out == {"title": "x", "notes": "freeform", "weird": 1}


def test_unknown_entity_type_is_left_alone():
    assert normalize_fields("Mystery", {"date": "2026-01-01"}) == {"date": "2026-01-01"}


# --- action payloads -----------------------------------------------------------


def test_action_recipient_alias_becomes_to():
    assert normalize_action_payload({"recipient": "pm@x.com", "subject": "hi"}) == {
        "to": "pm@x.com", "subject": "hi"
    }


# --- whole-payload normalization ----------------------------------------------


def test_normalize_payload_coerces_deltas_and_actions():
    payload = {
        "deltas": [
            {"op": "create", "entity_type": "Deadline", "entity_id": "ga",
             "fields": {"target_date": "2026-12-15"}},
        ],
        "actions": [
            {"type": "send_message", "category": "info_request",
             "payload": {"recipient": "bob", "subject": "?", "body": "hi"}},
        ],
    }
    normalize_payload(payload)
    assert payload["deltas"][0]["fields"] == {"due_date": "2026-12-15"}
    assert payload["actions"][0]["payload"]["to"] == "bob"


# --- prompt vocabulary --------------------------------------------------------


def test_fields_vocabulary_lists_canonical_names():
    vocab = fields_vocabulary()
    assert "Deadline:" in vocab and "due_date (ISO YYYY-MM-DD)" in vocab
    assert "from_entity_id" in vocab and "to_entity_id" in vocab
    assert "Task:" in vocab and "owner (single owner id)" in vocab
