from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from typing import Any

from a2a.types import DataPart, FilePart, TextPart


class UnsupportedInputError(ValueError):
    """Raised when an input payload cannot be mapped to Codex turn input."""


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _guess_mime_type(*candidates: Any) -> str | None:
    for candidate in candidates:
        normalized = _optional_string(candidate)
        if normalized:
            guessed, _ = mimetypes.guess_type(normalized)
            if guessed:
                return guessed
    return None


def _resolve_file_payload(part: Any) -> Mapping[str, Any] | None:
    if isinstance(part, FilePart):
        payload = part.file
        if hasattr(payload, "model_dump"):
            dumped = payload.model_dump(by_alias=True, exclude_none=True)
            if isinstance(dumped, Mapping):
                return dumped
        if isinstance(payload, Mapping):
            return payload

    if isinstance(part, Mapping) and "file" in part and isinstance(part["file"], Mapping):
        return part["file"]

    root = getattr(part, "root", None)
    if isinstance(root, FilePart):
        return _resolve_file_payload(root)
    if isinstance(root, Mapping) and "file" in root and isinstance(root["file"], Mapping):
        return root["file"]
    return None


def _resolve_data_payload(part: Any) -> Mapping[str, Any] | None:
    if isinstance(part, DataPart):
        return part.data
    if isinstance(part, Mapping) and "data" in part and isinstance(part["data"], Mapping):
        return part["data"]

    root = getattr(part, "root", None)
    if isinstance(root, DataPart):
        return root.data
    if isinstance(root, Mapping) and "data" in root and isinstance(root["data"], Mapping):
        return root["data"]
    return None


def _resolve_text_payload(part: Any) -> str | None:
    if isinstance(part, TextPart):
        return part.text
    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
        return part["text"]

    root = getattr(part, "root", None)
    if isinstance(root, TextPart):
        return root.text
    if isinstance(root, Mapping) and isinstance(root.get("text"), str):
        return root["text"]
    return None


def _data_url_for_image_bytes(*, encoded_bytes: str, mime_type: str) -> str:
    return f"data:{mime_type};base64,{encoded_bytes}"


def _normalize_prompt_image_part(part: Mapping[str, Any]) -> dict[str, Any]:
    url = _optional_string(part.get("url"))
    if url is None:
        url = _optional_string(part.get("image_url"))
    if url is None:
        url = _optional_string(part.get("imageUrl"))

    encoded_bytes = _optional_string(part.get("bytes"))
    mime_type = _optional_string(part.get("mimeType")) or _optional_string(part.get("mime_type"))
    name = _optional_string(part.get("name"))

    if url:
        return {"type": "image", "url": url}
    if encoded_bytes:
        if not mime_type:
            mime_type = _guess_mime_type(name)
        if not mime_type or not mime_type.startswith("image/"):
            raise UnsupportedInputError(
                "request.parts[].mimeType must be an image MIME type when bytes is provided"
            )
        return {
            "type": "image",
            "url": _data_url_for_image_bytes(encoded_bytes=encoded_bytes, mime_type=mime_type),
        }
    raise UnsupportedInputError("request.parts[].url or request.parts[].bytes is required")


def normalize_prompt_request_parts(parts: Any) -> list[dict[str, Any]]:
    if not isinstance(parts, list):
        raise UnsupportedInputError("request.parts must be an array")

    normalized: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise UnsupportedInputError("request.parts items must be objects")
        part_type = _optional_string(part.get("type"))
        if part_type == "text":
            text = part.get("text")
            if not isinstance(text, str):
                raise UnsupportedInputError("request.parts[].text must be a string")
            normalized.append({"type": "text", "text": text})
            continue
        if part_type == "image":
            normalized.append(_normalize_prompt_image_part(part))
            continue
        if part_type in {"mention", "skill"}:
            name = _optional_string(part.get("name"))
            path = _optional_string(part.get("path"))
            if not name:
                raise UnsupportedInputError("request.parts[].name must be a string")
            if not path:
                raise UnsupportedInputError("request.parts[].path must be a string")
            normalized.append({"type": part_type, "name": name, "path": path})
            continue
        raise UnsupportedInputError(
            "request.parts[].type must be one of: text, image, mention, skill"
        )
    return normalized


