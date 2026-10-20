"""prospective — a live PAPER session fed by real 1-minute data.

Everything in this package up to 003E could *replay* causal data; nothing could watch the
market and decide as it happened. This module closes that gap without inventing a second
engine: it polls :mod:`trading_bot.market_data.minute_collector`, aggregates only fully
observed minutes into decision bars, and hands them to the **production** ``VisionLane``
(production ``RiskManager`` and ``PaperBroker``) on a wall-clock schedule.

Three properties are enforced here rather than promised in a report:

* **PAPER only.** A mode other than ``PAPER`` raises before any object is built. There is
  no exchange client in this path and no code that can submit an order.
* **``data_time <= decision_time``.** A cycle runs only after the newest decision bar has
  closed *and* the measured delivery delay has elapsed; the stream row records both
  instants, and a violation stops the session instead of being logged as a curiosity.
* **No future in the series.** Only bars whose close is at or before ``data_time`` are
  passed to the lane, and each cycle re-runs the deterministic lane over that prefix. The
  recomputation is checked against the previous cycle row by row: if a past decision
  changes when new data arrives, the session stops (``PREFIX_DIVERGENCE``) instead of
  publishing a book that was rewritten after the fact.

The lane's sub-bar path is activated **here and only here**, for PAPER, as an explicit
constructor argument. Replays and benchmarks keep the default (one fill per bar open).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.config.risk import Risk
from trading_bot.market_data.minute_collector import (
    MinuteBar,
    MinuteCollector,
    aggregate_complete,
)
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.clock import timeframe_ms
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import DecisionLedger, read_entries
from trading_bot.vision.provider import VisionRequest, VisionResponse
from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries
from trading_bot.vision.settings import VisionConfig
from trading_bot.vision.signal_sources import (
    MIN_CANDLES,
    SIGNAL_SOURCE_LEGACY,
    SIGNAL_SOURCE_STRATEGY,
    SIGNAL_SOURCES,
    STRATEGY_EMA_CROSSOVER,
    SignalSourceConfigError,
    build_signal_provider,
    provider_name,
)

PAPER = "PAPER"
LIVE = "LIVE"
ALLOWED_MODES = (PAPER,)

#: The runtime files whose exact bytes a run depends on. The session records their
#: hashes so "tested runtime == used runtime" is checkable after the fact.
RUNTIME_PATHS = (
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/execution.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/clock.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/provider.py",
    "src/trading_bot/vision/settings.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/market_data/minute_collector.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/paper/broker.py",
    # 003J: the signal source and the strategy it may ask are part of the run's identity.
    "src/trading_bot/vision/signal_sources.py",
    "src/trading_bot/research/families/ema_crossover_family.py",
    "src/trading_bot/indicators/builtin.py",
)


class LiveModeRefused(RuntimeError):
    """Any attempt to run this path outside PAPER."""


class SessionAborted(RuntimeError):
    """The session cannot continue without inventing a result."""


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for relative in RUNTIME_PATHS:
        path = root / relative
        out[relative] = _sha256_file(path) if path.exists() else "MISSING"
    return out


def display_symbol(archive_symbol: str) -> str:
    """``BTCUSDT`` → ``BTC/USDT``, the shape the lane and its chart use."""

    text = str(archive_symbol)
    return f"{text[:-4]}/{text[-4:]}" if text.endswith("USDT") else text


@dataclass(frozen=True, slots=True)
class ProspectiveConfig:
    """Everything the session needs, declared before it starts."""

    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    timeframe: str = "5m"
    window_bars: int = 20
    decision_every_bars: int = 1
    duration_s: int = 2_700
    poll_interval_s: float = 15.0
    settle_ms: int = 2_500
    latency_ms: int = 30_000
    warmup_minutes: int = 240
    equity: float = 10_000.0
    mode: str = PAPER
    max_cycles: int | None = None
    stale_after_ms: int = 150_000
    max_skew_ms: int = 5_000
    #: 003J: which generator forms the decision. ``legacy_parity`` is the script that
    #: always ran here; ``strategy_experimental`` is the opt-in adapter and refuses any
    #: other mode. There is no third value and no silent fallback between them.
    signal_source: str = SIGNAL_SOURCE_LEGACY
    strategy_id: str = STRATEGY_EMA_CROSSOVER

    def __post_init__(self) -> None:
        if str(self.mode).upper() not in ALLOWED_MODES:
            raise LiveModeRefused(
                f"mode {self.mode!r} is not allowed: this session is PAPER only and has "
                "no path to a live order"
            )
        if not self.symbols:
            raise ValueError("a session with no symbols has nothing to decide")
        if self.window_bars < 20:
            raise ValueError("window_bars must be >= 20, the lane's minimum")
        if self.decision_every_bars < 1:
            raise ValueError("decision_every_bars must be >= 1")
        timeframe_ms(self.timeframe)
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if self.signal_source not in SIGNAL_SOURCES:
            raise SignalSourceConfigError(
                f"unknown signal source {self.signal_source!r}; allowed: {list(SIGNAL_SOURCES)}"
            )
        if self.signal_source == SIGNAL_SOURCE_STRATEGY and self.strategy_id != STRATEGY_EMA_CROSSOVER:
            raise SignalSourceConfigError(
                f"strategy {self.strategy_id!r} is not admitted to the experimental source; "
                f"the only admitted strategy is {STRATEGY_EMA_CROSSOVER!r}"
            )
        if self.signal_source == SIGNAL_SOURCE_STRATEGY and self.window_bars < MIN_CANDLES:
            raise SignalSourceConfigError(
                f"the experimental source needs window_bars >= {MIN_CANDLES} (the family's "
                f"own guard); got {self.window_bars}"
            )

    @property
    def interval_ms(self) -> int:
        return timeframe_ms(self.timeframe)


class PaperScriptProvider:
    """Deterministic PAPER signal. It is a script, never a model.

    The name and the ``provider`` field of every response say ``paper-script`` so no
    report can mistake this for ``REAL_MODEL_CALLED``. It exists to exercise the full
    chain — decision, risk gate, fill, costs, ledger — on real prices.
    """

    name = "paper-script"
    model = "deterministic-paper-script/1"

    def __init__(self, *, latency_ms: int = 0) -> None:
        self.seen = 0
        self.latency_ms = int(latency_ms)

    def analyze(self, request: VisionRequest) -> VisionResponse:
        self.seen += 1
        symbol = request.chart.symbol
        action = ("LONG", "NO_TRADE", "SHORT", "NO_TRADE")[(self.seen - 1) % 4]
        payload: dict[str, Any] = {
            "schema_version": "ai-vision-decision/1",
            "symbol": symbol,
            "action": action,
            "confidence": 0.5,
            "horizon_bars": 8,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "rationale": "PAPER scripted answer; not a model opinion.",
        }
        return VisionResponse(
            text=json.dumps(payload),
            model=self.model,
            provider=self.name,
            request_id=f"paper-{self.seen:05d}",
            latency_ms=self.latency_ms,
            attempts=1,
            image_sha256_in_request=request.chart.sha256 if request.chart.png else "",
        )


def _p95(values: Sequence[int]) -> int:
    if not values:
        return 0
    ordered = sorted(int(value) for value in values)
    index = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def _normalized(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "recorded_at_utc"}


def compare_prefix(
    previous: Sequence[dict[str, Any]], current: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Compare the overlapping part of two cycle ledgers, ignoring the wall-clock stamp.

    The previous run's final ``RUN_END`` is excluded because it describes a shorter
    series. Every other row must be identical: a decision made before the new bar existed
    cannot change because the new bar arrived.
    """

    # Two kinds of row are *not* past decisions and cannot be compared as such:
    #
    # * ``RUN`` is the header and describes the dataset, which necessarily grows;
    # * anything in the ``RUN_END`` phase is the shorter run closing out an order that
    #   never found a quote. The new bar may resolve that same order, which changes the
    #   terminal row without changing a single past decision.
    first = 1 if previous and previous[0].get("entry", {}).get("kind") == "RUN" else 0
    if first > 0 and current and current[0].get("entry", {}).get("kind") != "RUN":
        return {"ok": False, "compared": 0, "reason": "CURRENT_HEADER_MISSING"}
    compared = 0
    for row in previous[first:]:
        entry = row.get("entry", {})
        if entry.get("kind") == "RUN_END" or entry.get("phase") == "RUN_END":
            continue
        seq = int(row["seq"])
        if seq > len(current):
            return {"ok": False, "compared": compared, "reason": "CURRENT_LEDGER_SHORTER"}
        left = _normalized(entry)
        right = _normalized(current[seq - 1]["entry"])
        compared += 1
        if left != right:
            return {
                "ok": False,
                "compared": compared,
                "first_mismatch_seq": seq,
                "left_sha256": row["sha256"],
                "right_sha256": current[seq - 1]["sha256"],
                "reason": "PREFIX_DIVERGENCE",
            }
    return {"ok": True, "compared": compared}


