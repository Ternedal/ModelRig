from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
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
from kaliv_dev_control.workspace import SubprocessRunner

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


def toolchain() -> Toolchain:
    return Toolchain(
        (
            ToolBinding("python", "/trusted/python3", "1" * 64),
            ToolBinding("go", "/trusted/go", "2" * 64),
        )
    )


def attestation(
    t: DevelopmentTask,
    tc: Toolchain,
    *,
    catalog: ModelRigCommandCatalog | None = None,
) -> IsolationAttestation:
    authority = catalog or modelrig_command_catalog()
    return IsolationAttestation(
        task_id=t.task_id,
        task_sha256=hashlib.sha256(t.canonical_json().encode()).hexdigest(),
        repository=t.repository,
        base_sha=t.base_sha,
        catalog_sha256=authority.sha256,
        toolchain_sha256=tc.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(HASH,),
    )


class AcceptIsolation:
    def verify(self, proof: IsolationAttestation) -> None:
        self.proof = proof


class MutateToolchainIsolation:
    def __init__(self, value: Toolchain) -> None:
        self.value = value

    def verify(self, proof: IsolationAttestation) -> None:
        del proof
        replacement = Toolchain(
            (
                ToolBinding("python", "/untrusted/python3", "9" * 64),
                ToolBinding("go", "/untrusted/go", "8" * 64),
            )
        )
        self.value._bindings = replacement._bindings


class MutateBindingIsolation:
    def __init__(self, value: ToolBinding) -> None:
        self.value = value

    def verify(self, proof: IsolationAttestation) -> None:
        del proof
        object.__setattr__(self.value, "executable", "/untrusted/python3")
        object.__setattr__(self.value, "executable_sha256", "9" * 64)


class MutateTaskIsolation:
    def __init__(self, value: DevelopmentTask) -> None:
        self.value = value

    def verify(self, proof: IsolationAttestation) -> None:
        del proof
        object.__setattr__(self.value, "base_sha", "b" * 40)


class MutateAttestationIsolation:
    def verify(self, proof: IsolationAttestation) -> None:
        object.__setattr__(proof, "base_sha", "b" * 40)


class MutateSpecIsolation:
    def __init__(self, value: ProjectCommandSpec) -> None:
        self.value = value

    def verify(self, proof: IsolationAttestation) -> None:
        del proof
        object.__setattr__(
            self.value,
            "args",
            ("-c", "print('unattested-spec')"),
        )


class ReassignCatalog(ModelRigCommandCatalog):
    def __init__(self, specs, replacement: ModelRigCommandCatalog) -> None:
        super().__init__(specs)
        self.replacement = replacement
        self.materializer = None

    def resolve(self, command_id: str) -> ProjectCommandSpec:
        spec = super().resolve(command_id)
        if self.materializer is not None:
            self.materializer.catalog = self.replacement
        return spec


class SwapExecutableVerifierIsolation:
    def __init__(self) -> None:
        self.materializer = None

    def verify(self, proof):
        del proof
        self.materializer.executable_verifier = AcceptExecutable()


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
        headers=headers or {"Content-Type": "application/json", "ETag": '"abc"'},
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


