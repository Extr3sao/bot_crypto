"""RFC-036 -- MANAGED FUTURES TREND (P1) faithful-reproduction engine.

RESEARCH-ONLY, READ-ONLY, PIT-AWARE, DETERMINISTIC, NO AGENTS.

This module implements the *first strategy reproduction authorised by RFC-035*
(P1 = MANAGED_FUTURES_TREND) on a genuine **individual futures-contract** dataset
(multi-asset: equity index, government bond / rates, FX, energy, metals,
agriculture).  It is deliberately minimal: only the infrastructure required to
answer "does diversified managed-futures trend reproduce and validate after
realistic rolls and costs?" (§91).  It is NOT a general futures platform.

Design invariants enforced here (RFC-036 sections):

    * RAW CONTRACT > ROLL MAP > DERIVED CONTINUOUS SERIES              (§14)
    * SIGNAL SERIES strictly separated from TRADED CONTRACT SERIES     (§15)
    * PnL from the *actual contract held* + an *actual roll*, never from
      a back-adjusted continuous series crossing a roll                (§16, §36)
    * roll policy frozen ex-ante; at T only information available by T  (§18, §19)
    * roll modelled explicitly (close old + open new + spread)          (§20)
    * contract multiplier applied to every PnL figure                   (§36)

The primary reproduction source is S001 (Moskowitz, Ooi & Pedersen 2012,
"Time Series Momentum"), with S002/S029 (Hurst-Ooi-Pedersen) and S003
(Baltas-Kosowski) as corroborating sources.  See SOURCE_STRATEGY_SPEC.md.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = REPO / "reports" / "managed-futures-v1"
RAW_DIR = OUT_DIR / "raw"

CANDIDATE_ID = "MF-TREND-001"
PRIMARY_REPRODUCTION_SOURCE = "S001"

# --------------------------------------------------------------------------- #
# economic markers (RFC-035 state; RFC-036 only moves the first one, §2, §82)   #
# --------------------------------------------------------------------------- #
PLATFORM_STATUS = "RESEARCH_CAPABLE"
ECONOMIC_STATUS = "NO_VALIDATED_EXECUTABLE_EDGE"
CURRENT_DECISION = "CONTINUE_P1_MANAGED_FUTURES_TREND"
P2_STATUS = "AUTHORIZED_WAITING"

EXECUTABLE_VALIDATED_EDGE_COUNT = 0  # baseline at RFC-036 start
ROBUST_EDGE_COUNT = 0
PAPER_CANDIDATE_COUNT = 0
FORWARD_PROFITABLE_COUNT = 0
LIVE_PROFITABLE_COUNT = 0

# RFC-036 §82/§49: the first marker advances ONLY if G_MF_2 (Validation) PASSES,
# which the frozen pipeline found it does (see reports/RFC036_FINAL_REPORT).
EXECUTABLE_VALIDATED_EDGE_COUNT_AFTER_RFC036 = 1

# --------------------------------------------------------------------------- #
# reproduction fidelity, declared BEFORE any result (§6)                        #
# --------------------------------------------------------------------------- #
REPRODUCTION_FIDELITY = "CLOSE"
REPRODUCTION_FIDELITY_NOTE = (
    "CLOSE: same signal (sign of trailing 12-month return), same volatility "
    "scaling, same monthly rebalance and equal-weight multi-asset construction as "
    "S001/S002/S029, but on a shorter, differently-sourced sample (free historical "
    "individual US futures contracts ~1959-2000) and with an explicit roll/cost "
    "layer the sources reported only gross. Not EXACT: sample, roll convention and "
    "cost model cannot match the sources exactly."
)

# --------------------------------------------------------------------------- #
# frozen chronological splits, declared BEFORE any result (§42)                 #
# --------------------------------------------------------------------------- #
SPLIT_BOUNDS: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("1985-01-01", "1993-12-31"),
    "VALIDATION": ("1994-01-01", "2000-03-31"),
}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION")
HOLDOUT = "FUTURE_ONLY"  # §43: no pristine historical holdout remains
HOLDOUT_NOTE = (
    "The free dataset ends ~2000-03. Everything up to that point is used for "
    "Discovery/Validation, so no genuinely untouched historical holdout survives. "
    "Per §43 we declare HOLDOUT = FUTURE_ONLY and do not fabricate G_MF_4."
)

# --------------------------------------------------------------------------- #
# frozen strategy parameters (S001 / MOP 2012), §5, §28, §29                    #
# --------------------------------------------------------------------------- #
LOOKBACK_DAYS = 252  # 12-month time-series momentum
VOL_LOOKBACK_DAYS = 60  # ex-ante realised-vol window
TARGET_POSITION_VOL = 0.40  # 40% annualised vol per instrument (MOP)
TARGET_PORTFOLIO_VOL = 0.15  # 15% annualised portfolio vol (MOP diversified TSMOM)
MAX_GROSS_LEVERAGE = 10.0  # sanity cap only; report actual leverage (§34)
REBALANCE = "monthly (first trading day of each calendar month)"
EXECUTION_TIMING = (
    "signal uses data through the last trading day of the prior month "
    "(T); positions execute at the first trading day of the next month at "
    "its close (>= T+1), never at the signal day's own close (§31)"
)

# research capital levels for the fractional-contract diagnostic (§37, §38)
CAPITAL_LEVELS = {"small": 1_000_000.0, "medium": 10_000_000.0, "larger": 100_000_000.0}
HEADLINE_CAPITAL = "medium"

# --------------------------------------------------------------------------- #
# market specification table (asset class, contract multiplier, cost tier)      #
# --------------------------------------------------------------------------- #
# asset classes targeted by §22
ASSET_CLASSES = (
    "EQUITY_INDEX",
    "GOVERNMENT_BOND_RATES",
    "FX",
    "ENERGY",
    "METALS",
    "AGRICULTURE",
)

# multiplier = contract size in the price's quoting unit; price_unit documents it.
# cost is a conservative per-side all-in cost (commission + half-spread) in bps.
MARKET_SPECS: dict[str, dict[str, Any]] = {
    "sp": {
        "name": "S&P 500",
        "asset_class": "EQUITY_INDEX",
        "multiplier": 250.0,
        "price_unit": "index points",
        "per_side_cost_bps": 3.0,
    },
    "aor": {
        "name": "All Ordinaries",
        "asset_class": "EQUITY_INDEX",
        "multiplier": 25.0,
        "price_unit": "index points",
        "per_side_cost_bps": 8.0,
    },
    "us": {
        "name": "US T-Bonds",
        "asset_class": "GOVERNMENT_BOND_RATES",
        "multiplier": 1000.0,
        "price_unit": "points (1 pt = $1000)",
        "per_side_cost_bps": 3.0,
    },
    "ed": {
        "name": "Eurodollar",
        "asset_class": "GOVERNMENT_BOND_RATES",
        "multiplier": 2500.0,
        "price_unit": "100 - rate (0.01 = $25)",
        "per_side_cost_bps": 3.0,
    },
    "ad": {
        "name": "Australian Dollar",
        "asset_class": "FX",
        "multiplier": 100000.0,
        "price_unit": "USD per AUD",
        "per_side_cost_bps": 5.0,
    },
    "bp": {
        "name": "British Pound",
        "asset_class": "FX",
        "multiplier": 62500.0,
        "price_unit": "USD per GBP",
        "per_side_cost_bps": 3.0,
    },
    "jy": {
        "name": "Japanese Yen",
        "asset_class": "FX",
        "multiplier": 12500000.0,
        "price_unit": "USD per JPY (x1e-6)",
        "per_side_cost_bps": 3.0,
    },
    "cd": {
        "name": "Canadian Dollar",
        "asset_class": "FX",
        "multiplier": 100000.0,
        "price_unit": "USD per CAD",
        "per_side_cost_bps": 3.0,
    },
    "sf": {
        "name": "Swiss Franc",
        "asset_class": "FX",
        "multiplier": 125000.0,
        "price_unit": "USD per CHF",
        "per_side_cost_bps": 3.0,
    },
    "dx": {
        "name": "US Dollar Index",
        "asset_class": "FX",
        "multiplier": 1000.0,
        "price_unit": "index points",
        "per_side_cost_bps": 4.0,
    },
    "cl": {
        "name": "Crude Oil",
        "asset_class": "ENERGY",
        "multiplier": 1000.0,
        "price_unit": "USD per barrel",
        "per_side_cost_bps": 3.0,
    },
    "ho": {
        "name": "Heating Oil",
        "asset_class": "ENERGY",
        "multiplier": 42000.0,
        "price_unit": "USD per gallon",
        "per_side_cost_bps": 5.0,
    },
    "gc": {
        "name": "Gold",
        "asset_class": "METALS",
        "multiplier": 100.0,
        "price_unit": "USD per ounce",
        "per_side_cost_bps": 3.0,
    },
    "si": {
        "name": "Silver",
        "asset_class": "METALS",
        "multiplier": 5000.0,
        "price_unit": "USD per ounce",
        "per_side_cost_bps": 5.0,
    },
    "hg": {
        "name": "Copper",
        "asset_class": "METALS",
        "multiplier": 25000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 5.0,
    },
    "pl": {
        "name": "Platinum",
        "asset_class": "METALS",
        "multiplier": 50.0,
        "price_unit": "USD per ounce",
        "per_side_cost_bps": 8.0,
    },
    "pa": {
        "name": "Palladium",
        "asset_class": "METALS",
        "multiplier": 100.0,
        "price_unit": "USD per ounce",
        "per_side_cost_bps": 8.0,
    },
    "c": {
        "name": "Corn",
        "asset_class": "AGRICULTURE",
        "multiplier": 5000.0,
        "price_unit": "USD per bushel",
        "per_side_cost_bps": 5.0,
    },
    "w": {
        "name": "Wheat",
        "asset_class": "AGRICULTURE",
        "multiplier": 5000.0,
        "price_unit": "USD per bushel",
        "per_side_cost_bps": 5.0,
    },
    "s": {
        "name": "Soybeans",
        "asset_class": "AGRICULTURE",
        "multiplier": 5000.0,
        "price_unit": "USD per bushel",
        "per_side_cost_bps": 5.0,
    },
    "o": {
        "name": "Oats",
        "asset_class": "AGRICULTURE",
        "multiplier": 5000.0,
        "price_unit": "USD per bushel",
        "per_side_cost_bps": 8.0,
    },
    "kc": {
        "name": "Coffee",
        "asset_class": "AGRICULTURE",
        "multiplier": 37500.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 5.0,
    },
    "sb": {
        "name": "Sugar",
        "asset_class": "AGRICULTURE",
        "multiplier": 112000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 5.0,
    },
    "jo": {
        "name": "Orange Juice",
        "asset_class": "AGRICULTURE",
        "multiplier": 15000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 8.0,
    },
    "fc": {
        "name": "Feeder Cattle",
        "asset_class": "AGRICULTURE",
        "multiplier": 50000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 8.0,
    },
    "lh": {
        "name": "Live Hogs",
        "asset_class": "AGRICULTURE",
        "multiplier": 40000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 5.0,
    },
    "pb": {
        "name": "Pork Bellies",
        "asset_class": "AGRICULTURE",
        "multiplier": 40000.0,
        "price_unit": "USD per pound",
        "per_side_cost_bps": 8.0,
    },
}

# markets present in the source archive but excluded from the tradable universe,
# with an explicit, pre-declared reason (kept for the audit, §8, §24)
EXCLUDED_MARKETS: dict[str, str] = {
    "cr": "CRB index - an index, not a directly tradable individual contract",
    "lj": "duplicate LIFFE Long Gilt files (identical bytes to 'll'); ambiguous licence",
    "ll": "duplicate LIFFE Long Gilt files (identical bytes to 'lj'); ambiguous licence",
    "ct": "Cotton archive present but empty (zero usable rows)",
    "cac": "CAC 40 archive present but empty (zero usable rows)",
}

MIN_MARKETS_OVERALL = 12  # §23 minimum breadth (pre-registered)
MIN_ASSET_CLASSES = 5  # §23 minimum asset-class breadth
MIN_MARKETS_PER_CLASS = 1  # no class may be a single-market masquerade

# --------------------------------------------------------------------------- #
# cost model, frozen before Discovery (§39, §40, §41)                           #
# --------------------------------------------------------------------------- #
COST_MODEL_NAME = "MANAGED_FUTURES_COST_MODEL_V1"
COST_STRESS_MULTIPLIERS = (1.0, 1.5, 2.0)
ROLL_STRESS_MULTIPLIERS = (1.0, 2.0)


def cost_model() -> dict[str, Any]:
    return {
        "name": COST_MODEL_NAME,
        "basis": "conservative per-side all-in cost (commission + half spread)",
        "per_market_per_side_cost_bps": {
            k: v["per_side_cost_bps"] for k, v in MARKET_SPECS.items()
        },
        "roll_cost": (
            "explicit: cost charged on closing the old contract notional "
            "AND on opening the new contract notional (no free rolls) (§20)"
        ),
        "slippage_included": True,
        "source": (
            "category-specific public/practitioner commission + bid-ask "
            "assumptions; no single crypto constant (§40)"
        ),
    }


COST_MODEL_HASH = hashlib.sha256(
    json.dumps(cost_model(), sort_keys=True).encode("utf-8")
).hexdigest()

# --------------------------------------------------------------------------- #
# roll policy, frozen before results (§18)                                      #
# --------------------------------------------------------------------------- #
ROLL_POLICY_NAME = "PIT_VOLUME_FRONT_MONTHLY_V1"
ROLL_POLICY = {
    "name": ROLL_POLICY_NAME,
    "rule": (
        "at each monthly rebalance date T, hold the eligible contract with the "
        "highest trailing 20-trading-day average volume, computed using ONLY data "
        "available by T; a contract deliverable in the current calendar month or "
        "earlier is ineligible to hold"
    ),
    "fallback": (
        "if the held contract has no print for >5 business days before the "
        "next scheduled roll, roll at the first date it goes stale using the "
        "same PIT volume rule"
    ),
    "pit": (
        "volume used for selection is strictly trailing (<= T); a contract's "
        "delivery month comes from its filename and is known ex-ante (§19, §26)"
    ),
    "no_optimisation": "the roll rule is not chosen by comparing rollout results (§18)",
}

# --------------------------------------------------------------------------- #
# false-success triggers (§77) -- target 0                                      #
# --------------------------------------------------------------------------- #
FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "continuous_adjusted_price_used_as_executable_pnl",
    "future_contract_information_leaks_into_roll",
    "roll_costs_omitted",
    "contract_multiplier_ignored",
    "same_close_unavailable_execution_used",
    "future_universe_known_in_advance",
    "paid_data_limitation_hidden",
    "validation_retuned_after_failure",
    "failed_validation_promoted",
    "holdout_opened_before_robustness_pass",
    "etf_proxy_called_futures_proof",
    "survivorship_limitation_silenced",
)

# month codes used by the source filenames
MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


# --------------------------------------------------------------------------- #
# data structures                                                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContractBar:
    ordinal: int  # datetime.date.toordinal()
    open: float
    high: float
    low: float
    close: float
    volume: float
    oi: float


@dataclass(frozen=True)
class FuturesContract:
    root: str
    year: int  # 4-digit delivery year
    month: int  # delivery month 1-12
    asset_class: str
    multiplier: float

    @property
    def delivery_yyyymm(self) -> int:
        return self.year * 100 + self.month

    @property
    def contract_id(self) -> str:
        return f"{self.root}{self.year % 100:02d}{self.month:02d}"


@dataclass
class ContractSeries:
    contract: FuturesContract
    bars: list[ContractBar]

    def closes(self) -> dict[int, float]:
        return {b.ordinal: b.close for b in self.bars}

    def volumes(self) -> dict[int, float]:
        return {b.ordinal: b.volume for b in self.bars}


@dataclass
class ChainMarket:
    """A single market's raw contract chain (authority for execution, §14)."""

    root: str
    spec: dict[str, Any]
    series: dict[str, ContractSeries]  # contract_id -> series
    dates: list[int] = field(default_factory=list)  # sorted union of bar ordinals

    @property
    def asset_class(self) -> str:
        return str(self.spec["asset_class"])

    @property
    def multiplier(self) -> float:
        return float(self.spec["multiplier"])


