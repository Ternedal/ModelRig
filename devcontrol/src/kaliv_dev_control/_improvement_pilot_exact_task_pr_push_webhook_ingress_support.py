"""Security primitives for ADR-DC-094 push-webhook ingress."""
from __future__ import annotations
import hashlib, hmac, json, os, re, stat, uuid
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator, _require_host_controlled_ledger_root
from .improvement_physical_authority_keyring import PhysicalRequestAuthorityKeyringError, _WINDOWS_TRUSTED_CONTROL_SIDS, _require_host_control, _validate_windows_acl_snapshot, _windows_acl_snapshot
from .trusted_git_runtime_model import _has_linkish_component

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-push-webhook-ingress/v1"
AUTHORITY="hmac-authenticated-one-dc-l16-push-webhook-delivery-ledger-only"
LEDGER_SCOPE="canonical-host-github-push-webhook-delivery-ledger-v1"
REPOSITORY="Ternedal/ModelRig"; REPOSITORY_ID=1287914122
MAX_BODY_BYTES=8*1024*1024; MAX_RECORD_BYTES=256*1024; MAX_SECRET_BYTES=256; MIN_SECRET_BYTES=32
HEX40=re.compile(r"^[0-9a-f]{40}$"); HEX64=re.compile(r"^[0-9a-f]{64}$")
UTC=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LOGIN=re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REF=re.compile(r"^refs/heads/[^\x00-\x20~^:?*\\[\\]+$")
SIGNATURE=re.compile(r"^sha256=([0-9a-f]{64})$")
REQUIRED_HEADERS=frozenset({"x-github-delivery","x-github-event","x-github-hook-id","x-github-hook-installation-target-type","x-github-hook-installation-target-id","x-hub-signature-256","user-agent","content-type"})
POSIX_SECRET=Path("/etc/modelrig/devcontrol/authority/rsi-github-push-webhook-secret-v1")
WINDOWS_SECRET=Path(r"C:\Program Files\ModelRig\DevControl\authority\rsi-github-push-webhook-secret-v1")
POSIX_LEDGER=Path("/var/lib/modelrig/devcontrol/rsi-github-push-webhook-delivery-ledger-v1")
WINDOWS_LEDGER=Path(r"C:\Program Files\ModelRig\DevControl\state\rsi-github-push-webhook-delivery-ledger-v1")
WINDOWS_SECRET_READ_MASK=0x80000000|0x00020000|0x00000001|0x00000008|0x00000080
require_host_controlled_ledger_root=_require_host_controlled_ledger_root

class PilotExactTaskPrPushWebhookIngressError(ValueError): pass

def canonical(value: Any)->str:
    try: return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError) as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook evidence is not canonical JSON") from exc

def path_sha256(path:Path)->str: return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()
def hex64(value:Any,*,name:str)->str:
    if not isinstance(value,str) or HEX64.fullmatch(value) is None or value=="0"*64: raise PilotExactTaskPrPushWebhookIngressError(f"{name} invalid")
    return value
def hex40(value:Any,*,name:str)->str:
    if not isinstance(value,str) or HEX40.fullmatch(value) is None: raise PilotExactTaskPrPushWebhookIngressError(f"{name} invalid")
    return value
