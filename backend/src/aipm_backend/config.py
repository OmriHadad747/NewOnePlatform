"""Backend configuration: environment-driven, with optional .env support."""

from __future__ import annotations

import os

# Load a local .env if python-dotenv is installed. Optional so the backend
# (and its tests) run fine without it.
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def extraction_provider() -> str:
    """Which provider to use for extraction. Defaults to the cheapest."""
    from aipm.extraction import select_provider

    return os.environ.get("AIPM_EXTRACTION_PROVIDER") or select_provider()


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def gemini_model() -> str:
    return os.environ.get("AIPM_GEMINI_MODEL", "gemini-2.5-flash")
