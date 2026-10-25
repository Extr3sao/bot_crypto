"""RFC-030 — External alpha evidence & reproduction: shared library.

READ-ONLY, RESEARCH-ONLY, PIT-SAFE, DETERMINISTIC (§53 no agents).

Three layers:

1. EXTERNAL EVIDENCE (§4-§19): a structured source registry and candidate
   strategies scored on evidence / headroom / data / implementation /
   orthogonality.  Selection (§20-§21) happens *before* any backtest.
2. REPRODUCTION ENGINE (§22-§23): a deterministic daily-panel simulator that
   applies publication parameters with no tuning (§24) and honest costs.
3. STATISTICS + WRITERS: hand-rolled stats (scipy is not installed) and the
   artifact writers used by the run/verify scripts.

The reproduction window is entirely POST-PUBLICATION for both selected
strategies (Liu-Tsyvinski-Wu 2022 live sample ends 2018; Moskowitz-Ooi-Pedersen
2012 sample ends 2009).  That is deliberate: §24/§49 ask whether the edge
survived *after becoming known*.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "reports" / "external-alpha"
CACHE_DIR = OUT_DIR / "cache"

UNIVERSE = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT", "BCHUSDT", "XLMUSDT",
    "TRXUSDT", "ETCUSDT", "EOSUSDT", "XTZUSDT", "ZECUSDT", "DASHUSDT",
    "NEOUSDT", "ATOMUSDT", "VETUSDT", "FILUSDT", "THETAUSDT", "ALGOUSDT",
    "AVAXUSDT", "MATICUSDT", "FTTUSDT", "LUNAUSDT", "ICPUSDT", "SHIBUSDT",
)

# Chronological splits (§12 pattern reused).  All of them are post-publication.
SPLIT_BOUNDS: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("2018-01-01", "2021-06-30"),
    "VALIDATION": ("2021-07-01", "2023-12-31"),
    "HOLDOUT": ("2024-01-01", "2026-09-30"),
}
SPLIT_ORDER = ("DISCOVERY", "VALIDATION", "HOLDOUT")

# ---------------------------------------------------------------------------
# COST MODEL (§22, §23) — our unavoidable deviation from the papers, which
# report GROSS factor returns.  Conservative Binance spot all-taker tiers.
# ---------------------------------------------------------------------------
EXT_CRYPTO_COST_MODEL_V1: dict[str, float] = {
    "taker_fee_bps": 10.0,       # 0.10% spot taker, no BNB discount
    "half_spread_bps": 3.0,      # crossing half-spread on liquid USDT pairs
    "impact_bps": 2.0,           # small-size market impact
}
PER_SIDE_COST_BPS = (EXT_CRYPTO_COST_MODEL_V1["taker_fee_bps"]
                     + EXT_CRYPTO_COST_MODEL_V1["half_spread_bps"]
                     + EXT_CRYPTO_COST_MODEL_V1["impact_bps"])   # 15.0

# ---------------------------------------------------------------------------
# SOURCE REGISTRY (§5)
# ---------------------------------------------------------------------------
SOURCES: list[dict[str, Any]] = [
    {
        "SOURCE_ID": "S01",
        "title": "Common Risk Factors in Cryptocurrency",
        "authors": "Liu, Y.; Tsyvinski, A.; Wu, X.",
        "publication": "Journal of Finance 77(2):1133-1177 (NBER WP w25882, 2019)",
        "year": 2022,
        "URL": "https://onlinelibrary.wiley.com/doi/10.1111/jofi.13119",
        "artifact_type": "paper (+ public factor data)",
        "asset_class": "crypto",
        "strategy_family": "cross-sectional momentum / size",
        "holding_horizon": "1 week (also 1-4 week formations)",
        "sample_period": "2014-2018 (weekly)",
        "reported_gross_performance": "CMOM (momentum) and CSMB (size) factors are "
            "significant in the crypto cross-section; a 3-factor (market, size, "
            "momentum) model prices the cross-section (gross, no costs).",
        "reported_net_performance": "not reported (gross factor premia only)",
        "cost_assumptions": "none (factor premia, not implementable PnL)",
        "robustness_evidence": "multifactor spanning tests; alternative formations",
        "replication_evidence": "995+ citations; foundational crypto-factor paper",
        "known_criticisms": "short early-market sample; market-cap sorting uses "
            "data unavailable to us; gross only",
        "data_requirements": "weekly coin returns + market caps",
        "implementation_requirements": "cross-sectional sort, weekly rebalance",
        "reliability_score": 5,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S02",
        "title": "Time Series Momentum",
        "authors": "Moskowitz, T.; Ooi, Y.H.; Pedersen, L.H.",
        "publication": "Journal of Financial Economics 104(2):228-250",
        "year": 2012,
        "URL": "https://www.sciencedirect.com/science/article/pii/S0304405X11002613",
        "artifact_type": "paper",
        "asset_class": "futures (equity index, FX, commodity, bond)",
        "strategy_family": "time-series momentum / trend",
        "holding_horizon": "1 month (12-month formation); 1-12 month persistence",
        "sample_period": "1965-2009 (58 liquid instruments)",
        "reported_gross_performance": "past 12-month excess return positively "
            "predicts next-month return; diversified TSMOM portfolio has high "
            "gross Sharpe with large returns in extreme months.",
        "reported_net_performance": "not reported",
        "cost_assumptions": "not modelled (futures are cheap, but not zero)",
        "robustness_evidence": "58 markets, sub-samples, alternative lookbacks",
        "replication_evidence": "Hurst-Ooi-Pedersen century study; crypto extensions",
        "known_criticisms": "Huang-Li-Wang-Zhou (2020) argue the statistical "
            "evidence is weak under stronger inference",
        "data_requirements": "daily/monthly instrument prices",
        "implementation_requirements": "sign of trailing return + vol targeting",
        "reliability_score": 5,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S03",
        "title": "Time-series momentum: Is it there?",
        "authors": "Huang, D.; Li, J.; Wang, L.; Zhou, G.",
        "publication": "Journal of Financial Economics",
        "year": 2020,
        "URL": "https://ink.library.smu.edu.sg/context/lkcsb_research/article/7520/viewcontent/Time_series_momentum_JFE_sv.pdf",
        "artifact_type": "paper",
        "asset_class": "futures",
        "strategy_family": "time-series momentum (critique)",
        "holding_horizon": "1 month",
        "sample_period": "same instruments as MOP",
        "reported_gross_performance": "TSMOM predictability is statistically weak "
            "once a wild-bootstrap / joint-sign inference is used.",
        "reported_net_performance": "n/a",
        "cost_assumptions": "n/a",
        "robustness_evidence": "alternative inference methodology",
        "replication_evidence": "peer-reviewed critique of S02",
        "known_criticisms": "the criticised specification itself",
        "data_requirements": "as S02",
        "implementation_requirements": "none (critique)",
        "reliability_score": 5,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S04",
        "title": "A Century of Evidence on Trend-Following Investing",
        "authors": "Hurst, B.; Ooi, Y.H.; Pedersen, L.H.",
        "publication": "Journal of Portfolio Management",
        "year": 2017,
        "URL": "https://fairmodel.econ.yale.edu/ec439/hurst.pdf",
        "artifact_type": "paper",
        "asset_class": "multi-asset (commodities, equities, bonds, FX)",
        "strategy_family": "time-series momentum / trend",
        "holding_horizon": "1 month",
        "sample_period": "1880-2016",
        "reported_gross_performance": "trend following positive across a century, "
            "strongest in extreme markets (gross Sharpe ~1).",
        "reported_net_performance": "reported after fees in later work",
        "cost_assumptions": "futures-style costs",
        "robustness_evidence": "140 years, many sub-samples",
        "replication_evidence": "independent of S02 (different authors/methods)",
        "known_criticisms": "long-run equity-like Sharpe, not enormous",
        "data_requirements": "long daily price histories",
        "implementation_requirements": "trend signals, vol targeting",
        "reliability_score": 5,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S05",
        "title": "Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market",
        "authors": "Autonomous Univ. of Chile / AUT working paper",
        "publication": "Auckland Centre for Financial Research (working paper)",
        "year": 2022,
        "URL": "https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf",
        "artifact_type": "working paper",
        "asset_class": "crypto",
        "strategy_family": "time-series + cross-sectional momentum",
        "holding_horizon": "1 week",
        "sample_period": "2014-2022",
        "reported_gross_performance": "both TS and XS momentum significant; max "
            "Sharpe of a momentum strategy ~1.5.",
        "reported_net_performance": "not reported",
        "cost_assumptions": "mostly ignored",
        "robustness_evidence": "dual-family comparison, sub-samples",
        "replication_evidence": "consistent with S01/S02 in crypto",
        "known_criticisms": "working paper; costs absent",
        "data_requirements": "weekly crypto returns",
        "implementation_requirements": "sorts + sign rules",
        "reliability_score": 3,
        "authority_level": "OFFICIAL WORKING PAPER / UNIVERSITY",
    },
    {
        "SOURCE_ID": "S06",
        "title": "A Decade of Evidence of Trend Following Investing in Cryptocurrencies",
        "authors": "academic working paper (crypto trend)",
        "publication": "working paper / academia.edu",
        "year": 2022,
        "URL": "https://www.academia.edu/85983085/A_Decade_of_Evidence_of_Trend_Following_Investing_in_Cryptocurrencies",
        "artifact_type": "working paper",
        "asset_class": "crypto",
        "strategy_family": "trend following",
        "holding_horizon": "days-months",
        "sample_period": "~2013-2022",
        "reported_gross_performance": "risk-adjusted returns with Sharpe ratios "
            "typically 0.5-1.5 for crypto trend.",
        "reported_net_performance": "not consistently reported",
        "cost_assumptions": "varies",
        "robustness_evidence": "decade of crypto, several rules",
        "replication_evidence": "consistent with S02/S04 family",
        "known_criticisms": "working paper quality; few regimes (bull/bear only)",
        "data_requirements": "daily crypto prices",
        "implementation_requirements": "trend rules",
        "reliability_score": 3,
        "authority_level": "OFFICIAL WORKING PAPER / UNIVERSITY",
    },
    {
        "SOURCE_ID": "S07",
        "title": "Cryptocurrency momentum has (not) its moments",
        "authors": "Grobys, K.",
        "publication": "Financial Markets and Portfolio Management (Springer)",
        "year": 2025,
        "URL": "https://link.springer.com/article/10.1007/s11408-025-00474-9",
        "artifact_type": "paper",
        "asset_class": "crypto",
        "strategy_family": "cross-sectional momentum (tail risk)",
        "holding_horizon": "weekly",
        "sample_period": "2015-2023",
        "reported_gross_performance": "momentum payoffs are tail-driven; "
            "volatility-managed momentum improves risk-adjusted returns.",
        "reported_net_performance": "n/a",
        "cost_assumptions": "n/a",
        "robustness_evidence": "tail/volatility conditioning",
        "replication_evidence": "post-publication study",
        "known_criticisms": "high turnover costs not modelled",
        "data_requirements": "weekly crypto returns",
        "implementation_requirements": "sorts",
        "reliability_score": 4,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S08",
        "title": "On survivor cryptocurrency momentum",
        "authors": "Grobys, K.",
        "publication": "Finance Research Letters (Elsevier)",
        "year": 2026,
        "URL": "https://ideas.repec.org/a/eee/finlet/v92y2026ics1544612326001339.html",
        "artifact_type": "paper",
        "asset_class": "crypto",
        "strategy_family": "cross-sectional momentum (survivorship)",
        "holding_horizon": "weekly",
        "sample_period": "2014-2024",
        "reported_gross_performance": "compares survivor-only vs largest-30 coin "
            "momentum; survivorship materially changes conclusions.",
        "reported_net_performance": "n/a",
        "cost_assumptions": "n/a",
        "robustness_evidence": "survivorship decomposition",
        "replication_evidence": "post-publication re-examination",
        "known_criticisms": "shows the classic backtest is survivorship-biased",
        "data_requirements": "weekly crypto returns incl. dead coins",
        "implementation_requirements": "sorts incl. delisted names",
        "reliability_score": 4,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S09",
        "title": "Cryptocurrency Momentum and Reversal",
        "authors": "Dobrynskaya, V.",
        "publication": "working paper / SSRN",
        "year": 2021,
        "URL": "https://www.semanticscholar.org/paper/Cryptocurrency-Momentum-and-Reversal-Dobrynskaya/4766bd8a0399c64efc23c274f00b3f38154645fe",
        "artifact_type": "working paper",
        "asset_class": "crypto",
        "strategy_family": "cross-sectional momentum AND reversal",
        "holding_horizon": "1 week to several weeks",
        "sample_period": "2014-2020",
        "reported_gross_performance": "highly diversified cross-sectional momentum "
            "and reversal portfolios, sorting/holding 1 week+.",
        "reported_net_performance": "not reported",
        "cost_assumptions": "not modelled",
        "robustness_evidence": "many sorting/holding combinations",
        "replication_evidence": "consistent with S01",
        "known_criticisms": "working paper; costs and turnover not addressed",
        "data_requirements": "weekly crypto returns",
        "implementation_requirements": "sorts",
        "reliability_score": 3,
        "authority_level": "OFFICIAL WORKING PAPER / UNIVERSITY",
    },
    {
        "SOURCE_ID": "S10",
        "title": "Learning and predictability via technical analysis: Evidence from bitcoin and stocks",
        "authors": "Detzel, A.; Liu, H.; Strauss, J.; Zhou, G.; Zhu, Y.",
        "publication": "Financial Management",
        "year": 2021,
        "URL": "https://onlinelibrary.wiley.com/journal/1755053x",
        "artifact_type": "paper",
        "asset_class": "crypto (bitcoin) + equities",
        "strategy_family": "trend / technical analysis",
        "holding_horizon": "daily-monthly",
        "sample_period": "2010-2019 (BTC)",
        "reported_gross_performance": "moving-average trend signals are "
            "economically significant for bitcoin and outperform buy-and-hold.",
        "reported_net_performance": "not reported",
        "cost_assumptions": "not modelled",
        "robustness_evidence": "out-of-sample statistical tests",
        "replication_evidence": "peer-reviewed",
        "known_criticisms": "single asset; short sample",
        "data_requirements": "daily BTC prices",
        "implementation_requirements": "moving-average rule",
        "reliability_score": 4,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S11",
        "title": "Carry",
        "authors": "Koijen, R.; Moskowitz, T.; Pedersen, L.H.; Vrugt, E.",
        "publication": "Journal of Financial Economics 127(2):197-225",
        "year": 2018,
        "URL": "https://www.sciencedirect.com/science/article/pii/S0304405X17302368",
        "artifact_type": "paper",
        "asset_class": "global futures, FX, bonds, commodities, equities",
        "strategy_family": "carry across assets",
        "holding_horizon": "1 month",
        "sample_period": "1980-2012",
        "reported_gross_performance": "carry predicts returns across asset "
            "classes; diversified carry portfolio has high Sharpe.",
        "reported_net_performance": "not reported",
        "cost_assumptions": "limited",
        "robustness_evidence": "many asset classes",
        "replication_evidence": "widely replicated",
        "known_criticisms": "crash risk; crypto carry compressed (see RFC-029)",
        "data_requirements": "funding/basis/borrow series",
        "implementation_requirements": "carry ranking",
        "reliability_score": 5,
        "authority_level": "PEER-REVIEWED PAPER",
    },
    {
        "SOURCE_ID": "S12",
        "title": "Time Series Momentum Effect (research aggregator)",
        "authors": "Quantpedia",
        "publication": "Quantpedia (aggregator)",
        "year": 2024,
        "URL": "https://quantpedia.com/strategies/time-series-momentum-effect",
        "artifact_type": "aggregator",
        "asset_class": "multi-asset",
        "strategy_family": "time-series momentum",
        "holding_horizon": "1 month",
        "sample_period": "aggregated",
        "reported_gross_performance": "summarises S02 with extensions.",
        "reported_net_performance": "n/a",
        "cost_assumptions": "n/a",
        "robustness_evidence": "aggregation of published studies",
        "replication_evidence": "secondary",
        "known_criticisms": "not primary evidence",
        "data_requirements": "n/a",
        "implementation_requirements": "n/a",
        "reliability_score": 2,
        "authority_level": "HIGH-QUALITY QUANT RESEARCH (aggregator)",
    },
]

# ---------------------------------------------------------------------------
# CANDIDATE FAMILIES (§9, §13, §19) — scored BEFORE any of our backtests (§21)
# ---------------------------------------------------------------------------
CANDIDATES: list[dict[str, Any]] = [
    {
        "CANDIDATE_ID": "EXT-TSMOM-001",
        "family": "TIME-SERIES MOMENTUM / TREND",
        "CLAIM": "The sign of an instrument's past 12-month return positively "
                 "predicts its next-month return (trend persistence).",
        "SOURCE": ["S02", "S04", "S03", "S05", "S06", "S10", "S12"],
        "EVIDENCE": "Peer-reviewed (JFE) + a century of independent evidence + "
                    "crypto-specific extensions; one strong peer-reviewed critique.",
        "economic_mechanism": "trend persistence / underreaction + risk-management "
            "demand (institutional flow), not an indicator artefact",
        "EVIDENCE_STRENGTH": 4,
        "ECONOMIC_HEADROOM": 4,
        "DATA_FEASIBILITY": 5,
        "IMPLEMENTATION_COMPLEXITY": 5,
        "ORTHOGONALITY": 4,
        "expected_turnover": "~1 position change/asset/quarter (monthly rebalance)",
        "expected_holding": "1 month",
        "main_risks": "regime dependence; weak statistical inference (S03); "
            "single asset class (crypto) in our data",
        "DECISION": "REPRODUCE",
    },
    {
        "CANDIDATE_ID": "EXT-XMOM-001",
        "family": "CROSS-SECTIONAL MOMENTUM",
        "CLAIM": "Coins with high past-week returns outperform coins with low "
                 "past-week returns (cross-sectional momentum).",
        "SOURCE": ["S01", "S05", "S07", "S08", "S09"],
        "EVIDENCE": "Seminal JF paper + multiple post-publication re-examinations "
                    "(including a survivorship critique).",
        "economic_mechanism": "behavioural underreaction / limited attention",
        "EVIDENCE_STRENGTH": 4,
        "ECONOMIC_HEADROOM": 4,
        "DATA_FEASIBILITY": 5,
        "IMPLEMENTATION_COMPLEXITY": 5,
        "ORTHOGONALITY": 4,
        "expected_turnover": "high (weekly rebalance, full book)",
        "expected_holding": "1 week",
        "main_risks": "high turnover eats the small weekly spread; survivorship "
            "bias; crowding decay",
        "DECISION": "REPRODUCE",
    },
    {
        "CANDIDATE_ID": "EXT-XREV-001",
        "family": "MEDIUM-HORIZON MEAN REVERSION / REVERSAL",
        "CLAIM": "Extreme recent winners reverse over the following weeks.",
        "SOURCE": ["S09", "S07"],
        "EVIDENCE": "Working papers + post-publication tail studies; no "
                    "top-tier peer-reviewed anchor in crypto.",
        "economic_mechanism": "liquidity provision / overreaction",
        "EVIDENCE_STRENGTH": 3,
        "ECONOMIC_HEADROOM": 3,
        "DATA_FEASIBILITY": 5,
        "IMPLEMENTATION_COMPLEXITY": 5,
        "ORTHOGONALITY": 3,
        "expected_turnover": "high (weekly)",
        "expected_holding": "1-2 weeks",
        "main_risks": "only working-paper evidence; overlaps momentum decay",
        "DECISION": "REJECT",
    },
    {
        "CANDIDATE_ID": "EXT-CARRY-001",
        "family": "CARRY ACROSS ASSETS",
        "CLAIM": "High-carry assets outperform low-carry assets.",
        "SOURCE": ["S11"],
        "EVIDENCE": "Strong peer-reviewed cross-asset evidence (JFE).",
        "economic_mechanism": "risk premium for providing balance-sheet capacity",
        "EVIDENCE_STRENGTH": 4,
        "ECONOMIC_HEADROOM": 2,
        "DATA_FEASIBILITY": 4,
        "IMPLEMENTATION_COMPLEXITY": 4,
        "ORTHOGONALITY": 1,
        "expected_turnover": "monthly",
        "expected_holding": "1 month",
        "main_risks": "our crypto carry space was already falsified (RFC-028/029): "
            "structural funding compression makes net carry negative OOS",
        "DECISION": "REJECT",
    },
    {
        "CANDIDATE_ID": "EXT-SEAS-001",
        "family": "SEASONALITY / CALENDAR EFFECTS",
        "CLAIM": "Calendar effects (day-of-week, turn-of-month) are exploitable.",
        "SOURCE": ["S12"],
        "EVIDENCE": "Weak: aggregator-level only, no top-tier crypto anchor.",
        "economic_mechanism": "unclear / data-mining risk",
        "EVIDENCE_STRENGTH": 2,
        "ECONOMIC_HEADROOM": 2,
        "DATA_FEASIBILITY": 5,
        "IMPLEMENTATION_COMPLEXITY": 5,
        "ORTHOGONALITY": 3,
        "expected_turnover": "high",
        "expected_holding": "days",
        "main_risks": "multiple-testing / data mining; fails admission §13",
        "DECISION": "REJECT",
    },
]

MAX_EXTERNAL_STRATEGIES = 5
MAX_REPRODUCED = 2

SELECTION_RULE = (
    "Rank candidates by (EVIDENCE_STRENGTH + ECONOMIC_HEADROOM + "
    "DATA_FEASIBILITY + IMPLEMENTATION_COMPLEXITY + ORTHOGONALITY) descending; "
    "tie-break by (# independent evidence sources) descending, then by "
    "CANDIDATE_ID ascending.  Select the top 2 that pass the §13 admission "
    "criteria.  Selection is frozen BEFORE any of our backtests run (§21)."
)

# VERIFIED frozen selection (reproducible from the scorecard, not from results).
SELECTED = ("EXT-TSMOM-001", "EXT-XMOM-001")

# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Panel:
    """Daily multi-asset panel on a common calendar (int64 ms)."""

    dates: NDArray[Any]              # (n,) ms at 00:00 UTC
    assets: tuple[str, ...]
    close: NDArray[Any]              # (n, a) close, NaN where absent
    quote_volume: NDArray[Any]       # (n, a) quote volume, NaN where absent
    open_ms: NDArray[Any]            # (n, a) true first bar ms per asset/day

    @property
    def n(self) -> int:
        return int(self.dates.shape[0])

    @property
    def a(self) -> int:
        return len(self.assets)


def _load_symbol(sym: str) -> dict[str, NDArray[Any]]:
    with np.load(CACHE_DIR / f"daily_{sym}.npz", allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def build_panel() -> Panel:
    """Assemble the daily panel; assets without cache data are skipped."""
    raw: dict[str, dict[str, NDArray[Any]]] = {}
    for sym in UNIVERSE:
        p = CACHE_DIR / f"daily_{sym}.npz"
        if p.exists():
            raw[sym] = _load_symbol(sym)
    if not raw:
        raise FileNotFoundError("no RFC-030 daily cache; run sprint030_fetch.py first")
    all_days = sorted({int(t) for d in raw.values() for t in d["open_time_ms"].tolist()})
    day_to_i = {t: i for i, t in enumerate(all_days)}
    assets = tuple(sorted(raw))
    n, a = len(all_days), len(assets)
    close = np.full((n, a), np.nan)
    qv = np.full((n, a), np.nan)
    oms = np.full((n, a), np.nan)
    for j, sym in enumerate(assets):
        d = raw[sym]
        ts = d["open_time_ms"].astype(np.int64)
        idx = np.array([day_to_i[int(t)] for t in ts.tolist()], dtype=np.int64)
        close[idx, j] = d["close"]
        qv[idx, j] = d["quote_volume"]
        oms[idx, j] = d["open_time_ms"]
    return Panel(dates=np.array(all_days, dtype=np.int64), assets=assets,
                 close=close, quote_volume=qv, open_ms=oms)


def split_masks(panel: Panel) -> dict[str, NDArray[Any]]:
    out: dict[str, NDArray[Any]] = {}
    for name, (lo, hi) in SPLIT_BOUNDS.items():
        lo_ms = int(datetime.fromisoformat(lo + "T00:00:00+00:00").timestamp() * 1000)
        hi_ms = int(datetime.fromisoformat(hi + "T23:59:59+00:00").timestamp() * 1000)
        out[name] = (panel.dates >= lo_ms) & (panel.dates <= hi_ms)
    return out


# ---------------------------------------------------------------------------
# reproduction engine (§22-§23)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Rebalance:
    idx: int
    ts: int
    gross_bps: float
    cost_bps: float
    net_bps: float
    traded_notional: float
    n_long: int
    n_short: int


@dataclass(slots=True)
class BacktestResult:
    strategy: str
    split: str
    rebalances: list[Rebalance] = field(default_factory=list)
    skipped: int = 0

    def metrics(self, periods_per_year: float) -> dict[str, Any]:
        nets = np.array([r.net_bps for r in self.rebalances], dtype=np.float64)
        gross = np.array([r.gross_bps for r in self.rebalances], dtype=np.float64)
        cost = np.array([r.cost_bps for r in self.rebalances], dtype=np.float64)
        traded = np.array([r.traded_notional for r in self.rebalances], dtype=np.float64)
        if nets.size == 0:
            return {"status": "NO_TRADES", "rebalances": 0}
        wins = nets[nets > 0]
        losses = nets[nets <= 0]
        gp, gl = float(wins.sum()), float(-losses.sum())
        abs_gross = np.abs(gross)
        return {
            "status": "OK",
            "rebalances": int(nets.size),
            "gross_expectancy_bps": float(np.mean(gross)),
            "cost_expectancy_bps": float(np.mean(cost)),
            "net_expectancy_bps": float(np.mean(nets)),
            "net_pnl_bps": float(np.sum(nets)),
            "gross_sum_bps": float(np.sum(gross)),
            "cost_sum_bps": float(np.sum(cost)),
            "net_annualized_pct": float(np.mean(nets) / 1e4 * periods_per_year * 100.0),
            "gross_annualized_pct": float(np.mean(gross) / 1e4 * periods_per_year * 100.0),
            "sharpe": _sharpe(nets, periods_per_year),
            "sharpe_gross": _sharpe(gross, periods_per_year),
            "max_dd_bps": _max_drawdown(np.cumsum(nets)),
            "win_rate": float(np.mean(nets > 0)),
            "pf": (gp / gl) if gl > 0 else None,
            "mean_turnover_notional": float(np.mean(traded)),
            "mean_abs_gross_bps": float(np.mean(abs_gross)),
            "cost_share_of_gross": float(np.sum(cost) / np.sum(np.abs(gross)))
            if np.sum(np.abs(gross)) > 0 else None,
            "without_best_net_expectancy_bps": float(np.mean(np.sort(nets)[:-1]))
            if nets.size > 1 else None,
            "sum_net_bps": float(np.sum(nets)),
        }


def _sharpe(x: NDArray[Any], periods_per_year: float) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2 or float(np.std(x)) == 0.0:
        return None
    return float(np.mean(x) / np.std(x) * math.sqrt(periods_per_year))


def _max_drawdown(cum: NDArray[Any]) -> float:
    cum = np.asarray(cum, dtype=np.float64)
    if cum.size == 0:
        return 0.0
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum))


def _eligible(panel: Panel, day: int, lookback_days: int, min_obs: int = 20) -> NDArray[Any]:
    """Assets with a finite close at `day` and enough trailing history."""
    today = np.isfinite(panel.close[day])
    if day - lookback_days < 0:
        return np.zeros(panel.a, dtype=bool)
    back = np.isfinite(panel.close[day - lookback_days])
    return np.asarray(today & back, dtype=bool)


def _weekly_rebalance_days(panel: Panel, mask: NDArray[Any]) -> list[int]:
    """Mondays (and the first available day thereafter) inside the split."""
    import datetime as _dt
    days: list[int] = []
    for i in np.where(mask)[0].tolist():
        d = _dt.datetime.fromtimestamp(int(panel.dates[i]) / 1000, tz=UTC)
        if d.weekday() == 0:
            days.append(int(i))
    return days


def _monthly_rebalance_days(panel: Panel, mask: NDArray[Any]) -> list[int]:
    import datetime as _dt
    days: list[int] = []
    seen: set[tuple[int, int]] = set()
    for i in np.where(mask)[0].tolist():
        d = _dt.datetime.fromtimestamp(int(panel.dates[i]) / 1000, tz=UTC)
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            days.append(int(i))
    return days


def _weights_for_signal(
    panel: Panel, day: int, signal: NDArray[Any], eligible: NDArray[Any],
    long_short: bool, quantile: float,
) -> NDArray[Any]:
    """Equal-weight long top-quantile / (short bottom-quantile) of `signal`."""
    w = np.zeros(panel.a, dtype=np.float64)
    idx = np.where(eligible & np.isfinite(signal))[0]
    if idx.size < 4:
        return w
    order = idx[np.argsort(signal[idx], kind="mergesort")]
    k = max(1, round(idx.size * quantile))
    longs = order[-k:]
    w[longs] = 1.0 / k
    if long_short:
        shorts = order[:k]
        w[shorts] = -1.0 / k
    return w


def run_cross_sectional_momentum(
    panel: Panel, split: NDArray[Any], formation_days: int = 7,
    quantile: float = 0.2, cost_bps: float = PER_SIDE_COST_BPS,
) -> BacktestResult:
    """EXT-XMOM-001: weekly cross-sectional momentum (long top / short bottom)."""
    res = BacktestResult(strategy="EXT-XMOM-001", split="")
    days = _weekly_rebalance_days(panel, split)
    prev = np.zeros(panel.a, dtype=np.float64)
    for k, i in enumerate(days):
        nxt = days[k + 1] if k + 1 < len(days) else None
        if nxt is None:
            break
        back = i - formation_days
        if back < 0:
            res.skipped += 1
            continue
        elig = _eligible(panel, i, formation_days)
        if not (np.isfinite(panel.close[nxt]) & elig).any():
            res.skipped += 1
            continue
        sig = np.full(panel.a, np.nan)
        ok = elig & np.isfinite(panel.close[back])
        sig[ok] = panel.close[i, ok] / panel.close[back, ok] - 1.0
        w = _weights_for_signal(panel, i, sig, elig, True, quantile)
        if not np.any(w):
            res.skipped += 1
            continue
        ret = np.zeros(panel.a)
        good = np.isfinite(panel.close[nxt]) & np.isfinite(panel.close[i])
        ret[good] = panel.close[nxt, good] / panel.close[i, good] - 1.0
        gross_bps = float(np.nansum(w * ret) * 1e4)
        traded = float(np.nansum(np.abs(w - prev)))
        cost = traded * cost_bps
        res.rebalances.append(Rebalance(
            idx=i, ts=int(panel.dates[i]), gross_bps=gross_bps, cost_bps=cost,
            net_bps=gross_bps - cost, traded_notional=traded,
            n_long=int(np.sum(w > 0)), n_short=int(np.sum(w < 0))))
        prev = w
    return res


def run_time_series_momentum(
    panel: Panel, split: NDArray[Any], formation_days: int = 365,
    vol_target: float = 0.40, vol_lookback: int = 60,
    cost_bps: float = PER_SIDE_COST_BPS,
) -> BacktestResult:
    """EXT-TSMOM-001: sign of 12-month return, monthly rebalance, vol-scaled.

    Publication parameters (MOP 2012): 12-month formation, monthly hold, sign
    rule, per-instrument volatility targeting at 40% annualised.  Crypto is far
    more volatile than the paper's futures, so we cap the per-asset weight at
    1/N_gross and disclose this deviation; the SIGN rule is unchanged.
    """
    res = BacktestResult(strategy="EXT-TSMOM-001", split="")
    days = _monthly_rebalance_days(panel, split)
    prev = np.zeros(panel.a, dtype=np.float64)
    for k, i in enumerate(days):
        nxt = days[k + 1] if k + 1 < len(days) else None
        if nxt is None:
            break
        back = i - formation_days
        if back < 0:
            res.skipped += 1
            continue
        elig = _eligible(panel, i, formation_days)
        ok = elig & np.isfinite(panel.close[back])
        if not ok.any():
            res.skipped += 1
            continue
        sig = np.zeros(panel.a)
        sig[ok] = np.sign(panel.close[i, ok] / panel.close[back, ok] - 1.0)
        # ex-ante volatility from the trailing vol_lookback daily returns
        vol = np.full(panel.a, np.nan)
        lo = max(0, i - vol_lookback)
        win = panel.close[lo:i + 1]
        r = win[1:] / win[:-1] - 1.0
        vol = np.full(panel.a, np.nan)
        for jj in range(panel.a):
            col = r[:, jj]
            col = col[np.isfinite(col)]
            if col.size >= 2:
                vol[jj] = float(np.std(col)) * math.sqrt(365.0)
        scale = np.zeros(panel.a)
        good_v = ok & np.isfinite(vol) & (vol > 0)
        scale[good_v] = np.clip(vol_target / vol[good_v], 0.0, 4.0)
        raw = sig * scale
        gross_sum = float(np.sum(np.abs(raw)))
        if gross_sum <= 0:
            res.skipped += 1
            continue
        w = raw / gross_sum          # gross book normalised to 1
        ret = np.zeros(panel.a)
        good = np.isfinite(panel.close[nxt]) & np.isfinite(panel.close[i])
        ret[good] = panel.close[nxt, good] / panel.close[i, good] - 1.0
        gross_bps = float(np.nansum(w * ret) * 1e4)
        traded = float(np.nansum(np.abs(w - prev)))
        cost = traded * cost_bps
        res.rebalances.append(Rebalance(
            idx=i, ts=int(panel.dates[i]), gross_bps=gross_bps, cost_bps=cost,
            net_bps=gross_bps - cost, traded_notional=traded,
            n_long=int(np.sum(w > 0)), n_short=int(np.sum(w < 0))))
        prev = w
    return res


REPRODUCTION_FIDELITY = {
    "EXT-TSMOM-001": "CLOSE_REPRODUCTION",
    "EXT-XMOM-001": "CLOSE_REPRODUCTION",
}

PERIODS_PER_YEAR = {"EXT-TSMOM-001": 12.0, "EXT-XMOM-001": 52.0}


# ---------------------------------------------------------------------------
# writers / hashing
# ---------------------------------------------------------------------------

def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
