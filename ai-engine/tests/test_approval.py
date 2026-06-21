"""Unit tests for the pure approval-resolution core (prompt + result types)."""

from __future__ import annotations

from aipm.approval import (
    ApprovalResult,
    PendingProposal,
    build_approval_prefix,
    build_approval_prompt,
    summarize_pending,
)


def _pending() -> list[PendingProposal]:
    return [
        PendingProposal(id="prop_a", summary="open_ticket (Resolve PayPal support)"),
        PendingProposal(id="prop_b", summary="raise_flag (Black Friday risk)"),
    ]


# --- prompt --------------------------------------------------------------------


def test_prefix_is_stable_across_calls():
    assert build_approval_prefix() == build_approval_prefix()


def test_prompt_lists_pending_and_reply():
    prompt = build_approval_prompt("yes, open the ticket", _pending(), today="2026-06-16")
    assert "prop_a" in prompt.suffix
    assert "prop_b" in prompt.suffix
    assert "yes, open the ticket" in prompt.suffix
    assert "TODAY: 2026-06-16" in prompt.suffix
    assert prompt.prefix == build_approval_prefix()


def test_summarize_empty_pending():
    assert "no pending" in summarize_pending([])


def test_prefix_documents_single_pending_affirmative_rule():
    # a clear unconditional yes on a single pending request should approve it
    prefix = build_approval_prefix().lower()
    assert "exactly one pending request" in prefix
    assert "unconditional" in prefix
    assert "conditional" in prefix  # ... but conditional replies still defer


def test_prompt_defaults_today_to_current_date():
    from datetime import date

    prompt = build_approval_prompt("ok", _pending())
    assert f"TODAY: {date.today().isoformat()}" in prompt.suffix


# --- result types --------------------------------------------------------------


def test_from_dict_parses_decisions():
    result = ApprovalResult.from_dict(
        {
            "resolutions": [
                {"proposal_id": "prop_a", "decision": "approve", "reason_span": "open the ticket"},
                {"proposal_id": "prop_b", "decision": "defer", "reason_span": ""},
            ]
        }
    )
    assert result.approved_ids() == ["prop_a"]
    assert result.rejected_ids() == []


def test_from_dict_defaults_missing_fields():
    result = ApprovalResult.from_dict({"resolutions": [{"proposal_id": "prop_a"}]})
    assert result.resolutions[0].decision == "defer"
    assert result.resolutions[0].reason_span == ""


def test_approved_and_rejected_partition():
    result = ApprovalResult.from_dict(
        {
            "resolutions": [
                {"proposal_id": "prop_a", "decision": "approve"},
                {"proposal_id": "prop_b", "decision": "reject"},
            ]
        }
    )
    assert result.approved_ids() == ["prop_a"]
    assert result.rejected_ids() == ["prop_b"]


def test_roundtrips_through_dict():
    result = ApprovalResult.from_dict(
        {"resolutions": [{"proposal_id": "prop_a", "decision": "approve", "reason_span": "go"}]}
    )
    assert ApprovalResult.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_empty_result():
    assert ApprovalResult.from_dict({}).resolutions == []
