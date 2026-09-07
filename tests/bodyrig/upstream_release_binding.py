#!/usr/bin/env python3
"""Adversarial software contract for ModelRig #704 upstream BodyRig binding."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import build_mrbody  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig_fixtures import png_fixture, tracking_fixture, vrm_fixture  # noqa: E402
from scripts.bodyrig_bind_upstream_release import (  # noqa: E402
    BINDING_SCHEMA,
    UpstreamReleaseBindingError,
    build_binding,
    validate_release,
    write_binding,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fn, message: str) -> None:
    try:
        fn()
    except UpstreamReleaseBindingError:
        check(True, message)
    except Exception as exc:  # pragma: no cover - diagnostic boundary
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, message)
    else:
        check(False, message)


def sha(char: str) -> str:
    return char * 64


def renderer(*, platform: str, revision: str, digests: tuple[str, str, str]) -> dict:
    return {
        "bodyrig_revision": revision,
        "probe_report_sha256": sha(digests[0]),
        "deformation_report_sha256": sha(digests[1]),
        "quality_report_sha256": sha(digests[2]),
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "machine_quality_revision": "skinned-mesh-geometry-v1",
        "machine_quality_pass": True,
        "runtime_manifest_sha256": sha("4"),
        "avatar_sha256": sha("5"),
        "bodyprint_sha256": sha("6"),
        "renderer_name": "BodyRigReferenceRenderer",
        "renderer_version": "1",
        "unity_platform": platform,
        "unity_version": "6000.3.21f1",
        "build_guid": f"build-{platform.lower()}",
        "device_model": "Windows Rig" if platform == "WindowsPlayer" else "Meta Quest 2",
        "graphics_device": "fixture-gpu",
        "probe_observed_at": "2026-09-07T12:00:00Z",
        "deformation_observed_at": "2026-09-07T12:01:00Z",
        "quality_observed_at": "2026-09-07T12:02:00Z",
    }


def release_fixture(*, body_id: str, package_sha: str) -> dict:
    revision = "a" * 40
    return {
        "format": "bodyrig-release-acceptance",
        "version": 2,
        "completed_at": "2026-09-07T12:03:00Z",
        "bodyrig_revision": revision,
        "automated_acceptance": {
            "report_sha256": sha("1"),
            "package_sha256": package_sha,
            "body_id": body_id,
            "automated_pass": True,
            "physical_clone_mode": "stash-sith-high-fidelity",
            "physical_clone_session_sha256": sha("2"),
            "physical_clone_readiness_sha256": sha("3"),
            "skin_qa_report_sha256": sha("7"),
            "skin_qa_assessment": "low-risk",
        },
        "renderer_acceptance": {
            "windows_unity_univrm": renderer(
                platform="WindowsPlayer", revision=revision, digests=("8", "9", "a")
            ),
            "android_quest_class": renderer(
                platform="Android", revision=revision, digests=("b", "c", "d")
            ),
        },
        "release_gate_pass": True,
        "production_activation": True,
    }


identity = build_identity_bundle(tracking_fixture("upstream-binding-fixture.mov"))
package = build_mrbody(
    identity,
    display_name="Upstream binding fixture",
    avatar_vrm=vrm_fixture("upstream-binding"),
    thumbnail_png=png_fixture(),
    builder_revision="f" * 40,
)
body_id = identity["id"]
package_sha = hashlib.sha256(package).hexdigest()
release = release_fixture(body_id=body_id, package_sha=package_sha)
release_raw = (json.dumps(release, indent=2) + "\n").encode("utf-8")
release_sha = hashlib.sha256(release_raw).hexdigest()

core = validate_release(
    release,
    release_sha256=release_sha,
    installed_body_id=body_id,
    installed_package_sha256=package_sha,
)
check(core["body_id"] == body_id and core["package_sha256"] == package_sha,
      "canonical upstream release binds the installed body/package identity")
check(core["upstream_release_gate_pass"] is True and core["upstream_production_activation"] is True,
      "only the upstream final production PASS is accepted as reference authority")
check(core["runtime_manifest_sha256"] == sha("4") and core["avatar_sha256"] == sha("5"),
      "Windows/Quest runtime identity is reduced to one coherent hash-bound authority")

wrong_package = copy.deepcopy(release)
wrong_package["automated_acceptance"]["package_sha256"] = sha("e")
expect_error(
    lambda: validate_release(wrong_package, release_sha256=release_sha,
                             installed_body_id=body_id, installed_package_sha256=package_sha),
    "upstream package mismatch fails closed",
)

not_final = copy.deepcopy(release)
not_final["production_activation"] = False
expect_error(
    lambda: validate_release(not_final, release_sha256=release_sha,
                             installed_body_id=body_id, installed_package_sha256=package_sha),
    "non-final upstream receipt cannot be promoted into ModelRig proof authority",
)

cross_platform_drift = copy.deepcopy(release)
cross_platform_drift["renderer_acceptance"]["android_quest_class"]["avatar_sha256"] = sha("e")
expect_error(
    lambda: validate_release(cross_platform_drift, release_sha256=release_sha,
                             installed_body_id=body_id, installed_package_sha256=package_sha),
    "Windows/Quest runtime byte drift fails closed",
)

unknown_field = copy.deepcopy(release)
unknown_field["source_video_path"] = "C:/private/source.mp4"
expect_error(
    lambda: validate_release(unknown_field, release_sha256=release_sha,
                             installed_body_id=body_id, installed_package_sha256=package_sha),
    "unknown/private-looking upstream fields cannot silently enter the binding contract",
)

missing_quest = copy.deepcopy(release)
del missing_quest["renderer_acceptance"]["android_quest_class"]
expect_error(
    lambda: validate_release(missing_quest, release_sha256=release_sha,
                             installed_body_id=body_id, installed_package_sha256=package_sha),
    "one-platform physical proof is insufficient",
)

with tempfile.TemporaryDirectory(prefix="modelrig-bodyrig-upstream-") as temp:
    base = Path(temp)
    store_root = base / "store"
    store = MRBodyProfileStore(store_root)
    stored = store.install(package)
    release_path = base / "bodyrig-release-acceptance.json"
    release_path.write_bytes(release_raw)

    binding = build_binding(
        release_path=release_path,
        store_root=store_root,
        bodyrig_repo=base / "unused-bodyrig-repo",
        modelrig_repo=base / "unused-modelrig-repo",
        require_git_state=False,
    )
    check(binding["schema"] == BINDING_SCHEMA and binding["production_activation"] is False,
          "ModelRig binding remains non-activating even when upstream is production accepted")
    check(binding["bodyrig_checkout_verified"] is False
          and binding["modelrig_checkout_verified"] is False,
          "test seam cannot claim checkout verification without Git authority checks")
    check(binding["installed_package_verified"] is True
          and binding["upstream"]["package_sha256"] == stored.package_sha256,
          "binding re-loads and freshly validates the installed .mrbody store bytes")

    output = base / "modelrig-upstream-binding.json"
    write_binding(binding, output)
    written = json.loads(output.read_text(encoding="utf-8"))
    serialized = output.read_text(encoding="utf-8").lower()
    check(written["upstream"]["upstream_release_receipt_sha256"] == release_sha,
          "binding receipt hash-binds the exact upstream release receipt bytes")
    check(all(token not in serialized for token in ("source.mp4", "stash_api", "credential", "bearer_token")),
          "binding output contains no source/credential payload")
    expect_error(lambda: write_binding(binding, output),
                 "binding receipt is create-only and cannot overwrite prior evidence")

print(f"\nBodyRig upstream release binding contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