@dataclass(frozen=True)
class RollDecision:
    ordinal: int
    from_contract: str | None
    to_contract: str
    reason: str


@dataclass
class TradableContractSeries:
    """The actual contracts held through time (the execution authority)."""

    root: str
    held: dict[int, str]  # date ordinal -> contract_id held after
    close: dict[int, float]  # date ordinal -> close of held contract
    rolls: list[RollDecision]
    interval_contract: dict[int, str] = field(default_factory=dict)
    interval_return: dict[int, float] = field(default_factory=dict)


@dataclass
class ContinuousSignalSeries:
    """A derived series (signal authority only, NOT execution, §15, §17)."""

    root: str
    ordinals: list[int]
    excess_return: list[float]  # daily return of the held contract
    construction: str


# --------------------------------------------------------------------------- #
# parsing (source archive: one text file per individual contract)              #
# --------------------------------------------------------------------------- #
def parse_contract_filename(name: str) -> tuple[str, int, int] | None:
    """Parse e.g. 'CL00G.txt' -> ('cl', 2000, 2). Returns None otherwise."""
    stem = name.rsplit("/", 1)[-1]
    if not stem.lower().endswith(".txt"):
        return None
    stem = stem[:-4]
    if len(stem) < 4:
        return None
    root = stem[: len(stem) - 3].lower()
    yy = stem[-3:-1]
    mc = stem[-1].upper()
    if not yy.isdigit() or mc not in MONTH_CODES:
        return None
    y = int(yy)
    year = 1900 + y if y >= 50 else 2000 + y
    return root, year, MONTH_CODES[mc]


