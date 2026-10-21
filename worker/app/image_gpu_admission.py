"""Conservative preflight for dedicated image inference workers.

This is an admission check, not a guarantee that model weights fit in VRAM.
It intentionally never allocates CUDA memory or downloads models.
"""
from __future__ import annotations

from dataclasses import dataclass


class ImageGpuAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GpuBudget:
    index: int
    total_bytes: int
    free_bytes: int
    reserved_bytes: int
    usable_bytes: int


def inspect_cuda_budget(index: int, *, reserve_gib: float = 3.0,
                        min_usable_gib: float = 6.0) -> GpuBudget:
    if not isinstance(index, int) or index < 0:
        raise ImageGpuAdmissionError("invalid GPU index")
    if reserve_gib < 0 or min_usable_gib <= 0:
        raise ImageGpuAdmissionError("invalid GPU budget")
    try:
        import torch
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            raise ImageGpuAdmissionError("requested CUDA GPU unavailable")
        with torch.cuda.device(index):
            free, total = torch.cuda.mem_get_info()
    except ImageGpuAdmissionError:
        raise
    except Exception as exc:
        raise ImageGpuAdmissionError("CUDA memory probe failed") from exc
    reserved = int(reserve_gib * 1024**3)
    usable = max(0, free - reserved)
    if usable < int(min_usable_gib * 1024**3):
        raise ImageGpuAdmissionError("insufficient free VRAM after reservation")
    return GpuBudget(index, total, free, reserved, usable)
