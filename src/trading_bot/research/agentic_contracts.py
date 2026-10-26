"""CAP-001 — agentic market intelligence capability spike (data contracts only).

Governance framing: **CAPABILITY_SPIKE_OUTSIDE_ALPHA_FREEZE**.  This module makes
no alpha claim, defines no strategy, no signal, no backtest, no portfolio model,
no broker, no paper and no live code.  It exists to give the V3 paradigm its
*deterministic shell*: the structured artefacts an LLM analyst produces, the
immutable record of what it decided *before* the outcome was known, and the
evaluator primitives that later measure whether the analyst added value.

``ALPHA_RESEARCH_FREEZE`` stays ``ACTIVE`` and ``NEXT_ALPHA_RFC_ALLOWED`` stays
``NO``.  No RFC-045 is created by this spike.

Authority split (never blurred):

* TradingView MCP -> ``INTELLIGENCE_SOURCE`` (context, never accounting truth),
* reproducible history -> our own datasets,
* fills -> broker/exchange,
* PnL -> portfolio accounting.

Determinism split (deliberate, from the V3 paradigm):

* non-deterministic: market/regime interpretation, opportunity detection,
  news/context reasoning, evidence weighting, trade thesis, NO_TRADE judgment,
  confidence;
* deterministic and never delegated to an LLM: max risk, max exposure, position
  sizing, capital allocation limits, stop constraints, fees, accounting, PnL,
  reconciliation, execution permissions.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# §1 — spike identity and governance framing
# --------------------------------------------------------------------------- #

SPIKE_ID = "CAP-001"
SPIKE_NAME = "AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE"
GOVERNANCE_FRAMING = "CAPABILITY_SPIKE_OUTSIDE_ALPHA_FREEZE"
ALPHA_CLAIMED = "NONE"
TRADES_AUTHORIZED = 0
RFC_CREATED = "NONE"

#: The freeze is untouched by this spike (re-declared, never relaxed here).
ALPHA_RESEARCH_FREEZE = "ACTIVE"
NEXT_ALPHA_RFC_ALLOWED = "NO"
RESEARCH_STATUS = "PAUSED"

# --------------------------------------------------------------------------- #
# §2 — who owns which truth
# --------------------------------------------------------------------------- #

TRADINGVIEW_ROLE = "INTELLIGENCE_SOURCE"
HISTORICAL_AUTHORITY = "OUR_DATASETS"
FILLS_AUTHORITY = "BROKER_OR_EXCHANGE"
PNL_AUTHORITY = "PORTFOLIO_ACCOUNTING"
TRADINGVIEW_IS_ACCOUNTING_SOURCE_OF_TRUTH = False

AUTHORITY_MAP: dict[str, str] = {
    "tradingview": TRADINGVIEW_ROLE,
    "historical_bars": HISTORICAL_AUTHORITY,
    "fills": FILLS_AUTHORITY,
    "pnl": PNL_AUTHORITY,
}

# --------------------------------------------------------------------------- #
# §3 — the determinism split
# --------------------------------------------------------------------------- #

NON_DETERMINISTIC_DOMAINS: tuple[str, ...] = (
    "market_interpretation",
    "regime_interpretation",
    "opportunity_detection",
    "news_context_reasoning",
    "evidence_weighting",
    "trade_thesis",
    "no_trade_judgment",
    "confidence",
)

DETERMINISTIC_DOMAINS: tuple[str, ...] = (
    "max_risk",
    "max_exposure",
    "position_sizing",
    "capital_allocation_limits",
    "stop_constraints",
    "fees",
    "accounting",
    "pnl",
    "reconciliation",
    "execution_permissions",
)

#: The LLM may never emit these; they belong to the deterministic risk gate.
LLM_SIZING_FORBIDDEN = True
LLM_LEVERAGE_FORBIDDEN = True

FORBIDDEN_PROPOSAL_FIELDS: tuple[str, ...] = (
    "size",
    "quantity",
    "qty",
    "leverage",
    "notional",
    "position_size",
    "order_type",
    "order_id",
    "api_key",
    "exchange_order",
)

# --------------------------------------------------------------------------- #
# §4 — MarketSnapshot contract (12 fields)
# --------------------------------------------------------------------------- #

FRESHNESS_LEVELS: tuple[str, ...] = ("FRESH", "AGING", "STALE", "UNKNOWN")
FRESHNESS_FRESH_MAX_SECONDS = 3600
FRESHNESS_AGING_MAX_SECONDS = 86400

MARKET_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "timestamp",
    "asset",
    "price_state",
    "multi_timeframe",
    "technical_state",
    "relative_strength",
    "volume_state",
    "market_regime",
    "news",
    "macro_events",
    "evidence",
    "data_freshness",
)

#: Initial universe (different regimes on purpose).  Not 1000 symbols.
UNIVERSE_V1: tuple[str, ...] = (
    "BINANCE:BTCUSDT",
    "BINANCE:ETHUSDT",
    "SP:SPX",
    "NASDAQ:NDX",
    "TVC:GOLD",
    "TVC:US10Y",
    "FX:EURUSD",
)

TIMEFRAMES_V1: tuple[str, ...] = ("1h", "4h", "1D")
TIMEFRAME_MINUTES: dict[str, int] = {"1h": 60, "4h": 240, "1D": 1440}
FORBIDDEN_TIMEFRAMES_V1: tuple[str, ...] = ("1m", "5m", "15m", "30m")

EVIDENCE_KINDS: tuple[str, ...] = (
    "price_structure",
    "technical",
    "volume",
    "relative_strength",
    "news",
    "macro",
    "fundamental",
)


def freshness_class(age_seconds: int) -> str:
    """Deterministically classify a snapshot age. Never guessed by an LLM."""
    if age_seconds < 0:
        return "UNKNOWN"
    if age_seconds <= FRESHNESS_FRESH_MAX_SECONDS:
        return "FRESH"
    if age_seconds <= FRESHNESS_AGING_MAX_SECONDS:
        return "AGING"
    return "STALE"


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    published: int
    provider: str
    urgency: int
    link: str = ""


@dataclass(frozen=True, slots=True)
class MacroEvent:
    name: str
    country: str
    when: int
    importance: int
    actual: float | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    source: str
    detail: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class PriceState:
    symbol: str
    last: float
    change_pct: float
    bar_interval: str
    bar_count: int


@dataclass(frozen=True, slots=True)
class TimeframeState:
    interval: str
    last: float
    change_pct: float
    trend: str


@dataclass(frozen=True, slots=True)
class TechnicalState:
    rsi: float | None
    macd: float | None
    adx: float | None
    momentum: float | None
    sma50: float | None
    ema200: float | None
    recommendation: str


@dataclass(frozen=True, slots=True)
class VolumeState:
    last: float
    relative: float


@dataclass(frozen=True, slots=True)
class RelativeStrength:
    symbol: str
    reference: str
    value: float


@dataclass(frozen=True, slots=True)
class DataFreshness:
    snapshot_at: int
    newest_source_at: int
    oldest_source_at: int
    age_seconds: int
    level: str
    degraded: bool


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """The single artefact FASE 0 must be able to reconstruct, timestamped."""

    timestamp: int
    asset: str
    price_state: PriceState
    multi_timeframe: tuple[TimeframeState, ...]
    technical_state: TechnicalState
    relative_strength: RelativeStrength
    volume_state: VolumeState
    market_regime: str
    news: tuple[NewsItem, ...]
    macro_events: tuple[MacroEvent, ...]
    evidence: tuple[Evidence, ...]
    data_freshness: DataFreshness

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot_payload(snapshot: MarketSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


def validate_snapshot(snapshot: MarketSnapshot) -> list[str]:
    """Return the list of contract violations (empty list == valid)."""
    problems: list[str] = []
    if snapshot.timestamp <= 0:
        problems.append("timestamp must be a positive unix second value")
    if not snapshot.asset.strip():
        problems.append("asset must not be empty")
    if not snapshot.multi_timeframe:
        problems.append("multi_timeframe must have at least one interval")
    intervals = [tf.interval for tf in snapshot.multi_timeframe]
    if len(intervals) != len(set(intervals)):
        problems.append("multi_timeframe must not repeat an interval")
    for interval in intervals:
        if interval in FORBIDDEN_TIMEFRAMES_V1:
            problems.append(f"interval {interval} is not allowed in V1")
    if snapshot.data_freshness.level not in FRESHNESS_LEVELS:
        problems.append("data_freshness.level is not a known freshness class")
    if snapshot.data_freshness.level != snapshot.data_freshness.level.upper():
        problems.append("data_freshness.level must be upper-case")
    if snapshot.data_freshness.age_seconds < 0:
        problems.append("data_freshness.age_seconds must not be negative")
    for item in snapshot.evidence:
        if item.kind not in EVIDENCE_KINDS:
            problems.append(f"evidence kind {item.kind!r} is not a declared kind")
        if not item.source.strip():
            problems.append("evidence.source must not be empty")
    for event in snapshot.macro_events:
        if event.importance not in (-1, 0, 1):
            problems.append("macro event importance must be -1, 0 or 1")
    return problems


def snapshot_is_usable(snapshot: MarketSnapshot) -> bool:
    """A snapshot is only usable when it is contract-valid and not stale."""
    if validate_snapshot(snapshot):
        return False
    return snapshot.data_freshness.level in ("FRESH", "AGING") and not snapshot.data_freshness.degraded


def market_snapshot_fields() -> tuple[str, ...]:
    return MARKET_SNAPSHOT_FIELDS


# --------------------------------------------------------------------------- #
# §5 — MarketHypothesis contract (11 fields)
# --------------------------------------------------------------------------- #

DIRECTIONS: tuple[str, ...] = ("LONG", "SHORT", "NO_TRADE")

MARKET_HYPOTHESIS_FIELDS: tuple[str, ...] = (
    "asset",
    "horizon",
    "direction",
    "thesis",
    "catalysts",
    "evidence",
    "counter_evidence",
    "invalidation",
    "confidence",
    "expected_holding_period",
    "no_trade_reason",
)


@dataclass(frozen=True, slots=True)
class MarketHypothesis:
    asset: str
    horizon: str
    direction: str
    thesis: str
    catalysts: tuple[str, ...]
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: str
    confidence: float
    expected_holding_period: str
    no_trade_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_hypothesis(hypothesis: MarketHypothesis) -> list[str]:
    problems: list[str] = []
    if hypothesis.direction not in DIRECTIONS:
        problems.append(f"direction {hypothesis.direction!r} is not one of {DIRECTIONS}")
        return problems
    if not hypothesis.asset.strip():
        problems.append("asset must not be empty")
    if not 0.0 <= hypothesis.confidence <= 1.0:
        problems.append("confidence must be within [0, 1]")
    if hypothesis.direction == "NO_TRADE":
        if not hypothesis.no_trade_reason.strip():
            problems.append("NO_TRADE requires an explicit no_trade_reason")
    else:
        if not hypothesis.invalidation.strip():
            problems.append("a directional hypothesis requires an invalidation")
        if not hypothesis.evidence:
            problems.append("a directional hypothesis requires evidence")
    return problems


# --------------------------------------------------------------------------- #
# §6 — TradeProposal contract (no sizing, no leverage, ever)
# --------------------------------------------------------------------------- #

TRADE_PROPOSAL_FIELDS: tuple[str, ...] = (
    "asset",
    "direction",
    "horizon",
    "claim",
    "evidence",
    "counter_evidence",
    "invalidation",
    "confidence",
    "expected_reward_zone",
    "expected_risk_zone",
    "decision_time",
)


@dataclass(frozen=True, slots=True)
class ExpectedZone:
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class TradeProposal:
    asset: str
    direction: str
    horizon: str
    claim: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: str
    confidence: float
    expected_reward_zone: ExpectedZone
    expected_risk_zone: ExpectedZone
    decision_time: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _collect_keys(payload: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            keys.add(str(key))
            keys |= _collect_keys(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            keys |= _collect_keys(item)
    return keys


def forbidden_proposal_keys(payload: Any) -> list[str]:
    """Sizing/leverage/credential keys the LLM must never emit."""
    present = _collect_keys(payload)
    return sorted(key for key in FORBIDDEN_PROPOSAL_FIELDS if key in present)


def proposal_payload_is_safe(payload: Any) -> bool:
    return not forbidden_proposal_keys(payload)


def validate_proposal(proposal: TradeProposal) -> list[str]:
    problems: list[str] = []
    if proposal.direction not in ("LONG", "SHORT"):
        problems.append("a trade proposal must be LONG or SHORT (NO_TRADE is not a proposal)")
    if not 0.0 <= proposal.confidence <= 1.0:
        problems.append("confidence must be within [0, 1]")
    if not proposal.invalidation.strip():
        problems.append("a trade proposal requires an invalidation")
    reward = proposal.expected_reward_zone
    risk = proposal.expected_risk_zone
    if reward.low > reward.high:
        problems.append("expected_reward_zone.low must not exceed high")
    if risk.low > risk.high:
        problems.append("expected_risk_zone.low must not exceed high")
    problems.extend(
        f"proposal must not carry the deterministic field {key!r}"
        for key in forbidden_proposal_keys(proposal.to_dict())
    )
    return problems


# --------------------------------------------------------------------------- #
# §7 — immutable decision record (frozen before the outcome is known)
# --------------------------------------------------------------------------- #

SEALED_RECORD_FIELDS: tuple[str, ...] = (
    "timestamp",
    "prompt_version",
    "evidence_snapshot_hash",
    "agent_output",
    "critic_output",
    "decision",
)


def canonical_json(payload: Any) -> str:
    """Deterministic serialization used for every hash in this module."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_decision_hash(
    *,
    timestamp: int,
    prompt_version: str,
    evidence_snapshot_hash: str,
    agent_output: Any,
    critic_output: Any,
    decision: str,
) -> str:
    sealed = {
        "timestamp": timestamp,
        "prompt_version": prompt_version,
        "evidence_snapshot_hash": evidence_snapshot_hash,
        "agent_output": agent_output,
        "critic_output": critic_output,
        "decision": decision,
    }
    return payload_digest(sealed)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    timestamp: int
    prompt_version: str
    evidence_snapshot_hash: str
    agent_output: Any
    critic_output: Any
    decision: str
    decision_hash: str = ""

    def sealed_payload(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "prompt_version": self.prompt_version,
            "evidence_snapshot_hash": self.evidence_snapshot_hash,
            "agent_output": self.agent_output,
            "critic_output": self.critic_output,
            "decision": self.decision,
        }

    def recomputed_hash(self) -> str:
        return compute_decision_hash(
            timestamp=self.timestamp,
            prompt_version=self.prompt_version,
            evidence_snapshot_hash=self.evidence_snapshot_hash,
            agent_output=self.agent_output,
            critic_output=self.critic_output,
            decision=self.decision,
        )

    def is_verified(self) -> bool:
        return bool(self.decision_hash) and self.decision_hash == self.recomputed_hash()

    def to_dict(self) -> dict[str, Any]:
        payload = self.sealed_payload()
        payload["decision_hash"] = self.decision_hash
        return payload


