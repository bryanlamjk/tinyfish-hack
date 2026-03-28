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

from travel_deals_agent.config import get_tinyfish_api_key
from travel_deals_agent.prompts import build_goal


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
        help="Maximum number of results to request from the agent.",
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


def print_pretty_summary(payload: dict[str, Any]) -> None:
    print()
    print(f"Destination: {payload.get('destination')}")
    print(f"Category: {payload.get('searched_category')}")
    print(f"Summary: {payload.get('summary')}")

    results = payload.get("results") or []
    if not results:
        print("\nNo deals were returned.")
        return

    print("\nTop results:")
    for index, item in enumerate(results, start=1):
        title = item.get("title") or "Untitled"
        price = item.get("price") or "n/a"
        original_price = item.get("original_price") or "n/a"
        provider = item.get("provider") or "unknown provider"
        discount = item.get("discount_text") or "no discount text captured"
        reason = item.get("short_reason_it_is_a_good_deal") or "no rationale provided"
        booking_url = item.get("booking_url") or "n/a"

        print(f"\n{index}. {title}")
        print(f"   Provider: {provider}")
        print(f"   Price: {price} | Original: {original_price}")
        print(f"   Deal signal: {discount}")
        print(f"   Why it stands out: {reason}")
        print(f"   Link: {booking_url}")


def main() -> None:
    args = parse_args()
    client = TinyFish(api_key=get_tinyfish_api_key())

    goal = build_goal(
        destination=args.destination,
        date_hint=args.date_hint,
        category=args.category,
        currency=args.currency,
        max_results=args.max_results,
    )

    url = DEFAULT_SITES[args.site]
    profile = BrowserProfile.STEALTH if args.stealth else BrowserProfile.LITE

    print(f"Starting Tinyfish run on {url}")
    print(f"Looking for deals in {args.destination}")

    final_payload: dict[str, Any] | None = None
    run_id: str | None = None

    with client.agent.stream(goal=goal, url=url, browser_profile=profile) as stream:
        for event in stream:
            if isinstance(event, StartedEvent):
                run_id = event.run_id
                if args.show_sse:
                    print(f"[sse] STARTED {event.timestamp.isoformat()} run_id={run_id}")
                else:
                    print(f"Run ID: {run_id}")
            elif isinstance(event, StreamingUrlEvent):
                if args.show_sse:
                    print(
                        f"[sse] STREAMING_URL {event.timestamp.isoformat()} url={event.streaming_url}"
                    )
                else:
                    print(f"Live browser stream: {event.streaming_url}")
            elif isinstance(event, ProgressEvent):
                if args.show_sse:
                    print(f"[sse] PROGRESS {event.timestamp.isoformat()} {event.purpose}")
                else:
                    print(f"[progress] {event.purpose}")
            elif isinstance(event, HeartbeatEvent):
                if args.show_sse:
                    print(f"[sse] HEARTBEAT {event.timestamp.isoformat()}")
            elif isinstance(event, CompleteEvent):
                run_id = event.run_id
                if args.show_sse:
                    print(f"[sse] COMPLETE {event.timestamp.isoformat()} status={event.status}")
                if event.status != RunStatus.COMPLETED:
                    error_message = event.error.message if event.error else "Unknown Tinyfish error"
                    raise RuntimeError(f"Tinyfish run failed: {error_message}")
                final_payload = event.result_json

    if final_payload is None and run_id:
        run = client.runs.get(run_id)
        if run.status != RunStatus.COMPLETED:
            if run.error:
                raise RuntimeError(f"Tinyfish run failed after streaming: {run.error.message}")
            raise RuntimeError(f"Tinyfish run ended with unexpected status: {run.status}")
        final_payload = run.result

    if final_payload is None:
        raise RuntimeError(
            "Tinyfish completed but did not return a final JSON payload. Try a different site, add --stealth, or tighten the prompt."
        )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
        print(f"\nSaved raw result to {args.json_out}")

    print_pretty_summary(final_payload)


if __name__ == "__main__":
    main()
