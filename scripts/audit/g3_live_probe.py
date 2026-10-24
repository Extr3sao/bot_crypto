"""G-3 probe: drive a *real* live entrypoint with an instrumented broker.

Why a subprocess probe and not a unit test
------------------------------------------
ACC-G3-04 asks for a restart, and a restart means a **new process**. The probe
runs `trading_bot.app.main` — the same function `python -m trading_bot.app`
runs — with the exchange clients replaced by recorders. The parser, the mode
guard, the gate and the dispatch code are the real ones; only the HTTP client is
a double, so nothing here can reach Bitunix.

What it does not prove
----------------------
It is not independent of the tests (same author, same fixtures). A passing probe
means "this program, built this way, would have called the broker N times"; it
does not vouch that the live exchange accepts the payload.

Usage
-----
    python scripts/audit/g3_live_probe.py \
        --entrypoint place-order-futures --run-dir .tmp/probe --json out.json

Exit status is the entrypoint's (0 ok/refused-by-policy, 2 refused, 1 error);
the JSON always carries ``broker_calls``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: The package under test. Defaults to this checkout; the mutation harness points
#: it at a variant so the *subprocess* exercises the mutant, not the original.
APP_SRC = Path(os.environ.get("G3_APP_SRC") or (ROOT / "src")).resolve()


def _candles(n: int = 6) -> list[SimpleNamespace]:
    """Ascending closes: `_infer_futures_direction` must answer LONG."""
    return [SimpleNamespace(close=100.0 + i) for i in range(n)]


class _Recorder:
    """Collects every call that leaves the process boundary."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, sink: str, **payload: Any) -> None:
        self.calls.append({"sink": sink, **payload})


def _build_fakes(recorder: _Recorder) -> dict[str, Any]:
    from trading_bot.market_data.types import Balance, MarketRules

    class FakeFutures:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def place_order(self, **kwargs: Any) -> dict[str, Any]:
            recorder.record("futures.place_order", **kwargs)
            return {"orderId": "probe-order-1", "clientId": kwargs.get("client_id")}

        def flash_close_position(self, position_id: str) -> dict[str, Any]:
            recorder.record("futures.flash_close_position", position_id=position_id)
            return {"positionId": position_id, "closed": True}

        def place_position_tpsl(self, **kwargs: Any) -> dict[str, Any]:
            recorder.record("futures.place_position_tpsl", **kwargs)
            return {"positionId": kwargs.get("position_id"), "tpsl": True}

        def get_pending_positions(self, symbol: str | None = None) -> list[Any]:
            return []

        def get_account(self, asset: str = "USDT") -> Any:
            return SimpleNamespace(available=1_000.0, cross_unrealized_pnl=0.0)

        def get_symbol(self, symbol: str) -> Any:
            return SimpleNamespace(
                symbol_status="OPEN",
                is_api_supported=True,
                base_precision=4,
                min_trade_volume=0.0001,
                max_market_order_volume=0.0,
                quote_precision=2,
            )

        def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
            return _candles()

    class FakeSpot:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def place_spot_order(self, **kwargs: Any) -> dict[str, Any]:
            recorder.record("spot.place_spot_order", **kwargs)
            return {"orderId": "probe-spot-1", "placeStatus": "FILLED"}

        def fetch_last_price(self, symbol: str) -> float:
            return 100.0

        def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
            return _candles()

    class FakeConnector:
        def load_markets(self) -> None:
            return None

        def fetch_balance(self) -> list[Any]:
            return [Balance(asset="USDT", free=1_000.0, used=0.0, total=1_000.0)]

        def fetch_market_rules(self, symbol: str) -> Any:
            return MarketRules(
                symbol=symbol,
                is_open=True,
                quote="USDT",
                min_trade_value_usdt=10.0,
                min_volume=0.0001,
                base_precision=4,
                quote_precision=2,
            )

        def create_order(self, **kwargs: Any) -> Any:
            recorder.record("connector.create_order", **kwargs)
            return SimpleNamespace(
                id="probe-connector-1",
                client_order_id="probe-cid",
                status="closed",
            )

    return {"FakeFutures": FakeFutures, "FakeSpot": FakeSpot, "FakeConnector": FakeConnector}


def _live_settings() -> Any:
    """A *legal* live configuration.

    ``build_demo_settings`` is a paper fixture: sandbox=True, no exchange_id, no
    credentials. A real ``load_settings`` rejects live+sandbox, so this fixture
    has to be corrected before a gate can be expected to pass it. The values are
    synthetic and never leave the process; the probe replaces the HTTP clients.
    """
    from trading_bot.config.runtime import TradingMode
    from trading_bot.market_data.fake import build_demo_settings

    settings = build_demo_settings(mode="live")
    return settings.model_copy(
        update={
            "exchange": settings.exchange.model_copy(
                update={
                    "id": "bitunix",
                    "sandbox": False,
                    "api_key": "probe-key",
                    "api_secret": "probe-secret",
                }
            ),
            "runtime": settings.runtime.model_copy(
                update={
                    "mode": TradingMode.LIVE,
                    "live_trading_enabled": True,
                    "exchange_id": "bitunix",
                }
            ),
        }
    )


def _supports_run_dir(app_module: Any, command: str) -> bool:
    """Does this build's CLI accept ``--run-dir`` for ``command``?

    The probe has to work against the tree *before* the fix as well, otherwise
    the red run would fail on argparse instead of on the bypass it is meant to
    show.
    """
    parser = app_module._build_parser()
    for action in parser._actions:
        if getattr(action, "dest", None) == "command":
            sub = action.choices.get(command)
            if sub is None:
                return False
            return any(getattr(a, "dest", None) == "run_dir" for a in sub._actions)
    return False


