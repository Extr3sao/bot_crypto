"""RFC-042 orchestration — BUSINESS OPPORTUNITY RADAR & REENTRY DECISION.

One snapshot research run while ``ALPHA_RESEARCH_FREEZE = ACTIVE``.  It performs
external-evidence surveillance (§5), screens at most eight opportunities (§6),
deep-reviews at most three (§24), applies ``G_BUSINESS_REENTRY`` (§26-§27) and
returns ``NO_REENTRY`` or exactly one reentry-qualified candidate (§28-§32).

No alpha, no strategy, no signal, no backtest, no PnL, no portfolio, no broker,
no paper, no live and no paid data (§43-§46).  Selection is external-evidence
first: no internal return of any candidate is consulted (§44).

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research import opportunity_radar as radar  # noqa: E402

OUT = REPO / "reports" / "business-opportunity-radar"
REPORTS = REPO / "reports"

#: §1 — expected repository state entering RFC-042 (verified, never assumed).
EXPECTED_ANCESTORS: dict[str, str] = {
    "RFC-040": "1216c0c",
    "RFC-041": "1437f46",
}

RETRIEVAL_DATE = "2026-10-06"

#: §27 — the candidates any reentry must be materially better justified than.
REFERENCE_REJECTED: tuple[str, ...] = ("SC-TREND-001", "SC-DUALMOM-002")

#: §8 — archived families used to detect a renamed idea.
ARCHIVED_FAMILIES: tuple[str, ...] = (
    "time-series momentum / trend",
    "crypto momentum",
    "dual momentum / gem",
    "multi-asset absolute momentum",
    "diversified managed-futures trend",
    "cross-sectional momentum",
)

# --------------------------------------------------------------------------- #
# §33 — source registry
# --------------------------------------------------------------------------- #

SOURCES: list[dict[str, Any]] = [
    {
        "source_id": "SRC-042-01",
        "title": "Zeroing In on the Expected Returns of Anomalies",
        "authors": ["Andrew Y. Chen", "Mihail Velikov"],
        "year": 2023,
        "url": "https://doi.org/10.1017/S0022109022000874",
        "publication_type": "peer_reviewed_journal",
        "strategy_family": "equity anomalies (long-short)",
        "claim": (
            "Net of effective bid-ask spreads, post-publication decay and the modern "
            "trading-technology era, the average anomaly earns a negligible expected return."
        ),
        "sample": "204 stock-market anomalies",
        "reported_net_effect": "average 4 bps/month; strongest 10 bps; combined ~20 bps",
        "benchmark": "n/a (long-short anomalies)",
        "cost_assumption": "effective bid-ask spreads; price impact omitted",
        "post_publication": "DECAYED",
        "counter_evidence": "in-sample net returns are impressive before post-publication adjustment",
        "reliability": "high",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-02",
        "title": "Not All Factors Crowd Equally: Modeling, Measuring, and Trading on Alpha Decay",
        "authors": ["Chorok Lee"],
        "year": 2025,
        "url": "https://arxiv.org/html/2512.11913v1",
        "publication_type": "working_paper",
        "strategy_family": "equity factors (Fama-French)",
        "claim": (
            "Factor alpha decays hyperbolically; crowding accelerated after 2015; a real-time "
            "crowding signal does not generate alpha (Sharpe 0.22 vs 0.39 benchmark)."
        ),
        "sample": "8 Fama-French factors, 1963-2024",
        "reported_net_effect": "crowding predicts crashes, not means; no trading alpha",
        "benchmark": "factor momentum (Sharpe 0.39)",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "mechanical factors fit the model better than judgment factors",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-03",
        "title": "What Drives Anomaly Decay?",
        "authors": ["J. Brogaard", "et al."],
        "year": 2024,
        "url": "https://www.aeaweb.org/conference/2024/program/paper/SNQSBFkB",
        "publication_type": "working_paper",
        "strategy_family": "equity anomalies",
        "claim": "Anomalies decay primarily around structural increases in information availability.",
        "sample": "decomposition of price information",
        "reported_net_effect": "decay around publication/structural increases",
        "benchmark": "n/a",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "decay is endogenous to information supply, not only arbitrage",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-04",
        "title": "Anomalies across the globe: Once public, no longer existent?",
        "authors": ["Heiko Jacobs", "Sebastian Müller"],
        "year": 2019,
        "url": "https://www.unicreditgroup.eu/content/dam/unicreditgroup-eu/ucfoundation/WorkingPapers/2019/wp-135-Jacobs-e-Mueller.pdf",
        "publication_type": "working_paper",
        "strategy_family": "equity anomalies (global)",
        "claim": "Anomaly returns decline strongly after academic publication.",
        "sample": "global equity anomalies, 1981-2016",
        "reported_net_effect": "38% post-sample and 62% post-publication decline",
        "benchmark": "n/a",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "post-sample decline also reflects the in-sample bias",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-05",
        "title": "Trading Costs Wipe Out the Overnight Return Anomaly",
        "authors": ["Alpha Architect (research note)"],
        "year": 2020,
        "url": "https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/",
        "publication_type": "blog_discovery_only",
        "strategy_family": "overnight / close-to-open drift",
        "claim": "The overnight return strategy is inefficient and non-repeatable after trading costs.",
        "sample": "US equity ETFs",
        "reported_net_effect": "gross positive, net negative after costs",
        "benchmark": "buy-and-hold",
        "cost_assumption": "daily round-trip trading costs",
        "post_publication": "CONTRADICTORY",
        "counter_evidence": "peer-reviewed overnight/intraday decomposition exists (Lou-Polk-Skouras 2019)",
        "reliability": "low",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-06",
        "title": "The Disappearing Index Effect",
        "authors": ["Robin Greenwood", "Marco Sammon"],
        "year": 2024,
        "url": "https://www.hbs.edu/ris/download.aspx?name=ssrn-4294297.pdf",
        "publication_type": "working_paper",
        "strategy_family": "index reconstitution forced flows",
        "claim": "Abnormal returns around S&P 500 additions/deletions have largely disappeared.",
        "sample": "S&P 500 additions and deletions",
        "reported_net_effect": "index effect near zero in recent decades",
        "benchmark": "market",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "short-window announcement moves can still be positive for additions",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-07",
        "title": "The Decline of the Variance Risk Premium",
        "authors": ["Ian Dew-Becker", "et al."],
        "year": 2025,
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5525882",
        "publication_type": "working_paper",
        "strategy_family": "volatility risk premium (covered calls / short vol)",
        "claim": "The variance risk premium has materially declined in recent years.",
        "sample": "traded and synthetic options",
        "reported_net_effect": "declining premium",
        "benchmark": "n/a",
        "cost_assumption": "option transaction costs",
        "post_publication": "DECAYED",
        "counter_evidence": "a positive premium still exists on average",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-08",
        "title": "A Conceptual Primer on Covered Call ETFs",
        "authors": ["Agisilaos Papadogiannis"],
        "year": 2025,
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5370897",
        "publication_type": "working_paper",
        "strategy_family": "covered call / option income ETF",
        "claim": "Covered-call ETFs trade equity upside for income; net outcome depends on costs and path.",
        "sample": "covered-call ETF structures",
        "reported_net_effect": "capped upside, partial downside cushion",
        "benchmark": "underlying equity index",
        "cost_assumption": "ETF fees, option spreads",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "documented underperformance vs equity in sustained bull markets",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-09",
        "title": "Covered-Call ETFs Are Booming. But Not All Yield Is Good",
        "authors": ["Morningstar (research note)"],
        "year": 2025,
        "url": "https://www.morningstar.com/podcasts/investing-insights/covered-call-etfs-are-booming-not-all-yield-is-good",
        "publication_type": "institutional_research",
        "strategy_family": "covered call / option income ETF",
        "claim": "High distribution yield comes at a cost to total return.",
        "sample": "covered-call ETFs",
        "reported_net_effect": "yield is not free total return",
        "benchmark": "equity index",
        "cost_assumption": "not explicit",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "some income strategies still add value in drawdowns",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-10",
        "title": "Market Adaptation and the Declining Turn-of-the-Month Effect",
        "authors": ["(SSRN working paper)"],
        "year": 2024,
        "url": "https://papers.ssrn.com/sol3/Delivery.cfm/da7cf8bb-5d33-437f-b1d5-1159af31ac37-MECA.pdf?abstractid=6314509",
        "publication_type": "working_paper",
        "strategy_family": "turn-of-the-month seasonality",
        "claim": "The magnitude and prevalence of the turn-of-the-month effect declined over two decades.",
        "sample": "emerging equity markets",
        "reported_net_effect": "clear decline",
        "benchmark": "market",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "the effect still appears sporadically in some indices",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-11",
        "title": "Does the turn-of-the-month (TOM) effect still exist?",
        "authors": ["S. Merelä"],
        "year": 2023,
        "url": "https://aaltodoc.aalto.fi/bitstreams/27ca8cf2-8edd-4ac5-b81f-20b11032661a/download",
        "publication_type": "independent_replication_thesis",
        "strategy_family": "turn-of-the-month seasonality",
        "claim": "Independent replication of TOM on 15 indices finds weakened evidence.",
        "sample": "15 stock indices, 1983-2022",
        "reported_net_effect": "mixed / weakened",
        "benchmark": "market",
        "cost_assumption": "not explicit",
        "post_publication": "DECAYED",
        "counter_evidence": "some sub-periods remain significant",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-12",
        "title": "The Low Volatility Anomaly: contemporary evidence",
        "authors": ["PolQuant (independent research)"],
        "year": 2026,
        "url": "https://polquant.com/en/research/low-volatility-anomaly/",
        "publication_type": "blog_discovery_only",
        "strategy_family": "low volatility anomaly",
        "claim": "Low-volatility stocks show higher risk-adjusted returns in contemporary US data.",
        "sample": "contemporary US equities",
        "reported_net_effect": "positive risk-adjusted spread",
        "benchmark": "market",
        "cost_assumption": "not explicit",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "single-factor implementations often fail after fees",
        "reliability": "low",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-13",
        "title": "Deep Dive: Low-volatility investing — what the latest research says",
        "authors": ["The Evidence-Based Investor"],
        "year": 2026,
        "url": "https://www.evidenceinvestor.com/post/low-volatility-investing",
        "publication_type": "blog_discovery_only",
        "strategy_family": "low volatility anomaly",
        "claim": "Single-factor low-vol approaches fail; the paradox resolves across two halves of the strategy.",
        "sample": "US equities",
        "reported_net_effect": "no reliable single-factor net edge",
        "benchmark": "market",
        "cost_assumption": "not explicit",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "multi-factor combinations may help",
        "reliability": "low",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-14",
        "title": "Keep calm and carry on using minimum volatility index strategies",
        "authors": ["Boriana Iordanova", "UBS Asset Management"],
        "year": 2025,
        "url": "https://www.ubs.com/us/en/assetmanagement/insights/asset-class-perspectives/etf/articles/minimum-volatility-index.html",
        "publication_type": "institutional_research",
        "strategy_family": "minimum volatility index",
        "claim": "Global low-volatility indices outperformed in 2025 after a period of underperformance.",
        "sample": "global low-vol indices",
        "reported_net_effect": "cyclical outperformance",
        "benchmark": "market cap index",
        "cost_assumption": "index level (fees not included)",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "issuer research holds an incentive to favour the product",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-15",
        "title": "The Closed-End Fund Market, 2024",
        "authors": ["Investment Company Institute"],
        "year": 2025,
        "url": "https://www.ici.org/files/2025/per31-04.pdf",
        "publication_type": "official_industry_data",
        "strategy_family": "closed-end fund discount",
        "claim": "CEF assets totalled ~$652bn at year-end 2024; discounts remain structural.",
        "sample": "US closed-end fund industry",
        "reported_net_effect": "persistent discounts/premia",
        "benchmark": "NAV",
        "cost_assumption": "n/a",
        "post_publication": "SURVIVES",
        "counter_evidence": "discounts are not a tradable arbitrage without a catalyst",
        "reliability": "high",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-16",
        "title": "What drives closed-end fund discounts? Evidence from retail trading",
        "authors": ["L. Ma", "et al."],
        "year": 2024,
        "url": "https://ideas.repec.org/a/bla/finmgt/v53y2024i1p119-143.html",
        "publication_type": "peer_reviewed_journal",
        "strategy_family": "closed-end fund discount",
        "claim": "CEFs with higher retail ownership had larger discount increases (sentiment-driven).",
        "sample": "US closed-end funds",
        "reported_net_effect": "discount driven by retail sentiment, not a free arbitrage",
        "benchmark": "NAV",
        "cost_assumption": "not explicit",
        "post_publication": "WEAKENED_BUT_PRESENT",
        "counter_evidence": "mean reversion in pre-2014 samples was documented",
        "reliability": "high",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-17",
        "title": "Retail limit orders",
        "authors": ["A. Anand", "et al."],
        "year": 2026,
        "url": "https://academic.oup.com/rof/article/30/2/459/8277182",
        "publication_type": "peer_reviewed_journal",
        "strategy_family": "retail liquidity provision / market microstructure",
        "claim": "Retail limit orders are informative about execution quality but are adversely selected.",
        "sample": "US equity markets",
        "reported_net_effect": "retail limit orders face adverse selection",
        "benchmark": "market order / effective spread",
        "cost_assumption": "effective spreads",
        "post_publication": "SURVIVES",
        "counter_evidence": "limit orders can capture spread in benign flow",
        "reliability": "high",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-18",
        "title": "The Retail Execution Quality Landscape",
        "authors": ["A. H. Dyhrberg", "et al."],
        "year": 2023,
        "url": "https://www.aeaweb.org/conference/2024/program/paper/5Gtsa7ra",
        "publication_type": "working_paper",
        "strategy_family": "retail execution / market microstructure",
        "claim": "Off-exchange wholesaler executions save retail investors trading costs.",
        "sample": "US retail order flow",
        "reported_net_effect": "cost savings accrue to the wholesaler relationship, not as alpha",
        "benchmark": "exchange execution",
        "cost_assumption": "effective spreads",
        "post_publication": "SURVIVES",
        "counter_evidence": "retail order flow is segmented away from lit liquidity",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-19",
        "title": "A hidden cost of ETF investing: Retail demand shocks and intraday pricing",
        "authors": ["(Journal of Banking & Finance)"],
        "year": 2026,
        "url": "https://www.sciencedirect.com/science/article/pii/S0378426625002419",
        "publication_type": "peer_reviewed_journal",
        "strategy_family": "ETF microstructure",
        "claim": "Intraday ETF price pressure from retail demand shocks is a hidden cost to ETF buyers.",
        "sample": "US ETFs",
        "reported_net_effect": "retail intraday demand creates a cost, not a repeatable edge",
        "benchmark": "NAV",
        "cost_assumption": "intraday price impact",
        "post_publication": "SURVIVES",
        "counter_evidence": "arbitrageurs partially correct the pressure",
        "reliability": "high",
        "retrieval_date": RETRIEVAL_DATE,
    },
    {
        "source_id": "SRC-042-20",
        "title": "Multifactor funds: an early (bearish) assessment",
        "authors": ["Javier Estrada"],
        "year": 2023,
        "url": "https://blog.iese.edu/jestrada/files/2023/06/MultifactorFunds.pdf",
        "publication_type": "working_paper",
        "strategy_family": "multi-factor rotation",
        "claim": "Multifactor funds have, on average, disappointed against simple alternatives.",
        "sample": "multifactor mutual funds/ETFs",
        "reported_net_effect": "no reliable net benefit vs simple passive",
        "benchmark": "market portfolio",
        "cost_assumption": "fund fees",
        "post_publication": "DECAYED",
        "counter_evidence": "factor premia can revive in specific regimes",
        "reliability": "medium",
        "retrieval_date": RETRIEVAL_DATE,
    },
]

# --------------------------------------------------------------------------- #
# §34 — opportunity universe (max 8 screened) + §7 excluded-by-default list
# --------------------------------------------------------------------------- #

OPPORTUNITIES: tuple[radar.Opportunity, ...] = (
    radar.Opportunity(
        opportunity_id="OPP-042-001",
        title="Overnight (close-to-open) equity ETF drift",
        strategy_family="overnight / non-trading-hours return decomposition",
        mechanism="behavioral + institutional constraint",
        trigger="A",
        instrument="EU-retail UCITS equity ETF (fractional)",
        capital_fit="PASS",
        product_fit_200="PASS",
        tradability="PASS",
        data_feasibility="PASS",
        post_publication="CONTRADICTORY",
        implementation_distance="RUNTIME_READY",
        time_to_economic_answer="SHORT",
        source_ids=("SRC-042-01", "SRC-042-04", "SRC-042-05"),
        scores={
            "external_evidence": 4,
            "structural_mechanism": 3,
            "post_publication_survival": 2,
            "business_edge_plausibility": 2,
            "capital_fit_200": 4,
            "tradability": 4,
            "data_feasibility": 5,
            "cost_headroom": 1,
            "implementation_distance": 5,
            "research_expected_value": 2,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-002",
        title="Covered-call / equity index variance-risk-premium UCITS ETF",
        strategy_family="covered call / volatility risk premium product",
        mechanism="structural carry (risk premium)",
        trigger="D",
        instrument="EU-retail UCITS covered-call / equity-premium ETF (EUR)",
        capital_fit="PASS",
        product_fit_200="PASS",
        tradability="PASS",
        data_feasibility="PASS",
        post_publication="DECAYED",
        implementation_distance="SMALL_INTEGRATION",
        time_to_economic_answer="MEDIUM",
        source_ids=("SRC-042-07", "SRC-042-08", "SRC-042-09"),
        scores={
            "external_evidence": 4,
            "structural_mechanism": 4,
            "post_publication_survival": 2,
            "business_edge_plausibility": 2,
            "capital_fit_200": 4,
            "tradability": 4,
            "data_feasibility": 4,
            "cost_headroom": 3,
            "implementation_distance": 4,
            "research_expected_value": 2,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-003",
        title="Turn-of-the-month calendar seasonality",
        strategy_family="calendar seasonality / turn-of-the-month",
        mechanism="forced flow (monthly inflows)",
        trigger="A",
        instrument="EU-retail UCITS equity ETF (fractional)",
        capital_fit="PASS",
        product_fit_200="PASS",
        tradability="PASS",
        data_feasibility="PASS",
        post_publication="DECAYED",
        implementation_distance="RUNTIME_READY",
        time_to_economic_answer="SHORT",
        source_ids=("SRC-042-01", "SRC-042-10", "SRC-042-11"),
        scores={
            "external_evidence": 3,
            "structural_mechanism": 2,
            "post_publication_survival": 1,
            "business_edge_plausibility": 1,
            "capital_fit_200": 4,
            "tradability": 4,
            "data_feasibility": 5,
            "cost_headroom": 3,
            "implementation_distance": 5,
            "research_expected_value": 1,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-004",
        title="Index reconstitution forced-flow (S&P 500 additions/deletions)",
        strategy_family="index reconstitution forced flows",
        mechanism="forced flow (index trackers must trade)",
        trigger="B",
        instrument="US-listed single stocks (shorting deleted names required)",
        capital_fit="LIMITED",
        product_fit_200="LIMITED",
        tradability="FAIL",
        data_feasibility="LIMITED",
        post_publication="DECAYED",
        implementation_distance="MEDIUM_INTEGRATION",
        time_to_economic_answer="MEDIUM",
        source_ids=("SRC-042-06", "SRC-042-04"),
        scores={
            "external_evidence": 4,
            "structural_mechanism": 4,
            "post_publication_survival": 1,
            "business_edge_plausibility": 2,
            "capital_fit_200": 4,
            "tradability": 2,
            "data_feasibility": 3,
            "cost_headroom": 2,
            "implementation_distance": 3,
            "research_expected_value": 1,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-005",
        title="Minimum-volatility / low-volatility UCITS ETF",
        strategy_family="low volatility factor",
        mechanism="risk premium + institutional constraint",
        trigger="D",
        instrument="EU-retail UCITS minimum-volatility ETF (fractional)",
        capital_fit="PASS",
        product_fit_200="PASS",
        tradability="PASS",
        data_feasibility="PASS",
        post_publication="WEAKENED_BUT_PRESENT",
        implementation_distance="RUNTIME_READY",
        time_to_economic_answer="MEDIUM",
        source_ids=("SRC-042-02", "SRC-042-12", "SRC-042-13", "SRC-042-14"),
        scores={
            "external_evidence": 3,
            "structural_mechanism": 3,
            "post_publication_survival": 2,
            "business_edge_plausibility": 2,
            "capital_fit_200": 4,
            "tradability": 4,
            "data_feasibility": 4,
            "cost_headroom": 4,
            "implementation_distance": 4,
            "research_expected_value": 2,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-006",
        title="Closed-end fund discount mean reversion",
        strategy_family="closed-end fund discount",
        mechanism="institutional constraint + liquidity premium",
        trigger="B",
        instrument="US-listed closed-end funds (not PRIIPs-eligible for EU retail)",
        capital_fit="FAIL",
        product_fit_200="FAIL",
        tradability="FAIL",
        data_feasibility="FAIL",
        post_publication="WEAKENED_BUT_PRESENT",
        implementation_distance="MAJOR_BUILD",
        time_to_economic_answer="LONG",
        source_ids=("SRC-042-15", "SRC-042-16"),
        scores={
            "external_evidence": 3,
            "structural_mechanism": 3,
            "post_publication_survival": 2,
            "business_edge_plausibility": 2,
            "capital_fit_200": 1,
            "tradability": 2,
            "data_feasibility": 2,
            "cost_headroom": 1,
            "implementation_distance": 3,
            "research_expected_value": 1,
        },
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-007",
        title="Factor ETF rotation (value/quality/low-vol/momentum)",
        strategy_family="momentum rotation",
        mechanism="risk premium",
        trigger="A",
        instrument="EU-retail UCITS factor ETFs",
        capital_fit="PASS",
        product_fit_200="PASS",
        tradability="PASS",
        data_feasibility="PASS",
        post_publication="DECAYED",
        implementation_distance="RUNTIME_READY",
        time_to_economic_answer="MEDIUM",
        source_ids=("SRC-042-02", "SRC-042-20"),
        rehash_of=("SC-TREND-001", "SC-DUALMOM-002"),
    ),
    radar.Opportunity(
        opportunity_id="OPP-042-008",
        title="Retail liquidity provision via passive limit orders",
        strategy_family="market microstructure / liquidity provision",
        mechanism="liquidity premium",
        trigger="B",
        instrument="US equities / crypto spot (micro-lot)",
        capital_fit="FAIL",
        product_fit_200="FAIL",
        tradability="LIMITED",
        data_feasibility="LIMITED",
        post_publication="SURVIVES",
        implementation_distance="MAJOR_BUILD",
        time_to_economic_answer="LONG",
        source_ids=("SRC-042-17", "SRC-042-18", "SRC-042-19"),
        scores={
            "external_evidence": 3,
            "structural_mechanism": 3,
            "post_publication_survival": 2,
            "business_edge_plausibility": 2,
            "capital_fit_200": 1,
            "tradability": 3,
            "data_feasibility": 3,
            "cost_headroom": 1,
            "implementation_distance": 2,
            "research_expected_value": 1,
        },
    ),
)

#: §7 — families excluded by default; NOT counted in the screened universe.
EXCLUDED_BY_DEFAULT: tuple[dict[str, str], ...] = (
    {
        "family": "crypto TSMOM",
        "reason": "already carries its own evidence (EXT-TSMOM-001/002/003)",
        "reopened": "NO",
    },
    {
        "family": "crypto XMOM",
        "reason": "already carries its own evidence (EXT-XMOM-001)",
        "reopened": "NO",
    },
    {"family": "funding carry", "reason": "already tested and rejected in Phase 1", "reopened": "NO"},
    {"family": "basis", "reason": "already tested and rejected in Phase 1", "reopened": "NO"},
    {
        "family": "positioning",
        "reason": "PIT data certified but no reproducible net edge",
        "reopened": "NO",
    },
    {
        "family": "SC-TREND-001",
        "reason": "VALIDATED_DEFENSIVE, not a profit engine",
        "reopened": "NO",
    },
    {
        "family": "SC-DUALMOM-002",
        "reason": "REJECTED_BUSINESS_EDGE (risk-matched excess < 0)",
        "reopened": "NO",
    },
    {
        "family": "managed futures institutional P1",
        "reason": "MF-TREND-001 fails product-fit for 200 USDT",
        "reopened": "NO",
    },
)

# --------------------------------------------------------------------------- #
# §24-§25 + §10/§15 — narrative detail per screened opportunity
# --------------------------------------------------------------------------- #

DETAIL: dict[str, dict[str, Any]] = {
    "OPP-042-001": {
        "product_fit": {
            "instrument_availability": "UCITS equity ETF available in the EU",
            "eu_retail_access": "yes",
            "priips_ucits": "UCITS with KID",
            "fractional": "yes (several EU brokers)",
            "minimum_quantity": "1 fractional unit",
            "minimum_notional": "~1 EUR at some brokers",
            "fees": "0.05%-0.60% TER, no ticket fee at savings-plan brokers",
            "spread": "~1-3 bps for liquid UCITS ETFs",
            "currency_conversion_cost": "0 for EUR-listed UCITS",
            "short_or_leverage_required": "no",
        },
        "benchmark_case": (
            "Must beat a buy-and-hold UCITS world/equity ETF after ~2 trades/day. "
            "The overnight sleeve gives up the intraday drift and pays a round trip daily, "
            "so the benchmark-adjusted case is negative on the documented evidence."
        ),
        "primary_benchmark": "UCITS MSCI World ETF buy-and-hold (EUR)",
        "risk_matched_benchmark": "risk-matched passive (same ETF scaled to equal volatility)",
        "expected_cost_headroom": "UNKNOWN/WEAK -- daily round trip vs a thin, contested drift",
        "fastest_falsification": (
            "Compute the number of round trips per year required and multiply by the effective "
            "spread; compare with the overnight drift reported in the literature. If the "
            "round-trip cost exceeds the drift for the accessible ETF, kill it immediately "
            "(no backtest of a strategy needed -- a cost arithmetic check)."
        ),
        "why_materially_new": "NO -- the mechanism and its cost failure are already published",
    },
    "OPP-042-002": {
        "product_fit": {
            "instrument_availability": "UCITS covered-call / equity-premium income ETFs exist",
            "eu_retail_access": "yes",
            "priips_ucits": "UCITS with KID",
            "fractional": "yes at several EU brokers",
            "minimum_quantity": "1 fractional unit",
            "minimum_notional": "~1 EUR at some brokers",
            "fees": "~0.25%-0.60% TER on the UCITS wrapper",
            "spread": "~3-8 bps (less liquid than plain equity ETFs)",
            "currency_conversion_cost": "0 for EUR-listed share classes",
            "short_or_leverage_required": "no (embedded option overlay)",
        },
        "benchmark_case": (
            "Must beat the plain equity benchmark on a risk-matched basis. The product caps "
            "upside and pays the VRP as income; with a declining VRP (SRC-042-07) and the "
            "documented bull-market lag (SRC-042-08/09), the benchmark-adjusted case is not "
            "credible before any code."
        ),
        "primary_benchmark": "UCITS MSCI World ETF buy-and-hold (EUR)",
        "risk_matched_benchmark": "volatility-scaled passive equity (risk-matched)",
        "expected_cost_headroom": "UNKNOWN/WEAK -- yield is largely a return of equity beta in disguise",
        "fastest_falsification": (
            "Compare the UCITS covered-call ETF's risk-matched Sharpe and CAGR against the "
            "volatility-scaled plain equity ETF over the same window using free daily NAV "
            "series. If the risk-adjusted excess is not positive, kill it (no strategy code)."
        ),
        "why_materially_new": (
            "PARTIALLY -- UCITS retail access is newer than the legacy US wrappers, but the "
            "declining VRP evidence removes the benchmark-adjusted case"
        ),
    },
    "OPP-042-005": {
        "product_fit": {
            "instrument_availability": "UCITS minimum-volatility ETFs available",
            "eu_retail_access": "yes",
            "priips_ucits": "UCITS with KID",
            "fractional": "yes at several EU brokers",
            "minimum_quantity": "1 fractional unit",
            "minimum_notional": "~1 EUR at some brokers",
            "fees": "~0.20%-0.35% TER",
            "spread": "~2-5 bps",
            "currency_conversion_cost": "0 for EUR-listed share classes",
            "short_or_leverage_required": "no",
        },
        "benchmark_case": (
            "Must beat a plain equity benchmark on a risk-matched basis after fees. With "
            "post-2015 factor crowding (SRC-042-02) and single-factor disappointment "
            "(SRC-042-13), the benchmark-adjusted case is not credibly positive."
        ),
        "primary_benchmark": "UCITS MSCI World ETF buy-and-hold (EUR)",
        "risk_matched_benchmark": "low-vol ETF vs volatility-scaled market ETF",
        "expected_cost_headroom": "UNKNOWN/WEAK -- a factor tilt is not a business edge by itself",
        "fastest_falsification": (
            "Compute the risk-matched excess return of the UCITS minimum-volatility ETF over "
            "the volatility-scaled plain equity ETF using free daily NAV data. No positive "
            "excess over the full available window means kill it."
        ),
        "why_materially_new": "NO -- an old, heavily researched factor tilt aimed at a passive product",
    },
    "OPP-042-003": {
        "product_fit": {
            "instrument_availability": "UCITS equity ETF available",
            "eu_retail_access": "yes",
            "priips_ucits": "UCITS with KID",
            "fractional": "yes",
            "minimum_quantity": "1 fractional unit",
            "minimum_notional": "~1 EUR",
            "fees": "ETF TER only",
            "spread": "~1-3 bps",
            "currency_conversion_cost": "0",
            "short_or_leverage_required": "no",
        },
        "benchmark_case": (
            "The seasonal tilt leaves the investor out of the market for part of each month; "
            "the documented decline of the effect means it cannot credibly beat simple "
            "buy-and-hold on a risk-adjusted basis after costs."
        ),
        "primary_benchmark": "UCITS MSCI World ETF buy-and-hold (EUR)",
        "risk_matched_benchmark": "risk-matched passive (same ETF)",
        "expected_cost_headroom": "UNKNOWN/WEAK -- effect magnitude is comparable to costs",
        "fastest_falsification": (
            "Falsify with free monthly close data: measure the TOM window return net of "
            "costs against the non-TOM window over the last decade. If the difference is "
            "inside the cost band, stop."
        ),
        "why_materially_new": "NO -- a long-known seasonal effect with declining evidence",
    },
    "OPP-042-004": {
        "product_fit": {
            "instrument_availability": "US single stocks; no EU-retail UCITS equivalent",
            "eu_retail_access": "partial (US venue access varies)",
            "priips_ucits": "no UCITS wrapper",
            "fractional": "partial",
            "minimum_quantity": "1 share (or fractional at some brokers)",
            "minimum_notional": "varies",
            "fees": "commission + borrow on the short leg",
            "spread": "widens on event days",
            "currency_conversion_cost": "USD/EUR conversion on every trade",
            "short_or_leverage_required": "YES -- shorting the deleted name",
        },
        "benchmark_case": "Not applicable: the tradable version requires shorting, forbidden for this product.",
        "primary_benchmark": "n/a (short-required)",
        "risk_matched_benchmark": "n/a",
        "expected_cost_headroom": "UNKNOWN/WEAK -- event-day spreads and borrow costs",
        "fastest_falsification": (
            "Check the forced-flow condition: if the accessible index family no longer shows "
            "a tradable abnormal move in the announcement window (SRC-042-06), reject without "
            "any data purchase."
        ),
        "why_materially_new": "NO -- and it violates the no-short product constraint",
    },
    "OPP-042-006": {
        "product_fit": {
            "instrument_availability": "US-listed closed-end funds; not PRIIPs-eligible",
            "eu_retail_access": "NO for EU retail",
            "priips_ucits": "no (US CEFs fall outside PRIIPs KID access)",
            "fractional": "no",
            "minimum_quantity": "1 share",
            "minimum_notional": "varies",
            "fees": "commission + premium/discount execution risk",
            "spread": "wide for many CEFs",
            "currency_conversion_cost": "USD/EUR on every trade",
            "short_or_leverage_required": "no, but leverage is often embedded in the fund",
        },
        "benchmark_case": "Cannot be established for an EU-retail product that cannot be bought.",
        "primary_benchmark": "n/a (product not accessible)",
        "risk_matched_benchmark": "n/a",
        "expected_cost_headroom": "UNKNOWN/WEAK -- discount is not a cost-free arbitrage",
        "fastest_falsification": (
            "Check product access first: if EU-retail distribution is not available, the "
            "opportunity is dead before any data work."
        ),
        "why_materially_new": "NO -- and the product is not accessible to the target investor",
    },
    "OPP-042-008": {
        "product_fit": {
            "instrument_availability": "US equities / crypto spot micro-lots",
            "eu_retail_access": "partial",
            "priips_ucits": "n/a",
            "fractional": "partial",
            "minimum_quantity": "1 unit",
            "minimum_notional": "5 USD/5 USDT at some venues",
            "fees": "maker/taker per venue",
            "spread": "captured only if passive fill is achieved",
            "currency_conversion_cost": "venue dependent",
            "short_or_leverage_required": "no, but adverse selection is the risk",
        },
        "benchmark_case": (
            "Liquidity provision is a cost-reduction / execution-quality topic, not a "
            "benchmark-beating strategy at 200 USDT (SRC-042-17/18/19)."
        ),
        "primary_benchmark": "n/a (execution topic, not a strategy)",
        "risk_matched_benchmark": "n/a",
        "expected_cost_headroom": "UNKNOWN/WEAK -- retail flow is adversely selected",
        "fastest_falsification": (
            "Estimate the passive fill rate and average adverse selection at the target "
            "notional; if expected spread capture is below the fee floor at 200 USDT, stop."
        ),
        "why_materially_new": "NO -- execution quality, not a business edge",
    },
}

DEEP_REVIEW_IDS: tuple[str, ...] = ("OPP-042-002", "OPP-042-005", "OPP-042-001")

#: §26 — the conditions each deep-reviewed opportunity was tested against.
GATE_INPUTS: dict[str, dict[str, Any]] = {
    "OPP-042-002": {
        "credible_mechanism": True,
        "benchmark_adjusted_value_credible": False,
        "fast_falsification_defined": True,
        "materially_new_evidence": False,
        "materially_better_than_archive": False,
    },
    "OPP-042-005": {
        "credible_mechanism": False,
        "benchmark_adjusted_value_credible": False,
        "fast_falsification_defined": True,
        "materially_new_evidence": False,
        "materially_better_than_archive": False,
    },
    "OPP-042-001": {
        "credible_mechanism": False,
        "benchmark_adjusted_value_credible": False,
        "fast_falsification_defined": True,
        "materially_new_evidence": False,
        "materially_better_than_archive": False,
    },
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _render_value(value: Any, indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                out.append(f"{pad}- **{key}**:")
                out.extend(_render_value(item, indent + 1))
            else:
                out.append(f"{pad}- **{key}**: {item}")
        return out
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, sub in item.items():
                    marker = f"{pad}- " if first else f"{pad}  "
                    if isinstance(sub, (dict, list)):
                        out.append(f"{marker}**{key}**:")
                        out.extend(_render_value(sub, indent + 1))
                    else:
                        out.append(f"{marker}**{key}**: {sub}")
                    first = False
            else:
                out.append(f"{pad}- {item}")
        return out
    out.append(f"{pad}{value}")
    return out


def render(title: str, payload: Any) -> str:
    lines = [f"# {title}", ""]
    lines.extend(_render_value(payload, 0))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# entry gate
# --------------------------------------------------------------------------- #


def entry_gate() -> dict[str, Any]:
    head = git(["rev-parse", "HEAD"])
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    ancestors = {name: _is_ancestor(rev, head) for name, rev in EXPECTED_ANCESTORS.items()}
    state_path = REPO / "docs" / "research" / "ECONOMIC_STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    hard_rule_ok = (
        state["alpha_research_freeze"] == "ACTIVE"
        and state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"] == 0
    )
    return {
        "repository": str(REPO),
        "branch": branch,
        "head": head,
        "git_log_15": git(["log", "-15", "--oneline"]).splitlines(),
        "git_status_short": git(["status", "--short"]).splitlines(),
        "expected_ancestors": EXPECTED_ANCESTORS,
        "ancestors_present": ancestors,
        "alpha_research_freeze": state["alpha_research_freeze"],
        "business_validated_edge_count": state["kpi"]["BUSINESS_VALIDATED_EDGE_COUNT"],
        "hard_rule_ok": hard_rule_ok,
        "entry_condition_met": hard_rule_ok and all(ancestors.values()),
    }


def _is_ancestor(rev: str, head: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rev, head],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


# --------------------------------------------------------------------------- #
# scorecard, deep review, decision
# --------------------------------------------------------------------------- #


def scorecard_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for opp in OPPORTUNITIES:
        disp = radar.disposition(opp)
        row: dict[str, Any] = {
            "opportunity_id": opp.opportunity_id,
            "title": opp.title,
            "disposition": disp,
            "trigger": opp.trigger,
            "capital_fit": opp.capital_fit,
            "post_publication": opp.post_publication,
            "source_ids": list(opp.source_ids),
        }
        if opp.scores:
            row["scores"] = dict(opp.scores)
            row["total"] = radar.total_score(opp.scores)
            fails = radar.critical_fails(opp.scores)
            row["critical_fails"] = list(fails)
            row["deep_review_eligible"] = disp == "SCREENED"
        if opp.rehash_of:
            row["rehash_of"] = list(opp.rehash_of)
        rows.append(row)
    return rows


def deep_reviews() -> list[dict[str, Any]]:
    by_id = {o.opportunity_id: o for o in OPPORTUNITIES}
    out: list[dict[str, Any]] = []
    for oid in DEEP_REVIEW_IDS:
        opp = by_id[oid]
        detail = DETAIL[oid]
        out.append(
            {
                "opportunity_id": oid,
                "title": opp.title,
                "scores": dict(opp.scores),
                "total": radar.total_score(opp.scores),
                "critical_fails": list(radar.critical_fails(opp.scores)),
                "supporting_evidence": list(opp.source_ids),
                "counter_evidence": _counter_evidence(oid),
                "mechanism": opp.mechanism,
                "product_fit": detail["product_fit"],
                "benchmark_case": detail["benchmark_case"],
                "primary_benchmark": detail["primary_benchmark"],
                "risk_matched_benchmark": detail["risk_matched_benchmark"],
                "data": f"{opp.data_feasibility} (free daily data sufficient for falsification)",
                "cost": detail["expected_cost_headroom"],
                "fastest_falsification": detail["fastest_falsification"],
                "why_materially_new": detail["why_materially_new"],
                "verdict": "REJECTED_BEFORE_IMPLEMENTATION",
            }
        )
    return out


def _by_id(oid: str) -> radar.Opportunity:
    return next(o for o in OPPORTUNITIES if o.opportunity_id == oid)


def _title(oid: str) -> str:
    return _by_id(oid).title


def _capital_fit(oid: str) -> str:
    return _by_id(oid).capital_fit


def _mechanism(oid: str) -> str:
    return _by_id(oid).mechanism


def _score(oid: str, dimension: str) -> int:
    return int(_by_id(oid).scores[dimension])


def _counter_evidence(oid: str) -> list[str]:
    mapping = {
        "OPP-042-001": ["SRC-042-05 (costs wipe out the anomaly)", "SRC-042-01", "SRC-042-04"],
        "OPP-042-002": ["SRC-042-07 (declining VRP)", "SRC-042-09 (yield is not total return)"],
        "OPP-042-005": ["SRC-042-02 (post-2015 crowding)", "SRC-042-13 (single factor fails)"],
    }
    return mapping[oid]


def reentry_decision() -> dict[str, Any]:
    by_id = {o.opportunity_id: o for o in OPPORTUNITIES}
    verdicts: list[dict[str, Any]] = []
    passing: list[str] = []
    for oid in DEEP_REVIEW_IDS:
        opp = by_id[oid]
        inputs = GATE_INPUTS[oid]
        verdict = radar.gate_business_reentry(
            trigger=opp.trigger,
            materially_new_evidence=bool(inputs["materially_new_evidence"]),
            credible_mechanism=bool(inputs["credible_mechanism"]),
            capital_fit=opp.capital_fit,
            tradability_score=int(opp.scores["tradability"]),
            data_feasibility_score=int(opp.scores["data_feasibility"]),
            headroom=None,
            benchmark_adjusted_value_credible=bool(inputs["benchmark_adjusted_value_credible"]),
            fast_falsification_defined=bool(inputs["fast_falsification_defined"]),
            scores=opp.scores,
            materially_better_than_archive=bool(inputs["materially_better_than_archive"]),
        )
        entry = verdict.as_dict()
        entry["opportunity_id"] = oid
        verdicts.append(entry)
        if verdict.passed:
            passing.append(oid)

    authorized = radar.authorize_single_candidate(passing)
    transition = radar.freeze_transition(authorized)
    return {
        "gate": "G_BUSINESS_REENTRY",
        "result": "PASS" if authorized else "FAIL",
        "authorized_candidate": authorized or "NONE",
        "trigger": "NONE" if authorized is None else by_id[authorized].trigger,
        "per_opportunity_verdicts": verdicts,
        "materially_better_than": list(REFERENCE_REJECTED),
        "transition": transition,
        "tracked_state_update": "NONE" if authorized is None else "REQUIRED",
        "next": "WAIT" if authorized is None else "ONE BUSINESS-QUALIFIED STRATEGY REPRODUCTION",
        "lease": None,
        "profit_kpis": dict(radar.PROFIT_KPIS),
    }


def false_success_audit(decision: dict[str, Any]) -> dict[str, Any]:
    passing = [
        v["opportunity_id"] for v in decision["per_opportunity_verdicts"] if v["G_BUSINESS_REENTRY"] == "PASS"
    ]
    claims = {
        "old_rejected_family_renamed": any(
            bool(o.rehash_of) and radar.disposition(o) == "SCREENED" for o in OPPORTUNITIES
        ),
        "weak_source_treated_as_strong": False,
        "positive_return_treated_as_benchmark_edge": False,
        "product_fit_ignored": any(
            o.product_fit_200 == "FAIL" and radar.disposition(o) == "SCREENED" for o in OPPORTUNITIES
        ),
        "capital_200_constraint_ignored": any(
            o.capital_fit == "FAIL" and radar.disposition(o) == "SCREENED" for o in OPPORTUNITIES
        ),
        "paid_data_requirement_hidden": False,
        "internal_backtest_used_for_selection": False,
        "more_than_one_candidate_authorized": len(passing) > radar.MAX_REENTRY_CANDIDATES,
        "strategy_implemented": False,
        "freeze_released_without_gate_pass": decision["result"] != "PASS"
        and decision["transition"]["research_freeze"] != "ACTIVE",
    }
    return {
        "triggers": list(radar.FALSE_SUCCESS_TRIGGERS),
        "claims": claims,
        "FALSE_SUCCESS": radar.false_success_count(claims),
    }


# --------------------------------------------------------------------------- #
# artifact writers
# --------------------------------------------------------------------------- #


def build_plan(entry: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "title": "BUSINESS OPPORTUNITY RADAR & REENTRY DECISION",
        "reference_capital_usdt": radar.REFERENCE_CAPITAL_USDT,
        "mission": (
            "Search current external evidence, identify whether a materially new "
            "business-qualified opportunity exists, apply G_BUSINESS_REENTRY and return "
            "NO_REENTRY or exactly one reentry-qualified candidate."
        ),
        "not_allowed": [
            "strategy implementation",
            "backtest",
            "parameter search",
            "broker integration",
            "live trading",
            "new agents",
            "continuous daemon",
            "paid data purchase",
        ],
        "budget": {
            "MAX_OPPORTUNITIES_SCREENED": radar.MAX_OPPORTUNITIES_SCREENED,
            "MAX_DEEP_REVIEWS": radar.MAX_DEEP_REVIEWS,
            "MAX_REENTRY_CANDIDATES": radar.MAX_REENTRY_CANDIDATES,
        },
        "excluded_by_default": list(EXCLUDED_BY_DEFAULT),
        "scorecard_dimensions": list(radar.SCORECARD_DIMENSIONS),
        "critical_thresholds": dict(radar.CRITICAL_THRESHOLDS),
        "entry_gate": entry,
    }


def build_final_report(
    entry: dict[str, Any],
    decision: dict[str, Any],
    scorecard: list[dict[str, Any]],
    deep: list[dict[str, Any]],
    false_success: dict[str, Any],
    generated_at: str,
    verification: str,
) -> dict[str, Any]:
    top = deep[0]
    screened_count = sum(1 for r in scorecard if r["disposition"] == "SCREENED")
    return {
        "title": "RFC-042 BUSINESS OPPORTUNITY RADAR",
        "generated_at": generated_at,
        "reference_capital_usdt": radar.REFERENCE_CAPITAL_USDT,
        "research_freeze_at_entry": entry["alpha_research_freeze"],
        "opportunities_screened": len(OPPORTUNITIES),
        "opportunities_scored": screened_count,
        "opportunities_in_universe": len(OPPORTUNITIES),
        "deep_reviewed": len(deep),
        "g_business_reentry": decision["result"],
        "authorized_candidate": decision["authorized_candidate"],
        "trigger": decision["trigger"],
        "why_materially_new": top["why_materially_new"],
        "capital_fit": f"{_capital_fit(top['opportunity_id'])} on the top candidate {top['opportunity_id']}",
        "primary_benchmark": top["primary_benchmark"],
        "risk_matched_benchmark": top["risk_matched_benchmark"],
        "expected_cost_headroom": top["cost"],
        "fastest_falsification": top["fastest_falsification"],
        "kpi": dict(radar.PROFIT_KPIS),
        "research_freeze_at_exit": decision["transition"]["research_freeze"],
        "next_alpha_rfc_allowed": "NO"
        if not decision["transition"]["next_alpha_rfc_allowed"]
        else "ONE_CANDIDATE_ONLY",
        "false_success": false_success["FALSE_SUCCESS"],
        "independent_verification": verification,
        "next": decision["next"],
        "source_commit": entry["head"],
        "final_commit": "",
    }


def final_report_md(report: dict[str, Any]) -> str:
    lines = [
        "RFC-042 BUSINESS OPPORTUNITY RADAR",
        "",
        f"REFERENCE CAPITAL = {report['reference_capital_usdt']:.0f} USDT",
        "",
        f"Research freeze at entry = {report['research_freeze_at_entry']}",
        "",
        f"Opportunities screened = {report['opportunities_screened']}",
        "",
        f"Deep reviewed = {report['deep_reviewed']}",
        "",
        f"G_BUSINESS_REENTRY = {report['g_business_reentry']}",
        "",
        f"Authorized candidate = {report['authorized_candidate']}",
        "",
        f"Trigger = {report['trigger']}",
        "",
        f"Why materially new = {report['why_materially_new']}",
        "",
        f"Capital fit = {report['capital_fit']}",
        "",
        f"Primary benchmark = {report['primary_benchmark']}",
        "",
        f"Risk-matched benchmark = {report['risk_matched_benchmark']}",
        "",
        f"Expected cost headroom = {report['expected_cost_headroom']}",
        "",
        f"Fastest falsification = {report['fastest_falsification']}",
        "",
        f"BUSINESS_VALIDATED_EDGE_COUNT = {report['kpi']['BUSINESS_VALIDATED_EDGE_COUNT']}",
        "",
        f"PAPER_CANDIDATE_COUNT = {report['kpi']['PAPER_CANDIDATE_COUNT']}",
        "",
        f"FORWARD_PROFITABLE_COUNT = {report['kpi']['FORWARD_PROFITABLE_COUNT']}",
        "",
        f"LIVE_PROFITABLE_COUNT = {report['kpi']['LIVE_PROFITABLE_COUNT']}",
        "",
        f"REALIZED_TRADING_PNL = {report['kpi']['REALIZED_TRADING_PNL']}",
        "",
        f"Research freeze at exit = {report['research_freeze_at_exit']}",
        "",
        f"NEXT_ALPHA_RFC_ALLOWED = {report['next_alpha_rfc_allowed']}",
        "",
        f"FALSE_SUCCESS = {report['false_success']}",
        "",
        f"INDEPENDENT_VERIFICATION = {report['independent_verification']}",
        "",
        f"NEXT = {report['next']}",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    generated_at = now_utc()
    entry = entry_gate()
    if not entry["entry_condition_met"]:
        print(
            json.dumps(
                {
                    "ENTRY_GATE": "FAIL",
                    "reason": "hard rule §2 or ancestor check failed",
                    "entry_gate": entry,
                },
                indent=2,
            )
        )
        return 2

    scorecard = scorecard_rows()
    deep = deep_reviews()
    decision = reentry_decision()
    decision["lease"] = None
    false_success = false_success_audit(decision)

    plan = build_plan(entry, generated_at)
    universe = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "screened": [
            {
                "opportunity_id": o.opportunity_id,
                "title": o.title,
                "strategy_family": o.strategy_family,
                "mechanism": o.mechanism,
                "trigger": o.trigger,
                "instrument": o.instrument,
                "capital_fit": o.capital_fit,
                "product_fit_200": o.product_fit_200,
                "post_publication": o.post_publication,
                "implementation_distance": o.implementation_distance,
                "time_to_economic_answer": o.time_to_economic_answer,
                "source_ids": list(o.source_ids),
                "disposition": radar.disposition(o),
            }
            for o in OPPORTUNITIES
        ],
        "screened_count": sum(1 for o in OPPORTUNITIES if radar.disposition(o) == "SCREENED"),
        "excluded_by_default": list(EXCLUDED_BY_DEFAULT),
        "rehash_rejected": [
            o.opportunity_id for o in OPPORTUNITIES if radar.disposition(o) == "REJECTED_SAME_FAMILY_REHASH"
        ],
    }
    product_fit = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "reference_capital_usdt": radar.REFERENCE_CAPITAL_USDT,
        "rows": [
            {
                "opportunity_id": oid,
                "title": _title(oid),
                "capital_fit": _capital_fit(oid),
                **DETAIL[oid]["product_fit"],
            }
            for oid in DEEP_REVIEW_IDS
        ],
    }
    business_case = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "rows": [
            {
                "opportunity_id": oid,
                "mechanism": _mechanism(oid),
                "primary_benchmark": DETAIL[oid]["primary_benchmark"],
                "risk_matched_benchmark": DETAIL[oid]["risk_matched_benchmark"],
                "benchmark_case": DETAIL[oid]["benchmark_case"],
                "expected_cost_headroom": DETAIL[oid]["expected_cost_headroom"],
                "fastest_falsification": DETAIL[oid]["fastest_falsification"],
                "business_edge_plausibility_score": _score(oid, "business_edge_plausibility"),
            }
            for oid in DEEP_REVIEW_IDS
        ],
        "benchmark_predeclared": True,
    }

    write_json(OUT / "RFC042_PLAN.json", plan)
    write_md(OUT / "RFC042_PLAN.md", render("RFC-042 PLAN — BUSINESS OPPORTUNITY RADAR", plan))

    registry = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "retrieval_date": RETRIEVAL_DATE,
        "source_count": len(SOURCES),
        "sources": SOURCES,
        "discovery_only_policy": "blogs and social posts are DISCOVERY ONLY, never gate evidence",
    }
    write_json(OUT / "SOURCE_REGISTRY.json", registry)
    write_md(
        OUT / "SOURCE_REGISTRY.md",
        render("RFC-042 SOURCE REGISTRY", registry),
    )

    write_json(OUT / "OPPORTUNITY_UNIVERSE.json", universe)
    write_md(
        OUT / "OPPORTUNITY_UNIVERSE.md",
        render("RFC-042 OPPORTUNITY UNIVERSE (max 8)", universe),
    )

    scores_doc = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "dimensions": list(radar.SCORECARD_DIMENSIONS),
        "critical_thresholds": dict(radar.CRITICAL_THRESHOLDS),
        "rows": scorecard,
        "deep_review_selected": list(radar.select_deep_reviews(OPPORTUNITIES)),
        "note": "a high total never authorizes reentry; it only buys a DEEP_REVIEW",
    }
    write_json(OUT / "OPPORTUNITY_SCORECARD.json", scores_doc)
    write_md(
        OUT / "OPPORTUNITY_SCORECARD.md",
        render("RFC-042 OPPORTUNITY SCORECARD", scores_doc),
    )

    top3 = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "deep_review_count": len(deep),
        "reviews": deep,
    }
    write_json(OUT / "TOP3_DEEP_REVIEW.json", top3)
    write_md(OUT / "TOP3_DEEP_REVIEW.md", render("RFC-042 TOP-3 DEEP REVIEW", top3))

    write_json(OUT / "PRODUCT_FIT_200.json", product_fit)
    write_md(OUT / "PRODUCT_FIT_200.md", render("RFC-042 PRODUCT FIT @ 200 USDT", product_fit))

    write_json(OUT / "BUSINESS_EDGE_PLAUSIBILITY.json", business_case)
    write_md(
        OUT / "BUSINESS_EDGE_PLAUSIBILITY.md",
        render("RFC-042 BUSINESS EDGE PLAUSIBILITY", business_case),
    )

    write_json(OUT / "REENTRY_DECISION.json", decision)
    write_md(OUT / "REENTRY_DECISION.md", render("RFC-042 REENTRY DECISION", decision))

    verification_doc = {
        "rfc": "RFC-042",
        "generated_at": generated_at,
        "VERIFICATION_STATUS": "PENDING",
        "mismatch_count": None,
        "false_success": false_success["FALSE_SUCCESS"],
    }
    write_json(OUT / "RFC042_VERIFICATION.json", verification_doc)
    write_md(
        OUT / "RFC042_VERIFICATION.md",
        render("RFC-042 VERIFICATION", verification_doc),
    )

    report = build_final_report(
        entry, decision, scorecard, deep, false_success, generated_at, "PENDING"
    )
    write_json(REPORTS / "RFC042_FINAL_REPORT.json", report)
    write_md(REPORTS / "RFC042_FINAL_REPORT.md", final_report_md(report))

    print(
        json.dumps(
            {
                "entry_condition_met": entry["entry_condition_met"],
                "screened": universe["screened_count"],
                "deep_reviewed": len(deep),
                "G_BUSINESS_REENTRY": decision["result"],
                "authorized_candidate": decision["authorized_candidate"],
                "next": decision["next"],
                "FALSE_SUCCESS": false_success["FALSE_SUCCESS"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
