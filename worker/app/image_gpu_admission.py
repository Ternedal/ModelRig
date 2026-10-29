"""Conservative preflight for dedicated image inference workers.

This is an admission check, not a guarantee that model weights fit in VRAM.
It intentionally never allocates CUDA memory or downloads models.

Ported from #2300 (fd3127a7). ModelRig #2296 adds expected_uuid: the caller
holds the GPU lease for a physical GPU UUID and this check refuses to admit
if torch's device <index> is a different GPU (decision 6491161681).
"""
from __future__ import annotations

from dataclasses import dataclass
import math


class ImageGpuAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GpuBudget:
    index: int
    total_bytes: int
    free_bytes: int
    reserved_bytes: int
    usable_bytes: int


def _torch_uuid(props) -> str:
    """torch's device UUID as 'GPU-…' (torch prints it without the prefix)."""
    raw = getattr(props, "uuid", None)
    if raw is None:
        raise ImageGpuAdmissionError("this torch build does not report GPU UUIDs")
    return "GPU-" + str(raw).strip().lower().removeprefix("gpu-")


def inspect_cuda_budget(index: int, *, reserve_gib: float = 3.0,
                        min_usable_gib: float = 6.0, expected_uuid: str | None = None) -> GpuBudget:
    if type(index) is not int or index < 0:
        raise ImageGpuAdmissionError("invalid GPU index")
    if (type(reserve_gib) not in (int, float) or type(min_usable_gib) not in (int, float)
            or not math.isfinite(reserve_gib) or not math.isfinite(min_usable_gib)
            or reserve_gib < 0 or min_usable_gib <= 0):
        raise ImageGpuAdmissionError("invalid GPU budget")
    try:
        import torch
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            raise ImageGpuAdmissionError("requested CUDA GPU unavailable")
        if expected_uuid is not None:
            actual = _torch_uuid(torch.cuda.get_device_properties(index))
            if actual != expected_uuid:
                raise ImageGpuAdmissionError("GPU identity mismatch: cuda index does not match the leased GPU")
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
