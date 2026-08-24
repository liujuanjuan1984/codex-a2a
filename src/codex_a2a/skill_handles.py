from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any

SKILL_HANDLE_PREFIX = "skill:v1:"
_SKILL_HANDLE_PATTERN = re.compile(r"^skill:v1:[A-Za-z0-9_-]{43}$")


class SkillHandleResolutionError(ValueError):
    """Raised when an opaque skill handle cannot be resolved safely."""

    def __init__(self, code: str, handle: str) -> None:
        self.code = code
        self.handle = handle
        super().__init__(f"{code}: skill handle cannot be resolved")


@dataclass(frozen=True)
class _SkillCandidate:
    name: str
    path: str
    enabled: bool


def build_skill_handle(*, cwd: str, name: str, path: str) -> str:
    identity = (
        b"codex-a2a-skill-handle-v1\0"
        + "\0".join((cwd.strip(), name.strip(), path.strip())).encode()
    )
    digest = base64.urlsafe_b64encode(hashlib.sha256(identity).digest()).decode().rstrip("=")
    return f"{SKILL_HANDLE_PREFIX}{digest}"


def is_skill_handle(value: Any) -> bool:
    return isinstance(value, str) and _SKILL_HANDLE_PATTERN.fullmatch(value.strip()) is not None


def _skill_candidates(raw_result: Any) -> dict[str, list[_SkillCandidate]]:
    candidates: dict[str, list[_SkillCandidate]] = {}
    if not isinstance(raw_result, dict) or not isinstance(raw_result.get("data"), list):
        raise SkillHandleResolutionError("SKILL_DISCOVERY_UNAVAILABLE", "")
    for scope_entry in raw_result["data"]:
        if not isinstance(scope_entry, dict):
            continue
        cwd = scope_entry.get("cwd")
        skills = scope_entry.get("skills")
        if not isinstance(cwd, str) or not cwd.strip() or not isinstance(skills, list):
            continue
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            name = skill.get("name")
            path = skill.get("path")
            enabled = skill.get("enabled")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(path, str)
                or not path.strip()
                or not isinstance(enabled, bool)
            ):
                continue
            handle = build_skill_handle(cwd=cwd, name=name, path=path)
            candidates.setdefault(handle, []).append(
                _SkillCandidate(name=name.strip(), path=path.strip(), enabled=enabled)
            )
    return candidates


def resolve_skill_input_items(items: list[dict[str, Any]], raw_result: Any) -> list[dict[str, Any]]:
    candidates = _skill_candidates(raw_result)
    resolved: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") != "skill":
            resolved.append(dict(item))
            continue
        handle = item.get("handle")
        if not is_skill_handle(handle):
            raise SkillHandleResolutionError("SKILL_HANDLE_INVALID", str(handle or ""))
        normalized_handle = str(handle).strip()
        matches = candidates.get(normalized_handle, [])
        if not matches:
            raise SkillHandleResolutionError("SKILL_HANDLE_NOT_FOUND_OR_EXPIRED", normalized_handle)
        identities = {(match.name, match.path) for match in matches}
        if len(identities) != 1:
            raise SkillHandleResolutionError("SKILL_HANDLE_AMBIGUOUS", normalized_handle)
        enabled_matches = [match for match in matches if match.enabled]
        if not enabled_matches:
            raise SkillHandleResolutionError("SKILL_HANDLE_DISABLED", normalized_handle)
        match = enabled_matches[0]
        resolved.append({"type": "skill", "name": match.name, "path": match.path})
    return resolved
