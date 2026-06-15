"""Span-grounding: the deterministic safety net over LLM output.

Every proposed delta/action must cite a `source_span` -- a verbatim quote
from the raw event text. Here we verify (in plain Python, no model involved)
that each cited span actually appears in the raw text. Anything ungrounded is
a hallucination risk and is reported, and can be filtered out before a
proposal is ever shown for approval.
"""

from __future__ import annotations

import re

from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta


def _normalize(text: str) -> str:
    """Collapse runs of whitespace and l-strip/-rstrip, for tolerant matching."""
    return re.sub(r"\s+", " ", text).strip()


def is_grounded(span: str, raw_text: str) -> bool:
    span_n = _normalize(span)
    return bool(span_n) and span_n in _normalize(raw_text)


def check_grounding(result: ExtractionResult, raw_text: str) -> list[str]:
    """Return a list of human-readable problems for any ungrounded span."""
    problems: list[str] = []
    for d in result.deltas:
        if not is_grounded(d.source_span, raw_text):
            problems.append(
                f"delta {d.op} {d.entity_type} {d.entity_id!r}: "
                f"source_span not found in raw text: {d.source_span!r}"
            )
    for a in result.actions:
        if not is_grounded(a.source_span, raw_text):
            problems.append(
                f"action {a.type!r}: source_span not found in raw text: {a.source_span!r}"
            )
    return problems


def filter_grounded(result: ExtractionResult, raw_text: str) -> tuple[ExtractionResult, list[str]]:
    """Split a result into its grounded part and the list of dropped problems."""
    kept_deltas: list[ProposedDelta] = []
    kept_actions: list[ProposedAction] = []
    dropped: list[str] = []

    for d in result.deltas:
        if is_grounded(d.source_span, raw_text):
            kept_deltas.append(d)
        else:
            dropped.append(
                f"dropped delta {d.op} {d.entity_type} {d.entity_id!r}: "
                f"ungrounded span {d.source_span!r}"
            )
    for a in result.actions:
        if is_grounded(a.source_span, raw_text):
            kept_actions.append(a)
        else:
            dropped.append(f"dropped action {a.type!r}: ungrounded span {a.source_span!r}")

    return ExtractionResult(deltas=kept_deltas, actions=kept_actions), dropped
