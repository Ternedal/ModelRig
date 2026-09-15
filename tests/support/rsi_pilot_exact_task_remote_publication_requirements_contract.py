"""Adversarial contract for ADR-DC-049 inert remote-publication requirements."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_ref_update as ref_update,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_requirements as publication,
)
from rsi_pilot_exact_task_local_commit_ref_update_contract import (  # noqa: E402
    TARGET_REF,
    _live_object_write,
    _ref_update_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-049 unexpectedly accepted unsafe publication authority")


def _live_ref_update():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        object_receipt,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_object_write()
    ref_ledger_temp = tempfile.TemporaryDirectory(
        prefix="rsi-local-commit-ref-update-for-publication-requirements-"
    )
    ledger = ref_update._PilotExactTaskLocalCommitRefUpdateLedger(
        Path(ref_ledger_temp.name).resolve()
    )
    _calls, _updates, reader = _ref_update_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
        predicted_commit_sha=identity.predicted_commit_sha,
        root_tree_sha=identity.root_tree_sha,
    )
    times = iter(
        (
            "2026-09-15T05:34:09Z",
            "2026-09-15T05:34:10Z",
            "2026-09-15T05:34:11Z",
        )
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = ref_update._attach_verified_pilot_exact_task_local_commit(
            object_write_receipt=object_receipt,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert receipt.ref_update_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        ref_ledger_temp,
        receipt,
        identity,
        task,
        fixture,
        reader,
    )


def _publication_reader(
    *,
    base_reader,
    repository: str,
    remote_url: str | None = None,
    drift_remote: bool = False,
):
    calls: list[tuple[str, ...]] = []
    remote_calls = 0
    normal = remote_url or f"git@github.com:{repository}.git"

    def run(args, *, cwd, stdin=None, **kwargs):
        nonlocal remote_calls
        args = tuple(args)
        calls.append(args)
        if args == ("remote", "get-url", "--push", "origin"):
            remote_calls += 1
            value = normal
            if drift_remote and remote_calls >= 2:
                value = f"https://github.com/{repository}"
            return (value + "\n").encode("utf-8")
        return base_reader(args, cwd=cwd, stdin=stdin, **kwargs)

    def remote_count() -> int:
        return remote_calls

    return calls, remote_count, run


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        ref_ledger_temp,
        ref_receipt,
        identity,
        task,
        fixture,
        ref_reader,
    ) = _live_ref_update()
    try:
        calls, remote_count, reader = _publication_reader(
            base_reader=ref_reader,
            repository=task.repository,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            requirements = (
                publication._build_verified_pilot_exact_task_remote_publication_requirements(
                    ref_update_receipt=ref_receipt,
                    now_provider=lambda: "2026-09-15T05:34:12Z",
                )
            )

        assert len(calls) == 18
        assert remote_count() == 2
        assert requirements.requirements_authenticated is True
        assert requirements.ref_update_receipt_sha256 == ref_receipt.sha256
        assert requirements.object_write_receipt_sha256 == ref_receipt.object_write_receipt_sha256
        assert requirements.write_consumption_receipt_sha256 == ref_receipt.write_consumption_receipt_sha256
        assert requirements.local_commit_object_identity_sha256 == identity.sha256
        assert requirements.local_commit_plan_sha256 == identity.local_commit_plan_sha256
        assert requirements.development_task_sha256 == identity.development_task_sha256
        assert requirements.task_id == identity.task_id
        assert requirements.repository == task.repository
        assert requirements.base_sha == task.base_sha
        assert requirements.root_tree_sha == identity.root_tree_sha
        assert requirements.local_commit_sha == identity.predicted_commit_sha
        assert requirements.local_ref == TARGET_REF
        assert requirements.source_ref == TARGET_REF
        assert requirements.destination_ref == TARGET_REF
        assert requirements.source_ref_sha == identity.predicted_commit_sha
        assert requirements.push_refspec == f"{identity.predicted_commit_sha}:{TARGET_REF}"
        assert requirements.remote_name == "origin"
        assert requirements.remote_provider == "github"
        assert requirements.remote_repository == task.repository
        assert requirements.canonical_remote_url == f"https://github.com/{task.repository}.git"
        assert requirements.source_ref_update_completed_at_utc == "2026-09-15T05:34:11Z"
        assert requirements.requirements_materialized_at_utc == "2026-09-15T05:34:12Z"
        assert requirements.network_access_performed is False
        assert requirements.credential_material_present is False
        assert requirements.fresh_human_remote_publication_authorization_required is True
        assert requirements.one_shot_remote_publication_nonce_required is True
        assert requirements.fresh_remote_head_observation_before_authorization_required is True
        assert requirements.fresh_remote_head_revalidation_before_push_required is True
        assert requirements.fast_forward_only_required is True
        assert requirements.force_push_forbidden is True
        assert requirements.remote_delete_forbidden is True
        assert requirements.tag_publication_forbidden is True
        assert requirements.remote_write_authorized is False
        assert requirements.push_authorized is False
        assert requirements.pr_mutation_authorized is False
        assert requirements.production_activation_authorized is False

        reloaded = publication.PilotExactTaskRemotePublicationRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded == requirements
        assert reloaded.sha256 == requirements.sha256
        assert reloaded.requirements_authenticated is False

        reloaded_ref = ref_update.PilotExactTaskLocalCommitRefUpdateReceipt.from_mapping(
            ref_receipt.to_dict()
        )
        assert reloaded_ref.ref_update_authenticated is False
        _reject(
            lambda: publication._build_verified_pilot_exact_task_remote_publication_requirements(
                ref_update_receipt=reloaded_ref,
                now_provider=lambda: "2026-09-15T05:34:13Z",
            )
        )

        for field, value in (
            ("source_ref_update_authenticated_at_materialization", False),
            ("fresh_local_commit_state_matched", False),
            ("remote_configuration_observed_locally", False),
            ("local_commit_created", False),
            ("network_access_performed", True),
            ("credential_material_present", True),
            ("fast_forward_only_required", False),
            ("force_push_forbidden", False),
            ("remote_delete_forbidden", False),
            ("tag_publication_forbidden", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("source_ref_sha", "a" * 40),
            ("requirements_key_sha256", "b" * 64),
            ("remote_name", "upstream"),
        ):
            _reject(
                lambda field=field, value=value: (
                    publication.PilotExactTaskRemotePublicationRequirements.from_mapping(
                        {**requirements.to_dict(), field: value}
                    )
                )
            )

        assert publication._canonical_github_remote(
            f"git@github.com:{task.repository}.git",
            repository=task.repository,
        ) == f"https://github.com/{task.repository}.git"
        assert publication._canonical_github_remote(
            f"https://github.com/{task.repository}.git",
            repository=task.repository,
        ) == f"https://github.com/{task.repository}.git"
        assert publication._canonical_github_remote(
            f"ssh://git@github.com/{task.repository}.git",
            repository=task.repository,
        ) == f"https://github.com/{task.repository}.git"
        _reject(
            lambda: publication._canonical_github_remote(
                f"https://token@github.com/{task.repository}.git",
                repository=task.repository,
            )
        )
        _reject(
            lambda: publication._canonical_github_remote(
                "https://github.com/other/repository.git",
                repository=task.repository,
            )
        )

        _wrong_calls, _wrong_count, wrong_reader = _publication_reader(
            base_reader=ref_reader,
            repository=task.repository,
            remote_url="https://github.com/other/repository.git",
        )
        with patch.object(fixture["git_runner"], "run", side_effect=wrong_reader):
            _reject(
                lambda: publication._build_verified_pilot_exact_task_remote_publication_requirements(
                    ref_update_receipt=ref_receipt,
                    now_provider=lambda: "2026-09-15T05:34:13Z",
                )
            )

        _drift_calls, drift_count, drift_reader = _publication_reader(
            base_reader=ref_reader,
            repository=task.repository,
            drift_remote=True,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: publication._build_verified_pilot_exact_task_remote_publication_requirements(
                    ref_update_receipt=ref_receipt,
                    now_provider=lambda: "2026-09-15T05:34:13Z",
                )
            )
        assert drift_count() == 2

        _clock_calls, _clock_count, clock_reader = _publication_reader(
            base_reader=ref_reader,
            repository=task.repository,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=clock_reader):
            _reject(
                lambda: publication._build_verified_pilot_exact_task_remote_publication_requirements(
                    ref_update_receipt=ref_receipt,
                    now_provider=lambda: "2026-09-15T05:34:10Z",
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(requirements.to_dict())
        assert set(schema["required"]) == set(requirements.to_dict())
        assert schema["properties"]["network_access_performed"]["const"] is False
        assert schema["properties"]["credential_material_present"]["const"] is False
        assert schema["properties"]["fast_forward_only_required"]["const"] is True
        assert schema["properties"]["force_push_forbidden"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            publication.build_pilot_exact_task_remote_publication_requirements
        ).parameters
        assert tuple(public_parameters) == ("ref_update_receipt",)

        source = inspect.getsource(publication)
        assert '("remote", "get-url", "--push", PILOT_EXACT_TASK_REMOTE_NAME)' in source
        assert '("push",' not in source
        assert '"ls-remote"' not in source
        assert '("fetch",' not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert "credential_helper" not in source
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
