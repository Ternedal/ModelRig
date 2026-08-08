from pathlib import Path

path = Path("devcontrol/tests/test_foundation.py")
text = path.read_text(encoding="utf-8")

old_landed = '''            "draft_pr_readiness.py",
            "publisher_dry_run.py",
        }
'''
new_landed = '''            "draft_pr_readiness.py",
            "publisher_dry_run.py",
            "publisher_authorization.py",
            "publisher_authorization_chain_v2.py",
            "publisher_authorization_v2.py",
            "publisher_keyring_state.py",
            "publisher_recovery_authorization.py",
            "publisher_recovery_authorization_strict.py",
            "publisher_recovery_primary.py",
            "publisher_recovery_receipt_finalizer.py",
            "publisher_recovery_receipt_v3.py",
            "publisher_replay_h4.py",
        }
'''
old_future = '''        future = (
            "publisher_authorization",
            "publisher_replay_h4",
            "publisher_recovery_authorization",
            "local_candidate_materialization",
            "publisher",
        )
'''
new_future = '''        future = (
            "local_candidate_materialization",
            "local_candidate_materialization_h5c",
        )
'''

if text.count(old_landed) != 1:
    raise SystemExit("landed inventory marker mismatch")
if text.count(old_future) != 1:
    raise SystemExit("future inventory marker mismatch")

text = text.replace(old_landed, new_landed)
text = text.replace(old_future, new_future)
path.write_text(text, encoding="utf-8")
