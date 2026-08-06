from __future__ import annotations
import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kaliv_dev_control.catalog import CatalogError, CatalogMaterializer, IsolationAttestation, IsolationBoundary, LocalExecutableHashVerifier, NetworkMode, ProjectCommandSpec, ToolBinding, Toolchain, modelrig_command_catalog
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.github_read import GitHubReadAdapter, GitHubReadError, GitHubReadReceipt, HttpResponse, UrllibReadOnlyTransport
BASE_SHA = 'a' * 40
HASH = 'c' * 64

def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\x00' + data, usedforsecurity=False).hexdigest()

def task(*commands: str) -> DevelopmentTask:
    return DevelopmentTask.from_mapping({'schema': 'kaliv-development-task/v1', 'task_id': 'A5_SLICE', 'repository': 'Ternedal/ModelRig', 'base_sha': BASE_SHA, 'goal': 'Validate the next isolated control-plane slice.', 'acceptance_criteria': ['All fixed-authority tests pass.'], 'risk': 'low', 'allowed_paths': ['devcontrol/**'], 'protected_paths': ['devcontrol/secrets/**'], 'allowed_command_ids': list(commands) or ['modelrig.devcontrol.tests'], 'required_tests': ['modelrig.devcontrol.tests'], 'budget': {'max_changed_files': 20, 'max_added_lines': 5000, 'max_deleted_lines': 5000, 'max_attempts': 2, 'max_runtime_seconds': 3600, 'max_output_bytes': 1000000}, 'merge_authority': 'human'})

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

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], int, int]] = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError('unexpected transport call')
        return self.responses.pop(0)

def response(payload, *, status=200, headers=None) -> HttpResponse:
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return HttpResponse(status=status, headers=headers or {'Content-Type': 'application/json', 'ETag': '"abc"'}, body=body)

def file_payload(path: str, data: bytes, *, blob_sha: str | None=None, size: int | None=None):
    return {'type': 'file', 'path': path, 'sha': blob_sha or git_blob_sha(data), 'encoding': 'base64', 'content': base64.b64encode(data).decode('ascii'), 'size': len(data) if size is None else size}

def toolchain() -> Toolchain:
    return Toolchain((ToolBinding('python', '/trusted/python3', '1' * 64), ToolBinding('go', '/trusted/go', '2' * 64)))

def attestation(t: DevelopmentTask, tc: Toolchain) -> IsolationAttestation:
    catalog = modelrig_command_catalog()
    return IsolationAttestation(task_id=t.task_id, task_sha256=hashlib.sha256(t.canonical_json().encode()).hexdigest(), repository=t.repository, base_sha=t.base_sha, catalog_sha256=catalog.sha256, toolchain_sha256=tc.sha256, boundary=IsolationBoundary.OS_ISOLATED, network_mode=NetworkMode.DENY, evidence_sha256=(HASH,))

