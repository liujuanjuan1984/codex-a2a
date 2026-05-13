from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_a2a.jsonrpc.interrupt_params import (
    ElicitationReplyParams,
    PermissionReplyParams,
    PermissionsReplyParams,
    QuestionReplyParams,
    raise_interrupt_validation_error,
)
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError


def _mapped_validation_error(model, payload: dict[str, object]) -> JsonRpcParamsValidationError:  # noqa: ANN001
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(payload)
    with pytest.raises(JsonRpcParamsValidationError) as mapped:
        raise_interrupt_validation_error(excinfo.value)
    return mapped.value


def test_question_reply_params_strip_answers_and_preserve_group_shape() -> None:
    parsed = QuestionReplyParams.model_validate(
        {
            "request_id": "req-1",
            "answers": [[" yes ", "", "no"], []],
        }
    )

    assert parsed.answers == [["yes", "no"], []]


def test_raise_interrupt_validation_error_maps_answers_field() -> None:
    error = _mapped_validation_error(
        QuestionReplyParams,
        {"request_id": "req-1", "answers": ["bad"]},
    )

    assert str(error) == "answers[0] must be an array of strings"
    assert error.data == {"type": "INVALID_FIELD", "field": "answers"}


def test_raise_interrupt_validation_error_maps_permissions_field() -> None:
    error = _mapped_validation_error(
        PermissionsReplyParams,
        {"request_id": "req-2", "permissions": "bad"},
    )

    assert str(error) == "permissions must be an object"
    assert error.data == {"type": "INVALID_FIELD", "field": "permissions"}


def test_raise_interrupt_validation_error_maps_scope_field() -> None:
    error = _mapped_validation_error(
        PermissionsReplyParams,
        {"request_id": "req-3", "permissions": {}, "scope": "forever"},
    )

    assert str(error) == "scope must be one of: turn, session"
    assert error.data == {"type": "INVALID_FIELD", "field": "scope"}


def test_raise_interrupt_validation_error_maps_content_field() -> None:
    error = _mapped_validation_error(
        ElicitationReplyParams,
        {"request_id": "req-4", "action": "decline", "content": {"answer": "x"}},
    )

    assert str(error) == "content must be null when action is decline or cancel"
    assert error.data == {"type": "INVALID_FIELD", "field": "content"}


def test_raise_interrupt_validation_error_maps_extra_fields() -> None:
    error = _mapped_validation_error(
        PermissionReplyParams,
        {"request_id": "req-5", "reply": "once", "unexpected": True},
    )

    assert str(error) == "Unsupported fields: unexpected"
    assert error.data == {"type": "INVALID_FIELD", "fields": ["unexpected"]}
