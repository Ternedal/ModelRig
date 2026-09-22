"""C22-A operator-calibrated transient CognitiveProfile source.

The source is intentionally configuration-only. It reads one bounded local JSON
file, validates an explicit capability description and constructs the transient
CognitiveProfile used by a later explicit cognitive step.

No model call, route, scheduler, persistence or identity authority lives here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .. import paths as _paths
from .contracts import CognitiveProfile
from .cycle import cognitive_profile_ref


CONSCIOUSNESS_PROFILE_FILE_ENV = "KALIV_CONSCIOUSNESS_PROFILE_FILE"
_DEFAULT_PROFILE_FILE = "./kaliv-consciousness-profile.json"
_MAX_PROFILE_FILE_BYTES = 32 * 1024
_DEFAULT_ENGINE_INSTANCE_ID = "thought-engine:ollama:v1"

NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]


class CognitiveProfileSourceError(RuntimeError):
    pass


class _DuplicateJsonKeyError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitiveProfileConfig(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognitive-profile-config/v1"]
    provider: Annotated[str, Field(min_length=1, max_length=128)]
    model: NonEmptyRef
    reasoning_depth: UnitInterval
    planning_capacity: UnitInterval
    context_capacity_tokens: Annotated[
        int,
        Field(ge=1, le=2_000_000, strict=True),
    ]
    multimodal_capacity: UnitInterval
    tool_reasoning: UnitInterval
    uncertainty_calibration: UnitInterval
    calibration_refs: Annotated[
        list[NonEmptyRef],
        Field(min_length=1, max_length=32),
    ]

    @model_validator(mode="after")
    def unique_calibration_refs(self) -> "CognitiveProfileConfig":
        if len(self.calibration_refs) != len(set(self.calibration_refs)):
            raise ValueError("calibration_refs must be unique")
        return self


class CognitiveProfileLoadReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognitive-profile-load-receipt/v1"]
    config_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    profile_ref: NonEmptyRef
    profile_id: Annotated[str, Field(pattern=r"^cog-[a-f0-9]{32}$")]
    engine_instance_id: NonEmptyRef
    calibration_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    config_bytes: Annotated[int, Field(ge=1, le=_MAX_PROFILE_FILE_BYTES, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


class CognitiveProfileLoadResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognitive-profile-load-result/v1"]
    profile: CognitiveProfile
    receipt: CognitiveProfileLoadReceipt
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError("duplicate JSON key")
        result[key] = value
    return result


def cognitive_profile_config_path(
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve config without creating the data root or any file."""
    if env is None:
        # Keep the default literal here so the generated activation-readiness
        # source scan can correctly classify this path as a setting, not a
        # production feature switch.
        raw = os.getenv(
            "KALIV_CONSCIOUSNESS_PROFILE_FILE",
            "./kaliv-consciousness-profile.json",
        )
        explicit = CONSCIOUSNESS_PROFILE_FILE_ENV in os.environ
    else:
        raw = env.get(CONSCIOUSNESS_PROFILE_FILE_ENV, _DEFAULT_PROFILE_FILE)
        explicit = CONSCIOUSNESS_PROFILE_FILE_ENV in env

    value = raw.strip()
    if not value:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile path is blank"
        )
    if explicit:
        return Path(value)
    return Path(_paths.peek_resolve(_DEFAULT_PROFILE_FILE))


def _read_profile_config(path: Path) -> tuple[CognitiveProfileConfig, bytes]:
    try:
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise CognitiveProfileSourceError(
                "Consciousness cognitive profile path is not a file"
            )
        raw = path.read_bytes()
    except FileNotFoundError:
        raise
    except CognitiveProfileSourceError:
        raise
    except OSError as exc:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile could not be read"
        ) from exc

    if not raw or len(raw) > _MAX_PROFILE_FILE_BYTES:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile file violates size bounds"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile must be UTF-8"
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (json.JSONDecodeError, _DuplicateJsonKeyError, ValueError, TypeError) as exc:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile is not strict JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile must be one JSON object"
        )
    try:
        config = CognitiveProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise CognitiveProfileSourceError(
            "Consciousness cognitive profile failed strict validation"
        ) from exc
    return config, raw


def _profile_id(
    config: CognitiveProfileConfig,
    engine_instance_id: str,
) -> str:
    digest = hashlib.sha256(
        _canonical_json(
            {
                "config": config.model_dump(mode="json"),
                "engine_instance_id": engine_instance_id,
            }
        )
    ).hexdigest()
    return "cog-" + digest[:32]


def build_cognitive_profile(
    config: CognitiveProfileConfig,
    *,
    engine_instance_id: str = _DEFAULT_ENGINE_INSTANCE_ID,
) -> CognitiveProfile:
    """Construct one authority-free ephemeral profile from validated config."""
    if not isinstance(config, CognitiveProfileConfig):
        raise TypeError("config must be CognitiveProfileConfig")
    if (
        not isinstance(engine_instance_id, str)
        or not engine_instance_id.strip()
        or len(engine_instance_id) > 256
    ):
        raise CognitiveProfileSourceError("invalid ThoughtEngine instance id")

    return CognitiveProfile(
        schema="kaliv-consciousness-core/cognitive-profile/v1",
        profile_id=_profile_id(config, engine_instance_id),
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


def load_cognitive_profile(
    *,
    path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    engine_instance_id: str = _DEFAULT_ENGINE_INSTANCE_ID,
) -> CognitiveProfileLoadResult | None:
    """Load current operator calibration; missing config means unavailable.

    The file is deliberately read on every call. Replacing the configured model
    or its calibrated capability values therefore affects the next explicit
    cognitive step without mutating SelfState, Person or Personality.
    """
    config_path = (
        Path(path)
        if path is not None
        else cognitive_profile_config_path(env)
    )
    try:
        config, raw = _read_profile_config(config_path)
    except FileNotFoundError:
        return None

    profile = build_cognitive_profile(
        config,
        engine_instance_id=engine_instance_id,
    )
    config_sha = hashlib.sha256(_canonical_json(config)).hexdigest()
    receipt = CognitiveProfileLoadReceipt(
        schema="kaliv-consciousness-core/cognitive-profile-load-receipt/v1",
        config_sha256=config_sha,
        profile_ref=cognitive_profile_ref(profile),
        profile_id=profile.profile_id,
        engine_instance_id=profile.engine_instance_id,
        calibration_refs=config.calibration_refs,
        config_bytes=len(raw),
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
    return CognitiveProfileLoadResult(
        schema="kaliv-consciousness-core/cognitive-profile-load-result/v1",
        profile=profile,
        receipt=receipt,
        production_activation=False,
    )
