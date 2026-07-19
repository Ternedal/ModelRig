from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/t030-network-registry"
EXPECTED_BLOBS = {
    "worker/app/tools.py": "0235b0687c3b69c619b4f4975439da1d84d2a61c",
    "worker/app/capability_schema.py": "082c29057fdbaf1d19913b6c3cf242d9e2b52270",
    "backend/internal/capabilityschema/schema.go": "189945b0d0803754c5afbbb0335fd26d1aaf6da4",
    "backend/internal/capabilityschema/schema_test.go": "0d398b463ffd0a298e2b5bc3fcf554bdb494d7f3",
    "contracts/kaliv-capability-v2.schema.json": "41a6b77a7749ccd8ea96c6dbf6eebd56dc6a50d8",
    "contracts/kaliv-capability-v2-fixtures.json": "fa7d27636d54576d0b675b563fd3771fa1d70d7c",
    "tests/worker_capability_schema_v2.py": "0a5ab57aae774f3be719d8fefa36d4cd50b16f53",
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
                f"refusing T-030 patch: {relative} blob {actual} != {expected}"
            )
    if not (ROOT / "tests/worker_000_t030_source_bundle.py").exists():
        raise SystemExit("refusing T-030 patch: source-bundle sentinel is missing")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_tools() -> None:
    path = ROOT / "worker/app/tools.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'Cancellation = Literal["none", "cooperative", "forceable"]\n\n'
        "# WHAT A TOOL'S RESULT IS",
        '''Cancellation = Literal["none", "cooperative", "forceable"]

# Which network boundary execution crosses. This is metadata, never a router.
#
#   "none"               - execution performs no network I/O.
#   "loopback"           - a fixed loopback-only service/socket.
#   "configured_service" - a named service whose URL/topology comes from trusted
#                          operator configuration (for example Ollama). The
#                          descriptor names the service, never its URL or token.
#   "public"             - a deliberately public network destination.
#   "undeclared"         - legacy/unknown. Accepted by the v2 parser so old
#                          descriptors fail honestly, but forbidden for every
#                          tool in the production REGISTRY by contract tests.
NetworkMode = Literal[
    "none", "loopback", "configured_service", "public", "undeclared"
]

# WHAT A TOOL'S RESULT IS''',
        "network type",
    )

    text = replace_once(
        text,
        '''    env_allow: tuple = ()
    # May this action ever run with nobody watching? (F-604)''',
        '''    env_allow: tuple = ()
    # Network metadata belongs beside the executable tool definition. It does
    # not grant network access and is not consulted by the executor in this
    # slice; it makes the existing requirement visible to schema/API consumers.
    # Default undeclared preserves compatibility for ad-hoc test tools, while
    # the production REGISTRY contract rejects undeclared entries.
    network: NetworkMode = "undeclared"
    network_destinations: tuple[str, ...] = ()
    # May this action ever run with nobody watching? (F-604)''',
        "Tool network fields",
    )

    text = replace_once(
        text,
        '''        if self.idempotent is None:
            object.__setattr__(self, "idempotent", self.impact == "read")
        # A destructive or administrative action cannot be scheduled. This is''',
        '''        if self.idempotent is None:
            object.__setattr__(self, "idempotent", self.impact == "read")

        allowed_network = {
            "none", "loopback", "configured_service", "public", "undeclared"
        }
        if self.network not in allowed_network:
            raise ValueError(
                f"{self.name}: unsupported network mode {self.network!r}"
            )
        if not isinstance(self.network_destinations, tuple):
            raise ValueError(
                f"{self.name}: network_destinations must be a tuple"
            )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in self.network_destinations
        ):
            raise ValueError(
                f"{self.name}: network destinations must be non-empty strings"
            )
        if len(self.network_destinations) != len(set(self.network_destinations)):
            raise ValueError(
                f"{self.name}: network destinations contain duplicates"
            )
        if self.network in ("none", "undeclared") and self.network_destinations:
            raise ValueError(
                f"{self.name}: {self.network} network mode cannot name destinations"
            )
        if (
            self.network in ("loopback", "configured_service", "public")
            and not self.network_destinations
        ):
            raise ValueError(
                f"{self.name}: {self.network} network mode requires a destination"
            )

        # A destructive or administrative action cannot be scheduled. This is''',
        "Tool network validation",
    )

    replacements = (
        (
            '''        schedulable=True, risk="read",
        sensitivity="operational",  # GPU, VRAM, uptime -- a description of your machine''',
            '''        schedulable=True, risk="read",
        network="none",
        sensitivity="operational",  # GPU, VRAM, uptime -- a description of your machine''',
            "rig_status network",
        ),
        (
            '''        schedulable=True, risk="write",
        sensitivity="private",  # your own text, written back to you''',
            '''        schedulable=True, risk="write",
        network="none",
        sensitivity="private",  # your own text, written back to you''',
            "note_append network",
        ),
        (
            '''        schedulable=True, risk="read",
        sensitivity="operational",  # which models you run says something about you, but not much''',
            '''        schedulable=True, risk="read",
        network="configured_service",
        network_destinations=("ollama",),
        sensitivity="operational",  # which models you run says something about you, but not much''',
            "list_models network",
        ),
        (
            '''        schedulable=True, risk="read",
        sensitivity="public",  # the clock is not yours; it is everyone's''',
            '''        schedulable=True, risk="read",
        network="none",
        sensitivity="public",  # the clock is not yours; it is everyone's''',
            "current_datetime network",
        ),
        (
            '''        schedulable=True, risk="read",
        sensitivity="operational",  # job state and progress''',
            '''        schedulable=True, risk="read",
        network="none",
        sensitivity="operational",  # job state and progress''',
            "job_status network",
        ),
        (
            '''        unschedulable_because="et job-id er flygtigt; en plan om at annullere det rammer noget andet i morgen", risk="write",
        sensitivity="operational",  # acts on the rig, returns rig state''',
            '''        unschedulable_because="et job-id er flygtigt; en plan om at annullere det rammer noget andet i morgen", risk="write",
        network="none",
        sensitivity="operational",  # acts on the rig, returns rig state''',
            "cancel_job network",
        ),
        (
            '''        schedulable=True, risk="read",
        sensitivity="private",  # YOUR document names -- the F-208 case in one line''',
            '''        schedulable=True, risk="read",
        network="none",
        sensitivity="private",  # YOUR document names -- the F-208 case in one line''',
            "list_documents network",
        ),
        (
            '''        unschedulable_because="sletning af en model er uigenkaldelig og kan ikke fortrydes kl. 03:00", risk="write",
        sensitivity="operational",  # acts on the rig, returns rig state''',
            '''        unschedulable_because="sletning af en model er uigenkaldelig og kan ikke fortrydes kl. 03:00", risk="write",
        network="configured_service",
        network_destinations=("ollama",),
        sensitivity="operational",  # acts on the rig, returns rig state''',
            "delete_model network",
        ),
        (
            '''        unschedulable_because="modelhentning er en administrativ handling der bruger båndbredde og disk uden opsyn", risk="write",
        sensitivity="operational",  # acts on the rig, returns rig state''',
            '''        unschedulable_because="modelhentning er en administrativ handling der bruger båndbredde og disk uden opsyn", risk="write",
        network="configured_service",
        network_destinations=("ollama",),
        sensitivity="operational",  # acts on the rig, returns rig state''',
            "pull_model network",
        ),
    )
    for old, new, label in replacements:
        text = replace_once(text, old, new, label)

    text = replace_once(
        text,
        '''             "cancellation": t.cancellation,
             "idempotent": t.idempotent}''',
        '''             "cancellation": t.cancellation,
             "network": t.network,
             "network_destinations": list(t.network_destinations),
             "idempotent": t.idempotent}''',
        "tools API network metadata",
    )
    path.write_text(text, encoding="utf-8")


