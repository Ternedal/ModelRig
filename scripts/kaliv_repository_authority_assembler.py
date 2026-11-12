#!/usr/bin/env python3
"""Assemble the evidence file the repository_authority release gate qualifies.

``kaliv_repository_authority_qualifier.py`` validates a file with one entry per
core repository. Until now nothing produced that file: the four entries, their
Git SHAs and their evidence references had to be typed by hand, which is not
evidence. This tool builds it from the verdicts the four repositories' own
``verify-repository-authority.ps1 -Json`` print.

What it does
------------
- Reads one captured verdict per repository, exactly as the verifier wrote it.
- Refuses a verdict that is not that repository's format, is not a PASS, is not
  for ``main``, claims any other authority, or is for another commit than the
  pin the operator names.
- Derives each evidence reference from the verdict file's own bytes, so the
  reference cannot be reused for another file.
- Hands the assembled bytes to the qualifier before anything is written.

What it does not do
-------------------
It reads no GitHub setting and runs no verifier. It changes no repository
setting, activates nothing and writes only the files named on the command
line. A PASS here says that four verdict files agree with four pins; whether a
verdict was produced by the verifier at that commit is for the reviewer.

Run
---
    python scripts/kaliv_repository_authority_assembler.py \
        --modelrig  <dir>/modelrig.json  --pin-modelrig  <sha> \
        --bodyrig   <dir>/bodyrig.json   --pin-bodyrig   <sha> \
        --visionrig <dir>/visionrig.json --pin-visionrig <sha> \
        --voicerig  <dir>/voicerig.json  --pin-voicerig  <sha> \
        --output <dir>/repository-authority-evidence.json

Exit code 0: the evidence file and its assembly record are written.
Exit code 2: see below.

What a failed run leaves behind
-------------------------------
- **A refusal writes nothing.** That is everything about the verdicts, the
  pins, an output that already exists with other content, and the qualifier's
  answer. All of it is decided before the first output file is created.
- **An I/O failure while publishing can leave the set incomplete**: the
  evidence file without its record, or both without the report. The files are
  published in that order, each complete or not at all, and never over a file
  with other content. A published evidence file has already been accepted by
  the qualifier. The message names what was published; running the same
  command again completes the set.
- Each output is first written to a uniquely named ``.<name>.<random>.staged``
  file beside its target. A run that is killed can leave such a file. It is
  never read and can be deleted.

The report (``--report``) is the qualifier's latest verdict. The next run
replaces it. It is not immutable release evidence; refer to the evidence file
and the record.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True

RECORD_SCHEMA = "kaliv-repository-authority-assembly/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_MAX_VERDICT_BYTES = 1024 * 1024

# slot -> (repository, verdict format, the verdict carries github_head_revision)
#
# ModelRig's and BodyRig's verifiers report GitHub's head as ``head_revision``
# and fail the verdict when it differs from the checkout. VisionRig's and
# VoiceRig's report the checkout and GitHub's head as two fields.
REPOSITORIES: dict[str, tuple[str, str, bool]] = {
    "modelrig": ("Ternedal/ModelRig", "modelrig-repository-authority", False),
    "bodyrig": ("Ternedal/BodyRig", "bodyrig-repository-authority", False),
    "visionrig": ("Ternedal/VisionRig", "visionrig-repository-authority", True),
    "voicerig": ("Ternedal/VoiceRig", "voicerig-repository-authority", True),
}

# A file redirected from PowerShell is not always UTF-8: Windows PowerShell 5.1
# writes UTF-16 with ``>`` and a byte-order mark with ``-Encoding utf8``. The
# mark names the encoding, so nothing is guessed.
_BOMS: tuple[tuple[bytes, str, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8", "utf-8-bom"),
    (b"\xff\xfe", "utf-16-le", "utf-16-le-bom"),
    (b"\xfe\xff", "utf-16-be", "utf-16-be-bom"),
)


class AssemblerError(RuntimeError):
    pass


def _pin(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AssemblerError(f"{label} must be a lowercase 40-hex Git SHA")
    return value


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite number {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def read_verdict(path: Path, label: str) -> tuple[dict[str, Any], bytes, str]:
    """Return the verdict object, the file's exact bytes and its encoding."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise AssemblerError(f"{label} verdict file cannot be read") from exc
    if len(raw) > _MAX_VERDICT_BYTES:
        raise AssemblerError(f"{label} verdict file is too large")
    encoding, name, body = "utf-8", "utf-8", raw
    for mark, codec, codec_name in _BOMS:
        if raw.startswith(mark):
            encoding, name, body = codec, codec_name, raw[len(mark):]
            break
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError as exc:
        raise AssemblerError(
            f"{label} verdict file is not UTF-8, or UTF-16 with a byte-order mark"
        ) from exc
    if not text.strip():
        raise AssemblerError(
            f"{label} verdict file is empty; the verifier printed no verdict"
        )
    try:
        parsed = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except ValueError as exc:
        raise AssemblerError(
            f"{label} verdict file must hold exactly the one JSON verdict that "
            f"verify-repository-authority.ps1 -Json prints ({exc})"
        ) from exc
    if not isinstance(parsed, dict):
        raise AssemblerError(f"{label} verdict must be a JSON object")
    return parsed, raw, name


