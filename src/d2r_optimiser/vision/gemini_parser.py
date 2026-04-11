"""Screenshot parser backed by the Gemini API."""

from __future__ import annotations

import json
from pathlib import Path

from d2r_optimiser.vision.common import (
    SYSTEM_PROMPT,
    ParsedScreenshotItem,
    ScreenshotParserError,
    get_api_key,
    read_image_bytes,
)


def parse_item_screenshot(
    image_path: Path,
    *,
    model: str = "gemini-2.0-flash",
) -> ParsedScreenshotItem:
    """Parse a D2R item screenshot via the Gemini API."""
    api_key = get_api_key("GEMINI_API_KEY")
    if not api_key:
        msg = "GEMINI_API_KEY is not set."
        raise ScreenshotParserError(msg)

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        msg = "The Gemini SDK is not installed."
        raise ScreenshotParserError(msg) from exc

    image_bytes, mime_type = read_image_bytes(image_path)
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                SYSTEM_PROMPT,
                (
                    "Parse this Diablo II: Resurrected item screenshot into the "
                    "provided JSON schema. Prefer accuracy over completeness and "
                    "record any uncertainty in warnings."
                ),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedScreenshotItem,
            ),
        )
    except Exception as exc:
        msg = f"Gemini request failed: {exc}"
        raise ScreenshotParserError(msg) from exc

    content = response.text or ""
    if not content:
        raise ScreenshotParserError("Gemini returned an empty response.")

    try:
        parsed_json = json.loads(content)
    except json.JSONDecodeError as exc:
        msg = "Gemini returned invalid JSON for the parsed screenshot."
        raise ScreenshotParserError(msg) from exc

    return ParsedScreenshotItem.model_validate(parsed_json)
