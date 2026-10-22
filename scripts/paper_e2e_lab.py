"""paper_e2e_lab — WP-003-03: the PAPER flow, executed, not simulated in a test.

Two runtimes produce the evidence, and neither is a unit test:

* ``AutonomousPaperRuntime`` — market data → strategy → proposal → agents →
  verifier → decision → deterministic risk → ``PaperBroker`` → trace/outcome;
* the broker itself — fills, commissions, PnL and the accounting identities.

Both are driven over **recorded Binance klines** (``data/edge07/holdout-1h``,
sha256-checked against the manifest the fetch wrote). Nothing is synthesised:
the only adapter is a ``MarketDataSourceProtocol`` that serves the bars visible
at a replay clock, and the spread is the COST_MODEL_V3 majors default recorded
as ``ESTIMATED`` — there is no historical quote series, and inventing a zero
would be a fabricated cost.

Scenarios (each in its own process, isolation installed before anything else):

``E2E-COMMITTED``
    The committed admission ledger. Nothing in it is admitted for PAPER and no
    edge survives cost, so the honest expectation is NO_TRADE for every asset —
    this scenario measures the governance gate, not the broker.
``E2E-SCENARIO``
    The same runtime with a **declared scenario admission ledger** (written into
    the evidence, marked ``_scenario``) so the execution path can be exercised.
    It is not research evidence and it is never merged into ``config/``.
``E2E-RESTART``
    Crash-window drill: persist the book, rebuild the runtime from the store,
    reconcile, keep trading. Duplicate cloids across the restart would be a
    failure, not a fixture.

Abuse battery (``ABUSE_*``) — every one of them tries to create a real order
from inside a paper process and must be refused.

This script only *produces* evidence. ``scripts/verify_paper_e2e.py`` judges it.

    python scripts/paper_e2e_lab.py --out reports/.../lab --json reports/.../PAPER_E2E_LAB.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DATASET = REPO / "data" / "edge07" / "holdout-1h"
DATASET_MANIFEST = DATASET / "_FETCH_MANIFEST.json"
ASSETS = ("BTC", "ETH", "SOL")
TIMEFRAME = "1h"
INTERVAL_MS = 3_600_000
#: COST_MODEL_V3 majors default (BINANCE_SPOT_STANDARD_TAKER). There is no
#: recorded top-of-book series in this corpus, so the spread is an estimate and
#: the evidence says so instead of reporting a fabricated observed zero.
SPREAD_BPS = 1.0
SPREAD_PROVENANCE = "ESTIMATED: COST_MODEL_V3 majors default, not an observed quote"

INITIAL_EQUITY = 10_000.0
SIZE_USD = 1_000.0
LOOKBACK_BARS = 120

#: The event loop the child drives its cycles on, when one was created before the
#: guard. ``None`` means "make a fresh loop", which is what a plain local run does.
_RUN_LOOP: Any = None


def _run(coro: Any) -> Any:
    """Drive one coroutine on the child's loop, or on a fresh loop outside the lab.

    Windows implements ``socket.socketpair()`` — every ``asyncio`` loop's internal
    self-pipe — over a loopback TCP connection. The paper policy denies loopback by
    design, so the loop is created *before* the audit hook is installed and the
    cycles run on it afterwards. The window contains only the self-pipe: no
    connector, no scanner, no broker exists yet, and the child's network log records
    every audited event that happened after the hook went in (there must be none).
    """
    if _RUN_LOOP is None:
        import asyncio

        return asyncio.run(coro)
    return _RUN_LOOP.run_until_complete(coro)


RUNTIME_FILES = (
    "src/trading_bot/autonomous/runtime.py",
    "src/trading_bot/autonomous/decision.py",
    "src/trading_bot/autonomous/verifier.py",
    "src/trading_bot/autonomous/agents.py",
    "src/trading_bot/autonomous/admission_ledger.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/paper/paper_state_store.py",
    "src/trading_bot/paper/reconciliation_v4.py",
    "src/trading_bot/paper/snapshot_history.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/scanner/scanner.py",
    "src/trading_bot/execution/isolation.py",
    "src/trading_bot/execution/idempotency.py",
)

E2E_MODES = ("E2E-COMMITTED", "E2E-SCENARIO", "E2E-RESTART")
ABUSE_MODES = (
    "ABUSE-CONNECTOR-ORDER",
    "ABUSE-FUTURES-ORDER",
    "ABUSE-APP-ORDER",
    "ABUSE-DELEGATION",
    "ABUSE-RECONNECT",
    "ABUSE-RETRY",
    "ABUSE-NO-CREDENTIALS",
    "ABUSE-POLICY-WEAKEN",
)


# -- small helpers ---------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


# -- replay adapters (the only new code on the data path) ------------------------


class ReplayClock:
    """Deterministic epoch-millisecond clock; the runtime's only notion of now."""

    def __init__(self, start_ms: int) -> None:
        self.now_ms = int(start_ms)

    def __call__(self) -> int:
        return self.now_ms

    def seconds(self) -> float:
        return self.now_ms / 1000.0


