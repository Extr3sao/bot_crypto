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
    SourceUnavailable,
    aggregate_complete,
)
from trading_bot.ops.single_writer import LockRefused, pid_alive, reclaim_abandoned
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.clock import timeframe_ms
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import DecisionLedger, LedgerLockedError, read_entries
from trading_bot.vision.provenance import (
    RuntimeNotProvable,
    SessionIdentityMismatch,
    assert_provable,
    capture_session,
    drifted,
    file_hashes,
    resume_reasons,
)
from trading_bot.vision.provider import VisionRequest, VisionResponse
from trading_bot.vision.quotes import MinuteBarQuoteFeed, MinuteSeries
from trading_bot.vision.settings import VisionConfig
from trading_bot.vision.signal_sources import (
    SIGNAL_SOURCE_LEGACY,
    SIGNAL_SOURCE_STRATEGY,
    SIGNAL_SOURCES,
    STRATEGY_EMA_CROSSOVER,
    SUPPORTED_STRATEGIES,
    SignalSourceConfigError,
    build_signal_provider,
    min_candles_for,
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


def _pid_alive(pid: int) -> bool:
    """Backwards-compatible name for the shared probe (see ``ops.single_writer``)."""

    return pid_alive(pid)


def reclaim_stale_lock(path: Path) -> dict[str, Any] | None:
    """Take over a lock whose owner is *proved* gone, or refuse and say why.

    A lock is the only thing standing between two writers and one hash chain, so this
    function never guesses. The proof lives in ``ops.single_writer``: the owner's recorded
    process start time turns a recycled pid into evidence of death instead of a permanent
    refusal, the takeover is serialised and atomic, and a live owner is never dispossessed.
    A lock whose owner cannot be named here (empty, torn, or written by another host) is
    left alone and the session aborts with a code — deleting it could corrupt a writer that
    is still running, and that is worse than a manual step.
    """

    try:
        record = reclaim_abandoned(path, purpose="prospective-session")
    except LockRefused as exc:
        raise SessionAborted(f"RUNTIME_{exc.code}: {path}: {exc}") from exc
    if record is None:
        return None
    #: The evidence a reader needs: which owner, why it was considered gone, and which fence
    #: the new owner holds, so "resumed after a crash" cannot be confused with "deleted a
    #: lock and hoped".
    return {
        "lock": str(record["lock"]),
        "pid": record.get("pid"),
        "reason": str(record.get("reason")),
        "fence": record.get("fence"),
        "process_start_ms": record.get("process_start_ms"),
    }


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
            raise LiveModeRefused(                f"mode {self.mode!r} is not allowed: this session is PAPER only and has "
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
        if self.signal_source == SIGNAL_SOURCE_STRATEGY:
            # 003K widened the admitted set to the families that already exist in
            # ``research/families``; each one carries its own minimum window.
            required = min_candles_for(self.strategy_id)
            if self.window_bars < required:
                raise SignalSourceConfigError(
                    f"the experimental source needs window_bars >= {required} for "
                    f"{self.strategy_id!r} (the family's own guard); got {self.window_bars}"
                )
        elif self.strategy_id not in SUPPORTED_STRATEGIES:
            raise SignalSourceConfigError(
                f"strategy {self.strategy_id!r} is not admitted; allowed: "
                f"{sorted(SUPPORTED_STRATEGIES)}"
            )

    @property
    def interval_ms(self) -> int:
        return timeframe_ms(self.timeframe)

    def identity_payload(self) -> dict[str, Any]:
        """Every declared field, for the configuration fingerprint.

        The ``SESSION_START`` row publishes a subset a reader finds useful; the fingerprint
        must cover the whole declaration, because two sessions that differ only in
        ``stale_after_ms`` make different decisions but would otherwise hash the same.
        """

        return {
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "window_bars": int(self.window_bars),
            "decision_every_bars": int(self.decision_every_bars),
            "duration_s": int(self.duration_s),
            "poll_interval_s": float(self.poll_interval_s),
            "settle_ms": int(self.settle_ms),
            "latency_ms": int(self.latency_ms),
            "warmup_minutes": int(self.warmup_minutes),
            "equity": float(self.equity),
            "mode": str(self.mode),
            "max_cycles": None if self.max_cycles is None else int(self.max_cycles),
            "stale_after_ms": int(self.stale_after_ms),
            "max_skew_ms": int(self.max_skew_ms),
            "signal_source": self.signal_source,
            "strategy_id": self.strategy_id,
        }


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
    #: WP-04C: continue a session that was interrupted, after re-proving that the bytes
    #: are still the ones it pinned. ``False`` means a fresh session, which deletes the
    #: previous stream rather than appending to a different run's evidence.
    resume: bool = False
    _stream: DecisionLedger | None = field(default=None, init=False)
    _last_cycle_bar_open_ms: int | None = field(default=None, init=False)
    _previous_rows: list[dict[str, Any]] = field(default_factory=list, init=False)
    _cycle: int = field(default=0, init=False)
    _data_delay_ms: int = field(default=0, init=False)
    _started_at_ms: int = field(default=0, init=False)
    _last_block_signature: str | None = field(default=None, init=False)
    _blocked_reasons: set[str] = field(default_factory=set, init=False)
    _runtime: dict[str, str] = field(default_factory=dict, init=False)
    _pin: dict[str, Any] = field(default_factory=dict, init=False)
    _pinned_runtime: dict[str, str] = field(default_factory=dict, init=False)
    _pinned_digest: str = field(default="", init=False)
    _runtime_drift_paths: list[str] = field(default_factory=list, init=False)
    #: A delivered-latency measurement is part of the decision clock, not a property of the
    #: host: it decides when a bar's information is assumed to be available. A resumed
    #: session keeps the delay it pinned, or its first cycle would rewrite decisions the
    #: previous session already took (measured: 2608 ms → 4625 ms changed a DECISION row).
    _pinned_delay_ms: int | None = field(default=None, init=False)
    _measured_delay_ms: int | None = field(default=None, init=False)
    #: CODEX: locks taken over from a process that no longer exists. Recorded, because
    #: "the run resumed" and "the run resumed by deleting a lock" are different claims.
    _lock_reclaims: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.out_dir = Path(self.out_dir)
        self.root = Path(self.root)
        self._runtime = runtime_hashes(self.root)

    # -- provenance ----------------------------------------------------------

    def _previous_provenance(self) -> dict[str, Any] | None:
        """The block the interrupted session pinned, if this directory holds one."""
        path = self.out_dir / "SESSION_PROVENANCE.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _provider_identity(self) -> dict[str, Any]:
        """Who produces the prices and who produces the opinion. Both decide the run."""
        collector = self.collector
        if collector is not None:
            source = collector.source
            data = {
                "kind": "injected",
                "name": str(getattr(source, "name", type(source).__name__)),
                "base_url": getattr(source, "base_url", None),
            }
        else:
            default = _default_source()
            data = {
                "kind": "default",
                "name": str(getattr(default, "name", type(default).__name__)),
                "base_url": getattr(default, "base_url", None),
            }
        return {
            "signal": {
                "source": self.config.signal_source,
                "provider": provider_name(self.config.signal_source),
                "strategy_id": self.config.strategy_id
                if self.config.signal_source == SIGNAL_SOURCE_STRATEGY
                else None,
                "declared_latency_ms": int(self.config.latency_ms),
                "real_model_called": False,
            },
            "data": data,
        }

    def _pin_before_deciding(self, started_at_ms: int) -> tuple[dict[str, Any], int]:
        """Capture the session identity, refuse if it proves nothing, verify a resume.

        Runs before the collector and before the first bar is read, so the block describes
        the bytes that *are about to* decide rather than the bytes that happened to be on
        disk when the session ended. Nothing here touches the feed: a session whose runtime
        cannot be named fails before it can call a venue.
        """

        previous = self._previous_provenance() if self.resume else None
        if self.resume and previous is None:
            raise SessionAborted(
                "RESUME_WITHOUT_PROVENANCE: there is no pinned session in "
                f"{self.out_dir}, so a continuation could only claim an identity it never had"
            )
        block = capture_session(
            self.root,
            config=self.config.identity_payload(),
            provider=self._provider_identity(),
            started_at_ms=started_at_ms,
            mode=PAPER,
            resume_parent=previous,
        )
        assert_provable(block)
        origin = int(started_at_ms)
        if previous is not None:
            reasons = resume_reasons(previous, block)
            if reasons:
                raise SessionIdentityMismatch(
                    reasons,
                    {
                        "previous_session_id": previous.get("session_id"),
                        "previous_pinned_identity": previous.get("pinned_identity"),
                        "candidate_pinned_identity": block.get("pinned_identity"),
                        "changed_runtime_paths": drifted(
                            (block.get("runtime") or {}).get("sha256") or {},
                            (previous.get("runtime") or {}).get("sha256") or {},
                        ),
                        "previous_commit": (previous.get("code") or {}).get("commit"),
                        "candidate_commit": (block.get("code") or {}).get("commit"),
                    },
                )
            chain = (previous.get("resume") or {}).get("chain") or []
            origin = int(
                (chain[0] if chain else {}).get("started_at_ms")
                or previous.get("started_at_ms")
                or started_at_ms
            )
        self._pin = block
        self._pinned_runtime = dict((block.get("runtime") or {}).get("sha256") or {})
        self._pinned_digest = str((block.get("runtime") or {}).get("digest") or "")
        return block, origin

    def _runtime_drift(self) -> list[str]:
        """Paths whose bytes are no longer the ones this session pinned."""
        if not self._pinned_runtime:
            return []
        current = file_hashes(self.root, tuple(self._pinned_runtime))
        return drifted(current, self._pinned_runtime)

    def _resume_state(self) -> tuple[int, list[dict[str, Any]]]:
        """Continue the cycle counter and the prefix comparison across a restart.

        The previous session's last cycle ledger is a complete prefix; re-running the lane
        over it must reproduce every past decision, which is the same guarantee
        ``compare_prefix`` gives inside one process, extended over the gap.
        """

        directory = self.out_dir / "cycles"
        if not directory.is_dir():
            return 0, []
        indices = sorted(
            int(item.name.split("-")[-1])
            for item in directory.glob("cycle-*")
            if item.name.split("-")[-1].isdigit()
        )
        if not indices:
            return 0, []
        last = directory / f"cycle-{indices[-1]:04d}" / "ledger.jsonl"
        return indices[-1], read_entries(last)

    def _previous_delay(self) -> int | None:
        """The delay the interrupted session decided with, taken from its own chain."""
        for entry in reversed([row["entry"] for row in read_entries(self.out_dir / "STREAM.jsonl")]):
            delay = entry.get("data_delay_ms")
            if entry.get("kind") in ("CYCLE", "SESSION_END") and isinstance(delay, int):
                return int(delay)
        return None

    # -- session scaffolding -------------------------------------------------

    def _ensure_collector(self) -> MinuteCollector:
        if self.collector is not None:
            return self.collector
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for symbol in self.config.symbols:
            record = reclaim_stale_lock(self.out_dir / "market-1m" / f"{symbol}.jsonl.lock")
            if record:
                self._lock_reclaims.append(record)
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
        #: A crash inside a cycle leaves that cycle's ledger lock behind, and the resumed run
        #: reuses the same directory. Reclaiming it with the same proof as the stream lock is
        #: what makes "resume after a crash" a property instead of a manual ritual.
        inherited = reclaim_stale_lock(ledger_path.with_suffix(ledger_path.suffix + ".lock"))
        if inherited:
            self._lock_reclaims.append(inherited)
            self._emit_once(
                "LOCK_RECLAIMED",
                f"LOCK:{inherited['lock']}:{inherited.get('fence')}",
                {
                    "locks": [inherited],
                    "scope": "cycle_ledger",
                    "cycle": int(cycle),
                    "live_orders": 0,
                },
            )
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
            #: WP-04: the identity of the bytes that produced this cycle, repeated on every
            #: row so a reader does not have to trust a header written before the data.
            "provenance": {
                "run_id": self._pin.get("run_id"),
                "session_id": self._pin.get("session_id"),
                "pinned_identity": self._pin.get("pinned_identity"),
                "runtime_digest": self._pinned_digest,
            },
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
        started = int(self.clock())
        #: Before the collector, before the bootstrap, before any bar: the identity of the
        #: runtime is pinned, or the session does not start at all.
        pin, origin_ms = self._pin_before_deciding(started)
        collector = self._ensure_collector()
        stream_path = self.out_dir / "STREAM.jsonl"
        #: A process that was killed between ``O_CREAT`` and ``unlink`` leaves its lock
        #: behind; without this, the only way to resume a crashed session is to delete
        #: files by hand, which is exactly the manual step a sustained PAPER loop cannot
        #: have. A live owner still refuses (measured: exit 5, RUNTIME_LOCK_HELD).
        inherited = reclaim_stale_lock(stream_path.with_suffix(stream_path.suffix + ".lock"))
        if inherited:
            self._lock_reclaims.append(inherited)
        if stream_path.exists() and not pin["resume"]["resumed"]:
            stream_path.unlink()
        try:
            stream = DecisionLedger(stream_path).open()
        except LedgerLockedError as exc:
            #: A refusal is a code, not a traceback: a live second session must be visible in
            #: the operator's log as RUNTIME_LOCK_HELD, never as exit 1 with a stack.
            raise SessionAborted(f"RUNTIME_LOCK_HELD: {stream_path}: {exc}") from exc
        self._stream = stream
        #: On a resume the lane keeps reproducing the first session's decisions, so the
        #: prefix comparison still covers everything decided before the interruption.
        self._started_at_ms = int(origin_ms)
        if pin["resume"]["resumed"]:
            self._cycle, self._previous_rows = self._resume_state()
            self._pinned_delay_ms = self._previous_delay()
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
            "provenance": {
                "run_id": pin["run_id"],
                "session_id": pin["session_id"],
                "pinned_identity": pin["pinned_identity"],
                "runtime_digest": pin["runtime"]["digest"],
                "resumed": pin["resume"]["resumed"],
            },
        }
        stream.append("SESSION_START", session_info)
        self._write_json("SESSION_START.json", session_info)
        #: Written to the chain and to its own file *before* the bootstrap reads a bar, so
        #: the claim is on record before it can be reasonable to check it.
        stream.append("SESSION_PROVENANCE", pin)
        self._write_json("SESSION_PROVENANCE.json", pin)
        if self._lock_reclaims:
            #: Evidence, not housekeeping: a reader must be able to see that this session
            #: started over a lock whose owner was proved dead, and which one.
            stream.append(
                "LOCK_RECLAIMED",
                {"locks": list(self._lock_reclaims), "live_orders": 0},
            )
            self._write_json(
                "LOCKS_RECLAIMED.json",
                {
                    "session_id": pin["session_id"],
                    "run_id": pin["run_id"],
                    "locks": list(self._lock_reclaims),
                    "policy": "reclaim only when the recorded pid is provably gone",
                },
            )
            self._lock_reclaims = []
        session_record = self.out_dir / "provenance" / f"session-{pin['session_id']}.json"
        session_record.parent.mkdir(parents=True, exist_ok=True)
        session_record.write_text(
            json.dumps(pin, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        cycles: list[dict[str, Any]] = []
        blocked_cycles = 0
        try:
            bootstrap_started = int(self.clock())
            #: A venue that does not answer at startup used to escape as a raw
            #: ``SourceUnavailable`` traceback (measured: exit 1, no row, no code), which
            #: made an outage indistinguishable from a broken session. Blocking and
            #: retrying is the same condition the poll loop already handles, and it still
            #: refuses to decide without a measured delay: the deadline ends the session.
            measured: int | None = None
            warmed = False
            while True:
                try:
                    bootstrap = collector.bootstrap(minutes=self.config.warmup_minutes)
                    self._write_json("BOOTSTRAP.json", bootstrap)
                    self.progress("bootstrap complete")
                    measured = self._awaited_live_delay(collector, since_ms=bootstrap_started)
                except SourceUnavailable as exc:
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            f"FEED_DOWN:WARMUP:{exc.code}",
                            {
                                "cycle": self._cycle + 1,
                                "reason": "FEED_DOWN",
                                "phase": "WARMUP",
                                "detail": {"code": exc.code, "detail": exc.detail},
                                "at_ms": int(self.clock()),
                                "live_orders": 0,
                            },
                        )
                    )
                except SessionAborted as exc:
                    #: ``_awaited_live_delay`` gives up when no minute has closed yet; that
                    #: is a feed that has not produced data, not a reason to invent one.
                    blocked_cycles += int(
                        self._emit_once(
                            "BLOCKED",
                            "NO_LIVE_DATA:WARMUP",
                            {
                                "cycle": self._cycle + 1,
                                "reason": "NO_LIVE_DATA",
                                "phase": "WARMUP",
                                "detail": str(exc),
                                "at_ms": int(self.clock()),
                                "live_orders": 0,
                            },
                        )
                    )
                else:
                    warmed = True
                    break
                if int(self.clock()) >= deadline:
                    break
                self.sleeper(self.config.poll_interval_s)
            if not warmed or measured is None:
                #: The declared window ended before the venue produced a usable warm-up.
                #: That is a session that ran and blocked — the same thing the poll loop
                #: reports — not an exception: a caller reading the exit status must not
                #: have to choose between "crash" and "fine" for a known condition.
                summary = self._summary([], blocked_cycles)
                stream.append("SESSION_END", summary)
                self._write_json("SUMMARY.json", summary)
                return summary
            self._measured_delay_ms = int(measured)
            if self._pinned_delay_ms is not None:
                #: Continuing on the same clock: a fresh measurement is published beside
                #: the pinned value, but the pinned one is what the lane decides with, so
                #: the prefix this session reproduces stays comparable.
                self._data_delay_ms = int(self._pinned_delay_ms)
                delay_source = "PINNED_FROM_PREVIOUS_SESSION"
            else:
                self._data_delay_ms = int(measured)
                delay_source = "MEASURED_AT_SESSION_START"
            stream.append(
                "DELAY_MEASURED",
                {
                    "data_delay_ms": self._data_delay_ms,
                    "measured_now_ms": self._measured_delay_ms,
                    "source": delay_source,
                    "method": "p95 of (received_at - bar close) on minutes that closed "
                    "after the session started",
                },
            )
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
                #: WP-04C: the bytes were pinned at the start; if they moved, the next
                #: decision has no identity and is not taken. Checked here — after the data
                #: gate, immediately before a decision would be stamped.
                moved = self._runtime_drift()
                if moved:
                    self._runtime_drift_paths = moved
                    self._emit_once(
                        "BLOCKED",
                        "RUNTIME_DRIFT:" + ",".join(moved),
                        {
                            "cycle": self._cycle + 1,
                            "reason": "RUNTIME_DRIFT",
                            "detail": {
                                "changed_paths": moved,
                                "pinned_identity": pin["pinned_identity"],
                                "pinned_runtime_digest": pin["runtime"]["digest"],
                            },
                            "at_ms": int(self.clock()),
                            "at_utc": _utc_iso(int(self.clock())),
                            "live_orders": 0,
                        },
                    )
                    break
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
            #: WP-04: the same identity the session pinned, published with the result so the
            #: summary is not separable from the bytes that produced it.
            "provenance": {
                "run_id": self._pin.get("run_id"),
                "session_id": self._pin.get("session_id"),
                "pinned_identity": self._pin.get("pinned_identity"),
                "runtime_digest": self._pinned_digest,
                "resumed": bool((self._pin.get("resume") or {}).get("resumed")),
                "chain": list((self._pin.get("resume") or {}).get("chain") or []),
                "unavailable_reasons": list(self._pin.get("unavailable_reasons") or []),
            },
            "runtime_stable": not self._runtime_drift_paths,
            "runtime_drift": list(self._runtime_drift_paths),
            "provider": provider_name(self.config.signal_source),
            "signal_source": self.config.signal_source,
            "strategy_id": self.config.strategy_id
            if self.config.signal_source == SIGNAL_SOURCE_STRATEGY
            else None,
            "cycles_executed": len(executed),
            "cycles_blocked": blocked,
            "data_delay_ms": self._data_delay_ms,
            "data_delay_source": "PINNED_FROM_PREVIOUS_SESSION"
            if self._pinned_delay_ms is not None
            else "MEASURED_AT_SESSION_START",
            "data_delay_measured_now_ms": self._measured_delay_ms,
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
    "RuntimeNotProvable",
    "SessionAborted",
    "SessionIdentityMismatch",
    "aggregate_complete",
    "compare_prefix",
    "display_symbol",
    "runtime_hashes",
]
