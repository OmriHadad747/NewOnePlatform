# CLI

A thin client for `backend`'s API. This is the Phase 1 "surface" -- used to
feed events into a running backend and inspect/replay project state. No
direct dependency on `ai-engine` at runtime (only `backend` talks to it);
`ai-engine` is used in tests to build a realistic fake backend.

## Commands

```
aipm append <event.json>      # POST an event to the backend
aipm events                    # GET the full event log
aipm state                     # GET the current projected state
aipm replay <scenario.yaml>   # replay a scenario's events against the
                                # backend and check its checkpoints --
                                # simulates a project end-to-end
aipm extract <event_id>        # run extraction on a raw event -> a proposal
aipm proposals                 # list proposals awaiting approval
aipm approve <proposal_id>     # approve a proposal -> applied to state
```

The extract/approve commands drive the Step 3 loop: `extract` turns a raw
event into an `agent_proposal` (no state change), `proposals` lists what's
pending, and `approve` writes the `human_approval` that applies it.

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
