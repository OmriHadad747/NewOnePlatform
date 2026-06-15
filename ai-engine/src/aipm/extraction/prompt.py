"""Prompt construction, split into a cacheable prefix and a variable suffix.

The prefix (instructions + output schema + vocabulary) is identical on every
call, so a provider can mark it as cached and pay for it once. The suffix (the
current-state summary + the raw event text) is what changes per call.

This module is provider-agnostic: it produces plain text. Each provider
decides how to send the prefix (cached) and the suffix (fresh).
"""

from __future__ import annotations

from dataclasses import dataclass

from aipm.entities import ACTION_CATEGORIES, ACTION_TYPE_OUTBOUND_EVENTS, ENTITY_TYPES
from aipm.state import ProjectState

# The stable, cacheable instruction block. Keep this deterministic -- any
# change invalidates provider-side caches, so edit deliberately.
INSTRUCTIONS = """\
You are the extraction step of an AI project-manager agent.

You read one raw project event (a meeting transcript, an email reply, or a
note typed by a participant) together with the current project state, and you
propose structured changes for a human to approve. You never decide final
state yourself -- you only propose.

Rules:
- Propose only what the raw text supports. Do not invent facts.
- Every proposal MUST include a `source_span`: a short, VERBATIM quote copied
  exactly from the raw event text that justifies it. Do not paraphrase.
- Use `create` for a new entity, `update` to change an existing one (look at
  the current state to tell which, and to reuse existing entity ids).
- Keep entity ids short, lowercase, hyphenated, and stable across events.
- Propose an action only when the text implies the agent should DO something.
  Use category `info_request` for routine info-gathering the agent can send on
  its own, with type `send_email` or `send_reminder` (e.g. emailing a teammate
  for an update or a transcript). Use category `consequential` for things that
  need human sign-off, with type `open_ticket`, `raise_flag`, or
  `escalate_to_management`.

Output STRICT JSON, no prose, in exactly this shape:
{
  "deltas": [
    {
      "op": "create" | "update",
      "entity_type": <one of the entity types below>,
      "entity_id": "<short-stable-id>",
      "fields": { ... },
      "source_span": "<verbatim quote from the raw text>",
      "confidence": <0.0-1.0>
    }
  ],
  "actions": [
    {
      "type": <one of the action types below>,
      "category": "info_request" | "consequential",
      "payload": { ... },
      "source_span": "<verbatim quote from the raw text>",
      "confidence": <0.0-1.0>
    }
  ]
}
If nothing should change, return {"deltas": [], "actions": []}.
"""


@dataclass
class ExtractionPrompt:
    prefix: str  # stable, cacheable: instructions + vocabulary
    suffix: str  # variable: current state + the raw event

    def full(self) -> str:
        return f"{self.prefix}\n\n{self.suffix}"


def _vocabulary() -> str:
    entity_types = ", ".join(sorted(ENTITY_TYPES))
    categories = ", ".join(sorted(ACTION_CATEGORIES))
    action_types = ", ".join(sorted(ACTION_TYPE_OUTBOUND_EVENTS))
    return (
        f"Entity types: {entity_types}.\n"
        f"Action categories: {categories}.\n"
        f"Action types: {action_types}."
    )


def build_prefix() -> str:
    """The stable, cacheable part of the prompt."""
    return f"{INSTRUCTIONS}\n{_vocabulary()}"


def summarize_state(state: ProjectState) -> str:
    """A compact text summary of current state, to ground the model in context."""
    lines: list[str] = []
    for entity_type in sorted(state.entities):
        table = state.entities[entity_type]
        if not table:
            continue
        lines.append(f"{entity_type}:")
        for entity_id, entity in table.items():
            lines.append(f"  - {entity_id}: {entity.fields}")
    return "\n".join(lines) if lines else "(empty -- no entities yet)"


def build_prompt(raw_text: str, state: ProjectState) -> ExtractionPrompt:
    suffix = (
        "CURRENT PROJECT STATE:\n"
        f"{summarize_state(state)}\n\n"
        "RAW EVENT TEXT:\n"
        f"{raw_text}"
    )
    return ExtractionPrompt(prefix=build_prefix(), suffix=suffix)
