"""Entry point CLI del bot.

Comandos principales:

- ``config-check``: valida YAML + .env.
- ``scan --demo``: una iteracion sintetica.
- ``run --mode live``: loop real con dashboard local en ``/health``.
- ``place-order``: orden real explicita protegida por ``--confirm-live``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError

from trading_bot import __version__
from trading_bot.charting import ChartSnapshotRequest, render_local_chart_snapshot
from trading_bot.config import TradingMode, load_settings
from trading_bot.market_data.bitunix import (
    BitunixAPIError,
    BitunixMarketDataSource,
    BitunixSpotClient,
    to_api_symbol,
)
from trading_bot.market_data.bitunix_futures import BitunixFuturesClient, BitunixFuturesPosition
from trading_bot.trade_journal import (
    EntryThesisInput,
    TradeCase,
    TradeJournalStore,
    TradeOutcome,
    build_entry_thesis,
)

if TYPE_CHECKING:
    from trading_bot.config.settings import Settings
    from trading_bot.market_data.types import Balance
    from trading_bot.scanner.scanner import CounterSnapshot, UniverseScanner
    from trading_bot.scanner.types import MarketSnapshot


DEFAULT_DEMO_PAIRS: list[tuple[str, bool]] = [
    ("BTC/USDT", True),
    ("ETH/USDT", True),
    ("SOL/USDT", True),
    ("AVAX/USDT", True),
    ("MATIC/USDT", True),
]


@dataclass(slots=True)
class RuntimeState:
    mode: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    iteration: int = 0
    last_updated_at: str | None = None
    last_pairs_processed: int = 0
    last_pairs_active: int = 0
    last_pairs_inactive: int = 0
    last_scanner_errors: int = 0
    last_summary: list[dict[str, object]] = field(default_factory=list)
    last_live_event: dict[str, object] | None = None
    live_orders_sent: int = 0


@dataclass(slots=True)
class LiveExecutionState:
    orders_sent: int = 0
    traded_symbols: dict[str, float] = field(default_factory=dict)
    last_event: dict[str, object] | None = None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _render_dashboard_html(state: RuntimeState) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>{escape(str(item['symbol']))}</td>"
            f"<td>{escape(str(item['status']))}</td>"
            f"<td>{escape(str(item['score']))}</td>"
            f"<td>{escape(str(item['reason']))}</td>"
            "</tr>"
        )
        for item in state.last_summary
    )
    if not rows:
        rows = "<tr><td colspan='4'>Sin datos todavia</td></tr>"

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trading Bot Dashboard</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font-family: Consolas, monospace; background: #0b1220; color: #e5edf9; margin: 0; padding: 24px; }}
    .wrap {{ max-width: 980px; margin: 0 auto; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }}
    .card {{ background: #121a2b; border: 1px solid #22304a; border-radius: 14px; padding: 16px; }}
    .label {{ color: #8ca0c3; font-size: 12px; text-transform: uppercase; }}
    .value {{ font-size: 28px; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: #121a2b; border-radius: 14px; overflow: hidden; }}
    th, td {{ padding: 12px; border-bottom: 1px solid #22304a; text-align: left; }}
    th {{ color: #8ca0c3; font-size: 12px; text-transform: uppercase; }}
    .muted {{ color: #8ca0c3; }}
    a {{ color: #7dd3fc; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Trading Bot Runtime</h1>
    <p class="muted">Backend local de estado para el frontend.</p>
    <div class="grid">
      <div class="card"><div class="label">Modo</div><div class="value">{escape(state.mode)}</div></div>
      <div class="card"><div class="label">Iteracion</div><div class="value">{state.iteration}</div></div>
      <div class="card"><div class="label">Activos</div><div class="value">{state.last_pairs_active}</div></div>
      <div class="card"><div class="label">Inactivos</div><div class="value">{state.last_pairs_inactive}</div></div>
      <div class="card"><div class="label">Errores Scanner</div><div class="value">{state.last_scanner_errors}</div></div>
      <div class="card"><div class="label">Ordenes Live</div><div class="value">{state.live_orders_sent}</div></div>
    </div>
    <p class="muted">Ultima actualizacion: {escape(str(state.last_updated_at))}</p>
    <p class="muted">Health JSON: <a href="/health">/health</a></p>
    <table>
      <thead>
        <tr><th>Symbol</th><th>Status</th><th>Score</th><th>Reason</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</body>
</html>"""


