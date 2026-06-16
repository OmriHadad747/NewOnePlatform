# CLI

A thin client for `backend`'s API. This is the Phase 1 "surface" -- used to
feed events into a running backend and inspect/replay project state, and to
drive the whole extract -> approve -> act loop end-to-end from a terminal. No
direct dependency on `ai-engine` at runtime (only `backend` talks to it);
`ai-engine` is used in tests to build a realistic fake backend.

## Commands

```
# input -- mint a raw-input event from text, then print its id
aipm note <text>              # a manual_note (--source)
aipm email-in <text>          # an email_reply_received (--from <sender>)
aipm transcript <text>        # a transcript_ingested (--source)
aipm append <event.json>      # POST a hand-written event JSON

# inspect / drive the loop
aipm events                    # the full event log
aipm state                     # the current projected state
aipm extract <event_id>        # run extraction on a raw event -> a proposal
aipm proposals                 # proposals awaiting approval
aipm approve <proposal_id>     # approve a proposal -> applied to state
aipm replay <scenario.yaml>   # replay a scenario and check its checkpoints
```

By default each command prints a human-readable view. Add `--json` before the
command (e.g. `aipm --json state`) to get the raw API JSON instead.

## Simulating the full loop

Execution of outbound actions is a **stub** in Phase 1: the agent never really
sends an email or opens a ticket -- it logs an outbound event recording what it
*would* do. The CLI flags these `[SIMULATED]` so the simulation is obvious.

A typical end-to-end run:

```
# 1. an email reply lands from a vendor
aipm email-in "The vendor API access is delayed two weeks." --from vendor@acme.com
#   -> Added email_reply_received [raw_05c61cb2]

# 2. extract facts/actions from it (writes a proposal; auto-sends any
#    info_request status/clarification emails as [SIMULATED] email_sent)
aipm extract raw_05c61cb2

# 3. review and approve -- the one place text becomes state. Any consequential
#    action (open_ticket / raise_flag / escalate_to_management) then fires as a
#    [SIMULATED] outbound event.
aipm proposals
aipm approve prop_05c61cb2

# 4. inspect
aipm state      # entity tables + the approved-action audit trail
aipm events     # the whole log, outbound events flagged [SIMULATED]
```

The two email directions in the loop are both just events:

- **inbound** (a reply to one of the agent's questions) -> `aipm email-in ...`
- **outbound** (the agent asking for status/clarification, or escalating) ->
  an `email_sent` / `reminder_sent` / `ticket_opened` / `flag_raised` /
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
