"""Provider contract + the catalog/selection seam.

`ExtractionProvider` is the protocol every concrete provider (Gemini, Claude,
...) implements. Concrete providers make network calls, so they live in the
backend, not here -- this module only defines the contract and the *pure*
routing policy: given the known providers and an optional signal, pick a
name. That keeps the "which provider should the agent use?" decision
deterministic and testable, with no network involved. Today the policy is
trivial (cheapest available); a future agent can make it smarter without
touching any network code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aipm.extraction.prompt import ExtractionPrompt
from aipm.extraction.types import ExtractionResult

if TYPE_CHECKING:  # avoid a cycle: aipm.approval imports aipm.extraction.prompt
    from aipm.approval import ApprovalResult


@runtime_checkable
class ExtractionProvider(Protocol):
    name: str

    def extract(self, prompt: ExtractionPrompt) -> ExtractionResult: ...

    def resolve_approvals(self, prompt: ExtractionPrompt) -> "ApprovalResult":
        """Map a human's reply onto pending proposals (approve/reject/defer)."""
        ...


@dataclass(frozen=True)
class ProviderDescriptor:
    """Pure metadata about a provider, used by the selection policy."""

    name: str
    cost_tier: str  # "cheap" | "strong"
    notes: str = ""


# The known providers the agent can route between. Concrete implementations
# are registered in the backend; this catalog is just the decision input.
CATALOG: dict[str, ProviderDescriptor] = {
    "gemini": ProviderDescriptor(
        name="gemini",
        cost_tier="cheap",
        notes="Gemini 2.5 flash -- default, low cost.",
    ),
    "claude": ProviderDescriptor(
        name="claude",
        cost_tier="strong",
        notes="Claude Haiku -- fallback / stronger reasoning.",
    ),
}

_COST_ORDER = {"cheap": 0, "strong": 1}


def select_provider(
    signal: str | None = None,
    catalog: dict[str, ProviderDescriptor] = CATALOG,
) -> str:
    """Pure routing policy: choose a provider name.

    `signal` is a placeholder for future task metadata (text length, conflict
    density, ...). For now the policy is simply "cheapest available"; the
    signal is accepted so callers and the seam are already in place.
    """
    if not catalog:
        raise ValueError("no providers in catalog")
    return min(catalog.values(), key=lambda d: _COST_ORDER.get(d.cost_tier, 99)).name