@dataclass
class ProspectiveSession:
    """A wall-clock PAPER session over a live 1-minute feed."""

    config: ProspectiveConfig
    out_dir: Path
    vision_config: VisionConfig
    risk_policy: Risk
    root: Path = Path(".")
    collector: MinuteCollector | None = None
    clock: Callable[[], int] = lambda: int(time.time() * 1000)
    sleeper: Callable[[float], None] = time.sleep
    progress: Callable[[str], None] = lambda message: None
    _stream: DecisionLedger | None = field(default=None, init=False)
    _last_cycle_bar_open_ms: int | None = field(default=None, init=False)
    _previous_rows: list[dict[str, Any]] = field(default_factory=list, init=False)
    _cycle: int = field(default=0, init=False)
    _data_delay_ms: int = field(default=0, init=False)
    _started_at_ms: int = field(default=0, init=False)
    _last_block_signature: str | None = field(default=None, init=False)
    _blocked_reasons: set[str] = field(default_factory=set, init=False)
    _runtime: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.out_dir = Path(self.out_dir)
        self.root = Path(self.root)
        self._runtime = runtime_hashes(self.root)

    # -- session scaffolding -------------------------------------------------

    def _ensure_collector(self) -> MinuteCollector:
        if self.collector is not None:
            return self.collector
        self.out_dir.mkdir(parents=True, exist_ok=True)
        collector = MinuteCollector(
            source=_default_source(),
            root=self.out_dir / "market-1m",
            symbols=self.config.symbols,
            max_skew_ms=self.config.max_skew_ms,
            stale_after_ms=self.config.stale_after_ms,
            settle_ms=self.config.settle_ms,
            local_clock=self.clock,
        )
        self.collector = collector.open()
        return self.collector

    def _emit_once(self, kind: str, signature: str, payload: Mapping[str, Any]) -> bool:
        """Write a non-decision row once per distinct condition.

        A stale feed is polled every few seconds; writing ``BLOCKED`` each time would
        drown the chain in duplicates and make "one blocked episode" unreadable. The
        signature is the condition, not the timestamp.
        """

        if self._last_block_signature == signature:
            return False
        self._last_block_signature = signature
        assert self._stream is not None
        self._stream.append(kind, dict(payload))
        if kind == "BLOCKED":
            self._blocked_reasons.add(str(payload.get("reason", "")))
        return True

    def _write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        path = self.out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    # -- feed construction ---------------------------------------------------

    def _minute_series(self) -> dict[str, list[MinuteBar]]:
        assert self.collector is not None
        return self.collector.minute_bars()

    def _quote_feed(self, minutes: Mapping[str, Sequence[MinuteBar]]) -> MinuteBarQuoteFeed:
        series: dict[str, MinuteSeries] = {}
        for symbol, bars in minutes.items():
            display = display_symbol(symbol)
            series[display] = MinuteSeries.from_rows(
                display,
                [
                    [bar.open_ms, bar.open, bar.high, bar.low, bar.close, bar.volume]
                    for bar in bars
                ],
            )
        return MinuteBarQuoteFeed(series)

    def _decision_series(
        self, minutes: Mapping[str, Sequence[MinuteBar]], *, until_ms: int
    ) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
        """Aggregate complete minutes into decision bars that closed by ``until_ms``."""

        series: dict[str, list[Bar]] = {}
        aggregate: dict[str, Any] = {}
        for symbol, bars in minutes.items():
            usable = [bar for bar in bars if bar.close_ms <= int(until_ms)]
            grouped, meta = aggregate_complete(usable, interval_ms=self.config.interval_ms)
            series[display_symbol(symbol)] = grouped
            aggregate[symbol] = meta
        return series, aggregate

    # -- latency measurement -------------------------------------------------

    def _awaited_live_delay(self, collector: MinuteCollector, *, since_ms: int) -> int:
        """Wait for freshly closed minutes, then declare the delay actually observed.

        A bootstrap page carries hours of history whose ``received_at`` is the instant we
        asked, so its latencies are not delivery latencies at all. The delay that matters
        is the one measured on minutes that closed *after* the session started: those
        arrived because a poll was due, and their ``received_at - close`` is the real gap
        between the venue and this decision loop.
        """

        deadline = int(self.clock()) + 150_000
        while int(self.clock()) < deadline:
            collector.collect()
            samples = [
                bar.delivery_latency_ms
                for bars in collector.minute_bars().values()
                for bar in bars
                if bar.close_ms >= since_ms and bar.delivery_latency_ms >= 0
            ]
            if samples and len(samples) >= len(collector.symbols):
                self.progress(f"measured {len(samples)} live delivery latencies")
                return _p95(samples)
            self.sleeper(min(5.0, self.config.poll_interval_s))
        raise SessionAborted(
            "NO_LIVE_DATA: no minute closed after the session started, so the delivery "
            "delay cannot be measured and a decision would be stamped with a guess"
        )

    # -- cycle ---------------------------------------------------------------

    def _run_cycle(
        self,
        *,
        cycle: int,
        series: Mapping[str, Sequence[Bar]],
        minutes: Mapping[str, Sequence[MinuteBar]],
        data_time_ms: int,
        decision_time_ms: int,
        server_time_ms: int,
        health: Mapping[str, Any],
    ) -> dict[str, Any]:
        feed = self._quote_feed(minutes)
        directory = self.out_dir / "cycles" / f"cycle-{cycle:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        ledger_path = directory / "ledger.jsonl"
        if ledger_path.exists():
            ledger_path.unlink()
        # 003J: one resolution point for the signal source. The legacy branch builds the
        # same ``PaperScriptProvider(latency_ms=...)`` this line used to build; the
        # experimental branch builds the adapter. Anything else refuses the run.
        provider = build_signal_provider(
            self.config.signal_source,
            series=series,
            timeframe=self.config.timeframe,
            interval_ms=self.config.interval_ms,
            window_bars=self.config.window_bars,
            latency_ms=self.config.latency_ms,
            trace_path=directory / "SIGNAL_TRACE.jsonl",
            mode=self.config.mode,
            strategy_id=self.config.strategy_id,
        )
        lane = VisionLane(
            series={symbol: list(bars) for symbol, bars in series.items()},
            provider=provider,
            config=replace(
                self.vision_config,
                lane=replace(
                    self.vision_config.lane,
                    window_bars=self.config.window_bars,
                    decision_every_bars=self.config.decision_every_bars,
                    data_delay_ms=self._data_delay_ms,
                ),
            ),
            risk_policy=self.risk_policy,
            ledger_path=ledger_path,
            equity=self.config.equity,
            book_id="paper-prospective-003g",
            decision_every_bars=self.config.decision_every_bars,
            quote_feed=feed,
            subbar_entries=True,
            decision_from_ms=self._started_at_ms,
        )
        summary = lane.run()
        (directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        rows = read_entries(ledger_path)
        new_rows = max(0, len(rows) - len(self._previous_rows))
        prefix = compare_prefix(self._previous_rows, rows)
        self._previous_rows = rows
        record = {
            "cycle": cycle,
            "status": "EXECUTED",
            "mode": PAPER,
            "decision_bar_open_ms": int(data_time_ms) - self.config.interval_ms,
            "data_time_ms": int(data_time_ms),
            "data_time_utc": _utc_iso(data_time_ms),
            "decision_time_ms": int(decision_time_ms),
            "decision_time_utc": _utc_iso(decision_time_ms),
            "server_time_ms": int(server_time_ms),
            "data_time_le_decision_time": int(data_time_ms) <= int(decision_time_ms),
            "data_delay_ms": self._data_delay_ms,
            "declared_latency_ms": self.config.latency_ms,
            "timeframe": self.config.timeframe,
            "bar_interval_ms": self.config.interval_ms,
            "subbar_entries": True,
            "live_orders": 0,
            "series": {
                symbol: {
                    "bars": len(bars),
                    "first_open_ms": int(bars[0].ts_ms) if bars else None,
                    "last_open_ms": int(bars[-1].ts_ms) if bars else None,
                    "sha256": _series_digest(bars),
                }
                for symbol, bars in series.items()
            },
            "minutes": {
                symbol: {"minutes": len(bars), "sha256": _minutes_digest(bars)}
                for symbol, bars in minutes.items()
            },
            "health": {
                symbol: {"state": item.state, "reason": item.reason}
                for symbol, item in health.items()
            },
            "ledger": {
                "path": str(ledger_path.relative_to(self.out_dir)),
                "sha256": _sha256_file(ledger_path),
                "rows": len(rows),
                "new_rows": new_rows,
                "prefix": prefix,
            },
            "calls": int(summary.get("calls", 0)),
            "fills": int(summary.get("fills", 0)),
            "closed_trades": int(summary.get("closed_trades", 0)),
            "net_realised_usdt": summary.get("net_realised_usdt"),
            "drawdown_pct": summary.get("drawdown_pct"),
            "execution": summary.get("execution", {}),
            "reconciliation": summary.get("reconciliation", {}),
            "actions": summary.get("counters", {}),
            #: 003H: the lane's cost/PnL contract travels with the cycle, so a reader of the
            #: session — not of the lane — still sees that an open position owes a fee.
            "accounting": {
                "schema_version": (summary.get("accounting") or {}).get("schema_version"),
                "initial_equity_usdt": (summary.get("accounting") or {}).get(
                    "initial_equity_usdt"
                ),
                "costs_usdt": summary.get("costs_usdt"),
                "costs_realised_usdt": summary.get("costs_realised_usdt"),
                "costs_total_usdt": summary.get("costs_total_usdt"),
                "entry_commissions_accrued_open_usdt": summary.get(
                    "entry_commissions_accrued_open_usdt"
                ),
                "pnl_realised_usdt": summary.get("pnl_realised_usdt"),
                "pnl_unrealised_usdt": summary.get("pnl_unrealised_usdt"),
                "pnl_total_usdt": summary.get("pnl_total_usdt"),
                "marked_equity_usdt": summary.get("marked_equity_usdt"),
                "mark_prices": (summary.get("accounting") or {}).get("mark_prices", {}),
            },
            "open_positions_at_end": summary.get("open_positions_at_end", {}),
        }
        if not prefix["ok"]:
            record["status"] = "ABORTED"
            record["reason"] = "PREFIX_DIVERGENCE"
        if not record["data_time_le_decision_time"]:
            record["status"] = "ABORTED"
            record["reason"] = "DATA_TIME_AFTER_DECISION_TIME"
        return record

    # -- run -----------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        if str(self.config.mode).upper() != PAPER:
            raise LiveModeRefused("ProspectiveSession.run() is PAPER only")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        collector = self._ensure_collector()
        stream_path = self.out_dir / "STREAM.jsonl"
        if stream_path.exists():
            stream_path.unlink()
        stream = DecisionLedger(stream_path).open()
        self._stream = stream
        started = int(self.clock())
        self._started_at_ms = started
        deadline = started + self.config.duration_s * 1000
        session_info: dict[str, Any] = {
            "schema_version": "PROSPECTIVE_PAPER_SESSION_V1",
            "started_at_utc": _utc_iso(started),
            "mode": PAPER,
            "live_enabled": False,
            "live_orders": 0,
            "config": {
                "symbols": list(self.config.symbols),
                "timeframe": self.config.timeframe,
                "window_bars": self.config.window_bars,
                "decision_every_bars": self.config.decision_every_bars,
                "duration_s": self.config.duration_s,
                "poll_interval_s": self.config.poll_interval_s,
                "settle_ms": self.config.settle_ms,
                "declared_latency_ms": self.config.latency_ms,
                "warmup_minutes": self.config.warmup_minutes,
                "equity": self.config.equity,
                "signal_source": self.config.signal_source,
                "strategy_id": self.config.strategy_id,
            },
            "provider": provider_name(self.config.signal_source),
            "signal_source": self.config.signal_source,
            "strategy_id": self.config.strategy_id
            if self.config.signal_source == SIGNAL_SOURCE_STRATEGY
            else None,
            "real_model_called": False,
            "subbar_entries": "PAPER_ONLY",
            "runtime_sha256": self._runtime,
            "source": getattr(collector.source, "name", "unknown"),
        }
        stream.append("SESSION_START", session_info)
        self._write_json("SESSION_START.json", session_info)
        try:
            bootstrap_started = int(self.clock())
            bootstrap = collector.bootstrap(minutes=self.config.warmup_minutes)
            self._write_json("BOOTSTRAP.json", bootstrap)
            self.progress("bootstrap complete")
            self._data_delay_ms = self._awaited_live_delay(
                collector, since_ms=bootstrap_started
            )
            stream.append(
                "DELAY_MEASURED",
                {
                    "data_delay_ms": self._data_delay_ms,
                    "method": "p95 of (received_at - bar close) on minutes that closed "
                    "after the session started",
                },
            )
            cycles: list[dict[str, Any]] = []
            blocked_cycles = 0
            while int(self.clock()) < deadline:
                if self.config.max_cycles is not None and len(cycles) >= self.config.max_cycles:
                    break
                polled = collector.collect()
                server_time_ms = int(polled.get("server_time_ms", 0))
                at = int(self.clock())
                if not polled.get("ok", True):
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            f"FEED_DOWN:{polled.get('code', '')}",
                            {
                                "cycle": self._cycle + 1,
                                "reason": "FEED_DOWN",
                                "detail": {
                                    "code": polled.get("code"),
                                    "detail": polled.get("detail"),
                                },
                                "at_ms": at,
                                "at_utc": _utc_iso(at),
                                "live_orders": 0,
                            },
                        )
                    )
                    self.sleeper(self.config.poll_interval_s)
                    continue
                health = polled.get("health") or collector.health()
                # Freshness comes first: a stale or gapped feed must produce a BLOCKED
                # row even when no new decision bar exists to hang it on.
                bad = sorted(
                    symbol for symbol, item in health.items() if not item.tradeable
                )
                if bad:
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            "DATA_NOT_TRADEABLE:" + ",".join(bad),
                            {
                                "cycle": self._cycle + 1,
                                "reason": "DATA_NOT_TRADEABLE",
                                "detail": {
                                    symbol: {
                                        "state": health[symbol].state,
                                        "reason": health[symbol].reason,
                                    }
                                    for symbol in bad
                                },
                                "at_ms": at,
                                "at_utc": _utc_iso(at),
                                "live_orders": 0,
                            },
                        )
                    )
                    self.sleeper(self.config.poll_interval_s)
                    continue
                minutes = self._minute_series()
                if not minutes or any(len(bars) < 2 for bars in minutes.values()):
                    self.sleeper(self.config.poll_interval_s)
                    continue
                last_minute_close = min(bars[-1].close_ms for bars in minutes.values())
                series, aggregate = self._decision_series(
                    minutes, until_ms=last_minute_close
                )
                holes = {
                    symbol: meta["incomplete_groups"]
                    for symbol, meta in aggregate.items()
                    if meta["incomplete_groups"]
                }
                if holes:
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            "INCOMPLETE_DECISION_BAR:" + ",".join(sorted(holes)),
                            {
                                "cycle": self._cycle + 1,
                                "reason": "INCOMPLETE_DECISION_BAR",
                                "detail": holes,
                                "at_ms": at,
                                "at_utc": _utc_iso(at),
                                "live_orders": 0,
                            },
                        )
                    )
                    self.sleeper(self.config.poll_interval_s)
                    continue
                if any(len(bars) < self.config.window_bars for bars in series.values()):
                    self._emit_once(
                        "WARMING_UP",
                        "WARMING_UP",
                        {
                            "cycle": self._cycle + 1,
                            "bars": {symbol: len(bars) for symbol, bars in series.items()},
                            "needed": self.config.window_bars,
                            "at_ms": at,
                            "at_utc": _utc_iso(at),
                        },
                    )
                    self.sleeper(self.config.poll_interval_s)
                    continue
                newest = sorted({int(bars[-1].ts_ms) for bars in series.values()})
                if len(newest) != 1:
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            "MISALIGNED_DECISION_BARS",
                            {
                                "cycle": self._cycle + 1,
                                "reason": "MISALIGNED_DECISION_BARS",
                                "detail": {
                                    symbol: int(bars[-1].ts_ms)
                                    for symbol, bars in series.items()
                                },
                                "at_ms": at,
                                "at_utc": _utc_iso(at),
                                "live_orders": 0,
                            },
                        )
                    )
                    self.sleeper(self.config.poll_interval_s)
                    continue
                newest_open = newest[0]
                data_time_ms = newest_open + self.config.interval_ms
                if int(self.clock()) < data_time_ms + self._data_delay_ms + self.config.settle_ms:
                    self.sleeper(min(5.0, self.config.poll_interval_s))
                    continue
                if (
                    self._last_cycle_bar_open_ms is not None
                    and newest_open <= self._last_cycle_bar_open_ms
                ):
                    self.sleeper(self.config.poll_interval_s)
                    continue
                decision_time_ms = int(self.clock())
                if decision_time_ms < data_time_ms:
                    raise SessionAborted(
                        "the host clock is behind the data it is about to decide on: "
                        f"decision_time {decision_time_ms} < data_time {data_time_ms}"
                    )
                self._cycle += 1
                record = self._run_cycle(
                    cycle=self._cycle,
                    series=series,
                    minutes=minutes,
                    data_time_ms=data_time_ms,
                    decision_time_ms=decision_time_ms,
                    server_time_ms=server_time_ms,
                    health=health,
                )
                stream.append("CYCLE", record)
                cycles.append(record)
                self._last_cycle_bar_open_ms = newest_open
                self._last_block_signature = None
                self.progress(
                    f"cycle {self._cycle} bar {_utc_iso(newest_open)} "
                    f"fills={record['fills']} closed={record['closed_trades']}"
                )
                if record["status"] != "EXECUTED":
                    break
            summary = self._summary(cycles, blocked_cycles)
            stream.append("SESSION_END", summary)
            self._write_json("SUMMARY.json", summary)
            return summary
        finally:
            stream.close()
            collector.close()

    def _summary(self, cycles: Sequence[Mapping[str, Any]], blocked: int) -> dict[str, Any]:
        executed = [row for row in cycles if row.get("status") == "EXECUTED"]
        last = executed[-1] if executed else {}
        return {
            "schema_version": "PROSPECTIVE_PAPER_SUMMARY_V1",
            "mode": PAPER,
            "live_enabled": False,
            "live_orders": 0,
            "real_model_called": False,
            "provider": provider_name(self.config.signal_source),
            "signal_source": self.config.signal_source,
            "strategy_id": self.config.strategy_id
            if self.config.signal_source == SIGNAL_SOURCE_STRATEGY
            else None,
            "cycles_executed": len(executed),
            "cycles_blocked": blocked,
            "data_delay_ms": self._data_delay_ms,
            "declared_latency_ms": self.config.latency_ms,
            "subbar_entries": True,
            "decision_bars": sorted({int(row["decision_bar_open_ms"]) for row in executed}),
            "fills": int(last.get("fills", 0)) if last else 0,
            "closed_trades": int(last.get("closed_trades", 0)) if last else 0,
            "net_realised_usdt": last.get("net_realised_usdt") if last else None,
            "drawdown_pct": last.get("drawdown_pct") if last else None,
            "execution": last.get("execution", {}),
            "reconciliation": last.get("reconciliation", {}),
            "accounting": last.get("accounting", {}),
            "open_positions_at_end": last.get("open_positions_at_end", {}),
            "last_ledger": last.get("ledger", {}),
            "runtime_sha256": self._runtime,
            "blocked_reasons": sorted(
                set(self._blocked_reasons)
                | {
                    str(row.get("reason", ""))
                    for row in cycles
                    if row.get("status") != "EXECUTED"
                }
            ),
        }


def _series_digest(bars: Sequence[Bar]) -> str:
    payload = json.dumps(
        [
            [
                int(bar.ts_ms),
                round(float(bar.open), 8),
                round(float(bar.high), 8),
                round(float(bar.low), 8),
                round(float(bar.close), 8),
                round(float(bar.volume), 8),
            ]
            for bar in bars
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _minutes_digest(bars: Sequence[MinuteBar]) -> str:
    payload = json.dumps(
        [[int(bar.open_ms), bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _default_source() -> Any:
    from trading_bot.market_data.minute_collector import BinanceRestSource

    return BinanceRestSource()


__all__ = [
    "ALLOWED_MODES",
    "LIVE",
    "PAPER",
    "LiveModeRefused",
    "PaperScriptProvider",
    "ProspectiveConfig",
    "ProspectiveSession",
    "SessionAborted",
    "aggregate_complete",
    "compare_prefix",
    "display_symbol",
    "runtime_hashes",
]
