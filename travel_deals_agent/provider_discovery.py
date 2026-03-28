"""Provider discovery powered by Gemini grounded with Google Search."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse, urlunparse

from google import genai
from google.genai.errors import ClientError

from travel_deals_agent.prompts import build_provider_discovery_prompt


DEFAULT_GEMINI_DISCOVERY_MODEL = "gemini-2.5-flash"


def _normalize_url(raw_url: str) -> str | None:
    candidate = raw_url.strip()
    if not candidate:
        return None

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    normalized_path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def _normalize_provider_payload(payload: dict[str, Any], max_providers: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_domains: set[str] = set()

    for provider in payload.get("providers") or []:
        url = _normalize_url(str(provider.get("url") or ""))
        if not url:
            continue

        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        if domain in seen_domains:
            continue

        seen_domains.add(domain)
        normalized.append(
            {
                "provider_name": str(provider.get("provider_name") or domain),
                "url": url,
                "why_relevant": str(provider.get("why_relevant") or "Relevant ticket provider."),
            }
        )

        if len(normalized) >= max_providers:
            break

    if not normalized:
        raise RuntimeError("Gemini provider discovery did not return any usable URLs.")

    return normalized


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def discover_provider_urls(
    *,
    api_key: str,
    destination: str,
    category: str,
    date_hint: str | None,
    max_providers: int,
    model: str,
) -> dict[str, Any]:
    """Discover relevant provider URLs with Gemini grounded by Google Search."""
    client = genai.Client(api_key=api_key)
    prompt = build_provider_discovery_prompt(
        destination=destination,
        category=category,
        date_hint=date_hint,
        max_providers=max_providers,
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "tools": [{"google_search": {}}],
            },
        )
    except ClientError as exc:
        error_code = getattr(exc, "code", None)
        if error_code == 429:
            raise RuntimeError(
                "Gemini provider discovery hit a 429 RESOURCE_EXHAUSTED error. "
                "Gemini rate limits are enforced per Google project, not per API key, "
                "and grounding requests can be billed and limited differently from plain model calls. "
                "Check that the API key belongs to the project you inspected in AI Studio, "
                "that billing is enabled for that project if required, and try the stable "
                f"search-grounding model `{model}` instead of a preview model."
            ) from exc
        raise

    if not response.text:
        raise RuntimeError("Gemini provider discovery returned an empty response.")

    try:
        payload = _extract_json_payload(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini provider discovery returned invalid JSON: {exc}") from exc

    providers = _normalize_provider_payload(payload, max_providers=max_providers)
    return {
        "model": model,
        "search_summary": str(payload.get("search_summary") or ""),
        "providers": providers,
    }