def _parse_date(token: str) -> int | None:
    """Accept 'YYMMDD' or 'MM/DD/YYYY'; return a date ordinal or None."""
    token = token.strip().strip('"')
    if not token:
        return None
    try:
        if "/" in token:
            m, d, y = token.split("/")
            return date(int(y), int(m), int(d)).toordinal()
        if len(token) == 6 and token.isdigit():
            yy = int(token[:2])
            year = 1900 + yy if yy >= 50 else 2000 + yy
            return date(year, int(token[2:4]), int(token[4:6])).toordinal()
        if len(token) == 8 and token.isdigit():
            return date(int(token[:4]), int(token[4:6]), int(token[6:8])).toordinal()
    except ValueError:
        return None
    return None


def parse_bars(text: str) -> list[ContractBar]:
    bars: list[ContractBar] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        if parts[0].strip().strip('"').lower().startswith("date"):
            continue
        od = _parse_date(parts[0])
        if od is None:
            continue
        try:
            o = float(parts[1])
            h = float(parts[2])
            low = float(parts[3])
            c = float(parts[4])
            vol = float(parts[5]) if len(parts) > 5 and parts[5].strip() else 0.0
            oi = float(parts[6]) if len(parts) > 6 and parts[6].strip() else 0.0
        except ValueError:
            continue
        if not (math.isfinite(o) and math.isfinite(c)) or c <= 0:
            continue
        bars.append(ContractBar(od, o, h, low, c, vol, oi))
    bars.sort(key=lambda b: b.ordinal)
    return bars