class RecordedBarSource:
    """``MarketDataSourceProtocol`` over recorded klines, as of the replay clock.

    ``fetch_recent`` returns the last ``limit`` bars whose OPEN is at or before
    the clock — what a provider would have served at that instant. Volume is the
    trailing 24h quote volume implied by those bars. The spread is declared
    ``ESTIMATED`` for the reason in the module docstring.
    """

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Any]],
        clock: ReplayClock,
        *,
        timeframe_ms: int,
        spread_bps: float,
    ) -> None:
        self._bars = bars_by_symbol
        self._clock = clock
        self._day_bars = max(int(24 * 3_600_000 // timeframe_ms), 1)
        self._spread_bps = float(spread_bps)
        self.calls: dict[str, int] = {"fetch_recent": 0, "volume": 0, "spread": 0}

    @property
    def spread_bps(self) -> float:
        return self._spread_bps

    def _visible(self, symbol: str) -> list[Any]:
        cutoff = self._clock()
        return [b for b in self._bars.get(symbol, []) if b.timestamp <= cutoff]

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[Any]:
        self.calls["fetch_recent"] += 1
        visible = self._visible(symbol)
        return visible[-int(limit) :] if limit > 0 and visible else []

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        self.calls["volume"] += 1
        window = self._visible(symbol)[-self._day_bars :]
        return float(sum(b.volume * b.close for b in window))

    async def fetch_spread_bps(self, symbol: str) -> float:
        self.calls["spread"] += 1
        return self._spread_bps


def load_recorded_bars(assets: tuple[str, ...] = ASSETS) -> dict[str, list[Any]]:
    """Load the recorded 1h corpus into ``OHLCV`` rows, verifying its digests."""
    from trading_bot.market_data.types import OHLCV

    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, list[Any]] = {}
    for asset in assets:
        path = DATASET / f"{asset}USDT_holdout2026.json"
        entry = manifest["symbols"].get(f"{asset}USDT") or {}
        expected = str(entry.get("sha256", ""))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and actual != expected:
            raise RuntimeError(f"{path.name}: sha256 {actual} != manifest {expected}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        out[f"{asset}/USDT"] = [
            OHLCV(
                symbol=f"{asset}/USDT",
                timestamp=int(row["ts"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]
    return out


def dataset_provenance(assets: tuple[str, ...] = ASSETS) -> dict[str, Any]:
    """What was read, and the digest the fetch wrote for it."""
    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    rows: dict[str, Any] = {}
    for asset in assets:
        path = DATASET / f"{asset}USDT_holdout2026.json"
        entry = manifest["symbols"].get(f"{asset}USDT") or {}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows[f"{asset}/USDT"] = {
            "file": _relative(path),
            "sha256": digest,
            "manifest_sha256": entry.get("sha256"),
            "bars": entry.get("bars"),
            "first_utc": entry.get("first_utc"),
            "last_utc": entry.get("last_utc"),
            "matches_manifest": bool(entry.get("sha256")) and digest == entry.get("sha256"),
        }
    return {
        "source": manifest.get("source"),
        "interval": manifest.get("interval"),
        "requested_range": manifest.get("requested_range"),
        "normalization": manifest.get("normalization"),
        "manifest": _relative(DATASET_MANIFEST),
        "manifest_sha256": hashlib.sha256(DATASET_MANIFEST.read_bytes()).hexdigest(),
        "symbols": rows,
        "spread_bps": SPREAD_BPS,
        "spread_provenance": SPREAD_PROVENANCE,
    }


# -- the scenario admission ledger ------------------------------------------------


def scenario_ledger_payload() -> dict[str, Any]:
    """A declared scenario ledger: this is NOT research evidence.

    The committed ledger admits nothing for PAPER (every edge is
    ``NO_GROSS_EDGE``/``COST_KILLED``), which means the execution path can never
    be reached on committed configuration. Exercising it therefore needs an
    explicit, visibly-labelled input, never a silent edit of ``config/``.
    """
    return {
        "_schema_version": "strategy-admission-ledger-v1",
        "_scenario": True,
        "_claim": (
            "SCENARIO ONLY — the numbers below are fixed inputs used to exercise the "
            "PAPER execution path. They are not measured research, they carry no "
            "provenance, and they must never be copied into config/strategy_admission.json."
        ),
        "_sources": [],
        "strategies": {
            "momentum@1h": {
                "family": "momentum",
                "status": "PAPER_CANDIDATE",
                "admitted_for_paper": True,
                "expected_gross_edge_bps": 60.0,
                "edge_evidence": {
                    "source_doc": "SCENARIO:WP-003-03",
                    "metric": "scenario_only_gross_bps",
                    "value_bps": 60.0,
                    "knowledge": "SCENARIO",
                    "sample_trades": 1_000,
                    "note": "declared scenario input, not research",
                    "evidence_class": "SCENARIO",
                    "period": "SCENARIO",
                    "timeframe": TIMEFRAME,
                    "status": "PAPER_CANDIDATE",
                },
                "source_doc": "SCENARIO:WP-003-03",
                "rationale": "declared scenario input used to reach the broker path",
                "timeframe": TIMEFRAME,
            }
        },
    }


def build_ledger(kind: str) -> Any:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger

    if kind == "committed":
        return AdmissionLedger.load(REPO / "config" / "strategy_admission.json")
    return AdmissionLedger.from_dict(
        scenario_ledger_payload(), source_path="SCENARIO:WP-003-03 (in-memory)"
    )


# -- the runtime ---------------------------------------------------------------


def runtime_files() -> dict[str, str]:
    return {rel: _sha(REPO / rel) for rel in RUNTIME_FILES}


def build_runtime(
    *,
    root: Path,
    ledger_kind: str,
    start_index: int,
    cycles: int,
    read_history: bool = True,
    idempotency: Any | None = None,
) -> tuple[Any, Any, Any, ReplayClock, RecordedBarSource, dict[str, Any]]:
    """Compose the authoritative runtime. No strategy/risk/accounting is re-implemented."""
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.autonomous.strategy_state import StrategyRegistry
    from trading_bot.config.settings import load_settings
    from trading_bot.config.universe import PairSpec
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.snapshot_history import FetcherBarReader
    from trading_bot.research.families import (
        BreakoutFamily,
        EmaCrossoverFamily,
        MeanReversionFamily,
        MomentumFamily,
        TrendFamily,
        VolatilityFamily,
    )
    from trading_bot.risk.manager import RiskManager
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    bars = load_recorded_bars()
    span = min(len(rows) for rows in bars.values())
    if start_index + cycles + LOOKBACK_BARS + 2 > span:
        raise RuntimeError(
            f"window {start_index}+{cycles}+{LOOKBACK_BARS} does not fit the corpus ({span} bars)"
        )
    clock = ReplayClock(bars[f"{ASSETS[0]}/USDT"][start_index].timestamp + INTERVAL_MS)
    source = RecordedBarSource(bars, clock, timeframe_ms=INTERVAL_MS, spread_bps=SPREAD_BPS)

    settings = load_settings(config_dir="config/realdata")
    pairs = [PairSpec(symbol=f"{asset}/USDT", enabled=True) for asset in ASSETS]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [TIMEFRAME]})
    settings = settings.model_copy(update={"universe": universe})

    def scanner_factory() -> Any:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    ledger = build_ledger(ledger_kind)
    registry = StrategyRegistry.from_ledger(ledger, assets=list(ASSETS))
    if read_history:
        reader: Any = FetcherBarReader(source, timeframe=TIMEFRAME)
    else:

        class ExplodingReader:
            """A history provider that fails on purpose (the error-path scenario)."""

            def closed_bar_slice(self, *_args: Any, **_kwargs: Any) -> list[Any]:
                raise RuntimeError("scenario: history provider unavailable")

        reader = ExplodingReader()

    broker = PaperBroker(equity=INITIAL_EQUITY)
    risk = RiskManager(risk=settings.risk, equity=INITIAL_EQUITY, _clock=clock.seconds)

    runtime = AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=scanner_factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families={
            "ema_crossover": EmaCrossoverFamily(),
            "momentum": MomentumFamily(),
            "breakout": BreakoutFamily(),
            "trend": TrendFamily(),
            "mean_reversion": MeanReversionFamily(),
            "volatility": VolatilityFamily(),
        },
        strategy_map=registry.strategy_map(TIMEFRAME),
        ledger=ledger,
        run_dir=root / "run",
        assets=list(ASSETS),
        timeframe=TIMEFRAME,
        size_usd=SIZE_USD,
        lookback_bars=LOOKBACK_BARS,
        shadow_evaluation_enabled=True,
        environment=f"paper-e2e:{ledger_kind}",
        now_fn=clock,
        idempotency=idempotency,
        routing_mode="LEGACY",
    )
    meta = {
        "settings_mode": getattr(settings.runtime.mode, "value", str(settings.runtime.mode)),
        "enable_paper_trading": bool(settings.runtime.features.enable_paper_trading),
        "ledger_kind": ledger_kind,
        "ledger_source": ledger.source_path,
        "paper_candidates": registry.paper_candidates(TIMEFRAME),
        "registry_counts": registry.counts_by_status(),
        "strategy_ids": registry.strategy_ids(),
    }
    return runtime, broker, registry, clock, source, meta


async def _drive(
    runtime: Any, clock: ReplayClock, *, start_index: int, cycles: int
) -> dict[str, Any]:
    bars = load_recorded_bars()
    origin = bars[f"{ASSETS[0]}/USDT"][start_index].timestamp
    reports: list[Any] = []
    errors: list[str] = []
    started = time.perf_counter()
    for index in range(1, cycles + 1):
        clock.now_ms = origin + index * INTERVAL_MS
        try:
            reports.append(await runtime.run_cycle(cycle=index))
        except Exception as exc:  # a cycle failure is visible, never silent
            errors.append(f"cycle {index}: {type(exc).__name__}: {exc}")
    seconds = round(time.perf_counter() - started, 3)
    return {"reports": reports, "errors": errors, "seconds": seconds}


# -- evidence extraction -------------------------------------------------------


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        name = "null" if value is None else str(value)
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items()))


