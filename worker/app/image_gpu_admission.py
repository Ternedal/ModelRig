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


class GpuMemoryShortage(ImageGpuAdmissionError):
    """Not enough free VRAM right now -- another process (Ollama, typically) holds it. Transient:
    the executor puts the job back in the queue instead of failing it (G4, Anders 5 Nov 2026).

    ``budget`` is what the probe measured when it said no, and ``smi_used_mib`` what nvidia-smi
    said at the same moment (set by the caller that asked it), for the diagnostics stream."""

    def __init__(self, message: str, budget: "GpuBudget | None" = None):
        super().__init__(message)
        self.budget = budget
        self.smi_used_mib: int | None = None


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
    budget = GpuBudget(index, total, free, reserved, usable)
    if usable < int(min_usable_gib * 1024**3):
        raise GpuMemoryShortage("insufficient free VRAM after reservation", budget)
    return budget


def smi_used_mib(gpu_uuid: str | None, *, run=None, timeout_s: float = 3.0) -> int | None:
    """What ``nvidia-smi`` (NVML) says is in use on this GPU, in MiB, or None when it cannot say.

    A second opinion for the diagnostics stream, taken next to the admission probe. Under
    Windows' WDDM driver model ``cudaMemGetInfo`` answers from Windows' own GPU memory manager,
    which can oversubscribe a card; NVML counts what every process holds. When the two disagree,
    this is where it shows. Never an admission input, and never able to fail a load.
    """
    if not isinstance(gpu_uuid, str) or not gpu_uuid:
        return None
    try:
        import subprocess
        result = (run or subprocess.run)(
            ["nvidia-smi", "--query-gpu=uuid,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout_s, check=False)
        if getattr(result, "returncode", 1) != 0:
            return None
        for line in str(result.stdout).splitlines()[:64]:
            uuid, _, used = line.partition(",")
            if uuid.strip().lower() == gpu_uuid.strip().lower() and used.strip().isdigit():
                value = int(used.strip())
                return value if value < 10**7 else None
    except Exception:
        return None
    return None


def budget_detail(budget: object, smi_used: object = None) -> str | None:
    """A measured budget as one diagnostics detail in MiB, or None for anything that is not one.

    Rig 20/11: a job started on a card that another process held 8 GB of, and nothing said
    what the admission probe had seen. Numbers only -- no path, no name.
    """
    if not isinstance(budget, GpuBudget):
        return None
    mib = 1024 * 1024
    detail = (f"cuda{budget.index},free_mib={budget.free_bytes // mib},reserved_mib={budget.reserved_bytes // mib},"
              f"usable_mib={budget.usable_bytes // mib},total_mib={budget.total_bytes // mib}")
    if type(smi_used) is int and 0 <= smi_used < 10**7:
        # NVML's "used" at the same moment: free_mib + smi_used_mib should be about total_mib.
        detail += f",smi_used_mib={smi_used}"
    return detail
