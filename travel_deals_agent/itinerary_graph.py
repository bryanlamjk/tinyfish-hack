"""LangGraph pipeline for the multi-agent itinerary planner."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from google import genai
from langgraph.graph import END, START, StateGraph

from travel_deals_agent.config import get_gemini_api_key
from travel_deals_agent.itinerary_prompts import (
    build_intent_extraction_prompt,
    build_planner_prompt,
    build_synthesis_prompt,
)
from travel_deals_agent.itinerary_schemas import ItineraryState, SearchTask
from travel_deals_agent.provider_discovery import DEFAULT_GEMINI_DISCOVERY_MODEL
from travel_deals_agent.search_service import EventCallback, SearchParams, search_travel_deals


logger = logging.getLogger(__name__)
GEMINI_MODEL = DEFAULT_GEMINI_DISCOVERY_MODEL


async def _emit(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    """Emit an event to the caller if an event callback is present.

    Input: callback -- optional async/sync callable, payload -- event dict.
    Output: None. Side effect: invokes callback with payload.
    """
    if callback is None:
        return
    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, handling markdown fences.

    Input: raw_text -- the raw string response from Gemini.
    Output: A parsed dict. Raises RuntimeError on invalid JSON.
    """
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
            raise RuntimeError(f"Gemini returned invalid JSON: {text[:200]}")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini returned invalid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


def _call_gemini_sync(prompt: str) -> dict[str, Any]:
    """Make a synchronous Gemini call and parse the JSON response.

    Input: prompt -- the full prompt string.
    Output: Parsed JSON dict from the model response.
    """
    client = genai.Client(api_key=get_gemini_api_key())
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")
    return _extract_json_payload(response.text)


async def extract_intent(state: ItineraryState) -> dict[str, Any]:
    """Parse the user query into structured travel requirements via Gemini.

    Input: state containing user_query string.
    Output: dict with "intent" key containing a TravelIntent-shaped dict.
    """
    event_callback = state.get("event_callback")
    await _emit(event_callback, {"type": "intent.extraction_started", "query": state["user_query"]})

    prompt = build_intent_extraction_prompt(state["user_query"])
    intent = await asyncio.to_thread(_call_gemini_sync, prompt)

    logger.info("Extracted travel intent destination=%s duration=%s", intent.get("destination"), intent.get("duration_days"))
    await _emit(event_callback, {"type": "intent.extraction_completed", "intent": intent})
    return {"intent": intent}


async def plan_sub_tasks(state: ItineraryState) -> dict[str, Any]:
    """Generate concrete search queries for each part of the itinerary via Gemini.

    Input: state containing a populated "intent" (TravelIntent).
    Output: dict with "search_tasks" key containing a list of pending SearchTask dicts.
    """
    event_callback = state.get("event_callback")
    intent = state["intent"]
    await _emit(event_callback, {"type": "planner.started", "destination": intent.get("destination")})

    prompt = build_planner_prompt(intent)
    planner_output = await asyncio.to_thread(_call_gemini_sync, prompt)
    raw_tasks = planner_output.get("tasks") or []

    search_tasks: list[SearchTask] = [
        SearchTask(
            task_id=task.get("task_id", f"task-{index}"),
            query=task["query"],
            day=task.get("day"),
            time_of_day=task.get("time_of_day"),
            status="pending",
            results=[],
            summary="",
        )
        for index, task in enumerate(raw_tasks)
    ]

    logger.info("Planner generated %d search tasks", len(search_tasks))
    await _emit(
        event_callback,
        {
            "type": "planner.completed",
            "task_count": len(search_tasks),
            "tasks": [{"task_id": t["task_id"], "query": t["query"], "day": t["day"]} for t in search_tasks],
        },
    )
    return {"search_tasks": search_tasks}


