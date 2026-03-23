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

    @classmethod
    def from_legacy(
        cls,
        *,
        directory_resolver: DirectoryResolver | None = None,
        session_claim: SessionClaimHook | None = None,
        session_claim_finalize: SessionFinalizeHook | None = None,
        session_claim_release: SessionFinalizeHook | None = None,
        session_owner_matcher: SessionOwnerMatcher | None = None,
    ) -> SessionGuardHooks:
        return cls(
            directory_resolver=directory_resolver,
            session_claim=session_claim,
            session_claim_finalize=session_claim_finalize,
            session_claim_release=session_claim_release,
            session_owner_matcher=session_owner_matcher,
        )

    def missing_session_control_hooks(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.session_claim is None:
            missing.append("session_claim")
        if self.session_claim_finalize is None:
            missing.append("session_claim_finalize")
        if self.session_claim_release is None:
            missing.append("session_claim_release")
        return tuple(missing)
