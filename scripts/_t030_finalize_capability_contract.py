from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/t030-api-doc-client-fixtures"
EXPECTED_BLOBS = {
    "worker/app/tools.py": "bf3c97f14878daa4ceb24c6fca84969e1e999acc",
    "scripts/current_state.py": "c739671e9fdf5bb8bb0d96ca685b943da65240da",
    "tests/worker_capability_schema_v2.py": "74141b5e2c564a415c5af9ec91f65cd306a042fb",
}


def git_blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def require_base() -> None:
    for relative, expected in EXPECTED_BLOBS.items():
        raw = (ROOT / relative).read_bytes()
        actual = git_blob_sha(raw)
        if actual != expected:
            raise SystemExit(
                f"refusing final T-030 patch: {relative} blob {actual} != {expected}"
            )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_tools_api() -> None:
    path = ROOT / "worker/app/tools.py"
    text = path.read_text(encoding="utf-8")
    old = '''        return [
            {"name": t.name, "risk": t.risk, "description": t.description,
             "params": t.params, "enabled": self.is_enabled(t.name),
             "impact": t.impact,
             "schedulable": t.schedulable,
             # Why a client should not offer this on a schedule, in words, so the
             # picker can show the reason rather than a bare refusal after the tap.
             "unschedulable_reason": (
                 "" if t.schedulable else t.unschedulable_because),
             "cancellation": t.cancellation,
             "network": t.network,
             "network_destinations": list(t.network_destinations),
             "idempotent": t.idempotent}
            for t in REGISTRY.values()
        ]
'''
    new = '''        from .capability_schema import descriptor_from_tool

        result: list[dict] = []
        for tool in REGISTRY.values():
            descriptor = descriptor_from_tool(tool)
            name = descriptor.capability_id.removeprefix("tool:")
            # Preserve every legacy field and value for existing clients. The
            # nested descriptor is additive and is the one versioned static
            # representation new API/client code validates.
            result.append(
                {
                    "name": name,
                    "risk": descriptor.access,
                    "description": descriptor.description,
                    "params": descriptor.parameters,
                    "enabled": self.is_enabled(name),
                    "impact": descriptor.impact,
                    "schedulable": descriptor.scheduling.allowed,
                    "unschedulable_reason": descriptor.scheduling.reason,
                    "cancellation": descriptor.termination.mode,
                    "network": descriptor.network.mode,
                    "network_destinations": list(descriptor.network.destinations),
                    "idempotent": descriptor.replay.idempotent,
                    "descriptor": descriptor.to_dict(),
                }
            )
        return result
'''
    text = replace_once(text, old, new, "ToolGate.list_tools descriptor projection")
    path.write_text(text, encoding="utf-8")


def patch_current_state() -> None:
    path = ROOT / "scripts/current_state.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'def _tools() -> list[tuple[str, str, str]]:\n',
        'def _tools() -> list[tuple[str, list[str]]]:\n',
        "current-state tools annotation",
    )
    old_code = '''    code = (
        "from app.tools import REGISTRY\\n"
        "_AXES = ('risk','sensitivity','isolate','impact','schedulable',"
        "'cancellation','idempotent')\\n"
        "def _cell(v):\\n"
        "    if isinstance(v, bool): return '1' if v else '0'\\n"
        "    return str(getattr(v, 'value', v))\\n"
        "for n, t in sorted(REGISTRY.items()):\\n"
        "    print(n + '|' + '|'.join(_cell(getattr(t, a)) for a in _AXES))\\n"
    )
'''
    new_code = '''    code = (
        "from app.capability_schema import descriptors_from_registry\\n"
        "from app.tools import REGISTRY\\n"
        "def _cell(v):\\n"
        "    if isinstance(v, bool): return '1' if v else '0'\\n"
        "    return str(getattr(v, 'value', v))\\n"
        "for d in descriptors_from_registry(REGISTRY):\\n"
        "    values = (d.schema_id, d.access, d.impact, d.data_class, "
        "d.isolation.mode == 'process', d.scheduling.allowed, d.network.mode, "
        "d.termination.mode, d.replay.idempotent)\\n"
        "    print(d.capability_id + '|' + '|'.join(_cell(v) for v in values))\\n"
    )
'''
    text = replace_once(text, old_code, new_code, "current-state descriptor subprocess")
    old_intro = '''    L.append("## Tools the model can see")
    L.append("")
    L.append("Every column is a registry-owned axis (F-718). `risk` gates what a tool")
    L.append("may DO and `impact` how bad it is if it goes wrong; `sensitivity` gates")
    L.append("where its ANSWER may travel; `sched` is whether it may run unattended;")
    L.append("`stop` is what cancellation does; `replay` is whether running it twice is")
    L.append("safe. Read out of the code, so the page cannot claim one thing while the")
    L.append("gate enforces another.")
    L.append("")
    # Same axis order as the subprocess. One list, two ends (F-715): the header
    # and the emitter must not drift, so they share the order by construction.
    L.append("| Tool | risk | impact | sensitivity | isolated | sched | stop | replay |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, axes in _tools():
        risk, sens, iso, impact, sched, stop, replay = axes
        L.append(
            f"| `{name}` | {risk} | {impact} | {sens} | "
            f"{'yes' if iso == '1' else 'no'} | "
            f"{'yes' if sched == '1' else 'no'} | {stop} | "
            f"{'yes' if replay == '1' else 'no'} |"
        )
'''
    new_intro = '''    L.append("## Tools the model can see")
    L.append("")
    L.append("Every row is generated from the strict `kaliv-capability/v2` descriptor,")
    L.append("not from a parallel documentation projection. `access` gates what a tool")
    L.append("may do; `impact` describes the consequence; `data class` governs where")
    L.append("results may travel; scheduling, network, termination and replay semantics")
    L.append("are the same versioned values validated by worker, backend and clients.")
    L.append("")
    L.append("| Capability | schema | access | impact | data class | isolated | sched | network | stop | replay |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for capability_id, axes in _tools():
        schema, access, impact, data_class, iso, sched, network, stop, replay = axes
        L.append(
            f"| `{capability_id}` | `{schema}` | {access} | {impact} | {data_class} | "
            f"{'yes' if iso == '1' else 'no'} | "
            f"{'yes' if sched == '1' else 'no'} | {network} | {stop} | "
            f"{'yes' if replay == '1' else 'no'} |"
        )
'''
    text = replace_once(text, old_intro, new_intro, "current-state descriptor table")
    path.write_text(text, encoding="utf-8")


