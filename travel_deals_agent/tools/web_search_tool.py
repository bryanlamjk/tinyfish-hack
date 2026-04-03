"""Web-search tool for discovering providers before scraping."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import asdict, is_dataclass
from typing import Any

from langsmith import traceable

from travel_deals_agent.config import get_gemini_api_key
from travel_deals_agent.orchestrator_schemas import EventCallback, ProviderTarget
from travel_deals_agent.provider_discovery import discover_provider_urls
from travel_deals_agent.search_service import SearchParams


async def _emit(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return

    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


def _process_tool_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(inputs)
    sanitized.pop("event_callback", None)
    params = sanitized.get("params")
    if params is not None and is_dataclass(params):
        sanitized["params"] = asdict(params)
    return sanitized


@traceable(name="web_search_tool", run_type="tool", process_inputs=_process_tool_inputs)
async def run_web_search(
    params: SearchParams,
    *,
    query: str,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Discover provider targets using grounded web search."""
    await _emit(
        event_callback,
        {
            "type": "web_search.started",
            "category": query,
            "provider_limit": params.provider_limit,
            "block_marketplace_providers": params.block_marketplace_providers,
        },
    )

    discovery_payload = await asyncio.to_thread(
        discover_provider_urls,
        api_key=get_gemini_api_key(),
        category=query,
        date_hint=params.date_hint,
        max_providers=params.provider_limit,
        model=params.gemini_model,
        block_marketplace_providers=params.block_marketplace_providers,
    )
    selected_targets: list[ProviderTarget] = [
        {
            "site_id": f"site-{index + 1}",
            "provider_name": provider["provider_name"],
            "url": provider["url"],
            "why_relevant": provider.get("why_relevant") or "Relevant travel provider.",
        }
        for index, provider in enumerate(discovery_payload["providers"])
    ]

    await _emit(
        event_callback,
        {
            "type": "web_search.completed",
            "provider_count": len(selected_targets),
            "summary": discovery_payload.get("search_summary"),
        },
    )
    await _emit(
        event_callback,
        {
            "type": "providers.discovered",
            "providers": discovery_payload["providers"],
            "summary": discovery_payload.get("search_summary"),
        },
    )
    return {
        "provider_discovery": discovery_payload,
        "selected_targets": selected_targets,
    }
