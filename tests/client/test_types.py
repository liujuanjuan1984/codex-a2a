from a2a.types import Message, TaskIdParams, TaskQueryParams

from codex_a2a.client.types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


def test_send_request_builds_a2a_message() -> None:
    request = A2ASendRequest(
        text="hello world",
        context_id="ctx-1",
        metadata={"lang": "zh"},
        accepted_output_modes=["text/plain"],
        history_length=5,
        blocking=False,
    )

    message = request.to_message()
    config = request.to_send_configuration()

    assert isinstance(message, Message)
    assert message.context_id == "ctx-1"
    assert message.metadata == {"lang": "zh"}
    assert config.blocking is False
    assert config.accepted_output_modes == ["text/plain"]
    assert config.history_length == 5


def test_get_task_request_maps_to_query() -> None:
    request = A2AGetTaskRequest(task_id="task-1", history_length=10, metadata={"k": "v"})

    params = request.to_task_query()

    assert isinstance(params, TaskQueryParams)
    assert params.id == "task-1"
    assert params.history_length == 10
    assert params.metadata == {"k": "v"}


def test_cancel_task_request_maps_to_task_id() -> None:
    request = A2ACancelTaskRequest(task_id="task-1", metadata={"reason": "manual"})

    params = request.to_task_id()

    assert isinstance(params, TaskIdParams)
    assert params.id == "task-1"
    assert params.metadata == {"reason": "manual"}
