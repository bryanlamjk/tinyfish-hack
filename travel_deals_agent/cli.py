"""CLI for running a Tinyfish travel experience deal search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tinyfish import (
    BrowserProfile,
    CompleteEvent,
    HeartbeatEvent,
    ProgressEvent,
    RunStatus,
    StartedEvent,
    StreamingUrlEvent,
    TinyFish,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Tinyfish agent to find strong travel experience deals."
    )
    parser.add_argument("--destination", required=True, help="City, region, or country to search.")
    parser.add_argument(
        "--site",
        choices=sorted(DEFAULT_SITES),
        default="getyourguide",
        help="Marketplace to start from.",
    )
    parser.add_argument(
        "--category",
        default="guided tours, workshops, and memorable local experiences",
        help="Experience types to prioritize.",
    )
    parser.add_argument(
        "--date-hint",
        default=None,
        help="Optional travel timing, for example 'June 2026' or 'next weekend'.",
    )
    parser.add_argument(
        "--currency",
        default="USD",
        help="Preferred currency label to request in the output.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of results to request from each Tinyfish site run.",
    )
    parser.add_argument(
        "--discover-providers",
        action="store_true",
        help="Use Gemini grounded with Google Search to find 3-5 relevant provider URLs first.",
    )
    parser.add_argument(
        "--provider-limit",
        type=int,
        default=4,
        help="How many provider URLs Gemini should return when discovery is enabled (3-5).",
    )
    parser.add_argument(
        "--gemini-model",
        default=DEFAULT_GEMINI_DISCOVERY_MODEL,
        help="Gemini model to use for provider discovery.",
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Use Tinyfish's stealth browser profile.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to save the raw JSON result.",
    )
    parser.add_argument(
        "--show-sse",
        action="store_true",
        help="Print all Tinyfish SSE events, including timestamps and the live streaming URL.",
    )
    return parser.parse_args()


def _print_result_line(index: int, item: dict[str, Any], *, indent: str = "") -> None:
    title = item.get("title") or "Untitled"
    price = item.get("price") or "n/a"
    original_price = item.get("original_price") or "n/a"
    provider = item.get("provider") or item.get("source_provider") or "unknown provider"
    discount = item.get("discount_text") or "no discount text captured"
    reason = item.get("short_reason_it_is_a_good_deal") or "no rationale provided"
    booking_url = item.get("booking_url") or "n/a"

    print(f"\n{indent}{index}. {title}")
    print(f"{indent}   Provider: {provider}")
    print(f"{indent}   Price: {price} | Original: {original_price}")
    print(f"{indent}   Deal signal: {discount}")
    print(f"{indent}   Why it stands out: {reason}")
    print(f"{indent}   Link: {booking_url}")


def print_pretty_summary(payload: dict[str, Any]) -> None:
    print()
    print(f"Destination: {payload.get('destination')}")
    print(f"Category: {payload.get('searched_category')}")
    print(f"Summary: {payload.get('summary')}")

    provider_discovery = payload.get("provider_discovery") or {}
    discovered_providers = provider_discovery.get("providers") or []
    if discovered_providers:
        print("\nGemini provider discovery:")
        if provider_discovery.get("search_summary"):
            print(f"Summary: {provider_discovery['search_summary']}")

        for index, provider in enumerate(discovered_providers, start=1):
            name = provider.get("provider_name") or "Unknown provider"
            url = provider.get("url") or "n/a"
            reason = provider.get("why_relevant") or "No rationale provided."
            print(f"\n{index}. {name}")
            print(f"   URL: {url}")
            print(f"   Why relevant: {reason}")

    site_results = payload.get("site_results") or []
    if site_results:
        print("\nPer-site results:")
        for site in site_results:
            provider_name = site.get("provider_name") or "Unknown site"
            start_url = site.get("start_url") or "n/a"
            summary = site.get("summary") or "No summary returned."
            results = site.get("results") or []

            print(f"\nSite: {provider_name}")
            print(f"URL: {start_url}")
            print(f"Summary: {summary}")

            if not results:
                print("No deals were returned from this site.")
                continue

            for index, item in enumerate(results, start=1):
                _print_result_line(index, item, indent="   ")
        return

    results = payload.get("results") or []
    if not results:
        print("\nNo deals were returned.")
        return

    print("\nTop results:")
    for index, item in enumerate(results, start=1):
        _print_result_line(index, item)


def _run_tinyfish_site_search(
    *,
    client: TinyFish,
    goal: str,
    url: str,
    label: str,
    profile: BrowserProfile,
    show_sse: bool,
) -> dict[str, Any]:
    prefix = f"[{label}] "
    print(f"\n{prefix}Starting Tinyfish run on {url}")

    final_payload: dict[str, Any] | None = None
    run_id: str | None = None

    with client.agent.stream(goal=goal, url=url, browser_profile=profile) as stream:
        for event in stream:
            if isinstance(event, StartedEvent):
                run_id = event.run_id
                if show_sse:
                    print(f"{prefix}[sse] STARTED {event.timestamp.isoformat()} run_id={run_id}")
                else:
                    print(f"{prefix}Run ID: {run_id}")
            elif isinstance(event, StreamingUrlEvent):
                if show_sse:
                    print(
                        f"{prefix}[sse] STREAMING_URL {event.timestamp.isoformat()} url={event.streaming_url}"
                    )
                else:
                    print(f"{prefix}Live browser stream: {event.streaming_url}")
            elif isinstance(event, ProgressEvent):
                if show_sse:
                    print(f"{prefix}[sse] PROGRESS {event.timestamp.isoformat()} {event.purpose}")
                else:
                    print(f"{prefix}[progress] {event.purpose}")
            elif isinstance(event, HeartbeatEvent):
                if show_sse:
                    print(f"{prefix}[sse] HEARTBEAT {event.timestamp.isoformat()}")
            elif isinstance(event, CompleteEvent):
                run_id = event.run_id
                if show_sse:
                    print(f"{prefix}[sse] COMPLETE {event.timestamp.isoformat()} status={event.status}")
                if event.status != RunStatus.COMPLETED:
                    error_message = event.error.message if event.error else "Unknown Tinyfish error"
                    raise RuntimeError(f"Tinyfish run failed for {label}: {error_message}")
                final_payload = event.result_json

    if final_payload is None and run_id:
        run = client.runs.get(run_id)
        if run.status != RunStatus.COMPLETED:
            if run.error:
                raise RuntimeError(f"Tinyfish run failed after streaming for {label}: {run.error.message}")
            raise RuntimeError(f"Tinyfish run ended with unexpected status for {label}: {run.status}")
        final_payload = run.result

    if final_payload is None:
        raise RuntimeError(
            f"Tinyfish completed for {label} but did not return a final JSON payload. Try a different site, add --stealth, or tighten the prompt."
        )

    normalized_results: list[dict[str, Any]] = []
    for item in final_payload.get("results") or []:
        normalized_item = dict(item)
        normalized_item.setdefault("provider", normalized_item.get("provider") or label)
        normalized_item["source_provider"] = label
        normalized_item["source_url"] = url
        normalized_results.append(normalized_item)

    return {
        "provider_name": label,
        "start_url": url,
        "summary": final_payload.get("summary"),
        "results": normalized_results,
        "raw_payload": final_payload,
    }


def _build_multi_site_payload(
    *,
    destination: str,
    category: str,
    discovery_payload: dict[str, Any],
    site_results: list[dict[str, Any]],
) -> dict[str, Any]:
    flattened_results: list[dict[str, Any]] = []
    public_site_results: list[dict[str, Any]] = []
    successful_sites = 0

    for site in site_results:
        results = site.get("results") or []
        if results:
            successful_sites += 1
        flattened_results.extend(results)
        public_site_results.append(
            {
                "provider_name": site.get("provider_name"),
                "start_url": site.get("start_url"),
                "summary": site.get("summary"),
                "results": results,
            }
        )

    discovery_summary = discovery_payload.get("search_summary") or "Gemini discovered relevant providers."
    if flattened_results:
        summary = (
            f"{discovery_summary} Tinyfish returned {len(flattened_results)} total results "
            f"across {successful_sites} provider sites."
        )
    else:
        summary = f"{discovery_summary} Tinyfish did not return any matching deals from the discovered sites."

    return {
        "destination": destination,
        "searched_category": category,
        "summary": summary,
        "provider_discovery": discovery_payload,
        "site_results": public_site_results,
        "results": flattened_results,
    }


def main() -> None:
    args = parse_args()
    if args.discover_providers and not 3 <= args.provider_limit <= 5:
        raise RuntimeError("--provider-limit must be between 3 and 5 when using --discover-providers.")

    client = TinyFish(api_key=get_tinyfish_api_key())

    goal = build_goal(
        destination=args.destination,
        date_hint=args.date_hint,
        category=args.category,
        currency=args.currency,
        max_results=args.max_results,
    )

    profile = BrowserProfile.STEALTH if args.stealth else BrowserProfile.LITE
    print(f"Looking for deals in {args.destination}")

    discovery_payload: dict[str, Any] | None = None
    targets: list[dict[str, str]]
    if args.discover_providers:
        print("Discovering relevant providers with Gemini grounded by Google Search")
        discovery_payload = discover_provider_urls(
            api_key=get_gemini_api_key(),
            destination=args.destination,
            category=args.category,
            date_hint=args.date_hint,
            max_providers=args.provider_limit,
            model=args.gemini_model,
        )
        targets = [
            {"label": provider["provider_name"], "url": provider["url"]}
            for provider in discovery_payload["providers"]
        ]
    else:
        targets = [{"label": args.site, "url": DEFAULT_SITES[args.site]}]

    site_results = [
        _run_tinyfish_site_search(
            client=client,
            goal=goal,
            url=target["url"],
            label=target["label"],
            profile=profile,
            show_sse=args.show_sse,
        )
        for target in targets
    ]

    if discovery_payload:
        final_payload = _build_multi_site_payload(
            destination=args.destination,
            category=args.category,
            discovery_payload=discovery_payload,
            site_results=site_results,
        )
    else:
        final_payload = site_results[0]["raw_payload"]

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
        print(f"\nSaved raw result to {args.json_out}")

    print_pretty_summary(final_payload)


if __name__ == "__main__":
    main()
