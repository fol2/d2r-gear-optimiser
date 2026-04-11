"""Shared models and helpers for screenshot parsing backends."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from pydantic import BaseModel, Field


class ScreenshotParserError(RuntimeError):
    """Raised when screenshot parsing cannot complete successfully."""


class ParsedScreenshotItem(BaseModel):
    """Structured output for a parsed D2R item screenshot."""

    parse_ok: bool = True
    name: str = ""
    slot: str = ""
    item_type: str = ""
    base: str | None = None
    affixes: dict[str, float] = Field(default_factory=dict)
    socket_count: int = 0
    socket_fill: list[str] = Field(default_factory=list)
    ethereal: bool = False
    notes: str | None = None
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
You parse Diablo II: Resurrected item screenshots into structured inventory data.

Return only fields that can be justified from the screenshot.
Use these canonical slot names when possible:
weapon, shield, helmet, body, gloves, belt, boots, amulet, ring, charm.

Use these item_type values when possible:
unique, set, runeword, rare, magic, crafted, normal.

Rules:
- Assume the screenshot contains exactly one item tooltip.
  If it does not, set parse_ok=false and explain why.
- Extract only numeric affixes that belong on the item itself.
- Use snake_case stat keys such as:
  all_skills, mf, fcr, fhr, dr, strength, dexterity, vitality, life, mana,
  resistance_all, fire_res, cold_res, light_res, poison_res, damage_min,
  damage_max, ed, ias, ds, cb.
- socket_count is the total number of sockets shown on the item.
- socket_fill should list visible rune or jewel names in socket order
  when they are explicitly shown; otherwise leave it empty.
- Set confidence between 0.0 and 1.0.
- If any required field is uncertain, use your best guess,
  add a warning, and reduce confidence.
"""

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def read_image_bytes(path: Path) -> tuple[bytes, str]:
    """Read local image bytes and return ``(bytes, mime_type)``."""
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"

    try:
        return path.read_bytes(), mime_type
    except OSError as exc:
        msg = f"Cannot read screenshot {path}: {exc}"
        raise ScreenshotParserError(msg) from exc


def get_api_key(env_name: str) -> str | None:
    """Read an API key from the environment, falling back to the repo `.env`."""
    value = os.getenv(env_name)
    if value:
        return value

    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    prefix = f"{env_name}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip().strip('"').strip("'")
        if value:
            return value
    return None
