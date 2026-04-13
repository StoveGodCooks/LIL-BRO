"""Tests for hardware detection — mocked per platform."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src_local.agents.hardware import detect_hardware, score_model_fit, HardwareInfo


# ---------------------------------------------------------------------------
# Hardware detection with mocked system calls
# ---------------------------------------------------------------------------

class TestDetectHardware:
    """Hardware detection returns sane results on every platform."""

    @pytest.mark.asyncio
    async def test_returns_hardware_info(self):
        """detect_hardware always returns a HardwareInfo, never crashes."""
        info = await detect_hardware()
        assert isinstance(info, HardwareInfo)
        assert info.ram_gb > 0  # Should detect SOMETHING.

    @pytest.mark.asyncio
    async def test_summary_always_works(self):
        """summary() should never crash, even with empty data."""
        info = HardwareInfo()
        s = info.summary()
        assert "GPU" in s
        assert "RAM" in s

    @pytest.mark.asyncio
    async def test_mock_nvidia_gpu(self):
        """Mocked nvidia-smi returns GPU info."""
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "NVIDIA RTX 4090, 24564\n"

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
             patch("subprocess.run", return_value=fake_result), \
             patch("platform.system", return_value="Linux"):
            info = await detect_hardware()
        assert info.has_gpu
        assert "4090" in (info.gpu_name or "")
        assert info.vram_gb > 20

    @pytest.mark.asyncio
    async def test_mock_apple_silicon(self):
        """Mocked macOS Apple Silicon detection."""
        import json

        profiler_output = json.dumps({
            "SPDisplaysDataType": [{
                "sppci_model": "Apple M2 Pro",
            }]
        })

        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "sysctl":
                if "hw.memsize" in cmd:
                    result.stdout = "34359738368\n"  # 32 GB
                    result.returncode = 0
                elif "machdep.cpu.brand_string" in cmd:
                    result.stdout = ""
                    result.returncode = 1  # Apple Silicon doesn't have brand_string
                return result
            if cmd[0] == "system_profiler":
                result.stdout = profiler_output
                result.returncode = 0
                return result
            result.returncode = 1
            result.stdout = ""
            return result

        with patch("shutil.which", return_value=None), \
             patch("subprocess.run", side_effect=mock_run), \
             patch("platform.system", return_value="Darwin"), \
             patch("platform.machine", return_value="arm64"):
            # Also need to make psutil import fail.
            import builtins
            original_import = builtins.__import__

            def no_psutil(name, *args, **kwargs):
                if name == "psutil":
                    raise ImportError("mocked")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=no_psutil):
                info = await detect_hardware()

        assert info.has_gpu
        assert "Apple" in (info.gpu_name or "") or "M2" in (info.gpu_name or "")
        assert info.ram_gb > 30  # 32 GB unified


# ---------------------------------------------------------------------------
# Model fit scoring
# ---------------------------------------------------------------------------

class TestScoreModelFit:
    """score_model_fit ranks hardware against model requirements."""

    def _hw(self, *, gpu: bool = False, vram: float = 0, ram: float = 16) -> HardwareInfo:
        return HardwareInfo(
            gpu_name="Test GPU" if gpu else None,
            vram_gb=vram,
            ram_gb=ram,
            has_gpu=gpu,
        )

    def test_ideal_fit(self):
        hw = self._hw(gpu=True, vram=24)
        assert score_model_fit(min_vram_gb=6, min_ram_gb=16, runs_on_cpu=False, hw=hw) == 3

    def test_meets_minimum(self):
        hw = self._hw(gpu=True, vram=6)
        assert score_model_fit(min_vram_gb=6, min_ram_gb=16, runs_on_cpu=False, hw=hw) == 2

    def test_tight_fit(self):
        hw = self._hw(gpu=True, vram=5)
        assert score_model_fit(min_vram_gb=6, min_ram_gb=16, runs_on_cpu=False, hw=hw) == 1

    def test_wont_run(self):
        hw = self._hw(gpu=True, vram=2)
        assert score_model_fit(min_vram_gb=6, min_ram_gb=16, runs_on_cpu=False, hw=hw) == 0

    def test_cpu_only_ok(self):
        hw = self._hw(gpu=False, ram=16)
        assert score_model_fit(min_vram_gb=4, min_ram_gb=8, runs_on_cpu=True, hw=hw) >= 1

    def test_cpu_only_not_supported(self):
        hw = self._hw(gpu=False, ram=16)
        assert score_model_fit(min_vram_gb=6, min_ram_gb=16, runs_on_cpu=False, hw=hw) == 0
