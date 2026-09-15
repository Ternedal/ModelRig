"""Adversarial contract for ADR-DC-058 exact draft-PR create transaction."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_create_transaction as transaction  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_state_observation as observation  # noqa: E402
from kaliv_dev_control.bounded_subprocess import (  # noqa: E402
    BoundedStreamEvidence,
    BoundedSubprocessResult,
)
from rsi_pilot_exact_task_pr_credential_capability_contract import _descriptor  # noqa: E402
from rsi_pilot_exact_task_pr_state_observation_contract import (  # noqa: E402
    _live_observation,
    _reservation_material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-create-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        transaction.PilotExactTaskPrCreateTransactionError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-058 unexpectedly accepted unsafe PR create state")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def _fresh_reader(*, head_branch):
    url = observation._query_url(head_branch=head_branch)
    payload = b"[]"
    etag = 'W/"fresh-058"'
    return {
        "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "response_body_sha256": hashlib.sha256(payload).hexdigest(),
        "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
        "open_pr_match_count": 0,
    }


def _broker_runner(*, number: int, expected_capability, expected_requirements, calls):
    def run(
        command,
        *,
        cwd,
        env,
        stdin_bytes,
        timeout_seconds,
        max_output_bytes,
        stdout_prefix_bytes,
        stderr_prefix_bytes,
    ):
        args = tuple(command)
        environment = dict(env)
        request = json.loads(stdin_bytes.decode("utf-8"))
        request_sha256 = hashlib.sha256(stdin_bytes).hexdigest()
        calls.append((args, Path(cwd), environment, request))
        assert Path(cwd).is_absolute()
        assert timeout_seconds == 60
        assert max_output_bytes == 64 * 1024
        assert stdout_prefix_bytes == 64 * 1024
        assert stderr_prefix_bytes == 64 * 1024
        assert args[0].endswith("rsi-github-pr-broker-v1")
        assert args[1:] == (
            "--protocol",
            "github-rest-broker-v1",
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert not any(
            marker in key.upper()
            for key in environment
            for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
        )
        assert request == {
            "schema": transaction.PILOT_EXACT_TASK_PR_CREATE_BROKER_REQUEST_SCHEMA,
            "operation": "create-draft-pull-request",
            "api_origin": "https://api.github.com",
            "repository": "Ternedal/ModelRig",
            "base_branch": "main",
            "head_branch": expected_capability.head_branch,
            "head_sha": expected_capability.predicted_commit_sha,
            "title": expected_requirements.pr_title,
            "body": expected_requirements.pr_body,
            "draft": True,
            "maintainer_can_modify": False,
            "pr_plan_sha256": expected_capability.pr_plan_sha256,
            "pr_mutation_nonce_sha256": expected_capability.pr_mutation_nonce_sha256,
        }
        response = {
            "schema": transaction.PILOT_EXACT_TASK_PR_CREATE_BROKER_RESPONSE_SCHEMA,
            "status": "created",
            "http_status": 201,
            "request_sha256": request_sha256,
            "pr_mutation_nonce_sha256": expected_capability.pr_mutation_nonce_sha256,
            "pull_request_number": number,
            "api_url": f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{number}",
            "html_url": f"https://github.com/Ternedal/ModelRig/pull/{number}",
            "repository": "Ternedal/ModelRig",
            "base_ref": "main",
            "head_ref": expected_capability.head_branch,
            "head_sha": expected_capability.predicted_commit_sha,
            "draft": True,
            "maintainer_can_modify": False,
        }
        stdout = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        stderr = b""
        return BoundedSubprocessResult(
            args=args,
            returncode=0,
            stdout=_stream(stdout),
            stderr=_stream(stderr),
            total_output_bytes=len(stdout),
            output_limit_exceeded=False,
            timed_out=False,
            process_tree_terminated=False,
        )
    return run


def _readback_reader(*, number: int, calls):
    def read(*, pull_request_number, capability, requirements):
        assert pull_request_number == number
        calls.append((pull_request_number, capability.sha256, requirements.sha256))
        return {
            "response_body_sha256": hashlib.sha256(b"readback-058").hexdigest(),
            "response_etag_sha256": hashlib.sha256(b"etag-058").hexdigest(),
            "pull_request_number": number,
            "api_url": f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{number}",
            "html_url": f"https://github.com/Ternedal/ModelRig/pull/{number}",
        }
    return read


class _FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {"ETag": 'W/"readback-058"'}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, maximum: int) -> bytes:
        return self._payload[:maximum]


class _FakeOpener:
    def __init__(self, response) -> None:
        self.response = response
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _reservation_material()
    (
        receipt,
        identity,
        requirements,
        pr_reservation_ledger_temp,
        remote_broker_temp,
        remote_reservation_temp,
        remote_transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    ) = material
    pr_broker_temp = TemporaryDirectory(prefix="rsi-pr-create-broker-058-")
    transaction_temp = TemporaryDirectory(prefix="rsi-pr-create-transaction-058-")
    failure_temp = TemporaryDirectory(prefix="rsi-pr-create-failure-058-")
    try:
        supplied_observation = _live_observation(receipt)
        broker_path = Path(pr_broker_temp.name) / "rsi-github-pr-broker-v1"
        broker_path.write_bytes(b"broker-057")
        descriptor = _descriptor(broker_path)
        pr_capability = capability._materialize_verified_pilot_exact_task_pr_credential_capability(
            pr_state_observation=supplied_observation,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:23:40Z",
        )
        assert pr_capability.capability_authenticated is True

        ledger = transaction._PilotExactTaskPrCreateTransactionLedger(
            Path(transaction_temp.name)
        )
        broker_calls = []
        readback_calls = []
        number = 1458
        times = iter(
            (
                "2026-09-15T06:23:41Z",
                "2026-09-15T06:23:42Z",
                "2026-09-15T06:23:43Z",
                "2026-09-15T06:23:44Z",
                "2026-09-15T06:23:45Z",
            )
        )
        result = transaction._execute_verified_pilot_exact_task_pr_create(
            pr_credential_capability=pr_capability,
            ledger=ledger,
            state_reader=_fresh_reader,
            subprocess_runner=_broker_runner(
                number=number,
                expected_capability=pr_capability,
                expected_requirements=requirements,
                calls=broker_calls,
            ),
            readback_reader=_readback_reader(
                number=number,
                calls=readback_calls,
            ),
            now_provider=lambda: next(times),
            broker_host_control_required=False,
        )

        assert len(broker_calls) == 1
        assert len(readback_calls) == 1
        assert result.transaction_authenticated is True
        assert result.pr_credential_capability_sha256 == pr_capability.sha256
        assert result.pr_mutation_reservation_sha256 == receipt.sha256
        assert result.pr_mutation_requirements_sha256 == requirements.sha256
        assert result.remote_write_transaction_sha256 == receipt.remote_write_transaction_sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.pr_plan_sha256 == requirements.pr_plan_sha256
        assert result.pr_mutation_nonce_sha256 == receipt.pr_mutation_nonce_sha256
        assert result.transaction_key_sha256 == receipt.pr_mutation_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.base_branch == "main"
        assert result.head_branch == requirements.head_branch
        assert result.pull_request_number == number
        assert result.pull_request_api_url.endswith(f"/pulls/{number}")
        assert result.pull_request_html_url.endswith(f"/pull/{number}")
        assert result.started_at_utc == "2026-09-15T06:23:43Z"
        assert result.created_at_utc == "2026-09-15T06:23:44Z"
        assert result.verified_at_utc == "2026-09-15T06:23:45Z"
        assert ledger._start_path(receipt.pr_mutation_nonce_sha256).is_file()
        assert ledger._final_path(receipt.pr_mutation_nonce_sha256).is_file()

        for field in (
            "host_transaction_start_committed",
            "pr_mutation_slot_consumed",
            "fresh_pr_state_revalidated_before_create",
            "no_existing_open_pr_reverified",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "exact_draft_pr_request_performed",
            "pull_request_created",
            "draft_pull_request_created",
            "post_create_readback_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        assert "broker_executable_path" not in serialized
        assert os.fspath(broker_path) not in result.canonical_json()
        reloaded = transaction.PilotExactTaskPrCreateTransaction.from_mapping(
            serialized
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.transaction_authenticated is False

        reloaded_capability = capability.PilotExactTaskPrCredentialCapability.from_mapping(
            pr_capability.to_dict()
        )
        assert reloaded_capability.capability_authenticated is False
        _reject(lambda: transaction._require_live_capability(reloaded_capability))

        # Existing open PR must fail before any durable transaction-start marker.
        untouched_temp = TemporaryDirectory(prefix="rsi-pr-create-existing-058-")
        try:
            untouched_ledger = transaction._PilotExactTaskPrCreateTransactionLedger(
                Path(untouched_temp.name)
            )
            _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_create(
                pr_credential_capability=pr_capability,
                ledger=untouched_ledger,
                state_reader=lambda **_: {
                    "request_url_sha256": "1" * 64,
                    "response_body_sha256": "2" * 64,
                    "response_etag_sha256": "3" * 64,
                    "open_pr_match_count": 1,
                },
                subprocess_runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broker must not run")),
                readback_reader=lambda **_: (_ for _ in ()).throw(AssertionError("readback must not run")),
                now_provider=iter(("2026-09-15T06:23:41Z", "2026-09-15T06:23:42Z")).__next__,
                broker_host_control_required=False,
            ))
            assert list(Path(untouched_temp.name).iterdir()) == []
        finally:
            untouched_temp.cleanup()

        # Once the start marker exists, an ambiguous broker failure permanently
        # burns the automatic retry path for this nonce.
        failure_ledger = transaction._PilotExactTaskPrCreateTransactionLedger(
            Path(failure_temp.name)
        )
        failing_times = iter(
            (
                "2026-09-15T06:23:41Z",
                "2026-09-15T06:23:42Z",
                "2026-09-15T06:23:43Z",
            )
        )
        def failed_broker(command, **kwargs):
            args = tuple(command)
            stderr = b"ambiguous failure"
            return BoundedSubprocessResult(
                args=args,
                returncode=1,
                stdout=_stream(b""),
                stderr=_stream(stderr),
                total_output_bytes=len(stderr),
                output_limit_exceeded=False,
                timed_out=False,
                process_tree_terminated=False,
            )

        _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_create(
            pr_credential_capability=pr_capability,
            ledger=failure_ledger,
            state_reader=_fresh_reader,
            subprocess_runner=failed_broker,
            readback_reader=lambda **_: (_ for _ in ()).throw(AssertionError("readback must not run")),
            now_provider=lambda: next(failing_times),
            broker_host_control_required=False,
        ))
        start_path = failure_ledger._start_path(receipt.pr_mutation_nonce_sha256)
        final_path = failure_ledger._final_path(receipt.pr_mutation_nonce_sha256)
        assert start_path.is_file()
        assert not final_path.exists()

        retry_calls = []
        retry_times = iter(
            (
                "2026-09-15T06:23:41Z",
                "2026-09-15T06:23:42Z",
                "2026-09-15T06:23:43Z",
            )
        )
        _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_create(
            pr_credential_capability=pr_capability,
            ledger=failure_ledger,
            state_reader=_fresh_reader,
            subprocess_runner=_broker_runner(
                number=1459,
                expected_capability=pr_capability,
                expected_requirements=requirements,
                calls=retry_calls,
            ),
            readback_reader=_readback_reader(number=1459, calls=[]),
            now_provider=lambda: next(retry_times),
            broker_host_control_required=False,
        ))
        assert retry_calls == []
        assert start_path.is_file()
        assert not final_path.exists()

        # The broker may not alter any exact create semantics.
        request = transaction._broker_request(
            capability=pr_capability,
            requirements=requirements,
        )
        request_payload = transaction._canonical_bytes(request)
        request_sha256 = hashlib.sha256(request_payload).hexdigest()
        wrong_response = {
            "schema": transaction.PILOT_EXACT_TASK_PR_CREATE_BROKER_RESPONSE_SCHEMA,
            "status": "created",
            "http_status": 201,
            "request_sha256": request_sha256,
            "pr_mutation_nonce_sha256": pr_capability.pr_mutation_nonce_sha256,
            "pull_request_number": 1460,
            "api_url": "https://api.github.com/repos/Ternedal/ModelRig/pulls/1460",
            "html_url": "https://github.com/Ternedal/ModelRig/pull/1460",
            "repository": "Ternedal/ModelRig",
            "base_ref": "main",
            "head_ref": pr_capability.head_branch,
            "head_sha": "1" * 40,
            "draft": True,
            "maintainer_can_modify": False,
        }
        _reject(lambda: transaction._validate_broker_response(
            transaction._canonical_bytes(wrong_response),
            request_sha256=request_sha256,
            capability=pr_capability,
        ))

        # Freshly re-hash the broker; post-capability drift must fail.
        broker_path.write_bytes(b"tampered-after-capability")
        _reject(lambda: transaction._fresh_broker_binary(
            descriptor,
            require_host_control=False,
        ))
        broker_path.write_bytes(b"broker-057")

        # Exercise the production-shaped credential-free GET readback parser.
        document = {
            "number": number,
            "url": f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{number}",
            "html_url": f"https://github.com/Ternedal/ModelRig/pull/{number}",
            "state": "open",
            "draft": True,
            "title": requirements.pr_title,
            "body": requirements.pr_body,
            "maintainer_can_modify": False,
            "head": {
                "ref": pr_capability.head_branch,
                "sha": pr_capability.predicted_commit_sha,
                "repo": {"full_name": "Ternedal/ModelRig"},
            },
            "base": {
                "ref": "main",
                "repo": {"full_name": "Ternedal/ModelRig"},
            },
        }
        http_payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        fake = _FakeOpener(_FakeResponse(http_payload))
        with patch.object(transaction.urllib.request, "build_opener", return_value=fake):
            evidence = transaction._read_created_pr(
                pull_request_number=number,
                capability=pr_capability,
                requirements=requirements,
            )
        assert evidence["pull_request_number"] == number
        assert len(fake.requests) == 1
        http_request, timeout = fake.requests[0]
        assert http_request.get_method() == "GET"
        assert http_request.full_url.endswith(f"/pulls/{number}")
        assert timeout == 20
        lowered = {name.lower() for name in http_request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        wrong_document = dict(document)
        wrong_document["draft"] = False
        wrong_payload = json.dumps(wrong_document, separators=(",", ":")).encode("utf-8")
        fake_wrong = _FakeOpener(_FakeResponse(wrong_payload))
        with patch.object(transaction.urllib.request, "build_opener", return_value=fake_wrong):
            _reject(lambda: transaction._read_created_pr(
                pull_request_number=number,
                capability=pr_capability,
                requirements=requirements,
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["pull_request_created"]["const"] is True
        assert schema["properties"]["draft_pull_request_created"]["const"] is True
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_pr_create
        ).parameters
        assert tuple(public_parameters) == ("pr_credential_capability",)

        source = inspect.getsource(transaction)
        assert 'method="POST"' not in source
        assert "requests.post" not in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert '"Authorization":' not in source
        assert "Bearer " not in source
        assert "shell=True" not in source
        assert "run_bounded_subprocess" in source
        assert 'method="GET"' in source
        assert "_NoRedirectHandler" in source
        assert "create_once_file" in source
    finally:
        failure_temp.cleanup()
        transaction_temp.cleanup()
        pr_broker_temp.cleanup()
        pr_reservation_ledger_temp.cleanup()
        remote_broker_temp.cleanup()
        remote_reservation_temp.cleanup()
        remote_transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
