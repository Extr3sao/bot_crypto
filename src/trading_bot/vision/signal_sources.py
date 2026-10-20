"""signal_sources — where a paper decision comes from, behind an explicit switch.

RFC-TA-EXP-003J-001 found that the prospective PAPER session had exactly one signal
source: ``PaperScriptProvider``, which rotates ``LONG / NO_TRADE / SHORT / NO_TRADE`` on a
global counter. That generator cannot say anything about the market, so a session fed by
it cannot distinguish "no opportunity" from "no signal" from "blocked by the book".

This module adds a **second, opt-in** source and nothing else:

``legacy_parity``
    The existing ``PaperScriptProvider``. It stays the default, it stays the object that
    runs when nobody asks for anything, and its rotation is untouched.

``strategy_experimental``
    :class:`StrategySignalProvider`, which reads the **same bars the lane is deciding on**
    and asks the runtime-authoritative ``EmaCrossoverFamily`` for a direction per asset.
    It answers in the decision contract the lane already parses, so risk, sizing, fees,
    exits, the broker and the accounting are the code paths they always were.

Four properties are structural rather than promised:

* **PAPER only.** The adapter refuses to be constructed for any other mode, so a live
  caller cannot reach it even by mistake.
* **No parity fallback.** Every failure produces a typed ``NO_TRADE`` — never a scripted
  action. A broken feed cannot quietly become a signal.
* **Point in time by construction.** The window is cut at the bar the lane's *chart* says
  it closed on, and a window whose last bar had not closed by ``decision_ts_ms`` is
  refused rather than trimmed.
* **One state per (asset, strategy, timeframe).** The family is stateless and the adapter
  keeps no cross-asset cache, so the answer for BTC cannot depend on whether ETH was
  evaluated first. A permutation test in ``tests/unit/vision/test_signal_sources.py``
  holds that to account.

What this module deliberately does not add: an order, a size, a leverage, a stop policy,
a take-profit policy, a second ledger. The family's structural stop is reported, and the
lane's ``RiskManager`` remains the only thing that decides the levels actually used.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from trading_bot.indicators.builtin import AtrIndicator, EmaIndicator, RsiIndicator
from trading_bot.indicators.exceptions import IndicatorError
from trading_bot.indicators.types import IndicatorResult
from trading_bot.market_data.types import OHLCV
from trading_bot.research.families.breakout_family import BreakoutFamily
from trading_bot.research.families.ema_crossover_family import EmaCrossoverFamily
from trading_bot.research.families.mean_reversion_family import MeanReversionFamily
from trading_bot.research.families.momentum_family import MomentumFamily
from trading_bot.research.families.trend_family import TrendFamily
from trading_bot.research.families.volatility_family import VolatilityFamily
from trading_bot.vision.clock import bar_close_ms, information_ms
from trading_bot.vision.provider import VisionRequest, VisionResponse

SIGNAL_SOURCE_LEGACY: Final = "legacy_parity"
SIGNAL_SOURCE_STRATEGY: Final = "strategy_experimental"
SIGNAL_SOURCES: Final = (SIGNAL_SOURCE_LEGACY, SIGNAL_SOURCE_STRATEGY)

#: The strategy the canonical PAPER runtime executes through ``StrategyRouter``
#: (RUN-OP-003 / RUN-OP-004); the older ``EmaCrossoverStrategy`` class is TEST_ONLY and is
#: deliberately not reachable here.
STRATEGY_EMA_CROSSOVER: Final = "ema_crossover"

#: 003K: the other AlphaFamilies that already exist in ``research/families``. They are
#: admitted to the **experimental** paper source only after being selected on a research
#: window; their classification says so, and none of them is the default.
STRATEGY_MOMENTUM: Final = "momentum"
STRATEGY_BREAKOUT: Final = "breakout"
STRATEGY_MEAN_REVERSION: Final = "mean_reversion"
STRATEGY_TREND: Final = "trend"
STRATEGY_VOLATILITY: Final = "volatility"


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """What the adapter needs to know about one admitted family.

    ``min_candles`` is the family's own guard, copied here so the adapter can refuse the
    window *before* asking a family that would answer "no signal" — an empty list from a
    starved family and an empty list from a quiet market must not look the same.
    """

    strategy_id: str
    family_cls: type
    family_name: str
    min_candles: int
    invalidation: str
    indicator_kind: str
    classification: str


STRATEGY_SPECS: Final[dict[str, StrategySpec]] = {
    STRATEGY_EMA_CROSSOVER: StrategySpec(
        strategy_id=STRATEGY_EMA_CROSSOVER,
        family_cls=EmaCrossoverFamily,
        family_name="ema_crossover",
        min_candles=22,
        invalidation="fast EMA crosses back against the position",
        indicator_kind="ema_rsi_atr",
        classification="RUNTIME_REACHABLE",
    ),
    STRATEGY_MOMENTUM: StrategySpec(
        strategy_id=STRATEGY_MOMENTUM,
        family_cls=MomentumFamily,
        family_name="momentum",
        min_candles=36,
        invalidation="MACD histogram changes sign or momentum falls below its threshold",
        indicator_kind="family_native",
        classification="EXPERIMENTAL_PAPER",
    ),
    STRATEGY_BREAKOUT: StrategySpec(
        strategy_id=STRATEGY_BREAKOUT,
        family_cls=BreakoutFamily,
        family_name="breakout",
        min_candles=21,
        invalidation="close returns inside the Donchian channel",
        indicator_kind="family_native",
        classification="EXPERIMENTAL_PAPER",
    ),
    STRATEGY_MEAN_REVERSION: StrategySpec(
        strategy_id=STRATEGY_MEAN_REVERSION,
        family_cls=MeanReversionFamily,
        family_name="mean_reversion",
        min_candles=22,
        invalidation="close re-enters the band on the wrong side or the band expands",
        indicator_kind="family_native",
        classification="EXPERIMENTAL_PAPER",
    ),
    STRATEGY_TREND: StrategySpec(
        strategy_id=STRATEGY_TREND,
        family_cls=TrendFamily,
        family_name="trend",
        min_candles=56,
        invalidation="EMA ribbon loses its stack or the slow slope flips",
        indicator_kind="family_native",
        classification="EXPERIMENTAL_PAPER",
    ),
    STRATEGY_VOLATILITY: StrategySpec(
        strategy_id=STRATEGY_VOLATILITY,
        family_cls=VolatilityFamily,
        family_name="volatility",
        min_candles=27,
        invalidation="close returns inside the Bollinger band",
        indicator_kind="family_native",
        classification="EXPERIMENTAL_PAPER",
    ),
}

SUPPORTED_STRATEGIES: Final = tuple(STRATEGY_SPECS)

#: The family computes these itself when handed no indicators. The adapter computes the
#: same four inside the PIT window so the trace can carry the numbers the decision used,
#: and a test asserts the two dicts agree cell by cell.
INDICATOR_PARAMS: Final[dict[str, int]] = {
    "ema_fast": 9,
    "ema_slow": 21,
    "rsi": 14,
    "atr": 14,
}

#: Below this many candles the family refuses to produce a signal (its own guard). The
#: adapter reports that as a typed NO_TRADE instead of letting an empty list look like
#: a market opinion. Kept as the EMA value for callers that predate the registry.
MIN_CANDLES: Final = 22


def min_candles_for(strategy_id: str) -> int:
    """The family's own minimum, or a refusal for an id that is not admitted."""

    spec = STRATEGY_SPECS.get(str(strategy_id))
    if spec is None:
        raise SignalSourceConfigError(
            f"strategy {strategy_id!r} is not admitted to this adapter; "
            f"allowed: {sorted(SUPPORTED_STRATEGIES)}"
        )
    return spec.min_candles

