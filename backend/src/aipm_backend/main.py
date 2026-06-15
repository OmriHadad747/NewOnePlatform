"""Backend API: wraps ai-engine and owns the event log.

Event endpoints:
  POST /events  -- append a new event (validated against current state)
  GET  /events  -- list the full event log, in order
  GET  /state   -- the current projected project state

Extraction / approval flow (Step 3):
  POST /extract                    -- run extraction on a raw event, write an
                                      agent_proposal (no state change)
  GET  /proposals                  -- proposals still awaiting approval
  POST /proposals/{id}/approve     -- approve a proposal: write a
                                      human_approval that applies its
                                      deltas/actions to state
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException

from aipm.events import RAW_INPUT_TYPES, Event
from aipm.extraction import build_prompt, filter_grounded
from aipm.extraction.providers import ExtractionProvider
from aipm.projection import ProjectionError, apply_event, project

from aipm_backend import storage
from aipm_backend.extraction import get_provider
from aipm_backend.models import EventIn, ExtractRequest, serialize_state

app = FastAPI(title="AI PM Backend")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.post("/events", status_code=201)
def create_event(event_in: EventIn) -> dict:
    try:
        new_event = Event(**event_in.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    events = storage.read_events()
    state = project(events)

    try:
        apply_event(state, new_event)
    except ProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.write_event(new_event)
    return asdict(new_event)


@app.get("/events")
def list_events() -> list[dict]:
    return [asdict(event) for event in storage.read_events()]


@app.get("/state")
def get_state() -> dict:
    events = storage.read_events()
    state = project(events)
    return serialize_state(state)


@app.post("/extract", status_code=201)
def extract(
    req: ExtractRequest,
    provider: ExtractionProvider = Depends(get_provider),
) -> dict:
    events = storage.read_events()

    source = next((e for e in events if e.id == req.source_event_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"event {req.source_event_id!r} not found")
    if source.type not in RAW_INPUT_TYPES or not source.raw_text:
        raise HTTPException(
            status_code=400,
            detail=f"event {req.source_event_id!r} is not a raw-input event with text",
        )

    state = project(events)
    prompt = build_prompt(source.raw_text, state)

    try:
        result = provider.extract(prompt)
    except Exception as exc:  # provider/network failure -> 502
        raise HTTPException(status_code=502, detail=f"extraction failed: {exc}") from exc

    grounded, dropped = filter_grounded(result, source.raw_text)
    payload = grounded.to_payload(asserted_by=provider.name)
    payload["source_event_id"] = source.id
    payload["provider"] = provider.name

    proposal = Event(
        id=f"prop_{uuid.uuid4().hex[:12]}",
        type="agent_proposal",
        timestamp=_now(),
        source=f"extraction:{provider.name}",
        payload=payload,
    )
    storage.write_event(proposal)
    return {"proposal": asdict(proposal), "dropped": dropped}


@app.get("/proposals")
def list_proposals() -> list[dict]:
    events = storage.read_events()
    approved = {
        e.payload.get("approves") for e in events if e.type == "human_approval"
    }
    pending = [
        asdict(e)
        for e in events
        if e.type == "agent_proposal" and e.id not in approved
    ]
    return pending


@app.post("/proposals/{proposal_id}/approve", status_code=201)
def approve_proposal(proposal_id: str) -> dict:
    events = storage.read_events()

    proposal = next(
        (e for e in events if e.type == "agent_proposal" and e.id == proposal_id), None
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")

    approval = Event(
        id=f"appr_{uuid.uuid4().hex[:12]}",
        type="human_approval",
        timestamp=_now(),
        source="approval",
        payload={
            "deltas": proposal.payload.get("deltas", []),
            "actions": proposal.payload.get("actions", []),
            "approves": proposal_id,
        },
    )

    state = project(events)
    try:
        apply_event(state, approval)
    except ProjectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.write_event(approval)
    return asdict(approval)
