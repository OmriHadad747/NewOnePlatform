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


def message_approval() -> bool:
    """Whether an inbound message reply can approve/reject pending proposals.

    On by default so approvals flow through the same channel as everything else
    (any channel: email, Slack, ...) -- a human replies and the agent resolves
    the pending request from that reply, no separate approve command needed.
    Set AIPM_MESSAGE_APPROVAL=0 to require explicit POST /proposals/{id}/approve.
    The legacy AIPM_EMAIL_APPROVAL name is still honored as a fallback.
    """
    raw = os.environ.get("AIPM_MESSAGE_APPROVAL")
    if raw is None:
        raw = os.environ.get("AIPM_EMAIL_APPROVAL", "1")
    return raw.strip().lower() not in {"0", "false", "no", ""}


def channel() -> str:
    """The outbound channel adapter to deliver messages through.

    Phase 1 ships only the `stub` channel (logs the message_sent event without
    really sending). Real adapters (email, slack) register later behind the same
    `Channel` seam; AIPM_CHANNEL selects one.
    """
    return os.environ.get("AIPM_CHANNEL", "stub").strip().lower() or "stub"


def model_messages() -> bool:
    """Whether the agent may compose its own short replies inside a thread.

    On by default. These are info_request only -- a composed message can keep a
    conversation going but never triggers a consequential action. Set
    AIPM_MODEL_MESSAGES=0 to fall straight back to the templated nudge/escalation
    ladder instead.
    """
    return os.environ.get("AIPM_MODEL_MESSAGES", "1").strip().lower() not in {"0", "false", "no", ""}


def max_thread_turns() -> int:
    """Cap on model-composed replies per thread before falling back to escalation.

    Prevents the agent from chatting indefinitely when it can't get a clear
    answer. After this many composed messages on one thread, the conversation
    drops to the nudge/escalation backstop.
    """
    try:
        return max(0, int(os.environ.get("AIPM_MAX_THREAD_TURNS", "3")))
    except ValueError:
        return 3


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def gemini_model() -> str:
    return os.environ.get("AIPM_GEMINI_MODEL", "gemini-2.5-flash")


def claude_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def claude_model() -> str:
    return os.environ.get("AIPM_CLAUDE_MODEL", "claude-haiku-4-5")


def trace_dir() -> str | None:
    """Folder to write a per-call trace of every model interaction, or None.

    When AIPM_TRACE_DIR is set, each extract / resolve_approvals /
    compose_message call writes one JSON file there with the exact prompt the
    model saw and the result it returned -- so you can inspect its decisions and
    see where the prompts need strengthening. Off (None) unless the dir is set;
    it never touches the event log or projection.
    """
    return os.environ.get("AIPM_TRACE_DIR") or None
