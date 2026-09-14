"""ARC-01 funding PIT reader — causal, timestamp-scoped reads.

Invariant: data_time <= decision_time. Funding at T is first observable at T.
No future funding may leak into context at T.

Schema: see normalize_arc01_funding.py — funding_time_ms == availability_time_ms == settlement_time_ms,
with provider jitter handled. Next funding is derived, not observed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parents[4]
FUNDING_DIR_DEFAULT = REPO / "data" / "processed" / "arc01_funding"


def _load_partition(part_path: Path) -> list[dict]:
    rows: list[dict] = []
    with part_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: int(r["funding_time_ms"]))
    return rows


def _funding_dir(feed_dir: Path | None) -> Path:
    if feed_dir is not None:
        return feed_dir
    # Prefer worktree data, else parent main data
    for cand in (FUNDING_DIR_DEFAULT, REPO.parents[1] / "data" / "processed" / "arc01_funding"):
        if cand.is_dir() and any(cand.glob("*_funding.jsonl")):
            return cand
    return FUNDING_DIR_DEFAULT


def iter_funding_rows(symbol: str, feed_dir: Path | None = None) -> Iterator[dict]:
    fdir = _funding_dir(feed_dir)
    p = fdir / f"{symbol}_funding.jsonl"
    if not p.exists():
        # Try EVID fallback (committed snapshot)
        alt = REPO / "docs" / "arc01-data-authority-01" / f"{symbol}_funding.jsonl"
        if alt.exists():
            p = alt
        else:
            alt2 = REPO / "docs" / "external-audit-01" / "arc01-data-authority-01" / f"{symbol}_funding.jsonl"
            if alt2.exists():
                p = alt2
            else:
                return
                yield  # make generator
    for r in _load_partition(p):
        yield r


def funding_state_at(symbol: str, decision_time_ms: int, *, feed_dir: Path | None = None) -> list[dict]:
    """All funding observations with funding_time_ms <= decision_time_ms (causal)."""
    rows = [r for r in iter_funding_rows(symbol, feed_dir) if int(r["funding_time_ms"]) <= decision_time_ms]
    rows.sort(key=lambda r: int(r["funding_time_ms"]))
    return rows


def latest_funding_before(symbol: str, decision_time_ms: int, *, feed_dir: Path | None = None) -> dict | None:
    rows = funding_state_at(symbol, decision_time_ms, feed_dir=feed_dir)
    return rows[-1] if rows else None


def funding_rate_at(symbol: str, decision_time_ms: int, *, feed_dir: Path | None = None) -> float | None:
    """Eligible funding rate at T (latest with funding_time <= T), else None. PIT-safe."""
    latest = latest_funding_before(symbol, decision_time_ms, feed_dir=feed_dir)
    return float(latest["funding_rate"]) if latest else None
