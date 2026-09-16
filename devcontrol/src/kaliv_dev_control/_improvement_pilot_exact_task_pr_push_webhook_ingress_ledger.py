"""Durable receipt/ledger for ADR-DC-094 push-webhook ingress."""
from __future__ import annotations
import hashlib, json, os, stat, weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from .durable_publication import DurablePublicationError, create_once_file
from ._improvement_pilot_exact_task_pr_push_webhook_ingress_support import *

_authenticated:dict[int,tuple[int,str,weakref.ReferenceType[Any],Path]]={}
def _mark_authenticated(value:Any,path:Path)->None:
    key=id(value)
    def cleanup(_:weakref.ReferenceType[Any])->None: _authenticated.pop(key,None)
    _authenticated[key]=(os.getpid(),value.sha256,weakref.ref(value,cleanup),path)
def _authenticated_record(value:Any)->bool:
    row=_authenticated.get(id(value))
    if row is None: return False
    pid,digest,ref,path=row
    if pid!=os.getpid() or ref() is not value or value.sha256!=digest: return False
    candidate=Path(path)
    if not candidate.is_absolute() or candidate.is_symlink(): return False
    try: fd=os.open(candidate,os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
    except OSError: return False
    try:
        before=os.fstat(fd); expected=value.canonical_json().encode()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=len(expected) or before.st_size>MAX_RECORD_BYTES: return False
        remaining=before.st_size; chunks=[]
        while remaining:
            chunk=os.read(fd,min(65536,remaining))
            if not chunk: return False
            chunks.append(chunk); remaining-=len(chunk)
        if os.read(fd,1): return False
        after=os.fstat(fd)
        return (before.st_dev,before.st_ino,before.st_size)==(after.st_dev,after.st_ino,after.st_size) and b"".join(chunks)==expected
    except OSError: return False
    finally: os.close(fd)
if hasattr(os,"register_at_fork"): os.register_at_fork(after_in_child=_authenticated.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrPushWebhookDeliveryReceipt:
    ledger_root_path_sha256:str; secret_path_sha256:str; delivery_guid:str; hook_id:int
    hook_installation_target_type:str; hook_installation_target_id:int; event:str
    signature_header_sha256:str; raw_body_sha256:str; raw_body_byte_count:int
    canonical_payload_sha256:str; normalized_push_sha256:str; repository_id:int; repository:str
    ref:str; before_sha:str; after_sha:str; created:bool; deleted:bool; forced:bool
    sender_login:str; sender_user_id:int; sender_user_node_id_sha256:str
    header_inventory_sha256:str; received_at_utc:str
    hmac_sha256_verified:bool=True; raw_body_verified_before_parse:bool=True
    duplicate_security_headers_rejected:bool=True; sender_identity_used:bool=True
    pusher_identity_used:bool=False; webhook_delivery_ingested:bool=True
    durable_delivery_committed:bool=True; create_once_delivery_enforced:bool=True
    restart_safe_reauthentication_supported:bool=True; webhook_stream_completeness_attested:bool=False
    exact_head_last_push_selected:bool=False; last_push_actor_policy_evaluated:bool=False
    last_push_actor_attested:bool=False; review_policy_evaluated:bool=False
    branch_policy_fully_evaluated:bool=False; review_thread_mutation_authorized:bool=False
    merge_readiness_authorized:bool=False; merge_authorized:bool=False; release_authorized:bool=False
    deploy_authorized:bool=False; production_activation_authorized:bool=False
    authority:str=AUTHORITY; ledger_scope:str=LEDGER_SCOPE; schema:str=SCHEMA
    def __post_init__(self)->None:
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.ledger_scope!=LEDGER_SCOPE: raise PilotExactTaskPrPushWebhookIngressError("receipt schema/authority/scope invalid")
        for name in ("ledger_root_path_sha256","secret_path_sha256","signature_header_sha256","raw_body_sha256","canonical_payload_sha256","normalized_push_sha256","sender_user_node_id_sha256","header_inventory_sha256"): hex64(getattr(self,name),name=name)
        hex40(self.before_sha,name="before_sha"); hex40(self.after_sha,name="after_sha")
        if self.delivery_guid!=canonical_delivery_guid(self.delivery_guid) or isinstance(self.hook_id,bool) or not isinstance(self.hook_id,int) or self.hook_id<1 or self.hook_installation_target_type!="repository" or self.hook_installation_target_id!=REPOSITORY_ID or self.event!="push" or isinstance(self.raw_body_byte_count,bool) or not isinstance(self.raw_body_byte_count,int) or not 2<=self.raw_body_byte_count<=MAX_BODY_BYTES or self.repository_id!=REPOSITORY_ID or self.repository!=REPOSITORY or not isinstance(self.ref,str) or REF.fullmatch(self.ref) is None or not isinstance(self.sender_login,str) or LOGIN.fullmatch(self.sender_login) is None or isinstance(self.sender_user_id,bool) or not isinstance(self.sender_user_id,int) or self.sender_user_id<1: raise PilotExactTaskPrPushWebhookIngressError("receipt identity invalid")
        utc(self.received_at_utc,name="received_at_utc")
        if any(not isinstance(getattr(self,n),bool) for n in ("created","deleted","forced")): raise PilotExactTaskPrPushWebhookIngressError("push flags invalid")
        normalized={"repository_id":self.repository_id,"repository":self.repository,"ref":self.ref,"before_sha":self.before_sha,"after_sha":self.after_sha,"created":self.created,"deleted":self.deleted,"forced":self.forced,"sender_login":self.sender_login,"sender_user_id":self.sender_user_id,"sender_user_node_id_sha256":self.sender_user_node_id_sha256}
        if normalized_push_sha256(normalized)!=self.normalized_push_sha256: raise PilotExactTaskPrPushWebhookIngressError("normalized push hash mismatch")
        header={"delivery_guid":self.delivery_guid,"hook_id":self.hook_id,"hook_installation_target_type":self.hook_installation_target_type,"hook_installation_target_id":self.hook_installation_target_id,"event":self.event,"signature_header_sha256":self.signature_header_sha256}
        if hashlib.sha256(canonical(header).encode()).hexdigest()!=self.header_inventory_sha256: raise PilotExactTaskPrPushWebhookIngressError("header inventory hash mismatch")
        required_true=("hmac_sha256_verified","raw_body_verified_before_parse","duplicate_security_headers_rejected","sender_identity_used","webhook_delivery_ingested","durable_delivery_committed","create_once_delivery_enforced","restart_safe_reauthentication_supported")
        forced_false=("pusher_identity_used","webhook_stream_completeness_attested","exact_head_last_push_selected","last_push_actor_policy_evaluated","last_push_actor_attested","review_policy_evaluated","branch_policy_fully_evaluated","review_thread_mutation_authorized","merge_readiness_authorized","merge_authorized","release_authorized","deploy_authorized","production_activation_authorized")
        if any(getattr(self,n) is not True for n in required_true) or any(getattr(self,n) is not False for n in forced_false): raise PilotExactTaskPrPushWebhookIngressError("receipt widened authority/evidence")
    @property
    def receipt_authenticated(self)->bool: return _authenticated_record(self)
    @property
    def sha256(self)->str: return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self)->dict[str,Any]: return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self)->str: return canonical(self.to_dict())
    @classmethod
    def from_mapping(cls,value:Any)->"PilotExactTaskPrPushWebhookDeliveryReceipt":
        if not isinstance(value,Mapping) or set(value)!=set(cls.__dataclass_fields__): raise PilotExactTaskPrPushWebhookIngressError("receipt fields mismatch")
        return cls(**dict(value))

