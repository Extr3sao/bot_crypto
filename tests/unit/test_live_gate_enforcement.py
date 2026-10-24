"""P0 — the live gate is enforced on every path that opens risk.

DEF-G3-03 was not a missing check: ``execution/live_gate.py`` existed, passed
its own tests, and documented ten checks. The defect was that no live entrypoint
constructed it, so a configuration the gate would have rejected still reached
the broker. G-3 measured the same shape for the hot stop.

These tests pin the three layers that close it:

1. **verdict** — the ten checks run, and any rejecting check (or an exception,
   or a short report) is a refusal;
2. **boundary** — ``_live_order_boundary`` consults the gate inside the same
   lock the hot stop uses, for entry only (reduction stays possible);
3. **program** — ``scripts/audit/p0_live_gate_probe.py`` drives the real
   ``trading_bot.app.main`` in a subprocess with recording clients: parser, mode
   guard, hot stop, gate and dispatch are the real ones.

The probe cases are the ones that can fail for the right reason: a unit test of
``_evaluate_live_gate`` cannot prove the CLI calls it.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trading_bot import app as app_module
from trading_bot.autonomous.hot_stop import HOT_STOP_FILE_NAME, HotStopGate
from trading_bot.config.runtime import TradingMode
from trading_bot.domain.enums.kill_switch import KillSwitchAction
from trading_bot.execution.live_gate import GateReport, GateResult, LiveTradingGate
from trading_bot.market_data.fake import build_demo_settings
from trading_bot.paper.kill_switch_v2 import KillSwitch

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = Path(app_module.__file__).resolve()
PROBE = REPO_ROOT / "scripts" / "audit" / "p0_live_gate_probe.py"

GATE_IDS: tuple[str, ...] = tuple(f"GATE-{index:03d}" for index in range(1, 11))

#: Entrypoints that can open or increase exposure.
ENTRY_POINTS: tuple[str, ...] = (
    "place-order-futures",
    "place-order-spot",
    "run-futures",
    "run-spot",
)

#: Legitimate reduction/protection stays available even when the gate rejects.
REDUCTION_POINTS: tuple[str, ...] = (
    "close-position",
    "set-tpsl",
    "place-order-futures-close",
    "place-order-spot-sell",
)


# ---------------------------------------------------------------------------
# Fixtures shared with the gate's own contract
# ---------------------------------------------------------------------------


def _legal_settings() -> Any:
    """A live configuration the gate must pass: sandbox off, id and keys set."""
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


def _broken_settings(gate_id: str) -> Any:
    settings = _legal_settings()
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
            update={"exchange": settings.exchange.model_copy(update={"api_key": "", "api_secret": ""})}
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
    raise AssertionError(f"{gate_id} cannot be broken through configuration")


def _probe(entrypoint: str, run_dir: Path, *extra: str) -> dict[str, Any]:
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
    payload: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    assert Path(str(payload["app_file"])) == APP_PATH, payload
    return payload


# ---------------------------------------------------------------------------
# 1. Verdict: ten checks, and every rejection is a refusal
# ---------------------------------------------------------------------------


def test_the_gate_still_runs_its_ten_checks() -> None:
    report = LiveTradingGate(_legal_settings(), credentials=("k", "s")).validate()
    assert report.total_gates == 10
    assert [result.gate_id for result in report.results] == list(GATE_IDS)
    assert report.failed_gates == 0, [(r.gate_id, r.message) for r in report.results if not r.passed]


def test_a_legal_live_configuration_is_allowed() -> None:
    assert app_module._evaluate_live_gate(_legal_settings()).allowed is True


@pytest.mark.parametrize("gate_id", GATE_IDS[:8])
def test_each_configuration_rejection_blocks_entry(gate_id: str) -> None:
    verdict = app_module._evaluate_live_gate(_broken_settings(gate_id))
    assert verdict.allowed is False, gate_id
    assert gate_id in verdict.failed_gate_ids, verdict
    assert verdict.reason.startswith("live_gate_blocked:"), verdict


@pytest.mark.parametrize(
    ("gate_id", "method"),
    [("GATE-009", "_check_logging"), ("GATE-010", "_check_risk_limits")],
)
def test_a_forced_failure_of_the_informational_checks_also_blocks(
    gate_id: str, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GATE-009/010 cannot fail through config; a rejection must still block."""

    def forced(self: Any) -> GateResult:
        return GateResult(
            gate_id=gate_id,
            name=f"Forced {gate_id}",
            passed=False,
            severity="critical",
            message="test: forced rejection",
        )

    monkeypatch.setattr(LiveTradingGate, method, forced)
    verdict = app_module._evaluate_live_gate(_legal_settings())
    assert verdict.allowed is False
    assert gate_id in verdict.failed_gate_ids


def test_credentials_come_from_the_runtime_not_the_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI's env file is read by pydantic and never exported."""
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_API_SECRET", raising=False)
    assert app_module._evaluate_live_gate(_legal_settings()).allowed is True


