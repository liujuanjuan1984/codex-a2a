from codex_a2a.parts.text import extract_text_from_parts


def test_extract_text_from_parts_concatenates_text_parts() -> None:
    assert extract_text_from_parts(
        [
            {"type": "text", "text": "hello "},
            {"type": "text", "text": "world"},
        ]
    ) == "hello world"


def test_extract_text_from_parts_ignores_non_text_parts() -> None:
    assert extract_text_from_parts(
        [
            {"type": "image", "url": "ignored"},
            {"type": "text", "text": "ok"},
        ]
    ) == "ok"


def test_extract_text_from_parts_returns_empty_string_for_non_list_input() -> None:
    assert extract_text_from_parts({"type": "text", "text": "hello"}) == ""


def test_extract_text_from_parts_strips_outer_whitespace_after_join() -> None:
    assert extract_text_from_parts(
        [
            {"type": "text", "text": "  hello"},
            {"type": "text", "text": " world  "},
        ]
    ) == "hello world"
