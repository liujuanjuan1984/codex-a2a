from typing import Any


def error_data(payload: dict[str, Any]) -> Any:
    return payload["error"].get("data")


def error_reason(payload: dict[str, Any]) -> str | None:
    data = error_data(payload)
    if isinstance(data, list):
        for detail in data:
            if (
                isinstance(detail, dict)
                and detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo"
            ):
                reason = detail.get("reason")
                if isinstance(reason, str):
                    return reason
        return None
    if isinstance(data, dict):
        reason = data.get("type")
        return reason if isinstance(reason, str) else None
    return None


def error_context(payload: dict[str, Any]) -> dict[str, Any]:
    data = error_data(payload)
    if isinstance(data, list):
        for detail in data:
            if (
                isinstance(detail, dict)
                and detail.get("@type") == "type.googleapis.com/codex_a2a.ErrorContext"
            ):
                return detail
        return {}
    if isinstance(data, dict):
        return data
    return {}
