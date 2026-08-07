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
    segment_types = segment_types or (1,)
    ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
    header = ident + struct.pack(
        "<HHIQQQIHHHHHH", 2, 62, 1, 0, 64, 0, 0, 64, 56,
        len(segment_types), 0, 0, 0,
    )
    return header + b"".join(
        struct.pack("<IIQQQQQQ", kind, 5, 0, 0, 0, 0, 0, 0)
        for kind in segment_types
    )


def write_executable(root: Path, name: str, data: bytes) -> tuple[Path, str]:
    path = root / name
    path.write_bytes(data)
    path.chmod(0o500)
    return path.resolve(), hashlib.sha256(data).hexdigest()


def task(
    *commands: str,
    allowed_paths: tuple[str, ...] = ("devcontrol/**",),
) -> DevelopmentTask:
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


def static_toolchain() -> Toolchain:
    return Toolchain(
        (
            ToolBinding("sandbox", "/trusted/sandbox", "1" * 64),
            ToolBinding("statictool", "/trusted/tool", "2" * 64),
        )
    )


def attestation(
    value: DevelopmentTask,
    toolchain: Toolchain,
    catalog: ModelRigCommandCatalog,
) -> IsolationAttestation:
    return IsolationAttestation(
        task_id=value.task_id,
        task_sha256=hashlib.sha256(value.canonical_json().encode()).hexdigest(),
        repository=value.repository,
        base_sha=value.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(HASH,),
    )


class AcceptIsolation:
    def __init__(self) -> None:
        self.called = False

    def verify(self, proof: IsolationAttestation) -> None:
        self.called = True
        self.proof = proof


