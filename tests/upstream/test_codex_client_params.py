import asyncio
import json
import logging
import os
import shutil
import time
from unittest.mock import MagicMock

import pytest

from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.logging_context import bind_correlation_id
from codex_a2a.upstream.client import (
    CodexClient,
    CodexStartupPrerequisiteError,
    InterruptRequestBinding,
    _PendingInterruptRequest,
    _PendingRpcRequest,
)
from tests.support.fixtures import (
    replay_codex_jsonrpc_line_fixture,
    replay_codex_notification_fixture,
)
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_list_calls_use_expected_rpc_params() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        if method == "thread/list":
            return {"data": [{"id": "thr-1", "preview": "hello"}]}
        if method == "thread/read":
            return {"thread": {"turns": []}}
        return {}

    client._rpc_request = fake_rpc_request

    sessions = await client.list_sessions(params={"directory": "/evil", "limit": 1, "roots": True})
    assert sessions == [
        {"id": "thr-1", "title": "hello", "raw": {"id": "thr-1", "preview": "hello"}}
    ]

    messages = await client.list_messages("thr-1", params={"directory": "/evil", "limit": 10})
    assert messages == []

    assert seen[0] == ("thread/list", {"limit": 1})
    assert seen[1] == ("thread/read", {"threadId": "thr-1", "includeTurns": True})


@pytest.mark.asyncio
async def test_create_session_uses_model_id_override_not_startup_default() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
            codex_model="gpt-5.1-codex",
            codex_model_id="gpt-5.2-codex",
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"thread": {"id": "thr-1"}}

    client._rpc_request = fake_rpc_request

    session_id = await client.create_session(directory="/safe/project")

    assert session_id == "thr-1"
    assert seen == [
        (
            "thread/start",
            {
                "model": "gpt-5.2-codex",
                "cwd": "/safe/project",
            },
        )
    ]


@pytest.mark.asyncio
async def test_create_session_request_execution_options_override_default_model() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
            codex_model_id="gpt-default",
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"thread": {"id": "thr-override"}}

    client._rpc_request = fake_rpc_request

    session_id = await client.create_session(
        directory="/safe/project",
        execution_options=RequestExecutionOptions(
            model="gpt-5.2-codex",
            personality="pragmatic",
        ),
    )

    assert session_id == "thr-override"
    assert seen == [
        (
            "thread/start",
            {
                "cwd": "/safe/project",
                "model": "gpt-5.2-codex",
                "personality": "pragmatic",
            },
        )
    ]


@pytest.mark.asyncio
async def test_create_session_relies_on_startup_default_model_when_model_id_unset() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
            codex_model="gpt-5.1-codex",
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"thread": {"id": "thr-2"}}

    client._rpc_request = fake_rpc_request

    session_id = await client.create_session()

    assert session_id == "thr-2"
    assert seen == [("thread/start", {"cwd": "/safe"})]


@pytest.mark.asyncio
async def test_create_session_passes_session_title_to_thread_start_name() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"thread": {"id": "thr-3"}}

    client._rpc_request = fake_rpc_request

    session_id = await client.create_session(title="Demo Session")

    assert session_id == "thr-3"
    assert seen == [("thread/start", {"name": "Demo Session", "cwd": "/safe"})]


@pytest.mark.asyncio
async def test_list_messages_applies_limit_locally_after_mapping() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    async def fake_rpc_request(method: str, params: dict | None = None):
        assert method == "thread/read"
        assert params == {"threadId": "thr-1", "includeTurns": True}
        return {
            "thread": {
                "turns": [
                    {
                        "items": [
                            {"type": "userMessage", "id": "m-1", "text": "first"},
                            {"type": "agentMessage", "id": "m-2", "text": "second"},
                        ]
                    },
                    {
                        "items": [
                            {"type": "userMessage", "id": "m-3", "text": "third"},
                            {"type": "agentMessage", "id": "m-4", "text": "fourth"},
                        ]
                    },
                ]
            }
        }

    client._rpc_request = fake_rpc_request

    messages = await client.list_messages("thr-1", params={"limit": 2})

    assert [message["info"]["id"] for message in messages] == ["m-3", "m-4"]


@pytest.mark.asyncio
async def test_session_shell_uses_command_exec_without_thread_context() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"stdout": "/safe\n", "stderr": "", "exitCode": 0}

    client._rpc_request = fake_rpc_request

    result = await client.session_shell("thr-1", {"command": "pwd"})

    assert seen == [("command/exec", {"command": ["pwd"], "cwd": "/safe"})]
    assert result["info"]["id"].startswith("shell:thr-1:")
    assert result["parts"][0]["text"] == "exit_code: 0\nstdout:\n/safe"


