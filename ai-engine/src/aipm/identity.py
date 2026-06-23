"""Deterministic identity resolution: map a free-text person mention to a
unique team member's email, against the project roster.

Why this exists: humans refer to people by name ("Dana"), but names are not
unique -- two Danas can share a project. Email is the one stable identity we
have, so every place that keys on a person (a Task `owner`, a fan-out
`approver`, the approval gate) must compare emails, not names. The model is
good at *extracting the mention as written*; turning that mention into a
stable identity is a deterministic lookup, not an inference -- so it lives
here, in pure code, next to `schema.normalize_payload`, never in the model.

Resolution is conservative: it resolves only when the answer is unambiguous.
A bare "Dana" that matches two roster members comes back `ambiguous` (the
caller asks which one) -- it never silently guesses. A mention that matches
nobody comes back `unknown` and is left untouched (it's probably an external
person we don't track), so we don't pester anyone over every stray name.

Pure and deterministic: no I/O, no model. Same roster + mention -> same result.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Member:
    """One person on the roster. `email` is the stable identity key; `name` is
    a display name people use in free text. A member with no email is a legacy
    name-only entry -- it can never be an approval identity, so the resolver
    ignores it (it cannot map a mention to an email it doesn't have)."""

    email: str | None
    name: str | None = None


@dataclass(frozen=True)
class ResolveResult:
    status: str                       # "resolved" | "ambiguous" | "unknown"
    email: str | None = None          # the resolved email when status == "resolved"
    candidates: tuple[str, ...] = ()  # the colliding emails when status == "ambiguous"


def _local_part(email: str) -> str:
    """The bit before '@' -- a common informal handle (dana@co.com -> 'dana')."""
    return email.split("@", 1)[0].lower()


def build_roster(meta: dict) -> list[Member]:
    """Assemble the roster from project meta: `team` plus the pm/tech_lead roles.

    `team` entries may be plain strings (an email if it contains '@', else a
    legacy bare name) or `{"name", "email"}` dicts (the form that lets two
    people share a first name). pm/tech_lead are emails. Deduped by email.
    """
    seen: set[str] = set()
    members: list[Member] = []

    def add(email: str | None, name: str | None) -> None:
        key = (email or "").lower()
        if email and key in seen:
            return
        if email:
            seen.add(key)
        members.append(Member(email=email, name=name))

    for entry in meta.get("team") or []:
        if isinstance(entry, dict):
            add(entry.get("email"), entry.get("name"))
        elif isinstance(entry, str):
            add(entry, None) if "@" in entry else add(None, entry)

    for role in ("pm", "tech_lead"):
        value = meta.get(role)
        if isinstance(value, str) and value:
            add(value, None)

    return members


def resolve(mention: str, roster: list[Member]) -> ResolveResult:
    """Map `mention` (a name, email, or informal handle) to a single member email.

    Matching is two-tier so a precise reference beats a partial one:
      strong -- the mention equals a member's full email or full name;
      weak   -- the mention equals a member's email local-part or a token of
                their name (e.g. the first name "Dana" of "Dana Cohen").
    Strong matches are considered first; only if there are none do weak matches
    count. Either tier resolves when it points at exactly one email, and is
    `ambiguous` when it points at several. No match at all is `unknown`.
    """
    m = (mention or "").strip().lower()
    if not m:
        return ResolveResult("unknown")

    strong: set[str] = set()
    weak: set[str] = set()
    for member in roster:
        if not member.email:
            continue  # name-only legacy entry: not an identity we can resolve to
        email = member.email.lower()
        strong_labels = {email}
        weak_labels = {_local_part(email)}
        if member.name:
            strong_labels.add(member.name.strip().lower())
            weak_labels.update(tok for tok in member.name.lower().split() if tok)
        if m in strong_labels:
            strong.add(email)
        elif m in weak_labels:
            weak.add(email)

    pool = strong or weak
    if not pool:
        return ResolveResult("unknown")
    if len(pool) == 1:
        return ResolveResult("resolved", email=next(iter(pool)))
    return ResolveResult("ambiguous", candidates=tuple(sorted(pool)))


# Entity fields that name a person and so must resolve to an email. After
# `schema.normalize_fields`, assignee/responsible/... have already collapsed to
# the canonical `owner`, so that single key is all we resolve.
_PERSON_FIELDS = ("owner",)


@dataclass
class IdentityIssue:
    entity_type: str
    entity_id: str
    field: str
    mention: str
    candidates: list[str] = field(default_factory=list)


def resolve_payload_identities(deltas: list[dict], roster: list[Member]) -> list[IdentityIssue]:
    """Resolve every person field on `deltas` to an email, in place.

    Resolved mentions are rewritten to the member's email. Ambiguous mentions
    are left as-is and reported as `IdentityIssue`s (so the caller can ask the
    author which person they meant). Unknown mentions are left untouched and
    not reported -- they're usually external people we don't track, and flagging
    every one would be noise.
    """
    issues: list[IdentityIssue] = []
    for delta in deltas:
        fields = delta.get("fields", {})
        for key in _PERSON_FIELDS:
            mention = fields.get(key)
            if not isinstance(mention, str) or not mention.strip():
                continue
            result = resolve(mention, roster)
            if result.status == "resolved":
                fields[key] = result.email
            elif result.status == "ambiguous":
                issues.append(IdentityIssue(
                    entity_type=delta.get("entity_type", ""),
                    entity_id=delta.get("entity_id", ""),
                    field=key,
                    mention=mention,
                    candidates=list(result.candidates),
                ))
    return issues
