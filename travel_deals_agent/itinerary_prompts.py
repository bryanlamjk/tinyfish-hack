"""Prompt builders for the multi-agent itinerary planner."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


def build_intent_extraction_prompt(user_query: str) -> str:
    """Build a prompt that extracts structured travel intent from a free-form query.

    Input: user_query -- the raw user request (e.g. "5 day Kyoto trip for a couple").
    Output: A prompt string for Gemini that requests JSON matching TravelIntent.
    """
    return dedent(
        f"""
        You are a travel intent parser. Extract structured travel requirements
        from the user query below. Infer reasonable defaults when information is
        missing -- for example, default currency to USD, set duration to 3 days
        when unspecified, and mark dates as null when the user is flexible.

        User query: {user_query}

        Rules:
        1. "interests" should be a list of 1-5 short activity themes extracted
           from the query (e.g. "culture", "food", "adventure", "nightlife").
           If the query does not mention interests, infer sensible defaults from
           the destination.
        2. "group_type" should be a short label like "solo", "couple",
           "family with kids", "friends group", or null if unknown.
        3. "constraints" should capture explicit restrictions such as
           "wheelchair accessible", "vegetarian", "budget-friendly". Return an
           empty list when none are mentioned.
        4. "budget_range" should be a human-readable string like "$1000-2000"
           or null if the user did not mention budget.
        5. "travel_dates" should be a human-readable string like "June 2026"
           or "Dec 15-20 2026" or null if flexible.
        6. "duration_days" should be an integer. Infer from the date range if
           both start and end dates are given. Default to 3 if unspecified.
        7. Return JSON only with no markdown fences.

        Return JSON with this exact structure:
        {{
          "destination": "string",
          "travel_dates": "string or null",
          "duration_days": 3,
          "budget_range": "string or null",
          "currency": "USD",
          "interests": ["string"],
          "group_type": "string or null",
          "constraints": []
        }}
        """
    ).strip()


def build_planner_prompt(intent: dict[str, Any]) -> str:
    """Build a prompt that decomposes a travel intent into searchable sub-tasks.

    Input: intent -- a dict matching the TravelIntent schema.
    Output: A prompt string for Gemini that requests a JSON list of SearchTask objects.
    """
    destination = intent.get("destination", "unknown destination")
    duration_days = intent.get("duration_days") or 3
    travel_dates = intent.get("travel_dates") or "flexible dates"
    interests = ", ".join(intent.get("interests") or ["general sightseeing"])
    group_type = intent.get("group_type") or "not specified"
    budget_range = intent.get("budget_range") or "not specified"
    constraints = ", ".join(intent.get("constraints") or []) or "none"

    return dedent(
        f"""
        You are a travel activity planner. Given the structured travel intent
        below, generate a list of specific, searchable experience queries that
        a ticket search engine can use to find bookable activities.

        Destination: {destination}
        Duration: {duration_days} days
        Travel dates: {travel_dates}
        Interests: {interests}
        Group type: {group_type}
        Budget: {budget_range}
        Constraints: {constraints}

        Rules:
        1. Generate 1-3 experience searches per day. Assign each a day number
           and a time_of_day slot (morning, afternoon, or evening).
        2. Each query must be specific and include the destination name and the
           activity type (e.g. "guided temple tour in Kyoto", not just "temple").
        3. Distribute the user's interests across the days so the itinerary
           feels varied rather than repetitive.
        4. Only generate experience and activity searches. Do NOT generate
           accommodation, flight, or transport tasks -- those are handled by
           separate agents in the future.
        5. Use the task_id format "d{{day}}-{{time_of_day}}" (e.g. "d1-morning").
        6. Return JSON only with no markdown fences.

        Return JSON with this exact structure:
        {{
          "tasks": [
            {{
              "task_id": "d1-morning",
              "query": "specific searchable experience query",
              "day": 1,
              "time_of_day": "morning"
            }}
          ]
        }}
        """
    ).strip()


def build_synthesis_prompt(
    intent: dict[str, Any],
    search_tasks: list[dict[str, Any]],
) -> str:
    """Build a prompt that synthesizes search results into a day-by-day itinerary.

    Input:
        intent -- a dict matching the TravelIntent schema.
        search_tasks -- a list of completed SearchTask dicts, each containing
                        query context and search results.
    Output: A prompt string for Gemini that requests a structured itinerary JSON.
    """
    destination = intent.get("destination", "unknown destination")
    duration_days = intent.get("duration_days") or 3
    travel_dates = intent.get("travel_dates") or "flexible dates"
    currency = intent.get("currency", "USD")
    budget_range = intent.get("budget_range") or "not specified"
    group_type = intent.get("group_type") or "not specified"
    constraints = ", ".join(intent.get("constraints") or []) or "none"

    tasks_summary = json.dumps(search_tasks, indent=2, ensure_ascii=False)

    return dedent(
        f"""
        You are a travel itinerary composer. Given the travel intent and the
        search results below, create a polished day-by-day itinerary.

        Destination: {destination}
        Duration: {duration_days} days
        Travel dates: {travel_dates}
        Currency: {currency}
        Budget: {budget_range}
        Group type: {group_type}
        Constraints: {constraints}

        Search results (each task contains a query, the day/time it was planned
        for, and the actual bookable options found):
        {tasks_summary}

        Rules:
        1. For each day, pick the best 1-3 activities from the search results
           for that day. Prefer options with visible pricing, good ratings, and
           high relevance to the original query.
        2. Order activities logically within each day (morning -> afternoon ->
           evening). Consider travel time between locations.
        3. Include the booking_url and price from the actual search results --
           do not fabricate URLs or prices.
        4. If a search task returned no results or failed, note it and suggest
           the user search manually for that activity.
        5. Calculate an estimated cost per day and a total estimated cost based
           on the selected activities. Use {currency} as the display currency.
        6. Add brief practical notes where useful (e.g. "book in advance",
           "arrive early to avoid crowds", "near the previous location").
        7. If the search returned more interesting options than slots available,
           mention them as alternatives in the day's notes.
        8. Return JSON only with no markdown fences.

        Return JSON with this exact structure:
        {{
          "days": [
            {{
              "day_number": 1,
              "date": "date string or null",
              "activities": [
                {{
                  "time_of_day": "morning",
                  "title": "Activity title from search results",
                  "provider": "Provider name",
                  "price": "$XX.XX",
                  "currency": "{currency}",
                  "booking_url": "https://...",
                  "reason_selected": "Brief reason this was the best option",
                  "notes": "Practical tip or null"
                }}
              ],
              "estimated_cost": "$XX.XX",
              "notes": "Day-level notes or null"
            }}
          ],
          "total_estimated_cost": "$XXX.XX",
          "summary": "2-3 sentence overview of the full itinerary."
        }}
        """
    ).strip()
