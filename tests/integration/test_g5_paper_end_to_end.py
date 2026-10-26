"""G-5 — the real paper runtime must complete a measured end-to-end cycle.

The defect class this file closes is "exit 0 without a paper cycle". Each test
below drives the repository's real ``PaperCycleEngine`` through
``PaperOrchestrator`` / ``PaperSessionRunner`` with the same composition the
paper launcher uses (``scripts/start_paper_trading.py::build_cycle_engine``),
the real ``RiskManager``, the real ``HotStopGate`` and the real ``PaperBroker``.

Only two things are controlled:

- market data, from a deterministic synthetic fixture;
- the admission ledger, from ``docs/audit/fixtures/g5_paper_ledger.json``,
  explicitly labelled ``CONTROLLED_TEST_FIXTURE`` and not a production
  admission.

The clock is pinned to a Wednesday because the committed risk policy forbids
weekend trading. That is a test control, recorded in the evidence, not a
policy change.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.audit.g5_paper_e2e import DEFAULT_LEDGER, run_all

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("g5-paper-e2e")
    return asyncio.run(run_all(out, DEFAULT_LEDGER))


def test_the_run_is_paper_only(evidence: dict[str, Any]) -> None:
    assert evidence["execution_class"] == "PAPER_ONLY_SYNTHETIC_FIXTURE"
    assert evidence["live"] is False
    assert evidence["credentials_used"] is False
    assert evidence["order_sent"] is False
    assert "CONTROLLED_TEST_FIXTURE" in evidence["ledger_claim"]


def test_trade_opens_one_position_and_persists_it(evidence: dict[str, Any]) -> None:
    trade = evidence["scenarios"]["trade"]
    cycle = trade["cycle"]
    assert cycle["orders_created"] == 1
    assert cycle["risk_accepted"] == 1
    assert trade["broker_calls"]["execute_signal"] == 1
    assert len(trade["positions"]) == 1
    assert trade["positions"][0]["symbol"] == "BTC/USDT"
    assert trade["positions"][0]["side"] == "buy"
    assert trade["state_bytes"] > 0
    assert trade["state_after"]["open_positions"] == 1
    assert trade["state_after"]["sent_intents"] == 1
    assert all(trade["accounting"]["identities"].values())


def test_restart_recovers_the_book_and_reconciles_the_exit(
    evidence: dict[str, Any],
) -> None:
    restart = evidence["scenarios"]["restart"]
    before = restart["reconciliation_before"]
    assert before["status"] == "RECOVERED"
    assert before["restored_open_positions"] == 1
    assert before["restored_intents"] == 1
    assert len(restart["positions_after_reconcile"]) == 1

    cycle = restart["cycle"]
    assert cycle["orders_created"] == 0, "a restart re-opened a position"
    assert cycle["same_side_skips"] == 1
    assert restart["broker_calls"]["execute_signal"] == 0

    closed = restart["closed_trades"]
    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "take_profit"
    assert closed[0]["position_id"] == restart["positions_after_reconcile"][0]["position_id"]
    assert restart["realized_pnl_matches_equity"] is True
    assert restart["state_after"]["open_positions"] == 0
    assert restart["state_after"]["closed_trades"] == 1
    assert all(restart["accounting"]["identities"].values())


def test_flat_market_is_no_trade_with_zero_orders(evidence: dict[str, Any]) -> None:
    no_trade = evidence["scenarios"]["no_trade"]
    assert no_trade["cycle"]["orders_created"] == 0
    assert no_trade["cycle"]["signals_generated"] == 0
    assert no_trade["broker_calls"]["execute_signal"] == 0
    assert any(r["reason"] == "no_alpha_in_direction:ANY" for r in no_trade["cycle"]["rejections"])


def test_stale_data_is_refused_before_the_strategy(evidence: dict[str, Any]) -> None:
    stale = evidence["scenarios"]["stale"]
    assert stale["cycle"]["orders_created"] == 0
    assert stale["cycle"]["router_no_trade"] == 1
    assert stale["broker_calls"]["execute_signal"] == 0
    assert any(r["reason"] == "NO_TRADE:stale_context" for r in stale["cycle"]["rejections"])


def test_operator_stop_blocks_before_the_broker(evidence: dict[str, Any]) -> None:
    stopped = evidence["scenarios"]["kill_switch"]
    assert stopped["cycle"]["orders_created"] == 0
    assert stopped["cycle"]["hot_stop_blocked"] == 1
    assert stopped["cycle"]["risk_accepted"] == 1, (
        "the stop must be evaluated at the dispatch boundary, after risk"
    )
    assert stopped["broker_calls"] == {"execute_signal": 0, "close_position": 0}
    assert any(
        r["stage"] == "hot_stop" and "kill_switch_active" in r["reason"]
        for r in stopped["cycle"]["rejections"]
    )


def test_provider_exception_is_contained_and_creates_no_order(
    evidence: dict[str, Any],
) -> None:
    failed = evidence["scenarios"]["provider_exception"]
    assert failed["cycle"]["orders_created"] == 0
    assert failed["broker_calls"]["execute_signal"] == 0
    assert failed["status"]["last_session_metrics"]["scanner_errors"] == 1
    assert failed["status"]["last_session_metrics"]["total_snapshots"] == 0


def test_the_cli_calls_its_paper_scan_synthetic() -> None:
    """`run --mode paper` is a synthetic scan; it must say so, not imply a cycle."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_bot.app",
            "run",
            "--mode",
            "paper",
            "--auto-trade",
            "--once",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = completed.stdout.replace("\r\n", "\n")
    assert completed.returncode == 0, completed.stderr[-1000:]
    assert "paper_cycle=NOT_RUN" in output
    assert "broker=NOT_CONSTRUCTED" in output
    assert "--auto-trade no se aplica" in output
