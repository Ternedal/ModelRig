"""Independent authenticated semantic review with durable artifact publication."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _semantic_review_core as _core

# Preserve the complete existing semantic-review model, signer and verifier API.
# The core module owns models and canonical loaders; this facade owns publication.
for _name, _value in vars(_core).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

from .durable_publication import DurablePublicationError, create_once_file

SemanticReviewError = _core.SemanticReviewError
SemanticReviewRequest = _core.SemanticReviewRequest
SignedSemanticReviewVerdict = _core.SignedSemanticReviewVerdict
tier_a_toolhost_sha256 = _core.tier_a_toolhost_sha256


def _tier_a_toolhost_sha256_proxy(*args: Any, **kwargs: Any) -> str:
    return globals()["tier_a_toolhost_sha256"](*args, **kwargs)


# Preserve the established public patch point used by semantic-review fixtures.
_core.tier_a_toolhost_sha256 = _tier_a_toolhost_sha256_proxy


def _write_canonical_file(path: Path, value: Any, *, name: str) -> str:
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or _core._has_linkish_component(output.parent)
        or not output.parent.is_dir()
    ):
        raise SemanticReviewError(
            "semantic review output path is unsafe or already exists"
        )
    canonical_json = getattr(value, "canonical_json", None)
    if canonical_json is None:
        raise SemanticReviewError(f"{name} output is invalid")
    payload = canonical_json().encode("utf-8")
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise SemanticReviewError(
            f"{name} could not be durably published"
        ) from exc
    return _core._sha256_bytes(payload)


def write_semantic_review_request(
    path: Path,
    request: SemanticReviewRequest,
) -> str:
    if not isinstance(request, SemanticReviewRequest):
        raise SemanticReviewError(
            "semantic review request output is invalid"
        )
    return _write_canonical_file(
        path,
        request,
        name="semantic review request",
    )


def write_signed_semantic_review_verdict(
    path: Path,
    signed_verdict: SignedSemanticReviewVerdict,
) -> str:
    if not isinstance(signed_verdict, SignedSemanticReviewVerdict):
        raise SemanticReviewError(
            "signed semantic review verdict output is invalid"
        )
    return _write_canonical_file(
        path,
        signed_verdict,
        name="signed semantic review verdict",
    )
