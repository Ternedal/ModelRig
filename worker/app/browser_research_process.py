"""Isolated Browser Use process for one confirmed read-only research request.

This module is entered with ``python -I`` by :mod:`browser_research_tool`.  It
composes the already-delivered BrowserHost, common data-sharing receipt, public
peer binding, pinned numeric-IP transport and Browser Use/CDP guard.  It emits
exactly one normalized JSON line and never exposes raw exception text.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import inspect
import io
import json
import os
import re
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .browser_host import BrowserHost, BrowserHostRequest
from .browser_peer_fulfillment import BrowserPeerFulfillmentController
from .browser_peer_runtime import build_claim_bound_browser_use_runtime
from .browser_use_adapter import BrowserUseBindings, load_browser_use_bindings
from .data_sharing import DEFAULT_POLICY
from .research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from .research_contract import ReadOnlyBrowserPolicy, ResearchRequest
from .research_data_sharing import ResearchSharingIntent
from .research_egress import EgressPlan
from .research_peer_authorization import ResearchPeerAuthorizationBridge
from .research_peer_transfer import ResearchPeerTransferLedger

SCHEMA = "kaliv-browser-research-launch/v1"
MODEL_ENV = "KALIV_BROWSER_MODEL"
OLLAMA_ENV = "KALIV_BROWSER_OLLAMA_URL"
DATA_ENV = "KALIV_BROWSER_DATA_DIR"
EXECUTABLE_ENV = "MODELRIG_BROWSER_EXECUTABLE"
_MAX_INPUT_BYTES = 64 * 1024
_BINDING = re.compile(r"^[0-9a-f]{64}$")


class BrowserResearchProcessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _strict_payload(raw: bytes) -> tuple[str, dict[str, Any]]:
    if not raw or len(raw) > _MAX_INPUT_BYTES:
        raise BrowserResearchProcessError("invalid_request_size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrowserResearchProcessError("invalid_request_json") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "approval_binding",
        "request",
    }:
        raise BrowserResearchProcessError("invalid_request_shape")
    if value["schema"] != SCHEMA:
        raise BrowserResearchProcessError("unsupported_request_schema")
    binding = value["approval_binding"]
    if not isinstance(binding, str) or not _BINDING.fullmatch(binding):
        raise BrowserResearchProcessError("invalid_approval_binding")
    request = value["request"]
    if not isinstance(request, dict) or set(request) != {
        "query",
        "allowed_domains",
        "max_sources",
        "timeout_seconds",
    }:
        raise BrowserResearchProcessError("invalid_research_request")
    return binding, request


def _data_dir() -> Path:
    raw = os.getenv(DATA_ENV, "").strip()
    if not raw:
        raise BrowserResearchProcessError("browser_data_dir_missing")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise BrowserResearchProcessError("browser_data_dir_not_absolute")
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_ollama() -> tuple[str, str]:
    model = os.getenv(MODEL_ENV, "").strip()
    raw_url = os.getenv(OLLAMA_ENV, "").strip().rstrip("/")
    if not model or len(model) > 200:
        raise BrowserResearchProcessError("browser_model_missing")
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise BrowserResearchProcessError("ollama_url_invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        raise BrowserResearchProcessError("ollama_must_be_loopback")
    return model, raw_url


def _llm_factory() -> Any:
    model, host = _local_ollama()
    try:
        from browser_use import ChatOllama
    except ImportError as exc:
        raise BrowserResearchProcessError("browser_ollama_adapter_missing") from exc
    try:
        parameters = inspect.signature(ChatOllama).parameters
    except (TypeError, ValueError) as exc:
        raise BrowserResearchProcessError("browser_ollama_signature_unavailable") from exc
    kwargs: dict[str, Any] = {"model": model}
    if "host" in parameters:
        kwargs["host"] = host
    elif "base_url" in parameters:
        kwargs["base_url"] = host
    else:
        raise BrowserResearchProcessError("browser_ollama_host_contract_changed")
    if "temperature" in parameters:
        kwargs["temperature"] = 0
    try:
        return ChatOllama(**kwargs)
    except Exception as exc:
        raise BrowserResearchProcessError("browser_ollama_initialization_failed") from exc


def _bindings_loader() -> BrowserUseBindings:
    bindings = load_browser_use_bindings()
    executable = os.getenv(EXECUTABLE_ENV, "").strip()
    if not executable:
        return bindings
    try:
        path = Path(executable).expanduser().resolve(strict=True)
    except OSError as exc:
        raise BrowserResearchProcessError("browser_executable_invalid") from exc
    if not path.is_file():
        raise BrowserResearchProcessError("browser_executable_invalid")
    original = bindings.profile_factory

    def profile_factory(**kwargs: Any) -> Any:
        profile = original(**kwargs)
        profile.executable_path = str(path)
        return profile

    return dataclasses.replace(bindings, profile_factory=profile_factory)


def _resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise BrowserResearchProcessError("public_dns_failed") from exc
    addresses: list[str] = []
    for _family, _kind, _proto, _canon, sockaddr in rows:
        address = str(sockaddr[0])
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise BrowserResearchProcessError("public_dns_empty")
    return tuple(addresses)


def _request(value: dict[str, Any]) -> ResearchRequest:
    try:
        timeout = value["timeout_seconds"]
        policy = ReadOnlyBrowserPolicy(
            allowed_domains=tuple(value["allowed_domains"]),
            max_steps=12,
            max_pages=max(4, min(20, int(value["max_sources"]) * 3)),
            timeout_seconds=timeout,
            max_source_bytes=2_000_000,
        )
        return ResearchRequest(
            query=value["query"],
            policy=policy,
            max_sources=value["max_sources"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BrowserResearchProcessError("research_contract_rejected") from exc


def _intent(research: ResearchRequest) -> ResearchSharingIntent:
    payload = json.dumps(
        {
            "query": research.query,
            "allowed_domains": list(research.policy.allowed_domains),
            "max_sources": research.max_sources,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ResearchSharingIntent(
        plan=EgressPlan(
            destination="browser-use",
            purpose="Perform one exact user-confirmed read-only public web research request",
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            # The query is conservatively private.  The outer ToolGate approval is
            # materialized below as an exact one-use common permission.
            sensitivity="private",
            allowed_domains=research.policy.allowed_domains,
            max_bytes=1_000_000,
        ),
        summary="Exact user-confirmed Browser Use research request.",
    )


def _response(ok: bool, payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            {"ok": ok, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


async def _execute(binding: str, value: dict[str, Any]) -> dict[str, Any]:
    data_dir = _data_dir()
    research = _request(value)
    intent = _intent(research)
    common = VerifiableDataSharingLedger(str(data_dir / "data-sharing.db"))
    boundary = VerifiableResearchSharingBoundary(
        common,
        mode="enforce",
        policy=DEFAULT_POLICY,
    )
    peer: ResearchPeerTransferLedger | None = None
    runtime = None
    lease = None
    terminal = False
    try:
        request = intent.to_request()
        proposal = common.propose(request, now=int(time.time()), ttl_seconds=300)
        # This transition is not a self-approval: the process receives only a
        # digest created inside ToolGate's confirmed execution context.  Direct
        # runner calls have no binding and are refused in the parent process.
        common.approve(
            proposal.permission_id,
            actor=f"toolgate:{binding[:32]}",
            now=int(time.time()),
        )
        lease = boundary.prepare(
            intent,
            permission_id=proposal.permission_id,
            now=int(time.time()),
            receipt_ttl_seconds=min(300, research.policy.timeout_seconds + 30),
        )
        claim = boundary.claim(lease, intent, now=int(time.time()))
        bridge = ResearchPeerAuthorizationBridge(boundary)
        peer = ResearchPeerTransferLedger(
            bridge,
            _resolver,
            str(data_dir / "peer-transfer.db"),
        )
        controller = BrowserPeerFulfillmentController.create(
            bridge,
            peer,
            claim,
            lease,
            intent,
            timeout_seconds=min(30, research.policy.timeout_seconds),
            max_response_bytes=research.policy.max_source_bytes,
        )
        runtime = build_claim_bound_browser_use_runtime(
            controller,
            llm_factory=_llm_factory,
            bindings_loader=_bindings_loader,
            max_evidence_bytes=min(8_000_000, research.policy.max_source_bytes * research.max_sources),
            max_evidence_responses=max(4, research.policy.max_pages),
            now_factory=lambda: int(time.time()),
        )
        host_response = await BrowserHost(runtime.backend).execute(
            BrowserHostRequest(
                request_id=f"br_{uuid.uuid4().hex[:24]}",
                research=research,
            )
        )
        if host_response.ok:
            boundary.complete(
                lease,
                intent,
                outcome="completed",
                bytes_sent=controller.bytes_sent,
                now=int(time.time()),
            )
            terminal = True
            assert host_response.result is not None
            return host_response.result
        error_code = host_response.error_code or "browser_failed"
        boundary.complete(
            lease,
            intent,
            outcome="blocked" if error_code in {"contract_violation", "cleanup_failed"} else "failed",
            bytes_sent=controller.bytes_sent,
            error_code=error_code,
            now=int(time.time()),
        )
        terminal = True
        raise BrowserResearchProcessError(error_code)
    except BrowserResearchProcessError:
        raise
    except Exception as exc:
        if lease is not None and not terminal:
            try:
                boundary.complete(
                    lease,
                    intent,
                    outcome="failed",
                    bytes_sent=0,
                    error_code="browser_runtime_failed",
                    now=int(time.time()),
                )
                terminal = True
            except Exception:
                pass
        raise BrowserResearchProcessError("browser_runtime_failed") from exc
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                pass
        if peer is not None:
            try:
                peer.close()
            except Exception:
                pass
        try:
            common.close()
        except Exception:
            pass


def main() -> int:
    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    try:
        binding, value = _strict_payload(raw)
        # Keep Browser Use/package logging out of the one-response stdout
        # protocol.  Child Chromium diagnostics remain captured by the parent as
        # stderr and are never surfaced as trusted tool output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            payload = asyncio.run(_execute(binding, value))
        sys.stdout.buffer.write(_response(True, payload))
    except BrowserResearchProcessError as exc:
        sys.stdout.buffer.write(_response(False, {"code": exc.code}))
    except Exception:
        sys.stdout.buffer.write(_response(False, {"code": "browser_process_failed"}))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
