from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import json
import re
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


class GitHubReadError(RuntimeError):
    pass


def _valid_repository(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or any(char.isspace() for char in value)
        or len(value.encode("utf-8")) > 200
    ):
        return False
    parts = value.split("/")
    return len(parts) == 2 and all(part and part.strip() == part for part in parts)


def _normalize_path(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        raise GitHubReadError(f"{name} must be a string")
    try:
        return normalize_repo_path(value, name=name)
    except ContractError as exc:
        raise GitHubReadError(f"{name} is not a canonical repository path") from exc


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data,
        usedforsecurity=False,
    ).hexdigest()


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


class UrllibReadOnlyTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
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
            raise GitHubReadError("transport URL escaped the fixed GitHub API host")
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
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        try:
            response = self._opener.open(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            response = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubReadError("GitHub read did not complete") from exc
        try:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_length = int(declared, 10)
                except (TypeError, ValueError) as exc:
                    raise GitHubReadError("GitHub Content-Length is invalid") from exc
                if declared_length < 0 or declared_length > max_bytes:
                    raise GitHubReadError("GitHub response exceeded the read budget")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise GitHubReadError("GitHub response exceeded the read budget")
            return HttpResponse(
                status=int(response.status),
                headers={key: value for key, value in response.headers.items()},
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
            if self.path != "":
                raise GitHubReadError("commit receipt cannot contain a path")
            if self.subject_sha != self.base_sha:
                raise GitHubReadError("commit receipt is not bound to the base SHA")
        else:
            normalized = _normalize_path(self.path, name="receipt.path")
            if normalized != self.path:
                raise GitHubReadError("GitHub receipt path is not canonical")
        if (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or self.status != 200
            or isinstance(self.response_bytes, bool)
            or not isinstance(self.response_bytes, int)
            or not 0 <= self.response_bytes <= _MAX_RESPONSE_BYTES
        ):
            raise GitHubReadError("GitHub receipt response metadata is invalid")
        if (
            not isinstance(self.response_sha256, str)
            or not isinstance(self.etag_sha256, str)
            or _HEX64.fullmatch(self.response_sha256) is None
            or _HEX64.fullmatch(self.etag_sha256) is None
        ):
            raise GitHubReadError("GitHub receipt response hash is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "GitHubReadReceipt":
        if not isinstance(value, Mapping):
            raise GitHubReadError("GitHub receipt must be an object")
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
        if set(value) != fields:
            raise GitHubReadError("GitHub receipt fields mismatch")
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise GitHubReadError("GitHub receipt fields are invalid") from exc

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
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def verify_task(self, task: DevelopmentTask) -> None:
        if not isinstance(task, DevelopmentTask):
            raise GitHubReadError("receipt verification requires a development task")
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
            raise GitHubReadError("GitHub receipt is not bound to this exact task")


class GitHubReadAdapter:
    def __init__(
        self,
        task: DevelopmentTask,
        *,
        transport: ReadOnlyTransport | None = None,
        token: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        if not isinstance(task, DevelopmentTask):
            raise GitHubReadError("GitHub adapter requires a development task")
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
            or "\x00" in token
        ):
            raise GitHubReadError("GitHub token is invalid")
        if not _valid_repository(task.repository):
            raise GitHubReadError("task repository is invalid")
        self.task = task
        self.transport = transport or UrllibReadOnlyTransport()
        self._token = token
        self.timeout_seconds = timeout_seconds
        owner, repo = task.repository.split("/", 1)
        self._repository_path = "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe="")
        )

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
            self._matches(path, pattern) for pattern in self.task.allowed_paths
        ) and not any(
            self._matches(path, pattern) for pattern in self.task.protected_paths
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
        path: str,
        query: Mapping[str, str] | None = None,
    ) -> tuple[Mapping[str, Any], HttpResponse]:
        del path
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
                raise GitHubReadError("internal GitHub query is invalid")
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
            raise GitHubReadError("GitHub endpoint escaped the fixed API authority")
        max_bytes = min(self.task.budget.max_output_bytes, _MAX_RESPONSE_BYTES)
        response = self.transport.get(
            url,
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
            max_bytes=max_bytes,
        )
        if not isinstance(response, HttpResponse):
            raise GitHubReadError("GitHub transport returned an invalid response")
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
        if content_type not in {"application/json", "application/vnd.github+json"}:
            raise GitHubReadError("GitHub response is not JSON")
        if len(response.body) > max_bytes:
            raise GitHubReadError("GitHub response exceeded the task budget")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubReadError("GitHub response JSON is invalid") from exc
        if not isinstance(payload, Mapping):
            raise GitHubReadError("GitHub response must be an object")
        return payload, response

    def _receipt(
        self,
        *,
        operation: str,
        path: str,
        subject_sha: str,
        response: HttpResponse,
    ) -> GitHubReadReceipt:
        etag = response.headers.get("etag", "").encode("utf-8")
        return GitHubReadReceipt(
            task_id=self.task.task_id,
            task_sha256=self._sha256(self.task.canonical_json().encode("utf-8")),
            repository=self.task.repository,
            base_sha=self.task.base_sha,
            operation=operation,
            path=path,
            subject_sha=subject_sha,
            status=response.status,
            response_sha256=self._sha256(response.body),
            response_bytes=len(response.body),
            etag_sha256=self._sha256(etag),
        )

    def verify_base_commit(self) -> GitHubReadReceipt:
        payload, response = self._get(
            operation="verify_base_commit",
            suffix="/commits/" + self.task.base_sha,
            path="",
        )
        sha = payload.get("sha")
        if sha != self.task.base_sha:
            raise GitHubReadError(
                "GitHub commit response does not match task base SHA"
            )
        return self._receipt(
            operation="verify_base_commit", path="", subject_sha=sha, response=response
        )

    def read_bytes(
        self, path: str, *, max_bytes: int = 262_144
    ) -> tuple[bytes, GitHubReadReceipt]:
        normalized = _normalize_path(path, name="path")
        if not self._readable(normalized):
            raise GitHubReadError("GitHub path is outside readable task scope")
        upper = min(self.task.budget.max_output_bytes, 1_000_000)
        if (
            isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= upper
        ):
            raise GitHubReadError("GitHub file bound is invalid")
        encoded = urllib.parse.quote(normalized, safe="/")
        payload, response = self._get(
            operation="read_file",
            suffix="/contents/" + encoded,
            path=normalized,
            query={"ref": self.task.base_sha},
        )
        if payload.get("type") != "file" or payload.get("path") != normalized:
            raise GitHubReadError("GitHub content response is not the requested file")
        blob_sha = payload.get("sha")
        if not isinstance(blob_sha, str) or _HEX40.fullmatch(blob_sha) is None:
            raise GitHubReadError("GitHub content response has an invalid blob SHA")
        if payload.get("encoding") != "base64" or not isinstance(
            payload.get("content"), str
        ):
            raise GitHubReadError("GitHub content response is not inline base64")
        declared_size = payload.get("size")
        if (
            isinstance(declared_size, bool)
            or not isinstance(declared_size, int)
            or declared_size < 0
            or declared_size > max_bytes
        ):
            raise GitHubReadError("GitHub file exceeds the requested bound")
        encoded_content = payload["content"]
        if any(
            char.isspace() and char not in "\r\n" for char in encoded_content
        ):
            raise GitHubReadError(
                "GitHub file base64 contains unsupported whitespace"
            )
        compact_content = encoded_content.replace("\r", "").replace("\n", "")
        maximum_encoded = (max_bytes + 2) // 3 * 4
        if len(compact_content) > maximum_encoded:
            raise GitHubReadError("GitHub file base64 exceeds the requested bound")
        try:
            data = base64.b64decode(compact_content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GitHubReadError("GitHub file base64 is invalid") from exc
        if len(data) != declared_size:
            raise GitHubReadError(
                "GitHub file size does not match decoded content"
            )
        if _git_blob_sha(data) != blob_sha:
            raise GitHubReadError("GitHub blob SHA does not match decoded content")
        receipt = self._receipt(
            operation="read_file",
            path=normalized,
            subject_sha=blob_sha,
            response=response,
        )
        return data, receipt

    def read_text(
        self, path: str, *, max_bytes: int = 262_144
    ) -> tuple[str, GitHubReadReceipt]:
        data, receipt = self.read_bytes(path, max_bytes=max_bytes)
        if b"\x00" in data:
            raise GitHubReadError("GitHub file is binary")
        try:
            return data.decode("utf-8"), receipt
        except UnicodeDecodeError as exc:
            raise GitHubReadError("GitHub file is not UTF-8 text") from exc
