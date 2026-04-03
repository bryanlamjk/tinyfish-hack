"""Configuration helpers for the travel deals agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_dotenv_value(key: str) -> str:
    """Read a single key from a local .env file if present."""
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return ""

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        if name.strip() != key:
            continue

        return value.strip().strip("'\"")

    return ""


def get_optional_config_value(*keys: str) -> str | None:
    """Return the first configured value from env vars or .env, if any."""
    for key in keys:
        value = os.getenv(key, "").strip() or _read_dotenv_value(key)
        if value:
            return value
    return None


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class LangSmithSettings:
    enabled: bool
    api_key: str | None
    project: str
    endpoint: str | None
    workspace_id: str | None


def get_langsmith_settings() -> LangSmithSettings:
    """Return LangSmith tracing settings from env vars or .env."""
    api_key = get_optional_config_value("LANGSMITH_API_KEY")
    tracing_value = get_optional_config_value("LANGSMITH_TRACING")
    enabled = bool(api_key) and (tracing_value is None or _is_truthy(tracing_value))
    return LangSmithSettings(
        enabled=enabled,
        api_key=api_key,
        project=get_optional_config_value("LANGSMITH_PROJECT") or "tinyfish-travel-deals-agent",
        endpoint=get_optional_config_value("LANGSMITH_ENDPOINT"),
        workspace_id=get_optional_config_value("LANGSMITH_WORKSPACE_ID"),
    )


def configure_langsmith_environment() -> LangSmithSettings:
    """Mirror local LangSmith settings into process env vars for SDK integrations."""
    settings = get_langsmith_settings()
    if settings.api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.api_key
        os.environ["LANGSMITH_TRACING"] = "true" if settings.enabled else "false"
        os.environ["LANGSMITH_PROJECT"] = settings.project
        if settings.endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = settings.endpoint
        if settings.workspace_id:
            os.environ["LANGSMITH_WORKSPACE_ID"] = settings.workspace_id

        try:
            from langsmith import utils as langsmith_utils

            langsmith_utils.get_env_var.cache_clear()
        except Exception:
            pass

    return settings


def _get_required_key(*keys: str, label: str) -> str:
    """Return the first configured key from env vars or .env."""
    value = get_optional_config_value(*keys)
    if value:
        return value

    joined_keys = " or ".join(keys)
    raise RuntimeError(f"Missing {joined_keys}. Add one to .env or export it before running {label}.")


def get_tinyfish_api_key() -> str:
    """Return the Tinyfish API key or raise a helpful error."""
    return _get_required_key("TINYFISH_API_KEY", label="the Tinyfish search")


def get_gemini_api_key() -> str:
    """Return the Gemini API key or raise a helpful error."""
    return _get_required_key("GEMINI_API_KEY", "GOOGLE_API_KEY", label="provider discovery")
