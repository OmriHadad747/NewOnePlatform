"""Concrete extraction providers (the network layer) + the registry.

The pure contract, prompt, grounding and routing policy live in
`aipm.extraction`. This module holds the implementations that actually call a
model -- which is why they live in the backend (the I/O layer) and not in the
no-network ai-engine library.
"""

from __future__ import annotations

import json

from aipm.extraction import ExtractionResult
from aipm.extraction.prompt import ExtractionPrompt
from aipm.extraction.providers import ExtractionProvider

from aipm_backend import config


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
        return ExtractionResult.from_dict(json.loads(response.text))


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
    raise ValueError(f"unknown extraction provider: {name!r}")


def get_provider() -> ExtractionProvider:
    """FastAPI dependency. Tests override this to inject a StaticProvider."""
    return build_provider()