def check_verdict(slot: str, verdict: Mapping[str, Any], pin: str) -> str:
    """Validate one verdict against its slot and pin; return the pinned SHA."""
    repository, expected_format, has_github_head = REPOSITORIES[slot]

    def refuse(reason: str) -> AssemblerError:
        return AssemblerError(f"{repository} verdict refused: {reason}")

    if verdict.get("format") != expected_format:
        raise refuse(
            f"format is {verdict.get('format')!r}, expected {expected_format!r}"
        )
    version = verdict.get("version")
    if type(version) is not int or version != 1:
        raise refuse("version is not 1")
    if verdict.get("repository") != repository:
        raise refuse(f"it is for repository {verdict.get('repository')!r}")
    if verdict.get("branch") != "main":
        raise refuse("it is not for branch main")
    if verdict.get("passed") is not True:
        raise refuse("passed is not true")
    errors = verdict.get("errors")
    if not isinstance(errors, list) or errors:
        raise refuse("errors is not an empty list")
    if verdict.get("protected") is not True:
        raise refuse("protected is not true")
    mode = verdict.get("authority_mode")
    if not isinstance(mode, str) or not mode.strip():
        raise refuse("authority_mode is missing")
    if verdict.get("production_activation") is not False:
        raise refuse("production_activation is not false")
    # Defence in depth, by naming convention only. An authority field with
    # another kind of name would pass this loop. What bounds the schema is the
    # format and version check above: a new format has to be added on purpose.
    for key, value in verdict.items():
        if key.endswith(("_authority", "_activation")) and value is not False:
            raise refuse(f"{key} is not false")

    head = verdict.get("head_revision")
    if not isinstance(head, str) or _SHA40.fullmatch(head) is None:
        raise refuse("head_revision is not a lowercase 40-hex Git SHA")
    if has_github_head or "github_head_revision" in verdict:
        if verdict.get("github_head_revision") != head:
            raise refuse("GitHub's main was not on the verified checkout's commit")
    if head != pin:
        raise refuse(f"it is for commit {head}, but the pin is {pin}")
    return head


