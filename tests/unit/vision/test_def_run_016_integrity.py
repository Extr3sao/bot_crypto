"""DEF-RUN-016 — la invariante de ciclo de vida, atacada desde fuera.

Estos tests no comprueban que el carril "funcione": comprueban que **no puede publicar un
resumen** cuando la contabilidad de opiniones no cuadra, y que cada forma conocida de
romperla (opinión perdida, cierre duplicado, rechazo del broker, hueco, expiración,
sustitución, pendiente al final, resumen manipulado, ledger corrupto, fallo al publicar,
interrupción) deja un resultado observable y persistido.

Las doce formas del enunciado, una por test:

 1. opinión desaparecida ......................... ``test_a_lost_opinion_blocks_the_summary``
 2. cierre terminal duplicado ................... ``test_a_duplicate_terminal_is_refused``
 3. rechazo del broker .......................... ``test_a_broker_refusal_is_a_named_terminal``
 4. ``DATA_GAP`` ................................ ``test_a_hole_ends_the_opinion_with_its_code``
 5. ``DEFER`` con expiración .................... ``test_an_expired_opinion_is_joinable``
 6. ``SUPERSEDE`` con reemplazo ................. ``test_a_supersede_names_its_replacement``
 7. ``pending_at_end`` con y sin continuidad .... ``test_pending_at_end_is_terminal_in_its_own_session``
 8. resumen RUN manipulado ...................... ``test_a_tampered_summary_is_not_certified``
 9. ledger incompleto o corrupto ................ ``test_a_corrupt_or_unfinished_ledger_is_not_certified``
10. fallo durante la publicación ................ ``test_a_failure_while_publishing_leaves_no_verdict``
11. reinicio o interrupción ..................... ``test_an_interrupted_run_is_a_chain_without_a_verdict``
12. contadores correctos con eventos incorrectos  ``test_correct_counters_with_wrong_events_are_refused``

Ninguno se conforma con "no lanzó": cada uno exige el código, las opiniones afectadas y la
fila persistida que hace el fallo reconstruible.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.execution import Quote, QuoteRange
from trading_bot.vision.lane import (
    OPINION_LIFECYCLE_DEFER,
    OPINION_LIFECYCLE_SUPERSEDE,
    OpinionLifecycleError,
    VisionLane,
)
from trading_bot.vision.ledger import read_entries, verify_chain
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.quotes import MINUTE_MS
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
SYMBOL = "BTC/USDT"
START_MS = 1_792_500_000_000
MINUTE = MINUTE_MS

NO_TRADE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"NO_TRADE",'
    '"confidence":0.5,"horizon_bars":8,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"Nothing to do."}'
)

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.8,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
    '"invalidation":null,"rationale":"Continuation."}'
)


class LatencyProvider(ReplayProvider):
    def __init__(self, answers: list[str], *, latency_ms: int = 0) -> None:
        super().__init__(list(answers))
        self._latency_ms = latency_ms
        self.answered = 0

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        self.answered += 1
        response: VisionResponse = super().analyze(request)  # type: ignore[arg-type]
        return replace(response, latency_ms=self._latency_ms)


class Minutes:
    """Feed de 1 minuto con el contrato real, para que el test sea del carril."""

    name = "def_run_016_integrity_minutes"

    def __init__(self, bars: list[Bar]) -> None:
        self._minutes: list[Bar] = []
        for bar in bars:
            for minute in range(60):
                self._minutes.append(
                    Bar(
                        ts_ms=int(bar.ts_ms) + minute * MINUTE,
                        open=float(bar.open),
                        high=float(bar.open),
                        low=float(bar.open),
                        close=float(bar.open),
                        volume=1.0,
                    )
                )

    def first_quote_at_or_after(
        self, symbol: str, ts_ms: int, *, horizon_ms: int
    ) -> Quote | None:
        for bar in self._minutes:
            if int(bar.ts_ms) >= int(ts_ms):
                if int(bar.ts_ms) - int(ts_ms) > int(horizon_ms):
                    return None
                return Quote(
                    symbol=symbol, ts_ms=int(bar.ts_ms), price=float(bar.open), source=self.name
                )
        return None

    def range_between(self, symbol: str, after_ms: int, until_ms: int) -> QuoteRange | None:
        rows = [b for b in self._minutes if int(after_ms) < int(b.ts_ms) < int(until_ms)]
        if not rows:
            return None
        return QuoteRange(
            symbol=symbol,
            after_ms=int(after_ms),
            until_ms=int(until_ms),
            minutes=len(rows),
            high=max(float(b.high) for b in rows),
            low=min(float(b.low) for b in rows),
            last=float(rows[-1].close),
            source=self.name,
        )


def bars(*, count: int = 40, remove: tuple[int, ...] = ()) -> list[Bar]:
    out: list[Bar] = []
    for index in range(count):
        if index in set(remove):
            continue
        opened = 100.0 + index * 0.01
        out.append(
            Bar(
                ts_ms=START_MS + index * MINUTE,
                open=opened,
                high=opened * 1.0005,
                low=opened * 0.9995,
                close=opened,
                volume=10.0,
            )
        )
    return out


def policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def vision_config(
    *, max_opinion_age_ms: int = 0, decision_every_bars: int = 1
):
    base = load_vision_config(env={})
    lane = base.lane.__class__(
        timeframe="1m",
        window_bars=10,
        decision_every_bars=decision_every_bars,
        max_calls_per_run=200,
        max_estimated_spend_usd=10.0,
        max_opinion_age_ms=max_opinion_age_ms,
        data_delay_ms=0,
    )
    return base.__class__(provider=base.provider, lane=lane)


def make_lane(
    path: Path,
    *,
    series: list[Bar],
    latency_ms: int = 0,
    lifecycle: str = OPINION_LIFECYCLE_DEFER,
    max_opinion_age_ms: int = 0,
    feed: bool = True,
    provider=None,
    decision_every_bars: int = 1,
) -> VisionLane:
    return VisionLane(
        series={SYMBOL: series},
        provider=provider or LatencyProvider([LONG] * 400, latency_ms=latency_ms),
        config=vision_config(
            max_opinion_age_ms=max_opinion_age_ms,
            decision_every_bars=decision_every_bars,
        ),
        risk_policy=policy(),
        ledger_path=path,
        quote_feed=Minutes(series) if feed else None,
        subbar_entries=True,
        opinion_lifecycle=lifecycle,
    )


def rows_of(path: Path) -> list[dict[str, Any]]:
    return [dict(line["entry"], seq=int(line["seq"])) for line in read_entries(path)]


def of_kind(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == kind]


def _wrap(lane: VisionLane, hook) -> None:
    """Inyecta un fallo en el escritor del ledger, sin tocar el código de producción.

    Es una inyección de fallo, no una simulación del resultado: el carril corre entero y
    el único cambio es lo que llega al disco (o cuántas veces llega).
    """
    original = lane.ledger.append

    def append(kind, payload, *, clock=None):  # type: ignore[no-untyped-def]
        action = hook(kind, payload)
        if action is None:
            return original(kind, payload, clock=clock)
        if action[0] == "drop":
            return None
        if action[0] == "dup":
            original(kind, payload, clock=clock)
            return original(kind, action[1], clock=clock)
        if action[0] == "replace":
            return original(kind, action[1], clock=clock)
        raise AssertionError(f"unknown injection: {action!r}")

    lane.ledger.append = append  # type: ignore[method-assign]


def _failure_row(path: Path) -> dict[str, Any]:
    rows = of_kind(rows_of(path), "INTEGRITY_FAILURE")
    assert rows, "the failure must be persisted in the ledger, not only raised"
    return rows[-1]


# 1. opinión desaparecida -----------------------------------------------------------


def test_a_lost_opinion_blocks_the_summary(tmp_path):
    """Un relleno que no llega al ledger: la opinión nace, no muere y el resumen no sale."""
    path = tmp_path / "lost.jsonl"
    lane = make_lane(path, series=bars(count=40))
    dropped = {"done": False}

    def hook(kind: str, payload: dict[str, Any]):
        if kind == "FILL" and not dropped["done"]:
            dropped["done"] = True
            return ("drop",)
        return None

    _wrap(lane, hook)

    with pytest.raises(OpinionLifecycleError) as caught:
        lane.run()

    error = caught.value
    assert error.code == "OPINION_LIFECYCLE_VIOLATION"
    assert dropped["done"], "the fault must actually have fired"
    assert error.fields["unrecorded"], "the opinion that lost its terminal is named"
    missing = error.fields["unrecorded"][0]
    assert missing in {
        int(row["seq"]) for row in of_kind(rows_of(path), "DECISION") if row.get("intent")
    }, "the lost opinion is a real decision row, not an invented id"
    rows = rows_of(path)
    assert not of_kind(rows, "RUN_END"), "a PASS summary must not be published"
    failure = _failure_row(path)
    assert failure["code"] == "OPINION_LIFECYCLE_VIOLATION"
    assert failure["persisted_before_raise"] is True
    assert failure["opinion_accounting"]["adds_up"] is False
    assert verify_chain(path)["ok"] is True, "the failure row joins the chain, it is not outside it"


# 2. cierre terminal duplicado -----------------------------------------------------


def test_a_duplicate_terminal_is_refused(tmp_path):
    """Dos filas terminales para la misma opinión: se cuentan dos veces o se elige una."""
    path = tmp_path / "dup.jsonl"
    lane = make_lane(path, series=bars(count=40))
    duplicated = {"done": False}

    def hook(kind: str, payload: dict[str, Any]):
        if kind == "FILL" and not duplicated["done"]:
            duplicated["done"] = True
            return ("dup", dict(payload))
        return None

    _wrap(lane, hook)

    with pytest.raises(OpinionLifecycleError) as caught:
        lane.run()

    assert duplicated["done"]
    duplicates = caught.value.fields["duplicate_terminals"]
    assert duplicates, "two closures of one opinion must be named, not merged"
    assert len(duplicates[0]["events"]) == 2
    assert {event["class"] for event in duplicates[0]["events"]} == {"FILLED"}
    assert not of_kind(rows_of(path), "RUN_END")


# 3. rechazo del broker ------------------------------------------------------------


def test_a_broker_refusal_is_a_named_terminal(tmp_path):
    path = tmp_path / "broker.jsonl"
    lane = make_lane(path, series=bars(count=24))
    lane.broker.execute_signal = lambda signal: None  # type: ignore[method-assign]

    summary = lane.run()
    rows = rows_of(path)

    refusals = [
        outcome
        for outcome in of_kind(rows, "DECISION_OUTCOME")
        if outcome.get("risk_gate") == "BROKER_REJECTED"
    ]
    assert refusals, "the refusal is a row with the opinion's id"
    accounting = summary["opinion_accounting"]
    assert accounting["adds_up"] is True
    assert accounting["terminal_classes"]["GATED"] == len(refusals)
    assert accounting["terminal"] == accounting["generated"]
    births = {int(row["seq"]) for row in of_kind(rows, "DECISION")}
    assert all(int(row["decision_seq"]) in births for row in refusals), (
        "the refusal names an opinion that exists, so it is a closure and not an orphan"
    )


# 4. DATA_GAP ----------------------------------------------------------------------


def test_a_hole_ends_the_opinion_with_its_code(tmp_path):
    path = tmp_path / "gap.jsonl"
    answers = [NO_TRADE, NO_TRADE, LONG] + [LONG] * 400
    lane = make_lane(
        path,
        series=bars(count=40, remove=(12,)),
        feed=False,
        provider=LatencyProvider(answers, latency_ms=30_000),
    )
    summary = lane.run()
    rows = rows_of(path)

    gaps = [row for row in of_kind(rows, "GUARD_REJECT") if row.get("code") == "DATA_GAP"]
    assert gaps, "the hole must refuse an executable path"
    accounting = summary["opinion_accounting"]
    assert accounting["adds_up"] is True
    assert accounting["terminal_classes"]["REJECTED"] == len(
        [row for row in of_kind(rows, "GUARD_REJECT") if row.get("decision_seq") is not None]
    )
    assert summary["execution"]["opinions"]["rejected"].get("DATA_GAP") == len(gaps)
    for gap in gaps:
        assert gap["decision_seq"] in {int(row["seq"]) for row in of_kind(rows, "DECISION")}


# 5. DEFER con expiración ----------------------------------------------------------


def test_an_expired_opinion_is_joinable(tmp_path):
    """Sin ``decision_seq`` la expiración no se podía unir con su nacimiento."""
    path = tmp_path / "expired.jsonl"
    #: Cadencia 5 y no 1: con una decisión por barra la siguiente opinión sustituye a la
    #: que espera antes de que llegue a preciarse, y la expiración nunca se ejerce.
    lane = make_lane(
        path,
        series=bars(count=40),
        latency_ms=90_000,
        max_opinion_age_ms=60_000,
        decision_every_bars=5,
    )
    summary = lane.run()
    rows = rows_of(path)

    expired = [row for row in of_kind(rows, "GUARD_REJECT") if row.get("code") == "LATE_RESPONSE"]
    assert expired, "a model slower than its window cannot trade"
    births = {int(row["seq"]) for row in of_kind(rows, "DECISION")}
    for row in expired:
        assert int(row["decision_seq"]) in births, "the expiry names the opinion it kills"
        assert int(row["opinion_age_ms"]) > int(row["max_opinion_age_ms"])
    opinions = summary["execution"]["opinions"]
    assert opinions["expired"] == len(expired) == opinions["rejected"]["LATE_RESPONSE"]
    assert summary["opinion_accounting"]["unrecorded"] == []
    assert summary["opinion_accounting"]["adds_up"] is True


# 6. SUPERSEDE con reemplazo -------------------------------------------------------


def test_a_supersede_names_its_replacement(tmp_path):
    path = tmp_path / "supersede.jsonl"
    lane = make_lane(
        path,
        series=bars(count=40),
        latency_ms=30_000,
        lifecycle=OPINION_LIFECYCLE_SUPERSEDE,
    )
    summary = lane.run()
    rows = rows_of(path)

    superseded = [
        row
        for row in of_kind(rows, "GUARD_REJECT")
        if row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ]
    births = {int(row["seq"]) for row in of_kind(rows, "DECISION")}
    assert superseded, "with the pre-DEF-RUN-016 rule the waiting opinion is replaced"
    for row in superseded:
        assert int(row["decision_seq"]) in births
        assert int(row["replaced_by_decision_seq"]) in births, (
            "the replacement is a decision that exists, not a promise"
        )
    accounting = summary["opinion_accounting"]
    assert accounting["adds_up"] is True, f"a replaced opinion still terminates once: {accounting}"
    assert summary["execution"]["opinions"]["superseded"] == len(superseded)


# 7. pending_at_end con y sin continuidad ------------------------------------------


def test_pending_at_end_is_terminal_in_its_own_session(tmp_path):
    """Sin continuidad entre sesiones, una orden en vuelo muere con su sesión y lo dice."""
    first = tmp_path / "session-1.jsonl"
    first_summary = make_lane(first, series=bars(count=40)).run()
    first_rows = rows_of(first)

    pending_rows = [
        row
        for row in of_kind(first_rows, "GUARD_REJECT")
        if row.get("code") == "RUN_ENDED_WITH_ORDER_PENDING"
    ]
    accounting = first_summary["opinion_accounting"]
    assert accounting["session_continuity"] == "NONE"
    assert first_summary["execution"]["opinions"]["pending_at_end"] == len(pending_rows)
    for row in pending_rows:
        assert int(row["decision_seq"]) in {
            int(item["seq"]) for item in of_kind(first_rows, "DECISION")
        }
    assert accounting["adds_up"] is True
    assert accounting["terminal"] == accounting["generated"]

    #: La sesión siguiente vuelve a formar sus propias opiniones: no hereda las pendientes
    #: de la anterior ni las cuenta dos veces.
    second = tmp_path / "session-2.jsonl"
    second_summary = make_lane(second, series=bars(count=64)).run()
    second_rows = rows_of(second)
    second_births = {
        int(row["seq"])
        for row in of_kind(second_rows, "DECISION")
        if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}
    }
    assert second_summary["opinion_accounting"]["generated"] == len(second_births)
    assert second_summary["opinion_accounting"]["adds_up"] is True
    first_births = {
        int(row["seq"])
        for row in of_kind(first_rows, "DECISION")
        if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}
    }
    assert first_summary["opinion_accounting"]["generated"] == len(first_births)
    #: Las opiniones pendientes de la primera sesión terminan **en** la primera sesión:
    #: no hay ninguna que la segunda herede ni vuelva a contar.
    for row in pending_rows:
        assert int(row["decision_seq"]) in first_births
    assert not set(first_summary["opinion_accounting"]["unrecorded"]), (
        "nothing is left dangling for a later session to pick up"
    )


# 8. resumen RUN manipulado --------------------------------------------------------


def _verifier():
    spec = importlib.util.spec_from_file_location(
        "def_run_016_verify", REPO / "scripts" / "def_run_016_verify.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not (REPO / "scripts" / "def_run_016_verify.py").exists(),
    reason="scripts/def_run_016_verify.py is outside the supervisor slice and is not migrated",
)
def test_a_tampered_summary_is_not_certified(tmp_path):
    path = tmp_path / "summary.jsonl"
    make_lane(path, series=bars(count=40)).run()
    verifier = _verifier()
    rows = verifier.rows_of(path)
    metrics = verifier.recompute(rows, interval_ms=MINUTE)
    run_end = next(row for row in rows if row.get("kind") == "RUN_END")
    published = dict(run_end["execution"]["opinions"])

    assert verifier.summary_disagreements(rows, published) == [], (
        "the published summary must agree with a recompute from the bytes when untouched"
    )
    published["generated"] = int(published["generated"]) + 1
    disagreements = verifier.summary_disagreements(rows, published)
    assert disagreements, "an inflated summary must be refused by the independent recompute"
    assert any(item["field"] == "generated" for item in disagreements)
    assert metrics["terminal"] == metrics["actionable_opinions"]


# 9. ledger incompleto o corrupto --------------------------------------------------


def test_a_corrupt_or_unfinished_ledger_is_not_certified(tmp_path):
    path = tmp_path / "corrupt.jsonl"
    make_lane(path, series=bars(count=40)).run()
    verifier = _verifier()

    assert verifier.verify_chain(path)[0] is True

    tampered = tmp_path / "tampered.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["entry"] = {**record["entry"], "code": "FORGED"}
    lines[2] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, reason = verifier.verify_chain(tampered)
    assert ok is False and "rebuilt" in reason, "a rewritten past row cannot verify"

    original = path.read_text(encoding="utf-8").splitlines()
    unfinished = tmp_path / "unfinished.jsonl"
    unfinished.write_text(
        "\n".join(line for line in original if '"RUN_END"' not in line) + "\n",
        encoding="utf-8",
    )
    assert verifier.verify_chain(unfinished)[0] is True, "the chain is intact, the verdict is not"
    rows = verifier.rows_of(unfinished)
    metrics = verifier.recompute(rows, interval_ms=MINUTE)
    assert metrics["run_end_present"] is False
    run_end = next((row for row in rows if row.get("kind") == "RUN_END"), None)
    assert run_end is None, "an unfinished ledger publishes no PASS"


# 10. fallo durante la publicación de evidencias -----------------------------------


def test_a_failure_while_publishing_leaves_no_verdict(tmp_path):
    """Si el resumen no se puede persistir, la corrida no devuelve un resultado correcto."""
    path = tmp_path / "publish.jsonl"
    lane = make_lane(path, series=bars(count=40))

    def hook(kind: str, payload: dict[str, Any]):
        if kind == "RUN_END":
            raise OSError("disk full while publishing the summary")
        return None

    _wrap(lane, hook)

    with pytest.raises(OSError):
        lane.run()

    rows = rows_of(path)
    assert not of_kind(rows, "RUN_END"), "the summary that failed to persist is not in the chain"
    assert verify_chain(path)["ok"] is True
    #: Los contadores se verificaron antes de publicar, pero no hay resumen: nada que
    #: citar como PASS.
    assert all(row.get("kind") != "INTEGRITY_FAILURE" for row in rows), (
        "the accounting was sound; the failure was the write, and the two are distinguishable"
    )


# 11. reinicio o interrupción de ejecución -----------------------------------------


def test_an_interrupted_run_is_a_chain_without_a_verdict(tmp_path):
    class Interrupted(LatencyProvider):
        def analyze(self, request):  # type: ignore[override]
            if self.answered == 3:
                raise RuntimeError("process killed mid-run")
            return super().analyze(request)

    path = tmp_path / "interrupted.jsonl"
    lane = make_lane(path, series=bars(count=40), provider=Interrupted([LONG] * 400))

    with pytest.raises(RuntimeError):
        lane.run()

    rows = rows_of(path)
    assert rows and not of_kind(rows, "RUN_END")
    assert verify_chain(path)["ok"] is True, (
        "an interrupted run leaves a valid partial chain, not a corrupt file"
    )
    assert not path.with_suffix(".jsonl.lock").exists(), "the writer released its lock"

    restarted = tmp_path / "restarted.jsonl"
    summary = make_lane(restarted, series=bars(count=40)).run()
    first = rows_of(restarted)[0]
    assert first["kind"] == "RUN" and first["seq"] == 1, "a new session starts its own chain"
    assert summary["opinion_accounting"]["adds_up"] is True


# 12. contadores correctos con eventos incorrectos ---------------------------------


def test_correct_counters_with_wrong_events_are_refused(tmp_path):
    """Los contadores siguen cuadrando consigo mismos; las filas ya no cuadran con ellos."""
    path = tmp_path / "misattributed.jsonl"
    lane = make_lane(path, series=bars(count=40))
    rewired = {"done": False}

    def hook(kind: str, payload: dict[str, Any]):
        if kind == "FILL" and not rewired["done"]:
            rewired["done"] = True
            return ("replace", {**payload, "decision_seq": 1})  # seq 1 es la cabecera RUN
        return None

    _wrap(lane, hook)

    with pytest.raises(OpinionLifecycleError) as caught:
        lane.run()

    fields = caught.value.fields
    assert fields["unrecorded"], "the opinion whose fill was misattributed is now unrecorded"
    assert fields["orphan_terminals"], "the terminal points at an opinion that never existed"
    assert any(
        item["field"] == "executed_openings" for item in fields["counter_disagreements"]
    ), "the published counter and the ledger say different things"
    assert not of_kind(rows_of(path), "RUN_END")
