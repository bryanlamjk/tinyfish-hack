"""Top-level route selection for the LangGraph orchestrator."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from urllib.parse import urlparse

from google import genai
from langsmith import traceable

from travel_deals_agent.config import get_optional_config_value
from travel_deals_agent.prompts import build_router_prompt
from travel_deals_agent.provider_discovery import DEFAULT_GEMINI_DISCOVERY_MODEL
from travel_deals_agent.search_service import DEFAULT_SITES, SearchParams
from travel_deals_agent.orchestrator_schemas import RouteDecision


logger = logging.getLogger(__name__)
DEFAULT_ROUTER_MODEL = DEFAULT_GEMINI_DISCOVERY_MODEL
KNOWN_PROVIDER_URLS = {
    **DEFAULT_SITES,
    "booking": "https://www.booking.com",
    "booking.com": "https://www.booking.com",
    "expedia": "https://www.expedia.com",
    "expedia.com": "https://www.expedia.com",
    "headout": "https://www.headout.com",
    "headout.com": "https://www.headout.com",
    "kkday": "https://www.kkday.com",
    "kkday.com": "https://www.kkday.com",
    "pelago": "https://www.pelago.com",
    "pelago.co": "https://www.pelago.co",
    "tiqets": "https://www.tiqets.com",
    "tiqets.com": "https://www.tiqets.com",
    "trip": "https://www.trip.com",
    "trip.com": "https://www.trip.com",
}


# Parse a JSON object from router model output, including fenced JSON.
def _extract_json_payload(raw_text: str) -> dict[str, str]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])

    return payload if isinstance(payload, dict) else {}


# Normalize a provider URL into a consistent absolute URL.
def _normalize_provider_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    candidate = raw_url.strip().rstrip(".,)")
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = parsed.path or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# Derive a readable provider name from a provider URL.
def _provider_name_from_url(provider_url: str) -> str:
    domain = urlparse(provider_url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


# Look for an explicit provider URL or domain mentioned in the query.
def _extract_explicit_provider_url(query: str) -> str | None:
    url_match = re.search(r"https?://[^\s)]+", query, flags=re.IGNORECASE)
    if url_match:
        return _normalize_provider_url(url_match.group(0))

    domain_match = re.search(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", query, flags=re.IGNORECASE)
    if domain_match:
        return _normalize_provider_url(domain_match.group(0))

    lowered = query.lower()
    for alias, provider_url in KNOWN_PROVIDER_URLS.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return provider_url

    return None


# Decide the route using simple local rules when the model is unavailable.
def _heuristic_route(params: SearchParams) -> RouteDecision:
    if not params.discover_providers:
        provider_url = DEFAULT_SITES.get(params.site)
        return RouteDecision(
            route="direct_ticket_scrape",
            reasoning_summary="Provider discovery was disabled, so the app will use the selected site directly.",
            rewritten_query=params.category.strip(),
            provider_name=params.site,
            provider_url=provider_url,
        )

    explicit_url = _extract_explicit_provider_url(params.category)
    if explicit_url:
        return RouteDecision(
            route="direct_ticket_scrape",
            reasoning_summary="The query already names a provider or website, so the scraper can go there directly.",
            rewritten_query=params.category.strip(),
            provider_name=_provider_name_from_url(explicit_url),
            provider_url=explicit_url,
        )

    return RouteDecision(
        route="search_then_scrape",
        reasoning_summary="The query asks for tickets but does not specify a provider, so the app should search the web first.",
        rewritten_query=params.category.strip(),
        provider_name=None,
        provider_url=None,
    )


# Strip non-serializable inputs before sending router traces to LangSmith.
def _process_route_inputs(inputs: dict[str, object]) -> dict[str, object]:
    params = inputs.get("params")
    if params is not None and is_dataclass(params):
        return {"params": asdict(params)}
    return inputs


# Classify a request into direct scraping or web-search-then-scrape.
@traceable(name="route_query", run_type="chain", process_inputs=_process_route_inputs)
def route_query(params: SearchParams) -> RouteDecision:
    """Classify the query into a tool path for the orchestrator."""
    api_key = get_optional_config_value("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not api_key:
        return _heuristic_route(params)

    prompt = build_router_prompt(
        category=params.category,
        date_hint=params.date_hint,
        site=params.site if not params.discover_providers else None,
        discover_providers=params.discover_providers,
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=DEFAULT_ROUTER_MODEL,
            contents=prompt,
        )
        if not response.text:
            raise RuntimeError("Router model returned an empty response.")
        payload = _extract_json_payload(response.text)
        route = RouteDecision.model_validate(payload)
    except Exception as exc:
        logger.warning("Falling back to heuristic router after model error: %s", exc)
        route = _heuristic_route(params)

    explicit_url = route.provider_url or _extract_explicit_provider_url(params.category)
    normalized_provider_url = _normalize_provider_url(explicit_url)
    if normalized_provider_url:
        provider_name = route.provider_name or _provider_name_from_url(normalized_provider_url)
        return RouteDecision(
            route="direct_ticket_scrape",
            reasoning_summary=route.reasoning_summary,
            rewritten_query=route.rewritten_query.strip() or params.category.strip(),
            provider_name=provider_name,
            provider_url=normalized_provider_url,
        )

    if route.route == "direct_ticket_scrape" and not normalized_provider_url and not params.discover_providers:
        provider_url = DEFAULT_SITES.get(params.site)
        return RouteDecision(
            route="direct_ticket_scrape",
            reasoning_summary=route.reasoning_summary,
            rewritten_query=route.rewritten_query.strip() or params.category.strip(),
            provider_name=route.provider_name or params.site,
            provider_url=provider_url,
        )

    return RouteDecision(
        route="search_then_scrape",
        reasoning_summary=route.reasoning_summary,
        rewritten_query=route.rewritten_query.strip() or params.category.strip(),
        provider_name=None,
        provider_url=None,
    )
