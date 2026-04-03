"""LangSmith tracing helpers for the travel deals agent."""

from __future__ import annotations

from functools import lru_cache

from langsmith import Client

from travel_deals_agent.config import LangSmithSettings, configure_langsmith_environment


@lru_cache(maxsize=1)
def get_langsmith_client() -> Client | None:
    """Return a LangSmith client when tracing is configured."""
    settings = configure_langsmith_environment()
    if not settings.enabled or not settings.api_key:
        return None

    client_kwargs: dict[str, str] = {
        "api_key": settings.api_key,
    }
    if settings.endpoint:
        client_kwargs["api_url"] = settings.endpoint
    if settings.workspace_id:
        client_kwargs["workspace_id"] = settings.workspace_id
    return Client(**client_kwargs)


def get_tracing_context_kwargs(
    *,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a tracing_context kwargs payload for the current environment."""
    settings: LangSmithSettings = configure_langsmith_environment()
    client = get_langsmith_client()
    return {
        "enabled": settings.enabled and client is not None,
        "client": client,
        "project_name": settings.project,
        "tags": tags or [],
        "metadata": metadata or {},
    }