class MutateIsolation:
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
    return HttpResponse(
        status=200,
        headers={"Content-Type": "application/json", **headers},
        body=json.dumps(payload, separators=(",", ":")).encode(),
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

    def test_python_go_and_sandbox_specs_fail_closed(self):
        for tool_id, message in (
            ("python", "self-contained runtime"),
            ("go", "helper toolchain"),
            ("sandbox", "cannot be used"),
        ):
            with self.subTest(tool_id=tool_id):
                with self.assertRaisesRegex(CatalogError, message):
                    ProjectCommandSpec(
                        "modelrig.runtime.probe", tool_id, ("probe",), ".", 10, {}
                    )

    def test_custom_static_spec_has_only_fixed_environment(self):
        spec = ProjectCommandSpec(
            "modelrig.static.probe", "statictool", ("probe",), ".", 10, {"CI": "1"}
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
                        "modelrig.static.probe", "statictool", ("probe",), ".", 10,
                        {key: value},
                    )

    def test_empty_default_catalog_rejects_unknown_command_before_callback(self):
        catalog = modelrig_command_catalog()
        value = task("modelrig.devcontrol.tests")
        tools = Toolchain(())
        isolation = AcceptIsolation()
        with self.assertRaisesRegex(CatalogError, "not in the ModelRig catalog"):
            CatalogMaterializer(
                catalog, isolation_verifier=isolation
            ).materialize(value, tools, attestation(value, tools, catalog))
        self.assertFalse(isolation.called)

    def test_empty_catalog_materializes_only_an_immutable_empty_registry(self):
        catalog = modelrig_command_catalog()
        value = task()
        tools = Toolchain(())
        isolation = AcceptIsolation()
        registry = CatalogMaterializer(
            catalog, isolation_verifier=isolation
        ).materialize(value, tools, attestation(value, tools, catalog))
        self.assertTrue(isolation.called)
        execution_task = registry.execution_task(value)
        self.assertIsNot(execution_task, value)
        self.assertEqual(execution_task.canonical_json(), value.canonical_json())
        with self.assertRaisesRegex(Exception, "no launch authority"):
            registry.sandbox_bootstrap_executable(execution_task)
        with self.assertRaisesRegex(Exception, "not allowed"):
            registry.resolve(execution_task, "modelrig.static.probe")
        with self.assertRaises(Exception):
            registry._bootstrap_executable = "/attacker"

    def test_default_isolation_and_exact_authority_fail_closed_for_empty_catalog(self):
        catalog, value, tools = modelrig_command_catalog(), task(), Toolchain(())
        proof = attestation(value, tools, catalog)
        with self.assertRaisesRegex(CatalogError, "not been independently verified"):
            CatalogMaterializer(catalog).materialize(value, tools, proof)
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            CatalogMaterializer(
                catalog, isolation_verifier=AcceptIsolation()
            ).materialize(value, tools, replace(proof, base_sha="b" * 40))

    def test_isolation_verifier_cannot_mutate_private_attestation(self):
        catalog, value, tools = modelrig_command_catalog(), task(), Toolchain(())
        with self.assertRaisesRegex(CatalogError, "mutated"):
            CatalogMaterializer(
                catalog, isolation_verifier=MutateIsolation()
            ).materialize(value, tools, attestation(value, tools, catalog))

    def test_fake_executable_verifier_is_rejected(self):
        with self.assertRaisesRegex(CatalogError, "fixed static-runtime"):
            CatalogMaterializer(
                static_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=SimpleNamespace(
                    verify=lambda binding: binding.executable
                ),
            )

    def test_nonempty_catalog_is_rejected_before_callback_or_verifier(self):
        catalog = static_catalog()
        value = task("modelrig.static.probe")
        tools = static_toolchain()
        isolation = AcceptIsolation()
        supplied = LocalExecutableHashVerifier()
        with patch.object(
            LocalExecutableHashVerifier,
            "verify",
            side_effect=AssertionError("executable verifier must not be called"),
        ):
            with self.assertRaisesRegex(CatalogError, "deferred fail closed"):
                CatalogMaterializer(
                    catalog,
                    isolation_verifier=isolation,
                    executable_verifier=supplied,
                ).materialize(value, tools, attestation(value, tools, catalog))
        self.assertFalse(isolation.called)
        self.assertEqual(supplied._pins, {})

    def test_nonempty_catalog_never_invokes_frame_inspecting_callback(self):
        catalog = static_catalog()
        value = task("modelrig.static.probe")
        tools = static_toolchain()

        class FrameInspector:
            called = False

            def verify(self, proof: IsolationAttestation) -> None:
                del proof
                self.called = True
                caller_locals = sys._getframe(1).f_locals
                for candidate in caller_locals.values():
                    if isinstance(candidate, LocalExecutableHashVerifier):
                        candidate._pins["sandbox"] = (
                            ToolBinding("sandbox", "/trusted/sandbox", "1" * 64),
                            -1,
                            "/attacker-controlled/sandbox",
                        )

        isolation = FrameInspector()
        with self.assertRaisesRegex(CatalogError, "deferred fail closed"):
            CatalogMaterializer(
                catalog, isolation_verifier=isolation
            ).materialize(value, tools, attestation(value, tools, catalog))
        self.assertFalse(isolation.called)

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and hasattr(os, "memfd_create")
        and hasattr(os, "pread"),
        "Linux-only sealed ELF verification",
    )
    def test_static_verifier_directly_pins_sealed_static_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sandbox, sandbox_hash = write_executable(root, "sandbox", elf64(1))
            tool, tool_hash = write_executable(root, "tool", elf64(1))
            verifier = LocalExecutableHashVerifier()
            sandbox_invocation = verifier.verify(
                ToolBinding("sandbox", str(sandbox), sandbox_hash)
            )
            tool_invocation = verifier.verify(
                ToolBinding("statictool", str(tool), tool_hash)
            )
            self.assertTrue(sandbox_invocation.startswith(f"/proc/{os.getpid()}/fd/"))
            self.assertTrue(tool_invocation.startswith(f"/proc/{os.getpid()}/fd/"))
            self.assertNotEqual(sandbox_invocation, tool_invocation)

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and hasattr(os, "memfd_create")
        and hasattr(os, "pread"),
        "Linux-only sealed ELF verification",
    )
    def test_dynamic_runtime_is_rejected_for_every_tool_role(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool_id in ("sandbox", "statictool"):
                for segment in (2, 3):
                    with self.subTest(tool_id=tool_id, segment=segment):
                        path, digest = write_executable(
                            root, f"{tool_id}-{segment}", elf64(1, segment)
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


class GitHubReadTests(unittest.TestCase):
    def test_fixed_get_authority_and_exact_base_receipt(self):
        value = task(allowed_paths=("devcontrol/**",))
        transport = RecordingTransport(
            [json_response({"sha": BASE_SHA}, ETag='"commit"')]
        )
        adapter = GitHubReadAdapter(
            value, transport=transport, token="secret", timeout_seconds=7
        )
        receipt = adapter.verify_base_commit()
        self.assertEqual(receipt.subject_sha, BASE_SHA)
        url, headers, timeout, maximum = transport.calls[0]
        self.assertEqual(
            url,
            f"https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}",
        )
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(timeout, 7)
        self.assertLessEqual(maximum, value.budget.max_output_bytes)
        self.assertNotIn("secret", receipt.canonical_json())

    def test_scoped_read_verifies_size_and_git_blob(self):
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
        observed, receipt = GitHubReadAdapter(
            task(), transport=transport
        ).read_bytes("devcontrol/README.md", max_bytes=100)
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

    def test_blob_size_redirect_and_status_fail_closed(self):
        data = b"hello"
        payload = {
            "type": "file",
            "path": "devcontrol/x.txt",
            "sha": "b" * 40,
            "encoding": "base64",
            "size": len(data),
            "content": base64.b64encode(data).decode("ascii"),
        }
        adapter = GitHubReadAdapter(
            task(), transport=RecordingTransport([json_response(payload)])
        )
        with self.assertRaisesRegex(GitHubReadError, "blob SHA"):
            adapter.read_bytes("devcontrol/x.txt")
        payload["sha"], payload["size"] = git_blob_sha(data), len(data) + 1
        adapter = GitHubReadAdapter(
            task(), transport=RecordingTransport([json_response(payload)])
        )
        with self.assertRaisesRegex(GitHubReadError, "size does not match"):
            adapter.read_bytes("devcontrol/x.txt")
        for response, message in (
            (HttpResponse(200, {"Content-Type": "application/json", "Location": "https://evil"}, b"{}"), "redirects"),
            (HttpResponse(404, {"Content-Type": "application/json"}, b"{}"), "status 404"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(GitHubReadError, message):
                    GitHubReadAdapter(
                        task(), transport=RecordingTransport([response])
                    ).verify_base_commit()

    def test_receipt_reload_is_strict_and_task_bound(self):
        value = task()
        body = json.dumps({"sha": BASE_SHA}, separators=(",", ":")).encode()
        receipt = GitHubReadReceipt(
            task_id=value.task_id,
            task_sha256=hashlib.sha256(value.canonical_json().encode()).hexdigest(),
            repository=value.repository,
            base_sha=value.base_sha,
            operation="verify_base_commit",
            path="",
            subject_sha=value.base_sha,
            status=200,
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            etag_sha256=hashlib.sha256(b"").hexdigest(),
        )
        receipt.verify_task(value)
        self.assertEqual(GitHubReadReceipt.from_mapping(receipt.to_dict()), receipt)
        for field, malformed_value in (
            ("task_id", 1),
            ("repository", ["Ternedal", "ModelRig"]),
            ("status", 200.0),
            ("response_bytes", True),
        ):
            malformed = receipt.to_dict()
            malformed[field] = malformed_value
            with self.subTest(field=field):
                with self.assertRaises(GitHubReadError):
                    GitHubReadReceipt.from_mapping(malformed)
        with self.assertRaisesRegex(GitHubReadError, "exact task"):
            receipt.verify_task(replace(value, base_sha="b" * 40))

    def test_adapter_snapshot_is_immutable(self):
        original = task()
        adapter = GitHubReadAdapter(
            original, transport=RecordingTransport([])
        )
        object.__setattr__(original, "base_sha", "b" * 40)
        self.assertEqual(adapter.task.base_sha, BASE_SHA)
        with self.assertRaisesRegex(GitHubReadError, "immutable"):
            adapter.timeout_seconds = 1

    def test_transport_disables_proxy_and_rejects_host_escape(self):
        with patch(
            "kaliv_dev_control.github_read._system_tls_context",
            return_value=SimpleNamespace(),
        ):
            with patch("urllib.request.build_opener") as opener:
                transport = UrllibReadOnlyTransport()
        handlers = opener.call_args.args
        proxy = next(
            item for item in handlers if isinstance(item, urllib.request.ProxyHandler)
        )
        self.assertEqual(proxy.proxies, {})
        with self.assertRaisesRegex(GitHubReadError, "fixed GitHub API host"):
            transport.get(
                "https://evil.example/repos/x/y",
                headers={}, timeout_seconds=1, max_bytes=10,
            )


if __name__ == "__main__":
    unittest.main()
