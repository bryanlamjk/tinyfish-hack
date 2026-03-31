"""Shared search workflow for CLI and web app usage."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

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
    MARKETPLACE_PROVIDER_DOMAINS,
    discover_provider_urls,
)


DEFAULT_SITES: dict[str, str] = {
    "getyourguide": "https://www.getyourguide.com",
    "klook": "https://www.klook.com",
    "viator": "https://www.viator.com",
    "airbnb": "https://www.airbnb.com/experiences",
}
PREFERRED_PROVIDER_ORDER = {
    "getyourguide.com": 0,
    "airbnb.com": 1,
    "tiqets.com": 2,
    "headout.com": 3,
}

BOT_BLOCK_PATTERNS = (
    "captcha",
    "audio verification",
    "slider",
    "bot protection",
    "block to potentially lift",
    "blocked by",
    "cloudflare",
    "access denied",
    "unusual traffic",
)

TRANSIENT_STREAM_PATTERNS = (
    "incomplete chunked read",
    "peer closed connection",
    "server disconnected",
    "connection reset",
    "stream ended unexpectedly",
)

MAX_PROVIDER_ATTEMPTS = 2
MAX_PROGRESS_EVENTS = 36
MAX_IDENTICAL_PROGRESS_STREAK = 6


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchParams:
    category: str = "guided tours, workshops, and memorable local experiences"
    date_hint: str | None = None
    currency: str = "USD"
    max_results: int = 5
    discover_providers: bool = False
    provider_limit: int = 4
    block_marketplace_providers: bool = True
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


def _classify_provider_failure(message: str) -> tuple[str, str]:
    normalized = message.lower()
    if any(pattern in normalized for pattern in BOT_BLOCK_PATTERNS):
        return (
            "bot_protection",
            "This provider appears to be blocking browser automation. Try another provider, keep stealth on, or use a more specific activity page.",
        )
    if "loop" in normalized or "repeating the same action" in normalized or "too many progress steps" in normalized:
        return (
            "loop_detected",
            "This provider appears to be stuck in a loop. Try a narrower activity, a different provider, or a more specific starting page.",
        )
    if any(pattern in normalized for pattern in TRANSIENT_STREAM_PATTERNS):
        return (
            "transient_connection",
            "The provider stream disconnected unexpectedly. The app will retry once automatically when this happens.",
        )
    return (
        "unknown",
        "The run failed for this provider. Try rerunning, using stealth mode, or narrowing the search request.",
    )


def _should_retry_provider_error(message: str, attempt: int) -> bool:
    if attempt >= MAX_PROVIDER_ATTEMPTS:
        return False
    normalized = message.lower()
    return any(pattern in normalized for pattern in TRANSIENT_STREAM_PATTERNS)


def _rank_provider_target(target: dict[str, str]) -> tuple[int, str]:
    url = target["url"].lower()
    for domain, rank in PREFERRED_PROVIDER_ORDER.items():
        if domain in url:
            return (rank, target["provider_name"].lower())
    return (50, target["provider_name"].lower())


def _is_blocked_provider_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in MARKETPLACE_PROVIDER_DOMAINS)


def _filter_and_rank_targets(
    targets: list[dict[str, str]],
    *,
    block_marketplace_providers: bool,
) -> list[dict[str, str]]:
    if not block_marketplace_providers:
        return sorted(targets, key=_rank_provider_target)

    filtered = [target for target in targets if not _is_blocked_provider_url(target["url"])]
    if not filtered:
        filtered = targets
    return sorted(filtered, key=_rank_provider_target)


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


def _compact_text(value: str, *, limit: int = 220) -> str:
    compacted = " ".join(value.split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}

    return parsed if isinstance(parsed, dict) else {}


def _coerce_site_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, dict):
        if isinstance(raw_payload.get("results"), list):
            return dict(raw_payload)

        nested_result = raw_payload.get("result")
        if isinstance(nested_result, str):
            parsed_nested = _extract_json_object(nested_result)
            if parsed_nested:
                return parsed_nested

        return dict(raw_payload)

    if isinstance(raw_payload, str):
        return _extract_json_object(raw_payload)

    return {}


def _build_site_payload(
    *,
    provider_name: str,
    start_url: str,
    raw_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    normalized_payload = _coerce_site_payload(raw_payload)
    results = normalized_payload.get("results") if normalized_payload else []
    normalized_results = [
        _normalize_result_item(item, provider_name=provider_name, start_url=start_url)
        for item in (results or [])
        if isinstance(item, dict)
    ]
    summary = normalized_payload.get("summary") if normalized_payload else None
    if not summary:
        summary = "No strong matches found on this site."
    return {
        "provider_name": provider_name,
        "start_url": start_url,
        "summary": summary,
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
                f"{discovery_summary} Tinyfish did not return matching bookable options from the discovered sites."
            )
    else:
        if flattened_results:
            summary = f"Tinyfish returned {len(flattened_results)} results from {site_results[0]['provider_name']}."
        else:
            summary = "Tinyfish did not return any matching bookable options."

    if failed_sites:
        summary = f"{summary} {failed_sites} site runs failed."

    return {
        "search_query": params.category,
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
    await _emit(
        event_callback,
        {
            "type": "agent.queued",
            "site_id": site_id,
            "provider_name": provider_name,
            "start_url": start_url,
        },
    )

    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        client = AsyncTinyFish(api_key=tinyfish_api_key)
        run_id: str | None = None
        final_payload: dict[str, Any] | None = None
        progress_events = 0
        last_progress_purpose = ""
        identical_progress_streak = 0
        recent_progress: list[str] = []
        attempt_started_at = monotonic()
        logger.info(
            "Starting TinyFish run site_id=%s provider=%s url=%s attempt=%s",
            site_id,
            provider_name,
            start_url,
            attempt,
        )
        logger.info(
            "TinyFish goal site_id=%s provider=%s attempt=%s goal=%s",
            site_id,
            provider_name,
            attempt,
            _compact_text(goal, limit=600),
        )

        try:
            async with client.agent.stream(goal=goal, url=start_url, browser_profile=profile) as stream:
                async for event in stream:
                    if isinstance(event, StartedEvent):
                        run_id = event.run_id
                        logger.info(
                            "TinyFish run started site_id=%s provider=%s run_id=%s attempt=%s",
                            site_id,
                            provider_name,
                            run_id,
                            attempt,
                        )
                        await _emit(
                            event_callback,
                            {
                                "type": "agent.started",
                                "site_id": site_id,
                                "provider_name": provider_name,
                                "start_url": start_url,
                                "run_id": run_id,
                                "timestamp": _isoformat(event.timestamp),
                                "attempt": attempt,
                            },
                        )
                    elif isinstance(event, StreamingUrlEvent):
                        logger.info(
                            "TinyFish stream available site_id=%s provider=%s streaming_url=%s attempt=%s",
                            site_id,
                            provider_name,
                            event.streaming_url,
                            attempt,
                        )
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
                                "attempt": attempt,
                            },
                        )
                    elif isinstance(event, ProgressEvent):
                        progress_events += 1
                        identical_progress_streak = (
                            identical_progress_streak + 1 if event.purpose == last_progress_purpose else 1
                        )
                        last_progress_purpose = event.purpose
                        recent_progress.append(event.purpose)
                        if len(recent_progress) > 8:
                            recent_progress = recent_progress[-8:]
                        logger.info(
                            "TinyFish progress site_id=%s provider=%s attempt=%s step=%s repeat=%s elapsed_s=%.1f purpose=%s",
                            site_id,
                            provider_name,
                            attempt,
                            progress_events,
                            identical_progress_streak,
                            monotonic() - attempt_started_at,
                            _compact_text(event.purpose),
                        )
                        if progress_events > MAX_PROGRESS_EVENTS:
                            raise RuntimeError("Provider run appears stuck in a loop after too many progress steps.")
                        if identical_progress_streak >= MAX_IDENTICAL_PROGRESS_STREAK:
                            raise RuntimeError("Provider run appears stuck in a loop by repeating the same action.")
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
                                "attempt": attempt,
                            },
                        )
                    elif isinstance(event, HeartbeatEvent):
                        logger.info(
                            "TinyFish heartbeat site_id=%s provider=%s attempt=%s elapsed_s=%.1f progress_steps=%s last_purpose=%s",
                            site_id,
                            provider_name,
                            attempt,
                            monotonic() - attempt_started_at,
                            progress_events,
                            _compact_text(last_progress_purpose) if last_progress_purpose else "<none>",
                        )
                        await _emit(
                            event_callback,
                            {
                                "type": "agent.heartbeat",
                                "site_id": site_id,
                                "provider_name": provider_name,
                                "start_url": start_url,
                                "timestamp": _isoformat(event.timestamp),
                                "attempt": attempt,
                            },
                        )
                    elif isinstance(event, CompleteEvent):
                        run_id = event.run_id
                        if event.status != RunStatus.COMPLETED:
                            error_message = event.error.message if event.error else "Unknown Tinyfish error"
                            raise RuntimeError(error_message)
                        final_payload = dict(event.result_json or {})
                        logger.info(
                            "TinyFish raw payload site_id=%s provider=%s attempt=%s payload=%s",
                            site_id,
                            provider_name,
                            attempt,
                            json.dumps(final_payload, ensure_ascii=True),
                        )

            if run_id and not final_payload:
                logger.warning(
                    "TinyFish empty or missing stream payload site_id=%s provider=%s attempt=%s elapsed_s=%.1f progress_steps=%s recent_progress=%s",
                    site_id,
                    provider_name,
                    attempt,
                    monotonic() - attempt_started_at,
                    progress_events,
                    json.dumps(recent_progress, ensure_ascii=True),
                )
            if run_id and (final_payload is None or not final_payload):
                logger.info(
                    "Fetching TinyFish run snapshot site_id=%s provider=%s run_id=%s attempt=%s",
                    site_id,
                    provider_name,
                    run_id,
                    attempt,
                )
                run = await client.runs.get(run_id)
                logger.info(
                    "TinyFish run snapshot site_id=%s provider=%s run_id=%s attempt=%s status=%s result=%s",
                    site_id,
                    provider_name,
                    run_id,
                    attempt,
                    run.status,
                    json.dumps(dict(run.result or {}), ensure_ascii=True),
                )
                if run.status != RunStatus.COMPLETED:
                    if run.error:
                        raise RuntimeError(run.error.message)
                    raise RuntimeError(f"Unexpected Tinyfish run status: {run.status}")
                if run.result:
                    final_payload = dict(run.result)
            if final_payload is None:
                raise RuntimeError("Tinyfish completed without a final JSON payload.")
            if not final_payload:
                logger.warning(
                    "TinyFish final payload still empty site_id=%s provider=%s attempt=%s recent_progress=%s",
                    site_id,
                    provider_name,
                    attempt,
                    json.dumps(recent_progress, ensure_ascii=True),
                )

            site_payload = _build_site_payload(
                provider_name=provider_name,
                start_url=start_url,
                raw_payload=final_payload,
            )
            logger.info(
                "TinyFish run completed site_id=%s provider=%s attempt=%s results=%s payload=%s",
                site_id,
                provider_name,
                attempt,
                len(site_payload["results"]),
                json.dumps(site_payload, ensure_ascii=True),
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
                    "attempt": attempt,
                },
            )
            return site_payload
        except Exception as exc:
            message = str(exc)
            logger.exception(
                "TinyFish run failed site_id=%s provider=%s url=%s attempt=%s",
                site_id,
                provider_name,
                start_url,
                attempt,
            )
            failure_category, recommendation = _classify_provider_failure(message)
        finally:
            await client.close()

        if _should_retry_provider_error(message, attempt):
            await _emit(
                event_callback,
                {
                    "type": "agent.retrying",
                    "site_id": site_id,
                    "provider_name": provider_name,
                    "start_url": start_url,
                    "run_id": run_id,
                    "error": message,
                    "attempt": attempt,
                    "max_attempts": MAX_PROVIDER_ATTEMPTS,
                },
            )
            continue

        event_type = "agent.blocked" if failure_category == "bot_protection" else "agent.failed"
        await _emit(
            event_callback,
            {
                "type": event_type,
                "site_id": site_id,
                "provider_name": provider_name,
                "start_url": start_url,
                "run_id": run_id,
                "error": message,
                "failure_category": failure_category,
                "recommendation": recommendation,
                "attempt": attempt,
            },
        )
        return _build_site_payload(provider_name=provider_name, start_url=start_url, error=message)

    return _build_site_payload(
        provider_name=provider_name,
        start_url=start_url,
        error="Provider failed after multiple attempts.",
    )


async def search_travel_deals(
    params: SearchParams,
    *,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Run a travel deal search, optionally discovering providers first."""
    if params.discover_providers and not 1 <= params.provider_limit <= 5:
        raise RuntimeError("--provider-limit must be between 1 and 5 when provider discovery is enabled.")
    logger.info(
        "Search session started category=%s discover_providers=%s",
        params.category,
        params.discover_providers,
    )

    tinyfish_api_key = get_tinyfish_api_key()
    goal = build_goal(
        date_hint=params.date_hint,
        category=params.category,
        currency=params.currency,
        max_results=params.max_results,
    )

    await _emit(
        event_callback,
        {
            "type": "session.started",
            "category": params.category,
            "discover_providers": params.discover_providers,
            "block_marketplace_providers": params.block_marketplace_providers,
        },
    )

    discovery_payload: dict[str, Any] | None = None
    targets: list[dict[str, str]] = []

    if params.discover_providers:
        await _emit(
            event_callback,
            {
                "type": "providers.discovery_started",
                "category": params.category,
                "provider_limit": params.provider_limit,
                "model": params.gemini_model,
                "block_marketplace_providers": params.block_marketplace_providers,
            },
        )
        discovery_payload = await asyncio.to_thread(
            discover_provider_urls,
            api_key=get_gemini_api_key(),
            category=params.category,
            date_hint=params.date_hint,
            max_providers=params.provider_limit,
            model=params.gemini_model,
            block_marketplace_providers=params.block_marketplace_providers,
        )
        targets = [
            {
                "site_id": f"site-{index + 1}",
                "provider_name": provider["provider_name"],
                "url": provider["url"],
            }
            for index, provider in enumerate(discovery_payload["providers"])
        ]
        targets = _filter_and_rank_targets(
            targets,
            block_marketplace_providers=params.block_marketplace_providers,
        )
        targets = [{**target, "site_id": f"site-{index + 1}"} for index, target in enumerate(targets)]
        await _emit(
            event_callback,
            {
                "type": "providers.discovered",
                "providers": [
                    {
                        "provider_name": target["provider_name"],
                        "url": target["url"],
                        "why_relevant": next(
                            (
                                provider["why_relevant"]
                                for provider in discovery_payload["providers"]
                                if provider["url"] == target["url"]
                            ),
                            "Relevant travel provider.",
                        ),
                    }
                    for target in targets
                ],
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
    logger.info(
        "Search session completed category=%s total_results=%s providers=%s",
        params.category,
        len(final_payload["results"]),
        [site["provider_name"] for site in final_payload["site_results"]],
    )
    await _emit(
        event_callback,
        {
            "type": "session.completed",
            "payload": final_payload,
        },
    )
    return final_payload
