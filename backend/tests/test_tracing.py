"""The model-call tracer writes one input/output file per call, when enabled."""

from __future__ import annotations

import json

from aipm.approval import ApprovalResult
from aipm.conversation import ComposedMessage
from aipm.extraction.prompt import ExtractionPrompt
from aipm.extraction.types import ExtractionResult, ProposedDelta

from aipm_backend.extraction import StaticProvider, build_provider
from aipm_backend.tracing import TracingProvider


def _prompt() -> ExtractionPrompt:
    return ExtractionPrompt(prefix="INSTRUCTIONS", suffix="RAW EVENT TEXT:\nthe vendor is late")


def test_tracer_writes_one_file_per_call(tmp_path):
    inner = StaticProvider(
        ExtractionResult(deltas=[ProposedDelta("create", "Risk", "r1", {}, source_span="late")]),
        ApprovalResult([]),
        ComposedMessage(send=True, text="noted"),
    )
    provider = TracingProvider(inner, tmp_path)

    provider.extract(_prompt())
    provider.resolve_approvals(_prompt())
    provider.compose_message(_prompt())

    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 3
    kinds = {json.loads(f.read_text())["kind"] for f in files}
    assert kinds == {"extract", "resolve_approvals", "compose_message"}


def test_trace_file_captures_input_and_output(tmp_path):
    inner = StaticProvider(
        ExtractionResult(deltas=[ProposedDelta("create", "Risk", "r1", {"severity": "high"},
                                               source_span="the vendor is late")])
    )
    provider = TracingProvider(inner, tmp_path)
    provider.extract(_prompt())

    record = json.loads(next(tmp_path.glob("*.json")).read_text())
    # the prompt the model saw ...
    assert record["input"]["suffix"].startswith("RAW EVENT TEXT:")
    # ... and the structured result it produced
    assert record["output"]["deltas"][0]["entity_id"] == "r1"
    assert record["output"]["deltas"][0]["fields"]["severity"] == "high"


def test_build_provider_wraps_with_tracer_when_dir_set(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AIPM_TRACE_DIR", str(tmp_path))
    provider = build_provider("claude")
    assert isinstance(provider, TracingProvider)
    assert provider.name == "claude"  # transparently forwards the inner name


def test_build_provider_unwrapped_without_trace_dir(monkeypatch):
    monkeypatch.delenv("AIPM_TRACE_DIR", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = build_provider("claude")
    assert not isinstance(provider, TracingProvider)
