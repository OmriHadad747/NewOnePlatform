"""Unit tests for the pure model-composed message core (prompt + result type)."""

from __future__ import annotations

from aipm.conversation import (
    ComposedMessage,
    build_message_prefix,
    build_message_prompt,
    summarize_thread,
)


# --- prompt --------------------------------------------------------------------


def test_prefix_is_stable_across_calls():
    assert build_message_prefix() == build_message_prefix()


def test_prompt_includes_pending_thread_and_today():
    thread = [
        {"sender": "agent", "text": "OK to open a ticket for the login bug?"},
        {"sender": "pm@x.com", "text": "depends on whether legal signed off"},
    ]
    prompt = build_message_prompt(
        "open_ticket (login bug)", thread, today="2026-06-19"
    )
    assert "open_ticket (login bug)" in prompt.suffix
    assert "depends on whether legal signed off" in prompt.suffix
    assert "TODAY: 2026-06-19" in prompt.suffix
    assert prompt.prefix == build_message_prefix()


def test_summarize_empty_thread():
    assert "no messages" in summarize_thread([])


def test_prompt_defaults_today_to_current_date():
    from datetime import date

    prompt = build_message_prompt("x", [])
    assert f"TODAY: {date.today().isoformat()}" in prompt.suffix


# --- result type ---------------------------------------------------------------


def test_from_dict_parses_send_and_text():
    msg = ComposedMessage.from_dict({"send": True, "text": "Got it -- I'll hold."})
    assert msg.send is True
    assert msg.text == "Got it -- I'll hold."


def test_from_dict_defaults_missing_fields():
    msg = ComposedMessage.from_dict({})
    assert msg.send is False
    assert msg.text == ""


def test_roundtrips_through_dict():
    msg = ComposedMessage(send=True, text="hi")
    assert ComposedMessage.from_dict(msg.to_dict()).to_dict() == msg.to_dict()
