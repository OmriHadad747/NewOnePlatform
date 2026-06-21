"""Model-revision prompt: draft a structural correction to the project model.

When a human's reply reveals that the recorded model itself is wrong -- a
dependency that should not exist, a fact wired up incorrectly -- a status change
cannot fix it. The approval step flags that case as `revise`; this module builds
the prompt that turns the contradiction into concrete corrective deltas
(`create`/`update`/`delete`) for a human (the project manager) to approve.

It deliberately reuses the extraction output schema, so a provider's existing
`extract()` parses the result with no new network method. Pure: prompt
construction only, exactly like extraction and approval.
"""

from __future__ import annotations

from datetime import date

from aipm.extraction.prompt import (
    ExtractionPrompt,
    _vocabulary,
    summarize_meta,
    summarize_state,
)
from aipm.state import ProjectState

# Stable, cacheable instruction block, mirroring the extraction prompt's split.
REVISION_INSTRUCTIONS = """\
You are the self-correction step of an AI project-manager agent.

Earlier the agent recorded part of the project model. A person has now replied
in a way that reveals the MODEL ITSELF is wrong -- a dependency that should not
exist, an entity wired up incorrectly, a fact captured the wrong way. Your job
is to propose the structural correction for a human (the project manager) to
approve. You never change state yourself -- you only propose.

You are given the current project state, a short summary of the original claim
that triggered this, and the person's reply. Propose the minimal set of deltas
that make the model match what the reply says is true.

Rules:
- Propose only what the reply supports. Do not invent facts. Every delta MUST
  carry a `source_span`: a short, VERBATIM quote from the reply justifying it.
- Use `delete` to remove a relationship or entity that the reply shows was
  modeled wrongly -- most often a `Dependency` that is not real. Reference the
  exact entity_id from the current state. A `delete` needs only `op`,
  `entity_type`, `entity_id`, `source_span`.
- Use `update` to fix a wrong field, `create` to add a relationship the reply
  establishes.
- Reuse the exact entity ids shown in the current state. Use ONLY the canonical
  field names listed per entity type below.
- Propose no `actions`; a model revision only corrects state. Return an empty
  actions list.
- If, on reflection, the reply does NOT actually contradict the model, return
  no deltas.

Output STRICT JSON, no prose, in exactly this shape:
{
  "deltas": [
    {
      "op": "create" | "update" | "delete",
      "entity_type": <one of the entity types below>,
      "entity_id": "<existing id from current state>",
      "fields": { ... },
      "source_span": "<verbatim quote from the reply>",
      "confidence": <0.0-1.0>
    }
  ],
  "actions": []
}
If nothing should change, return {"deltas": [], "actions": []}.
"""


def build_revision_prefix() -> str:
    """The stable, cacheable part of the revision prompt."""
    return f"{REVISION_INSTRUCTIONS}\n{_vocabulary()}"


def build_revision_prompt(
    reply_text: str,
    original_summary: str,
    state: ProjectState,
    today: str | None = None,
) -> ExtractionPrompt:
    today = today or date.today().isoformat()
    parts: list[str] = [f"TODAY: {today}\n"]
    meta_summary = summarize_meta(state.meta)
    if meta_summary:
        parts.append(f"PROJECT:\n{meta_summary}\n")
    parts.append(f"CURRENT PROJECT STATE:\n{summarize_state(state)}\n")
    parts.append(f"ORIGINAL CLAIM (what the agent was about to record):\n{original_summary}\n")
    parts.append(f"THE PERSON'S REPLY:\n{reply_text}")
    return ExtractionPrompt(prefix=build_revision_prefix(), suffix="\n".join(parts))