def _start_web_server(host: str, port: int, state: RuntimeState, lock: Lock) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            with lock:
                payload = asdict(state)
                html = _render_dashboard_html(state)

            if self.path == "/health":
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-bot", description="crypto-scalping-agentic-bot CLI")
    parser.add_argument("--version", action="version", version=f"trading-bot {__version__}")
    sub = parser.add_subparsers(dest="command", required=False)

    config_parser = sub.add_parser("config-check", help="Valida los archivos YAML y .env.")
    config_parser.add_argument("--config-dir", default="config")
    config_parser.add_argument("--env-file", default=".env")

    scan_parser = sub.add_parser("scan", help="Ejecuta una iteracion del UniverseScanner.")
    scan_parser.add_argument("--demo", action="store_true", default=True)
    scan_parser.add_argument("--no-demo", dest="demo", action="store_false")
    scan_parser.add_argument(
        "--mode",
        default="paper",
        choices=["research", "backtest", "paper", "live", "shadow_live"],
    )
    scan_parser.add_argument("--config-dir", default="config")
    scan_parser.add_argument("--env-file", default=".env")

    run_parser = sub.add_parser("run", help="Arranca el bot.")
    run_parser.add_argument(
        "--mode",
        default="paper",
        choices=["research", "backtest", "paper", "live", "shadow_live"],
    )
    run_parser.add_argument("--loop-seconds", type=int, default=30)
    run_parser.add_argument("--once", action="store_true")
    run_parser.add_argument("--web-port", type=int, default=0)
    run_parser.add_argument("--web-host", default="127.0.0.1")
    run_parser.add_argument("--config-dir", default="config")
    run_parser.add_argument("--env-file", default=".env")
    run_parser.add_argument("--auto-trade", action="store_true")
    run_parser.add_argument(
        "--market-kind",
        choices=["spot", "futures"],
        default="futures",
        help="Tipo de mercado para auto-trade (default: futures).",
    )
    run_parser.add_argument("--trade-quote-usdt", type=float, default=10.0)
    run_parser.add_argument("--max-live-orders", type=int, default=1)
    run_parser.add_argument("--symbol-cooldown-seconds", type=int, default=900)

    order_parser = sub.add_parser("place-order", help="Coloca una orden real en Bitunix.")
    order_parser.add_argument("--symbol", required=True)
    order_parser.add_argument("--side", required=True, choices=["buy", "sell"])
    order_parser.add_argument("--order-type", required=True, choices=["market", "limit"])
    order_parser.add_argument("--amount", required=True, type=float)
    order_parser.add_argument("--price", type=float, default=None)
    order_parser.add_argument("--config-dir", default="config")
    order_parser.add_argument("--env-file", default=".env")
    order_parser.add_argument("--confirm-live", action="store_true")
    order_parser.add_argument(
        "--market-kind",
        choices=["spot", "futures"],
        default="futures",
        help="Tipo de ejecucion real (default: futures).",
    )
    order_parser.add_argument(
        "--trade-side",
        choices=["OPEN", "CLOSE"],
        default="OPEN",
        help="Solo futures: OPEN para abrir posicion, CLOSE para reducir/cerrar.",
    )
    order_parser.add_argument("--position-id", default=None, help="Solo futures CLOSE.")
    order_parser.add_argument("--reduce-only", action="store_true")
    order_parser.add_argument("--tp-price", type=float, default=None)
    order_parser.add_argument("--sl-price", type=float, default=None)

    positions_parser = sub.add_parser("positions", help="Lista posiciones abiertas en futures Bitunix.")
    positions_parser.add_argument("--config-dir", default="config")
    positions_parser.add_argument("--env-file", default=".env")
    positions_parser.add_argument("--symbol", default=None)

    close_parser = sub.add_parser("close-position", help="Cierra una posicion futures por positionId.")
    close_parser.add_argument("--position-id", required=True)
    close_parser.add_argument("--config-dir", default="config")
    close_parser.add_argument("--env-file", default=".env")

    tpsl_parser = sub.add_parser("set-tpsl", help="Configura TP/SL sobre una posicion futures.")
    tpsl_parser.add_argument("--symbol", required=True)
    tpsl_parser.add_argument("--position-id", required=True)
    tpsl_parser.add_argument("--qty", required=True, type=float)
    tpsl_parser.add_argument("--tp-price", type=float, default=None)
    tpsl_parser.add_argument("--sl-price", type=float, default=None)
    tpsl_parser.add_argument("--config-dir", default="config")
    tpsl_parser.add_argument("--env-file", default=".env")

    sub.add_parser("kill-switch", help="Stub reservado.")
    sub.add_parser("status", help="Stub reservado.")
    return parser


def _cmd_config_check(args: argparse.Namespace) -> int:
    env_file = args.env_file if args.env_file else None
    try:
        settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    except ValidationError as exc:
        sys.stderr.write("ERROR: la configuracion no es valida.\n\n")
        sys.stderr.write(exc.json(indent=2) + "\n")
        return 1

    print("Configuracion valida.")
    print(f"  mode:                 {settings.runtime.mode.value}")
    print(f"  live_trading_enabled: {settings.runtime.live_trading_enabled}")
    print(f"  pairs enabled:        {sum(1 for pair in settings.universe.pairs if pair.enabled)}")
    print(f"  strategies:           {len(settings.strategies.strategies)}")
    return 0


def _build_demo_scanner(mode: str) -> UniverseScanner:
    from trading_bot.market_data.fake import build_demo_fetcher, build_demo_settings
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    settings = build_demo_settings(pairs=DEFAULT_DEMO_PAIRS, mode=mode, kill_switch_enabled=False)
    source = build_demo_fetcher(settings)
    registry_per_mode = build_filter_set_per_mode(settings)
    return UniverseScanner(source=source, registry_per_mode=registry_per_mode, settings=settings)


def _build_live_scanner(config_dir: str, env_file: str | None) -> tuple[UniverseScanner, Settings, BitunixSpotClient]:
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    settings = load_settings(config_dir=config_dir, env_file=env_file)
    scanner_settings = settings.model_copy(
        update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
    )
    client = BitunixSpotClient(
        api_key=settings.exchange.api_key,
        api_secret=settings.exchange.api_secret,
    )
    source = BitunixMarketDataSource(client)
    registry_per_mode = build_filter_set_per_mode(scanner_settings)
    scanner = UniverseScanner(source=source, registry_per_mode=registry_per_mode, settings=scanner_settings)
    return scanner, settings, client