def build_turn_input_from_normalized_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for item in items:
        item_type = item.get("type")
        if item_type == "text":
            converted.append({"type": "text", "text": item["text"], "text_elements": []})
            continue
        if item_type == "image":
            converted.append({"type": "input_image", "image_url": item["url"]})
            continue
        if item_type in {"mention", "skill"}:
            converted.append({"type": item_type, "name": item["name"], "path": item["path"]})
            continue
        raise UnsupportedInputError(f"Unsupported normalized input item type: {item_type}")
    return converted


def convert_request_parts_to_turn_input(request: dict[str, Any]) -> list[dict[str, Any]]:
    return build_turn_input_from_normalized_items(
        normalize_prompt_request_parts(request.get("parts"))
    )


def map_a2a_message_parts_to_normalized_items(parts: Any) -> list[dict[str, Any]]:
    if not isinstance(parts, list):
        return []

    normalized: list[dict[str, Any]] = []
    for part in parts:
        text = _resolve_text_payload(part)
        if isinstance(text, str):
            normalized.append({"type": "text", "text": text})
            continue

        file_payload = _resolve_file_payload(part)
        if file_payload is not None:
            file_uri = _optional_string(file_payload.get("uri"))
            file_name = _optional_string(file_payload.get("name"))
            mime_type = _optional_string(file_payload.get("mimeType")) or _guess_mime_type(
                file_name,
                file_uri,
            )
            if file_uri:
                if mime_type and mime_type.startswith("image/"):
                    normalized.append({"type": "image", "url": file_uri})
                    continue
                if file_uri.startswith("data:image/"):
                    normalized.append({"type": "image", "url": file_uri})
                    continue
            file_bytes = _optional_string(file_payload.get("bytes"))
            if file_bytes and mime_type and mime_type.startswith("image/"):
                normalized.append(
                    {
                        "type": "image",
                        "url": _data_url_for_image_bytes(
                            encoded_bytes=file_bytes,
                            mime_type=mime_type,
                        ),
                    }
                )
                continue
            raise UnsupportedInputError(
                "Only text, image file, and codex rich input data parts are supported."
            )

        data_payload = _resolve_data_payload(part)
        if data_payload is not None:
            item_type = _optional_string(data_payload.get("type"))
            if item_type in {"mention", "skill"}:
                name = _optional_string(data_payload.get("name"))
                path = _optional_string(data_payload.get("path"))
                if not name or not path:
                    raise UnsupportedInputError(
                        "codex rich input data parts require string type, name, and path fields."
                    )
                normalized.append({"type": item_type, "name": name, "path": path})
                continue
            raise UnsupportedInputError(
                "Only mention and skill codex rich input data parts are supported."
            )

        raise UnsupportedInputError(
            "Only text, image file, and codex rich input data parts are supported."
        )

    return normalized


def extract_text_from_normalized_items(items: list[dict[str, Any]]) -> str:
    texts = [
        text.strip()
        for item in items
        if item.get("type") == "text" and isinstance(item.get("text"), str)
        for text in [item["text"]]
        if text.strip()
    ]
    return "\n".join(texts)


def summarize_normalized_items(items: list[dict[str, Any]]) -> str:
    text = extract_text_from_normalized_items(items)
    if text:
        return text

    mentions = [
        item["name"]
        for item in items
        if item.get("type") in {"mention", "skill"} and isinstance(item.get("name"), str)
    ]
    if mentions:
        return ", ".join(mentions)

    if any(item.get("type") == "image" for item in items):
        return "Image input"

    return "Rich input request"


def is_text_only_normalized_input(items: list[dict[str, Any]], *, user_text: str) -> bool:
    return len(items) == 1 and items[0].get("type") == "text" and items[0].get("text") == user_text
