from codex_a2a import a2a_proto


def test_a2a_proto_declares_explicit_public_exports() -> None:
    expected_exports = {
        "ROLE_AGENT",
        "ROLE_USER",
        "TASK_STATE_SUBMITTED",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_AUTH_REQUIRED",
        "to_value",
        "to_struct",
        "proto_to_python",
        "proto_clone",
        "proto_with_updates",
        "new_text_part",
        "new_data_part",
        "new_file_url_part",
        "new_file_bytes_part",
        "part_kind",
        "is_text_part",
        "is_data_part",
        "is_file_part",
        "part_text",
        "part_data",
    }

    assert set(a2a_proto.__all__) == expected_exports