def _run_single_iteration(mode: str) -> tuple[list[MarketSnapshot], CounterSnapshot]:
    scanner = _build_demo_scanner(mode=mode)
    snapshots = asyncio.run(scanner.run())
    return snapshots, scanner.counters


def _run_single_live_iteration(config_dir: str, env_file: str | None) -> tuple[list[MarketSnapshot], CounterSnapshot, BitunixSpotClient, Settings]:
    scanner, settings, client = _build_live_scanner(config_dir, env_file)
    snapshots = asyncio.run(scanner.run())
    return snapshots, scanner.counters, client, settings


def _print_demo_results(snapshots: list[MarketSnapshot], counters: CounterSnapshot, mode: str) -> int:
    print()
    print("=" * 78)
    print(f"Market scanner iteration -- DEMO mode (mode={mode}, synthetic data)")
    print("=" * 78)
    if not snapshots:
        print()
        print("  (sin snapshots en esta iteracion)")
    else:
        print()
        print(f"  {'SYMBOL':<14} {'LAST':>10} {'VOL_24H_USDT':>16} {'SPR_BPS':>9} {'ATR%':>7} {'SCORE':>7}  STATUS")
        print("  " + "-" * 76)
        for snap in snapshots:
            atr = f"{snap.atr_pct:.2f}" if snap.atr_pct is not None else "  n/a"
            status = "ACTIVE" if snap.active else f"INACTIVE ({snap.rejection_reason})"
            print(
                f"  {snap.symbol:<14} "
                f"{snap.last_price:>10.2f} "
                f"{snap.volume_24h_usdt:>16,.0f} "
                f"{snap.spread_bps:>9.2f} "
                f"{atr:>7} "
                f"{snap.rank_score:>7.3f}  {status}"
            )
    print()
    print("Counters (pine contract: spec section 10):")
    print(f"  pairs_processed:  {counters.pairs_processed}")
    print(f"  pairs_active:     {counters.pairs_active}")
    print(f"  pairs_inactive:   {counters.pairs_inactive}")
    print(f"  scanner_errors:   {counters.scanner_errors}")
    print()
    return 0


def _update_runtime_state(
    state: RuntimeState,
    snapshots: list[MarketSnapshot],
    counters: CounterSnapshot,
    *,
    iteration: int,
    live_execution: LiveExecutionState,
) -> None:
    state.iteration = iteration
    state.last_updated_at = _utc_now_iso()
    state.last_pairs_processed = counters.pairs_processed
    state.last_pairs_active = counters.pairs_active
    state.last_pairs_inactive = counters.pairs_inactive
    state.last_scanner_errors = counters.scanner_errors
    state.last_summary = [
        {
            "symbol": snap.symbol,
            "status": "ACTIVE" if snap.active else "INACTIVE",
            "score": round(snap.rank_score, 3),
            "reason": snap.rejection_reason or "",
            "price": round(snap.last_price, 8),
            "volume24h": round(snap.volume_24h_usdt, 4),
            "spreadPct": round(snap.spread_bps / 100.0, 4),
            "volatility1m": round(snap.volatility_pct or 0.0, 4),
        }
        for snap in snapshots
    ]
    state.last_live_event = live_execution.last_event
    state.live_orders_sent = live_execution.orders_sent


def _balance_for_asset(balances: list[Balance], asset: str) -> Balance | None:
    return next((row for row in balances if row.asset == asset), None)


def _infer_futures_direction(symbol: str, market_client: BitunixSpotClient) -> tuple[str, str]:
    """Infer LONG/SHORT from the latest short-term OHLCV slope."""

    candles = market_client.fetch_recent_ohlcv(symbol, limit=5)
    if len(candles) < 2:
        return "LONG", "ohlcv_direction_fallback_long_insufficient_history"

    first_close = candles[0].close
    last_close = candles[-1].close
    if last_close >= first_close:
        return "LONG", "ohlcv_direction_last_close_gte_first_close"
    return "SHORT", "ohlcv_direction_last_close_lt_first_close"


def _default_trade_journal_url() -> str:
    return "sqlite:///data/trade_journal.db"


def _default_snapshot_dir() -> Path:
    return Path("data/chart_snapshots")


def _create_futures_trade_case(
    *,
    snap: MarketSnapshot,
    direction: str,
    direction_reason: str,
    qty: float,
    tp_price: float,
    sl_price: float,
    market_client: BitunixSpotClient,
    journal_url: str | None = None,
    snapshot_dir: Path | None = None,
) -> tuple[str, str]:
    now_ms = int(time.time() * 1000)
    journal_url = journal_url or _default_trade_journal_url()
    snapshot_dir = snapshot_dir or _default_snapshot_dir()
    trade_case_id = f"tc-{uuid4().hex}"
    signal_id = f"sig-{to_api_symbol(snap.symbol)}-{now_ms}"
    candles = tuple(market_client.fetch_recent_ohlcv(snap.symbol, limit=80))
    thesis = build_entry_thesis(
        EntryThesisInput(
            trade_case_id=trade_case_id,
            signal_id=signal_id,
            symbol=snap.symbol,
            direction=direction,
            entry_price=snap.last_price,
            tp_price=tp_price,
            sl_price=sl_price,
            timeframe="1m",
            entry_reason=direction_reason,
            candles=candles,
            indicators={
                "scanner_score": round(snap.rank_score, 6),
                "volume_24h_usdt": round(snap.volume_24h_usdt, 6),
                "spread_bps": round(snap.spread_bps, 6),
                "atr_pct": round(snap.atr_pct or 0.0, 6),
                "planned_qty": qty,
            },
            created_at=now_ms,
        ),
        swing_window=2,
    )
    snapshot = render_local_chart_snapshot(
        ChartSnapshotRequest(
            trade_case_id=trade_case_id,
            symbol=snap.symbol,
            direction=direction,
            entry_price=snap.last_price,
            tp_price=tp_price,
            sl_price=sl_price,
            candles=candles,
            zones=thesis.zones,
            output_dir=snapshot_dir,
            captured_at=now_ms,
        )
    )
    with TradeJournalStore(journal_url) as journal:
        journal.create_case(
            TradeCase(
                trade_case_id=trade_case_id,
                signal_id=signal_id,
                symbol=snap.symbol,
                direction=direction,  # type: ignore[arg-type]
                status="pending_order",
                created_at=now_ms,
                entry_thesis=thesis,
                chart_snapshot=snapshot,
            )
        )
    return trade_case_id, snapshot.path


