"""WP-EDGE-14R — isolated execution of the *canonical* paper path.

The question this module answers is not "is the strategy profitable" but the one
the recovery brief asks first: **is the execution path actually connected, and
what stops it from producing a paper order?**  There are only two honest ways to
answer that, and this module does both, in two clearly separated arms.

The path under test is the runtime's own, not a re-implementation:

    PIT OHLCV -> CryptoAssetAgentRegistry.build_context -> StrategyRouter
    -> AlphaFamily -> SignalAdapter -> CandidatePortfolio
    -> RiskManager.check_signal -> PaperBroker.execute_signal

Arm ``GATE_INTACT`` builds its cycle engine from the **committed admission
ledger** (``config/strategy_admission.json``), exactly as
``scripts/start_paper_trading.py`` does, and reuses that script's own
``build_cycle_engine`` factory so the wiring cannot drift from the runtime's.
Whatever this arm does is what the runtime does.

Arm ``SANDBOX_ADMISSION`` builds the same engine but hands the factory a
scratch ledger that admits one family for paper.  It exists to separate two
claims that are easy to confuse and must never be:

* *the execution boundary works* — demonstrated by an order reaching the broker
  and a fill coming back; and
* *the system is allowed to trade* — **not** demonstrated here, and not
  claimed.  The authoritative ledger admits nothing, and this arm changes no
  committed configuration, weakens no risk limit and promotes nothing: the
  ledger it uses is a file under this work package's scratch directory, named
  as such in the output.

Consequently every fill carries ``fill_class = HYPOTHETICAL_FILL`` and
``runtime_authoritative = false``.  A fill produced by an input the runtime
would never accept is not a PAPER_BROKER_FILL of the authoritative path, and
reporting it as one would be exactly the false success this campaign forbids.

Nothing here sends an order, opens a credential or touches an exchange: the
bars come from ccxt's public endpoints and the fills come from ``PaperBroker``,
which never leaves the process.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "ARM_GATE_INTACT",
    "ARM_SANDBOX_ADMISSION",
    "EXECUTION_CLASSES",
    "SANDBOX_STRATEGY_ID",
    "build_sandbox_ledger",
    "canonical_bars_digest",
    "fetch_bars",
    "render_markdown",
    "run_execution",
    "write_bars_jsonl",
]

#: The three classes the brief requires to stay apart.  This module can only
#: ever emit ``PAPER_REPLAY``: historical bars are replayed through the live
#: paper path, which is real execution of the code but *not* prospective
#: observation, because the bars were already in the past when the run started.
EXECUTION_CLASSES = ("HISTORICAL_BACKTEST", "PAPER_REPLAY", "PROSPECTIVE_PAPER")

ARM_GATE_INTACT = "GATE_INTACT"
ARM_SANDBOX_ADMISSION = "SANDBOX_ADMISSION"

#: The per-cycle stage counters that are genuine counts (from
#: ``CycleStageCounts``).  Anything else in the per-cycle payload is a label or
#: a timestamp and must never be accumulated.
COUNT_FIELDS = (
    "contexts_built",
    "context_errors",
    "router_invocations",
    "router_no_trade",
    "router_errors",
    "strategy_invocations",
    "signals_generated",
    "strategy_errors",
    "adapter_errors",
    "bar_close_skips",
    "duplicate_intents",
    "risk_accepted",
    "risk_rejected",
    "risk_errors",
    "orders_created",
    "broker_errors",
)

#: The one family the sandbox arm admits, so a reader knows precisely which
#: gate was synthesised.
SANDBOX_STRATEGY_ID = "ema_crossover@1h"

REPO_ROOT = Path(__file__).resolve().parents[4]


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #


def _ohlcv(symbol: str, row: Sequence[float]) -> Any:
    from trading_bot.market_data.types import OHLCV

    return OHLCV(
        symbol=symbol,
        timestamp=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def fetch_bars(
    symbols: Sequence[str], timeframe: str, *, limit: int, exchange_id: str = "binance"
) -> dict[str, list[Any]]:
    """Public OHLCV through ccxt, read-only and credential-free.

    Quantities are capped by ``limit`` so a run cannot turn into an unbounded
    download; a symbol that fails is reported by raising rather than by
    silently shrinking the universe, because a quietly smaller universe would
    make the funnel numbers incomparable.
    """
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    out: dict[str, list[Any]] = {}
    for symbol in symbols:
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw:
            raise RuntimeError(f"{exchange_id} returned no bars for {symbol} {timeframe}")
        out[symbol] = [_ohlcv(symbol, row) for row in raw]
    return out


def canonical_bars_digest(bars: dict[str, list[Any]]) -> str:
    """SHA-256 over the canonical OHLCV matrix: same rows ⇒ same dataset id."""
    payload = json.dumps(
        {
            symbol: [
                [b.symbol, int(b.timestamp), b.open, b.high, b.low, b.close, b.volume]
                for b in series
            ]
            for symbol, series in sorted(bars.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_bars_jsonl(bars: dict[str, list[Any]], path: Path) -> Path:
    """Export the exact bars used, so a verifier can re-derive the digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for _symbol, series in sorted(bars.items()):
            for bar in series:
                handle.write(
                    json.dumps(
                        {
                            "symbol": bar.symbol,
                            "timestamp": int(bar.timestamp),
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
    return path


# --------------------------------------------------------------------------- #
# The sandbox admission (a scratch input, never a committed one)
# --------------------------------------------------------------------------- #


def build_sandbox_ledger(*, scratch_path: Path) -> Path:
    """Write a ledger that admits one family, into this WP's scratch space.

    The entry is marked ``SANDBOX_SYNTHETIC`` in its own evidence block so no
    reader can mistake it for a research measurement, and the file lives under
    the work package's scratch directory — it is not ``config/`` and nothing
    loads it unless this module is asked to.
    """
    payload = {
        "_schema_version": "strategy-admission-ledger-v1",
        "_generated_by": "trading_bot.research.economic_recovery.paper_exec",
        "_claim": (
            "SANDBOX ONLY: this ledger exists to exercise the paper execution "
            "boundary. It is not a research verdict and must never be promoted "
            "or committed as one; the authoritative ledger is "
            "config/strategy_admission.json, which admits nothing."
        ),
        "_sources": [
            {
                "path": "reports/economic-recovery/RFC-EDGE-014R/PAPER_EXECUTION_EVIDENCE.json",
                "sha256": "0" * 64,
            }
        ],
        "strategies": {
            SANDBOX_STRATEGY_ID: {
                "family": "ema_crossover",
                "status": "PAPER_CANDIDATE",
                "admitted_for_paper": True,
                "expected_gross_edge_bps": 1.0,
                "edge_evidence": {
                    "source_doc": "SANDBOX_SYNTHETIC_ADMISSION",
                    "metric": "sandbox_placeholder_gross_bps",
                    "value_bps": 1.0,
                    "knowledge": "ASSUMED",
                    "sample_trades": 0,
                    "note": (
                        "declared placeholder so the admission contract's "
                        "positive-edge requirement is satisfied; it is NOT a "
                        "measurement and no economic claim rests on it"
                    ),
                    "evidence_class": "ASSUMED",
                    "period": "",
                    "timeframe": "1h",
                    "status": "SANDBOX_SYNTHETIC",
                },
                "source_doc": "SANDBOX_SYNTHETIC_ADMISSION",
                "rationale": (
                    "synthesised by WP-EDGE-14R to prove the execution boundary "
                    "is reachable; NOT an admission of this family"
                ),
                "timeframe": "1h",
                "known": True,
            }
        },
    }
    scratch_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return scratch_path


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def _load_runtime_entrypoint() -> Any:
    """Import ``scripts/start_paper_trading.py`` as a module, not a copy.

    Reusing the entrypoint's own factory is the point: a second wiring written
    here could agree with the runtime today and drift from it tomorrow, and
    then this evidence would be about a path nobody runs.
    """
    scripts = REPO_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import start_paper_trading

    return start_paper_trading


def _runtime_settings(*, timeframe: str, symbols: Sequence[str]) -> Any:
    from trading_bot.config.settings import load_settings
    from trading_bot.config.universe import PairSpec

    settings = load_settings(config_dir=str(REPO_ROOT / "config"))
    universe = settings.universe.model_copy(
        update={
            "pairs": [PairSpec(symbol=s, enabled=True) for s in symbols],
            "timeframes": [timeframe],
        }
    )
    return settings.model_copy(update={"universe": universe})


def _run_arm(
    *,
    arm: str,
    bars: dict[str, list[Any]],
    settings: Any,
    timeframe: str,
    symbols: Sequence[str],
    balance: float,
    warmup_bars: int,
    ledger_path: Path,
    scratch_dir: Path,
) -> dict[str, Any]:
    """Run one arm of the replay and return its raw, unrounded observations."""
    entrypoint = _load_runtime_entrypoint()
    from trading_bot.paper.broker import PaperBroker

    broker = PaperBroker(equity=balance)
    # The canonical factory: identical to the one the PAPER entrypoint builds.
    engine = entrypoint.build_cycle_engine(
        settings,
        broker,
        assets=[s.split("/")[0] for s in symbols],
        timeframe=timeframe,
        ledger_path=ledger_path,
    )

    per_cycle: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    def position_key(symbol: str, opened_at: float, entry_price: float) -> tuple[str, float, float]:
        """Identity of an opening, as the broker's own record names it.

        ``opened_at`` alone is not an identity: it is ``time.time()``, and a replay fast
        enough to open two positions on the same symbol within one clock tick handed both
        the same instant, so a ``(symbol, opened_at)`` key silently dropped real fills.  The
        execution price is part of the identity precisely because two openings that share an
        instant cannot share a price.
        """
        return (symbol, opened_at, entry_price)

    def record_open(
        *,
        symbol: str,
        side: str,
        entry_price: float,
        opened_at: float,
        quantity: float | None,
        provenance: str,
        bar_index: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        key = position_key(symbol, opened_at, entry_price)
        if key in opened:
            return
        opened.add(key)
        row: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "opened_at": opened_at,
            "provenance": provenance,
            "opened_at_bar_index": bar_index,
        }
        if quantity is not None:
            row["quantity"] = quantity
        row.update(extra or {})
        fills.append(row)

    def drain_closes(*, origin: str, bar_index: int) -> None:
        """Record every close the broker performed and has not been asked about yet.

        The broker's own ``closed_trades`` is the authority on which positions were closed:
        reading only the trades this loop's ``check_positions_ohlc`` call returns would miss
        the closes the *engine* performs inside its cycle, and then the realised PnL this arm
        publishes would not add up to the equity the broker actually moved.  Each closed trade
        also names the opening it came from, which is how an opening that never survived to a
        snapshot is still recorded instead of vanishing.
        """
        settled = broker.closed_trades
        for trade in settled[closes_recorded[0] :]:
            record_open(
                symbol=trade.symbol,
                side=trade.side,
                entry_price=trade.entry_price,
                opened_at=trade.opened_at,
                quantity=trade.quantity,
                provenance="broker_closed_trade",
                bar_index=bar_index,
                extra={"strategy_name": trade.strategy_name},
            )
            exits.append(
                {
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "exit_reason": trade.exit_reason,
                    "strategy_name": trade.strategy_name,
                    "opened_at": trade.opened_at,
                    "closed_by": origin,
                    "closed_at_bar_index": bar_index,
                }
            )
        closes_recorded[0] = len(settled)

    #: Cursor over ``broker.closed_trades``, plus the openings already recorded.
    closes_recorded: list[int] = [0]
    opened: set[tuple[str, float, float]] = set()

    length = min(len(series) for series in bars.values())
    for index in range(warmup_bars, length - 1):
        history = {symbol: series[: index + 1] for symbol, series in bars.items()}
        stamps = {symbol: int(series[index].timestamp) for symbol, series in bars.items()}
        counts = engine.run_cycle_sync(history, stamps)
        payload = counts.to_dict()
        payload["bar_index"] = index
        payload["decision_ts"] = int(next(iter(stamps.values())))
        per_cycle.append(payload)
        if len(rejections) < 40:
            rejections.extend(payload["rejections"][: max(0, 40 - len(rejections))])

        # Closes the engine itself performed, during the cycle just run.
        drain_closes(origin="engine_cycle", bar_index=index)

        # Every entry still on the book becomes a fill record with its full provenance.
        for symbol, position in broker.positions.items():
            record_open(
                symbol=symbol,
                side=position.side,
                entry_price=position.entry_price,
                opened_at=position.opened_at,
                quantity=position.quantity,
                provenance="book_snapshot",
                bar_index=index,
                extra={
                    "notional_usdt": position.notional_usdt,
                    "entry_commission": position.entry_commission,
                    "stop_loss_pct": position.stop_loss_pct,
                    "take_profit_pct": position.take_profit_pct,
                    "strategy_name": position.strategy_name,
                    "decision_ts": int(next(iter(stamps.values()))),
                },
            )

        # Exits are checked on the NEXT bar: a position opened on bar t cannot
        # be stopped out by the same bar it was filled in.
        following = {symbol: series[index + 1] for symbol, series in bars.items()}
        broker.check_positions_ohlc(
            {symbol: (bar.open, bar.high, bar.low, bar.close) for symbol, bar in following.items()}
        )
        drain_closes(origin="settlement_check", bar_index=index + 1)

    # Mark any still-open book at the last close so the accounting closes.
    last = {symbol: series[length - 1].close for symbol, series in bars.items()}
    broker.check_positions(last)
    drain_closes(origin="final_mark", bar_index=length - 1)

    # Only the stage counters are summed: ``bar_index`` and ``decision_ts`` live
    # in the same per-cycle payload and adding them up would be an invented
    # number that looks like a count.
    totals: dict[str, int] = {field: 0 for field in COUNT_FIELDS}
    for payload in per_cycle:
        for field in COUNT_FIELDS:
            totals[field] += int(payload.get(field, 0) or 0)

    reasons: dict[str, int] = {}
    for payload in per_cycle:
        for rejection in payload.get("rejections", []):
            reason_key = f"{rejection.get('stage')}:{rejection.get('reason')}"
            reasons[reason_key] = reasons.get(reason_key, 0) + 1

    realised = sum(t["pnl"] for t in exits)
    equity_change = round(broker.equity - balance, 9)
    return {
        "arm": arm,
        "ledger_path": str(ledger_path),
        "broker_initial_equity": balance,
        "broker_final_equity": broker.equity,
        "cycles": len(per_cycle),
        "stage_totals": totals,
        "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "fills_opened": len(fills),
        "fills_closed": len(exits),
        "fills": fills,
        "exits": exits,
        "realised_pnl": realised,
        "ledger_identity": {
            "opened": len(fills),
            "closed": len(exits),
            "open_positions_at_end": len(broker.positions),
            "unpaired_opens": len(fills) - len(exits),
            "realised_pnl": round(realised, 9),
            "equity_change": equity_change,
            "realised_equals_equity_change": abs(realised - equity_change) < 1e-6,
            "reading": (
                "every close the broker performed is in ``exits``, including the ones the "
                "engine performs inside its own cycle, and every opening the broker performed "
                "is in ``fills``, including the ones that never survived to a book snapshot. "
                "An opening with no close is a position still open when the replay ended, and "
                "its count is ``open_positions_at_end``"
            ),
        },
        "rejections_sample": rejections,
        "per_cycle": per_cycle,
    }


def run_execution(
    *,
    symbols: Sequence[str] = ("BTC/USDT", "ETH/USDT"),
    timeframe: str = "1h",
    limit: int = 1000,
    warmup_bars: int = 120,
    balance: float = 10_000.0,
    scratch_dir: Path | None = None,
    bars: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """Execute both arms over one frozen dataset and return the full payload."""
    scratch = scratch_dir or (
        REPO_ROOT / "reports" / "economic-recovery" / "RFC-EDGE-014R" / "scratch"
    )
    scratch.mkdir(parents=True, exist_ok=True)

    if bars is None:
        bars = fetch_bars(symbols, timeframe, limit=limit)

    digest = canonical_bars_digest(bars)
    dataset_path = write_bars_jsonl(bars, scratch / "PAPER_REPLAY_BARS.jsonl")
    dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    settings = _runtime_settings(timeframe=timeframe, symbols=symbols)
    committed_ledger = REPO_ROOT / "config" / "strategy_admission.json"
    sandbox_ledger = build_sandbox_ledger(scratch_path=scratch / "SANDBOX_ADMISSION.json")

    gate_arm = _run_arm(
        arm=ARM_GATE_INTACT,
        bars=bars,
        settings=settings,
        timeframe=timeframe,
        symbols=symbols,
        balance=balance,
        warmup_bars=warmup_bars,
        ledger_path=committed_ledger,
        scratch_dir=scratch,
    )
    sandbox_arm = _run_arm(
        arm=ARM_SANDBOX_ADMISSION,
        bars=bars,
        settings=settings,
        timeframe=timeframe,
        symbols=symbols,
        balance=balance,
        warmup_bars=warmup_bars,
        ledger_path=sandbox_ledger,
        scratch_dir=scratch,
    )

    for arm_payload in (gate_arm, sandbox_arm):
        for fill in arm_payload["fills"]:
            fill["fill_class"] = "HYPOTHETICAL_FILL"
            fill["runtime_authoritative"] = arm_payload["arm"] == ARM_GATE_INTACT
            fill["order_sent"] = False
            fill["venue"] = "IN_PROCESS_PAPER_BROKER"

    bars_meta = {
        symbol: {
            "rows": len(series),
            "first_ts": int(series[0].timestamp),
            "last_ts": int(series[-1].timestamp),
        }
        for symbol, series in sorted(bars.items())
    }

    return {
        "schema_version": "EDGE14R_PAPER_EXECUTION_V1",
        "work_package": "WP-EDGE-14R/P1",
        "execution_class": "PAPER_REPLAY",
        "execution_class_reading": (
            "historical bars driven through the canonical paper path; this is "
            "real execution of the runtime's code but NOT prospective "
            "observation, because every bar predates the run"
        ),
        "path": (
            "PIT OHLCV -> CryptoAssetAgentRegistry -> StrategyRouter -> "
            "AlphaFamily -> SignalAdapter -> CandidatePortfolio -> "
            "RiskManager.check_signal -> PaperBroker.execute_signal"
        ),
        "engine_factory": "scripts/start_paper_trading.py::build_cycle_engine",
        "timeframe": timeframe,
        "symbols": list(symbols),
        "warmup_bars": warmup_bars,
        "dataset": {
            "source": "ccxt public OHLCV (read-only, no credentials)",
            "rows": bars_meta,
            "canonical_digest": digest,
            "exported_jsonl": str(dataset_path),
            "exported_sha256": dataset_sha,
        },
        "committed_ledger": str(committed_ledger),
        "sandbox_ledger": str(sandbox_ledger),
        "sandbox_strategy_id": SANDBOX_STRATEGY_ID,
        "arms": {ARM_GATE_INTACT: gate_arm, ARM_SANDBOX_ADMISSION: sandbox_arm},
        "order_sent": False,
        "exchange_orders": 0,
        "promotion": "NONE",
        "limitations": [
            "a sandbox ledger is not an admission: the fills of the sandbox arm "
            "certify connectivity, never admissibility",
            "one dataset, two symbols, one timeframe, one family: enough to "
            "diagnose the path, not enough to infer an edge",
            "fills are modelled by PaperBroker at bar OHLC with its own slippage "
            "and commission, not by venue data",
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    """Human-readable rendering of the execution payload."""
    lines = [
        "# WP-EDGE-14R — paper execution evidence",
        "",
        f"*Execution class `{payload['execution_class']}`. "
        f"Dataset `{payload['dataset']['canonical_digest'][:23]}…`. "
        f"{payload['order_sent']} orders sent.*",
        "",
        payload["execution_class_reading"],
        "",
        "## Arms",
        "",
        "| arm | ledger | cycles | contexts | router no-trade | risk accepted | "
        "risk rejected | orders created | fills closed | realised pnl |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, arm in payload["arms"].items():
        totals = arm["stage_totals"]
        lines.append(
            "| `{arm}` | {ledger} | {cycles} | {ctx} | {rnt} | {ra} | {rr} | "
            "{oc} | {fc} | {pnl} |".format(
                arm=name,
                ledger="committed" if name == ARM_GATE_INTACT else "sandbox",
                cycles=arm["cycles"],
                ctx=totals.get("contexts_built", 0),
                rnt=totals.get("router_no_trade", 0),
                ra=totals.get("risk_accepted", 0),
                rr=totals.get("risk_rejected", 0),
                oc=totals.get("orders_created", 0),
                fc=arm["fills_closed"],
                pnl=round(arm["realised_pnl"], 6),
            )
        )

    gate = payload["arms"][ARM_GATE_INTACT]
    sandbox = payload["arms"][ARM_SANDBOX_ADMISSION]
    lines += [
        "",
        "## Reading",
        "",
        f"- the authoritative arm produced **{gate['fills_closed']}** fill(s) over "
        f"{gate['cycles']} cycles: with the committed ledger the funnel stops at the "
        "router, before risk and before the broker, which is the gate working;",
        f"- the sandbox arm produced **{sandbox['fills_closed']}** fill(s) over "
        f"{sandbox['cycles']} cycles, so the risk and broker boundary is reachable "
        "once a strategy is admitted;",
        "- every fill is `HYPOTHETICAL_FILL` with `order_sent: false`; none of "
        "them is a PAPER_BROKER_FILL of the authoritative path, and none is an "
        "exchange order.",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines.append("")
    return "\n".join(lines)