def seal_decision_record(
    *,
    timestamp: int,
    prompt_version: str,
    evidence_snapshot_hash: str,
    agent_output: Any,
    critic_output: Any,
    decision: str,
) -> DecisionRecord:
    """Freeze a decision *before* the outcome exists (no hindsight editing)."""
    if decision not in DIRECTIONS:
        raise ValueError(f"decision must be one of {DIRECTIONS}, got {decision!r}")
    if not prompt_version.strip():
        raise ValueError("prompt_version must not be empty")
    if not evidence_snapshot_hash.strip():
        raise ValueError("evidence_snapshot_hash must not be empty")
    digest = compute_decision_hash(
        timestamp=timestamp,
        prompt_version=prompt_version,
        evidence_snapshot_hash=evidence_snapshot_hash,
        agent_output=agent_output,
        critic_output=critic_output,
        decision=decision,
    )
    return DecisionRecord(
        timestamp=timestamp,
        prompt_version=prompt_version,
        evidence_snapshot_hash=evidence_snapshot_hash,
        agent_output=agent_output,
        critic_output=critic_output,
        decision=decision,
        decision_hash=digest,
    )


def detect_tampering(records: Sequence[DecisionRecord]) -> list[int]:
    """Indices of records whose sealed hash no longer matches their content."""
    return [index for index, record in enumerate(records) if not record.is_verified()]