def _mark_trade_case_order_open(
    *,
    trade_case_id: str,
    order_id: str | None,
    position_id: str | None = None,
    journal_url: str = _default_trade_journal_url(),
) -> None:
    with TradeJournalStore(journal_url) as journal:
        journal.update_case_status(
            trade_case_id,
            status="open",
            order_id=order_id,
            position_id=position_id,
            updated_at=int(time.time() * 1000),
        )


def _mark_trade_case_order_rejected(
    *,
    trade_case_id: str,
    journal_url: str = _default_trade_journal_url(),
) -> None:
    with TradeJournalStore(journal_url) as journal:
        journal.update_case_status(
            trade_case_id,
            status="order_rejected",
            updated_at=int(time.time() * 1000),
        )


def _to_slash_symbol(api_symbol: str) -> str:
    if "/" in api_symbol:
        return api_symbol
    if api_symbol.endswith("USDT"):
        return f"{api_symbol[:-4]}/USDT"
    return api_symbol


def _find_open_trade_case(symbol: str, journal_url: str = _default_trade_journal_url()) -> TradeCase | None:
    with TradeJournalStore(journal_url) as journal:
        cases = journal.list_cases(symbol=symbol, status="open", limit=1)
    return cases[0] if cases else None


def _mark_trade_case_closed_from_position(
    *,
    symbol: str,
    position_id: str,
    side: str,
    qty: float,
    avg_open_price: float,
    pnl_net: float,
    close_reason: str,
    journal_url: str = _default_trade_journal_url(),
) -> str | None:
    case = _find_open_trade_case(symbol, journal_url=journal_url)
    if case is None or case.entry_thesis is None:
        return None

    risk_per_unit = abs(case.entry_thesis.entry_price - case.entry_thesis.sl_price)
    risk_amount = risk_per_unit * qty
    r_multiple = pnl_net / risk_amount if risk_amount > 0 else 0.0
    win_loss = "win" if pnl_net > 0 else "loss" if pnl_net < 0 else "breakeven"
    diagnosis = [close_reason]
    if close_reason == "signal_direction_flipped":
        diagnosis.append("structure_invalidated")
    if side.upper() == "BUY" and pnl_net > 0:
        diagnosis.append("support_respected")
    if side.upper() == "SELL" and pnl_net > 0:
        diagnosis.append("resistance_rejected")

    outcome = TradeOutcome(
        trade_case_id=case.trade_case_id,
        position_id=position_id,
        exit_reason=close_reason,
        pnl_net=round(pnl_net, 10),
        r_multiple=round(r_multiple, 6),
        mfe=0.0,
        mae=0.0,
        win_loss=win_loss,  # type: ignore[arg-type]
        closed_at=int(time.time() * 1000),
        post_trade_diagnosis=tuple(dict.fromkeys(diagnosis)),
    )
    with TradeJournalStore(journal_url) as journal:
        journal.save_outcome(outcome)
        journal.update_case_status(
            case.trade_case_id,
            status="closed",
            position_id=position_id,
            updated_at=outcome.closed_at,
        )
    return case.trade_case_id


def _save_reconciled_close(
    *,
    journal: TradeJournalStore,
    case: TradeCase,
    position_id: str,
    reason: str,
) -> None:
    closed_at = int(time.time() * 1000)
    outcome = TradeOutcome(
        trade_case_id=case.trade_case_id,
        position_id=position_id,
        exit_reason=reason,
        pnl_net=0.0,
        r_multiple=0.0,
        mfe=0.0,
        mae=0.0,
        win_loss="breakeven",
        closed_at=closed_at,
        post_trade_diagnosis=(reason,),
    )
    journal.save_outcome(outcome)


def _reconcile_missing_open_trade_cases(
    *,
    open_symbols: set[str],
    journal_url: str = _default_trade_journal_url(),
) -> list[str]:
    reconciled: list[str] = []
    with TradeJournalStore(journal_url) as journal:
        open_cases = journal.list_cases(status="open", limit=100)
        for case in open_cases:
            if case.symbol in open_symbols or case.entry_thesis is None:
                continue
            _save_reconciled_close(
                journal=journal,
                case=case,
                position_id=case.position_id or "unknown",
                reason="position_missing_on_reconcile",
            )
            reconciled.append(case.trade_case_id)
    return reconciled


