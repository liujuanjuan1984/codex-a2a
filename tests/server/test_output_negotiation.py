from __future__ import annotations

from a2a.types import Artifact, Message, Role, TaskArtifactUpdateEvent

from codex_a2a.a2a_proto import (
    new_data_part,
    new_file_url_part,
    new_text_part,
    part_text,
    proto_to_python,
)
from codex_a2a.server.output_negotiation import (
    annotate_output_negotiation_metadata,
    apply_accepted_output_modes,
    extract_accepted_output_modes_from_metadata,
    media_mode_is_accepted,
    merge_output_negotiation_metadata,
)


def test_merge_output_negotiation_metadata_preserves_existing_codex_fields() -> None:
    metadata = merge_output_negotiation_metadata(
        None,
        ["text/plain"],
    )
    merged = merge_output_negotiation_metadata(
        metadata,
        ["application/json"],
    )

    assert extract_accepted_output_modes_from_metadata(merged) == frozenset({"application/json"})
    payload = proto_to_python(merged)
    assert payload["codex"]["output_negotiation"]["accepted_output_modes"] == ["application/json"]


def test_apply_accepted_output_modes_falls_back_file_parts_to_text() -> None:
    event = TaskArtifactUpdateEvent(
        task_id="task-1",
        context_id="ctx-1",
        artifact=Artifact(
            artifact_id="artifact-1",
            parts=[
                new_file_url_part(
                    "https://example.com/demo.png",
                    media_type="image/png",
                    filename="demo.png",
                )
            ],
        ),
        append=False,
        last_chunk=True,
    )

    filtered = apply_accepted_output_modes(event, ["text/plain"])

    assert part_text(filtered.artifact.parts[0]) == (
        "[file omitted: demo.png | image/png | https://example.com/demo.png]"
    )


def test_apply_accepted_output_modes_drops_unaccepted_file_only_artifact() -> None:
    event = TaskArtifactUpdateEvent(
        task_id="task-1",
        context_id="ctx-1",
        artifact=Artifact(
            artifact_id="artifact-1",
            parts=[new_file_url_part("https://example.com/demo.png", media_type="image/png")],
        ),
        append=False,
        last_chunk=True,
    )

    assert apply_accepted_output_modes(event, ["application/json"]) is None


def test_media_mode_is_accepted_supports_wildcards() -> None:
    assert media_mode_is_accepted("image/png", frozenset({"image/*"}))
    assert media_mode_is_accepted("text/plain", frozenset({"*/plain"}))
    assert media_mode_is_accepted("application/json", frozenset({"application/json"}))
    assert media_mode_is_accepted("bad-mode", frozenset({"text/*"})) is False


def test_annotate_output_negotiation_metadata_leaves_unknown_payload_unchanged() -> None:
    payload = {"kind": "raw"}

    assert annotate_output_negotiation_metadata(payload, ["text/plain"]) is payload


def test_apply_accepted_output_modes_keeps_text_messages() -> None:
    message = Message(
        message_id="m-1",
        role=Role.ROLE_AGENT,
        parts=[new_text_part("hello"), new_data_part({"kind": "state"})],
    )

    filtered = apply_accepted_output_modes(message, ["text/plain"])

    assert [part_text(part) for part in filtered.parts] == ["hello", '{"kind":"state"}']
