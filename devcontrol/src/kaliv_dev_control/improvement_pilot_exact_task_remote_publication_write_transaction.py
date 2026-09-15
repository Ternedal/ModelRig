"""ADR-DC-053 exact create-only remote Git publication transaction.

Consumes one live ADR-DC-052 credential capability. The exact host-pinned remote
is freshly re-observed as absent, the pinned askpass broker is re-hashed under
host control, one bounded compare-and-swap create push is attempted, and the
exact destination ref is verified read-only afterwards. PR mutation remains
outside this boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from . import _improvement_pilot_exact_task_remote_publication_credential_capability_production_boundary as broker_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from . import improvement_pilot_exact_task_local_commit_publication_requirements as publication_boundary
from . import improvement_pilot_exact_task_remote_publication_credential_capability as capability_boundary
from .improvement_pilot_exact_task_remote_publication_credential_capability import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY,
    PilotExactTaskRemotePublicationCredentialCapability,
)
from . import improvement_pilot_exact_task_remote_publication_state_observation as state_boundary
from . import improvement_pilot_exact_task_remote_publication_target_attestation as target_boundary
from . import improvement_pilot_exact_task_remote_publication_write_reservation as reservation_boundary

PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-write-transaction/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY = (
    "completed-one-dc-l16-exact-remote-publication-create-only-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS = 60
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_EXPECTED_OLD_SHA = "0" * 40

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_MAX_PUSH_OUTPUT_BYTES = 64 * 1024
_MAX_REMOTE_OUTPUT_BYTES = 4096


class PilotExactTaskRemotePublicationWriteTransactionError(ValueError):
    """The exact remote publication transaction is stale, drifted, or unsafe."""


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
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "remote publication transaction is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            f"{name} is invalid"
        )
    if not allow_zero and value == "0" * 40:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            f"{name} must not be zero"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _stable_observation_mapping(value: Any) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("observed_at_utc")
    return result


def _require_live_capability(
    value: Any,
) -> tuple[
    PilotExactTaskRemotePublicationCredentialCapability,
    Any,
    Any,
    Any,
    Mapping[str, Any],
    Mapping[str, str],
]:
    if type(value) is not PilotExactTaskRemotePublicationCredentialCapability:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "exact ADR-DC-052 credential capability is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-052 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-052 capability identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.remote_publication_authorization_consumed is not True
        or value.remote_write_slot_reserved is not True
        or value.credential_broker_host_pinned is not True
        or value.credential_broker_binary_verified is not True
        or value.credential_secret_not_loaded is not True
        or value.credential_material_in_artifact is not False
        or value.credential_material_in_process_arguments is not False
        or value.credential_material_in_environment is not False
        or value.one_shot_remote_write_required is not True
        or value.fresh_remote_state_revalidation_before_write_required is not True
        or value.create_only_remote_ref_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.expected_old_remote_sha
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_EXPECTED_OLD_SHA
        or value.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
        or _REF.fullmatch(value.destination_ref) is None
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "remote transaction requires one live inert ADR-DC-052 capability"
        )

    cap_inputs = capability_boundary._get_live_remote_publication_credential_capability_inputs(
        value
    )
    if cap_inputs is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-052 live capability provenance is unavailable"
        )
    reservation = cap_inputs.get("remote_publication_write_reservation")
    descriptor = cap_inputs.get("credential_broker_descriptor")
    if (
        reservation is None
        or getattr(reservation, "sha256", None) != value.remote_write_reservation_sha256
        or getattr(reservation, "reservation_authenticated", None) is not True
        or not isinstance(descriptor, Mapping)
        or descriptor.get("broker_executable_path_sha256")
        != value.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256")
        != value.broker_executable_sha256
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-052 capability lost exact live reservation/broker provenance"
        )

    reservation_inputs = reservation_boundary._get_live_remote_publication_write_reservation_inputs(
        reservation
    )
    if reservation_inputs is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-051 live reservation provenance is unavailable"
        )
    observation = reservation_inputs.get("remote_publication_state_observation")
    if (
        observation is None
        or getattr(observation, "sha256", None) != value.fresh_state_observation_sha256
        or getattr(observation, "observation_authenticated", None) is not True
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-051 reservation lost exact remote-state provenance"
        )
    state_inputs = state_boundary._get_live_remote_publication_state_observation_inputs(
        observation
    )
    if state_inputs is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-050 live observation provenance is unavailable"
        )
    attestation = state_inputs.get("remote_publication_target_attestation")
    if (
        attestation is None
        or getattr(attestation, "sha256", None) != value.target_attestation_sha256
        or getattr(attestation, "target_attestation_authenticated", None) is not True
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-049 live target provenance is unavailable"
        )
    target_inputs = target_boundary._get_live_remote_publication_target_attestation_inputs(
        attestation
    )
    proof = None if target_inputs is None else target_inputs.get(
        "remote_publication_authorization_proof"
    )
    requirements = None if proof is None else getattr(
        getattr(proof, "authorization", None),
        "local_commit_publication_requirements",
        None,
    )
    if (
        proof is None
        or getattr(proof, "sha256", None) != value.authorization_proof_sha256
        or requirements is None
        or getattr(requirements, "sha256", None)
        != value.local_commit_publication_requirements_sha256
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-048/047 live publication provenance is unavailable"
        )
    publication_inputs = publication_boundary._get_live_local_commit_publication_requirements_inputs(
        requirements
    )
    if publication_inputs is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "trusted Git publication inputs are unavailable"
        )
    return value, reservation, observation, attestation, publication_inputs, descriptor


def _require_transaction_window(
    capability: PilotExactTaskRemotePublicationCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="remote transaction time")
    materialized = _utc(capability.materialized_at_utc, name="capability materialized_at_utc")
    if at < materialized:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "system clock moved backwards after ADR-DC-052 capability"
        )
    if (
        at - materialized
    ).total_seconds() > PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "ADR-DC-052 credential capability is too old for remote write"
        )


def _fresh_remote_absence(
    *,
    supplied_observation: Any,
    attestation: Any,
    now_provider: Callable[[], str],
) -> Any:
    try:
        fresh = state_boundary._observe_verified_pilot_exact_task_remote_publication_state(
            target_attestation=attestation,
            now_provider=now_provider,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "fresh remote absence revalidation failed immediately before write"
        ) from exc
    if _stable_observation_mapping(fresh) != _stable_observation_mapping(
        supplied_observation
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "fresh remote-state semantics drifted before write"
        )
    return fresh


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "live credential-broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "credential-broker binary could not be freshly verified"
        ) from exc
    digest = hashlib.sha256(payload).hexdigest()
    if digest != descriptor.get("broker_executable_sha256"):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "credential-broker binary changed after ADR-DC-052"
        )
    return path


def _brokered_push(
    *,
    runner: Any,
    workspace: Path,
    broker_path: Path,
    predicted_commit_sha: str,
    canonical_remote_url: str,
    destination_ref: str,
) -> Any:
    runtime = getattr(runner, "runtime", None)
    executable = getattr(runtime, "executable_path", None)
    hooks = getattr(runner, "_hooks", None)
    if runtime is None or executable is None or hooks is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "trusted Git runtime is unavailable for remote transaction"
        )
    try:
        runtime.verify()
        runner._verify_isolation()
        environment = runner.environment()
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "trusted Git runtime isolation could not be verified"
        ) from exc
    environment = dict(environment)
    environment["GIT_ASKPASS"] = os.fspath(broker_path)
    environment["GIT_ASKPASS_REQUIRE"] = "force"
    lease = f"--force-with-lease={destination_ref}:"
    refspec = f"{predicted_commit_sha}:{destination_ref}"
    command = (
        os.fspath(executable),
        "-c",
        "color.ui=false",
        "-c",
        "core.quotepath=false",
        "-c",
        f"core.hooksPath={os.fspath(hooks)}",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "http.followRedirects=false",
        "-c",
        "credential.helper=",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "push",
        "--porcelain",
        lease,
        canonical_remote_url,
        refspec,
    )
    if "--force" in command or any(item.startswith("+") for item in command):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "unconditional force-push syntax is forbidden"
        )
    try:
        result = run_bounded_subprocess(
            command,
            cwd=Path(workspace),
            env=environment,
            stdin_bytes=None,
            timeout_seconds=60,
            max_output_bytes=_MAX_PUSH_OUTPUT_BYTES,
            stdout_prefix_bytes=_MAX_PUSH_OUTPUT_BYTES,
            stderr_prefix_bytes=_MAX_PUSH_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "bounded remote push process failed"
        ) from exc
    finally:
        try:
            runtime.verify()
            runner._verify_isolation()
        except Exception as exc:
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "trusted Git runtime changed during remote push"
            ) from exc
    if (
        result.returncode != 0
        or result.output_limit_exceeded
        or result.timed_out
        or result.stdout.truncated
        or result.stderr.truncated
    ):
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "exact create-only remote push did not complete cleanly"
        )
    return result


def _verify_remote_ref_exact(
    *,
    runner: Any,
    workspace: Path,
    canonical_remote_url: str,
    destination_ref: str,
    predicted_commit_sha: str,
) -> None:
    args = (
        "-c",
        "protocol.https.allow=always",
        "-c",
        "http.followRedirects=false",
        "-c",
        "credential.helper=",
        "ls-remote",
        "--refs",
        canonical_remote_url,
        destination_ref,
    )
    try:
        output = runner.run(
            args,
            cwd=Path(workspace),
            maximum=_MAX_REMOTE_OUTPUT_BYTES,
            timeout_seconds=30,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "post-write remote ref verification failed"
        ) from exc
    expected = f"{predicted_commit_sha}\t{destination_ref}\n".encode("ascii")
    if output != expected:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "remote ref does not equal the exact published commit"
        )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[PilotExactTaskRemotePublicationCredentialCapability],
        ],
    ] = {}

    def mark(transaction: Any, capability: PilotExactTaskRemotePublicationCredentialCapability) -> None:
        key = id(transaction)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            transaction.sha256,
            weakref.ref(transaction, cleanup),
            weakref.ref(capability),
        )

    def get(transaction: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(transaction))
        if entry is None:
            return None
        pid, digest, transaction_ref, capability_ref = entry
        capability = capability_ref()
        if (
            pid != os.getpid()
            or transaction_ref() is not transaction
            or capability is None
            or capability.capability_authenticated is not True
            or capability.sha256 != transaction.credential_capability_sha256
            or transaction.sha256 != digest
        ):
            return None
        return MappingProxyType({"remote_publication_credential_capability": capability})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_write_transaction_authenticated,
    _get_live_remote_publication_write_transaction_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationWriteTransaction:
    credential_capability_sha256: str
    remote_write_reservation_sha256: str
    prewrite_state_observation_sha256: str
    target_attestation_sha256: str
    authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    canonical_remote_url: str
    destination_ref: str
    expected_old_remote_sha: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    push_stdout_sha256: str
    push_stderr_sha256: str
    push_total_output_bytes: int
    started_at_utc: str
    pushed_at_utc: str
    verified_at_utc: str
    host_replay_guard_committed: bool = True
    remote_publication_authorization_consumed: bool = True
    remote_write_slot_consumed: bool = True
    credential_broker_freshly_verified: bool = True
    credential_broker_invoked_by_git_only: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    fresh_remote_state_revalidated_before_write: bool = True
    create_only_compare_and_swap_performed: bool = True
    unconditional_force_push_forbidden: bool = True
    remote_write_performed: bool = True
    push_performed: bool = True
    remote_ref_verified: bool = True
    remote_publication_completed: bool = True
    separate_pr_mutation_authorization_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_SCHEMA:
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction schema is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY:
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction authority is unsupported"
            )
        for name in (
            "credential_capability_sha256",
            "remote_write_reservation_sha256",
            "prewrite_state_observation_sha256",
            "target_attestation_sha256",
            "authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "push_stdout_sha256",
            "push_stderr_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.expected_old_remote_sha, name="expected_old_remote_sha", allow_zero=True)
        if (
            self.expected_old_remote_sha
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_EXPECTED_OLD_SHA
            or self.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
            or _REF.fullmatch(self.destination_ref) is None
            or not self.destination_ref.endswith(self.remote_publication_nonce_sha256)
            or isinstance(self.push_total_output_bytes, bool)
            or not isinstance(self.push_total_output_bytes, int)
            or self.push_total_output_bytes < 0
            or self.push_total_output_bytes > _MAX_PUSH_OUTPUT_BYTES
        ):
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction binding is invalid"
            )
        started = _utc(self.started_at_utc, name="started_at_utc")
        pushed = _utc(self.pushed_at_utc, name="pushed_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        if pushed < started or verified < pushed:
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote transaction timestamps are not monotonic"
            )
        required_true = (
            "host_replay_guard_committed",
            "remote_publication_authorization_consumed",
            "remote_write_slot_consumed",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_by_git_only",
            "fresh_remote_state_revalidated_before_write",
            "create_only_compare_and_swap_performed",
            "unconditional_force_push_forbidden",
            "remote_write_performed",
            "push_performed",
            "remote_ref_verified",
            "remote_publication_completed",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "completed remote transaction cannot retain mutation authority"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_remote_publication_write_transaction_inputs(self) is not None

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
    ) -> "PilotExactTaskRemotePublicationWriteTransaction":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationWriteTransactionError(
                "remote publication transaction fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _execute_verified_pilot_exact_task_remote_publication_write(
    *,
    credential_capability: PilotExactTaskRemotePublicationCredentialCapability,
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskRemotePublicationWriteTransaction:
    (
        capability,
        reservation,
        supplied_observation,
        attestation,
        publication_inputs,
        descriptor,
    ) = _require_live_capability(credential_capability)
    started_at = now_provider()
    _require_transaction_window(capability, at_utc=started_at)

    fresh_observation = _fresh_remote_absence(
        supplied_observation=supplied_observation,
        attestation=attestation,
        now_provider=now_provider,
    )
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    runner = publication_inputs.get("git_runner")
    workspace = publication_inputs.get("workspace_root")
    if runner is None or workspace is None:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "trusted Git runner/workspace is unavailable"
        )
    result = _brokered_push(
        runner=runner,
        workspace=Path(workspace),
        broker_path=broker_path,
        predicted_commit_sha=capability.predicted_commit_sha,
        canonical_remote_url=capability.canonical_remote_url,
        destination_ref=capability.destination_ref,
    )
    pushed_at = now_provider()
    _verify_remote_ref_exact(
        runner=runner,
        workspace=Path(workspace),
        canonical_remote_url=capability.canonical_remote_url,
        destination_ref=capability.destination_ref,
        predicted_commit_sha=capability.predicted_commit_sha,
    )
    verified_at = now_provider()
    _require_transaction_window(capability, at_utc=verified_at)

    transaction = PilotExactTaskRemotePublicationWriteTransaction(
        credential_capability_sha256=capability.sha256,
        remote_write_reservation_sha256=reservation.sha256,
        prewrite_state_observation_sha256=fresh_observation.sha256,
        target_attestation_sha256=capability.target_attestation_sha256,
        authorization_proof_sha256=capability.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=(
            capability.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            capability.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=capability.remote_publication_nonce_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        canonical_remote_url=capability.canonical_remote_url,
        destination_ref=capability.destination_ref,
        expected_old_remote_sha=capability.expected_old_remote_sha,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        push_stdout_sha256=result.stdout.sha256,
        push_stderr_sha256=result.stderr.sha256,
        push_total_output_bytes=result.total_output_bytes,
        started_at_utc=started_at,
        pushed_at_utc=pushed_at,
        verified_at_utc=verified_at,
    )
    _mark_remote_publication_write_transaction_authenticated(
        transaction,
        capability,
    )
    if transaction.transaction_authenticated is not True:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "remote publication transaction lost live capability provenance"
        )
    return transaction


def execute_pilot_exact_task_remote_publication_write(
    credential_capability: PilotExactTaskRemotePublicationCredentialCapability,
) -> PilotExactTaskRemotePublicationWriteTransaction:
    """Perform one exact create-only remote Git publication transaction."""
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationWriteTransactionError(
            "remote publication transaction requires an elevated host operator"
        ) from exc
    return _execute_verified_pilot_exact_task_remote_publication_write(
        credential_capability=credential_capability,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_EXPECTED_OLD_SHA",
    "PilotExactTaskRemotePublicationWriteTransactionError",
    "PilotExactTaskRemotePublicationWriteTransaction",
    "execute_pilot_exact_task_remote_publication_write",
]
