"""Unit tests for the pure extraction core (no network, no LLM)."""

from __future__ import annotations

import pytest

from aipm.extraction.grounding import check_grounding, filter_grounded, is_grounded
from aipm.extraction.prompt import build_prefix, build_prompt, summarize_state
from aipm.extraction.providers import CATALOG, ProviderDescriptor, select_provider
from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta
from aipm.projection import apply_event, project
from aipm.events import Event
from aipm.state import ProjectState


def _result() -> ExtractionResult:
    return ExtractionResult(
        deltas=[
            ProposedDelta(
                op="create",
                entity_type="Risk",
                entity_id="vendor-delay",
                fields={"description": "Vendor API delayed", "severity": "high"},
                source_span="the vendor API access is delayed again",
            )
        ],
        actions=[
            ProposedAction(
                type="send_email",
                category="info_request",
                payload={"to": "bob"},
                source_span="ask Bob for the latest timeline",
            )
        ],
    )


# --- types / to_payload --------------------------------------------------


def test_to_payload_matches_projection_schema():
    payload = _result().to_payload(asserted_by="agent")

    assert payload["deltas"][0]["op"] == "create"
    assert payload["deltas"][0]["provenance"]["asserted_by"] == "agent"
    assert payload["deltas"][0]["provenance"]["source_span"] == "the vendor API access is delayed again"
    assert payload["actions"][0]["category"] == "info_request"
    assert payload["actions"][0]["provenance"]["asserted_by"] == "agent"


def test_to_payload_is_applicable_by_projection():
    """A proposal, once approved, must apply cleanly through the projection."""
    payload = _result().to_payload(asserted_by="agent")
    approval = Event(
        id="evt_appr",
        type="human_approval",
        timestamp="2025-02-03T10:00:00Z",
        source="approval",
        payload=payload,
    )

    state = project([])
    apply_event(state, approval)

    assert state.get("Risk", "vendor-delay").fields["severity"] == "high"
    assert len(state.actions) == 1
    assert state.actions[0].type == "send_email"


def test_result_roundtrips_through_dict():
    result = _result()
    assert ExtractionResult.from_dict(result.to_dict()).to_dict() == result.to_dict()


# --- grounding -----------------------------------------------------------


def test_is_grounded_tolerates_whitespace_differences():
    raw = "We are   blocked\non the   identity library."
    assert is_grounded("blocked on the identity library", raw)
    assert not is_grounded("blocked on the payments library", raw)


def test_check_grounding_flags_ungrounded_spans():
    raw = "the vendor API access is delayed again"
    result = ExtractionResult(
        deltas=[
            ProposedDelta("create", "Risk", "r1", {}, source_span="totally made up"),
        ],
    )

    problems = check_grounding(result, raw)

    assert len(problems) == 1
    assert "made up" in problems[0]


def test_filter_grounded_keeps_only_grounded_items():
    raw = "the vendor API access is delayed again"
    result = ExtractionResult(
        deltas=[
            ProposedDelta("create", "Risk", "r1", {}, source_span="the vendor API access is delayed"),
            ProposedDelta("create", "Risk", "r2", {}, source_span="hallucinated reason"),
        ],
    )

    kept, dropped = filter_grounded(result, raw)

    assert [d.entity_id for d in kept.deltas] == ["r1"]
    assert len(dropped) == 1
    assert "r2" in dropped[0]


# --- prompt --------------------------------------------------------------


def test_prefix_is_stable_across_calls():
    """The cacheable prefix must be byte-identical between calls."""
    assert build_prefix() == build_prefix()


def test_prompt_includes_state_and_raw_text():
    state = project(
        [
            Event(
                id="e1",
                type="human_approval",
                timestamp="t",
                source="s",
                payload={
                    "deltas": [
                        {
                            "op": "create",
                            "entity_type": "Task",
                            "entity_id": "build-auth",
                            "fields": {"title": "Build auth", "status": "open"},
                            "provenance": {"asserted_by": "PM"},
                        }
                    ]
                },
            )
        ]
    )

    prompt = build_prompt("Auth is now blocked.", state)

    assert "build-auth" in prompt.suffix
    assert "Auth is now blocked." in prompt.suffix
    assert prompt.prefix == build_prefix()


def test_summarize_empty_state():
    assert "empty" in summarize_state(ProjectState.empty())


def test_prompt_includes_project_context_when_set():
    state = ProjectState.empty()
    state.meta = {"name": "Apollo", "description": "Launch the lander", "team": ["alice", "bob"]}

    prompt = build_prompt("Auth is blocked.", state)

    assert "PROJECT:" in prompt.suffix
    assert "Apollo" in prompt.suffix
    assert "Launch the lander" in prompt.suffix
    assert "alice, bob" in prompt.suffix
    # the cacheable prefix is unaffected by per-project context
    assert prompt.prefix == build_prefix()


def test_prompt_omits_project_block_when_no_meta():
    prompt = build_prompt("Auth is blocked.", ProjectState.empty())
    assert "PROJECT:" not in prompt.suffix
    assert "RAW EVENT TEXT:" in prompt.suffix


# --- provider selection --------------------------------------------------


def test_select_provider_defaults_to_cheapest():
    assert select_provider() == "gemini"


def test_select_provider_respects_catalog():
    catalog = {"claude": ProviderDescriptor(name="claude", cost_tier="strong")}
    assert select_provider(catalog=catalog) == "claude"


def test_select_provider_empty_catalog_raises():
    with pytest.raises(ValueError, match="no providers"):
        select_provider(catalog={})


def test_catalog_has_gemini_and_claude():
    assert "gemini" in CATALOG and "claude" in CATALOG
