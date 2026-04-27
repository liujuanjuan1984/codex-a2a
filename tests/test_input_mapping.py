from __future__ import annotations

import pytest

from codex_a2a.a2a_proto import (
    new_data_part,
    new_file_bytes_part,
    new_file_url_part,
    new_text_part,
)
from codex_a2a.input_mapping import (
    UnsupportedInputError,
    convert_request_parts_to_turn_input,
    extract_text_from_normalized_items,
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
        (
            {"parts": [{"type": "image", "image_url": "https://example.com/demo.png"}]},
            "request.parts\\[\\]\\.url or request.parts\\[\\]\\.bytes is required",
        ),
        (
            {"parts": [{"type": "image", "bytes": "YWJj", "mime_type": "image/png"}]},
            "request.parts\\[\\]\\.mimeType must be an image MIME type when bytes is provided",
        ),
    ],
)
def test_convert_request_parts_to_turn_input_rejects_legacy_image_aliases(
    request_payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(UnsupportedInputError, match=message):
        convert_request_parts_to_turn_input(request_payload)


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


def test_map_a2a_message_parts_supports_v1_parts_and_image_variants() -> None:
    parts = [
        new_text_part("hello"),
        new_file_url_part(
            "https://example.com/demo.png",
            media_type="image/png",
            filename="demo.png",
        ),
        new_file_url_part("data:image/png;base64,AAAA"),
        new_file_bytes_part(b"\x00\x00\x00", media_type="image/jpeg"),
        new_data_part({"type": "mention", "name": "Demo App", "path": "app://demo"}),
        new_data_part({"type": "skill", "name": "skill-creator", "path": "/tmp/SKILL.md"}),
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
            [new_file_url_part("https://example.com/demo.txt", filename="demo.txt")],
            "Only text, image file, and codex rich input data parts are supported.",
        ),
        (
            [new_data_part({"type": "mention", "name": "Demo App"})],
            "codex rich input data parts require string type, name, and path fields.",
        ),
        (
            [new_data_part({"type": "audio", "name": "Clip", "path": "/tmp/clip.wav"})],
            "Only mention and skill codex rich input data parts are supported.",
        ),
        (
            [{"unknown": "shape"}],
            "A2A message parts must be protobuf Part values.",
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
