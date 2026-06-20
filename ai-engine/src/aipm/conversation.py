"""Model-composed messages: the agent's side of a conversation (info_request).

When a person replies inside a thread but doesn't clearly approve or reject the
pending request, a fixed template often doesn't fit. This module builds the
prompt that lets the model compose ONE short, purposeful reply to keep the
conversation moving -- and the result type the provider returns.

Hard boundary (mirrors the autonomy decision in DESIGN.md): a composed message
is `info_request` only. It can ask, clarify, or acknowledge; it can NEVER take a
consequential action. Consequential actions still require `human_approval`. The
model is therefore not asked to choose an action type at all -- only what to say,
and whether anything is worth saying.

Pure: prompt construction + result type only. The network call lives in a
backend provider, exactly like extraction and approval resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aipm.extraction.prompt import ExtractionPrompt

# Stable, cacheable instruction block. Mirrors the extraction/approval split so a
# provider can cache the prefix.
MESSAGE_INSTRUCTIONS = """\
You are the messaging step of an AI project-manager agent.

You are mid-conversation with a person in a single thread. You are shown what the
agent is waiting on (the pending request), the conversation so far, and the
person's latest message. Decide whether a brief reply would help move things
forward, and if so, write it.

Rules:
- You may ONLY converse: ask a question, clarify, or acknowledge. You can NEVER
  take or promise a consequential action (opening tickets, raising flags,
  escalating). Those need separate human approval -- never imply they're done.
- Keep it SHORT and purposeful: one or two sentences, no pleasantries padding.
- If the person's message already settles things, or nothing useful can be said,
  do not send a message.

Output STRICT JSON, no prose, in exactly this shape:
{
  "send": true | false,
  "text": "<the short message to send, or empty string if send is false>"
}
"""


@dataclass
class ComposedMessage:
    """The model's decision about what (if anything) to say next in a thread."""

    send: bool
    text: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ComposedMessage":
        return cls(send=bool(data.get("send")), text=(data.get("text") or ""))

    def to_dict(self) -> dict:
        return {"send": self.send, "text": self.text}


def build_message_prefix() -> str:
    """The stable, cacheable part of the messaging prompt."""
    return MESSAGE_INSTRUCTIONS


def summarize_thread(messages: list[dict]) -> str:
    """Render a thread's history as a compact transcript.

    Each message is a dict with `sender` and `text`; order is chronological.
    """
    if not messages:
        return "(no messages yet)"
    return "\n".join(f"  {m.get('sender', '?')}: {m.get('text', '')}" for m in messages)


def build_message_prompt(
    pending_summary: str,
    thread: list[dict],
    today: str | None = None,
) -> ExtractionPrompt:
    today = today or date.today().isoformat()
    suffix = "\n".join(
        [
            f"TODAY: {today}\n",
            f"PENDING REQUEST:\n  {pending_summary}\n",
            f"CONVERSATION SO FAR:\n{summarize_thread(thread)}",
        ]
    )
    return ExtractionPrompt(prefix=build_message_prefix(), suffix=suffix)
