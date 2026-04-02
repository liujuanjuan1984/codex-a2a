from __future__ import annotations

from types import SimpleNamespace

import pytest
from a2a.types import TextPart

from codex_a2a.input_mapping import (
    UnsupportedInputError,
    convert_request_parts_to_turn_input,
    extract_text_from_normalized_items,
    guess_image_mime_type_from_url,
    is_text_only_normalized_input,
    map_a2a_message_parts_to_normalized_items,
    summarize_normalized_items,
)


def test_convert_request_parts_to_turn_input_supports_rich_inputs() -> None:
    result = convert_request_parts_to_turn_input(
        {
            "parts": [
                {"type": "text", "text": "Review this."},
                {"type": "image", "bytes": "YWJj", "mimeType": "image/png"},
                {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                {"type": "skill", "name": "skill-creator", "path": "/tmp/SKILL.md"},
            ]
        }
    )

    assert result == [
        {"type": "text", "text": "Review this.", "text_elements": []},
        {"type": "input_image", "image_url": "data:image/png;base64,YWJj"},
        {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
        {"type": "skill", "name": "skill-creator", "path": "/tmp/SKILL.md"},
    ]


@pytest.mark.parametrize(
    ("request_payload", "message"),
    [
        ({}, "request.parts must be an array"),
        ({"parts": [123]}, "request.parts items must be objects"),
        ({"parts": [{"type": "text", "text": 123}]}, "request.parts\\[\\]\\.text must be a string"),
        (
            {"parts": [{"type": "image", "bytes": "YWJj", "mimeType": "text/plain"}]},
            "request.parts\\[\\]\\.mimeType must be an image MIME type when bytes is provided",
        ),
        (
            {"parts": [{"type": "image"}]},
            "request.parts\\[\\]\\.url or request.parts\\[\\]\\.bytes is required",
        ),
        (
            {"parts": [{"type": "mention", "path": "app://demo-app"}]},
            "request.parts\\[\\]\\.name must be a string",
        ),
        (
            {"parts": [{"type": "skill", "name": "skill-creator"}]},
            "request.parts\\[\\]\\.path must be a string",
        ),
        (
            {"parts": [{"type": "audio"}]},
            "request.parts\\[\\]\\.type must be one of: text, image, mention, skill",
        ),
    ],
)
def test_convert_request_parts_to_turn_input_rejects_invalid_shapes(
    request_payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(UnsupportedInputError, match=message):
        convert_request_parts_to_turn_input(request_payload)


def test_map_a2a_message_parts_supports_root_wrappers_and_image_variants() -> None:
    parts = [
        SimpleNamespace(root=TextPart(text="hello")),
        {"file": {"uri": "https://example.com/demo.png", "name": "demo.png"}},
        {"file": {"uri": "data:image/png;base64,AAAA"}},
        {"file": {"bytes": "AAAA", "mimeType": "image/jpeg"}},
        SimpleNamespace(
            root={"data": {"type": "mention", "name": "Demo App", "path": "app://demo"}}
        ),
        {"data": {"type": "skill", "name": "skill-creator", "path": "/tmp/SKILL.md"}},
    ]

    assert map_a2a_message_parts_to_normalized_items(parts) == [
        {"type": "text", "text": "hello"},
        {"type": "image", "url": "https://example.com/demo.png"},
        {"type": "image", "url": "data:image/png;base64,AAAA"},
        {"type": "image", "url": "data:image/jpeg;base64,AAAA"},
        {"type": "mention", "name": "Demo App", "path": "app://demo"},
        {"type": "skill", "name": "skill-creator", "path": "/tmp/SKILL.md"},
    ]


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        (
            [{"file": {"uri": "https://example.com/demo.txt", "name": "demo.txt"}}],
            "Only text, image file, and codex rich input data parts are supported.",
        ),
        (
            [{"data": {"type": "mention", "name": "Demo App"}}],
            "codex rich input data parts require string type, name, and path fields.",
        ),
        (
            [{"data": {"type": "audio", "name": "Clip", "path": "/tmp/clip.wav"}}],
            "Only mention and skill codex rich input data parts are supported.",
        ),
        (
            [SimpleNamespace(root={"unknown": "shape"})],
            "Only text, image file, and codex rich input data parts are supported.",
        ),
    ],
)
def test_map_a2a_message_parts_rejects_unsupported_inputs(
    parts: list[object],
    message: str,
) -> None:
    with pytest.raises(UnsupportedInputError, match=message):
        map_a2a_message_parts_to_normalized_items(parts)


def test_normalized_item_helpers_cover_summary_and_mime_guessing() -> None:
    assert map_a2a_message_parts_to_normalized_items(None) == []

    text_items = [
        {"type": "text", "text": "  hello  "},
        {"type": "text", "text": "\n"},
    ]
    assert extract_text_from_normalized_items(text_items) == "hello"
    assert summarize_normalized_items(text_items) == "hello"
    assert is_text_only_normalized_input([{"type": "text", "text": "hello"}], user_text="hello")
    assert not is_text_only_normalized_input(text_items, user_text="hello")

    assert (
        summarize_normalized_items(
            [
                {"type": "mention", "name": "Demo App"},
                {"type": "skill", "name": "skill-creator"},
            ]
        )
        == "Demo App, skill-creator"
    )
    assert (
        summarize_normalized_items([{"type": "image", "url": "https://example.com/demo.png"}])
        == "Image input"
    )
    assert (
        summarize_normalized_items([{"type": "skill", "path": "/tmp/SKILL.md"}])
        == "Rich input request"
    )

    assert guess_image_mime_type_from_url("data:image/png;base64,AAAA") == "image/png"
    assert guess_image_mime_type_from_url("https://example.com/demo.jpeg") == "image/jpeg"
    assert guess_image_mime_type_from_url("https://example.com/demo") is None
