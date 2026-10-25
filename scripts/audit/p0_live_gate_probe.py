"""P0 probe: does a *rejecting* LiveTradingGate stop the broker call?

Why a subprocess probe
----------------------
The acceptance criterion is about the program, not about a helper function: a
gate that validates correctly in a unit test but is never consulted proves
nothing. This probe runs ``trading_bot.app.main`` — the same function
``python -m trading_bot.app`` runs — with the exchange clients replaced by
recorders. The parser, the mode guard, the hot-stop boundary, the live gate and
the dispatch code are the real ones; only the HTTP client is a double, so
nothing here can reach Bitunix.

``--break`` makes exactly one of the gate's ten checks fail through real
settings (or, for GATE-009/010, through a forced failure on the real class).
That is how the probe answers "if gate N rejects, is the order still sent?".

What it does not prove
----------------------
It is not independent of the tests: same author, same fixtures. ``gate_validations``
proves the gate ran; it cannot prove a real exchange would accept the payload.

Usage
-----
    python scripts/audit/p0_live_gate_probe.py \
        --entrypoint place-order-futures --run-dir .tmp/probe --break GATE-003 --json out.json

Exit status is the entrypoint's (0 ok/refused-by-policy, 2 refused, 1 error);
the JSON always carries ``broker_calls`` and ``gate_validations``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: The package under test. Defaults to this checkout; the mutation harness points
#: it at a variant so the *subprocess* exercises the mutant, not the original.
APP_SRC = Path(os.environ.get("P0_APP_SRC") or (ROOT / "src")).resolve()

GATE_IDS: tuple[str, ...] = tuple(f"GATE-{index:03d}" for index in range(1, 11))

ENTRYPOINTS: tuple[str, ...] = (
    "place-order-futures",
    "place-order-futures-close",
    "place-order-spot",
    "place-order-spot-sell",
    "close-position",
    "set-tpsl",
    "run-futures",
    "run-spot",
)


def _candles(n: int = 6) -> list[SimpleNamespace]:
    """Ascending closes: `_infer_futures_direction` must answer LONG."""
    return [SimpleNamespace(close=100.0 + i) for i in range(n)]


class _Recorder:
    """Collects every call that leaves the process boundary."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, sink: str, **payload: Any) -> None:
        self.calls.append({"sink": sink, **payload})


def _position() -> SimpleNamespace:
    """The position a close entrypoint claims to reduce.

    Without it the classifier cannot prove a reduction and the order becomes
    UNKNOWN — which is the behaviour the RFC wants, but not the case these
    probe entrypoints are about.
    """
    return SimpleNamespace(
        position_id="p0-pos-1",
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        position_mode="ONE_WAY",
    )


def _build_fakes(
    recorder: _Recorder, *, with_position: bool = False, constructions: dict[str, int] | None = None
) -> dict[str, Any]:
    from trading_bot.market_data.types import Balance, MarketRules

    counters = constructions if constructions is not None else {"client": 0, "scanner": 0}

    def observed() -> list[Any]:
        return [_position()] if with_position else []

    class FakeFutures:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            counters["client"] += 1

        def place_order(self, **kwargs: Any) -> dict[str, Any]:
            guard = kwargs.pop("payload_guard", None)
            if guard is not None:
                guard(
                    {
                        "symbol": kwargs.get("symbol"),
                        "side": str(kwargs.get("side", "")).upper(),
                        "qty": str(kwargs.get("qty")),
                        "tradeSide": str(kwargs.get("trade_side", "")).upper(),
                        "reduceOnly": bool(kwargs.get("reduce_only")),
                        "positionId": kwargs.get("position_id"),
                    }
                )
            recorder.record("futures.place_order", **kwargs)
            return {"orderId": "p0-order-1", "clientId": kwargs.get("client_id")}

        def flash_close_position(
            self, position_id: str, *, payload_guard: Any = None
        ) -> dict[str, Any]:
            payload = {"positionId": position_id}
            if payload_guard is not None:
                payload_guard(payload)
            recorder.record("futures.flash_close_position", position_id=position_id)
            return {"positionId": position_id, "closed": True}

        def place_position_tpsl(self, **kwargs: Any) -> dict[str, Any]:
            recorder.record("futures.place_position_tpsl", **kwargs)
            return {"positionId": kwargs.get("position_id"), "tpsl": True}

        def get_pending_positions(self, symbol: str | None = None) -> list[Any]:
            return observed()

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
            counters["client"] += 1

        def place_spot_order(self, **kwargs: Any) -> dict[str, Any]:
            recorder.record("spot.place_spot_order", **kwargs)
            return {"orderId": "p0-spot-1", "placeStatus": "FILLED"}

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
                id="p0-connector-1",
                client_order_id="p0-cid",
                status="closed",
            )

    return {"FakeFutures": FakeFutures, "FakeSpot": FakeSpot, "FakeConnector": FakeConnector}


