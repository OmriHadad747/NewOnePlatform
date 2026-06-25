"""Executive briefing: answer a free-language question about the project.

An executive asks something in plain language ("what are the blockers?", "are
we on track for the deadline?", "who owns the BigQuery work?") and the agent
answers from the current project state. Unlike extraction/approval, the answer
is prose for a human to read, not structured JSON.

Pure: prompt construction only. The network call lives in a backend provider,
exactly like extraction, approval resolution, and message composition. The
answer is grounded in the projected state the caller passes in -- the model is
told to rely on it and to say so when the state doesn't contain the answer,
rather than inventing facts.
"""

from __future__ import annotations

from datetime import date

from aipm.extraction.prompt import ExtractionPrompt, summarize_meta, summarize_state
from aipm.state import ProjectState

# Stable, cacheable instruction block. Mirrors the extraction/messaging split so
# a provider can cache the prefix and pay for it once.
BRIEFING_INSTRUCTIONS = """\
You are the briefing step of an AI project-manager agent named Shlomi.

A project stakeholder (often an executive) asks you a question in plain language.
You answer it using ONLY the project state you are given: tasks and their status
and owners, risks and their severity, decisions, dependencies between tasks, open
questions, deadlines, and the project's overall framing.

Rules:
- Answer ONLY from the provided state and project context. Do not invent facts,
  names, dates, or numbers that are not present.
- If the state does not contain what's needed to answer, say so plainly and
  point to what IS known, rather than guessing.
- Be concise and direct -- a busy executive is reading. Lead with the answer,
  then the few specifics that support it (blocked tasks, high risks, owners,
  dates). Prefer short paragraphs or tight bullet points.
- Surface the things that matter without being asked when they're clearly
  relevant to the question: blockers, unowned high-severity risks, overdue or
  at-risk deadlines, unresolved decisions.
- Write in plain prose for a human. Do NOT output JSON or code fences. Refer to
  people and tasks by their readable names, not internal ids.
"""


def build_briefing_prefix() -> str:
    """The stable, cacheable part of the briefing prompt."""
    return BRIEFING_INSTRUCTIONS


def build_briefing_prompt(
    question: str, state: ProjectState, today: str | None = None
) -> ExtractionPrompt:
    today = today or date.today().isoformat()
    parts: list[str] = [f"TODAY: {today}\n"]
    meta_summary = summarize_meta(state.meta)
    if meta_summary:
        parts.append(f"PROJECT:\n{meta_summary}\n")
    parts.append(f"CURRENT PROJECT STATE:\n{summarize_state(state)}\n")
    parts.append(f"QUESTION:\n{question.strip()}")
    return ExtractionPrompt(prefix=build_briefing_prefix(), suffix="\n".join(parts))
