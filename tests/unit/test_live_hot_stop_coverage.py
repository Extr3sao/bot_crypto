"""G-3 — the hot stop at the LIVE execution boundary.

The live entrypoints (`trading-bot run --auto-trade`, `place-order`,
`close-position`, `set-tpsl`) are a different program from
``AutonomousPaperRuntime``. Before G-3 they never constructed ``HotStopGate``, so
a `KILL_SWITCH` that stopped the autonomous runtime left them free to send.

These tests pin two things at once:

1. **coverage** — no live sink is called outside `_live_order_boundary`
   (structural, so a new call site cannot skip the gate);
2. **behaviour** — entry is refused while stopped, and reduction/protection
   still reaches the broker, because a stop that trapped the book would be a
   second hazard.

The process-boundary cases go through `scripts/audit/g3_live_probe.py`, which
runs `trading_bot.app.main` with recording clients: the parser, the mode guard,
the gate and the dispatch code are real, only the HTTP client is a double.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from trading_bot import app as app_module
from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME, HotStopGate
from trading_bot.config.runtime import TradingMode
from trading_bot.execution.order_authorization import (
    BITUNIX_FUTURES,
    OrderIntent,
    OrderPrimitive,
)
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.paper.kill_switch_v2 import KillSwitch

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = Path(app_module.__file__).resolve()
PROBE = REPO_ROOT / "scripts" / "audit" / "g3_live_probe.py"

#: Every attribute that leaves the process towards an exchange. If a new one is
#: added, this tuple has to grow, which is the point: the failure is "someone
#: forgot the gate", and silence is the wrong default.
LIVE_SINKS = (
    "create_order",
    "place_order",
    "place_spot_order",
    "flash_close_position",
    "place_position_tpsl",
)

ENTRY_POINTS = (
    "place-order-futures",
    "place-order-spot",
    "run-futures",
    "run-spot",
)

#: Proven reductions only. RFC-TAP-EXEC-SEC-002 removed `set-tpsl` and a spot
#: `sell`: neither is enforced by the venue, so a stop may (and does) refuse them.
REDUCTION_POINTS = (
    ("close-position", ()),
    ("place-order-futures", ("--trade-side", "CLOSE")),
)

UNKNOWN_POINTS = (
    ("set-tpsl", ()),
    ("place-order-spot", ("--side", "sell")),
)


def _live_settings() -> object:
    """Legal live settings for the in-process boundary test.

    P0 made ``settings`` a required argument of ``_live_order_boundary``; this
    helper keeps the G-3 in-flight test about the lock, not about config.
    """
    settings = build_demo_settings(mode="live")
    return settings.model_copy(
        update={
            "exchange": settings.exchange.model_copy(
                update={
                    "id": "bitunix",
                    "sandbox": False,
                    "api_key": "test-key",
                    "api_secret": "test-secret",
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


def _probe(entrypoint: str, run_dir: Path, *extra: str) -> dict[str, object]:
    """Run one real entrypoint in its own process against a recording broker."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "probe.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROBE),
            "--entrypoint",
            entrypoint,
            "--run-dir",
            str(run_dir),
            *extra,
            "--json",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.is_file(), completed.stderr[-2000:]
    return json.loads(out.read_text(encoding="utf-8"))


def _engage_with_the_operator_cli(run_dir: Path, reason: str = "operator stop") -> None:
    """Write the marker the way an operator does — a **different** process."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_bot.app",
            "kill-switch",
            "--run-dir",
            str(run_dir),
            "--engage",
            "--reason",
            reason,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert (run_dir / HOT_STOP_FILE_NAME).is_file()


# ---------------------------------------------------------------------------
# ACC-G3-01 / 02 — positive control and the blocked entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entrypoint", ENTRY_POINTS)
def test_positive_control_reaches_the_broker(entrypoint: str, tmp_path: Path) -> None:
    """Without a marker the path is live: exactly one call leaves the process."""
    payload = _probe(entrypoint, tmp_path / "run")
    assert payload["broker_calls"] == 1, payload
    assert payload["exit_code"] == 0, payload
    assert payload["marker_present"] is False


@pytest.mark.parametrize("entrypoint", ENTRY_POINTS)
def test_entry_is_refused_with_a_marker(entrypoint: str, tmp_path: Path) -> None:
    """The marker sits in the directory the command was told to watch."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")

    payload = _probe(entrypoint, run_dir)

    assert payload["broker_calls"] == 0, payload
    if entrypoint.startswith("place-order"):
        assert payload["exit_code"] == 2, payload
    # The loop reports the skip instead of exiting: it must keep running so the
    # operator can still flatten and read evidence.
    assert payload["exit_code"] == 0 or entrypoint.startswith("place-order")


