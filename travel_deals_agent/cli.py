"""CLI for running concurrent TinyFish travel deal searches."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from travel_deals_agent.provider_discovery import DEFAULT_GEMINI_DISCOVERY_MODEL
from travel_deals_agent.search_service import DEFAULT_SITES, SearchParams, search_travel_deals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TinyFish travel deal searches, optionally across multiple providers in parallel."
    )
    parser.add_argument("--destination", required=True, help="City, region, or country to search.")
    parser.add_argument(
        "--site",
        choices=sorted(DEFAULT_SITES),
        default="getyourguide",
        help="Marketplace to start from when provider discovery is off.",
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
        help="Use Gemini grounded with Google Search to discover provider URLs before running TinyFish.",
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
        help="Print detailed live events while concurrent runs are in progress.",
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
            summary = site.get("summary") or site.get("error") or "No summary returned."
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

async def _run_search(args: argparse.Namespace) -> dict[str, Any]:
    async def on_event(event: dict[str, Any]) -> None:
        event_type = event.get("type")
        label = event.get("provider_name") or event.get("site_id") or "search"
        prefix = f"[{label}] "

        if event_type == "providers.discovery_started":
            print("Discovering relevant providers with Gemini grounded by Google Search")
        elif event_type == "providers.discovered":
            providers = event.get("providers") or []
            print(f"Gemini discovered {len(providers)} providers.")
        elif event_type == "agent.started":
            print(f"{prefix}Run ID: {event.get('run_id')}")
        elif event_type == "agent.streaming_url":
            if args.show_sse:
                print(f"{prefix}[stream] {event.get('streaming_url')}")
        elif event_type == "agent.progress":
            print(f"{prefix}[progress] {event.get('purpose')}")
        elif event_type == "agent.completed":
            print(f"{prefix}Completed with {event.get('result_count', 0)} results.")
        elif event_type == "agent.failed":
            print(f"{prefix}Failed: {event.get('error')}")
        elif event_type == "session.failed":
            print(f"[session] Failed: {event.get('error')}")
        elif args.show_sse:
            print(json.dumps(event))

    params = SearchParams(
        destination=args.destination,
        category=args.category,
        date_hint=args.date_hint,
        currency=args.currency,
        max_results=args.max_results,
        discover_providers=args.discover_providers,
        provider_limit=args.provider_limit,
        gemini_model=args.gemini_model,
        stealth=args.stealth,
        site=args.site,
    )
    return await search_travel_deals(params, event_callback=on_event)


def main() -> None:
    args = parse_args()
    final_payload = asyncio.run(_run_search(args))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
        print(f"\nSaved raw result to {args.json_out}")

    print_pretty_summary(final_payload)


if __name__ == "__main__":
    main()
