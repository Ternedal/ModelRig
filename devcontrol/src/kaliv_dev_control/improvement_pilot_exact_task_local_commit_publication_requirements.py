"""ADR-DC-047 read-only verification and publication requirements.

Accepts only one live ADR-DC-046 completed local-write transaction, revalidates
its exact local ref, commit/tree bytes, required superproject objects and
unchanged workspace, then freezes requirements for any later remote publication.

This boundary is read-only. It grants no remote write, push, PR mutation, merge,
release, deploy, or production-activation authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PilotExactTaskLocalCommitObjectIdentity,
)
from . import improvement_pilot_exact_task_local_commit_write_reservation as reservation_boundary
from . import improvement_pilot_exact_task_local_commit_write_transaction as transaction_boundary
from .improvement_pilot_exact_task_local_commit_write_transaction import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY,
    PilotExactTaskLocalCommitWriteTransactionReceipt,
)

PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-publication-requirements/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY = (
    "host-verified-one-dc-l16-exact-local-commit-publication-requirements-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCOPE = (
    "verified-local-commit-publication-requirements-only-v1"
)

_MAX_BATCH_BYTES = 64 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^refs/modelrig/rsi/local-commit/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitPublicationRequirementsError(ValueError):
    """The completed local commit cannot be verified for publication planning."""


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
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "publication requirements are not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _trusted_read(
    inputs: Mapping[str, Any],
    args: tuple[str, ...],
    *,
    stdin: bytes | None = None,
    maximum: int = 4096,
) -> bytes:
    try:
        kwargs: dict[str, Any] = {
            "cwd": inputs["workspace_root"],
            "maximum": maximum,
            "timeout_seconds": 120,
        }
        if stdin is not None:
            kwargs["stdin"] = stdin
        result = inputs["git_runner"].run(args, **kwargs)
    except Exception as exc:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            f"trusted Git verification failed: {args[0]}"
        ) from exc
    if not isinstance(result, bytes):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "trusted Git verification returned non-bytes output"
        )
    return result


def _require_live_transaction(
    value: Any,
) -> tuple[
    PilotExactTaskLocalCommitWriteTransactionReceipt,
    PilotExactTaskLocalCommitObjectIdentity,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitWriteTransactionReceipt:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "exact ADR-DC-046 local-write transaction receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "ADR-DC-046 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "ADR-DC-046 transaction identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.local_commit_write_completed is not True
        or value.git_object_write_performed is not True
        or value.local_ref_update_performed is not True
        or value.local_commit_created is not True
        or value.exact_commit_object_verified is not True
        or value.local_ref_create_only_cas_succeeded is not True
        or value.post_write_ref_verified is not True
        or value.post_write_workspace_revalidated is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "publication verification requires one completed inert ADR-DC-046 transaction"
        )

    inputs = transaction_boundary._get_live_local_commit_write_transaction_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "ADR-DC-046 live transaction provenance is unavailable"
        )
    identity = inputs.get("local_commit_object_identity")
    reservation = inputs.get("local_commit_write_reservation")
    if (
        type(identity) is not PilotExactTaskLocalCommitObjectIdentity
        or identity.identity_authenticated is not True
        or identity.sha256 != value.local_commit_object_identity_sha256
        or reservation is None
        or getattr(reservation, "sha256", None) != value.write_reservation_sha256
        or getattr(reservation, "reservation_authenticated", None) is not True
        or identity.base_sha != value.base_sha
        or identity.index_manifest_sha256 != value.index_manifest_sha256
        or identity.root_tree_sha != value.root_tree_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "ADR-DC-046 transaction lost exact live reservation/object provenance"
        )
    return value, identity, inputs


def _verify_ref_and_commit(
    *,
    transaction: PilotExactTaskLocalCommitWriteTransactionReceipt,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> None:
    if _REF.fullmatch(transaction.local_ref) is None:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "ADR-DC-046 local ref is outside the host-pinned namespace"
        )
    target = _trusted_read(
        inputs,
        ("rev-parse", "--verify", f"{transaction.local_ref}^{{commit}}"),
        maximum=4096,
    ).decode("ascii", errors="strict").strip()
    if target != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "local candidate ref no longer points to the exact commit"
        )

    expected_payload = identity_boundary._commit_payload(
        tree_sha=identity.root_tree_sha,
        parent_sha=identity.base_sha,
        subject=identity.commit_subject,
        epoch_seconds=identity.commit_epoch_seconds,
    )
    actual_payload = _trusted_read(
        inputs,
        ("cat-file", "commit", identity.predicted_commit_sha),
        maximum=64 * 1024 * 1024,
    )
    if (
        actual_payload != expected_payload
        or hashlib.sha256(actual_payload).hexdigest() != identity.commit_payload_sha256
        or identity_boundary._git_sha1("commit", actual_payload)
        != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "local candidate commit object differs from the frozen ADR-DC-042 payload"
        )


def _verify_tree_objects_and_collect_entries(
    *,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> tuple[tuple[tuple[str, str, str], ...], int]:
    reservation_boundary._fresh_identity_revalidation(identity)
    index_payload = identity_boundary._read_index_manifest(inputs)
    entries = identity_boundary._parse_index_manifest(index_payload)
    if (
        hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256
        or len(entries) != identity.index_entry_count
    ):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "publication verification index differs from ADR-DC-042"
        )
    tree_objects = transaction_boundary._tree_object_payloads(entries)
    if not tree_objects or tree_objects[-1][0] != identity.root_tree_sha:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "publication verification tree set differs from ADR-DC-042 root"
        )
    for sha, expected_payload in tree_objects:
        actual_payload = _trusted_read(
            inputs,
            ("cat-file", "tree", sha),
            maximum=64 * 1024 * 1024,
        )
        if actual_payload != expected_payload:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "local tree object bytes differ from the exact reconstructed tree"
            )
    return entries, len(tree_objects)


def _verify_required_superproject_objects(
    *,
    entries: tuple[tuple[str, str, str], ...],
    tree_objects: tuple[tuple[str, bytes], ...],
    base_sha: str,
    inputs: Mapping[str, Any],
) -> tuple[int, int]:
    expected: dict[str, str] = {base_sha: "commit"}
    gitlink_count = 0
    for mode, object_sha, _path in entries:
        if mode == "160000":
            # A gitlink target belongs to the submodule repository and need not
            # exist in the superproject object database.
            gitlink_count += 1
            continue
        existing = expected.get(object_sha)
        if existing is not None and existing != "blob":
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "one object identity is bound to conflicting Git object types"
            )
        expected[object_sha] = "blob"
    for tree_sha, _payload in tree_objects:
        existing = expected.get(tree_sha)
        if existing is not None and existing != "tree":
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "one object identity is bound to conflicting Git object types"
            )
        expected[tree_sha] = "tree"

    ordered = sorted(expected)
    stdin = ("\n".join(ordered) + "\n").encode("ascii")
    if len(stdin) > _MAX_BATCH_BYTES:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "required-object batch exceeds byte bound"
        )
    raw = _trusted_read(
        inputs,
        ("cat-file", "--batch-check=%(objectname) %(objecttype)"),
        stdin=stdin,
        maximum=_MAX_BATCH_BYTES,
    )
    try:
        lines = raw.decode("ascii", errors="strict").splitlines()
    except UnicodeError as exc:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "required-object verification output is not canonical ASCII"
        ) from exc
    if len(lines) != len(ordered):
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "required-object verification returned the wrong result count"
        )
    for requested, line in zip(ordered, lines, strict=True):
        parts = line.split(" ")
        if len(parts) != 2 or parts[0] != requested or parts[1] != expected[requested]:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "required local Git object is missing or has the wrong type"
            )
    return len(ordered), gitlink_count


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]],
    ] = {}

    def mark(
        requirements: Any,
        transaction: PilotExactTaskLocalCommitWriteTransactionReceipt,
    ) -> None:
        key = id(requirements)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            requirements.sha256,
            weakref.ref(requirements, cleanup),
            weakref.ref(transaction),
        )

    def get(requirements: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(requirements))
        if entry is None:
            return None
        pid, digest, requirements_ref, transaction_ref = entry
        transaction = transaction_ref()
        if (
            pid != os.getpid()
            or requirements_ref() is not requirements
            or transaction is None
            or transaction.transaction_authenticated is not True
            or requirements.sha256 != digest
            or requirements.local_commit_write_transaction_sha256 != transaction.sha256
        ):
            return None
        inputs = transaction_boundary._get_live_local_commit_write_transaction_inputs(
            transaction
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_write_transaction"] = transaction
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_local_commit_publication_requirements_authenticated,
    _get_live_local_commit_publication_requirements_inputs,
) = _live_registry()


_REQUIRED_TRUE = (
    "local_commit_mechanically_verified",
    "local_ref_verified",
    "commit_object_bytes_verified",
    "tree_object_bytes_verified",
    "required_superproject_objects_verified",
    "workspace_and_index_revalidated",
    "head_remains_frozen_base",
    "publication_requirements_materialized",
    "separate_human_remote_publication_authorization_required",
    "remote_target_host_pinned_required",
    "remote_write_reservation_required",
    "remote_branch_compare_and_swap_required",
    "no_force_push_required",
    "separate_pr_mutation_authorization_required",
    "superproject_gitlink_target_presence_not_required",
)

_FORCED_FALSE = (
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitPublicationRequirements:
    local_commit_write_transaction_sha256: str
    write_reservation_sha256: str
    authorization_proof_sha256: str
    authorization_signature_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    repository: str
    base_sha: str
    local_ref: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    verified_tree_object_count: int
    verified_required_object_count: int
    gitlink_entry_count: int
    verified_at_utc: str
    local_commit_mechanically_verified: bool = True
    local_ref_verified: bool = True
    commit_object_bytes_verified: bool = True
    tree_object_bytes_verified: bool = True
    required_superproject_objects_verified: bool = True
    workspace_and_index_revalidated: bool = True
    head_remains_frozen_base: bool = True
    publication_requirements_materialized: bool = True
    separate_human_remote_publication_authorization_required: bool = True
    remote_target_host_pinned_required: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    superproject_gitlink_target_presence_not_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements schema is unsupported"
            )
        if self.requirements_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCOPE:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements scope is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements authority is unsupported"
            )
        for name in (
            "local_commit_write_transaction_sha256",
            "write_reservation_sha256",
            "authorization_proof_sha256",
            "authorization_signature_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.local_write_nonce_sha256 == self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "local-write nonce must differ from execution nonce"
            )
        if _REF.fullmatch(self.local_ref) is None:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements local ref is invalid"
            )
        if not isinstance(self.repository, str) or self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements repository is unsupported"
            )
        for name, value, minimum, maximum in (
            ("verified_tree_object_count", self.verified_tree_object_count, 1, 1_000_000),
            ("verified_required_object_count", self.verified_required_object_count, 1, 2_000_001),
            ("gitlink_entry_count", self.gitlink_entry_count, 0, 1_000_000),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise PilotExactTaskLocalCommitPublicationRequirementsError(
                    f"{name} is invalid"
                )
        _utc(self.verified_at_utc, name="verified_at_utc")
        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication verification requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements cannot grant remote/publication authority"
            )

    @property
    def verification_authenticated(self) -> bool:
        return _get_live_local_commit_publication_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskLocalCommitPublicationRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls, text: str
    ) -> "PilotExactTaskLocalCommitPublicationRequirements":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def materialize_pilot_exact_task_local_commit_publication_requirements(
    local_commit_write_transaction: PilotExactTaskLocalCommitWriteTransactionReceipt,
) -> PilotExactTaskLocalCommitPublicationRequirements:
    """Verify the exact local commit and freeze inert remote-publication requirements."""
    try:
        transaction, identity, inputs = _require_live_transaction(
            local_commit_write_transaction
        )
        reservation = inputs["local_commit_write_reservation"]
        _verify_ref_and_commit(
            transaction=transaction,
            identity=identity,
            inputs=inputs,
        )
        entries, tree_count = _verify_tree_objects_and_collect_entries(
            identity=identity,
            inputs=inputs,
        )
        tree_objects = transaction_boundary._tree_object_payloads(entries)
        required_count, gitlink_count = _verify_required_superproject_objects(
            entries=entries,
            tree_objects=tree_objects,
            base_sha=identity.base_sha,
            inputs=inputs,
        )
        # One final full workspace/index/object check after all object/ref reads.
        reservation_boundary._fresh_identity_revalidation(identity)
        verified_at = _now_utc_seconds()
        result = PilotExactTaskLocalCommitPublicationRequirements(
            local_commit_write_transaction_sha256=transaction.sha256,
            write_reservation_sha256=transaction.write_reservation_sha256,
            authorization_proof_sha256=transaction.authorization_proof_sha256,
            authorization_signature_sha256=transaction.authorization_signature_sha256,
            local_commit_object_identity_sha256=identity.sha256,
            execution_nonce_sha256=transaction.execution_nonce_sha256,
            local_write_nonce_sha256=transaction.local_write_nonce_sha256,
            repository=identity.repository,
            base_sha=identity.base_sha,
            local_ref=transaction.local_ref,
            index_manifest_sha256=identity.index_manifest_sha256,
            root_tree_sha=identity.root_tree_sha,
            commit_payload_sha256=identity.commit_payload_sha256,
            predicted_commit_sha=identity.predicted_commit_sha,
            verified_tree_object_count=tree_count,
            verified_required_object_count=required_count,
            gitlink_entry_count=gitlink_count,
            verified_at_utc=verified_at,
        )
        _mark_local_commit_publication_requirements_authenticated(result, transaction)
        if result.verification_authenticated is not True:
            raise PilotExactTaskLocalCommitPublicationRequirementsError(
                "publication requirements lost live transaction provenance"
            )
        return result
    except PilotExactTaskLocalCommitPublicationRequirementsError:
        raise
    except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise PilotExactTaskLocalCommitPublicationRequirementsError(
            "local commit publication verification failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_PUBLICATION_REQUIREMENTS_SCOPE",
    "PilotExactTaskLocalCommitPublicationRequirementsError",
    "PilotExactTaskLocalCommitPublicationRequirements",
    "materialize_pilot_exact_task_local_commit_publication_requirements",
]