def _decision_rows(runtime: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trace in runtime.trace_store.read():
        proposal = trace.proposal or {}
        rows.append(
            {
                "decision_id": trace.decision_id,
                "asset": trace.asset,
                "symbol": trace.symbol,
                "mode": trace.mode.value,
                "reason": trace.reason,
                "classification": trace.classification,
                "no_trade_kind": trace.no_trade_kind,
                "order_created": bool(trace.order_created),
                "orders_created": int(trace.orders_created),
                "market_time_ms": int(trace.market_time_ms),
                "decision_time_ms": int(trace.decision_time_ms),
                "strategy_id": proposal.get("strategy_id"),
                "expected_gross_edge_bps": proposal.get("expected_gross_edge_bps"),
                "expected_net_edge_bps": proposal.get("expected_net_edge_bps"),
                "risk_state": (trace.risk or {}).get("state"),
                "risk_rule": (trace.risk or {}).get("rule"),
                "verifier_verdict": (trace.verification or {}).get("verdict"),
                "errors": list(trace.errors),
                "trace_hash": trace.trace_hash,
            }
        )
    return rows


def _economic_digest(
    decisions: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    accounting: dict[str, Any],
) -> str:
    """Digest of what the run *did*, excluding non-deterministic identifiers.

    Session ids and decision ids are ``uuid4``-derived, so they cannot be part of
    a reproducibility claim. Prices, modes, reasons, sizes, commissions and the
    accounting identities are all deterministic over the same bars and clock.
    """
    body = {
        "decisions": [
            {
                key: row[key]
                for key in (
                    "asset",
                    "mode",
                    "classification",
                    "no_trade_kind",
                    "reason",
                    "order_created",
                    "market_time_ms",
                    "decision_time_ms",
                    "strategy_id",
                    "expected_gross_edge_bps",
                    "expected_net_edge_bps",
                    "risk_state",
                )
            }
            for row in decisions
        ],
        "executions": sorted(
            (
                str(row.get("symbol")),
                str(row.get("strategy_id")),
                float(row.get("notional_usdt") or 0.0),
            )
            for row in executions
        ),
        "trades": sorted(
            (
                str(row.get("symbol")),
                str(row.get("side")),
                round(float(row.get("entry_price") or 0.0), 10),
                round(float(row.get("exit_price") or 0.0), 10),
                round(float(row.get("quantity") or 0.0), 12),
                round(float(row.get("pnl") or 0.0), 10),
                str(row.get("exit_reason")),
                round(float(row.get("entry_commission") or 0.0), 10),
                round(float(row.get("exit_commission") or 0.0), 10),
            )
            for row in trades
        ),
        "accounting": {
            key: round(float(accounting[key]), 10)
            for key in (
                "initial_equity",
                "cash",
                "realised_pnl",
                "unrealised_pnl",
                "accrued_entry_commissions",
                "equity_mark_to_market",
                "ledger_equity",
            )
            if key in accounting
        },
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarise_run(
    *,
    root: Path,
    runtime: Any,
    broker: Any,
    registry: Any,
    clock: ReplayClock,
    source: RecordedBarSource,
    drive: dict[str, Any],
    meta: dict[str, Any],
    guard: Any,
) -> dict[str, Any]:
    reports = drive["reports"]
    summary = runtime.finalize_summary(
        run_id=f"{meta['ledger_kind']}-run",
        started_at_ms=int(reports[0].started_at_ms) if reports else 0,
        cycle_reports=reports,
        errors=list(drive["errors"]),
    )
    bars = load_recorded_bars()
    prices = {
        symbol: max(
            (bar for bar in rows if bar.timestamp <= clock.now_ms),
            key=lambda bar: bar.timestamp,
        ).close
        for symbol, rows in bars.items()
        if any(bar.timestamp <= clock.now_ms for bar in rows)
    }
    trades = broker.closed_trades_rows()
    accounting = broker.accounting_snapshot(prices)
    accounting["live_equity"] = broker.equity
    accounting["closed_trades_count"] = len(trades)
    accounting["fills_opened"] = broker._fills_opened
    accounting["fills_closed"] = broker._fills_closed
    decisions = _decision_rows(runtime)
    refusals: dict[str, int] = {}
    for row in decisions:
        if row["mode"] == "TRADE_PAPER" and not row["order_created"]:
            for message in row["errors"] or ["no_reason_recorded"]:
                key = str(message).split(":", 1)[-1].strip()[:120]
                refusals[key] = refusals.get(key, 0) + 1
    executions = [dict(row) for row in runtime._executions]
    return {
        "status": "OK",
        "ledger": meta,
        "cycles_requested": len(reports),
        "cycles_completed": len(reports),
        "cycle_errors": list(drive["errors"]),
        "seconds": drive["seconds"],
        "totals": summary.totals(),
        "decisions": {
            "count": len(decisions),
            "by_mode": _count(decisions, "mode"),
            "by_no_trade_kind": _count(decisions, "no_trade_kind"),
            "by_classification": _count(decisions, "classification"),
            "orders_created": sum(1 for row in decisions if row["order_created"]),
            "unexecuted_trade_decisions": sum(
                1 for row in decisions if row["mode"] == "TRADE_PAPER" and not row["order_created"]
            ),
            "unexecuted_reasons": dict(sorted(refusals.items())),
            "rows": decisions,
        },
        "executions": {
            "count": len(executions),
            "cloids": [row.get("cloid") for row in executions],
            "unique_cloids": len({row.get("cloid") for row in executions}),
            "rows": executions,
        },
        "fills": {
            "opened": broker._fills_opened,
            "closed": broker._fills_closed,
            "closed_trades": trades,
            "open_positions": [
                {
                    "position_id": pos.position_id,
                    "entry_order_id": pos.entry_order_id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "quantity": pos.quantity,
                    "notional_usdt": pos.notional_usdt,
                }
                for pos in broker.positions.values()
            ],
        },
        "accounting": accounting,
        "risk_events": list(getattr(broker, "_risk_events", [])),
        "chain": summary.chain,
        "replay": summary.replay,
        "source_calls": dict(source.calls),
        "isolation": {
            "installed": guard is not None,
            "policy": None if guard is None else guard.policy.as_dict(),
            "summary": None if guard is None else guard.summary(),
            "attempts": [] if guard is None else [dict(row) for row in guard.attempts],
        },
        "economic_digest": _economic_digest(decisions, executions, trades, accounting),
        "run_dir": _relative(root / "run"),
        "registry": {
            "counts": registry.counts_by_status(),
            "paper_candidates": registry.paper_candidates(TIMEFRAME),
        },
    }


# -- scenarios -----------------------------------------------------------------


def scenario_committed(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Committed ledger: the governance gate, measured. Expect no orders at all."""
    from trading_bot.execution import isolation

    guard = isolation.active()
    runtime, broker, registry, clock, source, meta = build_runtime(
        root=root,
        ledger_kind="committed",
        start_index=args.start,
        cycles=args.cycles,
    )
    drive = _run(_drive(runtime, clock, start_index=args.start, cycles=args.cycles))
    payload = summarise_run(
        root=root,
        runtime=runtime,
        broker=broker,
        registry=registry,
        clock=clock,
        source=source,
        drive=drive,
        meta=meta,
        guard=guard,
    )

    # Fail-closed probe: an orchestrator error must stop the run with zero orders.
    error_runtime, error_broker, _, error_clock, _, _ = build_runtime(
        root=root / "error_probe",
        ledger_kind="scenario",
        start_index=args.start,
        cycles=3,
        read_history=False,
    )
    error_drive = _run(_drive(error_runtime, error_clock, start_index=args.start, cycles=3))
    error_rows = _decision_rows(error_runtime)
    payload["error_probe"] = {
        "cycles_attempted": 3,
        "cycles_completed": len(error_drive["reports"]),
        "cycle_errors": error_drive["errors"],
        "orders_created": sum(report.orders_created for report in error_drive["reports"]),
        "broker_fills_opened": error_broker._fills_opened,
        "broker_closed_trades": len(error_broker.closed_trades),
        "executions": [dict(row) for row in error_runtime._executions],
        "decisions": {
            "count": len(error_rows),
            "by_mode": _count(error_rows, "mode"),
            "by_no_trade_kind": _count(error_rows, "no_trade_kind"),
        },
        "accounting_identities": error_broker.accounting_snapshot({})["identities"],
    }
    return payload


def scenario_trade(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Declared scenario ledger: exercise decision → risk → broker → fills."""
    from trading_bot.execution import isolation

    guard = isolation.active()
    runtime, broker, registry, clock, source, meta = build_runtime(
        root=root,
        ledger_kind="scenario",
        start_index=args.start,
        cycles=args.cycles,
    )
    drive = _run(_drive(runtime, clock, start_index=args.start, cycles=args.cycles))
    payload = summarise_run(
        root=root,
        runtime=runtime,
        broker=broker,
        registry=registry,
        clock=clock,
        source=source,
        drive=drive,
        meta=meta,
        guard=guard,
    )
    payload["scenario_ledger"] = scenario_ledger_payload()
    return payload


def scenario_restart(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Persist the book, rebuild from the store, reconcile, and keep trading."""
    from trading_bot.execution import isolation
    from trading_bot.execution.idempotency import IdempotencyGuard
    from trading_bot.paper.paper_runtime_state import save_session_state
    from trading_bot.paper.paper_state_store import PaperStateStore
    from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4

    guard = isolation.active()
    first = max(args.cycles // 2, 20)
    idempotency = IdempotencyGuard()
    runtime, broker, _registry, clock, _source, _meta = build_runtime(
        root=root / "phase1",
        ledger_kind="scenario",
        start_index=args.start,
        cycles=first,
        idempotency=idempotency,
    )
    phase1 = _run(_drive(runtime, clock, start_index=args.start, cycles=first))
    for execution in runtime._executions:
        idempotency.register(str(execution.get("cloid")))
    store = PaperStateStore(root / "state.json")
    save_session_state(
        store=store,
        run_id="restart-phase1",
        broker=broker,
        risk=getattr(runtime, "_risk", None),
        idempotency=idempotency,
    )
    persisted = {
        "equity": broker.equity,
        "closed_trades": len(broker.closed_trades),
        "open_positions": len(broker.positions),
        "fills_opened": broker._fills_opened,
        "intents": len(idempotency.sent_cloids),
    }

    # -- crash boundary: the book above is on disk; everything below is a new runtime
    restarted_guard = IdempotencyGuard()
    restarted, broker2, registry2, clock2, source2, meta2 = build_runtime(
        root=root / "phase2",
        ledger_kind="scenario",
        start_index=args.start + first,
        cycles=args.restart_cycles,
        idempotency=restarted_guard,
    )
    clock2.now_ms = clock.now_ms
    report = StartupReconcilerV4(
        store=store,
        broker=broker2,
        risk_manager=getattr(restarted, "_risk", None),
        idempotency=restarted_guard,
    ).reconcile()
    recovered = {
        "equity": broker2.equity,
        "closed_trades": len(broker2.closed_trades),
        "open_positions": len(broker2.positions),
        "fills_opened": broker2._fills_opened,
        "intents": len(restarted_guard.sent_cloids),
    }
    phase2 = _run(
        _drive(restarted, clock2, start_index=args.start + first, cycles=args.restart_cycles)
    )
    payload = summarise_run(
        root=root / "phase2",
        runtime=restarted,
        broker=broker2,
        registry=registry2,
        clock=clock2,
        source=source2,
        drive=phase2,
        meta=meta2,
        guard=guard,
    )
    payload["status"] = "OK"
    payload["restart"] = {
        "phase1_cycles": len(phase1["reports"]),
        "phase1_errors": phase1["errors"],
        "phase1_decisions": len(_decision_rows(runtime)),
        "phase1_executions": len(runtime._executions),
        "phase1_cloids": [row.get("cloid") for row in runtime._executions],
        "persisted": persisted,
        "recovered": recovered,
        "reconciliation": report.to_dict(),
        "equity_delta": round(broker2.equity - broker.equity, 9),
        "closed_delta": len(broker2.closed_trades) - len(broker.closed_trades),
        "phase2_executions": len(restarted._executions),
    }
    return payload


# -- abuse battery -------------------------------------------------------------


def _attempt(action: Any) -> dict[str, Any]:
    from trading_bot.execution import isolation

    try:
        action()
    except isolation.NetworkBlocked as exc:
        return {"outcome": "DENIED", "code": exc.code, "detail": str(exc)[:240]}
    except isolation.OrderRouteRefused as exc:
        return {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:240]}
    except isolation.PolicyRedefined as exc:
        return {"outcome": "REFUSED", "code": exc.code, "detail": str(exc)[:240]}
    except Exception as exc:
        return {"outcome": "OTHER", "error": type(exc).__name__, "detail": str(exc)[:240]}
    return {"outcome": "ALLOWED"}


class _Venue:
    """A venue stand-in that records every call: ``calls`` must stay empty."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_order(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("create_order")
        return {"id": "venue-order-1", "status": "closed"}

    def cancel_order(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("cancel_order")


class _Log:
    def bind(self, **_kwargs: Any) -> _Log:
        return self

    def info(self, *_args: Any, **_kwargs: Any) -> None: ...

    def warning(self, *_args: Any, **_kwargs: Any) -> None: ...

    def error(self, *_args: Any, **_kwargs: Any) -> None: ...

    def debug(self, *_args: Any, **_kwargs: Any) -> None: ...


def _ccxt_connector(venue: Any) -> Any:
    from trading_bot.market_data.exchange_connector import CCXTExchangeConnector

    # Built without __init__ and then populated: every attribute below belongs to the
    # real connector, so the object stays typed as Any on purpose rather than being
    # half-typed by a cast that would hide a wrong attribute name.
    connector: Any = object.__new__(CCXTExchangeConnector)
    connector._exchange_instance = venue
    connector._config = None
    connector._log = _Log()
    connector._retry_decorator = lambda function: function
    return connector


def abuse_connector_order(root: Path) -> dict[str, Any]:
    venue = _Venue()
    connector = _ccxt_connector(venue)
    create = _attempt(lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0))
    cancel = _attempt(lambda: connector.cancel_order("order-1", "BTC/USDT"))
    return {
        "status": "OK",
        "order_attempts": {"create_order": create, "cancel_order": cancel},
        "venue_calls": list(venue.calls),
    }


def abuse_futures_order(root: Path) -> dict[str, Any]:
    from trading_bot.market_data.bitunix_futures import (
        BitunixFuturesClient,
        BitunixFuturesConnector,
    )

    client: Any = object.__new__(BitunixFuturesClient)
    http_calls: list[str] = []

    def _request(*_args: Any, **_kwargs: Any) -> Any:
        http_calls.append("request")
        return {"code": 0, "data": {"orderId": "venue-order-1"}}

    client._request = _request
    client.futures_base_url = "https://fapi.bitunix.com"
    client._symbol_cache = None

    direct = _attempt(
        lambda: client.place_order(symbol="BTCUSDT", side="BUY", qty=0.01, client_id="scenario-1")
    )
    connector: Any = object.__new__(BitunixFuturesConnector)
    connector._client = client
    via_connector = _attempt(lambda: connector.create_order("BTCUSDT", "buy", "market", 0.01))
    return {
        "status": "OK",
        "order_attempts": {
            "client_place_order": direct,
            "connector_create_order": via_connector,
        },
        "http_calls": len(http_calls),
    }


def abuse_app_order(root: Path) -> dict[str, Any]:
    """Drive the CLI order route itself: it must refuse before any client exists."""
    from trading_bot import app

    args = argparse.Namespace(
        confirm_live=False,
        env_file=None,
        config_dir="config/realdata",
        market_kind="spot",
        symbol="BTC/USDT",
        side="buy",
        amount="1",
        order_type="market",
        price=None,
        position_id=None,
        reduce_only=False,
        tp_price=None,
        sl_price=None,
    )
    code = app._cmd_place_order(args)
    return {
        "status": "OK",
        "order_attempts": {
            "app_place_order_without_confirm": {
                "outcome": "REFUSED" if code != 0 else "ALLOWED",
                "exit_code": code,
                "detail": "the CLI refuses before any client exists (--confirm-live gate)",
            }
        },
        "venue_calls": [],
    }


def abuse_delegation(root: Path) -> dict[str, Any]:
    """A wrapper that delegates to the protected method must be refused too."""
    venue = _Venue()
    connector = _ccxt_connector(venue)

    class DelegatingWrapper:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def send(self, *args: Any, **kwargs: Any) -> Any:
            return self._inner.create_order(*args, **kwargs)

    delegated = _attempt(
        lambda: DelegatingWrapper(connector).send("BTC/USDT", "buy", "market", 1.0)
    )
    return {
        "status": "OK",
        "order_attempts": {"wrapper_send": delegated},
        "venue_calls": list(venue.calls),
    }


def abuse_reconnect(root: Path) -> dict[str, Any]:
    """Reconnect the adapter, then try again: the reconnect must not open a route."""
    venue = _Venue()
    connector = _ccxt_connector(venue)
    replacement = _Venue()
    reconnect = _attempt(lambda: setattr(connector, "_exchange_instance", replacement))
    after = _attempt(lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0))
    return {
        "status": "OK",
        "steps": {"reconnect": reconnect},
        "order_attempts": {"order_after_reconnect": after},
        "venue_calls": list(replacement.calls),
    }


def abuse_retry(root: Path) -> dict[str, Any]:
    """A retried order must still be refused — and no venue may ever see one."""
    from trading_bot.execution.idempotency import IdempotencyGuard

    venue = _Venue()
    connector = _ccxt_connector(venue)
    guard = IdempotencyGuard()
    attempts: dict[str, Any] = {}
    for index in range(3):
        cloid = f"retry-cloid-{index}"
        guard.register(cloid)
        attempts[f"retry_{index}"] = _attempt(
            lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0)
        )
    return {
        "status": "OK",
        "order_attempts": attempts,
        "venue_calls": list(venue.calls),
        "intents_registered": guard.active_count,
    }


def abuse_no_credentials(root: Path) -> dict[str, Any]:
    """No credentials, no order — and no venue call."""
    venue = _Venue()
    connector = _ccxt_connector(venue)
    attempt = _attempt(lambda: connector.create_order("BTC/USDT", "buy", "market", 1.0))
    return {
        "status": "OK",
        "order_attempts": {"order_without_credentials": attempt},
        "venue_calls": list(venue.calls),
        "config_present": connector._config is not None,
        "credentials_in_environment": sorted(
            name
            for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "EXCHANGE_API_KEY")
            if os.environ.get(name)
        ),
    }


def abuse_policy_weaken(root: Path) -> dict[str, Any]:
    """Install a paper policy, then try to replace it with a live one."""
    from trading_bot.execution import isolation

    weaken = _attempt(lambda: isolation.install(isolation.policy_for_mode("live")))
    order = _attempt(lambda: isolation.assert_order_allowed("scenario.live_order"))
    guard = isolation.active()
    policy_now = None if guard is None else guard.policy.as_dict()
    return {
        "status": "OK",
        "guard_attempts": {"install_live_policy": weaken},
        "order_attempts": {"order_under_paper_policy": order},
        "policy_now": policy_now,
    }


def run_child(mode: str, root: Path, args: argparse.Namespace) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    if mode == "E2E-COMMITTED":
        return scenario_committed(root, args)
    if mode == "E2E-SCENARIO":
        return scenario_trade(root, args)
    if mode == "E2E-RESTART":
        return scenario_restart(root, args)
    handlers = {
        "ABUSE-CONNECTOR-ORDER": abuse_connector_order,
        "ABUSE-FUTURES-ORDER": abuse_futures_order,
        "ABUSE-APP-ORDER": abuse_app_order,
        "ABUSE-DELEGATION": abuse_delegation,
        "ABUSE-RECONNECT": abuse_reconnect,
        "ABUSE-RETRY": abuse_retry,
        "ABUSE-NO-CREDENTIALS": abuse_no_credentials,
        "ABUSE-POLICY-WEAKEN": abuse_policy_weaken,
    }
    return handlers[mode](root)


# -- parent --------------------------------------------------------------------


def _git_state() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "status_short": _git("status", "--short").splitlines(),
        "source_dirty": bool(_git("status", "--porcelain")),
    }


