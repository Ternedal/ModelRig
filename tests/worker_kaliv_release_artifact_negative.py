"""Adversarial filesystem and attestation checks with the real structural gate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from worker_kaliv_release_artifact_preflight import PreflightFixture, module


class ArtifactNegativeTests(PreflightFixture):
    def test_incomplete_and_extra_gate_sets(self):
        for change in ("missing", "extra"):
            with self.subTest(change=change):
                items = copy.deepcopy(self.attestations)
                if change == "missing":
                    del items[self.first]
                else:
                    items["invented_gate"] = dict(self.item)
                with self.assertRaisesRegex(module.AttestationError, "exactly cover"):
                    module.preflight(self.manifest, items, self.root)

    def test_inexact_attestation_fields(self):
        for item in (None, [], {**self.item, "extra": True},
                     {key: value for key, value in self.item.items() if key != "path"}):
            with self.subTest(item=item):
                self.attestations[self.first] = item
                with self.assertRaisesRegex(module.AttestationError, "invalid attestation fields"):
                    self.verify()

    def test_reference_and_digest_validation(self):
        original = copy.deepcopy(self.item)
        cases = (
            ("reference", "receipt:wrong", "reference mismatch"),
            ("reference", [], "reference mismatch"),
            ("sha256", "f" * 64, "byte hash mismatch"),
            ("sha256", "A" * 64, "invalid SHA-256"),
            ("sha256", "a" * 63, "invalid SHA-256"),
            ("sha256", None, "invalid SHA-256"),
            ("sha256", [], "invalid SHA-256"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field, value=value):
                self.item.clear()
                self.item.update(original)
                self.item[field] = value
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.verify()

    def test_missing_file_and_directory_are_not_evidence(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()
        self.path.mkdir()
        with self.assertRaisesRegex(module.AttestationError, "unsafe or missing artifact"):
            self.verify()

    def symlink_or_skip(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem cannot create symlinks")

    def test_leaf_symlink_to_internal_file_is_rejected(self):
        link = self.root / "linked.json"
        self.symlink_or_skip(link, self.path)
        self.item["path"] = link.name
        with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
            self.verify()

    def test_leaf_symlink_to_outside_file_is_rejected(self):
        outside = self.directory / "outside.json"
        outside.write_bytes(self.path.read_bytes())
        self.path.unlink()
        self.symlink_or_skip(self.path, outside)
        with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
            self.verify()

    def test_directory_symlinks_inside_and_outside_are_rejected(self):
        for target in (self.root, self.directory):
            with self.subTest(target=target):
                link = self.root / "directory-link"
                self.symlink_or_skip(link, target, directory=True)
                self.item["path"] = f"{link.name}/{self.path.name}"
                with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
                    self.verify()
                link.unlink()

    def test_windows_reparse_attribute_is_rejected(self):
        original = Path.lstat

        def reparse(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.path:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, "lstat", reparse):
            with self.assertRaisesRegex(module.AttestationError, "reparse point"):
                self.verify()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO files unavailable")
    def test_named_pipe_is_rejected_without_blocking(self):
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(module.AttestationError, "unsafe or missing artifact"):
            self.verify()

    def test_artifact_size_boundary(self):
        # A small injected budget tests both boundaries without allocating
        # sixteen megabytes for each ordinary regression execution.
        with patch.object(module, "MAX_BYTES", 1024):
            data = b"x" * 1024
            self.path.write_bytes(data)
            self.item["sha256"] = hashlib.sha256(data).hexdigest()
            self.assertEqual(self.verify()["state"], "BYTE_HASHES_VERIFIED_ONLY")
            self.path.write_bytes(data + b"x")
            with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
                self.verify()

    def test_file_growth_during_read_obeys_byte_budget(self):
        original_fstat = os.fstat
        changed = False

        def grow(fd):
            nonlocal changed
            info = original_fstat(fd)
            if not changed:
                self.path.write_bytes(b"x" * 2048)
                changed = True
            return info

        with patch.object(module, "MAX_BYTES", 1024):
            with patch.object(module.os, "fstat", side_effect=grow):
                with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
                    self.verify()

    def test_cli_missing_input_returns_json(self):
        missing = self.directory / "missing.json"
        completed = subprocess.run(
            [sys.executable, str(Path(module.__file__)), str(missing),
             str(missing), str(self.root)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(result["state"], "INVALID")
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)



class ArtifactProducerReplayTests(PreflightFixture):
    def setUp(self):
        super().setUp()
        # Reuse the existing canonical test fixtures and REAL validators.
        # These are synthetic reports; no physical observations are created.
        import worker_kaliv_software_exact_green_qualifier as software
        import worker_kaliv_repository_authority_qualifier as authority
        import worker_consciousness_core_live_lifecycle_qualification as lifecycle
        import worker_kaliv_voicerig_physical_qualifier as voice
        import worker_kaliv_bodyrig_digital_twin_m6_qualifier as m6
        import worker_kaliv_bodyrig_photoreal_qualifier as photo

        pins = {item["repository"]: item["git_sha"] for item in self.manifest["repositories"]}
        model_sha, body_sha, voice_sha = (
            pins["Ternedal/ModelRig"], pins["Ternedal/BodyRig"], pins["Ternedal/VoiceRig"]
        )
        lifecycle_payload = lifecycle.evidence()
        lifecycle_payload["candidate_git_sha"] = model_sha
        lifecycle_payload["live_cycle"]["candidate"]["git_sha"] = model_sha
        lifecycle_payload["dormancy_restart"]["candidate_git_sha"] = model_sha
        lifecycle_payload["model_swap"]["candidate_git_sha"] = model_sha
        voice_payload = voice._acceptance()
        voice_payload["source"]["revision"] = voice_sha
        m6_payload = m6._authority()
        m6_payload["bodyrig_revision"] = body_sha
        m6_payload["release_id"] = m6.module._release_id(m6_payload)
        photo_payload = photo._authority()
        photo_payload["bodyrig_revision"] = body_sha
        photo_payload["release_id"] = photo.module._release_id(photo_payload)

        self.payloads = {
            "software_exact_green": software._evidence(),
            "consciousness_live_lifecycle": lifecycle_payload,
            "voicerig_physical_acceptance": voice_payload,
            "bodyrig_photoreal_likeness": photo_payload,
            "bodyrig_digital_twin_m6": m6_payload,
            "repository_authority": authority._evidence(),
        }
        self.qualifiers = {
            "software_exact_green": software.module.qualify,
            "consciousness_live_lifecycle": lifecycle.qualifier.qualify,
            "voicerig_physical_acceptance": lambda p: voice.module.qualify(p, expected_voicerig_sha=voice_sha),
            "bodyrig_photoreal_likeness": lambda p: photo.module.qualify(p, expected_bodyrig_sha=body_sha),
            "bodyrig_digital_twin_m6": lambda p: m6.module.qualify(p, expected_bodyrig_sha=body_sha),
            "repository_authority": authority.module.qualify,
        }
        for gate, payload in self.payloads.items():
            self.write_payload(gate, payload)
            ref = self.qualifiers[gate](payload)["release_evidence_ref"]
            self.manifest["gates"][gate]["evidence_refs"] = [ref]
            self.attestations[gate]["reference"] = ref

    def write_raw(self, gate, raw):
        item = self.attestations[gate]
        (self.root / item["path"]).write_bytes(raw)
        item["sha256"] = hashlib.sha256(raw).hexdigest()

    def write_payload(self, gate, payload):
        self.write_raw(gate, json.dumps(payload, sort_keys=True).encode("utf-8"))

    def replay(self):
        return module.preflight(self.manifest, self.attestations, self.root, replay_producers=True)

    def test_six_real_producers_replay_without_global_release_authority(self):
        result = self.replay()
        report = result["producer_replay"]
        self.assertEqual(report["state"], "PARTIAL")
        self.assertIs(report["complete"], False)
        self.assertEqual(report["verified_gates"], list(self.payloads))
        self.assertEqual(report["not_replayed_gates"], [
            "visionrig_physical_perception", "bodyrig_android_live_body",
            "end_to_end_latency", "recovery_soak",
        ])
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)
        self.assertEqual(len(report["verdicts"]), 6)
        for entry in report["verdicts"]:
            expected = self.qualifiers[entry["gate"]](self.payloads[entry["gate"]])
            self.assertEqual(entry["producer_schema"], expected["schema"])
            self.assertEqual(entry["release_evidence_ref"], expected["release_evidence_ref"])
            self.assertEqual(entry["state"], "PRODUCER_PAYLOAD_REPLAYED_ONLY")
            self.assertIs(entry["production_activation"], False)

    def test_default_remains_byte_only_and_does_not_invoke_producers(self):
        payload = copy.deepcopy(self.payloads["software_exact_green"])
        payload["repositories"][0]["software_green"] = False
        self.write_payload("software_exact_green", payload)
        with patch.object(module, "_replay_producer", side_effect=AssertionError("not opted in")):
            result = self.verify()
        self.assertNotIn("producer_replay", result)

    def test_each_producer_rejects_rehashed_failed_evidence(self):
        mutations = {
            "software_exact_green": lambda p: p["repositories"][0].update(software_green=False),
            "consciousness_live_lifecycle": lambda p: p["dormancy_restart"].update(restart_proven=False),
            "voicerig_physical_acceptance": lambda p: p["quality"].update({"pass": False}),
            "bodyrig_photoreal_likeness": lambda p: p.update(photoreal_digital_twin_ready=False),
            "bodyrig_digital_twin_m6": lambda p: p.update(digital_twin_ready=False),
            "repository_authority": lambda p: p["repositories"][0].update(live_repository_authority_passed=False),
        }
        for gate, mutate in mutations.items():
            with self.subTest(gate=gate):
                payload = copy.deepcopy(self.payloads[gate])
                mutate(payload)
                self.write_payload(gate, payload)
                with self.assertRaisesRegex(module.AttestationError, "producer replay failed"):
                    self.replay()
                self.write_payload(gate, self.payloads[gate])

    def test_each_producer_must_reproduce_manifest_reference(self):
        for gate in self.payloads:
            with self.subTest(gate=gate):
                original = self.attestations[gate]["reference"]
                forged = original.rsplit(":", 1)[0] + ":" + "f" * 64
                self.attestations[gate]["reference"] = forged
                self.manifest["gates"][gate]["evidence_refs"] = [forged]
                with self.assertRaisesRegex(module.AttestationError, "producer evidence reference mismatch"):
                    self.replay()
                self.attestations[gate]["reference"] = original
                self.manifest["gates"][gate]["evidence_refs"] = [original]

    def test_valid_but_changed_source_receipt_is_not_old_evidence(self):
        payload = copy.deepcopy(self.payloads["software_exact_green"])
        payload["repositories"][0]["evidence_ref"] += ":different-run"
        self.write_payload("software_exact_green", payload)
        with self.assertRaisesRegex(module.AttestationError, "producer evidence reference mismatch"):
            self.replay()

    def test_wrong_source_revisions_fail_even_when_file_hash_matches(self):
        mutations = {
            "software_exact_green": lambda p: p["repositories"][2].update(git_sha="f" * 40),
            "consciousness_live_lifecycle": lambda p: p.update(candidate_git_sha="f" * 40),
            "voicerig_physical_acceptance": lambda p: p["source"].update(revision="f" * 40),
            "bodyrig_photoreal_likeness": lambda p: p.update(bodyrig_revision="f" * 40),
            "bodyrig_digital_twin_m6": lambda p: p.update(bodyrig_revision="f" * 40),
            "repository_authority": lambda p: p["repositories"][3].update(git_sha="f" * 40),
        }
        for gate, mutate in mutations.items():
            with self.subTest(gate=gate):
                payload = copy.deepcopy(self.payloads[gate])
                mutate(payload)
                self.write_payload(gate, payload)
                with self.assertRaisesRegex(module.AttestationError, "producer replay failed"):
                    self.replay()
                self.write_payload(gate, self.payloads[gate])

    def test_source_verdict_wrappers_cannot_replace_raw_evidence(self):
        for gate in self.payloads:
            with self.subTest(gate=gate):
                self.write_payload(gate, self.qualifiers[gate](self.payloads[gate]))
                with self.assertRaisesRegex(module.AttestationError, "producer replay failed"):
                    self.replay()
                self.write_payload(gate, self.payloads[gate])

    def test_json_whitespace_and_key_order_do_not_change_canonical_reference(self):
        for gate, payload in self.payloads.items():
            raw = json.dumps(payload, indent=3, sort_keys=False).encode("utf-8") + b"\n"
            self.write_raw(gate, raw)
        self.assertEqual(len(self.replay()["producer_replay"]["verified_gates"]), 6)

    def test_strict_json_applies_to_the_verified_source_bytes(self):
        for raw, reason in (
            (b'{"schema":"a","schema":"b"}', "duplicate JSON object field"),
            (b'{"nested":{"x":1,"x":2}}', "duplicate JSON object field"),
            (b'{"x":NaN}', "invalid JSON constant"),
            (b"[]", "must be an object"),
            (b"\xff", "utf-8"),
            (b'{"x":' * 65 + b"0" + b"}" * 65, "nesting limit"),
        ):
            with self.subTest(raw=raw[:50]):
                self.write_raw("software_exact_green", raw)
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.replay()

    def test_replay_json_budget_is_smaller_than_generic_artifact_budget(self):
        with patch.object(module, "MAX_JSON_BYTES", self.path.stat().st_size - 1):
            with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
                self.replay()

    def test_replay_uses_same_bytes_as_hash_without_reopening_artifact(self):
        from contextlib import contextmanager

        original_open = module._open_artifact
        original_bytes = self.path.read_bytes()
        original_digest = hashlib.sha256(original_bytes).hexdigest()
        opens = []

        @contextmanager
        def replace_after_read(root, parts):
            opens.append("/".join(parts))
            with original_open(root, parts) as source:
                yield source
            if "/".join(parts) == self.item["path"]:
                self.path.write_bytes(b"replaced after snapshot was read")

        with patch.object(module, "_open_artifact", replace_after_read):
            result = self.replay()
        self.assertEqual(opens.count(self.item["path"]), 1)
        self.assertEqual(result["verified_artifacts"][0]["sha256"], original_digest)
        self.assertEqual(len(result["producer_replay"]["verified_gates"]), 6)

    def test_replay_does_not_fetch_nested_artifacts_or_contact_live_services(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch("socket.socket", side_effect=AssertionError("unexpected network")):
            with patch("subprocess.run", side_effect=AssertionError("unexpected process")):
                self.replay()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_cli_replays_all_supported_payloads(self):
        completed = self.cli(replay_producers=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(len(result["producer_replay"]["verified_gates"]), 6)
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)

    def test_cli_rehashed_semantic_failure_returns_invalid(self):
        payload = copy.deepcopy(self.payloads["software_exact_green"])
        payload["repositories"][0]["software_green"] = False
        self.write_payload("software_exact_green", payload)
        self.assertInvalid(self.cli(replay_producers=True), "software_green must be true")

    def test_missing_producer_module_fails_closed(self):
        with patch.object(module.importlib, "import_module", side_effect=ModuleNotFoundError("missing qualifier")):
            with self.assertRaisesRegex(module.AttestationError, "producer replay failed: missing qualifier"):
                self.replay()

    def test_producer_authority_overclaim_cannot_escape_adapter(self):
        verdict = self.qualifiers["software_exact_green"](self.payloads["software_exact_green"])
        verdict["production_activation"] = True
        with patch("kaliv_software_exact_green_qualifier.qualify", return_value=verdict):
            with self.assertRaisesRegex(module.AttestationError, "not a bounded qualification"):
                self.replay()

    def test_replay_opt_in_must_be_boolean(self):
        for value in (None, 1, "true"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(module.AttestationError, "must be a boolean"):
                    module.preflight(self.manifest, self.attestations, self.root, replay_producers=value)

if __name__ == "__main__":
    unittest.main()

