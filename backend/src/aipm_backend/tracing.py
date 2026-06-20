"""Optional on-disk trace of every model call (input prompt + output).

`TracingProvider` wraps any `ExtractionProvider` and, for each call, writes one
JSON file capturing the exact prompt the model saw (prefix + suffix) and the
result it returned. It's enabled by pointing `AIPM_TRACE_DIR` at a folder (see
`config.trace_dir`); without that, providers are used unwrapped and nothing is
written.

This is purely an observability aid -- it never changes what the model returns,
never touches the event log, and never records anything but the prompt and the
parsed result (no API keys, no transport details). Files are named
`<ms-timestamp>_<kind>_<rand>.json` so a plain directory listing is in call
order.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aipm.extraction.prompt import ExtractionPrompt
from aipm.extraction.providers import ExtractionProvider


class TracingProvider:
    """Decorates a provider; records each call's prompt + result to a folder."""

    def __init__(self, inner: ExtractionProvider, trace_dir: str | Path) -> None:
        self._inner = inner
        self.name = inner.name
        self._dir = Path(trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _record(self, kind: str, prompt: ExtractionPrompt, output: dict) -> None:
        stamp = f"{time.time_ns() // 1_000_000}_{kind}_{uuid.uuid4().hex[:6]}"
        record = {
            "kind": kind,
            "provider": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": {"prefix": prompt.prefix, "suffix": prompt.suffix},
            "output": output,
        }
        (self._dir / f"{stamp}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False)
        )

    def extract(self, prompt: ExtractionPrompt):
        result = self._inner.extract(prompt)
        self._record("extract", prompt, result.to_dict())
        return result

    def resolve_approvals(self, prompt: ExtractionPrompt):
        result = self._inner.resolve_approvals(prompt)
        self._record("resolve_approvals", prompt, result.to_dict())
        return result

    def compose_message(self, prompt: ExtractionPrompt):
        result = self._inner.compose_message(prompt)
        self._record("compose_message", prompt, result.to_dict())
        return result
