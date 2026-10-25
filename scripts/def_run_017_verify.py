"""DEF-RUN-017 / WP-017-03 — verificador independiente.

Este fichero **no importa ``trading_bot``**. No comparte el módulo que produjo la
reconstrucción, ni el que escribió el ledger, ni el que generó el informe. Reimplementa:

* la cadena hash de cada ledger,
* la contabilidad de cada operación **por flujos de caja** (no por diferencia de precios),
* el ciclo de vida de cada opinión (una y solo una terminal),
* la conciliación de la fila ``RUN_END`` con los eventos,
* la aritmética de ``ECONOMIC_ATTRIBUTION.json`` y de ``PAIRED_DELTA.csv``.

Si algo falta, está alterado o no cuadra, el código de salida es distinto de cero. Un
``PASS`` que se pueda imprimir sin mirar los bytes no es una verificación.

Uso::

    python scripts/def_run_017_verify.py [--root .] [--json out.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCENARIOS = ("m1_cadence1", "m1_cadence5", "m1_hole", "m1_zero_delay", "m3_cadence1")
LABELS = ("CURRENT", "PROPOSED")
#: La evidencia vive en dos capas: ``data/`` está versionado y sobrevive a un checkout
#: limpio; ``reports/`` es la capa legible y el repositorio la excluye por política. El
#: verificador prefiere la primera y cae a la segunda, y publica cuál usó.
RFC16_ROOTS = (
    "data/def-run-016",
    "reports/ai-bots/RFC-DEF-RUN-016/evidence",
)
RFC17_ROOTS = (
    "data/def-run-017",
    "reports/ai-bots/RFC-DEF-RUN-017/evidence",
)
RFC16 = RFC16_ROOTS[-1]
RFC17 = RFC17_ROOTS[-1]
GENESIS = "0" * 64
Q = Decimal("0.00000001")
TOL = Decimal("0.00000002")
ROUNDING = Decimal("0.0000005")
TERMINAL_CLASSES = ("FILLED", "CLOSED", "BLOCKED_BY_RISK", "GATED", "REJECTED")
ACTIONABLE = ("OPEN_LONG", "OPEN_SHORT", "CLOSE")


class Blocked(Exception):
    """Falta un artefacto: no se puede verificar lo que no existe."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def number(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not money")
    if isinstance(value, (int, float)):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return str(value.quantize(Q))


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows_of(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def chain_report(path: Path) -> dict[str, Any]:
    """Reimplementación de la cadena: cada línea lleva el hash de la anterior."""
    prev = GENESIS
    for position, record in enumerate(rows_of(path), start=1):
        entry = record.get("entry")
        if not isinstance(entry, dict):
            return {"ok": False, "reason": f"NO_ENTRY_AT_{position}", "rows": position}
        if int(record.get("seq", -1)) != position:
            return {"ok": False, "reason": f"SEQ_GAP_AT_{position}", "rows": position}
        if str(record.get("prev_sha256")) != prev:
            return {"ok": False, "reason": f"BROKEN_LINK_AT_{position}", "rows": position}
        expected = hashlib.sha256(
            canonical(
                {
                    "seq": int(record["seq"]),
                    "prev_sha256": str(record["prev_sha256"]),
                    "entry": entry,
                }
            ).encode()
        ).hexdigest()
        if expected != str(record.get("sha256")):
            return {"ok": False, "reason": f"TAMPERED_LINE_{position}", "rows": position}
        prev = expected
    return {"ok": True, "reason": "INTACT", "rows": position if prev != GENESIS else 0}


def opinion_key(entry: dict[str, Any]) -> tuple[str, str] | None:
    """Identidad independiente: los bytes del gráfico y la acción. Sin hash propio."""
    chart = entry.get("chart") or {}
    decision = entry.get("decision") or {}
    if not chart.get("sha256") or not decision.get("action"):
        return None
    return (str(chart["sha256"]), str(decision["action"]))


def terminal_of(entry: dict[str, Any]) -> str | None:
    kind = entry.get("kind")
    if kind == "FILL":
        return "FILLED"
    if kind == "DECISION_OUTCOME":
        if str(entry.get("intent") or "") == "CLOSE":
            if entry.get("executed") is True:
                return "CLOSED"
            if entry.get("executed") is False:
                return "GATED"
            return None
        if entry.get("approved") is False:
            return "BLOCKED_BY_RISK"
        if entry.get("approved") is True and entry.get("executed") is False:
            return "GATED"
        return None
    if kind == "GUARD_REJECT" and entry.get("decision_seq") is not None:
        return "REJECTED"
    return None


def cash_flow_trade(fill: dict[str, Any], close: dict[str, Any]) -> dict[str, Any]:
    """Contabilidad por caja: lo que sale, lo que entra y lo que queda.

    Es deliberadamente otra formulación que la del módulo de auditoría (que resta precios).
    Si las dos coinciden, el PnL no depende de cómo se calculó.
    """
    quantity = number(fill["quantity"])
    entry_price = number(fill["entry_price"])
    exit_price = number(close["exit_price"])
    buy = str(fill["side"]).lower() == "buy"
    entry_fee = number(fill.get("entry_commission_usdt", 0))
    exit_fee = number(close.get("exit_commission_usdt", 0))
    #: En largo la caja de entrada sale (negativa) y la de salida entra; en corto, al revés.
    sign = -1 if buy else 1
    entry_cash = sign * quantity * entry_price - entry_fee
    exit_cash = -sign * quantity * exit_price - exit_fee
    realized = entry_cash + exit_cash
    return {
        "quantity": quantity,
        "entry_cash": entry_cash,
        "exit_cash": exit_cash,
        "realized": realized,
        "fees": entry_fee + exit_fee,
        "buy": buy,
        "gross": sign * quantity * (exit_price - entry_price),
        #: El coste de ejecución es lo que el precio pagado resta al PnL, y eso es
        #: ``referencia - pagado`` con el signo direccional (contrario al de la caja).
        "slippage": -sign
        * quantity
        * (
            (number(close.get("exit_reference_price", exit_price)) - exit_price)
            - (number(fill.get("reference_price", entry_price)) - entry_price)
        ),
    }


def resolve(root: Path, roots: Iterable[str], relative: str) -> Path | None:
    for base in roots:
        candidate = root / base / relative
        if candidate.exists():
            return candidate
    return None


def verify_ledger(root: Path, label: str, scenario: str) -> dict[str, Any]:
    """Verifica un ledger entero y devuelve sus números, no los del informe."""
    path = resolve(root, RFC16_ROOTS, f"ledgers/{label}/{scenario}.jsonl")
    if path is None:
        raise Blocked("MISSING_LEDGER", f"ledgers/{label}/{scenario}.jsonl")
    records = rows_of(path)
    entries = [record["entry"] for record in records]
    checks: list[dict[str, Any]] = []
    chain = chain_report(path)
    checks.append(
        {"code": f"CHAIN_{label}_{scenario}", "ok": chain["ok"], "detail": chain["reason"]}
    )
    kinds = [entry.get("kind") for entry in entries]
    checks.append(
        {
            "code": f"RUN_FIRST_{label}_{scenario}",
            "ok": kinds[0] == "RUN" and kinds.count("RUN") == 1,
            "detail": f"first={kinds[0]} runs={kinds.count('RUN')}",
        }
    )
    checks.append(
        {
            "code": f"RUN_END_LAST_{label}_{scenario}",
            "ok": kinds[-1] == "RUN_END" and kinds.count("RUN_END") == 1,
            "detail": f"last={kinds[-1]} count={kinds.count('RUN_END')}",
        }
    )
    run = entries[0] if kinds[0] == "RUN" else {}
    run_end = next((entry for entry in entries if entry.get("kind") == "RUN_END"), {})

    decisions: dict[int, dict[str, Any]] = {}
    for record, entry in zip(records, entries, strict=False):
        if entry.get("kind") == "DECISION" and entry.get("intent") in ACTIONABLE:
            decisions[int(record["seq"])] = entry
    terminals: dict[int, list[str]] = {}
    orphan = 0
    for entry in entries:
        cls = terminal_of(entry)
        if cls is None:
            continue
        seq = entry.get("decision_seq")
        if seq is None:
            continue
        if int(seq) not in decisions:
            orphan += 1
            continue
        terminals.setdefault(int(seq), []).append(cls)
    classes = {name: 0 for name in TERMINAL_CLASSES}
    unrecorded = 0
    duplicated = 0
    for seq in decisions:
        events = terminals.get(seq, [])
        if not events:
            unrecorded += 1
            continue
        if len(events) > 1:
            duplicated += 1
        classes[events[0]] += 1
    checks += [
        {
            "code": f"ONE_TERMINAL_PER_OPINION_{label}_{scenario}",
            "ok": unrecorded == 0 and duplicated == 0 and orphan == 0,
            "detail": f"unrecorded={unrecorded} duplicate={duplicated} orphan={orphan}",
        },
        {
            "code": f"TERMINAL_CLASSES_BALANCE_{label}_{scenario}",
            "ok": len(decisions) == sum(classes.values()),
            "detail": f"opinions={len(decisions)} terminals={sum(classes.values())}",
        },
    ]

    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    closes = [entry for entry in entries if entry.get("kind") == "CLOSE"]
    fill_positions = [str(fill.get("position_id")) for fill in fills]
    fill_decisions = [int(fill.get("decision_seq")) for fill in fills]
    close_positions = [str(close.get("position_id")) for close in closes]
    checks += [
        {
            "code": f"POSITION_IDS_UNIQUE_{label}_{scenario}",
            "ok": len(set(fill_positions)) == len(fill_positions),
            "detail": f"{len(fill_positions)} fills, {len(set(fill_positions))} positions",
        },
        {
            "code": f"ONE_FILL_PER_DECISION_{label}_{scenario}",
            "ok": len(set(fill_decisions)) == len(fill_decisions),
            "detail": f"{len(fill_decisions)} fills, {len(set(fill_decisions))} decisions",
        },
        {
            "code": f"ONE_CLOSE_PER_POSITION_{label}_{scenario}",
            "ok": len(set(close_positions)) == len(close_positions)
            and set(close_positions) <= set(fill_positions),
            "detail": f"{len(close_positions)} closes, {len(set(close_positions))} unique",
        },
    ]
    by_position = {str(fill["position_id"]): fill for fill in fills}
    missing_close = sorted(set(by_position) - set(close_positions))
    checks.append(
        {
            "code": f"NO_FILL_WITHOUT_CLOSE_{label}_{scenario}",
            "ok": not missing_close,
            "detail": f"{len(missing_close)} positions open at cutoff",
        }
    )

    realized = Decimal(0)
    fees = Decimal(0)
    slippage = Decimal(0)
    gross = Decimal(0)
    trades: list[dict[str, Any]] = []
    for close in closes:
        position = str(close["position_id"])
        fill = by_position.get(position)
        if fill is None:
            raise Blocked(
                "ORPHAN_CLOSE", f"{label}/{scenario}: CLOSE {position} has no FILL"
            )
        flow = cash_flow_trade(fill, close)
        declared = number(close.get("pnl_net_usdt", flow["realized"]))
        if (flow["realized"] - declared).copy_abs() > TOL:
            checks.append(
                {
                    "code": f"NET_FROM_CASH_MATCHES_{label}_{scenario}_{position[-4:]}",
                    "ok": False,
                    "detail": f"cash {money(flow['realized'])} vs ledger {money(declared)}",
                }
            )
        realized += flow["realized"]
        fees += flow["fees"]
        slippage += flow["slippage"]
        gross += flow["gross"]
        seq = int(fill["decision_seq"])
        trades.append(
            {
                "decision_seq": seq,
                "position_id": position,
                "opinion": opinion_key(decisions[seq]) if seq in decisions else None,
                "net": flow["realized"],
                "fees": flow["fees"],
                "slippage": flow["slippage"],
                "gross": flow["gross"],
                "exit_reason": close.get("exit_reason"),
            }
        )

    declared_net = number(run_end.get("pnl_realised_usdt", realized + 1))
    declared_costs = number(run_end.get("costs_realised_usdt", fees + slippage + 1))
    declared_fills = int(run_end.get("fills", -1))
    declared_closed = int(run_end.get("closed_trades", -1))
    declared_calls = int(run_end.get("calls", -1))
    decision_rows = sum(1 for entry in entries if entry.get("kind") == "DECISION")
    checks += [
        {
            "code": f"RUN_END_NET_RECONCILED_{label}_{scenario}",
            "ok": (realized - declared_net).copy_abs() <= TOL,
            "detail": f"cash-flow {money(realized)} vs RUN_END {money(declared_net)}",
        },
        {
            "code": f"RUN_END_COSTS_RECONCILED_{label}_{scenario}",
            "ok": (fees + slippage - declared_costs).copy_abs() <= TOL,
            "detail": f"{money(fees + slippage)} vs {money(declared_costs)}",
        },
        {
            "code": f"RUN_END_COUNTERS_MATCH_EVENTS_{label}_{scenario}",
            "ok": declared_fills == len(fills)
            and declared_closed == len(closes)
            and declared_calls == decision_rows,
            "detail": f"fills {declared_fills}/{len(fills)}, closed {declared_closed}/"
            f"{len(closes)}, calls {declared_calls}/{decision_rows}",
        },
    ]
    declared_opinions = run_end.get("opinion_accounting") or {}
    if declared_opinions:
        checks.append(
            {
                "code": f"OPINION_SELF_DECLARATION_MATCHES_{label}_{scenario}",
                #: ``unrecorded`` y ``duplicate_terminals`` son listas de ids, no contadores:
                #: el ledger declara *qué* opiniones fallan, y el verificador vuelve a contarlas.
                "ok": int(declared_opinions.get("generated", -1)) == len(decisions)
                and len(declared_opinions.get("unrecorded") or []) == unrecorded
                and len(declared_opinions.get("duplicate_terminals") or []) == duplicated
                and bool(declared_opinions.get("adds_up", False)),
                "detail": f"declared generated={declared_opinions.get('generated')} "
                f"unrecorded={len(declared_opinions.get('unrecorded') or [])} "
                f"duplicates={len(declared_opinions.get('duplicate_terminals') or [])} "
                f"adds_up={declared_opinions.get('adds_up')}",
            }
        )
    initial = number((run_end.get("accounting") or {}).get("initial_equity_usdt", 0))
    return {
        "label": label,
        "scenario": scenario,
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": len(entries),
        "fills": len(fills),
        "closes": len(closes),
        "decisions": decision_rows,
        "opinions": len(decisions),
        "classes": classes,
        "unrecorded": unrecorded,
        "duplicate_terminals": duplicated,
        "orphan_terminals": orphan,
        "net": money(realized),
        "fees": money(fees),
        "slippage": money(slippage),
        "gross": money(gross),
        "initial_equity": money(initial),
        "marked_equity": money(initial + realized),
        "run_end_marked_equity": run_end.get("marked_equity_usdt"),
        "trades": trades,
        "checks": checks,
        "max_opinion_age_ms": (run.get("lane") or {}).get("max_opinion_age_ms"),
    }


def _check(code: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"code": code, "ok": bool(ok), "detail": detail}


def _artifact(root: Path, manifest_dir: Path, key: str) -> Path | None:
    """Una clave de manifiesto puede ser relativa al repo o al paquete versionado."""
    for candidate in (root / key, manifest_dir / key):
        if candidate.is_file():
            return candidate
    return None


def _bootstrap_ci(values: list[float], *, seed: int, resamples: int) -> dict[str, Any]:
    """El protocolo del OOS congela el remuestreo, así que se puede repetir aquí.

    Reimplementación con la stdlib: el bloque es el día, la semilla ``17017`` y 2.000
    remuestras. Si el intervalo publicado no sale de estos deltas diarios, algo se tocó a
    mano después de ejecutar; ese es exactamente el fraude que un OOS debe poder detectar.
    """
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        draw = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(draw) / len(draw))
    means.sort()
    return {
        "mean": round(sum(values) / len(values), 6),
        "ci95": [
            round(means[int(0.025 * len(means))], 6),
            round(means[int(0.975 * len(means)) - 1], 6),
        ],
    }