@pytest.mark.asyncio
async def test_session_prompt_async_maps_rich_input_parts_to_turn_start() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"turn": {"id": "turn-42"}}

    client._rpc_request = fake_rpc_request

    result = await client.session_prompt_async(
        "thr-1",
        {
            "parts": [
                {"type": "text", "text": "Use the app."},
                {"type": "image", "url": "https://example.com/image.png"},
                {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                {
                    "type": "skill",
                    "name": "skill-creator",
                    "path": "/tmp/skill-creator/SKILL.md",
                },
            ]
        },
    )

    assert result == {"ok": True, "session_id": "thr-1", "turn_id": "turn-42"}
    assert seen == [
        (
            "turn/start",
            {
                "threadId": "thr-1",
                "input": [
                    {"type": "text", "text": "Use the app.", "text_elements": []},
                    {
                        "type": "input_image",
                        "image_url": "https://example.com/image.png",
                    },
                    {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                    {
                        "type": "skill",
                        "name": "skill-creator",
                        "path": "/tmp/skill-creator/SKILL.md",
                    },
                ],
                "cwd": "/safe",
            },
        )
    ]


@pytest.mark.asyncio
async def test_exec_start_uses_interactive_command_exec_params() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_workspace_root="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None, float | None | object]] = []

    async def fake_rpc_request(
        method: str,
        params: dict | None = None,
        *,
        timeout_override=None,  # noqa: ANN001
        _skip_ensure: bool = False,
    ):
        del _skip_ensure
        seen.append((method, params, timeout_override))
        return {"stdout": "", "stderr": "", "exitCode": 0}

    client._rpc_request = fake_rpc_request

    result = await client.exec_start(
        {
            "command": "bash",
            "arguments": "-lc 'printf hello'",
            "processId": "exec-1",
            "tty": True,
            "rows": 24,
            "cols": 80,
            "outputBytesCap": 4096,
            "disableOutputCap": False,
            "timeoutMs": 3000,
            "disableTimeout": False,
        }
    )

    assert result == {"stdout": "", "stderr": "", "exitCode": 0}
    assert len(seen) == 1
    method, params, timeout_override = seen[0]
    assert method == "command/exec"
    assert params == {
        "command": ["bash", "-lc", "printf hello"],
        "processId": "exec-1",
        "tty": True,
        "streamStdin": True,
        "streamStdoutStderr": True,
        "cwd": "/safe",
        "size": {"rows": 24, "cols": 80},
        "outputBytesCap": 4096,
        "disableOutputCap": False,
        "timeoutMs": 3000,
        "disableTimeout": False,
    }
    assert timeout_override is not None


@pytest.mark.asyncio
async def test_exec_control_methods_forward_expected_rpc_calls() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(
        method: str,
        params: dict | None = None,
        *,
        timeout_override=None,  # noqa: ANN001
        _skip_ensure: bool = False,
    ):
        del timeout_override, _skip_ensure
        seen.append((method, params))
        return {}

    client._rpc_request = fake_rpc_request

    await client.exec_write(process_id="exec-1", delta_base64="cHdkCg==", close_stdin=False)
    await client.exec_resize(process_id="exec-1", rows=40, cols=120)
    await client.exec_terminate(process_id="exec-1")

    assert seen == [
        (
            "command/exec/write",
            {"processId": "exec-1", "deltaBase64": "cHdkCg==", "closeStdin": False},
        ),
        ("command/exec/resize", {"processId": "exec-1", "size": {"rows": 40, "cols": 120}}),
        ("command/exec/terminate", {"processId": "exec-1"}),
    ]


@pytest.mark.asyncio
async def test_thread_lifecycle_methods_forward_expected_rpc_calls() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(
        method: str,
        params: dict | None = None,
        *,
        timeout_override=None,  # noqa: ANN001
        _skip_ensure: bool = False,
    ):
        del timeout_override, _skip_ensure
        seen.append((method, params))
        if method == "thread/fork":
            return {"thread": {"id": "thr-1-fork", "preview": "Forked thread"}}
        if method == "thread/unarchive":
            return {"thread": {"id": "thr-1", "preview": "Restored thread"}}
        if method == "thread/metadata/update":
            return {"thread": {"id": "thr-1", "preview": "Thread 1"}}
        return {}

    client._rpc_request = fake_rpc_request

    fork = await client.thread_fork("thr-1", params={"ephemeral": True})
    await client.thread_archive("thr-1")
    await client.thread_unsubscribe("thr-1")
    unarchive = await client.thread_unarchive("thr-1")
    metadata = await client.thread_metadata_update(
        "thr-1", params={"gitInfo": {"branch": "feat/thread-lifecycle"}}
    )

    assert fork == {
        "id": "thr-1-fork",
        "title": "Forked thread",
        "raw": {"id": "thr-1-fork", "preview": "Forked thread"},
    }
    assert unarchive == {
        "id": "thr-1",
        "title": "Restored thread",
        "raw": {"id": "thr-1", "preview": "Restored thread"},
    }
    assert metadata == {
        "id": "thr-1",
        "title": "Thread 1",
        "raw": {"id": "thr-1", "preview": "Thread 1"},
    }
    assert seen == [
        ("thread/fork", {"threadId": "thr-1", "ephemeral": True}),
        ("thread/archive", {"threadId": "thr-1"}),
        ("thread/unsubscribe", {"threadId": "thr-1"}),
        ("thread/unarchive", {"threadId": "thr-1"}),
        (
            "thread/metadata/update",
            {"threadId": "thr-1", "gitInfo": {"branch": "feat/thread-lifecycle"}},
        ),
    ]


@pytest.mark.asyncio
async def test_command_exec_output_delta_notification_maps_to_exec_stream_event() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "command/exec/outputDelta",
            "params": {
                "processId": "exec-1",
                "stream": "stdout",
                "deltaBase64": "aGVsbG8K",
                "capReached": True,
            },
        }
    )

    assert events == [
        {
            "type": "exec.output.delta",
            "properties": {
                "process_id": "exec-1",
                "stream": "stdout",
                "delta_base64": "aGVsbG8K",
                "cap_reached": True,
            },
        }
    ]


