from pathlib import Path

root = Path.cwd()
workflow_path = root / '.github/workflows/_tests.yml'
coverage_path = root / 'tests/workflow_test_coverage.py'

w = workflow_path.read_text(encoding='utf-8')
w = w.replace('DevControl DC-L01 through DC-L11 tests', 'DevControl DC-L01 through DC-L12 tests')

# Earlier slice gates must reject only still-future DC-L13 surfaces.
w = w.replace('''          for future_module in (\n              "kaliv_dev_control.publisher_authorization",\n              "kaliv_dev_control.local_candidate_materialization",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''', '''          for future_module in (\n              "kaliv_dev_control.local_candidate_materialization",\n              "kaliv_dev_control.local_candidate_materialization_h5c",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''', 1)
w = w.replace('''          for future_module in (\n              "kaliv_dev_control.publisher_authorization",\n              "kaliv_dev_control.publisher_authorization_v2",\n              "kaliv_dev_control.publisher_recovery_authorization",\n              "kaliv_dev_control.local_candidate_materialization",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''', '''          for future_module in (\n              "kaliv_dev_control.local_candidate_materialization",\n              "kaliv_dev_control.local_candidate_materialization_h5c",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''')
w = w.replace('''          for future_module in (\n              "kaliv_dev_control.publisher_authorization",\n              "kaliv_dev_control.publisher_authorization_v2",\n              "kaliv_dev_control.publisher_authorization_chain_v2",\n              "kaliv_dev_control.publisher_replay_h4",\n              "kaliv_dev_control.publisher_recovery_authorization",\n              "kaliv_dev_control.local_candidate_materialization",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''', '''          for future_module in (\n              "kaliv_dev_control.local_candidate_materialization",\n              "kaliv_dev_control.local_candidate_materialization_h5c",\n          ):\n              assert importlib.util.find_spec(future_module) is None, future_module\n''')

marker = '      - name: DevControl final boundary regressions\n'
if marker not in w:
    raise SystemExit('final regression marker not found')
step = '''      - name: DevControl DC-L12 authorization and authenticated recovery boundary
        env:
          PYTHONDONTWRITEBYTECODE: "1"
        shell: bash
        run: |
          set -o pipefail
          PYTHONPATH=devcontrol/src python3 - <<'PY' 2>&1 | tee -a /tmp/modelrig-ci-test.log
          import importlib
          import importlib.util
          import inspect
          from pathlib import Path

          import kaliv_dev_control

          public = importlib.import_module("kaliv_dev_control.publisher_authorization")
          chain = importlib.import_module("kaliv_dev_control.publisher_authorization_chain_v2")
          keyring = importlib.import_module("kaliv_dev_control.publisher_keyring_state")
          recovery = importlib.import_module("kaliv_dev_control.publisher_recovery_authorization")
          primary = importlib.import_module("kaliv_dev_control.publisher_recovery_primary")
          receipt = importlib.import_module("kaliv_dev_control.publisher_recovery_receipt_v3")
          finalizer = importlib.import_module("kaliv_dev_control.publisher_recovery_receipt_finalizer")
          support = importlib.import_module("kaliv_dev_control._publisher_authorization_legacy")
          tier_a_facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
          toolhost = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")

          assert callable(public.AsymmetricPublisherAuthorizationVerifier)
          assert callable(public.PublisherAuthorizationVerifierV2)
          assert callable(public.PublisherReplayLedgerV2)
          assert public.PublisherReplayLedgerV2 is primary.PublisherReplayLedgerV3
          assert callable(recovery.PublisherReplayRecoveryAuthorizationVerifierV1)
          assert callable(receipt.PublisherReplayRecoveryReceiptV3)
          assert callable(finalizer.finalize_publisher_replay_recovery_receipt_v3)
          assert callable(keyring.RollbackSafeEd25519AuthorityVerifier)
          assert Path(support.__file__).name == "__init__.py"

          support_source = inspect.getsource(support)
          keyring_source = inspect.getsource(keyring)
          landed_source = "".join(
              inspect.getsource(module)
              for module in (public, chain, keyring, recovery, primary, receipt, finalizer)
          )
          for token in (
              "import hmac",
              "HmacPublisherAuthorizationIssuer",
              "TrustedAuthorizationIssuerKey",
              "Ed25519PrivateKey",
              "private_key",
              ".sign(",
              "globals().update",
              "sys.modules",
          ):
              assert token not in support_source + keyring_source, token
          for token in (
              "Authorization:",
              "requests.",
              "urllib",
              "http.client",
              "subprocess",
              "create_pull_request",
              "update_pull_request",
              "merge_pull_request",
              "git push",
          ):
              assert token not in landed_source, token
          for token in ("Path(", "open(", "read_text", "read_bytes"):
              assert token not in keyring_source, token

          for name in (
              "AsymmetricPublisherAuthorizationLease",
              "PublisherReplayLedgerV2",
              "PublisherReplayRecoveryReceiptV3",
              "RollbackSafeEd25519AuthorityVerifier",
          ):
              assert not hasattr(kaliv_dev_control, name), name
              assert not hasattr(tier_a_facade, name), name

          assert all(
              "publisher_authorization" not in path
              and "publisher_recovery" not in path
              and "publisher_keyring_state" not in path
              for path in toolhost._TIER_A_BUNDLE_FILES
          )
          assert importlib.util.find_spec(
              "kaliv_dev_control._compatibility_v1.publisher_authorization"
          ) is None
          for future_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(future_module) is None, future_module
          PY

'''
w = w.replace(marker, step + marker)
workflow_path.write_text(w, encoding='utf-8')