class CatalogTests(unittest.TestCase):

    def test_catalog_is_deterministic_and_versioned(self):
        first = modelrig_command_catalog()
        second = modelrig_command_catalog()
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(len(first.sha256), 64)
        self.assertEqual(first.command_ids, ('modelrig.backend.tests', 'modelrig.backend.vet', 'modelrig.devcontrol.tests', 'modelrig.version.check', 'modelrig.workflow.test-coverage'))
        self.assertIn('test_*.py', first.resolve('modelrig.devcontrol.tests').args)

    def test_unknown_task_command_is_rejected(self):
        t = task('modelrig.not-real')
        tc = toolchain()
        materializer = CatalogMaterializer(modelrig_command_catalog(), isolation_verifier=AcceptIsolation(), executable_verifier=AcceptExecutable())
        with self.assertRaises(CatalogError):
            materializer.materialize(t, tc, attestation(t, tc))

    def test_default_isolation_verifier_is_fail_closed(self):
        t = task()
        tc = toolchain()
        with self.assertRaisesRegex(CatalogError, 'not been independently verified'):
            CatalogMaterializer(modelrig_command_catalog(), executable_verifier=AcceptExecutable()).materialize(t, tc, attestation(t, tc))

    def test_attestation_must_bind_exact_task(self):
        t = task()
        tc = toolchain()
        proof = attestation(t, tc)
        tampered = IsolationAttestation.from_mapping({**proof.to_dict(), 'base_sha': 'd' * 40})
        with self.assertRaisesRegex(CatalogError, 'exact authority'):
            CatalogMaterializer(modelrig_command_catalog(), isolation_verifier=AcceptIsolation(), executable_verifier=AcceptExecutable()).materialize(t, tc, tampered)

    def test_missing_tool_binding_is_rejected(self):
        t = task('modelrig.backend.tests')
        tc = Toolchain((ToolBinding('python', '/trusted/python3', '1' * 64),))
        with self.assertRaisesRegex(CatalogError, 'required tool'):
            CatalogMaterializer(modelrig_command_catalog(), isolation_verifier=AcceptIsolation(), executable_verifier=AcceptExecutable()).materialize(t, tc, attestation(t, tc))

    def test_materialized_registry_contains_only_task_grants(self):
        t = task('modelrig.devcontrol.tests', 'modelrig.version.check')
        tc = toolchain()
        isolation = AcceptIsolation()
        executables = AcceptExecutable()
        registry = CatalogMaterializer(modelrig_command_catalog(), isolation_verifier=isolation, executable_verifier=executables).materialize(t, tc, attestation(t, tc))
        command = registry.resolve(t, 'modelrig.devcontrol.tests')
        self.assertEqual(command.argv[0], '/trusted/python3')
        self.assertEqual(command.argv[1:4], ('-m', 'unittest', 'discover'))
        self.assertEqual(command.cwd, 'devcontrol/src')
        self.assertIn('../tests', command.argv)
        self.assertEqual(command.env['MODELRIG_DEVCONTROL'], '1')
        self.assertEqual(isolation.calls, 1)
        self.assertEqual(executables.seen, ['python'])
        with self.assertRaises(Exception):
            registry.resolve(t, 'modelrig.backend.tests')

    @unittest.skipIf(os.name == 'nt', 'portable verifier deliberately fails closed on Windows')
    def test_local_executable_hash_verifier_uses_regular_canonical_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / 'python').resolve()
            path.write_bytes(b'trusted executable')
            path.chmod(448)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            LocalExecutableHashVerifier().verify(ToolBinding('python', str(path), digest))
            with self.assertRaisesRegex(CatalogError, 'hash mismatch'):
                LocalExecutableHashVerifier().verify(ToolBinding('python', str(path), '0' * 64))
            alias = path.parent / 'alias'
            alias.symlink_to(path)
            with self.assertRaisesRegex(CatalogError, 'linked|safely'):
                LocalExecutableHashVerifier().verify(ToolBinding('python', str(alias), digest))

    def test_catalog_objects_reject_mutable_boolean_and_loader_authority(self):
        with self.assertRaises(CatalogError):
            ProjectCommandSpec('modelrig.demo', 'python', ['-V'], '.', 10)
        with self.assertRaises(CatalogError):
            ProjectCommandSpec('modelrig.demo', 'python', ('-V',), '.', True)
        with self.assertRaisesRegex(CatalogError, 'isolation'):
            ProjectCommandSpec('modelrig.demo', 'python', ('-V',), '.', 10, {'LD_PRELOAD': '/tmp/hook.so'})
        with self.assertRaisesRegex(CatalogError, 'isolation'):
            ProjectCommandSpec('modelrig.demo', 'python', ('-V',), '.', 10, {'GIT_CONFIG_GLOBAL': '/tmp/config'})

    def test_attestation_reload_is_strict(self):
        t = task()
        tc = toolchain()
        proof = attestation(t, tc)
        self.assertEqual(IsolationAttestation.from_mapping(proof.to_dict()).canonical_json(), proof.canonical_json())
        with self.assertRaises(CatalogError):
            IsolationAttestation.from_mapping({**proof.to_dict(), 'extra': True})
        with self.assertRaises(CatalogError):
            IsolationAttestation.from_mapping({**proof.to_dict(), 'task_id': 'lower'})

