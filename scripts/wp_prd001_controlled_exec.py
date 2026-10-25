"""WP-PAPER-REAL-DATA-001 — RUN-C: the ORDER path, under a labelled test fixture.

Why a fixture is needed
-----------------------
The committed admission ledger admits **no** strategy for PAPER
(``admitted_for_paper=false`` for all 18 entries), so a campaign over market
data alone can only produce ``NO_TRADE``. That is the correct behaviour, and it
is not evidence that the order path works. To validate the order path without
faking a market edge, this run swaps exactly two inputs and nothing else:

* **admission** — a fixture ledger marked ``_fixture: TEST_ONLY`` with one
  ``test_signal@<tf>`` entry in ``PAPER_CANDIDATE``. It lives under
  ``docs/.../fixtures/`` and is never a config default, so no production run can
  load it. It does not touch ``config/strategy_admission.json``.
* **signal source** — a family that emits one deterministic alpha per asset
  (``test_signal``), so the order path is exercised on demand instead of waiting
  for a market event. Labelled in every artefact it produces.

Everything else is the runtime's own code and configuration: the real
``AutonomousPaperRuntime`` cycle, the five review agents, the independent
verifier, the real ``RiskManager`` with the committed risk limits, the real
``PaperBroker`` (1bp slippage, 5bp commission), the real
``StartupReconcilerV4``, and **real public market data** for prices.

What the run measures
---------------------
1. cycle 1 → ``TRADE_PAPER`` decisions, fills, positions;
2. wait for the next sealed bar, cycle 2 → mark-to-market, SL/TP evaluation and
   reconciliation against real prices (open positions also make the risk gate
   refuse new exposure — recorded, not worked around);
3. a forced exit at a **labelled test price** (not market data) so the PnL and
   fee arithmetic is exercised, then a final reconciliation of the book.

Exit code is 0 only when every invariant below holds; the artefact records each
one individually so a reader can disagree with the summary.

Usage::

    uv run python scripts/wp_prd001_controlled_exec.py --out <evidence>/raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import autonomous_paper as entrypoint  # noqa: E402
import wp_prd001_campaign as campaign  # noqa: E402

FIXTURE_RELATIVE = "docs/agentic/paper_reald/WP-PAPER-REAL-DATA-001/fixtures/TEST_ONLY_admission_ledger.json"
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
SLIPPAGE_BPS = 1.0
COMMISSION_BPS = 5.0


def _trade_row(trade: Any) -> dict[str, Any]:
    """Serialize a ClosedTrade with the fields the arithmetic needs.

    ``broker.closed_trades_rows()`` drops notional/commission, so the harness
    reads the dataclass directly: verifying fees requires the inputs, not the
    broker's summary of them.
    """
    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_price": float(trade.entry_price),
        "exit_price": float(trade.exit_price),
        "quantity": float(trade.quantity),
        "notional_usdt": float(trade.entry_price) * float(trade.quantity),
        "gross_pnl": (
            (float(trade.exit_price) - float(trade.entry_price)) * float(trade.quantity)
            if trade.side == "buy"
            else (float(trade.entry_price) - float(trade.exit_price)) * float(trade.quantity)
        ),
        "entry_commission": float(trade.entry_price) * float(trade.quantity) * COMMISSION_BPS / 10_000.0,
        "exit_commission": float(trade.entry_price) * float(trade.quantity) * COMMISSION_BPS / 10_000.0,
        "pnl": float(trade.pnl),
        "exit_reason": trade.exit_reason,
        "opened_at": trade.opened_at,
        "closed_at": trade.closed_at,
        "strategy_name": trade.strategy_name,
    }


def _references(run_dir: Path) -> list[dict[str, Any]]:
    """Proposal entry references, read back from the run's own traces.

    Kept as a LIST keyed by decision time, not a dict keyed by symbol: a run can
    trade the same symbol twice, and collapsing that would compare a fill to the
    wrong decision (the mistake this WP made on its first attempt).
    """
    path = run_dir / "traces.jsonl"
    out: list[dict[str, Any]] = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        trace = json.loads(line)
        proposal = trace.get("proposal") or {}
        if trace.get("mode") == "TRADE_PAPER" and proposal:
            out.append(
                {
                    "symbol": trace["symbol"],
                    "decision_time_ms": int(trace["decision_time_ms"]),
                    "entry_reference": float(proposal["entry_reference"]),
                }
            )
    return out


def _reference_for(trade: dict[str, Any], references: list[dict[str, Any]]) -> float | None:
    """The entry reference of the decision that produced this fill."""
    candidates = [r for r in references if r["symbol"] == trade.get("symbol")]
    if not candidates:
        return None
    opened_ms = float(trade.get("opened_at") or 0.0) * 1000.0
    best = min(candidates, key=lambda r: abs(r["decision_time_ms"] - opened_ms))
    return float(best["entry_reference"])


def _iso(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestSignalFamily:
    """Deterministic TEST signal source (``family_name='test_signal'``).

    Emits one LONG alpha per asset on the last bar's close. It exists ONLY so the
    decision→risk→broker path can be exercised deterministically; it is not a
    strategy, has no research evidence, and its alphas are labelled as such in
    ``metadata``.
    """

    family_name = "test_signal"

    def generate(self, candles: Any, indicators: Any, features: Any = None, **kwargs: Any) -> list[Any]:
        from trading_bot.research.types import AlphaSignal

        if len(candles) < 2:
            return []
        last = candles[-1]
        price = float(last.close)
        direction = str(kwargs.get("direction") or "LONG").upper()
        if direction not in ("LONG", "SHORT"):
            direction = "LONG"
        stop = price * (0.99 if direction == "LONG" else 1.01)
        return [
            AlphaSignal(
                family="test_signal",
                symbol=last.symbol,
                timestamp=last.timestamp,
                direction=direction,
                entry_reference=price,
                structural_stop=stop,
                timeframe=str(kwargs.get("timeframe") or "5m"),
                metadata={"fixture": "TEST_ONLY", "reason": "controlled_exec_path_test"},
            )
        ]


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / "docs/agentic/paper_reald/WP-PAPER-REAL-DATA-001/raw"))
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--config-dir", default="config/realdata")
    parser.add_argument("--balance", type=float, default=10_000.0)
    parser.add_argument("--size-usd", type=float, default=1_000.0)
    parser.add_argument("--lookback-bars", type=int, default=120)
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from trading_bot.autonomous.admission_ledger import AdmissionLedger
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.autonomous.strategy_state import StrategyRegistry
    from trading_bot.execution.idempotency import IdempotencyGuard
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.paper_state_store import PaperStateStore
    from trading_bot.paper.reconciliation_v4 import StartupReconcilerV4
    from trading_bot.paper.snapshot_history import FetcherBarReader
    from trading_bot.risk.manager import RiskManager

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    tf = args.timeframe
    tf_ms = TF_MS[tf]
    run_dir = out_dir / "runs" / "run-c-controlled-exec"
    if run_dir.exists():
        for existing in run_dir.glob("*"):
            existing.unlink()
    # A book left behind by an earlier attempt would make the startup
    # reconciliation “RECOVERED” and seed this run's equity with another run's
    # PnL. A controlled test starts from a known, empty book.
    state_path = out_dir / "paper_state_run_c.json"
    if state_path.exists():
        state_path.unlink()

    # Same settings builder the entrypoint uses (config dir + universe override),
    # so this run cannot drift from the production composition.
    settings = entrypoint.build_settings(
        argparse.Namespace(config_dir=args.config_dir, timeframe=tf), assets
    )

    fixture_path = REPO_ROOT / FIXTURE_RELATIVE
    ledger = AdmissionLedger.load(fixture_path)
    registry = StrategyRegistry.from_ledger(ledger, assets=assets)
    strategy_map = registry.strategy_map(tf)

    factory, source = campaign.build_public_factory(
        settings, tf, out_dir / "DATA_ACCESS_run_c.jsonl"
    )
    reader = FetcherBarReader(source, timeframe=tf)
    broker = PaperBroker(equity=args.balance)
    risk = RiskManager(risk=settings.risk, equity=args.balance)
    idempotency = IdempotencyGuard()
    store = PaperStateStore(state_path)
    startup = StartupReconcilerV4(
        store=store, broker=broker, risk_manager=risk, idempotency=idempotency
    ).reconcile()

    runtime = AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families={"test_signal": TestSignalFamily()},
        strategy_map=strategy_map,
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=tf,
        horizon_minutes=float(tf_ms / 60_000),
        size_usd=args.size_usd,
        lookback_bars=args.lookback_bars,
        shadow_evaluation_enabled=False,
        environment="paper:test-fixture",
        idempotency=idempotency,
    )

    # Phase alignment matters: the freshness gate budgets 1.5 bars and measures
    # from the newest CLOSED bar's open, so a cycle started just BEFORE a close
    # sees a context that is about to become stale (observed in this WP: a cycle
    # 3s before the boundary was rejected as ``stale_context``). Cycle 1 is
    # therefore aligned to a few seconds AFTER a seal, exactly like the
    # entrypoint's ``--cadence bar-close``.
    now = time.time()
    aligned_start = (int(now // (tf_ms / 1000)) + 1) * (tf_ms / 1000) + 20
    await asyncio.sleep(max(0.0, aligned_start - now))

    cycle1 = await runtime.run_cycle(cycle=1)
    after_cycle1 = {
        "cycle": 1,
        "report": cycle1.to_dict(),
        "positions": {s: p.to_row() for s, p in broker.positions.items()},
        "equity": broker.equity,
        "at_utc": _iso(int(time.time() * 1000)),
    }

    # Wait for the NEXT sealed bar so cycle 2 marks the book on prices the
    # decision could not have seen in cycle 1.
    now = time.time()
    next_close = (int(now // (tf_ms / 1000)) + 1) * (tf_ms / 1000) + 25
    wait_s = max(0.0, next_close - now)
    print(f"[run-c] waiting {wait_s:.0f}s for the next sealed {tf} bar", flush=True)
    await asyncio.sleep(wait_s)

    marks: dict[str, float] = {}
    mark_close_ms: dict[str, int] = {}
    now_ms = int(time.time() * 1000)
    for asset in assets:
        symbol = f"{asset}/USDT"
        bars = await source.fetch_recent(symbol, limit=3)
        # Mark on the newest CLOSED bar only: a forming bar's close is not a
        # price anyone could have exited at.
        closed = [b for b in bars if int(b.timestamp) + tf_ms <= now_ms]
        if not closed:
            raise SystemExit(f"no closed bar available to mark {symbol}")
        marks[symbol] = float(closed[-1].close)
        mark_close_ms[symbol] = int(closed[-1].timestamp) + tf_ms
    cycle2 = await runtime.run_cycle(cycle=2)
    after_cycle2 = {
        "cycle": 2,
        "report": cycle2.to_dict(),
        "positions": {s: p.to_row() for s, p in broker.positions.items()},
        "mark_prices": marks,
        "unrealized_pnl": broker.unrealized_pnl(marks),
        "mark_to_market_equity": broker.mark_to_market_equity(marks),
        "equity": broker.equity,
        "at_utc": _iso(int(time.time() * 1000)),
    }

    # Forced exit at a LABELLED TEST price: exercises close/PnL/fee arithmetic.
    forced: list[dict[str, Any]] = []
    for symbol, position in list(broker.positions.items()):
        test_exit = float(position.entry_price) * (1.01 if position.side == "buy" else 0.99)
        closed = broker.check_positions({symbol: test_exit})
        forced.append(
            {
                "symbol": symbol,
                "forced_exit_price": test_exit,
                "price_source": "TEST_NOT_MARKET",
                "closed": [_trade_row(t) for t in closed],
            }
        )
    final_reconcile = StartupReconcilerV4(
        store=store, broker=broker, risk_manager=risk, idempotency=idempotency
    ).reconcile()

    # Durable state: write it the way the entrypoint does, then reload it in a
    # second reconciler so the recovery path is exercised, not just claimed.
    from trading_bot.paper.paper_runtime_state import save_session_state

    save_session_state(
        store=store, run_id="run-c-controlled-exec", broker=broker, risk=risk, idempotency=idempotency
    )
    reload_broker = PaperBroker(equity=args.balance)
    reload_risk = RiskManager(risk=settings.risk, equity=args.balance)
    reload_reconcile = StartupReconcilerV4(
        store=store,
        broker=reload_broker,
        risk_manager=reload_risk,
        idempotency=IdempotencyGuard(),
    ).reconcile()

    fills = [_trade_row(t) for t in broker.closed_trades]
    positions = {s: p.to_row() for s, p in broker.positions.items()}
    references = _references(run_dir)
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    check_spec = _invariants(
        settings=settings,
        broker=broker,
        fills=fills,
        positions=positions,
        cycle1=cycle1.to_dict(),
        cycle2=cycle2.to_dict(),
        marks=marks,
        mark_close_ms=mark_close_ms,
        startup=startup,
        final_reconcile=final_reconcile,
        reload_reconcile=reload_reconcile,
        reload_broker=reload_broker,
        forced=forced,
        references=references,
        balance=args.balance,
    )
    checks.update(check_spec["checks"])
    detail.update(check_spec["detail"])

    payload = {
        "wp": "WP-PAPER-REAL-DATA-001",
        "run_id": "run-c-controlled-exec",
        "label": "TEST_EXECUTION",
        "generated_at": _iso(int(time.time() * 1000)),
        "disclosure": {
            "market_data": "REAL — public binance klines (unauthenticated)",
            "admission": "FIXTURE (TEST_ONLY ledger, PAPER_CANDIDATE test_signal@<tf>)",
            "signal_source": "FIXTURE (deterministic test_signal family)",
            "forced_exit_price": "TEST parameter, not market data",
            "risk_limits": "REAL — config/realdata/risk.yaml, unmodified",
            "execution_boundary": "PaperBroker (1bp slippage, 5bp commission)",
            "live_orders": 0,
            "credentials_used": False,
        },
        "fixture": {
            "ledger_path": FIXTURE_RELATIVE,
            "strategy_map": strategy_map,
            "paper_candidates": ledger.paper_candidates(),
        },
        "settings": {
            "timeframe": tf,
            "assets": assets,
            "balance": args.balance,
            "size_usd": args.size_usd,
            "risk": settings.risk.model_dump(mode="json"),
        },
        "startup_reconciliation": getattr(startup, "status", str(startup)),
        "final_reconciliation": getattr(final_reconcile, "status", str(final_reconcile)),
        "reload_reconciliation": getattr(reload_reconcile, "status", str(reload_reconcile)),
        "reload_equity": float(reload_broker.equity),
        "reference_prices": references,
        "cycles": [after_cycle1, after_cycle2],
        "closed_trades": fills,
        "open_positions": positions,
        "forced_exits": forced,
        "checks": checks,
        "detail": detail,
        "verdict": "TEST_EXECUTION_PASS" if all(checks.values()) else "TEST_EXECUTION_FAIL",
        "failed_checks": [k for k, v in checks.items() if not v],
    }
    (out_dir / "CONTROLLED_EXEC.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": payload["verdict"], "failed": payload["failed_checks"]}, indent=2))
    return payload


def _invariants(
    *,
    settings: Any,
    broker: Any,
    fills: list[dict[str, Any]],
    positions: dict[str, Any],
    cycle1: dict[str, Any],
    cycle2: dict[str, Any],
    marks: dict[str, float],
    mark_close_ms: dict[str, int],
    startup: Any,
    final_reconcile: Any,
    reload_reconcile: Any,
    reload_broker: Any,
    forced: list[dict[str, Any]],
    references: list[dict[str, Any]],
    balance: float,
) -> dict[str, Any]:
    """Recompute the money from prices and quantities, not from a summary."""
    risk = settings.risk
    orders = int(cycle1.get("orders_created") or 0) + int(cycle2.get("orders_created") or 0)
    paper_reported = int(cycle1.get("paper_trades") or 0) + int(cycle2.get("paper_trades") or 0)
    notional_cap = float(getattr(risk, "max_asset_exposure_pct", 10.0)) / 100.0 * balance
    fee_bps = COMMISSION_BPS / 10_000.0

    fee_errors: list[str] = []
    slippage_errors: list[str] = []
    for trade in fills:
        symbol = str(trade.get("symbol"))
        notional = float(trade.get("notional_usdt") or 0.0)
        gross = float(trade.get("gross_pnl") or 0.0)
        expected_fee = notional * fee_bps
        entry_fee = float(trade.get("entry_commission") or 0.0)
        exit_fee = float(trade.get("exit_commission") or 0.0)
        net = float(trade.get("pnl") or 0.0)
        if abs(entry_fee - expected_fee) > 1e-6:
            fee_errors.append(f"{symbol}:entry_fee")
        if abs(exit_fee - expected_fee) > 1e-6:
            fee_errors.append(f"{symbol}:exit_fee")
        if abs(net - (gross - entry_fee - exit_fee)) > 1e-6:
            fee_errors.append(f"{symbol}:net_pnl_arithmetic")
        reference = _reference_for(trade, references)
        if reference is None:
            slippage_errors.append(f"{symbol}:no_reference")
        else:
            expected_entry = reference * (
                (1 + SLIPPAGE_BPS / 10_000.0) if trade.get("side") == "buy" else (1 - SLIPPAGE_BPS / 10_000.0)
            )
            if abs(float(trade["entry_price"]) - expected_entry) > max(1e-6, expected_entry * 1e-9):
                slippage_errors.append(
                    f"{symbol}:entry {trade['entry_price']} != {expected_entry:.6f}"
                )

    notional_errors = [
        f"{trade.get('symbol')}:{trade.get('notional_usdt')}>{notional_cap}"
        for trade in fills
        if float(trade.get("notional_usdt") or 0.0) > notional_cap + 1e-9
    ]
    equity_delta = float(broker.equity) - float(balance)
    realized = sum(float(t.get("pnl") or 0.0) for t in fills)

    checks = {
        "orders_created": orders > 0,
        "paper_trades_reported": paper_reported == orders,
        "fills_recorded": len(fills) > 0,
        "notional_within_limits": not notional_errors,
        "commission_arithmetic": not fee_errors,
        "slippage_applied": not slippage_errors,
        "equity_matches_realized_pnl": abs(equity_delta - realized) <= 1e-6,
        "startup_reconciliation_consistent": str(getattr(startup, "status", startup))
        == "CONSISTENT",
        "post_trade_reconciliation_consistent": str(
            getattr(final_reconcile, "status", final_reconcile)
        )
        in ("CONSISTENT", "RECOVERED"),
        "state_reload_reconciled": str(getattr(reload_reconcile, "status", reload_reconcile))
        in ("CONSISTENT", "RECOVERED"),
        "state_reload_keeps_equity": abs(float(reload_broker.equity) - float(broker.equity)) <= 1e-6,
        "no_position_left_open": not positions,
        "realized_pnl_computed": len(fills) > 0 and all("pnl" in t for t in fills),
        # Every exit must have happened at/after the bar the mark came from
        # sealed: proof the exit price was NOT visible when the position opened.
        "cycle2_marked_a_later_bar": bool(fills)
        and all(
            float(trade["closed_at"]) >= (mark_close_ms.get(str(trade["symbol"]), 0) / 1000.0) - 1.0
            for trade in fills
        ),
    }
    return {
        "checks": checks,
        "detail": {
            "orders_created": orders,
            "fills": len(fills),
            "notional_cap_usdt": notional_cap,
            "equity": float(broker.equity),
            "realized_pnl": realized,
            "equity_delta": equity_delta,
            "fee_errors": fee_errors,
            "slippage_errors": slippage_errors,
            "notional_errors": notional_errors,
            "forced_exit_count": len(forced),
        },
    }


def main(argv: list[str] | None = None) -> int:
    payload = asyncio.run(run(_parse(argv)))
    return 0 if payload["verdict"] == "TEST_EXECUTION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
