from __future__ import annotations

import socket

import pytest

from codex_a2a.client.network_policy import (
    A2ANetworkPolicyError,
    matches_allowed_host,
    validate_agent_url,
)


def test_matches_allowed_host_exact_and_wildcard() -> None:
    assert matches_allowed_host("peer.example.com", ["peer.example.com"])
    assert matches_allowed_host("a.example.com", ["*.example.com"])
    assert matches_allowed_host("b.a.example.com", ["*.example.com"])
    assert not matches_allowed_host("example.com", ["*.example.com"])
    assert not matches_allowed_host("other.org", ["*.example.com"])
    assert not matches_allowed_host("evil-example.com", ["*.example.com"])
    assert not matches_allowed_host("", ["peer.example.com"])


def _patch_public_dns(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def fake_resolve(host: str) -> tuple[str, ...]:
        del host
        return tuple(addresses)

    monkeypatch.setattr(
        "codex_a2a.client.network_policy.resolve_host_addresses",
        fake_resolve,
    )


@pytest.mark.asyncio
async def test_validate_rejects_non_http_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("file:///etc/passwd")
    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("ftp://peer.example.com/")
    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("peer.example.com/path")


@pytest.mark.asyncio
async def test_validate_rejects_missing_host_and_userinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="host"):
        await validate_agent_url("https:///path")
    with pytest.raises(A2ANetworkPolicyError, match="userinfo"):
        await validate_agent_url(
            "https://user:pass@peer.example.com/"  # pragma: allowlist secret
        )


@pytest.mark.asyncio
async def test_validate_rejects_host_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="not allowed"):
        await validate_agent_url(
            "https://other.org/",
            allowed_hosts=["peer.example.com"],
        )


@pytest.mark.asyncio
async def test_validate_accepts_allowlisted_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    decision = await validate_agent_url(
        "https://peer.example.com/",
        allowed_hosts=["*.example.com"],
    )
    assert decision.host == "peer.example.com"
    assert decision.allowed_host is True
    assert decision.credentials_allowed is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "172.16.0.1",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
    ],
)
@pytest.mark.asyncio
async def test_validate_rejects_private_resolution(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    _patch_public_dns(monkeypatch, address)

    with pytest.raises(A2ANetworkPolicyError, match="private/loopback"):
        await validate_agent_url("https://peer.example.com/")


@pytest.mark.asyncio
async def test_allow_private_hosts_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_public_dns(monkeypatch, "127.0.0.1")

    decision = await validate_agent_url(
        "https://127.0.0.1:8000/",
        allow_private_hosts=True,
    )
    assert decision.credentials_allowed is False


@pytest.mark.asyncio
async def test_validate_rejects_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> tuple[str, ...]:
        del host
        raise socket.gaierror("no such host")

    monkeypatch.setattr(
        "codex_a2a.client.network_policy.resolve_host_addresses",
        fake_resolve,
    )

    with pytest.raises(A2ANetworkPolicyError, match="could not be resolved"):
        await validate_agent_url("https://peer.example.com/")
