"""FastAPI server for concurrent TinyFish search sessions."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from travel_deals_agent.itinerary_graph import plan_itinerary
from travel_deals_agent.provider_discovery import DEFAULT_GEMINI_DISCOVERY_MODEL
from travel_deals_agent.search_service import SearchParams, search_travel_deals


if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

logger = logging.getLogger(__name__)
app = FastAPI(title="Travel Deals Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000","http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    category: str = Field(..., description="The full search request to search for.")
    date_hint: str | None = Field(default=None, description="Optional timing hint.")
    currency: str = Field(default="USD", description="Preferred display currency.")
    max_results: int = Field(default=3, ge=1, le=10, description="Max results per TinyFish site run.")
    discover_providers: bool = Field(default=True, description="Use Gemini to discover providers first.")
    provider_limit: int = Field(default=4, ge=1, le=5, description="How many providers to discover.")
    block_marketplace_providers: bool = Field(
        default=True,
        description="When true, Gemini discovery and target filtering avoid travel marketplaces and aggregators.",
    )
    gemini_model: str = Field(default=DEFAULT_GEMINI_DISCOVERY_MODEL)
    stealth: bool = Field(default=False)
    site: str = Field(default="getyourguide")


class SearchSessionCreated(BaseModel):
    session_id: str


@dataclass
class SearchSession:
    session_id: str
    request: SearchRequest
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    history: list[dict[str, Any]] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None


SESSIONS: dict[str, SearchSession] = {}


async def _publish(session: SearchSession, event: dict[str, Any]) -> None:
    payload = {"session_id": session.session_id, **event}
    session.history.append(payload)
    async with session.condition:
        session.condition.notify_all()


async def _run_session(session: SearchSession) -> None:
    try:
        logger.info("Backend session starting session_id=%s", session.session_id)
        params = SearchParams(
            category=session.request.category,
            date_hint=session.request.date_hint,
            currency=session.request.currency,
            max_results=session.request.max_results,
            discover_providers=session.request.discover_providers,
            provider_limit=session.request.provider_limit,
            block_marketplace_providers=session.request.block_marketplace_providers,
            gemini_model=session.request.gemini_model,
            stealth=session.request.stealth,
            site=session.request.site,
        )
        session.result = await search_travel_deals(params, event_callback=lambda event: _publish(session, event))
        logger.info("Backend session completed session_id=%s", session.session_id)
    except Exception as exc:
        session.error = str(exc)
        logger.exception("Backend session failed session_id=%s", session.session_id)
        await _publish(session, {"type": "session.failed", "error": session.error})
    finally:
        session.done = True
        async with session.condition:
            session.condition.notify_all()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/searches", response_model=SearchSessionCreated)
async def create_search_session(request: SearchRequest) -> SearchSessionCreated:
    session_id = str(uuid4())
    session = SearchSession(session_id=session_id, request=request)
    SESSIONS[session_id] = session
    logger.info("Created backend session session_id=%s request=%s", session_id, request.model_dump())
    asyncio.create_task(_run_session(session))
    return SearchSessionCreated(session_id=session_id)


@app.get("/api/searches/{session_id}")
async def get_search_session(session_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session.")
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "done": session.done,
        "error": session.error,
        "result": session.result,
    }


@app.get("/api/searches/{session_id}/events")
async def stream_search_events(session_id: str) -> StreamingResponse:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session.")

    async def event_stream() -> Any:
        index = 0
        while True:
            while index < len(session.history):
                payload = session.history[index]
                index += 1
                yield f"data: {json.dumps(payload)}\n\n"

            if session.done:
                break

            try:
                async with session.condition:
                    await asyncio.wait_for(session.condition.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


class ItineraryRequest(BaseModel):
    """Request body for the itinerary planner endpoint."""

    query: str = Field(..., description="Free-form travel query (e.g. '5 day Kyoto trip for a couple').")
    currency: str = Field(default="USD", description="Preferred display currency.")


class ItinerarySessionCreated(BaseModel):
    """Response body after creating an itinerary session."""

    session_id: str


@dataclass
class ItinerarySession:
    """Tracks the state and event history of a running itinerary planning session."""

    session_id: str
    request: ItineraryRequest
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    history: list[dict[str, Any]] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None


ITINERARY_SESSIONS: dict[str, ItinerarySession] = {}


async def _publish_itinerary(session: ItinerarySession, event: dict[str, Any]) -> None:
    """Append an event to the itinerary session history and notify SSE waiters.

    Input: session -- the ItinerarySession, event -- event dict.
    Output: None.
    """
    payload = {"session_id": session.session_id, **event}
    session.history.append(payload)
    async with session.condition:
        session.condition.notify_all()


async def _run_itinerary_session(session: ItinerarySession) -> None:
    """Execute the itinerary planner pipeline for a session.

    Input: session -- an ItinerarySession with the user's request.
    Output: None. Mutates session.result or session.error.
    """
    try:
        logger.info("Itinerary session starting session_id=%s", session.session_id)
        session.result = await plan_itinerary(
            session.request.query,
            event_callback=lambda event: _publish_itinerary(session, event),
        )
        logger.info("Itinerary session completed session_id=%s", session.session_id)
    except Exception as exc:
        session.error = str(exc)
        logger.exception("Itinerary session failed session_id=%s", session.session_id)
        await _publish_itinerary(session, {"type": "itinerary.failed", "error": session.error})
    finally:
        session.done = True
        async with session.condition:
            session.condition.notify_all()


@app.post("/api/itinerary", response_model=ItinerarySessionCreated)
async def create_itinerary_session(request: ItineraryRequest) -> ItinerarySessionCreated:
    """Create a new itinerary planning session and start processing in the background.

    Input: request -- ItineraryRequest with query and optional currency.
    Output: ItinerarySessionCreated with the new session_id.
    """
    session_id = str(uuid4())
    session = ItinerarySession(session_id=session_id, request=request)
    ITINERARY_SESSIONS[session_id] = session
    logger.info("Created itinerary session session_id=%s request=%s", session_id, request.model_dump())
    asyncio.create_task(_run_itinerary_session(session))
    return ItinerarySessionCreated(session_id=session_id)


@app.get("/api/itinerary/{session_id}")
async def get_itinerary_session(session_id: str) -> dict[str, Any]:
    """Poll for the current state and result of an itinerary session.

    Input: session_id -- UUID of the itinerary session.
    Output: Dict with session metadata, completion status, and result or error.
    """
    session = ITINERARY_SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown itinerary session.")
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "done": session.done,
        "error": session.error,
        "result": session.result,
    }


@app.get("/api/itinerary/{session_id}/events")
async def stream_itinerary_events(session_id: str) -> StreamingResponse:
    """Stream SSE events for an itinerary session.

    Input: session_id -- UUID of the itinerary session.
    Output: StreamingResponse with text/event-stream content type.
    """
    session = ITINERARY_SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown itinerary session.")

    async def event_stream() -> Any:
        index = 0
        while True:
            while index < len(session.history):
                payload = session.history[index]
                index += 1
                yield f"data: {json.dumps(payload)}\n\n"

            if session.done:
                break

            try:
                async with session.condition:
                    await asyncio.wait_for(session.condition.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("travel_deals_agent.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