async def execute_searches(state: ItineraryState) -> dict[str, Any]:
    """Run all planned search tasks in parallel via search_travel_deals.

    Input: state containing "search_tasks" (list of pending SearchTask) and "intent" (TravelIntent).
    Output: dict with "search_tasks" key containing the fully updated task list.
    """
    tasks = state["search_tasks"]
    event_callback = state.get("event_callback")
    intent = state["intent"]

    await _emit(event_callback, {"type": "searches.started", "task_count": len(tasks)})

    async def _run_single_task(task: SearchTask) -> SearchTask:
        """Execute one search task and return the updated task dict.

        Input: task -- a pending SearchTask dict.
        Output: The same task dict with status, results, and summary populated.
        """
        task_id = task["task_id"]
        await _emit(event_callback, {"type": "search_task.started", "task_id": task_id, "query": task["query"]})

        try:
            params = SearchParams(
                category=task["query"],
                date_hint=intent.get("travel_dates"),
                currency=intent.get("currency", "USD"),
                discover_providers=True,
                provider_limit=3,
            )
            payload = await search_travel_deals(params, event_callback=event_callback)

            return SearchTask(
                task_id=task_id,
                query=task["query"],
                day=task["day"],
                time_of_day=task["time_of_day"],
                status="completed",
                results=payload.get("results", []),
                summary=payload.get("summary", ""),
            )
        except Exception as exc:
            logger.exception("Search task failed task_id=%s", task_id)
            await _emit(event_callback, {"type": "search_task.failed", "task_id": task_id, "error": str(exc)})
            return SearchTask(
                task_id=task_id,
                query=task["query"],
                day=task["day"],
                time_of_day=task["time_of_day"],
                status="failed",
                results=[],
                summary=f"Search failed: {exc}",
            )

    updated_tasks = await asyncio.gather(*[_run_single_task(t) for t in tasks])

    completed_count = sum(1 for t in updated_tasks if t["status"] == "completed")
    total_results = sum(len(t["results"]) for t in updated_tasks)
    logger.info("All searches finished completed=%d failed=%d total_results=%d", completed_count, len(tasks) - completed_count, total_results)
    await _emit(
        event_callback,
        {"type": "searches.completed", "completed_count": completed_count, "total_results": total_results},
    )
    return {"search_tasks": list(updated_tasks)}


async def synthesize_itinerary(state: ItineraryState) -> dict[str, Any]:
    """Compose search results into a day-by-day itinerary via Gemini.

    Input: state containing "intent" (TravelIntent) and "search_tasks" (completed SearchTask list).
    Output: dict with "itinerary" and "final_response" keys.
    """
    event_callback = state.get("event_callback")
    await _emit(event_callback, {"type": "synthesis.started"})

    prompt = build_synthesis_prompt(intent=state["intent"], search_tasks=state["search_tasks"])
    itinerary_output = await asyncio.to_thread(_call_gemini_sync, prompt)

    days = itinerary_output.get("days", [])
    logger.info("Itinerary synthesized with %d days", len(days))
    await _emit(
        event_callback,
        {
            "type": "synthesis.completed",
            "day_count": len(days),
            "total_estimated_cost": itinerary_output.get("total_estimated_cost"),
        },
    )
    return {"itinerary": days, "final_response": itinerary_output}


def build_itinerary_graph() -> Any:
    """Construct and compile the LangGraph itinerary planner pipeline.

    Input: None.
    Output: A compiled LangGraph StateGraph ready for ainvoke.
    """
    workflow = StateGraph(ItineraryState)
    workflow.add_node("extract_intent", extract_intent)
    workflow.add_node("plan_sub_tasks", plan_sub_tasks)
    workflow.add_node("execute_searches", execute_searches)
    workflow.add_node("synthesize_itinerary", synthesize_itinerary)
    workflow.add_edge(START, "extract_intent")
    workflow.add_edge("extract_intent", "plan_sub_tasks")
    workflow.add_edge("plan_sub_tasks", "execute_searches")
    workflow.add_edge("execute_searches", "synthesize_itinerary")
    workflow.add_edge("synthesize_itinerary", END)
    return workflow.compile()


ITINERARY_GRAPH = build_itinerary_graph()


async def plan_itinerary(
    user_query: str,
    *,
    event_callback: EventCallback | None = None,
) -> dict[str, Any]:
    """Run the full itinerary planner pipeline and return the final response.

    Input:
        user_query -- the raw user request string.
        event_callback -- optional async/sync callable for SSE-style progress events.
    Output: A dict containing the synthesized itinerary (days, total_estimated_cost, summary).
    """
    state = await ITINERARY_GRAPH.ainvoke(
        {
            "user_query": user_query,
            "event_callback": event_callback,
        }
    )
    return state["final_response"]
