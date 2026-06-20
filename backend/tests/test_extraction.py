"""Unit tests for the provider layer (no network).

The actual model calls are exercised live by the user; here we cover the
parts with logic: JSON parsing of a model reply and provider selection.
"""

from __future__ import annotations

import pytest

from aipm_backend.extraction import (
    ClaudeProvider,
    GeminiProvider,
    build_provider,
    parse_extraction_json,
)


def test_parse_plain_json():
    result = parse_extraction_json(
        '{"deltas": [{"op": "create", "entity_type": "Risk", "entity_id": "r1",'
        ' "fields": {"severity": "high"}, "source_span": "vendor delayed"}],'
        ' "actions": []}'
    )
    assert result.deltas[0].entity_id == "r1"
    assert result.deltas[0].fields == {"severity": "high"}
    assert result.actions == []


def test_parse_json_wrapped_in_code_fence():
    result = parse_extraction_json('```json\n{"deltas": [], "actions": []}\n```')
    assert result.deltas == []
    assert result.actions == []


def test_parse_json_tolerates_trailing_prose():
    # the model returns a valid object then keeps talking -> must not crash
    text = (
        '{"deltas": [{"op": "create", "entity_type": "Risk", "entity_id": "r1",'
        ' "fields": {}, "source_span": "vendor late"}], "actions": []}\n\n'
        "I hope this captures the risk you mentioned!"
    )
    result = parse_extraction_json(text)
    assert result.deltas[0].entity_id == "r1"


def test_parse_json_tolerates_leading_prose_and_fence():
    text = 'Sure, here is the JSON:\n```json\n{"deltas": [], "actions": []}\n```\nLet me know!'
    result = parse_extraction_json(text)
    assert result.deltas == [] and result.actions == []


def test_parse_json_handles_braces_inside_strings():
    text = '{"deltas": [], "actions": [], "note": "use {curly} carefully"} trailing'
    # should parse the whole first object, not stop at the inner brace
    result = parse_extraction_json(text)
    assert result.deltas == []


def test_build_provider_claude_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AIPM_EXTRACTION_PROVIDER", "claude")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_provider()


def test_build_provider_claude_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = build_provider("claude")
    assert isinstance(provider, ClaudeProvider)
    assert provider.name == "claude"


def test_build_provider_gemini_with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    provider = build_provider("gemini")
    assert isinstance(provider, GeminiProvider)


def test_build_provider_unknown_name():
    with pytest.raises(ValueError, match="unknown extraction provider"):
        build_provider("llama")


def test_extraction_provider_env_overrides_default(monkeypatch):
    monkeypatch.setenv("AIPM_EXTRACTION_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert build_provider().name == "claude"
