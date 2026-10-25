"""exp_003o_contract — the frozen, signal-free contract EXP-003O is built on.

What lives here and nowhere else:

* the 24 experimental cells inherited from EXP-003N, with their stage, timeframe and
  the parameters that were frozen before this experiment existed;
* the evaluation vocabulary (``SIGNAL`` / ``NO_SIGNAL`` / ``NOT_READY`` /
  ``NOT_EVALUABLE``) and the reason codes that may accompany it;
* deterministic writers (sorted JSON, gzip with ``mtime=0``), hashing helpers and the
  canonical bar-window digest.

What deliberately does **not** live here: any indicator, any rule, any threshold test,
any decision. The original producer and the independent rebuilder share the contract and
nothing else, so a shared bug can only be a *format* bug, never a *signal* bug.

The module imports the standard library only. That is checked, not asserted.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
OUT: Final = REPO / "reports" / "ai-bots" / "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001"
SOURCE_003N: Final = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DATASET: Final = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"

RUN_ID: Final = "EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001"
SCHEMA_EVALUATION: Final = "AI_BOTS_003O_EVALUATION_V1"
SCHEMA_PARITY: Final = "AI_BOTS_003O_PARITY_V1"

MINUTE_MS: Final = 60_000
DAY_MS: Final = 86_400_000

TIMEFRAME_MS: Final[dict[str, int]] = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000}

#: Every lane-A family is evaluated on a **fixed 80-bar window** ending at the decision
#: bar. That is the frozen producer's own convention (``max(min_candles + 1, 80)``), and
#: it is part of the observable contract: an EMA re-seeded on a window is not the same
#: number as an EMA run over the whole series, so the rebuilder must reproduce the window,
#: not merely the formula.
LANE_A_WINDOW: Final = 80

SYMBOLS: Final = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

HOLDOUT: Final = ("2026-08-06T00:00:00Z", "2026-08-20T00:00:00Z")
PARTITIONS: Final[dict[str, tuple[str, str]]] = {
    "IS": ("2026-06-21T00:00:00Z", "2026-07-11T00:00:00Z"),
    "VAL": ("2026-07-11T00:00:00Z", "2026-07-26T00:00:00Z"),
    "TEST": ("2026-07-26T00:00:00Z", "2026-08-06T00:00:00Z"),
}

#: The six ``AlphaFamily`` classes 003N screened in lane A. ``min_candles`` is each
#: family's own guard; the evaluations start at the window, which is wider for all six.
LANE_A_FAMILIES: Final[dict[str, dict[str, Any]]] = {
    "ema_crossover": {"min_candles": 22, "long_short": True},
    "momentum": {"min_candles": 36, "long_short": True},
    "breakout": {"min_candles": 21, "long_short": True},
    "mean_reversion": {"min_candles": 22, "long_short": True},
    "trend": {"min_candles": 56, "long_short": True},
    "volatility": {"min_candles": 27, "long_short": True},
}

#: The three WP-EDGE-015 machines 003N screened in lane B, with the parameters 003N froze.
#:
#: Their parameter names say ``_hours`` but the machines consume them as **bar counts**.
#: On 1h bars the two readings coincide; on 4h bars they do not, so the 4h cells run a
#: rule that is ~4x longer than its own parameter names claim. That is a defect in the
#: inherited universe (DEF-003O-02), reproduced here rather than silently repaired.
LANE_B_FAMILIES: Final[dict[str, dict[str, Any]]] = {
    "vol_regime_breakout": {
        "atr_hours": 24,
        "atr_percentile_max": 0.95,
        "atr_percentile_min": 0.5,
        "channel_hours": 168,
        "percentile_window_hours": 720,
        "regime_ema_hours": 200,
        "trail_atr_multiple": 3.0,
    },
    "trend_pullback": {
        "atr_hours": 24,
        "fast_ema_hours": 20,
        "slow_ema_hours": 50,
        "stop_atr_multiple": 3.0,
        "trend_ema_hours": 200,
        "trend_slope_hours": 24,
    },
    "mean_reversion_vol_liq": {
        "atr_hours": 24,
        "atr_percentile_max": 0.5,
        "atr_stop_multiple": 4.0,
        "max_hold_hours": 48,
        "mean_hours": 48,
        "percentile_window_hours": 720,
        "volume_median_hours": 168,
        "volume_multiple_min": 1.2,
        "z_entry": -2.0,
        "z_exit": 0.0,
    },
}

#: The bar index from which each lane-B machine can have every input it reads.
#:
#: ``vol_regime_breakout`` reads an ATR percentile over 720 ATR values, and the ATR itself
#: only exists after 24 bars, so bar 743 is the first bar whose rank exists. The pullback
#: reads a 200-bar EMA and a value of it 24 bars back: bar 223. The mean-reversion machine
#: needs the same percentile (744) and a 48-bar mean (48): 744 wins.
LANE_B_WARMUP: Final[dict[str, int]] = {
    "vol_regime_breakout": 743,
    "trend_pullback": 223,
    "mean_reversion_vol_liq": 743,
}

STATES: Final = ("SIGNAL", "NO_SIGNAL", "NOT_READY", "NOT_EVALUABLE")
DIRECTIONS: Final = ("LONG", "SHORT", "FLAT")
REASONS: Final = (
    "WARMUP",
    "IN_POSITION",
    "RULE_FALSE",
    "EXIT_RULE",
    "ENTRY_RULE",
)

#: A difference class the comparator may emit. Closed on purpose: an unexplained
#: difference is a class of its own, never a free-text excuse.
DIFFERENCE_CLASSES: Final = (
    "MISSING_EVALUATION",
    "EXTRA_EVALUATION",
    "EXTRA_SIGNAL",
    "MISSING_SIGNAL",
    "DIRECTION_MISMATCH",
    "STATE_MISMATCH",
    "TIMING_MISMATCH",
    "PIT_VIOLATION",
    "INPUT_MISMATCH",
    "PARAMETER_HASH_MISMATCH",
    "DUPLICATE_KEY",
    "CONTRACT_AMBIGUITY",
    "DATA_INTEGRITY_FAIL",
    "INDEPENDENCE_VIOLATION",
    "PREFIX_INVARIANCE_FAIL",
)


def utc_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000)


def iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload), encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    """Deterministic gzip: no mtime, no filename — two runs produce the same bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as handle,
        gzip.GzipFile(fileobj=handle, mode="wb", compresslevel=9, mtime=0) as stream,
    ):
        for row in rows:
            line = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            stream.write(line.encode("utf-8") + b"\n")


