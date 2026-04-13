"""VRAM detection and dynamic context-window calculation.

Detects GPU memory via nvidia-smi (or Apple system_profiler), then
calculates optimal per-bro context windows based on the ACTUAL model
architecture — queried from Ollama's /api/show endpoint.

If model info isn't available, falls back to tested VRAM tiers
(validated against Qwen 2.5 7B KV-cache math).
"""

from __future__ import annotations

import logging
import subprocess

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tested VRAM tiers — fallback when /api/show is unavailable.
# (min_vram_mb, big_bro_ctx, lil_bro_ctx)
# Validated against Qwen 2.5 7B (Q4_K_M): ~56 KB/token, ~4,700 MB weights.
# ---------------------------------------------------------------------------
_VRAM_TIERS: list[tuple[int, int, int]] = [
    (24_576,  32_768,  32_768),
    (16_384,  32_768,  32_768),
    (12_288,  32_768,  16_384),
    (10_240,  24_576,  16_384),
    ( 8_192,  16_384,   8_192),
    ( 6_144,   8_192,   4_096),
]

_FLOOR_BIG = 4_096
_FLOOR_LIL = 4_096
_FALLBACK_BIG = 8_192
_FALLBACK_LIL = 4_096

# Quantization → approximate bytes per parameter.
_QUANT_BPP: dict[str, float] = {
    "Q2_K":   0.31,
    "Q3_K_S": 0.38,
    "Q3_K_M": 0.42,
    "Q4_0":   0.50,
    "Q4_K_S": 0.52,
    "Q4_K_M": 0.55,
    "Q4_1":   0.56,
    "Q5_0":   0.63,
    "Q5_K_S": 0.66,
    "Q5_K_M": 0.69,
    "Q6_K":   0.83,
    "Q8_0":   1.00,
    "F16":    2.00,
    "F32":    4.00,
}
_DEFAULT_BPP = 0.55  # assume Q4_K_M if unknown


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
        first_line = result.stdout.strip().splitlines()[0].strip()
        return int(first_line)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass

    # macOS: Apple Silicon unified memory — report system RAM.
    try:
        import platform
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            total_bytes = int(result.stdout.strip())
            # Report ~75% of unified memory as available for model use.
            return int(total_bytes / (1024 ** 2) * 0.75)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Query Ollama /api/show for model architecture details
# ---------------------------------------------------------------------------

