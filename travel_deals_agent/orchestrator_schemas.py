"""Shared state and schemas for the LangGraph orchestrator."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field

from travel_deals_agent.search_service import SearchParams


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class ProviderTarget(TypedDict):
    provider_name: str
    url: str
    why_relevant: NotRequired[str]
    site_id: NotRequired[str]


class RouteDecision(BaseModel):
    route: Literal["direct_ticket_scrape", "search_then_scrape"] = Field(
        description="Whether to scrape an explicit provider directly or search the web for providers first."
    )
    reasoning_summary: str = Field(description="Short explanation of why this route was chosen.")
    rewritten_query: str = Field(description="Normalized query to pass to downstream tools.")
    provider_name: str | None = Field(default=None, description="Explicit provider name when one was found.")
    provider_url: str | None = Field(default=None, description="Explicit provider URL when one was found.")


class OrchestratorState(TypedDict, total=False):
    params: SearchParams
    event_callback: EventCallback | None
    route: Literal["direct_ticket_scrape", "search_then_scrape"]
    route_reasoning: str
    rewritten_query: str
    selected_targets: list[ProviderTarget]
    provider_discovery: dict[str, Any]
    final_payload: dict[str, Any]
