"""Static contract test for the release workflow's visibility boundary.

The workflow cannot be executed on every PR because it is tag-triggered, but the
failure class is simple enough to pin mechanically: exactly one job may create a
release, it must create/edit it as draft before any build uploads, uploads may
not have their own public fallback, and publication must be the last explicit
state transition after asset verification.
"""
from pathlib import Path

text = Path(".github/workflows/build-and-release.yml").read_text(encoding="utf-8")
ensure_block = text.split("  ensure-draft-release:", 1)[1].split("\n  determine-matrix:", 1)[0]

checks = {
    "single release-create authority": text.count("gh release create") == 1,
    "creation is explicitly draft": "gh release create \"$TAG\" --draft" in text,
    "existing release is forced back to draft": "gh release edit \"$TAG\" --draft=true" in text,
    "draft authority has explicit repo context": "actions/checkout@v5" in ensure_block,
    "draft state is verified before build uploads": "state=$(gh release view \"$TAG\" --json isDraft" in text,
    "asset verification checks draft visibility": "release became public before verification" in text,
    "only final transition publishes": text.count("--draft=false --latest") == 1,
    "upload jobs target existing release": text.count("gh release upload") >= 5,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("release workflow contract failed: " + ", ".join(failed))
print(f"\nworkflow_release: {len(checks)} passed, 0 failed")
