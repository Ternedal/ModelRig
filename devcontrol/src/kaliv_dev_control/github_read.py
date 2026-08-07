from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import json
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .contract import ContractError, DevelopmentTask, normalize_repo_path

RECEIPT_SCHEMA = "kaliv-development-github-read-receipt/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_API_HOST = "api.github.com"
_API_VERSION = "2022-11-28"
_MAX_RESPONSE_BYTES = 4_000_000
_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"


class GitHubReadError(RuntimeError):
    pass


def _valid_repository(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\0" in value
        or any(char.isspace() for char in value)
        or len(value.encode("utf-8")) > 200
    ):
        return False
    parts = value.split("/")
    return len(parts) == 2 and all(
        part and part.strip() == part and part not in {".", ".."}
        for part in parts
    )


def _normalize_path(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise GitHubReadError(f"{name} must be a string")
    try:
        return normalize_repo_path(value, name=name)
    except ContractError as exc:
        raise GitHubReadError(f"{name} is not a canonical repository path") from exc


def _git_blob_sha(data: bytes) -> str:
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or not 100 <= self.status <= 599
        ):
            raise GitHubReadError("HTTP status must be an integer in 100..599")
        if not isinstance(self.headers, Mapping) or len(self.headers) > 200:
            raise GitHubReadError("HTTP headers must be a bounded mapping")
        clean: dict[str, str] = {}
        for key, value in self.headers.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or "\r" in key + value
                or "\n" in key + value
                or len(key.encode("utf-8")) > 256
                or len(value.encode("utf-8")) > 8192
            ):
                raise GitHubReadError(
                    "HTTP headers must be bounded canonical strings"
                )
            clean[key.lower()] = value
        object.__setattr__(self, "headers", MappingProxyType(clean))
        if not isinstance(self.body, bytes):
            raise GitHubReadError("HTTP body must be bytes")


class ReadOnlyTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: int,
        max_bytes: int,
    ) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _system_tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    loaded = False

    if sys.platform == "win32":
        enum_certificates = getattr(ssl, "enum_certificates", None)
        if enum_certificates is None:
            raise GitHubReadError("system TLS trust roots are unavailable")
        for store_name in ("ROOT", "CA"):
            try:
                certificates = enum_certificates(store_name)
            except (OSError, ssl.SSLError):
                continue
            for certificate, encoding, trust in certificates:
                if encoding != "x509_asn":
                    continue
                trusted = trust is True or (
                    isinstance(trust, (set, frozenset))
                    and _SERVER_AUTH_OID in trust
                )
                if not trusted:
                    continue
                try:
                    context.load_verify_locations(
                        cadata=ssl.DER_cert_to_PEM_cert(certificate)
                    )
                except (ValueError, ssl.SSLError):
                    continue
                loaded = True
    else:
        paths = ssl.get_default_verify_paths()
        locations = (
            {"cafile": paths.openssl_cafile}
            if paths.openssl_cafile
            else None,
            {"capath": paths.openssl_capath}
            if paths.openssl_capath
            else None,
        )
        for location in locations:
            if location is None:
                continue
            try:
                context.load_verify_locations(**location)
            except (OSError, ssl.SSLError):
                continue
            loaded = True

    if not loaded:
        raise GitHubReadError("system TLS trust roots are unavailable")
    return context


def _deadline_socket(response: Any) -> Any:
    pending = [response]
    seen: set[int] = set()
    for _ in range(5):
        following: list[Any] = []
        for candidate in pending:
            marker = id(candidate)
            if marker in seen:
                continue
            seen.add(marker)
            if callable(getattr(candidate, "settimeout", None)):
                return candidate
            for name in ("fp", "raw", "_sock"):
                child = getattr(candidate, name, None)
                if child is not None:
                    following.append(child)
        pending = following
    raise GitHubReadError(
        "GitHub response transport cannot enforce a wall-clock deadline"
    )


def _abort_response(response: Any, transport_socket: Any) -> None:
    try:
        transport_socket.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass
    try:
        transport_socket.close()
    except (AttributeError, OSError):
        pass
    try:
        response.close()
    except (AttributeError, OSError):
        pass