# ---------------------------------------------------------------------------
# ACC-G3-03 / 04 — another process writes; a restart inherits
# ---------------------------------------------------------------------------


def test_operator_cli_marker_blocks_the_next_process(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _engage_with_the_operator_cli(run_dir)

    payload = _probe("place-order-futures", run_dir)

    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload
    assert payload["marker_reason"] == "operator stop"


def test_restart_over_the_same_run_dir_stays_blocked(tmp_path: Path) -> None:
    """Two successive processes; the second one boots engaged and stays quiet."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _engage_with_the_operator_cli(run_dir)

    first = _probe("run-futures", run_dir)
    second = _probe("run-futures", run_dir)

    assert first["broker_calls"] == 0, first
    assert second["broker_calls"] == 0, second

    events = [
        json.loads(line)
        for line in (run_dir / "kill_switch_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "restored" for event in events), events


# ---------------------------------------------------------------------------
# ACC-G3-05 / 06 — fail closed on a bad marker and on the boot-time switch
# ---------------------------------------------------------------------------


def test_unreadable_marker_blocks_entry(tmp_path: Path) -> None:
    """A directory where the marker should be is *presence*, not absence."""
    run_dir = tmp_path / "run"
    (run_dir / HOT_STOP_FILE_NAME).mkdir(parents=True)

    payload = _probe("place-order-futures", run_dir)

    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload


def test_env_kill_switch_blocks_entry_without_a_marker(tmp_path: Path) -> None:
    """A live path has no DecisionEngine rule 0, so the boot switch is checked here."""
    run_dir = tmp_path / "run"

    payload = _probe("place-order-futures", run_dir, "--env-kill-switch", "halted")

    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload
    # Not persisted: KILL_SWITCH_ENV keeps the boot-time semantics G-1 fixed.
    assert payload["marker_present"] is False


# ---------------------------------------------------------------------------
# ACC-G3-07 — reduction is not trapped by the stop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("entrypoint", "extra"), REDUCTION_POINTS)
def test_reduction_and_protection_still_reach_the_broker(
    entrypoint: str, extra: tuple[str, ...], tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")

    payload = _probe(entrypoint, run_dir, *extra)

    assert payload["broker_calls"] == 1, payload
    assert payload["exit_code"] == 0, payload


@pytest.mark.parametrize(("entrypoint", "extra"), UNKNOWN_POINTS)
def test_unproven_protection_is_refused_by_the_stop(
    entrypoint: str, extra: tuple[str, ...], tmp_path: Path
) -> None:
    """A spot sell and a TP/SL change are UNKNOWN: the stop applies to both."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")

    payload = _probe(entrypoint, run_dir, *extra)

    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload


# ---------------------------------------------------------------------------
# ACC-G3-08 — the structure: no sink outside the boundary
# ---------------------------------------------------------------------------


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


def _is_boundary(context_expr: ast.expr) -> bool:
    return (
        isinstance(context_expr, ast.Call)
        and isinstance(context_expr.func, ast.Name)
        and context_expr.func.id == "_live_order_boundary"
    )


def _sink_calls(tree: ast.AST) -> list[ast.Call]:
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LIVE_SINKS
        ):
            found.append(node)
    return found


def test_every_live_sink_is_inside_the_boundary() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    sinks = _sink_calls(tree)
    assert len(sinks) == 7, f"expected the 7 known live sinks, found {len(sinks)}"

    escapes: list[str] = []
    for node in sinks:
        guarded = False
        for ancestor in _ancestors(tree, node):
            if not isinstance(ancestor, ast.With):
                continue
            if any(_is_boundary(item.context_expr) for item in ancestor.items):
                guarded = True
                break
        if not guarded:
            escapes.append(f"line {node.lineno}: {ast.unparse(node)[:80]}")
    assert not escapes, "live sink reached without _live_order_boundary:\n" + "\n".join(escapes)


