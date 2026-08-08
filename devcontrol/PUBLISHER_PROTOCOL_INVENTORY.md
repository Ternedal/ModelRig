# Publisher protocol and durable-publication inventory

This final DC-L14 inventory is generated from the recursively discovered supported source tree.
It inventories evidence, review, authorization, recovery, dry-run and local-only materialization
surfaces without granting live publisher, remote Git, GitHub mutation, credential or activation authority.

## Supported protocol source files

- `devcontrol/src/kaliv_dev_control/_local_candidate_materialization_legacy/__init__.py`
- `devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy/__init__.py`
- `devcontrol/src/kaliv_dev_control/_semantic_review_core.py`
- `devcontrol/src/kaliv_dev_control/draft_pr_readiness.py`
- `devcontrol/src/kaliv_dev_control/durable_publication.py`
- `devcontrol/src/kaliv_dev_control/local_candidate_materialization.py`
- `devcontrol/src/kaliv_dev_control/local_candidate_materialization_h5c.py`
- `devcontrol/src/kaliv_dev_control/publisher_authorization.py`
- `devcontrol/src/kaliv_dev_control/publisher_authorization_chain_v2.py`
- `devcontrol/src/kaliv_dev_control/publisher_authorization_v2.py`
- `devcontrol/src/kaliv_dev_control/publisher_dry_run.py`
- `devcontrol/src/kaliv_dev_control/publisher_keyring_state.py`
- `devcontrol/src/kaliv_dev_control/publisher_recovery_authorization.py`
- `devcontrol/src/kaliv_dev_control/publisher_recovery_authorization_strict.py`
- `devcontrol/src/kaliv_dev_control/publisher_recovery_primary.py`
- `devcontrol/src/kaliv_dev_control/publisher_recovery_receipt_finalizer.py`
- `devcontrol/src/kaliv_dev_control/publisher_recovery_receipt_v3.py`
- `devcontrol/src/kaliv_dev_control/publisher_replay_h4.py`
- `devcontrol/src/kaliv_dev_control/semantic_review.py`
- `devcontrol/src/kaliv_dev_control/store.py`
- `devcontrol/src/kaliv_dev_control/streaming_publication.py`
- `devcontrol/src/kaliv_dev_control/trusted_git_runtime_staging.py`

## Packaging boundary

- `kaliv_dev_control._compatibility_v1` is physically excluded from wheel and sdist artifacts.
- `_local_candidate_materialization_legacy` is a static validation/evidence support package, not an executable legacy runner.
- There is no remote publication authority in the supported package or runtime.
- Live publication, push, reviewer mutation, merge, release, deployment and activation remain absent.