@pytest.mark.asyncio
async def test_discovery_notifications_map_to_stream_events() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification({"method": "skills/changed", "params": {}})
    await client._handle_notification(
        {
            "method": "app/list/updated",
            "params": {
                "data": [
                    {
                        "id": "demo-app",
                        "name": "Demo App",
                        "description": "Example connector",
                        "installUrl": "https://example.com/apps/demo-app",
                        "isAccessible": True,
                        "isEnabled": True,
                    }
                ]
            },
        }
    )

    assert events == [
        {
            "type": "discovery.skills.changed",
            "properties": {},
        },
        {
            "type": "discovery.apps.updated",
            "properties": {
                "items": [
                    {
                        "id": "demo-app",
                        "name": "Demo App",
                        "description": "Example connector",
                        "is_accessible": True,
                        "is_enabled": True,
                        "install_url": "https://example.com/apps/demo-app",
                        "mention_path": "app://demo-app",
                        "branding": None,
                        "labels": None,
                        "codex": {
                            "raw": {
                                "id": "demo-app",
                                "name": "Demo App",
                                "description": "Example connector",
                                "installUrl": "https://example.com/apps/demo-app",
                                "isAccessible": True,
                                "isEnabled": True,
                            }
                        },
                    }
                ]
            },
        },
    ]


@pytest.mark.asyncio
async def test_thread_lifecycle_notifications_map_to_stream_events() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "thread/started",
            "params": {
                "thread": {
                    "id": "thr-1",
                    "preview": "Thread 1",
                    "status": {"type": "idle"},
                }
            },
        }
    )
    await client._handle_notification(
        {
            "method": "thread/status/changed",
            "params": {"threadId": "thr-1", "status": "running"},
        }
    )
    await client._handle_notification(
        {
            "method": "thread/archived",
            "params": {"threadId": "thr-1"},
        }
    )

    assert events == [
        {
            "type": "thread.lifecycle.started",
            "properties": {
                "thread_id": "thr-1",
                "thread": {
                    "id": "thr-1",
                    "title": "Thread 1",
                    "status": {"type": "idle"},
                    "raw": {
                        "id": "thr-1",
                        "preview": "Thread 1",
                        "status": {"type": "idle"},
                    },
                },
                "status": {"type": "idle"},
                "source": "thread/started",
                "codex": {
                    "raw": {
                        "thread": {
                            "id": "thr-1",
                            "preview": "Thread 1",
                            "status": {"type": "idle"},
                        }
                    }
                },
            },
        },
        {
            "type": "thread.lifecycle.status_changed",
            "properties": {
                "thread_id": "thr-1",
                "status": {"type": "running"},
                "source": "thread/status/changed",
                "codex": {"raw": {"threadId": "thr-1", "status": "running"}},
            },
        },
        {
            "type": "thread.lifecycle.archived",
            "properties": {
                "thread_id": "thr-1",
                "source": "thread/archived",
                "codex": {"raw": {"threadId": "thr-1"}},
            },
        },
    ]


@pytest.mark.asyncio
async def test_turn_lifecycle_notifications_map_to_stream_events() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "turn/started",
            "params": {"threadId": "thr-1", "turn": {"id": "turn-1", "status": "inProgress"}},
        }
    )
    await client._handle_notification(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thr-1",
                "turn": {"id": "turn-1", "status": "completed", "items": []},
            },
        }
    )

    assert events == [
        {
            "type": "turn.lifecycle.started",
            "properties": {
                "thread_id": "thr-1",
                "turn_id": "turn-1",
                "turn": {"id": "turn-1", "status": "inProgress"},
                "status": "inProgress",
                "source": "turn/started",
                "codex": {
                    "raw": {
                        "threadId": "thr-1",
                        "turn": {"id": "turn-1", "status": "inProgress"},
                    }
                },
            },
        },
        {
            "type": "turn.lifecycle.completed",
            "properties": {
                "thread_id": "thr-1",
                "turn_id": "turn-1",
                "turn": {"id": "turn-1", "status": "completed", "items": []},
                "status": "completed",
                "source": "turn/completed",
                "codex": {
                    "raw": {
                        "threadId": "thr-1",
                        "turn": {"id": "turn-1", "status": "completed", "items": []},
                    }
                },
            },
        },
    ]


@pytest.mark.asyncio
async def test_permission_reply_maps_to_codex_decision() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["100"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="100",
            interrupt_type="permission",
            session_id="thr-1",
            created_at=time.time(),
        ),
        rpc_request_id=100,
        params={"threadId": "thr-1"},
    )

    sent: list[dict] = []
    events: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._send_json_message = fake_send_json
    client._enqueue_stream_event = fake_enqueue

    ok = await client.permission_reply("100", reply="always")
    assert ok is True
    assert sent == [{"id": 100, "result": {"decision": "acceptForSession"}}]
    assert events[-1]["type"] == "permission.replied"
    assert events[-1]["properties"]["id"] == "100"
    assert events[-1]["properties"]["requestID"] == "100"
    assert "100" not in client._pending_server_requests


@pytest.mark.asyncio
async def test_question_reply_builds_answer_map() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["200"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="200",
            interrupt_type="question",
            session_id="thr-2",
            created_at=time.time(),
        ),
        rpc_request_id=200,
        params={
            "threadId": "thr-2",
            "questions": [
                {"id": "q1", "question": "Q1"},
                {"id": "q2", "question": "Q2"},
            ],
        },
    )

    sent: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(_event: dict) -> None:
        return None

    client._send_json_message = fake_send_json
    client._enqueue_stream_event = fake_enqueue

    ok = await client.question_reply("200", answers=[["A"], ["B", "C"]])
    assert ok is True
    assert sent == [
        {
            "id": 200,
            "result": {
                "answers": {
                    "q1": {"answers": ["A"]},
                    "q2": {"answers": ["B", "C"]},
                }
            },
        }
    ]


