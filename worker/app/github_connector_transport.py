"""Dormant account-bound authenticated transport for the T-036 GitHub pilot.

Security shape:

* the model/client never supplies a URL host, method or credential;
* only ``https://api.github.com`` is resolved;
* every DNS answer must be globally routable and one deterministic address is
  selected before the socket opens;
* the generic public header validator remains credential-free;
* a bearer token is loaded at execution time from a configured secret file and
  enters only ``PinnedHttpTransport.request_with_trusted_bearer``;
* grant account and configured credential account must match before a read;
* redirects are not followed by the pinned transport;
* no token is stored in connector SQLite, result/source receipts or exceptions.

The module is still dormant: nothing registers this runtime with ToolGate or an
HTTP route, and ``production_activation`` remains false in the surrounding
connector contract.
"""
from __future__ import annotations

import ipaddress
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from .github_connector_client import (
    GitHubReadClient,
    GitHubReadRemoteError,
    GitHubReadResult,
    GitHubTransportRequest,
    GitHubTransportResponse,
)
from .github_connector_contract import (
    GitHubConnectorDenied,
    GitHubConnectorGrantStore,
    normalize_account,
)
from .pinned_http_transport import PinnedHttpTransport
from .web_fetch import WebFetchError, default_resolver

_GITHUB_HOST = "api.github.com"
_GITHUB_PORT = 443
_DEFAULT_TIMEOUT_SECONDS = 15.0
_MAX_TOKEN_FILE_BYTES = 4_096


class GitHubCredentialError(RuntimeError):
    """Credential configuration failed without exposing secret material."""


class GitHubCredentialProvider(Protocol):
    @property
    def account(self) -> str:
        ...

    def bearer_token(self) -> str:
        ...


class FileGitHubCredentialProvider:
    """Read one account token from a local secret file only when needed.

    The token itself is never copied into environment variables by this class.
    On POSIX the file must not be group/world-accessible. Windows ACL handling
    remains the host/deployment responsibility until the Windows secret-store
    slice is added.
    """

    def __init__(self, *, account: str, token_file: str | os.PathLike[str]) -> None:
        self._account = normalize_account(account)
        self._path = Path(token_file)

    @property
    def account(self) -> str:
        return self._account

    def bearer_token(self) -> str:
        try:
            info = self._path.stat()
        except OSError as exc:
            raise GitHubCredentialError("GitHub credential file is unavailable") from exc
        if not stat.S_ISREG(info.st_mode):
            raise GitHubCredentialError("GitHub credential path is not a regular file")
        if info.st_size < 1 or info.st_size > _MAX_TOKEN_FILE_BYTES:
            raise GitHubCredentialError("GitHub credential file size is invalid")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise GitHubCredentialError("GitHub credential file permissions are too broad")
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            raise GitHubCredentialError("GitHub credential file cannot be read") from exc
        if len(raw) > _MAX_TOKEN_FILE_BYTES:
            raise GitHubCredentialError("GitHub credential file size is invalid")
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise GitHubCredentialError("GitHub credential token must be ASCII") from exc
        # A normal text file may have exactly one trailing line ending. Nothing
        # else is stripped: leading/trailing spaces and multi-line values fail.
        token = text[:-2] if text.endswith("\r\n") else text[:-1] if text.endswith("\n") else text
        if "\r" in token or "\n" in token or token != token.strip():
            raise GitHubCredentialError("GitHub credential token format is invalid")
        if not 20 <= len(token) <= _MAX_TOKEN_FILE_BYTES:
            raise GitHubCredentialError("GitHub credential token length is invalid")
        if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token):
            raise GitHubCredentialError("GitHub credential token format is invalid")
        return token