def verify_oos(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verifica el bloque fuera de muestra desde sus propios deltas diarios.

    No importa ``trading_bot`` y no se cree ninguna cifra publicada: recalcula la aritmética
    de cada celda, reconstruye el delta diario pareado, repite el bootstrap congelado y
    vuelve a aplicar la regla de decisión escrita en el protocolo. Si el estado publicado no
    es el que la regla produce, el verificador falla — un ``EVIDENCED`` escrito a mano no
    pasa por aquí.
    """
    plan_path = resolve(root, RFC17_ROOTS, "oos/OOS_PLAN.json")
    if plan_path is None:
        raise Blocked("MISSING_OOS_PLAN", "oos/OOS_PLAN.json")
    results_path = resolve(root, RFC17_ROOTS, "oos/OOS_RESULTS.json")
    if results_path is None:
        raise Blocked("MISSING_OOS_RESULTS", "oos/OOS_RESULTS.json")
    runs_path = resolve(root, RFC17_ROOTS, "oos/OOS_RUNS_untouched_test.json")
    if runs_path is None:
        raise Blocked("MISSING_OOS_RUNS", "oos/OOS_RUNS_untouched_test.json")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    runs = json.loads(runs_path.read_text(encoding="utf-8"))["runs"]
    checks: list[dict[str, Any]] = []

    declared = plan.get("partitions", {}).get("untouched_test") or {}
    checks.append(
        _check(
            "OOS_PLAN_FROZEN",
            str(plan.get("status")) == "FROZEN_BEFORE_EXECUTION"
            and str(plan.get("executed_partition")) == "untouched_test",
            f"status={plan.get('status')} partition={plan.get('executed_partition')}",
        )
    )
    checks.append(
        _check(
            "OOS_PARTITION_AS_DECLARED",
            len(declared) == 3
            and declared.get("days") == 8
            and declared.get("first_day_utc") == "2021-02-09"
            and declared.get("last_day_utc") == "2021-02-16"
            and set(plan.get("symbols") or []) == {"UNI/USDT", "AAVE/USDT"}
            and set(plan.get("lifecycles") or []) == {"SUPERSEDE", "DEFER"}
            and 1.0 in (plan.get("cost_multipliers") or []),
            f"8 días 2021-02-09..16, 2 símbolos, 2 vidas, coste x1.0 — leído {declared}",
        )
    )

    declared_datasets = plan.get("datasets") or {}
    declared_ok = len(declared_datasets) == 2 and all(
        str(meta.get("path", "")).startswith("data/")
        and len(str(meta.get("sha256", ""))) == 64
        and int(meta.get("rows", 0)) > 0
        for meta in declared_datasets.values()
    )
    checks.append(
        _check(
            "OOS_DATASET_DECLARED",
            declared_ok,
            ", ".join(
                f"{symbol}: {meta.get('rows')} filas sha256:{str(meta.get('sha256'))[:12]}…"
                for symbol, meta in sorted(declared_datasets.items())
            )
            or "el plan no declara datasets",
        )
    )

    #: Los datasets viven versionados en ``data/quote-feed-1m``; en un sandbox que no los
    #: copia no se puede afirmar que sus bytes coinciden, así que no se emite el check. La
    #: decisión de emitirlo o no queda visible en ``oos.datasets_in_checkout``: un PASS sin
    #: este check es un PASS sobre el plan, no sobre los bytes del mercado.
    datasets_present = bool(declared_datasets) and all(
        (root / str(meta.get("path"))).is_file() for meta in declared_datasets.values()
    )
    if datasets_present:
        dataset_problems: list[str] = []
        for symbol, meta in sorted(declared_datasets.items()):
            path = root / str(meta.get("path"))
            if sha256_file(path) != meta.get("sha256"):
                dataset_problems.append(f"{symbol}: sha256 no coincide con el plan")
            elif len(json.loads(path.read_text(encoding="utf-8"))) != meta.get("rows"):
                dataset_problems.append(f"{symbol}: filas distintas de las declaradas")
        checks.append(
            _check(
                "OOS_DATASET_BYTES_MATCH",
                not dataset_problems,
                "; ".join(dataset_problems) or "sha256 y filas de los dos datasets coinciden",
            )
        )

    checks.append(
        _check(
            "OOS_PLAN_HASH_ANCHORED",
            str(results.get("plan_sha256")) == sha256_file(plan_path),
            f"results.plan_sha256={str(results.get('plan_sha256'))[:16]}… "
            f"vs sha256(plan)={sha256_file(plan_path)[:16]}…",
        )
    )

    cells: dict[str, dict[str, Any]] = results.get("cells") or {}
    expected_keys = {
        f"{symbol}|{lifecycle}|1.0"
        for symbol in ("UNI/USDT", "AAVE/USDT")
        for lifecycle in ("DEFER", "SUPERSEDE")
    }
    checks.append(
        _check(
            "OOS_GRID_COMPLETE",
            set(cells) == expected_keys
            and all(int(cell.get("days", 0)) == 8 for cell in cells.values())
            and all(len(cell.get("per_day_net") or []) == 8 for cell in cells.values())
            and len(runs) == 32,
            f"celdas={sorted(cells)} días={sorted({c.get('days') for c in cells.values()})} "
            f"runs={len(runs)}",
        )
    )

    #: La comisión es la única parte del coste que **no** está dentro de los precios de
    #: relleno; el slippage sí, y por eso ``bruto - costes`` no es el neto (sería contarlo dos
    #: veces, el error que RFC-017 documenta en `ECONOMIC_ATTRIBUTION.md`). La identidad que
    #: se puede comprobar con lo publicado es: ``bruto - neto == comisiones``, y las comisiones
    #: son 10 bps por lado sobre 500 USDT de stake => 1,0 USDT por ida y vuelta.
    commission_per_round_trip = Decimal("1.0")
    arithmetic: list[str] = []
    for key, cell in sorted(cells.items()):
        total = sum((number(value) for value in cell.get("per_day_net") or []), Decimal(0))
        net = number(cell.get("net_pnl_usdt", "NaN"))
        gross = number(cell.get("gross_pnl_usdt", "NaN"))
        costs = number(cell.get("costs_usdt", "NaN"))
        trades = int(cell.get("closed_trades", -1))
        if (total - net).copy_abs() > TOL * 100:
            arithmetic.append(f"{key}: suma diaria {money(total)} != neto {money(net)}")
        expected_commission = commission_per_round_trip * trades
        if (gross - net).copy_abs() - expected_commission > TOL * 100:
            arithmetic.append(
                f"{key}: bruto-neto={money(gross - net)} no son {money(expected_commission)} "
                f"de comisiones para {trades} operaciones"
            )
        if costs + TOL * 100 < expected_commission:
            arithmetic.append(
                f"{key}: costes {money(costs)} menores que la comisión {money(expected_commission)}"
            )
        if int(cell.get("fills", -1)) != trades:
            arithmetic.append(f"{key}: fills != cerradas")
        if int(cell.get("chain_failures", -1)) != 0:
            arithmetic.append(f"{key}: chain_failures={cell.get('chain_failures')}")
    checks.append(
        _check(
            "OOS_CELL_ARITHMETIC",
            not arithmetic,
            "; ".join(arithmetic)
            or f"{len(cells)} celdas: neto = suma diaria y bruto - neto = comisiones "
            "(el slippage ya está dentro del bruto, no se resta otra vez)",
        )
    )

    deltas: dict[str, dict[str, Any]] = results.get("paired_day_deltas") or {}
    delta_problems: list[str] = []
    bootstrap_problems: list[str] = []
    for symbol in ("UNI/USDT", "AAVE/USDT"):
        defer = cells.get(f"{symbol}|DEFER|1.0") or {}
        sup = cells.get(f"{symbol}|SUPERSEDE|1.0") or {}
        published = (deltas.get(symbol) or {}).get("per_day_usdt") or []
        try:
            expected = [
                float(number(a) - number(b))
                for a, b in zip(
                    defer.get("per_day_net") or [], sup.get("per_day_net") or [], strict=False
                )
            ]
        except InvalidOperation:
            expected = []
        if len(expected) != len(published) or any(
            abs(round(a, 8) - b) > 1e-9 for a, b in zip(expected, published, strict=True)
        ):
            delta_problems.append(f"{symbol}: delta diario publicado no es DEFER-SUPERSEDE")
            continue
        if int((deltas.get(symbol) or {}).get("samples", 0)) != len(published):
            delta_problems.append(f"{symbol}: samples != días")
        recomputed = _bootstrap_ci(
            published,
            seed=int((deltas.get(symbol) or {}).get("seed", -1)),
            resamples=int((deltas.get(symbol) or {}).get("resamples", 0)),
        )
        claimed = deltas.get(symbol) or {}
        ci = claimed.get("ci95") or [None, None]
        if (
            abs(recomputed["mean"] - float(claimed.get("mean"))) > 2e-6
            or abs(recomputed["ci95"][0] - float(ci[0])) > 2e-6
            or abs(recomputed["ci95"][1] - float(ci[1])) > 2e-6
        ):
            bootstrap_problems.append(
                f"{symbol}: publicado mean={claimed.get('mean')} ci={ci} vs "
                f"recalculado mean={recomputed['mean']} ci={recomputed['ci95']}"
            )
        counts = (
            sum(1 for value in published if value > 0),
            sum(1 for value in published if value < 0),
            sum(1 for value in published if value == 0),
        )
        if counts != (
            claimed.get("days_positive"),
            claimed.get("days_negative"),
            claimed.get("days_flat"),
        ):
            delta_problems.append(f"{symbol}: conteo de días no cuadra {counts}")
    checks.append(
        _check(
            "OOS_PAIRED_DELTA_ARITHMETIC",
            not delta_problems,
            "; ".join(delta_problems) or "delta diario = neto DEFER - neto SUPERSEDE, día a día",
        )
    )
    checks.append(
        _check(
            "OOS_BOOTSTRAP_REPRODUCED",
            not bootstrap_problems,
            "; ".join(bootstrap_problems)
            or "bootstrap por bloques (día, semilla 17017, 2.000 remuestras) reproducido",
        )
    )

    lifecycle_problems: list[str] = []
    for symbol in ("UNI/USDT", "AAVE/USDT"):
        deferred = int((cells.get(f"{symbol}|DEFER|1.0") or {}).get("deferred_slots", -1))
        superseded = int((cells.get(f"{symbol}|SUPERSEDE|1.0") or {}).get("deferred_slots", -1))
        if deferred <= 0:
            lifecycle_problems.append(f"{symbol}: DEFER aplazó {deferred} opiniones")
        if superseded != 0:
            lifecycle_problems.append(f"{symbol}: SUPERSEDE aplazó {superseded} opiniones")
    defer_runs = [run for run in runs if run.get("lifecycle") == "DEFER"]
    sup_runs = [run for run in runs if run.get("lifecycle") == "SUPERSEDE"]
    if not any(int(run.get("deferred_slots", 0)) > 0 for run in defer_runs):
        lifecycle_problems.append("ningún day-run DEFER registra aplazamientos")
    if sum(int(run.get("superseded", 0)) for run in sup_runs) == 0:
        lifecycle_problems.append("ningún day-run SUPERSEDE registra sustituciones")
    checks.append(
        _check(
            "OOS_LIFECYCLE_ACTUALLY_DIFFERS",
            not lifecycle_problems,
            "; ".join(lifecycle_problems)
            or "DEFER aplaza y SUPERSEDE sustituye: las dos ramas no son la misma ejecución",
        )
    )

    #: Una celda que falta no puede tumbar al verificador: se declara irrecomputable y el
    #: check falla. Un verificador que revienta con evidencia mala es un verificador que no
    #: distingue "no lo sé" de "está bien".
    symbols = ("UNI/USDT", "AAVE/USDT")
    try:
        net_defer = {
            s: number((cells.get(f"{s}|DEFER|1.0") or {}).get("net_pnl_usdt", "NaN"))
            for s in symbols
        }
        net_sup = {
            s: number((cells.get(f"{s}|SUPERSEDE|1.0") or {}).get("net_pnl_usdt", "NaN"))
            for s in symbols
        }
        expectancy = {
            s: number((cells.get(f"{s}|DEFER|1.0") or {}).get("expectancy_usdt", "NaN"))
            for s in symbols
        }
        better = all(net_defer[s] > net_sup[s] for s in symbols)
        worse = all(net_defer[s] < net_sup[s] for s in symbols)
        separates = all(
            (deltas.get(s) or {}).get("ci95") is not None
            and (
                float((deltas[s]["ci95"])[1]) < 0.0
                or float((deltas[s]["ci95"])[0]) > 0.0
            )
            for s in symbols
        )
        positive_expectancy = all(expectancy[s] > 0 for s in symbols)
        if better and separates and positive_expectancy:
            recomputed_status = "EVIDENCED"
        elif worse and separates:
            recomputed_status = "NEGATIVE"
        elif not runs:
            recomputed_status = "INCONCLUSIVE"
        else:
            recomputed_status = "NOT_EVIDENCED"
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        better = worse = separates = positive_expectancy = None
        recomputed_status = f"UNRECOMPUTABLE ({type(exc).__name__})"
    published_status = str((results.get("decision") or {}).get("economic_status"))
    checks.append(
        _check(
            "OOS_DECISION_RULE_REAPPLIED",
            published_status == recomputed_status,
            f"publicado={published_status} recalculado={recomputed_status} "
            f"(mejor_en_ambos={better} peor_en_ambos={worse} ic_sin_cero={separates} "
            f"expectancy_positiva={positive_expectancy})",
        )
    )
    checks.append(
        _check(
            "OOS_DECISION_NOT_A_LIVE_AUTHORISATION",
            published_status in ("EVIDENCED", "NEGATIVE", "NOT_EVIDENCED", "INCONCLUSIVE"),
            f"estado={published_status}: un OOS de 8 días no autoriza LIVE en ningún caso",
        )
    )

    chain_ok = all(bool((run.get("chain") or {}).get("ok")) for run in runs)
    checks.append(
        _check(
            "OOS_RUN_CHAINS_RECORDED",
            chain_ok and int(results.get("chain_failures", -1)) == 0,
            f"chain_failures={results.get('chain_failures')} "
            f"runs_con_cadena_rota={[r.get('ledger') for r in runs if not (r.get('chain') or {}).get('ok')][:3]}",
        )
    )

    ledger_paths = [root / str(run.get("ledger")) for run in runs]
    ledgers_present = bool(ledger_paths) and all(path.is_file() for path in ledger_paths)
    if ledgers_present:
        mismatched = [
            run.get("ledger")
            for run in runs
            if sha256_file(root / str(run.get("ledger"))) != str(run.get("ledger_sha256"))
        ]
        checks.append(
            _check(
                "OOS_LEDGER_BYTES_MATCH_RECORD",
                not mismatched,
                f"{len(runs) - len(mismatched)}/{len(runs)} ledgers con sha256 registrado: "
                f"{mismatched[:2]}",
            )
        )

    summary = {
        "partition": results.get("partition"),
        "cells": {
            key: {
                "net_pnl_usdt": money(number(cell.get("net_pnl_usdt", "NaN"))),
                "closed_trades": cell.get("closed_trades"),
                "deferred_slots": cell.get("deferred_slots"),
            }
            for key, cell in sorted(cells.items())
        },
        "economic_status": published_status,
        "economic_status_recomputed": recomputed_status,
        "runs": len(runs),
        "datasets_verified_in_checkout": datasets_present,
        "ledgers_in_checkout": ledgers_present,
    }
    return checks, summary


def verify_oos_stress(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Verifica el estrés de coste x2 si existe, sin dejarlo tocar la decisión primaria.

    Se emite cuando el fichero está: en un paquete anterior al estrés, su ausencia no puede
    contarse como PASS ni como FAIL, así que no se emite check y el resumen lo declara.
    """
    path = resolve(root, RFC17_ROOTS, "oos/OOS_STRESS_COST2.json")
    if path is None:
        return [], None
    stress = json.loads(path.read_text(encoding="utf-8"))
    cells: dict[str, dict[str, Any]] = stress.get("cells") or {}
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "OOS_STRESS_NOT_DECISIVE",
            stress.get("used_for_decision") is False
            and float(stress.get("cost_multiplier", -1)) == 2.0,
            f"used_for_decision={stress.get('used_for_decision')} "
            f"multiplicador={stress.get('cost_multiplier')}",
        )
    )
    problems: list[str] = []
    for key, cell in sorted(cells.items()):
        total = sum((number(value) for value in cell.get("per_day_net") or []), Decimal(0))
        net = number(cell.get("net_pnl_usdt", "NaN"))
        trades = int(cell.get("closed_trades", -1))
        if (total - net).copy_abs() > TOL * 100:
            problems.append(f"{key}: suma diaria {money(total)} != neto {money(net)}")
        if int(cell.get("fills", -1)) != trades:
            problems.append(f"{key}: fills != cerradas")
        if number(cell.get("costs_usdt", "NaN")) < Decimal(trades) - TOL * 100:
            problems.append(f"{key}: costes por debajo de las comisiones")
        if int(cell.get("chain_failures", -1)) != 0:
            problems.append(f"{key}: chain_failures={cell.get('chain_failures')}")
        if key.endswith("|DEFER|2.0") and int(cell.get("deferred_slots", 0)) <= 0:
            problems.append(f"{key}: la rama DEFER no aplazó nada bajo estrés")
    checks.append(
        _check(
            "OOS_STRESS_ARITHMETIC",
            not problems,
            "; ".join(problems) or f"{len(cells)} celdas de estrés cuadran",
        )
    )
    published = str(stress.get("stress_status"))
    recomputed = "UNRECOMPUTABLE"
    try:
        symbols = sorted((stress.get("paired_day_deltas") or {}).keys())
        better = all(
            number(cells[f"{s}|DEFER|2.0"]["net_pnl_usdt"])
            > number(cells[f"{s}|SUPERSEDE|2.0"]["net_pnl_usdt"])
            for s in symbols
        )
        worse = all(
            number(cells[f"{s}|DEFER|2.0"]["net_pnl_usdt"])
            < number(cells[f"{s}|SUPERSEDE|2.0"]["net_pnl_usdt"])
            for s in symbols
        )
        separates = all(
            (stress["paired_day_deltas"][s].get("ci95") or [None, None])[1] is not None
            and (
                float(stress["paired_day_deltas"][s]["ci95"][1]) < 0.0
                or float(stress["paired_day_deltas"][s]["ci95"][0]) > 0.0
            )
            for s in symbols
        )
        positive = all(
            number(cells[f"{s}|DEFER|2.0"].get("expectancy_usdt", "NaN")) > 0 for s in symbols
        )
        recomputed = (
            "EVIDENCED"
            if (better and separates and positive)
            else "NEGATIVE"
            if (worse and separates)
            else "NOT_EVIDENCED"
        )
    except (KeyError, InvalidOperation, TypeError, ValueError):
        recomputed = "UNRECOMPUTABLE"
    checks.append(
        _check(
            "OOS_STRESS_STATUS_REAPPLIED",
            published == recomputed,
            f"publicado={published} recalculado={recomputed}",
        )
    )
    summary = {
        "cost_multiplier": stress.get("cost_multiplier"),
        "runs": stress.get("runs"),
        "used_for_decision": stress.get("used_for_decision"),
        "stress_status": published,
        "stress_status_recomputed": recomputed,
        "cells": {
            key: {
                "net_pnl_usdt": money(number(cell.get("net_pnl_usdt", "NaN"))),
                "closed_trades": cell.get("closed_trades"),
                "deferred_slots": cell.get("deferred_slots"),
            }
            for key, cell in sorted(cells.items())
        },
    }
    return checks, summary


