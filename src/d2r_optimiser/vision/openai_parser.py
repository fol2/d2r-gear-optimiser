"""Screenshot parser backed by the OpenAI API."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from d2r_optimiser.vision.common import (
    SYSTEM_PROMPT,
    ParsedScreenshotItem,
    ScreenshotParserError,
    get_api_key,
    read_image_bytes,
)


def _image_to_data_url(path: Path) -> str:
    """Encode a local image file as a data URL for the OpenAI API."""
    raw, mime_type = read_image_bytes(path)
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_item_screenshot(image_path: Path, *, model: str = "gpt-4o-mini") -> ParsedScreenshotItem:
    """Parse a D2R item screenshot via the OpenAI API."""
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        msg = "OPENAI_API_KEY is not set."
        raise ScreenshotParserError(msg)

    try:
        from openai import OpenAI
    except ImportError as exc:
        msg = "The OpenAI SDK is not installed."
        raise ScreenshotParserError(msg) from exc

    client = OpenAI(api_key=api_key)
    data_url = _image_to_data_url(image_path)
    schema = ParsedScreenshotItem.model_json_schema()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Parse this Diablo II: Resurrected item screenshot "
                                "into the provided JSON schema. Prefer accuracy "
                                "over completeness and record any uncertainty "
                                "in warnings."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "parsed_screenshot_item",
                    "schema": schema,
                    "strict": True,
                },
            },
        )
    except Exception as exc:
        msg = f"OpenAI request failed: {exc}"
        raise ScreenshotParserError(msg) from exc

    choice = response.choices[0]
    message = choice.message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise ScreenshotParserError(f"Model refused the request: {refusal}")

    content = message.content or ""
    if not content:
        raise ScreenshotParserError("OpenAI returned an empty response.")

    try:
        parsed_json = json.loads(content)
    except json.JSONDecodeError as exc:
        msg = "OpenAI returned invalid JSON for the parsed screenshot."
        raise ScreenshotParserError(msg) from exc

    return ParsedScreenshotItem.model_validate(parsed_json)
