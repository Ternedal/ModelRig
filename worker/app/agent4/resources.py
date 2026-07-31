"""Thread-safe in-process resource leases for Agent 4 campaigns."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import re
from threading import RLock
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from .domain import CampaignValidationError, _require_aware, _require_text

_RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


class ResourceLeaseError(RuntimeError):
    """Base class for resource lease failures."""


class ResourceLeaseConflictError(ResourceLeaseError):
    """Raised when one campaign requests incompatible duplicate ownership."""


class ResourceLeaseNotFoundError(ResourceLeaseError):
    """Raised when a lease cannot be found or has already expired."""


def _resource_vector(
    value: Mapping[str, int],
    *,
    field_name: str,
    allow_empty: bool = False,
    allow_zero: bool = False,
) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise CampaignValidationError(f"{field_name} must be a mapping")
    normalized: dict[str, int] = {}
    for raw_name, quantity in value.items():
        if not isinstance(raw_name, str):
            raise CampaignValidationError(f"{field_name} names must be strings")
        name = raw_name.strip().lower()
        if not _RESOURCE_NAME.fullmatch(name):
            raise CampaignValidationError(
                f"{field_name} contains invalid resource name {raw_name!r}"
            )
        minimum = 0 if allow_zero else 1
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < minimum
        ):
            requirement = "a non-negative" if allow_zero else "a positive"
            raise CampaignValidationError(
                f"{field_name}.{name} must be {requirement} integer"
            )
        if name in normalized:
            raise CampaignValidationError(
                f"{field_name} contains duplicate normalized resource {name!r}"
            )
        normalized[name] = quantity
    if not normalized and not allow_empty:
        raise CampaignValidationError(f"{field_name} must not be empty")
    return MappingProxyType(dict(sorted(normalized.items())))


def _ttl(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise CampaignValidationError("lease ttl must be a positive timedelta")
    return value


@dataclass(frozen=True, slots=True)
class ResourceLease:
    lease_id: str
    campaign_id: str
    resources: Mapping[str, int]
    acquired_at: datetime
    expires_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _require_text(self.lease_id, "lease_id"))
        object.__setattr__(
            self,
            "campaign_id",
            _require_text(self.campaign_id, "campaign_id"),
        )
        object.__setattr__(
            self,
            "resources",
            _resource_vector(self.resources, field_name="resources"),
        )
        acquired_at = _require_aware(self.acquired_at, "acquired_at")
        expires_at = _require_aware(self.expires_at, "expires_at")
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "expires_at", expires_at)
        if expires_at <= acquired_at:
            raise CampaignValidationError("expires_at must be after acquired_at")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise CampaignValidationError("lease revision must be at least 1")

    def expired(self, now: datetime) -> bool:
        return self.expires_at <= _require_aware(now, "now")


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    capacities: Mapping[str, int]
    used: Mapping[str, int]
    available: Mapping[str, int]
    leases: tuple[ResourceLease, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capacities",
            _resource_vector(self.capacities, field_name="capacities"),
        )
        object.__setattr__(
            self,
            "used",
            _resource_vector(
                self.used,
                field_name="used",
                allow_empty=True,
                allow_zero=True,
            ),
        )
        object.__setattr__(
            self,
            "available",
            _resource_vector(
                self.available,
                field_name="available",
                allow_empty=True,
                allow_zero=True,
            ),
        )


class InMemoryResourceLeaseManager:
    """Atomic all-or-none leases over fixed named resource capacities.

    Expired leases are reclaimed lazily on every public operation. The manager
    is deliberately process-local: T-031 startup recovery fails interrupted
    campaigns closed, so a restarted process begins with no active ownership.
    """

    def __init__(self, capacities: Mapping[str, int]) -> None:
        self._capacities = _resource_vector(capacities, field_name="capacities")
        self._leases: dict[str, ResourceLease] = {}
        self._campaign_leases: dict[str, str] = {}
        self._lock = RLock()

    @property
    def capacities(self) -> Mapping[str, int]:
        return self._capacities

    def try_acquire(
        self,
        campaign_id: str,
        resources: Mapping[str, int],
        *,
        now: datetime,
        ttl: timedelta,
    ) -> ResourceLease | None:
        campaign_id = _require_text(campaign_id, "campaign_id")
        requirements = _resource_vector(resources, field_name="resources")
        now = _require_aware(now, "now")
        ttl = _ttl(ttl)
        with self._lock:
            self._reap(now)
            existing_id = self._campaign_leases.get(campaign_id)
            if existing_id is not None:
                existing = self._leases[existing_id]
                if existing.resources == requirements:
                    return existing
                raise ResourceLeaseConflictError(
                    f"campaign {campaign_id!r} already holds an incompatible lease"
                )
            self._validate_known(requirements)
            used = self._used()
            if any(
                used.get(name, 0) + quantity > self._capacities[name]
                for name, quantity in requirements.items()
            ):
                return None
            lease = ResourceLease(
                lease_id=f"lease-{uuid4().hex}",
                campaign_id=campaign_id,
                resources=requirements,
                acquired_at=now,
                expires_at=now + ttl,
            )
            self._leases[lease.lease_id] = lease
            self._campaign_leases[campaign_id] = lease.lease_id
            return lease

    def renew(
        self,
        lease_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> ResourceLease:
        lease_id = _require_text(lease_id, "lease_id")
        now = _require_aware(now, "now")
        ttl = _ttl(ttl)
        with self._lock:
            self._reap(now)
            current = self._leases.get(lease_id)
            if current is None:
                raise ResourceLeaseNotFoundError(f"lease {lease_id!r} was not found")
            renewed = replace(
                current,
                expires_at=now + ttl,
                revision=current.revision + 1,
            )
            self._leases[lease_id] = renewed
            return renewed

    def get(self, lease_id: str, *, now: datetime) -> ResourceLease | None:
        lease_id = _require_text(lease_id, "lease_id")
        now = _require_aware(now, "now")
        with self._lock:
            self._reap(now)
            return self._leases.get(lease_id)

    def for_campaign(
        self,
        campaign_id: str,
        *,
        now: datetime,
    ) -> ResourceLease | None:
        campaign_id = _require_text(campaign_id, "campaign_id")
        now = _require_aware(now, "now")
        with self._lock:
            self._reap(now)
            lease_id = self._campaign_leases.get(campaign_id)
            return self._leases.get(lease_id) if lease_id is not None else None

    def release(self, lease_id: str) -> bool:
        lease_id = _require_text(lease_id, "lease_id")
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            if lease is None:
                return False
            self._campaign_leases.pop(lease.campaign_id, None)
            return True

    def release_campaign(self, campaign_id: str) -> bool:
        campaign_id = _require_text(campaign_id, "campaign_id")
        with self._lock:
            lease_id = self._campaign_leases.pop(campaign_id, None)
            if lease_id is None:
                return False
            self._leases.pop(lease_id, None)
            return True

    def snapshot(self, *, now: datetime) -> ResourceSnapshot:
        now = _require_aware(now, "now")
        with self._lock:
            self._reap(now)
            used = self._used()
            available = {
                name: capacity - used.get(name, 0)
                for name, capacity in self._capacities.items()
            }
            return ResourceSnapshot(
                capacities=self._capacities,
                used=used,
                available=available,
                leases=tuple(
                    sorted(
                        self._leases.values(),
                        key=lambda lease: (
                            lease.expires_at,
                            lease.acquired_at,
                            lease.lease_id,
                        ),
                    )
                ),
            )

    def _validate_known(self, resources: Mapping[str, int]) -> None:
        unknown = sorted(set(resources) - set(self._capacities))
        if unknown:
            raise CampaignValidationError(
                "unknown resources: " + ", ".join(unknown)
            )
        oversized = [
            name
            for name, quantity in resources.items()
            if quantity > self._capacities[name]
        ]
        if oversized:
            raise CampaignValidationError(
                "request exceeds configured capacity for: " + ", ".join(oversized)
            )

    def _reap(self, now: datetime) -> None:
        expired = [
            lease_id
            for lease_id, lease in self._leases.items()
            if lease.expires_at <= now
        ]
        for lease_id in expired:
            lease = self._leases.pop(lease_id)
            self._campaign_leases.pop(lease.campaign_id, None)

    def _used(self) -> dict[str, int]:
        used: dict[str, int] = {}
        for lease in self._leases.values():
            for name, quantity in lease.resources.items():
                used[name] = used.get(name, 0) + quantity
        return used
