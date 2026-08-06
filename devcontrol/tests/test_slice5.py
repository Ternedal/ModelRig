from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from kaliv_dev_control.catalog import (
    CatalogError,
    CatalogMaterializer,
    IsolationAttestation,
    IsolationBoundary,
    LocalExecutableHashVerifier,
    NetworkMode,
    ProjectCommandSpec,
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
    UrllibReadOnlyTransport,
)

BASE_SHA = "a" * 40
HASH = "c" * 64


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data,
        usedforsecurity=False,
    ).hexdigest()


def task(*commands: str) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A5_SLICE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Validate the isolated catalog and GitHub read boundary.",
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
                "max_output_bytes": 1_000_000,
            },
            "merge_authority": "human",
        }
    )


class AcceptIsolation:
    def verify(self, attestation: IsolationAttestation) -> None:
        self.attestation = attestation


class AcceptExecutable:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def verify(self, binding: ToolBinding) -> str:
        self.seen.append(binding.tool_id)
        return binding.executable


class FakeTransport:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], int, int]] = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def response(payload, *, status=200, headers=None) -> HttpResponse:
    return HttpResponse(
        status=status,
        headers=headers
        or {"Content-Type": "application/json", "ETag": '"abc"'},
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def file_payload(path: str, data: bytes, *, blob_sha: str | None = None, size=None):
    return {
        "type": "file",
        "path": path,
        "sha": blob_sha or git_blob_sha(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
        "size": len(data) if size is None else size,
    }


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
    def test_catalog_is_deterministic_and_test_command_needs_no_pythonpath(self):
        catalog = modelrig_command_catalog()
        self.assertEqual(catalog.sha256, modelrig_command_catalog().sha256)
        spec = catalog.resolve("modelrig.devcontrol.tests")
        self.assertEqual(spec.cwd, "devcontrol/src")
        self.assertIn("../tests", spec.args)
        self.assertNotIn("PYTHONPATH", spec.env)

    def test_catalog_environment_rejects_loader_python_and_git_authority(self):
        for key in (
            "LD_PRELOAD",
            "LD_AUDIT",
            "DYLD_INSERT_LIBRARIES",
            "PYTHONPATH",
            "PYTHONHOME",
            "GIT_CONFIG_GLOBAL",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                CatalogError, "isolation"
            ):
                ProjectCommandSpec(
                    "modelrig.demo", "python", ("-V",), ".", 10, {key: "x"}
                )

    def test_default_isolation_is_fail_closed_and_attestation_is_exact(self):
        t = task()
        tc = toolchain()
        proof = attestation(t, tc)
        with self.assertRaisesRegex(CatalogError, "not been independently verified"):
            CatalogMaterializer(
                modelrig_command_catalog(), executable_verifier=AcceptExecutable()
            ).materialize(t, tc, proof)
        tampered = IsolationAttestation.from_mapping(
            {**proof.to_dict(), "base_sha": "d" * 40}
        )
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, tampered)

    def test_materialization_contains_only_task_grants_and_pinned_path(self):
        t = task("modelrig.devcontrol.tests", "modelrig.version.check")
        tc = toolchain()
        verifier = AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=AcceptIsolation(),
            executable_verifier=verifier,
        ).materialize(t, tc, attestation(t, tc))
        command = registry.resolve(t, "modelrig.devcontrol.tests")
        self.assertEqual(command.argv[0], "/trusted/python3")
        self.assertEqual(verifier.seen, ["python"])
        self.assertIs(getattr(registry, "_catalog_executable_verifier"), verifier)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only pinning")
    def test_sealed_executable_object_is_launched_after_source_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "python"
            shutil.copy2(Path(sys.executable).resolve(), source)
            source.chmod(0o500)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            verifier = LocalExecutableHashVerifier()
            pinned = verifier.verify(
                ToolBinding("python", str(source.resolve()), digest)
            )
            replacement = source.with_name("replacement")
            replacement.write_bytes(b"not the verified executable")
            replacement.chmod(0o500)
            os.replace(replacement, source)
            result = subprocess.run(
                [pinned, "-c", "print('pinned-object')"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "pinned-object")
            with self.assertRaises(OSError):
                Path(pinned).write_bytes(b"tampered")

    @unittest.skipIf(os.name == "nt", "Windows verifier fails closed")
    def test_linked_executable_and_hash_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / "tool").resolve()
            path.write_bytes(b"trusted")
            path.chmod(0o500)
            alias = path.parent / "alias"
            alias.symlink_to(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(CatalogError, "linked|safely"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("python", str(alias), digest)
                )
            with self.assertRaisesRegex(CatalogError, "hash mismatch"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("python", str(path), "0" * 64)
                )

    def test_attestation_reload_is_strict(self):
        proof = attestation(task(), toolchain())
        self.assertEqual(
            IsolationAttestation.from_mapping(proof.to_dict()).canonical_json(),
            proof.canonical_json(),
        )
        with self.assertRaises(CatalogError):
            IsolationAttestation.from_mapping({**proof.to_dict(), "task_id": "bad"})


class GitHubReadTests(unittest.TestCase):
    def test_verify_base_commit_is_fixed_exact_sha_get(self):
        transport = FakeTransport(response({"sha": BASE_SHA}))
        receipt = GitHubReadAdapter(task(), transport=transport).verify_base_commit()
        url, headers, timeout, maximum = transport.calls[0]
        self.assertEqual(
            url,
            f"https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}",
        )
        self.assertNotIn("Authorization", headers)
        self.assertEqual((timeout, maximum), (30, 1_000_000))
        self.assertEqual(receipt.subject_sha, BASE_SHA)

    def test_read_bytes_is_scoped_blob_verified_and_token_free(self):
        data = b"print('ok')\n"
        transport = FakeTransport(
            response(file_payload("devcontrol/src/demo.py", data))
        )
        observed, receipt = GitHubReadAdapter(
            task(), transport=transport, token="secret-token"
        ).read_bytes("devcontrol/src/demo.py")
        self.assertEqual(observed, data)
        self.assertIn("ref=" + BASE_SHA, transport.calls[0][0])
        self.assertNotIn("secret-token", receipt.canonical_json())
        receipt.verify_task(task())

    def test_blob_sha_and_size_mismatches_are_rejected(self):
        with self.assertRaisesRegex(GitHubReadError, "blob SHA"):
            GitHubReadAdapter(
                task(),
                transport=FakeTransport(
                    response(
                        file_payload(
                            "devcontrol/readme.txt", b"hello", blob_sha="b" * 40
                        )
                    )
                ),
            ).read_bytes("devcontrol/readme.txt")
        with self.assertRaisesRegex(GitHubReadError, "bound|size"):
            GitHubReadAdapter(
                task(),
                transport=FakeTransport(
                    response(file_payload("devcontrol/readme.txt", b"hello", size=99))
                ),
            ).read_bytes("devcontrol/readme.txt", max_bytes=5)

    def test_protected_and_git_paths_fail_before_network(self):
        transport = FakeTransport()
        adapter = GitHubReadAdapter(task(), transport=transport)
        for path in ("devcontrol/secrets/token.txt", ".git/config"):
            with self.assertRaises(GitHubReadError):
                adapter.read_bytes(path)
        self.assertEqual(transport.calls, [])

    def test_redirect_non_json_and_commit_mismatch_are_rejected(self):
        redirect = response(
            {"sha": BASE_SHA},
            headers={
                "Content-Type": "application/json",
                "Location": "https://example.org",
            },
        )
        with self.assertRaisesRegex(GitHubReadError, "redirect"):
            GitHubReadAdapter(task(), transport=FakeTransport(redirect)).verify_base_commit()
        with self.assertRaisesRegex(GitHubReadError, "not JSON"):
            GitHubReadAdapter(
                task(),
                transport=FakeTransport(
                    HttpResponse(200, {"Content-Type": "text/html"}, b"html")
                ),
            ).verify_base_commit()
        with self.assertRaisesRegex(GitHubReadError, "does not match"):
            GitHubReadAdapter(
                task(), transport=FakeTransport(response({"sha": "d" * 40}))
            ).verify_base_commit()

    def test_receipt_reload_types_and_task_binding_are_strict(self):
        receipt = GitHubReadAdapter(
            task(), transport=FakeTransport(response({"sha": BASE_SHA}))
        ).verify_base_commit()
        self.assertEqual(
            GitHubReadReceipt.from_mapping(receipt.to_dict()).canonical_json(),
            receipt.canonical_json(),
        )
        for change in (
            {"task_id": 1},
            {"repository": 1},
            {"status": 201},
            {"status": 200.0},
        ):
            with self.subTest(change=change), self.assertRaises(GitHubReadError):
                GitHubReadReceipt.from_mapping({**receipt.to_dict(), **change})
        other = DevelopmentTask.from_mapping({**task().to_dict(), "task_id": "OTHER"})
        with self.assertRaisesRegex(GitHubReadError, "exact task"):
            receipt.verify_task(other)

    def test_default_transport_disables_proxy_inheritance_and_host_escape(self):
        with patch("kaliv_dev_control.github_read.urllib.request.build_opener") as builder:
            builder.return_value = object()
            UrllibReadOnlyTransport()
        handlers = builder.call_args.args
        proxy = next(item for item in handlers if isinstance(item, urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        transport = UrllibReadOnlyTransport()
        with patch.object(transport._opener, "open") as opener:
            with self.assertRaisesRegex(GitHubReadError, "fixed GitHub"):
                transport.get(
                    "https://example.org/repos/Ternedal/ModelRig",
                    headers={},
                    timeout_seconds=1,
                    max_bytes=100,
                )
            opener.assert_not_called()


class SchemaTests(unittest.TestCase):
    def test_schemas_match_the_landed_task_identity(self):
        root = Path(__file__).resolve().parents[1] / "schemas"
        for name in (
            "development-github-read-receipt-v1.schema.json",
            "development-isolation-attestation-v1.schema.json",
        ):
            schema = json.loads((root / name).read_text(encoding="utf-8"))
            self.assertEqual(
                schema["properties"]["task_id"]["pattern"],
                "^[A-Z][A-Z0-9_-]{2,63}$",
            )


if __name__ == "__main__":
    unittest.main()
