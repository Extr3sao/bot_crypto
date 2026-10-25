"""RFC-EDGE-009 registration: constants, hypotheses and the decision rules.

Everything a reader needs to judge the package *before* seeing a result is
fixed here: the classification vocabulary, the filter ladder, the frequency
target, the hypotheses with the condition that falsifies each one, and the
holdouts this project has already spent.

The registration is not advisory. ``scripts/edge09_experiments.py`` classifies
each hypothesis with :func:`trading_bot.research.edge09.verdict.classify`, which
imports the thresholds below and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
WP: Final[Path] = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-09"
RFC: Final[Path] = WP / "RFC-EDGE-009.md"

#: The forward microstructure corpora this project already holds. They are
#: *reports* directories by construction (the collector writes there), which is
#: why the estate audit measures them rather than copying them.
CAPTURE_ROOT: Final[Path] = REPO_ROOT / "reports" / "microstructure-forward-continuous"

#: Authoritative inputs this package READS and never writes.
RISK_CONFIG: Final[Path] = REPO_ROOT / "config" / "risk.yaml"
RUNTIME_CONFIG: Final[Path] = REPO_ROOT / "config" / "runtime.yaml"
COST_MODEL_V3: Final[Path] = REPO_ROOT / "docs" / "COST_MODEL_V3.json"
COST_MODEL_V4: Final[Path] = REPO_ROOT / "docs" / "EXECUTION_COST_MODEL_V4.json"
FORWARD_CONTRACT: Final[Path] = REPO_ROOT / "docs" / "FORWARD_DATA_CONTRACT.json"
SOURCE_REGISTRY: Final[Path] = REPO_ROOT / "docs" / "source_registry.md"

SCHEMA_VERSION: Final[str] = "EDGE09_V1"

#: The decision grid. One second is the coarsest clock at which the captured
#: quote stream is still a *microstructure* measurement and the finest clock at
#: which a retail taker order could plausibly be routed by this runtime.
GRID_SECONDS: Final[int] = 1

#: Forward horizons, in seconds, at which a mid move is measured. 1 s is the
#: fastest a routed taker order could be followed by its own exit; 60 s is the
#: slowest that is still microstructure rather than trend.
HORIZONS_SECONDS: Final[tuple[int, ...]] = (1, 5, 60)

#: Horizons the *frequency* bound is evaluated at. The bound must answer the
#: question the ACTIVE objective asks — "can any hold clear the barrier, and how
#: often" — so it has to include holds longer than the microstructure window,
#: otherwise a zero would only describe the shortest clock.
FREQUENCY_HORIZONS_SECONDS: Final[tuple[int, ...]] = (1, 5, 60, 900, 3600)

#: Minimum independent observations for a cell to be reported as measured.
MIN_OBSERVATIONS: Final[int] = 500

#: A candidate must clear the round trip by this multiple to be admitted,
#: exactly as the frozen cost model V4 requires.
MIN_GROSS_SAFETY_MULTIPLE: Final[float] = 1.5

#: The ACTIVE track's registered frequency objective, in EXECUTED trades per
#: day across the aggregate universe. Taken from the brief; it is an objective,
#: not an entitlement: no trade is forced to reach it.
ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY: Final[float] = 3.0

#: The QUALITY track trades on a slower clock and is judged separately.
QUALITY_FREQUENCY_FLOOR_TRADES_PER_DAY: Final[float] = 0.05

#: Aggregate universe of this package: the three assets every earlier package
#: has read, measured here on a *new modality* (quote/depth/flow, forward).
UNIVERSE: Final[tuple[str, ...]] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MARKETS: Final[tuple[str, ...]] = ("spot", "perp")

#: Holdouts this project has already spent. A hypothesis of this package is not
#: allowed to be evaluated on any of them; the audit states the overlap that
#: does exist (different modality, same calendar) rather than hiding it.
CONSUMED_HOLDOUTS: Final[tuple[dict[str, str], ...]] = (
    {
        "holder": "WP-EDGE-07",
        "what": "the pre-registered decisive window of the EDGE-07 thrust book",
        "evidence": "reports/edge-recovery/WP-EDGE-07/validation/VALIDATION.json",
    },
    {
        "holder": "WP-EDGE-08",
        "what": "a cross-section of six symbols never measured before",
        "symbols": "AAVEUSDT, UNIUSDT, KSMUSDT, SNXUSDT, CRVUSDT, SUSHIUSDT",
        "window": "2025-01-01..2026-10-14 (the decisive window, bars 1h/4h/1d)",
        "evidence": "reports/edge-recovery/WP-EDGE-08/validation/VALIDATION.json",
    },
)

#: The complete vocabulary a hypothesis may end in. ``ADMIT_RESEARCH`` is the
#: only positive one and it still does not authorise paper or live trading.
CLASSIFICATIONS: Final[tuple[str, ...]] = (
    "ADMIT_RESEARCH",
    "COST_KILLED",
    "FREQUENCY_KILLED",
    "CAPACITY_KILLED",
    "NO_GROSS_EDGE",
    "NO_INFORMATION",
    "INSUFFICIENT_SAMPLE",
    "LIMITED_HISTORY",
    "NO_VIABLE_DATA",
    "NON_EXECUTABLE_UNDER_RUNTIME",
    "OBSERVED",
)

#: Filter ladder, applied in order. A hypothesis that fails a filter is
#: classified and reported there; it is not re-parameterised and re-run.
LADDER: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "F0",
        "name": "information",
        "rule": "the feature must order the forward return (|Spearman IC| >= 0.01, n >= 500)",
    },
    {
        "id": "F1",
        "name": "gross edge",
        "rule": "mean gross move in bps must be positive on the pooled sample",
    },
    {
        "id": "F2",
        "name": "cost survival",
        "rule": "mean gross >= the measured round-trip cost of the venue/asset, in bps",
    },
    {
        "id": "F3",
        "name": "admission margin",
        "rule": "mean gross >= 1.5 x round-trip cost (the frozen safety multiple)",
    },
    {
        "id": "F4",
        "name": "capacity",
        "rule": "the measured book must absorb the order size inside the barrier; failing it is CAPACITY_KILLED",
    },
    {
        "id": "F5",
        "name": "frequency",
        "rule": "the structure must offer >= 3 executed opportunities per day (ACTIVE); failing it is FREQUENCY_KILLED",
    },
)

#: Cost scenarios compared, all authoritative (V3 venue spec ids). The first is
#: the frozen admission scenario; the others exist to test whether the *fee
#: schedule* is the binding constraint rather than the signal.
SCENARIOS_COMPARED: Final[tuple[str, ...]] = (
    "BINANCE_SPOT_STANDARD_TAKER",
    "MEXC_SPOT_TAKER",
    "OKX_SPOT_TAKER",
    "KRAKENPRO_SPOT_TAKER",
)


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """One falsifiable economic hypothesis, with the rule that kills it."""

    id: str
    track: str
    title: str
    statement: str
    falsified_if: str
    data_requirement: str
    decided_at: str
    executable: bool
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "track": self.track,
            "title": self.title,
            "statement": self.statement,
            "falsified_if": self.falsified_if,
            "data_requirement": self.data_requirement,
            "decided_at": self.decided_at,
            "executable": self.executable,
            "note": self.note,
        }


HYPOTHESES: Final[tuple[Hypothesis, ...]] = (
    Hypothesis(
        id="E-01",
        track="ACTIVE",
        title="quote imbalance is big enough to pay a taker round trip",
        statement=(
            "the book's own imbalance (bid vs ask size at the touch, and its change) "
            "predicts the mid move over 1/5/60 s by more than the venue's round-trip "
            "taker cost, so the prediction is executable by a taker order"
        ),
        falsified_if=(
            "the best measured mean gross move at any horizon is below the measured "
            "round-trip cost for that asset"
        ),
        data_requirement="forward book_ticker at quote level (no historical substitute exists)",
        decided_at="F2/F3 (cost survival, admission margin)",
        executable=True,
    ),
    Hypothesis(
        id="E-02",
        track="CROSS-VENUE",
        title="the fee schedule is the binding constraint, not the signal",
        statement=(
            "the same measured gross move clears the barrier at a venue whose taker "
            "fee is lower, so the venue choice (not the model) is what blocks the edge"
        ),
        falsified_if=(
            "no compared venue brings the round-trip cost at or below the measured "
            "gross move, including the venue with the lowest researched taker fee"
        ),
        data_requirement="measured spread + the published fee schedules already registered",
        decided_at="F2 (cost survival) with V3 venue scenarios",
        executable=False,
        note="a venue change is a governance decision; this measures, it does not adopt",
    ),
    Hypothesis(
        id="E-03",
        track="ACTIVE",
        title="the measured book can absorb our order size inside the barrier",
        statement=(
            "at the registered order size the captured book offers enough notional "
            "inside the barrier-implied impact, so the modelled cost is not a fiction"
        ),
        falsified_if=(
            "the notional available within the barrier-implied price band is below the "
            "runtime's minimum order notional"
        ),
        data_requirement="forward depth snapshots (10 levels) per symbol and market",
        decided_at="F4 (capacity)",
        executable=True,
    ),
    Hypothesis(
        id="E-04",
        track="QUALITY",
        title="open interest with price is exploitable on a slower clock",
        statement=(
            "the quadrant 'price down and open interest up' carries a positive forward "
            "move large enough to pay the round trip at a 5-minute horizon"
        ),
        falsified_if=(
            "no quadrant cell reaches a positive mean gross move at or above the "
            "round-trip cost, or the sample is below the registered floor"
        ),
        data_requirement="forward open interest + mid at 5-minute resolution",
        decided_at="F1/F2 with an explicit sample floor",
        executable=True,
    ),
    Hypothesis(
        id="E-05",
        track="ACTIVE",
        title="three executed trades a day is reachable by a positive structure",
        statement=(
            "a structure whose expected move clears the barrier occurs at least three "
            "times a day across the aggregate universe, so the ACTIVE objective is a "
            "strategy question and not an arithmetic impossibility"
        ),
        falsified_if=(
            "the measured count of barrier-clearing opportunities per day is below the "
            "registered 3.0, no trade being forced to reach it"
        ),
        data_requirement="the same quote panel, counted without a performance filter",
        decided_at="F5 (frequency), on the pooled universe",
        executable=True,
    ),
    Hypothesis(
        id="E-06",
        track="EXECUTION",
        title="a taker entry pays no more than the measured spread and impact",
        statement=(
            "the price a taker order actually pays, measured against the mid at the "
            "decision instant, matches the modelled spread plus impact component, so "
            "the cost model is not systematically optimistic"
        ),
        falsified_if=(
            "the measured execution shortfall exceeds the modelled spread+impact "
            "component by more than the published tolerance"
        ),
        data_requirement="forward tape (agg_trade with aggressor side) + book_ticker",
        decided_at="measured, then compared to the model; not an admission filter",
        executable=True,
    ),
    Hypothesis(
        id="E-07",
        track="GUARD",
        title="negative control: the pipeline does not manufacture an edge",
        statement=(
            "the identical pipeline, fed a feature destroyed by a deterministic shuffle "
            "inside each day, produces no cost-surviving edge"
        ),
        falsified_if=(
            "the negative control reaches the positive classification, which would "
            "invalidate every other result in this package"
        ),
        data_requirement="the same panel",
        decided_at="must end COST_KILLED or NO_GROSS_EDGE or NO_INFORMATION",
        executable=False,
        note="FALSE_SUCCESS guard: a positive control here stops the package",
    ),
)

#: Measured spreads published by earlier phases, used only as a cross-check of
#: this package's own measurement. They are NOT used as the measurement.
PRIOR_SPREAD_CROSSCHECK_BPS: Final[dict[str, float]] = {
    "BTCUSDT": 0.001,
    "ETHUSDT": 0.004,
    "SOLUSDT": 0.84,
}

WHAT_THIS_CANNOT_SAY: Final[tuple[str, ...]] = (
    "profitability of any book: promotion is NONE and no order is sent",
    "anything about liquidity outside the 4.16 h the forward capture covers",
    "anything about the perp trade flow: this environment delivered zero perp aggTrade "
    "messages (SRC-15/SRC-18) and the absence is declared, never substituted",
    "anything about realised maker fills: no venue in this project has a measured fill model",
    "anything about markets the runtime excludes (derivatives are information, not product)",
)
