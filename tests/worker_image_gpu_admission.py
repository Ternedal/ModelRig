"""GPU admission tests with mocked CUDA (no GPU required).

Ported unchanged from worker/tests/test_image_gpu_admission.py on
fix-image-gpu-budget-validation (#2300 @ fd3127a7), ModelRig #2296.
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
    def _torch(self, free_gib, total_gib=12, count=2):
        cuda = types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: count,
            device=lambda index: _Device(index),
            mem_get_info=lambda: (int(free_gib * 1024**3), int(total_gib * 1024**3)),
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


if __name__ == "__main__":
    unittest.main()
