"""FastAPI server for concurrent TinyFish search sessions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from travel_deals_agent.provider_discovery import DEFAULT_GEMINI_DISCOVERY_MODEL
from travel_deals_agent.search_service import SearchParams, search_travel_deals


app = FastAPI(title="Travel Deals Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    destination: str = Field(..., description="City, region, or country to search.")
    category: str = Field(..., description="Experience category to search for.")
    date_hint: str | None = Field(default=None, description="Optional timing hint.")
    currency: str = Field(default="USD", description="Preferred display currency.")
    max_results: int = Field(default=3, ge=1, le=10, description="Max results per TinyFish site run.")
    discover_providers: bool = Field(default=True, description="Use Gemini to discover providers first.")
    provider_limit: int = Field(default=4, ge=3, le=5, description="How many providers to discover.")
    gemini_model: str = Field(default=DEFAULT_GEMINI_DISCOVERY_MODEL)
    stealth: bool = Field(default=False)
    site: str = Field(default="getyourguide")
    include_viator: bool = Field(default=False, description="Whether Viator should be included in discovery results.")


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
        params = SearchParams(
            destination=session.request.destination,
            category=session.request.category,
            date_hint=session.request.date_hint,
            currency=session.request.currency,
            max_results=session.request.max_results,
            discover_providers=session.request.discover_providers,
            provider_limit=session.request.provider_limit,
            gemini_model=session.request.gemini_model,
            stealth=session.request.stealth,
            site=session.request.site,
            include_viator=session.request.include_viator,
        )
        session.result = await search_travel_deals(params, event_callback=lambda event: _publish(session, event))
    except Exception as exc:
        session.error = str(exc)
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


def main() -> None:
    import uvicorn

    uvicorn.run("travel_deals_agent.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
