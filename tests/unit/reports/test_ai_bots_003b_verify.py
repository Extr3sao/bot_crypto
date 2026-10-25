"""El verificador de AI-BOTS-003B tiene que discrepar cuando los números mienten.

Un verificador que sólo detecta ediciones por el hash de la cadena no verifica nada sobre
la economía: por eso cada mutación vuelve a sellar la cadena antes de comprobar. Lo que
debe fallar entonces es la **regla**, no el hash.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import ai_bots_003b_verify as verify  # noqa: E402

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.provider import ReplayProvider  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402

HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":0.5,"take_profit_pct":0.75,'
    '"invalidation":null,"rationale":"Continuation."}'
)


class SlowProvider(ReplayProvider):
    def __init__(self, answers: list[str], *, latency_ms: int = 90_000) -> None:
        super().__init__(list(answers))
        self._latency = latency_ms

    def analyze(self, request):  # type: ignore[override]
        from dataclasses import replace

        return replace(super().analyze(request), latency_ms=self._latency)


def series() -> list[Bar]:
    """Entrada en el índice 32, stop perforado ahí mismo y hueco de salida después."""

    bars: list[Bar] = []
    price = 100.0
    for index in range(96):
        natural = price
        open_price, close = natural, natural * 1.002
        high, low = max(open_price, close) * 1.001, min(open_price, close) * 0.999
        if index == 32:
            open_price, high, low, close = natural, natural * 1.002, natural * 0.990, natural * 1.001
        if index == 33:
            open_price = natural * 0.97
            high, low, close = open_price * 1.004, open_price * 0.996, open_price * 1.002
        bars.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
        price = close
    return bars


@pytest.fixture(scope="module")
def run_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[dict], dict]:
    out = tmp_path_factory.mktemp("ai-bots-003b")
    base = load_vision_config(env={})
    lane_config = base.lane.__class__(
        timeframe="1h",
        window_bars=30,
        decision_every_bars=15,
        max_calls_per_run=20,
        max_estimated_spend_usd=5.0,
    )
    lane = VisionLane(
        series={"BTC/USDT": series()},
        provider=SlowProvider([LONG] * 40),
        config=base.__class__(provider=base.provider, lane=lane_config),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=out / "decisions.jsonl",
    )
    summary = lane.run()
    summary["root_free"] = "reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B"
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return verify.load_rows(out / "decisions.jsonl"), summary


def mutate(rows: list[dict], kind: str, edit) -> list[dict]:
    for row in rows:
        if row["entry"]["kind"] == kind:
            edit(row["entry"])
            break
    else:  # pragma: no cover - a mutation with no target is a broken test
        raise AssertionError(f"no {kind} row to mutate")
    return verify.reseal(rows)


def test_the_published_run_verifies(run_artifacts) -> None:
    rows, summary = run_artifacts
    verdict = verify.verify_rows(rows, summary)

    assert verdict.failures == [], verdict.failures
    assert len(verdict.checks) >= 15


def test_the_run_contains_the_scenarios_the_mutations_need(run_artifacts) -> None:
    rows, _ = run_artifacts
    fills = verify.rows_of(rows, "FILL")
    closes = verify.rows_of(rows, "CLOSE")

    assert fills and any(c["exit_reason"] == "stop_loss" for c in closes)
    assert any(f["quote_ts_ms"] > f["decision_ts_ms"] for f in fills), (
        "the fixture must exercise a delayed quote, or the PIT checks are vacuous"
    )


def test_a_fill_that_predates_the_answer_is_caught(run_artifacts) -> None:
    rows, summary = run_artifacts
    tampered = mutate(
        rows,
        "FILL",
        lambda entry: entry.__setitem__("quote_ts_ms", entry["received_at_ms"] - 1),
    )

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "fill_quote_at_or_after_answer" in names


def test_a_lied_about_lag_is_caught(run_artifacts) -> None:
    rows, summary = run_artifacts
    tampered = mutate(
        rows, "FILL", lambda entry: entry.__setitem__("quote_lag_ms", entry["quote_lag_ms"] + 60_000)
    )

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "fill_quote_lag_is_measured" in names


def test_a_pnl_that_does_not_net_its_costs_is_caught(run_artifacts) -> None:
    rows, summary = run_artifacts
    tampered = mutate(
        rows, "CLOSE", lambda entry: entry.__setitem__("pnl_net_usdt", entry["pnl_net_usdt"] + 1.0)
    )

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "net_pnl_nets_every_named_cost" in names
    assert "cash_rebuilds_from_realised_pnl" in names


def test_a_stop_credited_better_than_its_level_is_caught(run_artifacts) -> None:
    rows, summary = run_artifacts

    def improve(entry: dict) -> None:
        entry["exit_price"] = float(entry["stop_loss_price"]) * 1.01

    tampered = mutate(rows, "CLOSE", improve)

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "stop_never_credited_better_than_its_level" in names


def test_an_actionable_decision_with_no_terminal_row_is_caught(run_artifacts) -> None:
    """Una decisión que se esfuma entre el veredicto y la ejecución no es un no-trade."""
    rows, summary = run_artifacts
    target = next(f for f in verify.rows_of(rows, "FILL"))["decision_seq"]
    tampered = verify.reseal(
        [
            row
            for row in rows
            if not (
                row["entry"]["kind"] in {"FILL", "DECISION_OUTCOME"}
                and row["entry"].get("decision_seq") == target
            )
        ]
    )

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "every_actionable_decision_is_resolved" in names


def test_a_reused_position_id_is_caught(run_artifacts) -> None:
    rows, summary = run_artifacts
    fill = next(row for row in rows if row["entry"]["kind"] == "FILL")
    duplicated = [*rows, json.loads(json.dumps(fill))]
    tampered = verify.reseal(duplicated)

    names = [check.name for check in verify.verify_rows(tampered, summary).checks if not check.ok]
    assert "position_ids_are_unique_and_owned" in names


def test_an_absolute_path_in_the_summary_is_caught(run_artifacts, tmp_path: Path) -> None:
    rows, summary = run_artifacts
    dirty = dict(summary)
    dirty["artifact"] = str(tmp_path / "decisions.jsonl")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in verify.reseal(rows)) + "\n",
        encoding="utf-8",
    )

    verdict = verify.verify_run(ledger, dirty)

    assert "summary_is_portable_between_roots" in [
        check.name for check in verdict.checks if not check.ok
    ]


def test_the_cli_refuses_to_pass_without_artifacts(tmp_path: Path) -> None:
    code = verify.main(
        [
            "--ledger",
            str(tmp_path / "missing.jsonl"),
            "--summary",
            str(tmp_path / "missing.json"),
        ]
    )

    assert code == 2, "a missing artifact is BLOCKED, never a pass"
