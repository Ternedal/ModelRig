from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.catalog import (
    CatalogError,
    CatalogMaterializer,
    IsolationAttestation,
    IsolationBoundary,
    LocalExecutableHashVerifier,
    NetworkMode,
    ToolBinding,
    Toolchain,
    modelrig_command_catalog,
)
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.github_read import (
    GitHubReadAdapter,
    GitHubReadError,
    GitHubReadReceipt,
    HttpResponse,
)


BASE_SHA = "a" * 40
BLOB_SHA = "b" * 40
HASH = "c" * 64


def task(*commands: str) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A5_SLICE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Validate the next isolated control-plane slice.",
            "acceptance_criteria": ["All fixed-authority tests pass."],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": list(commands) or ["modelrig.devcontrol.tests"],
            "required_tests": ["modelrig.devcontrol.tests"],
            "budget": {
                "max_changed_files": 20,
                "max_added_lines": 5000,
                "max_deleted_lines": 5000,
                "max_attempts": 2,
                "max_runtime_seconds": 3600,
                "max_output_bytes": 1000000,
            },
            "merge_authority": "human",
        }
    )


class AcceptIsolation:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, attestation: IsolationAttestation) -> None:
        self.calls += 1


class AcceptExecutable:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def verify(self, binding: ToolBinding) -> None:
        self.seen.append(binding.tool_id)


class FakeTransport:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], int, int]] = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def response(payload, *, status=200, headers=None) -> HttpResponse:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return HttpResponse(
        status=status,
        headers=headers or {"Content-Type": "application/json", "ETag": '"abc"'},
        body=body,
    )


def toolchain() -> Toolchain:
    return Toolchain(
        (
            ToolBinding("python", "/trusted/python3", "1" * 64),
            ToolBinding("go", "/trusted/go", "2" * 64),
        )
    )


def attestation(t: DevelopmentTask, tc: Toolchain) -> IsolationAttestation:
    catalog = modelrig_command_catalog()
    return IsolationAttestation(
        task_id=t.task_id,
        task_sha256=hashlib.sha256(t.canonical_json().encode()).hexdigest(),
        repository=t.repository,
        base_sha=t.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=tc.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(HASH,),
    )


class CatalogTests(unittest.TestCase):
    def test_catalog_is_deterministic_and_versioned(self):
        first = modelrig_command_catalog()
        second = modelrig_command_catalog()
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(len(first.sha256), 64)
        self.assertEqual(
            first.command_ids,
            (
                "modelrig.backend.tests",
                "modelrig.backend.vet",
                "modelrig.devcontrol.tests",
                "modelrig.version.check",
                "modelrig.workflow.test-coverage",
            ),
        )

    def test_unknown_task_command_is_rejected(self):
        t = task("modelrig.not-real")
        tc = toolchain()
        materializer = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=AcceptIsolation(),
            executable_verifier=AcceptExecutable(),
        )
        with self.assertRaises(CatalogError):
            materializer.materialize(t, tc, attestation(t, tc))

    def test_default_isolation_verifier_is_fail_closed(self):
        t = task()
        tc = toolchain()
        with self.assertRaisesRegex(CatalogError, "not been independently verified"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, attestation(t, tc))

    def test_attestation_must_bind_exact_task(self):
        t = task()
        tc = toolchain()
        proof = attestation(t, tc)
        tampered = IsolationAttestation.from_mapping(
            {**proof.to_dict(), "base_sha": "d" * 40}
        )
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, tampered)

    def test_missing_tool_binding_is_rejected(self):
        t = task("modelrig.backend.tests")
        tc = Toolchain((ToolBinding("python", "/trusted/python3", "1" * 64),))
        with self.assertRaisesRegex(CatalogError, "required tool"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, attestation(t, tc))

    def test_materialized_registry_contains_only_task_grants(self):
        t = task("modelrig.devcontrol.tests", "modelrig.version.check")
        tc = toolchain()
        isolation = AcceptIsolation()
        executables = AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=isolation,
            executable_verifier=executables,
        ).materialize(t, tc, attestation(t, tc))
        command = registry.resolve(t, "modelrig.devcontrol.tests")
        self.assertEqual(command.argv[0], "/trusted/python3")
        self.assertEqual(command.argv[1:4], ("-m", "unittest", "discover"))
        self.assertEqual(command.env["MODELRIG_DEVCONTROL"], "1")
        self.assertEqual(isolation.calls, 1)
        self.assertEqual(executables.seen, ["python"])
        with self.assertRaises(Exception):
            registry.resolve(t, "modelrig.backend.tests")

    def test_local_executable_hash_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python"
            path.write_bytes(b"trusted executable")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            LocalExecutableHashVerifier().verify(
                ToolBinding("python", str(path.resolve()), digest)
            )
            with self.assertRaisesRegex(CatalogError, "hash mismatch"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("python", str(path.resolve()), "0" * 64)
                )

    def test_catalog_objects_reject_mutable_or_boolean_authority(self):
        from kaliv_dev_control.catalog import ProjectCommandSpec

        with self.assertRaises(CatalogError):
            ProjectCommandSpec("modelrig.demo", "python", ["-V"], ".", 10)
        with self.assertRaises(CatalogError):
            ProjectCommandSpec("modelrig.demo", "python", ("-V",), ".", True)

    def test_attestation_reload_is_strict(self):
        t = task()
        tc = toolchain()
        proof = attestation(t, tc)
        self.assertEqual(
            IsolationAttestation.from_mapping(proof.to_dict()).canonical_json(),
            proof.canonical_json(),
        )
        with self.assertRaises(CatalogError):
            IsolationAttestation.from_mapping({**proof.to_dict(), "extra": True})


