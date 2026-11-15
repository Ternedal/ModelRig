"""Read-only check of the image engine's environment on the rig; prints JSON evidence.

  <media venv>\\Scripts\\python scripts\\media_image_env_check.py [--profile PROFILE.json ...]

Run it with the media venv's own Python (deploy/media-image-requirements.txt). It never downloads,
never loads weights and does not render. Exit codes: 0 every check passed, 1 at least one failed
(see "checks"), 2 usage. See worker/app/media_image_env.py and docs/MEDIA_IMAGE_RIG_QUALIFICATION.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

from app.media_generation_contract import GenerationError  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_image_env import (  # noqa: E402
    check_environment,
    check_profile_snapshot,
    hub_cache,
    load_modules,
    report,
)


def main(argv: list[str], env=None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", action="append", default=[], help="an image profile JSON to check against the cache")
    args = parser.parse_args(argv)
    modules = load_modules()
    checks = check_environment(modules, env)
    cache = hub_cache(env, modules)
    for path in args.profile:
        try:
            with open(path, encoding="utf-8") as handle:
                profile = parse_profile(json.load(handle))
        except (OSError, ValueError, GenerationError) as exc:
            checks.append({"name": f"profile:{os.path.basename(path)}", "ok": False, "detail": str(exc)})
            continue
        if profile.modality != "image":
            checks.append({"name": f"profile:{profile.profile_id}", "ok": False, "detail": "not an image profile"})
            continue
        checks += check_profile_snapshot(profile, cache)
    result = report(checks, env)
    result["hub_cache"] = str(cache)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
