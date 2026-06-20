"""End-to-end simulation of a multi-person project, driven through the backend.

There are no API keys in this environment, so the LLM is replaced by a scripted
stand-in (exactly how the test suite injects results). EVERYTHING ELSE is the
real system: the append-only event log, the projection, threads, the channel
seam, approval resolution, the conflict checks, model-composed replies, and the
nudge/escalation ladder all run for real. Participant replies are simulated as
`message-in` calls on the right thread, and output is rendered with the actual
CLI renderers so it reads like a command-line session.

Run:  python simulations/orion_checkout.py
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

# Configure the environment BEFORE importing the app. Fresh event log, auto
# extraction on, model messages on with a small per-thread cap.
_LOG = os.path.join(tempfile.mkdtemp(prefix="orion_"), "events.jsonl")
os.environ.update({
    "AIPM_EVENT_LOG": _LOG,
    "AIPM_AUTO_EXTRACT": "1",
    "AIPM_MESSAGE_APPROVAL": "1",
    "AIPM_MODEL_MESSAGES": "1",
    "AIPM_MAX_THREAD_TURNS": "2",
})
for _k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient  # noqa: E402

from aipm.approval import ApprovalResolution, ApprovalResult  # noqa: E402
from aipm.conversation import ComposedMessage  # noqa: E402
from aipm.extraction.types import ExtractionResult, ProposedAction, ProposedDelta  # noqa: E402

from aipm_backend.extraction import (  # noqa: E402
    StaticProvider,
    get_provider,
    get_provider_optional,
)
from aipm_backend.main import app  # noqa: E402
from aipm_cli.main import (  # noqa: E402
    render_events,
    render_extract,
    render_message_approvals,
    render_open_tickets,
    render_review,
    render_state,
)

# --- harness: swap the scripted provider, drive the backend, render like the CLI ---

_provider = {"p": StaticProvider(ExtractionResult())}
app.dependency_overrides[get_provider] = lambda: _provider["p"]
app.dependency_overrides[get_provider_optional] = lambda: _provider["p"]
client = TestClient(app)


def use(extraction=None, approval=None, composed=None):
    """Set what the (scripted) model will return for the next call."""
    _provider["p"] = StaticProvider(extraction or ExtractionResult(), approval, composed)


def _now():
    return datetime.now(timezone.utc).isoformat()


def banner(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def cli(line):
    print("\n  $ " + line)


def d(op, etype, eid, fields, span):
    return ProposedDelta(op, etype, eid, fields, source_span=span)


def a(atype, category, payload, span):
    return ProposedAction(atype, category, payload, source_span=span)


def post_raw(event_type, text, source, payload=None):
    event = {
        "id": f"raw_{uuid.uuid4().hex[:8]}",
        "type": event_type,
        "timestamp": _now(),
        "source": source,
        "raw_text": text,
        "payload": payload or {},
    }
    return client.post("/events", json=event).json()


def message_in(text, sender, thread=None, channel="email"):
    payload = {"channel": channel}
    if thread:
        payload["thread_id"] = thread
    flags = f" --from {sender} --channel {channel}" + (f" --thread {thread}" if thread else "")
    cli(f'aipm message-in "{text}"{flags}')
    return post_raw("message_received", text, sender, payload)


def proposals():
    return client.get("/proposals").json()


def thread_of(proposal_id):
    return next(p for p in proposals() if p["id"] == proposal_id)["payload"]["thread_id"]


# --- the project --------------------------------------------------------------

banner("ORION CHECKOUT REVAMP -- project setup")
cli('aipm init "Orion Checkout" --team alice bob carol dave '
    '--start 2026-06-01 --end 2026-08-31 --pm pm@orion.com --tech-lead alice@orion.com')
client.post("/project", json={
    "name": "Orion Checkout",
    "description": "Rebuild the checkout + payments flow",
    "team": ["alice", "bob", "carol", "dave"],
    "start_date": "2026-06-01",
    "end_date": "2026-08-31",
    "pm": "pm@orion.com",
    "tech_lead": "alice@orion.com",
})
print("  Initialized. Team of 4, PM + tech lead set.")
print("  Plan: Alice->checkout API, Bob->PayPal, Carol->UI (needs API),")
print("        Dave->E2E tests (needs UI + PayPal).")

# 1) Kickoff transcript -> the agent extracts tasks, dependencies, a risk,
#    auto-pings Bob (info_request), and asks the PM to authorize a flag.
banner("1) Kickoff meeting -> extraction, auto-ping, and an approval request")
TRANSCRIPT = (
    "Kickoff for the Orion checkout revamp. "
    "Alice will build the checkout API. "
    "Bob will integrate PayPal for payments. "
    "Carol will build the checkout UI, which depends on the checkout API. "
    "Dave will own the end-to-end tests, which depend on the checkout UI and the PayPal integration. "
    "There is a high risk that the PayPal vendor access is delayed. "
    "We should flag the vendor risk to the PM. "
    "Someone should ask Bob for the PayPal timeline."
)
use(ExtractionResult(
    deltas=[
        d("create", "Task", "checkout-api", {"title": "Build checkout API", "owner": "alice", "status": "open"},
          "Alice will build the checkout API"),
        d("create", "Task", "paypal-integration", {"title": "Integrate PayPal", "owner": "bob", "status": "open"},
          "Bob will integrate PayPal for payments"),
        d("create", "Task", "checkout-ui", {"title": "Build checkout UI", "owner": "carol", "status": "open"},
          "Carol will build the checkout UI, which depends on the checkout API"),
        d("create", "Task", "e2e-tests", {"title": "End-to-end tests", "owner": "dave", "status": "open"},
          "Dave will own the end-to-end tests, which depend on the checkout UI and the PayPal integration"),
        d("create", "Dependency", "dep-ui-api",
          {"from_entity_id": "checkout-ui", "to_entity_id": "checkout-api", "status": "active"},
          "Carol will build the checkout UI, which depends on the checkout API"),
        d("create", "Dependency", "dep-qa-ui",
          {"from_entity_id": "e2e-tests", "to_entity_id": "checkout-ui", "status": "active"},
          "Dave will own the end-to-end tests, which depend on the checkout UI and the PayPal integration"),
        d("create", "Dependency", "dep-qa-pay",
          {"from_entity_id": "e2e-tests", "to_entity_id": "paypal-integration", "status": "active"},
          "Dave will own the end-to-end tests, which depend on the checkout UI and the PayPal integration"),
        d("create", "Risk", "vendor-paypal", {"severity": "high", "status": "open"},
          "There is a high risk that the PayPal vendor access is delayed"),
    ],
    actions=[
        a("send_message", "info_request", {"to": "bob", "subject": "PayPal timeline?",
          "body": "What's the latest timeline on PayPal vendor access?"},
          "Someone should ask Bob for the PayPal timeline"),
        a("raise_flag", "consequential", {"entity_id": "vendor-paypal", "reason": "PayPal vendor access may be delayed"},
          "We should flag the vendor risk to the PM"),
    ],
))
cli('aipm transcript "<kickoff notes>"')
resp = post_raw("transcript_ingested", TRANSCRIPT, "meeting")
print(render_extract(resp["extraction"]))
kickoff_prop = resp["extraction"]["proposal"]["id"]
kickoff_thread = resp["extraction"]["proposal"]["payload"]["thread_id"]

# 2) PM approves the kickoff on its thread -> all deltas + the flag apply.
banner("2) PM replies on the approval thread -> everything applies")
use(approval=ApprovalResult([ApprovalResolution(kickoff_prop, "approve", "yes, flag it and log the plan")]))
r = message_in("Yes, go ahead -- flag the vendor risk and record the plan.",
               "pm@orion.com", thread=kickoff_thread)
print(render_message_approvals(r["approvals"]))
print("  (extraction skipped on this threaded reply -> no duplicate proposals)")

# 3) A participant sends a fresh status update -> mined into a delta.
banner("3) Bob sends a status update (a fresh message) -> extracted")
BOB = "PayPal integration is now in progress and the vendor access is confirmed."
use(ExtractionResult(deltas=[
    d("update", "Task", "paypal-integration", {"status": "in_progress"},
      "PayPal integration is now in progress"),
    d("update", "Risk", "vendor-paypal", {"status": "mitigated"},
      "the vendor access is confirmed"),
]))
r = message_in(BOB, "bob@orion.com")  # no thread -> a new topic, so it IS extracted
print(render_extract(r["extraction"]))
# auto-approve Bob's own factual update so state moves forward
bob_prop = r["extraction"]["proposal"]["id"]
client.post(f"/proposals/{bob_prop}/approve")
print("  (PM-less factual update approved via dev path for the demo)")

# 4) Dave claims done -> the dependency-aware conflict check fires (advisory).
banner("4) Dave says tests are done -> conflict check sees the open dependencies")
DAVE = "The end-to-end tests are done."
use(ExtractionResult(deltas=[
    d("update", "Task", "e2e-tests", {"status": "done"}, "The end-to-end tests are done"),
]))
r = message_in(DAVE, "dave@orion.com")
print(render_extract(r["extraction"]))

# 5) Two-gate ticket opening across the whole team.
banner("5) Open tickets -> ONE batch to the PM (two-gate flow)")
cli("aipm open-tickets")
r = client.post("/open-tickets").json()
print(render_open_tickets(r))
batch_id = r["proposal"]["id"]
batch_thread = r["proposal"]["payload"]["thread_id"]

banner("5a) PM approves the batch -> fans out a confirmation to each owner")
use(approval=ApprovalResult([ApprovalResolution(batch_id, "approve", "yes, open them all")]))
r = message_in("Approved, open tickets for everyone.", "pm@orion.com", thread=batch_thread)
print(render_message_approvals(r["approvals"]))

# map owner -> their confirmation thread
owner_thread = {}
owner_prop = {}
for p in proposals():
    owner = p["payload"].get("approver")
    if owner:
        owner_thread[owner] = p["payload"]["thread_id"]
        owner_prop[owner] = p["id"]

# 6) Alice confirms cleanly -> her ticket opens.
banner("6) Alice confirms her ticket -> it opens (hers only)")
use(approval=ApprovalResult([ApprovalResolution(owner_prop["alice"], "approve", "yes open mine")]))
r = message_in("Yes, open my ticket.", "alice", thread=owner_thread["alice"])
print(render_message_approvals(r["approvals"]))

# 7) Bob is ambiguous -> the agent composes a short reply (info_request only),
#    then Bob confirms -> ticket opens.
banner("7) Bob is ambiguous -> the agent composes a reply, then Bob confirms")
use(approval=ApprovalResult([ApprovalResolution(owner_prop["bob"], "defer", "")]),
    composed=ComposedMessage(send=True,
                             text="Happy to hold -- should I open it once the API contract is frozen?"))
r = message_in("Depends -- is the checkout API contract frozen yet?", "bob", thread=owner_thread["bob"])
print(render_message_approvals(r["approvals"]))
use(approval=ApprovalResult([ApprovalResolution(owner_prop["bob"], "approve", "ok open it")]))
r = message_in("OK, it's frozen -- open it.", "bob", thread=owner_thread["bob"])
print(render_message_approvals(r["approvals"]))

# 8) Carol ignores the ask twice -> nudge, then escalation to the PM.
banner("8) Carol doesn't address it -> nudge, then escalation to the PM")
use(approval=ApprovalResult([ApprovalResolution(owner_prop["carol"], "defer", "")]),
    composed=ComposedMessage(send=False))  # model has nothing useful to add
r = message_in("Thanks team!", "carol", thread=owner_thread["carol"])
print(render_message_approvals(r["approvals"]))
use(approval=ApprovalResult([ApprovalResolution(owner_prop["carol"], "defer", "")]),
    composed=ComposedMessage(send=False))
r = message_in("Have a good weekend.", "carol", thread=owner_thread["carol"])
print(render_message_approvals(r["approvals"]))

# 9) Deterministic review pass over the whole project state.
banner("9) aipm review -> deterministic scan for follow-ups (no LLM)")
cli("aipm review")
print(render_review(client.post("/review-state").json()))

# 10) Final picture.
banner("10) Final project state")
print(render_state(client.get("/state").json()))

banner("Event log (every step is one append-only event)")
print(render_events(client.get("/events").json()))

print(f"\n[event log: {_LOG}]")