def _reconcile_open_trade_cases_with_positions(
    *,
    positions: list[BitunixFuturesPosition],
    journal_url: str = _default_trade_journal_url(),
) -> list[str]:
    by_symbol = {
        _to_slash_symbol(position.symbol): position
        for position in positions
        if position.qty > 0
    }
    reconciled: list[str] = []
    with TradeJournalStore(journal_url) as journal:
        open_cases = journal.list_cases(status="open", limit=100)
        for case in open_cases:
            position = by_symbol.get(case.symbol)
            if position is None:
                _save_reconciled_close(
                    journal=journal,
                    case=case,
                    position_id=case.position_id or "unknown",
                    reason="position_missing_on_reconcile",
                )
                reconciled.append(case.trade_case_id)
                continue

            position_direction = "LONG" if position.side.upper() == "BUY" else "SHORT"
            if case.direction != position_direction:
                _save_reconciled_close(
                    journal=journal,
                    case=case,
                    position_id=case.position_id or "unknown",
                    reason="position_direction_mismatch_on_reconcile",
                )
                reconciled.append(case.trade_case_id)
                continue

            if case.position_id != position.position_id:
                journal.update_case_status(
                    case.trade_case_id,
                    status="open",
                    position_id=position.position_id,
                    updated_at=int(time.time() * 1000),
                )
    return reconciled


def _maybe_execute_live_trade(
    *,
    settings: Settings,
    snapshots: list[MarketSnapshot],
    client: BitunixSpotClient,
    execution: LiveExecutionState,
    trade_quote_usdt: float,
    max_live_orders: int,
    symbol_cooldown_seconds: int,
) -> dict[str, object]:
    min_notional_buffer = 1.02
    now_ts = time.time()

    if settings.runtime.mode != TradingMode.LIVE:
        return {"status": "SKIPPED", "reason": "mode_is_not_live"}
    if execution.orders_sent >= max_live_orders:
        return {"status": "SKIPPED", "reason": "session_order_cap_reached"}
    if trade_quote_usdt <= 0:
        return {"status": "SKIPPED", "reason": "trade_quote_usdt_must_be_positive"}

    active = sorted((snap for snap in snapshots if snap.active), key=lambda snap: snap.rank_score, reverse=True)
    if not active:
        return {"status": "SKIPPED", "reason": "no_active_signals"}

    balances = client.fetch_balances()
    usdt_balance = _balance_for_asset(balances, "USDT")
    usdt_free = usdt_balance.free if usdt_balance is not None else 0.0
    if usdt_free <= 0:
        return {"status": "SKIPPED", "reason": "no_free_usdt_balance"}

    for snap in active:
        last_trade_ts = execution.traded_symbols.get(snap.symbol)
        if last_trade_ts is not None and (now_ts - last_trade_ts) < symbol_cooldown_seconds:
            cooldown_left = int(symbol_cooldown_seconds - (now_ts - last_trade_ts))
            print(f"[run] live-skip symbol={snap.symbol} reason=symbol_cooldown_active cooldown_left_seconds={cooldown_left}")
            continue

        rule = client.get_symbol(snap.symbol)
        if not rule.is_open or rule.quote != "USDT":
            print(f"[run] live-skip symbol={snap.symbol} reason=symbol_not_open_or_quote_not_usdt is_open={rule.is_open} quote={rule.quote}")
            continue

        min_target_usdt = rule.min_trade_value_usdt * min_notional_buffer if rule.min_trade_value_usdt > 0 else 0.0
        desired_usdt = max(trade_quote_usdt, min_target_usdt)
        target_usdt = min(desired_usdt, usdt_free)
        if target_usdt < rule.min_trade_value_usdt:
            print(f"[run] live-skip symbol={snap.symbol} reason=target_below_min_notional target_usdt={target_usdt:.6f} min_trade_value_usdt={rule.min_trade_value_usdt:.6f}")
            continue

        raw_amount = target_usdt / snap.last_price
        amount = max(rule.min_volume, raw_amount)
        amount = rule.round_base_amount(amount)
        estimated_cost = amount * snap.last_price
        if estimated_cost > usdt_free:
            amount = rule.round_base_amount((usdt_free * 0.98) / snap.last_price)
            estimated_cost = amount * snap.last_price
        if amount <= 0:
            print(f"[run] live-skip symbol={snap.symbol} reason=rounded_amount_zero")
            continue
        if amount < rule.min_volume:
            print(f"[run] live-skip symbol={snap.symbol} reason=amount_below_min_volume amount={amount:.12f} min_volume={rule.min_volume:.12f}")
            continue
        if estimated_cost < rule.min_trade_value_usdt:
            print(
                f"[run] live-skip symbol={snap.symbol} reason=cost_below_min_notional "
                f"estimated_cost={estimated_cost:.6f} min_trade_value_usdt={rule.min_trade_value_usdt:.6f} "
                f"target_usdt={target_usdt:.6f} raw_amount={raw_amount:.12f} rounded_amount={amount:.12f}"
            )
            continue

        order = client.place_spot_order(
            symbol=snap.symbol,
            side="buy",
            order_type="market",
            amount=amount,
            price=snap.last_price,
        )
        execution.orders_sent += 1
        execution.traded_symbols[snap.symbol] = now_ts
        return {
            "status": "LIVE_ORDER_OK",
            "symbol": snap.symbol,
            "score": round(snap.rank_score, 3),
            "amount": amount,
            "estimatedCostUsdt": round(estimated_cost, 4),
            "orderId": order.get("orderId"),
            "placeStatus": order.get("placeStatus"),
        }

    return {"status": "SKIPPED", "reason": "no_tradeable_active_signal"}


