"""Rollback-safe external keyring state for DC-L12 authority verification.

The provider is injected and read for every verification. This module contains
no filesystem provider, network client, credential, private key or signer. A
signed local artifact is therefore insufficient to establish monotonic epoch or
revocation state.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)

_DOMAIN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


@dataclass(frozen=True, slots=True)
class PublisherExternalKeyringState:
    authority_domain: str
    generation: int
    minimum_keyring_epoch: int
    revoked_key_ids: tuple[str, ...]
    observed_at_utc: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.authority_domain, str)
            or _DOMAIN.fullmatch(self.authority_domain) is None
        ):
            raise AsymmetricAuthorityError("external keyring authority domain is invalid")
        for name, value in (
            ("external keyring generation", self.generation),
            ("external minimum keyring epoch", self.minimum_keyring_epoch),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise AsymmetricAuthorityError(f"{name} is invalid")
        if (
            not isinstance(self.revoked_key_ids, tuple)
            or tuple(sorted(set(self.revoked_key_ids))) != self.revoked_key_ids
        ):
            raise AsymmetricAuthorityError(
                "external revoked key IDs must be sorted and unique"
            )
        if any(
            not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None
            for key_id in self.revoked_key_ids
        ):
            raise AsymmetricAuthorityError("external revoked key ID is invalid")
        if not isinstance(self.observed_at_utc, str) or _UTC.fullmatch(
            self.observed_at_utc
        ) is None:
            raise AsymmetricAuthorityError(
                "external keyring observation must be canonical UTC seconds"
            )
        try:
            datetime.strptime(
                self.observed_at_utc,
                "%Y-%m-%dT%H:%M:%SZ",
            ).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise AsymmetricAuthorityError(
                "external keyring observation time is invalid"
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_domain": self.authority_domain,
            "generation": self.generation,
            "minimum_keyring_epoch": self.minimum_keyring_epoch,
            "revoked_key_ids": list(self.revoked_key_ids),
            "observed_at_utc": self.observed_at_utc,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class PublisherExternalKeyringStateProvider(Protocol):
    """Externally anchored monotonic state provider."""

    def read_current(self) -> PublisherExternalKeyringState:
        """Return the current externally anchored state."""


class RollbackSafeEd25519AuthorityVerifier(Ed25519AuthorityVerifier):
    """Ed25519 verifier that fails closed on external state rollback or drift."""

    def __init__(
        self,
        trusted_keys: Mapping[str, TrustedEd25519AuthorityKey],
        *,
        authority_domain: str,
        state_provider: PublisherExternalKeyringStateProvider,
    ) -> None:
        if not isinstance(authority_domain, str) or _DOMAIN.fullmatch(
            authority_domain
        ) is None:
            raise AsymmetricAuthorityError("external authority domain is invalid")
        if state_provider is None or not callable(
            getattr(state_provider, "read_current", None)
        ):
            raise AsymmetricAuthorityError(
                "external keyring state provider is required"
            )
        super().__init__(trusted_keys, minimum_keyring_epoch=1)
        self._authority_domain = authority_domain
        self._state_provider = state_provider
        self._state_lock = threading.Lock()
        self._highest_generation = 0
        self._generation_sha256: dict[int, str] = {}

    def _observe_state(self) -> PublisherExternalKeyringState:
        state = self._state_provider.read_current()
        if not isinstance(state, PublisherExternalKeyringState):
            raise AsymmetricAuthorityError("external keyring state is invalid")
        if state.authority_domain != self._authority_domain:
            raise AsymmetricAuthorityError(
                "external keyring state belongs to another authority domain"
            )
        with self._state_lock:
            known = self._generation_sha256.get(state.generation)
            if state.generation < self._highest_generation:
                raise AsymmetricAuthorityError(
                    "external keyring state generation rolled back"
                )
            if known is not None and known != state.sha256:
                raise AsymmetricAuthorityError(
                    "external keyring state drifted within one generation"
                )
            self._generation_sha256[state.generation] = state.sha256
            if state.generation > self._highest_generation:
                self._highest_generation = state.generation
        return state

    def verify(
        self,
        *,
        payload: bytes,
        signature: DetachedEd25519AuthoritySignature,
        at_utc: str,
    ) -> str:
        state = self._observe_state()
        if signature.keyring_epoch < state.minimum_keyring_epoch:
            raise AsymmetricAuthorityError(
                "authority signature predates external minimum keyring epoch"
            )
        if signature.key_id in state.revoked_key_ids:
            raise AsymmetricAuthorityError(
                "authority signing key is externally revoked"
            )
        return super().verify(payload=payload, signature=signature, at_utc=at_utc)


__all__ = [
    "PublisherExternalKeyringState",
    "PublisherExternalKeyringStateProvider",
    "RollbackSafeEd25519AuthorityVerifier",
]