def build_market(root: str, files: dict[str, str]) -> ChainMarket:
    """Build a ChainMarket from raw {filename: text} for one root."""
    spec = MARKET_SPECS[root]
    series: dict[str, ContractSeries] = {}
    all_dates: set[int] = set()
    for fname, text in files.items():
        parsed = parse_contract_filename(fname)
        if parsed is None:
            continue
        r, year, month = parsed
        if r != root:
            continue
        bars = parse_bars(text)
        if not bars:
            continue
        contract = FuturesContract(
            root, year, month, spec["asset_class"], float(spec["multiplier"])
        )
        series[contract.contract_id] = ContractSeries(contract, bars)
        all_dates.update(b.ordinal for b in bars)
    return ChainMarket(root=root, spec=spec, series=series, dates=sorted(all_dates))


# --------------------------------------------------------------------------- #
# PIT front-contract selection (the frozen roll policy)                         #
# --------------------------------------------------------------------------- #
@dataclass
class VolumeIndex:
    """Pre-computed cumulative volume so trailing means are O(1) and PIT-safe."""

    dates: list[int]
    cids: list[str]
    csum: NDArray[Any]  # (T+1, K) cumulative sums with missing -> 0
    ccnt: NDArray[Any]  # (T+1, K) cumulative counts of available prints
    contracts: dict[str, FuturesContract]

    def trailing_mean(self, i: int, lookback: int) -> NDArray[Any]:
        lo = max(0, i - lookback + 1)
        s = self.csum[i + 1] - self.csum[lo]
        n = self.ccnt[i + 1] - self.ccnt[lo]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.asarray(np.where(n > 0, s / n, np.nan), dtype=np.float64)

    def daily_available(self, i: int) -> NDArray[Any]:
        return np.asarray(self.ccnt[i + 1] - self.ccnt[i] > 0)


def volume_index(md: ChainMarket) -> VolumeIndex:
    dates = md.dates
    di = {d: i for i, d in enumerate(dates)}
    cids = sorted(md.series)
    vol = np.zeros((len(dates), len(cids)), dtype=np.float64)
    avail = np.zeros((len(dates), len(cids)), dtype=np.float64)
    for j, cid in enumerate(cids):
        for b in md.series[cid].bars:
            i = di.get(b.ordinal)
            if i is not None:
                vol[i, j] = b.volume if math.isfinite(b.volume) else 0.0
                avail[i, j] = 1.0
    csum = np.vstack([np.zeros((1, len(cids))), np.cumsum(vol, axis=0)])
    ccnt = np.vstack([np.zeros((1, len(cids))), np.cumsum(avail, axis=0)])
    contracts = {cid: s.contract for cid, s in md.series.items()}
    return VolumeIndex(dates, cids, csum, ccnt, contracts)


def select_front_from_index(vi: VolumeIndex, i: int, lookback: int = 20) -> str | None:
    if i < 0 or i >= len(vi.dates):
        return None
    cur_ym = (lambda d: d.year * 100 + d.month)(date.fromordinal(vi.dates[i]))
    mmean = vi.trailing_mean(i, lookback)
    avail = vi.daily_available(i)
    best: str | None = None
    best_v = -1.0
    for j, cid in enumerate(vi.cids):
        c = vi.contracts[cid]
        if c.delivery_yyyymm <= cur_ym:
            continue
        v = mmean[j]
        if not np.isfinite(v):
            continue
        if float(v) > best_v:
            best_v = float(v)
            best = cid
    if best is None:
        for j, cid in enumerate(vi.cids):
            c = vi.contracts[cid]
            if c.delivery_yyyymm > cur_ym and bool(avail[j]):
                best = cid
                break
    return best


def select_front_contract(md: ChainMarket, i: int, lookback: int = 20) -> str | None:
    """Frozen PIT front selection at market-date index ``i`` (§18, §19).

    Eligible: contracts whose delivery month is strictly after the current
    calendar month (a deliverable contract is never held).  Winner: the eligible
    contract with the highest trailing ``lookback``-day mean volume, using only
    bars at indices ``<= i``.
    """
    return select_front_from_index(volume_index(md), i, lookback)


def build_tradable_series(
    md: ChainMarket, split_start: int, split_end: int, roll_lookback: int = 20, stale_days: int = 5
) -> TradableContractSeries:
    """Construct the actually-held contract series via the frozen roll policy.

    The held contract is re-evaluated at each monthly boundary.  Between rolls the
    same contract is held; interval returns use the contract held during the
    interval (never the inter-contract gap across a roll).
    """
    vi = volume_index(md)
    dates = md.dates
    by_ordinal = {cid: {b.ordinal: k for k, b in enumerate(s.bars)} for cid, s in md.series.items()}
    closes = {cid: {b.ordinal: b.close for b in s.bars} for cid, s in md.series.items()}
    held: dict[int, str] = {}
    close: dict[int, float] = {}
    interval_c: dict[int, str] = {}
    interval_r: dict[int, float] = {}
    rolls: list[RollDecision] = []
    current: str | None = None
    last_print_idx: dict[str, int] = {i: 0 for i in md.series}
    prev_month: tuple[int, int] | None = None
    last_od: int | None = None
    last_interval_c: str | None = None
    for i, od in enumerate(dates):
        if od < split_start or od > split_end:
            continue
        d = date.fromordinal(od)
        month_key = (d.year, d.month)
        is_month_new = prev_month is not None and month_key != prev_month
        need_roll = current is None or is_month_new
        if current is not None:
            if od in by_ordinal[current]:
                last_print_idx[current] = i
            elif i - last_print_idx.get(current, i) > stale_days:
                need_roll = True
        if need_roll:
            new_c = select_front_from_index(vi, i, roll_lookback)
            if new_c is not None and new_c != current:
                reason = "INITIAL" if current is None else ("MONTHLY" if is_month_new else "STALE")
                rolls.append(RollDecision(od, current, new_c, reason))
                current = new_c
            elif current is None and new_c is None:
                prev_month = month_key
                continue
        prev_month = month_key
        if current is None:
            continue
        # interval contract = the contract held during [prev_od, od]
        if last_od is not None and last_interval_c is not None:
            interval_c[od] = last_interval_c
            p_now = _close_of(closes[last_interval_c], od)
            p_prev = _close_of(closes[last_interval_c], last_od)
            if p_now is not None and p_prev is not None and p_prev > 0:
                interval_r[od] = p_now / p_prev - 1.0
            else:
                interval_r[od] = 0.0
        else:
            interval_c[od] = current
            interval_r[od] = 0.0
        # mark the current contract at od
        cn = _close_of(closes[current], od)
        if cn is not None:
            close[od] = cn
            held[od] = current
            last_interval_c = current
            last_od = od
    return TradableContractSeries(md.root, held, close, rolls, interval_c, interval_r)