@pytest.mark.asyncio
async def test_permissions_reply_maps_to_granted_subset_and_scope() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["210"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="210",
            interrupt_type="permissions",
            session_id="thr-2",
            created_at=time.time(),
        ),
        rpc_request_id=210,
        params={"threadId": "thr-2"},
    )

    sent: list[dict] = []
    events: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._send_json_message = fake_send_json
    client._enqueue_stream_event = fake_enqueue

    ok = await client.permissions_reply(
        "210",
        permissions={"fileSystem": {"write": ["/workspace/project"]}},
        scope="session",
    )
    assert ok is True
    assert sent == [
        {
            "id": 210,
            "result": {
                "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
                "scope": "session",
            },
        }
    ]
    assert events[-1]["type"] == "permissions.replied"
    assert events[-1]["properties"]["id"] == "210"
    assert "210" not in client._pending_server_requests


@pytest.mark.asyncio
async def test_elicitation_reply_maps_to_action_and_content() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["220"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="220",
            interrupt_type="elicitation",
            session_id="thr-3",
            created_at=time.time(),
        ),
        rpc_request_id=220,
        params={"threadId": "thr-3"},
    )

    sent: list[dict] = []
    events: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._send_json_message = fake_send_json
    client._enqueue_stream_event = fake_enqueue

    ok = await client.elicitation_reply(
        "220",
        action="accept",
        content={"workspace_root": "/workspace/project"},
    )
    assert ok is True
    assert sent == [
        {
            "id": 220,
            "result": {
                "action": "accept",
                "content": {"workspace_root": "/workspace/project"},
            },
        }
    ]
    assert events[-1]["type"] == "elicitation.replied"
    assert events[-1]["properties"]["id"] == "220"
    assert "220" not in client._pending_server_requests


@pytest.mark.asyncio
async def test_interrupt_request_status_uses_configured_ttl(monkeypatch) -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_timeout=1.0,
            a2a_interrupt_request_ttl_seconds=5,
        )
    )
    client._pending_server_requests["req-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="req-1",
            interrupt_type="permission",
            session_id="thr-1",
            created_at=10.0,
        ),
        rpc_request_id=1,
        params={"threadId": "thr-1"},
    )

    monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 14.0)
    monkeypatch.setattr("codex_a2a.upstream.interrupts.time.time", lambda: 14.0)
    assert (await client.resolve_interrupt_request("req-1"))[0] == "active"

    monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 15.0)
    monkeypatch.setattr("codex_a2a.upstream.interrupts.time.time", lambda: 15.0)
    assert (await client.resolve_interrupt_request("req-1"))[0] == "expired"
    assert (await client.resolve_interrupt_request("req-1"))[0] == "expired"

    monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 616.0)
    monkeypatch.setattr("codex_a2a.upstream.interrupts.time.time", lambda: 616.0)
    assert (await client.resolve_interrupt_request("req-1"))[0] == "missing"
    assert "req-1" not in client._pending_server_requests


@pytest.mark.asyncio
async def test_stream_events_broadcasts_to_all_consumers() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))

    async def fake_ensure_started() -> None:
        return None

    client._ensure_started = fake_ensure_started

    stop_1 = asyncio.Event()
    stop_2 = asyncio.Event()
    seen_1: list[dict] = []
    seen_2: list[dict] = []

    async def consume(stop_event: asyncio.Event, out: list[dict]) -> None:
        async for event in client.stream_events(stop_event=stop_event):
            out.append(event)
            stop_event.set()

    task_1 = asyncio.create_task(consume(stop_1, seen_1))
    task_2 = asyncio.create_task(consume(stop_2, seen_2))

    for _ in range(20):
        if len(client._event_subscribers) == 2:
            break
        await asyncio.sleep(0)

    payload = {"type": "message.part.updated", "properties": {"sessionID": "thr-1"}}
    await client._enqueue_stream_event(payload)
    await asyncio.wait_for(asyncio.gather(task_1, task_2), timeout=1.0)

    assert seen_1 == [payload]
    assert seen_2 == [payload]


@pytest.mark.asyncio
async def test_handle_notification_normalizes_tool_output_delta_payload() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "item/commandExecution/outputDelta",
            "params": {
                "threadId": "thr-1",
                "itemId": "msg-1",
                "callID": "call-1",
                "tool": "bash",
                "state": {"status": "running"},
                "delta": "Passed\n",
            },
        }
    )

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "message.part.updated"
    assert event["properties"]["part"] == {
        "sessionID": "thr-1",
        "messageID": "msg-1",
        "id": "msg-1",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-1",
        "tool": "bash",
        "state": {"status": "running"},
        "sourceMethod": "commandExecution",
    }
    assert event["properties"]["delta"] == {
        "kind": "output_delta",
        "source_method": "commandExecution",
        "call_id": "call-1",
        "tool": "bash",
        "status": "running",
        "output_delta": "Passed\n",
    }


@pytest.mark.asyncio
async def test_handle_notification_normalizes_file_change_output_delta_payload() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "item/fileChange/outputDelta",
            "params": {
                "threadId": "thr-1",
                "callID": "call-file-1",
                "tool": "apply_patch",
                "delta": "Updated src/app.py\n",
            },
        }
    )

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "message.part.updated"
    assert event["properties"]["part"] == {
        "sessionID": "thr-1",
        "id": "call-file-1",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-file-1",
        "tool": "apply_patch",
        "sourceMethod": "fileChange",
    }
    assert event["properties"]["delta"] == {
        "kind": "output_delta",
        "source_method": "fileChange",
        "call_id": "call-file-1",
        "tool": "apply_patch",
        "output_delta": "Updated src/app.py\n",
    }