def file_payload(path: str, data: bytes, *, blob_sha=None, size=None):
    return {
        "type": "file",
        "path": path,
        "sha": blob_sha or git_blob_sha(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode(),
        "size": len(data) if size is None else size,
    }


class CatalogTests(unittest.TestCase):
    def test_catalog_is_deterministic_and_test_command_needs_no_pythonpath(self):
        catalog = modelrig_command_catalog()
        self.assertEqual(catalog.sha256, modelrig_command_catalog().sha256)
        spec = catalog.resolve("modelrig.devcontrol.tests")
        self.assertEqual(spec.cwd, "devcontrol/src")
        self.assertIn("../tests", spec.args)
        self.assertNotIn("PYTHONPATH", spec.env)
        self.assertEqual(
            {
                key: spec.env[key]
                for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
            },
            {
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "LC_CTYPE": "C",
                "TZ": "UTC",
            },
        )

    def test_catalog_environment_rejects_authority_variables(self):
        for key in (
            "LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES",
            "PYTHONPATH", "PYTHONHOME", "GIT_CONFIG_GLOBAL",
            "LANG", "LC_ALL", "LC_CTYPE", "TZ",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(CatalogError, "isolation"):
                ProjectCommandSpec("modelrig.demo", "python", ("-V",), ".", 10, {key: "x"})

    def test_catalog_environment_overrides_ambient_locale_and_timezone(self):
        spec = ProjectCommandSpec(
            "modelrig.demo", "python", ("-V",), ".", 10, {}
        )
        observed: dict[str, str] = {}

        def fake_bounded(args, **kwargs):
            del args
            observed.update(kwargs["env"])
            stream = SimpleNamespace(truncated=False, prefix=b"")
            return SimpleNamespace(
                output_limit_exceeded=False,
                timed_out=False,
                stdout=stream,
                stderr=stream,
                returncode=0,
            )

        with patch.dict(
            os.environ,
            {
                "PATH": "/attacker/bin",
                "LANG": "attacker_LANG",
                "LC_ALL": "attacker_LC_ALL",
                "LC_CTYPE": "attacker_LC_CTYPE",
                "TZ": "attacker/TZ",
            },
            clear=False,
        ), patch(
            "kaliv_dev_control.workspace.run_bounded_subprocess",
            side_effect=fake_bounded,
        ):
            result = SubprocessRunner().run(
                ("/bin/true",),
                cwd=Path.cwd(),
                timeout_seconds=1,
                max_output_bytes=100,
                env=spec.env,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            {
                key: observed[key]
                for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
            },
            {
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "LC_CTYPE": "C",
                "TZ": "UTC",
            },
        )

    def test_default_isolation_is_fail_closed_and_attestation_is_exact(self):
        t, tc = task(), toolchain()
        proof = attestation(t, tc)
        with self.assertRaisesRegex(CatalogError, "not been independently verified"):
            CatalogMaterializer(
                modelrig_command_catalog(), executable_verifier=AcceptExecutable()
            ).materialize(t, tc, proof)
        tampered = IsolationAttestation.from_mapping({**proof.to_dict(), "base_sha": "d" * 40})
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                isolation_verifier=AcceptIsolation(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, tampered)

    def test_materialization_contains_only_task_grants(self):
        t, tc, verifier = task("modelrig.devcontrol.tests", "modelrig.version.check"), toolchain(), AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=AcceptIsolation(),
            executable_verifier=verifier,
        ).materialize(t, tc, attestation(t, tc))
        self.assertEqual(registry.resolve(t, "modelrig.devcontrol.tests").argv[0], "/trusted/python3")
        self.assertEqual(registry.sandbox_bootstrap_executable(t), "/trusted/python3")
        self.assertEqual(verifier.seen, ["python"])
        self.assertIs(getattr(registry, "_catalog_executable_verifier"), verifier)

    def test_materialized_registry_rejects_unattested_task_and_retargeting(self):
        t, tc = task("modelrig.devcontrol.tests"), toolchain()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=AcceptIsolation(),
            executable_verifier=AcceptExecutable(),
        ).materialize(t, tc, attestation(t, tc))
        self.assertEqual(
            registry.resolve(t, "modelrig.devcontrol.tests").command_id,
            "modelrig.devcontrol.tests",
        )
        other = DevelopmentTask.from_mapping({
            **t.to_dict(), "task_id": "OTHER", "base_sha": "b" * 40,
        })
        with self.assertRaisesRegex(CommandPolicyError, "immutable"):
            registry._bound_task_identity = (
                other.task_id,
                hashlib.sha256(other.canonical_json().encode()).hexdigest(),
                other.repository,
                other.base_sha,
            )
        with self.assertRaisesRegex(CommandPolicyError, "immutable"):
            registry._bootstrap_executable = "/attacker/python"
        with self.assertRaisesRegex(CommandPolicyError, "exact task"):
            registry.resolve(other, "modelrig.devcontrol.tests")
        with self.assertRaisesRegex(CommandPolicyError, "exact task"):
            registry.sandbox_bootstrap_executable(other)

    def test_materialized_go_command_uses_attested_pinned_bootstrap(self):
        t, tc, verifier = task("modelrig.backend.vet"), toolchain(), AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=AcceptIsolation(),
            executable_verifier=verifier,
        ).materialize(t, tc, attestation(t, tc))
        template = registry.resolve(t, "modelrig.backend.vet")
        self.assertEqual(template.argv[0], "/trusted/go")
        self.assertEqual(verifier.seen, ["python", "go"])
        bootstrap = registry.sandbox_bootstrap_executable(t)
        self.assertEqual(bootstrap, "/trusted/python3")
        with patch("kaliv_dev_control.commands.sys.executable", "/attacker/python"):
            confined = CommandExecutor._confined_argv(
                Path("/sandbox"),
                Path("/sandbox/repository"),
                template.argv,
                registry.sandbox_bootstrap_executable(t),
            )
        self.assertEqual(confined[0], "/trusted/python3")
        self.assertEqual(confined[-len(template.argv):], template.argv)

    def test_materialization_uses_validated_task_snapshot(self):
        original = task("modelrig.devcontrol.tests")
        expected = DevelopmentTask.from_mapping(original.to_dict())
        tc = toolchain()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=MutateTaskIsolation(original),
            executable_verifier=AcceptExecutable(),
        ).materialize(original, tc, attestation(expected, tc))
        self.assertEqual(original.base_sha, "b" * 40)
        self.assertEqual(
            registry.resolve(expected, "modelrig.devcontrol.tests").argv[0],
            "/trusted/python3",
        )
        with self.assertRaisesRegex(CommandPolicyError, "exact task"):
            registry.resolve(original, "modelrig.devcontrol.tests")

    def test_materialization_uses_private_stable_attestation_snapshot(self):
        t = task("modelrig.devcontrol.tests")
        tc = toolchain()
        proof = attestation(t, tc)
        with self.assertRaisesRegex(CatalogError, "mutated"):
            CatalogMaterializer(
                modelrig_command_catalog(),
                isolation_verifier=MutateAttestationIsolation(),
                executable_verifier=AcceptExecutable(),
            ).materialize(t, tc, proof)
        self.assertEqual(proof.base_sha, BASE_SHA)

    def test_materialization_uses_attested_catalog_snapshot(self):
        t, tc = task("modelrig.devcontrol.tests"), toolchain()
        source = modelrig_command_catalog()
        replacement = ModelRigCommandCatalog((
            ProjectCommandSpec(
                "modelrig.devcontrol.tests", "python",
                ("-c", "print('replacement')"), ".", 10,
            ),
        ))
        catalog = ReassignCatalog(
            tuple(source.resolve(key) for key in source.command_ids),
            replacement,
        )
        materializer = CatalogMaterializer(
            catalog,
            isolation_verifier=AcceptIsolation(),
            executable_verifier=AcceptExecutable(),
        )
        catalog.materializer = materializer
        with self.assertRaisesRegex(CatalogError, "exact authority"):
            materializer.materialize(
                t, tc, attestation(t, tc, catalog=replacement)
            )

    def test_materialization_deep_copies_catalog_specs(self):
        t = task("modelrig.devcontrol.tests")
        tc = toolchain()
        catalog = modelrig_command_catalog()
        owned_spec = catalog.resolve("modelrig.devcontrol.tests")
        registry = CatalogMaterializer(
            catalog,
            isolation_verifier=MutateSpecIsolation(owned_spec),
            executable_verifier=AcceptExecutable(),
        ).materialize(t, tc, attestation(t, tc, catalog=catalog))
        template = registry.resolve(t, "modelrig.devcontrol.tests")
        self.assertIn("../tests", template.argv)
        self.assertNotIn("unattested-spec", " ".join(template.argv))

    def test_materialization_uses_original_executable_verifier_snapshot(self):
        t, tc = task("modelrig.devcontrol.tests"), toolchain()
        original = AcceptExecutable()
        isolation = SwapExecutableVerifierIsolation()
        materializer = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=isolation,
            executable_verifier=original,
        )
        isolation.materializer = materializer
        registry = materializer.materialize(t, tc, attestation(t, tc))
        self.assertEqual(original.seen, ["python"])
        self.assertIs(getattr(registry, "_catalog_executable_verifier"), original)

    def test_materialization_uses_attested_toolchain_snapshot(self):
        t, tc, verifier = task("modelrig.devcontrol.tests"), toolchain(), AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=MutateToolchainIsolation(tc),
            executable_verifier=verifier,
        ).materialize(t, tc, attestation(t, tc))
        self.assertEqual(registry.resolve(t, "modelrig.devcontrol.tests").argv[0], "/trusted/python3")
        self.assertEqual(registry.sandbox_bootstrap_executable(t), "/trusted/python3")
        self.assertEqual(verifier.seen, ["python"])

    def test_materialization_deep_copies_tool_bindings(self):
        t = task("modelrig.devcontrol.tests")
        tc = toolchain()
        owned_binding = tc.resolve("python")
        verifier = AcceptExecutable()
        registry = CatalogMaterializer(
            modelrig_command_catalog(),
            isolation_verifier=MutateBindingIsolation(owned_binding),
            executable_verifier=verifier,
        ).materialize(t, tc, attestation(t, tc))
        self.assertEqual(
            registry.resolve(t, "modelrig.devcontrol.tests").argv[0],
            "/trusted/python3",
        )
        self.assertEqual(registry.sandbox_bootstrap_executable(t), "/trusted/python3")
        self.assertEqual(verifier.seen, ["python"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only pinning")
    def test_sealed_object_survives_path_replacement_and_verifier_close(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "python"
            shutil.copy2(Path(sys.executable).resolve(), source)
            source.chmod(0o500)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            verifier = LocalExecutableHashVerifier()
            pinned = verifier.verify(ToolBinding("python", str(source.resolve()), digest))
            replacement = source.with_name("replacement")
            replacement.write_bytes(b"not the verified executable")
            replacement.chmod(0o500)
            os.replace(replacement, source)
            result = subprocess.run([pinned, "-c", "print('pinned-object')"], text=True, capture_output=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, "pinned-object"), result.stderr)
            with self.assertRaises(OSError):
                Path(pinned).write_bytes(b"tampered")
            descriptor = int(Path(pinned).name)
            verifier.close()
            unrelated = os.open("/bin/echo", os.O_RDONLY)
            try:
                self.assertNotEqual(unrelated, descriptor)
                result = subprocess.run([pinned, "-c", "print('still-pinned')"], text=True, capture_output=True)
                self.assertEqual((result.returncode, result.stdout.strip()), (0, "still-pinned"), result.stderr)
            finally:
                os.close(unrelated)
            with self.assertRaisesRegex(CatalogError, "closed"):
                verifier.verify(ToolBinding("python", str(source.resolve()), digest))

    @unittest.skipUnless(
        sys.platform.startswith("linux") and hasattr(os, "mkfifo"),
        "Linux FIFO regression",
    )
    def test_fifo_executable_candidate_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "fifo-tool"
            os.mkfifo(fifo, 0o500)
            script = """
import sys
from kaliv_dev_control.catalog import CatalogError, LocalExecutableHashVerifier, ToolBinding
try:
    LocalExecutableHashVerifier().verify(ToolBinding("python", sys.argv[1], "0" * 64))
except CatalogError as exc:
    print(exc)
    raise SystemExit(0)
raise SystemExit(2)
"""
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script, str(fifo.resolve())],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=3,
                )
            except subprocess.TimeoutExpired as exc:
                self.fail(f"FIFO executable verification blocked: {exc}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("regular executable", result.stdout)

    @unittest.skipIf(os.name == "nt", "Windows verifier fails closed")
    def test_link_and_hash_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / "tool").resolve()
            path.write_bytes(b"trusted")
            path.chmod(0o500)
            alias = path.parent / "alias"
            alias.symlink_to(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(CatalogError, "linked|safely"):
                LocalExecutableHashVerifier().verify(ToolBinding("python", str(alias), digest))
            with self.assertRaisesRegex(CatalogError, "hash mismatch"):
                LocalExecutableHashVerifier().verify(ToolBinding("python", str(path), "0" * 64))

    def test_attestation_reload_is_strict(self):
        proof = attestation(task(), toolchain())
        self.assertEqual(IsolationAttestation.from_mapping(proof.to_dict()).canonical_json(), proof.canonical_json())
        with self.assertRaises(CatalogError):
            IsolationAttestation.from_mapping({**proof.to_dict(), "task_id": "bad"})


class GitHubReadTests(unittest.TestCase):
    def test_invalid_direct_task_sha_fails_before_network(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(GitHubReadError, "identity"):
            GitHubReadAdapter(replace(task(), base_sha="main"), transport=transport)
        self.assertEqual(transport.calls, [])

    def test_validated_adapter_authority_cannot_be_retargeted(self):
        transport = FakeTransport(response({"sha": BASE_SHA}))
        adapter = GitHubReadAdapter(task(), transport=transport, token="secret-token")
        replacements = (
            ("task", replace(task(), base_sha="b" * 40)),
            ("_snapshot", adapter._snapshot),
            ("_repository_path", "/repos/Other/Repo"),
            ("_token", "replacement-token"),
            ("timeout_seconds", 1),
            ("transport", FakeTransport(response({"sha": "b" * 40}))),
        )
        for name, value in replacements:
            with self.subTest(name=name), self.assertRaisesRegex(
                GitHubReadError, "immutable"
            ):
                setattr(adapter, name, value)
        receipt = adapter.verify_base_commit()
        self.assertEqual(receipt.base_sha, BASE_SHA)
        self.assertIn(
            "/repos/Ternedal/ModelRig/commits/" + BASE_SHA,
            transport.calls[0][0],
        )
        self.assertEqual(
            transport.calls[0][1]["Authorization"],
            "Bearer secret-token",
        )

    def test_verify_base_commit_is_fixed_exact_sha_get(self):
        transport = FakeTransport(response({"sha": BASE_SHA}))
        receipt = GitHubReadAdapter(task(), transport=transport).verify_base_commit()
        url, headers, timeout, maximum = transport.calls[0]
        self.assertEqual(url, f"https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}")
        self.assertNotIn("Authorization", headers)
        self.assertEqual((timeout, maximum, receipt.subject_sha), (30, 1_000_000, BASE_SHA))

    def test_scoped_blob_verified_read_and_token_free_receipt(self):
        data = b"print('ok')\n"
        transport = FakeTransport(response(file_payload("devcontrol/src/demo.py", data)))
        observed, receipt = GitHubReadAdapter(task(), transport=transport, token="secret-token").read_bytes("devcontrol/src/demo.py")
        self.assertEqual(observed, data)
        self.assertIn("ref=" + BASE_SHA, transport.calls[0][0])
        self.assertNotIn("secret-token", receipt.canonical_json())
        receipt.verify_task(task())

    def test_blob_sha_and_size_mismatches_are_rejected(self):
        with self.assertRaisesRegex(GitHubReadError, "blob SHA"):
            GitHubReadAdapter(
                task(), transport=FakeTransport(response(file_payload("devcontrol/readme.txt", b"hello", blob_sha="b" * 40)))
            ).read_bytes("devcontrol/readme.txt")
        with self.assertRaisesRegex(GitHubReadError, "bound|size"):
            GitHubReadAdapter(
                task(), transport=FakeTransport(response(file_payload("devcontrol/readme.txt", b"hello", size=99)))
            ).read_bytes("devcontrol/readme.txt", max_bytes=5)

    def test_protected_and_git_paths_fail_before_network(self):
        transport = FakeTransport()
        adapter = GitHubReadAdapter(task(), transport=transport)
        for path in ("devcontrol/secrets/token.txt", ".git/config"):
            with self.assertRaises(GitHubReadError):
                adapter.read_bytes(path)
        self.assertEqual(transport.calls, [])

    def test_redirect_non_json_and_commit_mismatch_are_rejected(self):
        redirect = response({"sha": BASE_SHA}, headers={"Content-Type": "application/json", "Location": "https://example.org"})
        with self.assertRaisesRegex(GitHubReadError, "redirect"):
            GitHubReadAdapter(task(), transport=FakeTransport(redirect)).verify_base_commit()
        with self.assertRaisesRegex(GitHubReadError, "not JSON"):
            GitHubReadAdapter(task(), transport=FakeTransport(HttpResponse(200, {"Content-Type": "text/html"}, b"html"))).verify_base_commit()
        with self.assertRaisesRegex(GitHubReadError, "does not match"):
            GitHubReadAdapter(task(), transport=FakeTransport(response({"sha": "d" * 40}))).verify_base_commit()

    def test_receipt_reload_types_and_task_binding_are_strict(self):
        receipt = GitHubReadAdapter(task(), transport=FakeTransport(response({"sha": BASE_SHA}))).verify_base_commit()
        self.assertEqual(GitHubReadReceipt.from_mapping(receipt.to_dict()).canonical_json(), receipt.canonical_json())
        for change in ({"task_id": 1}, {"repository": 1}, {"status": 201}, {"status": 200.0}):
            with self.subTest(change=change), self.assertRaises(GitHubReadError):
                GitHubReadReceipt.from_mapping({**receipt.to_dict(), **change})
        with self.assertRaisesRegex(GitHubReadError, "exact task"):
            receipt.verify_task(DevelopmentTask.from_mapping({**task().to_dict(), "task_id": "OTHER"}))

    def test_transport_ignores_environment_network_and_tls_authority(self):
        compiled = SimpleNamespace(
            openssl_cafile="/compiled/ca.pem",
            openssl_capath="/compiled/certs",
            cafile="/attacker/ca.pem",
            capath="/attacker/certs",
        )
        context = unittest.mock.MagicMock()
        with patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://attacker.invalid:8080",
                "SSL_CERT_FILE": "/attacker/ca.pem",
                "SSL_CERT_DIR": "/attacker/certs",
            },
        ), patch(
            "kaliv_dev_control.github_read.ssl.SSLContext",
            return_value=context,
        ), patch(
            "kaliv_dev_control.github_read.ssl.get_default_verify_paths",
            return_value=compiled,
        ), patch(
            "kaliv_dev_control.github_read.urllib.request.build_opener"
        ) as builder:
            builder.return_value = object()
            UrllibReadOnlyTransport()

        context.load_verify_locations.assert_any_call(cafile="/compiled/ca.pem")
        context.load_verify_locations.assert_any_call(capath="/compiled/certs")
        loaded = repr(context.load_verify_locations.call_args_list)
        self.assertNotIn("/attacker/", loaded)
        handlers = builder.call_args.args
        proxy = next(
            item for item in handlers
            if isinstance(item, urllib.request.ProxyHandler)
        )
        https = next(
            item for item in handlers
            if isinstance(item, urllib.request.HTTPSHandler)
        )
        self.assertEqual(proxy.proxies, {})
        self.assertIs(https._context, context)

        transport = UrllibReadOnlyTransport()
        with patch.object(transport._opener, "open") as opener:
            with self.assertRaisesRegex(GitHubReadError, "fixed GitHub"):
                transport.get(
                    "https://example.org/repos/Ternedal/ModelRig",
                    headers={}, timeout_seconds=1, max_bytes=100,
                )
            opener.assert_not_called()


class SchemaTests(unittest.TestCase):
    def test_schemas_match_landed_task_identity(self):
        root = Path(__file__).resolve().parents[1] / "schemas"
        for name in (
            "development-github-read-receipt-v1.schema.json",
            "development-isolation-attestation-v1.schema.json",
        ):
            schema = json.loads((root / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["properties"]["task_id"]["pattern"], "^[A-Z][A-Z0-9_-]{2,63}$")


if __name__ == "__main__":
    unittest.main()