class EnvironmentFileGitHubCredentialProvider(FileGitHubCredentialProvider):
    """Deployment convenience: environment carries account/path, never token."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        account_key: str = "KALIV_GITHUB_ACCOUNT",
        token_file_key: str = "KALIV_GITHUB_TOKEN_FILE",
    ) -> None:
        values = os.environ if env is None else env
        account = values.get(account_key, "")
        token_file = values.get(token_file_key, "")
        if not account or not token_file:
            raise GitHubCredentialError("GitHub account/token-file configuration is missing")
        super().__init__(account=account, token_file=token_file)


class GitHubPinnedTransport:
    """Concrete credential + DNS + pinned-socket implementation of `.get()`."""

    def __init__(
        self,
        *,
        credentials: GitHubCredentialProvider,
        resolver=default_resolver,
        transport: PinnedHttpTransport | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise GitHubCredentialError("GitHub transport timeout must be numeric")
        if not 0 < float(timeout_seconds) <= 60:
            raise GitHubCredentialError("GitHub transport timeout must be within 60 seconds")
        self._credentials = credentials
        self._account = normalize_account(credentials.account)
        self._resolver = resolver
        self._transport = transport or PinnedHttpTransport()
        self._timeout = float(timeout_seconds)

    @property
    def account(self) -> str:
        return self._account

    def get(self, request: GitHubTransportRequest) -> GitHubTransportResponse:
        if request.origin != "https://api.github.com":
            raise GitHubReadRemoteError("GitHub transport origin mismatch")
        addresses = self._resolve_public_addresses()
        selected = addresses[0]
        token = self._credentials.bearer_token()
        headers = dict(request.headers)
        try:
            response = self._transport.request_with_trusted_bearer(
                request.url,
                connect_address=selected,
                headers=headers,
                bearer_token=token,
                timeout_seconds=self._timeout,
                max_wire_bytes=request.max_response_bytes,
            )
        except WebFetchError as exc:
            raise GitHubReadRemoteError("GitHub pinned transport failed") from exc
        try:
            connected = ipaddress.ip_address(response.connected_address).compressed
        except ValueError as exc:
            raise GitHubReadRemoteError("GitHub transport returned invalid peer evidence") from exc
        if connected != selected:
            raise GitHubReadRemoteError("GitHub transport peer did not match pinned DNS address")
        return GitHubTransportResponse(
            status=response.status,
            headers=response.headers,
            body=response.body,
        )

    def _resolve_public_addresses(self) -> tuple[str, ...]:
        try:
            raw: Sequence[str] = self._resolver(_GITHUB_HOST, _GITHUB_PORT)
        except WebFetchError as exc:
            raise GitHubReadRemoteError("GitHub DNS resolution failed") from exc
        except Exception as exc:
            raise GitHubReadRemoteError("GitHub DNS resolution failed") from exc
        if not raw:
            raise GitHubReadRemoteError("GitHub DNS resolution returned no addresses")
        values: list[str] = []
        for item in raw:
            try:
                parsed = ipaddress.ip_address(item)
            except ValueError as exc:
                raise GitHubReadRemoteError("GitHub DNS returned an invalid address") from exc
            if not parsed.is_global:
                raise GitHubReadRemoteError("GitHub DNS returned a non-public address")
            normalized = parsed.compressed
            if normalized not in values:
                values.append(normalized)
        values.sort(
            key=lambda value: (
                ipaddress.ip_address(value).version,
                ipaddress.ip_address(value).packed,
            )
        )
        return tuple(values)


class AccountBoundGitHubReadClient:
    """Runtime facade that binds #497 grant-account to configured credential."""

    def __init__(
        self,
        *,
        grants: GitHubConnectorGrantStore,
        transport: GitHubPinnedTransport,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        self._grants = grants
        self._transport = transport
        self._client = GitHubReadClient(
            grants=grants,
            transport=transport,
            max_response_bytes=max_response_bytes,
        )

    @property
    def account(self) -> str:
        return self._transport.account

    def read(
        self,
        grant_id: str,
        *,
        repository: str,
        operation: str,
        object_id: int | None = None,
        now: int,
    ) -> GitHubReadResult:
        grant = self._grants.get(grant_id)
        if grant is None:
            raise GitHubConnectorDenied("unknown GitHub connector grant")
        if grant.scope.account != self._transport.account:
            raise GitHubConnectorDenied("GitHub grant account does not match configured credential")
        return self._client.read(
            grant_id,
            repository=repository,
            operation=operation,
            object_id=object_id,
            now=now,
        )
