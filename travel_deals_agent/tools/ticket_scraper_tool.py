"""Ticket scraping tool wrapper for the LangGraph orchestrator."""

from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass, replace
from typing import Any

from langsmith import traceable

from travel_deals_agent.orchestrator_schemas import EventCallback, ProviderTarget
from travel_deals_agent.search_service import SearchParams, search_travel_deals


# Emit a tool event if the caller provided a callback.
async def _emit(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return

    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


# Remove callback objects and dataclasses before tracing tool inputs.
def _process_tool_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(inputs)
    sanitized.pop("event_callback", None)
    params = sanitized.get("params")
    if params is not None and is_dataclass(params):
        sanitized["params"] = asdict(params)
    return sanitized


# Build a provider-discovery payload for explicit targets selected by the router.
def _build_synthetic_provider_discovery(targets: list[ProviderTarget]) -> dict[str, Any]:
    return {
        "model": "orchestrator-router",
        "search_summary": "The orchestrator used an explicit provider from the query.",
        "providers": [
            {
                "provider_name": target["provider_name"],
                "url": target["url"],
                "why_relevant": target.get("why_relevant") or "Explicit provider selected by the app.",
            }
            for target in targets
        ],
    }


# Run the TinyFish scraper against explicit targets or the default discovery flow.
@traceable(name="ticket_scraper_tool", run_type="tool", process_inputs=_process_tool_inputs)
async def run_ticket_scraper(
    params: SearchParams,
    *,
    query: str,
    targets: list[ProviderTarget] | None = None,
    provider_discovery: dict[str, Any] | None = None,
    emit_provider_discovery: bool = False,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Run the TinyFish scraper tool, optionally against explicit targets."""
    effective_targets = targets or []
    effective_discovery = provider_discovery
    if effective_targets and not effective_discovery:
        effective_discovery = _build_synthetic_provider_discovery(effective_targets)

    if effective_discovery and emit_provider_discovery:
        await _emit(
            event_callback,
            {
                "type": "providers.discovered",
                "providers": effective_discovery.get("providers") or [],
                "summary": effective_discovery.get("search_summary"),
            },
        )

    await _emit(
        event_callback,
        {
            "type": "ticket_scraper.started",
            "category": query,
            "provider_count": len(effective_targets) or 1,
        },
    )

    tool_params = replace(
        params,
        category=query,
        discover_providers=not bool(effective_targets) and params.discover_providers,
        explicit_targets=[
            {"site_id": target.get("site_id") or f"site-{index + 1}", "provider_name": target["provider_name"], "url": target["url"]}
            for index, target in enumerate(effective_targets)
        ]
        or None,
        prefetched_provider_discovery=effective_discovery,
    )
    payload = await search_travel_deals(tool_params, event_callback=event_callback)
    await _emit(
        event_callback,
        {
            "type": "ticket_scraper.completed",
            "result_count": len(payload.get("results") or []),
            "summary": payload.get("summary"),
        },
    )
    return payload
