"""The image engine's rig-readiness check (#2275 backlog item 4).

Everything here runs offline with fake modules. CI has no torch or diffusers; the real pinned
versions are checked by scripts/media_image_env_check.py on the rig (and were checked offline
against the pinned diffusers when the pins were chosen).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

from app.media_generation_contract import GenerationError
from app.media_generation_profiles import DIFFUSERS_PIPELINES, parse_profile
from app.media_image_env import (
    PINNED_VERSIONS,
    check_environment,
    check_profile_snapshot,
    hub_cache,
    report,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "media-profiles" / "sdxl-base-1.0.json.example"
REQUIREMENTS = ROOT / "deploy" / "media-image-requirements.txt"
REV = "0123456789abcdef0123456789abcdef01234567"


def module(name: str, version: str, **attrs) -> ModuleType:
    value = ModuleType(name)
    value.__version__ = version
    for key, item in attrs.items():
        setattr(value, key, item)
    return value


class GoodPipeline:
    interrupt = property(lambda self: self._interrupt)

    def __call__(self, prompt=None, num_inference_steps=50, width=None, height=None, generator=None,
                 callback_on_step_end=None):
        self._interrupt = False
        for _ in range(num_inference_steps):
            if self.interrupt:
                continue
        return None

    def enable_model_cpu_offload(self, gpu_id=None):
        return None


class NoCallback(GoodPipeline):
    def __call__(self, prompt=None, num_inference_steps=50, width=None, height=None, generator=None):
        self._interrupt = False
        if self.interrupt:
            return None


class NeverResets(GoodPipeline):
    def __call__(self, prompt=None, num_inference_steps=50, width=None, height=None, generator=None,
                 callback_on_step_end=None):
        if self.interrupt:
            return None


def fake_torch(devices=((8, 6, "NVIDIA GeForce RTX 3060", 12 * 2 ** 30),) * 2, available=True):
    cuda = SimpleNamespace(
        is_available=lambda: available,
        device_count=lambda: len(devices),
        get_device_capability=lambda i: devices[i][:2],
        get_device_name=lambda i: devices[i][2],
        get_device_properties=lambda i: SimpleNamespace(total_memory=devices[i][3]),
    )
    return module("torch", "2.8.0+cu126", cuda=cuda)


def good_modules(**overrides):
    diffusers = module("diffusers", PINNED_VERSIONS["diffusers"], **{name: GoodPipeline for name in DIFFUSERS_PIPELINES})
    modules = {name: module(name, version) for name, version in PINNED_VERSIONS.items()}
    modules["torch"] = fake_torch()
    modules["diffusers"] = diffusers
    modules.update(overrides)
    return modules


def by_name(checks):
    return {c["name"]: c for c in checks}


class EnvironmentTests(unittest.TestCase):
    def test_a_good_environment_passes_every_check(self):
        checks = check_environment(good_modules(), {})
        result = report(checks, {})
        self.assertTrue(result["ok"], [c for c in checks if not c["ok"]])
        self.assertEqual(result["offline_switches_in_this_shell"],
                         {"HF_HUB_OFFLINE": "unset", "TRANSFORMERS_OFFLINE": "unset"},
                         "information only: the executor sets them itself")
        devices = by_name(checks)["cuda:available"]["detail"]["devices"]
        self.assertEqual([(d["capability"], d["bf16"], d["total_gib"]) for d in devices], [("8.6", True, 12.0)] * 2)

    def test_a_cuda_local_label_matches_its_public_pin(self):
        self.assertTrue(by_name(check_environment(good_modules(), {}))["version:torch"]["ok"])

    def test_a_wrong_or_missing_version_fails(self):
        checks = by_name(check_environment(good_modules(diffusers=module("diffusers", "0.36.0"), accelerate="ImportError"), {}))
        self.assertFalse(checks["version:diffusers"]["ok"])
        self.assertEqual(checks["version:accelerate"]["detail"], "not importable (ImportError)")

    def test_no_cuda_or_a_card_without_bf16_fails(self):
        none = by_name(check_environment(good_modules(torch=fake_torch(available=False)), {}))
        self.assertFalse(none["cuda:available"]["ok"])
        self.assertEqual((none["cuda:bf16"]["ok"], none["cuda:bf16"]["detail"]), (False, "no CUDA device"))
        turing = fake_torch(devices=((7, 5, "NVIDIA GeForce RTX 2080", 8 * 2 ** 30),))
        checks = by_name(check_environment(good_modules(torch=turing), {}))
        self.assertTrue(checks["cuda:available"]["ok"])
        self.assertFalse(checks["cuda:bf16"]["ok"])
        self.assertEqual(checks["cuda:bf16"]["detail"], ["NVIDIA GeForce RTX 2080"])

    def test_a_pipeline_without_the_callback_or_the_interrupt_reset_fails(self):
        for broken, problem in ((NoCallback, "__call__ lacks callback_on_step_end"),
                                (NeverResets, "__call__ does not reset the interrupt flag")):
            with self.subTest(broken=broken.__name__):
                diffusers = module("diffusers", PINNED_VERSIONS["diffusers"],
                                   **{name: GoodPipeline for name in DIFFUSERS_PIPELINES})
                setattr(diffusers, "FluxPipeline", broken)
                checks = by_name(check_environment(good_modules(diffusers=diffusers), {}))
                self.assertFalse(checks["pipeline:FluxPipeline"]["ok"])
                self.assertIn(problem, checks["pipeline:FluxPipeline"]["detail"])
                self.assertTrue(checks["pipeline:StableDiffusionXLPipeline"]["ok"])

    def test_a_missing_pipeline_class_fails(self):
        diffusers = module("diffusers", PINNED_VERSIONS["diffusers"], StableDiffusionXLPipeline=GoodPipeline)
        checks = by_name(check_environment(good_modules(diffusers=diffusers), {}))
        self.assertEqual(checks["pipeline:QwenImagePipeline"]["detail"], "not in this diffusers")

    def test_nothing_checked_is_not_ok(self):
        self.assertFalse(report([], {})["ok"])


class PinTests(unittest.TestCase):
    def test_the_requirements_file_and_the_check_pin_the_same_versions(self):
        pins = {}
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                name, version = line.split("==")
                pins[name.replace("-", "_")] = version
        self.assertEqual(pins, PINNED_VERSIONS)

    def test_the_check_module_imports_no_engine_at_module_level(self):
        source = (ROOT / "worker" / "app" / "media_image_env.py").read_text(encoding="utf-8")
        top = [line for line in source.splitlines() if re.match(r"(import|from) ", line)]
        self.assertFalse([line for line in top if re.search(r"\b(torch|diffusers|transformers|accelerate)\b", line)])


class ProfileTemplateTests(unittest.TestCase):
    def template(self):
        return json.loads(TEMPLATE.read_text(encoding="utf-8"))

    def test_the_template_is_refused_until_its_revision_is_pinned(self):
        with self.assertRaisesRegex(GenerationError, "revision"):
            parse_profile(self.template())

    def test_the_pinned_template_is_a_default_off_candidate_image_profile(self):
        profile = parse_profile({**self.template(), "revision": REV})
        self.assertEqual((profile.modality, profile.backend, profile.pipeline), ("image", "diffusers", "StableDiffusionXLPipeline"))
        self.assertEqual(profile.qualification, "candidate", "needs KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1 as well")
        self.assertEqual(profile.license, "openrail++")
        self.assertEqual(profile.resources.devices, ("cuda:1",))
        self.assertFalse(profile.resources.cpu_offload)
        self.assertTrue(TEMPLATE.name.endswith(".json.example"), "a profile directory loads only *.json")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.profile = parse_profile({**json.loads(TEMPLATE.read_text(encoding="utf-8")), "revision": REV})
        self.snapshot = self.tmp / "models--stabilityai--stable-diffusion-xl-base-1.0" / "snapshots" / REV
        index = {"_class_name": "StableDiffusionXLPipeline", "unet": ["diffusers", "UNet2DConditionModel"],
                 "vae": ["diffusers", "AutoencoderKL"], "scheduler": ["diffusers", "EulerDiscreteScheduler"],
                 "tokenizer": ["transformers", "CLIPTokenizer"], "image_encoder": [None, None]}
        self.snapshot.mkdir(parents=True)
        (self.snapshot / "model_index.json").write_text(json.dumps(index), encoding="utf-8")
        for name, config in (("unet", "config.json"), ("vae", "config.json"), ("scheduler", "scheduler_config.json"),
                             ("tokenizer", "tokenizer_config.json")):
            (self.snapshot / name).mkdir()
            (self.snapshot / name / config).write_text("{}", encoding="utf-8")
        for name in ("unet", "vae"):
            (self.snapshot / name / "diffusion_pytorch_model.safetensors").write_bytes(b"x")

    def test_a_complete_snapshot_passes(self):
        (check,) = check_profile_snapshot(self.profile, self.tmp)
        self.assertTrue(check["ok"], check)

    def test_a_missing_revision_or_weights_fail(self):
        (self.snapshot / "unet" / "diffusion_pytorch_model.safetensors").unlink()
        (check,) = check_profile_snapshot(self.profile, self.tmp)
        self.assertEqual(check["detail"], ["unet/ has no .safetensors weights"])
        other = parse_profile({**json.loads(TEMPLATE.read_text(encoding="utf-8")), "revision": "f" * 40})
        (check,) = check_profile_snapshot(other, self.tmp)
        self.assertFalse(check["ok"])
        self.assertIn("no model_index.json", check["detail"])

    def test_the_cache_location_follows_the_hub_and_the_environment(self):
        hub = module("huggingface_hub", "0.35.3", constants=SimpleNamespace(HF_HUB_CACHE="/x/hub"))
        self.assertEqual(hub_cache({}, {"huggingface_hub": hub}), Path("/x/hub"))
        self.assertEqual(hub_cache({"HF_HOME": "/h"}, {}), Path("/h") / "hub")
        self.assertEqual(hub_cache({"HF_HUB_CACHE": "/c", "HF_HOME": "/h"}, {}), Path("/c"))


class ScriptTests(unittest.TestCase):
    def test_the_script_reports_json_and_fails_without_the_engine(self):
        # CI has no torch/diffusers: every engine check fails, exit 1, and the output is still JSON.
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "media_image_env_check.py")],
                                   capture_output=True, text=True, timeout=120,
                                   env={**os.environ, "PYTHONPATH": str(ROOT / "worker")})
        result = json.loads(completed.stdout)
        if all(c["ok"] for c in result["checks"]):
            self.skipTest("this interpreter has the full pinned engine and a CUDA device")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(result["format"], "kaliv-media-image-env/v1")
        self.assertIn("version:diffusers", {c["name"] for c in result["checks"]})


if __name__ == "__main__":
    unittest.main()
