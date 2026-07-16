"""Static contract test for the release workflow's visibility boundary.

The workflow is tag-triggered and cannot run on every PR, but its failure
class is mechanical enough to pin statically (analysis 2026-07-16 F-010,
adapted from PR #3 to THIS repo's flow): exactly one job may create a release
and only ever as a draft; a public release is forced back to draft before any
upload; every upload job depends on that guarantee; and publication is the
last explicit transition, after asset verification. Before 1.58.46 each build
job had a `gh release create || true` fallback WITHOUT --draft -- a tag pushed
before the draft existed made the first build publish an empty release and
fill it progressively.
"""
from pathlib import Path

text = Path(".github/workflows/build-and-release.yml").read_text(encoding="utf-8")

checks = {
    "exactly one release-create authority":
        sum(1 for l in text.splitlines()
            if "gh release create" in l and not l.lstrip().startswith("#")) == 1,
    "creation is explicitly draft":
        'gh release create "$TAG" --draft' in text,
    "a public release is forced back to draft before uploads":
        'gh release edit "$TAG" --draft=true' in text,
    "no public create fallback remains":
        "|| true" not in "".join(l for l in text.splitlines() if "gh release create" in l),
    "android uploads wait for the draft guarantee":
        "needs: [server-tests, ensure-draft-release]" in text,
    "desktop uploads wait for the draft guarantee":
        "needs: [server-tests, determine-matrix, ensure-draft-release]" in text,
    "server-binary uploads wait for the draft guarantee":
        "needs: [determine-matrix, server-tests, ensure-draft-release]" in text,
    "publication is an explicit final transition":
        "--draft=false --latest" in text,
    "assets are verified in the same job before publish":
        text.index("MISSING:") < text.index("--draft=false --latest"),
}

passed = failed = 0
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    passed += bool(ok)
    failed += not ok

print(f"\n===== WORKFLOW CONTRACT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
