"""Profile-driven diffusers adapter: load order, lease and budget (ModelRig #2296).

torch and diffusers are fakes injected through sys.modules: no GPU, no model
download, no weights. The GPU lease is real (a temporary lease directory).
Ported in spirit from worker/tests/test_qwen_image_adapter.py on the image branch.
"""
import dataclasses
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

from app.diffusers_image_adapter import DiffusersImageAdapter  # noqa: E402
from app.gpu_lease import GpuBusy, GpuLeaseError, acquire_gpu_lease  # noqa: E402
from app.image_gpu_admission import ImageGpuAdmissionError  # noqa: E402
from app.media_generation_contract import GenerationError, GenerationRequest  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402

GPU0 = "GPU-00000000-1111-2222-3333-444444444444"
GPU1 = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
           "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0},cuda:1={GPU1}"}
GIB = 1024**3


class _Image:
    def save(self, output, format):
        assert format == "PNG"
        output.write(b"\x89PNG\r\n\x1a\nfake")


class _Device:
    def __init__(self, index):
        self.index = index

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def fake_modules(calls, free_gib=11.0):
    class FakePipeline:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls.append(("from_pretrained", model_id, kwargs))
            return cls()

        def to(self, device):
            calls.append(("to", device))
            return self

        def enable_model_cpu_offload(self, **kwargs):
            calls.append(("offload", kwargs))

        def __call__(self, **kwargs):
            calls.append(("call", kwargs))
            return types.SimpleNamespace(images=[_Image()])

    class Generator:
        def __init__(self, device):
            self.device = device

        def manual_seed(self, seed):
            calls.append(("seed", self.device, seed))
            return self

    cuda = types.SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 2, device=lambda i: _Device(i),
        mem_get_info=lambda: (int(free_gib * GIB), 12 * GIB),
        get_device_properties=lambda i: types.SimpleNamespace(uuid={0: GPU0, 1: GPU1}[i][len("GPU-"):]),
        empty_cache=lambda: calls.append(("empty_cache",)),
    )
    torch = types.SimpleNamespace(bfloat16="bf16", cuda=cuda, Generator=Generator)
    diffusers = types.SimpleNamespace(StableDiffusionXLPipeline=FakePipeline, FluxPipeline=FakePipeline,
                                      QwenImagePipeline=FakePipeline)
    return {"torch": torch, "diffusers": diffusers}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lease_dir = self.tmp.name
        self.profile = parse_profile(image_profile())
        self.calls = []

    def adapter(self, profile=None, env=OFFLINE, device="cuda:1"):
        return DiffusersImageAdapter(profile or self.profile, device=device, lease_dir=self.lease_dir, env=env)

    def req(self, **kw):
        base = {"profile_id": "sdxl-base", "task": "text_to_image", "prompt": "a lighthouse"}
        base.update(kw)
        return GenerationRequest(**base)

    def test_construction_is_strict(self):
        with self.assertRaises(ValueError):
            DiffusersImageAdapter(parse_profile(video_profile()), device="cuda:1", lease_dir=self.lease_dir)
        with self.assertRaises(ValueError):
            self.adapter(device="cuda:0")
        with self.assertRaises(ValueError):
            self.adapter(profile=dataclasses.replace(self.profile, pipeline="DiffusionPipeline"))
        with self.assertRaises(RuntimeError):
            self.adapter().render(self.req())

    def test_offline_mode_is_required_before_anything_else(self):
        for env in ({}, {"HF_HUB_OFFLINE": "1"}, {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "1"}):
            with self.subTest(env=env), patch("app.diffusers_image_adapter.inspect_cuda_budget") as budget, \
                    patch.dict(sys.modules, fake_modules(self.calls)), self.assertRaises(GenerationError):
                self.adapter(env=env).load()
            budget.assert_not_called()
        self.assertEqual(self.calls, [])
        with acquire_gpu_lease(GPU1, lease_dir=self.lease_dir):
            pass  # no lease was left behind

    def test_missing_or_unordered_gpu_identity_stops_load_before_the_lease(self):
        leases = []
        envs = (
            {k: v for k, v in OFFLINE.items() if k != "KALIV_GPU_DEVICE_UUIDS"},
            {k: v for k, v in OFFLINE.items() if k != "CUDA_DEVICE_ORDER"},
            dict(OFFLINE, KALIV_GPU_DEVICE_UUIDS=f"cuda:0={GPU0}"),
        )
        for env in envs:
            with self.subTest(env=sorted(env)), \
                    patch("app.diffusers_image_adapter.acquire_gpu_lease", side_effect=lambda *a, **k: leases.append(a)), \
                    patch("app.diffusers_image_adapter.inspect_cuda_budget") as budget, \
                    patch.dict(sys.modules, fake_modules(self.calls)), \
                    self.assertRaises((GenerationError, GpuLeaseError)):
                self.adapter(env=env).load()
            budget.assert_not_called()
        self.assertEqual(leases, [])
        self.assertEqual(self.calls, [])

    def test_a_cuda_index_that_is_another_gpu_is_refused_inside_the_lease(self):
        swapped = dict(OFFLINE, KALIV_GPU_DEVICE_UUIDS=f"cuda:0={GPU1},cuda:1={GPU0}")
        with patch.dict(sys.modules, fake_modules(self.calls)), self.assertRaises(ImageGpuAdmissionError):
            self.adapter(env=swapped).load()
        self.assertEqual([c for c in self.calls if c[0] == "from_pretrained"], [])
        with acquire_gpu_lease(GPU0, lease_dir=self.lease_dir):
            pass

    def test_a_busy_gpu_stops_load_before_budget_or_import(self):
        holder = acquire_gpu_lease(GPU1, lease_dir=self.lease_dir)
        self.addCleanup(holder.release)
        with patch("app.diffusers_image_adapter.inspect_cuda_budget") as budget, \
                patch.dict(sys.modules, fake_modules(self.calls)), self.assertRaises(GpuBusy):
            self.adapter().load()
        budget.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_budget_is_checked_while_the_lease_is_held(self):
        seen = []

        def budget(index, **kwargs):
            seen.append((index, kwargs))
            with self.assertRaises(GpuBusy):  # nobody else can take this GPU now
                acquire_gpu_lease(GPU1, lease_dir=self.lease_dir)

        with patch("app.diffusers_image_adapter.inspect_cuda_budget", side_effect=budget), \
                patch.dict(sys.modules, fake_modules(self.calls)):
            adapter = self.adapter()
            adapter.load()
        self.assertEqual(seen, [(1, {"reserve_gib": 2.0, "min_usable_gib": 8.0, "expected_uuid": GPU1})])
        self.assertEqual(self.calls[0], ("from_pretrained", "example/sdxl-base",
                                         {"revision": self.profile.revision, "torch_dtype": "bf16",
                                          "local_files_only": True}))
        self.assertEqual(self.calls[1], ("to", "cuda:1"))
        with self.assertRaises(GpuBusy):  # held for as long as the model is resident
            acquire_gpu_lease(GPU1, lease_dir=self.lease_dir)
        adapter.close()
        with acquire_gpu_lease(GPU1, lease_dir=self.lease_dir):
            pass

    def test_a_failed_budget_or_load_releases_the_lease(self):
        # Keep our own reference to each lease: release must be explicit, not
        # left to garbage collection of the failed load's frame.
        leases = []

        def tracking_acquire(*args, **kwargs):
            lease = acquire_gpu_lease(*args, **kwargs)
            leases.append(lease)
            return lease

        with patch("app.diffusers_image_adapter.acquire_gpu_lease", side_effect=tracking_acquire):
            with patch("app.diffusers_image_adapter.inspect_cuda_budget",
                       side_effect=ImageGpuAdmissionError("insufficient free VRAM")), \
                    patch.dict(sys.modules, fake_modules(self.calls)), self.assertRaises(ImageGpuAdmissionError):
                self.adapter().load()
            self.assertEqual(self.calls, [])
            broken = fake_modules(self.calls)
            broken["diffusers"].StableDiffusionXLPipeline.from_pretrained = classmethod(
                lambda cls, *a, **k: (_ for _ in ()).throw(OSError("weights missing")))
            with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, broken), \
                    self.assertRaises(OSError):
                self.adapter().load()
        self.assertEqual(len(leases), 2)
        self.assertTrue(all(not lease.held for lease in leases), "a failed load must release its lease")
        with acquire_gpu_lease(GPU1, lease_dir=self.lease_dir):
            pass

    def test_profile_resources_decide_admission(self):
        sdxl = parse_profile(image_profile())  # needs 8 GiB usable after a 2 GiB reserve
        flux = parse_profile(image_profile(profile_id="flux-dev", pipeline="FluxPipeline",
                                           resources={"min_usable_gib": 12, "reserve_gib": 2,
                                                      "devices": ["cuda:1"], "cpu_offload": False}))
        with patch.dict(sys.modules, fake_modules(self.calls, free_gib=10.0)):
            ok = self.adapter(profile=sdxl)
            ok.load()
            ok.close()
            with self.assertRaises(ImageGpuAdmissionError):
                self.adapter(profile=flux).load()
        with acquire_gpu_lease(GPU1, lease_dir=self.lease_dir):
            pass

    def test_cpu_offload_profile(self):
        offload = parse_profile(image_profile(resources={"min_usable_gib": 4, "reserve_gib": 1,
                                                         "devices": ["cuda:1"], "cpu_offload": True}))
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls)):
            adapter = self.adapter(profile=offload)
            adapter.load()
            adapter.close()
        self.assertIn(("offload", {"gpu_id": 1}), self.calls)
        self.assertNotIn(("to", "cuda:1"), self.calls)

    def test_render_uses_validated_request_and_returns_png(self):
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls)):
            adapter = self.adapter()
            adapter.load()
            artifact = adapter.render(self.req(width=832, height=1216, steps=12, seed=42))
            with self.assertRaises(GenerationError):
                adapter.render(self.req(prompt="x" * 501))
            adapter.close()
        self.assertEqual(artifact.mime_type, "image/png")
        self.assertTrue(artifact.data.startswith(b"\x89PNG"))
        call = [c for c in self.calls if c[0] == "call"]
        self.assertEqual(len(call), 1, "the over-long prompt never reached the pipeline")
        kwargs = call[0][1]
        self.assertEqual((kwargs["prompt"], kwargs["num_inference_steps"], kwargs["width"], kwargs["height"]),
                         ("a lighthouse", 12, 832, 1216))
        self.assertIn(("seed", "cpu", 42), self.calls)
        self.assertIn(("empty_cache",), self.calls)

    def test_image_to_image_is_not_rendered_by_this_slice(self):
        both = parse_profile(image_profile(tasks=["text_to_image", "image_to_image"]))
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls)):
            adapter = self.adapter(profile=both)
            adapter.load()
            with self.assertRaises(GenerationError):
                adapter.render(self.req(task="image_to_image", input_asset_id="img_1"))
            adapter.close()


if __name__ == "__main__":
    unittest.main()
