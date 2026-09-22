"""C22-B strict operator-declared production CognitiveProfile resolution.

The existing CognitiveProfile contract requires normalized capacity fields, but
ModelRig has no benchmark authority for inventing production scores. This
module therefore resolves a profile only from a bounded local operator
configuration. Missing configuration means "unavailable", never guessed
defaults.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CognitiveProfile
from .cycle import cognitive_profile_ref


CONSCIOUSNESS_PROFILE_PATH_ENV = "KALIV_CONSCIOUSNESS_PROFILE_PATH"
CONSCIOUSNESS_PROFILE_PATH_DEFAULT = "./consciousness-profile.json"
MAX_PROFILE_CONFIG_BYTES = 16 * 1024

NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]


class ProductionCognitiveProfileError(RuntimeError):
    pass


class _DuplicateJSONKeyError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ProductionCognitiveProfileConfig(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/production-cognitive-profile-config/v1"
    ]
    provider: Annotated[str, Field(min_length=1, max_length=128)]
    model: NonEmptyRef
    reasoning_depth: UnitInterval
    planning_capacity: UnitInterval
    context_capacity_tokens: Annotated[int, Field(ge=1, le=2_000_000, strict=True)]
    multimodal_capacity: UnitInterval
    tool_reasoning: UnitInterval
    uncertainty_calibration: UnitInterval
    source_ref: NonEmptyRef
    capacity_basis: Literal["operator_declared"]
    production_activation: Literal[False]


class ProductionCognitiveProfileReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/production-cognitive-profile-receipt/v1"
    ]
    config_ref: NonEmptyRef
    profile_ref: NonEmptyRef
    source_ref: NonEmptyRef
    provider: Annotated[str, Field(min_length=1, max_length=128)]
    model: NonEmptyRef
    capacity_basis: Literal["operator_declared"]
    measured_capability_claim: Literal[False]
    profile_ephemeral: Literal[True]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    action_authority: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]


class ProductionCognitiveProfileResolution(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/production-cognitive-profile-resolution/v1"
    ]
    profile: CognitiveProfile
    receipt: ProductionCognitiveProfileReceipt
    production_activation: Literal[False]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def production_cognitive_profile_path(
    env: Mapping[str, str] | None = None,
) -> Path:
    if env is None:
        raw = os.getenv(
            "KALIV_CONSCIOUSNESS_PROFILE_PATH",
            CONSCIOUSNESS_PROFILE_PATH_DEFAULT,
        )
    else:
        raw = env.get(
            CONSCIOUSNESS_PROFILE_PATH_ENV,
            CONSCIOUSNESS_PROFILE_PATH_DEFAULT,
        )
    if not isinstance(raw, str) or not raw.strip():
        raise ProductionCognitiveProfileError(
            "Consciousness profile path must be a non-empty string"
        )
    return Path(raw)


def _read_config(path: Path) -> ProductionCognitiveProfileConfig:
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ProductionCognitiveProfileError(
            "cannot inspect Consciousness profile config"
        ) from exc

    if stat.st_size <= 0 or stat.st_size > MAX_PROFILE_CONFIG_BYTES:
        raise ProductionCognitiveProfileError(
            "Consciousness profile config size is outside the allowed bound"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProductionCognitiveProfileError(
            "cannot read Consciousness profile config"
        ) from exc
    if len(raw) > MAX_PROFILE_CONFIG_BYTES:
        raise ProductionCognitiveProfileError(
            "Consciousness profile config exceeds the allowed bound"
        )

    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKeyError, ValueError) as exc:
        raise ProductionCognitiveProfileError(
            "invalid Consciousness profile JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProductionCognitiveProfileError(
            "Consciousness profile config must be one JSON object"
        )

    try:
        config = ProductionCognitiveProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise ProductionCognitiveProfileError(
            "Consciousness profile config failed strict validation"
        ) from exc

    # Defensive finite check independent of parser/model implementation.
    for value in (
        config.reasoning_depth,
        config.planning_capacity,
        config.multimodal_capacity,
        config.tool_reasoning,
        config.uncertainty_calibration,
    ):
        if not math.isfinite(value):
            raise ProductionCognitiveProfileError(
                "Consciousness profile contains non-finite capacity"
            )
    return config


def resolve_production_cognitive_profile(
    *,
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProductionCognitiveProfileResolution | None:
    """Resolve one explicit local profile; missing config means unavailable."""
    resolved_path = (
        Path(path)
        if path is not None
        else production_cognitive_profile_path(env)
    )
    try:
        config = _read_config(resolved_path)
    except FileNotFoundError:
        return None

    config_ref = (
        "cognitive-profile-config:"
        + hashlib.sha256(_canonical_json(config)).hexdigest()
    )
    profile_id = "cog-" + _sha256(
        {
            "config_ref": config_ref,
            "projection": "production-cognitive-profile-v1",
        }
    )[:32]
    engine_instance_id = "engine-instance:" + _sha256(
        {
            "provider": config.provider,
            "model": config.model,
            "source_ref": config.source_ref,
        }
    )

    profile = CognitiveProfile(
        schema="kaliv-consciousness-core/cognitive-profile/v1",
        profile_id=profile_id,
        engine_instance_id=engine_instance_id,
        provider=config.provider,
        model=config.model,
        reasoning_depth=config.reasoning_depth,
        planning_capacity=config.planning_capacity,
        context_capacity_tokens=config.context_capacity_tokens,
        multimodal_capacity=config.multimodal_capacity,
        tool_reasoning=config.tool_reasoning,
        uncertainty_calibration=config.uncertainty_calibration,
        ephemeral=True,
        identity_authority=False,
        persistent_state_authority=False,
        action_authority=False,
        production_activation=False,
    )
    receipt = ProductionCognitiveProfileReceipt(
        schema="kaliv-consciousness-core/production-cognitive-profile-receipt/v1",
        config_ref=config_ref,
        profile_ref=cognitive_profile_ref(profile),
        source_ref=config.source_ref,
        provider=config.provider,
        model=config.model,
        capacity_basis="operator_declared",
        measured_capability_claim=False,
        profile_ephemeral=True,
        identity_authority=False,
        persistent_state_authority=False,
        action_authority=False,
        model_calls=0,
        production_activation=False,
    )
    return ProductionCognitiveProfileResolution(
        schema="kaliv-consciousness-core/production-cognitive-profile-resolution/v1",
        profile=profile,
        receipt=receipt,
        production_activation=False,
    )
