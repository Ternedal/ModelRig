from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .. import backup
from .authority_pair import adopt_live_pair, read_binding_path


def adopt_current_pair(*, offline_confirmed: bool = False) -> Optional[str]:
    """Adopt pre-schema-5 Agent 3 authority under an explicit offline boundary.

    Normal startup never calls this. The migration operator stops the appliance
    first and then opts in explicitly. Before any persistent pair id is written,
    the existing run/progress stores must both be present, structurally valid
    and semantically coherent at the execution-watermark boundary. The complete
    structural + semantic check is repeated while ``adopt_live_pair`` holds
    write locks on both attached databases, so a successful transition cannot
    race a writer or bless schema drift in the pre-lock validation gap.

    A genuinely empty run-only store needs no adoption because it carries no
    execution authority yet. An already-bound valid pair is accepted
    idempotently. One-sided or mismatched binding is never repaired here.
    """
    if not offline_confirmed:
        raise RuntimeError(
            "Agent 3 pair adoption is an offline trust transition; stop the appliance "
            "and pass --offline-confirmed"
        )

    inventory = {item.key: item for item in backup.items()}
    runs = inventory[backup.AGENT3_RUNS_KEY]
    progress = inventory[backup.AGENT3_EXECUTION_PROGRESS_KEY]
    runs_exists = os.path.isfile(runs.path)
    progress_exists = os.path.isfile(progress.path)

    if not runs_exists and not progress_exists:
        return None
    if progress_exists and not runs_exists:
        raise RuntimeError(
            "cannot adopt Agent 3 progress authority without its run store"
        )
    if runs_exists and not progress_exists:
        run_count, run_problem = backup._agent3_runs_row_count_path(runs.path)
        if run_problem:
            raise RuntimeError("invalid Agent 3 run store: " + run_problem)
        if not run_count:
            return None
        raise RuntimeError(
            "cannot adopt non-empty Agent 3 run authority without execution-progress sidecar"
        )

    runs_binding, runs_binding_problem = read_binding_path(runs.path)
    progress_binding, progress_binding_problem = read_binding_path(progress.path)
    if runs_binding_problem or progress_binding_problem:
        raise RuntimeError(
            "invalid persistent Agent 3 pair binding: "
            + str(runs_binding_problem or progress_binding_problem)
        )
    if (runs_binding is None) != (progress_binding is None):
        raise RuntimeError(
            "Agent 3 persistent pair binding exists on only one authority store"
        )

    pair_id: Optional[str] = None
    if runs_binding is not None and progress_binding is not None:
        pair_id, pair_problem = backup._live_pair_id_problem(runs.path, progress.path)
        if pair_problem:
            raise RuntimeError("invalid Agent 3 live pair: " + pair_problem)
        assert pair_id is not None

    def authority_problem() -> tuple[Optional[int], Optional[str]]:
        run_count, run_problem = backup._agent3_runs_row_count_path(
            runs.path, pair_id=pair_id
        )
        progress_problem = backup._execution_progress_problem_path(
            progress.path, pair_id=pair_id
        )
        semantic_problem = None
        if not run_problem and not progress_problem:
            semantic_problem = backup._agent3_pair_semantic_problem_paths(
                runs.path, progress.path
            )
        return run_count, str(run_problem or progress_problem or semantic_problem) if (
            run_problem or progress_problem or semantic_problem
        ) else None

    run_count, problem = authority_problem()
    if problem:
        raise RuntimeError("refusing Agent 3 pair adoption: " + problem)
    if run_count is None:
        raise RuntimeError("could not inspect Agent 3 run authority")

    def locked_validator(_connection) -> Optional[str]:
        _run_count, locked_problem = authority_problem()
        return locked_problem

    return adopt_live_pair(runs.path, locked_validator)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kaliv-agent3-adopt-pair")
    parser.add_argument(
        "--offline-confirmed",
        action="store_true",
        help="confirm that ModelRig/Agent3 writers are stopped for this trust transition",
    )
    args = parser.parse_args(argv)
    try:
        pair_id = adopt_current_pair(offline_confirmed=args.offline_confirmed)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if pair_id is None:
        print("no materialized Agent 3 authority pair requires adoption")
    else:
        print(f"Agent 3 authority pair adopted/validated: {pair_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
