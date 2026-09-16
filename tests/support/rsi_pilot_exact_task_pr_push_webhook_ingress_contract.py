"""Adversarial contract for ADR-DC-094 HMAC push-webhook ingress ledger."""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "devcontrol" / "src"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

from kaliv_dev_control import improvement_pilot_exact_task_pr_push_webhook_ingress as ingress
from kaliv_dev_control import _improvement_pilot_exact_task_pr_push_webhook_ingress_support as ingress_support
from kaliv_dev_control import _improvement_pilot_exact_task_pr_push_webhook_ingress_ledger as ingress_ledger

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-push-webhook-ingress-v1.schema.json"
SECRET = b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
GUID = "123e4567-e89b-12d3-a456-426614174000"
AFTER = "a" * 40
BEFORE = "b" * 40


def _reject(fn, *, contains=None):
    try:
        fn()
    except (ingress.PilotExactTaskPrPushWebhookIngressError, ValueError, TypeError, OSError, AssertionError) as exc:
        if contains is not None:
            assert contains.lower() in str(exc).lower(), (contains, str(exc))
        return
    raise AssertionError("ADR-DC-094 accepted unsafe webhook ingress")


def _payload(*, repository="Ternedal/ModelRig", repository_id=1287914122, sender_login="reviewer-a", sender_id=9001, sender_node="U_sender_094", ref="refs/heads/agent/rsi/remote-candidate/" + "c" * 64, before=BEFORE, after=AFTER, created=False, deleted=False, forced=False):
    return {
        "ref": ref,
        "before": before,
        "after": after,
        "created": created,
        "deleted": deleted,
        "forced": forced,
        "repository": {"id": repository_id, "full_name": repository},
        "sender": {"login": sender_login, "id": sender_id, "node_id": sender_node},
        # Deliberately different: ADR-094 must bind GitHub webhook sender, not pusher metadata.
        "pusher": {"name": "not-the-sender", "email": "nobody@example.invalid"},
    }


def _body(payload=None):
    value = _payload() if payload is None else payload
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _headers(raw_body: bytes, *, guid=GUID, event="push", target_type="repository", target_id="1287914122", hook_id="424242", signature=None):
    if signature is None:
        signature = "sha256=" + hmac.new(SECRET, raw_body, hashlib.sha256).hexdigest()
    return [
        ("X-GitHub-Delivery", guid),
        ("X-GitHub-Event", event),
        ("X-GitHub-Hook-ID", hook_id),
        ("X-GitHub-Hook-Installation-Target-Type", target_type),
        ("X-GitHub-Hook-Installation-Target-ID", target_id),
        ("X-Hub-Signature-256", signature),
        ("User-Agent", "GitHub-Hookshot/094-test"),
        ("Content-Type", "application/json; charset=utf-8"),
    ]


def _ingest(secret_path: Path, ledger, raw_body: bytes, headers=None, *, at="2026-09-16T04:40:00Z"):
    return ingress._ingest_verified_pilot_exact_task_pr_push_webhook(
        headers=_headers(raw_body) if headers is None else headers,
        raw_body=raw_body,
        secret_path=secret_path,
        ledger=ledger,
        now_provider=lambda: at,
        require_host_control=False,
    )


