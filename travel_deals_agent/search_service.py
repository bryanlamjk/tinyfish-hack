"""Shared search workflow for CLI and web app usage."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from tinyfish import (
    AsyncTinyFish,
    BrowserProfile,
    CompleteEvent,
    HeartbeatEvent,
    ProgressEvent,
    RunStatus,
    StartedEvent,
    StreamingUrlEvent,
)

from travel_deals_agent.config import get_gemini_api_key, get_tinyfish_api_key
from travel_deals_agent.prompts import build_goal
from travel_deals_agent.provider_discovery import (
    DEFAULT_GEMINI_DISCOVERY_MODEL,
    discover_provider_urls,
)


DEFAULT_SITES: dict[str, str] = {
    "getyourguide": "https://www.getyourguide.com",
    "klook": "https://www.klook.com",
    "viator": "https://www.viator.com",
    "airbnb": "https://www.airbnb.com/experiences",
}


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(slots=True)
class SearchParams:
    destination: str
    category: str = "guided tours, workshops, and memorable local experiences"
    date_hint: str | None = None
    currency: str = "USD"
    max_results: int = 5
    discover_providers: bool = False
    provider_limit: int = 4
    gemini_model: str = DEFAULT_GEMINI_DISCOVERY_MODEL
    stealth: bool = False
    site: str = "getyourguide"


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _build_preview_url(streaming_url: str) -> str:
    if streaming_url.startswith("wss://"):
        return f"https://{streaming_url.removeprefix('wss://')}"
    if streaming_url.startswith("ws://"):
        return f"http://{streaming_url.removeprefix('ws://')}"
    return streaming_url


async def _emit(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return

    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


def _normalize_result_item(item: dict[str, Any], *, provider_name: str, start_url: str) -> dict[str, Any]:
    normalized = dict(item)
    normalized.setdefault("provider", normalized.get("provider") or provider_name)
    normalized["source_provider"] = provider_name
    normalized["source_url"] = start_url
    return normalized


def _build_site_payload(
    *,
    provider_name: str,
    start_url: str,
    raw_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    results = raw_payload.get("results") if raw_payload else []
    normalized_results = [
        _normalize_result_item(item, provider_name=provider_name, start_url=start_url)
        for item in (results or [])
        if isinstance(item, dict)
    ]
    return {
        "provider_name": provider_name,
        "start_url": start_url,
        "summary": (raw_payload or {}).get("summary") if raw_payload else None,
        "results": normalized_results,
        "error": error,
    }


def _build_final_payload(
    *,
    params: SearchParams,
    discovery_payload: dict[str, Any] | None,
    site_results: list[dict[str, Any]],
) -> dict[str, Any]:
    flattened_results: list[dict[str, Any]] = []
    successful_sites = 0
    failed_sites = 0

    for site in site_results:
        results = site.get("results") or []
        flattened_results.extend(results)
        if site.get("error"):
            failed_sites += 1
        elif results:
            successful_sites += 1

    if discovery_payload:
        discovery_summary = discovery_payload.get("search_summary") or "Gemini discovered relevant providers."
        if flattened_results:
            summary = (
                f"{discovery_summary} Tinyfish returned {len(flattened_results)} total results "
                f"across {successful_sites} provider sites."
            )
        else:
            summary = (
                f"{discovery_summary} Tinyfish did not return matching deals from the discovered sites."
            )
    else:
        if flattened_results:
            summary = f"Tinyfish returned {len(flattened_results)} results from {site_results[0]['provider_name']}."
        else:
            summary = "Tinyfish did not return any matching deals."

    if failed_sites:
        summary = f"{summary} {failed_sites} site runs failed."

    return {
        "destination": params.destination,
        "searched_category": params.category,
        "summary": summary,
        "provider_discovery": discovery_payload,
        "site_results": site_results,
        "results": flattened_results,
    }


async def _run_tinyfish_site_stream(
    *,
    tinyfish_api_key: str,
    goal: str,
    provider_name: str,
    start_url: str,
    site_id: str,
    profile: BrowserProfile,
    event_callback: EventCallback | None,
) -> dict[str, Any]:
    client = AsyncTinyFish(api_key=tinyfish_api_key)
    run_id: str | None = None
    final_payload: dict[str, Any] | None = None

    await _emit(
        event_callback,
        {
            "type": "agent.queued",
            "site_id": site_id,
            "provider_name": provider_name,
            "start_url": start_url,
        },
    )

    try:
        async with client.agent.stream(goal=goal, url=start_url, browser_profile=profile) as stream:
            async for event in stream:
                if isinstance(event, StartedEvent):
                    run_id = event.run_id
                    await _emit(
                        event_callback,
                        {
                            "type": "agent.started",
                            "site_id": site_id,
                            "provider_name": provider_name,
                            "start_url": start_url,
                            "run_id": run_id,
                            "timestamp": _isoformat(event.timestamp),
                        },
                    )
                elif isinstance(event, StreamingUrlEvent):
                    await _emit(
                        event_callback,
                        {
                            "type": "agent.streaming_url",
                            "site_id": site_id,
                            "provider_name": provider_name,
                            "start_url": start_url,
                            "run_id": event.run_id,
                            "streaming_url": event.streaming_url,
                            "preview_url": _build_preview_url(event.streaming_url),
                            "timestamp": _isoformat(event.timestamp),
                        },
                    )
                elif isinstance(event, ProgressEvent):
                    await _emit(
                        event_callback,
                        {
                            "type": "agent.progress",
                            "site_id": site_id,
                            "provider_name": provider_name,
                            "start_url": start_url,
                            "run_id": event.run_id,
                            "purpose": event.purpose,
                            "timestamp": _isoformat(event.timestamp),
                        },
                    )
                elif isinstance(event, HeartbeatEvent):
                    await _emit(
                        event_callback,
                        {
                            "type": "agent.heartbeat",
                            "site_id": site_id,
                            "provider_name": provider_name,
                            "start_url": start_url,
                            "timestamp": _isoformat(event.timestamp),
                        },
                    )
                elif isinstance(event, CompleteEvent):
                    run_id = event.run_id
                    if event.status != RunStatus.COMPLETED:
                        error_message = event.error.message if event.error else "Unknown Tinyfish error"
                        raise RuntimeError(error_message)
                    final_payload = dict(event.result_json or {})

        if final_payload is None and run_id:
            run = await client.runs.get(run_id)
            if run.status != RunStatus.COMPLETED:
                if run.error:
                    raise RuntimeError(run.error.message)
                raise RuntimeError(f"Unexpected Tinyfish run status: {run.status}")
            final_payload = dict(run.result or {})

        if final_payload is None:
            raise RuntimeError("Tinyfish completed without a final JSON payload.")

        site_payload = _build_site_payload(
            provider_name=provider_name,
            start_url=start_url,
            raw_payload=final_payload,
        )
        await _emit(
            event_callback,
            {
                "type": "agent.completed",
                "site_id": site_id,
                "provider_name": provider_name,
                "start_url": start_url,
                "summary": site_payload.get("summary"),
                "result_count": len(site_payload["results"]),
                "results": site_payload["results"],
            },
        )
        return site_payload
    except Exception as exc:
        message = str(exc)
        await _emit(
            event_callback,
            {
                "type": "agent.failed",
                "site_id": site_id,
                "provider_name": provider_name,
                "start_url": start_url,
                "run_id": run_id,
                "error": message,
            },
        )
        return _build_site_payload(provider_name=provider_name, start_url=start_url, error=message)


async def search_travel_deals(
    params: SearchParams,
    *,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Run a travel deal search, optionally discovering providers first."""
    if params.discover_providers and not 3 <= params.provider_limit <= 5:
        raise RuntimeError("--provider-limit must be between 3 and 5 when provider discovery is enabled.")

    tinyfish_api_key = get_tinyfish_api_key()
    goal = build_goal(
        destination=params.destination,
        date_hint=params.date_hint,
        category=params.category,
        currency=params.currency,
        max_results=params.max_results,
    )

    await _emit(
        event_callback,
        {
            "type": "session.started",
            "destination": params.destination,
            "category": params.category,
            "discover_providers": params.discover_providers,
        },
    )

    discovery_payload: dict[str, Any] | None = None
    targets: list[dict[str, str]] = []

    if params.discover_providers:
        await _emit(
            event_callback,
            {
                "type": "providers.discovery_started",
                "destination": params.destination,
                "category": params.category,
                "provider_limit": params.provider_limit,
                "model": params.gemini_model,
            },
        )
        discovery_payload = await asyncio.to_thread(
            discover_provider_urls,
            api_key=get_gemini_api_key(),
            destination=params.destination,
            category=params.category,
            date_hint=params.date_hint,
            max_providers=params.provider_limit,
            model=params.gemini_model,
        )
        targets = [
            {
                "site_id": f"site-{index + 1}",
                "provider_name": provider["provider_name"],
                "url": provider["url"],
            }
            for index, provider in enumerate(discovery_payload["providers"])
        ]
        await _emit(
            event_callback,
            {
                "type": "providers.discovered",
                "providers": discovery_payload["providers"],
                "summary": discovery_payload.get("search_summary"),
            },
        )
    else:
        targets = [
            {
                "site_id": "site-1",
                "provider_name": params.site,
                "url": DEFAULT_SITES[params.site],
            }
        ]

    profile = BrowserProfile.STEALTH if params.stealth else BrowserProfile.LITE
    site_results = await asyncio.gather(
        *[
            _run_tinyfish_site_stream(
                tinyfish_api_key=tinyfish_api_key,
                goal=goal,
                provider_name=target["provider_name"],
                start_url=target["url"],
                site_id=target["site_id"],
                profile=profile,
                event_callback=event_callback,
            )
            for target in targets
        ]
    )

    final_payload = _build_final_payload(
        params=params,
        discovery_payload=discovery_payload,
        site_results=site_results,
    )
    await _emit(
        event_callback,
        {
            "type": "session.completed",
            "payload": final_payload,
        },
    )
    return final_payload