def patch_worker_contract_test() -> None:
    path = ROOT / "tests/worker_capability_schema_v2.py"
    text = path.read_text(encoding="utf-8")
    old = '''    listed = {item["name"]: item for item in tools.GATE.list_tools()}
    for name, (mode, destinations) in expected.items():
        assert listed[name]["network"] == mode
        assert listed[name]["network_destinations"] == list(destinations)
'''
    new = '''    descriptors = {
        item.capability_id.removeprefix("tool:"): item
        for item in descriptors_from_registry(tools.REGISTRY)
    }
    listed = {item["name"]: item for item in tools.GATE.list_tools()}
    expected_legacy_keys = {
        "name", "risk", "description", "params", "enabled", "impact",
        "schedulable", "unschedulable_reason", "cancellation", "network",
        "network_destinations", "idempotent", "descriptor",
    }
    for name, (mode, destinations) in expected.items():
        item = listed[name]
        descriptor = descriptors[name]
        assert set(item) == expected_legacy_keys
        assert parse_descriptor(item["descriptor"]) == descriptor
        assert "enabled" not in item["descriptor"]
        assert item["risk"] == descriptor.access
        assert item["description"] == descriptor.description
        assert item["params"] == descriptor.parameters
        assert item["impact"] == descriptor.impact
        assert item["schedulable"] is descriptor.scheduling.allowed
        assert item["unschedulable_reason"] == descriptor.scheduling.reason
        assert item["cancellation"] == descriptor.termination.mode
        assert item["network"] == mode == descriptor.network.mode
        assert item["network_destinations"] == list(destinations)
        assert item["idempotent"] is descriptor.replay.idempotent
'''
    text = replace_once(text, old, new, "worker API descriptor parity test")
    path.write_text(text, encoding="utf-8")


def restore_workflow_and_remove_self() -> None:
    workflow = ROOT / ".github/workflows/agent3-full-diagnostics.yml"
    text = workflow.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "permissions:\n  contents: write\n",
        "permissions:\n  contents: read\n",
        "workflow permission restore",
    )
    pattern = re.compile(
        r"\n      # T030_FINAL_PATCH_BEGIN\n.*?\n      # T030_FINAL_PATCH_END\n",
        re.DOTALL,
    )
    text, count = pattern.subn("", text, count=1)
    if count != 1:
        raise SystemExit(f"workflow final patch restore count = {count}")
    workflow.write_text(text, encoding="utf-8")
    Path(__file__).unlink()


def validate_and_generate() -> None:
    subprocess.run(
        [os.sys.executable, "tests/worker_capability_schema_v2.py"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "worker")},
        check=True,
    )
    subprocess.run(
        [os.sys.executable, "scripts/current_state.py"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    if os.environ.get("GITHUB_HEAD_REF") not in (None, "", BRANCH):
        raise SystemExit("refusing final T-030 patch outside the exact branch")
    require_base()
    patch_tools_api()
    patch_current_state()
    patch_worker_contract_test()
    validate_and_generate()
    print("final T-030 API/doc patch applied; connector cleanup pending")


if __name__ == "__main__":
    main()
