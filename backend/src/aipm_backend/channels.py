"""Outbound channel adapters: how a message_sent is actually delivered.

This is the messaging counterpart to the extraction provider seam. ai-engine
stays pure and never sends anything; delivery is I/O, so it lives here. Every
channel implements the same tiny contract -- `send(...) -> message_id` -- so the
rest of the backend opens a thread and posts to it without caring whether the
underlying transport is email, Slack, or (in Phase 1) a stub that just records
the event.

A future email/Slack adapter is a new class implementing `Channel`, registered
in `get_channel`. Nothing else in the backend changes.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from aipm_backend import config


@runtime_checkable
class Channel(Protocol):
    name: str

    def send(
        self,
        thread_id: str,
        recipient: str | None,
        text: str,
        subject: str | None = None,
    ) -> str:
        """Deliver a message in a thread and return a channel-side message id."""
        ...


class StubChannel:
    """Phase-1 channel: delivery is a no-op; the message_sent event IS the record.

    Returns a synthetic message id so callers can thread replies exactly as a
    real adapter would, without any network or transport.
    """

    name = "stub"

    def send(
        self,
        thread_id: str,
        recipient: str | None,
        text: str,
        subject: str | None = None,
    ) -> str:
        return f"stub_{uuid.uuid4().hex[:12]}"


def get_channel() -> Channel:
    """The configured outbound channel. Phase 1 only knows the stub."""
    name = config.channel()
    if name == "stub":
        return StubChannel()
    raise ValueError(f"unknown channel: {name!r}")
