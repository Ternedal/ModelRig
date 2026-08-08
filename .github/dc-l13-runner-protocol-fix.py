from pathlib import Path

path = Path("devcontrol/src/kaliv_dev_control/_local_candidate_materialization_legacy/__init__.py")
text = path.read_text(encoding="utf-8")

old_import = "from typing import Any, Callable, Mapping, TypeVar\n"
new_import = "from typing import Any, Callable, Mapping, Protocol, TypeVar\n"
if text.count(old_import) != 1:
    raise SystemExit("typing import marker mismatch")
text = text.replace(old_import, new_import)

marker = "_MAX_GIT_EXECUTABLE_BYTES = 512 * 1024 * 1024\n\n"
protocol = '''_MAX_GIT_EXECUTABLE_BYTES = 512 * 1024 * 1024


class _GitEvidenceRunner(Protocol):
    """Minimal structural contract consumed by static Git evidence helpers."""

    _transaction_root: Path

    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        maximum: int = _MAX_GIT_OUTPUT_BYTES,
        expected_codes: tuple[int, ...] = (0,),
    ) -> bytes: ...

'''
if text.count(marker) != 1:
    raise SystemExit("protocol insertion marker mismatch")
text = text.replace(marker, protocol)

if text.count("runner: _GitRunner") != 4:
    raise SystemExit("legacy runner annotation count mismatch")
text = text.replace("runner: _GitRunner", "runner: _GitEvidenceRunner")

if "_GitRunner" in text:
    raise SystemExit("legacy runner name survived")

compile(text, str(path), "exec")
path.write_text(text, encoding="utf-8")
