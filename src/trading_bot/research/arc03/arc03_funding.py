"""ARC-03 funding-cashflow authority reader (reused certified ARC-01 funding bytes).

ARC-03 uses participation/price data as its **signal**. Funding is NOT a signal input:
it enters only as an execution **cashflow** leg, because a 60-minute holding period can
straddle a provider funding settlement (BTC/ETH settle every 8h; SOLUSDT ran a 2h/4h
schedule in 2022-11), and ignoring it would misstate net performance.

The partitions consumed here are **byte-identical copies of the independently verified
ARC-01 funding authority** (`ARC01_FUNDING_MANIFEST.json`, dataset
``5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec``). Reuse is proved by
SHA256 equality, not asserted: `ARC03_FUNDING_REUSE_ASSESSMENT.json` records the
identity check between the ARC-01 partition digests and these partitions.

Frozen semantics (from `ARC01_MANIFEST_V1.json`, reused without reinterpretation):

* ``funding_time_ms == availability_time_ms == settlement_time_ms``; funding is knowable
  exactly at settlement, so a settlement inside ``(entry_time, exit_time]`` is charged.
* ``funding_interval_hours`` is read per row; a permanently fixed 8h cadence is never
  assumed (SOLUSDT 2022 historic 2h/4h rows are honoured).
"""

from __future__ import annotations

import json
import os
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from trading_bot.research.arc03.arc03_normalize import sha256_file

REPO = Path(__file__).resolve().parents[4]
FUNDING_RELPATH = Path("data") / "processed" / "arc03_funding"

#: Certified ARC-01 funding partition digests this authority must reproduce byte-for-byte.
ARC01_FUNDING_PARTITION_SHA256: dict[str, str] = {
    "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
    "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
    "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
}
ARC01_FUNDING_DATASET_SHA256 = "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"


def resolve_funding_dir(data_root: Path | str | None = None) -> Path:
    """Funding partition directory under an explicit or ``ARC03_DATA_ROOT`` data root."""
    if data_root is None:
        env = os.environ.get("ARC03_DATA_ROOT")
        if env:
            data_root = env
    base = Path(data_root) if data_root is not None else REPO
    if not base.is_absolute():
        raise ValueError(f"ARC03 data root must be an absolute path, got {base!r}")
    return base / FUNDING_RELPATH


@dataclass(frozen=True)
class FundingSeries:
    """Certified funding settlements for one symbol (monotonic, conflict-free)."""

    symbol: str
    funding_time_ms: tuple[int, ...]
    funding_rate: tuple[float, ...]
    interval_hours: tuple[int, ...]
    sha256: str
    path: str
    rows: int
    matches_arc01_authority: bool

    def settlements_in(self, after_ms: int, up_to_ms: int) -> list[tuple[int, float]]:
        """Every settlement with ``after_ms < funding_time_ms <= up_to_ms``.

        Returns ``[]`` when the interval is empty. This is the frozen cashflow window:
        a settlement exactly at the entry instant is NOT charged (it was already in the
        price), while a settlement exactly at the exit instant IS charged.
        """
        if up_to_ms <= after_ms:
            return []
        lo = bisect_right(self.funding_time_ms, after_ms)
        hi = bisect_right(self.funding_time_ms, up_to_ms)
        return [
            (self.funding_time_ms[i], self.funding_rate[i]) for i in range(lo, hi)
        ]


def load_funding(symbol: str, *, funding_dir: Path | None = None, verify: bool = True) -> FundingSeries:
    base = funding_dir if funding_dir is not None else resolve_funding_dir()
    path = base / f"{symbol}_funding.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing ARC-03 funding partition: {path}")
    times: list[int] = []
    rates: list[float] = []
    intervals: list[int] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            times.append(int(r["funding_time_ms"]))
            rates.append(float(r["funding_rate"]))
            intervals.append(int(r["funding_interval_hours"]))
    if any(times[i] <= times[i - 1] for i in range(1, len(times))):
        raise ValueError(f"FUNDING_TIMESTAMPS_NOT_STRICTLY_MONOTONIC in {symbol}")
    digest = sha256_file(path) if verify else ""
    expected = ARC01_FUNDING_PARTITION_SHA256.get(symbol)
    return FundingSeries(
        symbol=symbol,
        funding_time_ms=tuple(times),
        funding_rate=tuple(rates),
        interval_hours=tuple(intervals),
        sha256=digest,
        path=str(path),
        rows=len(times),
        matches_arc01_authority=(expected is not None and digest == expected),
    )


def funding_cashflow_return(
    series: FundingSeries, *, entry_time_ms: int, exit_time_ms: int, direction_sign: int
) -> tuple[float, int]:
    """Frozen ARC-03 funding cashflow leg: ``sum(-direction_sign * funding_rate)``.

    Sign convention follows Binance USD-M: with ``funding_rate > 0`` the LONG side pays
    and the SHORT side receives, so LONG (``direction_sign = +1``) accrues ``-rate`` and
    SHORT (``direction_sign = -1``) accrues ``+rate``. Applied to the constant entry
    notional (no intra-hold compounding).

    Returns ``(cashflow_return, settlements_applied)``.
    """
    total = 0.0
    applied = 0
    for _t, rate in series.settlements_in(entry_time_ms, exit_time_ms):
        total += -direction_sign * rate
        applied += 1
    return total, applied


__all__ = [
    "ARC01_FUNDING_DATASET_SHA256",
    "ARC01_FUNDING_PARTITION_SHA256",
    "FUNDING_RELPATH",
    "FundingSeries",
    "funding_cashflow_return",
    "load_funding",
    "resolve_funding_dir",
]
