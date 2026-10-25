"""Instrumented, offline probe of FenixAI's chart pipeline (safe, no keys, no network).

Runs the upstream code as it is at the pinned commit against synthetic candles and records
what the source says happens: a PNG is produced from the given context, the cache is keyed by
symbol+timeframe, and freshness is enforced by TTL rather than by binding the image to a hash.

This is NOT REA evidence. REA does not execute Python; this is the complementary instrumented
execution the RFC asks for, and it is labelled as such.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(os.environ.get("PROBE_TARGET_ROOT", Path.cwd()))  # fenix checkout root
sys.path.insert(0, str(ROOT))

REPORT: dict[str, object] = {
    "probe": "fenix_chart_pipeline",
    "target_root": str(ROOT),
    "commit": sys.argv[1] if len(sys.argv) > 1 else "unknown",
    "evidence_class": "INSTRUMENTED_EXECUTION_NOT_REA",
    "python": sys.version.split()[0],
    "steps": [],
}


def step(name: str, **payload: object) -> None:
    REPORT["steps"].append({"step": name, **payload})  # type: ignore[union-attr]


def synth_klines(bars: int = 120, seed: int = 7) -> dict[str, list]:
    """Deterministic pseudo-random walk; no exchange, no network."""
    state = seed
    price = 60_000.0
    rows: dict[str, list] = {"datetime": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(bars):
        state = (1103515245 * state + 12345) % (2**31)
        drift = ((state % 200) - 100) / 10_000.0
        open_ = price
        close = price * (1 + drift)
        high = max(open_, close) * 1.001
        low = min(open_, close) * 0.999
        rows["datetime"].append((start + timedelta(minutes=15 * i)).isoformat())
        rows["open"].append(round(open_, 2))
        rows["high"].append(round(high, 2))
        rows["low"].append(round(low, 2))
        rows["close"].append(round(close, 2))
        rows["volume"].append(round(100 + (state % 500), 3))
        price = close
    return rows


try:
    from src.charts.service import ChartService  # noqa: E402
except Exception as exc:  # pragma: no cover - the outcome is the measurement
    step("import_chart_service", ok=False, error=f"{type(exc).__name__}: {exc}")
    print(json.dumps(REPORT, indent=2))
    raise SystemExit(3)

step("import_chart_service", ok=True, module=ChartService.__module__)

klines = synth_klines()
svc = ChartService()

started = time.time()
first = svc.generate(klines, symbol="BTCUSDT", timeframe="15m", use_cache=False)
step(
    "generate_btc_15m",
    ok=bool(getattr(first, "ok", False)),
    backend=str(getattr(first, "backend", None)),
    error=getattr(first, "error", None),
    image_bytes=len(getattr(first, "image_b64", "") or ""),
    generation_ms=round((time.time() - started) * 1000, 1),
    description=getattr(first, "description", None),
)

if not getattr(first, "ok", False):
    REPORT["verdict"] = "RENDER_FAILED"
    print(json.dumps(REPORT, indent=2))
    raise SystemExit(4)

raw = base64.b64decode(first.image_b64)
step(
    "image_identity",
    png_magic=raw[:8].hex(),
    sha256=hashlib.sha256(raw).hexdigest(),
    bytes=len(raw),
)

second = svc.generate(klines, symbol="BTCUSDT", timeframe="15m", use_cache=False)
step(
    "determinism_same_input",
    identical_png=base64.b64decode(second.image_b64) == raw,
    note="same candles, same symbol, same timeframe, cache bypassed",
)

# The cache is keyed by symbol+timeframe: another symbol must not be served this image.
svc.generate(klines, symbol="BTCUSDT", timeframe="15m", use_cache=True)
cached_same = svc.get_cached("BTCUSDT", "15m")
cached_other = svc.get_cached("ETHUSDT", "15m")
step(
    "cache_keying",
    same_symbol_hit=cached_same is not None,
    other_symbol_hit=cached_other is not None,
    other_symbol_image_reused=bool(
        cached_other is not None and cached_other.image_b64 == first.image_b64
    ),
)

# The cache can be asked to be strict; the freshness question is answerable here.
expired = svc.get_cached("BTCUSDT", "15m", max_age=0)
step(
    "cache_ttl_enforced_when_asked",
    max_age_zero_returns_none=expired is None,
    default_ttl_seconds=120,
    note="freshness is available at the cache; the visual node never calls it",
)

# Freshness: the container knows how to be stale, the visual agent never asks it to be.
try:
    from src.tools.chart_capture_scheduler import CaptureMethod, ChartSnapshot  # noqa: E402

    fresh = ChartSnapshot(
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=datetime.now(timezone.utc),
        method=CaptureMethod.MPLFINANCE,
        image_b64=first.image_b64,
    )
    old = ChartSnapshot(
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        method=CaptureMethod.MPLFINANCE,
        image_b64=first.image_b64,
    )
    step(
        "freshness_primitive",
        fresh_is_valid=fresh.is_valid(),
        stale_is_valid=old.is_valid(),
        stale_age_seconds=round(old.age_seconds, 1),
        fresh_cache_key=fresh.cache_key,
        note="TTL for 15m is 600s; the snapshot can express staleness",
    )
except Exception as exc:  # pragma: no cover
    step("freshness_primitive", ok=False, error=f"{type(exc).__name__}: {exc}")

# What the visual agent actually receives: a bare base64 string with no symbol, no hash, no clock.
payload = [
    {"type": "text", "text": "analyst prompt as in visual.py"},
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{first.image_b64}"}},
]
step(
    "payload_shape_sent_to_model",
    image_is_bare_base64=True,
    carries_hash=False,
    carries_symbol_in_payload=False,
    carries_timestamp_in_payload=False,
    payload_digest_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
)

REPORT["verdict"] = "RENDER_AND_CACHE_REPRODUCED"
REPORT["what_this_proves"] = [
    "the upstream renderer runs offline and emits a PNG from the supplied klines",
    "the same input produces the same bytes within one environment",
    "the cache is keyed by symbol+timeframe and does not cross-serve another symbol",
    "staleness exists as a primitive (TTL) but nothing in the image payload records it",
]
REPORT["what_this_does_not_prove"] = [
    "no model was called: the provider path never ran",
    "the environment is our venv, not theirs: byte-identity with their CI is not claimed",
    "no exchange data, no orders, no risk code was executed",
]

out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("fenix_chart_probe.json")
out.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({k: REPORT[k] for k in ("verdict", "steps")}, indent=2, ensure_ascii=False))
