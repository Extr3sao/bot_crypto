"""ARP-005 PATH A — the isolated extended research corpus (research-only).

Adds six provider windows (2025-09 .. 2026-02) *before* the frozen baseline W1
window, so a 5-day-hold daily experiment can reach a usable sample. Rules:

* the extended files live in ``reports/alpha-recovery-v1-4/data/`` and are never
  mixed into ``reports/strategy-baseline/data/`` — the baseline corpus digest
  (``9d51385d…``) pinned by the frozen ARP-003/004 manifests is untouched;
* :func:`ext_corpus_digest` fingerprints only the *new* windows, so the augmented
  dataset has its own identity;
* no interpolation/synthesis: the ARP-004 ``daily_bars_from_5m`` derivation already
  drops any incomplete UTC day, and gaps are simply absent days.

Earlier windows are historical only; the paper run (2026-09-25) and OOS W7 stay out.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from trading_bot.market_data.types import OHLCV

__all__ = [
    "EXT_CORPUS",
    "EXT_SPLIT_WINDOWS",
    "EXT_WINDOWS",
    "ext_corpus_digest",
    "ext_dataset_fingerprints",
    "load_ext_bars",
]

REPO = Path(__file__).resolve().parents[4]
EXT_CORPUS = REPO / "reports/alpha-recovery-v1-4/data"
BASE_CORPUS = REPO / "reports/strategy-baseline/data"

#: new provider windows (naming differs from W1..W7 so they can never collide)
EXT_WINDOWS: tuple[str, ...] = (
    "WX1_2025-09",
    "WX2_2025-10",
    "WX3_2025-11",
    "WX4_2025-12",
    "WX5_2026-01",
    "WX6_2026-02",
)

_BASE_DEV = ("W1_2026-03", "W2_2026-04", "W3_2026-05", "W4_2026-06")
_BASE_VAL = ("W5_2026-07", "W6_2026-08")
_BASE_OOS = ("W7_2026-09",)

#: chronological windows per split; extended DEV prepends the six new months
EXT_SPLIT_WINDOWS: dict[str, tuple[str, ...]] = {
    "DEV": EXT_WINDOWS + _BASE_DEV,
    "VALIDATION": _BASE_VAL,
    "OOS_LOCK": _BASE_OOS,
}


def _ext_files() -> list[Path]:
    if not EXT_CORPUS.exists():
        return []
    return sorted(p for p in EXT_CORPUS.glob("*.json") if not p.name.startswith("_"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ext_corpus_digest() -> str:
    """sha256 over the ordered extended-window file digests (new data only)."""
    combined = hashlib.sha256()
    for path in _ext_files():
        combined.update(_sha256_file(path).encode())
    return combined.hexdigest()


def ext_dataset_fingerprints() -> dict[str, object]:
    entries = []
    for path in _ext_files():
        bars = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            {
                "file": path.name,
                "sha256": _sha256_file(path),
                "rows": len(bars),
                "start_ms": bars[0]["ts"] if bars else None,
                "end_ms": bars[-1]["ts"] if bars else None,
            }
        )
    return {"files": entries, "ext_corpus_digest": ext_corpus_digest()}


def load_ext_bars(symbol: str, window: str) -> list[OHLCV]:
    """Load one window: extended dir for ``WX*``, baseline dir otherwise."""
    base = EXT_CORPUS if window.startswith("WX") else BASE_CORPUS
    path = base / f"{symbol}_{window}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        OHLCV(
            symbol=symbol,
            timestamp=int(b["ts"]),
            open=float(b["open"]),
            high=float(b["high"]),
            low=float(b["low"]),
            close=float(b["close"]),
            volume=float(b["volume"]),
        )
        for b in raw
    ]