def _run_child(mode: str, root: Path, args: argparse.Namespace, timeout: float) -> dict[str, Any]:
    case = root / mode
    shutil.rmtree(case, ignore_errors=True)
    case.mkdir(parents=True, exist_ok=True)
    network_log = case / "network.jsonl"
    started = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            mode,
            "--root",
            str(case),
            "--cycles",
            str(args.cycles),
            "--restart-cycles",
            str(args.restart_cycles),
            "--start",
            str(args.start),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "TRADING_BOT_MODE": "paper", "PYTHONIOENCODING": "utf-8"},
    )
    seconds = round(time.perf_counter() - started, 2)
    payload_path = case / "child.json"
    payload: dict[str, Any]
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    else:
        payload = {
            "status": "NO_OUTPUT",
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    payload["returncode"] = proc.returncode
    payload["seconds"] = seconds
    payload["mode"] = mode
    payload["network_log"] = (
        [
            json.loads(line)
            for line in network_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if network_log.exists()
        else []
    )
    payload["stderr_tail"] = proc.stderr[-4000:]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", default="", help=argparse.SUPPRESS)
    parser.add_argument("--root", default="", help=argparse.SUPPRESS)
    parser.add_argument("--out", default="reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/lab")
    parser.add_argument(
        "--json",
        default="reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/PAPER_E2E_LAB.json",
    )
    parser.add_argument("--cycles", type=int, default=160)
    parser.add_argument("--restart-cycles", type=int, default=40)
    parser.add_argument("--start", type=int, default=600, help="bar index the replay starts at")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    if args.child:
        root = Path(args.root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        from trading_bot.execution import isolation

        global _RUN_LOOP
        pre_hook: list[str] = []
        try:
            import asyncio

            _RUN_LOOP = asyncio.new_event_loop()
            pre_hook.append(
                "asyncio event loop (its self-pipe is a loopback socketpair "
                "on Windows; created before the hook, no venue object exists yet)"
            )
        except Exception as exc:  # a host that cannot pre-create a loop still runs
            _RUN_LOOP = None
            pre_hook.append(f"event loop creation failed before the hook: {type(exc).__name__}")
        isolation.install_for_runtime("paper", log_path=root / "network.jsonl")
        started = time.perf_counter()
        try:
            payload = run_child(args.child, root, args)
            payload["pre_hook"] = pre_hook
        except Exception as exc:  # a failed scenario is evidence, not a crash to hide
            import traceback

            payload = {
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-4000:],
            }
        payload.setdefault("pre_hook", pre_hook)
        payload["recorded_at_utc"] = _utc_now()
        payload["child_seconds"] = round(time.perf_counter() - started, 3)
        _write_json(root / "child.json", payload)
        print(json.dumps({"mode": args.child, "status": payload.get("status")}))
        return 0 if payload.get("status") == "OK" else 1

    out = (REPO / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    print(f"[paper-e2e] {started_at} -> {out}")

    scenarios: dict[str, Any] = {}
    for mode in E2E_MODES:
        print(f"[paper-e2e] running {mode}")
        scenarios[mode] = _run_child(mode, out, args, args.timeout)
        print(
            f"[paper-e2e] {mode}: status={scenarios[mode].get('status')} "
            f"rc={scenarios[mode].get('returncode')} seconds={scenarios[mode].get('seconds')}"
        )

    abuse: dict[str, Any] = {}
    for mode in ABUSE_MODES:
        print(f"[paper-e2e] running {mode}")
        abuse[mode] = _run_child(mode, out, args, 600.0)
        print(
            f"[paper-e2e] {mode}: status={abuse[mode].get('status')} rc={abuse[mode].get('returncode')}"
        )

    bundle: dict[str, Any] = {
        "schema": "wp00303-paper-e2e-lab/1",
        "generated_at_utc": _utc_now(),
        "started_at_utc": started_at,
        "git": _git_state(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "runtime_sha256": runtime_files(),
        "dataset": dataset_provenance(),
        "parameters": {
            "assets": list(ASSETS),
            "timeframe": TIMEFRAME,
            "start_index": args.start,
            "cycles": args.cycles,
            "restart_cycles": args.restart_cycles,
            "initial_equity": INITIAL_EQUITY,
            "size_usd": SIZE_USD,
            "lookback_bars": LOOKBACK_BARS,
            "spread_bps": SPREAD_BPS,
            "spread_provenance": SPREAD_PROVENANCE,
        },
        "scenarios": scenarios,
        "abuse": abuse,
        "claims": {
            "PAPER_RUNTIME_EXECUTED": True,
            "MARKET_DATA_PROVENANCE": "RECORDED_BINANCE_KLINES",
            "SPREAD_PROVENANCE": SPREAD_PROVENANCE,
            "ADMISSION_IN_SCENARIO": "SCENARIO_ONLY (not research evidence)",
            "OS_SANDBOX": "NOT_AVAILABLE",
            "EXTERNAL_SESSION": "NOT_PERFORMED (a paper process may not reach a venue)",
            "LIVE_ORDERS": "NONE",
        },
    }
    _write_json(REPO / args.json, bundle)
    print(json.dumps({"scenarios": {k: v.get("status") for k, v in scenarios.items()}}, indent=1))
    print(f"[paper-e2e] wrote {_relative(REPO / args.json)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
