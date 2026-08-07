from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kaliv_dev_control.catalog import (
    CatalogError,
    CatalogMaterializer,
    IsolationAttestation,
    IsolationBoundary,
    LocalExecutableHashVerifier,
    ModelRigCommandCatalog,
    NetworkMode,
    ProjectCommandSpec,
    ToolBinding,
    Toolchain,
    modelrig_command_catalog,
)
from kaliv_dev_control.commands import CommandExecutor, CommandPolicyError
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
FIXED_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "LC_CTYPE": "C",
    "TZ": "UTC",
}


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data,
        usedforsecurity=False,
    ).hexdigest()


def elf64(*segment_types: int) -> bytes:
    if not segment_types:
        segment_types = (1,)
    ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
    header = ident + struct.pack(
        "<HHIQQQIHHHHHH",
        2,
        62,
        1,
        0,
        64,
        0,
        0,
        64,
        56,
        len(segment_types),
        0,
        0,
        0,
    )
    programs = b"".join(
        struct.pack("<IIQQQQQQ", kind, 5, 0, 0, 0, 0, 0, 0)
        for kind in segment_types
    )
    return header + programs


def write_executable(root: Path, name: str, data: bytes) -> tuple[Path, str]:
    path = root / name
    path.write_bytes(data)
    path.chmod(0o500)
    return path.resolve(), hashlib.sha256(data).hexdigest()


def task(*commands: str, allowed_paths: tuple[str, ...] = ("devcontrol/**",)) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A5_SLICE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Validate the dormant catalog and GitHub read boundary.",
            "acceptance_criteria": ["All fixed-authority tests pass."],
            "risk": "low",
            "allowed_paths": list(allowed_paths),
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": list(commands),
            "required_tests": ["DC-L03 fixed-authority regressions"],
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


def static_catalog() -> ModelRigCommandCatalog:
    return ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                "modelrig.static.probe",
                "statictool",
                ("probe",),
                ".",
                30,
                {"CI": "1"},
            ),
        )
    )


def attestation(
    t: DevelopmentTask,
    tc: Toolchain,
    catalog: ModelRigCommandCatalog,
) -> IsolationAttestation:
    return IsolationAttestation(
        task_id=t.task_id,
        task_sha256=hashlib.sha256(t.canonical_json().encode("utf-8")).hexdigest(),
        repository=t.repository,
        base_sha=t.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=tc.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(HASH,),
    )


class AcceptIsolation:
    def verify(self, proof: IsolationAttestation) -> None:
        self.proof = proof