@pytest.mark.asyncio
async def test_handle_notification_normalizes_command_execution_started_state() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "item/started",
            "params": {
                "threadId": "thr-1",
                "item": {
                    "type": "commandExecution",
                    "id": "call-1",
                    "status": "inProgress",
                    "command": "/bin/bash -lc pytest",
                    "cwd": "/workspace",
                },
            },
        }
    )

    assert len(events) == 1
    event = events[0]
    assert event["properties"]["part"] == {
        "sessionID": "thr-1",
        "messageID": "call-1",
        "id": "call-1",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-1",
        "sourceMethod": "commandExecution",
        "state": {
            "status": "running",
            "input": {
                "command": "/bin/bash -lc pytest",
                "cwd": "/workspace",
            },
        },
    }
    assert event["properties"]["delta"] == {
        "kind": "state",
        "source_method": "commandExecution",
        "call_id": "call-1",
        "status": "running",
        "input": {
            "command": "/bin/bash -lc pytest",
            "cwd": "/workspace",
        },
    }


@pytest.mark.asyncio
async def test_handle_notification_normalizes_file_change_completed_state() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_notification(
        {
            "method": "item/completed",
            "params": {
                "threadId": "thr-1",
                "item": {
                    "type": "fileChange",
                    "id": "call-file-1",
                    "status": "completed",
                    "changes": [
                        {"path": "/workspace/src/app.py", "kind": {"type": "edit"}},
                    ],
                },
            },
        }
    )

    assert len(events) == 1
    event = events[0]
    assert event["properties"]["part"] == {
        "sessionID": "thr-1",
        "messageID": "call-file-1",
        "id": "call-file-1",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-file-1",
        "sourceMethod": "fileChange",
        "state": {
            "status": "completed",
            "input": {
                "paths": ["/workspace/src/app.py"],
                "change_count": 1,
            },
        },
    }
    assert event["properties"]["delta"] == {
        "kind": "state",
        "source_method": "fileChange",
        "call_id": "call-file-1",
        "status": "completed",
        "input": {
            "paths": ["/workspace/src/app.py"],
            "change_count": 1,
        },
    }


@pytest.mark.asyncio
async def test_handle_notification_replays_real_command_execution_fixture() -> None:
    fixture, events = await replay_codex_notification_fixture(
        "codex_app_server",
        "command_execution_output_delta.json",
    )
    tool_events = [
        event
        for event in events
        if event.get("properties", {}).get("part", {}).get("type") == "tool_call"
    ]
    expected_command = (
        '/bin/bash -lc "python3 -c \\"import sys,time; '
        "[print(f'chunk-{i}', flush=True) or time.sleep(0.2) for i in range(3)]"
        '\\""'
    )

    assert fixture["response_text"] == "DONE"
    assert [event["type"] for event in tool_events] == [
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
    ]
    assert tool_events[0]["properties"]["part"] == {
        "sessionID": "thr-fixture-command",
        "messageID": "call-fixture-command",
        "id": "call-fixture-command",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-fixture-command",
        "sourceMethod": "commandExecution",
        "state": {
            "status": "running",
            "input": {
                "command": expected_command,
                "cwd": "/tmp/codex-a2a-command-fixture",
            },
        },
    }
    assert tool_events[0]["properties"]["delta"]["kind"] == "state"
    assert [event["properties"]["delta"]["output_delta"] for event in tool_events[1:3]] == [
        "chunk-1\n",
        "chunk-2\n",
    ]
    assert tool_events[3]["properties"]["delta"] == {
        "kind": "state",
        "source_method": "commandExecution",
        "call_id": "call-fixture-command",
        "status": "completed",
        "input": {
            "command": expected_command,
            "cwd": "/tmp/codex-a2a-command-fixture",
        },
        "output": {
            "text": "chunk-1\nchunk-2\n",
            "exit_code": 0,
            "duration_ms": 487,
        },
    }


@pytest.mark.asyncio
async def test_read_stdout_loop_replays_real_command_execution_jsonrpc_lines() -> None:
    fixture, events = await replay_codex_jsonrpc_line_fixture(
        "codex_app_server",
        "command_execution_output_delta.json",
        chunk_sizes=(97, 211, 503),
    )
    tool_events = [
        event
        for event in events
        if event.get("properties", {}).get("part", {}).get("type") == "tool_call"
    ]

    assert fixture["response_text"] == "DONE"
    assert [event["type"] for event in tool_events] == [
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
    ]
    assert [event["properties"]["delta"]["kind"] for event in tool_events] == [
        "state",
        "output_delta",
        "output_delta",
        "state",
    ]
    assert tool_events[-1]["properties"]["delta"]["status"] == "completed"


@pytest.mark.asyncio
async def test_handle_notification_replays_real_file_change_fixture() -> None:
    fixture, events = await replay_codex_notification_fixture(
        "codex_app_server",
        "file_change_output_delta.json",
    )
    tool_events = [
        event
        for event in events
        if event.get("properties", {}).get("part", {}).get("type") == "tool_call"
    ]

    assert fixture["response_text"] == "DONE"
    assert [event["type"] for event in tool_events] == [
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
    ]
    assert tool_events[0]["properties"]["part"] == {
        "sessionID": "thr-fixture-file-change",
        "messageID": "call-fixture-file-change",
        "id": "call-fixture-file-change",
        "type": "tool_call",
        "role": "assistant",
        "callID": "call-fixture-file-change",
        "sourceMethod": "fileChange",
        "state": {
            "status": "running",
            "input": {
                "paths": ["/tmp/codex-a2a-file-change-fixture/fixture-from-codex.txt"],
                "change_count": 1,
            },
        },
    }
    assert tool_events[1]["properties"]["delta"] == {
        "kind": "output_delta",
        "source_method": "fileChange",
        "call_id": "call-fixture-file-change",
        "output_delta": "Success. Updated the following files:\nA fixture-from-codex.txt\n",
    }
    assert tool_events[2]["properties"]["delta"] == {
        "kind": "state",
        "source_method": "fileChange",
        "call_id": "call-fixture-file-change",
        "status": "completed",
        "input": {
            "paths": ["/tmp/codex-a2a-file-change-fixture/fixture-from-codex.txt"],
            "change_count": 1,
        },
    }


