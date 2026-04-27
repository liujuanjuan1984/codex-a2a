from a2a.types import CancelTaskRequest, GetTaskRequest, Message

from codex_a2a.a2a_proto import proto_to_python
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
    assert proto_to_python(message.metadata) == {"lang": "zh"}
    assert config.return_immediately is True
    assert config.accepted_output_modes == ["text/plain"]
    assert config.history_length == 5


def test_get_task_request_maps_to_query() -> None:
    request = A2AGetTaskRequest(task_id="task-1", history_length=10, metadata={"k": "v"})

    params = request.to_task_query()

    assert isinstance(params, GetTaskRequest)
    assert params.id == "task-1"
    assert params.history_length == 10


def test_cancel_task_request_maps_to_task_id() -> None:
    request = A2ACancelTaskRequest(task_id="task-1", metadata={"reason": "manual"})

    params = request.to_task_id()

    assert isinstance(params, CancelTaskRequest)
    assert params.id == "task-1"
    assert proto_to_python(params.metadata) == {"reason": "manual"}
