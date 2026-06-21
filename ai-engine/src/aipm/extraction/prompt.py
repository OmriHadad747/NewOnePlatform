"""Prompt construction, split into a cacheable prefix and a variable suffix.

The prefix (instructions + output schema + vocabulary) is identical on every
call, so a provider can mark it as cached and pay for it once. The suffix (the
current-state summary + the raw event text) is what changes per call.

This module is provider-agnostic: it produces plain text. Each provider
decides how to send the prefix (cached) and the suffix (fresh).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aipm.entities import ACTION_CATEGORIES, ACTION_TYPE_OUTBOUND_EVENTS, ENTITY_TYPES
from aipm.schema import fields_vocabulary
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
- Use `delete` ONLY to remove an entity that the raw text shows was modeled
  wrongly and should not exist -- most often a `Dependency` you now know is not
  real (e.g. "X doesn't actually depend on Y"). A `delete` delta needs just
  `op`, `entity_type`, `entity_id`, and a `source_span`; no `fields`. Never
  delete an entity that isn't in the current state.
- New information can contradict the recorded model, not just add to it. If the
  text implies an existing dependency, owner, or fact is wrong, propose the
  correction (an `update`, or a `delete` of the bad relationship) rather than
  ignoring it -- a human still approves it.
- Keep entity ids short, lowercase, hyphenated, and stable across events.
- Model each concrete piece of work as a `Task` with a single `owner`. Reuse the
  same task id across events. Do NOT model work only as `Owner` entities.
- Use ONLY the canonical field names listed for each entity type below; do not
  invent field names. Put any extra detail in a `notes` field.
- A `Dependency` links two task ids: `from_entity_id` is the task that is
  blocked, `to_entity_id` is the task it waits for. Reference TASK ids, not
  owner ids.
- Write dates as `due_date` in ISO YYYY-MM-DD. If a date is missing its year,
  resolve it to the soonest occurrence on/after TODAY (given below).
- Propose an action only when the text implies the agent should DO something.
  Use category `info_request` for routine info-gathering the agent can send on
  its own, with type `send_message` -- and ALWAYS include `to`, `subject`, and
  `body` in its payload. Use category `consequential` for things that need human
  sign-off, with type `open_ticket`, `raise_flag`, or `escalate_to_management`.
  A `raise_flag` or `escalate_to_management` payload MUST include `entity_id`
  (the id of the entity it concerns) and `reason`; an `open_ticket` payload MUST
  include `task_id` and `title`.

Output STRICT JSON, no prose, in exactly this shape:
{
  "deltas": [
    {
      "op": "create" | "update" | "delete",
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
        f"Action types: {action_types}.\n"
        f"Canonical fields per entity type (use these names exactly):\n"
        f"{fields_vocabulary()}"
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


def summarize_meta(meta: dict) -> str:
    """A compact text summary of project-level context (name, goal, team)."""
    lines: list[str] = []
    for key in ("name", "description", "team", "start_date", "end_date", "pm", "tech_lead"):
        value = meta.get(key)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def build_prompt(raw_text: str, state: ProjectState, today: str | None = None) -> ExtractionPrompt:
    today = today or date.today().isoformat()
    parts: list[str] = [f"TODAY: {today}\n"]
    meta_summary = summarize_meta(state.meta)
    if meta_summary:
        parts.append(f"PROJECT:\n{meta_summary}\n")
    parts.append(f"CURRENT PROJECT STATE:\n{summarize_state(state)}\n")
    parts.append(f"RAW EVENT TEXT:\n{raw_text}")
    return ExtractionPrompt(prefix=build_prefix(), suffix="\n".join(parts))
