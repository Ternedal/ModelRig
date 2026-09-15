"""Adversarial contract for hardened ADR-DC-075 reviewer-write transaction."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for path in (SUPPORT, DEV):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_credential_capability as capability_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_transaction as transaction  # noqa: E402
from kaliv_dev_control.bounded_subprocess import (  # noqa: E402
    BoundedStreamEvidence,
    BoundedSubprocessResult,
)
import rsi_pilot_exact_task_pr_reviewer_write_credential_capability_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-write-transaction-v1.schema.json"
)
UPDATED = "2026-09-15T06:25:42Z"


def _reject(fn) -> None:
    try:
        fn()
    except (
        transaction.PilotExactTaskPrReviewerWriteTransactionError,
        capability_boundary.PilotExactTaskPrReviewerWriteCredentialCapabilityError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-075 unexpectedly accepted unsafe reviewer-write transaction")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def _live_capability():
    preflight, parent_temp, cleanup = parent._live_preflight()
    write_temp = TemporaryDirectory(prefix="rsi-write-075-cap-")
    broker_path = Path(write_temp.name) / "reviewer-write-broker"
    broker_bytes = b"reviewer-write-broker-075-hardened-fixture"
    broker_path.write_bytes(broker_bytes)
    broker_path.chmod(0o755)
    capability = parent._materialize(
        preflight,
        parent._descriptor(broker_path, broker_bytes),
        at="2026-09-15T06:25:39Z",
    )
    assert capability.capability_authenticated is True
    return capability, broker_path, broker_bytes, write_temp, parent_temp, cleanup


def _fresh_reader(capability):
    def read(*, reservation_receipt, reviewer_target, reviewer_handoff_requirements):
        del reviewer_handoff_requirements
        assert reservation_receipt.pull_request_number == capability.pull_request_number
        return {
            "pr_request_url_sha256": hashlib.sha256(
                capability.pull_request_api_url.encode("utf-8")
            ).hexdigest(),
            "pr_response_body_sha256": hashlib.sha256(b"fresh-075").hexdigest(),
            "pr_response_etag_sha256": hashlib.sha256(b"fresh-etag-075").hexdigest(),
            "pull_request_author_login": capability.pull_request_author_login,
            "pull_request_author_user_id": capability.pull_request_author_user_id,
            "observed_updated_at_utc": reviewer_target.ready_updated_at_utc,
            "requested_reviewer_count": 0,
            "requested_team_count": 0,
        }

    return read


def _runner(capability, calls):
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
        del cwd, timeout_seconds, max_output_bytes, stdout_prefix_bytes, stderr_prefix_bytes
        args = tuple(command)
        request = json.loads(stdin_bytes.decode("utf-8"))
        calls.append((args, dict(env), request))
        request_sha = hashlib.sha256(stdin_bytes).hexdigest()
        assert args[1:] == (
            "--protocol",
            "github-rest-reviewer-write-broker-v1",
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert request["operation"] == "request-pull-request-reviewer"
        assert request["reviewers"] == [capability.reviewer_login]
        assert request["team_reviewers"] == []
        assert request["head_sha"] == capability.predicted_commit_sha
        assert request["reviewer_write_credential_capability_sha256"] == capability.sha256
        assert request["request_path"] == (
            f"/repos/Ternedal/ModelRig/pulls/{capability.pull_request_number}/requested_reviewers"
        )
        assert not any(
            marker in key.upper()
            for key in env
            for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
        )
        response = {
            "schema": transaction.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA,
            "status": "reviewer-requested",
            "operation": "request-pull-request-reviewer",
            "request_sha256": request_sha,
            "reviewer_write_credential_capability_sha256": capability.sha256,
            "repository": capability.repository,
            "pull_request_number": capability.pull_request_number,
            "head_sha": capability.predicted_commit_sha,
            "reviewer_login": capability.reviewer_login,
            "reviewer_user_id": capability.reviewer_user_id,
            "reviewer_request_nonce_sha256": capability.reviewer_request_nonce_sha256,
            "requested_reviewer_count": 1,
            "requested_team_count": 0,
            "updated_at_utc": UPDATED,
        }
        stdout = json.dumps(
            response,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return BoundedSubprocessResult(
            args=args,
            returncode=0,
            stdout=_stream(stdout),
            stderr=_stream(b""),
            total_output_bytes=len(stdout),
            output_limit_exceeded=False,
            timed_out=False,
            process_tree_terminated=False,
        )

    return run


def _readback(**kwargs):
    assert kwargs["expected_updated_at_utc"] == UPDATED
    return {
        "response_body_sha256": hashlib.sha256(b"post-075").hexdigest(),
        "response_etag_sha256": hashlib.sha256(b"post-etag-075").hexdigest(),
        "updated_at_utc": UPDATED,
        "requested_reviewer_count": 1,
        "requested_team_count": 0,
    }


def _times():
    return iter(
        (
            "2026-09-15T06:25:40Z",
            "2026-09-15T06:25:40Z",
            "2026-09-15T06:25:42Z",
            "2026-09-15T06:25:43Z",
        )
    ).__next__


def _execute(capability, ledger, calls, *, readback=_readback):
    return transaction._execute_verified_pilot_exact_task_pr_reviewer_write(
        reviewer_write_credential_capability=capability,
        ledger=ledger,
        pr_state_reader=_fresh_reader(capability),
        subprocess_runner=_runner(capability, calls),
        readback_reader=readback,
        now_provider=_times(),
        broker_host_control_required=False,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    capability, broker_path, broker_bytes, write_temp, parent_temp, cleanup = (
        _live_capability()
    )
    ok_temp = TemporaryDirectory(prefix="rsi-write-075-ok-")
    tamper_temp = TemporaryDirectory(prefix="rsi-write-075-tamper-")
    ambiguous_temp = TemporaryDirectory(prefix="rsi-write-075-ambiguous-")
    try:
        calls = []
        ledger = transaction._TransactionLedger(Path(ok_temp.name))
        result = _execute(capability, ledger, calls)
        assert result.transaction_authenticated is True
        assert result.reviewer_write_credential_capability_sha256 == capability.sha256
        assert result.reviewer_request_nonce_sha256 == capability.reviewer_request_nonce_sha256
        assert result.reviewer_request_performed is True
        assert result.exact_reviewer_set_verified is True
        assert result.team_reviewers_absent_verified is True
        assert result.nonce_reusable is False
        assert result.reviewer_mutation_authorized is False
        assert len(calls) == 1

        reloaded = transaction.PilotExactTaskPrReviewerWriteTransaction.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.transaction_authenticated is False

        # Durable completion rejects a second attempt before another broker call.
        _reject(lambda: _execute(capability, ledger, calls))
        assert len(calls) == 1

        replayed_capability = (
            capability_boundary.PilotExactTaskPrReviewerWriteCredentialCapability.from_mapping(
                capability.to_dict()
            )
        )
        assert replayed_capability.capability_authenticated is False
        _reject(lambda: transaction._require_live_capability(replayed_capability))

        # Public transaction window is deliberately stricter than materialization.
        _reject(
            lambda: transaction._require_transaction_window(
                capability,
                at_utc="2026-09-15T06:25:50Z",
            )
        )

        # A broker change is checked only after the durable start marker. It burns
        # the nonce even though no broker invocation occurs, preventing a later
        # silent retry after an integrity failure.
        broker_path.write_bytes(broker_bytes + b"-tampered")
        broker_path.chmod(0o755)
        tamper_calls = []
        tamper_ledger = transaction._TransactionLedger(Path(tamper_temp.name))
        _reject(lambda: _execute(capability, tamper_ledger, tamper_calls))
        assert tamper_calls == []
        assert tamper_ledger._start_path(capability.reviewer_request_nonce_sha256).is_file()
        assert not tamper_ledger._final_path(capability.reviewer_request_nonce_sha256).exists()
        broker_path.write_bytes(broker_bytes)
        broker_path.chmod(0o755)
        _reject(lambda: _execute(capability, tamper_ledger, tamper_calls))
        assert tamper_calls == []

        # If the broker may have succeeded but independent readback fails, the
        # start marker remains and automatic retry cannot invoke the broker twice.
        ambiguous_calls = []
        ambiguous_ledger = transaction._TransactionLedger(Path(ambiguous_temp.name))

        def failed_readback(**kwargs):
            del kwargs
            raise transaction.PilotExactTaskPrReviewerWriteTransactionError(
                "simulated ambiguous post-write readback failure"
            )

        _reject(
            lambda: _execute(
                capability,
                ambiguous_ledger,
                ambiguous_calls,
                readback=failed_readback,
            )
        )
        assert len(ambiguous_calls) == 1
        assert ambiguous_ledger._start_path(
            capability.reviewer_request_nonce_sha256
        ).is_file()
        assert not ambiguous_ledger._final_path(
            capability.reviewer_request_nonce_sha256
        ).exists()
        _reject(lambda: _execute(capability, ambiguous_ledger, ambiguous_calls))
        assert len(ambiguous_calls) == 1

        # Missing immutable reviewer node identity must fail closed.
        _, _, _, _, _, requirements, _ = transaction._require_live_capability(capability)
        missing_node_document = {
            "number": capability.pull_request_number,
            "url": capability.pull_request_api_url,
            "html_url": capability.pull_request_html_url,
            "node_id": "synthetic-pr-node",
            "state": "open",
            "closed_at": None,
            "merged_at": None,
            "draft": False,
            "title": requirements.pr_title,
            "body": requirements.pr_body,
            "maintainer_can_modify": False,
            "updated_at": UPDATED,
            "user": {
                "login": capability.pull_request_author_login,
                "id": capability.pull_request_author_user_id,
            },
            "head": {
                "ref": capability.head_branch,
                "sha": capability.predicted_commit_sha,
                "repo": {"full_name": capability.repository},
            },
            "base": {
                "ref": capability.base_branch,
                "repo": {"full_name": capability.repository},
            },
            "requested_reviewers": [
                {
                    "login": capability.reviewer_login,
                    "id": capability.reviewer_user_id,
                    "type": "User",
                }
            ],
            "requested_teams": [],
        }
        _reject(
            lambda: transaction._validate_post_request_document(
                document=missing_node_document,
                headers={},
                payload=b"{}",
                capability=capability,
                requirements=requirements,
                expected_updated_at_utc=UPDATED,
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            transaction.PilotExactTaskPrReviewerWriteTransaction.__dataclass_fields__
        )
        assert len(fields) == 71
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["reviewer_request_performed"]["const"] is True
        assert schema["properties"]["nonce_reusable"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                transaction.execute_pilot_exact_task_pr_reviewer_write
            ).parameters
        ) == ("reviewer_write_credential_capability",)
        source = inspect.getsource(transaction)
        assert "UrllibReadOnlyTransport" in source
        assert "reviewer_write_credential_capability_sha256" in source
        assert "reviewer immutable node identity is missing or changed" in source
        assert source.index("ledger.begin(start)") < source.index(
            "_fresh_broker_binary("
        )
        assert "urllib.request" not in source
        assert "merge_pull_request(" not in source
        assert "label_pr(" not in source
    finally:
        ambiguous_temp.cleanup()
        tamper_temp.cleanup()
        ok_temp.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