def ledger_digest(records: Sequence[DecisionRecord]) -> str:
    return payload_digest([record.to_dict() for record in records])


@dataclass(slots=True)
class DecisionLedger:
    """Append-only store: seals decisions, then measures them, never edits them."""

    records: list[DecisionRecord] = field(default_factory=list)

    def append(self, record: DecisionRecord) -> None:
        if not record.is_verified():
            raise ValueError("refusing to append an unsealed or tampered decision record")
        if any(existing.decision_hash == record.decision_hash for existing in self.records):
            raise ValueError("refusing to append a duplicate decision_hash")
        self.records.append(record)

    def hashes(self) -> tuple[str, ...]:
        return tuple(record.decision_hash for record in self.records)

    def digest(self) -> str:
        return ledger_digest(self.records)


# --------------------------------------------------------------------------- #
# §8 — deterministic evaluator primitives (does the agent add value?)
# --------------------------------------------------------------------------- #

BASELINES: tuple[str, ...] = (
    "A_NO_TRADE",
    "B_BUY_AND_HOLD",
    "C_SIMPLE_TREND",
    "D_PASSIVE_PORTFOLIO",
)

EVALUATION_METRICS: tuple[str, ...] = (
    "net_pnl",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "hit_rate",
    "expectancy",
    "profit_factor",
    "mae",
    "mfe",
    "confidence_calibration",
    "no_trade_value",
)