def test_each_boundary_carries_the_typed_order_and_context() -> None:
    """The category is derived from the intent, not declared by the caller."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    boundaries = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_live_order_boundary"
    ]
    # One per live dispatch site: 7 sinks, 7 boundaries. A count that drops is a
    # sink that lost its gate, not a refactor.
    assert len(boundaries) >= 7, f"expected >= 7 boundaries, found {len(boundaries)}"
    missing = [
        node.lineno
        for node in boundaries
        if not {"intent", "settings", "confirm_live"} <= {keyword.arg for keyword in node.keywords}
    ]
    assert not missing, f"_live_order_boundary without a typed context at lines {missing}"
    legacy = [
        node.lineno
        for node in boundaries
        if any(keyword.arg == "opens_risk" for keyword in node.keywords)
    ]
    assert not legacy, f"caller-supplied exposure booleans survived at lines {legacy}"


# ---------------------------------------------------------------------------
# ACC-G3-09 — the in-flight barrier is the same one G-2 argued for
# ---------------------------------------------------------------------------


def test_engage_waits_for_the_inflight_dispatch(tmp_path: Path) -> None:
    switch = KillSwitch()
    gate = HotStopGate(kill_switch=switch, run_dir=tmp_path)
    settings = _live_settings()
    entered = threading.Event()
    release = threading.Event()
    sent: list[str] = []

    opening = OrderIntent(
        entrypoint="run",
        primitive=OrderPrimitive.FUTURES_PLACE_ORDER,
        symbol="BTC/USDT",
        side="BUY",
        qty=10.0,
        trade_side="OPEN",
    )

    def dispatch() -> None:
        with app_module._live_order_boundary(
            gate,
            intent=opening,
            position=None,
            capabilities=BITUNIX_FUTURES,
            settings=settings,
            confirm_live=True,
        ) as allowed:
            assert allowed
            entered.set()
            assert release.wait(timeout=10)
            sent.append("order")

    worker = threading.Thread(target=dispatch, daemon=True)
    worker.start()
    assert entered.wait(timeout=10)

    acks: list[object] = []
    engager = threading.Thread(
        target=lambda: acks.append(gate.engage("operator stop")), daemon=True
    )
    engager.start()
    time.sleep(0.2)
    assert not acks, "engage ACKed while a dispatch was in flight"

    release.set()
    worker.join(timeout=10)
    engager.join(timeout=10)

    assert len(acks) == 1
    assert getattr(acks[0], "persisted", False) is True
    assert sent == ["order"]

    with app_module._live_order_boundary(
        gate,
        intent=opening,
        position=None,
        capabilities=BITUNIX_FUTURES,
        settings=settings,
        confirm_live=True,
    ) as allowed:
        assert not allowed, "a dispatch began after the stop was in force"


# ---------------------------------------------------------------------------
# ACC-G3-10 / 14 — contract preserved, and the target is the runtime module
# ---------------------------------------------------------------------------


def test_disarm_is_still_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = app_module.main(["kill-switch", "--run-dir", str(tmp_path), "--disarm"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert not (tmp_path / HOT_STOP_FILE_NAME).exists()


def test_the_module_under_test_is_the_runtime_module() -> None:
    """ACC-G3-14: TEST_TARGET == RUNTIME_TARGET, across the process boundary.

    The probe runs in its own interpreter; this asserts it loaded the same
    ``trading_bot.app`` file the tests did, so a result cannot come from a
    second checkout or a stale install.
    """
    assert PROBE.is_file()
    payload = _probe("place-order-futures", Path(_tmp_dir()))
    assert payload["argv"][0] == "place-order"
    assert Path(str(payload["app_file"])) == APP_PATH


def _tmp_dir() -> str:
    """A throwaway directory for the identity check, outside pytest's fixtures."""
    import tempfile

    return tempfile.mkdtemp(prefix="g3-identity-")