def patch_python_schema() -> None:
    path = ROOT / "worker/app/capability_schema.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'mode: Literal["none", "loopback", "public", "undeclared"]',
        'mode: Literal["none", "loopback", "configured_service", "public", "undeclared"]',
        "Python network enum",
    )
    text = replace_once(
        text,
        '"network destinations require loopback or public mode"',
        '"network destinations require loopback, configured_service or public mode"',
        "Python destination error",
    )
    text = replace_once(
        text,
        '''        if self.mode in {"loopback", "public"} and not self.destinations:
            raise ValueError(
                "loopback or public network mode requires a destination"
            )''',
        '''        if self.mode in {"loopback", "configured_service", "public"} and not self.destinations:
            raise ValueError("networked mode requires a destination")''',
        "Python network destination requirement",
    )
    path.write_text(text, encoding="utf-8")


def patch_go_schema() -> None:
    path = ROOT / "backend/internal/capabilityschema/schema.go"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'networkModes      = set("none", "loopback", "public", "undeclared")',
        'networkModes      = set("none", "loopback", "configured_service", "public", "undeclared")',
        "Go network enum",
    )
    text = replace_once(
        text,
        'return errors.New("network destinations require loopback or public mode")',
        'return errors.New("network destinations require loopback, configured_service or public mode")',
        "Go destination error",
    )
    text = replace_once(
        text,
        '''if (d.Network.Mode == "loopback" || d.Network.Mode == "public") && len(d.Network.Destinations) == 0 {
		return errors.New("loopback or public network mode requires a destination")
	}''',
        '''if (d.Network.Mode == "loopback" || d.Network.Mode == "configured_service" || d.Network.Mode == "public") && len(d.Network.Destinations) == 0 {
		return errors.New("networked mode requires a destination")
	}''',
        "Go network destination requirement",
    )
    path.write_text(text, encoding="utf-8")


