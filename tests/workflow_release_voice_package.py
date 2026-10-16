"""Release contract: the Windows worker must not silently ship core-only.

This is a static gate in ordinary CI. The separate Windows packaging workflow
then proves the actual PyInstaller EXE imports both voice providers. Neither
test claims a physical CUDA/model/audio pass.
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "tests" / "support"))
from source_code import code_of  # noqa: E402

release = code_of(root / ".github/workflows/build-and-release.yml")
candidate = code_of(root / ".github/workflows/voice-worker-package.yml")
requirements = code_of(root / "worker/requirements-release-voice.txt")

pins = (
    "faster-whisper==1.2.1",
    "soundfile==0.13.1",
    "piper-tts==1.4.2",
)
for pin in pins:
    assert sum(1 for line in requirements.splitlines() if line.strip() == pin) == 1, pin

for name, workflow in (("release", release), ("candidate", candidate)):
    assert "-r worker/requirements-release-voice.txt" in workflow, name
    # app.body_session imports the repo-root bodyrig package. --paths worker
    # alone builds an EXE that fails at boot with ModuleNotFoundError: bodyrig.
    assert "--paths worker --paths ." in workflow, name
    assert "$worker.HasExited" in workflow, name
    for module in ("faster_whisper", "ctranslate2", "soundfile", "piper", "onnxruntime", "av"):
        assert f"--collect-all {module}" in workflow, (name, module)
    assert "8099/capabilities" in workflow, name
    assert "8099/voice/asr/status" in workflow, name
    assert "8099/voice/tts/status" in workflow, name
    assert "$caps.asr -ne $true -or $caps.tts -ne $true" in workflow, name
    assert "$asr.available -ne $true -or $tts.available -ne $true" in workflow, name

assert "pull_request:" in candidate
assert "workflow_dispatch:" in candidate
assert "gh release create" not in candidate
assert "gh release upload" not in candidate
assert "push:" not in candidate
assert "GPL-3.0-or-later" in requirements
print("release voice packaging: pinned deps, frozen EXE smoke, PR gate, no candidate publication PASS")
