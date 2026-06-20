# Design: messages, threads, and model-composed replies

Status: in progress. This document records the plan we agreed on so the work is
resumable. It supersedes the "email" framing described in older READMEs.

## Why

Everything in the system used to be "email". We are generalizing to **messages**
so any channel (email, Slack, …) is just an adapter, and so the agent can hold a
short, focused **conversation** with a person instead of sending one-shot
templated emails.

Core invariant is untouched: inbound and outbound messages are projection-inert;
`human_approval` remains the ONLY event that mutates entity/action state.

## Decisions (locked)

1. **Duplicate-ticket bug (#1):** no dedicated patch. The thread model removes
   its root cause — an approval reply arrives *inside its own thread* and is
   resolved as an approval only; it is never re-mined for new consequential
   actions, so the same ticket cannot be re-proposed. One residual edge (a
   brand-new *un-threaded* message restating already-pending consequential
   intent) is explicitly deferred.
2. **Migration:** clean rename, not back-compat aliasing.
   - `email_reply_received` → `message_received` (raw input)
   - `email_sent` + `reminder_sent` → `message_sent` (outbound)
   - action types `send_email` + `send_reminder` → `send_message`
   - CLI `email-in` → `message-in`
   - `AIPM_EMAIL_APPROVAL` → `AIPM_MESSAGE_APPROVAL` (old name still read as a
     fallback so existing environments keep working)
3. **Model-composed message autonomy:** info_request only. A model-composed
   message can continue a conversation but can NEVER trigger a consequential
   action — that still requires `human_approval`.
4. **Conversation limit:** per-thread turn cap (default 3) on model-composed
   messages, with the existing nudge/escalation ladder as the backstop.

## The pieces

### a) Event model (ai-engine)
`channel` and `thread_id` live in `Event.payload` (no dataclass change). World-
effects (`ticket_opened`, `flag_raised`, `report_to_management`) stay distinct —
they are not chat.

### b) Thread primitive
A `thread_id` is minted at the first outreach message and **reused** for nudge /
escalation / model replies on the same conversation. A proposal stores its
`thread_id`, so "has an approval request been sent?" and "how many follow-ups?"
become "scan messages by `thread_id`" instead of brittle source-string matching.

### c) Channel seam (backend)
`Channel.send(thread_id, recipient, text, subject) -> message_id`, mirroring the
`ExtractionProvider` seam. `StubChannel` is the Phase-1 implementation; real
email/Slack adapters slot in later. ai-engine stays pure.

### d) Inbound routing (this is what dissolves bug #1)
- message on an **approval thread** → approval resolution scoped to that one
  proposal; auto-extraction is skipped (it is a reply, not new raw input).
- **un-threaded** inbound (transcript / note / fresh message) → full extraction,
  exactly as before. This is the only place consequential proposals originate.

### e) Model-composed message (info_request only)
Pure prompt in `aipm/conversation.py` → `ComposedMessage`. Provider method
`compose_message` lives in the backend, like `extract`/`resolve_approvals`.
Triggered when a threaded reply is ambiguous ("defer"): the agent composes a
short clarifying message, up to the per-thread turn cap, then falls back to the
escalation ladder.

## Phases

1. Rename + thread plumbing + inbound routing (closes bug #1).
2. Channel seam (stub is impl #1).
3. Model-composed message step.
4. (later) real Slack/email adapter.
