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


def get_tinyfish_api_key() -> str:
    """Return the Tinyfish API key or raise a helpful error."""
    api_key = os.getenv("TINYFISH_API_KEY", "").strip() or _read_dotenv_value("TINYFISH_API_KEY")
    if api_key:
        return api_key

    raise RuntimeError(
        "Missing TINYFISH_API_KEY. Add it to .env or export it before running the agent."
    )