def utc(value:Any,*,name:str)->datetime:
    if not isinstance(value,str) or UTC.fullmatch(value) is None: raise PilotExactTaskPrPushWebhookIngressError(f"{name} invalid")
    try: return datetime.strptime(value,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc: raise PilotExactTaskPrPushWebhookIngressError(f"{name} invalid") from exc
def now_utc_seconds()->str: return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
def canonical_delivery_guid(value:Any)->str:
    if not isinstance(value,str) or len(value)>64: raise PilotExactTaskPrPushWebhookIngressError("delivery GUID invalid")
    try: return str(uuid.UUID(value))
    except (ValueError,AttributeError) as exc: raise PilotExactTaskPrPushWebhookIngressError("delivery GUID invalid") from exc

def require_header_pairs(headers:Any)->Mapping[str,str]:
    if isinstance(headers,(str,bytes,bytearray)) or not isinstance(headers,Sequence): raise PilotExactTaskPrPushWebhookIngressError("raw header sequence required")
    out:dict[str,str]={}
    for row in headers:
        if not isinstance(row,Sequence) or isinstance(row,(str,bytes,bytearray)) or len(row)!=2: raise PilotExactTaskPrPushWebhookIngressError("header pair invalid")
        name,value=row
        if not isinstance(name,str) or not isinstance(value,str): raise PilotExactTaskPrPushWebhookIngressError("header pair invalid")
        key=name.strip().lower()
        if not key or "\r" in value or "\n" in value: raise PilotExactTaskPrPushWebhookIngressError("header value invalid")
        if key in REQUIRED_HEADERS:
            if key in out: raise PilotExactTaskPrPushWebhookIngressError("duplicate or case-colliding security header")
            out[key]=value.strip()
    if set(out)!=REQUIRED_HEADERS: raise PilotExactTaskPrPushWebhookIngressError("required webhook headers missing")
    if out["x-github-event"]!="push": raise PilotExactTaskPrPushWebhookIngressError("webhook event is not push")
    if out["x-github-hook-installation-target-type"]!="repository" or out["x-github-hook-installation-target-id"]!=str(REPOSITORY_ID): raise PilotExactTaskPrPushWebhookIngressError("webhook target invalid")
    try: hook_id=int(out["x-github-hook-id"])
    except ValueError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook hook id invalid") from exc
    if hook_id<1 or str(hook_id)!=out["x-github-hook-id"]: raise PilotExactTaskPrPushWebhookIngressError("webhook hook id invalid")
    if not out["user-agent"].startswith("GitHub-Hookshot/"): raise PilotExactTaskPrPushWebhookIngressError("webhook user-agent invalid")
    if out["content-type"].split(";",1)[0].strip().lower()!="application/json": raise PilotExactTaskPrPushWebhookIngressError("webhook content type invalid")
    if SIGNATURE.fullmatch(out["x-hub-signature-256"]) is None: raise PilotExactTaskPrPushWebhookIngressError("webhook signature header invalid")
    return MappingProxyType(out)

def canonical_secret_path()->Path:
    if os.name=="posix": return POSIX_SECRET
    if os.name=="nt": return WINDOWS_SECRET
    raise PilotExactTaskPrPushWebhookIngressError("webhook secret platform unsupported")
def canonical_ledger_root()->Path:
    try:
        _require_elevated_operator()
        if os.name=="posix": return _require_host_controlled_ledger_root(POSIX_LEDGER)
        if os.name=="nt": return _require_host_controlled_ledger_root(WINDOWS_LEDGER)
    except PhysicalHostStateError as exc: raise PilotExactTaskPrPushWebhookIngressError("canonical webhook ledger is not host controlled") from exc
    raise PilotExactTaskPrPushWebhookIngressError("webhook ledger platform unsupported")
def _require_windows_secret_confidentiality(path:Path)->None:
    try:
        owner,entries=_windows_acl_snapshot(path); _validate_windows_acl_snapshot(owner,entries,is_directory=False)
    except PhysicalRequestAuthorityKeyringError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook secret ACL cannot be trusted") from exc
    if owner not in _WINDOWS_TRUSTED_CONTROL_SIDS: raise PilotExactTaskPrPushWebhookIngressError("webhook secret owner invalid")
    if any(mask&WINDOWS_SECRET_READ_MASK and sid not in _WINDOWS_TRUSTED_CONTROL_SIDS for mask,sid in entries): raise PilotExactTaskPrPushWebhookIngressError("webhook secret is readable by an untrusted principal")
def read_secret_bytes(path:Path,*,require_host_control:bool)->bytes:
    candidate=Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate): raise PilotExactTaskPrPushWebhookIngressError("webhook secret path unsafe")
    flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
    try: fd=os.open(candidate,flags)
    except OSError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook secret missing or unreadable") from exc
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not MIN_SECRET_BYTES<=before.st_size<=MAX_SECRET_BYTES: raise PilotExactTaskPrPushWebhookIngressError("webhook secret file unsafe")
        if require_host_control:
            try: _require_host_control(candidate,before)
            except PhysicalRequestAuthorityKeyringError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook secret is not host controlled") from exc
            if os.name=="posix" and stat.S_IMODE(before.st_mode)&0o077: raise PilotExactTaskPrPushWebhookIngressError("webhook secret is not root-private")
            if os.name=="nt": _require_windows_secret_confidentiality(candidate)
        remaining=before.st_size; chunks=[]
        while remaining:
            chunk=os.read(fd,min(4096,remaining))
            if not chunk: raise PilotExactTaskPrPushWebhookIngressError("webhook secret read incomplete")
            chunks.append(chunk); remaining-=len(chunk)
        if os.read(fd,1): raise PilotExactTaskPrPushWebhookIngressError("webhook secret changed while reading")
        after=os.fstat(fd)
        if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size): raise PilotExactTaskPrPushWebhookIngressError("webhook secret identity changed while reading")
        secret=b"".join(chunks)
        if any(b<33 or b>126 for b in secret): raise PilotExactTaskPrPushWebhookIngressError("webhook secret must be printable non-whitespace ASCII")
        return secret
    except OSError as exc: raise PilotExactTaskPrPushWebhookIngressError("webhook secret could not be read safely") from exc
    finally: os.close(fd)