def _live_settings() -> Any:
    """A *legal* live configuration: the gate must pass when nothing is broken.

    ``build_demo_settings`` is a paper fixture (sandbox=True, no exchange_id, no
    credentials). A real ``load_settings`` rejects live+sandbox, so the probe
    corrects those fields instead of asking the gate to bless an invalid config.
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
            "risk": settings.risk.model_copy(
                update={"kill_switch_enabled": True, "live_trading_enabled": False}
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


def _break_settings(settings: Any, gate_id: str) -> Any:
    """Make one check reject using real configuration values."""
    if gate_id == "GATE-001":
        return settings.model_copy(
            update={"runtime": settings.runtime.model_copy(update={"live_trading_enabled": False})}
        )
    if gate_id == "GATE-002":
        return settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
    if gate_id == "GATE-003":
        return settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"max_risk_per_trade_pct": 0.0})}
        )
    if gate_id == "GATE-004":
        return settings.model_copy(
            update={
                "exchange": settings.exchange.model_copy(update={"api_key": "", "api_secret": ""})
            }
        )
    if gate_id == "GATE-005":
        return settings.model_copy(
            update={"exchange": settings.exchange.model_copy(update={"sandbox": True})}
        )
    if gate_id == "GATE-006":
        return settings.model_copy(
            update={
                "runtime": settings.runtime.model_copy(
                    update={
                        "storage": settings.runtime.storage.model_copy(
                            update={"database_url": "sqlite:///p0-missing-state/db.sqlite"}
                        )
                    }
                )
            }
        )
    if gate_id == "GATE-007":
        return settings.model_copy(
            update={"runtime": settings.runtime.model_copy(update={"exchange_id": ""})}
        )
    if gate_id == "GATE-008":
        return settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"live_trading_enabled": True})}
        )
    if gate_id in {"GATE-009", "GATE-010"}:
        # These two checks cannot fail through configuration: one reports the
        # logging block, the other returns warnings on a pass. A forced failure
        # on the *real* class is the only way to ask whether a rejected check of
        # that severity still stops the order.
        return settings
    raise SystemExit(f"unknown gate {gate_id!r}")


def _force_check_failure(gate_id: str) -> None:
    from trading_bot.execution.live_gate import GateResult, LiveTradingGate

    def forced(self: Any) -> GateResult:
        return GateResult(
            gate_id=gate_id,
            name=f"Forced {gate_id}",
            passed=False,
            severity="critical",
            message="p0 probe: forced rejection",
        )

    target = "_check_logging" if gate_id == "GATE-009" else "_check_risk_limits"
    setattr(LiveTradingGate, target, forced)


def _supports_run_dir(app_module: Any, command: str) -> bool:
    """Does this build's CLI accept ``--run-dir`` for ``command``?

    The probe has to work against the tree *before* the fix as well, otherwise
    the red run would fail on argparse instead of on the order it sent.
    """
    parser = app_module._build_parser()
    for action in parser._actions:
        if getattr(action, "dest", None) == "command":
            sub = action.choices.get(command)
            if sub is None:
                return False
            return any(getattr(a, "dest", None) == "run_dir" for a in sub._actions)
    return False


def _argv_for(entrypoint: str, run_dir: Path) -> list[str]:
    if entrypoint in {"place-order-futures", "place-order-futures-close"}:
        closes = entrypoint.endswith("-close")
        argv = [
            "place-order",
            "--symbol",
            "BTCUSDT",
            "--side",
            # The fixture position is a LONG: closing it is a sell.
            "sell" if closes else "buy",
            "--order-type",
            "market",
            "--amount",
            "0.01",
            "--confirm-live",
            "--market-kind",
            "futures",
            "--trade-side",
            "CLOSE" if closes else "OPEN",
        ]
        if closes:
            argv += ["--reduce-only", "--position-id", "p0-pos-1"]
        return argv
    if entrypoint in {"place-order-spot", "place-order-spot-sell"}:
        return [
            "place-order",
            "--symbol",
            "BTC/USDT",
            "--side",
            "sell" if entrypoint.endswith("-sell") else "buy",
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
        return ["close-position", "--position-id", "p0-pos-1"]
    if entrypoint == "set-tpsl":
        return [
            "set-tpsl",
            "--symbol",
            "BTCUSDT",
            "--position-id",
            "p0-pos-1",
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
            "--confirm-live",
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
    parser.add_argument("--entrypoint", required=True, choices=ENTRYPOINTS)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--break", dest="break_gate", default=None, choices=GATE_IDS)
    parser.add_argument(
        "--gate-crash",
        action="store_true",
        help="Make LiveTradingGate.validate raise, to test the fail-closed wrapper.",
    )
    parser.add_argument(
        "--settings-error",
        action="store_true",
        help="Make load_settings raise, to test what happens when the config cannot be read.",
    )
    parser.add_argument(
        "--no-confirm-live",
        action="store_true",
        help="Drop --confirm-live from the argv, to test REQ-01.",
    )
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    # The gate's GATE-006 resolves the SQLite path against the working
    # directory. A deployment has that directory; a fresh `git archive` export
    # does not, because git does not store empty directories.
    (Path.cwd() / "data" / "storage").mkdir(parents=True, exist_ok=True)

    os.environ.pop("TRADING_BOT_KILL_SWITCH", None)
    sys.path.insert(0, str(APP_SRC))

    from trading_bot import app as app_module
    from trading_bot.execution.live_gate import LiveTradingGate

    recorder = _Recorder()
    constructions = {"client": 0, "scanner": 0}
    fakes = _build_fakes(
        recorder,
        with_position=args.entrypoint in {"place-order-futures-close", "close-position"},
        constructions=constructions,
    )
    settings = (
        _break_settings(_live_settings(), args.break_gate) if args.break_gate else _live_settings()
    )
    if args.settings_error:
        settings = _live_settings()

    # Count every time the real gate is consulted. A gate that is never called
    # is the defect this probe has to be able to see.
    validate_calls: list[int] = [0]
    original_validate = LiveTradingGate.validate

    def counting_validate(self: Any) -> Any:
        validate_calls[0] += 1
        return original_validate(self)

    setattr(LiveTradingGate, "validate", counting_validate)  # noqa: B010 - test double

    if args.gate_crash:

        def crashing_validate(self: Any) -> Any:
            validate_calls[0] += 1
            raise RuntimeError("p0 probe: gate crashed")

        setattr(LiveTradingGate, "validate", crashing_validate)  # noqa: B010
    elif args.break_gate in {"GATE-009", "GATE-010"}:
        _force_check_failure(args.break_gate)

    gate_module_file = getattr(sys.modules[LiveTradingGate.__module__], "__file__", None)

    live_app: Any = app_module
    live_app.BitunixFuturesClient = fakes["FakeFutures"]
    live_app.BitunixSpotClient = fakes["FakeSpot"]

    if args.settings_error:

        def raising_load_settings(**kwargs: Any) -> Any:
            raise ValueError("p0 probe: settings unavailable")

        live_app.load_settings = raising_load_settings
    else:
        live_app.load_settings = lambda **kwargs: settings

    def _single_live_iteration(config_dir: str, env_file: str | None) -> Any:
        constructions["scanner"] += 1
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
    live_app._create_futures_trade_case = lambda **kwargs: ("p0-tc-1", "")
    live_app._mark_trade_case_order_open = lambda **kwargs: None
    live_app._reconcile_open_trade_cases_with_positions = lambda **kwargs: []

    cli = _argv_for(args.entrypoint, run_dir)
    if args.no_confirm_live and "--confirm-live" in cli:
        cli.remove("--confirm-live")
    if _supports_run_dir(app_module, cli[0]) and "--run-dir" not in cli:
        cli += ["--run-dir", str(run_dir)]

    out, err = io.StringIO(), io.StringIO()
    exit_code = 1
    error = ""
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exit_code = int(app_module.main(cli))
    except SystemExit as exc:  # argparse refusals
        exit_code = int(exc.code or 0)
    except BaseException as exc:  # the probe must report, not crash
        error = f"{type(exc).__name__}: {exc}"

    payload = {
        "entrypoint": args.entrypoint,
        "break_gate": args.break_gate,
        "gate_crash": args.gate_crash,
        "settings_error": args.settings_error,
        "argv": cli,
        "app_file": str(Path(app_module.__file__).resolve()),
        "gate_file": str(Path(gate_module_file).resolve()) if gate_module_file else "",
        "app_src": str(APP_SRC),
        "patched": {"futures": live_app.BitunixFuturesClient.__name__},
        "run_dir": str(run_dir),
        "exit_code": exit_code,
        "error": error,
        "gate_validations": validate_calls[0],
        "broken_gate_ids": [args.break_gate] if args.break_gate else [],
        "no_confirm_live": args.no_confirm_live,
        "scanner_builds": constructions["scanner"],
        "client_constructions": constructions["client"],
        "broker_calls": len(recorder.calls),
        "calls": recorder.calls,
        "stdout_tail": out.getvalue()[-2000:],
        "stderr_tail": err.getvalue()[-2000:],
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