def _query_model_info(
    model_name: str,
    base_url: str = "http://127.0.0.1:11434",
) -> dict | None:
    """Fetch model architecture info from Ollama. Returns None on failure."""
    try:
        resp = httpx.post(
            f"{base_url}/api/show",
            json={"name": model_name},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        log.debug("Could not query /api/show for %s: %s", model_name, exc)
        return None


def _parse_model_arch(data: dict) -> dict:
    """Extract architecture values from /api/show response.

    Returns dict with keys: num_layers, num_kv_heads, head_dim,
    parameter_size, quantization, num_ctx (model's max context).
    """
    info = data.get("model_info", {})
    details = data.get("details", {})

    # Parameter size: "7B", "3B", "14B", etc.
    param_size_str = details.get("parameter_size", "")
    param_billions = 0.0
    if param_size_str:
        try:
            param_billions = float(param_size_str.upper().replace("B", "").strip())
        except ValueError:
            pass

    # Quantization level.
    quant = details.get("quantization_level", "")

    # Architecture details from model_info.
    # Keys vary by model family but follow patterns like:
    #   <family>.block_count, <family>.attention.head_count_kv,
    #   <family>.attention.head_count, <family>.embedding_length
    num_layers = 0
    num_kv_heads = 0
    head_dim = 0
    model_ctx = 0

    for key, val in info.items():
        k = key.lower()
        if k.endswith(".block_count") and not num_layers:
            try:
                num_layers = int(val)
            except (TypeError, ValueError):
                pass
        elif k.endswith(".head_count_kv") and not num_kv_heads:
            try:
                num_kv_heads = int(val)
            except (TypeError, ValueError):
                pass
        elif k.endswith(".context_length") and not model_ctx:
            try:
                model_ctx = int(val)
            except (TypeError, ValueError):
                pass

    # head_dim: derive from embedding_length / head_count.
    embedding_length = 0
    head_count = 0
    for key, val in info.items():
        k = key.lower()
        if k.endswith(".embedding_length") and not embedding_length:
            try:
                embedding_length = int(val)
            except (TypeError, ValueError):
                pass
        elif k.endswith(".head_count") and not k.endswith("head_count_kv") and not head_count:
            try:
                head_count = int(val)
            except (TypeError, ValueError):
                pass

    if embedding_length and head_count:
        head_dim = embedding_length // head_count

    return {
        "num_layers": num_layers,
        "num_kv_heads": num_kv_heads,
        "head_dim": head_dim,
        "param_billions": param_billions,
        "quantization": quant,
        "model_ctx": model_ctx,
    }


def _estimate_kv_bytes_per_token(arch: dict) -> int | None:
    """Calculate KV-cache bytes per token from architecture.

    Formula: 2 (K+V) × num_layers × num_kv_heads × head_dim × 2 (fp16 bytes)
    """
    layers = arch.get("num_layers", 0)
    kv_heads = arch.get("num_kv_heads", 0)
    hdim = arch.get("head_dim", 0)

    if not all([layers, kv_heads, hdim]):
        return None

    return 2 * layers * kv_heads * hdim * 2


def _estimate_weight_mb(arch: dict) -> float | None:
    """Estimate loaded model weight size in MB from params + quantization."""
    param_b = arch.get("param_billions", 0)
    if not param_b:
        return None

    quant = arch.get("quantization", "")
    bpp = _DEFAULT_BPP
    # Try exact match first, then partial match.
    if quant in _QUANT_BPP:
        bpp = _QUANT_BPP[quant]
    else:
        for q_key, q_bpp in _QUANT_BPP.items():
            if q_key in quant:
                bpp = q_bpp
                break

    total_bytes = param_b * 1e9 * bpp
    return total_bytes / (1024 ** 2)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_context_windows(
    vram_mb: int | None,
    model_name: str = "",
    base_url: str = "http://127.0.0.1:11434",
) -> tuple[int, int, str]:
    """Select optimal (big_ctx, lil_ctx, reason) for the given model + VRAM.

    Tries dynamic calculation first (query /api/show for real architecture).
    Falls back to pre-validated VRAM tiers if model info is unavailable.

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

    # ── Try dynamic calculation from model architecture ─────────
    if model_name:
        data = _query_model_info(model_name, base_url)
        if data:
            arch = _parse_model_arch(data)
            kv_per_token = _estimate_kv_bytes_per_token(arch)
            weight_mb = _estimate_weight_mb(arch)

            if kv_per_token and weight_mb:
                # Available VRAM after loading weights (with 10% overhead buffer).
                available_mb = vram_mb - weight_mb - (vram_mb * 0.10)
                if available_mb < 256:
                    available_mb = 256  # absolute floor

                available_bytes = available_mb * 1024 * 1024
                # Total tokens we can fit in VRAM.
                max_tokens = int(available_bytes / kv_per_token)

                # Split: Big Bro gets 60%, Lil Bro gets 40%.
                big_ctx = int(max_tokens * 0.60)
                lil_ctx = int(max_tokens * 0.40)

                # Ceiling: never exceed the model's declared context length.
                model_max = arch.get("model_ctx", 0)
                if model_max:
                    big_ctx = min(big_ctx, model_max)
                    lil_ctx = min(lil_ctx, model_max)

                # Round down to nearest 1024 for clean numbers.
                big_ctx = max(_FLOOR_BIG, (big_ctx // 1024) * 1024)
                lil_ctx = max(_FLOOR_LIL, (lil_ctx // 1024) * 1024)

                quant = arch.get("quantization", "?")
                reason = (
                    f"Dynamic: {model_name} ({arch['param_billions']:.0f}B {quant}) "
                    f"· {vram_mb} MB VRAM · ~{weight_mb:.0f} MB weights · "
                    f"{kv_per_token} B/token KV → "
                    f"Big {big_ctx // 1024}K / Lil {lil_ctx // 1024}K"
                )
                log.info(reason)
                return (big_ctx, lil_ctx, reason)

            log.info(
                "Partial model info for %s (layers=%s kv_heads=%s) — using tier fallback",
                model_name, arch.get("num_layers"), arch.get("num_kv_heads"),
            )

    # ── Fallback: pre-validated tier table ──────────────────────
    for min_vram, big_ctx, lil_ctx in _VRAM_TIERS:
        if vram_mb >= min_vram:
            reason = (
                f"Detected {vram_mb} MB VRAM — "
                f"Big Bro {big_ctx // 1024}K / Lil Bro {lil_ctx // 1024}K"
            )
            log.info(reason)
            return (big_ctx, lil_ctx, reason)

    reason = (
        f"Low VRAM ({vram_mb} MB) — "
        f"minimum context Big {_FLOOR_BIG // 1024}K / Lil {_FLOOR_LIL // 1024}K"
    )
    log.info(reason)
    return (_FLOOR_BIG, _FLOOR_LIL, reason)
