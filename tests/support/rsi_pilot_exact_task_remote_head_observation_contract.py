"""Adversarial contract for ADR-DC-050 read-only exact remote-head observation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_head_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_requirements as publication  # noqa: E402
from rsi_pilot_exact_task_remote_publication_requirements_contract import (  # noqa: E402
    _live_ref_update,
    _publication_reader,
)

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-remote-head-observation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-050 unexpectedly accepted unsafe remote observation")


def _live_requirements():
    values = _live_ref_update()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, ref_reader,
    ) = values
    _calls, _count, reader = _publication_reader(
        base_reader=ref_reader,
        repository=task.repository,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        requirements = publication._build_verified_pilot_exact_task_remote_publication_requirements(
            ref_update_receipt=ref_receipt,
            now_provider=lambda: "2026-09-15T05:34:12Z",
        )
    assert requirements.requirements_authenticated is True
    return (*values[:-1], reader, requirements)


def _reader(*, base_reader, requirements, operation_root, first, second=None):
    calls: list[tuple[str, ...]] = []
    remote_calls = 0
    fixed = (
        "-c", "protocol.allow=https",
        "-c", "protocol.version=2",
        "-c", "http.followRedirects=false",
        "ls-remote", "--heads",
        requirements.canonical_remote_url,
        requirements.destination_ref,
    )

    def run(args, *, cwd, stdin=None, **kwargs):
        nonlocal remote_calls
        args = tuple(args)
        calls.append(args)
        if args == fixed:
            assert cwd == operation_root
            remote_calls += 1
            selected = first if remote_calls == 1 or second is None else second
            if selected is None:
                return b""
            return f"{selected}\t{requirements.destination_ref}\n".encode("ascii")
        return base_reader(args, cwd=cwd, stdin=stdin, **kwargs)

    return calls, fixed, run


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _live_requirements()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements,
    ) = values
    try:
        calls, fixed, reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
        )
        times = iter(("2026-09-15T05:34:13Z", "2026-09-15T05:34:14Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = observation._observe_verified_pilot_exact_task_remote_head(
                requirements=requirements,
                now_provider=lambda: next(times),
            )

        assert calls.count(fixed) == 2
        assert receipt.observation_authenticated is True
        assert receipt.requirements_sha256 == requirements.sha256
        assert receipt.requirements_key_sha256 == requirements.requirements_key_sha256
        assert receipt.ref_update_receipt_sha256 == requirements.ref_update_receipt_sha256
        assert receipt.task_id == identity.task_id
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_commit_sha == identity.predicted_commit_sha
        assert receipt.source_ref == requirements.source_ref
        assert receipt.destination_ref == requirements.destination_ref
        assert receipt.canonical_remote_url == requirements.canonical_remote_url
        assert receipt.remote_name == "origin"
        assert receipt.remote_provider == "github"
        assert receipt.remote_head_present is True
        assert receipt.remote_head_sha == task.base_sha
        assert receipt.publication_mode == observation.PUBLICATION_MODE_FAST_FORWARD
        assert receipt.first_remote_observation_sha256 == receipt.second_remote_observation_sha256
        assert receipt.local_state_before_sha256 == requirements.post_ref_update_workspace_snapshot_sha256
        assert receipt.local_state_after_sha256 == receipt.local_state_before_sha256
        assert receipt.network_access_performed is True
        assert receipt.credential_material_present is False
        assert receipt.remote_head_observed is True
        assert receipt.remote_head_stable_across_double_observation is True
        assert receipt.local_commit_state_matched is True
        assert receipt.fast_forward_candidate is True
        assert receipt.human_remote_publication_authorization_verified is False
        assert receipt.remote_publication_authorization_consumed is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = observation.PilotExactTaskRemoteHeadObservation.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.observation_authenticated is False

        reloaded_requirements = publication.PilotExactTaskRemotePublicationRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded_requirements.requirements_authenticated is False
        _reject(lambda: observation._observe_verified_pilot_exact_task_remote_head(
            requirements=reloaded_requirements,
            now_provider=lambda: "2026-09-15T05:34:15Z",
        ))

        absent_calls, absent_fixed, absent_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=None,
        )
        absent_times = iter(("2026-09-15T05:34:15Z", "2026-09-15T05:34:16Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=absent_reader):
            absent = observation._observe_verified_pilot_exact_task_remote_head(
                requirements=requirements,
                now_provider=lambda: next(absent_times),
            )
        assert absent_calls.count(absent_fixed) == 2
        assert absent.remote_head_present is False
        assert absent.remote_head_sha is None
        assert absent.publication_mode == observation.PUBLICATION_MODE_CREATE

        unsafe_calls, _unsafe_fixed, unsafe_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first="a" * 40,
        )
        unsafe_times = iter(("2026-09-15T05:34:17Z", "2026-09-15T05:34:18Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=unsafe_reader):
            _reject(lambda: observation._observe_verified_pilot_exact_task_remote_head(
                requirements=requirements,
                now_provider=lambda: next(unsafe_times),
            ))
        assert unsafe_calls

        drift_calls, drift_fixed, drift_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
            second="b" * 40,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(lambda: observation._observe_verified_pilot_exact_task_remote_head(
                requirements=requirements,
                now_provider=lambda: "2026-09-15T05:34:19Z",
            ))
        assert drift_calls.count(drift_fixed) == 2

        malformed = (
            f"{task.base_sha}\t{requirements.destination_ref}\n"
            f"{task.base_sha}\t{requirements.destination_ref}\n"
        ).encode("ascii")
        _reject(lambda: observation._parse_ls_remote(
            malformed, destination_ref=requirements.destination_ref
        ))
        _reject(lambda: observation._parse_ls_remote(
            f"{task.base_sha}\trefs/heads/other\n".encode("ascii"),
            destination_ref=requirements.destination_ref,
        ))

        for field, value in (
            ("network_access_performed", False),
            ("credential_material_present", True),
            ("remote_head_observed", False),
            ("remote_head_stable_across_double_observation", False),
            ("local_commit_state_matched", False),
            ("fast_forward_candidate", False),
            ("human_remote_publication_authorization_verified", True),
            ("remote_publication_authorization_consumed", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("destination_ref", "refs/heads/other"),
            ("local_commit_sha", "c" * 40),
            ("observation_key_sha256", "d" * 64),
        ):
            _reject(lambda field=field, value=value: (
                observation.PilotExactTaskRemoteHeadObservation.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["network_access_performed"]["const"] is True
        assert schema["properties"]["credential_material_present"]["const"] is False
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            observation.observe_pilot_exact_task_remote_head
        ).parameters
        assert tuple(public_parameters) == ("requirements",)
        source = inspect.getsource(observation)
        assert '"ls-remote"' in source
        assert '"protocol.allow=https"' in source
        assert '"http.followRedirects=false"' in source
        assert '("push",' not in source
        assert '("fetch",' not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert "git_runner" not in public_parameters
        assert "remote_name" not in public_parameters
        assert "destination_ref" not in public_parameters
        assert "args" not in public_parameters
    finally:
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
