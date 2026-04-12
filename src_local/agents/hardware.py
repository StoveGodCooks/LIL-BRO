"""Hardware detection for LIL BRO LOCAL.

Probes GPU (NVIDIA via nvidia-smi), system RAM, and CPU info to
rank which models from the catalog will run well on this machine.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
from dataclasses import dataclass


@dataclass
class HardwareInfo:
    """Detected hardware capabilities."""
    gpu_name: str | None = None
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    cpu_name: str | None = None
    has_gpu: bool = False

    def summary(self) -> str:
        lines = []
        if self.has_gpu and self.gpu_name:
            lines.append(f"  GPU : {self.gpu_name} ({self.vram_gb:.1f} GB VRAM)")
        else:
            lines.append("  GPU : None detected (CPU-only mode)")
        lines.append(f"  RAM : {self.ram_gb:.0f} GB")
        if self.cpu_name:
            lines.append(f"  CPU : {self.cpu_name}")
        return "\n".join(lines)


async def detect_hardware() -> HardwareInfo:
    """Probe GPU and system RAM. Non-blocking."""
    info = HardwareInfo()

    # System RAM.
    try:
        import psutil
        info.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        # Fallback: read from /proc/meminfo on Linux.
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        info.ram_gb = kb / (1024 ** 2)
                        break
        except Exception:
            # Windows without psutil — try wmic.
            try:
                proc = await asyncio.create_subprocess_exec(
                    "wmic", "ComputerSystem", "get", "TotalPhysicalMemory",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                for line in stdout.decode().strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        info.ram_gb = int(line) / (1024 ** 3)
                        break
            except Exception:
                info.ram_gb = 8.0  # Conservative default.

    # CPU name.
    try:
        if platform.system() == "Windows":
            info.cpu_name = platform.processor() or "Unknown CPU"
        else:
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            info.cpu_name = line.split(":", 1)[1].strip()
                            break
            except Exception:
                info.cpu_name = platform.processor() or "Unknown CPU"
    except Exception:
        pass

    # NVIDIA GPU via nvidia-smi.
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = await asyncio.create_subprocess_exec(
                nvidia_smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0:
                output = stdout.decode("utf-8", errors="replace").strip()
                if output:
                    # Take the first GPU.
                    parts = output.splitlines()[0].split(",")
                    if len(parts) >= 2:
                        info.gpu_name = parts[0].strip()
                        try:
                            info.vram_gb = float(parts[1].strip()) / 1024
                        except ValueError:
                            pass
                        info.has_gpu = True
        except (asyncio.TimeoutError, OSError):
            pass

    return info


def score_model_fit(
    *,
    min_vram_gb: float,
    min_ram_gb: float,
    runs_on_cpu: bool,
    hw: HardwareInfo,
) -> int:
    """Score how well a model fits the detected hardware.

    Returns:
      3 = ideal fit (plenty of headroom)
      2 = workable (meets minimums)
      1 = tight (barely meets, or CPU-only for a GPU model)
      0 = won't run (below minimums)
    """
    if hw.has_gpu:
        if hw.vram_gb >= min_vram_gb * 1.5:
            return 3  # Plenty of headroom.
        if hw.vram_gb >= min_vram_gb:
            return 2  # Meets minimum.
        if runs_on_cpu and hw.ram_gb >= min_ram_gb:
            return 1  # Can fall back to CPU.
        if hw.vram_gb >= min_vram_gb * 0.8:
            return 1  # Tight fit.
        return 0
    else:
        # CPU-only.
        if not runs_on_cpu:
            return 0
        if hw.ram_gb >= min_ram_gb * 1.5:
            return 2
        if hw.ram_gb >= min_ram_gb:
            return 1
        return 0