#: The family exposes no calibrated conviction. Sending a fixed score keeps the two arms
#: comparable on the one field ``PositionSize`` echoes, and the report says so rather than
#: dressing a rule margin up as a probability.
DECLARED_CONFIDENCE: Final = 0.5

PAPER_MODE: Final = "PAPER"

TRACE_SCHEMA: Final = "AI_BOTS_003J_SIGNAL_TRACE_V1"


class SignalSourceConfigError(ValueError):
    """A signal source that may not run: unknown name, wrong mode, wrong strategy."""


class SignalBlocked(RuntimeError):
    """A decision that could not be formed from data. ``code`` is stable and countable."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round(value: float) -> float:
    return round(float(value), 8)


def _as_float(value: IndicatorResult) -> float:
    """Narrow one indicator value to a number, or refuse the malformed shape.

    ``IndicatorResult`` allows a list or a dict because some indicators return series.
    The four this adapter computes are scalars; a non-scalar would mean the wrong
    indicator was wired in, which is a rejection rather than a silent ``float()`` on a
    list.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignalBlocked(
            "INDICATOR_NOT_SCALAR", f"expected a scalar indicator, got {type(value).__name__}"
        )
    return float(value)


@dataclass(frozen=True, slots=True)
class PitWindow:
    """The exact bars a decision may read, and the fingerprint of those bars."""

    symbol: str
    bars: tuple[Any, ...]
    last_open_ms: int
    last_close_ms: int
    digest: str

    @property
    def max_input_data_time_ms(self) -> int:
        return int(self.last_close_ms)

    def candles(self) -> list[OHLCV]:
        """The window as the strategy's own input type, in chronological order."""

        return [
            OHLCV(
                symbol=self.symbol,
                timestamp=int(bar.ts_ms),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in self.bars
        ]


def _digest(bars: Sequence[Any]) -> str:
    payload = json.dumps(
        [
            [
                int(bar.ts_ms),
                _round(bar.open),
                _round(bar.high),
                _round(bar.low),
                _round(bar.close),
                _round(bar.volume),
            ]
            for bar in bars
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def point_in_time_window(
    series: Mapping[str, Sequence[Any]],
    symbol: str,
    *,
    last_open_ms: int,
    interval_ms: int,
    decision_ts_ms: int,
    limit: int,
) -> PitWindow:
    """Cut the window at the bar the decision is about.

    ``last_open_ms`` is the chart's own last bar, not an argument the caller may soften:
    the bars after it did not exist when the picture was drawn, so they are dropped. The
    window also refuses a bar whose close had not reached the decision instant — that is
    the look-ahead this function exists to prevent, and trimming it would hide the defect
    rather than refuse it.
    """

    bars = series.get(symbol)
    if not bars:
        raise SignalBlocked("ASSET_NOT_IN_SERIES", f"{symbol} has no bars in this run")
    if int(interval_ms) <= 0:
        raise SignalBlocked("BAD_INTERVAL", f"interval {interval_ms} is not a duration")
    usable = [bar for bar in bars if int(bar.ts_ms) <= int(last_open_ms)]
    if not usable:
        raise SignalBlocked(
            "WINDOW_EMPTY", f"{symbol}: no bar at or before {_utc(int(last_open_ms))}"
        )
    if int(usable[-1].ts_ms) != int(last_open_ms):
        raise SignalBlocked(
            "DECISION_BAR_NOT_IN_SERIES",
            f"{symbol}: the chart closed on {_utc(int(last_open_ms))} but the series has no "
            f"such bar (last is {_utc(int(usable[-1].ts_ms))})",
        )
    if information_ms(int(last_open_ms), int(interval_ms), 0) > int(decision_ts_ms):
        raise SignalBlocked(
            "BAR_CLOSED_AFTER_DECISION",
            f"{symbol}: the bar closing at {_utc(bar_close_ms(int(last_open_ms), int(interval_ms)))} "
            f"cannot inform a decision stamped {_utc(int(decision_ts_ms))}",
        )
    window = tuple(usable[-int(limit) :]) if int(limit) > 0 else tuple(usable)
    return PitWindow(
        symbol=symbol,
        bars=window,
        last_open_ms=int(last_open_ms),
        last_close_ms=bar_close_ms(int(last_open_ms), int(interval_ms)),
        digest=_digest(window),
    )


def compute_indicators(candles: Sequence[OHLCV]) -> dict[str, IndicatorResult]:
    """The four indicators the family consumes, computed over the PIT window only."""

    return {
        "ema_fast": EmaIndicator().compute(candles, {"period": INDICATOR_PARAMS["ema_fast"]}),
        "ema_slow": EmaIndicator().compute(candles, {"period": INDICATOR_PARAMS["ema_slow"]}),
        "rsi": RsiIndicator().compute(candles, {"period": INDICATOR_PARAMS["rsi"]}),
        "atr": AtrIndicator().compute(candles, {"period": INDICATOR_PARAMS["atr"]}),
    }


def _strategy_version(family_cls: type = EmaCrossoverFamily) -> str:
    """A version that is a hash of the code, not a number somebody remembered to bump."""

    try:
        path = inspect.getsourcefile(family_cls)
    except (TypeError, OSError):  # pragma: no cover - frozen interpreter
        return "UNKNOWN"
    if not path:
        return "UNKNOWN"
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest[:16]}"


@dataclass
class StrategySignalProvider:
    """``VisionProvider``-shaped adapter over one admitted AlphaFamily.

    It answers with the decision contract the lane already parses, so nothing downstream
    has to learn a new shape. ``image_sha256_in_request`` is deliberately empty: this
    adapter reads numbers, and claiming an attached chart would be a false receipt.

    The family is chosen by ``strategy_id`` from :data:`STRATEGY_SPECS`; the default is the
    EMA family that 003J proved, and every other family declares itself
    ``EXPERIMENTAL_PAPER`` in the trace until it has its own evidence.
    """

    series: Mapping[str, Sequence[Any]]
    timeframe: str
    interval_ms: int
    window_bars: int
    strategy_id: str = STRATEGY_EMA_CROSSOVER
    mode: str = PAPER_MODE
    trace_path: Path | None = None
    family: Any = None
    name: str = "strategy-signal"
    model: str = "strategy-signal/1"
    calls: int = 0
    no_trade: int = 0
    blocked: int = 0
    strategy_version: str = ""
    spec: StrategySpec = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if str(self.mode).upper() != PAPER_MODE:
            raise SignalSourceConfigError(
                f"strategy_experimental is PAPER only; mode {self.mode!r} is refused before "
                "any decision is formed"
            )
        spec = STRATEGY_SPECS.get(str(self.strategy_id))
        if spec is None:
            raise SignalSourceConfigError(
                f"strategy {self.strategy_id!r} is not admitted to this adapter; "
                f"allowed: {sorted(SUPPORTED_STRATEGIES)}"
            )
        self.spec = spec
        if int(self.interval_ms) <= 0:
            raise SignalSourceConfigError("interval_ms must be positive")
        if int(self.window_bars) < spec.min_candles:
            raise SignalSourceConfigError(
                f"window_bars must be >= {spec.min_candles} for {spec.family_name}: "
                "the family refuses fewer candles"
            )
        if self.family is None:
            self.family = spec.family_cls()
        self.model = f"{spec.family_name}@strategy-signal/1"
        if not self.strategy_version:
            self.strategy_version = _strategy_version(type(self.family))

    # -- trace ---------------------------------------------------------------

    def _trace(self, row: Mapping[str, Any]) -> None:
        if self.trace_path is None:
            return
        path = Path(self.trace_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(row), sort_keys=True, default=str) + "\n")

    # -- decision ------------------------------------------------------------

    def _response(self, payload: Mapping[str, Any]) -> VisionResponse:
        self.calls += 1
        return VisionResponse(
            text=json.dumps(payload, separators=(",", ":"), sort_keys=True),
            model=self.model,
            provider=self.name,
            request_id=f"strategy-{self.calls:06d}",
            latency_ms=0,
            attempts=1,
            image_sha256_in_request="",
        )

    def _no_trade(
        self,
        *,
        request: VisionRequest,
        symbol: str,
        reason: str,
        detail: str,
        quality: str = "REJECT",
        extra: Mapping[str, Any] | None = None,
    ) -> VisionResponse:
        """A typed refusal. It is a decision, not a fallback to the scripted rotation."""

        self.no_trade += 1
        if quality == "REJECT":
            self.blocked += 1
        payload = {
            "schema_version": "ai-vision-decision/1",
            "symbol": symbol,
            "action": "NO_TRADE",
            "confidence": DECLARED_CONFIDENCE,
            "horizon_bars": 1,
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "invalidation": None,
            "rationale": f"{reason}: {detail}"[:600],
        }
        self._trace(
            {
                "schema_version": TRACE_SCHEMA,
                "provider": self.name,
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "strategy_classification": self.spec.classification,
                "asset": symbol,
                "timeframe": self.timeframe,
                "decision_time_ms": int(request.decision_ts_ms),
                "decision_time_utc": _utc(int(request.decision_ts_ms)),
                "max_input_data_time_ms": None,
                "max_input_data_time_utc": None,
                "market_data_fingerprint": None,
                "chart_sha256": request.chart.sha256,
                "action": "NO_TRADE",
                "proposal_id": None,
                "evidence_refs": [f"chart:{request.chart.sha256}"],
                "counter_evidence_refs": [],
                "invalidation": None,
                "reason_code": reason,
                "reason_detail": detail[:400],
                "quality_status": quality,
                **(dict(extra) if extra else {}),
            }
        )
        return self._response(payload)

    def _rationale(
        self,
        *,
        signal: Any,
        action: str,
        stop_pct: float,
        last_close: float,
        indicators: Mapping[str, IndicatorResult],
    ) -> str:
        """A sentence a reader can check, built only from what the decision consumed."""

        facts = [f"{self.spec.family_name} {action}"]
        if indicators:
            facts.append(
                f"EMA{INDICATOR_PARAMS['ema_fast']}="
                f"{_as_float(indicators['ema_fast']):.6f} vs "
                f"EMA{INDICATOR_PARAMS['ema_slow']}="
                f"{_as_float(indicators['ema_slow']):.6f}"
            )
            facts.append(f"RSI={_as_float(indicators['rsi']):.2f}")
            facts.append(f"ATR={_as_float(indicators['atr']):.6f}")
        family = getattr(signal, "family", self.spec.family_name)
        facts.append(f"family={family}")
        facts.append(f"close {last_close:.6f}")
        facts.append(f"structural stop {stop_pct:.4f}% away")
        return (
            ", ".join(facts)
            + f". Declared confidence {DECLARED_CONFIDENCE} is a fixed placeholder: the "
            "family exposes no calibrated conviction."
        )

    def analyze(self, request: VisionRequest) -> VisionResponse:
        symbol = str(request.chart.symbol)
        decision_ts_ms = int(request.decision_ts_ms)
        last_open_ms = int(request.chart.last_ts_ms)
        try:
            window = point_in_time_window(
                self.series,
                symbol,
                last_open_ms=last_open_ms,
                interval_ms=self.interval_ms,
                decision_ts_ms=decision_ts_ms,
                limit=self.window_bars,
            )
        except SignalBlocked as exc:
            return self._no_trade(
                request=request,
                symbol=symbol,
                reason=exc.code,
                detail=exc.detail,
                extra={"decision_bar_open_ms": last_open_ms},
            )

        candles = window.candles()
        if len(candles) < self.spec.min_candles:
            return self._no_trade(
                request=request,
                symbol=symbol,
                reason="INSUFFICIENT_WINDOW",
                detail=(
                    f"{len(candles)} candles in the window, {self.spec.min_candles} required "
                    f"by {self.spec.family_name}"
                ),
                extra={
                    "decision_bar_open_ms": last_open_ms,
                    "market_data_fingerprint": window.digest,
                    "max_input_data_time_ms": window.max_input_data_time_ms,
                    "max_input_data_time_utc": _utc(window.max_input_data_time_ms),
                },
            )
        try:
            # The EMA family is handed the four indicators the adapter computed, because
            # the trace publishes them; every other family computes its own inside the same
            # PIT window (its documented contract) and the trace names that difference.
            indicators: dict[str, IndicatorResult] = (
                compute_indicators(candles) if self.spec.indicator_kind == "ema_rsi_atr" else {}
            )
        except IndicatorError as exc:
            return self._no_trade(
                request=request,
                symbol=symbol,
                reason="INDICATOR_FAILED",
                detail=str(exc),
                extra={
                    "decision_bar_open_ms": last_open_ms,
                    "market_data_fingerprint": window.digest,
                },
            )

        signals = self.family.generate(candles, indicators, timeframe=self.timeframe)
        last_close = float(candles[-1].close)
        base = {
            "decision_bar_open_ms": last_open_ms,
            "market_data_fingerprint": window.digest,
            "max_input_data_time_ms": window.max_input_data_time_ms,
            "max_input_data_time_utc": _utc(window.max_input_data_time_ms),
            "window_bars": len(candles),
            "last_close": last_close,
            "indicator_source": self.spec.indicator_kind,
            "indicators": {key: _round(_as_float(value)) for key, value in indicators.items()},
        }
        if not signals:
            return self._no_trade(
                request=request,
                symbol=symbol,
                reason="STRATEGY_NO_SIGNAL",
                detail=(
                    f"{self.spec.family_name} produced no direction on this window; the "
                    "family's own pre-registered condition did not hold"
                ),
                quality="PASS",
                extra=base,
            )

        signal = signals[0]
        # ``effective_stop`` is `float | None`; the family always fills it for a directional
        # signal, so a missing one is a contract violation rather than a zero-width stop.
        if signal.effective_stop is None:
            return self._no_trade(
                request=request,
                symbol=symbol,
                reason="STRATEGY_STOP_MISSING",
                detail="the family returned a directional signal without a structural stop",
                extra=base,
            )
        stop_pct = abs(last_close - float(signal.effective_stop)) / last_close * 100.0
        stop_pct = max(0.01, min(25.0, stop_pct))
        action = "LONG" if signal.direction == "LONG" else "SHORT"
        payload = {
            "schema_version": "ai-vision-decision/1",
            "symbol": symbol,
            "action": action,
            "confidence": DECLARED_CONFIDENCE,
            "horizon_bars": 8,
            "stop_loss_pct": round(stop_pct, 6),
            "take_profit_pct": None,
            "invalidation": f"{self.spec.invalidation}"[:240],
            "rationale": (
                self._rationale(
                    signal=signal,
                    action=action,
                    stop_pct=stop_pct,
                    last_close=last_close,
                    indicators=indicators,
                )
            )[:600],
        }
        self._trace(
            {
                "schema_version": TRACE_SCHEMA,
                "provider": self.name,
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "strategy_classification": self.spec.classification,
                "asset": symbol,
                "timeframe": self.timeframe,
                "decision_time_ms": decision_ts_ms,
                "decision_time_utc": _utc(decision_ts_ms),
                "action": action,
                "proposal_id": None,
                "evidence_refs": [
                    f"chart:{request.chart.sha256}",
                    f"window:{window.digest}",
                    f"bar:{last_open_ms}",
                ],
                "counter_evidence_refs": [],
                "invalidation": payload["invalidation"],
                "reason_code": "STRATEGY_DIRECTIONAL",
                "reason_detail": None,
                "quality_status": "PASS",
                **base,
            }
        )
        return self._response(payload)


def provider_name(source: str) -> str:
    """The provider a source resolves to, without constructing one."""

    if source == SIGNAL_SOURCE_LEGACY:
        return "paper-script"
    if source == SIGNAL_SOURCE_STRATEGY:
        return "strategy-signal"
    raise SignalSourceConfigError(
        f"unknown signal source {source!r}; allowed: {list(SIGNAL_SOURCES)}"
    )


def build_signal_provider(
    source: str,
    *,
    series: Mapping[str, Sequence[Any]],
    timeframe: str,
    interval_ms: int,
    window_bars: int,
    latency_ms: int = 0,
    trace_path: Path | str | None = None,
    mode: str = PAPER_MODE,
    strategy_id: str = STRATEGY_EMA_CROSSOVER,
) -> Any:
    """Resolve the configured source to a provider, or refuse the run.

    The legacy branch builds the very object the session used before this module existed,
    with the same argument, which is what keeps the default path byte-identical in its
    decisions.
    """

    if source == SIGNAL_SOURCE_LEGACY:
        from trading_bot.vision.prospective import PaperScriptProvider

        return PaperScriptProvider(latency_ms=int(latency_ms))
    if source == SIGNAL_SOURCE_STRATEGY:
        return StrategySignalProvider(
            series=series,
            timeframe=timeframe,
            interval_ms=int(interval_ms),
            window_bars=int(window_bars),
            strategy_id=strategy_id,
            mode=mode,
            trace_path=None if trace_path is None else Path(trace_path),
        )
    raise SignalSourceConfigError(
        f"unknown signal source {source!r}; allowed: {list(SIGNAL_SOURCES)}; "
        "there is no silent fallback to the scripted rotation"
    )


__all__ = [
    "DECLARED_CONFIDENCE",
    "INDICATOR_PARAMS",
    "MIN_CANDLES",
    "PAPER_MODE",
    "SIGNAL_SOURCES",
    "SIGNAL_SOURCE_LEGACY",
    "SIGNAL_SOURCE_STRATEGY",
    "STRATEGY_BREAKOUT",
    "STRATEGY_EMA_CROSSOVER",
    "STRATEGY_MEAN_REVERSION",
    "STRATEGY_MOMENTUM",
    "STRATEGY_SPECS",
    "STRATEGY_TREND",
    "STRATEGY_VOLATILITY",
    "SUPPORTED_STRATEGIES",
    "PitWindow",
    "SignalBlocked",
    "SignalSourceConfigError",
    "StrategySignalProvider",
    "StrategySpec",
    "build_signal_provider",
    "compute_indicators",
    "min_candles_for",
    "point_in_time_window",
    "provider_name",
]
