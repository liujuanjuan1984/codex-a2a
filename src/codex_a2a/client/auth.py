from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from collections.abc import Mapping

from a2a.client.auth.credentials import CredentialService
from a2a.client.middleware import ClientCallContext

BASIC_AUTH_FORMAT_ERROR = (
    "A2A_CLIENT_BASIC_AUTH must be 'username:password' or a base64-encoded "
    "'username:password' value"
)


def validate_basic_auth(value: str) -> None:
    if ":" in value:
        return
    decoded = _decode_basic_auth(value)
    if b":" not in decoded:
        raise ValueError(BASIC_AUTH_FORMAT_ERROR)


def encode_basic_auth(value: str) -> str:
    if ":" in value:
        return b64encode(value.encode()).decode()
    decoded = _decode_basic_auth(value)
    if b":" not in decoded:
        raise ValueError(BASIC_AUTH_FORMAT_ERROR)
    return b64encode(decoded).decode()


def _decode_basic_auth(value: str) -> bytes:
    padded_value = value + ("=" * (-len(value) % 4))
    try:
        return b64decode(padded_value, validate=True)
    except (BinasciiError, ValueError) as exc:
        raise ValueError(BASIC_AUTH_FORMAT_ERROR) from exc


class StaticCredentialService(CredentialService):
    def __init__(self, credentials: Mapping[str, str]) -> None:
        self._credentials = {
            scheme_name: credential
            for scheme_name, credential in dict(credentials).items()
            if isinstance(scheme_name, str) and scheme_name and isinstance(credential, str)
        }

    async def get_credentials(
        self,
        security_scheme_name: str,
        context: ClientCallContext | None,
    ) -> str | None:
        return self._credentials.get(security_scheme_name)
