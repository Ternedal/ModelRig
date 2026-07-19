from __future__ import annotations

import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = "kaliv-capability/v2"


class CapabilitySchemaError(ValueError):
    """The descriptor is malformed or contradicts its own safety metadata."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class Isolation(StrictModel):
    mode: Literal["in_process", "process"]
    env_allow: list[str]

    @model_validator(mode="after")
    def validate_env(self) -> "Isolation":
        if any(not value.strip() for value in self.env_allow):
            raise ValueError("isolation.env_allow contains an empty value")
        if len(self.env_allow) != len(set(self.env_allow)):
            raise ValueError("isolation.env_allow contains duplicates")
        return self


class Scheduling(StrictModel):
    allowed: bool
    reason: str

    @model_validator(mode="after")
    def validate_reason(self) -> "Scheduling":
        if self.allowed and self.reason:
            raise ValueError(
                "schedulable capability must not carry a refusal reason"
            )
        if not self.allowed and not self.reason.strip():
            raise ValueError("unschedulable capability requires a reason")
        return self


class Confirmation(StrictModel):
    mode: Literal["none", "required"]


class Network(StrictModel):
    mode: Literal["none", "loopback", "configured_service", "public", "undeclared"]
    destinations: list[str]

    @model_validator(mode="after")
    def validate_destinations(self) -> "Network":
        if any(not value.strip() for value in self.destinations):
            raise ValueError("network.destinations contains an empty value")
        if len(self.destinations) != len(set(self.destinations)):
            raise ValueError("network.destinations contains duplicates")
        if self.mode in {"none", "undeclared"} and self.destinations:
            raise ValueError(
                "network destinations require loopback, configured_service or public mode"
            )
        if self.mode in {"loopback", "configured_service", "public"} and not self.destinations:
            raise ValueError("networked mode requires a destination")
        return self


class Termination(StrictModel):
    mode: Literal["none", "cooperative", "forceable"]


class Replay(StrictModel):
    idempotent: bool


class CapabilityDescriptorV2(StrictModel):
    schema_id: Literal["kaliv-capability/v2"] = Field(alias="schema")
    capability_id: str = Field(pattern=r"^tool:[A-Za-z0-9._:-]{1,155}$")
    kind: Literal["tool"]
    description: str = Field(min_length=1)
    access: Literal["read", "write", "desktop"]
    impact: Literal["read", "write", "desktop", "destructive", "admin"]
    data_class: Literal["public", "operational", "private", "secret"]
    parameters: dict[str, Any]
    isolation: Isolation
    scheduling: Scheduling
    confirmation: Confirmation
    network: Network
    termination: Termination
    replay: Replay
    production_activation: Literal[False]

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "CapabilityDescriptorV2":
        if not self.description.strip():
            raise ValueError("description must contain visible text")
        expected = "required" if self.access in {"write", "desktop"} else "none"
        if self.confirmation.mode != expected:
            raise ValueError("confirmation mode contradicts access")
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def termination_mode(self) -> str:
        return self.termination.mode

    @property
    def network_mode(self) -> str:
        return self.network.mode

    @property
    def idempotent(self) -> bool:
        return self.replay.idempotent


def parse_descriptor(payload: Mapping[str, Any]) -> CapabilityDescriptorV2:
    try:
        return CapabilityDescriptorV2.model_validate(dict(payload))
    except (TypeError, ValueError) as exc:
        raise CapabilitySchemaError(str(exc)) from exc


def descriptor_from_tool(tool: object) -> CapabilityDescriptorV2:
    name = getattr(tool, "name", None)
    if not isinstance(name, str) or not name:
        raise CapabilitySchemaError("tool.name must be a non-empty string")

    schedulable = getattr(tool, "schedulable", None)
    isolate = getattr(tool, "isolate", None)
    if not isinstance(schedulable, bool) or not isinstance(isolate, bool):
        raise CapabilitySchemaError(f"{name}: boolean metadata is invalid")

    reason = getattr(tool, "unschedulable_because", "")
    env_allow = getattr(tool, "env_allow", ())
    destinations = getattr(tool, "network_destinations", ())
    if not isinstance(reason, str) or not isinstance(env_allow, tuple):
        raise CapabilitySchemaError(
            f"{name}: scheduling or isolation metadata is invalid"
        )
    if not isinstance(destinations, tuple):
        raise CapabilitySchemaError(
            f"{name}.network_destinations must be a tuple"
        )

    try:
        risk = getattr(tool, "risk")
        return CapabilityDescriptorV2(
            schema=SCHEMA,
            capability_id=f"tool:{name}",
            kind="tool",
            description=getattr(tool, "description"),
            access=risk,
            impact=getattr(tool, "impact"),
            data_class=getattr(tool, "sensitivity"),
            parameters=getattr(tool, "params"),
            isolation=Isolation(
                mode="process" if isolate else "in_process",
                env_allow=list(env_allow),
            ),
            scheduling=Scheduling(
                allowed=schedulable,
                reason="" if schedulable else (
                    reason or "not declared schedulable"
                ),
            ),
            confirmation=Confirmation(
                mode="required" if risk in {"write", "desktop"} else "none"
            ),
            network=Network(
                mode=getattr(tool, "network", "undeclared"),
                destinations=list(destinations),
            ),
            termination=Termination(mode=getattr(tool, "cancellation")),
            replay=Replay(idempotent=getattr(tool, "idempotent")),
            production_activation=False,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise CapabilitySchemaError(f"{name}: {exc}") from exc


def descriptors_from_registry(
    registry: Mapping[str, object],
) -> tuple[CapabilityDescriptorV2, ...]:
    descriptors: list[CapabilityDescriptorV2] = []
    for name, tool in sorted(registry.items()):
        descriptor = descriptor_from_tool(tool)
        if descriptor.capability_id != f"tool:{name}":
            raise CapabilitySchemaError(
                f"registry key {name!r} does not match "
                f"{descriptor.capability_id!r}"
            )
        descriptors.append(descriptor)

    ids = [item.capability_id for item in descriptors]
    if len(ids) != len(set(ids)):
        raise CapabilitySchemaError("registry produced duplicate capability ids")
    return tuple(descriptors)
