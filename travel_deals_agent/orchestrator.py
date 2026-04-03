"""LangGraph orchestrator for routing search requests across tools."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from travel_deals_agent.orchestrator_schemas import EventCallback, OrchestratorState
from travel_deals_agent.router import route_query
from travel_deals_agent.tracing import get_tracing_context_kwargs
from travel_deals_agent.tools.ticket_scraper_tool import run_ticket_scraper
from travel_deals_agent.tools.web_search_tool import run_web_search


# Emit an event to the caller if an event callback is present.
async def _emit(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return

    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


# Route the request and seed state with any explicit provider target.
async def _route_request(state: OrchestratorState) -> dict[str, Any]:
    params = state["params"]
    event_callback = state.get("event_callback")
    await _emit(
        event_callback,
        {
            "type": "router.started",
            "category": params.category,
        },
    )

    decision = await asyncio.to_thread(route_query, params)
    selected_targets = []
    provider_discovery = None
    if decision.route == "direct_ticket_scrape" and decision.provider_url:
        selected_targets = [
            {
                "site_id": "site-1",
                "provider_name": decision.provider_name or decision.provider_url,
                "url": decision.provider_url,
                "why_relevant": "Explicit provider selected by the router.",
            }
        ]
        provider_discovery = {
            "model": "orchestrator-router",
            "search_summary": "The orchestrator selected the provider mentioned in the query.",
            "providers": [
                {
                    "provider_name": selected_targets[0]["provider_name"],
                    "url": selected_targets[0]["url"],
                    "why_relevant": selected_targets[0]["why_relevant"],
                }
            ],
        }

    await _emit(
        event_callback,
        {
            "type": "router.completed",
            "route": decision.route,
            "reasoning_summary": decision.reasoning_summary,
            "provider_url": decision.provider_url,
        },
    )
    await _emit(
        event_callback,
        {
            "type": "route.selected",
            "route": decision.route,
            "reasoning_summary": decision.reasoning_summary,
        },
    )
    return {
        "route": decision.route,
        "route_reasoning": decision.reasoning_summary,
        "rewritten_query": decision.rewritten_query,
        "selected_targets": selected_targets,
        "provider_discovery": provider_discovery,
    }


# Choose the next graph node based on the router decision.
def _next_after_route(state: OrchestratorState) -> str:
    return "web_search" if state["route"] == "search_then_scrape" else "ticket_scraper"


# Run the web-search tool and update the state with the discovered provider targets.
async def _run_web_search_node(state: OrchestratorState) -> dict[str, Any]:
    params = state["params"]
    result = await run_web_search(
        params,
        query=state.get("rewritten_query") or params.category,
        event_callback=state.get("event_callback"),
    )
    return {
        "provider_discovery": result["provider_discovery"],
        "selected_targets": result["selected_targets"],
    }


# Run the ticket scraper tool and update the state with the returned payload.
async def _run_ticket_scraper_node(state: OrchestratorState) -> dict[str, Any]:
    params = state["params"]
    payload = await run_ticket_scraper(
        params,
        query=state.get("rewritten_query") or params.category,
        targets=state.get("selected_targets"),
        provider_discovery=state.get("provider_discovery"),
        emit_provider_discovery=state.get("route") == "direct_ticket_scrape",
        event_callback=state.get("event_callback"),
    )
    enriched_payload = dict(payload)
    enriched_payload["orchestration"] = {
        "route": state.get("route"),
        "route_reasoning": state.get("route_reasoning"),
        "tool_chain": ["web_search_tool", "ticket_scraper_tool"]
        if state.get("route") == "search_then_scrape"
        else ["ticket_scraper_tool"],
    }
    return {"final_payload": enriched_payload}


# Emit a final orchestration event after the graph finishes.
async def _finalize(state: OrchestratorState) -> dict[str, Any]:
    await _emit(
        state.get("event_callback"),
        {
            "type": "orchestrator.completed",
            "route": state.get("route"),
            "result_count": len((state.get("final_payload") or {}).get("results") or []),
        },
    )
    return {}


# Build and compile the LangGraph workflow for request orchestration.
def _build_graph() -> Any:
    workflow = StateGraph(OrchestratorState)
    workflow.add_node("route_request", _route_request)
    workflow.add_node("web_search", _run_web_search_node)
    workflow.add_node("ticket_scraper", _run_ticket_scraper_node)
    workflow.add_node("finalize", _finalize)
    workflow.add_edge(START, "route_request")
    workflow.add_conditional_edges(
        "route_request",
        _next_after_route,
        {
            "web_search": "web_search",
            "ticket_scraper": "ticket_scraper",
        },
    )
    workflow.add_edge("web_search", "ticket_scraper")
    workflow.add_edge("ticket_scraper", "finalize")
    workflow.add_edge("finalize", END)
    return workflow.compile()


GRAPH = _build_graph()


# Run the LangGraph orchestrator and return the final payload to the caller.
async def orchestrate_search(
    params: Any,
    *,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Run the top-level LangGraph orchestrator."""
    await _emit(
        event_callback,
        {
            "type": "orchestrator.started",
            "category": params.category,
        },
    )
    tracing_kwargs = get_tracing_context_kwargs(
        tags=["tinyfish-travel-deals-agent", "langgraph"],
        metadata={
            "category": params.category,
            "date_hint": params.date_hint or "",
            "currency": params.currency,
            "discover_providers": params.discover_providers,
            "provider_limit": params.provider_limit,
            "site": params.site,
            "stealth": params.stealth,
        },
    )
    with tracing_context(**tracing_kwargs):
        state = await GRAPH.ainvoke(
            {
                "params": params,
                "event_callback": event_callback,
            }
        )
    return state["final_payload"]
