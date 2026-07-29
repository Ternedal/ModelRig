"""Dormant verified source and citation evidence for T-034.

The existing :class:`SourceReceipt` proves URL + content integrity. This module
adds the missing execution provenance: the exact common data-sharing claim and
one completed public-peer ledger chain for every initial/redirect URL in the
``FetchTrace``. It performs no DNS, socket, browser, ToolGate, route or model I/O.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .research_claim_evidence import DataSharingClaimEvidence
from .research_contract import (
    Citation,
    ResearchContractError,
    ResearchResult,
    SourceReceipt,
    canonicalize_url,
)
from .research_peer_transfer import ResearchPeerBinding
from .web_fetch import FetchTrace

SOURCE_EVIDENCE_SCHEMA = "kaliv-research-source-receipt/v1"
CITATION_EVIDENCE_SCHEMA = "kaliv-research-citation-evidence/v1"
CITATION_BUNDLE_SCHEMA = "kaliv-research-citation-bundle/v1"
_MAX_HOPS = 6
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^src_[0-9a-f]{20}$")
_VERIFIED_SOURCE_ID = re.compile(r"^vsrc_[0-9a-f]{32}$")
_BINDING_ID = re.compile(r"^rpt_[a-z0-9._-]{1,96}$")
_AUTHORIZATION_ID = re.compile(r"^rpa_[0-9a-f]{64}$")
_RECEIPT_ID = re.compile(r"^dsr_[a-z0-9._-]{1,96}$")
_MARKER = re.compile(r"^[1-9][0-9]{0,3}$")


class ResearchSourceEvidenceError(ValueError):
    """Source/citation evidence is malformed or not execution-verifiable."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _url_sha256(url: str) -> str:
    return _sha(canonicalize_url(url))


