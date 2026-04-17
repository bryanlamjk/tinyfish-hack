"""State and data models for the multi-agent itinerary planner."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from travel_deals_agent.search_service import EventCallback


class TravelIntent(TypedDict):
    """Structured extraction of a user's travel query.

    Input: Raw user query parsed by Gemini.
    Output: Populated by the extract_intent graph node.
    """

    destination: str
    travel_dates: str | None
    duration_days: int | None
    budget_range: str | None
    currency: str
    interests: list[str]
    group_type: str | None
    constraints: list[str]


class SearchTask(TypedDict):
    """A single searchable sub-task that also holds its results.

    The planner creates tasks with status="pending" and empty results.
    The search node fills in results, summary, and flips status to "completed" or "failed".

    Input: Populated by the plan_sub_tasks graph node.
    Output: Updated in-place by the execute_searches graph node.
    """

    task_id: str
    query: str
    day: int | None
    time_of_day: str | None
    status: Literal["pending", "completed", "failed"]
    results: list[dict[str, Any]]
    summary: str


class ItineraryDay(TypedDict):
    """One day of the synthesized itinerary.

    Input: Search results from completed SearchTasks.
    Output: Populated by the synthesize_itinerary graph node.
    """

    day_number: int
    date: str | None
    activities: list[dict[str, Any]]
    estimated_cost: str | None
    notes: NotRequired[str | None]


class ItineraryState(TypedDict, total=False):
    """LangGraph state schema for the itinerary planner pipeline.

    Input: user_query and optional event_callback provided by the caller.
    Output: final_response populated after all nodes complete.
    """

    user_query: str
    event_callback: EventCallback | None
    intent: TravelIntent
    search_tasks: list[SearchTask]
    itinerary: list[ItineraryDay]
    final_response: dict[str, Any]