@dataclass(frozen=True, slots=True)
class IncrementalEdge:
    agent_outcome: float
    baseline_outcome: float
    cost: float
    baseline: str

    @property
    def edge(self) -> float:
        return self.agent_outcome - self.baseline_outcome - self.cost

    @property
    def positive(self) -> bool:
        return self.edge > 0.0


def incremental_edge(
    *,
    agent_outcome: float,
    baseline_outcome: float,
    cost: float,
    baseline: str,
) -> IncrementalEdge:
    if baseline not in BASELINES:
        raise ValueError(f"baseline must be one of {BASELINES}, got {baseline!r}")
    if cost < 0.0:
        raise ValueError("cost must not be negative")
    return IncrementalEdge(
        agent_outcome=agent_outcome,
        baseline_outcome=baseline_outcome,
        cost=cost,
        baseline=baseline,
    )


def hit_rate(returns: Sequence[float]) -> float:
    if not returns:
        raise ValueError("hit_rate needs at least one observation")
    return sum(1 for value in returns if value > 0.0) / len(returns)


def expectancy(returns: Sequence[float]) -> float:
    if not returns:
        raise ValueError("expectancy needs at least one observation")
    return math.fsum(returns) / len(returns)


def profit_factor(returns: Sequence[float]) -> float | None:
    """None when there is no losing observation (undefined, never invented)."""
    wins = math.fsum(value for value in returns if value > 0.0)
    losses = math.fsum(value for value in returns if value < 0.0)
    if losses == 0.0:
        return None
    return wins / abs(losses)


