import json

from scripts.check_codex_app_server_schema import (
    EXPERIMENTAL_PROTOCOL_TOKENS,
    STABLE_PROTOCOL_TOKENS,
    collect_schema_tokens,
    missing_protocol_tokens,
)


def test_schema_token_collection_and_stable_contract(tmp_path) -> None:
    schema_path = tmp_path / "ClientRequest.json"
    schema_path.write_text(
        json.dumps({"methods": sorted(STABLE_PROTOCOL_TOKENS)}),
        encoding="utf-8",
    )

    tokens = collect_schema_tokens(tmp_path)

    assert missing_protocol_tokens(tokens, include_experimental=False) == []
    assert missing_protocol_tokens(tokens, include_experimental=True) == sorted(
        EXPERIMENTAL_PROTOCOL_TOKENS
    )


def test_schema_contract_reports_missing_stable_token() -> None:
    tokens = set(STABLE_PROTOCOL_TOKENS) - {"turn/start"}

    assert missing_protocol_tokens(tokens, include_experimental=False) == ["turn/start"]
