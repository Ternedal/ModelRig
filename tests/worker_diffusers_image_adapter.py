"""Profile-driven diffusers adapter: load order, lease and budget (ModelRig #2296).

torch and diffusers are fakes injected through sys.modules: no GPU, no model
download, no weights. The GPU lease is real (a temporary lease directory).
Ported in spirit from worker/tests/test_qwen_image_adapter.py on the image branch.
"""
import dataclasses
import gc
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

import app.diffusers_image_adapter as adapter_module  # noqa: E402
from app.diffusers_image_adapter import (  # noqa: E402
    DiffusersImageAdapter, GpuResourcesRetained, quarantined_gpus, release_proven_free,
)
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


class FakeAllocator:
    """Stands in for torch's CUDA caching allocator: bytes held by live FakeTensors."""

    def __init__(self):
        self.allocated = 0
        self.broken = False

    def memory_allocated(self, index):
        if self.broken:
            raise RuntimeError("CUDA error: an illegal memory access was encountered")
        return self.allocated


class FakeTensor:
    def __init__(self, allocator, nbytes):
        self.allocator, self.nbytes = allocator, nbytes
        allocator.allocated += nbytes

    def __del__(self):
        self.allocator.allocated -= self.nbytes


def fake_modules(calls, free_gib=11.0, allocator=None, hook_cache=None, workspace_api=True):
    allocator = allocator or FakeAllocator()
    workspaces = []  # torch keeps cuBLAS workspaces per handle, outside any model

    class FakePipeline:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls.append(("from_pretrained", model_id, kwargs))
            return cls()

        def to(self, device):
            calls.append(("to", device))
            self.weights = FakeTensor(allocator, 1 * GIB)  # the model is now resident
            if hook_cache is not None:
                hook_cache.append(self)  # e.g. an offload hook registry that outlives the adapter
            return self

        def enable_model_cpu_offload(self, **kwargs):
            calls.append(("offload", kwargs))

        def __call__(self, **kwargs):
            calls.append(("call", kwargs))
            if not workspaces:
                workspaces.append(FakeTensor(allocator, 32 * 1024 * 1024))
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
        memory_allocated=allocator.memory_allocated,
        synchronize=lambda index: calls.append(("synchronize", index)),
    )
    def clear_workspaces():
        calls.append(("clear_cublas_workspaces",))
        workspaces.clear()

    torch_c = types.SimpleNamespace(_cuda_clearCublasWorkspaces=clear_workspaces) if workspace_api else types.SimpleNamespace()
    torch = types.SimpleNamespace(bfloat16="bf16", cuda=cuda, Generator=Generator, _C=torch_c)
    diffusers = types.SimpleNamespace(StableDiffusionXLPipeline=FakePipeline, FluxPipeline=FakePipeline,
                                      QwenImagePipeline=FakePipeline)
    return {"torch": torch, "diffusers": diffusers}


