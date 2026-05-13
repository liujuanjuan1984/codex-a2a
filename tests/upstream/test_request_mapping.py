from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.upstream.request_mapping import (
    apply_thread_start_execution_options,
    apply_turn_start_execution_options,
    build_discovery_skills_params,
    build_interactive_exec_params,
    build_thread_rpc_params,
    coerce_request_execution_options,
    format_exec_result_text,
)


def test_coerce_request_execution_options_clones_non_empty_values() -> None:
    options = RequestExecutionOptions(model="gpt-5", personality="pragmatic")

    cloned = coerce_request_execution_options(options)

    assert cloned == options
    assert cloned is not options
    assert coerce_request_execution_options(RequestExecutionOptions()) is None
    assert coerce_request_execution_options(None) is None


def test_apply_thread_start_execution_options_prefers_explicit_model_and_personality() -> None:
    params = apply_thread_start_execution_options(
        {},
        execution_options=RequestExecutionOptions(
            model="gpt-5.5",
            personality="friendly",
        ),
        default_model_id="gpt-default",
    )

    assert params == {
        "model": "gpt-5.5",
        "personality": "friendly",
    }


def test_apply_turn_start_execution_options_merges_non_empty_controls() -> None:
    params = apply_turn_start_execution_options(
        {},
        execution_options=RequestExecutionOptions(
            effort="high",
            summary="detailed",
            personality="pragmatic",
        ),
        default_model_id="gpt-default",
    )

    assert params == {
        "model": "gpt-default",
        "effort": "high",
        "summary": "detailed",
        "personality": "pragmatic",
    }


def test_build_interactive_exec_params_prefers_explicit_directory_and_optional_limits() -> None:
    params = build_interactive_exec_params(
        command_text="bash -lc",
        arguments="echo hello",
        process_id="proc-1",
        directory="/workspace/project",
        default_workspace_root="/workspace",
        tty=True,
        rows=40,
        cols=120,
        output_bytes_cap=2048,
        disable_output_cap=False,
        timeout_ms=5000,
        disable_timeout=True,
    )

    assert params == {
        "command": ["bash", "-lc", "echo", "hello"],
        "processId": "proc-1",
        "tty": True,
        "streamStdin": True,
        "streamStdoutStderr": True,
        "cwd": "/workspace/project",
        "size": {"rows": 40, "cols": 120},
        "outputBytesCap": 2048,
        "disableOutputCap": False,
        "timeoutMs": 5000,
        "disableTimeout": True,
    }


def test_build_discovery_param_helpers_map_repo_shape_to_rpc_shape() -> None:
    assert build_discovery_skills_params(
        {
            "cwds": ["/repo"],
            "force_reload": True,
            "per_cwd_extra_user_roots": [
                {"cwd": "/repo", "extra_user_roots": ["/alt"]},
                {"cwd": "/skip"},
            ],
        }
    ) == {
        "cwds": ["/repo"],
        "forceReload": True,
        "perCwdExtraUserRoots": [{"cwd": "/repo", "extraUserRoots": ["/alt"]}],
    }


def test_build_thread_rpc_params_drops_directory_and_normalizes_git_info() -> None:
    params = build_thread_rpc_params(
        "thr-2",
        {
            "directory": "/ignored",
            "limit": 20,
            "git_info": {
                "branch": "main",
                "sha": "abc123",
                "origin_url": "https://example.com/repo.git",
                "ignored": "value",
            },
            "optional": None,
        },
    )

    assert params == {
        "threadId": "thr-2",
        "limit": 20,
        "gitInfo": {
            "branch": "main",
            "sha": "abc123",
            "originUrl": "https://example.com/repo.git",
        },
    }


def test_format_exec_result_text_keeps_present_streams_and_trims_trailing_newlines() -> None:
    result = format_exec_result_text(
        {
            "exitCode": 0,
            "stdout": "hello\n",
            "stderr": "warn\n\n",
        }
    )

    assert result == "exit_code: 0\nstdout:\nhello\nstderr:\nwarn"