@pytest.mark.asyncio
async def test_read_stdout_loop_replays_real_file_change_jsonrpc_lines() -> None:
    fixture, events = await replay_codex_jsonrpc_line_fixture(
        "codex_app_server",
        "file_change_output_delta.json",
        chunk_sizes=(41, 89, 233),
    )
    tool_events = [
        event
        for event in events
        if event.get("properties", {}).get("part", {}).get("type") == "tool_call"
    ]

    assert fixture["response_text"] == "DONE"
    assert [event["type"] for event in tool_events] == [
        "message.part.updated",
        "message.part.updated",
        "message.part.updated",
    ]
    assert tool_events[1]["properties"]["delta"]["kind"] == "output_delta"
    assert tool_events[2]["properties"]["delta"]["status"] == "completed"


@pytest.mark.asyncio
async def test_read_stdout_loop_drops_invalid_and_non_object_json_lines(caplog) -> None:
    with caplog.at_level("DEBUG", logger="codex_a2a.upstream.client"):
        fixture, events = await replay_codex_jsonrpc_line_fixture(
            "codex_app_server",
            "command_execution_output_delta.json",
            prefix_lines=[
                b'{"method":"turn/started","params":\n',
                b"42\n",
                b"[1,2,3]\n",
            ],
            chunk_sizes=(19, 37, 211),
        )

    assert fixture["response_text"] == "DONE"
    assert any(event["type"] == "message.part.updated" for event in events)
    assert "drop non-json line from codex app-server" in caplog.text
    assert "drop non-object jsonrpc payload from codex app-server: int" in caplog.text
    assert "drop non-object jsonrpc payload from codex app-server: list" in caplog.text


@pytest.mark.asyncio
async def test_send_message_timeout_override_none_disables_wait_timeout() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=0.01))

    async def fake_rpc_request(_method: str, _params: dict | None = None):
        return {"turn": {"id": "turn-1"}}

    client._rpc_request = fake_rpc_request
    tracker = client._get_or_create_tracker("thr-1", "turn-1")

    async def finish_turn() -> None:
        await asyncio.sleep(0.05)
        tracker.text_chunks.append("done")
        tracker.completed.set()

    finisher = asyncio.create_task(finish_turn())
    message = await asyncio.wait_for(
        client.send_message("thr-1", "hello", timeout_override=None),
        timeout=1.0,
    )
    await finisher

    assert message.text == "done"
    assert ("thr-1", "turn-1") not in client._turn_trackers


@pytest.mark.asyncio
async def test_send_message_uses_structured_input_items_when_provided() -> None:
    client = CodexClient(
        make_settings(a2a_bearer_token="t-1", codex_workspace_root="/safe", codex_timeout=1.0)
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"turn": {"id": "turn-1"}}

    client._rpc_request = fake_rpc_request
    tracker = client._get_or_create_tracker("thr-1", "turn-1")
    tracker.text_chunks.append("done")
    tracker.completed.set()

    message = await client.send_message(
        "thr-1",
        "",
        input_items=[
            {"type": "text", "text": "Look at the screenshot."},
            {"type": "image", "url": "https://example.com/screenshot.png"},
            {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
        ],
    )

    assert message.text == "done"
    assert seen == [
        (
            "turn/start",
            {
                "threadId": "thr-1",
                "input": [
                    {
                        "type": "text",
                        "text": "Look at the screenshot.",
                        "text_elements": [],
                    },
                    {
                        "type": "input_image",
                        "image_url": "https://example.com/screenshot.png",
                    },
                    {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                ],
                "cwd": "/safe",
            },
        )
    ]


@pytest.mark.asyncio
async def test_send_message_request_execution_options_are_forwarded_to_turn_start() -> None:
    client = CodexClient(
        make_settings(a2a_bearer_token="t-1", codex_workspace_root="/safe", codex_timeout=1.0)
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        return {"turn": {"id": "turn-1"}}

    client._rpc_request = fake_rpc_request
    tracker = client._get_or_create_tracker("thr-1", "turn-1")
    tracker.text_chunks.append("done")
    tracker.completed.set()

    message = await client.send_message(
        "thr-1",
        "hello",
        execution_options=RequestExecutionOptions(
            model="gpt-5.2-codex",
            effort="high",
            summary="concise",
            personality="pragmatic",
        ),
    )

    assert message.text == "done"
    assert seen == [
        (
            "turn/start",
            {
                "threadId": "thr-1",
                "input": [{"type": "text", "text": "hello", "text_elements": []}],
                "cwd": "/safe",
                "model": "gpt-5.2-codex",
                "effort": "high",
                "summary": "concise",
                "personality": "pragmatic",
            },
        )
    ]


@pytest.mark.asyncio
async def test_unsupported_server_request_returns_jsonrpc_error() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    sent: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    client._send_json_message = fake_send_json

    await client._handle_server_request({"id": 300, "method": "item/tool/call", "params": {}})

    assert sent == [
        {
            "id": 300,
            "error": {
                "code": -32601,
                "message": "Unsupported server request method: item/tool/call",
            },
        }
    ]


@pytest.mark.asyncio
async def test_permission_request_emits_shared_message_and_patterns() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 301,
            "method": "execCommandApproval",
            "params": {
                "conversationId": "thr-1",
                "callId": "call-1",
                "command": ["cat", ".env"],
                "cwd": "/repo",
                "parsedCmd": [
                    {"cmd": "cat .env", "name": "cat", "path": "/repo/.env", "type": "read"}
                ],
                "reason": "The command needs confirmation before continuing.",
            },
        }
    )

    assert len(events) == 1
    props = events[0]["properties"]
    assert props["id"] == "301"
    assert props["sessionID"] == "thr-1"
    assert props["display_message"] == "The command needs confirmation before continuing."
    assert props["permission"] == "command_execution"
    assert props["patterns"] == ["/repo/.env"]
    assert "always" not in props
    assert "reason" not in props
    assert props["metadata"]["raw"]["parsedCmd"] == [
        {"cmd": "cat .env", "name": "cat", "path": "/repo/.env", "type": "read"}
    ]


@pytest.mark.asyncio
async def test_question_request_emits_shared_questions_and_display_message() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 302,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": "thr-2",
                "itemId": "item-1",
                "turnId": "turn-1",
                "description": "Please confirm how the agent should continue.",
                "prompt": "Proceed with deployment?",
                "questions": [
                    {
                        "header": "Deploy",
                        "id": "q1",
                        "question": "Proceed with deployment?",
                    }
                ],
            },
        }
    )

    assert len(events) == 1
    props = events[0]["properties"]
    assert props["id"] == "302"
    assert props["display_message"] == "Please confirm how the agent should continue."
    assert "description" not in props
    assert "prompt" not in props
    assert props["questions"] == [
        {"header": "Deploy", "id": "q1", "question": "Proceed with deployment?"}
    ]
    assert props["metadata"]["raw"]["prompt"] == "Proceed with deployment?"


