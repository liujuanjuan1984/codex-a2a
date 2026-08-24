import pytest

import codex_a2a.skill_handles as skill_handles
from codex_a2a.skill_handles import (
    SkillHandleResolutionError,
    build_skill_handle,
    resolve_skill_input_items,
)


def _skills_payload(*, enabled: bool = True) -> dict:
    return {
        "data": [
            {
                "cwd": "/workspace",
                "skills": [
                    {
                        "name": "demo",
                        "path": "/workspace/.codex/skills/demo/SKILL.md",
                        "enabled": enabled,
                    }
                ],
            }
        ]
    }


def test_resolve_skill_handle_returns_current_upstream_name_and_path() -> None:
    handle = build_skill_handle(
        cwd="/workspace",
        name="demo",
        path="/workspace/.codex/skills/demo/SKILL.md",
    )

    assert resolve_skill_input_items([{"type": "skill", "handle": handle}], _skills_payload()) == [
        {
            "type": "skill",
            "name": "demo",
            "path": "/workspace/.codex/skills/demo/SKILL.md",
        }
    ]


@pytest.mark.parametrize(
    ("handle", "payload", "code"),
    [
        (
            "skill:v1:" + "a" * 43,
            _skills_payload(),
            "SKILL_HANDLE_NOT_FOUND_OR_EXPIRED",
        ),
        (
            build_skill_handle(
                cwd="/workspace",
                name="demo",
                path="/workspace/.codex/skills/demo/SKILL.md",
            ),
            _skills_payload(enabled=False),
            "SKILL_HANDLE_DISABLED",
        ),
    ],
)
def test_resolve_skill_handle_reports_stable_unavailable_errors(
    handle: str, payload: dict, code: str
) -> None:
    with pytest.raises(SkillHandleResolutionError) as exc_info:
        resolve_skill_input_items([{"type": "skill", "handle": handle}], payload)

    assert exc_info.value.code == code
    assert exc_info.value.handle == handle
    assert "/workspace" not in str(exc_info.value)


def test_resolve_skill_handle_rejects_colliding_candidates(monkeypatch) -> None:
    handle = "skill:v1:" + "a" * 43
    monkeypatch.setattr(skill_handles, "build_skill_handle", lambda **kwargs: handle)
    payload = _skills_payload()
    payload["data"][0]["skills"].append(
        {
            "name": "other",
            "path": "/workspace/.codex/skills/other/SKILL.md",
            "enabled": True,
        }
    )

    with pytest.raises(SkillHandleResolutionError) as exc_info:
        resolve_skill_input_items([{"type": "skill", "handle": handle}], payload)

    assert exc_info.value.code == "SKILL_HANDLE_AMBIGUOUS"