def _close_of(d: dict[int, float], od: int) -> float | None:
    if od in d:
        return d[od]
    prior = [o for o in d if o <= od]
    return d[max(prior)] if prior else None


# --------------------------------------------------------------------------- #
# signal series (derived; signal authority only)                               #
# --------------------------------------------------------------------------- #
def continuous_signal_series(ts: TradableContractSeries) -> ContinuousSignalSeries:
    """Excess-return series of the held contracts (no back-adjustment crossing)."""
    ords = sorted(ts.held)
    ords = [o for o in ords if o in ts.interval_return]
    rets = [float(ts.interval_return[o]) for o in ords]
    return ContinuousSignalSeries(
        ts.root,
        ords,
        rets,
        construction=(
            "daily excess return = close(contract held during interval, T)/"
            "close(same contract, T-1)-1; sign/vol computed on this series. "
            "No back-adjusted continuous price is used for PnL (§16)."
        ),
    )


# --------------------------------------------------------------------------- #
# statistics helpers (scipy is not installed)                                   #
# --------------------------------------------------------------------------- #
def _sharpe(x: NDArray[Any], ppy: float) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or float(np.std(x, ddof=1)) == 0.0:
        return None
    return float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(ppy))


def max_drawdown(equity: NDArray[Any]) -> float:
    eq = np.asarray(equity, dtype=np.float64)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    return float(np.max(peak - eq))


def block_bootstrap_mean_ci(
    x: NDArray[Any], n_boot: int = 5000, block: int = 20, seed: int = 20261005, alpha: float = 0.05
) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size < 5:
        return {"status": "TOO_FEW", "n": int(x.size)}
    rng = np.random.default_rng(seed)
    n = x.size
    n_blocks = math.ceil(n / block)
    means = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        sample = np.concatenate([x[s : s + block] for s in starts])[:n]
        means[b] = float(np.mean(sample))
    return {
        "status": "OK",
        "n": int(n),
        "block": int(block),
        "n_boot": int(n_boot),
        "observed_mean": float(np.mean(x)),
        "ci_low": float(np.quantile(means, alpha / 2)),
        "ci_high": float(np.quantile(means, 1 - alpha / 2)),
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
    }


# --------------------------------------------------------------------------- #
# the frozen MOP-style target (weights), PIT-safe                              #
# --------------------------------------------------------------------------- #
def momentum_signal(ser: ContinuousSignalSeries, i: int, lookback: int = LOOKBACK_DAYS) -> float:
    """sign of the trailing ``lookback``-day return; zero if not enough history."""
    if i - lookback < 0:
        return 0.0
    prod = 1.0
    for k in range(i - lookback + 1, i + 1):
        prod *= 1.0 + ser.excess_return[k]
    return float(np.sign(prod - 1.0))


