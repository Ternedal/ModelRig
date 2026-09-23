#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_b_cache_manifest.py"

spec = importlib.util.spec_from_file_location("stage_b_cache_manifest", SCRIPT)
assert spec is not None and spec.loader is not None
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)

HEAD_A = "a" * 40
HEAD_B = "b" * 40
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_manifest_error(fn, message: str) -> None:
    try:
        fn()
    except manifest.CacheManifestError:
        check(True, message)
    else:
        check(False, message)


def make_cache(root: Path) -> None:
    root.mkdir()
    (root / "proofs.json").write_text(
        json.dumps({"proof": {"sha256": "1" * 64}, "fresh": {"sha256": "2" * 64}}),
        encoding="utf-8",
    )
    ledger = root / "start-ledger"
    ledger.mkdir()
    (ledger / "nonce-a.json").write_text(
        json.dumps({"nonce_sha256": "3" * 64}),
        encoding="utf-8",
    )


with tempfile.TemporaryDirectory(prefix="stage-b-cache-manifest-test-") as raw:
    base = Path(raw)

    cache = base / "valid"
    make_cache(cache)
    created = manifest.create_manifest(cache, HEAD_A)
    verified = manifest.verify_manifest(cache, HEAD_A)
    check(created == verified, "freshly sealed cache verifies for the same exact head")

    expect_manifest_error(
        lambda: manifest.verify_manifest(cache, HEAD_B),
        "cache sealed for one exact head is rejected for a different SHA",
    )

    tampered = base / "tampered-proof"
    make_cache(tampered)
    manifest.create_manifest(tampered, HEAD_A)
    (tampered / "proofs.json").write_text('{"tampered":true}\n', encoding="utf-8")
    expect_manifest_error(
        lambda: manifest.verify_manifest(tampered, HEAD_A),
        "tampered proofs.json is rejected",
    )

    ledger_tampered = base / "tampered-ledger"
    make_cache(ledger_tampered)
    manifest.create_manifest(ledger_tampered, HEAD_A)
    (ledger_tampered / "start-ledger" / "nonce-a.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )
    expect_manifest_error(
        lambda: manifest.verify_manifest(ledger_tampered, HEAD_A),
        "tampered start-ledger payload is rejected",
    )

    extra_payload = base / "extra-payload"
    make_cache(extra_payload)
    manifest.create_manifest(extra_payload, HEAD_A)
    (extra_payload / "unexpected.json").write_text("{}\n", encoding="utf-8")
    expect_manifest_error(
        lambda: manifest.verify_manifest(extra_payload, HEAD_A),
        "unexpected payload files invalidate the sealed cache digest",
    )

    wrong_schema = base / "wrong-schema"
    make_cache(wrong_schema)
    manifest.create_manifest(wrong_schema, HEAD_A)
    manifest_path = wrong_schema / manifest.MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema"] = "modelrig-stage-b-cache/v0"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    expect_manifest_error(
        lambda: manifest.verify_manifest(wrong_schema, HEAD_A),
        "stale cache manifest schema is rejected",
    )

    malformed = base / "malformed"
    make_cache(malformed)
    (malformed / manifest.MANIFEST_NAME).write_text("{", encoding="utf-8")
    expect_manifest_error(
        lambda: manifest.verify_manifest(malformed, HEAD_A),
        "malformed cache manifest fails closed",
    )

    invalid_sha = base / "invalid-sha"
    make_cache(invalid_sha)
    expect_manifest_error(
        lambda: manifest.create_manifest(invalid_sha, "not-a-sha"),
        "non-canonical head SHA is rejected",
    )

print(f"Stage-B cache-manifest contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