def patch_json_contracts() -> None:
    schema_path = ROOT / "contracts/kaliv-capability-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    modes = schema["properties"]["network"]["properties"]["mode"]["enum"]
    if modes != ["none", "loopback", "public", "undeclared"]:
        raise SystemExit(f"unexpected JSON network enum: {modes!r}")
    schema["properties"]["network"]["properties"]["mode"]["enum"] = [
        "none", "loopback", "configured_service", "public", "undeclared"
    ]
    changed = False
    for rule in schema["allOf"]:
        try:
            enum = rule["if"]["properties"]["network"]["properties"]["mode"]["enum"]
        except KeyError:
            continue
        if enum == ["loopback", "public"]:
            rule["if"]["properties"]["network"]["properties"]["mode"]["enum"] = [
                "loopback", "configured_service", "public"
            ]
            changed = True
    if not changed:
        raise SystemExit("JSON configured-service conditional anchor is missing")
    schema_path.write_text(
        json.dumps(schema, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    fixtures_path = ROOT / "contracts/kaliv-capability-v2-fixtures.json"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    for fixture in fixtures["valid"]:
        name = fixture["name"]
        descriptor = fixture["descriptor"]
        if name == "note_append":
            descriptor["network"] = {"mode": "none", "destinations": []}
        elif name == "list_models":
            descriptor["network"] = {
                "mode": "configured_service",
                "destinations": ["ollama"],
            }
        else:
            raise SystemExit(f"unexpected valid fixture {name!r}")
        fixture["canonical"] = json.dumps(
            descriptor,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    for fixture in fixtures["invalid"]:
        if fixture["name"] == "network_mode_without_destination":
            fixture["descriptor"]["network"] = {
                "mode": "configured_service",
                "destinations": [],
            }
    if not any(x["name"] == "unknown_network_mode" for x in fixtures["invalid"]):
        descriptor = copy.deepcopy(fixtures["valid"][0]["descriptor"])
        descriptor["network"] = {
            "mode": "vpn_magic",
            "destinations": ["ollama"],
        }
        fixtures["invalid"].append(
            {"name": "unknown_network_mode", "descriptor": descriptor}
        )
    fixtures_path.write_text(
        json.dumps(fixtures, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def patch_tests() -> None:
    path = ROOT / "tests/worker_capability_schema_v2.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        assert descriptor.network_mode == "undeclared"\n',
        '        assert descriptor.network_mode == tool.network\n'
        '        assert tuple(descriptor.network.destinations) == tool.network_destinations\n',
        "Python registry descriptor parity",
    )
    anchor = '''        assert descriptor.canonical_json() == json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def test_schema_document_matches_runtime_contract() -> None:
'''
    replacement = '''        assert descriptor.canonical_json() == json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def test_registry_owns_network_metadata_and_api_preserves_it() -> None:
    expected = {
        "rig_status": ("none", ()),
        "note_append": ("none", ()),
        "list_models": ("configured_service", ("ollama",)),
        "current_datetime": ("none", ()),
        "job_status": ("none", ()),
        "cancel_job": ("none", ()),
        "list_documents": ("none", ()),
        "delete_model": ("configured_service", ("ollama",)),
        "pull_model": ("configured_service", ("ollama",)),
    }
    actual = {
        name: (tool.network, tool.network_destinations)
        for name, tool in tools.REGISTRY.items()
    }
    assert actual == expected
    assert all(mode != "undeclared" for mode, _ in actual.values())

    listed = {item["name"]: item for item in tools.GATE.list_tools()}
    for name, (mode, destinations) in expected.items():
        assert listed[name]["network"] == mode
        assert listed[name]["network_destinations"] == list(destinations)


def test_tool_network_metadata_fails_closed() -> None:
    def make(**overrides):
        values = {
            "name": "network_contract_test",
            "risk": "read",
            "description": "network metadata contract test",
            "network": "none",
        }
        values.update(overrides)
        return tools.Tool(**values)

    make(network="none")
    make(network="configured_service", network_destinations=("ollama",))

    invalid = (
        {"network": "none", "network_destinations": ("ollama",)},
        {"network": "configured_service", "network_destinations": ()},
        {"network": "vpn_magic"},
        {"network": "public", "network_destinations": ("",)},
        {"network": "loopback", "network_destinations": ("svc", "svc")},
        {"network": "public", "network_destinations": ["example.com"]},
    )
    for values in invalid:
        try:
            make(**values)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"invalid Tool network metadata accepted: {values!r}"
            )


def test_schema_document_matches_runtime_contract() -> None:
'''
    text = replace_once(text, anchor, replacement, "Python network tests")
    text = replace_once(
        text,
        '''    assert (
        JSON_SCHEMA["properties"]["production_activation"]["const"]
        is False
    )
''',
        '''    assert (
        JSON_SCHEMA["properties"]["production_activation"]["const"]
        is False
    )
    assert (
        "configured_service"
        in JSON_SCHEMA["properties"]["network"]["properties"]["mode"]["enum"]
    )
''',
        "Python schema enum assertion",
    )
    path.write_text(text, encoding="utf-8")

    go_test = ROOT / "backend/internal/capabilityschema/schema_test.go"
    text = go_test.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "func TestCanonicalJSONDoesNotHTMLEscape(t *testing.T) {\n",
        '''func TestConfiguredServiceNetworkMode(t *testing.T) {
	fixtures := loadFixtures(t)
	for _, fixture := range fixtures.Valid {
		descriptor, err := Parse(fixture.Descriptor)
		if err != nil {
			t.Fatal(err)
		}
		if descriptor.CapabilityID != "tool:list_models" {
			continue
		}
		if descriptor.Network.Mode != "configured_service" {
			t.Fatalf("list_models network mode = %q", descriptor.Network.Mode)
		}
		if len(descriptor.Network.Destinations) != 1 ||
			descriptor.Network.Destinations[0] != "ollama" {
			t.Fatalf("list_models destinations = %#v", descriptor.Network.Destinations)
		}
		return
	}
	t.Fatal("list_models configured-service fixture is missing")
}

func TestCanonicalJSONDoesNotHTMLEscape(t *testing.T) {
''',
        "Go configured-service fixture test",
    )
    go_test.write_text(text, encoding="utf-8")


def restore_workflow_and_remove_helpers() -> None:
    workflow = ROOT / ".github/workflows/agent3-full-diagnostics.yml"
    text = workflow.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "permissions:\n  contents: write\n",
        "permissions:\n  contents: read\n",
        "workflow permission restore",
    )
    pattern = re.compile(
        r"\n      # T030_SELF_PATCH_BEGIN\n.*?\n      # T030_SELF_PATCH_END\n",
        re.DOTALL,
    )
    text, count = pattern.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit(f"workflow patch block restore count = {count}")
    workflow.write_text(text, encoding="utf-8")
    (ROOT / "tests/worker_000_t030_source_bundle.py").unlink()
    Path(__file__).unlink()


def validate() -> None:
    subprocess.run(
        [
            "gofmt", "-w",
            str(ROOT / "backend/internal/capabilityschema/schema.go"),
            str(ROOT / "backend/internal/capabilityschema/schema_test.go"),
        ],
        check=True,
    )
    for relative in (
        "worker/app/tools.py",
        "worker/app/capability_schema.py",
        "tests/worker_capability_schema_v2.py",
    ):
        compile((ROOT / relative).read_text(encoding="utf-8"), relative, "exec")

    module_path = ROOT / "worker/app/capability_schema.py"
    spec = importlib.util.spec_from_file_location("t030_capability_schema", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load Python capability schema")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fixtures = json.loads(
        (ROOT / "contracts/kaliv-capability-v2-fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    for fixture in fixtures["valid"]:
        descriptor = module.parse_descriptor(fixture["descriptor"])
        if descriptor.canonical_json() != fixture["canonical"]:
            raise SystemExit(f"canonical mismatch: {fixture['name']}")
    for fixture in fixtures["invalid"]:
        try:
            module.parse_descriptor(fixture["descriptor"])
        except module.CapabilitySchemaError:
            pass
        else:
            raise SystemExit(f"invalid fixture accepted: {fixture['name']}")

    subprocess.run(
        ["go", "test", "./internal/capabilityschema"],
        cwd=ROOT / "backend",
        check=True,
    )


def main() -> None:
    if os.environ.get("GITHUB_HEAD_REF") not in (None, "", BRANCH):
        raise SystemExit("refusing T-030 patch outside the exact branch")
    require_base()
    patch_tools()
    patch_python_schema()
    patch_go_schema()
    patch_json_contracts()
    patch_tests()
    validate()
    restore_workflow_and_remove_helpers()
    print("T-030 network-registry patch applied and self-cleaned")


if __name__ == "__main__":
    main()