def run_contract():
    if os.name == "nt":
        return
    with tempfile.TemporaryDirectory(prefix="rsi-webhook-094-") as directory:
        root = Path(directory)
        secret_path = root / "webhook-secret"
        secret_path.write_bytes(SECRET)
        secret_path.chmod(0o600)
        ledger_root = root / "ledger"
        ledger_root.mkdir()
        ledger = ingress._PushWebhookLedger(ledger_root, require_host_control=False)
        raw = _body()

        result = _ingest(secret_path, ledger, raw)
        assert result.receipt_authenticated is True
        assert result.delivery_guid == GUID
        assert result.repository == "Ternedal/ModelRig" and result.repository_id == 1287914122
        assert result.ref.startswith("refs/heads/")
        assert result.before_sha == BEFORE and result.after_sha == AFTER
        assert result.sender_login == "reviewer-a" and result.sender_user_id == 9001
        assert result.sender_identity_used is True and result.pusher_identity_used is False
        assert result.hmac_sha256_verified is True
        assert result.raw_body_verified_before_parse is True
        assert result.webhook_delivery_ingested is True
        assert result.webhook_stream_completeness_attested is False
        assert result.exact_head_last_push_selected is False
        assert result.last_push_actor_policy_evaluated is False
        assert result.last_push_actor_attested is False
        assert result.merge_authorized is False and result.production_activation_authorized is False
        record_path = ledger.path(GUID)
        record_bytes = record_path.read_bytes()
        assert SECRET not in record_bytes
        assert raw not in record_bytes
        assert result.raw_body_sha256 == hashlib.sha256(raw).hexdigest()

        replayed = ingress.PilotExactTaskPrPushWebhookDeliveryReceipt.from_mapping(result.to_dict())
        assert replayed == result and replayed.receipt_authenticated is False

        ingress._authenticated.clear()
        loaded = ledger.load(GUID)
        assert loaded == result and loaded.receipt_authenticated is True

        # HMAC must fail before JSON parsing.
        invalid_json = b"{not-json"
        wrong_sig = _headers(invalid_json, signature="sha256=" + "0" * 64)
        _reject(lambda: _ingest(secret_path, ledger, invalid_json, wrong_sig), contains="HMAC")
        good_sig_bad_json = _headers(invalid_json)
        _reject(lambda: _ingest(secret_path, ledger, invalid_json, good_sig_bad_json), contains="invalid JSON")

        duplicate = _headers(raw) + [("x-hub-signature-256", _headers(raw)[5][1])]
        _reject(lambda: ingress._require_header_pairs(duplicate), contains="duplicate")
        _reject(lambda: _ingest(secret_path, ledger, raw, _headers(raw, event="issues")))
        _reject(lambda: _ingest(secret_path, ledger, raw, _headers(raw, target_type="organization")))
        _reject(lambda: _ingest(secret_path, ledger, raw, _headers(raw, target_id="1")))

        wrong_repo = _body(_payload(repository="Other/Repo"))
        _reject(lambda: _ingest(secret_path, ledger, wrong_repo, _headers(wrong_repo)))
        wrong_repo_id = _body(_payload(repository_id=1))
        _reject(lambda: _ingest(secret_path, ledger, wrong_repo_id, _headers(wrong_repo_id)))

        # Create-once delivery GUID makes replay non-idempotent and fail-closed.
        _reject(lambda: _ingest(secret_path, ledger, raw), contains="replay")

        # Receipt structural hashes detect ordinary normalized-field tamper.
        tampered = result.to_dict(); tampered["sender_login"] = "reviewer-b"
        _reject(lambda: ingress.PilotExactTaskPrPushWebhookDeliveryReceipt.from_mapping(tampered), contains="normalized push")
        tampered = result.to_dict(); tampered["header_inventory_sha256"] = "4" * 64
        _reject(lambda: ingress.PilotExactTaskPrPushWebhookDeliveryReceipt.from_mapping(tampered), contains="header inventory")
        tampered = result.to_dict(); tampered["last_push_actor_attested"] = True
        _reject(lambda: ingress.PilotExactTaskPrPushWebhookDeliveryReceipt.from_mapping(tampered), contains="widened")

        # Durable authentication disappears immediately if the record is modified.
        original = record_path.read_bytes()
        record_path.write_bytes(original + b"\n")
        assert loaded.receipt_authenticated is False
        _reject(lambda: ledger.load(GUID))
        record_path.write_bytes(original)
        assert ledger.load(GUID).receipt_authenticated is True

        # Aliased hard-link records fail closed via st_nlink != 1.
        alias = root / "alias.json"
        os.link(record_path, alias)
        try:
            _reject(lambda: ledger.load(GUID))
        finally:
            alias.unlink()
        assert ledger.load(GUID).receipt_authenticated is True

        _reject(lambda: ledger.load("00000000-0000-0000-0000-000000000000"))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(ingress.PilotExactTaskPrPushWebhookDeliveryReceipt.__dataclass_fields__)
        assert len(fields) == 49
        assert set(schema["properties"]) == fields and set(schema["required"]) == fields
        assert schema["properties"]["hmac_sha256_verified"]["const"] is True
        assert schema["properties"]["webhook_stream_completeness_attested"]["const"] is False
        assert schema["properties"]["last_push_actor_attested"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(ingress.ingest_pilot_exact_task_pr_push_webhook).parameters) == ("headers", "raw_body")
        assert tuple(inspect.signature(ingress.load_pilot_exact_task_pr_push_webhook_delivery).parameters) == ("delivery_guid",)
        assert callable(ingress_ledger.require_host_controlled_ledger_root)
        source = "\n".join((inspect.getsource(ingress_support), inspect.getsource(ingress_ledger), inspect.getsource(ingress)))
        assert "hmac.compare_digest" in source and "create_once_file" in source and "O_NOFOLLOW" in source
        for forbidden in (
            "urllib.request", "requests.", "run_bounded_subprocess", 'method="POST"',
            "request_pull_request_reviewers(", "add_review_to_pr(", "resolve_review_thread(",
            "merge_pull_request(", "enable_auto_merge(", "label_pr(",
        ):
            assert forbidden not in source


if __name__ == "__main__":
    run_contract()
