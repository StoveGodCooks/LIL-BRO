"""VRAM detection and dynamic context-window calculation.

Detects GPU memory via nvidia-smi, then selects optimal per-bro
context windows from tested tiers. Each tier is validated against
real KV-cache math:

    KV cache = 2 (K+V) x 28 layers x 4 KV heads x 128 head_dim x 2 bytes
             = 57,344 bytes per token (~56 KB)

If no GPU is detected (CPU-only, AMD, or nvidia-smi missing), falls
back to conservative defaults.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tested VRAM tiers — (min_vram_mb, big_bro_ctx, lil_bro_ctx)
#
# Each tier is validated against the KV-cache formula so both bros'
# caches + model weights (~4,700 MB) fit comfortably with headroom.
#
# KV cache per context size (fp16, Qwen 2.5 7B):
#   4K  =  224 MB     16K =  896 MB
#   8K  =  448 MB     24K = 1,344 MB
#  12K  =  672 MB     32K = 1,792 MB
# ---------------------------------------------------------------------------
_VRAM_TIERS: list[tuple[int, int, int]] = [
    # (min_vram_mb, big_ctx, lil_ctx)   # total KV   headroom after weights+KV
    (24_576,  32_768,  32_768),          # 3,584 MB   ~16 GB+
    (16_384,  32_768,  32_768),          # 3,584 MB   ~8 GB
    (12_288,  32_768,  16_384),          # 2,688 MB   ~4.9 GB
    (10_240,  24_576,  16_384),          # 2,240 MB   ~3.3 GB
    ( 8_192,  16_384,   8_192),          # 1,344 MB   ~2.1 GB  ← RTX 3070
    ( 6_144,   8_192,   4_096),          #   672 MB   ~0.8 GB
]

# Absolute minimums when VRAM is very low or undetected
_FLOOR_BIG = 4_096
_FLOOR_LIL = 4_096

# Fallback for CPU-only / no GPU detected
_FALLBACK_BIG = 8_192
_FALLBACK_LIL = 4_096


def detect_vram_mb() -> int | None:
    """Return total GPU VRAM in MiB, or None if detection fails."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        # Multi-GPU: take the first GPU (primary)
        first_line = result.stdout.strip().splitlines()[0].strip()
        return int(first_line)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def calculate_context_windows(
    vram_mb: int | None,
) -> tuple[int, int, str]:
    """Select optimal (big_ctx, lil_ctx, reason) from detected VRAM.

    Uses pre-validated tiers instead of raw formulas — each tier has
    been tested against the KV-cache math for Qwen 2.5 7B (Q4_K_M).

    Returns:
        (big_bro_ctx, lil_bro_ctx, reason_string)
    """
    if vram_mb is None:
        return (
            _FALLBACK_BIG,
            _FALLBACK_LIL,
            "No GPU detected — using conservative CPU defaults "
            f"(Big {_FALLBACK_BIG // 1024}K / Lil {_FALLBACK_LIL // 1024}K)",
        )

    # Walk tiers from highest to lowest, pick first that fits
    for min_vram, big_ctx, lil_ctx in _VRAM_TIERS:
        if vram_mb >= min_vram:
            reason = (
                f"Detected {vram_mb} MB VRAM — "
                f"Big Bro {big_ctx // 1024}K / Lil Bro {lil_ctx // 1024}K"
            )
            log.info(reason)
            return (big_ctx, lil_ctx, reason)

    # Below all tiers — minimum viable
    reason = (
        f"Low VRAM ({vram_mb} MB) — "
        f"minimum context Big {_FLOOR_BIG // 1024}K / Lil {_FLOOR_LIL // 1024}K"
    )
    log.info(reason)
    return (_FLOOR_BIG, _FLOOR_LIL, reason)
