"""Separate verification of RFC-TAP-EXEC-SEC-002.

What this buys, and what it does not
------------------------------------
This script does **not** import the implementation's test suite and does not
read its assertions. It exports the commit under review with ``git archive`` and
re-derives every requirement from ``docs/audit/RFC-TAP-EXEC-SEC-002.md``:

* structural checks parse the exported ``app.py`` and adapter AST;
* behavioural checks drive ``trading_bot.app.main`` in a subprocess against its
  own recording clients, with its own scenario table — not the fixtures in
  ``tests/unit/test_exec_sec_process.py``;
* the mutation matrix is re-run against the same commit and must kill every
  mutant.

It is still written by the same author as the implementation. The verdict is
therefore ``PROCEDURALLY_SEPARATED``, never "independently audited". It proves
that a different artefact, with its own scenarios, reaches the same result.

Usage
-----
    uv run --frozen python scripts/audit/verify_exec_sec.py --rev <sha>
    uv run --frozen python scripts/audit/verify_exec_sec.py --rev <sha> --json out.json

Exit status: 0 only when every check passes.

The ``--scenario`` mode is internal: it runs inside the exported tree with
``PYTHONPATH`` pointing at that tree, so every ``trading_bot`` import comes from
the commit under review rather than from this checkout.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

APP_REL = "src/trading_bot/app.py"
AUTH_REL = "src/trading_bot/execution/order_authorization.py"
ADAPTER_REL = "src/trading_bot/market_data/bitunix_futures.py"
STOP_REL = "src/trading_bot/autonomous/hot_stop.py"
GATE_REL = "src/trading_bot/execution/live_gate.py"

#: ``hot_stop.py`` as verified by G-1/G-2/G-3 and P0. This RFC must not change it.
HOT_STOP_SHA256 = "76cfca23d1e7758607c466eea4ff5c0a9411cb812d433eb7ca16dfb45cfdf8b1"

GATE_IDS: tuple[str, ...] = tuple(f"GATE-{index:03d}" for index in range(1, 11))

SUITE_TARGETS: tuple[str, ...] = (
    "tests/unit/test_order_authorization.py",
    "tests/unit/test_exec_sec_process.py",
    "tests/unit/test_live_gate_enforcement.py",
    "tests/unit/test_live_hot_stop_coverage.py",
    "tests/unit/test_app_cli_contract.py",
    "tests/unit/test_app_demo.py",
    "tests/unit/test_app_trade_journal.py",
)


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate
    return here.parents[2]


REPO_ROOT = _find_repo_root()


@dataclass
class Check:
    check_id: str
    criterion: str
    description: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scenario runner (executed against the export)
# ---------------------------------------------------------------------------


def _scenario_mode(spec_path: Path, out_path: Path) -> int:
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    results = [_run_scenario(spec) for spec in payload["scenarios"]]
    out_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


def _break_settings(settings: Any, gate_id: str) -> Any:
    """Make exactly one check reject through real configuration."""
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
                "exchange": settings.exchange.model_copy(
                    update={"api_key": "", "api_secret": ""}
                )
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
                            update={"database_url": "sqlite:///verify-missing/db.sqlite"}
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
    return settings


def _settings(*, legal: bool) -> Any:
    from trading_bot.config.runtime import TradingMode
    from trading_bot.market_data.fake import build_demo_settings

    settings = build_demo_settings(mode="live")
    updates: dict[str, Any] = {
        "id": "bitunix",
        "sandbox": False,
        "api_key": "verify-key" if legal else "",
        "api_secret": "verify-secret" if legal else "",
    }
    return settings.model_copy(
        update={
            "exchange": settings.exchange.model_copy(update=updates),
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


def _run_scenario(spec: dict[str, Any]) -> dict[str, Any]:
    import contextlib
    import io

    from trading_bot import app as app_module
    from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME
    from trading_bot.execution.live_gate import GateResult, LiveTradingGate

    calls: list[dict[str, Any]] = []
    state = {"scanner": 0, "clients": 0, "gate": 0}
    position_spec = spec.get("position")

    def position() -> Any:
        from types import SimpleNamespace

        values = {
            "position_id": "pos-1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 0.01,
            "position_mode": "ONE_WAY",
        }
        values.update(position_spec or {})
        return SimpleNamespace(**values)

    class Futures:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            state["clients"] += 1

        def place_order(self, **kwargs: Any) -> dict[str, Any]:
            guard = kwargs.pop("payload_guard", None)
            wire = {
                "symbol": kwargs.get("symbol"),
                "side": str(kwargs.get("side", "")).upper(),
                "qty": str(kwargs.get("qty")),
                "tradeSide": str(kwargs.get("trade_side", "")).upper(),
                "reduceOnly": bool(kwargs.get("reduce_only")),
                "positionId": kwargs.get("position_id"),
            }
            if spec.get("drop_reduce_only"):
                wire.pop("reduceOnly", None)
            if guard is not None:
                guard(wire)
            calls.append({"sink": "futures.place_order", "wire": wire})
            return {"orderId": "order-1"}

        def flash_close_position(
            self, position_id: str, *, payload_guard: Any = None
        ) -> dict[str, Any]:
            wire: dict[str, Any] = {"positionId": position_id}
            if spec.get("flash_extra"):
                wire.update({"side": "BUY", "qty": "0.01"})
            if payload_guard is not None:
                payload_guard(wire)
            calls.append({"sink": "futures.flash_close_position", "wire": wire})
            return {"positionId": position_id, "closed": True}

        def place_position_tpsl(self, **kwargs: Any) -> dict[str, Any]:
            calls.append({"sink": "futures.place_position_tpsl", "wire": {}})
            return {"positionId": kwargs.get("position_id")}

        def get_pending_positions(self, symbol: str | None = None) -> list[Any]:
            if spec.get("position_error"):
                from trading_bot.market_data.bitunix import BitunixAPIError

                raise BitunixAPIError("verify: position read failed")
            return [position()] if position_spec is not None else []

        def get_account(self, asset: str = "USDT") -> Any:
            from types import SimpleNamespace

            return SimpleNamespace(available=1_000.0, cross_unrealized_pnl=0.0)

        def get_symbol(self, symbol: str) -> Any:
            from types import SimpleNamespace

            return SimpleNamespace(
                symbol_status="OPEN",
                is_api_supported=True,
                base_precision=4,
                min_trade_volume=0.0001,
                max_market_order_volume=0.0,
                quote_precision=2,
            )

        def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
            from types import SimpleNamespace

            return [SimpleNamespace(close=100.0 + index) for index in range(6)]

    class Spot:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            state["clients"] += 1

        def place_spot_order(self, **kwargs: Any) -> dict[str, Any]:
            calls.append({"sink": "spot.place_spot_order", "wire": {}})
            return {"orderId": "spot-1", "placeStatus": "FILLED"}

        def fetch_last_price(self, symbol: str) -> float:
            return 100.0

        def fetch_recent_ohlcv(self, symbol: str, limit: int = 80) -> list[Any]:
            from types import SimpleNamespace

            return [SimpleNamespace(close=100.0 + index) for index in range(6)]

    class Connector:
        def load_markets(self) -> None:
            return None

        def fetch_balance(self) -> list[Any]:
            from trading_bot.market_data.types import Balance

            return [Balance(asset="USDT", free=1_000.0, used=0.0, total=1_000.0)]

        def fetch_market_rules(self, symbol: str) -> Any:
            from trading_bot.market_data.types import MarketRules

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
            from types import SimpleNamespace

            calls.append({"sink": "connector.create_order", "wire": {}})
            return SimpleNamespace(id="connector-1", client_order_id="cid", status="closed")

    settings = _settings(legal=not spec.get("broken", False))
    break_gate = spec.get("break_gate")
    if break_gate in set(GATE_IDS[:8]):
        settings = _break_settings(settings, break_gate)
    if spec.get("settings_error"):

        def load_settings(**kwargs: Any) -> Any:
            raise ValueError("verify: settings unavailable")

        app_module.load_settings = load_settings
    else:
        app_module.load_settings = lambda **kwargs: settings

    app_module.BitunixFuturesClient = Futures
    app_module.BitunixSpotClient = Spot

    def iteration(config_dir: str, env_file: str | None) -> Any:
        from types import SimpleNamespace

        state["scanner"] += 1
        snapshot = SimpleNamespace(
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
        counters = SimpleNamespace(
            pairs_processed=1, pairs_active=1, pairs_inactive=0, scanner_errors=0
        )
        return [snapshot], counters, Connector(), settings

    app_module._run_single_live_iteration = iteration
    app_module._run_single_iteration = lambda mode: (
        [],
        SimpleNamespace(
            pairs_processed=0, pairs_active=0, pairs_inactive=0, scanner_errors=0
        ),
    )
    app_module._create_futures_trade_case = lambda **kwargs: ("tc-1", "")
    app_module._mark_trade_case_order_open = lambda **kwargs: None
    app_module._mark_trade_case_order_rejected = lambda **kwargs: None
    app_module._reconcile_open_trade_cases_with_positions = lambda **kwargs: []
    app_module._mark_trade_case_closed_from_position = lambda **kwargs: None

    original_validate = LiveTradingGate.validate

    def counting_validate(self: Any) -> Any:
        state["gate"] += 1
        return original_validate(self)

    app_module.LiveTradingGate.validate = counting_validate  # type: ignore[method-assign]

    if spec.get("gate_crash"):

        def crash(self: Any) -> Any:
            state["gate"] += 1
            raise RuntimeError("verify: gate crashed")

        app_module.LiveTradingGate.validate = crash  # type: ignore[method-assign]
    elif spec.get("break_gate") in {"GATE-009", "GATE-010"}:
        gate_id = spec["break_gate"]

        def forced(self: Any) -> GateResult:
            return GateResult(
                gate_id=gate_id,
                name=f"Forced {gate_id}",
                passed=False,
                severity="critical",
                message="verify: forced rejection",
            )

        target = "_check_logging" if gate_id == "GATE-009" else "_check_risk_limits"
        setattr(LiveTradingGate, target, forced)

    run_dir = Path(spec["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    if spec.get("hot_stop"):
        (run_dir / HOT_STOP_FILE_NAME).write_text("verify stop\n", encoding="utf-8")

    argv = [*spec["argv"], "--run-dir", str(run_dir)]
    out, err = io.StringIO(), io.StringIO()
    exit_code = 1
    error = ""
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exit_code = int(app_module.main(argv))
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    except BaseException as exc:  # the runner reports, it never crashes the verifier
        error = f"{type(exc).__name__}: {exc}"

    return {
        "name": spec["name"],
        "exit_code": exit_code,
        "calls": calls,
        "call_count": len(calls),
        "scanner_builds": state["scanner"],
        "client_constructions": state["clients"],
        "gate_validations": state["gate"],
        "stderr_tail": err.getvalue()[-1200:],
        "error": error,
    }


# ---------------------------------------------------------------------------
# Export, scenarios, AST
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1800):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _export(rev: str, destination: Path) -> Path:
    archive = destination.parent / "verify-tree.tar"
    completed = _run(
        ["git", "archive", "--format=tar", "-o", str(archive), rev], cwd=REPO_ROOT
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git archive failed: {completed.stderr[-400:]}")
    tree = destination
    tree.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        try:
            tar.extractall(tree, filter="data")
        except TypeError:
            tar.extractall(tree)
    return tree


def _scenarios() -> list[dict[str, Any]]:
    run_argv = [
        "run",
        "--mode",
        "live",
        "--once",
        "--auto-trade",
        "--confirm-live",
        "--market-kind",
        "futures",
        "--trade-quote-usdt",
        "50",
        "--env-file",
        "",
    ]
    scenarios: list[dict[str, Any]] = [
        {
            "name": "run_no_confirm",
            "argv": [part for part in run_argv if part != "--confirm-live"],
            "position": None,
        },
        {"name": "run_legal", "argv": run_argv, "position": None},
        {"name": "run_settings_error", "argv": run_argv, "position": None, "settings_error": True},
        {"name": "run_gate_crash", "argv": run_argv, "position": None, "gate_crash": True},
        {"name": "run_hot_stop", "argv": run_argv, "position": None, "hot_stop": True},
        {
            "name": "paper_no_confirm",
            "argv": ["run", "--mode", "paper", "--once", "--auto-trade"],
            "position": None,
        },
    ]
    for gate_id in GATE_IDS:
        scenarios.append(
            {
                "name": f"run_break_{gate_id}",
                "argv": run_argv,
                "position": None,
                "break_gate": gate_id,
            }
        )

    def place(side: str, trade_side: str, *, reduce_only: bool, qty: float = 0.01) -> list[str]:
        argv = [
            "place-order",
            "--symbol",
            "BTCUSDT",
            "--side",
            side,
            "--order-type",
            "market",
            "--amount",
            str(qty),
            "--confirm-live",
            "--market-kind",
            "futures",
            "--trade-side",
            trade_side,
        ]
        if reduce_only:
            argv += ["--reduce-only", "--position-id", "pos-1"]
        return argv

    close_argv = place("sell", "CLOSE", reduce_only=True)
    scenarios += [
        {
            "name": "place_open_break",
            "argv": place("buy", "OPEN", reduce_only=False),
            "position": None,
            "break_gate": "GATE-003",
        },
        {
            "name": "place_open_legal",
            "argv": place("buy", "OPEN", reduce_only=False),
            "position": None,
        },
        {
            "name": "place_close_long_break",
            "argv": close_argv,
            "position": {"side": "BUY", "qty": 0.01},
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_short_break",
            "argv": place("buy", "CLOSE", reduce_only=True, qty=0.5),
            "position": {"side": "SELL", "qty": 0.5},
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_no_position_break",
            "argv": close_argv,
            "position": None,
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_excess_break",
            "argv": place("sell", "CLOSE", reduce_only=True, qty=0.5),
            "position": {"side": "BUY", "qty": 0.01},
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_hedge_break",
            "argv": close_argv,
            "position": {"side": "BUY", "qty": 0.01, "position_mode": "HEDGE"},
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_wrong_side_break",
            "argv": place("buy", "CLOSE", reduce_only=True),
            "position": {"side": "BUY", "qty": 1.0},
            "break_gate": "GATE-004",
        },
        {
            "name": "place_close_drop_reduce_break",
            "argv": close_argv,
            "position": {"side": "BUY", "qty": 0.01},
            "break_gate": "GATE-004",
            "drop_reduce_only": True,
        },
        {
            "name": "place_spot_sell_break",
            "argv": [
                "place-order",
                "--symbol",
                "BTC/USDT",
                "--side",
                "sell",
                "--order-type",
                "market",
                "--amount",
                "0.01",
                "--price",
                "100",
                "--confirm-live",
                "--market-kind",
                "spot",
            ],
            "position": None,
            "break_gate": "GATE-004",
        },
        {
            "name": "close_position_break",
            "argv": ["close-position", "--position-id", "pos-1"],
            "position": {"side": "BUY", "qty": 0.01},
            "break_gate": "GATE-004",
        },
        {
            "name": "close_position_flash_extra_break",
            "argv": ["close-position", "--position-id", "pos-1"],
            "position": {"side": "BUY", "qty": 0.01},
            "break_gate": "GATE-004",
            "flash_extra": True,
        },
        {
            "name": "close_position_hot_stop",
            "argv": ["close-position", "--position-id", "pos-1"],
            "position": {"side": "BUY", "qty": 0.01},
            "hot_stop": True,
        },
        {
            "name": "set_tpsl_break",
            "argv": [
                "set-tpsl",
                "--symbol",
                "BTCUSDT",
                "--position-id",
                "pos-1",
                "--qty",
                "0.01",
                "--tp-price",
                "110",
                "--sl-price",
                "90",
            ],
            "position": None,
            "break_gate": "GATE-004",
        },
        {
            "name": "set_tpsl_legal",
            "argv": [
                "set-tpsl",
                "--symbol",
                "BTCUSDT",
                "--position-id",
                "pos-1",
                "--qty",
                "0.01",
                "--tp-price",
                "110",
                "--sl-price",
                "90",
            ],
            "position": None,
        },
    ]
    return scenarios


def _run_scenarios(tree: Path, tmp: Path) -> dict[str, dict[str, Any]]:
    """Run each scenario in its own process.

    One process per scenario is not ceremony: ``process_kill_switch()`` is a
    module singleton and ``HotStopGate.__post_init__`` engages it when it adopts
    a marker. A shared process would let the ``run_hot_stop`` scenario stop every
    scenario after it, which is exactly the kind of cross-test leakage this
    verifier exists to avoid.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src"), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("TRADING_BOT_KILL_SWITCH", None)
    env.pop("PYTEST_ADDOPTS", None)
    (tree / "data" / "storage").mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for index, spec in enumerate(_scenarios()):
        spec["run_dir"] = str(tmp / "runs" / str(index))
        spec_path = tmp / f"scenario-{index}.json"
        out_path = tmp / f"scenario-{index}-result.json"
        spec_path.write_text(json.dumps({"scenarios": [spec]}, indent=2), encoding="utf-8")
        completed = _run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--scenario",
                str(spec_path),
                "--scenario-out",
                str(out_path),
            ],
            cwd=tree,
            env=env,
        )
        if not out_path.is_file():
            raise RuntimeError(
                f"scenario {spec['name']} failed: {completed.stderr[-800:]}"
            )
        row = json.loads(out_path.read_text(encoding="utf-8"))[0]
        results[row["name"]] = row
    return results