def _timestamp(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchSourceEvidenceError(f"{name} must be a non-negative integer")
    return value


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _public_address(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ResearchSourceEvidenceError(f"{name} must be an IP address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ResearchSourceEvidenceError(f"{name} must be an IP address") from exc
    if not address.is_global:
        raise ResearchSourceEvidenceError(f"{name} must be public")
    return address.compressed


def _normalized_addresses(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ResearchSourceEvidenceError("addresses must be a sequence")
    if not values or len(values) > 32:
        raise ResearchSourceEvidenceError("addresses must contain 1..32 entries")
    normalized: list[str] = []
    for value in values:
        address = _public_address(value, "address")
        if address not in normalized:
            normalized.append(address)
    normalized.sort(
        key=lambda value: (
            ipaddress.ip_address(value).version,
            ipaddress.ip_address(value).packed,
        )
    )
    return tuple(normalized)


def _dns_sha256(host: str, port: int, addresses: tuple[str, ...]) -> str:
    return _sha(
        _canonical_json(
            {"host": host, "port": port, "addresses": list(addresses)}
        )
    )


def _source_receipt_sha256(receipt: SourceReceipt) -> str:
    return _sha(_canonical_json(receipt.to_dict()))


def _trace_payload(trace: FetchTrace) -> dict[str, Any]:
    return {
        "requested_url_sha256": _url_sha256(trace.requested_url),
        "final_url_sha256": _url_sha256(trace.final_url),
        "visited_url_sha256s": [_url_sha256(url) for url in trace.visited_urls],
        "resolution_chain": [
            {
                "url_sha256": _url_sha256(url),
                "addresses": list(addresses),
            }
            for url, addresses in trace.resolved_addresses
        ],
        "source_receipt_sha256": _source_receipt_sha256(trace.receipt),
    }


def _event_value(event: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in event:
        raise ResearchSourceEvidenceError(f"{label} event is missing {key}")
    return event[key]


@dataclass(frozen=True)
class VerifiedResearchHop:
    """One exact redirect-chain hop proven by a terminal peer-ledger sequence."""

    sequence: int
    url_sha256: str
    host: str
    port: int
    binding_id: str
    authorization_id: str
    authorization_digest: str
    claim_receipt_id: str
    request_digest: str
    dns_sha256: str
    addresses: tuple[str, ...]
    selected_address: str
    connected_address: str
    bytes_sent: int
    issued_at: int
    claimed_at: int
    finished_at: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or not 0 <= self.sequence < _MAX_HOPS
        ):
            raise ResearchSourceEvidenceError("hop sequence is invalid")
        for name, value in (
            ("url_sha256", self.url_sha256),
            ("authorization_digest", self.authorization_digest),
            ("request_digest", self.request_digest),
            ("dns_sha256", self.dns_sha256),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ResearchSourceEvidenceError(f"{name} must be lowercase SHA-256")
        if not isinstance(self.binding_id, str) or _BINDING_ID.fullmatch(
            self.binding_id
        ) is None:
            raise ResearchSourceEvidenceError("binding_id is invalid")
        if not isinstance(
            self.authorization_id, str
        ) or _AUTHORIZATION_ID.fullmatch(self.authorization_id) is None:
            raise ResearchSourceEvidenceError("authorization_id is invalid")
        if self.authorization_id != f"rpa_{self.authorization_digest}":
            raise ResearchSourceEvidenceError(
                "authorization_id does not match authorization_digest"
            )
        if not isinstance(
            self.claim_receipt_id, str
        ) or _RECEIPT_ID.fullmatch(self.claim_receipt_id) is None:
            raise ResearchSourceEvidenceError("claim_receipt_id is invalid")
        if not isinstance(self.host, str) or not self.host:
            raise ResearchSourceEvidenceError("host is invalid")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ResearchSourceEvidenceError("port is invalid")
        normalized = _normalized_addresses(self.addresses)
        if normalized != self.addresses:
            raise ResearchSourceEvidenceError(
                "addresses must be unique, normalized and sorted"
            )
        selected = _public_address(self.selected_address, "selected_address")
        connected = _public_address(self.connected_address, "connected_address")
        if selected not in normalized:
            raise ResearchSourceEvidenceError(
                "selected_address is not in the DNS answer set"
            )
        if selected != normalized[0]:
            raise ResearchSourceEvidenceError(
                "selected_address is not the deterministic first public address"
            )
        if connected != selected:
            raise ResearchSourceEvidenceError(
                "connected_address does not match selected_address"
            )
        if _dns_sha256(self.host, self.port, normalized) != self.dns_sha256:
            raise ResearchSourceEvidenceError("dns_sha256 does not match the hop")
        if (
            isinstance(self.bytes_sent, bool)
            or not isinstance(self.bytes_sent, int)
            or self.bytes_sent < 0
        ):
            raise ResearchSourceEvidenceError("bytes_sent is invalid")
        issued = _timestamp(self.issued_at, "issued_at")
        claimed = _timestamp(self.claimed_at, "claimed_at")
        finished = _timestamp(self.finished_at, "finished_at")
        if not issued <= claimed <= finished:
            raise ResearchSourceEvidenceError("hop timestamps are out of order")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "binding_id": self.binding_id,
            "authorization_id": self.authorization_id,
            "authorization_digest": self.authorization_digest,
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "dns_sha256": self.dns_sha256,
            "addresses": list(self.addresses),
            "selected_address": self.selected_address,
            "connected_address": self.connected_address,
            "bytes_sent": self.bytes_sent,
            "issued_at": self.issued_at,
            "claimed_at": self.claimed_at,
            "finished_at": self.finished_at,
        }

    @property
    def digest(self) -> str:
        return _sha(_canonical_json(self.digest_payload()))

    def to_dict(self) -> dict[str, Any]:
        value = self.digest_payload()
        value.update(
            {
                "issued_at": _iso(self.issued_at),
                "claimed_at": _iso(self.claimed_at),
                "finished_at": _iso(self.finished_at),
                "hop_sha256": self.digest,
            }
        )
        return value

    @classmethod
    def from_ledger(
        cls,
        *,
        sequence: int,
        url: str,
        binding: ResearchPeerBinding,
        events: Iterable[Mapping[str, Any]],
    ) -> "VerifiedResearchHop":
        if not isinstance(binding, ResearchPeerBinding):
            raise ResearchSourceEvidenceError(
                "binding must be a ResearchPeerBinding"
            )
        canonical = canonicalize_url(url)
        parsed = urlsplit(canonical)
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (
            binding.url_sha256 != _url_sha256(canonical)
            or binding.host != host
            or binding.port != port
        ):
            raise ResearchSourceEvidenceError(
                "peer binding does not match the exact hop URL"
            )
        matching = [
            event
            for event in events
            if isinstance(event, Mapping)
            and event.get("binding_id") == binding.binding_id
        ]
        if [event.get("event_type") for event in matching] != [
            "issued",
            "claimed",
            "finished",
        ]:
            raise ResearchSourceEvidenceError(
                "peer ledger must contain exact issued/claimed/finished events"
            )
        issued, claimed, finished = matching
        for label, event in (
            ("issued", issued),
            ("claimed", claimed),
            ("finished", finished),
        ):
            expected = {
                "authorization_id": binding.authorization_id,
                "authorization_digest": binding.authorization_digest,
                "claim_receipt_id": binding.claim_receipt_id,
                "request_digest": binding.request_digest,
                "url_sha256": binding.url_sha256,
                "host": binding.host,
                "port": binding.port,
                "dns_sha256": binding.dns_sha256,
                "selected_address": binding.selected_address,
            }
            for key, value in expected.items():
                if _event_value(event, key, label) != value:
                    raise ResearchSourceEvidenceError(
                        f"{label} event {key} does not match the peer binding"
                    )
        if finished.get("outcome") != "connected":
            raise ResearchSourceEvidenceError(
                "finished peer event is not a connected outcome"
            )
        if finished.get("error_code") is not None:
            raise ResearchSourceEvidenceError(
                "connected peer event cannot include error_code"
            )
        peer = finished.get("peer_address")
        if peer != binding.selected_address:
            raise ResearchSourceEvidenceError(
                "finished peer event does not prove the selected address"
            )
        bytes_sent = finished.get("bytes_sent")
        if (
            isinstance(bytes_sent, bool)
            or not isinstance(bytes_sent, int)
            or not 0 <= bytes_sent <= binding.max_bytes
        ):
            raise ResearchSourceEvidenceError(
                "finished peer event bytes exceed the authorized ceiling"
            )
        issued_at = _timestamp(_event_value(issued, "ts", "issued"), "issued.ts")
        claimed_at = _timestamp(
            _event_value(claimed, "ts", "claimed"), "claimed.ts"
        )
        finished_at = _timestamp(
            _event_value(finished, "ts", "finished"), "finished.ts"
        )
        if issued_at != binding.issued_at:
            raise ResearchSourceEvidenceError(
                "issued event timestamp does not match the binding"
            )
        if finished_at >= binding.expires_at:
            raise ResearchSourceEvidenceError(
                "finished peer event is not inside the binding lifetime"
            )
        return cls(
            sequence=sequence,
            url_sha256=binding.url_sha256,
            host=binding.host,
            port=binding.port,
            binding_id=binding.binding_id,
            authorization_id=binding.authorization_id,
            authorization_digest=binding.authorization_digest,
            claim_receipt_id=binding.claim_receipt_id,
            request_digest=binding.request_digest,
            dns_sha256=binding.dns_sha256,
            addresses=binding.addresses,
            selected_address=binding.selected_address,
            connected_address=peer,
            bytes_sent=bytes_sent,
            issued_at=issued_at,
            claimed_at=claimed_at,
            finished_at=finished_at,
        )


@dataclass(frozen=True)
class VerifiedResearchSourceReceipt:
    """A source receipt bound to the exact T-032 claim and redirect peer chain."""

    source: SourceReceipt
    claim_receipt_id: str
    request_digest: str
    source_receipt_sha256: str
    fetch_trace_sha256: str
    hop_chain_sha256: str
    hops: tuple[VerifiedResearchHop, ...]
    verified_at: int
    schema: str = SOURCE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SOURCE_EVIDENCE_SCHEMA:
            raise ResearchSourceEvidenceError(
                "unsupported verified source receipt schema"
            )
        if not isinstance(self.source, SourceReceipt):
            raise ResearchSourceEvidenceError("source must be a SourceReceipt")
        if not isinstance(
            self.claim_receipt_id, str
        ) or _RECEIPT_ID.fullmatch(self.claim_receipt_id) is None:
            raise ResearchSourceEvidenceError("claim_receipt_id is invalid")
        for name, value in (
            ("request_digest", self.request_digest),
            ("source_receipt_sha256", self.source_receipt_sha256),
            ("fetch_trace_sha256", self.fetch_trace_sha256),
            ("hop_chain_sha256", self.hop_chain_sha256),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ResearchSourceEvidenceError(f"{name} must be lowercase SHA-256")
        if self.source_receipt_sha256 != _source_receipt_sha256(self.source):
            raise ResearchSourceEvidenceError(
                "source_receipt_sha256 does not match the source"
            )
        if not 1 <= len(self.hops) <= _MAX_HOPS:
            raise ResearchSourceEvidenceError("verified source requires 1..6 hops")
        if tuple(hop.sequence for hop in self.hops) != tuple(range(len(self.hops))):
            raise ResearchSourceEvidenceError("hop sequences must be contiguous")
        if len({hop.binding_id for hop in self.hops}) != len(self.hops):
            raise ResearchSourceEvidenceError("peer binding ids must be unique")
        if len({hop.authorization_id for hop in self.hops}) != len(self.hops):
            raise ResearchSourceEvidenceError("peer authorization ids must be unique")
        for hop in self.hops:
            if (
                hop.claim_receipt_id != self.claim_receipt_id
                or hop.request_digest != self.request_digest
            ):
                raise ResearchSourceEvidenceError(
                    "hop does not match the common data-sharing claim"
                )
        expected_chain = _sha(
            _canonical_json([hop.digest_payload() for hop in self.hops])
        )
        if self.hop_chain_sha256 != expected_chain:
            raise ResearchSourceEvidenceError("hop_chain_sha256 does not match")
        verified = _timestamp(self.verified_at, "verified_at")
        if verified != max(hop.finished_at for hop in self.hops):
            raise ResearchSourceEvidenceError(
                "verified_at must equal the last peer completion"
            )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_id": self.source.source_id,
            "source_receipt_sha256": self.source_receipt_sha256,
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "fetch_trace_sha256": self.fetch_trace_sha256,
            "hop_chain_sha256": self.hop_chain_sha256,
            "verified_at": self.verified_at,
        }

    @property
    def digest(self) -> str:
        return _sha(_canonical_json(self.digest_payload()))

    @property
    def verified_source_id(self) -> str:
        return f"vsrc_{self.digest[:32]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "verified_source_id": self.verified_source_id,
            "source": self.source.to_dict(),
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "source_receipt_sha256": self.source_receipt_sha256,
            "fetch_trace_sha256": self.fetch_trace_sha256,
            "hop_chain_sha256": self.hop_chain_sha256,
            "hops": [hop.to_dict() for hop in self.hops],
            "verified_at": _iso(self.verified_at),
            "production_activation": False,
        }

    @classmethod
    def from_execution(
        cls,
        *,
        trace: FetchTrace,
        claim: DataSharingClaimEvidence,
        bindings: Sequence[ResearchPeerBinding],
        peer_events: Iterable[Mapping[str, Any]],
    ) -> "VerifiedResearchSourceReceipt":
        if not isinstance(trace, FetchTrace):
            raise ResearchSourceEvidenceError("trace must be a FetchTrace")
        if not isinstance(claim, DataSharingClaimEvidence):
            raise ResearchSourceEvidenceError(
                "claim must be DataSharingClaimEvidence"
            )
        visited = tuple(canonicalize_url(url) for url in trace.visited_urls)
        resolved = tuple(
            (canonicalize_url(url), tuple(addresses))
            for url, addresses in trace.resolved_addresses
        )
        if (
            not visited
            or len(visited) != len(resolved)
            or len(visited) != len(bindings)
            or len(visited) > _MAX_HOPS
        ):
            raise ResearchSourceEvidenceError(
                "trace, resolution and peer-binding hop counts differ"
            )
        if trace.requested_url != visited[0] or trace.final_url != visited[-1]:
            raise ResearchSourceEvidenceError(
                "trace endpoints do not match the visited chain"
            )
        if trace.receipt.url != trace.final_url:
            raise ResearchSourceEvidenceError(
                "source receipt URL does not match the final trace URL"
            )
        events = tuple(peer_events)
        hops: list[VerifiedResearchHop] = []
        for index, (url, addresses, binding) in enumerate(
            zip(
                visited,
                (item[1] for item in resolved),
                bindings,
                strict=True,
            )
        ):
            normalized = _normalized_addresses(addresses)
            if normalized != addresses:
                raise ResearchSourceEvidenceError(
                    "fetch trace addresses are not normalized and sorted"
                )
            if binding.addresses != normalized:
                raise ResearchSourceEvidenceError(
                    "fetch trace DNS answers do not match the peer binding"
                )
            hop = VerifiedResearchHop.from_ledger(
                sequence=index,
                url=url,
                binding=binding,
                events=events,
            )
            if (
                hop.claim_receipt_id != claim.receipt_id
                or hop.request_digest != claim.request_digest
                or binding.max_bytes != claim.max_bytes
                or binding.issued_at < claim.claimed_at
                or binding.expires_at > claim.expires_at
            ):
                raise ResearchSourceEvidenceError(
                    "peer hop is outside the exact common claim"
                )
            hops.append(hop)
        if {
            event.get("binding_id")
            for event in events
            if isinstance(event, Mapping)
        } != {hop.binding_id for hop in hops}:
            raise ResearchSourceEvidenceError(
                "peer event inventory contains unknown or missing bindings"
            )
        source_digest = _source_receipt_sha256(trace.receipt)
        trace_digest = _sha(_canonical_json(_trace_payload(trace)))
        chain_digest = _sha(
            _canonical_json([hop.digest_payload() for hop in hops])
        )
        return cls(
            source=trace.receipt,
            claim_receipt_id=claim.receipt_id,
            request_digest=claim.request_digest,
            source_receipt_sha256=source_digest,
            fetch_trace_sha256=trace_digest,
            hop_chain_sha256=chain_digest,
            hops=tuple(hops),
            verified_at=max(hop.finished_at for hop in hops),
        )


@dataclass(frozen=True)
class VerifiedCitationEvidence:
    marker: str
    statement_sha256: str
    source_ids: tuple[str, ...]
    verified_source_ids: tuple[str, ...]
    schema: str = CITATION_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CITATION_EVIDENCE_SCHEMA:
            raise ResearchSourceEvidenceError(
                "unsupported citation evidence schema"
            )
        if not isinstance(self.marker, str) or _MARKER.fullmatch(self.marker) is None:
            raise ResearchSourceEvidenceError("citation marker is invalid")
        if not isinstance(
            self.statement_sha256, str
        ) or _SHA256.fullmatch(self.statement_sha256) is None:
            raise ResearchSourceEvidenceError(
                "statement_sha256 must be lowercase SHA-256"
            )
        if (
            not self.source_ids
            or len(self.source_ids) != len(set(self.source_ids))
            or any(_SOURCE_ID.fullmatch(value) is None for value in self.source_ids)
        ):
            raise ResearchSourceEvidenceError("citation source_ids are invalid")
        if (
            len(self.verified_source_ids) != len(self.source_ids)
            or len(self.verified_source_ids)
            != len(set(self.verified_source_ids))
            or any(
                _VERIFIED_SOURCE_ID.fullmatch(value) is None
                for value in self.verified_source_ids
            )
        ):
            raise ResearchSourceEvidenceError(
                "citation verified_source_ids are invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "marker": self.marker,
            "statement_sha256": self.statement_sha256,
            "source_ids": list(self.source_ids),
            "verified_source_ids": list(self.verified_source_ids),
        }


@dataclass(frozen=True)
class VerifiedCitationBundle:
    answer_sha256: str
    source_receipts: tuple[VerifiedResearchSourceReceipt, ...]
    citations: tuple[VerifiedCitationEvidence, ...]
    schema: str = CITATION_BUNDLE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CITATION_BUNDLE_SCHEMA:
            raise ResearchSourceEvidenceError(
                "unsupported citation bundle schema"
            )
        if not isinstance(
            self.answer_sha256, str
        ) or _SHA256.fullmatch(self.answer_sha256) is None:
            raise ResearchSourceEvidenceError(
                "answer_sha256 must be lowercase SHA-256"
            )
        source_ids = [receipt.source.source_id for receipt in self.source_receipts]
        verified_ids = [receipt.verified_source_id for receipt in self.source_receipts]
        if (
            not source_ids
            or len(source_ids) != len(set(source_ids))
            or len(verified_ids) != len(set(verified_ids))
        ):
            raise ResearchSourceEvidenceError(
                "citation bundle source inventory is invalid"
            )
        if not self.citations:
            raise ResearchSourceEvidenceError(
                "citation bundle requires citation evidence"
            )
        known = set(verified_ids)
        for citation in self.citations:
            if set(citation.verified_source_ids) - known:
                raise ResearchSourceEvidenceError(
                    "citation evidence references an unknown verified source"
                )

    @property
    def digest(self) -> str:
        return _sha(
            _canonical_json(
                {
                    "schema": self.schema,
                    "answer_sha256": self.answer_sha256,
                    "verified_source_ids": [
                        receipt.verified_source_id
                        for receipt in self.source_receipts
                    ],
                    "citations": [citation.to_dict() for citation in self.citations],
                }
            )
        )

    @property
    def bundle_id(self) -> str:
        return f"rcb_{self.digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "bundle_id": self.bundle_id,
            "answer_sha256": self.answer_sha256,
            "sources": [receipt.to_dict() for receipt in self.source_receipts],
            "citations": [citation.to_dict() for citation in self.citations],
            "production_activation": False,
        }

    @classmethod
    def from_result(
        cls,
        result: ResearchResult,
        verified_sources: Sequence[VerifiedResearchSourceReceipt],
    ) -> "VerifiedCitationBundle":
        if not isinstance(result, ResearchResult):
            raise ResearchSourceEvidenceError("result must be a ResearchResult")
        if isinstance(verified_sources, (str, bytes)) or not isinstance(
            verified_sources, Sequence
        ):
            raise ResearchSourceEvidenceError(
                "verified_sources must be a sequence"
            )
        by_source: dict[str, VerifiedResearchSourceReceipt] = {}
        for receipt in verified_sources:
            if not isinstance(receipt, VerifiedResearchSourceReceipt):
                raise ResearchSourceEvidenceError(
                    "verified source inventory contains an invalid receipt"
                )
            source_id = receipt.source.source_id
            if source_id in by_source:
                raise ResearchSourceEvidenceError(
                    "verified source inventory contains duplicate source ids"
                )
            by_source[source_id] = receipt
        result_sources = {source.source_id: source for source in result.sources}
        if set(by_source) != set(result_sources):
            raise ResearchSourceEvidenceError(
                "every result source must have exact verified execution evidence"
            )
        for source_id, source in result_sources.items():
            if by_source[source_id].source != source:
                raise ResearchSourceEvidenceError(
                    "verified source does not match the result source receipt"
                )
        citations: list[VerifiedCitationEvidence] = []
        for citation in result.citations:
            if not isinstance(citation, Citation):
                raise ResearchSourceEvidenceError(
                    "result citation has an invalid type"
                )
            receipts = tuple(by_source[source_id] for source_id in citation.source_ids)
            citations.append(
                VerifiedCitationEvidence(
                    marker=citation.marker,
                    statement_sha256=_sha(citation.statement),
                    source_ids=citation.source_ids,
                    verified_source_ids=tuple(
                        receipt.verified_source_id for receipt in receipts
                    ),
                )
            )
        return cls(
            answer_sha256=_sha(result.answer),
            source_receipts=tuple(
                by_source[source.source_id] for source in result.sources
            ),
            citations=tuple(citations),
        )
