"""ADR-DC-094 public HMAC-verified durable GitHub push-webhook ingress boundary."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Sequence
from . import _improvement_pilot_exact_task_pr_push_webhook_ingress_support as support
from ._improvement_pilot_exact_task_pr_push_webhook_ingress_ledger import PilotExactTaskPrPushWebhookDeliveryReceipt, _PushWebhookLedger, _authenticated

SCHEMA=support.SCHEMA; AUTHORITY=support.AUTHORITY; LEDGER_SCOPE=support.LEDGER_SCOPE
PilotExactTaskPrPushWebhookIngressError=support.PilotExactTaskPrPushWebhookIngressError
_require_header_pairs=support.require_header_pairs

def _ingest_verified_pilot_exact_task_pr_push_webhook(*,headers:Sequence[Sequence[str]],raw_body:bytes,secret_path:Path,ledger:_PushWebhookLedger,now_provider:Any,require_host_control:bool)->PilotExactTaskPrPushWebhookDeliveryReceipt:
    normalized_headers=support.require_header_pairs(headers)
    if not isinstance(raw_body,bytes) or not 2<=len(raw_body)<=support.MAX_BODY_BYTES: raise PilotExactTaskPrPushWebhookIngressError("raw webhook body invalid")
    secret=support.read_secret_bytes(secret_path,require_host_control=require_host_control)
    try: support.verify_hmac(secret=secret,raw_body=raw_body,signature_header=normalized_headers["x-hub-signature-256"])
    finally: del secret
    try: payload=json.loads(raw_body.decode("utf-8",errors="strict"))
    except (UnicodeError,json.JSONDecodeError) as exc: raise PilotExactTaskPrPushWebhookIngressError("authenticated webhook body is invalid JSON") from exc
    push=support.normalized_push(payload); guid=support.canonical_delivery_guid(normalized_headers["x-github-delivery"])
    signature_sha=hashlib.sha256(normalized_headers["x-hub-signature-256"].encode("ascii")).hexdigest()
    header={"delivery_guid":guid,"hook_id":int(normalized_headers["x-github-hook-id"]),"hook_installation_target_type":normalized_headers["x-github-hook-installation-target-type"],"hook_installation_target_id":int(normalized_headers["x-github-hook-installation-target-id"]),"event":normalized_headers["x-github-event"],"signature_header_sha256":signature_sha}
    received_at=now_provider(); support.utc(received_at,name="received_at_utc")
    value=PilotExactTaskPrPushWebhookDeliveryReceipt(
        ledger_root_path_sha256=support.path_sha256(ledger.root),secret_path_sha256=support.path_sha256(secret_path),delivery_guid=guid,
        hook_id=header["hook_id"],hook_installation_target_type=header["hook_installation_target_type"],hook_installation_target_id=header["hook_installation_target_id"],event=header["event"],signature_header_sha256=signature_sha,
        raw_body_sha256=hashlib.sha256(raw_body).hexdigest(),raw_body_byte_count=len(raw_body),canonical_payload_sha256=hashlib.sha256(support.canonical(payload).encode()).hexdigest(),normalized_push_sha256=support.normalized_push_sha256(push),
        repository_id=push["repository_id"],repository=push["repository"],ref=push["ref"],before_sha=push["before_sha"],after_sha=push["after_sha"],created=push["created"],deleted=push["deleted"],forced=push["forced"],sender_login=push["sender_login"],sender_user_id=push["sender_user_id"],sender_user_node_id_sha256=push["sender_user_node_id_sha256"],
        header_inventory_sha256=hashlib.sha256(support.canonical(header).encode()).hexdigest(),received_at_utc=received_at,
    )
    path=ledger.commit(value)
    from ._improvement_pilot_exact_task_pr_push_webhook_ingress_ledger import _mark_authenticated
    _mark_authenticated(value,path)
    if value.receipt_authenticated is not True: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery lost durable authentication")
    return value

def ingest_pilot_exact_task_pr_push_webhook(headers:Sequence[Sequence[str]],raw_body:bytes)->PilotExactTaskPrPushWebhookDeliveryReceipt:
    ledger=_PushWebhookLedger(support.canonical_ledger_root(),require_host_control=True)
    return _ingest_verified_pilot_exact_task_pr_push_webhook(headers=headers,raw_body=raw_body,secret_path=support.canonical_secret_path(),ledger=ledger,now_provider=support.now_utc_seconds,require_host_control=True)
def load_pilot_exact_task_pr_push_webhook_delivery(delivery_guid:str)->PilotExactTaskPrPushWebhookDeliveryReceipt:
    return _PushWebhookLedger(support.canonical_ledger_root(),require_host_control=True).load(delivery_guid)

__all__=["SCHEMA","AUTHORITY","LEDGER_SCOPE","PilotExactTaskPrPushWebhookIngressError","PilotExactTaskPrPushWebhookDeliveryReceipt","ingest_pilot_exact_task_pr_push_webhook","load_pilot_exact_task_pr_push_webhook_delivery"]