class GitHubReadTests(unittest.TestCase):
    def test_boolean_http_bounds_are_rejected(self):
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), transport=FakeTransport(), timeout_seconds=True)
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), transport=FakeTransport()).read_bytes(
                "devcontrol/readme.txt", max_bytes=True
            )

    def test_verify_base_commit_is_exact_sha_get(self):
        transport = FakeTransport(response({"sha": BASE_SHA}))
        receipt = GitHubReadAdapter(task(), transport=transport).verify_base_commit()
        url, headers, timeout, max_bytes = transport.calls[0]
        self.assertEqual(
            url,
            f"https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}",
        )
        self.assertNotIn("Authorization", headers)
        self.assertEqual(timeout, 30)
        self.assertEqual(max_bytes, 1000000)
        self.assertEqual(receipt.operation, "verify_base_commit")
        self.assertEqual(receipt.subject_sha, BASE_SHA)

    def test_commit_mismatch_is_rejected(self):
        transport = FakeTransport(response({"sha": "d" * 40}))
        with self.assertRaisesRegex(GitHubReadError, "does not match"):
            GitHubReadAdapter(task(), transport=transport).verify_base_commit()

    def test_read_text_is_scoped_and_bound_to_base_sha(self):
        payload = {
            "type": "file",
            "path": "devcontrol/src/demo.py",
            "sha": BLOB_SHA,
            "encoding": "base64",
            "content": base64.b64encode(b"print('ok')\n").decode()[:8]
            + "\n"
            + base64.b64encode(b"print('ok')\n").decode()[8:],
            "size": 12,
        }
        transport = FakeTransport(response(payload))
        text, receipt = GitHubReadAdapter(
            task(), transport=transport, token="secret-token"
        ).read_text("devcontrol/src/demo.py")
        self.assertEqual(text, "print('ok')\n")
        url, headers, _, _ = transport.calls[0]
        self.assertIn("ref=" + BASE_SHA, url)
        self.assertIn("/contents/devcontrol/src/demo.py", url)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertNotIn("secret-token", receipt.canonical_json())
        self.assertEqual(receipt.subject_sha, BLOB_SHA)
        receipt.verify_task(task())

    def test_receipt_task_rebinding_rejects_another_task(self):
        original = task()
        receipt = GitHubReadAdapter(
            original, transport=FakeTransport(response({"sha": BASE_SHA}))
        ).verify_base_commit()
        other = DevelopmentTask.from_mapping(
            {**original.to_dict(), "task_id": "OTHER_TASK"}
        )
        with self.assertRaisesRegex(GitHubReadError, "exact task"):
            receipt.verify_task(other)

    def test_protected_path_is_denied_before_network(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(GitHubReadError, "outside readable"):
            GitHubReadAdapter(task(), transport=transport).read_text(
                "devcontrol/secrets/token.txt"
            )
        self.assertEqual(transport.calls, [])

    def test_git_metadata_is_denied_before_network(self):
        transport = FakeTransport()
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), transport=transport).read_text(".git/config")
        self.assertEqual(transport.calls, [])

    def test_binary_text_is_rejected(self):
        data = b"a\x00b"
        payload = {
            "type": "file",
            "path": "devcontrol/blob.bin",
            "sha": BLOB_SHA,
            "encoding": "base64",
            "content": base64.b64encode(data).decode(),
            "size": len(data),
        }
        with self.assertRaisesRegex(GitHubReadError, "binary"):
            GitHubReadAdapter(task(), transport=FakeTransport(response(payload))).read_text(
                "devcontrol/blob.bin"
            )

    def test_redirect_is_rejected(self):
        redirected = response(
            {"sha": BASE_SHA},
            headers={"Content-Type": "application/json", "Location": "https://example.org"},
        )
        with self.assertRaisesRegex(GitHubReadError, "redirect"):
            GitHubReadAdapter(task(), transport=FakeTransport(redirected)).verify_base_commit()

    def test_non_json_is_rejected(self):
        bad = HttpResponse(200, {"Content-Type": "text/html"}, b"<html></html>")
        with self.assertRaisesRegex(GitHubReadError, "not JSON"):
            GitHubReadAdapter(task(), transport=FakeTransport(bad)).verify_base_commit()

    def test_file_size_mismatch_is_rejected(self):
        payload = {
            "type": "file",
            "path": "devcontrol/readme.txt",
            "sha": BLOB_SHA,
            "encoding": "base64",
            "content": base64.b64encode(b"hello").decode(),
            "size": 99,
        }
        with self.assertRaisesRegex(GitHubReadError, "size does not match"):
            GitHubReadAdapter(task(), transport=FakeTransport(response(payload))).read_bytes(
                "devcontrol/readme.txt"
            )

    def test_receipt_reload_rejects_tampering(self):
        receipt = GitHubReadAdapter(
            task(), transport=FakeTransport(response({"sha": BASE_SHA}))
        ).verify_base_commit()
        self.assertEqual(
            GitHubReadReceipt.from_mapping(receipt.to_dict()).canonical_json(),
            receipt.canonical_json(),
        )
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), "status": 201})
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), "extra": True})


if __name__ == "__main__":
    unittest.main()
