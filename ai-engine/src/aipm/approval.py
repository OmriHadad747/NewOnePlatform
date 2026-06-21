"""Approval resolution: decide, from a human's reply, which pending proposals
they have approved or rejected.

The agent emails a person to ask permission for a consequential action (open a
ticket, raise a flag, escalate). The person replies in natural language, in the
same channel (email today; Slack/Teams later). This module builds the prompt
that maps that reply onto the set of pending proposals -- crucially
distinguishing a genuine authorization ("yes, go ahead and open it") from
merely answering a question or adding information ("yes, we do need PayPal"),
which is NOT an approval.

Pure: prompt construction + result types only. The network call lives in a
backend provider, exactly like extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from aipm.extraction.prompt import ExtractionPrompt

# Stable, cacheable instruction block. Mirrors the extraction prompt's split
# (cacheable prefix + variable suffix) so a provider can cache the prefix.
APPROVAL_INSTRUCTIONS = """\
You are the approval step of an AI project-manager agent.

The agent has asked a human to authorize one or more pending actions. You are
given that person's reply and the list of pending requests. Decide, for each
pending request, whether the reply authorizes it.

Rules:
- Use "approve" ONLY when the reply clearly authorizes that specific action
  (e.g. "yes, open the ticket", "go ahead", "approved", "do it", "sounds good").
- If there is exactly ONE pending request, a clear and UNCONDITIONAL affirmative
  reply -- "yes", "ok", "go ahead", "do it", "approved", "proceed", "ship it",
  and the like, in any language -- approves it, even if the reply does not
  restate the request's details. But a CONDITIONAL or questioning reply
  ("yes, but ...", "ok if ...", "what about ...?") is NOT approval -- defer it.
- Use "reject" when the reply clearly declines it ("no", "don't", "hold off",
  "not yet").
- Use "amend" when the reply confirms a status change only PARTIALLY -- the
  work is mostly finished but a piece remains, or it cannot be fully completed
  yet ("almost done, just a small fix left", "done except for X", "I finished
  my part but it still depends on Y"). Do NOT "approve" such a reply: approving
  would record an untrue "done". Instead set "amended_status" to the truthful
  status the entity should take now -- "in_progress" when work continues,
  "blocked" when it is waiting on something else.
- Use "defer" when the reply does not address that request. Answering a
  question, confirming a fact, or adding new information is NOT approval --
  use "defer" for it.
- Judge each pending request independently: one reply may approve one request,
  reject another, and not address a third.
- Only reference proposal ids from the PENDING REQUESTS list. Never invent ids.

Output STRICT JSON, no prose, in exactly this shape:
{
  "resolutions": [
    {
      "proposal_id": "<one of the pending ids>",
      "decision": "approve" | "reject" | "amend" | "defer",
      "amended_status": "<truthful status when decision is amend, else empty>",
      "reason_span": "<short verbatim quote from the reply, or empty string>"
    }
  ]
}
If the reply addresses none of the pending requests, return {"resolutions": []}.
"""


@dataclass
class PendingProposal:
    """A proposal awaiting approval, as shown to the resolver."""

    id: str
    summary: str


@dataclass
class ApprovalResolution:
    proposal_id: str
    decision: str  # "approve" | "reject" | "amend" | "defer"
    reason_span: str = ""
    # Set only when decision == "amend": the truthful status the entity should
    # take when the reply confirms a status change is only PARTIALLY true (e.g.
    # "almost done, a piece is left"). Empty otherwise.
    amended_status: str = ""


@dataclass
class ApprovalResult:
    resolutions: list[ApprovalResolution] = field(default_factory=list)

    def approved_ids(self) -> list[str]:
        return [r.proposal_id for r in self.resolutions if r.decision == "approve"]

    def rejected_ids(self) -> list[str]:
        return [r.proposal_id for r in self.resolutions if r.decision == "reject"]

    @classmethod
    def from_dict(cls, data: dict) -> ApprovalResult:
        return cls(
            resolutions=[
                ApprovalResolution(
                    proposal_id=r["proposal_id"],
                    decision=(r.get("decision") or "defer"),
                    reason_span=(r.get("reason_span") or ""),
                    amended_status=(r.get("amended_status") or ""),
                )
                for r in data.get("resolutions", [])
            ]
        )

    def to_dict(self) -> dict:
        return {
            "resolutions": [
                {
                    "proposal_id": r.proposal_id,
                    "decision": r.decision,
                    "reason_span": r.reason_span,
                    "amended_status": r.amended_status,
                }
                for r in self.resolutions
            ]
        }


def build_approval_prefix() -> str:
    """The stable, cacheable part of the approval prompt."""
    return APPROVAL_INSTRUCTIONS


def summarize_pending(pending: list[PendingProposal]) -> str:
    if not pending:
        return "(no pending requests)"
    return "\n".join(f"  - {p.id}: {p.summary}" for p in pending)


def build_approval_prompt(
    reply_text: str,
    pending: list[PendingProposal],
    today: str | None = None,
) -> ExtractionPrompt:
    today = today or date.today().isoformat()
    suffix = "\n".join(
        [
            f"TODAY: {today}\n",
            f"PENDING REQUESTS:\n{summarize_pending(pending)}\n",
            f"HUMAN REPLY:\n{reply_text}",
        ]
    )
    return ExtractionPrompt(prefix=build_approval_prefix(), suffix=suffix)