def _read_response_body(
    response: Any,
    *,
    max_bytes: int,
    deadline: float,
) -> bytes:
    read_once = getattr(response, "read1", None)
    fallback = getattr(response, "read", None)
    if not callable(read_once) and not callable(fallback):
        raise GitHubReadError("GitHub response body is not readable")
    transport_socket = _deadline_socket(response)
    completed = threading.Event()
    result: list[bytes] = []
    failures: list[BaseException] = []

    def consume() -> None:
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GitHubReadError(
                        "GitHub read exceeded the wall-clock deadline"
                    )
                try:
                    transport_socket.settimeout(max(0.001, remaining))
                except (OSError, ValueError) as exc:
                    raise GitHubReadError(
                        "GitHub response deadline could not be enforced"
                    ) from exc
                amount = min(65_536, max_bytes + 1 - total)
                if amount <= 0:
                    raise GitHubReadError(
                        "GitHub response exceeded the read budget"
                    )
                chunk = read_once(amount) if callable(read_once) else fallback(1)
                if not isinstance(chunk, (bytes, bytearray)):
                    raise GitHubReadError(
                        "GitHub response body is not bytes"
                    )
                if not chunk:
                    result.append(b"".join(chunks))
                    return
                total += len(chunk)
                if total > max_bytes:
                    raise GitHubReadError(
                        "GitHub response exceeded the read budget"
                    )
                chunks.append(bytes(chunk))
        except BaseException as exc:
            failures.append(exc)
        finally:
            completed.set()

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GitHubReadError("GitHub read exceeded the wall-clock deadline")
    try:
        transport_socket.settimeout(max(0.001, remaining))
    except (OSError, ValueError) as exc:
        raise GitHubReadError(
            "GitHub response deadline could not be enforced"
        ) from exc
    worker = threading.Thread(
        target=consume,
        name="kaliv-github-read",
        daemon=True,
    )
    worker.start()
    if not completed.wait(remaining):
        _abort_response(response, transport_socket)
        raise GitHubReadError("GitHub read exceeded the wall-clock deadline")
    if time.monotonic() > deadline:
        _abort_response(response, transport_socket)
        raise GitHubReadError("GitHub read exceeded the wall-clock deadline")
    if failures:
        failure = failures[0]
        if isinstance(failure, GitHubReadError):
            raise failure
        if isinstance(failure, (TimeoutError, OSError)):
            raise GitHubReadError("GitHub read did not complete") from failure
        raise GitHubReadError("GitHub response body could not be read") from failure
    if len(result) != 1:
        raise GitHubReadError("GitHub response body could not be read")
    return result[0]


