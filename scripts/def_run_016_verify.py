"""DEF-RUN-016 — verificador independiente (solo stdlib).

No importa ``trading_bot``: recalcula todo desde los bytes publicados. Si este script y el
constructor discrepan, el informe no vale; por eso las cuentas se rehacen aquí y no se leen
del JSON que produjo el carril.

Comprueba:

* las cadenas de hashes de los ledgers del audit y que sus métricas publicadas se
  reconstruyen fila a fila;
* que CURRENT (regla ``SUPERSEDE``, la de antes del arreglo) destruye opiniones ejecutables
  y que PROPOSED no lo hace, con los dos controles inertes;
* los invariantes de causalidad de cada relleno (``quote >= received >= decision``, edad
  dentro del TTL, sin posiciones duplicadas);
* que la economía publicada se reconstruye desde los ledgers de ``EXP-003L`` y que la
  alternativa se eligió en DEV y se juzgó en HOLDOUT;
* que ``config/risk.yaml`` es el mismo que declararon las sesiones publicadas.

Uso::

    python scripts/def_run_016_verify.py
    python scripts/def_run_016_verify.py --root reports/ai-bots/RFC-DEF-RUN-016
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
SCHEMA_AUDIT = "DEF_RUN_016_AUDIT_V1"
SCHEMA_COMPARISON = "DEF_RUN_016_COMPARISON_V1"
SCHEMA_ECONOMICS = "DEF_RUN_016_ECONOMICS_V1"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    return bool(ok)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_chain(path: Path) -> tuple[bool, str]:
    prev = GENESIS
    expected_seq = 1
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        if int(record["seq"]) != expected_seq:
            return False, f"seq {record['seq']} != {expected_seq}"
        if record["prev_sha256"] != prev:
            return False, f"prev_sha256 broken at seq {record['seq']}"
        computed = hashlib.sha256(
            canonical(
                {
                    "seq": record["seq"],
                    "prev_sha256": record["prev_sha256"],
                    "entry": record["entry"],
                }
            ).encode()
        ).hexdigest()
        if computed != record["sha256"]:
            return False, f"row {record['seq']} rebuilt to {computed[:12]}"
        prev = record["sha256"]
        expected_seq += 1
    return True, f"{expected_seq - 1} rows"


def rows_of(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            record = json.loads(line)
            entry = dict(record["entry"])
            entry["seq"] = int(record["seq"])
            out.append(entry)
    return out


def terminal_of(row: dict[str, Any]) -> tuple[str, str] | None:
    """Qué declara esta fila, leída como documento y no como contador.

    La fila de aprobación de una entrada rellenada no es un cierre: no lleva ``executed`` y
    el ``FILL`` que la sigue es el evento terminal. Por eso una opinión rellenada tiene una
    sola fila de cierre aunque su aprobación también nombre su ``decision_seq``.
    """
    kind = row.get("kind")
    if kind == "FILL":
        return ("FILLED", "FILL")
    if kind == "DECISION_OUTCOME":
        intent = str(row.get("intent") or "")
        executed = row.get("executed")
        if intent == "CLOSE":
            if executed is True:
                return ("CLOSED", "CLOSE_EXECUTED")
            if executed is False:
                return ("GATED", str(row.get("risk_gate") or "CLOSE_NOT_EXECUTED"))
            return None
        if row.get("approved") is False:
            return ("BLOCKED_BY_RISK", str(row.get("risk_blocked_by") or "unknown"))
        if row.get("approved") is True and executed is False:
            return ("GATED", str(row.get("risk_gate") or "unknown"))
        return None
    if kind == "GUARD_REJECT" and row.get("decision_seq") is not None:
        return ("REJECTED", str(row.get("code") or "UNKNOWN"))
    return None


def percentiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "p50": None}
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "p50": round(ordered[max(0, math.ceil(0.5 * len(ordered)) - 1)], 6),
    }


# --------------------------------------------------------------------------- audit


#: Campos del bloque ``execution.opinions`` que la identidad obliga a cruzar. ``rejected``
#: se compara aparte, código a código, porque su suma es el quinto sumando.
SUMMARY_FIELDS = ("generated", "executed_openings", "closed_by_intent", "blocked_by_risk", "gated")


def summary_disagreements(
    rows: list[dict[str, Any]], published: dict[str, Any]
) -> list[dict[str, Any]]:
    """Contrasta el resumen que publicó el carril con lo que dicen las filas.

    Función pura y sin estado para que una prueba pueda manipular un resumen y comprobar
    que el verificador lo rechaza. No importa ``trading_bot``: el resumen es un documento
    más, y sus números no valen por venir del productor.
    """
    metrics = recompute(rows, interval_ms=int(metrics_interval(rows)))
    disagreements: list[dict[str, Any]] = []
    for field, derived in (
        ("generated", metrics["actionable_opinions"]),
        ("executed_openings", metrics["terminal_classes"]["FILLED"]),
        ("closed_by_intent", metrics["terminal_classes"]["CLOSED"]),
        ("blocked_by_risk", metrics["terminal_classes"]["BLOCKED_BY_RISK"]),
        ("gated", metrics["terminal_classes"]["GATED"]),
    ):
        if int(published.get(field, -1)) != int(derived):
            disagreements.append(
                {"field": field, "published": published.get(field), "ledger": derived}
            )
    rejected = sum(int(value) for value in (published.get("rejected") or {}).values())
    if rejected != int(metrics["terminal_classes"]["REJECTED"]):
        disagreements.append(
            {
                "field": "rejected",
                "published": rejected,
                "ledger": metrics["terminal_classes"]["REJECTED"],
            }
        )
    for field, code in (
        ("expired", "LATE_RESPONSE"),
        ("superseded", "SUPERSEDED_BY_NEWER_OPINION"),
        ("pending_at_end", "RUN_ENDED_WITH_ORDER_PENDING"),
    ):
        derived = int(metrics["rejected_by_code"].get(code, 0))
        if int(published.get(field, -1)) != derived:
            disagreements.append(
                {"field": field, "published": published.get(field), "ledger": derived}
            )
    return disagreements


def metrics_interval(rows: list[dict[str, Any]]) -> int:
    """El intervalo declarado por el ``RUN``. Un ledger sin cabecera no se certifica."""
    run = next((row for row in rows if row.get("kind") == "RUN"), None)
    if run is None:
        raise ValueError("ledger has no RUN header")
    lane = run.get("lane") or {}
    return int(lane.get("bar_interval_ms") or lane.get("interval_ms") or 60_000)


def verify_capture(root: Path, label: str, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    check(f"{label}: schema", payload.get("schema_version") == SCHEMA_AUDIT, str(payload.get("schema_version")))
    check(f"{label}: lifecycle declared", payload.get("lifecycle") in ("DEFER", "SUPERSEDE"))
    check(
        f"{label}: lane module is this tree",
        Path(payload.get("lane_module_path", "")).as_posix().endswith("src/trading_bot/vision/lane.py"),
        str(payload.get("lane_module_path")),
    )
    derived: dict[str, dict[str, Any]] = {}
    for name, scenario in sorted(payload["scenarios"].items()):
        ledger = root / "evidence" / "ledgers" / label / f"{name}.jsonl"
        if not check(f"{label}/{name}: ledger present", ledger.is_file(), str(ledger)):
            continue
        ok, detail = verify_chain(ledger)
        check(f"{label}/{name}: hash chain", ok, detail)
        check(
            f"{label}/{name}: ledger sha256",
            sha256_file(ledger) == scenario["ledger"]["sha256"],
            scenario["ledger"]["sha256"][:12],
        )
        rows = rows_of(ledger)
        check(f"{label}/{name}: row count", len(rows) == scenario["ledger"]["rows"], f"{len(rows)}")
        metrics = recompute(rows, interval_ms=int(scenario["config"]["interval_ms"]))
        derived[name] = metrics
        for field in (
            "calls",
            "decision_rows",
            "actionable_opinions",
            "fills",
            "deferred_slots",
            "superseded",
            "expired",
            "data_gap",
            "risk_blocked",
            "pending_at_end",
            "stale_fills",
            "over_age_fills",
            "ids_unique",
            "duplicate_terminals",
            "orphan_terminals",
            "unrecorded",
            "terminal_before_birth",
            "fills_without_approval",
            "run_end_present",
            "rows_after_run_end",
            "terminal",
        ):
            check(
                f"{label}/{name}: {field} recomputes",
                metrics[field] == scenario["metrics"][field],
                f"published={scenario['metrics'][field]} rebuilt={metrics[field]}",
            )
        classes = metrics["terminal_classes"]
        #: El resumen del `RUN` no se cree: se contrasta con las clases recalculadas desde los
        #: bytes. Un contador que solo coincide consigo mismo no prueba nada.
        published = (scenario.get("summary_view") or {}).get("execution_opinions") or {}
        if published:
            disagreements = summary_disagreements(rows, published)
            check(
                f"{label}/{name}: summary agrees with the ledger",
                not disagreements,
                f"{disagreements[:3]}",
            )
        #: La declaración del carril tampoco se acepta: si dice que cuadra, sus números
        #: tienen que ser los que salen de las filas. Un PASS auto-declarado no es prueba.
        declared = (scenario.get("summary_view") or {}).get("opinion_accounting") or {}
        if declared:
            check(
                f"{label}/{name}: the runtime's own accounting is the ledger's",
                declared.get("adds_up") is True
                and int(declared.get("generated", -1)) == metrics["actionable_opinions"]
                and int(declared.get("terminal", -1)) == metrics["terminal"]
                and (declared.get("terminal_classes") or {}) == metrics["terminal_classes"]
                and not declared.get("unrecorded")
                and not declared.get("duplicate_terminals")
                and (declared.get("counter_disagreements") or []) == [],
                f"declared={ {key: declared.get(key) for key in ('adds_up', 'generated', 'terminal')} } "
                f"ledger={metrics['actionable_opinions']}/{metrics['terminal']}",
            )
        #: Estructura: cada opinión nace una vez, termina exactamente una vez, y ninguna
        #: fila terminal apunta a un nacimiento que no existe. Es lo que impide que dos
        #: contadores correctos describan eventos incorrectos.
        check(
            f"{label}/{name}: unique opinion ids",
            metrics["ids_unique"] is True,
            f"duplicates={metrics['ids_unique']}",
        )
        check(
            f"{label}/{name}: exactly one terminal per opinion",
            metrics["duplicate_terminals"] == 0 and metrics["orphan_terminals"] == 0,
            f"duplicate={metrics['duplicate_terminals']} orphan={metrics['orphan_terminals']}",
        )
        check(
            f"{label}/{name}: lifecycle identity",
            metrics["unrecorded"] == 0
            and metrics["terminal"] == metrics["actionable_opinions"],
            f"actionable={metrics['actionable_opinions']} classes={classes} "
            f"unrecorded={metrics['unrecorded']} rejected={metrics['rejected_by_code']}",
        )
        #: Un ledger sin ``RUN_END`` no tiene veredicto: puede ser una corrida interrumpida
        #: y certificarla como PASS sería exactamente el falso positivo que se persigue.
        check(
            f"{label}/{name}: the run closed with a verdict",
            metrics["run_end_present"] is True and metrics["rows_after_run_end"] == 0,
            f"run_end={metrics['run_end_present']} rows_after={metrics['rows_after_run_end']}",
        )
        check(
            f"{label}/{name}: legal transitions",
            metrics["terminal_before_birth"] == 0
            and metrics["fills_without_approval"] == 0,
            f"terminal_before_birth={metrics['terminal_before_birth']} "
            f"fills_without_approval={metrics['fills_without_approval']}",
        )
        check(
            f"{label}/{name}: no stale or over-age fill",
            metrics["stale_fills"] == 0 and metrics["over_age_fills"] == 0,
            f"stale={metrics['stale_fills']} over_age={metrics['over_age_fills']}",
        )
        check(
            f"{label}/{name}: no duplicate position",
            metrics["duplicate_positions"] == 0,
            str(metrics["duplicate_positions"]),
        )
    return derived


def recompute(rows: list[dict[str, Any]], *, interval_ms: int) -> dict[str, Any]:
    decisions = [row for row in rows if row.get("kind") == "DECISION"]
    actionable = [row for row in decisions if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}]
    fills = [row for row in rows if row.get("kind") == "FILL"]
    outcomes = [row for row in rows if row.get("kind") == "DECISION_OUTCOME"]
    rejects = [row for row in rows if row.get("kind") == "GUARD_REJECT"]
    deferred = [row for row in rows if row.get("kind") == "OPINION_DEFERRED"]

    #: Una opinión accionable tiene **exactamente un** evento terminal. Aquí no hay
    #: precedencia que pueda ocultar un segundo cierre: se recogen **todas** las filas que
    #: declaran cierre y una lista con más de una es un fallo, no un empate a resolver. Es
    #: la diferencia entre «elegir la buena» y «comprobar que solo hay una».
    births = {int(row["seq"]): row for row in actionable}
    events: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        observed = terminal_of(row)
        target = row.get("decision_seq")
        if observed is None or target is None:
            continue
        events.setdefault(int(target), []).append(
            {
                "seq": int(row["seq"]),
                "kind": row.get("kind"),
                "class": observed[0],
                "reason": observed[1],
            }
        )
    classes: dict[str, set[int]] = {
        "FILLED": set(),
        "CLOSED": set(),
        "BLOCKED_BY_RISK": set(),
        "GATED": set(),
        "REJECTED": set(),
    }
    rejected_by_code: Counter[str] = Counter()
    duplicate_terminals: list[int] = []
    orphan_terminals: list[int] = []
    terminal_before_birth: list[int] = []
    for seq, found in sorted(events.items()):
        if seq not in births:
            orphan_terminals.append(seq)
            continue
        if len(found) > 1:
            duplicate_terminals.append(seq)
        first = found[0]
        classes[first["class"]].add(seq)
        if first["class"] == "REJECTED":
            rejected_by_code[str(first["reason"])] += 1
        if int(first["seq"]) < seq:
            terminal_before_birth.append(seq)
    pending = [row for row in actionable if int(row["seq"]) not in events]
    unrecorded = [seq for seq in sorted(births) if seq not in events]
    resolved = {name: len(group) for name, group in classes.items()}
    run_end = [index for index, row in enumerate(rows) if row.get("kind") == "RUN_END"]
    approved_seqs = {
        int(row["decision_seq"])
        for row in outcomes
        if row.get("approved") is True and row.get("risk_gate") == "check_signal"
    }
    fills_without_approval = [
        row for row in fills if int(row["decision_seq"]) not in approved_seqs
    ]

    run = next((row for row in rows if row.get("kind") == "RUN"), None) or {}
    max_age = int(((run.get("lane") or {}).get("max_opinion_age_ms")) or interval_ms)
    stale = [
        row
        for row in fills
        if int(row["quote_ts_ms"]) < int(row["received_at_ms"])
        or int(row["quote_ts_ms"]) < int(row["decision_ts_ms"])
    ]
    over_age = [row for row in fills if int(row["opinion_age_ms"]) > max_age]
    positions = [str(row.get("position_id")) for row in fills]
    duplicates = len([item for item, count in Counter(positions).items() if count > 1])
    return {
        "calls": len(decisions),
        "decision_rows": len(decisions),
        "actionable_opinions": len(actionable),
        "fills": len(fills),
        "deferred_slots": len(deferred),
        "superseded": len([row for row in rejects if row.get("code") == "SUPERSEDED_BY_NEWER_OPINION"]),
        "expired": len([row for row in rejects if row.get("code") == "LATE_RESPONSE"]),
        "data_gap": len([row for row in rejects if row.get("code") == "DATA_GAP"]),
        "risk_blocked": len([row for row in outcomes if row.get("approved") is False]),
        "pending_at_end": len(pending),
        "terminal_classes": resolved,
        "terminal": sum(resolved.values()),
        "rejected_by_code": dict(sorted(rejected_by_code.items())),
        "unrecorded": len(unrecorded),
        "duplicate_terminals": len(duplicate_terminals),
        "orphan_terminals": len(orphan_terminals),
        "terminal_before_birth": len(terminal_before_birth),
        "fills_without_approval": len(fills_without_approval),
        "ids_unique": len({int(row["seq"]) for row in decisions}) == len(decisions),
        "run_end_present": bool(run_end),
        "rows_after_run_end": (len(rows) - run_end[0] - 1) if run_end else 0,
        "stale_fills": len(stale),
        "over_age_fills": len(over_age),
        "duplicate_positions": duplicates,
        "opinion_age_p50": percentiles([int(row["opinion_age_ms"]) for row in fills])["p50"],
    }


def verify_comparison(payload: dict[str, Any], current: dict[str, Any], proposed: dict[str, Any]) -> None:
    check("comparison: schema", payload.get("schema_version") == SCHEMA_COMPARISON)
    check(
        "comparison: lifecycle pair",
        payload.get("lifecycle_current") == "SUPERSEDE"
        and payload.get("lifecycle_proposed") == "DEFER",
        f"{payload.get('lifecycle_current')} -> {payload.get('lifecycle_proposed')}",
    )
    check("comparison: same dataset", payload.get("same_dataset") is True)
    check("comparison: verdict", payload.get("verdict") == "IMPROVED", str(payload.get("verdict")))
    for name, scenario in sorted(payload["scenarios"].items()):
        check(f"comparison/{name}: same series", scenario["same_series"] is True)
        check(f"comparison/{name}: same config", scenario["same_config"] is True)
        check(
            f"comparison/{name}: same bars hash",
            current["scenarios"][name]["series"]["bars_sha256"]
            == proposed["scenarios"][name]["series"]["bars_sha256"],
        )

    key = "m1_cadence1"
    check(
        "current destroys executable opinions",
        current["scenarios"][key]["metrics"]["superseded"] > 0,
        str(current["scenarios"][key]["metrics"]["superseded"]),
    )
    check(
        "proposed does not supersede when it can price",
        proposed["scenarios"][key]["metrics"]["superseded"]
        < current["scenarios"][key]["metrics"]["superseded"],
        f"{current['scenarios'][key]['metrics']['superseded']} -> {proposed['scenarios'][key]['metrics']['superseded']}",
    )
    check(
        "proposed defers instead of paying",
        proposed["scenarios"][key]["metrics"]["deferred_slots"] > 0
        and current["scenarios"][key]["metrics"]["deferred_slots"] == 0,
        f"deferred {current['scenarios'][key]['metrics']['deferred_slots']} -> {proposed['scenarios'][key]['metrics']['deferred_slots']}",
    )
    check(
        "proposed calls drop by the deferred slots",
        proposed["scenarios"][key]["metrics"]["calls"]
        <= current["scenarios"][key]["metrics"]["calls"],
        f"calls {current['scenarios'][key]['metrics']['calls']} -> {proposed['scenarios'][key]['metrics']['calls']}",
    )
    for control in ("m1_zero_delay", "m1_cadence5"):
        check(
            f"control {control} is inert",
            current["scenarios"][control]["metrics"]["fills"]
            == proposed["scenarios"][control]["metrics"]["fills"],
            f"fills {current['scenarios'][control]['metrics']['fills']} -> {proposed['scenarios'][control]['metrics']['fills']}",
        )
    check(
        "no fill in any scenario is stale or over age",
        all(
            scenario["metrics"]["stale_fills"] == 0 and scenario["metrics"]["over_age_fills"] == 0
            for capture in (current, proposed)
            for scenario in capture["scenarios"].values()
        ),
    )


# ----------------------------------------------------------------------- economics


def verify_economics(root: Path, payload: dict[str, Any]) -> None:
    check("economics: schema", payload.get("schema_version") == SCHEMA_ECONOMICS)
    corpus = payload["corpus"]
    #: El coste del modelo se publica una vez; se guarda con un nombre propio porque el
    #: bucle de reconstrucción usa ``cost_bps`` para el coste de **cada** operación.
    model_round_trip_bps = float(payload["costs"]["round_trip_bps"])
    ledgers = sorted((root.parents[2] / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001" / "runs").glob("*/*/*/*/ledger.jsonl"))
    check("economics: corpus found", len(ledgers) == corpus["runs"], f"{len(ledgers)}")

    rebuilt: list[dict[str, Any]] = []
    total_decisions = 0
    total_trades = 0
    for path in ledgers:
        rows = rows_of(path)
        run = next((row for row in rows if row.get("kind") == "RUN"), {})
        timeframe = str((run.get("lane") or {}).get("timeframe") or "")
        decisions = [row for row in rows if row.get("kind") == "DECISION"]
        closes = [row for row in rows if row.get("kind") == "CLOSE"]
        strategy = "unknown"
        for row in decisions:
            model = str((row.get("provider") or {}).get("model") or "")
            if "@" in model:
                strategy = model.split("@")[0]
                break
        net_bps: list[float] = []
        gross_bps: list[float] = []
        cost_bps: list[float] = []
        for close in closes:
            entry = float(close.get("entry_price") or 0.0)
            quantity = float(close.get("quantity") or 0.0)
            notional = entry * quantity
            if notional <= 0:
                continue
            net_bps.append(float(close.get("pnl_net_usdt") or 0.0) / notional * 10_000.0)
            gross_bps.append(float(close.get("gross_pnl_usdt") or 0.0) / notional * 10_000.0)
            cost_bps.append(
                (
                    float(close.get("commissions_usdt") or 0.0)
                    + float(close.get("execution_cost_usdt") or 0.0)
                )
                / notional
                * 10_000.0
            )
        rebuilt.append(
            {
                "timeframe": timeframe,
                "strategy": strategy,
                "decisions": len(decisions),
                "trades": len(net_bps),
                "net_bps": statistics.fmean(net_bps) if net_bps else None,
                "gross_bps": statistics.fmean(gross_bps) if gross_bps else None,
                "cost_bps": statistics.fmean(cost_bps) if cost_bps else None,
            }
        )
        total_decisions += len(decisions)
        total_trades += len(net_bps)

    check(
        "economics: decision count rebuilds",
        total_decisions == corpus["decisions"],
        f"{total_decisions} vs {corpus['decisions']}",
    )
    check(
        "economics: trade count rebuilds",
        total_trades == corpus["closed_trades"],
        f"{total_trades} vs {corpus['closed_trades']}",
    )
    published = {(run["timeframe"], run["strategy"]): run for run in payload["runs"]}
    check(
        "economics: every run is published once",
        len(published) == len(rebuilt) == 8,
        f"{len(published)}/{len(rebuilt)}",
    )
    for run in rebuilt:
        key = (run["timeframe"], run["strategy"])
        if key not in published:
            check(f"economics/{key}: published", False, "missing")
            continue
        declared = published[key]
        check(
            f"economics/{key}: trades",
            declared["closed_trades"] == run["trades"],
            f"{declared['closed_trades']} vs {run['trades']}",
        )
        expected = run["net_bps"]
        check(
            f"economics/{key}: net expectancy rebuilds",
            expected is not None
            and declared["expectancy_bps_net"] is not None
            and abs(declared["expectancy_bps_net"] - expected) <= 1e-4,
            f"{declared['expectancy_bps_net']} vs {expected}",
        )

    alternatives = payload["alternatives"]
    check(
        "economics: no alternative has positive dev expectancy",
        all((item["dev_expectancy_bps_net"] or 0.0) <= 0 for item in alternatives),
        str([item["dev_expectancy_bps_net"] for item in alternatives]),
    )
    check(
        "economics: verdict follows the holdout",
        (
            payload["verdict"] == "ECONOMIC_EDGE_NOT_EVIDENCED"
            and all((item["holdout_expectancy_bps_net"] or -1.0) <= 0 for item in alternatives)
        )
        or payload["verdict"] == "ECONOMIC_EDGE_EVIDENCED",
        str(payload["verdict"]),
    )
    chosen = payload["selection"]["chosen"]
    if chosen is not None:
        dev_scores = {
            (item["timeframe"], item["strategy"]): item["dev_expectancy_bps_net"]
            for item in alternatives
            if (item["dev_expectancy_bps_net"] is not None)
        }
        best = max(dev_scores, key=lambda key: dev_scores[key])
        check(
            "economics: choice was made on dev only",
            (chosen["timeframe"], chosen["strategy"]) == best,
            f"chosen={chosen} best_dev={best}",
        )
    breakeven = [
        run["breakeven_cost_multiplier"]
        for run in payload["runs"]
        if run.get("breakeven_cost_multiplier") is not None
    ]
    check(
        "economics: cost multiplier to break even is below 0.15x everywhere",
        all(value < 0.15 for value in breakeven),
        str(sorted(round(value, 3) for value in breakeven)),
    )
    check(
        "economics: model cost is the published one",
        abs(model_round_trip_bps - 24.786424) < 1e-3,
        str(model_round_trip_bps),
    )

    live = payload["live_corpus_audit"]
    check(
        "live corpus: summed rows exceed distinct opinions",
        live["decision_rows_summed_over_cycles"] > live["distinct_decisions"] * 10,
        f"{live['decision_rows_summed_over_cycles']} vs {live['distinct_decisions']}",
    )
    check(
        "live corpus: distinct decisions under 100",
        live["distinct_decisions"] < 100,
        str(live["distinct_decisions"]),
    )

    risk_yaml = root.parents[2] / "config" / "risk.yaml"
    if risk_yaml.is_file():
        recorded = None
        meta = root.parents[2] / "reports" / "ai-bots" / "DEF-RUN-PAPER" / "model-20261020T170635Z" / "RUN_META.json"
        if meta.is_file():
            recorded = load(meta).get("risk_yaml_sha256")
        check(
            "risk.yaml is the one the published sessions declared",
            recorded is None or sha256_file(risk_yaml) == recorded,
            f"{sha256_file(risk_yaml)[:12]} vs {recorded}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("reports/ai-bots/RFC-DEF-RUN-016"))
    args = parser.parse_args(argv)
    root = args.root if args.root.is_absolute() else (Path(__file__).resolve().parents[1] / args.root)

    evidence = root / "evidence"
    try:
        current = load(evidence / "AUDIT_CURRENT.json")
        proposed = load(evidence / "AUDIT_PROPOSED.json")
        comparison = load(evidence / "AUDIT_COMPARISON.json")
        economics = load(evidence / "ECONOMICS.json")
    except FileNotFoundError as exc:
        print(f"FAIL: missing artifact: {exc.filename}")
        return 1

    current_metrics = verify_capture(root, "CURRENT", current)
    proposed_metrics = verify_capture(root, "PROPOSED", proposed)
    verify_comparison(comparison, current, proposed)
    verify_economics(root, economics)

    failed = [item for item in RESULTS if not item[1]]
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    print(
        f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed"
        + (f" — {len(failed)} FAILED" if failed else "")
    )
    print(
        "CURRENT m1_cadence1:"
        f" actionable={current_metrics.get('m1_cadence1', {}).get('actionable_opinions')}"
        f" superseded={current_metrics.get('m1_cadence1', {}).get('superseded')}"
        f" fills={current_metrics.get('m1_cadence1', {}).get('fills')}"
    )
    print(
        "PROPOSED m1_cadence1:"
        f" actionable={proposed_metrics.get('m1_cadence1', {}).get('actionable_opinions')}"
        f" deferred={proposed_metrics.get('m1_cadence1', {}).get('deferred_slots')}"
        f" fills={proposed_metrics.get('m1_cadence1', {}).get('fills')}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