c = coverage_path.read_text(encoding='utf-8')
insert_after = '    "test_h10r_tier_a_legacy_runner_extraction.py",\n'
modules = '''    "test_h5d_public_authorization_surface.py",
    "test_publisher_authorization_chain_v2.py",
    "test_publisher_authorization_v2.py",
    "test_publisher_keyring_state.py",
    "test_publisher_recovery_authorization_h6.py",
    "test_publisher_recovery_primary_h9.py",
    "test_publisher_recovery_receipt_finalizer_h8.py",
    "test_publisher_recovery_receipt_v3_h7.py",
    "test_publisher_recovery_signature_window_h6.py",
    "test_slice10k_publisher_authorization.py",
'''
if insert_after not in c:
    raise SystemExit('module insertion marker not found')
c = c.replace(insert_after, insert_after + modules)
c = c.replace('the thirty-nine DC-L01–L11 test modules are present', 'the forty-nine DC-L01–L12 test modules are present')

old_absence = '''check(
    all(
        importlib.util.find_spec(module) is None
        for module in (
            "kaliv_dev_control.publisher_authorization",
            "kaliv_dev_control.publisher_authorization_v2",
            "kaliv_dev_control.publisher_recovery_authorization",
            "kaliv_dev_control.publisher_replay_h4",
            "kaliv_dev_control.local_candidate_materialization",
        )
    ),
    "DC-L12–L13 authorization, recovery, replay and materialization modules remain absent",
)
'''
new_checks = '''publisher_authorization = importlib.import_module(
    "kaliv_dev_control.publisher_authorization"
)
publisher_chain = importlib.import_module(
    "kaliv_dev_control.publisher_authorization_chain_v2"
)
publisher_keyring = importlib.import_module(
    "kaliv_dev_control.publisher_keyring_state"
)
publisher_recovery = importlib.import_module(
    "kaliv_dev_control.publisher_recovery_authorization"
)
check(
    callable(publisher_authorization.PublisherAuthorizationVerifierV2)
    and callable(publisher_authorization.PublisherReplayLedgerV2),
    "DC-L12 exposes one-time Ed25519 authorization and replay evidence",
)
check(
    callable(publisher_recovery.PublisherReplayRecoveryAuthorizationVerifierV1),
    "DC-L12 exposes authenticated dual-role recovery verification",
)
check(
    callable(publisher_keyring.RollbackSafeEd25519AuthorityVerifier),
    "DC-L12 requires a rollback-safe external keyring-state verifier",
)
check(
    all(
        importlib.util.find_spec(module) is None
        for module in (
            "kaliv_dev_control.local_candidate_materialization",
            "kaliv_dev_control.local_candidate_materialization_h5c",
        )
    ),
    "DC-L13 local candidate materialization remains absent",
)
support_path = (
    root
    / "devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy/__init__.py"
)
support_source = support_path.read_text(encoding="utf-8")
keyring_source = (
    root / "devcontrol/src/kaliv_dev_control/publisher_keyring_state.py"
).read_text(encoding="utf-8")
check(
    not (
        root
        / "devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy.py"
    ).exists()
    and not (
        root / "devcontrol/src/kaliv_dev_control/_compatibility_v1"
    ).exists(),
    "rejected dynamic legacy and v1 compatibility files are not distributed",
)
check(
    all(
        token not in support_source + keyring_source
        for token in (
            "import hmac",
            "HmacPublisherAuthorizationIssuer",
            "TrustedAuthorizationIssuerKey",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
            "globals().update",
            "sys.modules",
            "subprocess",
            "requests.",
        )
    ),
    "DC-L12 support and external-state verifier contain no signing, secret, process or transport boundary",
)
check(
    all(
        token not in keyring_source
        for token in ("Path(", "open(", "read_text", "read_bytes")
    ),
    "rollback-safe keyring state cannot be sourced from a local file",
)
'''
if old_absence not in c:
    raise SystemExit('old absence block not found')
c = c.replace(old_absence, new_checks)
c = c.replace('''check(
    "DevControl DC-L11 readiness and publisher dry-run boundary" in workflow,
    "CI contains an explicit non-mutating DC-L11 intent boundary gate",
)
''', '''check(
    "DevControl DC-L11 readiness and publisher dry-run boundary" in workflow,
    "CI contains an explicit non-mutating DC-L11 intent boundary gate",
)
check(
    "DevControl DC-L12 authorization and authenticated recovery boundary" in workflow,
    "CI contains an explicit offline DC-L12 authorization/recovery boundary gate",
)
''')
coverage_path.write_text(c, encoding='utf-8')

print('patched', workflow_path, workflow_path.stat().st_size)
print('patched', coverage_path, coverage_path.stat().st_size)