def _close_stale_futures_positions(
    *,
    active_api_symbols: set[str],
    client: BitunixFuturesClient,
    execution: LiveExecutionState,
    desired_directions: dict[str, str] | None = None,
) -> dict[str, object] | None:
    positions = client.get_pending_positions()
    for position in positions:
        if position.qty <= 0:
            continue
        close_reason: str | None = None
        if position.symbol not in active_api_symbols:
            close_reason = "signal_no_longer_active"
        elif desired_directions:
            desired_direction = desired_directions.get(position.symbol)
            current_direction = "LONG" if position.side.upper() == "BUY" else "SHORT"
            if desired_direction and desired_direction != current_direction:
                close_reason = "signal_direction_flipped"
        if close_reason is None:
            continue
        result = client.flash_close_position(position.position_id)
        closed_trade_case_id = _mark_trade_case_closed_from_position(
            symbol=_to_slash_symbol(position.symbol),
            position_id=position.position_id,
            side=position.side,
            qty=position.qty,
            avg_open_price=position.avg_open_price,
            pnl_net=position.realized_pnl + position.unrealized_pnl,
            close_reason=close_reason,
        )
        execution.orders_sent += 1
        execution.traded_symbols[position.symbol] = time.time()
        return {
            "status": "FUTURES_POSITION_CLOSED",
            "tradeCaseId": closed_trade_case_id,
            "symbol": position.symbol,
            "positionId": position.position_id,
            "side": position.side,
            "qty": position.qty,
            "reason": close_reason,
            "result": result,
        }
    return None


def _maybe_execute_live_futures_trade(
    *,
    settings: Settings,
    snapshots: list[MarketSnapshot],
    futures_client: BitunixFuturesClient,
    market_client: BitunixSpotClient,
    execution: LiveExecutionState,
    trade_quote_usdt: float,
    max_live_orders: int,
    symbol_cooldown_seconds: int,
) -> dict[str, object]:
    now_ts = time.time()

    if settings.runtime.mode != TradingMode.LIVE:
        return {"status": "SKIPPED", "reason": "mode_is_not_live"}
    if execution.orders_sent >= max_live_orders:
        return {"status": "SKIPPED", "reason": "session_order_cap_reached"}
    if trade_quote_usdt <= 0:
        return {"status": "SKIPPED", "reason": "trade_quote_usdt_must_be_positive"}

    active = sorted((snap for snap in snapshots if snap.active), key=lambda snap: snap.rank_score, reverse=True)
    active_api_symbols = {to_api_symbol(snap.symbol) for snap in active}
    desired_directions: dict[str, str] = {}
    direction_reasons: dict[str, str] = {}
    for snap in active:
        direction, reason = _infer_futures_direction(snap.symbol, market_client)
        api_symbol = to_api_symbol(snap.symbol)
        desired_directions[api_symbol] = direction
        direction_reasons[api_symbol] = reason
    close_event = _close_stale_futures_positions(
        active_api_symbols=active_api_symbols,
        client=futures_client,
        execution=execution,
        desired_directions=desired_directions,
    )
    if close_event is not None:
        return close_event

    if not active:
        return {"status": "SKIPPED", "reason": "no_active_signals"}

    open_positions = [position for position in futures_client.get_pending_positions() if position.qty > 0]
    reconciled_trade_cases = _reconcile_open_trade_cases_with_positions(
        positions=open_positions
    )
    if open_positions:
        return {
            "status": "SKIPPED",
            "reason": "open_futures_position_exists",
            "openSymbols": [position.symbol for position in open_positions],
            "reconciledTradeCases": reconciled_trade_cases,
        }

    account = futures_client.get_account("USDT")
    available_margin = account.available + account.cross_unrealized_pnl
    if available_margin <= 0:
        return {"status": "SKIPPED", "reason": "no_available_futures_margin"}

    tp_pct = float(settings.risk.default_take_profit_pct)
    sl_pct = float(settings.risk.default_stop_loss_pct)

    for snap in active:
        api_symbol = to_api_symbol(snap.symbol)
        last_trade_ts = execution.traded_symbols.get(api_symbol)
        if last_trade_ts is not None and (now_ts - last_trade_ts) < symbol_cooldown_seconds:
            cooldown_left = int(symbol_cooldown_seconds - (now_ts - last_trade_ts))
            print(f"[run] futures-skip symbol={snap.symbol} reason=symbol_cooldown_active cooldown_left_seconds={cooldown_left}")
            continue

        rule = futures_client.get_symbol(snap.symbol)
        if rule.symbol_status != "OPEN" or not rule.is_api_supported:
            print(f"[run] futures-skip symbol={snap.symbol} reason=symbol_not_tradeable status={rule.symbol_status} api_supported={rule.is_api_supported}")
            continue

        target_usdt = min(trade_quote_usdt, available_margin)
        raw_qty = target_usdt / snap.last_price
        precision = max(rule.base_precision, 0)
        qty = float(f"{raw_qty:.{precision}f}") if precision > 0 else float(int(raw_qty))
        if qty <= 0:
            print(f"[run] futures-skip symbol={snap.symbol} reason=rounded_qty_zero")
            continue
        if qty < rule.min_trade_volume:
            print(
                f"[run] futures-skip symbol={snap.symbol} reason=qty_below_min_trade_volume "
                f"qty={qty:.12f} min_trade_volume={rule.min_trade_volume:.12f}"
            )
            continue
        if rule.max_market_order_volume > 0 and qty > rule.max_market_order_volume:
            qty = rule.max_market_order_volume

        direction = desired_directions.get(api_symbol, "LONG")
        direction_reason = direction_reasons.get(api_symbol, "direction_reason_unavailable")
        side = "BUY" if direction == "LONG" else "SELL"
        if direction == "LONG":
            tp_price = snap.last_price * (1 + tp_pct / 100.0)
            sl_price = snap.last_price * (1 - sl_pct / 100.0)
        else:
            tp_price = snap.last_price * (1 - tp_pct / 100.0)
            sl_price = snap.last_price * (1 + sl_pct / 100.0)

        trade_case_id, chart_snapshot_path = _create_futures_trade_case(
            snap=snap,
            direction=direction,
            direction_reason=direction_reason,
            qty=qty,
            tp_price=tp_price,
            sl_price=sl_price,
            market_client=market_client,
        )
        try:
            order = futures_client.place_order(
                symbol=snap.symbol,
                side=side,
                qty=qty,
                order_type="MARKET",
                trade_side="OPEN",
                tp_price=tp_price,
                sl_price=sl_price,
            )
        except Exception:
            _mark_trade_case_order_rejected(trade_case_id=trade_case_id)
            raise

        order_id = order.get("orderId")
        new_positions = futures_client.get_pending_positions(snap.symbol)
        position_id = next((position.position_id for position in new_positions if position.qty > 0), None)
        _mark_trade_case_order_open(
            trade_case_id=trade_case_id,
            order_id=str(order_id) if order_id is not None else None,
            position_id=position_id,
        )
        execution.orders_sent += 1
        execution.traded_symbols[api_symbol] = now_ts
        return {
            "status": "FUTURES_ORDER_OK",
            "tradeCaseId": trade_case_id,
            "chartSnapshotPath": chart_snapshot_path,
            "positionId": position_id,
            "symbol": snap.symbol,
            "direction": direction,
            "assumption": direction_reason,
            "score": round(snap.rank_score, 3),
            "qty": qty,
            "tpPrice": round(tp_price, rule.quote_precision),
            "slPrice": round(sl_price, rule.quote_precision),
            "orderId": order_id,
            "clientId": order.get("clientId"),
        }

    return {"status": "SKIPPED", "reason": "no_tradeable_active_signal"}


