from codex_a2a import a2a_proto


def test_a2a_proto_does_not_expose_legacy_aliases_or_module_level_export_list() -> None:
    assert not hasattr(a2a_proto, "__all__")
    for deprecated_alias in (
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
    ):
        assert not hasattr(a2a_proto, deprecated_alias)
