"""Tests for deterministic identity resolution (aipm.identity)."""

from aipm.identity import (
    Member,
    build_roster,
    resolve,
    resolve_payload_identities,
)


# --- build_roster --------------------------------------------------------------


def test_build_roster_from_email_strings():
    roster = build_roster({"team": ["dana@co.com", "eran@co.com"]})
    assert Member("dana@co.com", None) in roster
    assert Member("eran@co.com", None) in roster


def test_build_roster_from_dicts():
    roster = build_roster({"team": [{"name": "Dana Cohen", "email": "dana.cohen@co.com"}]})
    assert roster == [Member("dana.cohen@co.com", "Dana Cohen")]


def test_build_roster_bare_name_is_legacy_no_email():
    roster = build_roster({"team": ["alice"]})
    assert roster == [Member(None, "alice")]


def test_build_roster_includes_pm_and_tech_lead():
    roster = build_roster({"team": [], "pm": "pm@co.com", "tech_lead": "cto@co.com"})
    emails = {m.email for m in roster}
    assert emails == {"pm@co.com", "cto@co.com"}


def test_build_roster_dedupes_by_email():
    roster = build_roster({"team": ["pm@co.com"], "pm": "pm@co.com"})
    assert roster.count(Member("pm@co.com", None)) == 1
    assert len([m for m in roster if m.email == "pm@co.com"]) == 1


# --- resolve -------------------------------------------------------------------


def test_resolve_exact_email():
    roster = [Member("dana@co.com", "Dana")]
    assert resolve("dana@co.com", roster).status == "resolved"
    assert resolve("dana@co.com", roster).email == "dana@co.com"


def test_resolve_by_full_name():
    roster = [Member("dana.cohen@co.com", "Dana Cohen")]
    r = resolve("Dana Cohen", roster)
    assert r.status == "resolved"
    assert r.email == "dana.cohen@co.com"


def test_resolve_by_local_part():
    roster = [Member("dana@co.com", None)]
    r = resolve("dana", roster)
    assert r.status == "resolved"
    assert r.email == "dana@co.com"


def test_resolve_is_case_insensitive():
    roster = [Member("Dana@Co.com", "Dana")]
    assert resolve("DANA@co.COM", roster).status == "resolved"


def test_resolve_unknown_returns_unknown():
    roster = [Member("dana@co.com", "Dana")]
    assert resolve("bob", roster).status == "unknown"
    assert resolve("", roster).status == "unknown"


def test_resolve_two_same_first_name_is_ambiguous():
    """The core case: two Danas -> a bare 'Dana' must not be guessed."""
    roster = [
        Member("dana.cohen@co.com", "Dana Cohen"),
        Member("dana.levi@co.com", "Dana Levi"),
    ]
    r = resolve("Dana", roster)
    assert r.status == "ambiguous"
    assert set(r.candidates) == {"dana.cohen@co.com", "dana.levi@co.com"}


def test_resolve_full_name_disambiguates_two_same_first_name():
    roster = [
        Member("dana.cohen@co.com", "Dana Cohen"),
        Member("dana.levi@co.com", "Dana Levi"),
    ]
    r = resolve("Dana Levi", roster)
    assert r.status == "resolved"
    assert r.email == "dana.levi@co.com"


def test_resolve_strong_beats_weak():
    """An exact full-name match wins over another member's first-name match."""
    roster = [
        Member("dana@co.com", "Dana"),
        Member("dana.cohen@co.com", "Dana Cohen"),
    ]
    r = resolve("Dana", roster)  # 'Dana' == member A's full name (strong), B token (weak)
    assert r.status == "resolved"
    assert r.email == "dana@co.com"


def test_resolve_ignores_name_only_legacy_members():
    roster = [Member(None, "Dana")]  # legacy, no email
    assert resolve("Dana", roster).status == "unknown"


# --- resolve_payload_identities -----------------------------------------------


def test_resolve_payload_rewrites_owner_to_email():
    roster = [Member("dana@co.com", "Dana")]
    deltas = [{"entity_type": "Task", "entity_id": "t1", "fields": {"owner": "Dana"}}]
    issues = resolve_payload_identities(deltas, roster)
    assert deltas[0]["fields"]["owner"] == "dana@co.com"
    assert issues == []


def test_resolve_payload_reports_ambiguous_and_leaves_value():
    roster = [
        Member("dana.cohen@co.com", "Dana Cohen"),
        Member("dana.levi@co.com", "Dana Levi"),
    ]
    deltas = [{"entity_type": "Task", "entity_id": "t1", "fields": {"owner": "Dana"}}]
    issues = resolve_payload_identities(deltas, roster)
    assert deltas[0]["fields"]["owner"] == "Dana"  # untouched
    assert len(issues) == 1
    assert issues[0].mention == "Dana"
    assert set(issues[0].candidates) == {"dana.cohen@co.com", "dana.levi@co.com"}


def test_resolve_payload_leaves_unknown_untouched_silently():
    roster = [Member("dana@co.com", "Dana")]
    deltas = [{"entity_type": "Task", "entity_id": "t1", "fields": {"owner": "external-bob"}}]
    issues = resolve_payload_identities(deltas, roster)
    assert deltas[0]["fields"]["owner"] == "external-bob"
    assert issues == []


def test_resolve_payload_ignores_non_person_fields():
    roster = [Member("dana@co.com", "Dana")]
    deltas = [{"entity_type": "Task", "entity_id": "t1", "fields": {"title": "Dana", "status": "open"}}]
    resolve_payload_identities(deltas, roster)
    assert deltas[0]["fields"]["title"] == "Dana"  # not a person field
