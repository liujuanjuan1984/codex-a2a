from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

DirectoryResolver = Callable[[str | None], str | None]
SessionClaimHook = Callable[..., Awaitable[bool]]
SessionFinalizeHook = Callable[..., Awaitable[None]]
SessionOwnerMatcher = Callable[..., Awaitable[bool | None]]


@dataclass(frozen=True)
class SessionGuardHooks:
    directory_resolver: DirectoryResolver | None = None
    session_claim: SessionClaimHook | None = None
    session_claim_finalize: SessionFinalizeHook | None = None
    session_claim_release: SessionFinalizeHook | None = None
    session_owner_matcher: SessionOwnerMatcher | None = None