def partial_load_fakes(calls, *, keep_pipeline=None, keep_exception=None, interrupt=False, chained=False):
    """Pipeline.to() allocates 6 GiB of 'weights' and then fails, like an OOM half-way."""
    allocator = FakeAllocator()
    modules = fake_modules(calls, allocator=allocator)
    pipeline_class = modules["diffusers"].StableDiffusionXLPipeline

    def failing_to(pipe, device):
        pipe.weights = FakeTensor(allocator, 6 * GIB)
        pipe.hooks = [pipe]  # a reference cycle, as module hooks create: only gc frees it
        if keep_pipeline is not None:
            keep_pipeline.append(pipe)  # a library cache that outlives the call
        error = KeyboardInterrupt() if interrupt else RuntimeError("CUDA out of memory (partial load)")
        if chained:  # the real cause sits one level down, in a frame that still holds the pipeline
            def inner(module):
                raise ValueError(f"cannot move {type(module).__name__}")
            try:
                inner(pipe)
            except ValueError as cause:
                error.__cause__ = cause
        if keep_exception is not None:
            try:
                raise error
            except BaseException as exc:
                keep_exception.append(exc)  # e.g. an error tracker keeping the last exception
                raise
        raise error

    pipeline_class.to = failing_to
    return modules, allocator


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self.empty_quarantine)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lease_dir = self.tmp.name
        self.profile = parse_profile(image_profile())
        self.calls = []

    @staticmethod
    def empty_quarantine():
        """Test isolation only: the quarantine is process-wide by design."""
        for entry in list(adapter_module._QUARANTINE):
            entry.lease.release()
            adapter_module._QUARANTINE.remove(entry)

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
                    self.assertRaisesRegex(GenerationError, "OSError"):
                self.adapter().load()
        self.assertEqual(len(leases), 2)
        self.assertTrue(all(not lease.held for lease in leases), "a failed load must release its lease")
        with acquire_gpu_lease(GPU1, lease_dir=self.lease_dir):
            pass

    # --- #2315 review 4411189866: a failed load must not free the GPU while the model is resident ----
    def partial_load_modules(self, **kwargs):
        return partial_load_fakes(self.calls, **kwargs)

    def other_executor_can_take_the_gpu(self) -> bool:
        """A separate process that takes the same lease, as a second executor would."""
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from app.gpu_lease import acquire_gpu_lease, GpuBusy\n"
                "try:\n    acquire_gpu_lease(%r, lease_dir=%r).release(); print('free')\n"
                "except GpuBusy:\n    print('busy')\n") % (str(Path(__file__).resolve().parents[1] / "worker"),
                                                        GPU1, self.lease_dir)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn(out.stdout.strip(), ("free", "busy"), out.stderr)
        return out.stdout.strip() == "free"

    def test_partial_load_failure_is_cleaned_up_before_the_lease_is_released(self):
        modules, allocator = self.partial_load_modules()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            adapter = self.adapter()
            with self.assertRaisesRegex(GenerationError, "verified released") as caught:
                adapter.load()
        self.assertIsNone(caught.exception.__context__, "the error must not chain to the frames that held the model")
        self.assertEqual(allocator.allocated, 0)
        self.assertFalse(adapter.retains_gpu)
        self.assertIn(("synchronize", 1), self.calls)
        self.assertTrue(self.other_executor_can_take_the_gpu())

    def test_an_exception_kept_elsewhere_does_not_pin_the_model(self):
        kept = []
        modules, allocator = self.partial_load_modules(keep_exception=kept)
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(GenerationError, "verified released"):
                self.adapter().load()
        self.assertEqual(len(kept), 1, "someone still holds the original exception")
        self.assertIsNone(kept[0].__traceback__, "its frames were cleared")
        self.assertEqual(allocator.allocated, 0)
        self.assertTrue(self.other_executor_can_take_the_gpu())

    def test_a_kept_chained_exception_does_not_pin_the_model(self):
        kept = []
        modules, allocator = self.partial_load_modules(keep_exception=kept, chained=True)
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(GenerationError, "verified released"):
                self.adapter().load()
        self.assertIsNotNone(kept[0].__cause__)
        self.assertIsNone(kept[0].__cause__.__traceback__, "the chained cause's frames were cleared too")
        self.assertEqual(allocator.allocated, 0)

    def test_memory_still_resident_keeps_the_lease_until_it_is_gone(self):
        cache = []
        modules, allocator = self.partial_load_modules(keep_pipeline=cache)
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            adapter = self.adapter()
            with self.assertRaises(GpuResourcesRetained):
                adapter.load()
            self.assertEqual(allocator.allocated, 6 * GIB)
            self.assertTrue(adapter.retains_gpu)
            self.assertFalse(self.other_executor_can_take_the_gpu(),
                             "a second executor must not get a GPU that still holds the failed model")
            with self.assertRaises(GpuResourcesRetained):
                adapter.load()  # refused without touching the GPU again
            adapter.close()
            self.assertFalse(self.other_executor_can_take_the_gpu(), "close() keeps it while memory is resident")
            cache.clear()
            gc.collect()
            adapter.close()
        self.assertFalse(adapter.retains_gpu)
        self.assertTrue(self.other_executor_can_take_the_gpu(), "released once the memory is measurably gone")

    def test_a_broken_cuda_context_proves_nothing_and_keeps_the_lease(self):
        modules, allocator = self.partial_load_modules()
        real_to = modules["diffusers"].StableDiffusionXLPipeline.to

        def to_then_break(pipe, device):
            allocator.broken = True
            return real_to(pipe, device)

        modules["diffusers"].StableDiffusionXLPipeline.to = to_then_break
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            adapter = self.adapter()
            with self.assertRaises(GpuResourcesRetained):
                adapter.load()
        self.assertFalse(self.other_executor_can_take_the_gpu())

    def test_an_interrupt_mid_load_keeps_the_lease(self):
        modules, _ = self.partial_load_modules(interrupt=True)
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
            adapter = self.adapter()
            with self.assertRaises(KeyboardInterrupt):
                adapter.load()
        self.assertTrue(adapter.retains_gpu)
        self.assertFalse(self.other_executor_can_take_the_gpu())

    def test_a_failing_baseline_read_releases_before_any_model_load(self):
        allocator = FakeAllocator()
        allocator.broken = True
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator)), self.assertRaises(RuntimeError):
            self.adapter().load()
        self.assertEqual([c for c in self.calls if c[0] == "from_pretrained"], [])
        self.assertTrue(self.other_executor_can_take_the_gpu())

    # --- #2315 review 5696815799: a successful load's close() follows the same rule ------------------
    def test_close_releases_once_the_model_is_measurably_gone(self):
        allocator = FakeAllocator()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator)):
            adapter = self.adapter()
            adapter.load()
            adapter.render(self.req(seed=1))  # leaves a cuBLAS workspace behind, as torch does
        self.assertEqual(allocator.allocated, 1 * GIB + 32 * 1024 * 1024)
        self.assertFalse(self.other_executor_can_take_the_gpu())
        self.assertTrue(adapter.close())
        self.assertIn(("clear_cublas_workspaces",), self.calls)
        self.assertEqual(allocator.allocated, 0)
        self.assertTrue(self.other_executor_can_take_the_gpu())
        self.assertTrue(adapter.close(), "closing twice is harmless")

    def test_close_keeps_the_lease_while_a_hook_cache_holds_the_model(self):
        cache, allocator = [], FakeAllocator()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator, hook_cache=cache)):
            adapter = self.adapter()
            adapter.load()
            self.assertFalse(adapter.close(), "the model is still referenced by the hook cache")
            self.assertTrue(adapter.retains_gpu)
            self.assertFalse(adapter.loaded)
            self.assertFalse(self.other_executor_can_take_the_gpu(),
                             "a second executor must not get a GPU that still holds the model")
            with self.assertRaises(GpuResourcesRetained):
                adapter.load()
            cache.clear()
            gc.collect()
            self.assertTrue(adapter.close())
        self.assertEqual(allocator.allocated, 0)
        self.assertTrue(self.other_executor_can_take_the_gpu())

    def test_close_with_a_broken_cuda_context_keeps_the_lease(self):
        allocator = FakeAllocator()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator)):
            adapter = self.adapter()
            adapter.load()
        allocator.broken = True
        self.assertFalse(adapter.close())
        self.assertFalse(self.other_executor_can_take_the_gpu())
        allocator.broken = False
        self.assertTrue(adapter.close())
        self.assertTrue(self.other_executor_can_take_the_gpu())

    def test_without_the_workspace_api_a_leftover_workspace_keeps_the_lease(self):
        """Older torch without _cuda_clearCublasWorkspaces: measured, not assumed -> fail closed."""
        allocator = FakeAllocator()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator, workspace_api=False)):
            adapter = self.adapter()
            adapter.load()
            adapter.render(self.req())
            self.assertFalse(adapter.close())
        self.assertFalse(self.other_executor_can_take_the_gpu())

    # --- #2315 review 5697335934: a retained lease must survive dropping the adapter --------------
    EXECUTOR = """
import gc, os, sys, time
sys.path[:0] = [{worker!r}, {tests!r}]
from unittest.mock import patch
import worker_diffusers_image_adapter as T
from app.diffusers_image_adapter import (DiffusersImageAdapter, GpuResourcesRetained,
                                         quarantined_gpus, release_proven_free)
from app.media_generation_profiles import parse_profile
flags, scenario, lease_dir = sys.argv[1], sys.argv[2], sys.argv[3]
def flag(name): return os.path.join(flags, name)
def publish(name, text):  # atomic: the parent never sees a created-but-empty flag
    open(flag(name) + ".tmp", "w").write(text)
    os.replace(flag(name) + ".tmp", flag(name))
def wait_any(*names):
    while not any(os.path.exists(flag(n)) for n in names):
        time.sleep(0.02)
cache, calls = [], []
if scenario == "close":
    modules = T.fake_modules(calls, hook_cache=cache)
else:
    modules, _ = T.partial_load_fakes(calls, keep_pipeline=cache)
with patch("app.diffusers_image_adapter.inspect_cuda_budget"), patch.dict(sys.modules, modules):
    adapter = DiffusersImageAdapter(parse_profile(T.image_profile()), device="cuda:1",
                                    lease_dir=lease_dir, env=T.OFFLINE)
    if scenario == "close":
        adapter.load()
        assert adapter.close() is False
    else:
        try:
            adapter.load()
        except GpuResourcesRetained:
            pass
        else:
            raise SystemExit("expected GpuResourcesRetained")
    del adapter          # the executor drops the adapter...
    gc.collect()         # ...and it is really gone
    publish("dropped", ",".join(quarantined_gpus()))
    wait_any("clear", "exit")
    if os.path.exists(flag("clear")):
        assert release_proven_free() == 0, "still resident: nothing may be released"
        cache.clear()
        gc.collect()
        publish("released", str(release_proven_free()))
        wait_any("exit")
"""

    def start_executor(self, scenario):
        flags = tempfile.mkdtemp(dir=self.lease_dir)
        root = Path(__file__).resolve().parents[1]
        code = self.EXECUTOR.format(worker=str(root / "worker"), tests=str(root / "tests"))
        proc = subprocess.Popen([sys.executable, "-c", code, flags, scenario, self.lease_dir])
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(10)))
        deadline = time.monotonic() + 30
        while not os.path.exists(os.path.join(flags, "dropped")):
            self.assertIsNone(proc.poll(), "executor process failed")
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        return proc, flags

    def test_a_dropped_adapter_after_close_false_keeps_the_gpu_until_measured_free(self):
        proc, flags = self.start_executor("close")
        self.assertEqual(Path(flags, "dropped").read_text(), GPU1, "the lease sits in the process quarantine")
        self.assertFalse(self.other_executor_can_take_the_gpu(),
                         "adapter dropped and collected, model still resident: the GPU must stay leased")
        Path(flags, "clear").touch()
        deadline = time.monotonic() + 30
        while not Path(flags, "released").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertEqual(Path(flags, "released").read_text(), "1", "a measured release, not a GC side effect")
        self.assertTrue(self.other_executor_can_take_the_gpu())
        Path(flags, "exit").touch()
        self.assertEqual(proc.wait(10), 0)

    def test_a_dropped_adapter_after_a_retained_failed_load_keeps_the_gpu_until_exit(self):
        proc, flags = self.start_executor("failed")
        self.assertFalse(self.other_executor_can_take_the_gpu())
        Path(flags, "exit").touch()  # the executor exits without ever proving the memory free
        self.assertEqual(proc.wait(10), 0)
        self.assertTrue(self.other_executor_can_take_the_gpu(), "the OS frees the lease with the process")

    def test_release_proven_free_releases_only_measured_entries(self):
        cache, allocator = [], FakeAllocator()
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, allocator=allocator, hook_cache=cache)):
            adapter = self.adapter()
            adapter.load()
            self.assertFalse(adapter.close())
            del adapter
            gc.collect()
            self.assertEqual(quarantined_gpus(), [GPU1])
            self.assertEqual(release_proven_free(), 0)
            self.assertFalse(self.other_executor_can_take_the_gpu())
            cache.clear()
            self.assertEqual(release_proven_free(), 1)
            self.assertEqual(quarantined_gpus(), [])
        self.assertTrue(self.other_executor_can_take_the_gpu())

    def test_quarantined_leases_are_held_against_garbage_collection(self):
        cache = []
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, hook_cache=cache)):
            adapter = self.adapter()
            adapter.load()
            self.assertFalse(adapter.close())
        self.assertTrue(adapter_module._QUARANTINE[0].lease._hold_until_exit,
                        "not even interpreter-shutdown finalisation may release it")

    def test_an_adapter_whose_quarantine_was_released_elsewhere_can_load_again(self):
        cache = []
        with patch("app.diffusers_image_adapter.inspect_cuda_budget"), \
                patch.dict(sys.modules, fake_modules(self.calls, hook_cache=cache)):
            adapter = self.adapter()
            adapter.load()
            self.assertFalse(adapter.close())
            self.assertTrue(adapter.retains_gpu)
            cache.clear()
            self.assertEqual(release_proven_free(), 1)
            self.assertFalse(adapter.retains_gpu, "the executor-level release is visible to the adapter")
            adapter.load()
            self.assertTrue(adapter.loaded)
            self.assertFalse(self.other_executor_can_take_the_gpu())
            self.assertFalse(adapter.close(), "the hook cache took the reloaded model again: measured, kept")
        self.empty_quarantine()

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