def _argv_for(entrypoint: str, run_dir: Path, trade_side: str, side: str) -> list[str]:
    if entrypoint == "place-order-futures":
        argv = [
            "place-order",
            "--symbol",
            "BTCUSDT",
            "--side",
            "buy",
            "--order-type",
            "market",
            "--amount",
            "0.01",
            "--confirm-live",
            "--market-kind",
            "futures",
            "--trade-side",
            trade_side,
        ]
        if trade_side == "CLOSE":
            argv.append("--reduce-only")
        return argv
    if entrypoint == "place-order-spot":
        return [
            "place-order",
            "--symbol",
            "BTC/USDT",
            "--side",
            side,
            "--order-type",
            "market",
            "--amount",
            "0.01",
            "--price",
            "100",
            "--confirm-live",
            "--market-kind",
            "spot",
        ]
    if entrypoint == "close-position":
        return ["close-position", "--position-id", "probe-pos-1"]
    if entrypoint == "set-tpsl":
        return [
            "set-tpsl",
            "--symbol",
            "BTCUSDT",
            "--position-id",
            "probe-pos-1",
            "--qty",
            "0.01",
            "--tp-price",
            "110",
            "--sl-price",
            "90",
        ]
    if entrypoint in {"run-futures", "run-spot"}:
        return [
            "run",
            "--mode",
            "live",
            "--once",
            "--auto-trade",
            "--market-kind",
            "futures" if entrypoint == "run-futures" else "spot",
            "--trade-quote-usdt",
            "50",
            "--loop-seconds",
            "30",
            "--env-file",
            "",
        ]
    raise SystemExit(f"unknown entrypoint {entrypoint!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive one live entrypoint offline.")
    parser.add_argument(
        "--entrypoint",
        required=True,
        choices=[
            "place-order-futures",
            "place-order-spot",
            "close-position",
            "set-tpsl",
            "run-futures",
            "run-spot",
        ],
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--trade-side", default="OPEN", choices=["OPEN", "CLOSE"])
    parser.add_argument("--side", default="buy", choices=["buy", "sell"])
    parser.add_argument("--env-kill-switch", default="", help="Value for TRADING_BOT_KILL_SWITCH.")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    # GATE-006 resolves the configured SQLite path against the working
    # directory; a deployment has it, a fresh `git archive` export does not.
    (Path.cwd() / "data" / "storage").mkdir(parents=True, exist_ok=True)

    if args.env_kill_switch:
        # Must be set before trading_bot.autonomous.decision is imported: the
        # switch boots once, at import.
        os.environ["TRADING_BOT_KILL_SWITCH"] = args.env_kill_switch
    else:
        os.environ.pop("TRADING_BOT_KILL_SWITCH", None)

    sys.path.insert(0, str(APP_SRC))

    from trading_bot import app as app_module
    from trading_bot.autonomous.hot_stop import AUDIT_FILE_NAME, HOT_STOP_FILE_NAME

    recorder = _Recorder()
    fakes = _build_fakes(recorder)
    settings = _live_settings()

    # One Any-typed alias: the module really does export these names, but
    # assigning to them through the module type is not visible to mypy.
    live_app: Any = app_module
    live_app.BitunixFuturesClient = fakes["FakeFutures"]
    live_app.BitunixSpotClient = fakes["FakeSpot"]
    live_app.load_settings = lambda **kwargs: settings

    def _single_live_iteration(config_dir: str, env_file: str | None) -> Any:
        snapshots = [
            SimpleNamespace(
                symbol="BTC/USDT",
                active=True,
                last_price=100.0,
                rank_score=0.9,
                spread_bps=1.0,
                volume_24h_usdt=5_000_000.0,
                atr_pct=0.5,
                volatility_pct=0.5,
                timestamp=0,
                rejection_reason=None,
            )
        ]
        counters = SimpleNamespace(
            pairs_processed=1, pairs_active=1, pairs_inactive=0, scanner_errors=0
        )
        return snapshots, counters, fakes["FakeConnector"](), settings

    live_app._run_single_live_iteration = _single_live_iteration
    live_app._create_futures_trade_case = lambda **kwargs: ("probe-tc-1", "")
    live_app._mark_trade_case_order_open = lambda **kwargs: None
    live_app._reconcile_open_trade_cases_with_positions = lambda **kwargs: []

    cli = _argv_for(args.entrypoint, run_dir, args.trade_side, args.side)
    if _supports_run_dir(app_module, cli[0]) and "--run-dir" not in cli:
        cli += ["--run-dir", str(run_dir)]

    exit_code = 1
    error = ""
    try:
        exit_code = int(app_module.main(cli))
    except SystemExit as exc:  # argparse refusals
        exit_code = int(exc.code or 0)
    except BaseException as exc:  # the probe must report, not crash
        error = f"{type(exc).__name__}: {exc}"

    marker = run_dir / HOT_STOP_FILE_NAME
    payload = {
        "entrypoint": args.entrypoint,
        "argv": cli,
        "app_file": str(Path(app_module.__file__).resolve()),
        "app_src": str(APP_SRC),
        "patched": {
            "futures": live_app.BitunixFuturesClient.__name__,
            "spot": live_app.BitunixSpotClient.__name__,
        },
        "run_dir": str(run_dir),
        "exit_code": exit_code,
        "error": error,
        "broker_calls": len(recorder.calls),
        "calls": recorder.calls,
        "marker_present": marker.exists(),
        "marker_reason": marker.read_text(encoding="utf-8", errors="replace").strip()
        if marker.is_file()
        else "",
        "audit_lines": len((run_dir / AUDIT_FILE_NAME).read_text(encoding="utf-8").splitlines())
        if (run_dir / AUDIT_FILE_NAME).is_file()
        else 0,
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
