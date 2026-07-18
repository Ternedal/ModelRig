"""Vendor-neutral contract for read-only web research with verifiable citations.

This module deliberately contains no browser, HTTP client, LLM, ToolGate or UI
integration. A future BrowserUse, Playwright or plain-HTTP adapter must satisfy
this contract instead of defining ModelRig's trust boundary itself.

The v1 contract is intentionally narrow:

* public ``http``/``https`` URLs only;
* explicit exact/wildcard domain allowlists;
* ephemeral browser profile;
* no credentials, login, uploads or downloads;
* bounded pages, steps, bytes and wall-clock time;
* deterministic source receipts tied to canonical URL + content hash;
* citations must reference receipts that are present in the result.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

SCHEMA_VERSION = "modelrig.research.v1"
_MAX_QUERY_CHARS = 4_000
_MAX_TITLE_CHARS = 500
_MAX_EXCERPT_CHARS = 2_000
_SOURCE_ID_RE = re.compile(r"^src_[0-9a-f]{20}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKER_RE = re.compile(r"^[1-9][0-9]{0,3}$")
_DOMAIN_RE = re.compile(
    r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ResearchContractError(ValueError):
    """The adapter produced or requested something outside the v1 contract."""


def _clean_text(value: str, *, name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ResearchContractError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ResearchContractError(f"{name} must not be empty")
    if len(cleaned) > max_chars:
        raise ResearchContractError(f"{name} exceeds {max_chars} characters")
    return cleaned


def _canonical_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ResearchContractError("URL host is not valid IDNA") from exc


def canonicalize_url(raw_url: str) -> str:
    """Return the stable citation form of a public web URL.

    Fragments never identify fetched content and are removed. Host names are
    lower-cased/IDNA-normalized and default ports are removed. Query order is
    preserved because reordering signed or repeated parameters can change the
    resource.
    """
    raw = _clean_text(raw_url, name="url", max_chars=8_192)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ResearchContractError("URL has an invalid port") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ResearchContractError("only http/https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ResearchContractError("URL credentials are forbidden")
    if not parsed.hostname:
        raise ResearchContractError("URL must include a host")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ResearchContractError("direct IP URLs are forbidden; use an allowlisted public domain")

    host = _canonical_host(parsed.hostname)
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    canonical = SplitResult(scheme, netloc, path, parsed.query, "")
    return urlunsplit(canonical)


def normalize_domain_rule(rule: str) -> str:
    """Normalize one exact domain or explicit ``*.subdomain`` rule."""
    value = _clean_text(rule, name="domain rule", max_chars=255).lower().rstrip(".")
    wildcard = value.startswith("*.")
    domain = value[2:] if wildcard else value
    if "://" in domain or "/" in domain or ":" in domain:
        raise ResearchContractError("domain rules contain host names only")
    domain = _canonical_host(domain)
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ResearchContractError("IP literals are not valid domain rules")
    if domain == "localhost" or domain.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ResearchContractError("local/internal domain rules are forbidden in v1")
    normalized = f"*.{domain}" if wildcard else domain
    if not _DOMAIN_RE.fullmatch(normalized):
        raise ResearchContractError(f"invalid domain rule: {rule}")
    return normalized


def host_allowed(url: str, rules: Iterable[str]) -> bool:
    """Check an URL against exact rules and explicit wildcard subdomain rules."""
    canonical = canonicalize_url(url)
    host = urlsplit(canonical).hostname or ""
    normalized = tuple(normalize_domain_rule(rule) for rule in rules)
    for rule in normalized:
        if rule.startswith("*."):
            suffix = rule[1:]
            if host.endswith(suffix) and host != rule[2:]:
                return True
        elif host == rule:
            return True
    return False


@dataclass(frozen=True)
class ReadOnlyBrowserPolicy:
    """Hard boundary shared by all v1 research adapters."""

    allowed_domains: tuple[str, ...]
    max_steps: int = 12
    max_pages: int = 8
    timeout_seconds: int = 90
    max_source_bytes: int = 2_000_000
    profile_mode: str = "ephemeral"
    credentials: str = "deny"
    logins: str = "deny"
    uploads: str = "deny"
    downloads: str = "deny"

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(normalize_domain_rule(d) for d in self.allowed_domains))
        if not normalized:
            raise ResearchContractError("allowed_domains must fail closed, not be empty")
        object.__setattr__(self, "allowed_domains", normalized)

        bounds = {
            "max_steps": (self.max_steps, 1, 50),
            "max_pages": (self.max_pages, 1, 25),
            "timeout_seconds": (self.timeout_seconds, 1, 300),
            "max_source_bytes": (self.max_source_bytes, 1_024, 10_000_000),
        }
        for name, (value, minimum, maximum) in bounds.items():
            if not isinstance(value, int) or not minimum <= value <= maximum:
                raise ResearchContractError(f"{name} must be between {minimum} and {maximum}")

        fixed = {
            "profile_mode": (self.profile_mode, "ephemeral"),
            "credentials": (self.credentials, "deny"),
            "logins": (self.logins, "deny"),
            "uploads": (self.uploads, "deny"),
            "downloads": (self.downloads, "deny"),
        }
        for name, (actual, required) in fixed.items():
            if actual != required:
                raise ResearchContractError(f"v1 requires {name}={required!r}")

    def require_allowed_url(self, url: str) -> str:
        canonical = canonicalize_url(url)
        if not host_allowed(canonical, self.allowed_domains):
            raise ResearchContractError("URL host is outside the research allowlist")
        return canonical

    def require_public_address(self, address: str) -> str:
        """Reject loopback, private, link-local, multicast and reserved targets.

        Adapters must apply this to every DNS answer immediately before opening
        a connection and again after redirects. That closes the gap between an
        allowed host name and where it resolves at execution time.
        """
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ResearchContractError("resolved address is not a valid IP") from exc
        if not parsed.is_global:
            raise ResearchContractError("resolved address is not public")
        return parsed.compressed

    def accept_receipt(self, receipt: "SourceReceipt") -> "SourceReceipt":
        self.require_allowed_url(receipt.url)
        if receipt.bytes_read > self.max_source_bytes:
            raise ResearchContractError("source exceeds max_source_bytes")
        return receipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_domains": list(self.allowed_domains),
            "max_steps": self.max_steps,
            "max_pages": self.max_pages,
            "timeout_seconds": self.timeout_seconds,
            "max_source_bytes": self.max_source_bytes,
            "profile_mode": self.profile_mode,
            "credentials": self.credentials,
            "logins": self.logins,
            "uploads": self.uploads,
            "downloads": self.downloads,
        }


@dataclass(frozen=True)
class ResearchRequest:
    query: str
    policy: ReadOnlyBrowserPolicy
    max_sources: int = 5
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _clean_text(self.query, name="query", max_chars=_MAX_QUERY_CHARS))
        if self.schema_version != SCHEMA_VERSION:
            raise ResearchContractError(f"unsupported schema_version: {self.schema_version}")
        if not isinstance(self.max_sources, int) or not 1 <= self.max_sources <= self.policy.max_pages:
            raise ResearchContractError("max_sources must be between 1 and policy.max_pages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query": self.query,
            "max_sources": self.max_sources,
            "policy": self.policy.to_dict(),
        }


@dataclass(frozen=True)
class SourceReceipt:
    source_id: str
    url: str
    title: str
    retrieved_at: str
    content_sha256: str
    excerpt: str
    media_type: str
    bytes_read: int
    adapter: str

    def __post_init__(self) -> None:
        canonical = canonicalize_url(self.url)
        object.__setattr__(self, "url", canonical)
        if not _SOURCE_ID_RE.fullmatch(self.source_id):
            raise ResearchContractError("source_id has an invalid format")
        if not _SHA256_RE.fullmatch(self.content_sha256):
            raise ResearchContractError("content_sha256 must be lowercase SHA-256")
        if self.source_id != source_id_for(canonical, self.content_sha256):
            raise ResearchContractError("source_id does not match URL + content hash")
        object.__setattr__(self, "title", _clean_text(self.title, name="title", max_chars=_MAX_TITLE_CHARS))
        if not isinstance(self.excerpt, str) or len(self.excerpt) > _MAX_EXCERPT_CHARS:
            raise ResearchContractError(f"excerpt exceeds {_MAX_EXCERPT_CHARS} characters")
        if not isinstance(self.bytes_read, int) or self.bytes_read < 0:
            raise ResearchContractError("bytes_read must be a non-negative integer")
        object.__setattr__(self, "media_type", _clean_text(self.media_type, name="media_type", max_chars=100).lower())
        object.__setattr__(self, "adapter", _clean_text(self.adapter, name="adapter", max_chars=100))
        try:
            stamp = datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResearchContractError("retrieved_at must be ISO-8601") from exc
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ResearchContractError("retrieved_at must be UTC")

    @classmethod
    def from_content(
        cls,
        *,
        url: str,
        title: str,
        content: bytes | str,
        excerpt: str,
        media_type: str,
        adapter: str,
        retrieved_at: datetime | None = None,
    ) -> "SourceReceipt":
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        canonical = canonicalize_url(url)
        digest = hashlib.sha256(raw).hexdigest()
        stamp = retrieved_at or datetime.now(timezone.utc)
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ResearchContractError("retrieved_at must be timezone-aware UTC")
        return cls(
            source_id=source_id_for(canonical, digest),
            url=canonical,
            title=title,
            retrieved_at=stamp.isoformat().replace("+00:00", "Z"),
            content_sha256=digest,
            excerpt=excerpt,
            media_type=media_type,
            bytes_read=len(raw),
            adapter=adapter,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "retrieved_at": self.retrieved_at,
            "content_sha256": self.content_sha256,
            "excerpt": self.excerpt,
            "media_type": self.media_type,
            "bytes_read": self.bytes_read,
            "adapter": self.adapter,
        }


def source_id_for(canonical_url: str, content_sha256: str) -> str:
    if not _SHA256_RE.fullmatch(content_sha256):
        raise ResearchContractError("content_sha256 must be lowercase SHA-256")
    material = f"{canonicalize_url(canonical_url)}\0{content_sha256}".encode("utf-8")
    return "src_" + hashlib.sha256(material).hexdigest()[:20]


@dataclass(frozen=True)
class Citation:
    marker: str
    statement: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _MARKER_RE.fullmatch(self.marker):
            raise ResearchContractError("citation marker must be an integer from 1 to 9999")
        object.__setattr__(self, "statement", _clean_text(self.statement, name="statement", max_chars=2_000))
        source_ids = tuple(dict.fromkeys(self.source_ids))
        if not source_ids or any(not _SOURCE_ID_RE.fullmatch(s) for s in source_ids):
            raise ResearchContractError("citation must reference one or more valid source_ids")
        object.__setattr__(self, "source_ids", source_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker": self.marker,
            "statement": self.statement,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class ResearchResult:
    answer: str
    sources: tuple[SourceReceipt, ...]
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ResearchContractError(f"unsupported schema_version: {self.schema_version}")
        object.__setattr__(self, "answer", _clean_text(self.answer, name="answer", max_chars=100_000))
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ResearchContractError("source receipts must have unique source_ids")
        if not self.citations:
            raise ResearchContractError("a research answer must include citations")
        markers = [citation.marker for citation in self.citations]
        if len(markers) != len(set(markers)):
            raise ResearchContractError("citation markers must be unique")
        known = set(source_ids)
        for citation in self.citations:
            missing = set(citation.source_ids) - known
            if missing:
                raise ResearchContractError(f"citation references unknown source_ids: {sorted(missing)}")
            if f"[{citation.marker}]" not in self.answer:
                raise ResearchContractError(f"answer is missing citation marker [{citation.marker}]")
        cleaned_warnings = tuple(
            _clean_text(warning, name="warning", max_chars=1_000) for warning in self.warnings
        )
        object.__setattr__(self, "warnings", cleaned_warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "answer": self.answer,
            "sources": [source.to_dict() for source in self.sources],
            "citations": [citation.to_dict() for citation in self.citations],
            "warnings": list(self.warnings),
        }