def verify_hmac(*,secret:bytes,raw_body:bytes,signature_header:str)->None:
    expected="sha256="+hmac.new(secret,raw_body,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature_header): raise PilotExactTaskPrPushWebhookIngressError("webhook HMAC verification failed")
def normalized_push(payload:Any)->Mapping[str,Any]:
    if not isinstance(payload,Mapping): raise PilotExactTaskPrPushWebhookIngressError("push payload must be an object")
    repo=payload.get("repository"); sender=payload.get("sender")
    if not isinstance(repo,Mapping) or not isinstance(sender,Mapping): raise PilotExactTaskPrPushWebhookIngressError("push payload identity missing")
    if repo.get("full_name")!=REPOSITORY or repo.get("id")!=REPOSITORY_ID: raise PilotExactTaskPrPushWebhookIngressError("push repository identity invalid")
    ref=payload.get("ref")
    if not isinstance(ref,str) or len(ref.encode())>512 or REF.fullmatch(ref) is None: raise PilotExactTaskPrPushWebhookIngressError("push ref invalid")
    before=hex40(payload.get("before"),name="before_sha"); after=hex40(payload.get("after"),name="after_sha")
    flags={}
    for name in ("created","deleted","forced"):
        value=payload.get(name)
        if not isinstance(value,bool): raise PilotExactTaskPrPushWebhookIngressError(f"push {name} invalid")
        flags[name]=value
    login=sender.get("login"); user_id=sender.get("id"); node=sender.get("node_id")
    if not isinstance(login,str) or LOGIN.fullmatch(login) is None or isinstance(user_id,bool) or not isinstance(user_id,int) or user_id<1 or not isinstance(node,str) or not node or len(node.encode())>512: raise PilotExactTaskPrPushWebhookIngressError("push sender identity invalid")
    return MappingProxyType({"repository_id":REPOSITORY_ID,"repository":REPOSITORY,"ref":ref,"before_sha":before,"after_sha":after,"created":flags["created"],"deleted":flags["deleted"],"forced":flags["forced"],"sender_login":login,"sender_user_id":user_id,"sender_user_node_id_sha256":hashlib.sha256(node.encode()).hexdigest()})
def normalized_push_sha256(value:Mapping[str,Any])->str: return hashlib.sha256(canonical(dict(value)).encode()).hexdigest()
