"""Configuration helpers for the travel deals agent."""

from __future__ import annotations

import os
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


def _get_required_key(*keys: str, label: str) -> str:
    """Return the first configured key from env vars or .env."""
    for key in keys:
        value = os.getenv(key, "").strip() or _read_dotenv_value(key)
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
