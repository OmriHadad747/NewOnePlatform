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


def auto_extract() -> bool:
    """Whether the backend extracts automatically when a raw event is ingested.

    On by default so the system runs itself: posting a transcript/email/note
    triggers extraction in the same request. Set AIPM_AUTO_EXTRACT=0 to turn
    it off and drive extraction manually via POST /extract.
    """
    return os.environ.get("AIPM_AUTO_EXTRACT", "1").strip().lower() not in {"0", "false", "no", ""}


def email_approval() -> bool:
    """Whether an inbound email reply can approve/reject pending proposals.

    On by default so approvals flow through the same channel as everything else
    (email today; Slack/Teams later) -- a human replies and the agent resolves
    the pending request from that reply, no separate approve command needed.
    Set AIPM_EMAIL_APPROVAL=0 to require explicit POST /proposals/{id}/approve.
    """
    return os.environ.get("AIPM_EMAIL_APPROVAL", "1").strip().lower() not in {"0", "false", "no", ""}


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def gemini_model() -> str:
    return os.environ.get("AIPM_GEMINI_MODEL", "gemini-2.5-flash")


def claude_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def claude_model() -> str:
    return os.environ.get("AIPM_CLAUDE_MODEL", "claude-haiku-4-5")
