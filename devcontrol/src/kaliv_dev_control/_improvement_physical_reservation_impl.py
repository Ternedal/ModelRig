"""Authenticated host-local reservation boundary before DC-L15 execution.

The authority-bearing path derives its own repository, operation root and wall
clock, snapshots caller-owned authority inputs into exact local value objects,
and copies the caller runtime into a transaction-private staged runtime before
any trusted Git execution. That private runtime is bound to the candidate-
snapshot receipt already named by the human-signed qualification chain. After
an irreversible create-once host lock, the path re-reads ``refs/heads/main``
through the private runtime, re-verifies the signed request at current time,
and only then commits a receipt.

The durable ledger is host-local replay/recovery state, not reloadable authority.
The create-once reservation lock remains as the permanent replay marker after a
successful commit. Transaction provenance is process-local object identity bound
to the authenticated receipt digest, originating PID, and the exact current
bytes of both final receipt and replay marker. Removing or replacing either
marker invalidates live provenance immediately. Only the exact, unmodified
in-memory receipt returned by the successful authenticated transaction can
report ``transaction_authenticated=True``; forked children inherit no authority.

Neither the durable state nor the returned receipt claims distributed/global
replay safety, a persistent frozen main, physical campaign completion, pilot GO,
publication, or activation authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    remove_tree_durable,
    unlink_durable,
)
from .improvement_candidate_snapshot import CandidateSnapshotReceipt
from .improvement_physical_request import (
    PhysicalQualificationRequest,
    PhysicalQualificationRequestError,
    verify_physical_qualification_request,
)
from .improvement_qualification_packet import QualificationPacket
from .trusted_git_runtime_model import _has_linkish_component
from .trusted_git_runtime_runner import TrustedGitRunner
from .trusted_git_runtime_staging import TrustedGitRuntime, stage_trusted_git_runtime

MAIN_OBSERVATION_SCHEMA = "kaliv-rsi-local-main-head-observation/v1"
RESERVATION_SCHEMA = "kaliv-rsi-physical-qualification-reservation/v1"
RESERVATION_AUTHORITY = "consumed-request-evidence-only"
LEDGER_SCOPE = "canonical-host-local-v1"
MAIN_REF = "refs/heads/main"
_MAX_OBSERVATION_AGE = timedelta(minutes=5)
_MAX_ARTIFACT_BYTES = 256 * 1024

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalQualificationReservationError(ValueError):
    """The trusted observation or host-local reservation is invalid."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PhysicalQualificationReservationError(
            "physical qualification reservation is not canonical JSON"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalQualificationReservationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalQualificationReservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _safe_root(path: Path, *, name: str) -> Path:
    root = Path(path)
    if not root.is_absolute() or not root.is_dir() or _has_linkish_component(root):
        raise PhysicalQualificationReservationError(
            f"{name} must be an absolute link-free directory"
        )
    return root.resolve()


def _ensure_link_free_directory(path: Path, *, name: str) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise PhysicalQualificationReservationError(f"{name} must be absolute")
    cursor = target
    missing: list[Path] = []
    while not cursor.exists():
        if cursor.parent == cursor:
            raise PhysicalQualificationReservationError(f"{name} has no existing parent")
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir() or _has_linkish_component(cursor):
        raise PhysicalQualificationReservationError(f"{name} parent is unsafe")
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        except OSError as exc:
            raise PhysicalQualificationReservationError(
                f"{name} could not be created"
            ) from exc
        if not directory.is_dir() or directory.is_symlink():
            raise PhysicalQualificationReservationError(f"{name} creation raced")
    return _safe_root(target, name=name)


def _path_sha256(path: Path) -> str:
    return _sha256_bytes(os.fsencode(os.fspath(path)))