def read_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@dataclass(frozen=True)
class Bar:
    """One closed bar. ``ts_ms`` is the bar's **open** time, as the venue reports it."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def bar_bytes(bar: Bar) -> bytes:
    """Canonical bytes for one bar: the digest inputs are numbers, never pretty-printing."""

    return struct.pack("<q5d", int(bar.ts_ms), bar.open, bar.high, bar.low, bar.close, bar.volume)


def window_digest(window: list[Bar]) -> str:
    digest = hashlib.sha256()
    for bar in window:
        digest.update(bar_bytes(bar))
    return digest.hexdigest()


def cell_id(family: str, timeframe: str) -> str:
    return f"{family}@{timeframe}"


def cell_inventory() -> list[dict[str, Any]]:
    """The 24 cells 003N screened, in a stable order, with their lane and warm-up."""

    cells: list[dict[str, Any]] = []
    for family in LANE_A_FAMILIES:
        for timeframe in ("5m", "1h", "4h"):
            cells.append(
                {
                    "cell_id": cell_id(family, timeframe),
                    "lane": "A",
                    "family": family,
                    "timeframe": timeframe,
                    "warmup_bars": LANE_A_WINDOW - 1,
                    "parameters": {"window_bars": LANE_A_WINDOW, **LANE_A_FAMILIES[family]},
                }
            )
    for family in LANE_B_FAMILIES:
        for timeframe in ("1h", "4h"):
            cells.append(
                {
                    "cell_id": cell_id(family, timeframe),
                    "lane": "B",
                    "family": family,
                    "timeframe": timeframe,
                    "warmup_bars": LANE_B_WARMUP[family],
                    "parameters": LANE_B_FAMILIES[family],
                }
            )
    return cells


def parameter_hash(parameters: dict[str, Any]) -> str:
    return sha256_bytes(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def evaluation_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (str(row["cell_id"]), str(row["symbol"]), int(row["decision_ms"]))


def partition_of(decision_ms: int) -> str | None:
    for name, (start, end) in PARTITIONS.items():
        if utc_ms(start) <= decision_ms < utc_ms(end):
            return name
    return None