class GitHubReadTests(unittest.TestCase):

    def test_boolean_http_bounds_and_bad_token_are_rejected(self):
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), transport=FakeTransport(), timeout_seconds=True)
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), token='contains whitespace')
        with self.assertRaises(GitHubReadError):
            GitHubReadAdapter(task(), transport=FakeTransport()).read_bytes('devcontrol/readme.txt', max_bytes=True)

    def test_verify_base_commit_is_exact_sha_get(self):
        transport = FakeTransport(response({'sha': BASE_SHA}))
        receipt = GitHubReadAdapter(task(), transport=transport).verify_base_commit()
        url, headers, timeout, max_bytes = transport.calls[0]
        self.assertEqual(url, f'https://api.github.com/repos/Ternedal/ModelRig/commits/{BASE_SHA}')
        self.assertNotIn('Authorization', headers)
        self.assertEqual(timeout, 30)
        self.assertEqual(max_bytes, 1000000)
        self.assertEqual(receipt.operation, 'verify_base_commit')
        self.assertEqual(receipt.subject_sha, BASE_SHA)

    def test_commit_mismatch_is_rejected(self):
        transport = FakeTransport(response({'sha': 'd' * 40}))
        with self.assertRaisesRegex(GitHubReadError, 'does not match'):
            GitHubReadAdapter(task(), transport=transport).verify_base_commit()

    def test_read_text_is_scoped_blob_verified_and_bound_to_base_sha(self):
        data = b"print('ok')\n"
        payload = file_payload('devcontrol/src/demo.py', data)
        encoded = payload['content']
        payload['content'] = encoded[:8] + '\n' + encoded[8:]
        transport = FakeTransport(response(payload))
        text, receipt = GitHubReadAdapter(task(), transport=transport, token='secret-token').read_text('devcontrol/src/demo.py')
        self.assertEqual(text, "print('ok')\n")
        url, headers, _, _ = transport.calls[0]
        self.assertIn('ref=' + BASE_SHA, url)
        self.assertIn('/contents/devcontrol/src/demo.py', url)
        self.assertEqual(headers['Authorization'], 'Bearer secret-token')
        self.assertNotIn('secret-token', receipt.canonical_json())
        self.assertEqual(receipt.subject_sha, git_blob_sha(data))
        receipt.verify_task(task())

    def test_blob_sha_mismatch_is_rejected(self):
        payload = file_payload('devcontrol/readme.txt', b'hello', blob_sha='b' * 40)
        with self.assertRaisesRegex(GitHubReadError, 'blob SHA'):
            GitHubReadAdapter(task(), transport=FakeTransport(response(payload))).read_bytes('devcontrol/readme.txt')

    def test_receipt_task_rebinding_and_invalid_identity_are_rejected(self):
        original = task()
        receipt = GitHubReadAdapter(original, transport=FakeTransport(response({'sha': BASE_SHA}))).verify_base_commit()
        other = DevelopmentTask.from_mapping({**original.to_dict(), 'task_id': 'OTHER_TASK'})
        with self.assertRaisesRegex(GitHubReadError, 'exact task'):
            receipt.verify_task(other)
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), 'task_id': 'lowercase'})
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), 'subject_sha': 'b' * 40})

    def test_protected_path_and_git_metadata_are_denied_before_network(self):
        transport = FakeTransport()
        adapter = GitHubReadAdapter(task(), transport=transport)
        with self.assertRaisesRegex(GitHubReadError, 'outside readable'):
            adapter.read_text('devcontrol/secrets/token.txt')
        with self.assertRaises(GitHubReadError):
            adapter.read_text('.git/config')
        self.assertEqual(transport.calls, [])

    def test_binary_text_is_rejected(self):
        data = b'a\x00b'
        payload = file_payload('devcontrol/blob.bin', data)
        with self.assertRaisesRegex(GitHubReadError, 'binary'):
            GitHubReadAdapter(task(), transport=FakeTransport(response(payload))).read_text('devcontrol/blob.bin')

    def test_redirect_and_non_json_are_rejected(self):
        redirected = response({'sha': BASE_SHA}, headers={'Content-Type': 'application/json', 'Location': 'https://example.org'})
        with self.assertRaisesRegex(GitHubReadError, 'redirect'):
            GitHubReadAdapter(task(), transport=FakeTransport(redirected)).verify_base_commit()
        bad = HttpResponse(200, {'Content-Type': 'text/html'}, b'<html></html>')
        with self.assertRaisesRegex(GitHubReadError, 'not JSON'):
            GitHubReadAdapter(task(), transport=FakeTransport(bad)).verify_base_commit()

    def test_file_bound_is_checked_before_decoding(self):
        payload = file_payload('devcontrol/readme.txt', b'hello', size=99)
        with self.assertRaisesRegex(GitHubReadError, 'bound'):
            GitHubReadAdapter(task(), transport=FakeTransport(response(payload))).read_bytes('devcontrol/readme.txt', max_bytes=5)

    def test_receipt_reload_rejects_tampering(self):
        receipt = GitHubReadAdapter(task(), transport=FakeTransport(response({'sha': BASE_SHA}))).verify_base_commit()
        self.assertEqual(GitHubReadReceipt.from_mapping(receipt.to_dict()).canonical_json(), receipt.canonical_json())
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), 'status': 201})
        with self.assertRaises(GitHubReadError):
            GitHubReadReceipt.from_mapping({**receipt.to_dict(), 'extra': True})

    def test_urllib_transport_rejects_non_github_authority_before_open(self):
        transport = UrllibReadOnlyTransport()
        with patch.object(transport._opener, 'open') as opener:
            with self.assertRaisesRegex(GitHubReadError, 'fixed GitHub'):
                transport.get('https://example.org/repos/Ternedal/ModelRig', headers={}, timeout_seconds=1, max_bytes=100)
            opener.assert_not_called()

class SchemaTests(unittest.TestCase):

    def test_slice5_schemas_use_contract_task_id_pattern(self):
        root = Path(__file__).resolve().parents[1] / 'schemas'
        for name in ('development-github-read-receipt-v1.schema.json', 'development-isolation-attestation-v1.schema.json'):
            schema = json.loads((root / name).read_text(encoding='utf-8'))
            self.assertEqual(schema['properties']['task_id']['pattern'], '^[A-Z][A-Z0-9_-]{2,63}$')
if __name__ == '__main__':
    unittest.main()
