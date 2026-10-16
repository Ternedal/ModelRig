"""Offline integration and CLI regression tests using complete synthetic evidence.

The real assembler and structural gate run here. These fixtures are explicitly
synthetic and never constitute physical evidence or release authorization.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kaliv_release_artifact_preflight as module
from kaliv_release_manifest_assembler import assemble
from kaliv_system_release_gate import REQUIRED_GATES, REQUIRED_REPOSITORIES

PINS = {repo: format(i + 1, "x") * 40 for i, repo in enumerate(REQUIRED_REPOSITORIES)}
M, B, V, VOICE = (PINS[repo] for repo in REQUIRED_REPOSITORIES)


def fixture(root: Path) -> tuple[dict, dict]:
    """Assemble all ten canonical references; write only synthetic local bytes."""
    digest = "a" * 64  # Producer-payload digest deliberately differs from file SHA.
    refs = {
        "software_exact_green": f"kaliv-software-exact-green:{M}:{B}:{V}:{VOICE}:{digest}",
        "consciousness_live_lifecycle": f"consciousness-live-lifecycle:{M}:{digest}",
        "visionrig_physical_perception": f"visionrig-physical-perception:{V}:{digest}",
        "voicerig_physical_acceptance": f"voicerig-physical-acceptance:{VOICE}:{digest}",
        "bodyrig_photoreal_likeness": f"bodyrig-photoreal-likeness:{B}:{digest}",
        "bodyrig_digital_twin_m6": f"bodyrig-digital-twin-m6:{B}:{digest}",
        "bodyrig_android_live_body": f"kaliv-body-android-physical-gate:{M}:{digest}",
        "end_to_end_latency": f"kaliv-end-to-end-latency:{M}:{digest}",
        "recovery_soak": f"kaliv-recovery-soak:{M}:{digest}",
        "repository_authority": f"kaliv-repository-authority:{M}:{B}:{V}:{VOICE}:{digest}",
    }
    manifest, _ = assemble(
        release_id="kaliv-rc-synthetic-preflight-test",
        modelrig_sha=M, bodyrig_sha=B, visionrig_sha=V, voicerig_sha=VOICE,
        evidence_refs=refs,
    )
    attestations = {}
    for gate in REQUIRED_GATES:
        data = json.dumps({"gate": gate, "synthetic": True}).encode("utf-8")
        rel = f"{gate}.json"
        (root / rel).write_bytes(data)
        if gate.startswith("visionrig_"):
            repo = "Ternedal/VisionRig"
        elif gate.startswith("voicerig_"):
            repo = "Ternedal/VoiceRig"
        elif gate in {"bodyrig_photoreal_likeness", "bodyrig_digital_twin_m6"}:
            repo = "Ternedal/BodyRig"
        else:
            repo = "Ternedal/ModelRig"
        attestations[gate] = {
            "reference": refs[gate], "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "repository": repo, "git_sha": PINS[repo],
        }
    return manifest, attestations


class PreflightFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "artifacts"
        self.root.mkdir()
        self.manifest, self.attestations = fixture(self.root)
        self.first = REQUIRED_GATES[0]
        self.item = self.attestations[self.first]
        self.path = self.root / self.item["path"]

    def verify(self):
        return module.preflight(self.manifest, self.attestations, self.root)

    def cli(self, *, manifest=None, attestations=None, root=None, replay_producers=False):
        manifest_path = self.directory / "manifest.json"
        attestations_path = self.directory / "attestations.json"
        manifest_path.write_bytes(
            json.dumps(self.manifest).encode("utf-8") if manifest is None else manifest
        )
        attestations_path.write_bytes(
            json.dumps(self.attestations).encode("utf-8") if attestations is None else attestations
        )
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kaliv_release_artifact_preflight.py"),
             str(manifest_path), str(attestations_path), str(self.root if root is None else root),
             *(["--replay-producers"] if replay_producers else [])],
            capture_output=True, text=True, timeout=10,
        )

    def assertInvalid(self, completed, reason):
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema"], "kaliv-artifact-byte-preflight/v1")
        self.assertEqual(result["state"], "INVALID")
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)
        self.assertIn(reason, result["error"])

class ArtifactPreflightTests(PreflightFixture):
    def test_real_manifest_never_grants_release_authority(self):
        result = self.verify()
        self.assertEqual(result["state"], "BYTE_HASHES_VERIFIED_ONLY")
        self.assertEqual(result["release_id"], self.manifest["release_id"])
        self.assertEqual(result["pinned_repositories"], PINS)
        self.assertEqual(result["checked_gates"], list(REQUIRED_GATES))
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)
        self.assertEqual(result["requires"], [
            "producer_semantic_replay", "human_approval", "trusted_provenance",
        ])
        self.assertEqual(len(result["verified_artifacts"]), 10)
        for record in result["verified_artifacts"]:
            item = self.attestations[record["gate"]]
            self.assertEqual(record, {
                "gate": record["gate"], **item,
                "size_bytes": (self.root / item["path"]).stat().st_size,
            })
            self.assertNotEqual(record["sha256"], record["reference"].split(":")[-1])

    def test_each_gate_rejects_wrong_repository_even_with_valid_pin(self):
        for gate in REQUIRED_GATES:
            with self.subTest(gate=gate):
                original = copy.deepcopy(self.attestations[gate])
                wrong = next(repo for repo in REQUIRED_REPOSITORIES
                             if repo != original["repository"])
                self.attestations[gate]["repository"] = wrong
                self.attestations[gate]["git_sha"] = PINS[wrong]
                with self.assertRaisesRegex(module.AttestationError, "evidence repository mismatch"):
                    self.verify()
                self.attestations[gate] = original

    def test_rejects_wrong_revision(self):
        self.item["git_sha"] = "f" * 40
        with self.assertRaisesRegex(module.AttestationError, "repository pin mismatch"):
            self.verify()

    def test_rejects_malformed_manifest_with_domain_error(self):
        for manifest in ({}, [], None):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(module.AttestationError, "invalid release manifest"):
                    module.preflight(manifest, self.attestations, self.root)
        self.manifest["gates"][self.first]["status"] = []
        with self.assertRaisesRegex(module.AttestationError, "invalid release manifest"):
            self.verify()

    def test_pending_and_failed_gates_cannot_be_byte_verified(self):
        for status in ("PENDING", "FAIL"):
            with self.subTest(status=status):
                self.manifest["gates"][self.first] = {"status": status, "evidence_refs": []}
                with self.assertRaisesRegex(module.AttestationError, "not fully qualified"):
                    self.verify()

    def test_activation_claim_is_invalid(self):
        self.manifest["production_activation"] = True
        with self.assertRaisesRegex(module.AttestationError, "cannot activate production"):
            self.verify()

    def test_tampered_bytes_rejected(self):
        self.path.write_bytes(self.path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(module.AttestationError, "byte hash mismatch"):
            self.verify()

    def test_portable_path_policy(self):
        for value in ("", ".", "..", "/etc/passwd", "../escape", "nested/../escape",
                      "./file", "nested//file", "nested/", r"..\escape", r"C:\escape",
                      "C:relative", r"\\server\share\file", "file:stream",
                      "NUL", "con.txt", "CON .txt", "nested/COM1.json", "file.", "file ",
                      "file?.json", "file*.json", "file|.json", 'file".json',
                      "file\x00.json", "file\n.json", None, []):
            with self.subTest(path=value):
                self.item["path"] = value
                with self.assertRaisesRegex(module.AttestationError, "invalid relative path"):
                    self.verify()

    def test_nested_regular_artifact(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.path.rename(nested / self.path.name)
        self.item["path"] = f"nested/{self.path.name}"
        self.assertEqual(self.verify()["state"], "BYTE_HASHES_VERIFIED_ONLY")

    def test_changed_file_during_hashing_is_rejected(self):
        real_fstat = os.fstat
        calls = 0

        def changed(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.path.write_bytes(self.path.read_bytes() + b"changed")
            return real_fstat(fd)

        with patch.object(module.os, "fstat", side_effect=changed):
            with self.assertRaisesRegex(module.AttestationError, "changed during verification"):
                self.verify()

    def test_replaced_file_between_inspection_and_open_is_rejected(self):
        replacement = self.root / "replacement.json"
        replacement.write_bytes(self.path.read_bytes())
        original_open = module._open_artifact

        @contextmanager
        def replaced(root, parts):
            replacement.replace(self.path)
            with original_open(root, parts) as source:
                yield source

        with patch.object(module, "_open_artifact", replaced):
            with self.assertRaisesRegex(module.AttestationError, "changed during verification"):
                self.verify()

    @unittest.skipUnless(
        os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"),
        "descriptor-relative traversal is unavailable",
    )
    def test_parent_symlink_swap_cannot_redirect_open(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.path.rename(nested / self.path.name)
        self.item["path"] = f"nested/{self.path.name}"
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / self.path.name).write_bytes(b"must never be opened")
        original_inspect = module._inspect_path
        swapped = False

        def inspect_then_swap(root, parts, gate):
            nonlocal swapped
            info = original_inspect(root, parts, gate)
            if not swapped:
                nested.rename(self.root / "original-directory")
                nested.symlink_to(outside, target_is_directory=True)
                swapped = True
            return info

        # No file descriptor may reach fdopen after the directory is swapped.
        with patch.object(module, "_inspect_path", inspect_then_swap):
            with patch.object(module.os, "fdopen", wraps=os.fdopen) as opened:
                with self.assertRaises(OSError):
                    self.verify()
                self.assertEqual(opened.call_count, 0)

    def test_fallback_checks_stable_regular_files(self):
        # Exercise the path-based branch used on platforms without openat.
        with patch.object(module.os, "supports_dir_fd", set()):
            self.assertEqual(self.verify()["state"], "BYTE_HASHES_VERIFIED_ONLY")

    def test_no_network_subprocess_or_artifact_writes(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with patch("socket.socket", side_effect=AssertionError("unexpected network")):
            with patch("subprocess.run", side_effect=AssertionError("unexpected process")):
                self.verify()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})

    def test_cli_success_uses_real_manifest(self):
        completed = self.cli()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(len(result["verified_artifacts"]), 10)
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)

    def test_cli_malformed_manifest_returns_invalid_json(self):
        self.assertInvalid(self.cli(manifest=b"{}"), "invalid release manifest")

    def test_cli_strict_json_for_both_inputs(self):
        cases = (
            (b'{"schema":"first","schema":"second"}', "duplicate JSON object field"),
            (b'{"nested":{"x":1,"x":2}}', "duplicate JSON object field"),
            (b'{"x":NaN}', "invalid JSON constant"),
            (b'{"x":Infinity}', "invalid JSON constant"),
            (b'{"x":-Infinity}', "invalid JSON constant"),
            (b'{"x":1e999}', "non-finite JSON number"),
            (b'{"x":-1e999}', "non-finite JSON number"),
            (b'{"nested":[{"x":1e999}]}', "non-finite JSON number"),
            (b"[]", "must be an object"),
            (b"null", "must be an object"),
            (b"\xff", "utf-8"),
            (b"{", "property name"),
        )
        for field in ("manifest", "attestations"):
            for raw, reason in cases:
                with self.subTest(field=field, raw=raw):
                    self.assertInvalid(self.cli(**{field: raw}), reason)

    def test_cli_oversized_inputs_are_bounded(self):
        for field in ("manifest", "attestations"):
            with self.subTest(field=field):
                self.assertInvalid(
                    self.cli(**{field: b" " * (module.MAX_JSON_BYTES + 1)}),
                    "JSON input exceeds size limit",
                )

    def test_cli_deeply_nested_json_is_invalid(self):
        for depth in (module.MAX_JSON_DEPTH + 1, 2000):
            with self.subTest(depth=depth):
                raw = b'{"x":' * depth + b"0" + b"}" * depth
                self.assertInvalid(self.cli(manifest=raw), "JSON input exceeds nesting limit")

    def test_cli_missing_artifact_root_is_invalid(self):
        self.assertInvalid(self.cli(root=self.directory / "missing"), "root does not exist")

    def test_cli_invalid_metadata_and_tampering_fail_closed(self):
        for field, value, reason in (
            ("sha256", "not-a-digest", "invalid SHA-256"),
            ("repository", [], "evidence repository mismatch"),
            ("git_sha", None, "repository pin mismatch"),
            ("path", "../escape", "invalid relative path"),
        ):
            with self.subTest(field=field):
                original = copy.deepcopy(self.item)
                self.item[field] = value
                self.assertInvalid(self.cli(), reason)
                self.item.clear()
                self.item.update(original)
        self.path.write_bytes(b"tampered")
        self.assertInvalid(self.cli(), "byte hash mismatch")


if __name__ == "__main__":
    unittest.main()

