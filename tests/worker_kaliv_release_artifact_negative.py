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



class ProducerReplayFixture(PreflightFixture):
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
        self.add_latency_fixture(model_sha)

    def add_latency_fixture(self, model_sha):
        import kaliv_end_to_end_latency_qualifier as latency

        self.latency_producer = latency
        self.latency_sources = {}
        self.latency_paths = {}
        details = {
            "perception_received": {"input_kind": "voice", "input_id": "input-1"},
            "cognition_completed": {"cognition_event_id": "latency-event-1",
                                    "transition_receipt_ref": "transition:synthetic", "completed_cycles": 1},
            "outward_started": {"outward_kind": "voice+body", "started": True,
                                "utterance_id": "utterance-1", "body_runtime_id": "body-1"},
        }
        for phase, at_ms in zip(details, (1000.0, 1300.0, 1500.0)):
            value = {
                "schema": latency.SOURCE_SCHEMA, "phase": phase,
                "candidate_git_sha": model_sha, "event_id": "latency-event-1",
                "runtime_epoch": "epoch-1", "observer_id": "observer-1",
                "clock": {"kind": "monotonic", "unit": "milliseconds", "origin": "single-observer"},
                "observed_at_ms": at_ms, "real_event": True, "simulated": False,
                "replay": False, "details": details[phase], "production_activation": False,
            }
            self.latency_sources[phase] = value
            rel = Path("latency") / f"{phase}.json"
            self.latency_paths[phase] = rel
            path = self.root / rel
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(json.dumps(value, sort_keys=True).encode("utf-8"))
        self.latency_report = self.measure_latency()
        self.write_payload("end_to_end_latency", self.latency_report)
        reference = self.latency_report["release_evidence_ref"]
        self.manifest["gates"]["end_to_end_latency"]["evidence_refs"] = [reference]
        self.attestations["end_to_end_latency"]["reference"] = reference

    def measure_latency(self):
        return self.latency_producer.qualify_receipts(
            evidence_root=self.root,
            perception_path=self.latency_paths["perception_received"],
            cognition_path=self.latency_paths["cognition_completed"],
            outward_path=self.latency_paths["outward_started"],
        )

    def write_latency_source(self, phase, raw, *, update_claim=True):
        (self.root / self.latency_paths[phase]).write_bytes(raw)
        if update_claim:
            for item in self.latency_report["source_receipts"]:
                if item["phase"] == phase:
                    item["sha256"] = hashlib.sha256(raw).hexdigest()
            self.write_payload("end_to_end_latency", self.latency_report)

    def write_raw(self, gate, raw):
        item = self.attestations[gate]
        (self.root / item["path"]).write_bytes(raw)
        item["sha256"] = hashlib.sha256(raw).hexdigest()

    def write_payload(self, gate, payload):
        self.write_raw(gate, json.dumps(payload, sort_keys=True).encode("utf-8"))

    def replay(self):
        return module.preflight(self.manifest, self.attestations, self.root, replay_producers=True)