def _cmd_scan(args: argparse.Namespace) -> int:
    if not args.demo:
        snapshots, counters, _, _ = _run_single_live_iteration(
            config_dir=args.config_dir,
            env_file=args.env_file if args.env_file else None,
        )
        return _print_demo_results(snapshots, counters, mode=args.mode)

    snapshots, counters = _run_single_iteration(mode=args.mode)
    return _print_demo_results(snapshots, counters, mode=args.mode)


def _cmd_run(args: argparse.Namespace) -> int:
    if args.loop_seconds < 1:
        sys.stderr.write("ERROR: --loop-seconds debe ser >= 1.\n")
        return 2
    if args.web_port < 0:
        sys.stderr.write("ERROR: --web-port debe ser >= 0.\n")
        return 2
    if args.max_live_orders < 1:
        sys.stderr.write("ERROR: --max-live-orders debe ser >= 1.\n")
        return 2
    if args.symbol_cooldown_seconds < 0:
        sys.stderr.write("ERROR: --symbol-cooldown-seconds debe ser >= 0.\n")
        return 2

    state = RuntimeState(mode=args.mode)
    live_execution = LiveExecutionState()
    lock = Lock()
    web_server: ThreadingHTTPServer | None = None
    if args.web_port:
        web_server = _start_web_server(args.web_host, args.web_port, state, lock)
        print(f"[run] dashboard web disponible en http://{args.web_host}:{args.web_port}")

    env_file = args.env_file if args.env_file else None
    loop_label = "live real" if args.mode in {"live", "shadow_live"} else "--demo"

    def execute_iteration(iteration: int) -> int:
        if args.mode in {"live", "shadow_live"}:
            print(f"[run] ejecutando una iteracion {loop_label} (mode={args.mode})." if args.once else "")
            try:
                snapshots, counters, client, settings = _run_single_live_iteration(
                    config_dir=args.config_dir,
                    env_file=env_file,
                )
            except Exception as exc:
                live_execution.last_event = {"status": "ERROR", "reason": type(exc).__name__, "message": str(exc)}
                with lock:
                    _update_runtime_state(
                        state,
                        [],
                        type("CounterSnapshotLike", (), {
                            "pairs_processed": 0,
                            "pairs_active": 0,
                            "pairs_inactive": 0,
                            "scanner_errors": 1,
                        })(),
                        iteration=iteration,
                        live_execution=live_execution,
                    )
                print(f"[run] live-error={json.dumps(live_execution.last_event, ensure_ascii=True)}")
                return 1

            if args.auto_trade:
                try:
                    if args.market_kind == "futures":
                        futures_client = BitunixFuturesClient(
                            api_key=settings.exchange.api_key,
                            api_secret=settings.exchange.api_secret,
                        )
                        live_execution.last_event = _maybe_execute_live_futures_trade(
                            settings=settings,
                            snapshots=snapshots,
                            futures_client=futures_client,
                            market_client=client,
                            execution=live_execution,
                            trade_quote_usdt=args.trade_quote_usdt,
                            max_live_orders=args.max_live_orders,
                            symbol_cooldown_seconds=args.symbol_cooldown_seconds,
                        )
                    else:
                        live_execution.last_event = _maybe_execute_live_trade(
                            settings=settings,
                            snapshots=snapshots,
                            client=client,
                            execution=live_execution,
                            trade_quote_usdt=args.trade_quote_usdt,
                            max_live_orders=args.max_live_orders,
                            symbol_cooldown_seconds=args.symbol_cooldown_seconds,
                        )
                except Exception as exc:
                    live_execution.last_event = {"status": "ERROR", "reason": type(exc).__name__, "message": str(exc)}
                print(f"[run] live-event={json.dumps(live_execution.last_event, ensure_ascii=True)}")

            with lock:
                _update_runtime_state(state, snapshots, counters, iteration=iteration, live_execution=live_execution)
            return _print_demo_results(snapshots, counters, mode=args.mode)

        snapshots, counters = _run_single_iteration(mode=args.mode)
        with lock:
            _update_runtime_state(state, snapshots, counters, iteration=iteration, live_execution=live_execution)
        return _print_demo_results(snapshots, counters, mode=args.mode)

    if args.once:
        exit_code = execute_iteration(1)
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        return exit_code

    print(f"[run] iniciando loop continuo {loop_label} (mode={args.mode}, every={args.loop_seconds}s). Ctrl+C para salir.")
    iteration = 0
    try:
        while True:
            iteration += 1
            print()
            print(f"[run] iteration={iteration}")
            execute_iteration(iteration)
            print(f"[run] sleeping {args.loop_seconds}s before next iteration...")
            time.sleep(args.loop_seconds)
    except KeyboardInterrupt:
        print("\n[run] parada manual detectada. Saliendo de forma segura.")
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        return 0