def _csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Blocked("MISSING_CSV", str(path))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def verify(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    runs: dict[str, dict[str, dict[str, Any]]] = {"CURRENT": {}, "PROPOSED": {}}
    for label in LABELS:
        for scenario in SCENARIOS:
            result = verify_ledger(root, label, scenario)
            runs[label][scenario] = result
            checks.extend(result["checks"])

    attribution_path = resolve(root, RFC17_ROOTS, "ECONOMIC_ATTRIBUTION.json")
    if attribution_path is None:
        raise Blocked("MISSING_ATTRIBUTION", "ECONOMIC_ATTRIBUTION.json")
    attribution = json.loads(attribution_path.read_text(encoding="utf-8"))

    totals_reported = attribution.get("totals") or {}
    base_net = sum((number(run["net"]) for run in runs["CURRENT"].values()), Decimal(0))
    cand_net = sum((number(run["net"]) for run in runs["PROPOSED"].values()), Decimal(0))
    checks += [
        _check(
            "ATTRIBUTION_BASELINE_NET_MATCHES",
            (base_net - number(totals_reported.get("baseline_net_usdt", "NaN"))).copy_abs()
            <= TOL * 100,
            f"cash-flow {money(base_net)} vs report {totals_reported.get('baseline_net_usdt')}",
        ),
        _check(
            "ATTRIBUTION_CANDIDATE_NET_MATCHES",
            (cand_net - number(totals_reported.get("candidate_net_usdt", "NaN"))).copy_abs()
            <= TOL * 100,
            f"cash-flow {money(cand_net)} vs report {totals_reported.get('candidate_net_usdt')}",
        ),
        _check(
            "ATTRIBUTION_DELTA_MATCHES",
            (
                (cand_net - base_net)
                - number(totals_reported.get("delta_net_usdt", "NaN"))
            ).copy_abs()
            <= TOL * 100,
            f"cash-flow {money(cand_net - base_net)} vs report "
            f"{totals_reported.get('delta_net_usdt')}",
        ),
    ]

    # -- emparejamiento, con claves propias (sha del gráfico + acción) -----------------
    def index(label: str) -> tuple[dict[tuple[str, str], Decimal], set[tuple[str, str]]]:
        table: dict[tuple[str, str], Decimal] = {}
        duplicated: set[tuple[str, str]] = set()
        for scenario in SCENARIOS:
            for trade in runs[label][scenario]["trades"]:
                key = trade["opinion"]
                if key is None:
                    continue
                scoped = (scenario, key)
                if scoped in table:
                    duplicated.add(scoped)
                table[scoped] = trade["net"]
        return table, duplicated

    base_index, base_dup = index("CURRENT")
    cand_index, cand_dup = index("PROPOSED")
    ambiguous = base_dup | cand_dup
    matched_delta = Decimal(0)
    matched = baseline_only = candidate_only = 0
    for key in set(base_index) | set(cand_index):
        if key in ambiguous:
            continue
        if key in base_index and key in cand_index:
            matched += 1
            matched_delta += cand_index[key] - base_index[key]
        elif key in base_index:
            baseline_only += 1
        else:
            candidate_only += 1
    checks += [
        _check(
            "PAIR_COUNTS_MATCH_REPORT",
            matched == int(totals_reported.get("matched_pairs", -1))
            and baseline_only == int(totals_reported.get("baseline_only", -1))
            and candidate_only == int(totals_reported.get("candidate_only", -1))
            and len(ambiguous) == int(totals_reported.get("ambiguous", -1)),
            f"verifier matched={matched} baseline_only={baseline_only} "
            f"candidate_only={candidate_only} ambiguous={len(ambiguous)} vs report "
            f"{totals_reported.get('matched_pairs')}/"
            f"{totals_reported.get('baseline_only')}/"
            f"{totals_reported.get('candidate_only')}/"
            f"{totals_reported.get('ambiguous')}",
        ),
        _check(
            "MATCHED_PAIRS_DELTA_ZERO_OR_REPORTED",
            (matched_delta - number(totals_reported.get("delta_from_matched_pairs_usdt", "NaN")))
            .copy_abs()
            <= TOL * 100,
            f"verifier {money(matched_delta)} vs report "
            f"{totals_reported.get('delta_from_matched_pairs_usdt')}",
        ),
    ]

    # -- CSV de operaciones y de emparejamiento -----------------------------------
    trade_csv = resolve(root, RFC17_ROOTS, "TRADE_LEDGER.csv")
    if trade_csv is None:
        raise Blocked("MISSING_CSV", "TRADE_LEDGER.csv")
    trade_rows = _csv(trade_csv)
    expected_trades = sum(run["closes"] for run in runs["CURRENT"].values()) + sum(
        run["closes"] for run in runs["PROPOSED"].values()
    )
    by_label: dict[str, Decimal] = {"baseline": Decimal(0), "candidate": Decimal(0)}
    for row in trade_rows:
        by_label[row["label"]] += number(row["realized_pnl_quote"])
    checks += [
        _check(
            "TRADE_LEDGER_COVERS_EVERY_CLOSE",
            len(trade_rows) == expected_trades,
            f"{len(trade_rows)} csv rows vs {expected_trades} closes in the ledgers",
        ),
        _check(
            "TRADE_LEDGER_NET_MATCHES_LEDGERS",
            (by_label["baseline"] - base_net).copy_abs() <= TOL * 100
            and (by_label["candidate"] - cand_net).copy_abs() <= TOL * 100,
            f"csv {money(by_label['baseline'])}/{money(by_label['candidate'])} vs "
            f"ledgers {money(base_net)}/{money(cand_net)}",
        ),
    ]
    pair_csv = resolve(root, RFC17_ROOTS, "PAIRED_DELTA.csv")
    if pair_csv is None:
        raise Blocked("MISSING_CSV", "PAIRED_DELTA.csv")
    pair_rows = _csv(pair_csv)
    pair_delta = sum((number(row["realized_delta"]) for row in pair_rows), Decimal(0))
    pair_status = {
        status: sum(1 for row in pair_rows if row["match_status"] == status)
        for status in ("MATCHED", "BASELINE_ONLY", "CANDIDATE_ONLY", "AMBIGUOUS")
    }
    checks += [
        _check(
            "PAIRED_DELTA_RECONCILES_TO_DELTA",
            (pair_delta - (cand_net - base_net)).copy_abs() <= TOL * 100,
            f"pairs {money(pair_delta)} vs delta {money(cand_net - base_net)}",
        ),
        _check(
            "PAIRED_DELTA_STATUS_COUNTS",
            pair_status["MATCHED"] == matched
            and pair_status["BASELINE_ONLY"] == baseline_only
            and pair_status["CANDIDATE_ONLY"] == candidate_only,
            f"csv {pair_status} vs verifier {matched}/{baseline_only}/{candidate_only}",
        ),
    ]

    # -- anclas externas: los manifiestos -------------------------------------------
    rfc16_manifest = resolve(root, RFC16_ROOTS, "ARTIFACT_MANIFEST.json")
    if rfc16_manifest is not None:
        declared = json.loads(rfc16_manifest.read_text(encoding="utf-8")).get("evidence") or {}
        mismatched = [
            path
            for path, expected in declared.items()
            if _artifact(root, rfc16_manifest.parent, path) is None
            or sha256_file(_artifact(root, rfc16_manifest.parent, path))
            != expected.get("sha256")
        ]
        checks.append(
            _check(
                "RFC16_EVIDENCE_HASHES_MATCH",
                not mismatched,
                f"{len(declared) - len(mismatched)}/{len(declared)} artefactos coinciden: "
                f"{mismatched[:3]}",
            )
        )
    else:
        raise Blocked("MISSING_RFC16_MANIFEST", str(rfc16_manifest))

    rfc17_manifest = resolve(root, RFC17_ROOTS, "ARTIFACT_MANIFEST.json")
    if rfc17_manifest is not None:
        declared = json.loads(rfc17_manifest.read_text(encoding="utf-8")).get("artifacts") or {}
        mismatched = [
            path
            for path, expected in declared.items()
            if _artifact(root, rfc17_manifest.parent, path) is None
            or sha256_file(_artifact(root, rfc17_manifest.parent, path))
            != expected.get("sha256")
        ]
        checks.append(
            _check(
                "RFC17_ARTIFACT_HASHES_MATCH",
                not mismatched,
                f"{len(declared) - len(mismatched)}/{len(declared)} artefactos coinciden: "
                f"{mismatched[:3]}",
            )
        )

    report = resolve(root, RFC17_ROOTS, "RUN_REPORT.json")
    if report is not None:
        declared = json.loads(report.read_text(encoding="utf-8"))
        claimed = declared.get("economics") or {}
        checks += [
            _check(
                "RUN_REPORT_NUMBERS_MATCH",
                (
                    number(claimed.get("baseline_net_usdt", "NaN")) - base_net
                ).copy_abs()
                <= TOL * 100
                and (number(claimed.get("candidate_net_usdt", "NaN")) - cand_net).copy_abs()
                <= TOL * 100,
                f"informe {claimed.get('baseline_net_usdt')}/"
                f"{claimed.get('candidate_net_usdt')} vs reconstruido "
                f"{money(base_net)}/{money(cand_net)}",
            ),
            _check(
                "RUN_REPORT_FALSE_SUCCESS_ZERO",
                int(declared.get("false_success", -1)) == 0,
                f"false_success={declared.get('false_success')}",
            ),
            _check(
                "RUN_REPORT_NO_PASS_WHEN_DATALESS",
                not (
                    declared.get("technical_status") == "PASS"
                    and any(not check["ok"] for check in checks)
                ),
                "un informe PASS sobre checks fallidos es un falso éxito",
            ),
        ]

    oos_checks, oos_summary = verify_oos(root)
    checks.extend(oos_checks)
    stress_checks, stress_summary = verify_oos_stress(root)
    checks.extend(stress_checks)

    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": "DEF_RUN_017_VERIFICATION_V1",
        "verifier": "scripts/def_run_017_verify.py",
        "imports_trading_bot": False,
        "checks": len(checks),
        "check_codes": [check["code"] for check in checks],
        "failed": len(failed),
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "evidence_roots": {
            "attribution": str(attribution_path),
            "ledgers": str(runs["CURRENT"][SCENARIOS[0]]["path"]),
            "manifest": str(rfc16_manifest) if rfc16_manifest else None,
        },
        "totals": {
            "baseline_net_usdt": money(base_net),
            "candidate_net_usdt": money(cand_net),
            "delta_net_usdt": money(cand_net - base_net),
            "matched_pairs": matched,
            "baseline_only": baseline_only,
            "candidate_only": candidate_only,
            "ambiguous": len(ambiguous),
        },
        "ledgers": {label: runs[label] for label in LABELS},
        "oos": oos_summary,
        "oos_stress": stress_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--json",
        default="reports/ai-bots/RFC-DEF-RUN-017/evidence/INDEPENDENT_VERIFICATION.json",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        report = verify(root)
    except Blocked as exc:
        print(f"BLOCKED {exc.code}: {exc.detail}")
        return 2
    target = Path(args.json)
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"status={report['status']} checks={report['checks']} failed={report['failed']}")
    for check in report["failed_checks"]:
        print(f"  FAIL {check['code']}: {check['detail']}")
    print(
        f"delta={report['totals']['delta_net_usdt']} "
        f"matched={report['totals']['matched_pairs']} "
        f"base_only={report['totals']['baseline_only']} "
        f"cand_only={report['totals']['candidate_only']}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