class ArtifactProducerReplayTests(ProducerReplayFixture):
    def test_supported_producers_replay_without_global_release_authority(self):
        result = self.replay()
        report = result["producer_replay"]
        self.assertEqual(report["state"], "PARTIAL")
        self.assertIs(report["complete"], False)
        self.assertEqual(report["verified_gates"], [
            gate for gate in module.REQUIRED_GATES if gate in self.payloads or gate == "end_to_end_latency"
        ])
        self.assertEqual(report["not_replayed_gates"], [
            "visionrig_physical_perception", "bodyrig_android_live_body",
            "recovery_soak",
        ])
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)
        self.assertEqual(len(report["verdicts"]), 7)
        for entry in report["verdicts"]:
            expected = (self.latency_report if entry["gate"] == "end_to_end_latency"
                        else self.qualifiers[entry["gate"]](self.payloads[entry["gate"]]))
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
        self.assertEqual(len(self.replay()["producer_replay"]["verified_gates"]), 7)

    def test_strict_json_applies_to_the_verified_source_bytes(self):
        for raw, reason in (
            (b'{"schema":"a","schema":"b"}', "duplicate JSON object field"),
            (b'{"nested":{"x":1,"x":2}}', "duplicate JSON object field"),
            (b'{"x":NaN}', "invalid JSON constant"),
            (b'{"nested":[{"x":1e999}]}', "non-finite JSON number"),
            (b'{"x":-1e999}', "non-finite JSON number"),
            (b"[]", "must be an object"),
            (b"\xff", "utf-8"),
            (b'{"x":' * 65 + b"0" + b"}" * 65, "nesting limit"),
        ):
            with self.subTest(raw=raw[:50]):
                self.write_raw("software_exact_green", raw)
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.replay()

    def test_overflow_in_nested_metadata_is_rejected_even_with_matching_producer_reference(self):
        gate = "consciousness_live_lifecycle"
        for number, token in ((float("inf"), b"1e999"), (float("-inf"), b"-1e999")):
            with self.subTest(token=token):
                payload = copy.deepcopy(self.payloads[gate])
                payload["live_cycle"]["diagnostics"] = {"numbers": [number]}
                # The existing producer hashes extra diagnostic fields without
                # rejecting infinity. Even its matching ref must not bypass
                # the preflight's stricter JSON input contract.
                reference = self.qualifiers[gate](payload)["release_evidence_ref"]
                self.manifest["gates"][gate]["evidence_refs"] = [reference]
                self.attestations[gate]["reference"] = reference
                raw = json.dumps(payload).encode("utf-8")
                literal = b"Infinity" if number > 0 else b"-Infinity"
                self.write_raw(gate, raw.replace(literal, token))
                with self.assertRaisesRegex(module.AttestationError, "non-finite JSON number"):
                    self.replay()
                self.assertInvalid(self.cli(replay_producers=True), "non-finite JSON number")

    def test_finite_exponents_and_numeric_text_preserve_producer_reference(self):
        gate = "consciousness_live_lifecycle"
        payload = copy.deepcopy(self.payloads[gate])
        payload["live_cycle"]["diagnostics"] = {
            "numbers": [1.7976931348623157e308, -1.7976931348623157e308, 5e-324, -0.0, 0.0],
            "text": "1e999 and -Infinity are ordinary text",
        }
        reference = self.qualifiers[gate](payload)["release_evidence_ref"]
        self.manifest["gates"][gate]["evidence_refs"] = [reference]
        self.attestations[gate]["reference"] = reference
        self.write_payload(gate, payload)
        result = self.replay()
        replayed = next(item for item in result["producer_replay"]["verdicts"] if item["gate"] == gate)
        self.assertEqual(replayed["release_evidence_ref"], reference)

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
        self.assertEqual(len(result["producer_replay"]["verified_gates"]), 7)

    def test_replay_does_not_contact_services_or_mutate_artifacts(self):
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("socket.socket", side_effect=AssertionError("unexpected network")):
            with patch("subprocess.run", side_effect=AssertionError("unexpected process")):
                self.replay()
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes()
                                  for p in self.root.rglob("*") if p.is_file()})

    def test_cli_replays_all_supported_payloads(self):
        completed = self.cli(replay_producers=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(len(result["producer_replay"]["verified_gates"]), 7)
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


class ArtifactLatencyReplayTests(ProducerReplayFixture):
    def latency_verdict(self, result):
        return next(item for item in result["producer_replay"]["verdicts"]
                    if item["gate"] == "end_to_end_latency")

    def test_latency_replay_binds_each_source_file_and_measured_phases(self):
        result = self.replay()
        replayed = self.latency_verdict(result)
        self.assertEqual(replayed["producer_schema"], self.latency_producer.VERDICT_SCHEMA)
        self.assertEqual(replayed["release_evidence_ref"], self.latency_report["release_evidence_ref"])
        self.assertEqual(len(replayed["verified_source_receipts"]), 3)
        for record in replayed["verified_source_receipts"]:
            path = self.root / record["path"]
            self.assertEqual(record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(record["size_bytes"], path.stat().st_size)
            self.assertFalse(Path(record["path"]).is_absolute())
        self.assertEqual(self.latency_report["end_to_end_ms"], 500.0)
        self.assertIs(self.latency_report["threshold_applied"], False)
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)

    def test_changed_source_without_updating_digest_is_rejected(self):
        phase = "perception_received"
        raw = (self.root / self.latency_paths[phase]).read_bytes() + b"\n"
        self.write_latency_source(phase, raw, update_claim=False)
        with self.assertRaisesRegex(module.AttestationError, "source byte hash mismatch"):
            self.replay()

    def test_rehashed_spliced_or_failed_source_receipts_are_rejected(self):
        cases = (
            ("cognition_completed", lambda p: p.update(candidate_git_sha="f" * 40), "candidate SHA mismatch"),
            ("cognition_completed", lambda p: p.update(event_id="other-event"), "mixed correlation"),
            ("outward_started", lambda p: p.update(runtime_epoch="other-epoch"), "mixed runtime epoch"),
            ("outward_started", lambda p: p.update(observer_id="other-observer"), "mixed observer"),
            ("cognition_completed", lambda p: p.update(observed_at_ms=999.0), "timestamps must be monotone"),
            ("perception_received", lambda p: p.update(simulated=True), "non-simulated"),
            ("perception_received", lambda p: p.update(replay=True), "replay evidence"),
            ("cognition_completed", lambda p: p["details"].update(completed_cycles=0), "completed real cycle"),
            ("outward_started", lambda p: p["details"].update(started=False), "actual outward start"),
        )
        for phase, mutate, reason in cases:
            with self.subTest(phase=phase, reason=reason):
                payload = copy.deepcopy(self.latency_sources[phase])
                mutate(payload)
                self.write_latency_source(phase, json.dumps(payload).encode("utf-8"))
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.replay()
                self.write_latency_source(phase, json.dumps(self.latency_sources[phase], sort_keys=True).encode("utf-8"))

    def test_rehashed_valid_source_change_does_not_match_old_latency_verdict(self):
        payload = copy.deepcopy(self.latency_sources["outward_started"])
        payload["observed_at_ms"] = 1600.0
        self.write_latency_source("outward_started", json.dumps(payload).encode("utf-8"))
        with self.assertRaisesRegex(module.AttestationError, "latency verdict does not match source receipts"):
            self.replay()

    def test_coherent_new_verdict_still_requires_manifest_reference_binding(self):
        payload = copy.deepcopy(self.latency_sources["outward_started"])
        payload["observed_at_ms"] = 1600.0
        self.write_latency_source("outward_started", json.dumps(payload).encode("utf-8"))
        changed = self.measure_latency()
        self.write_payload("end_to_end_latency", changed)
        with self.assertRaisesRegex(module.AttestationError, "producer evidence reference mismatch"):
            self.replay()
        self.manifest["gates"]["end_to_end_latency"]["evidence_refs"] = [changed["release_evidence_ref"]]
        self.attestations["end_to_end_latency"]["reference"] = changed["release_evidence_ref"]
        result = self.replay()
        self.assertEqual(self.latency_verdict(result)["release_evidence_ref"], changed["release_evidence_ref"])
        self.assertIs(result["release_ready"], False)

    def test_report_fields_are_compared_canonically_including_boolean_types(self):
        for field, value in (
            ("end_to_end_ms", 999.0), ("threshold_applied", 0),
            ("production_activation", 0), ("release_gate_satisfied", True),
            ("state", "QUALIFIED"), ("release_ready", True),
        ):
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(self.latency_report)
                report[field] = value
                self.write_payload("end_to_end_latency", report)
                with self.assertRaisesRegex(module.AttestationError, "latency verdict does not match source receipts"):
                    self.replay()

    def test_source_declarations_must_cover_exactly_three_distinct_phases(self):
        sources = self.latency_report["source_receipts"]
        malformed = (
            None, sources[:2], [sources[0], sources[0], sources[2]],
            [{**sources[0], "phase": []}, sources[1], sources[2]],
            [{**sources[0], "extra": True}, sources[1], sources[2]],
            [{**sources[0], "sha256": "A" * 64}, sources[1], sources[2]],
        )
        for value in malformed:
            with self.subTest(value=value):
                report = copy.deepcopy(self.latency_report)
                report["source_receipts"] = value
                self.write_payload("end_to_end_latency", report)
                with self.assertRaisesRegex(module.AttestationError, "producer replay failed"):
                    self.replay()

    def test_nested_source_path_escape_is_rejected(self):
        report = copy.deepcopy(self.latency_report)
        report["source_receipts"][0]["path"] = "../outside.json"
        self.write_payload("end_to_end_latency", report)
        with self.assertRaisesRegex(module.AttestationError, "invalid relative path"):
            self.replay()

    def test_nested_source_symlink_is_rejected(self):
        source = self.root / self.latency_paths["perception_received"]
        target = source.with_name("source-target.json")
        source.rename(target)
        try:
            source.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem cannot create symlinks")
        with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
            self.replay()

    def test_source_json_is_strict_even_when_declared_byte_digest_matches(self):
        for raw, reason in (
            (b'{"schema":"a","schema":"b"}', "duplicate JSON object field"),
            (b'{"nested":{"x":1,"x":2}}', "duplicate JSON object field"),
            (b'{"observed_at_ms":NaN}', "invalid JSON constant"),
            (b'{"observed_at_ms":1e999}', "non-finite JSON number"),
            (b'{"nested":[{"x":-1e999}]}', "non-finite JSON number"),
            (b"[]", "must be an object"), (b"\xff", "utf-8"),
            (b'{"x":' * 65 + b"0" + b"}" * 65, "nesting limit"),
        ):
            with self.subTest(raw=raw[:40]):
                self.write_latency_source("perception_received", raw)
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.replay()

    def test_extreme_integer_measurements_fail_closed_through_api_and_cli(self):
        for phase, original in self.latency_sources.items():
            with self.subTest(phase=phase):
                payload = copy.deepcopy(original)
                payload["observed_at_ms"] = 10 ** 400
                self.write_latency_source(phase, json.dumps(payload).encode("utf-8"))
                try:
                    with self.assertRaisesRegex(module.AttestationError, "numeric value exceeds supported range"):
                        self.replay()
                    self.assertInvalid(self.cli(replay_producers=True), "numeric value exceeds supported range")
                finally:
                    self.write_latency_source(phase, json.dumps(original, sort_keys=True).encode("utf-8"))

    def test_source_size_limit_is_checked_before_staging_or_json_decode(self):
        self.write_latency_source("perception_received", b"x" * (module.MAX_JSON_BYTES + 1))
        with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
            self.replay()

    def test_private_snapshot_directories_are_removed_on_success_and_failure(self):
        real_temporary_directory = module.tempfile.TemporaryDirectory
        created = []

        def temporary(*args, **kwargs):
            context = real_temporary_directory(*args, **kwargs)
            created.append(Path(context.name))
            return context

        with patch.object(module.tempfile, "TemporaryDirectory", side_effect=temporary):
            self.replay()
            bad = copy.deepcopy(self.latency_sources["outward_started"])
            bad["details"]["started"] = False
            self.write_latency_source("outward_started", json.dumps(bad).encode("utf-8"))
            with self.assertRaisesRegex(module.AttestationError, "actual outward start"):
                self.replay()
        self.assertEqual(len(created), 2)
        self.assertTrue(all(not path.exists() for path in created))

    def test_source_replay_uses_original_verified_snapshot_if_path_changes_after_read(self):
        from contextlib import contextmanager

        source_rel = self.latency_paths["perception_received"].as_posix()
        real_open = module._open_artifact
        opened = []

        @contextmanager
        def replace_after_snapshot(root, parts):
            relative = "/".join(parts)
            opened.append(relative)
            with real_open(root, parts) as source:
                yield source
            if relative == source_rel:
                (self.root / source_rel).write_bytes(b"changed after the verified snapshot")

        with patch.object(module, "_open_artifact", replace_after_snapshot):
            result = self.replay()
        self.assertEqual(opened.count(source_rel), 1)
        self.assertEqual(self.latency_verdict(result)["release_evidence_ref"],
                         self.latency_report["release_evidence_ref"])

    def test_missing_source_returns_invalid_json_from_cli(self):
        (self.root / self.latency_paths["cognition_completed"]).unlink()
        self.assertInvalid(self.cli(replay_producers=True), "producer replay failed")

    def test_legacy_latency_verdict_is_not_silently_treated_as_v2(self):
        report = copy.deepcopy(self.latency_report)
        report["schema"] = "kaliv-system/end-to-end-latency-verdict/v1"
        self.write_payload("end_to_end_latency", report)
        with self.assertRaisesRegex(module.AttestationError, "canonical v2 verdict"):
            self.replay()

if __name__ == "__main__":
    unittest.main()