def max_drawdown(equity: Sequence[float]) -> float:
    """Peak-to-trough drawdown as a positive fraction of the running peak."""
    if not equity:
        raise ValueError("max_drawdown needs at least one equity point")
    peak = equity[0]
    worst = 0.0
    for point in equity:
        peak = max(peak, point)
        if peak > 0.0:
            worst = max(worst, (peak - point) / peak)
    return worst


def brier_score(pairs: Sequence[tuple[float, bool]]) -> float:
    """Confidence calibration: mean squared error of stated confidence."""
    if not pairs:
        raise ValueError("brier_score needs at least one (confidence, outcome) pair")
    return math.fsum((confidence - (1.0 if outcome else 0.0)) ** 2 for confidence, outcome in pairs) / len(
        pairs
    )


# --------------------------------------------------------------------------- #
# §9 — gates, budget and the forbidden roadmap
# --------------------------------------------------------------------------- #

GATES: tuple[str, ...] = (
    "G0_TV_CONTEXT",
    "G1_AGENT_HYPOTHESES",
    "G2_CAUSAL_FREEZE",
    "G3_AGENT_EDGE",
    "G4_PORTFOLIO_EDGE",
    "G5_PAPER_EXECUTION",
    "G6_CANARY_200_USDT",
)

GATE_STATUSES: tuple[str, ...] = ("PASS", "FAIL", "NOT_VERIFIED", "NOT_STARTED")