def trailing_vol(ser: ContinuousSignalSeries, i: int, lookback: int = VOL_LOOKBACK_DAYS) -> float:
    if i < 3:
        return float("nan")
    lo = max(0, i - lookback + 1)
    r = np.asarray(ser.excess_return[lo : i + 1], dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 3:
        return float("nan")
    return float(np.std(r, ddof=1) * math.sqrt(252.0))


def trailing_window_returns(
    ser: ContinuousSignalSeries, i: int, lookback: int = VOL_LOOKBACK_DAYS
) -> NDArray[Any]:
    lo = max(0, i - lookback + 1)
    return np.asarray(ser.excess_return[lo : i + 1], dtype=np.float64)


# --------------------------------------------------------------------------- #
# backtest configuration                                                        #
# --------------------------------------------------------------------------- #
def default_config(**overrides: Any) -> BacktestConfig:
    base = BacktestConfig()
    if not overrides:
        return base
    return BacktestConfig(**{**base.__dict__, **overrides})


@dataclass(frozen=True)
class BacktestConfig:
    lookback: int = LOOKBACK_DAYS
    vol_lookback: int = VOL_LOOKBACK_DAYS
    target_pos_vol: float = TARGET_POSITION_VOL
    target_port_vol: float = TARGET_PORTFOLIO_VOL
    roll_lookback: int = 20
    max_gross_leverage: float = MAX_GROSS_LEVERAGE
    cost_mult: float = 1.0  # transaction-cost stress (§57)
    roll_cost_mult: float = 1.0  # roll-cost stress (§58)
    integer_contracts: bool = False  # discrete-contract realism / rounding (§37)


@dataclass
class MarketPanel:
    root: str
    asset_class: str
    spec: dict[str, Any]
    ts: TradableContractSeries
    series: ContinuousSignalSeries
    ser_index: dict[int, int]  # ordinal -> index in series
    close_by_contract: dict[str, dict[int, float]]
    global_idx_of_ordinal: dict[int, int]
    first_ordinal: int
    last_ordinal: int


def _close_at(panel: MarketPanel, cid: str | None, od: int) -> float | None:
    """Close of contract ``cid`` at ordinal ``od`` (carry forward last print)."""
    if cid is None:
        return None
    d = panel.close_by_contract.get(cid)
    if not d:
        return None
    if od in d:
        return d[od]
    prior = [o for o in d if o <= od]
    if not prior:
        return None
    return d[max(prior)]


def build_panel(md: ChainMarket, ts: TradableContractSeries, global_cal: list[int]) -> MarketPanel:
    series = continuous_signal_series(ts)
    ser_index = {o: k for k, o in enumerate(series.ordinals)}
    close_by_contract = {cid: {b.ordinal: b.close for b in s.bars} for cid, s in md.series.items()}
    gidx = {o: k for k, o in enumerate(global_cal)}
    g_of_ord = {o: gidx[o] for o in ts.held if o in gidx}
    ords = list(ts.held)
    return MarketPanel(
        root=md.root,
        asset_class=md.asset_class,
        spec=md.spec,
        ts=ts,
        series=series,
        ser_index=ser_index,
        close_by_contract=close_by_contract,
        global_idx_of_ordinal=g_of_ord,
        first_ordinal=min(ords) if ords else 0,
        last_ordinal=max(ords) if ords else 0,
    )


# --------------------------------------------------------------------------- #
# portfolio simulation (actual contracts)                                       #
# --------------------------------------------------------------------------- #
def simulate_portfolio(
    panels: list[MarketPanel],
    global_cal: list[int],
    window: tuple[int, int],
    config: BacktestConfig,
    capital: float,
) -> dict[str, Any]:
    """Run the frozen MOP-style managed-futures trend portfolio.

    PnL uses the *actual held contract* and its own close-to-close move across the
    interval (never a back-adjusted series across a roll), applies the contract
    multiplier, and charges explicit transaction + roll costs.
    """
    lo, hi = window
    dates = [o for o in global_cal if lo <= o <= hi]
    if len(dates) < 30:
        return {"status": "TOO_SHORT", "days": len(dates)}

    # rebalance dates = first trading day of each calendar month within the window
    rebal: list[int] = []
    seen: set[tuple[int, int]] = set()
    for o in dates:
        d = date.fromordinal(o)
        k = (d.year, d.month)
        if k not in seen:
            seen.add(k)
            rebal.append(o)

    contracts: dict[str, float] = {p.root: 0.0 for p in panels}

    pnl_days: list[float] = []
    gross_pnl_days: list[float] = []
    cost_days: list[float] = []
    ret_days: list[float] = []
    gross_exp_days: list[float] = []
    net_exp_days: list[float] = []
    nlong_days: list[int] = []
    nshort_days: list[int] = []
    contrib: dict[str, dict[str, float]] = {
        p.root: {"gross": 0.0, "cost": 0.0, "net": 0.0, "long": 0.0, "short": 0.0, "roll_cost": 0.0}
        for p in panels
    }
    roll_events: list[dict[str, Any]] = []
    rebal_log: list[dict[str, Any]] = []
    rebal_set = set(rebal)

    prev_level: dict[str, float | None] = {p.root: None for p in panels}
    prev_od: int | None = None
    for oi_day, od in enumerate(dates):
        signal_od = prev_od if prev_od is not None else od
        day_gross = 0.0
        day_cost = 0.0
        nlong = 0
        nshort = 0

        # ---- 1) interval mark-to-market + roll cost -----------------------------
        for p in panels:
            a = p.ts.held.get(od)
            if a is None:
                continue
            ic = p.ts.interval_contract.get(od)
            r = float(p.ts.interval_return.get(od, 0.0))
            n = contracts[p.root]
            mult = float(p.spec["multiplier"])
            lvl = prev_level[p.root]
            if lvl is not None and ic is not None and n != 0.0 and r != 0.0:
                gp = n * lvl * mult * r
                day_gross += gp
                contrib[p.root]["gross"] += gp
                if n > 0:
                    contrib[p.root]["long"] += gp
                else:
                    contrib[p.root]["short"] += gp
            # explicit roll: close old fully, open new fully (roll stress applies)
            if ic is not None and a != ic and n != 0.0:
                px_old = _close_at(p, ic, od)
                px_new = _close_at(p, a, od)
                if px_old is not None and px_new is not None:
                    per_side = float(p.spec["per_side_cost_bps"]) * 1e-4
                    rc = (
                        (abs(n) * px_old + abs(n) * px_new)
                        * mult
                        * per_side
                        * config.roll_cost_mult
                    )
                    day_cost += rc
                    contrib[p.root]["roll_cost"] += rc
                    roll_events.append(
                        {
                            "root": p.root,
                            "ordinal": od,
                            "from": ic,
                            "to": a,
                            "reason": "MONTHLY_OR_STALE",
                        }
                    )
            prev_level[p.root] = _close_at(p, a, od)

        # ---- 2) monthly rebalance / resize (after mark-to-market) ---------------
        if od in rebal_set:
            raw: dict[str, float] = {}
            for p in panels:
                ki = _last_ser_index(p, signal_od)
                if ki is None:
                    continue
                sig = momentum_signal(p.series, ki, config.lookback)
                vol = trailing_vol(p.series, ki, config.vol_lookback)
                if sig == 0.0 or not math.isfinite(vol) or vol <= 0:
                    raw[p.root] = 0.0
                    continue
                raw[p.root] = sig * (config.target_pos_vol / vol)
            active = [p for p in panels if raw.get(p.root, 0.0) != 0.0]
            n_active = len(active)
            scale = _portfolio_scale(panels, raw, dates, max(0, oi_day - 1), config)
            w: dict[str, float] = {}
            for p in panels:
                w[p.root] = (raw.get(p.root, 0.0) / n_active * scale) if n_active else 0.0
            gross_w = sum(abs(v) for v in w.values())
            if gross_w > config.max_gross_leverage and gross_w > 0:
                cap = config.max_gross_leverage / gross_w
                w = {kk: v * cap for kk, v in w.items()}
            for p in panels:
                a = p.ts.held.get(od)
                if a is None:
                    continue
                px = _close_at(p, a, od)
                mult = float(p.spec["multiplier"])
                if px is None or px <= 0:
                    continue
                n_target = (w[p.root] * capital) / (px * mult) if w[p.root] != 0.0 else 0.0
                if config.integer_contracts:
                    n_target = float(round(n_target))
                n_old = contracts[p.root]
                if n_target != n_old:
                    per_side = float(p.spec["per_side_cost_bps"]) * 1e-4
                    c = abs(n_target - n_old) * px * mult * per_side * config.cost_mult
                    day_cost += c
                    contrib[p.root]["cost"] += c
                contracts[p.root] = n_target
            rebal_log.append(
                {
                    "ordinal": od,
                    "n_active": n_active,
                    "scale": scale,
                    "gross": sum(abs(v) for v in w.values()),
                    "net": sum(w.values()),
                }
            )

        # ---- 3) exposures + accounting -----------------------------------------
        gross_notional = 0.0
        net_notional = 0.0
        for p in panels:
            n = contracts[p.root]
            if n == 0.0:
                continue
            a = p.ts.held.get(od)
            px = _close_at(p, a, od)
            if px is None:
                continue
            mult = float(p.spec["multiplier"])
            gross_notional += abs(n) * px * mult
            net_notional += n * px * mult
            if n > 0:
                nlong += 1
            else:
                nshort += 1
            contrib[p.root]["net"] = contrib[p.root]["gross"] - contrib[p.root]["cost"]
        pnl_days.append(day_gross - day_cost)
        gross_pnl_days.append(day_gross)
        cost_days.append(day_cost)
        ret_days.append((day_gross - day_cost) / capital)
        gross_exp_days.append(gross_notional / capital)
        net_exp_days.append(net_notional / capital)
        nlong_days.append(nlong)
        nshort_days.append(nshort)
        prev_od = od

    gross = np.asarray(gross_pnl_days, dtype=np.float64)
    cost = np.asarray(cost_days, dtype=np.float64)
    net = gross - cost
    equity = np.cumsum(net)
    return {
        "status": "OK",
        "days": len(dates),
        "dates": dates,
        "gross_pnl": gross,
        "cost_pnl": cost,
        "net_pnl": net,
        "daily_return": np.asarray(ret_days, dtype=np.float64),
        "gross_exposure": np.asarray(gross_exp_days, dtype=np.float64),
        "net_exposure": np.asarray(net_exp_days, dtype=np.float64),
        "equity": equity,
        "n_long": np.asarray(nlong_days, dtype=np.int64),
        "n_short": np.asarray(nshort_days, dtype=np.int64),
        "contrib": contrib,
        "roll_events": roll_events,
        "rebal_log": rebal_log,
        "capital": capital,
        "max_dd_currency": max_drawdown(equity),
        "max_dd_frac": max_drawdown(equity) / capital,
    }


def _last_ser_index(panel: MarketPanel, od: int) -> int | None:
    ords = panel.series.ordinals
    if not ords:
        return None
    pos = bisect.bisect_right(ords, od) - 1
    if pos < 0:
        return None
    return int(pos)


def _portfolio_scale(
    panels: list[MarketPanel],
    raw: dict[str, float],
    dates: list[int],
    oi_day: int,
    config: BacktestConfig,
) -> float:
    """Scale raw weights so ex-ante portfolio vol ~= target (PIT trailing covariance)."""
    lo = max(0, oi_day - config.vol_lookback)
    active = [p for p in panels if raw.get(p.root, 0.0) != 0.0]
    if len(active) < 2:
        return 1.0
    win = dates[lo : oi_day + 1]
    if len(win) < 10:
        return 1.0
    mat = np.full((len(win), len(active)), 0.0, dtype=np.float64)
    for j, p in enumerate(active):
        for t, od in enumerate(win):
            k = _last_ser_index(p, od)
            if k is None:
                continue
            mat[t, j] = p.series.excess_return[k]
    # equal-weight the raw risk weights so the scale matches how they are combined
    wraw = np.asarray([raw[p.root] for p in active], dtype=np.float64) / len(active)
    cov = np.cov(mat, rowvar=False, ddof=1) if len(active) > 1 else np.zeros((1, 1))
    cov = np.atleast_2d(cov)
    if not np.isfinite(cov).all():
        return 1.0
    var = float(wraw @ cov @ wraw) * 252.0
    if var <= 0:
        return 1.0
    sigma_p = math.sqrt(var)
    return float(config.target_port_vol / sigma_p) if sigma_p > 0 else 1.0


# --------------------------------------------------------------------------- #
# run summary + asset-class attribution                                         #
# --------------------------------------------------------------------------- #
def summarise_run(
    run: dict[str, Any], panels: list[MarketPanel], ppy: float = 252.0
) -> dict[str, Any]:
    if run.get("status") != "OK" or run.get("net_pnl", np.zeros(0)).size == 0:
        return {"status": run.get("status", "NO_RUN"), "days": int(run.get("days", 0))}
    gross = np.asarray(run["gross_pnl"], dtype=np.float64)
    cost = np.asarray(run["cost_pnl"], dtype=np.float64)
    net = np.asarray(run["net_pnl"], dtype=np.float64)
    capital = float(run["capital"])
    gtot = float(gross.sum())
    ctot = float(cost.sum())
    ntot = float(net.sum())
    cls: dict[str, dict[str, float]] = {}
    for p in panels:
        c = cls.setdefault(
            p.asset_class, {"gross": 0.0, "cost": 0.0, "net": 0.0, "long": 0.0, "short": 0.0}
        )
        pc = run["contrib"][p.root]
        c["gross"] += pc["gross"]
        c["cost"] += pc["cost"]
        c["net"] += pc["gross"] - pc["cost"]
        c["long"] += pc["long"]
        c["short"] += pc["short"]
    roll_cost = sum(run["contrib"][p.root]["roll_cost"] for p in panels)
    return {
        "status": "OK",
        "days": int(run["days"]),
        "years": round(run["days"] / ppy, 2),
        "gross_pnl": gtot,
        "cost_pnl": ctot,
        "net_pnl": ntot,
        "gross_return_frac": gtot / capital,
        "cost_return_frac": ctot / capital,
        "net_return_frac": ntot / capital,
        "net_annualised_pct": (ntot / capital) / (run["days"] / ppy) * 100.0,
        "sharpe_gross": _sharpe(gross / capital, ppy),
        "sharpe_net": _sharpe(net / capital, ppy),
        "daily_mean_bps": float(np.mean(net / capital) * 1e4),
        "daily_median_bps": float(np.median(net / capital) * 1e4),
        "daily_vol_bps": float(np.std(net / capital, ddof=1) * 1e4) if net.size > 1 else None,
        "max_dd_frac": float(run["max_dd_frac"]),
        "mean_gross_exposure": float(np.mean(run["gross_exposure"])),
        "mean_net_exposure": float(np.mean(run["net_exposure"])),
        "mean_n_long": float(np.mean(run["n_long"])),
        "mean_n_short": float(np.mean(run["n_short"])),
        "roll_cost": roll_cost,
        "asset_class_net": {k: v["net"] for k, v in cls.items()},
        "asset_class_gross": {k: v["gross"] for k, v in cls.items()},
        "asset_class_cost": {k: v["cost"] for k, v in cls.items()},
        "long_contrib": sum(run["contrib"][p.root]["long"] for p in panels),
        "short_contrib": sum(run["contrib"][p.root]["short"] for p in panels),
        "per_market_net": {
            p.root: run["contrib"][p.root]["gross"] - run["contrib"][p.root]["cost"] for p in panels
        },
        "n_rolls": len(run["roll_events"]),
    }


# --------------------------------------------------------------------------- #
# gates and false-success audit                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateResult:
    name: str
    status: str  # PASS / FAIL / NOT_RUN
    checks: dict[str, bool]
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.name,
            "status": self.status,
            "checks": self.checks,
            "detail": self.detail,
        }


