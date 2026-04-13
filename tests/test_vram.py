"""Tests for VRAM detection and dynamic context-window calculation."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src_local.vram import (
    calculate_context_windows,
    _parse_model_arch,
    _estimate_kv_bytes_per_token,
    _estimate_weight_mb,
    _FLOOR_BIG,
    _FLOOR_LIL,
    _FALLBACK_BIG,
    _FALLBACK_LIL,
)


# ---------------------------------------------------------------------------
# Tier-based fallback (no model info)
# ---------------------------------------------------------------------------

class TestTierFallback:
    """When model info isn't available, use the pre-validated VRAM tier table."""

    def test_no_gpu_returns_fallback(self):
        big, lil, reason = calculate_context_windows(None)
        assert big == _FALLBACK_BIG
        assert lil == _FALLBACK_LIL
        assert "No GPU" in reason

    def test_24gb_gets_max(self):
        big, lil, _ = calculate_context_windows(24_576)
        assert big == 32_768
        assert lil == 32_768

    def test_8gb_tier(self):
        big, lil, _ = calculate_context_windows(8_192)
        assert big == 16_384
        assert lil == 8_192

    def test_6gb_tier(self):
        big, lil, _ = calculate_context_windows(6_144)
        assert big == 8_192
        assert lil == 4_096

    def test_below_all_tiers_uses_floor(self):
        big, lil, _ = calculate_context_windows(2_048)
        assert big == _FLOOR_BIG
        assert lil == _FLOOR_LIL

    def test_exact_tier_boundary(self):
        big, lil, _ = calculate_context_windows(10_240)
        assert big == 24_576
        assert lil == 16_384


# ---------------------------------------------------------------------------
# Dynamic calculation from model architecture
# ---------------------------------------------------------------------------

class TestDynamicCalculation:
    """When /api/show returns model info, calculate context windows dynamically."""

    # Simulated /api/show response for Qwen 2.5 7B Q4_K_M
    QWEN_7B_SHOW = {
        "details": {
            "parameter_size": "7B",
            "quantization_level": "Q4_K_M",
        },
        "model_info": {
            "qwen2.block_count": 28,
            "qwen2.attention.head_count_kv": 4,
            "qwen2.attention.head_count": 28,
            "qwen2.embedding_length": 3584,
            "qwen2.context_length": 32768,
        },
    }

    def test_parse_arch_qwen(self):
        arch = _parse_model_arch(self.QWEN_7B_SHOW)
        assert arch["num_layers"] == 28
        assert arch["num_kv_heads"] == 4
        assert arch["head_dim"] == 128  # 3584 / 28
        assert arch["param_billions"] == 7.0
        assert arch["quantization"] == "Q4_K_M"
        assert arch["model_ctx"] == 32768

    def test_kv_bytes_per_token_qwen(self):
        arch = _parse_model_arch(self.QWEN_7B_SHOW)
        kv = _estimate_kv_bytes_per_token(arch)
        # 2 * 28 * 4 * 128 * 2 = 57,344
        assert kv == 57_344

    def test_weight_estimate_q4(self):
        arch = _parse_model_arch(self.QWEN_7B_SHOW)
        weight_mb = _estimate_weight_mb(arch)
        assert weight_mb is not None
        # 7B * 0.55 bpp = 3.85 GB = ~3,942 MB
        assert 3_500 < weight_mb < 4_500

    def test_dynamic_uses_api_show(self):
        """Full end-to-end: mock /api/show → get dynamic context windows."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.QWEN_7B_SHOW

        with patch("src_local.vram.httpx.post", return_value=mock_resp):
            big, lil, reason = calculate_context_windows(
                8_192, model_name="qwen2.5-coder:7b"
            )
        assert "Dynamic" in reason
        assert big >= _FLOOR_BIG
        assert lil >= _FLOOR_LIL
        # With 8GB VRAM, ~4GB weights, ~3.4GB available → should fit some context.
        assert big > 4_096
        assert lil > 2_048

    def test_falls_back_when_api_fails(self):
        """If /api/show fails, use the tier table."""
        with patch("src_local.vram.httpx.post", side_effect=Exception("connection refused")):
            big, lil, reason = calculate_context_windows(
                8_192, model_name="qwen2.5-coder:7b"
            )
        # Should use tier fallback, not dynamic.
        assert "Dynamic" not in reason
        assert big == 16_384
        assert lil == 8_192

    def test_never_exceeds_model_max_ctx(self):
        """Context windows should be capped at the model's declared max."""
        # Pretend we have 48GB VRAM — should still cap at 32K for this model.
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.QWEN_7B_SHOW

        with patch("src_local.vram.httpx.post", return_value=mock_resp):
            big, lil, _ = calculate_context_windows(
                49_152, model_name="qwen2.5-coder:7b"
            )
        assert big <= 32_768
        assert lil <= 32_768

    def test_never_below_floor(self):
        """Even with tiny VRAM, never go below floor."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.QWEN_7B_SHOW

        with patch("src_local.vram.httpx.post", return_value=mock_resp):
            big, lil, _ = calculate_context_windows(
                5_000, model_name="qwen2.5-coder:7b"
            )
        assert big >= _FLOOR_BIG
        assert lil >= _FLOOR_LIL


# ---------------------------------------------------------------------------
# Architecture parsing edge cases
# ---------------------------------------------------------------------------

class TestArchParsing:
    """Edge cases for model architecture parsing."""

    def test_empty_model_info(self):
        arch = _parse_model_arch({"details": {}, "model_info": {}})
        assert arch["num_layers"] == 0
        assert arch["num_kv_heads"] == 0
        assert arch["param_billions"] == 0.0

    def test_missing_quant(self):
        arch = _parse_model_arch({
            "details": {"parameter_size": "14B"},
            "model_info": {},
        })
        assert arch["param_billions"] == 14.0
        assert arch["quantization"] == ""

    def test_kv_returns_none_on_incomplete_arch(self):
        arch = {"num_layers": 28, "num_kv_heads": 0, "head_dim": 128}
        assert _estimate_kv_bytes_per_token(arch) is None

    def test_weight_returns_none_on_zero_params(self):
        arch = {"param_billions": 0, "quantization": "Q4_K_M"}
        assert _estimate_weight_mb(arch) is None
