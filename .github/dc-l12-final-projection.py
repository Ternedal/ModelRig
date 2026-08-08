from pathlib import Path

root = Path.cwd()

support = root / "devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy/__init__.py"
text = support.read_text(encoding="utf-8")
old = "signer, credential value, transport, subprocess or remote"
new = "signer, credential value, transport, process launch or remote"
if old not in text:
    raise SystemExit("support docstring marker missing")
support.write_text(text.replace(old, new, 1), encoding="utf-8")

worker = root / "tests/worker_toolhost.py"
text = worker.read_text(encoding="utf-8")
text = text.replace("import time\nimport time\n", "import time\n", 1)
marker = "from dataclasses import replace\n\nsys.path.insert"
replacement = "from dataclasses import replace\n\nif hasattr(sys.stdout, \"reconfigure\"):\n    sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"backslashreplace\")\n\nsys.path.insert"
if marker not in text:
    raise SystemExit("worker stdout marker missing")
worker.write_text(text.replace(marker, replacement, 1), encoding="utf-8")

readme = root / "devcontrol/README.md"
text = readme.read_text(encoding="utf-8")
heading = "## DC-L12 — one-time authorization and authenticated recovery"
if heading not in text:
    text += f'''\n\n{heading}\n\nDC-L12 adds verification-only Ed25519 authorization for one exact signed publisher request, crash-durable one-time nonce consumption, dual-role authenticated replay recovery, a physically primary recovery ledger and deterministic missing-v3-receipt finalization.\n\nEvery authorization verification also reads an injected external monotonic keyring-state provider. Generation rollback, same-generation drift, a signature below the external minimum epoch and external key revocation all fail closed. No local file is accepted as the monotonic anchor.\n\nThe landed boundary intentionally excludes the rejected dynamic v1/HMAC compatibility authority, private keys, signers, credentials, Git/HTTP/GitHub adapters, subprocess publishers, remote writes and DC-L13 local candidate materialization. Package-root, Tier-A facade and execution-bundle exports remain unchanged.\n'''
readme.write_text(text, encoding="utf-8")

foundation = root / "devcontrol/tests/test_foundation.py"
text = foundation.read_text(encoding="utf-8")
if "import importlib\n" not in text:
    text = text.replace("import json\n", "import importlib\nimport json\n", 1)
method = '''\n    def test_dc_l12_authority_remains_offline_and_non_root(self) -> None:\n        import kaliv_dev_control\n\n        public = importlib.import_module(\n            "kaliv_dev_control.publisher_authorization"\n        )\n        keyring = importlib.import_module(\n            "kaliv_dev_control.publisher_keyring_state"\n        )\n        self.assertTrue(callable(public.PublisherAuthorizationVerifierV2))\n        self.assertTrue(callable(keyring.RollbackSafeEd25519AuthorityVerifier))\n        for name in (\n            "PublisherAuthorizationVerifierV2",\n            "PublisherReplayLedgerV2",\n            "RollbackSafeEd25519AuthorityVerifier",\n        ):\n            self.assertFalse(hasattr(kaliv_dev_control, name), name)\n        self.assertIsNone(\n            importlib.util.find_spec(\n                "kaliv_dev_control.local_candidate_materialization"\n            )\n        )\n\n'''
if "test_dc_l12_authority_remains_offline_and_non_root" not in text:
    final_marker = '\n\nif __name__ == "__main__":\n'
    if final_marker not in text:
        raise SystemExit("foundation final marker missing")
    text = text.replace(final_marker, method + final_marker, 1)
foundation.write_text(text, encoding="utf-8")
