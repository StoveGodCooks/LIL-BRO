"""Hardware detection for LIL BRO LOCAL.

Probes GPU (NVIDIA via nvidia-smi), system RAM, and CPU info to
rank which models from the catalog will run well on this machine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("lilbro-local.hardware")


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

    # ── System RAM ────────────────────────────────────────────
    _system = platform.system()
    try:
        import psutil
        info.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        if _system == "Darwin":
            # macOS: sysctl returns total bytes.
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                )
                info.ram_gb = int(result.stdout.strip()) / (1024 ** 3)
            except Exception:
                info.ram_gb = 8.0
        elif _system == "Linux":
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            info.ram_gb = kb / (1024 ** 2)
                            break
            except Exception:
                info.ram_gb = 8.0
        else:
            # Windows without psutil — try wmic.
            try:
                result = subprocess.run(
                    ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line.isdigit():
                        info.ram_gb = int(line) / (1024 ** 3)
                        break
            except Exception:
                info.ram_gb = 8.0  # Conservative default.

    # ── CPU name ───────────────────────────────────────────────
    try:
        if _system == "Darwin":
            # macOS: works on both Intel and Apple Silicon.
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=5,
                )
                cpu = result.stdout.strip()
                if cpu:
                    info.cpu_name = cpu
                else:
                    raise ValueError("empty")
            except Exception:
                # Apple Silicon doesn't always populate brand_string.
                machine = platform.machine()  # "arm64" on M-series
                if machine == "arm64":
                    info.cpu_name = "Apple Silicon"
                else:
                    info.cpu_name = machine or "Unknown CPU"
        elif _system == "Windows":
            info.cpu_name = platform.processor() or "Unknown CPU"
        else:
            # Linux
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

    # ── GPU detection ──────────────────────────────────────────
    # Try NVIDIA first (all platforms), then Apple Metal (macOS).
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi and _system == "Windows":
        # Fallback: known Windows paths.
        for candidate in [
            os.path.join(os.environ.get("SystemRoot", r"C:\WINDOWS"), "System32", "nvidia-smi.exe"),
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]:
            if os.path.isfile(candidate):
                nvidia_smi = candidate
                break

    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    parts = output.splitlines()[0].split(",")
                    if len(parts) >= 2:
                        info.gpu_name = parts[0].strip()
                        try:
                            info.vram_gb = float(parts[1].strip()) / 1024
                        except ValueError:
                            pass
                        info.has_gpu = True
                        logger.info("GPU detected: %s (%.1f GB VRAM)", info.gpu_name, info.vram_gb)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("nvidia-smi failed: %s", exc)

    # macOS: Apple Silicon / AMD GPU via system_profiler.
    if not info.has_gpu and _system == "Darwin":
        try:
            import json as _json
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = _json.loads(result.stdout)
                displays = data.get("SPDisplaysDataType", [])
                for gpu in displays:
                    name = gpu.get("sppci_model", "")
                    # Apple Silicon uses unified memory — report system RAM.
                    vram_str = gpu.get("spdisplays_vram", "")
                    if "apple" in name.lower() or not vram_str:
                        # Unified memory: GPU shares system RAM.
                        info.gpu_name = name or "Apple GPU (Metal)"
                        info.vram_gb = info.ram_gb  # Shared unified memory.
                        info.has_gpu = True
                        logger.info(
                            "Apple GPU detected: %s (%.1f GB unified)",
                            info.gpu_name, info.vram_gb,
                        )
                    else:
                        # Discrete AMD GPU on older Intel Macs.
                        info.gpu_name = name
                        # vram_str is like "4 GB" or "8192 MB"
                        try:
                            parts = vram_str.split()
                            val = float(parts[0])
                            if len(parts) > 1 and "MB" in parts[1].upper():
                                val /= 1024
                            info.vram_gb = val
                        except (ValueError, IndexError):
                            info.vram_gb = 0.0
                        info.has_gpu = True
                        logger.info(
                            "AMD GPU detected: %s (%.1f GB VRAM)",
                            info.gpu_name, info.vram_gb,
                        )
                    break  # Use first GPU found.
        except Exception as exc:
            logger.warning("system_profiler GPU probe failed: %s", exc)

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
