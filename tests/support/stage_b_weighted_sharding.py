"""Deterministic weighted partitioning for Stage-B contract shards.

The Stage-B workflow needs reviewable, stable shard membership while allowing
measured contract costs to replace naive round-robin assignment.  This module is
pure orchestration: it never executes a contract and never weakens a contract's
own timeout or authority semantics.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def weighted_shards(
    contract_files: Sequence[str],
    cost_seconds: Mapping[str, float],
    shard_count: int,
) -> tuple[tuple[str, ...], ...]:
    """Partition contracts by deterministic longest-processing-time scheduling.

    Every contract must have exactly one positive finite checked-in cost and the
    cost table must not contain stale/unknown entries.  Contracts are assigned in
    descending cost order to the currently lightest shard; canonical contract
    order breaks equal-cost ties and is restored inside each resulting shard.
    """

    files = tuple(contract_files)
    if not files:
        raise AssertionError("Stage-B weighted sharding requires contracts")
    if len(set(files)) != len(files):
        raise AssertionError("Stage-B weighted sharding rejects duplicate contracts")
    if not isinstance(shard_count, int) or isinstance(shard_count, bool):
        raise AssertionError("Stage-B shard count must be an integer")
    if not 1 <= shard_count <= len(files):
        raise AssertionError(
            "Stage-B shard count must be between 1 and the contract count"
        )

    file_set = set(files)
    cost_set = set(cost_seconds)
    missing = sorted(file_set - cost_set)
    extra = sorted(cost_set - file_set)
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise AssertionError(
            "Stage-B weighted cost table must exactly match contracts: "
            + "; ".join(details)
        )

    normalized_costs: dict[str, float] = {}
    for filename in files:
        raw = cost_seconds[filename]
        if isinstance(raw, bool):
            raise AssertionError(
                f"invalid Stage-B cost for {filename}: boolean values are not costs"
            )
        try:
            cost = float(raw)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"invalid Stage-B cost for {filename}: {raw!r}"
            ) from exc
        if not math.isfinite(cost) or cost <= 0:
            raise AssertionError(
                f"invalid Stage-B cost for {filename}: expected positive finite seconds"
            )
        normalized_costs[filename] = cost

    canonical_index = {filename: index for index, filename in enumerate(files)}
    ordered = sorted(
        files,
        key=lambda filename: (
            -normalized_costs[filename],
            canonical_index[filename],
        ),
    )

    shard_members: list[list[str]] = [[] for _ in range(shard_count)]
    shard_loads = [0.0 for _ in range(shard_count)]
    for filename in ordered:
        shard_index = min(
            range(shard_count),
            key=lambda index: (shard_loads[index], index),
        )
        shard_members[shard_index].append(filename)
        shard_loads[shard_index] += normalized_costs[filename]

    for shard in shard_members:
        shard.sort(key=canonical_index.__getitem__)

    flattened = [filename for shard in shard_members for filename in shard]
    if len(flattened) != len(files) or set(flattened) != file_set:
        raise AssertionError(
            "Stage-B weighted sharding must assign every contract exactly once"
        )
    if any(not shard for shard in shard_members):
        raise AssertionError("Stage-B weighted sharding produced an empty shard")

    return tuple(tuple(shard) for shard in shard_members)
