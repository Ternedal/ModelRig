#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "browser_peer_public_validation_operator.py"
LAUNCHER = ROOT / "scripts" / "run-browser-peer-public-validation.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("browser_peer_operator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_result() -> dict:
    digest = "a" * 64
    git_sha = "b" * 40
    return {
        "schema": "kaliv-browser-peer-public-validation/v1",
        "generated_at": "2026-07-20T18:15:46Z",
        "passed": True,
        "candidate": {
            "version": "1.58.125",
            "git_sha": git_sha,
            "code_sha256": "c" * 64,
            "branch": "agent/test",
            "working_tree_clean": True,
            "dirty_entries": 0,
            "version_stamps_consistent": True,
            "version_check_detail": None,
        },
        "target": {"host": "example.com", "port": 443, "url_sha256": "d" * 64},
        "dns": {
            "addresses": ["93.184.216.34"],
            "answer_count": 1,
            "dns_sha256": "e" * 64,
            "selected_address": "93.184.216.34",
        },
        "transport": {
            "connected_address": "93.184.216.34",
            "connected_port": 443,
            "bytes_sent": 202,
            "response_status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
        },
        "citation": {
            "adapter": "deterministic-web-fetch",
            "content_sha256": digest,
            "bytes_read": 559,
            "media_type": "text/html",
        },
        "evidence": {
            "schema": "kaliv-browser-peer-runtime/v1",
            "selected_address": "93.184.216.34",
            "connected_port": 443,
            "bytes_sent": 202,
            "status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
            "url_sha256": "d" * 64,
            "production_activation": False,
        },
        "limits": {
            "method": "GET",
            "max_outbound_bytes": 4096,
            "max_response_bytes": 262144,
            "timeout_seconds": 15.0,
            "redirects_followed": False,
        },
        "plan": {
            "plan_id": "bpv_" + "f" * 32,
            "consumed_path": "validation/browser-peer-public-validation-plan.consumed-bpv_x.json",
            "consumed_sha256": "1" * 64,
        },
        "public_network_contacted": True,
        "redirects_followed": False,
        "validation_only": True,
        "production_activation": False,
        "error": None,
    }


def expect_blocked(module, result: dict) -> None:
    try:
        module._validate_result(result)
    except module.OperatorValidationError:
        return
    raise AssertionError("invalid result was accepted")


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "https://example.com" not in source
    assert "https://example.com" not in launcher
    assert "GITHUB_ACTIONS" in source and 'system_name != "Windows"' in source
    assert "stdin_isatty" in source and "stdout_isatty" in source
    assert "EXECUTE ONE PUBLIC GET" in source
    assert '"prepare"' in source and '"run"' in source
    assert '"--execute-public-network"' in source
    assert "Invoke-WebRequest" not in launcher and "curl" not in launcher.lower()
    assert "browser_peer_public_validation_operator.py" in launcher

    # The intended launcher must refuse to create physical evidence from a stale
    # stacked head. It fetches the current main anchor, requires a clean tree and
    # proves that exact fetched commit is an ancestor before invoking Python.
    assert "status --porcelain" in launcher
    assert "fetch --quiet origin main" in launcher
    assert "rev-parse origin/main" in launcher
    assert "merge-base --is-ancestor" in launcher
    assert "Reconcile the integration candidate" in launcher
    assert launcher.index("merge-base --is-ancestor") < launcher.index(
        "& $python.Source $operatorScript --url $Url"
    )

    module = load_module()
    module._require_physical_operator(
        environ={},
        system_name="Windows",
        stdin_isatty=True,
        stdout_isatty=True,
    )
    for kwargs in (
        dict(environ={}, system_name="Linux", stdin_isatty=True, stdout_isatty=True),
        dict(
            environ={"GITHUB_ACTIONS": "true"},
            system_name="Windows",
            stdin_isatty=True,
            stdout_isatty=True,
        ),
        dict(
            environ={"CI": "1"},
            system_name="Windows",
            stdin_isatty=True,
            stdout_isatty=True,
        ),
        dict(environ={}, system_name="Windows", stdin_isatty=False, stdout_isatty=True),
    ):
        try:
            module._require_physical_operator(**kwargs)
        except module.OperatorValidationError:
            pass
        else:
            raise AssertionError("non-physical environment was accepted")

    valid = sample_result()
    summary = module._validate_result(valid)
    assert summary["transport"]["connected_address"] == "93.184.216.34"

    changed = copy.deepcopy(valid)
    changed["transport"]["connected_address"] = "93.184.216.35"
    expect_blocked(module, changed)

    changed = copy.deepcopy(valid)
    changed["citation"]["content_sha256"] = "2" * 64
    expect_blocked(module, changed)

    changed = copy.deepcopy(valid)
    changed["production_activation"] = True
    expect_blocked(module, changed)

    changed = copy.deepcopy(valid)
    changed["plan"]["consumed_path"] = "validation/plan.json"
    expect_blocked(module, changed)

    print("browser peer physical operator contract: PASS")


if __name__ == "__main__":
    main()
