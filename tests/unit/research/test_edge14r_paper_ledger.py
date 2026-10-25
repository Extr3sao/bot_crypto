"""The published paper ledger has to add up on its own terms.

`PAPER_EXECUTION_EVIDENCE.json` is the arm the recovery package publishes, and its recorder has
already been wrong once: it identified an opening by ``(symbol, position.opened_at)`` — a
wall-clock instant that two openings on one symbol can share in a replay this fast — and it read
only the closes its own settlement call returned, so the closes the engine performs inside its
cycle were invisible.  The defect was visible only to a reader who subtracted the numbers
(299 openings against 301 closes), which is exactly the kind of reading a test should do for
everyone.  These checks are that subtraction, committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = (
    REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R" / "PAPER_EXECUTION_EVIDENCE.json"
)

CLOSED_BY = {"engine_cycle", "settlement_check", "final_mark"}


@pytest.fixture(scope="module")
def sandbox() -> dict[str, Any]:
    if not EVIDENCE.is_file():
        pytest.skip("the 014R paper execution evidence has not been produced in this checkout")
    payload: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return payload["arms"]["SANDBOX_ADMISSION"]  # type: ignore[no-any-return]


def opening(row: dict[str, Any]) -> tuple[str, float, float]:
    """The identity the arm uses, so a collision cannot hide behind a rounded figure."""
    return (str(row["symbol"]), float(row["opened_at"]), float(row["entry_price"]))


def test_no_opening_is_recorded_twice(sandbox: dict[str, Any]) -> None:
    keys = [opening(fill) for fill in sandbox["fills"]]
    assert len(keys) == len(set(keys)), "an opening was recorded more than once"
    assert sandbox["fills_opened"] == len(keys), "the count does not match the rows it counts"


def test_every_close_names_an_opening_the_arm_recorded(sandbox: dict[str, Any]) -> None:
    recorded = {opening(fill) for fill in sandbox["fills"]}
    missing = [row for row in sandbox["exits"] if opening(row) not in recorded]
    assert not missing, f"{len(missing)} close(s) name an opening the ledger does not carry"


def test_the_ledger_balances_against_the_positions_it_left_open(sandbox: dict[str, Any]) -> None:
    identity = sandbox["ledger_identity"]
    assert identity["opened"] == sandbox["fills_opened"]
    assert identity["closed"] == sandbox["fills_closed"] == len(sandbox["exits"])
    assert identity["opened"] - identity["closed"] == identity["unpaired_opens"]
    assert identity["unpaired_opens"] == identity["open_positions_at_end"]


def test_the_arm_explains_the_equity_it_moved(sandbox: dict[str, Any]) -> None:
    identity = sandbox["ledger_identity"]
    moved = float(sandbox["broker_final_equity"]) - float(sandbox["broker_initial_equity"])
    assert identity["realised_equals_equity_change"] is True
    assert abs(float(identity["realised_pnl"]) - moved) < 1e-6, (
        "the realised PnL this arm publishes is not the equity the broker moved"
    )


def test_every_close_says_what_closed_it(sandbox: dict[str, Any]) -> None:
    origins = [row.get("closed_by") for row in sandbox["exits"]]
    assert set(origins) <= CLOSED_BY, f"unknown closing stage(s): {set(origins) - CLOSED_BY}"
    assert all(isinstance(row.get("opened_at"), (int, float)) for row in sandbox["exits"])