def _calls(node: ast.AST, attr: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    )


def _ancestors(root: ast.AST, target: ast.AST) -> list[ast.AST]:
    chain: list[ast.AST] = []

    def walk(node: ast.AST, stack: list[ast.AST]) -> None:
        if node is target:
            chain.extend(stack)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, [*stack, node])

    walk(root, [])
    return chain


def _ast_checks(tree: Path) -> list[Check]:
    checks: list[Check] = []
    app_path = tree / APP_REL
    auth_path = tree / AUTH_REL
    adapter_path = tree / ADAPTER_REL
    app_tree = ast.parse(app_path.read_text(encoding="utf-8"))
    # A pre-RFC export has no classifier and no guard; parsing an empty module
    # lets the structural checks report FAIL instead of crashing the verifier.
    empty = ast.Module(body=[], type_ignores=[])
    auth_tree = ast.parse(auth_path.read_text(encoding="utf-8")) if auth_path.is_file() else empty
    adapter_tree = (
        ast.parse(adapter_path.read_text(encoding="utf-8")) if adapter_path.is_file() else empty
    )

    sinks = {"create_order", "place_order", "place_spot_order", "flash_close_position", "place_position_tpsl"}
    sink_calls = [
        node
        for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in sinks
    ]
    escapes: list[str] = []
    for node in sink_calls:
        guarded = any(
            isinstance(ancestor, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "_live_order_boundary"
                for item in ancestor.items
            )
            for ancestor in _ancestors(app_tree, node)
        )
        if not guarded:
            escapes.append(f"line {node.lineno}: {ast.unparse(node)[:70]}")
    checks.append(
        Check(
            "V-02",
            "REQ-02",
            "every live sink is lexically inside _live_order_boundary",
            len(sink_calls) == 7 and not escapes,
            f"{len(sink_calls)} sinks, {len(escapes)} escapes",
            {"sinks": [ast.unparse(node)[:60] for node in sink_calls], "escapes": escapes},
        )
    )

    boundaries = [
        node
        for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_live_order_boundary"
    ]
    missing = [
        node.lineno
        for node in boundaries
        if not {"intent", "settings", "capabilities", "confirm_live"}
        <= {keyword.arg for keyword in node.keywords}
    ]
    legacy = [
        node.lineno
        for node in boundaries
        if any(keyword.arg == "opens_risk" for keyword in node.keywords)
    ]
    checks.append(
        Check(
            "V-03",
            "REQ-02",
            "all boundary call sites carry the typed context and none supplies opens_risk",
            len(boundaries) == 7 and not missing and not legacy,
            f"{len(boundaries)} boundaries; missing={missing}; legacy={legacy}",
        )
    )

    boundary_def = next(
        (
            node
            for node in ast.walk(app_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_live_order_boundary"
        ),
        None,
    )
    if boundary_def is None:
        checks.append(Check("V-04", "REQ-02", "boundary has no permissive defaults", False, "missing"))
    else:
        arguments = boundary_def.args
        defaults = [None] * (len(arguments.args) - len(arguments.defaults)) + list(arguments.defaults)
        required = {"settings", "intent", "position", "capabilities", "confirm_live"}
        permissive = [
            argument.arg
            for argument, default in zip(arguments.args, defaults, strict=True)
            if argument.arg in required and default is not None
        ]
        kw_defaults = {
            argument.arg: default
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        }
        permissive += [name for name in required if name in kw_defaults and kw_defaults[name] is not None]
        checks.append(
            Check(
                "V-04",
                "REQ-02",
                "the boundary has no defaults for settings, intent, position, capabilities or confirmation",
                not permissive,
                f"permissive defaults: {permissive}",
            )
        )

    confirm_guard = None
    run_def = next(
        (
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_cmd_run"
        ),
        None,
    )
    if run_def is not None:
        for node in ast.walk(run_def):
            if (
                isinstance(node, ast.If)
                and "confirm_live" in ast.unparse(node.test)
                and any(
                    isinstance(child, ast.Return)
                    and isinstance(child.value, ast.Constant)
                    and child.value.value == 2
                    for child in ast.walk(node)
                )
            ):
                confirm_guard = node.lineno
                break
    scanner_call = min(
        (
            node.lineno
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_run_single_live_iteration"
        ),
        default=10**9,
    )
    checks.append(
        Check(
            "V-05",
            "REQ-01",
            "run refuses an unconfirmed auto-trade before the scanner runs",
            confirm_guard is not None and confirm_guard < scanner_call,
            f"guard_line={confirm_guard}, first_scanner_line={scanner_call}",
        )
    )

    builder = next(
        (
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_build_parser"
        ),
        None,
    )
    run_parser_name = None
    if builder is not None:
        for node in ast.walk(builder):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "add_parser"
                and node.value.args
                and isinstance(node.value.args[0], ast.Constant)
                and node.value.args[0].value == "run"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        run_parser_name = target.id
    parser_has_flag = False
    if builder is not None and run_parser_name:
        parser_has_flag = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and getattr(node.func.value, "id", None) == run_parser_name
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--confirm-live"
            for node in ast.walk(builder)
        )
    checks.append(
        Check(
            "V-06",
            "REQ-01",
            "the run parser declares --confirm-live",
            parser_has_flag,
            "add_argument('--confirm-live') present" if parser_has_flag else "absent",
        )
    )

    guard_before_request: list[str] = []
    for function_name in ("place_order", "flash_close_position"):
        function = next(
            (
                node
                for node in ast.walk(adapter_tree)
                if isinstance(node, ast.FunctionDef) and node.name == function_name
            ),
            None,
        )
        if function is None:
            guard_before_request.append(f"{function_name}:missing")
            continue
        guard_lines = [
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "payload_guard"
        ]
        request_lines = [
            node.lineno
            for node in ast.walk(function)
            if _calls(node, "_request")
        ]
        if not guard_lines or not request_lines or min(guard_lines) > min(request_lines):
            guard_before_request.append(function_name)
    checks.append(
        Check(
            "V-07",
            "REQ-03 / T07",
            "the adapter invokes the payload guard before the HTTP request",
            not guard_before_request,
            f"unprotected: {guard_before_request}",
        )
    )

    classifier_rules = {
        "R-TPSL-NOT-MONOTONIC",
        "R-SPOT-SELL-NO-VENUE-PROOF",
        "R-REDUCE-ONLY",
        "R-FLASH-CLOSE",
        "R-CLOSE-QTY-EXCESS",
        "R-CLOSE-HEDGE-AMBIGUOUS",
        "R-CLOSE-STALE",
    }
    literals = {node.value for node in ast.walk(auth_tree) if isinstance(node, ast.Constant)}
    missing_rules = classifier_rules - literals
    checks.append(
        Check(
            "V-01",
            "REQ-03 / REQ-04",
            "the classifier names the reduction rules the contract requires",
            auth_path.is_file() and not missing_rules,
            f"missing rules: {sorted(missing_rules)}",
        )
    )

    stop_hash = hashlib.sha256((tree / STOP_REL).read_bytes()).hexdigest()
    checks.append(
        Check(
            "V-08",
            "REQ-05",
            "hot_stop.py is byte-identical to the G-1/G-2/G-3/P0 authority",
            stop_hash == HOT_STOP_SHA256,
            f"sha256={stop_hash}",
        )
    )

    gate_literals = {
        node.value
        for node in ast.walk(ast.parse((tree / GATE_REL).read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
    }
    checks.append(
        Check(
            "V-09",
            "REQ-02",
            "LiveTradingGate still declares GATE-001..GATE-010",
            all(gate_id in gate_literals for gate_id in GATE_IDS),
            "ten gate ids present" if all(gate_id in gate_literals for gate_id in GATE_IDS) else "missing",
        )
    )
    return checks


# ---------------------------------------------------------------------------
# Behaviour checks
# ---------------------------------------------------------------------------


def _expect(
    results: dict[str, dict[str, Any]],
    name: str,
    *,
    exit_code: int,
    calls: int,
) -> tuple[bool, str, dict[str, Any]]:
    row = results.get(name)
    if row is None:
        return False, f"{name}: scenario missing", {}
    ok = row["exit_code"] == exit_code and row["call_count"] == calls
    detail = (
        f"{name}: exit={row['exit_code']} (want {exit_code}), "
        f"calls={row['call_count']} (want {calls})"
    )
    return ok, detail, row


def _behavior_checks(results: dict[str, dict[str, Any]]) -> list[Check]:
    checks: list[Check] = []

    ok, detail, row = _expect(results, "run_no_confirm", exit_code=2, calls=0)
    checks.append(
        Check(
            "V-10",
            "REQ-01 / T01",
            "run --auto-trade without confirmation exits 2 with no scanner or client",
            ok and row.get("scanner_builds") == 0 and row.get("client_constructions") == 0,
            detail
            + f", scanner={row.get('scanner_builds')}, clients={row.get('client_constructions')}",
            row,
        )
    )

    gate_failures = []
    gate_evidence: dict[str, Any] = {}
    for gate_id in GATE_IDS:
        name = f"run_break_{gate_id}"
        ok, detail, row = _expect(results, name, exit_code=2, calls=0)
        gate_evidence[name] = {
            "passed": ok,
            "exit_code": row.get("exit_code"),
            "calls": row.get("call_count"),
            "gate_validations": row.get("gate_validations"),
            "mentions_gate": gate_id in str(row.get("stderr_tail", "")),
        }
        if not ok or gate_id not in str(row.get("stderr_tail", "")):
            gate_failures.append(detail)
    checks.append(
        Check(
            "V-11",
            "REQ-02 / T02",
            "each of the ten rejected checks stops the live loop with zero broker calls",
            not gate_failures,
            "; ".join(gate_failures) or "10/10 refused",
            gate_evidence,
        )
    )

    ok, detail, row = _expect(results, "run_legal", exit_code=0, calls=1)
    ok_open, detail_open, row_open = _expect(
        results, "place_open_legal", exit_code=0, calls=1
    )
    checks.append(
        Check(
            "V-12",
            "ACC-07",
            "the positive control still reaches the recording broker",
            ok and ok_open,
            f"{detail}; {detail_open}",
            {"run": row, "place_order": row_open},
        )
    )

    error_cases = ["run_settings_error", "run_gate_crash", "place_open_break"]
    error_failures = []
    error_evidence: dict[str, Any] = {}
    for name in error_cases:
        ok, detail, row = _expect(results, name, exit_code=2, calls=0)
        error_evidence[name] = {"passed": ok, "exit_code": row.get("exit_code")}
        if not ok:
            error_failures.append(detail)
    checks.append(
        Check(
            "V-13",
            "REQ-02 / T03",
            "unreadable settings, a crashing gate and a rejecting gate all fail closed",
            not error_failures,
            "; ".join(error_failures) or "3/3 refused",
            error_evidence,
        )
    )

    reduction_names = [
        "place_close_long_break",
        "place_close_short_break",
        "close_position_break",
        "close_position_hot_stop",
    ]
    reduction_failures = []
    reduction_evidence: dict[str, Any] = {}
    for name in reduction_names:
        ok, detail, row = _expect(results, name, exit_code=0, calls=1)
        reduction_evidence[name] = {
            "passed": ok,
            "calls": row.get("call_count"),
            "wire": row.get("calls", [{}])[0].get("wire") if row.get("calls") else None,
        }
        if not ok:
            reduction_failures.append(detail)
    checks.append(
        Check(
            "V-14",
            "REQ-03 / T05 / ACC-05",
            "a proven close reaches the broker while the gate rejects, and under the stop",
            not reduction_failures,
            "; ".join(reduction_failures) or "4/4 proven closes reached the broker",
            reduction_evidence,
        )
    )

    unknown_cases = [
        "place_close_no_position_break",
        "place_close_excess_break",
        "place_close_hedge_break",
        "place_close_wrong_side_break",
        "place_spot_sell_break",
        "set_tpsl_break",
    ]
    unknown_failures = []
    unknown_evidence: dict[str, Any] = {}
    for name in unknown_cases:
        ok, detail, row = _expect(results, name, exit_code=2, calls=0)
        unknown_evidence[name] = {"passed": ok, "reason_tail": row.get("stderr_tail", "")[-160:]}
        if not ok:
            unknown_failures.append(detail)
    checks.append(
        Check(
            "V-15",
            "REQ-03 / REQ-04 / T06 / T09",
            "unproven reductions (no position, excess, hedge, wrong side, spot sell, TP/SL) take the gate",
            not unknown_failures,
            "; ".join(unknown_failures) or "6/6 refused",
            unknown_evidence,
        )
    )

    mutation_cases = ["place_close_drop_reduce_break", "close_position_flash_extra_break"]
    mutation_failures = []
    mutation_evidence: dict[str, Any] = {}
    for name in mutation_cases:
        ok, detail, row = _expect(results, name, exit_code=2, calls=0)
        mutation_evidence[name] = {"passed": ok, "exit_code": row.get("exit_code")}
        if not ok:
            mutation_failures.append(detail)
    checks.append(
        Check(
            "V-16",
            "ACC-03 / T07",
            "a mutated final payload loses the exemption with zero broker calls",
            not mutation_failures,
            "; ".join(mutation_failures) or "drop reduceOnly and injected side both refused",
            mutation_evidence,
        )
    )

    ok_tpsl, detail_tpsl, row_tpsl = _expect(results, "set_tpsl_legal", exit_code=0, calls=1)
    checks.append(
        Check(
            "V-17",
            "REQ-04",
            "set-tpsl is not exempt by name but still works when every check passes",
            ok_tpsl,
            detail_tpsl,
            row_tpsl,
        )
    )

    ok_stop, detail_stop, row_stop = _expect(results, "run_hot_stop", exit_code=0, calls=0)
    checks.append(
        Check(
            "V-18",
            "REQ-05 / T10",
            "the hot stop keeps its G-3 skip/exit-0 behaviour with confirmation present",
            ok_stop,
            detail_stop,
            row_stop,
        )
    )

    ok_paper, detail_paper, row_paper = _expect(results, "paper_no_confirm", exit_code=0, calls=0)
    checks.append(
        Check(
            "V-19",
            "REQ-01 / T04",
            "paper is not blocked by the live confirmation flag",
            ok_paper,
            detail_paper,
            row_paper,
        )
    )
    return checks


# ---------------------------------------------------------------------------
# Suite + mutation
# ---------------------------------------------------------------------------


def _suite_check(tree: Path) -> Check:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tree / "src"), str(tree)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    completed = _run(
        [sys.executable, "-m", "pytest", *SUITE_TARGETS, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=tree,
        env=env,
    )
    tail = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    return Check(
        "V-20",
        "ACC-06 / T12",
        "the affected suite passes on the exported commit",
        completed.returncode == 0,
        tail or completed.stderr[-400:],
    )


def _mutation_check(rev: str, tmp: Path) -> Check:
    out = tmp / "mutations.json"
    script = REPO_ROOT / "scripts" / "audit" / "exec_sec_mutants.py"
    completed = _run(
        [sys.executable, str(script), "--rev", rev, "--json", str(out)],
        cwd=REPO_ROOT,
        timeout=1800,
    )
    if not out.is_file():
        return Check(
            "V-21",
            "T12 / ACC-06",
            "the mutation matrix kills every mutant",
            False,
            f"mutation run failed: {completed.stderr[-400:]}",
        )
    payload = json.loads(out.read_text(encoding="utf-8"))
    return Check(
        "V-21",
        "T12 / ACC-06",
        "the mutation matrix kills every mutant on the exported commit",
        payload.get("killed") == payload.get("mutants") and payload.get("mutants", 0) >= 14,
        f"{payload.get('killed')}/{payload.get('mutants')} killed",
        {"mutants": payload.get("mutants"), "killed": payload.get("killed")},
    )


def _hash_manifest(tree: Path, run_dir: Path | None) -> str:
    files = [
        APP_REL,
        AUTH_REL,
        ADAPTER_REL,
        "tests/unit/test_order_authorization.py",
        "tests/unit/test_exec_sec_process.py",
        "tests/unit/test_live_gate_enforcement.py",
        "tests/unit/test_live_hot_stop_coverage.py",
        "scripts/audit/exec_sec_mutants.py",
        "scripts/audit/verify_exec_sec.py",
        "docs/audit/RFC-TAP-EXEC-SEC-002.md",
    ]
    lines = []
    for rel in files:
        path = tree / rel
        if path.is_file():
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
    manifest = "\n".join(lines) + "\n"
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        # LF, not the platform default: `sha256sum -c` treats the CR as part of
        # the path on a Windows checkout, so a CRLF manifest verifies nothing.
        (run_dir / "ARTIFACTS.sha256").write_text(
            manifest, encoding="utf-8", newline="\n"
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Separate verifier for RFC-TAP-EXEC-SEC-002.")
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--json", default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--scenario", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--scenario-out", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.scenario:
        if not args.scenario_out:
            raise SystemExit("--scenario requires --scenario-out")
        return _scenario_mode(Path(args.scenario), Path(args.scenario_out))

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="verify-exec-sec-"))
    checks: list[Check] = []
    try:
        tree = _export(args.rev, tmp / "tree")
        results = _run_scenarios(tree, tmp)
        checks.extend(_ast_checks(tree))
        checks.extend(_behavior_checks(results))
        checks.append(_suite_check(tree))
        checks.append(_mutation_check(args.rev, tmp))
        manifest = _hash_manifest(tree, Path(args.run_dir) if args.run_dir else None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = [check for check in checks if check.passed]
    verdict = (
        "P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED"
        if len(passed) == len(checks)
        else "NOT_VERIFIED"
    )
    report = {
        "tool": "verify_exec_sec",
        "rfc": "RFC-TAP-EXEC-SEC-002",
        "run_id": Path(args.run_dir).name if args.run_dir else "",
        "rev": _run(["git", "rev-parse", args.rev], cwd=REPO_ROOT).stdout.strip(),
        "independence": {
            "kind": "PROCEDURALLY_SEPARATED",
            "author": "same author as the implementation",
            "separate_artefact": True,
            "imports_suite": False,
            "scenarios": "own table in scripts/audit/verify_exec_sec.py",
            "export": "git archive",
        },
        "verdict": verdict,
        "checks_total": len(checks),
        "checks_passed": len(passed),
        "checks": [check.__dict__ for check in checks],
        "artifacts_sha256": manifest,
        "seconds": round(time.time() - started, 1),
        "limitations": [
            "offline: all brokers are recorders; no exchange accepted a payload",
            "same author; procedural separation only",
            "does not cover G-4 (run --demo), DEF-P0-03 or GATE-009/010 configuration",
            "Bitunix hedge mode is refused rather than exercised",
        ],
    }
    for check in checks:
        print(
            f"{check.check_id:<5} {'PASS' if check.passed else 'FAIL':<4} "
            f"{check.criterion:<12} {check.description}"
        )
        if not check.passed:
            print(f"      {check.detail}")
    print(f"\n{len(passed)}/{len(checks)} checks passed — {verdict}")
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n", encoding="utf-8", newline="\n")
    return 0 if verdict.startswith("P0_ORDER_AUTHORIZATION_VERIFIED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
