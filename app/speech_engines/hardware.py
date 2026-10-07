"""Host compute detection for engine choice.

Kokoro in this app uses the CPU ONNX runtime. A detected NVIDIA GPU is
reported so a later GPU engine can opt in, and so the interface can say
why the current local engine stays on the CPU.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import shutil
import subprocess


def probe_hardware() -> dict:
    """Return CPU/GPU facts. Never raises."""
    info = {
        "cpu": True,
        "cuda": False,
        "gpu_name": "",
        "vram_mb": 0,
        "kokoro_device": "cpu",
    }
    nvidia = shutil.which("nvidia-smi")
    if not nvidia:
        return info
    try:
        completed = subprocess.run(
            [nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return info
    line = (completed.stdout or "").strip().splitlines()
    if completed.returncode != 0 or not line or not line[0].strip():
        return info
    parts = [part.strip() for part in line[0].split(",")]
    info["cuda"] = True
    info["gpu_name"] = parts[0]
    if len(parts) > 1:
        try:
            info["vram_mb"] = int(float(parts[1]))
        except ValueError:
            info["vram_mb"] = 0
    return info
