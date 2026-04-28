from __future__ import annotations

from typing import Any

from a2a.types import Message, Role, Task, TaskState, TaskStatus

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.parts.text import extract_text_from_parts


def session_context_id(session_id: str) -> str:
    return session_id


def extract_session_title(session: dict[str, Any]) -> str:
    title = session.get("title")
    if not isinstance(title, str):
        return ""
    return title.strip()


def as_a2a_session_task(session: Any) -> Task | None:
    if not isinstance(session, dict):
        return None
    raw_id = session.get("id")
    if not isinstance(raw_id, str):
        return None
    session_id = raw_id.strip()
    if not session_id:
        return None
    title = extract_session_title(session)
    if not title:
        return None
    task = Task(
        id=session_id,
        context_id=session_context_id(session_id),
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        metadata={
            "shared": {"session": {"id": session_id, "title": title}},
            "codex": {"raw": session},
        },
    )
    return task


def as_a2a_message(session_id: str, item: Any) -> Message | None:
    if not isinstance(item, dict):
        return None

    info = item.get("info")
    if not isinstance(info, dict):
        return None
    raw_id = info.get("id")
    if not isinstance(raw_id, str):
        return None
    message_id = raw_id.strip()
    if not message_id:
        return None

    role_raw = info.get("role")
    role = Role.ROLE_AGENT
    if isinstance(role_raw, str) and role_raw.strip().lower() == "user":
        role = Role.ROLE_USER

    text = extract_text_from_parts(item.get("parts"))

    message = Message(
        message_id=message_id,
        role=role,
        parts=[new_text_part(text)],
        context_id=session_context_id(session_id),
        metadata={
            "shared": {"session": {"id": session_id}},
            "codex": {"raw": item},
        },
    )
    return message


def extract_raw_items(raw_result: Any, *, kind: str) -> list[Any]:
    if isinstance(raw_result, list):
        return raw_result
    raise ValueError(f"Codex {kind} payload must be an array; got {type(raw_result).__name__}")
