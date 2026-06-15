"""Concrete extraction providers (the network layer) + the registry.

The pure contract, prompt, grounding and routing policy live in
`aipm.extraction`. This module holds the implementations that actually call a
model -- which is why they live in the backend (the I/O layer) and not in the
no-network ai-engine library.
"""

from __future__ import annotations

import json
import re

from aipm.extraction import ExtractionResult
from aipm.extraction.prompt import ExtractionPrompt
from aipm.extraction.providers import ExtractionProvider

from aipm_backend import config


def parse_extraction_json(text: str) -> ExtractionResult:
    """Parse a model's JSON reply into an ExtractionResult.

    Tolerates a leading/trailing ```json fence in case a provider wraps its
    output, then defers to ExtractionResult.from_dict.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return ExtractionResult.from_dict(json.loads(text))


class GeminiProvider:
    """Extraction via Google Gemini. The SDK is imported lazily so the rest of
    the backend (and the test suite) work without google-genai installed."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def extract(self, prompt: ExtractionPrompt) -> ExtractionResult:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self._model,
            contents=prompt.suffix,
            config=genai_types.GenerateContentConfig(
                # The stable prefix is sent as a system instruction; Gemini 2.5
                # caches repeated prefixes implicitly, so we pay for it once.
                system_instruction=prompt.prefix,
                response_mime_type="application/json",
            ),
        )
        return parse_extraction_json(response.text)


class ClaudeProvider:
    """Extraction via Anthropic Claude (default: Haiku). The SDK is imported
    lazily so the backend and tests work without `anthropic` installed."""

    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def extract(self, prompt: ExtractionPrompt) -> ExtractionResult:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=8192,
            # The stable prefix goes in `system` with a cache breakpoint, so a
            # repeated prefix is billed once (caching kicks in once the prefix
            # crosses the model's minimum cacheable size).
            system=[
                {
                    "type": "text",
                    "text": prompt.prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt.suffix}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_extraction_json(text)


class StaticProvider:
    """Returns a fixed result -- used by tests and for offline/dry runs."""

    name = "static"

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    def extract(self, prompt: ExtractionPrompt) -> ExtractionResult:
        return self._result


def build_provider(name: str | None = None) -> ExtractionProvider:
    name = name or config.extraction_provider()
    if name == "gemini":
        key = config.gemini_api_key()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; cannot use the gemini provider"
            )
        return GeminiProvider(key, config.gemini_model())
    if name == "claude":
        key = config.claude_api_key()
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; cannot use the claude provider"
            )
        return ClaudeProvider(key, config.claude_model())
    raise ValueError(f"unknown extraction provider: {name!r}")


def get_provider() -> ExtractionProvider:
    """FastAPI dependency. Tests override this to inject a StaticProvider."""
    return build_provider()
