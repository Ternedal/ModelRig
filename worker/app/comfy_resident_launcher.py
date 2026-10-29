"""Runs ComfyUI's main.py in THIS process while holding the GPU's resident lock.

ModelRig #2296 slice 2. Started by comfy_supervisor with ComfyUI's own
Python, so it imports nothing from ModelRig (stdlib only):

    <comfy python> comfy_resident_launcher.py --resident-lock <lock> -- <main.py> <comfy args...>

The lock is taken before ComfyUI's code runs and is held by the very process
that owns the CUDA context, so it is released only when ComfyUI itself exits
(the OS drops it with the process). That ties "GPU in use" to ComfyUI's life
on POSIX and Windows alike, independent of the supervisor surviving.

Exit codes: 64 usage error, 75 resident lock already held (refuse to start).
"""
import os
import runpy
import sys

_RESIDENT_FD = None  # kept open for the life of this process


def _lock(path: str) -> int:
    if os.path.islink(path):
        raise OSError("resident lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise
    return fd


def main(argv: list) -> int:
    global _RESIDENT_FD
    if len(argv) < 4 or argv[0] != "--resident-lock" or argv[2] != "--":
        print("usage: comfy_resident_launcher.py --resident-lock <lock> -- <main.py> [args]", file=sys.stderr)
        return 64
    lock_path, main_py, comfy_args = argv[1], argv[3], argv[4:]
    if (not os.path.isabs(lock_path) or not os.path.isabs(main_py)
            or os.path.basename(main_py) != "main.py" or not os.path.isfile(main_py)):
        print("resident launcher: absolute lock path and an existing absolute main.py are required",
              file=sys.stderr)
        return 64
    try:
        _RESIDENT_FD = _lock(lock_path)
    except OSError:
        print("resident launcher: the GPU's resident lock is already held", file=sys.stderr)
        return 75
    sys.argv = [main_py] + comfy_args
    sys.path.insert(0, os.path.dirname(main_py))
    runpy.run_path(main_py, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