def test_a_short_report_is_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [
        GateResult(
            gate_id=gate_id,
            name="passing",
            passed=True,
            severity="critical",
            message="ok",
        )
        for gate_id in GATE_IDS[:9]
    ]
    short = GateReport(
        all_passed=True,
        total_gates=9,
        passed_gates=9,
        failed_gates=0,
        critical_failures=[],
        results=results,
    )
    monkeypatch.setattr(LiveTradingGate, "validate", lambda self: short)
    verdict = app_module._evaluate_live_gate(_legal_settings())
    assert verdict.allowed is False
    assert verdict.reason == "live_gate_incomplete:9/10"


def test_a_gate_that_raises_is_not_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self: Any) -> GateReport:
        raise RuntimeError("test: gate crashed")

    monkeypatch.setattr(LiveTradingGate, "validate", explode)
    verdict = app_module._evaluate_live_gate(_legal_settings())
    assert verdict.allowed is False
    assert verdict.reason == "live_gate_error:RuntimeError"


# ---------------------------------------------------------------------------
# 2. Boundary: the gate is inside the entry boundary, reduction stays free
# ---------------------------------------------------------------------------


def _boundary(gate: HotStopGate, settings: Any, *, opens_risk: bool) -> bool:
    with app_module._live_order_boundary(gate, opens_risk=opens_risk, settings=settings) as allowed:
        return allowed


def test_the_boundary_refuses_entry_when_the_gate_rejects(tmp_path: Path) -> None:
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    assert _boundary(gate, _broken_settings("GATE-004"), opens_risk=True) is False


def test_the_boundary_does_not_consult_the_gate_for_reduction(tmp_path: Path) -> None:
    gate = HotStopGate(kill_switch=KillSwitch(), run_dir=tmp_path)
    assert _boundary(gate, _broken_settings("GATE-004"), opens_risk=False) is True


def test_the_stop_has_priority_over_the_gate(tmp_path: Path) -> None:
    switch = KillSwitch()
    gate = HotStopGate(kill_switch=switch, run_dir=tmp_path)
    switch.activate(KillSwitchAction.USER)
    settings = _broken_settings("GATE-004")

    assert _boundary(gate, settings, opens_risk=True) is False
    reason = app_module._live_refusal_reason(gate, settings)
    assert reason == "process_kill_switch_active", reason


def test_settings_is_a_required_boundary_argument() -> None:
    import inspect

    signature = inspect.signature(app_module._live_order_boundary.__wrapped__)
    parameter = signature.parameters["settings"]
    assert parameter.default is inspect.Parameter.empty, "a boundary without settings is a bypass"


def test_every_boundary_call_site_states_risk_and_settings() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_live_order_boundary"
    ]
    assert len(calls) == 7, f"expected the 7 known boundary call sites, found {len(calls)}"
    missing = [
        call.lineno
        for call in calls
        if not {"opens_risk", "settings"} <= {keyword.arg for keyword in call.keywords}
    ]
    assert not missing, f"_live_order_boundary without opens_risk/settings at lines {missing}"


# ---------------------------------------------------------------------------
# 3. Program: the real CLI refuses before the broker call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate_id", GATE_IDS)
def test_a_rejecting_gate_sends_nothing_and_exits_2(gate_id: str, tmp_path: Path) -> None:
    payload = _probe("place-order-futures", tmp_path / "run", "--break", gate_id)
    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload
    assert payload["gate_validations"] >= 1, payload
    assert gate_id in payload["stderr_tail"], payload["stderr_tail"]


@pytest.mark.parametrize("entrypoint", ENTRY_POINTS)
def test_every_entrypoint_is_covered(entrypoint: str, tmp_path: Path) -> None:
    payload = _probe(entrypoint, tmp_path / "run", "--break", "GATE-003")
    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload


@pytest.mark.parametrize("entrypoint", ENTRY_POINTS)
def test_positive_control_still_reaches_the_broker(entrypoint: str, tmp_path: Path) -> None:
    payload = _probe(entrypoint, tmp_path / "run")
    assert payload["broker_calls"] == 1, payload
    assert payload["exit_code"] == 0, payload


@pytest.mark.parametrize("entrypoint", REDUCTION_POINTS)
def test_reduction_is_not_trapped_by_a_rejecting_gate(
    entrypoint: str, tmp_path: Path
) -> None:
    payload = _probe(entrypoint, tmp_path / "run", "--break", "GATE-004")
    assert payload["broker_calls"] == 1, payload
    assert payload["exit_code"] == 0, payload


@pytest.mark.parametrize("entrypoint", ["place-order-futures", "run-futures"])
def test_unreadable_settings_refuse(entrypoint: str, tmp_path: Path) -> None:
    payload = _probe(entrypoint, tmp_path / "run", "--settings-error")
    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload


@pytest.mark.parametrize("entrypoint", ["place-order-spot", "run-spot"])
def test_a_crashing_gate_refuses(entrypoint: str, tmp_path: Path) -> None:
    payload = _probe(entrypoint, tmp_path / "run", "--gate-crash")
    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload


def test_the_hot_stop_still_wins_over_a_rejecting_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / HOT_STOP_FILE_NAME).write_text("operator stop\n", encoding="utf-8")

    payload = _probe("place-order-futures", run_dir, "--break", "GATE-004")

    assert payload["broker_calls"] == 0, payload
    assert payload["exit_code"] == 2, payload
    assert "kill_switch_engaged_hot" in payload["stderr_tail"], payload["stderr_tail"]
    assert "live_gate_blocked" not in payload["stderr_tail"], payload["stderr_tail"]