#: G0 cannot be PASS without a credentialled, timestamped real snapshot.
G_TV_CONTEXT = "NOT_VERIFIED"

KPI_DEFINITIONS: dict[str, str] = {
    "STRATEGY_EDGE": "value added by a deterministic strategy rule set",
    "AGENTIC_DECISION_EDGE": "value added by agentic decisions net of an appropriate baseline and cost",
    "PORTFOLIO_EDGE": "marginal contribution of agentic decisions to the whole portfolio",
}

KPI_VALUES: dict[str, int] = {
    "STRATEGY_EDGE": 0,
    "AGENTIC_DECISION_EDGE": 0,
    "PORTFOLIO_EDGE": 0,
}

IMMEDIATE_KPI_TARGET = "AGENTIC_DECISION_EDGE 0 -> 1 (or PORTFOLIO_EDGE 0 -> 1)"

#: Budget before G3 is reached.  Nothing beyond this is funded.
BUDGET_BEFORE_G3: dict[str, int] = {
    "MAX_AI_AGENTS": 2,
    "MAX_TRADINGVIEW_CONNECTORS": 1,
    "MAX_SHADOW_ENGINES": 1,
    "MAX_EVALUATORS": 1,
}

#: TradingView must not become another indicator-combination machine.
FORBIDDEN_DURING_ROADMAP: tuple[str, ...] = (
    "tsmom_campaign",
    "xmom_campaign",
    "rsi_strategy",
    "macd_strategy",
    "mean_reversion",
    "pine_strategy_mining",
    "hyperparameter_optimization",
)

#: Read-only MCP tools the spike may use.  Alerts and watchlist writes are out.
READ_ONLY_MCP_TOOLS: tuple[str, ...] = (
    "get_ohlcv",
    "get_technicals_rating",
    "run_screener",
    "get_symbol_data",
    "get_symbol_data_batch",
    "get_news",
    "get_economic_data",
    "get_economic_calendar",
    "get_dividends_calendar",
    "get_earnings_calendar",
    "search_symbols",
    "list_watchlists",
    "get_watchlist",
)

WRITE_MCP_TOOLS: tuple[str, ...] = (
    "create_alert",
    "update_alert",
    "delete_alert",
    "stop_alerts",
    "restart_alerts",
    "create_watchlist",
    "delete_watchlist",
    "add_to_watchlist",
    "remove_from_watchlist",
    "update_watchlist",
)

MCP_RATE_LIMIT_REQUESTS_PER_MINUTE = 100
MCP_MAX_OHLCV_BARS = 5000

#: Real, documented limits the adapter must respect.
MCP_CONSTRAINTS: dict[str, str] = {
    "auth": "OAuth 2.1 against a paid TradingView account (Essential or above); no API key",
    "transport": "streamable HTTP MCP, consumed by an LLM client (Claude / ChatGPT / Codex)",
    "rate_limit": "~100 requests per minute per user",
    "get_ohlcv_max_bars": "5000",
    "get_technicals_rating": "single timeframe per call; multi_timeframe must be composed",
    "run_screener_max_rows": "1000",
    "create_alert": "simple price conditions only; multi-condition and indicator alerts rejected",
    "webhooks": "cannot be configured through MCP (2FA not available); set up on tradingview.com",
}

FALSE_SUCCESS_TRIGGERS: tuple[str, ...] = (
    "claiming G_TV_CONTEXT = PASS without a credentialled real snapshot",
    "presenting synthetic fixture data as live market data",
    "letting the LLM emit position size or leverage",
    "editing a sealed decision record after the outcome is known",
    "counting an agent win against the wrong baseline",
    "reporting edge without subtracting cost",
    "raising any profit KPI off zero without realized evidence",
    "relaxing the freeze to make the spike look approved",
    "creating an RFC the freeze does not allow",
)