class UrllibReadOnlyTransport:
    def __init__(self) -> None:
        context = _system_tls_context()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
            _NoRedirect(),
        )

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: int,
        max_bytes: int,
    ) -> HttpResponse:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= timeout_seconds <= 120
            or not 1 <= max_bytes <= 16_000_000
        ):
            raise GitHubReadError("HTTP bounds are invalid")
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _API_HOST
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise GitHubReadError(
                "transport URL escaped the fixed GitHub API host"
            )
        if not isinstance(headers, Mapping):
            raise GitHubReadError("HTTP headers must be a mapping")
        request_headers: dict[str, str] = {}
        for key, value in headers.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or "\r" in key + value
                or "\n" in key + value
            ):
                raise GitHubReadError("HTTP request headers are invalid")
            request_headers[key] = value
        request = urllib.request.Request(
            url, headers=request_headers, method="GET"
        )
        deadline = time.monotonic() + timeout_seconds
        try:
            response = self._opener.open(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            response = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubReadError("GitHub read did not complete") from exc
        try:
            if time.monotonic() >= deadline:
                raise GitHubReadError("GitHub read exceeded the wall-clock deadline")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    length = int(declared, 10)
                except (TypeError, ValueError) as exc:
                    raise GitHubReadError(
                        "GitHub Content-Length is invalid"
                    ) from exc
                if length < 0 or length > max_bytes:
                    raise GitHubReadError(
                        "GitHub response exceeded the read budget"
                    )
            body = _read_response_body(
                response,
                max_bytes=max_bytes,
                deadline=deadline,
            )
            return HttpResponse(
                status=int(response.status),
                headers=dict(response.headers.items()),
                body=body,
            )
        finally:
            response.close()


@dataclass(frozen=True, slots=True)
class GitHubReadReceipt:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    operation: str
    path: str
    subject_sha: str
    status: int
    response_sha256: str
    response_bytes: int
    etag_sha256: str
    schema: str = RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise GitHubReadError("unsupported GitHub receipt schema")
        if (
            not isinstance(self.task_id, str)
            or _TASK_ID.fullmatch(self.task_id) is None
            or not _valid_repository(self.repository)
        ):
            raise GitHubReadError("GitHub receipt identity is invalid")
        if (
            not isinstance(self.task_sha256, str)
            or _HEX64.fullmatch(self.task_sha256) is None
        ):
            raise GitHubReadError("GitHub receipt task hash is invalid")
        if (
            not isinstance(self.base_sha, str)
            or not isinstance(self.subject_sha, str)
            or _HEX40.fullmatch(self.base_sha) is None
            or _HEX40.fullmatch(self.subject_sha) is None
        ):
            raise GitHubReadError("GitHub receipt SHA is invalid")
        if self.operation not in {"verify_base_commit", "read_file"}:
            raise GitHubReadError("GitHub receipt operation is unsupported")
        if self.operation == "verify_base_commit":
            if self.path != "" or self.subject_sha != self.base_sha:
                raise GitHubReadError(
                    "commit receipt is not bound to the base SHA"
                )
        elif _normalize_path(self.path, name="receipt.path") != self.path:
            raise GitHubReadError("GitHub receipt path is not canonical")
        if (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or self.status != 200
            or isinstance(self.response_bytes, bool)
            or not isinstance(self.response_bytes, int)
            or not 0 <= self.response_bytes <= _MAX_RESPONSE_BYTES
        ):
            raise GitHubReadError(
                "GitHub receipt response metadata is invalid"
            )
        if (
            not isinstance(self.response_sha256, str)
            or not isinstance(self.etag_sha256, str)
            or _HEX64.fullmatch(self.response_sha256) is None
            or _HEX64.fullmatch(self.etag_sha256) is None
        ):
            raise GitHubReadError(
                "GitHub receipt response hash is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> GitHubReadReceipt:
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "operation",
            "path",
            "subject_sha",
            "status",
            "response_sha256",
            "response_bytes",
            "etag_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise GitHubReadError("GitHub receipt fields mismatch")
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise GitHubReadError(
                "GitHub receipt fields are invalid"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "operation": self.operation,
            "path": self.path,
            "subject_sha": self.subject_sha,
            "status": self.status,
            "response_sha256": self.response_sha256,
            "response_bytes": self.response_bytes,
            "etag_sha256": self.etag_sha256,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def verify_task(self, task: DevelopmentTask) -> None:
        if not isinstance(task, DevelopmentTask):
            raise GitHubReadError(
                "receipt verification requires a development task"
            )
        expected = {
            "task_id": task.task_id,
            "task_sha256": hashlib.sha256(
                task.canonical_json().encode("utf-8")
            ).hexdigest(),
            "repository": task.repository,
            "base_sha": task.base_sha,
        }
        actual = {
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
        }
        if actual != expected:
            raise GitHubReadError(
                "GitHub receipt is not bound to this exact task"
            )


@dataclass(frozen=True, slots=True)
class _TaskSnapshot:
    task: DevelopmentTask
    canonical_json: str
    task_id: str
    repository: str
    base_sha: str
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    max_output_bytes: int


class GitHubReadAdapter:
    __slots__ = (
        "_snapshot",
        "transport",
        "_token",
        "timeout_seconds",
        "_repository_path",
        "_sealed",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise GitHubReadError(
                "GitHub read adapter authority is immutable"
            )
        object.__setattr__(self, name, value)

    @property
    def task(self) -> DevelopmentTask:
        return self._snapshot.task

    def __init__(
        self,
        task: DevelopmentTask,
        *,
        transport: ReadOnlyTransport | None = None,
        token: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        if not isinstance(task, DevelopmentTask):
            raise GitHubReadError(
                "GitHub adapter requires a development task"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 120
        ):
            raise GitHubReadError("GitHub timeout is outside bounds")
        if token is not None and (
            not isinstance(token, str)
            or not token
            or len(token) > 4096
            or any(char.isspace() for char in token)
            or "\0" in token
        ):
            raise GitHubReadError("GitHub token is invalid")
        try:
            canonical = DevelopmentTask.from_mapping(task.to_dict())
        except (AttributeError, ContractError, TypeError, ValueError) as exc:
            raise GitHubReadError("task identity is invalid") from exc
        if (
            not isinstance(canonical.task_id, str)
            or _TASK_ID.fullmatch(canonical.task_id) is None
            or not _valid_repository(canonical.repository)
            or not isinstance(canonical.base_sha, str)
            or _HEX40.fullmatch(canonical.base_sha) is None
        ):
            raise GitHubReadError("task identity is invalid")
        self._snapshot = _TaskSnapshot(
            task=canonical,
            canonical_json=canonical.canonical_json(),
            task_id=canonical.task_id,
            repository=canonical.repository,
            base_sha=canonical.base_sha,
            allowed_paths=canonical.allowed_paths,
            protected_paths=canonical.protected_paths,
            max_output_bytes=canonical.budget.max_output_bytes,
        )
        self.transport = transport or UrllibReadOnlyTransport()
        self._token = token
        self.timeout_seconds = timeout_seconds
        owner, repo = self._snapshot.repository.split("/", 1)
        self._repository_path = "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )
        object.__setattr__(self, "_sealed", True)

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        return (
            fnmatch.fnmatchcase(path, pattern)
            or path == pattern
            or path.startswith(pattern.rstrip("/") + "/")
        )

    def _readable(self, path: str) -> bool:
        if path == ".git" or path.startswith(".git/"):
            return False
        return any(
            self._matches(path, item)
            for item in self._snapshot.allowed_paths
        ) and not any(
            self._matches(path, item)
            for item in self._snapshot.protected_paths
        )

    def _headers(self) -> Mapping[str, str]:
        values = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "kaliv-dev-control/1",
        }
        if self._token is not None:
            values["Authorization"] = f"Bearer {self._token}"
        return MappingProxyType(values)

    def _get(
        self,
        *,
        operation: str,
        suffix: str,
        query: Mapping[str, str] | None = None,
    ) -> tuple[Mapping[str, Any], HttpResponse]:
        if (
            operation not in {"verify_base_commit", "read_file"}
            or not suffix.startswith("/")
            or "?" in suffix
            or "#" in suffix
            or "\\" in suffix
        ):
            raise GitHubReadError("internal GitHub endpoint is invalid")
        url = "https://" + _API_HOST + self._repository_path + suffix
        if query:
            if any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in query.items()
            ):
                raise GitHubReadError(
                    "internal GitHub query is invalid"
                )
            url += "?" + urllib.parse.urlencode(
                query, quote_via=urllib.parse.quote
            )
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _API_HOST
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not parsed.path.startswith(self._repository_path + "/")
        ):
            raise GitHubReadError(
                "GitHub endpoint escaped the fixed API authority"
            )
        maximum = min(
            self._snapshot.max_output_bytes, _MAX_RESPONSE_BYTES
        )
        response = self.transport.get(
            url,
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
            max_bytes=maximum,
        )
        if not isinstance(response, HttpResponse):
            raise GitHubReadError(
                "GitHub transport returned an invalid response"
            )
        if "location" in response.headers:
            raise GitHubReadError("GitHub redirects are not accepted")
        if response.status != 200:
            raise GitHubReadError(
                f"GitHub {operation} returned status {response.status}"
            )
        content_type = (
            response.headers.get("content-type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if content_type not in {
            "application/json",
            "application/vnd.github+json",
        }:
            raise GitHubReadError("GitHub response is not JSON")
        if len(response.body) > maximum:
            raise GitHubReadError(
                "GitHub response exceeded the task budget"
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubReadError(
                "GitHub response JSON is invalid"
            ) from exc
        if not isinstance(payload, Mapping):
            raise GitHubReadError("GitHub response must be an object")
        return payload, response

    def _receipt(
        self,
        operation: str,
        path: str,
        subject_sha: str,
        response: HttpResponse,
    ) -> GitHubReadReceipt:
        return GitHubReadReceipt(
            task_id=self._snapshot.task_id,
            task_sha256=self._sha256(
                self._snapshot.canonical_json.encode("utf-8")
            ),
            repository=self._snapshot.repository,
            base_sha=self._snapshot.base_sha,
            operation=operation,
            path=path,
            subject_sha=subject_sha,
            status=response.status,
            response_sha256=self._sha256(response.body),
            response_bytes=len(response.body),
            etag_sha256=self._sha256(
                response.headers.get("etag", "").encode("utf-8")
            ),
        )

    def verify_base_commit(self) -> GitHubReadReceipt:
        payload, response = self._get(
            operation="verify_base_commit",
            suffix="/commits/" + self._snapshot.base_sha,
        )
        sha = payload.get("sha")
        if sha != self._snapshot.base_sha:
            raise GitHubReadError(
                "GitHub commit response does not match task base SHA"
            )
        return self._receipt(
            "verify_base_commit", "", sha, response
        )

    def read_bytes(
        self,
        path: str,
        *,
        max_bytes: int = 262_144,
    ) -> tuple[bytes, GitHubReadReceipt]:
        normalized = _normalize_path(path, name="path")
        if not self._readable(normalized):
            raise GitHubReadError(
                "GitHub path is outside readable task scope"
            )
        upper = min(self._snapshot.max_output_bytes, 1_000_000)
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= upper
        ):
            raise GitHubReadError("GitHub file bound is invalid")
        payload, response = self._get(
            operation="read_file",
            suffix="/contents/"
            + urllib.parse.quote(normalized, safe="/"),
            query={"ref": self._snapshot.base_sha},
        )
        if (
            payload.get("type") != "file"
            or payload.get("path") != normalized
        ):
            raise GitHubReadError(
                "GitHub content response is not the requested file"
            )
        blob_sha = payload.get("sha")
        if (
            not isinstance(blob_sha, str)
            or _HEX40.fullmatch(blob_sha) is None
        ):
            raise GitHubReadError(
                "GitHub content response has an invalid blob SHA"
            )
        content = payload.get("content")
        if (
            payload.get("encoding") != "base64"
            or not isinstance(content, str)
        ):
            raise GitHubReadError(
                "GitHub content response is not inline base64"
            )
        size = payload.get("size")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 <= size <= max_bytes
        ):
            raise GitHubReadError(
                "GitHub file exceeds the requested bound"
            )
        if any(
            char.isspace() and char not in "\r\n"
            for char in content
        ):
            raise GitHubReadError(
                "GitHub file base64 contains unsupported whitespace"
            )
        compact = content.replace("\r", "").replace("\n", "")
        if len(compact) > (max_bytes + 2) // 3 * 4:
            raise GitHubReadError(
                "GitHub file base64 exceeds the requested bound"
            )
        try:
            data = base64.b64decode(compact, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GitHubReadError(
                "GitHub file base64 is invalid"
            ) from exc
        if len(data) != size:
            raise GitHubReadError(
                "GitHub file size does not match decoded content"
            )
        if _git_blob_sha(data) != blob_sha:
            raise GitHubReadError(
                "GitHub blob SHA does not match decoded content"
            )
        return data, self._receipt(
            "read_file", normalized, blob_sha, response
        )

    def read_text(
        self,
        path: str,
        *,
        max_bytes: int = 262_144,
    ) -> tuple[str, GitHubReadReceipt]:
        data, receipt = self.read_bytes(path, max_bytes=max_bytes)
        if b"\0" in data:
            raise GitHubReadError("GitHub file is binary")
        try:
            return data.decode("utf-8"), receipt
        except UnicodeDecodeError as exc:
            raise GitHubReadError(
                "GitHub file is not UTF-8 text"
            ) from exc
