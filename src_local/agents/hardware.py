"""Hardware detection for LIL BRO LOCAL.

Probes GPU (NVIDIA via nvidia-smi), system RAM, and CPU info to
rank which models from the catalog will run well on this machine.

All subprocess calls are run in threads so the async event loop is
never blocked — even if nvidia-smi or wmic takes a few seconds.
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


# ── Sync helpers (run in threads) ────────────────────────────────

def _detect_ram_sync() -> float:
    """Detect system RAM in GB (sync, safe to call in a thread)."""
    _system = platform.system()
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass

    if _system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        except Exception:
            return 8.0
    elif _system == "Linux":
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
        except Exception:
            return 8.0
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
                    return int(line) / (1024 ** 3)
        except Exception:
            pass

    return 8.0  # Conservative default.


def _detect_cpu_sync() -> str | None:
    """Detect CPU name (sync, safe to call in a thread)."""
    _system = platform.system()
    try:
        if _system == "Darwin":
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=5,
                )
                cpu = result.stdout.strip()
                if cpu:
                    return cpu
                raise ValueError("empty")
            except Exception:
                machine = platform.machine()
                if machine == "arm64":
                    return "Apple Silicon"
                return machine or "Unknown CPU"
        elif _system == "Windows":
            return platform.processor() or "Unknown CPU"
        else:
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except Exception:
                return platform.processor() or "Unknown CPU"
    except Exception:
        pass
    return None


def _detect_gpu_sync(ram_gb: float) -> tuple[str | None, float, bool]:
    """Detect GPU. Returns (name, vram_gb, has_gpu). Sync, thread-safe."""
    _system = platform.system()

    # Try NVIDIA first.
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi and _system == "Windows":
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
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    parts = output.splitlines()[0].split(",")
                    if len(parts) >= 2:
                        gpu_name = parts[0].strip()
                        try:
                            vram_gb = float(parts[1].strip()) / 1024
                        except ValueError:
                            vram_gb = 0.0
                        logger.info("GPU detected: %s (%.1f GB VRAM)", gpu_name, vram_gb)
                        return gpu_name, vram_gb, True
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("nvidia-smi failed: %s", exc)

    # macOS: Apple Silicon / AMD GPU via system_profiler.
    if _system == "Darwin":
        try:
            import json as _json
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0:
                data = _json.loads(result.stdout)
                displays = data.get("SPDisplaysDataType", [])
                for gpu in displays:
                    name = gpu.get("sppci_model", "")
                    vram_str = gpu.get("spdisplays_vram", "")
                    if "apple" in name.lower() or not vram_str:
                        gpu_name = name or "Apple GPU (Metal)"
                        vram_gb = ram_gb  # Unified memory.
                        logger.info(
                            "Apple GPU detected: %s (%.1f GB unified)",
                            gpu_name, vram_gb,
                        )
                        return gpu_name, vram_gb, True
                    else:
                        gpu_name = name
                        try:
                            p = vram_str.split()
                            val = float(p[0])
                            if len(p) > 1 and "MB" in p[1].upper():
                                val /= 1024
                            vram_gb = val
                        except (ValueError, IndexError):
                            vram_gb = 0.0
                        logger.info(
                            "AMD GPU detected: %s (%.1f GB VRAM)",
                            gpu_name, vram_gb,
                        )
                        return gpu_name, vram_gb, True
        except Exception as exc:
            logger.warning("system_profiler GPU probe failed: %s", exc)

    return None, 0.0, False


# ── Main async entry point ───────────────────────────────────────

async def detect_hardware() -> HardwareInfo:
    """Probe GPU and system RAM. All subprocess calls run in threads."""
    info = HardwareInfo()
    loop = asyncio.get_running_loop()

    # Run RAM and CPU detection in parallel (both are fast but may
    # involve subprocess calls that block for a second or two).
    ram_future = loop.run_in_executor(None, _detect_ram_sync)
    cpu_future = loop.run_in_executor(None, _detect_cpu_sync)

    info.ram_gb, info.cpu_name = await asyncio.gather(ram_future, cpu_future)

    # GPU detection needs ram_gb for Apple unified memory, so runs after.
    gpu_name, vram_gb, has_gpu = await loop.run_in_executor(
        None, _detect_gpu_sync, info.ram_gb,
    )
    info.gpu_name = gpu_name
    info.vram_gb = vram_gb
    info.has_gpu = has_gpu

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