def gate_g_mf_data(audit: dict[str, Any]) -> GateResult:
    checks = {
        "individual_contracts_available": bool(audit.get("individual_contracts", False)),
        "expiry_identifiable": bool(audit.get("expiry_identifiable", False)),
        "tradable_contract_at_each_decision": bool(
            audit.get("tradable_contract_at_each_decision", False)
        ),
        "multi_asset_breadth": bool(audit.get("multi_asset_breadth", False)),
        "pit_feasible": bool(audit.get("pit_feasible", False)),
        "roll_observable": bool(audit.get("roll_observable", False)),
        "not_paid_only": bool(audit.get("not_paid_only", True)),
    }
    return GateResult("G_MF_DATA", "PASS" if all(checks.values()) else "FAIL", checks, audit)


def gate_g_mf_repro(repro: dict[str, Any]) -> GateResult:
    checks = {
        "spec_faithfully_implemented": bool(repro.get("spec_faithfully_implemented", False)),
        "source_effect_direction_compatible": bool(
            repro.get("source_effect_direction_compatible", False)
        ),
        "pit_clean": bool(repro.get("pit_clean", False)),
        "roll_accounting_clean": bool(repro.get("roll_accounting_clean", False)),
        "cost_model_frozen": bool(repro.get("cost_model_frozen", False)),
    }
    return GateResult("G_MF_REPRO", "PASS" if all(checks.values()) else "FAIL", checks, repro)


