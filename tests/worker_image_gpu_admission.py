"""GPU admission tests with mocked CUDA (no GPU required).

Ported from worker/tests/test_image_gpu_admission.py on
fix-image-gpu-budget-validation (#2300 @ fd3127a7), ModelRig #2296, plus the
GPU identity check (decision 6491161681).
"""
import sys
import types
import unittest
from unittest.mock import patch

from app.image_gpu_admission import inspect_cuda_budget, ImageGpuAdmissionError


class _Device:
    def __init__(self, index):
        self.index = index
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class ImageGpuAdmissionTests(unittest.TestCase):
    def _torch(self, free_gib, total_gib=12, count=2, uuids=None):
        uuids = uuids or {0: "00000000-1111-2222-3333-444444444444", 1: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
        cuda = types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: count,
            device=lambda index: _Device(index),
            mem_get_info=lambda: (int(free_gib * 1024**3), int(total_gib * 1024**3)),
            get_device_properties=lambda index: types.SimpleNamespace(uuid=uuids[index]),
        )
        return types.SimpleNamespace(cuda=cuda)

    def test_accepts_with_headroom(self):
        with patch.dict(sys.modules, {"torch": self._torch(11)}):
            budget = inspect_cuda_budget(1, reserve_gib=3, min_usable_gib=6)
        self.assertEqual(budget.index, 1)
        self.assertEqual(budget.usable_bytes, 8 * 1024**3)

    def test_rejects_busy_gpu(self):
        with patch.dict(sys.modules, {"torch": self._torch(7)}):
            with self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(0)

    def test_a_busy_gpu_is_a_transient_shortage_other_refusals_are_not(self):
        # G4: only "not enough free VRAM right now" is GpuMemoryShortage, which the executor waits out.
        from app.image_gpu_admission import GpuMemoryShortage
        with patch.dict(sys.modules, {"torch": self._torch(free_gib=2)}), self.assertRaises(GpuMemoryShortage):
            inspect_cuda_budget(0, reserve_gib=1, min_usable_gib=8)
        with patch.dict(sys.modules, {"torch": self._torch(free_gib=11, count=0)}):
            with self.assertRaises(ImageGpuAdmissionError) as caught:
                inspect_cuda_budget(0, reserve_gib=1, min_usable_gib=8)
            self.assertNotIsInstance(caught.exception, GpuMemoryShortage, "a missing GPU is not a wait")

    def test_a_shortage_carries_what_the_probe_measured_and_a_budget_reads_as_mib(self):
        # Rig 20/11: a job started on a card another process held 8 GB of, and nothing said what
        # the probe had seen. The numbers ride on the result and on the refusal.
        from app.image_gpu_admission import GpuBudget, GpuMemoryShortage, budget_detail
        with patch.dict(sys.modules, {"torch": self._torch(free_gib=4)}), self.assertRaises(GpuMemoryShortage) as caught:
            inspect_cuda_budget(1, reserve_gib=1, min_usable_gib=8)
        self.assertEqual(budget_detail(caught.exception.budget),
                         "cuda1,free_mib=4096,reserved_mib=1024,usable_mib=3072,total_mib=12288")
        with patch.dict(sys.modules, {"torch": self._torch(free_gib=11)}):
            admitted = inspect_cuda_budget(1, reserve_gib=1, min_usable_gib=8)
        self.assertEqual(budget_detail(admitted), "cuda1,free_mib=11264,reserved_mib=1024,usable_mib=10240,total_mib=12288")
        self.assertIsNone(GpuMemoryShortage("insufficient free VRAM after reservation").budget, "a bare shortage still works")
        for not_a_budget in (None, object(), "cuda1", {"free_bytes": 1}, unittest.mock.MagicMock()):
            self.assertIsNone(budget_detail(not_a_budget))
        self.assertIsInstance(admitted, GpuBudget)

    def test_nvidia_smi_is_a_second_opinion_that_can_only_be_missing_never_fail(self):
        # Under WDDM cudaMemGetInfo answers from Windows' GPU memory manager; NVML counts every process.
        from app.image_gpu_admission import GpuBudget, budget_detail, smi_used_mib
        uuid = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        out = "GPU-00000000-1111-2222-3333-444444444444, 9845\nGPU-AAAAAAAA-bbbb-cccc-dddd-eeeeeeeeeeee, 8149\n"
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return types.SimpleNamespace(returncode=0, stdout=out)
        self.assertEqual(smi_used_mib(uuid, run=run), 8149, "matched by UUID, case-insensitively")
        self.assertEqual(calls[0][0], ["nvidia-smi", "--query-gpu=uuid,memory.used", "--format=csv,noheader,nounits"])
        self.assertEqual(calls[0][1].get("timeout"), 3.0)
        self.assertIsNone(smi_used_mib("GPU-ffffffff-0000-0000-0000-000000000000", run=run), "an unknown GPU")
        self.assertIsNone(smi_used_mib(uuid, run=lambda *a, **k: types.SimpleNamespace(returncode=9, stdout=out)))
        self.assertIsNone(smi_used_mib(uuid, run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=uuid + ", [N/A]\n")))

        def missing(*a, **k):
            raise FileNotFoundError("nvidia-smi")
        self.assertIsNone(smi_used_mib(uuid, run=missing), "no nvidia-smi is not an error")
        for nothing in (None, "", 7):
            self.assertIsNone(smi_used_mib(nothing, run=run))
        gib = 1024**3
        budget = GpuBudget(1, 12 * gib, 11 * gib, gib, 10 * gib)
        self.assertEqual(budget_detail(budget, 8149),
                         "cuda1,free_mib=11264,reserved_mib=1024,usable_mib=10240,total_mib=12288,smi_used_mib=8149")
        for not_a_reading in (None, True, "8149", -1, 8149.0, 10**7):
            self.assertEqual(budget_detail(budget, not_a_reading),
                             "cuda1,free_mib=11264,reserved_mib=1024,usable_mib=10240,total_mib=12288")

    def test_rejects_missing_gpu(self):
        with patch.dict(sys.modules, {"torch": self._torch(11, count=1)}):
            with self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(1)

    def test_rejects_bool_index_and_nonfinite_budget(self):
        for index in (True, False, 1.5, '0'):
            with self.subTest(index=index), self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(index)
        for reserve in (float('nan'), float('inf'), True, '3'):
            with self.subTest(reserve=reserve), self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(0, reserve_gib=reserve)
        for minimum in (float('nan'), float('-inf'), False, '6'):
            with self.subTest(minimum=minimum), self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(0, min_usable_gib=minimum)

    def test_invalid_budget(self):
        with self.assertRaises(ImageGpuAdmissionError):
            inspect_cuda_budget(-1)
        with self.assertRaises(ImageGpuAdmissionError):
            inspect_cuda_budget(0, reserve_gib=-1)


    def test_expected_uuid_must_match_the_device(self):
        leased = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch.dict(sys.modules, {"torch": self._torch(11)}):
            self.assertEqual(inspect_cuda_budget(1, reserve_gib=3, min_usable_gib=6, expected_uuid=leased).index, 1)
            with self.assertRaises(ImageGpuAdmissionError):
                inspect_cuda_budget(0, reserve_gib=3, min_usable_gib=6, expected_uuid=leased)

    def test_torch_uuid_with_prefix_or_upper_case_is_normalized(self):
        torch = self._torch(11, uuids={0: "GPU-AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"})
        with patch.dict(sys.modules, {"torch": torch}):
            inspect_cuda_budget(0, expected_uuid="GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def test_a_torch_without_uuids_fails_closed(self):
        torch = self._torch(11)
        torch.cuda.get_device_properties = lambda index: types.SimpleNamespace(name="no uuid here")
        with patch.dict(sys.modules, {"torch": torch}), self.assertRaises(ImageGpuAdmissionError):
            inspect_cuda_budget(0, expected_uuid="GPU-00000000-1111-2222-3333-444444444444")


if __name__ == "__main__":
    unittest.main()