def _read_bound_file(path: Path, *, maximum: int) -> bytes | None:
    """Read one regular marker through an opened descriptor, never path metadata alone."""

    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 1
    ):
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError:
        return None
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size < 1
            or observed.st_size > maximum
        ):
            return None
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _canonical_host_state_root() -> Path:
    if os.name == "nt":
        root = Path(r"C:\ProgramData\ModelRig\DevControl")
    elif os.name == "posix":
        root = Path("/var/lib/modelrig/devcontrol")
    else:
        raise PhysicalQualificationReservationError(
            "canonical physical request state is unsupported on this platform"
        )
    return _ensure_link_free_directory(root, name="canonical DevControl host state")


def _canonical_host_ledger_root() -> Path:
    return _ensure_link_free_directory(
        _canonical_host_state_root() / "rsi-physical-request-ledger-v1",
        name="canonical physical request ledger",
    )


def _canonical_operation_root() -> Path:
    return _ensure_link_free_directory(
        _canonical_host_state_root() / "rsi-physical-git-operation-v1",
        name="canonical physical request Git operation root",
    )


def _canonical_repository_root() -> Path:
    """Bind production observation to the checkout containing this authority code."""

    root = Path(__file__).resolve().parents[3]
    if not (root / "devcontrol").is_dir():
        raise PhysicalQualificationReservationError(
            "canonical ModelRig repository root could not be derived"
        )
    return _safe_root(root, name="canonical ModelRig repository root")


_OBSERVATION_FIELDS = {
    "schema",
    "repository",
    "repository_root_path_sha256",
    "ref",
    "observed_sha",
    "observed_at_utc",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "network_performed",
    "repository_mutated",
    "authority",
}