def _cmd_place_order(args: argparse.Namespace) -> int:
    if not args.confirm_live:
        sys.stderr.write("ERROR: falta --confirm-live para habilitar una orden real.\n")
        return 2

    env_file = args.env_file if args.env_file else None
    settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    if settings.runtime.mode != TradingMode.LIVE:
        sys.stderr.write("ERROR: runtime.mode debe ser 'live' para colocar una orden real.\n")
        return 2

    if args.market_kind == "futures":
        client = BitunixFuturesClient(
            api_key=settings.exchange.api_key,
            api_secret=settings.exchange.api_secret,
        )
        try:
            order = client.place_order(
                symbol=args.symbol,
                side=args.side,
                qty=float(args.amount),
                order_type=args.order_type,
                trade_side=args.trade_side,
                price=float(args.price) if args.price is not None else None,
                position_id=args.position_id,
                reduce_only=bool(args.reduce_only),
                tp_price=args.tp_price,
                sl_price=args.sl_price,
            )
        except BitunixAPIError as exc:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
            return 1

        print(
            json.dumps(
                {
                    "success": True,
                    "marketKind": "futures",
                    "symbol": args.symbol,
                    "side": args.side,
                    "tradeSide": args.trade_side,
                    "orderType": args.order_type,
                    "amount": float(args.amount),
                    "price": float(args.price) if args.price is not None else None,
                    "orderId": order.get("orderId"),
                    "clientId": order.get("clientId"),
                },
                ensure_ascii=True,
            )
        )
        return 0

    client = BitunixSpotClient(
        api_key=settings.exchange.api_key,
        api_secret=settings.exchange.api_secret,
    )
    price = float(args.price) if args.price is not None else client.fetch_last_price(args.symbol)
    try:
        order = client.place_spot_order(
            symbol=args.symbol,
            side=args.side,
            order_type=args.order_type,
            amount=float(args.amount),
            price=price,
        )
    except BitunixAPIError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "marketKind": "spot",
                "symbol": args.symbol,
                "side": args.side,
                "orderType": args.order_type,
                "amount": float(args.amount),
                "price": price,
                "orderId": order.get("orderId"),
                "placeStatus": order.get("placeStatus"),
            },
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_positions(args: argparse.Namespace) -> int:
    env_file = args.env_file if args.env_file else None
    settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    client = BitunixFuturesClient(
        api_key=settings.exchange.api_key,
        api_secret=settings.exchange.api_secret,
    )
    try:
        positions = client.get_pending_positions(symbol=args.symbol)
    except BitunixAPIError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
        return 1
    print(
        json.dumps(
            {"success": True, "positions": [asdict(position) for position in positions]},
            ensure_ascii=True,
        )
    )
    return 0


def _cmd_close_position(args: argparse.Namespace) -> int:
    env_file = args.env_file if args.env_file else None
    settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    client = BitunixFuturesClient(
        api_key=settings.exchange.api_key,
        api_secret=settings.exchange.api_secret,
    )
    try:
        result = client.flash_close_position(args.position_id)
    except BitunixAPIError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps({"success": True, "marketKind": "futures", "result": result}, ensure_ascii=True))
    return 0


def _cmd_set_tpsl(args: argparse.Namespace) -> int:
    env_file = args.env_file if args.env_file else None
    settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    client = BitunixFuturesClient(
        api_key=settings.exchange.api_key,
        api_secret=settings.exchange.api_secret,
    )
    try:
        result = client.place_position_tpsl(
            symbol=args.symbol,
            position_id=args.position_id,
            qty=float(args.qty),
            tp_price=args.tp_price,
            sl_price=args.sl_price,
        )
    except BitunixAPIError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps({"success": True, "marketKind": "futures", "result": result}, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "config-check":
        return _cmd_config_check(args)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "place-order":
        return _cmd_place_order(args)
    if args.command == "positions":
        return _cmd_positions(args)
    if args.command == "close-position":
        return _cmd_close_position(args)
    if args.command == "set-tpsl":
        return _cmd_set_tpsl(args)
    if args.command == "kill-switch":
        print("[stub] kill-switch: pendiente.")
        return 0
    if args.command == "status":
        print("[stub] status: pendiente.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