class MutateAttestationIsolation:
    def verify(self, proof: IsolationAttestation) -> None:
        object.__setattr__(proof, "base_sha", "b" * 40)


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], int, int]] = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def json_response(payload: object, **headers: str) -> HttpResponse:
    values = {"Content-Type": "application/json", **headers}
    return HttpResponse(
        status=200,
        headers=values,
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


class CatalogRuntimeTests(unittest.TestCase):
    def test_default_catalog_is_empty_and_removed_ids_are_absent(self):
        catalog = modelrig_command_catalog()
        self.assertEqual(catalog.command_ids, ())
        for command_id in (
            "modelrig.version.check",
            "modelrig.devcontrol.tests",
            "modelrig.workflow.test-coverage",
            "modelrig.backend.vet",
            "modelrig.backend.tests",
        ):
            with self.assertRaisesRegex(CatalogError, "not in the ModelRig catalog"):
                catalog.resolve(command_id)

    def test_python_go_and_sandbox_command_specs_fail_closed(self):
        cases = (
            ("python", "self-contained runtime"),
            ("go", "helper toolchain"),
            ("sandbox", "cannot be used"),
        )
        for tool_id, message in cases:
            with self.subTest(tool_id=tool_id):
                with self.assertRaisesRegex(CatalogError, message):
                    ProjectCommandSpec(
                        "modelrig.runtime.probe",
                        tool_id,
                        ("probe",),
                        ".",
                        10,
                        {},
                    )

    def test_custom_static_spec_gets_only_reviewed_fixed_environment(self):
        spec = ProjectCommandSpec(
            "modelrig.static.probe",
            "statictool",
            ("probe",),
            ".",
            10,
            {"CI": "1"},
        )
        self.assertEqual(dict(spec.env), {"CI": "1", **FIXED_ENV})
        for key, value in (
            ("PATH", "/attacker"),
            ("PYTHONPATH", "."),
            ("LD_PRELOAD", "/tmp/x.so"),
            ("GIT_CONFIG_GLOBAL", "/tmp/config"),
            ("TZ", "Europe/Copenhagen"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(CatalogError, "positive list"):
                    ProjectCommandSpec(
                        "modelrig.static.probe",
                        "statictool",
                        ("probe",),
                        ".",
                        10,
                        {key: value},
                    )

    def test_empty_catalog_materializes_without_launch_authority(self):
        catalog = modelrig_command_catalog()
        t = task()
        tc = Toolchain(())
        registry = CatalogMaterializer(
            catalog,
            isolation_verifier=AcceptIsolation(),
        ).materialize(t, tc, attestation(t, tc, catalog))
        with self.assertRaisesRegex(CommandPolicyError, "not registered"):
            registry.resolve(t, "modelrig.version.check")
        with self.assertRaisesRegex(CommandPolicyError, "no launch authority"):
            registry.sandbox_bootstrap_executable(t)

    def test_default_isolation_and_exact_authority_fail_closed(self):
        catalog = modelrig_command_catalog()
        t = task()
        tc = Toolchain(())
        proof = attestation(t, tc, catalog)
        with self.assertRaisesRegex(CatalogError, "not been independently verified"):
            CatalogMaterializer(catalog).materialize(t, tc, proof)
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            CatalogMaterializer(
                catalog,
                isolation_verifier=AcceptIsolation(),
            ).materialize(t, tc, replace(proof, base_sha="b" * 40))

    def test_isolation_verifier_cannot_mutate_private_attestation(self):
        catalog = modelrig_command_catalog()
        t = task()
        tc = Toolchain(())
        with self.assertRaisesRegex(CatalogError, "mutated"):
            CatalogMaterializer(
                catalog,
                isolation_verifier=MutateAttestationIsolation(),
            ).materialize(t, tc, attestation(t, tc, catalog))

    def test_fake_executable_verifier_is_rejected(self):
        with self.assertRaisesRegex(CatalogError, "fixed static-runtime"):
            CatalogMaterializer(
                static_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=SimpleNamespace(verify=lambda binding: binding.executable),
            )

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and hasattr(os, "memfd_create")
        and hasattr(os, "pread"),
        "Linux-only sealed ELF verification",
    )
    def test_static_catalog_materializes_through_sealed_static_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sandbox, sandbox_hash = write_executable(root, "sandbox", elf64(1))
            tool, tool_hash = write_executable(root, "tool", elf64(1))
            catalog = static_catalog()
            t = task("modelrig.static.probe")
            tc = Toolchain(
                (
                    ToolBinding("sandbox", str(sandbox), sandbox_hash),
                    ToolBinding("statictool", str(tool), tool_hash),
                )
            )
            registry = CatalogMaterializer(
                catalog,
                isolation_verifier=AcceptIsolation(),
            ).materialize(t, tc, attestation(t, tc, catalog))
            template = registry.resolve(t, "modelrig.static.probe")
            self.assertTrue(template.argv[0].startswith(f"/proc/{os.getpid()}/fd/"))
            self.assertEqual(template.argv[1:], ("probe",))
            bootstrap = registry.sandbox_bootstrap_executable(t)
            self.assertTrue(bootstrap.startswith(f"/proc/{os.getpid()}/fd/"))
            self.assertEqual(registry.sandbox_bootstrap_mode(t), "static")
            confined = CommandExecutor._confined_argv(
                Path("/sandbox"),
                Path("/sandbox/repository"),
                template.argv,
                bootstrap,
                "static",
            )
            self.assertEqual(confined[:3], (bootstrap, "/sandbox", "/sandbox/repository"))
            self.assertEqual(confined[3:], template.argv)

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and hasattr(os, "memfd_create")
        and hasattr(os, "pread"),
        "Linux-only sealed ELF verification",
    )
    def test_dynamic_runtime_is_rejected_for_sandbox_and_normal_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool_id in ("sandbox", "statictool"):
                for segment in (2, 3):
                    with self.subTest(tool_id=tool_id, segment=segment):
                        path, digest = write_executable(
                            root,
                            f"{tool_id}-{segment}",
                            elf64(1, segment),
                        )
                        with self.assertRaisesRegex(CatalogError, "dynamic runtime"):
                            LocalExecutableHashVerifier().verify(
                                ToolBinding(tool_id, str(path), digest)
                            )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only verifier")
    def test_symlink_fifo_and_hash_mismatch_fail_closed(self):
        if not hasattr(os, "memfd_create") or not hasattr(os, "pread"):
            self.skipTest("sealed ELF verification unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, digest = write_executable(root, "tool", elf64(1))
            link = root / "link"
            link.symlink_to(path)
            with self.assertRaisesRegex(CatalogError, "linked or non-canonical"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("statictool", str(link.absolute()), digest)
                )
            with self.assertRaisesRegex(CatalogError, "hash mismatch"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("statictool", str(path), "0" * 64)
                )
            fifo = root / "fifo"
            os.mkfifo(fifo, 0o500)
            with self.assertRaisesRegex(CatalogError, "regular executable"):
                LocalExecutableHashVerifier().verify(
                    ToolBinding("statictool", str(fifo.resolve()), "0" * 64)
                )

    def test_removed_python_command_cannot_materialize(self):
        t = task("modelrig.devcontrol.tests")
        catalog = modelrig_command_catalog()
        tc = Toolchain(())
        with self.assertRaisesRegex(CatalogError, "not in the ModelRig catalog"):
            CatalogMaterializer(
                catalog,
                isolation_verifier=AcceptIsolation(),
            ).materialize(t, tc, attestation(t, tc, catalog))


class GitHubReadTests(unittest.TestCase):
    def test_fixed_get_authority_and_exact_base_receipt(self):
        t = task(allowed_paths=("devcontrol/**",))
        transport = RecordingTransport(
            [json_response({"sha": BASE_SHA}, ETag='"commit"')]
        )
        adapter = GitHubReadAdapter(t, transport=transport, token="secret", timeout_seconds=7)
        receipt = adapter.verify_base_commit()
        self.assertEqual(receipt.subject_sha, BASE_SHA)
        self.assertEqual(receipt.operation, "verify_base_commit")
        self.assertEqual(len(transport.calls), 1)
        url, headers, timeout, maximum = transport.calls[0]
        self.assertEqual(
            url,
            f"https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}",
        )
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(timeout, 7)
        self.assertLessEqual(maximum, t.budget.max_output_bytes)
        self.assertNotIn("secret", receipt.canonical_json())

    def test_scoped_read_verifies_file_size_and_git_blob_identity(self):
        data = b"hello\n"
        payload = {
            "type": "file",
            "path": "devcontrol/README.md",
            "sha": git_blob_sha(data),
            "encoding": "base64",
            "size": len(data),
            "content": base64.b64encode(data).decode("ascii"),
        }
        transport = RecordingTransport([json_response(payload, ETag='"file"')])
        adapter = GitHubReadAdapter(task(), transport=transport)
        observed, receipt = adapter.read_bytes("devcontrol/README.md", max_bytes=100)
        self.assertEqual(observed, data)
        self.assertEqual(receipt.path, "devcontrol/README.md")
        self.assertIn("ref=" + BASE_SHA, transport.calls[0][0])

    def test_protected_and_git_paths_fail_before_network(self):
        transport = RecordingTransport([])
        adapter = GitHubReadAdapter(task(), transport=transport)
        for path in ("devcontrol/secrets/token", ".git/config", "README.md"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(GitHubReadError, "outside readable"):
                    adapter.read_bytes(path)
        self.assertEqual(transport.calls, [])

    def test_blob_mismatch_size_mismatch_redirect_and_status_fail_closed(self):
        data = b"hello"
        payload = {
            "type": "file",
            "path": "devcontrol/x.txt",
            "sha": "b" * 40,
            "encoding": "base64",
            "size": len(data),
            "content": base64.b64encode(data).decode("ascii"),
        }
        adapter = GitHubReadAdapter(task(), transport=RecordingTransport([json_response(payload)]))
        with self.assertRaisesRegex(GitHubReadError, "blob SHA"):
            adapter.read_bytes("devcontrol/x.txt")

        payload["sha"] = git_blob_sha(data)
        payload["size"] = len(data) + 1
        adapter = GitHubReadAdapter(task(), transport=RecordingTransport([json_response(payload)]))
        with self.assertRaisesRegex(GitHubReadError, "size does not match"):
            adapter.read_bytes("devcontrol/x.txt")

        adapter = GitHubReadAdapter(
            task(),
            transport=RecordingTransport(
                [HttpResponse(200, {"Content-Type": "application/json", "Location": "https://evil"}, b"{}")]
            ),
        )
        with self.assertRaisesRegex(GitHubReadError, "redirects"):
            adapter.verify_base_commit()

        adapter = GitHubReadAdapter(
            task(),
            transport=RecordingTransport(
                [HttpResponse(404, {"Content-Type": "application/json"}, b"{}")]
            ),
        )
        with self.assertRaisesRegex(GitHubReadError, "status 404"):
            adapter.verify_base_commit()

    def test_receipt_reload_is_strict_and_task_bound(self):
        t = task()
        body = json.dumps({"sha": BASE_SHA}, separators=(",", ":")).encode()
        receipt = GitHubReadReceipt(
            task_id=t.task_id,
            task_sha256=hashlib.sha256(t.canonical_json().encode()).hexdigest(),
            repository=t.repository,
            base_sha=t.base_sha,
            operation="verify_base_commit",
            path="",
            subject_sha=t.base_sha,
            status=200,
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            etag_sha256=hashlib.sha256(b"").hexdigest(),
        )
        receipt.verify_task(t)
        restored = GitHubReadReceipt.from_mapping(receipt.to_dict())
        self.assertEqual(restored, receipt)
        for field, value in (
            ("task_id", 1),
            ("repository", ["Ternedal", "ModelRig"]),
            ("status", 200.0),
            ("response_bytes", True),
        ):
            malformed = receipt.to_dict()
            malformed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(GitHubReadError):
                    GitHubReadReceipt.from_mapping(malformed)
        with self.assertRaisesRegex(GitHubReadError, "exact task"):
            receipt.verify_task(replace(t, base_sha="b" * 40))

    def test_adapter_snapshot_is_immutable(self):
        original = task()
        adapter = GitHubReadAdapter(original, transport=RecordingTransport([]))
        object.__setattr__(original, "base_sha", "b" * 40)
        self.assertEqual(adapter.task.base_sha, BASE_SHA)
        with self.assertRaisesRegex(GitHubReadError, "immutable"):
            adapter.timeout_seconds = 1

    def test_transport_rejects_host_escape_and_disables_proxy_redirect_handlers(self):
        with patch("kaliv_dev_control.github_read._system_tls_context", return_value=SimpleNamespace()):
            with patch("urllib.request.build_opener") as opener:
                transport = UrllibReadOnlyTransport()
        handlers = opener.call_args.args
        self.assertTrue(any(isinstance(item, urllib.request.ProxyHandler) for item in handlers))
        proxy = next(item for item in handlers if isinstance(item, urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        with self.assertRaisesRegex(GitHubReadError, "fixed GitHub API host"):
            transport.get(
                "https://evil.example/repos/x/y",
                headers={},
                timeout_seconds=1,
                max_bytes=10,
            )


if __name__ == "__main__":
    unittest.main()