@dataclass(frozen=True, slots=True)
class LocalMainHeadObservation:
    """Serializable evidence only; this type by itself grants no authority."""

    repository: str
    repository_root_path_sha256: str
    observed_sha: str
    observed_at_utc: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    ref: str = MAIN_REF
    network_performed: bool = False
    repository_mutated: bool = False
    authority: str = "evidence-only"
    schema: str = MAIN_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MAIN_OBSERVATION_SCHEMA:
            raise PhysicalQualificationReservationError(
                "main-head observation schema is unsupported"
            )
        if self.repository != "Ternedal/ModelRig" or self.ref != MAIN_REF:
            raise PhysicalQualificationReservationError(
                "main-head observation repository/ref is unsupported"
            )
        for name, value, pattern in (
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("observed_sha", self.observed_sha, _HEX40),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _utc(self.observed_at_utc, name="observed_at_utc")
        if (
            self.network_performed is not False
            or self.repository_mutated is not False
            or self.authority != "evidence-only"
        ):
            raise PhysicalQualificationReservationError(
                "main-head observation must remain local read-only evidence"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "LocalMainHeadObservation":
        return cls(
            **_strict(value, fields=_OBSERVATION_FIELDS, name="main-head observation")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "ref": self.ref,
            "observed_sha": self.observed_sha,
            "observed_at_utc": self.observed_at_utc,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "network_performed": self.network_performed,
            "repository_mutated": self.repository_mutated,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


class _GitReader(Protocol):
    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        maximum: int,
        **kwargs: Any,
    ) -> bytes: ...


def _observe_with_reader(
    *,
    reader: _GitReader,
    repository_root: Path,
    repository: str,
    observed_at_utc: str,
    git_runtime_manifest_sha256: str,
    git_executable_sha256: str,
) -> LocalMainHeadObservation:
    root = _safe_root(repository_root, name="main observation repository root")
    try:
        raw = reader.run(
            ("rev-parse", "--verify", f"{MAIN_REF}^{{commit}}"),
            cwd=root,
            maximum=4096,
        )
        observed_sha = raw.decode("ascii", errors="strict").strip()
    except (UnicodeError, OSError, ValueError) as exc:
        raise PhysicalQualificationReservationError(
            "trusted local Git could not observe main head"
        ) from exc
    _hex(observed_sha, name="observed main SHA", pattern=_HEX40)
    return LocalMainHeadObservation(
        repository=repository,
        repository_root_path_sha256=_path_sha256(root),
        observed_sha=observed_sha,
        observed_at_utc=observed_at_utc,
        git_runtime_manifest_sha256=git_runtime_manifest_sha256,
        git_executable_sha256=git_executable_sha256,
    )


def observe_local_main_head(
    *,
    trusted_git: TrustedGitRuntime,
    repository_root: Path,
    operation_root: Path,
    observed_at_utc: str,
    repository: str = "Ternedal/ModelRig",
) -> LocalMainHeadObservation:
    """Collect read-only observation evidence; does not itself authorize consume."""

    if type(trusted_git) is not TrustedGitRuntime:
        raise PhysicalQualificationReservationError(
            "main observation requires exact TrustedGitRuntime"
        )
    operation = _safe_root(operation_root, name="main observation operation root")
    runner = TrustedGitRunner(trusted_git, operation_root=operation)
    evidence = runner.evidence()
    observation = _observe_with_reader(
        reader=runner,
        repository_root=repository_root,
        repository=repository,
        observed_at_utc=observed_at_utc,
        git_runtime_manifest_sha256=evidence.runtime_manifest_sha256,
        git_executable_sha256=evidence.executable_sha256,
    )
    trusted_git.verify()
    return observation


_RESERVATION_FIELDS = {
    "schema",
    "ledger_scope",
    "ledger_root_path_sha256",
    "repository_root_path_sha256",
    "snapshot_receipt_sha256",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "request_id",
    "request_sha256",
    "qualification_packet_sha256",
    "signature_sha256",
    "requester_actor_id",
    "requested_main_sha",
    "observed_main_sha",
    "main_observation_sha256",
    "observed_at_utc",
    "consumed_at_utc",
    "collector_actor_id",
    "approver_actor_id",
    "main_head_match_confirmed",
    "request_consumed",
    "host_replay_guard_committed",
    "global_replay_safe",
    "frozen_main_confirmed",
    "physical_campaign_completed",
    "campaign_start_authorized",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
}


def _transaction_identity_registry():
    """Bind live provenance to identity, contents, process and exact replay markers."""

    references: dict[int, tuple[int, str, Path, bytes, Path, bytes, Any]] = {}

    def mark(
        value: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        if (
            _read_bound_file(final_path, maximum=_MAX_ARTIFACT_BYTES) != final_payload
            or _read_bound_file(lock_path, maximum=_MAX_ARTIFACT_BYTES) != lock_payload
        ):
            raise PhysicalQualificationReservationError(
                "physical reservation replay markers changed before provenance registration"
            )
        identity = id(value)
        origin_pid = os.getpid()
        authenticated_sha256 = value.sha256

        def discard(reference: Any, *, identity: int = identity) -> None:
            entry = references.get(identity)
            if entry is not None and entry[6] is reference:
                references.pop(identity, None)

        references[identity] = (
            origin_pid,
            authenticated_sha256,
            Path(final_path),
            bytes(final_payload),
            Path(lock_path),
            bytes(lock_payload),
            weakref.ref(value, discard),
        )

    def contains(value: Any) -> bool:
        entry = references.get(id(value))
        if entry is None:
            return False
        (
            origin_pid,
            authenticated_sha256,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            reference,
        ) = entry
        if origin_pid != os.getpid() or reference() is not value:
            return False
        try:
            if value.sha256 != authenticated_sha256:
                return False
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            _read_bound_file(final_path, maximum=_MAX_ARTIFACT_BYTES) == final_payload
            and _read_bound_file(lock_path, maximum=_MAX_ARTIFACT_BYTES) == lock_payload
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=references.clear)

    return mark, contains


_mark_transaction_authenticated, _is_transaction_authenticated = (
    _transaction_identity_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PhysicalQualificationReservation:
    """Parsed receipt data; live provenance binds identity, digest, process and markers."""

    ledger_root_path_sha256: str
    repository_root_path_sha256: str
    snapshot_receipt_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    request_id: str
    request_sha256: str
    qualification_packet_sha256: str
    signature_sha256: str
    requester_actor_id: str
    requested_main_sha: str
    observed_main_sha: str
    main_observation_sha256: str
    observed_at_utc: str
    consumed_at_utc: str
    collector_actor_id: str
    approver_actor_id: str
    ledger_scope: str = LEDGER_SCOPE
    main_head_match_confirmed: bool = True
    request_consumed: bool = True
    host_replay_guard_committed: bool = True
    global_replay_safe: bool = False
    frozen_main_confirmed: bool = False
    physical_campaign_completed: bool = False
    campaign_start_authorized: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = RESERVATION_AUTHORITY
    schema: str = RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RESERVATION_SCHEMA or self.ledger_scope != LEDGER_SCOPE:
            raise PhysicalQualificationReservationError(
                "physical reservation schema/ledger scope is unsupported"
            )
        _identifier(self.request_id, name="request_id")
        for name, value, pattern in (
            ("ledger_root_path_sha256", self.ledger_root_path_sha256, _HEX64),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("snapshot_receipt_sha256", self.snapshot_receipt_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("observed_main_sha", self.observed_main_sha, _HEX40),
            ("main_observation_sha256", self.main_observation_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _actor(self.requester_actor_id, name="requester_actor_id")
        collector = _actor(self.collector_actor_id, name="collector_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        if collector == approver:
            raise PhysicalQualificationReservationError(
                "physical collector and approver must remain different actors"
            )
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        if observed > consumed or consumed - observed > _MAX_OBSERVATION_AGE:
            raise PhysicalQualificationReservationError(
                "main-head observation is future-dated or stale at consumption"
            )
        if self.requested_main_sha != self.observed_main_sha:
            raise PhysicalQualificationReservationError(
                "reservation main SHA does not match requested main SHA"
            )
        if (
            self.main_head_match_confirmed is not True
            or self.request_consumed is not True
            or self.host_replay_guard_committed is not True
            or self.global_replay_safe is not False
        ):
            raise PhysicalQualificationReservationError(
                "reservation replay scope/consume evidence is invalid"
            )
        if (
            self.frozen_main_confirmed is not False
            or self.physical_campaign_completed is not False
            or self.campaign_start_authorized is not False
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != RESERVATION_AUTHORITY
        ):
            raise PhysicalQualificationReservationError(
                "reservation may not claim freeze, campaign, pilot, publication or activation authority"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalQualificationReservation":
        """Parse schema-valid data without granting transaction provenance."""

        return cls(
            **_strict(value, fields=_RESERVATION_FIELDS, name="physical reservation")
        )

    @property
    def transaction_authenticated(self) -> bool:
        """True only while identity, PID, contents and exact replay markers remain bound."""

        return _is_transaction_authenticated(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ledger_scope": self.ledger_scope,
            "ledger_root_path_sha256": self.ledger_root_path_sha256,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "snapshot_receipt_sha256": self.snapshot_receipt_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "signature_sha256": self.signature_sha256,
            "requester_actor_id": self.requester_actor_id,
            "requested_main_sha": self.requested_main_sha,
            "observed_main_sha": self.observed_main_sha,
            "main_observation_sha256": self.main_observation_sha256,
            "observed_at_utc": self.observed_at_utc,
            "consumed_at_utc": self.consumed_at_utc,
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "main_head_match_confirmed": self.main_head_match_confirmed,
            "request_consumed": self.request_consumed,
            "host_replay_guard_committed": self.host_replay_guard_committed,
            "global_replay_safe": self.global_replay_safe,
            "frozen_main_confirmed": self.frozen_main_confirmed,
            "physical_campaign_completed": self.physical_campaign_completed,
            "campaign_start_authorized": self.campaign_start_authorized,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


class _PhysicalQualificationRequestLedger:
    """Private create-once replay/recovery state for one canonical host ledger."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_root(root, name="physical request ledger root")
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, request_sha256: str) -> tuple[Path, Path, Path]:
        digest = _hex(request_sha256, name="request_sha256", pattern=_HEX64)
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def _lock_payload(self, request_sha256: str) -> bytes:
        digest = _hex(request_sha256, name="request_sha256", pattern=_HEX64)
        return _canonical(
            {
                "schema": "kaliv-rsi-physical-qualification-reservation-lock/v1",
                "ledger_scope": LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "request_sha256": digest,
            }
        ).encode("utf-8")

    def _load_final(
        self,
        path: Path,
        *,
        expected_payload: bytes | None = None,
    ) -> PhysicalQualificationReservation:
        """Parse persisted state without granting authenticated transaction provenance."""

        if not path.is_file() or _has_linkish_component(path):
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is missing or unsafe"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact size is invalid"
            )
        if expected_payload is not None and payload != expected_payload:
            raise PhysicalQualificationReservationError(
                "physical reservation final read-back does not match committed payload"
            )
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is invalid JSON"
            ) from exc
        receipt = PhysicalQualificationReservation.from_mapping(value)
        if payload != receipt.canonical_json().encode("utf-8"):
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is not canonical"
            )
        if receipt.ledger_root_path_sha256 != self.root_sha256:
            raise PhysicalQualificationReservationError(
                "physical reservation belongs to another host ledger root"
            )
        return receipt

    def load(self, request_sha256: str) -> PhysicalQualificationReservation:
        """Load durable data only; this never recreates transaction authority."""

        final, pending, lock = self._paths(request_sha256)
        if final.exists() or final.is_symlink():
            return self._load_final(final)
        if pending.exists() or pending.is_symlink() or lock.exists() or lock.is_symlink():
            raise PhysicalQualificationReservationError(
                "physical request is host-locally consumed but reservation requires recovery"
            )
        raise PhysicalQualificationReservationError(
            "physical request reservation is missing from canonical host ledger"
        )

    def acquire_lock(self, request_sha256: str) -> None:
        final, pending, lock = self._paths(request_sha256)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PhysicalQualificationReservationError(
                "physical request has already been host-locally consumed or requires recovery"
            )
        marker = self._lock_payload(request_sha256)
        try:
            create_once_file(lock, marker)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PhysicalQualificationReservationError(
                "physical request could not be durably host-reserved"
            ) from exc

    def commit_locked_mapping(
        self,
        *,
        request_sha256: str,
        mapping: Mapping[str, Any],
    ) -> PhysicalQualificationReservation:
        final, pending, lock = self._paths(request_sha256)
        lock_payload = self._lock_payload(request_sha256)
        if _read_bound_file(lock, maximum=_MAX_ARTIFACT_BYTES) != lock_payload:
            raise PhysicalQualificationReservationError(
                "physical request replay marker is missing after host-local consumption"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PhysicalQualificationReservationError(
                "physical reservation commit state already exists"
            )
        payload = _canonical(mapping).encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalQualificationReservationError(
                "physical reservation exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            self._load_final(final, expected_payload=payload)
            unlink_durable(pending)
            # The create-once lock is deliberately permanent after commit. It is
            # the replay marker, not temporary cleanup state.
            verified = self._load_final(final, expected_payload=payload)
            if _read_bound_file(lock, maximum=_MAX_ARTIFACT_BYTES) != lock_payload:
                raise PhysicalQualificationReservationError(
                    "physical request replay marker changed before provenance registration"
                )
            _mark_transaction_authenticated(
                verified,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if verified.transaction_authenticated is not True:
                raise PhysicalQualificationReservationError(
                    "physical reservation lost replay provenance before return"
                )
            return verified
        except Exception as exc:
            raise PhysicalQualificationReservationError(
                "physical request is durably host-consumed but reservation requires recovery"
            ) from exc


def _snapshot_authority_inputs(
    *,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
) -> tuple[
    PhysicalQualificationRequest,
    QualificationPacket,
    CandidateSnapshotReceipt,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
]:
    """Copy caller-owned authority inputs into exact local value objects."""

    if type(request) is not PhysicalQualificationRequest:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact PhysicalQualificationRequest"
        )
    if type(qualification) is not QualificationPacket:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact QualificationPacket"
        )
    if type(snapshot_receipt) is not CandidateSnapshotReceipt:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact CandidateSnapshotReceipt"
        )
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact detached Ed25519 signature"
        )
    if type(verifier) is not Ed25519AuthorityVerifier:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact Ed25519AuthorityVerifier"
        )

    try:
        request_snapshot = PhysicalQualificationRequest.from_json(
            request.canonical_json()
        )
        qualification_snapshot = QualificationPacket.from_json(
            qualification.canonical_json()
        )
        snapshot_mapping = json.loads(snapshot_receipt.canonical_json())
        snapshot_snapshot = CandidateSnapshotReceipt(**snapshot_mapping)
        signature_snapshot = DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(signature.canonical_json())
        )

        trusted_keys: dict[str, TrustedEd25519AuthorityKey] = {}
        source_keys = verifier._trusted_keys
        minimum_epoch = verifier._minimum_keyring_epoch
        if not isinstance(source_keys, dict):
            raise TypeError("authority verifier keyring is not concrete")
        for key_id, key in source_keys.items():
            if type(key) is not TrustedEd25519AuthorityKey:
                raise TypeError("authority verifier contains overridable key type")
            trusted_keys[key_id] = TrustedEd25519AuthorityKey.from_mapping(
                json.loads(key.canonical_json())
            )
        verifier_snapshot = Ed25519AuthorityVerifier(
            trusted_keys,
            minimum_keyring_epoch=minimum_epoch,
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PhysicalQualificationReservationError(
            "physical request authority inputs could not be snapshotted"
        ) from exc

    return (
        request_snapshot,
        qualification_snapshot,
        snapshot_snapshot,
        signature_snapshot,
        verifier_snapshot,
    )


def _snapshot_trusted_git_runtime(
    trusted_git: TrustedGitRuntime,
    *,
    operation_root: Path,
) -> tuple[TrustedGitRuntime, Path]:
    """Copy a verified caller runtime into one transaction-private runtime tree."""

    if type(trusted_git) is not TrustedGitRuntime:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact TrustedGitRuntime"
        )
    snapshot_root: Path | None = None
    try:
        operation = _safe_root(
            operation_root,
            name="physical request Git operation root",
        )
        source_root = Path(os.fspath(trusted_git.transaction_root)).resolve()
        source_runtime = TrustedGitRuntime(source_root)
        snapshot_root = Path(
            tempfile.mkdtemp(prefix=".rsi-physical-runtime-", dir=operation)
        ).resolve()
        snapshot_root = _safe_root(
            snapshot_root,
            name="physical request private Git runtime snapshot root",
        )
        if os.name == "posix":
            os.chmod(snapshot_root, 0o700)
            observed = snapshot_root.stat()
            if (
                (hasattr(os, "geteuid") and observed.st_uid != os.geteuid())
                or stat.S_IMODE(observed.st_mode) & 0o077
            ):
                raise PhysicalQualificationReservationError(
                    "physical request private Git runtime snapshot is not process-private"
                )
        staged_root = stage_trusted_git_runtime(
            source_runtime.receipt.manifest,
            source_root=source_runtime.runtime_root,
            staging_root=snapshot_root,
        )
        snapshot_runtime = TrustedGitRuntime(staged_root)
        if (
            snapshot_runtime.receipt.manifest.sha256
            != source_runtime.receipt.manifest.sha256
        ):
            raise PhysicalQualificationReservationError(
                "physical request private Git runtime snapshot identity changed"
            )
        snapshot_runtime.verify()
        return snapshot_runtime, snapshot_root
    except PhysicalQualificationReservationError:
        if snapshot_root is not None and snapshot_root.exists():
            try:
                remove_tree_durable(snapshot_root)
            except DurablePublicationError:
                pass
        raise
    except (AttributeError, OSError, TypeError, ValueError, DurablePublicationError) as exc:
        if snapshot_root is not None and snapshot_root.exists():
            try:
                remove_tree_durable(snapshot_root)
            except DurablePublicationError:
                pass
        raise PhysicalQualificationReservationError(
            "physical request Trusted Git runtime could not be privately snapshotted"
        ) from exc


def _verify_request_at(
    *,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    at_utc: str,
):
    try:
        return verify_physical_qualification_request(
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            verified_at_utc=at_utc,
        )
    except PhysicalQualificationRequestError as exc:
        raise PhysicalQualificationReservationError(
            f"physical request re-verification failed: {exc}"
        ) from exc


def _require_requested_main(
    observation: LocalMainHeadObservation,
    request: PhysicalQualificationRequest,
) -> None:
    if observation.repository != request.repository:
        raise PhysicalQualificationReservationError(
            "trusted main observation belongs to another repository"
        )
    if observation.observed_sha != request.requested_frozen_main_sha:
        raise PhysicalQualificationReservationError(
            "observed main head does not match the human-requested main SHA"
        )


def _require_signed_runtime_pin(
    *,
    snapshot_receipt: CandidateSnapshotReceipt,
    qualification: QualificationPacket,
    observation: LocalMainHeadObservation,
) -> None:
    if type(snapshot_receipt) is not CandidateSnapshotReceipt:
        raise PhysicalQualificationReservationError(
            "physical request consumption requires exact CandidateSnapshotReceipt"
        )
    if (
        snapshot_receipt.sha256 != qualification.snapshot_receipt_sha256
        or snapshot_receipt.materialization_receipt_sha256
        != qualification.materialization_receipt_sha256
        or snapshot_receipt.task_sha256 != qualification.task_sha256
        or snapshot_receipt.candidate_commit_sha != qualification.candidate_commit_sha
        or snapshot_receipt.candidate_tree_sha != qualification.candidate_tree_sha
    ):
        raise PhysicalQualificationReservationError(
            "snapshot receipt is not the one bound by the signed qualification chain"
        )
    if (
        observation.git_runtime_manifest_sha256
        != snapshot_receipt.git_runtime_manifest_sha256
        or observation.git_executable_sha256 != snapshot_receipt.git_executable_sha256
    ):
        raise PhysicalQualificationReservationError(
            "trusted Git runtime does not match the signed snapshot runtime identity"
        )


def _reservation_mapping(
    *,
    ledger: _PhysicalQualificationRequestLedger,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
    requester_actor_id: str,
    observation: LocalMainHeadObservation,
    consumed_at_utc: str,
) -> dict[str, Any]:
    return {
        "schema": RESERVATION_SCHEMA,
        "ledger_scope": LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "repository_root_path_sha256": observation.repository_root_path_sha256,
        "snapshot_receipt_sha256": snapshot_receipt.sha256,
        "git_runtime_manifest_sha256": observation.git_runtime_manifest_sha256,
        "git_executable_sha256": observation.git_executable_sha256,
        "request_id": request.request_id,
        "request_sha256": request.sha256,
        "qualification_packet_sha256": qualification.sha256,
        "signature_sha256": signature.sha256,
        "requester_actor_id": requester_actor_id,
        "requested_main_sha": request.requested_frozen_main_sha,
        "observed_main_sha": observation.observed_sha,
        "main_observation_sha256": observation.sha256,
        "observed_at_utc": observation.observed_at_utc,
        "consumed_at_utc": consumed_at_utc,
        "collector_actor_id": request.collector_actor_id,
        "approver_actor_id": request.approver_actor_id,
        "main_head_match_confirmed": True,
        "request_consumed": True,
        "host_replay_guard_committed": True,
        "global_replay_safe": False,
        "frozen_main_confirmed": False,
        "physical_campaign_completed": False,
        "campaign_start_authorized": False,
        "pilot_go_authorized": False,
        "activation_authorized": False,
        "remote_publication_authorized": False,
        "authority": RESERVATION_AUTHORITY,
    }


def _consume_physical_qualification_request_once(
    *,
    ledger_root: Path,
    trusted_git: TrustedGitRuntime,
    repository_root: Path,
    operation_root: Path,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PhysicalQualificationReservation:
    """Private injectable transaction used by production and deterministic tests."""

    (
        request_snapshot,
        qualification_snapshot,
        snapshot_snapshot,
        signature_snapshot,
        verifier_snapshot,
    ) = _snapshot_authority_inputs(
        request=request,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        signature=signature,
        verifier=verifier,
    )
    trusted_runtime, runtime_snapshot_root = _snapshot_trusted_git_runtime(
        trusted_git,
        operation_root=operation_root,
    )
    ledger = _PhysicalQualificationRequestLedger(
        _safe_root(ledger_root, name="physical request ledger root")
    )
    transaction_succeeded = False
    try:
        preflight_at = now_provider()
        _utc(preflight_at, name="trusted preflight time")
        _verify_request_at(
            request=request_snapshot,
            qualification=qualification_snapshot,
            signature=signature_snapshot,
            verifier=verifier_snapshot,
            at_utc=preflight_at,
        )
        preflight_observation = observe_local_main_head(
            trusted_git=trusted_runtime,
            repository_root=repository_root,
            operation_root=operation_root,
            observed_at_utc=preflight_at,
            repository=request_snapshot.repository,
        )
        _require_signed_runtime_pin(
            snapshot_receipt=snapshot_snapshot,
            qualification=qualification_snapshot,
            observation=preflight_observation,
        )
        _require_requested_main(preflight_observation, request_snapshot)

        ledger.acquire_lock(request_snapshot.sha256)
        try:
            observed_at = now_provider()
            _utc(observed_at, name="trusted post-lock observation time")
            observation = observe_local_main_head(
                trusted_git=trusted_runtime,
                repository_root=repository_root,
                operation_root=operation_root,
                observed_at_utc=observed_at,
                repository=request_snapshot.repository,
            )
            _require_signed_runtime_pin(
                snapshot_receipt=snapshot_snapshot,
                qualification=qualification_snapshot,
                observation=observation,
            )
            _require_requested_main(observation, request_snapshot)

            consumed_at = now_provider()
            consumed = _utc(consumed_at, name="trusted consumption time")
            observed = _utc(observation.observed_at_utc, name="observed_at_utc")
            if observed > consumed or consumed - observed > _MAX_OBSERVATION_AGE:
                raise PhysicalQualificationReservationError(
                    "trusted main observation is future-dated or stale at consumption"
                )
            request_receipt = _verify_request_at(
                request=request_snapshot,
                qualification=qualification_snapshot,
                signature=signature_snapshot,
                verifier=verifier_snapshot,
                at_utc=consumed_at,
            )
            mapping = _reservation_mapping(
                ledger=ledger,
                request=request_snapshot,
                qualification=qualification_snapshot,
                snapshot_receipt=snapshot_snapshot,
                signature=signature_snapshot,
                requester_actor_id=request_receipt.requester_actor_id,
                observation=observation,
                consumed_at_utc=consumed_at,
            )
            result = ledger.commit_locked_mapping(
                request_sha256=request_snapshot.sha256,
                mapping=mapping,
            )
            transaction_succeeded = True
            return result
        except PhysicalQualificationReservationError:
            raise
        except Exception as exc:
            raise PhysicalQualificationReservationError(
                "physical request is durably host-consumed but reservation requires recovery"
            ) from exc
    finally:
        try:
            remove_tree_durable(runtime_snapshot_root)
        except DurablePublicationError as exc:
            if transaction_succeeded:
                raise PhysicalQualificationReservationError(
                    "physical request committed but private Git runtime cleanup failed closed"
                ) from exc


def consume_physical_qualification_request_once(
    *,
    trusted_git: TrustedGitRuntime,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
) -> PhysicalQualificationReservation:
    """Authenticate, observe, and host-reserve one request exactly once.

    Callers cannot supply repository root, operation root, observation evidence,
    time, ledger ID/root, or a prebuilt receipt. Caller-owned authority inputs are
    reconstructed into exact local objects before verification, and caller-owned
    Git runtime bytes are copied into a transaction-private staged runtime before
    execution. The runtime must match the exact snapshot-runtime identity already
    named by the human-signed qualification chain. Live provenance remains true
    only while the exact final receipt and permanent replay marker are still
    present byte-for-byte. Persisted ledger data alone is replay/recovery state.
    """

    return _consume_physical_qualification_request_once(
        ledger_root=_canonical_host_ledger_root(),
        trusted_git=trusted_git,
        repository_root=_canonical_repository_root(),
        operation_root=_canonical_operation_root(),
        request=request,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )
