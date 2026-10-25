"""RFC-026 — Execution economics diagnosis: shared research library.

READ-ONLY, RESEARCH-ONLY, PIT-SAFE BY CONSTRUCTION.

This library answers a single question: *can the orthogonal directional
information frozen by RFC-025 actually be traded under a realistic execution
policy?*  It does **not** touch ``COST_MODEL_V3`` (23.790569 bps), which stays
the certified baseline/control (§1, §9, §36), and it does **not** retune the
alpha (§3).  The only experimental variable is the execution policy.

Evidence discipline (§13):
  * ``CERTIFIED_EMPIRICAL`` — the model is composed *only* of measured/known
    components with evidence.
  * ``EMPIRICAL_PARTIAL``   — some components measured, others inherited.
  * ``BOUNDED_ESTIMATE``    — the number is an interval, not a point.
  * ``THEORETICAL_ONLY``    — an unattainable upper/lower bound, diagnostic.
  * ``NOT_TESTABLE``        — the data required to model it does not exist.

The maker path refuses to emit a scalar: no historical L2 book exists
(§16, §17), so maker fills are ``NOT_TESTABLE_HISTORICALLY`` and can never
support an admission claim.

NO IMPUTATION: a missing datum stays NaN / None; it is never forward-filled.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint002_lib as L  # noqa: E402
import sprint002_pipeline as P  # noqa: E402
import sprint025_lib as OL  # noqa: E402
import sprint025_signals as SG  # noqa: E402

EXEC_OUT = REPO / "reports" / "execution-economics"
SCRATCH_DIR = REPO / "reports"

ASSETS = OL.ASSETS
CURRENT_COST_BPS = L.CERTIFIED_ROUND_TRIP_BPS  # 23.790569 — immutable baseline
CERTIFIED_ROUND_TRIP_BPS = L.CERTIFIED_ROUND_TRIP_BPS

# ---------------------------------------------------------------------------
# COST_MODEL_V3 decomposition (BINANCE_SPOT_STANDARD_TAKER) — baseline control.
# ---------------------------------------------------------------------------

COST_MODEL_V3_COMPONENTS: dict[str, float] = {
    "exchange_fee_entry": 10.0,
    "exchange_fee_exit": 10.0,
    "spread": 1.0,
    "slippage": 2.632456,
    "market_impact": 0.158114,
    "funding": 0.0,
}
COST_MODEL_V3_ROUND_TRIP = round(sum(COST_MODEL_V3_COMPONENTS.values()), 6)
COST_MODEL_V3_SHA = "2f0e62d2408e6cc544d139bd6d43292698061d4d6ac325f70adab2b781965159"

# Stress multipliers certified for the baseline (§42).
COST_STRESS: dict[str, float] = dict(L.COST_STRESS)

# ---------------------------------------------------------------------------
# Official fee schedule (§10).  Values are published exchange rates, not
# assumptions; the account's tier is unknown, so the conservative default
# (VIP0 / regular user) is used.
# ---------------------------------------------------------------------------

OFFICIAL_FEES: dict[str, dict[str, Any]] = {
    "BINANCE_SPOT_VIP0": {
        "venue": "Binance",
        "product": "Spot",
        "tier": "Regular User / VIP0 (30d volume < 1,000,000 USD, 0 BNB)",
        "maker_fee_bps": 10.0,
        "taker_fee_bps": 10.0,
        "rebate_bps": 0.0,
        "source_id": "SRC-01",
        "url": "https://www.binance.com/en/fee/trading",
        "access_date": "2026-09-26",
        "instrument": "BTCUSDT/ETHUSDT/SOLUSDT spot",
        "discount": "pay-in-BNB (-25%) POSSIBLE, not applicable",
    },
    "BINANCE_USDM_PERP_VIP0": {
        "venue": "Binance",
        "product": "USD\u24c8-M Perpetual",
        "tier": "VIP0",
        "maker_fee_bps": 2.0,
        "taker_fee_bps": 5.0,
        "rebate_bps": 0.0,
        "source_id": "SRC-02",
        "url": "https://www.binance.com/en/fee/futureFee",
        "access_date": "2026-09-26",
        "instrument": "BTCUSDT/ETHUSDT/SOLUSDT perp",
        "discount": "periodic 0% maker promo POSSIBLE, not applicable; product "
                    "excluded from the runtime",
    },
}

# ---------------------------------------------------------------------------
# EXECUTION_COST_MODEL_V4 — per-asset *measured* spot cost (reused, not
# re-derived).  Source: docs/EXECUTION_COST_MODEL_V4.{md,json}, forward
# bookTicker capture, research-only.
# ---------------------------------------------------------------------------

V4_MEASURED_SPOT: dict[str, dict[str, Any]] = {
    "BTCUSDT": {"spread_bps": 0.0012, "slippage_impact_bps": 3.4988, "rt_total_bps": 23.500, "n": 37},
    "ETHUSDT": {"spread_bps": 0.0375, "slippage_impact_bps": 3.7233, "rt_total_bps": 23.761, "n": 37},
    "SOLUSDT": {"spread_bps": 0.8422, "slippage_impact_bps": 3.8445, "rt_total_bps": 24.687, "n": 37},
}
V4_SPOT_FEE_BPS_PER_SIDE = 10.0

# ---------------------------------------------------------------------------
# Frozen alpha candidates (§3, §62) — pre-registered RFC-025 variants only.
# ---------------------------------------------------------------------------

FROZEN_ALPHA: tuple[dict[str, Any], ...] = (
    {
        "candidate_id": "basis_z@1h|VOL|z1.0",
        "hypothesis_id": "H-ORTHO-01",
        "feature": "basis_z",
        "condition": "VOL",
        "z_thr": 1.0,
        "timeframe": "1h",
        "direction": "contrarian",
        "role": "PRIMARY",
        "rationale": "best gross expectancy among RFC-025 variants with a "
                     "sufficient sample (n=61 DISCOVERY)",
    },
    {
        "candidate_id": "funding_z@30m|VOL|z1.0",
        "hypothesis_id": "H-ORTHO-06",
        "feature": "funding_z",
        "condition": "VOL",
        "z_thr": 1.0,
        "timeframe": "30m",
        "direction": "contrarian",
        "role": "SECONDARY",
        "rationale": "largest sufficient sample (n=106 DISCOVERY), second gross",
    },
    {
        "candidate_id": "basis_z@30m|VOL|z1.0",
        "hypothesis_id": "H-ORTHO-01",
        "feature": "basis_z",
        "condition": "VOL",
        "z_thr": 1.0,
        "timeframe": "30m",
        "direction": "contrarian",
        "role": "TERTIARY",
        "rationale": "largest sample of all (n=143 DISCOVERY), robustness reference",
    },
)

# Frozen shared exit (identical to RFC-025 — the alpha is NOT retuned).
TARGET_MULT = 2.0
STOP_MULT = 1.5
HOLD_BARS = 16
WARM = 262

# ---------------------------------------------------------------------------
# Latency scenarios (§22).  Sensitivity analysis only, never a certified fact.
# ---------------------------------------------------------------------------

LATENCY_SCENARIOS_MS: tuple[int, ...] = (0, 50, 100, 250, 500, 1000)
RUNTIME_MEASURED_LATENCY_MS: int | None = None  # no certified runtime measurement

# Feasibility frontier (§7) — diagnostic re-costing, trades unchanged.
FRONTIER_COSTS_BPS: tuple[float, ...] = (
    0.0, 5.0, 10.0, 15.0, 20.0, CURRENT_COST_BPS, 25.0, 30.0, 35.0, 40.0,
)


# ---------------------------------------------------------------------------
# Frozen trade intents — re-run each candidate through the certified engine.
# ---------------------------------------------------------------------------


def run_candidate(candidate: dict[str, Any], windows: tuple[str, ...]) -> tuple[list[L.Trade], int]:
    """Replay one frozen candidate through the certified event engine.

    Deterministic; identical engine/exit/cost to RFC-025, so the resulting
    trade set reproduces the RFC-025 aggregate metrics exactly.
    """
    trades: list[L.Trade] = []
    eval_bars = 0
    tf = str(candidate["timeframe"])
    for asset in ASSETS:
        for window in windows:
            b = OL.bundle_for(asset, window, tf)
            sig = SG.signal_array(asset, b, str(candidate["feature"]),
                                  float(candidate["z_thr"]), candidate["condition"] == "VOL")
            spec = L.Spec(
                candidate_id=str(candidate["candidate_id"]),
                hypothesis_id=str(candidate["hypothesis_id"]),
                family="rfc026_frozen",
                timeframe=tf,
                signals=P._const_signal(sig),
                warmup=WARM,
                atr_target_mult=TARGET_MULT,
                atr_target_is_atr=True,
                atr_stop_mult=STOP_MULT,
                hold_bars=HOLD_BARS,
            )
            trades.extend(L.run_spec(spec, b, asset, window))
            eval_bars += max(0, len(b) - WARM)
    return trades, eval_bars


# ---------------------------------------------------------------------------
# Gross-edge uncertainty (§6) — the alpha's own uncertainty, never hidden by
# execution improvements.
# ---------------------------------------------------------------------------


def gross_bps(trades: list[L.Trade]) -> NDArray[Any]:
    return np.array([t.gross_bps for t in trades], dtype=np.float64)


def _bootstrap_mean_ci(
    x: NDArray[Any], n_boot: int = 2000, seed: int = 20261026, ci: float = 0.90
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean (deterministic seed)."""
    if x.shape[0] == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.shape[0], size=(n_boot, x.shape[0]))
    means = x[idx].mean(axis=1)
    lo_q = (1.0 - ci) / 2.0
    hi_q = 1.0 - lo_q
    lo = float(np.quantile(means, lo_q))
    hi = float(np.quantile(means, hi_q))
    return (lo, hi)


def _trimmed_mean(x: NDArray[Any], frac: float = 0.10) -> float:
    if x.shape[0] == 0:
        return float("nan")
    k = math.floor(x.shape[0] * frac)
    if k == 0:
        return float(np.mean(x))
    s = np.sort(x)
    return float(np.mean(s[k:-k])) if s.shape[0] - 2 * k > 0 else float(np.mean(s))


def _ex_best_trade_mean(x: NDArray[Any]) -> float:
    if x.shape[0] <= 1:
        return float("nan")
    return float((np.sum(x) - np.max(x)) / (x.shape[0] - 1))


def break_even_analysis(trades: list[L.Trade]) -> dict[str, Any]:
    """Point + conservative break-even cost of a frozen candidate (§5, §6)."""
    x = gross_bps(trades)
    n = int(x.shape[0])
    if n == 0:
        return {"n": 0}
    mean = float(np.mean(x))
    ci_lo, ci_hi = _bootstrap_mean_ci(x)
    med = float(np.median(x))
    trimmed = _trimmed_mean(x)
    ex_best = _ex_best_trade_mean(x)
    sd = float(np.std(x, ddof=1)) if n > 1 else 0.0
    t_stat = float(mean / (sd / math.sqrt(n))) if sd > 0 and n > 1 else None
    conservative = min(v for v in (ci_lo, med, trimmed, ex_best) if math.isfinite(v))
    return {
        "n": n,
        "gross_mean_bps": round(mean, 4),
        "gross_median_bps": round(med, 4),
        "gross_sd_bps": round(sd, 4),
        "bootstrap_ci90_low_bps": round(ci_lo, 4),
        "bootstrap_ci90_high_bps": round(ci_hi, 4),
        "trimmed_mean_bps": round(trimmed, 4),
        "ex_best_trade_mean_bps": round(ex_best, 4),
        "t_stat": round(t_stat, 4) if t_stat is not None else None,
        "break_even_cost_bps": round(mean, 4),
        "conservative_break_even_cost_bps": round(conservative, 4),
        "current_cost_bps": CURRENT_COST_BPS,
        "required_cost_reduction_bps": round(CURRENT_COST_BPS - mean, 4),
        "required_cost_reduction_pct": round((CURRENT_COST_BPS - mean) / CURRENT_COST_BPS * 100.0, 2),
        "alpha_uncertainty_high": bool(conservative <= 0.0),
    }


# ---------------------------------------------------------------------------
# Cost models / execution policies (§12, §30).
# ---------------------------------------------------------------------------

EXEC_STATES = (
    "CERTIFIED_EMPIRICAL",
    "EMPIRICAL_PARTIAL",
    "BOUNDED_ESTIMATE",
    "THEORETICAL_ONLY",
    "NOT_TESTABLE",
)


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """One pre-registered execution policy (§30)."""

    policy_id: str
    entry_mode: str
    exit_mode: str
    timeout_s: float | None
    fallback: str | None
    latency_ms: int
    fee_model: str
    fill_model: str
    spread_model: str
    slippage_model: str
    data_requirements: tuple[str, ...]
    status: str
    round_trip_cost_bps: float | None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_policy_id": self.policy_id,
            "entry_mode": self.entry_mode,
            "exit_mode": self.exit_mode,
            "timeout_s": self.timeout_s,
            "fallback": self.fallback,
            "latency_assumption_ms": self.latency_ms,
            "fee_model": self.fee_model,
            "fill_model": self.fill_model,
            "spread_model": self.spread_model,
            "slippage_model": self.slippage_model,
            "data_requirements": list(self.data_requirements),
            "status": self.status,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "notes": self.notes,
        }


def policy_registry() -> list[ExecutionPolicy]:
    """The <=8 primary execution policies, frozen BEFORE any result (§31, §63)."""
    v4_mid = sum(v["rt_total_bps"] for v in V4_MEASURED_SPOT.values()) / len(V4_MEASURED_SPOT)
    fee_perp_taker = 2.0 * OFFICIAL_FEES["BINANCE_USDM_PERP_VIP0"]["taker_fee_bps"]
    fee_perp_maker = 2.0 * OFFICIAL_FEES["BINANCE_USDM_PERP_VIP0"]["maker_fee_bps"]
    return [
        ExecutionPolicy(
            policy_id="E0_CURRENT_TAKER",
            entry_mode="taker_market", exit_mode="taker_market", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="COST_MODEL_V3 BINANCE_SPOT_STANDARD_TAKER",
            fill_model="deterministic_cross", spread_model="V3 constant 1.0",
            slippage_model="V3 modelled 2.632456+0.158114",
            data_requirements=("none",), status="CERTIFIED_EMPIRICAL",
            round_trip_cost_bps=CURRENT_COST_BPS,
            notes="certified baseline/control — unchanged",
        ),
        ExecutionPolicy(
            policy_id="E1_EMPIRICAL_TAKER_SPOT",
            entry_mode="taker_market", exit_mode="taker_market", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="SPOT VIP0 taker 10/side (SRC-01)",
            fill_model="deterministic_cross", spread_model="V4 measured per asset",
            slippage_model="V4 inherited V3 slippage+impact",
            data_requirements=("forward bookTicker",), status="EMPIRICAL_PARTIAL",
            round_trip_cost_bps=round(v4_mid, 6),
            notes="measured spread, forward-only normal regime",
        ),
        ExecutionPolicy(
            policy_id="E2_MAKER_ENTRY_MAKER_EXIT_SPOT",
            entry_mode="limit_post_only", exit_mode="limit_post_only", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="SPOT VIP0 maker 10/side (SRC-01)",
            fill_model="UNMODELLED — no historical L2 book",
            spread_model="V4 measured", slippage_model="n/a",
            data_requirements=("historical L2 book", "queue", "trade-through"),
            status="NOT_TESTABLE", round_trip_cost_bps=None,
            notes="maker==taker on spot VIP0: no fee saving even if fills",
        ),
        ExecutionPolicy(
            policy_id="E3_MAKER_ENTRY_TAKER_EXIT_SPOT",
            entry_mode="limit_post_only", exit_mode="taker_market", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="SPOT VIP0 maker 10 / taker 10 (SRC-01)",
            fill_model="UNMODELLED — no historical L2 book",
            spread_model="V4 measured", slippage_model="V4 inherited",
            data_requirements=("historical L2 book", "queue"),
            status="NOT_TESTABLE", round_trip_cost_bps=None,
            notes="protected exit is taker; entry fill still unverified",
        ),
        ExecutionPolicy(
            policy_id="E4_TAKER_ENTRY_MAKER_EXIT_SPOT",
            entry_mode="taker_market", exit_mode="limit_post_only", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="SPOT VIP0 taker 10 / maker 10 (SRC-01)",
            fill_model="UNMODELLED — no historical L2 book",
            spread_model="V4 measured", slippage_model="V4 inherited",
            data_requirements=("historical L2 book", "queue"),
            status="NOT_TESTABLE", round_trip_cost_bps=None,
            notes="exit fill unverified; worst of both worlds on spot fees",
        ),
        ExecutionPolicy(
            policy_id="E5_LIMIT_TIMEOUT_FALLBACK_SPOT",
            entry_mode="limit_timeout_then_taker", exit_mode="taker_market",
            timeout_s=30.0, fallback="taker_market", latency_ms=100,
            fee_model="SPOT VIP0", fill_model="UNMODELLED — needs fill probability",
            spread_model="V4 measured", slippage_model="V4 inherited",
            data_requirements=("historical L2 book", "queue", "forward fill evidence"),
            status="NOT_TESTABLE", round_trip_cost_bps=None,
            notes="hybrid maker->fallback needs fill rates from a forward collector",
        ),
        ExecutionPolicy(
            policy_id="E6_PERP_TAKER_INFORMATIONAL",
            entry_mode="taker_market", exit_mode="taker_market", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="USDM PERP VIP0 taker 5/side (SRC-02)",
            fill_model="deterministic_cross", spread_model="V4 measured (perp proxy)",
            slippage_model="V4 inherited",
            data_requirements=("perp klines",),
            status="BOUNDED_ESTIMATE",
            round_trip_cost_bps=round(fee_perp_taker + v4_mid / 2.0, 6),
            notes="product EXCLUDED from runtime; funding/carry adds cost; informational only",
        ),
        ExecutionPolicy(
            policy_id="E7_PERP_MAKER_THEORETICAL_UPPER_BOUND",
            entry_mode="limit_post_only", exit_mode="limit_post_only", timeout_s=None, fallback=None,
            latency_ms=0, fee_model="USDM PERP VIP0 maker 2/side (SRC-02)",
            fill_model="perfection_assumed (FORBIDDEN for admission)",
            spread_model="zero_assumed", slippage_model="zero_assumed",
            data_requirements=("historical L2 book",),
            status="THEORETICAL_ONLY", round_trip_cost_bps=round(fee_perp_maker, 6),
            notes="unattainable bound: zero spread/slippage + certain fills",
        ),
    ]


def theoretical_floor_bps() -> dict[str, float]:
    """Absolute, evidence-only cost floors (§8, §44)."""
    spot_fee = 2.0 * OFFICIAL_FEES["BINANCE_SPOT_VIP0"]["taker_fee_bps"]
    perp_maker = 2.0 * OFFICIAL_FEES["BINANCE_USDM_PERP_VIP0"]["maker_fee_bps"]
    # measured minimum realistic spread (tightest majors, forward capture)
    min_spread = min(v["spread_bps"] for v in V4_MEASURED_SPOT.values())
    return {
        "theoretical_cost_floor_runtime_venue_bps": round(spot_fee, 6),
        "theoretical_minimum_realistic_cost_bps": round(spot_fee + min_spread, 6),
        "perfect_maker_upper_bound_spot_bps": round(spot_fee, 6),
        "perfect_maker_upper_bound_perp_bps": round(perp_maker, 6),
    }


# ---------------------------------------------------------------------------
# Feasibility frontier (§7) — purely diagnostic, trades unchanged.
# ---------------------------------------------------------------------------


def feasibility_frontier(trades: list[L.Trade], costs: tuple[float, ...]) -> list[dict[str, Any]]:
    x = gross_bps(trades)
    n = int(x.shape[0])
    out: list[dict[str, Any]] = []
    for c in costs:
        net = x - c
        wins = net[net > 0]
        losses = net[net < 0]
        pf = float(wins.sum() / abs(losses.sum())) if losses.shape[0] else None
        out.append({
            "total_round_trip_cost_bps": round(c, 6),
            "n_trades": n,
            "net_expectancy_bps": round(float(np.mean(net)), 4) if n else None,
            "net_pnl_usdt": round(float(net.sum()) / 1e4 * L.ROOT_NOTIONAL, 2) if n else None,
            "profit_factor": round(pf, 4) if pf is not None else None,
            "win_rate": round(float(wins.shape[0]) / n, 4) if n else None,
        })
    return out


# ---------------------------------------------------------------------------
# Forward microstructure capture (§14-§16) — spread measured from the
# repository's own forward bookTicker captures (research-only, post-W7).
# ---------------------------------------------------------------------------


def _book_ticker_dirs(market: str | None = None) -> list[Path]:
    pattern = "**/segments/binance/*/*/book_ticker/**/*.jsonl.gz"
    files: list[Path] = []
    for root in SCRATCH_DIR.glob("microstructure*"):
        if not root.is_dir():
            continue
        for f in root.glob(pattern):
            parts = f.parts
            mkt = parts[parts.index("binance") + 1]
            if market and mkt != market:
                continue
            files.append(f)
    return sorted(files)


def _read_book_tickers(path: Path, limit: int) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if len(rows) >= limit:
                    break
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                b, a = d.get("bid"), d.get("ask")
                if not b or not a:
                    continue
                bf, af = float(b), float(a)
                if not math.isfinite(bf) or not math.isfinite(af) or bf <= 0 or af <= 0:
                    continue
                mid = (bf + af) / 2.0
                ts = float(d.get("exchange_event_time") or d.get("receive_time") or 0.0)
                rows.append((str(d.get("symbol") or ""), mid, (af - bf) / mid * 1e4, ts))
    except (OSError, EOFError):
        return rows
    return rows


def measure_spreads(
    market: str = "spot", max_files_per_symbol: int = 8, per_file_limit: int = 4000
) -> dict[str, Any]:
    """Measured spread distribution per asset, stratified by a vol proxy (§20, §70)."""
    files = _book_ticker_dirs(market)
    per_symbol: dict[str, list[tuple[float, float, float]]] = {a: [] for a in ASSETS}
    counted: dict[str, int] = {a: 0 for a in ASSETS}
    for f in files:
        sym_guess = f.parts[f.parts.index("binance") + 2]
        if sym_guess in counted and counted[sym_guess] >= max_files_per_symbol:
            continue
        rows = _read_book_tickers(f, per_file_limit)
        for sym, mid, sp, _ts in rows:
            if sym in per_symbol:
                per_symbol[sym].append((sp, mid, 0.0))
        if rows and sym_guess in counted:
            counted[sym_guess] += 1
    out: dict[str, Any] = {"market": market, "assets": {}, "n_files_scanned": len(files)}
    for sym, triples in per_symbol.items():
        if not triples:
            out["assets"][sym] = {"status": "NO_CAPTURE"}
            continue
        sps = np.array([t[0] for t in triples], dtype=np.float64)
        mids = np.array([t[1] for t in triples], dtype=np.float64)
        out["assets"][sym] = _spread_stats(sps, mids)
    return out


def _spread_stats(sps: NDArray[Any], mids: NDArray[Any]) -> dict[str, Any]:
    n = int(sps.shape[0])
    res: dict[str, Any] = {
        "n": n,
        "mean_bps": round(float(np.mean(sps)), 6),
        "median_bps": round(float(np.median(sps)), 6),
        "p90_bps": round(float(np.quantile(sps, 0.90)), 6),
        "p99_bps": round(float(np.quantile(sps, 0.99)), 6),
        "max_bps": round(float(np.max(sps)), 6),
    }
    if n >= 40:
        r = np.abs(np.diff(mids) / mids[:-1])
        vol = np.full(n, np.nan)
        vol[1:] = r
        med = float(np.nanmedian(vol))
        hi = np.isfinite(vol) & (vol > med)
        lo = np.isfinite(vol) & (vol <= med)
        res["vol_proxy"] = "abs(mid return) per tick, split at median"
        res["high_vol_mean_spread_bps"] = round(float(np.mean(sps[hi])), 6) if hi.any() else None
        res["low_vol_mean_spread_bps"] = round(float(np.mean(sps[lo])), 6) if lo.any() else None
        res["vol_spread_ratio"] = (
            round(float(np.mean(sps[hi]) / np.mean(sps[lo])), 4)
            if hi.any() and lo.any() and np.mean(sps[lo]) > 0 else None
        )
    return res


def microstructure_inventory() -> dict[str, Any]:
    """Inventory of every microstructure source found in the repo (§14)."""
    roots = sorted(p.name for p in SCRATCH_DIR.glob("microstructure*") if p.is_dir())
    bt_spot = len(_book_ticker_dirs("spot"))
    bt_perp = len(_book_ticker_dirs("perp"))
    depth = len(list(SCRATCH_DIR.glob("microstructure*/**/depth_snapshot/*/*.jsonl.gz")))
    aggt = len(list(SCRATCH_DIR.glob("microstructure*/**/agg_trade/*/*.jsonl.gz")))
    v1_agg = len(list((SCRATCH_DIR / "microstructure-v1" / "aggtrades").glob("AGG_*.json")))
    return {
        "forward_capture_roots": roots,
        "historical_order_book": {
            "available": False,
            "reason": "Binance exposes bookTicker/depth only as a live stream; no "
                      "historical L2 endpoint (confirmed by RFC-025 probes)",
        },
        "historical_aggTrades": {
            "available": True,
            "detail": "reports/microstructure-v1/aggtrades/AGG_<SYM>_<day>.json — "
                      f"{v1_agg} files, 14 discontinuous days 2026-03..2026-09",
            "granularity": "minute aggregates (no intra-minute price path, no bid/ask)",
            "usable_for": ["signed flow", "aggressor volume"],
            "not_usable_for": ["trade-through", "queue", "realized slippage", "adverse selection"],
        },
        "forward_book_ticker": {"available": True, "n_files_spot": bt_spot, "n_files_perp": bt_perp,
                                "regime": "FORWARD_RESEARCH_ONLY (2026-09-28..10-01)"},
        "forward_depth_snapshot": {"available": True, "n_files": depth},
        "forward_agg_trade": {"available": True, "n_files": aggt},
        "historical_order_book_feasible": False,
    }


# ---------------------------------------------------------------------------
# Honest maker / adverse-selection bounds (§17-§19, §23-§24).
# ---------------------------------------------------------------------------


def maker_fill_bounds() -> dict[str, Any]:
    """Maker fill behaviour is NOT testable from historical data (§16)."""
    return {
        "status": "NOT_TESTABLE_HISTORICALLY",
        "reason": "no historical best-bid/ask/depth/queue; fill probability, partial "
                  "fills and adverse selection cannot be measured ex-post",
        "optimistic_bound": {"fill_prob": 1.0, "effective_cost_bps": None,
                             "label": "99th-percentile, unattainable, never admission"},
        "neutral_bound": {"fill_prob": 0.5, "effective_cost_bps": None,
                          "label": "V3 modelling constant (ASSUMED), diagnostic"},
        "conservative_bound": {"fill_prob": 0.2, "effective_cost_bps": None,
                               "label": "adverse-selection heavy, diagnostic"},
        "certifiable": False,
    }


def adverse_selection_bounds() -> dict[str, Any]:
    return {
        "status": "NOT_TESTABLE_HISTORICALLY",
        "reason": "post-fill markout requires actual passive fills; none are observable "
                  "in the repository history",
        "post_fill_horizons_s": [1, 5, 30, 60, 300],
        "certifiable": False,
    }


# ---------------------------------------------------------------------------
# Serialisation helpers (mirror sprint025_lib).
# ---------------------------------------------------------------------------


def sha256_obj(obj: Any) -> str:
    return OL.sha256_obj(obj)


def write_json(path: Path, payload: Any) -> None:
    OL.write_json(path, payload)


def write_md(path: Path, text: str) -> None:
    OL.write_md(path, text)


@dataclass(slots=True)
class Artifact:
    """One required RFC-026 artifact (§60)."""

    name: str
    md: str
    json: dict[str, Any] = field(default_factory=dict)

    def emit(self, out_dir: Path) -> None:
        write_md(out_dir / f"{self.name}.md", self.md)
        write_json(out_dir / f"{self.name}.json", self.json)
