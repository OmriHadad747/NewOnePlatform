"""Canonical field vocabulary for entities + actions, and the normalization
that enforces it.

Root problem this solves: the extraction prompt used to name entity *types* but
not their *fields*, so the model invented field names (`date`/`target_date` for a
deadline, `owners` for an owner, `dependent`/`blocker` for a dependency). The
deterministic safety nets (review, conflicts) key off canonical names
(`due_date`, `owner`, `from_entity_id`, ...), so they silently failed to engage.

The fix has two halves that back each other up:
  1. `fields_vocabulary()` advertises the canonical schema in the prompt, so the
     model emits the right names in the first place.
  2. `normalize_payload()` deterministically maps known aliases back to canonical
     -- the real guarantee, since the model is free-form. Run it on extracted
     deltas/actions before they become a proposal, and every downstream rule can
     rely on canonical names.

Pure and deterministic: no I/O, no model. Unknown fields are passed through
untouched (we only rename what we recognize), so this never loses information.
"""

from __future__ import annotations

# Per entity type: canonical field -> (aliases the model commonly emits, short
# human description used in the prompt). The canonical key is the name every
# deterministic rule downstream relies on; the aliases are coerced to it.
ENTITY_FIELDS: dict[str, dict[str, tuple[list[str], str]]] = {
    "Task": {
        "title": (["name", "summary"], "short title of the work"),
        "owner": (["assignee", "owners", "responsible", "person"], "single owner id"),
        "status": (["state"], "one of: open, in_progress, blocked, done"),
        "due_date": (["date", "target_date", "deadline", "due"], "ISO YYYY-MM-DD"),
    },
    "Deadline": {
        "title": (["name"], "what is due"),
        "due_date": (["date", "target_date", "deadline_date", "deadline", "due"], "ISO YYYY-MM-DD"),
        "status": (["state"], "one of: tentative, committed, met, missed"),
    },
    "Risk": {
        "description": (["summary", "detail"], "what the risk is"),
        "severity": (["priority", "level"], "one of: low, medium, high, critical"),
        "status": (["state"], "one of: open, mitigated, resolved, accepted"),
        "owner": (["assignee", "responsible"], "single owner id, if any"),
    },
    "Dependency": {
        "from_entity_id": (["dependent", "from", "blocked", "downstream", "blocked_task"],
                           "Task id that is blocked"),
        "to_entity_id": (["blocker", "blocking", "blocking_on", "blocked_by", "to",
                          "upstream", "depends_on"], "Task id it waits for"),
        "status": (["state"], "one of: active, resolved"),
    },
    "Owner": {
        "name": (["person", "who"], "the person"),
        "responsibility": (["role", "area", "scope"], "what they own"),
    },
    "Decision": {
        "description": (["decision", "summary", "resolution"], "what was decided"),
        "status": (["state"], "one of: open, decided"),
    },
    "OpenQuestion": {
        "description": (["question", "summary"], "the open question"),
        "status": (["state"], "one of: open, answered"),
        "owner": (["assignee", "responsible"], "single owner id, if any"),
    },
}

# Action payload aliases: the only common miss we saw was the message recipient.
_ACTION_PAYLOAD_ALIASES = {
    "to": ["recipient", "recipients", "to_address", "addressee"],
}


def _alias_map(schema: dict[str, tuple[list[str], str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canon, (aliases, _desc) in schema.items():
        for alias in aliases:
            out[alias.lower()] = canon
    return out


def normalize_fields(entity_type: str, fields: dict) -> dict:
    """Rename a delta's field keys to their canonical names for `entity_type`.

    Canonical keys always win over aliases when both are present, regardless of
    order. `owner`-style fields given as a list are collapsed to their first
    element. Unrecognized keys are kept verbatim.
    """
    schema = ENTITY_FIELDS.get(entity_type)
    if not schema:
        return dict(fields)
    canon_lower = {c.lower(): c for c in schema}
    alias_to_canon = _alias_map(schema)

    out: dict = {}
    # Pass 1: keys that are already canonical take precedence.
    for k, v in fields.items():
        if k.lower() in canon_lower:
            out[canon_lower[k.lower()]] = v
    # Pass 2: aliases fill any gaps; unknown keys pass through.
    for k, v in fields.items():
        if k.lower() in canon_lower:
            continue
        canon = alias_to_canon.get(k.lower())
        if canon is None:
            out.setdefault(k, v)
            continue
        if canon == "owner" and isinstance(v, list):
            v = v[0] if v else None
        out.setdefault(canon, v)
    return out


def normalize_action_payload(payload: dict) -> dict:
    """Map known action-payload aliases (e.g. `recipient` -> `to`) to canonical."""
    alias_to_canon = {a.lower(): c for c, aliases in _ACTION_PAYLOAD_ALIASES.items() for a in aliases}
    out: dict = {}
    for k, v in payload.items():
        if k in _ACTION_PAYLOAD_ALIASES:  # already canonical
            out[k] = v
    for k, v in payload.items():
        if k in _ACTION_PAYLOAD_ALIASES:
            continue
        out.setdefault(alias_to_canon.get(k.lower(), k), v)
    return out


def normalize_payload(payload: dict) -> dict:
    """Normalize every delta's fields and every action's payload in a proposal
    payload (the dict produced by `ExtractionResult.to_payload`). Returns the
    same payload object, mutated, for convenience."""
    for delta in payload.get("deltas", []):
        delta["fields"] = normalize_fields(delta.get("entity_type", ""), delta.get("fields", {}))
    for action in payload.get("actions", []):
        action["payload"] = normalize_action_payload(action.get("payload", {}))
    return payload


def fields_vocabulary() -> str:
    """Render the canonical field schema for the extraction prompt prefix."""
    lines: list[str] = []
    for etype in sorted(ENTITY_FIELDS):
        parts = ", ".join(f"{canon} ({desc})" for canon, (_a, desc) in ENTITY_FIELDS[etype].items())
        lines.append(f"  {etype}: {parts}")
    return "\n".join(lines)
