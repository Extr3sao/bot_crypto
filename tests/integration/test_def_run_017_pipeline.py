"""DEF-RUN-017 — el auditor contra el runtime de verdad, no contra un mock.

`TEST_TARGET == RUNTIME_TARGET`: se ejecuta ``VisionLane`` con el broker y el gestor de
riesgo reales, se escriben dos ledgers (SUPERSEDE y DEFER) sobre las mismas barras y se
reconstruye el dinero desde sus bytes. Lo que se exige:

* las dos reconstrucciones pasan todas sus comprobaciones,
* el neto reconstruido coincide con el que el run declaró en ``RUN_END``,
* el delta atribuido cierra sin residual,
* ninguna opinión queda sin terminal.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.economic_audit import Q_USDT, attribute, reconstruct
from trading_bot.vision.lane import (
    OPINION_LIFECYCLE_DEFER,
    OPINION_LIFECYCLE_SUPERSEDE,
    VisionLane,
)
from trading_bot.vision.provider import ReplayProvider
from trading_bot.vision.quotes import MINUTE_MS
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[2]
SYMBOL = "BTC/USDT"
START_MS = 1_792_500_000_000

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":0.4,"take_profit_pct":0.75,'
    '"invalidation":null,"rationale":"Continuation."}'
)


def bars(count: int = 60) -> list[Bar]:
    out: list[Bar] = []
    for index in range(count):
        opened = 100.0 + index * 0.06
        out.append(
            Bar(
                ts_ms=START_MS + index * MINUTE_MS,
                open=opened,
                high=opened * 1.003,
                low=opened * 0.997,
                close=opened * 1.0005,
                volume=10.0,
            )
        )
    return out


def run_lane(tmp_path: Path, lifecycle: str) -> tuple[dict, Path]:
    base = load_vision_config(env={})
    config = base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1m",
            window_bars=10,
            decision_every_bars=1,
            max_calls_per_run=200,
            max_estimated_spend_usd=10.0,
            data_delay_ms=3_620,
            max_opinion_age_ms=0,
        ),
    )
    ledger = tmp_path / f"{lifecycle.lower()}.jsonl"
    lane = VisionLane(
        series={SYMBOL: bars()},
        provider=ReplayProvider([LONG] * 400),
        config=config,
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        book_id=f"def-run-017-{lifecycle.lower()}",
        opinion_lifecycle=lifecycle,
    )
    summary = lane.run()
    return summary, ledger


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict:
    """Un carril por ciclo de vida, ejecutado una vez para toda la suite."""
    directory = tmp_path_factory.mktemp("def017")
    base_summary, base_ledger = run_lane(directory, OPINION_LIFECYCLE_SUPERSEDE)
    cand_summary, cand_ledger = run_lane(directory, OPINION_LIFECYCLE_DEFER)
    return {
        "base_summary": base_summary,
        "base_ledger": base_ledger,
        "cand_summary": cand_summary,
        "cand_ledger": cand_ledger,
    }


def test_both_lifecycles_produce_a_ledger_the_auditor_can_reconstruct(runs):
    base_summary, base_ledger = runs["base_summary"], runs["base_ledger"]
    cand_summary, cand_ledger = runs["cand_summary"], runs["cand_ledger"]

    base = reconstruct(base_ledger, source_commit="test")
    cand = reconstruct(cand_ledger, source_commit="test")
    assert base.status == "PASS", base.failed
    assert cand.status == "PASS", cand.failed
    assert base.accounting["unrecorded"] == 0
    assert cand.accounting["unrecorded"] == 0

    #: El neto del ledger no es el del resumen: los dos tienen que decir lo mismo.
    #: ``net()`` es la vista publicada a 8 decimales; ``net_exact()`` suma los trades.
    assert base.net_exact().quantize(Q_USDT) == base.net()
    assert cand.net_exact().quantize(Q_USDT) == cand.net()
    assert f"{float(base.net()):.6f}" == f"{float(base_summary['net_realised_usdt']):.6f}"
    assert f"{float(cand.net()):.6f}" == f"{float(cand_summary['net_realised_usdt']):.6f}"


def test_the_defer_lifecycle_records_deferrals_and_supersede_does_not(runs):
    base_ledger, cand_ledger = runs["base_ledger"], runs["cand_ledger"]

    def kinds(path: Path) -> dict[str, int]:
        counts: dict[str, int] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            kind = json.loads(line)["entry"].get("kind")
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    base_kinds = kinds(base_ledger)
    cand_kinds = kinds(cand_ledger)
    assert base_kinds.get("OPINION_DEFERRED", 0) == 0
    assert cand_kinds.get("OPINION_DEFERRED", 0) >= 1
    assert base_kinds.get("GUARD_REJECT", 0) >= 1
    assert cand_kinds.get("GUARD_REJECT", 0) == 0


def test_the_attribution_closes_without_residual_on_a_real_run(runs):
    base_ledger, cand_ledger = runs["base_ledger"], runs["cand_ledger"]
    base = reconstruct(base_ledger, source_commit="test")
    cand = reconstruct(cand_ledger, source_commit="test")
    result = attribute({"m1": base}, {"m1": cand})
    scenario = result["per_scenario"]["m1"]
    assert scenario["reconciled"] is True
    assert Decimal(scenario["residual_usdt"]) == 0
    assert Decimal(result["totals"]["delta_net_usdt"]) == (
        cand.net_exact() - base.net_exact()
    ).quantize(Q_USDT)