@pytest.mark.asyncio
async def test_permissions_request_emits_shared_permissions_details() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 304,
            "method": "item/permissions/requestApproval",
            "params": {
                "threadId": "thr-4",
                "turnId": "turn-1",
                "itemId": "item-1",
                "reason": "Select the writable workspace root.",
                "permissions": {
                    "fileSystem": {"write": ["/workspace/project", "/workspace/shared"]}
                },
            },
        }
    )

    assert len(events) == 1
    assert events[0]["type"] == "permissions.asked"
    props = events[0]["properties"]
    assert props["id"] == "304"
    assert props["display_message"] == "Select the writable workspace root."
    assert props["permissions"] == {
        "fileSystem": {"write": ["/workspace/project", "/workspace/shared"]}
    }


@pytest.mark.asyncio
async def test_elicitation_request_emits_shared_elicitation_details() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 305,
            "method": "mcpServer/elicitation/request",
            "params": {
                "threadId": "thr-5",
                "turnId": "turn-2",
                "serverName": "drive",
                "mode": "form",
                "message": "Select the target folder.",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "title": "Folder"},
                    },
                },
                "_meta": {"persist": "session"},
            },
        }
    )

    assert len(events) == 1
    assert events[0]["type"] == "elicitation.asked"
    props = events[0]["properties"]
    assert props["id"] == "305"
    assert props["display_message"] == "Select the target folder."
    assert props["server_name"] == "drive"
    assert props["mode"] == "form"
    assert props["requested_schema"]["type"] == "object"
    assert props["meta"] == {"persist": "session"}


@pytest.mark.asyncio
async def test_permission_request_promotes_nested_request_message() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 303,
            "method": "execCommandApproval",
            "params": {
                "conversationId": "thr-3",
                "callId": "call-3",
                "command": ["cat", ".env"],
                "cwd": "/repo",
                "parsedCmd": [
                    {"cmd": "cat .env", "name": "cat", "path": "/repo/.env", "type": "read"}
                ],
                "request": {
                    "description": "Agent wants to read the environment file.",
                    "reason": "The command needs confirmation before continuing.",
                },
            },
        }
    )

    assert len(events) == 1
    props = events[0]["properties"]
    assert props["display_message"] == "Agent wants to read the environment file."
    assert props["permission"] == "command_execution"
    assert props["patterns"] == ["/repo/.env"]
    assert "request" not in props
    assert props["metadata"]["raw"]["request"] == {
        "description": "Agent wants to read the environment file.",
        "reason": "The command needs confirmation before continuing.",
    }


@pytest.mark.asyncio
async def test_question_request_promotes_nested_context_details() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    events: list[dict] = []

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._enqueue_stream_event = fake_enqueue

    await client._handle_server_request(
        {
            "id": 304,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": "thr-4",
                "itemId": "item-4",
                "turnId": "turn-4",
                "context": {
                    "description": "Please confirm how the agent should continue.",
                    "questions": [{"id": "q1", "question": "Proceed with deployment?"}],
                },
            },
        }
    )

    assert len(events) == 1
    props = events[0]["properties"]
    assert props["display_message"] == "Please confirm how the agent should continue."
    assert props["questions"] == [{"id": "q1", "question": "Proceed with deployment?"}]
    assert props["metadata"]["method"] == "item/tool/requestUserInput"
    assert props["metadata"]["raw"]["context"]["description"] == (
        "Please confirm how the agent should continue."
    )


