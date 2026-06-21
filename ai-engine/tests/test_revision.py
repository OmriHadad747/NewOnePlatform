"""Tests for the model-revision prompt builder."""

from __future__ import annotations

from aipm.revision import build_revision_prompt
from aipm.state import ProjectState


def _state_with_dependency() -> ProjectState:
    state = ProjectState.empty()
    state.meta.update({"name": "Demo", "pm": "pm@demo.com"})
    state.entities["Dependency"]["dep1"] = type(
        "E", (), {"fields": {"from_entity_id": "sync", "to_entity_id": "legacy", "status": "active"}}
    )()
    return state


def test_revision_prompt_carries_state_claim_and_reply():
    state = _state_with_dependency()
    prompt = build_revision_prompt(
        reply_text="the sync doesn't actually depend on the legacy work",
        original_summary="update Task 'sync'; update Dependency 'dep1'",
        state=state,
        today="2026-06-21",
    )

    # The reply and the original claim are both grounded into the suffix.
    assert "doesn't actually depend" in prompt.suffix
    assert "ORIGINAL CLAIM" in prompt.suffix
    assert "dep1" in prompt.suffix  # current state is summarized in

    # The instruction prefix teaches delete-based structural correction.
    assert "delete" in prompt.prefix
    assert "model" in prompt.prefix.lower()


def test_revision_prompt_prefix_is_stable():
    """The cacheable prefix must not depend on the per-call inputs."""
    a = build_revision_prompt("reply a", "claim a", ProjectState.empty(), today="2026-01-01")
    b = build_revision_prompt("reply b", "claim b", ProjectState.empty(), today="2026-12-31")
    assert a.prefix == b.prefix