def load_qualifier() -> Any:
    script = Path(__file__).resolve().parent / "kaliv_repository_authority_qualifier.py"
    spec = importlib.util.spec_from_file_location(
        "_kaliv_repository_authority_qualifier", script
    )
    if spec is None or spec.loader is None:
        raise AssemblerError("the repository-authority qualifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _holds(path: Path, data: bytes) -> bool:
    try:
        return path.is_file() and path.read_bytes() == data
    except OSError:
        return False


def _other_content(path: Path, label: str) -> AssemblerError:
    return AssemblerError(
        f"{label} {path.name} already exists with other content; "
        "move it away before assembling again"
    )


def _stage(target: Path, data: bytes) -> Path:
    """Write ``data`` to a new, uniquely named file beside ``target``.

    The file is read back before it is returned, so what gets published is
    known to be the bytes the qualifier accepted.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".staged"
    )
    path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not _holds(path, data):
            raise OSError(f"the staged copy of {target.name} does not read back as written")
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return path


def _create_exclusively(target: Path, data: bytes) -> None:
    handle = open(target, "xb")  # FileExistsError if the target exists
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not _holds(target, data):
            raise OSError(f"{target.name} does not read back as written")
    except BaseException:
        # This call created the file, so it may remove its own partial write.
        with contextlib.suppress(OSError):
            target.unlink()
        raise


def _publish_new(staged: Path, target: Path, data: bytes, label: str) -> None:
    """Give ``target`` the staged bytes; never replace a file with other content.

    A hard link is atomic and refuses an existing target, so two runs cannot
    overwrite each other and no reader sees a half-written file.
    """
    try:
        try:
            os.link(staged, target)
        except FileExistsError:
            raise
        except OSError:
            # No hard links on this file system. Still exclusive, not atomic.
            _create_exclusively(target, data)
    except FileExistsError:
        if not _holds(target, data):
            raise _other_content(target, label) from None


def assemble(
    *,
    verdict_files: Mapping[str, Path],
    pins: Mapping[str, str],
    output: Path,
    record: Path,
    report: Path | None = None,
    qualifier: Any = None,
) -> dict[str, Any]:
    if set(verdict_files) != set(REPOSITORIES) or set(pins) != set(REPOSITORIES):
        raise AssemblerError(
            "exactly one verdict file and one pin per core repository are required"
        )
    qual = qualifier if qualifier is not None else load_qualifier()

    targets = {"output": Path(output), "record": Path(record)}
    if report is not None:
        targets["report"] = Path(report)
    resolved_targets = {name: path.resolve() for name, path in targets.items()}
    if len(set(resolved_targets.values())) != len(resolved_targets):
        raise AssemblerError("output, record and report must be different files")
    inputs = {slot: Path(path).resolve() for slot, path in verdict_files.items()}
    if len(set(inputs.values())) != len(inputs):
        raise AssemblerError("each repository needs its own verdict file")
    for name, path in resolved_targets.items():
        if path in inputs.values():
            raise AssemblerError(f"{name} must not replace a verdict file")

    entries: dict[str, dict[str, Any]] = {}
    described: list[dict[str, Any]] = []
    for slot, (repository, _format, _has_github_head) in REPOSITORIES.items():
        pin = _pin(pins[slot], f"--pin-{slot}")
        verdict, raw, encoding = read_verdict(verdict_files[slot], repository)
        head = check_verdict(slot, verdict, pin)
        digest = hashlib.sha256(raw).hexdigest()
        entries[repository] = {
            "repository": repository,
            "git_sha": head,
            "live_repository_authority_passed": True,
            "evidence_ref": (
                f"repository-authority-verdict:{repository}:{head}:sha256:{digest}"
            ),
        }
        described.append(
            {
                "repository": repository,
                "file": Path(verdict_files[slot]).name,
                "sha256": digest,
                "bytes": len(raw),
                "encoding": encoding,
                "format": verdict["format"],
                "head_revision": head,
                "authority_mode": verdict["authority_mode"],
                "required_status_checks": verdict.get("required_status_checks"),
            }
        )

    evidence = {
        "schema": qual.SCHEMA,
        "repositories": [entries[repo] for repo in qual.REQUIRED_REPOSITORIES],
        "production_activation": False,
    }
    rendered = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        # The qualifier sees the exact bytes that are about to be written.
        verdict = qual.qualify(json.loads(rendered.decode("utf-8")))
    except qual.RepositoryAuthorityQualificationError as exc:
        raise AssemblerError(f"the qualifier refused the assembled evidence: {exc}") from exc
    if verdict.get("repository_authority_gate_satisfied") is not True:
        raise AssemblerError("the qualifier did not accept the assembled evidence")

    assembly = {
        "schema": RECORD_SCHEMA,
        "evidence": {
            "file": Path(output).name,
            "sha256": hashlib.sha256(rendered).hexdigest(),
        },
        "release_evidence_ref": verdict["release_evidence_ref"],
        "pins": {REPOSITORIES[slot][0]: pins[slot] for slot in REPOSITORIES},
        "verdicts": described,
        "limitations": [
            "This record is not a qualification verdict. Run "
            "kaliv_repository_authority_qualifier.py on the evidence file.",
            "The assembler reads verdict files. It reads no GitHub setting and "
            "cannot tell which copy of a verifier wrote a verdict, or when.",
            "A verdict is a reading of the settings at the moment it was taken. "
            "It says nothing about the settings before or after.",
            "The qualifier sees the evidence file only. The verdict files are a "
            "separate trust boundary that a reviewer checks by the hashes here.",
            "A report written with --report is the qualifier's latest verdict and "
            "is replaced by the next run. It is not immutable release evidence.",
        ],
        "production_activation": False,
    }
    record_bytes = (json.dumps(assembly, indent=2, sort_keys=True) + "\n").encode("utf-8")

    # Refusals end here: nothing has been created yet.
    for name, data in (("output", rendered), ("record", record_bytes)):
        if targets[name].exists() and not _holds(targets[name], data):
            raise _other_content(targets[name], name)

    staged: list[Path] = []
    published: list[str] = []
    try:
        staged_output = _stage(targets["output"], rendered)
        staged.append(staged_output)
        staged_record = _stage(targets["record"], record_bytes)
        staged.append(staged_record)
        staged_report = None
        if report is not None:
            staged_report = _stage(targets["report"], b"")
            staged.append(staged_report)
            # The qualifier's own command line reads the staged evidence file,
            # which is the file about to be published, and writes its report.
            # The report is the qualifier's and not a copy; a refusal here
            # still publishes nothing.
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = qual.main([str(staged_output), "--report", str(staged_report)])
            except OSError:
                raise
            except Exception as exc:
                raise AssemblerError(
                    f"the qualifier's command line failed on the staged evidence file: {exc}"
                ) from exc
            if code != 0:
                raise AssemblerError(
                    "the qualifier's command line refused the staged evidence file"
                )

        # Publication, in a fixed order. Each step adds one complete file.
        _publish_new(staged_output, targets["output"], rendered, "output")
        published.append(targets["output"].name)
        _publish_new(staged_record, targets["record"], record_bytes, "record")
        published.append(targets["record"].name)
        if staged_report is not None:
            os.replace(staged_report, targets["report"])
            published.append(targets["report"].name)
    except (OSError, AssemblerError) as exc:
        reason = str(exc) if isinstance(exc, AssemblerError) else f"a file could not be written: {exc}"
        if not published:
            if isinstance(exc, AssemblerError):
                raise
            raise AssemblerError(f"{reason}; nothing was published") from exc
        raise AssemblerError(
            f"{reason}; already published, complete and accepted by the qualifier: "
            f"{', '.join(published)}. Run the same command again to complete the set"
        ) from exc
    finally:
        for path in staged:
            with contextlib.suppress(OSError):
                path.unlink()
    return assembly


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble repository_authority evidence from the four verifiers' "
            "-Json verdicts. Reads files only; changes no repository setting."
        )
    )
    for slot, (repository, _format, _has_github_head) in REPOSITORIES.items():
        parser.add_argument(
            f"--{slot}",
            type=Path,
            required=True,
            metavar="FILE",
            help=f"captured -Json verdict from {repository}",
        )
        parser.add_argument(
            f"--pin-{slot}",
            required=True,
            metavar="SHA",
            help=f"the release pin for {repository} (40 hex, lowercase)",
        )
    parser.add_argument("--output", type=Path, required=True, help="evidence file to write")
    parser.add_argument(
        "--record",
        type=Path,
        help="assembly record to write (default: <output stem>-assembly.json)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help=(
            "also let the qualifier write its latest verdict here; the next run "
            "replaces it, so it is not immutable release evidence"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    record = args.record
    if record is None:
        record = args.output.with_name(args.output.stem + "-assembly.json")
    try:
        assembly = assemble(
            verdict_files={slot: getattr(args, slot) for slot in REPOSITORIES},
            pins={slot: getattr(args, f"pin_{slot}") for slot in REPOSITORIES},
            output=args.output,
            record=record,
            report=args.report,
        )
    except AssemblerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(assembly, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
