"""ARC-02 funding-cashflow authority reader (reused certified ARC-01/ARC-03 funding bytes).

ARC-02's signal is purely a BTC/follower 5m price-leg signal. Funding is **not** a signal
input for ARC-02: it enters only as an execution **cashflow** leg, because a 5-minute
holding period can straddle a provider funding settlement (BTCUSDT/ETHUSDT settle every
8h, SOLUSDT ran a 2h/4h schedule in 2022-11; a 5-minute hold therefore contains a
settlement roughly once in 96 entries). Ignoring that flow would misstate net
performance, so the cashflow is frozen rather than omitted.

The partitions consumed here are **byte-identical copies of the independently verified
ARC-01 funding authority** (dataset
``5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec``), reused through the
certified ARC-03 funding root. Reuse is proved by SHA256 equality, not asserted.

Frozen semantics (reused without reinterpretation):

* ``funding_time_ms == availability_time_ms == settlement_time_ms`` — a settlement is
  knowable exactly at its settlement instant;
* ``funding_interval_hours`` is read per row; a permanently fixed 8h cadence is never
  assumed;
* cashflow window is ``(entry_time_ms, exit_time_ms]``: a settlement exactly at the entry
  instant is not charged (already in the entry price), a settlement exactly at the exit
  instant is charged;
* ``cashflow_return = -direction_sign * funding_rate`` on the constant entry notional.
"""

from __future__ import annotations

import json
import os
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from trading_bot.research.arc02.arc02_normalize import sha256_file

REPO = Path(__file__).resolve().parents[4]
FUNDING_RELPATH = Path("data") / "processed" / "arc03_funding"

#: Certified ARC-01 funding partition digests the reused bytes must reproduce exactly.
ARC01_FUNDING_PARTITION_SHA256: dict[str, str] = {
    "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
    "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
    "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
}
ARC01_FUNDING_DATASET_SHA256 = "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec"


def resolve_funding_dir(data_root: Path | str | None = None) -> Path:
    """Funding partition directory under an explicit or ``ARC02_DATA_ROOT`` data root."""
    if data_root is None:
        env = os.environ.get("ARC02_DATA_ROOT")
        if env:
            data_root = env
    base = Path(data_root) if data_root is not None else REPO
    if not base.is_absolute():
        raise ValueError(f"ARC02 data root must be an absolute path, got {base!r}")
    return base / FUNDING_RELPATH


@dataclass(frozen=True)
class FundingSeries:
    """Certified funding settlements for one symbol (monotonic, conflict-free)."""

    symbol: str
    funding_time_ms: tuple[int, ...]
    funding_rate: tuple[float, ...]
    funding_interval_hours: tuple[int, ...]
    sha256: str
    path: str
    rows: int
    index: dict[int, int] = field(default_factory=dict, repr=False)

    def settlements_in(self, entry_time_ms: int, exit_time_ms: int) -> list[tuple[int, float]]:
        """Certified settlements with ``entry_time_ms < funding_time_ms <= exit_time_ms``."""
        left = bisect_right(self.funding_time_ms, entry_time_ms)
        right = bisect_right(self.funding_time_ms, exit_time_ms)
        return [(self.funding_time_ms[i], self.funding_rate[i]) for i in range(left, right)]

    def cashflow_return(self, direction_sign: int, entry_time_ms: int, exit_time_ms: int) -> float:
        """Funding cashflow return over ``(entry, exit]`` for a unit notional position."""
        return sum(-direction_sign * rate for _, rate in self.settlements_in(entry_time_ms, exit_time_ms))


def load_funding(symbol: str, *, funding_dir: Path | None = None, verify: bool = True) -> FundingSeries:
    base = funding_dir if funding_dir is not None else resolve_funding_dir()
    path = base / f"{symbol}_funding.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing ARC-02 funding partition: {path}")
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
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"funding settlements are not strictly monotonic for {symbol}")
    digest = sha256_file(path) if verify else ""
    return FundingSeries(
        symbol=symbol,
        funding_time_ms=tuple(times),
        funding_rate=tuple(rates),
        funding_interval_hours=tuple(intervals),
        sha256=digest,
        path=str(path),
        rows=len(times),
        index={t: i for i, t in enumerate(times)},
    )


__all__ = [
    "ARC01_FUNDING_DATASET_SHA256",
    "ARC01_FUNDING_PARTITION_SHA256",
    "FUNDING_RELPATH",
    "FundingSeries",
    "load_funding",
    "resolve_funding_dir",
]
