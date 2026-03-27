from codex_a2a.execution.stream_interrupts import extract_interrupt_asked_event


def test_extract_permission_interrupt_keeps_explicit_display_message_only() -> None:
    event = {
        "type": "permission.asked",
        "properties": {
            "id": "perm-1",
            "display_message": "Agent wants to read the environment file.",
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "perm-1",
        "interrupt_type": "permission",
        "details": {
            "permission": None,
            "patterns": [],
            "always": [],
            "display_message": "Agent wants to read the environment file.",
        },
    }


def test_extract_question_interrupt_keeps_explicit_display_message_only() -> None:
    event = {
        "type": "question.asked",
        "properties": {
            "id": "q-1",
            "questions": [{"id": "q1", "question": "Proceed with deployment?"}],
            "display_message": "Please confirm how the agent should continue.",
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "q-1",
        "interrupt_type": "question",
        "details": {
            "questions": [{"id": "q1", "question": "Proceed with deployment?"}],
            "display_message": "Please confirm how the agent should continue.",
        },
    }


def test_extract_permission_interrupt_promotes_reason_and_parsed_paths() -> None:
    event = {
        "type": "permission.asked",
        "properties": {
            "id": "perm-2",
            "metadata": {
                "raw": {
                    "reason": "The command needs confirmation.",
                    "parsedCmd": [{"path": "/repo/.env"}],
                }
            },
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "perm-2",
        "interrupt_type": "permission",
        "details": {
            "permission": None,
            "patterns": ["/repo/.env"],
            "always": [],
            "display_message": "The command needs confirmation.",
        },
    }


def test_extract_question_interrupt_promotes_nested_questions() -> None:
    event = {
        "type": "question.asked",
        "properties": {
            "id": "q-2",
            "metadata": {"method": "item/tool/requestUserInput"},
            "context": {"questions": [{"id": "q1", "question": "Proceed with deployment?"}]},
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "q-2",
        "interrupt_type": "question",
        "details": {"questions": [{"id": "q1", "question": "Proceed with deployment?"}]},
    }


def test_extract_permissions_interrupt_keeps_permissions_and_reason() -> None:
    event = {
        "type": "permissions.asked",
        "properties": {
            "id": "perm-v2-1",
            "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
            "display_message": "Select the writable workspace root.",
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "perm-v2-1",
        "interrupt_type": "permissions",
        "details": {
            "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
            "display_message": "Select the writable workspace root.",
        },
    }


def test_extract_elicitation_interrupt_promotes_form_details() -> None:
    event = {
        "type": "elicitation.asked",
        "properties": {
            "id": "eli-1",
            "server_name": "drive",
            "mode": "form",
            "requested_schema": {"type": "object", "properties": {"folder": {"type": "string"}}},
            "display_message": "Select the target folder.",
        },
    }

    assert extract_interrupt_asked_event(event) == {
        "request_id": "eli-1",
        "interrupt_type": "elicitation",
        "details": {
            "server_name": "drive",
            "mode": "form",
            "requested_schema": {"type": "object", "properties": {"folder": {"type": "string"}}},
            "url": None,
            "elicitation_id": None,
            "display_message": "Select the target folder.",
        },
    }
