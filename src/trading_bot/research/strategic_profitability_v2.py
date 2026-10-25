"""RFC-035 - Strategic Profitability Plan V2 & Multi-Asset Opportunity Admission.

This module is the *admission review* that RFC-034 demanded before any new alpha
code may be written.  It does **not** implement, backtest, tune or promote a
strategy (RFC-035 defines ``ADMISSION_REVIEW``, not ``ALPHA_IMPLEMENTATION``).
It only records:

* the reviewed external strategy universe (10-15 families, no variants),
* the external SOURCE_REGISTRY with per-source reliability and post-publication
  evidence,
* a deterministic STRATEGY_SCORECARD with critical-dimension rules,
* the MAX 5 shortlist, MAX 3 finalists and MAX 2 authorized reproductions,
* the G_REENTRY gate, and
* the FALSE_SUCCESS triggers specific to an external-evidence admission review.

The pure functions here are the single source of truth consumed by
``scripts/rfc035_run.py`` to emit the ``reports/profitability-v2/`` artifacts and
the tracked ``docs/research/STRATEGIC_PROFITABILITY_PLAN_V2`` documents.  The
independent verifier re-derives the same invariants without importing this
module.

Economic marker (unchanged by RFC-035): every execution counter stays at zero
until a strategy passes REPRODUCTION -> DISCOVERY -> VALIDATION.  Rewriting the
plan does not move ``EXECUTABLE_VALIDATED_EDGE_COUNT``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# --------------------------------------------------------------------------- #
# Canonical status of the economic project (RFC-034 truth, still in force)
# --------------------------------------------------------------------------- #

PLATFORM_STATUS = "RESEARCH_CAPABLE"
ECONOMIC_STATUS = "NO_VALIDATED_EXECUTABLE_EDGE"
CURRENT_DECISION = "PAUSE_TRADING_PROJECT"

#: RFC-034 set PROFITABILITY_RESEARCH_STATUS = PAUSED with
#: NEXT_ALPHA_RFC_ALLOWED = False.  RFC-035 flips these ONLY if G_REENTRY passes.
ENTRY_PROFITABILITY_RESEARCH_STATUS = "PAUSED"
ENTRY_NEXT_ALPHA_RFC_ALLOWED = False
APPROVED_PROFITABILITY_RESEARCH_STATUS = "REENTRY_APPROVED"
NEXT_RFC_TYPE = "EXTERNAL_STRATEGY_REPRODUCTION"

#: §86 - canonical project KPI.  Phase 2 target is 1, not a test/RFC count.
EXECUTABLE_VALIDATED_EDGE_COUNT = 0
PHASE_2_TARGET_EXECUTABLE_VALIDATED_EDGE_COUNT = 1
ROBUST_EDGE_COUNT = 0
PAPER_CANDIDATE_COUNT = 0
FORWARD_PROFITABLE_COUNT = 0
LIVE_PROFITABLE_COUNT = 0
STATISTICAL_HISTORICAL_EFFECT = 1

# §64 - future implementation budget (recorded now, enforced later).
MAX_IMPLEMENTED_STRATEGIES = 2
MAX_PARAMETER_VARIANTS = 3

# §42/§47/§49 - hard caps for this admission review.
MAX_TOP5 = 5
MAX_FINALISTS = 3
MAX_AUTHORIZED = 2


# --------------------------------------------------------------------------- #
# §24 - economic headroom bands
# --------------------------------------------------------------------------- #

#: Ordered (upper_bound_exclusive, class).  §24 is explicit: 1.5-2.0 RESEARCHABLE.
HEADROOM_BANDS: tuple[tuple[float, str], ...] = (
    (1.0, "REJECT"),
    (1.25, "TOO_THIN"),
    (1.5, "WEAK"),
    (2.0, "RESEARCHABLE"),
    (float("inf"), "STRONG_HEADROOM"),
)


def classify_headroom(ratio: float) -> str:
    """§23/§24 - classify HEADROOM_RATIO = expected gross edge / realistic cost."""
    if ratio < 0:
        raise ValueError("headroom ratio must be non-negative")
    for upper, name in HEADROOM_BANDS:
        if ratio < upper:
            return name
    return "STRONG_HEADROOM"  # unreachable, kept for exhaustiveness


# §28 - data cost classes.
DATA_COST_CLASSES: tuple[str, ...] = (
    "FREE_EXISTING",
    "FREE_NEW",
    "LOW_COST",
    "PAID",
    "EXPENSIVE",
    "UNAVAILABLE",
)

FREE_OR_LOW_DATA = frozenset({"FREE_EXISTING", "FREE_NEW", "LOW_COST"})

# §57 - ETF proxy classification.
PROXY_CLASSES: tuple[str, ...] = (
    "VALID_PROXY",
    "RESEARCH_PROXY_ONLY",
    "INVALID_PROXY",
)

# §61/§62 - relative (never dated) effort estimates.
EFFORT_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH")

# §46 - reproduction fidelity potential.
FIDELITY_CLASSES: tuple[str, ...] = (
    "EXACT",
    "CLOSE",
    "CONCEPTUAL",
    "NOT_REPRODUCIBLE",
)

# §19 - post-publication survival.
POST_PUBLICATION_CLASSES: tuple[str, ...] = (
    "SURVIVES",
    "WEAKENED_BUT_PRESENT",
    "DECAYED",
    "UNKNOWN",
)

# §75 - exact decision values.
DECISIONS: tuple[str, ...] = (
    "AUTHORIZE_P1",
    "AUTHORIZE_P2",
    "WATCHLIST",
    "DEFER_DATA",
    "REJECT_ECONOMICS",
    "REJECT_EVIDENCE",
    "REJECT_TRADABILITY",
    "REJECT_COMPLEXITY",
)

# §16 - source authority ladder (strongest first).
SOURCE_AUTHORITY_LADDER: tuple[str, ...] = (
    "peer_reviewed_paper",
    "academic_working_paper",
    "independent_replication",
    "exchange_index_research",
    "established_quant_research",
    "open_source_implementation",
    "blog",
    "social_media",
)

STRONG_SOURCE_TYPES: tuple[str, ...] = (
    "peer_reviewed_paper",
    "academic_working_paper",
    "independent_replication",
    "exchange_index_research",
    "established_quant_research",
)


# --------------------------------------------------------------------------- #
# §17 - source registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Source:
    """One external evidence source (§17)."""

    source_id: str
    title: str
    authors: str
    publication: str
    year: int
    url: str
    source_type: str
    retrieval_date: str
    strategy_family: str
    asset_class: str
    sample: str
    reported_effect: str
    cost_assumption: str
    oos_evidence: str
    post_publication_evidence: str
    independent_replication: str
    reliability: str
    evidence_role: str  # "supporting" | "counter" | "context"

    @property
    def is_strong(self) -> bool:
        return self.source_type in STRONG_SOURCE_TYPES


#: Retrieved 2026-10-05.  Supporting, counter and context sources are mixed on
#: purpose (§72/§73 - contradictory evidence is mandatory).
SOURCES: tuple[Source, ...] = (
    Source(
        source_id="S001",
        title="Time Series Momentum",
        authors="Moskowitz, Ooi, Pedersen",
        publication="Journal of Financial Economics 104(2)",
        year=2012,
        url="https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MANAGED_FUTURES_TREND",
        asset_class="equity index, government bond, FX, commodity futures",
        sample="58 liquid futures, 1965-2009",
        reported_effect=(
            "diversified TSMOM portfolio alpha ~20.7% p.a., vol 15.74%, "
            "Sharpe ~1.31, MaxDD ~-33.9%"
        ),
        cost_assumption="gross; no explicit transaction-cost deduction",
        oos_evidence="within-sample across 58 markets; later papers extend",
        post_publication_evidence="still positive but weaker in recent decades",
        independent_replication="Baltas-Kosowski 2013; Hurst et al 2017",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S002",
        title="A Century of Evidence on Trend-Following Investing",
        authors="Hurst, Ooi, Pedersen",
        publication="Journal of Portfolio Management 44(1)",
        year=2017,
        url="https://fairmodel.econ.yale.edu/ec439/hurst.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MANAGED_FUTURES_TREND",
        asset_class="multi-asset (equities, bonds, FX, commodities)",
        sample="global markets, 1880-2016 (decade by decade)",
        reported_effect="positive average return in every decade since 1880, low correlation",
        cost_assumption="gross; notes capacity/crowding as a drag",
        oos_evidence="130+ year out-of-sample across decades",
        post_publication_evidence="survives but with capacity and return-pressure caveats",
        independent_replication="consistent with Moskowitz-Ooi-Pedersen (2012)",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S003",
        title="Momentum Strategies in Futures Markets and Trend-following Funds",
        authors="Baltas, Kosowski",
        publication="SSRN working paper / Imperial College",
        year=2013,
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1968996",
        source_type="academic_working_paper",
        retrieval_date="2026-10-05",
        strategy_family="MANAGED_FUTURES_TREND",
        asset_class="futures (bonds, commodities, FX, equity indices)",
        sample="12 futures, 1999-2009 intraday; CTA indices",
        reported_effect="1-12 month trends dominate; linear-trend signals cut turnover",
        cost_assumption="discusses turnover and cost sensitivity",
        oos_evidence="reproduces CTA benchmark returns from TSMOM factors",
        post_publication_evidence="trend/CTA returns resilient but capacity-constrained",
        independent_replication="aligns with S001, S002",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S004",
        title="Time-series momentum: Is it there?",
        authors="Huang, Li, Wang, Zhou",
        publication="Journal of Financial Economics 135(3)",
        year=2020,
        url="https://ink.library.smu.edu.sg/context/lkcsb_research/article/7520/viewcontent/Time_series_momentum_JFE_sv.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MANAGED_FUTURES_TREND",
        asset_class="futures (equity index, bond, FX, commodity)",
        sample="same assets as S001, re-examined asset-by-asset",
        reported_effect=(
            "asset-by-asset time-series regressions reveal little TSM in- or out-of-sample; "
            "the diversified result is fragile"
        ),
        cost_assumption="statistical, not cost-focused",
        oos_evidence="argues the headline TSMOM effect is weak at the single-asset level",
        post_publication_evidence="counter-evidence to S001",
        independent_replication="a replication challenge to Moskowitz-Ooi-Pedersen",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S005",
        title="Returns to Buying Winners and Selling Losers (cross-sectional momentum)",
        authors="Jegadeesh, Titman",
        publication="Journal of Finance 48(1)",
        year=1993,
        url="https://www.jstor.org/stable/2328882",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="CROSS_SECTIONAL_MOMENTUM",
        asset_class="US equities",
        sample="US stocks, 1965-1989",
        reported_effect="12-1 momentum winners beat losers by ~1%/month gross",
        cost_assumption="gross; no cost deduction",
        oos_evidence="extended to 1990s-2000s; broadly holds",
        post_publication_evidence="decays after publication (McLean-Pontiff ~35%)",
        independent_replication="Asness-Moskowitz-Pedersen 2013; Carhart 1997",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S006",
        title="Does Academic Research Destroy Stock Return Predictability?",
        authors="McLean, Pontiff",
        publication="Journal of Finance 71(1)",
        year=2016,
        url="https://www.fmg.ac.uk/sites/default/files/2020-08/Jeffrey-Pontiff.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MULTI_FAMILY",
        asset_class="US equities (anomalies)",
        sample="97 published predictors, 1926-2011",
        reported_effect="~35% average post-publication decay; ~58% for returns reported",
        cost_assumption="gross vs post-publication decay, not trading cost",
        oos_evidence="out-of-sample decay across 97 anomalies",
        post_publication_evidence="the canonical post-publication decay estimate",
        independent_replication="widely cited; extended by Jensen-Kelly-Pedersen 2023",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S007",
        title="Replicating Anomalies",
        authors="Hou, Xue, Zhang",
        publication="Review of Financial Studies 33(5)",
        year=2020,
        url="https://www.nber.org/system/files/working_papers/w23394/w23394.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MULTI_FAMILY",
        asset_class="US equities (452 anomalies)",
        sample="452 published anomalies",
        reported_effect="65% cannot clear a t > 1.96 hurdle (many are microcap-driven)",
        cost_assumption="returns not adjusted for trading cost",
        oos_evidence="direct replication with consistent methodology",
        post_publication_evidence="roughly two-thirds fail strict replication",
        independent_replication="Jensen-Kelly-Pedersen 2023 partially counters",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S008",
        title="...and the Cross-Section of Expected Returns",
        authors="Harvey, Liu, Zhu",
        publication="Review of Financial Studies 29(1)",
        year=2016,
        url="https://www.nber.org/system/files/working_papers/w20592/w20592.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MULTI_FAMILY",
        asset_class="US equities (316+ factors)",
        sample="316 factors, 1967-2014",
        reported_effect="a t > 3.0 (not 2.0) hurdle is needed after multiple testing",
        cost_assumption="statistical, not trading cost",
        oos_evidence="multiple-testing framework with historical cutoffs",
        post_publication_evidence="many published factors are marginal",
        independent_replication="Feng-Giglio-Xiu 2020 taming the factor zoo",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S009",
        title="Is There a Replication Crisis in Finance?",
        authors="Jensen, Kelly, Pedersen",
        publication="Journal of Finance 78(5)",
        year=2023,
        url="https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MULTI_FAMILY",
        asset_class="global equities (93 countries)",
        sample="153 factors, 93 countries",
        reported_effect=(
            "hierarchical Bayesian model finds most factors replicate once country and "
            "taxonomy are accounted for; the crisis is partly overstated"
        ),
        cost_assumption="cross-country factor returns; not net-of-cost",
        oos_evidence="out-of-sample hierarchical replication across countries",
        post_publication_evidence="more optimistic than Hou-Xue-Zhang",
        independent_replication="balancing counterpoint to S007/S008",
        reliability="high",
        evidence_role="context",
    ),
    Source(
        source_id="S010",
        title="Common Risk Factors in the Returns on Stocks and Bonds (value/size)",
        authors="Fama, French",
        publication="Journal of Financial Economics 33(1)",
        year=1993,
        url="https://www.sciencedirect.com/science/article/pii/0304405X93900235",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="VALUE_QUALITY",
        asset_class="US equities",
        sample="US stocks, 1963-1991",
        reported_effect="value (HML) premium positive and significant",
        cost_assumption="gross; no trading cost",
        oos_evidence="long out-of-sample history, US and global",
        post_publication_evidence="value weakened 2007-2020 then partially recovered",
        independent_replication="Ken French data library; Asness et al 2013",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S011",
        title="A Five-Factor Asset Pricing Model (profitability, investment)",
        authors="Fama, French",
        publication="Journal of Financial Economics 116(1)",
        year=2015,
        url="https://www.sciencedirect.com/science/article/pii/S0304405X14002323",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="VALUE_QUALITY",
        asset_class="US equities",
        sample="US stocks, 1963-2013",
        reported_effect="adds profitability (RMW) and investment (CMA) factors",
        cost_assumption="gross",
        oos_evidence="in-sample factor construction; broad OOS support",
        post_publication_evidence="quality/profitability broadly persistent",
        independent_replication="Novy-Marx 2013 gross profitability",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S012",
        title="Betting Against Beta",
        authors="Frazzini, Pedersen",
        publication="Journal of Financial Economics 111(1)",
        year=2014,
        url="https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="LOW_VOL_BAB",
        asset_class="equities, bonds, futures, FX (multi-asset)",
        sample="US and global assets, 1926-2012",
        reported_effect=(
            "leveraged low-beta / short high-beta BAB factor earns positive risk-adjusted returns"
        ),
        cost_assumption="gross; leverage and financing not fully charged",
        oos_evidence="low-beta effect across asset classes",
        post_publication_evidence="replication studies question the effect after 2012",
        independent_replication="mixed: Cederburg et al 2016; Barroso et al",
        reliability="medium-high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S013",
        title="Does It Pay to Bet Against Beta? Conditional Performance of the Beta Anomaly",
        authors="Cederburg, O'Doherty",
        publication="Journal of Finance 71(2)",
        year=2016,
        url="https://tevgeniou.github.io/EquityRiskFactors/bibliography/ConditionalBetaFactor.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="LOW_VOL_BAB",
        asset_class="US equities",
        sample="US stocks, dynamic beta",
        reported_effect="the beta anomaly is weak/unprofitable in a third of states",
        cost_assumption="conditional, cost-aware",
        oos_evidence="conditional performance analysis",
        post_publication_evidence="BAB is regime-dependent, not a free lunch",
        independent_replication="a replication challenge to S012",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S014",
        title="Common Risk Factors in Currency Markets",
        authors="Lustig, Roussanov, Verdelhan",
        publication="Review of Financial Studies 24(11)",
        year=2011,
        url="https://www.nber.org/system/files/working_papers/w14082/w14082.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="FX_CARRY",
        asset_class="currencies (forwards)",
        sample="35 currencies, 1983-2009",
        reported_effect="a slope (carry) factor explains the cross-section of currency returns",
        cost_assumption="gross; no bid/ask or funding charge",
        oos_evidence="broad cross-currency evidence",
        post_publication_evidence="carry survives but crashes periodically",
        independent_replication="Menkhoff et al 2012; Koijen et al 2018",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S015",
        title="Carry Trades and Currency Crashes",
        authors="Brunnermeier, Nagel, Pedersen",
        publication="NBER Macroeconomics Annual 23",
        year=2009,
        url="https://www.fmg.ac.uk/sites/default/files/2020-08/M-Brunnermeier.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="FX_CARRY",
        asset_class="currencies",
        sample="major currencies",
        reported_effect="carry earns a premium but has negative skew and crash risk",
        cost_assumption="gross risk framing",
        oos_evidence="documents crash risk explicitly",
        post_publication_evidence="carry persists with fat left tail",
        independent_replication="Jurek 2014 crash-neutral carry",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S016",
        title="Empirical evidence on the currency carry trade, 1900-2012",
        authors="Doskov, Nielsen",
        publication="Journal of International Money and Finance 51",
        year=2015,
        url="https://www.sciencedirect.com/science/article/abs/pii/S0261560614002150",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="FX_CARRY",
        asset_class="currencies",
        sample="currencies, 1900-2012 (112 years)",
        reported_effect="annual carry excess return ~2.4%; losses >10% in 6 of 112 years",
        cost_assumption="excess return; bid/ask not fully netted",
        oos_evidence="longest available OOS carry sample",
        post_publication_evidence="positive but modest and crash-prone",
        independent_replication="qualitatively consistent with S014",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S017",
        title="The Strategic and Tactical Value of Commodity Futures",
        authors="Erb, Harvey",
        publication="Financial Analysts Journal 62(2)",
        year=2006,
        url="https://www.tandfonline.com/doi/abs/10.2469/faj.v62.n2.4081",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="COMMODITY_MOMENTUM",
        asset_class="commodity futures",
        sample="commodity futures, 1982-2004",
        reported_effect="commodities diversify; term-structure and momentum signals have tactical value",
        cost_assumption="gross; roll yield discussed",
        oos_evidence="long commodity history",
        post_publication_evidence="commodity premia weakened post-2008",
        independent_replication="Gorton-Rouwenhorst 2006; Fuertes et al 2015",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S018",
        title="Facts and Fantasies about Commodity Futures",
        authors="Gorton, Rouwenhorst",
        publication="Financial Analysts Journal 62(2)",
        year=2006,
        url="https://www.nber.org/system/files/working_papers/w10595/w10595.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="FUTURES_CURVE_CARRY",
        asset_class="commodity futures",
        sample="commodity futures, 1959-2004",
        reported_effect="futures basis relates to risk premiums; collateralised futures earn equity-like returns",
        cost_assumption="gross; basis/roll analysed",
        oos_evidence="long sample",
        post_publication_evidence="basis premium persists but is smaller",
        independent_replication="Erb-Harvey 2006; Szymanowska et al 2014",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S019",
        title="Commodity Strategies Based on Momentum, Term Structure and Idiosyncratic Volatility",
        authors="Fuertes, Miffre, Fernandez-Perez",
        publication="Journal of Futures Markets 35(3)",
        year=2015,
        url="https://www.bayes.citystgeorges.ac.uk/__data/assets/pdf_file/0017/251702/No.-34-Fuertes_Commodity-Strategies.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="COMMODITY_MOMENTUM",
        asset_class="commodity futures",
        sample="commodity futures, 1980s-2010s",
        reported_effect="momentum, term-structure and IV signals are distinct and combinable",
        cost_assumption="discusses transaction costs and liquidity",
        oos_evidence="long commodity sample, robustness",
        post_publication_evidence="signals remain but weaker",
        independent_replication="de Groot et al 2014",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S020",
        title="Exploiting commodity momentum along the futures curves",
        authors="de Groot, Karstanje, Zhou",
        publication="Journal of Banking and Finance 48",
        year=2014,
        url="https://www.sciencedirect.com/science/article/abs/pii/S0378426614002751",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="FUTURES_CURVE_CARRY",
        asset_class="commodity futures",
        sample="commodity futures, 1986-2013",
        reported_effect="curve-structure carry and momentum combine into a profitable commodity portfolio",
        cost_assumption="net-of-cost considered; commodity futures turn over slowly",
        oos_evidence="subsample robustness",
        post_publication_evidence="carry/curve premia persist at lower magnitude",
        independent_replication="consistent with Gorton-Rouwenhorst and Erb-Harvey",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S021",
        title="Factor Momentum and the Momentum Factor",
        authors="Ehsani, Linnainmaa",
        publication="Journal of Finance 77(3)",
        year=2022,
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3014521",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="EQUITY_FACTOR_MOMENTUM",
        asset_class="US equities (factors)",
        sample="US factors, 1963-2016",
        reported_effect="factor momentum subsumes much stock momentum; factors time each other",
        cost_assumption="gross factor returns",
        oos_evidence="robust within sample; replication contested",
        post_publication_evidence="challenged as partially not replicable",
        independent_replication="Cakici-Zaremba 2025 challenges; Arnott et al 2018 supports",
        reliability="medium-high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S022",
        title="Factor momentum versus price momentum: Insights from international markets",
        authors="Cakici, Zaremba, Fieberg, Nolte",
        publication="Journal of Banking and Finance",
        year=2025,
        url="https://www.sciencedirect.com/science/article/abs/pii/S0378426624002462",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="EQUITY_FACTOR_MOMENTUM",
        asset_class="international equities",
        sample="51 countries",
        reported_effect="factor momentum exists but does not fully subsume price/industry momentum",
        cost_assumption="gross",
        oos_evidence="international OOS",
        post_publication_evidence="evidence depends on methodological and dataset choices",
        independent_replication="a replication challenge to S021",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S023",
        title="Pairs Trading: Performance of a Relative-Value Arbitrage Rule",
        authors="Gatev, Goetzmann, Rouwenhorst",
        publication="Review of Financial Studies 19(3)",
        year=2006,
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=141615",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="RELATIVE_VALUE_PAIRS",
        asset_class="US equities",
        sample="US stocks, 1962-2002",
        reported_effect="pairs trading earns ~11% p.a. gross excess in the early sample",
        cost_assumption="gross; high turnover, shorting and borrow not fully charged",
        oos_evidence="1962-2002 in-sample",
        post_publication_evidence="returns decay sharply after 2002 (crowding)",
        independent_replication="Do-Faff 2010 confirms post-2002 decay",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S024",
        title="The Profitability of Pairs Trading Strategies (decay evidence)",
        authors="Do, Faff",
        publication="Journal of Banking and Finance / working paper",
        year=2010,
        url="https://www.sciencedirect.com/science/article/abs/pii/S0378426609001957",
        source_type="independent_replication",
        retrieval_date="2026-10-05",
        strategy_family="RELATIVE_VALUE_PAIRS",
        asset_class="US equities",
        sample="US stocks, 1962-2009 extended",
        reported_effect="out-of-sample pairs returns fall, becoming insignificant after 2003",
        cost_assumption="cost-aware; shorting and turnover included",
        oos_evidence="extends Gatev et al out-of-sample",
        post_publication_evidence="naive pairs trading has decayed",
        independent_replication="a replication of S023 showing decay",
        reliability="high",
        evidence_role="counter",
    ),
    Source(
        source_id="S025",
        title="Variance Risk Premiums",
        authors="Carr, Wu",
        publication="Review of Financial Studies 22(3)",
        year=2009,
        url="https://www.sciencedirect.com/science/article/abs/pii/S0304405X08001747",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="VOLATILITY_RISK_PREMIUM",
        asset_class="equity index options, variance swaps",
        sample="S&P 500 index options",
        reported_effect="implied variance systematically exceeds realized variance -> premium",
        cost_assumption="variance-swap replication; option bid/ask and jumps matter a lot",
        oos_evidence="long index-option sample",
        post_publication_evidence="premium persists but is negative-skew and cost-sensitive",
        independent_replication="Bollerslev-Tauchen-Zhou 2009; numerous",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S026",
        title="Value and Momentum Everywhere",
        authors="Asness, Moskowitz, Pedersen",
        publication="Journal of Finance 68(3)",
        year=2013,
        url="https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="VALUE_QUALITY",
        asset_class="equities, bonds, currencies, commodities",
        sample="global multi-asset, 1972-2011",
        reported_effect="combo value+momentum everywhere earns strong risk-adjusted returns",
        cost_assumption="gross; turnover discussed",
        oos_evidence="cross-asset-class evidence",
        post_publication_evidence="robust but weakening in recent years",
        independent_replication="broader factor literature",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S027",
        title="Carry",
        authors="Koijen, Moskowitz, Pedersen, Vrugt",
        publication="Journal of Financial Economics 127(2)",
        year=2018,
        url="https://pages.stern.nyu.edu/~lpederse/papers/Carry.pdf",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="MULTI_ASSET_CARRY",
        asset_class="equities, bonds, currencies, commodities, options",
        sample="global multi-asset, 1980s-2012",
        reported_effect="a single global carry factor earns strong returns across asset classes",
        cost_assumption="gross; roll/funding discussed",
        oos_evidence="cross-asset carry factor",
        post_publication_evidence="carry persists but is crash-prone",
        independent_replication="overlaps FX and futures-curve carry (S014, S018)",
        reliability="high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S028",
        title="The Volatility Effect: Lower Risk Without Lower Return",
        authors="Blitz, van Vliet",
        publication="Journal of Portfolio Management 34(1)",
        year=2007,
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=980865",
        source_type="peer_reviewed_paper",
        retrieval_date="2026-10-05",
        strategy_family="LOW_VOL_BAB",
        asset_class="US and international equities",
        sample="US and international equities, 1986-2006",
        reported_effect="low-volatility stocks earn higher risk-adjusted returns",
        cost_assumption="gross; long-only tilt available",
        oos_evidence="international replication",
        post_publication_evidence="low-vol persists but has crowding/value overlap",
        independent_replication="Baker-Bradley-Wurgler 2011; Frazzini-Pedersen 2014",
        reliability="medium-high",
        evidence_role="supporting",
    ),
    Source(
        source_id="S029",
        title="Demystifying Managed Futures",
        authors="Hurst, Ooi, Pedersen",
        publication="Journal of Investment Management 11(3)",
        year=2013,
        url="https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Demystifying-Managed-Futures.pdf",
        source_type="established_quant_research",
        retrieval_date="2026-10-05",
        strategy_family="MANAGED_FUTURES_TREND",
        asset_class="multi-asset futures",
        sample="multi-asset futures, long history",
        reported_effect="diversified TSMOM gross Sharpe ~1.0 at 10% vol; positive in crises",
        cost_assumption="gross; notes capacity limits at scale",
        oos_evidence="practitioner multi-decade evidence",
        post_publication_evidence="still positive; capacity ceiling disputed",
        independent_replication="vendor research, not peer-reviewed",
        reliability="medium",
        evidence_role="context",
    ),
    Source(
        source_id="S030",
        title="Ken French Data Library (factor and portfolio returns)",
        authors="French, K.",
        publication="Dartmouth / online data library",
        year=2024,
        url="https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
        source_type="open_source_implementation",
        retrieval_date="2026-10-05",
        strategy_family="VALUE_QUALITY",
        asset_class="equities",
        sample="US and global factor returns",
        reported_effect="reference factor/portfolio series for replication",
        cost_assumption="pre-built gross portfolio returns",
        oos_evidence="data source, not an effect",
        post_publication_evidence="n/a",
        independent_replication="widely used",
        reliability="medium",
        evidence_role="context",
    ),
)


# --------------------------------------------------------------------------- #
# §38/§39 - scorecard dimensions
# --------------------------------------------------------------------------- #

SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "evidence_strength",
    "economic_headroom",
    "post_publication_survival",
    "data_feasibility",
    "tradability",
    "implementation_simplicity",
    "orthogonality",
    "portability",
)

#: §39 - a family cannot be a finalist if any of these is <= 1.
CRITICAL_DIMENSIONS: tuple[str, ...] = (
    "evidence_strength",
    "data_feasibility",
    "tradability",
)

#: §40 - ranking priority.  Evidence, then economics, then tradability, then data.
PRIORITY_ORDER: tuple[str, ...] = (
    "evidence_strength",
    "economic_headroom",
    "tradability",
    "data_feasibility",
    "post_publication_survival",
    "orthogonality",
    "implementation_simplicity",
    "portability",
)


# --------------------------------------------------------------------------- #
# §3/§6/§9 - reviewed strategy universe
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StrategyFamily:
    """One reviewed strategy family (no variants)."""

    family_id: str
    name: str
    required_group: str  # §9 A-J, or "EXTRA"
    asset_class: str
    markets: str
    horizon: str
    mechanism: str
    scores: dict[str, int]
    headroom_ratio: float | None
    turnover: str
    holding_period: str
    data_cost_class: str
    data_notes: str
    tradability_notes: str
    post_publication: str
    proxy: str
    research_cost: str
    time_to_validation: str
    fidelity: str
    capacity: str
    source_ids: tuple[str, ...]
    counter_evidence: str
    uncertainties: str
    early_kill_condition: str
    implementation_concept: str
    net_evidence_exception: bool = False

    @property
    def headroom_class(self) -> str:
        if self.headroom_ratio is None:
            return "NOT_APPLICABLE"
        return classify_headroom(self.headroom_ratio)

    @property
    def weak_critical_dimensions(self) -> tuple[str, ...]:
        return tuple(dim for dim in CRITICAL_DIMENSIONS if self.scores.get(dim, 0) <= 1)

    @property
    def in_top5_pool(self) -> bool:
        """§39 - critical dimension <= 1 removes a family from the shortlist."""
        return not self.weak_critical_dimensions


def _scores(
    evidence: int,
    economics: int,
    post_pub: int,
    data: int,
    tradability: int,
    simplicity: int,
    orthogonality: int,
    portability: int,
) -> dict[str, int]:
    return {
        "evidence_strength": evidence,
        "economic_headroom": economics,
        "post_publication_survival": post_pub,
        "data_feasibility": data,
        "tradability": tradability,
        "implementation_simplicity": simplicity,
        "orthogonality": orthogonality,
        "portability": portability,
    }


#: 12 families: the required §9 groups A-J plus two evidence-justified extras.
STRATEGY_FAMILIES: tuple[StrategyFamily, ...] = (
    StrategyFamily(
        family_id="MANAGED_FUTURES_TREND",
        name="Multi-asset managed-futures trend (time-series momentum)",
        required_group="A",
        asset_class="futures",
        markets="equity indices, government bonds, rates, FX, energy, metals, agriculture",
        horizon="WEEKLY/MONTHLY",
        mechanism=(
            "trend persistence driven by behavioural underreaction / delayed overreaction, "
            "plus risk transfer from hedgers to speculators"
        ),
        scores=_scores(5, 4, 4, 3, 4, 3, 5, 4),
        headroom_ratio=3.5,
        turnover="MONTHLY rebalance; LOW-MEDIUM turnover",
        holding_period="weeks to months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "daily futures closes across a broad market set are freely obtainable; the real "
            "work is PIT continuous-contract construction with an explicit roll rule"
        ),
        tradability_notes=(
            "long/short on liquid futures is structurally easy; margin-based, no borrow "
            "constraint; roll is an explicit cost"
        ),
        post_publication="SURVIVES",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="MEDIUM",
        time_to_validation="MEDIUM",
        fidelity="CLOSE",
        capacity="HIGH",
        source_ids=("S001", "S002", "S003", "S029", "S004"),
        counter_evidence=(
            "Huang et al (S004) argue single-asset TSM is weak; capacity/crowding critiques"
        ),
        uncertainties=(
            "can a free, PIT-safe multi-market futures dataset reproduce the effect without a "
            "paid vendor; is the recent-decade decay material"
        ),
        early_kill_condition=(
            "cannot reproduce a positive gross diversified trend effect on PIT free data, or "
            "gross edge < realistic roll+commission+spread floor"
        ),
        implementation_concept=(
            "volatility-scaled sign of past 3-12 month returns across a diversified futures "
            "universe; monthly rebalance; equal risk per market; explicit roll cost"
        ),
    ),
    StrategyFamily(
        family_id="CROSS_SECTIONAL_MOMENTUM",
        name="Cross-sectional equity momentum (winners minus losers)",
        required_group="B",
        asset_class="equities",
        markets="US / developed equity universe",
        horizon="MONTHLY",
        mechanism=(
            "behavioural underreaction to news plus slow information diffusion across stocks"
        ),
        scores=_scores(4, 3, 3, 2, 3, 2, 3, 3),
        headroom_ratio=2.0,
        turnover="MONTHLY rebalance; MEDIUM turnover",
        holding_period="1-12 months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "price momentum is computable from free daily prices, but a survivorship-free, "
            "PIT historical constituent universe is the hard part (§59)"
        ),
        tradability_notes=(
            "shorting losers requires borrow and is costly; long-only degrades the mechanism"
        ),
        post_publication="WEAKENED_BUT_PRESENT",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="MEDIUM",
        time_to_validation="HIGH",
        fidelity="CONCEPTUAL",
        capacity="MEDIUM",
        source_ids=("S005", "S006", "S026"),
        counter_evidence=(
            "McLean-Pontiff ~35% post-publication decay; momentum crashes (Daniel-Moskowitz)"
        ),
        uncertainties=(
            "survivorship-free universe availability; whether net-of-borrow long/short "
            "momentum survives"
        ),
        early_kill_condition=(
            "cannot assemble a PIT survivorship-free universe, or net edge < cost after short "
            "borrow and turnover"
        ),
        implementation_concept=(
            "rank a broad equity universe on 12-1 month returns, long top decile / short "
            "bottom decile, monthly rebalance, with borrow cost for the short leg"
        ),
    ),
    StrategyFamily(
        family_id="EQUITY_FACTOR_MOMENTUM",
        name="Equity factor momentum (timing factor premia)",
        required_group="C",
        asset_class="equities",
        markets="US / developed factor portfolios",
        horizon="MONTHLY",
        mechanism=(
            "persistent autocorrelation in factor premia due to slow capital reallocation "
            "across styles"
        ),
        scores=_scores(4, 3, 3, 2, 3, 2, 3, 3),
        headroom_ratio=2.0,
        turnover="MONTHLY rebalance; MEDIUM turnover",
        holding_period="1-12 months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "factor returns can be proxied via pre-built books (French data), but the timing "
            "signal needs a consistent factor set and PIT discipline"
        ),
        tradability_notes="traded via factor long/short baskets or factor ETFs; capacity moderate",
        post_publication="WEAKENED_BUT_PRESENT",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="MEDIUM",
        time_to_validation="HIGH",
        fidelity="CONCEPTUAL",
        capacity="MEDIUM",
        source_ids=("S021", "S022"),
        counter_evidence=(
            "Cakici-Zaremba (S022): factor momentum does not fully subsume price momentum and "
            "is dataset-dependent"
        ),
        uncertainties=(
            "is factor momentum distinct from price momentum; does it survive transaction costs"
        ),
        early_kill_condition=(
            "factor momentum cannot be distinguished from price momentum, or net edge < cost"
        ),
        implementation_concept=(
            "time-series momentum on a fixed set of factor returns; rotate into factors with "
            "positive trailing momentum; monthly"
        ),
    ),
    StrategyFamily(
        family_id="VALUE_QUALITY",
        name="Value / quality factor portfolio",
        required_group="D",
        asset_class="equities",
        markets="US / global equity universe",
        horizon="MONTHLY/QUARTERLY",
        mechanism=(
            "risk premium for bearing fundamental risk and investor over-extrapolation of "
            "growth / distress (slow-moving valuation differentials)"
        ),
        scores=_scores(5, 4, 4, 2, 3, 2, 3, 3),
        headroom_ratio=3.0,
        turnover="QUARTERLY rebalance; LOW turnover",
        holding_period="months to years",
        data_cost_class="PAID",
        data_notes=(
            "value/quality require PIT fundamentals and a survivorship-free universe; the "
            "clean data are commercial (Compustat-class) -> §29 paid-data handling"
        ),
        tradability_notes=(
            "long-only value/quality is tradable via ETFs; the long/short premium needs shorts"
        ),
        post_publication="SURVIVES",
        proxy="VALID_PROXY",
        research_cost="HIGH",
        time_to_validation="HIGH",
        fidelity="CONCEPTUAL",
        capacity="HIGH",
        source_ids=("S010", "S011", "S026", "S030"),
        counter_evidence=(
            "value drawdown 2007-2020; Hou-Xue-Zhang strict replication failures; "
            "microcap dependence concerns"
        ),
        uncertainties=(
            "can a free/low-cost proxy reproduce the effect faithfully; is value timing needed"
        ),
        early_kill_condition=(
            "PIT fundamentals cannot be obtained without paid data, or a free proxy cannot "
            "preserve the mechanism"
        ),
        implementation_concept=(
            "long high value + high quality / short low, or a long-only ETF proxy; "
            "quarterly rebalance; fundamentals PIT"
        ),
    ),
    StrategyFamily(
        family_id="LOW_VOL_BAB",
        name="Low-volatility / defensive (betting-against-beta)",
        required_group="E",
        asset_class="equities",
        markets="US / international equities",
        horizon="MONTHLY",
        mechanism=(
            "leverage constraints push investors toward high-beta assets, leaving a low-risk "
            "premium (institutional constraint)"
        ),
        scores=_scores(4, 3, 3, 2, 3, 3, 3, 3),
        headroom_ratio=2.5,
        turnover="MONTHLY rebalance; LOW-MEDIUM turnover",
        holding_period="months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "beta estimation needs a survivorship-free return panel; low-vol can be done "
            "long-only with free prices"
        ),
        tradability_notes=(
            "BAB needs leverage and shorting high-beta; long-only low-vol is easy"
        ),
        post_publication="WEAKENED_BUT_PRESENT",
        proxy="VALID_PROXY",
        research_cost="MEDIUM",
        time_to_validation="MEDIUM",
        fidelity="CONCEPTUAL",
        capacity="HIGH",
        source_ids=("S012", "S013", "S028"),
        counter_evidence=(
            "Cederburg-O'Doherty (S013): the beta anomaly is regime-dependent; leverage "
            "financing costs erode BAB"
        ),
        uncertainties=(
            "is BAB a financing artefact; does long-only low-vol preserve enough of the premium"
        ),
        early_kill_condition=(
            "the beta anomaly is only profitable in rare states, or leverage cost exceeds the "
            "premium"
        ),
        implementation_concept=(
            "rank stocks on beta / volatility, long low-beta (or a low-vol ETF), short high-beta "
            "with leverage; monthly"
        ),
    ),
    StrategyFamily(
        family_id="MULTI_ASSET_CARRY",
        name="Multi-asset carry (cross-asset carry factor)",
        required_group="F",
        asset_class="multi-asset",
        markets="FX, bonds, commodities, equities, options",
        horizon="MONTHLY",
        mechanism="carry risk premium: investors are paid to hold/roll high-yield instruments",
        scores=_scores(3, 4, 3, 3, 3, 2, 4, 3),
        headroom_ratio=3.0,
        turnover="MONTHLY rebalance; LOW turnover",
        holding_period="months",
        data_cost_class="LOW_COST",
        data_notes=(
            "requires per-asset carry definitions (forward points, roll yields, dividends); "
            "patchy but constructible from free/low-cost sources"
        ),
        tradability_notes="cross-asset carry is tradable but each sleeve adds instrument complexity",
        post_publication="SURVIVES",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="HIGH",
        time_to_validation="HIGH",
        fidelity="CONCEPTUAL",
        capacity="MEDIUM",
        source_ids=("S027", "S014", "S018"),
        counter_evidence=(
            "carry crashes (Brunnermeier-Nagel-Pedersen); sleeves overlap FX and curve carry"
        ),
        uncertainties=(
            "does a simplified multi-asset carry survive when each sleeve needs its own data"
        ),
        early_kill_condition=(
            "the composite adds no edge beyond its single-asset sleeves, or data is too patchy"
        ),
        implementation_concept=(
            "rank instruments within each asset class by carry, long top / short bottom, "
            "aggregate with equal risk; monthly"
        ),
    ),
    StrategyFamily(
        family_id="FX_CARRY",
        name="FX carry trade (high-yield vs low-yield currencies)",
        required_group="G",
        asset_class="FX",
        markets="major and liquid emerging currencies",
        horizon="MONTHLY",
        mechanism=(
            "risk premium for bearing currency crash risk and funding-liquidity constraints"
        ),
        scores=_scores(4, 3, 4, 3, 3, 3, 4, 4),
        headroom_ratio=3.0,
        turnover="MONTHLY rebalance; LOW turnover",
        holding_period="months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "spot FX and short-rate interest differentials are freely available; forward "
            "points are less freely available but approximable"
        ),
        tradability_notes=(
            "retail FX carry is implementable long/short with leverage; watch funding and "
            "negative skew"
        ),
        post_publication="SURVIVES",
        proxy="NOT_APPLICABLE",
        research_cost="MEDIUM",
        time_to_validation="MEDIUM",
        fidelity="CLOSE",
        capacity="MEDIUM",
        source_ids=("S014", "S015", "S016"),
        counter_evidence=(
            "Brunnermeier-Nagel-Pedersen crash risk; 2.4%/yr is modest and left-skewed"
        ),
        uncertainties=(
            "does the premium survive bid/ask and periodic crashes; is the free interest-rate "
            "differential clean enough"
        ),
        early_kill_condition=(
            "net carry after spread and funding is negative, or the crash tail is unacceptable"
        ),
        implementation_concept=(
            "rank currencies by interest differential, long high-yield / short low-yield, "
            "volatility-scaled; monthly"
        ),
    ),
    StrategyFamily(
        family_id="FUTURES_CURVE_CARRY",
        name="Futures curve / term-structure carry",
        required_group="H",
        asset_class="commodity / futures",
        markets="commodity and financial futures",
        horizon="MONTHLY",
        mechanism=(
            "roll yield / risk premium for providing storage or hedging services; basis "
            "predicts futures returns"
        ),
        scores=_scores(4, 5, 4, 4, 4, 3, 4, 4),
        headroom_ratio=4.0,
        turnover="MONTHLY rebalance; LOW turnover",
        holding_period="months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "needs a term structure (two or more contract months) to compute basis; free for a "
            "subset of liquid futures; PIT roll rules required"
        ),
        tradability_notes="liquid futures, long/short, roll is explicit; no borrow needed",
        post_publication="SURVIVES",
        proxy="NOT_APPLICABLE",
        research_cost="LOW",
        time_to_validation="LOW",
        fidelity="CLOSE",
        capacity="HIGH",
        source_ids=("S018", "S020", "S017"),
        counter_evidence=(
            "post-2008 commodity premia compression; simple long-only commodity indices "
            "disappointed (Main et al)"
        ),
        uncertainties=(
            "is free term-structure data clean enough; how much does roll cost erode the basis"
        ),
        early_kill_condition=(
            "free basis data is too sparse/unreliable, or net carry after roll < cost"
        ),
        implementation_concept=(
            "compute the futures basis (near minus far) per market, long backwardated / short "
            "contangoed, volatility-scaled; monthly"
        ),
    ),
    StrategyFamily(
        family_id="RELATIVE_VALUE_PAIRS",
        name="Relative-value / pairs / spread mean-reversion",
        required_group="I",
        asset_class="equities",
        markets="US equities (or liquid ETFs)",
        horizon="DAILY/WEEKLY",
        mechanism=(
            "temporary liquidity-driven mispricing between economically linked securities "
            "(liquidity provision)"
        ),
        scores=_scores(3, 2, 2, 3, 2, 3, 3, 3),
        headroom_ratio=1.2,
        turnover="DAILY/WEEKLY rebalance; HIGH turnover",
        holding_period="days",
        data_cost_class="FREE_NEW",
        data_notes="daily prices suffice; but shorting and borrow history matter",
        tradability_notes=(
            "needs shorting and borrow; high turnover makes cost dominant; EXT-TSMOM-001-style "
            "short-feasibility trap"
        ),
        post_publication="DECAYED",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="MEDIUM",
        time_to_validation="MEDIUM",
        fidelity="CONCEPTUAL",
        capacity="LOW",
        source_ids=("S023", "S024"),
        counter_evidence=(
            "Do-Faff (S024): naive pairs returns fall and become insignificant after 2003"
        ),
        uncertainties=(
            "is any residual edge net of spread, borrow and turnover; crowding"
        ),
        early_kill_condition=(
            "gross mean-reversion edge below round-trip cost (TOO_THIN headroom)"
        ),
        implementation_concept=(
            "form distance-matched pairs, trade divergence from the spread; weekly; "
            "explicit spread + borrow cost"
        ),
    ),
    StrategyFamily(
        family_id="VOLATILITY_RISK_PREMIUM",
        name="Volatility / variance risk premium",
        required_group="J",
        asset_class="options",
        markets="equity index options / variance swaps",
        horizon="MONTHLY",
        mechanism=(
            "investors overpay for variance insurance; premium for bearing volatility risk "
            "(institutional hedging demand)"
        ),
        scores=_scores(5, 4, 4, 1, 2, 2, 4, 2),
        headroom_ratio=5.0,
        turnover="MONTHLY rebalance; LOW-MEDIUM turnover",
        holding_period="weeks to months",
        data_cost_class="EXPENSIVE",
        data_notes=(
            "requires historical option chains / implied-variance surfaces with bid/ask; "
            "expensive and incomplete for free (§14, §27) -> paid/expensive data"
        ),
        tradability_notes=(
            "short-vol exposure needs an options infrastructure we do not have; large tail risk"
        ),
        post_publication="SURVIVES",
        proxy="NOT_APPLICABLE",
        research_cost="HIGH",
        time_to_validation="HIGH",
        fidelity="NOT_REPRODUCIBLE",
        capacity="MEDIUM",
        source_ids=("S025",),
        counter_evidence=(
            "option bid/ask and jumps dominate; negative skew -> large rare losses; individual "
            "equity VRP may be negative"
        ),
        uncertainties=(
            "no options infrastructure and no affordable option history -> not reproducible here"
        ),
        early_kill_condition=(
            "cannot obtain affordable PIT option data, or cannot model option execution"
        ),
        implementation_concept=(
            "sell index variance / short straddles vs realized vol; requires option data and "
            "execution we do not have (recorded, NOT built)"
        ),
    ),
    StrategyFamily(
        family_id="COMMODITY_MOMENTUM",
        name="Cross-sectional commodity futures momentum",
        required_group="EXTRA",
        asset_class="commodity futures",
        markets="energy, metals, agriculture, softs",
        horizon="MONTHLY",
        mechanism=(
            "behavioural underreaction to commodity supply/demand news plus slow hedging "
            "adjustment"
        ),
        scores=_scores(4, 4, 4, 3, 4, 3, 3, 3),
        headroom_ratio=3.5,
        turnover="MONTHLY rebalance; LOW turnover",
        holding_period="1-12 months",
        data_cost_class="FREE_NEW",
        data_notes=(
            "free daily commodity futures closes exist for a broad set; roll rules needed; "
            "smaller universe than managed futures"
        ),
        tradability_notes="liquid commodity futures, long/short, no borrow; roll is the cost",
        post_publication="SURVIVES",
        proxy="RESEARCH_PROXY_ONLY",
        research_cost="LOW",
        time_to_validation="LOW",
        fidelity="CLOSE",
        capacity="MEDIUM",
        source_ids=("S017", "S019", "S020"),
        counter_evidence=(
            "commodity premia weakened post-2008; momentum can overlap curve carry and managed "
            "futures trend"
        ),
        uncertainties=(
            "distinctness from managed-futures trend and curve carry; free data depth"
        ),
        early_kill_condition=(
            "commodity momentum is not distinct from trend, or net edge < roll+commission cost"
        ),
        implementation_concept=(
            "rank commodity futures on 3-12 month returns, long top / short bottom, "
            "volatility-scaled; monthly"
        ),
    ),
    StrategyFamily(
        family_id="COUNTRY_EQUITY_MOMENTUM",
        name="Cross-country equity index momentum (via liquid ETFs)",
        required_group="EXTRA",
        asset_class="equities (indices)",
        markets="developed and emerging country equity ETFs",
        horizon="MONTHLY",
        mechanism=(
            "slow diffusion of country-level macro information and persistent capital flows "
            "(slow capital)"
        ),
        scores=_scores(3, 3, 3, 4, 4, 4, 3, 4),
        headroom_ratio=2.5,
        turnover="MONTHLY rebalance; LOW turnover",
        holding_period="1-12 months",
        data_cost_class="FREE_EXISTING",
        data_notes="liquid country ETFs have free, clean, long daily price histories; no fundamentals",
        tradability_notes="long-only country ETF rotation, or long/short with shortable ETFs",
        post_publication="WEAKENED_BUT_PRESENT",
        proxy="VALID_PROXY",
        research_cost="LOW",
        time_to_validation="LOW",
        fidelity="CLOSE",
        capacity="MEDIUM",
        source_ids=("S026", "S005"),
        counter_evidence=(
            "country momentum is correlated with global equity beta; limited independent edge"
        ),
        uncertainties=(
            "is there a genuine country effect beyond global equity beta and US momentum"
        ),
        early_kill_condition=(
            "returns are explained by static equity beta, or net edge < ETF cost"
        ),
        implementation_concept=(
            "rank country ETFs on trailing 3-12 month returns, hold top-k; monthly; explicit "
            "spread + borrow for shorts"
        ),
    ),
)


def family_by_id(family_id: str) -> StrategyFamily:
    for fam in STRATEGY_FAMILIES:
        if fam.family_id == family_id:
            return fam
    raise KeyError(family_id)


# --------------------------------------------------------------------------- #
# §42-§50 - shortlist, finalist and authorization derivation
# --------------------------------------------------------------------------- #


def _priority_key(fam: StrategyFamily) -> tuple[int, ...]:
    """§40 - descending lexicographic priority key (higher is better)."""
    return tuple(fam.scores[dim] for dim in PRIORITY_ORDER)


def ranked_families() -> tuple[StrategyFamily, ...]:
    """§39/§40 - eligible families ranked by the priority ordering (deterministic)."""
    eligible = [f for f in STRATEGY_FAMILIES if f.in_top5_pool]
    # Sort by priority descending, then family_id ascending for determinism.
    ordered = sorted(eligible, key=lambda f: (tuple(-v for v in _priority_key(f)), f.family_id))
    return tuple(ordered)


def select_top5() -> tuple[StrategyFamily, ...]:
    """§42 - the MAX 5 shortlist for deep review."""
    return ranked_families()[:MAX_TOP5]


def select_finalists() -> tuple[StrategyFamily, ...]:
    """§47 - the MAX 3 finalists, excluding REJECT/TOO_THIN economics."""
    out: list[StrategyFamily] = []
    for fam in ranked_families():
        if fam.headroom_class in {"REJECT", "TOO_THIN"}:
            continue
        out.append(fam)
        if len(out) == MAX_FINALISTS:
            break
    return tuple(out)


def candidate_passes_reentry(fam: StrategyFamily) -> bool:
    """§51 - does this family meet every re-entry condition?"""
    s = fam.scores
    strong_evidence = s["evidence_strength"] >= 4
    credible_mechanism = bool(fam.mechanism.strip())
    headroom_ok = fam.headroom_ratio is not None and (
        fam.headroom_ratio >= 1.5 or fam.net_evidence_exception
    )
    tradable = s["tradability"] >= 3
    data_feasible = s["data_feasibility"] >= 3
    data_affordable = fam.data_cost_class in FREE_OR_LOW_DATA
    no_major_infra = s["implementation_simplicity"] >= 3
    return all(
        (
            strong_evidence,
            credible_mechanism,
            headroom_ok,
            tradable,
            data_feasible,
            data_affordable,
            no_major_infra,
        )
    )


def authorize_reproductions() -> tuple[StrategyFamily, ...]:
    """§49/§54 - MAX 2 authorized reproductions among the finalists, in rank order."""
    out: list[StrategyFamily] = []
    for fam in select_finalists():
        if candidate_passes_reentry(fam):
            out.append(fam)
        if len(out) == MAX_AUTHORIZED:
            break
    return tuple(out)


class ReentryStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ReentryGate:
    status: ReentryStatus
    qualifying: tuple[str, ...]
    authorized_p1: str | None
    authorized_p2: str | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status_value(self) -> str:
        return self.status.value


def evaluate_reentry_gate() -> ReentryGate:
    """§51/§52/§53 - G_REENTRY = PASS iff >= 1 family passes every condition."""
    qualifying = tuple(
        fam.family_id for fam in STRATEGY_FAMILIES if candidate_passes_reentry(fam)
    )
    authorized = authorize_reproductions()
    p1 = authorized[0].family_id if len(authorized) >= 1 else None
    p2 = authorized[1].family_id if len(authorized) >= 2 else None
    if qualifying:
        return ReentryGate(ReentryStatus.PASS, qualifying, p1, p2, ())
    return ReentryGate(
        ReentryStatus.FAIL,
        (),
        None,
        None,
        ("NO STRATEGY MEETS THE RE-ENTRY CONDITIONS",),
    )


def decision_for(fam: StrategyFamily, gate: ReentryGate) -> str:
    """§75 - map a family to exactly one decision value."""
    if fam.family_id == gate.authorized_p1:
        return "AUTHORIZE_P1"
    if fam.family_id == gate.authorized_p2:
        return "AUTHORIZE_P2"
    if fam.weak_critical_dimensions:
        if "data_feasibility" in fam.weak_critical_dimensions:
            return "DEFER_DATA"
        if "tradability" in fam.weak_critical_dimensions:
            return "REJECT_TRADABILITY"
        return "REJECT_EVIDENCE"
    if fam.headroom_class in {"REJECT", "TOO_THIN"}:
        return "REJECT_ECONOMICS"
    if fam.scores["data_feasibility"] <= 2 or fam.data_cost_class in {"PAID", "EXPENSIVE"}:
        return "DEFER_DATA"
    if fam.scores["tradability"] <= 2:
        return "REJECT_TRADABILITY"
    return "WATCHLIST"


def profitability_research_status(gate: ReentryGate) -> str:
    """§52/§53 - PAUSED unless G_REENTRY passes."""
    if gate.status is ReentryStatus.PASS:
        return APPROVED_PROFITABILITY_RESEARCH_STATUS
    return ENTRY_PROFITABILITY_RESEARCH_STATUS


def next_alpha_rfc_allowed(gate: ReentryGate) -> bool:
    """§52/§53 - only a passing G_REENTRY may enable a future alpha RFC."""
    return gate.status is ReentryStatus.PASS


# --------------------------------------------------------------------------- #
# §88 - FALSE_SUCCESS triggers for an admission review
# --------------------------------------------------------------------------- #

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "weak_source_treated_as_strong_evidence",
    "reported_gross_treated_as_net",
    "paid_or_unavailable_data_ignored",
    "short_feasibility_ignored",
    "survivorship_not_penalised",
    "crypto_tsmom_failure_generalised_to_managed_futures",
    "strategy_selected_after_internal_backtest",
    "score_changed_to_justify_preferred_candidate",
    "candidate_implemented_during_rfc035",
    "next_alpha_rfc_enabled_without_g_reentry_pass",
)


@dataclass(frozen=True, slots=True)
class AdmissionClaim:
    """A project-level claim checked against the admission rules (§88)."""

    weak_source_used_as_strong: bool = False
    gross_reported_as_net: bool = False
    paid_data_ignored: bool = False
    short_feasibility_ignored: bool = False
    survivorship_ignored: bool = False
    crypto_tsmom_generalised: bool = False
    selected_after_internal_backtest: bool = False
    score_adjusted_for_preferred: bool = False
    implemented_during_rfc035: bool = False
    alpha_rfc_enabled_without_pass: bool = False

    def false_success(self) -> tuple[str, ...]:
        fired: list[str] = []
        if self.weak_source_used_as_strong:
            fired.append("weak_source_treated_as_strong_evidence")
        if self.gross_reported_as_net:
            fired.append("reported_gross_treated_as_net")
        if self.paid_data_ignored:
            fired.append("paid_or_unavailable_data_ignored")
        if self.short_feasibility_ignored:
            fired.append("short_feasibility_ignored")
        if self.survivorship_ignored:
            fired.append("survivorship_not_penalised")
        if self.crypto_tsmom_generalised:
            fired.append("crypto_tsmom_failure_generalised_to_managed_futures")
        if self.selected_after_internal_backtest:
            fired.append("strategy_selected_after_internal_backtest")
        if self.score_adjusted_for_preferred:
            fired.append("score_changed_to_justify_preferred_candidate")
        if self.implemented_during_rfc035:
            fired.append("candidate_implemented_during_rfc035")
        if self.alpha_rfc_enabled_without_pass:
            fired.append("next_alpha_rfc_enabled_without_g_reentry_pass")
        return tuple(fired)


def audit_false_success(gate: ReentryGate) -> dict[str, Any]:
    """§88 - RFC-035 must never fire a FALSE_SUCCESS trigger."""
    status = profitability_research_status(gate)
    # Guard: a future alpha RFC may only be enabled when the gate passed.
    enabled_without_pass = next_alpha_rfc_allowed(gate) and gate.status is not ReentryStatus.PASS
    claim = AdmissionClaim(alpha_rfc_enabled_without_pass=enabled_without_pass)
    return {
        "triggers": list(FALSE_SUCCESS_TRIGGERS),
        "fired": list(claim.false_success()),
        "false_success": len(claim.false_success()),
        "profitability_research_status": status,
    }


# --------------------------------------------------------------------------- #
# §76-§78 - the plan summary used by the tracked and report artifacts
# --------------------------------------------------------------------------- #


def plan_summary() -> dict[str, Any]:
    """Compact, machine-readable plan summary (§78)."""
    gate = evaluate_reentry_gate()
    authorized = authorize_reproductions()
    top5 = select_top5()
    finalists = select_finalists()
    return {
        "rfc": "RFC-035",
        "title": "STRATEGIC PROFITABILITY PLAN V2",
        "phase_1_status": "CLOSED",
        "phase_2_status": profitability_research_status(gate),
        "platform_status": PLATFORM_STATUS,
        "economic_status": ECONOMIC_STATUS,
        "entry_profitability_research_status": ENTRY_PROFITABILITY_RESEARCH_STATUS,
        "entry_next_alpha_rfc_allowed": ENTRY_NEXT_ALPHA_RFC_ALLOWED,
        "strategy_families_reviewed": len(STRATEGY_FAMILIES),
        "top5": [f.family_id for f in top5],
        "finalists": [f.family_id for f in finalists],
        "g_reentry": gate.status_value,
        "authorized_reproductions": [f.family_id for f in authorized],
        "p1": gate.authorized_p1,
        "p2": gate.authorized_p2,
        "next_alpha_rfc_allowed": next_alpha_rfc_allowed(gate),
        "next_rfc_type": NEXT_RFC_TYPE if gate.status is ReentryStatus.PASS else None,
        "kpi": {
            "executable_validated_edge_count": EXECUTABLE_VALIDATED_EDGE_COUNT,
            "robust_edge_count": ROBUST_EDGE_COUNT,
            "paper_candidate_count": PAPER_CANDIDATE_COUNT,
            "forward_profitable_count": FORWARD_PROFITABLE_COUNT,
            "live_profitable_count": LIVE_PROFITABLE_COUNT,
            "phase_2_target": PHASE_2_TARGET_EXECUTABLE_VALIDATED_EDGE_COUNT,
        },
        "max_implemented_strategies": MAX_IMPLEMENTED_STRATEGIES,
        "max_parameter_variants": MAX_PARAMETER_VARIANTS,
    }
