# CLI

A thin client for `backend`'s API. This is the Phase 1 "surface" -- used to
feed events into a running backend and inspect/replay project state, and to
drive the whole extract -> approve -> act loop end-to-end from a terminal. No
direct dependency on `ai-engine` at runtime (only `backend` talks to it);
`ai-engine` is used in tests to build a realistic fake backend.

## Commands

```
# setup -- define the project (frames extraction)
aipm init <name> [--description ...] [--team alice bob]

# input -- mint a raw-input event from text. With auto-extraction on (the
# backend default), each of these extracts, proposes, and auto-sends any
# info_request messages in the same step, printing the result inline.
aipm note <text>              # a manual_note (--source)
aipm message-in <text>        # a message_received (--from <sender>, --channel, --thread)
aipm transcript <text>        # a transcript_ingested (--source)
aipm append <event.json>      # POST a hand-written event JSON

# inspect / drive the loop
aipm events                    # the full event log
aipm state                     # the current projected state (incl. project meta)
aipm extract <event_id>        # manually run extraction on a raw event
aipm proposals                 # proposals awaiting approval (approve by replying)
aipm review                    # scan state for follow-ups (open Qs, blockers...)
aipm replay <scenario.yaml>   # replay a scenario and check its checkpoints
```

By default each command prints a human-readable view. Add `--json` before the
command (e.g. `aipm --json state`) to get the raw API JSON instead.

## Simulating the full loop

Execution of outbound actions is a **stub** in Phase 1: the agent never really
sends an email or opens a ticket -- it logs an outbound event recording what it
*would* do. The CLI flags these `[SIMULATED]` so the simulation is obvious.

A typical end-to-end run (auto-extraction on, a provider configured):

```
# 0. define the project once
aipm init "Apollo" --description "Ship the lander" --team alice bob

# 1. a message reply lands from a vendor -- the agent extracts, proposes, and
#    auto-sends any info_request messages right here, printing the result inline.
aipm message-in "The vendor API access is delayed two weeks." --from vendor@acme.com
#   -> Added message_received [raw_05c61cb2]
#   -> Extraction result ... Proposal prop_... / [SIMULATED] message_sent ...

# 2. review and approve -- the one place text becomes state. Approve by REPLYING
#    on the proposal's thread (there is no approve command); any consequential
#    action (open_ticket / raise_flag / escalate_to_management) then fires as a
#    [SIMULATED] outbound event.
aipm proposals
aipm message-in "yes, go ahead" --from pm@acme.com --thread thr_05c61cb2

# 3. let the agent scan for follow-ups it should chase on its own
aipm review     # open questions, blocked/in-progress tasks, unowned risks...

# 4. inspect
aipm state      # project meta + entity tables + the approved-action audit trail
aipm events     # the whole log, outbound events flagged [SIMULATED]
```

Without a provider configured (no API key), or with `AIPM_AUTO_EXTRACT=0`,
`message-in`/`note`/`transcript` just log the event and tell you to run
`aipm extract <id>` yourself -- the manual path still works the same.

The two message directions in the loop are both just events:

- **inbound** (a reply to one of the agent's questions) -> `aipm message-in ...`
- **outbound** (the agent asking for status/clarification, or escalating) ->
  a `message_sent` / `ticket_opened` / `flag_raised` /
  `report_to_management` event, written by the backend and shown `[SIMULATED]`.

`info_request` emails (asking for a status update or a clarification on an open
question) are sent automatically at `extract` time -- no approval. Anything
`consequential` waits for `approve`. See `backend/README.md` for that split.

The backend URL defaults to `http://localhost:8000`, overridable via
`AIPM_BACKEND_URL`.

## Running

```
cd cli
pip install -e ".[dev]"
python -m aipm_cli.main state
```

(requires `backend` running separately)

## Running the tests

```
cd cli
pip install -e ../ai-engine
pip install -e ".[dev]"
pytest
```