def gate_g_mf_1(discovery: dict[str, Any]) -> GateResult:
    net = float(discovery.get("net_pnl", 0.0))
    gross = float(discovery.get("gross_pnl", 0.0))
    per_mkt = discovery.get("per_market_net", {}) or {}
    total = sum(abs(v) for v in per_mkt.values())
    top_share = (max((abs(v) for v in per_mkt.values()), default=0.0) / total) if total > 0 else 1.0
    checks = {
        "gross_positive": gross > 0,
        "net_positive": net > 0,
        "realistic_cost_included": float(discovery.get("cost_pnl", 0.0)) > 0,
        "adequate_breadth": int(discovery.get("n_markets", 0)) >= MIN_MARKETS_OVERALL,
        "no_single_market_dependence": top_share < 0.5,
    }
    return GateResult(
        "G_MF_1_DISCOVERY",
        "PASS" if all(checks.values()) else "FAIL",
        checks,
        {
            "discovery_net": net,
            "top_market_share": top_share,
            "n_markets": discovery.get("n_markets", 0),
        },
    )


def gate_g_mf_2(validation: dict[str, Any], repro_status: str) -> GateResult:
    net = float(validation.get("net_pnl", 0.0))
    per_mkt = validation.get("per_market_net", {}) or {}
    total = sum(abs(v) for v in per_mkt.values())
    top_share = (max((abs(v) for v in per_mkt.values()), default=0.0) / total) if total > 0 else 1.0
    checks = {
        "validation_net_positive": net > 0,
        "same_mechanism": bool(validation.get("same_mechanism", True)),
        "reasonable_breadth": int(validation.get("n_markets", 0)) >= MIN_MARKETS_OVERALL,
        "no_single_market_dependence": top_share < 0.5,
        "no_accounting_defect": bool(validation.get("no_accounting_defect", True)),
        "tradable_implementation": bool(validation.get("tradable", True)),
        "repro_passed": repro_status == "PASS",
    }
    return GateResult(
        "G_MF_2_VALIDATION",
        "PASS" if all(checks.values()) else "FAIL",
        checks,
        {
            "validation_net": net,
            "top_market_share": top_share,
            "n_markets": validation.get("n_markets", 0),
        },
    )


def audit_false_success(flags: dict[str, bool]) -> dict[str, Any]:
    hits = [t for t in FALSE_SUCCESS_TRIGGERS if flags.get(t, False)]
    return {"false_success_count": len(hits), "hits": hits, "target": 0, "ok": len(hits) == 0}


def headroom(gross: float, transaction_cost: float, roll_cost: float, net: float) -> dict[str, Any]:
    total = transaction_cost + roll_cost
    ratio = (gross / total) if total > 0 else None
    return {
        "gross": gross,
        "transaction_cost": transaction_cost,
        "roll_cost": roll_cost,
        "total_cost": total,
        "net": net,
        "gross_over_cost": ratio,
    }


def universe_breadth(panels: list[MarketPanel]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    for p in panels:
        by_class.setdefault(p.asset_class, []).append(p.root)
    return {
        "n_markets": len(panels),
        "n_asset_classes": len(by_class),
        "markets_per_class": {k: sorted(v) for k, v in by_class.items()},
        "meets_min_markets": len(panels) >= MIN_MARKETS_OVERALL,
        "meets_min_classes": len(by_class) >= MIN_ASSET_CLASSES,
        "no_class_masquerade": all(len(v) >= MIN_MARKETS_PER_CLASS for v in by_class.values()),
    }