@pytest.mark.asyncio
async def test_ensure_started_passes_runtime_overrides_to_codex_cli() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_timeout=1.0,
            codex_cli_bin="codex-custom",
            codex_model="gpt-5.1-codex",
            codex_profile="coding",
            codex_model_reasoning_effort="high",
            codex_model_reasoning_summary="concise",
            codex_model_verbosity="medium",
            codex_approval_policy="on-request",
            codex_sandbox_mode="workspace-write",
            codex_sandbox_workspace_write_writable_roots=["/safe", "/tmp/cache"],
            codex_sandbox_workspace_write_network_access=True,
            codex_sandbox_workspace_write_exclude_slash_tmp=True,
            codex_sandbox_workspace_write_exclude_tmpdir_env_var=False,
            codex_web_search="live",
            codex_review_model="gpt-5.1",
        )
    )

    captured: list[tuple] = []

    class _DummyStdin:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

    dummy_process = MagicMock()
    dummy_process.stdin = _DummyStdin()
    dummy_process.stdout = object()
    dummy_process.stderr = object()
    dummy_process.returncode = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.append((args, kwargs))
        return dummy_process

    async def fake_rpc_request(
        method: str, params: dict | None = None, *, _skip_ensure: bool = False
    ):
        assert method == "initialize"
        assert _skip_ensure is True
        assert params == {
            "clientInfo": {
                "name": "codex_a2a",
                "title": "Codex A2A",
                "version": client.settings.a2a_version,
            },
            "capabilities": {
                "experimentalApi": True,
            },
        }
        return {}

    async def fake_send_json(payload: dict) -> None:
        assert payload == {"method": "initialized", "params": {}}

    async def fake_stdout_loop() -> None:
        return None

    async def fake_stderr_loop() -> None:
        return None

    client._rpc_request = fake_rpc_request
    client._send_json_message = fake_send_json
    client._read_stdout_loop = fake_stdout_loop
    client._read_stderr_loop = fake_stderr_loop
    client._resolve_cli_bin = lambda: "codex-custom"

    original = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = fake_create_subprocess_exec
    try:
        await client._ensure_started()
    finally:
        asyncio.create_subprocess_exec = original
        await client.close()

    assert captured
    args, _kwargs = captured[0]
    assert args[:21] == (
        "codex-custom",
        "-c",
        'model="gpt-5.1-codex"',
        "-c",
        'profile="coding"',
        "-c",
        'model_reasoning_effort="high"',
        "-c",
        'model_reasoning_summary="concise"',
        "-c",
        'model_verbosity="medium"',
        "-c",
        'approval_policy="on-request"',
        "-c",
        'sandbox_mode="workspace-write"',
        "-c",
        'web_search="live"',
        "-c",
        'review_model="gpt-5.1"',
        "-c",
        'sandbox_workspace_write={"writable_roots": ["/safe", "/tmp/cache"], '
        '"network_access": true, "exclude_slash_tmp": true, '
        '"exclude_tmpdir_env_var": false}',
    )
    assert args[21:] == ("app-server", "--listen", "stdio://")


def test_build_startup_config_overrides_omits_empty_workspace_write_config() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))

    assert client._startup_config_overrides == {"model": "gpt-5.1-codex"}


def test_build_startup_config_overrides_prefers_profile_when_model_not_explicit() -> None:
    client = CodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_timeout=1.0,
            codex_profile="coding",
        )
    )

    assert client._startup_config_overrides == {"profile": "coding"}


@pytest.mark.asyncio
async def test_startup_preflight_fails_clearly_when_codex_is_missing() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))

    original_which = shutil.which
    original_exists = os.path.exists
    shutil.which = lambda _name: None
    os.path.exists = (
        lambda path: False
        if path == os.path.expanduser("~/.npm-global/bin/codex")
        else original_exists(path)
    )
    try:
        with pytest.raises(CodexStartupPrerequisiteError) as excinfo:
            await client.startup_preflight()
    finally:
        shutil.which = original_which
        os.path.exists = original_exists
        await client.close()

    assert "Install Codex" in str(excinfo.value)


@pytest.mark.asyncio
async def test_read_stdout_loop_handles_very_long_json_line() -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    payload = {"method": "event/test", "params": {"blob": "x" * 200_000}}
    encoded = (json.dumps(payload) + "\n").encode("utf-8")

    class _ChunkedStream:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = list(chunks)

        async def read(self, _size: int) -> bytes:
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    process = MagicMock()
    process.stdout = _ChunkedStream(
        [
            encoded[:70_000],
            encoded[70_000:140_000],
            encoded[140_000:],
        ]
    )
    client._process = process

    seen: list[dict] = []

    async def fake_dispatch(message: dict[str, object]) -> None:
        seen.append(message)

    client._dispatch_message = fake_dispatch

    await client._read_stdout_loop()

    assert len(seen) == 1
    assert seen[0]["method"] == "event/test"
    assert seen[0]["params"]["blob"] == "x" * 200_000


@pytest.mark.asyncio
async def test_dispatch_message_logs_with_pending_request_correlation_id(caplog) -> None:
    client = CodexClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    loop = asyncio.get_running_loop()
    future: asyncio.Future[object] = loop.create_future()
    client._pending_requests["7"] = _PendingRpcRequest(
        request_id="7",
        method="thread/list",
        future=future,
        correlation_id="corr-rpc-7",
    )

    with bind_correlation_id(None):
        with caplog.at_level(logging.DEBUG, logger="codex_a2a.upstream.client"):
            await client._dispatch_message({"id": 7, "result": {"data": []}})

    assert future.result() == {"data": []}
    assert any(
        record.message == "codex rpc response method=thread/list request_id=7"
        and record.correlation_id == "corr-rpc-7"
        for record in caplog.records
    )
