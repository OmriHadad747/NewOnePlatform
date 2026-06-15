"""Extraction core (pure): types, prompt, grounding, and the routing policy.

Concrete network-calling providers (Gemini, Claude) live in the backend; this
package stays free of I/O and network so it remains deterministic and
testable.
"""

from aipm.extraction.grounding import check_grounding, filter_grounded, is_grounded
from aipm.extraction.prompt import ExtractionPrompt, build_prompt, summarize_state
from aipm.extraction.providers import (
    CATALOG,
    ExtractionProvider,
    ProviderDescriptor,
    select_provider,
)
from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta

__all__ = [
    "ExtractionResult",
    "ProposedDelta",
    "ProposedAction",
    "ExtractionPrompt",
    "build_prompt",
    "summarize_state",
    "is_grounded",
    "check_grounding",
    "filter_grounded",
    "ExtractionProvider",
    "ProviderDescriptor",
    "CATALOG",
    "select_provider",
]
