"""Routing layer for screenshot parsing backends."""

from __future__ import annotations

import os
from pathlib import Path

from d2r_optimiser.vision.common import ParsedScreenshotItem, ScreenshotParserError

SUPPORTED_PROVIDERS = ("gemini", "openai")


def resolve_provider(provider: str | None = None) -> str:
    """Resolve the effective screenshot parsing provider."""
    candidate = (provider or os.getenv("D2R_SCREENSHOT_PROVIDER", "auto")).strip().lower()

    if candidate == "auto":
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        msg = "No screenshot provider configured. Set GEMINI_API_KEY or OPENAI_API_KEY."
        raise ScreenshotParserError(msg)

    if candidate not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        msg = f"Unsupported screenshot provider {candidate!r}. Use one of: {supported}, auto."
        raise ScreenshotParserError(msg)

    return candidate


def parse_item_screenshot(
    image_path: Path,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ParsedScreenshotItem:
    """Parse an item screenshot using the requested provider."""
    resolved = resolve_provider(provider)

    if resolved == "gemini":
        from d2r_optimiser.vision.gemini_parser import parse_item_screenshot as _parse_gemini

        return _parse_gemini(image_path, model=model or "gemini-2.0-flash")

    from d2r_optimiser.vision.openai_parser import parse_item_screenshot as _parse_openai

    return _parse_openai(image_path, model=model or "gpt-4o-mini")