class _PushWebhookLedger:
    def __init__(self,root:Path,*,require_host_control:bool)->None:
        candidate=Path(root)
        if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink(): raise PilotExactTaskPrPushWebhookIngressError("webhook ledger root unsafe")
        if require_host_control:
            try: candidate=require_host_controlled_ledger_root(candidate)
            except PhysicalHostStateError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook ledger root is not host controlled") from exc
        self.root=candidate; self.require_host_control=require_host_control
    def path(self,delivery_guid:str)->Path: return self.root/f"{canonical_delivery_guid(delivery_guid)}.json"
    def _read(self,path:Path)->bytes:
        candidate=Path(path)
        if not candidate.is_absolute() or candidate.is_symlink() or candidate.parent!=self.root: raise PilotExactTaskPrPushWebhookIngressError("webhook record path unsafe")
        try: fd=os.open(candidate,os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
        except OSError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record missing or unreadable") from exc
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 2<=before.st_size<=MAX_RECORD_BYTES: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record unsafe")
            if self.require_host_control and os.name=="posix" and (before.st_uid!=0 or stat.S_IMODE(before.st_mode)&0o077): raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record is not root-private")
            remaining=before.st_size; chunks=[]
            while remaining:
                chunk=os.read(fd,min(65536,remaining))
                if not chunk: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record read incomplete")
                chunks.append(chunk); remaining-=len(chunk)
            if os.read(fd,1): raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record changed while reading")
            after=os.fstat(fd)
            if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size): raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record identity changed while reading")
            return b"".join(chunks)
        except OSError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record could not be read safely") from exc
        finally: os.close(fd)
    def commit(self,value:PilotExactTaskPrPushWebhookDeliveryReceipt)->Path:
        path=self.path(value.delivery_guid); payload=value.canonical_json().encode()
        try: create_once_file(path,payload,mode=0o600)
        except (DurablePublicationError,FileExistsError,OSError) as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery replay or durable publication failure") from exc
        if self._read(path)!=payload: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery durable readback mismatch")
        return path
    def load(self,delivery_guid:str)->PilotExactTaskPrPushWebhookDeliveryReceipt:
        path=self.path(delivery_guid); payload=self._read(path)
        try: raw=json.loads(payload.decode("utf-8",errors="strict"))
        except (UnicodeError,json.JSONDecodeError) as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record JSON invalid") from exc
        value=PilotExactTaskPrPushWebhookDeliveryReceipt.from_mapping(raw)
        if value.delivery_guid!=canonical_delivery_guid(delivery_guid) or value.ledger_root_path_sha256!=path_sha256(self.root) or value.canonical_json().encode()!=payload: raise PilotExactTaskPrPushWebhookIngressError("webhook delivery record canonical binding invalid")
        _mark_authenticated(value,path); return value
