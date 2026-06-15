"""Backend API: wraps ai-engine and owns the event log.

Endpoints:
  POST /events  -- append a new event (validated against current state)
  GET  /events  -- list the full event log, in order
  GET  /state   -- the current projected project state
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from aipm.projection import ProjectionError, apply_event, project

from aipm_backend import storage
from aipm_backend.models import EventIn, serialize_state
from aipm.events import Event

app = FastAPI(title="AI PM Backend")


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
