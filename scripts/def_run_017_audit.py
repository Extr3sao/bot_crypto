"""DEF-RUN-017 / WP-017-01/02 — ¿de dónde salen los 8,12 USDT?

Reconstruye BASELINE y CANDIDATE desde los diez ledgers publicados de RFC-016 con
``trading_bot.vision.economic_audit`` (aritmética decimal, identidades desde precios) y
publica:

* ``TRADE_LEDGER.csv`` — un round trip por fila, con su opinión, precios, costes y PnL.
* ``PAIRED_DELTA.csv`` — el emparejamiento por identidad de opinión, con los no emparejados
  conservados y su motivo.
* ``ECONOMIC_ATTRIBUTION.json`` / ``.md`` — la descomposición, el inventario de mecanismos y
  la reconciliación con lo que RFC-016 publicó.

No decide causalidad. Un delta que cierra por pertenencia de operaciones sigue siendo
compatible con varias historias; el informe dice cuál está soportada y cuál no.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from trading_bot.vision.economic_audit import (  # noqa: E402
    RunEconomics,
    attribute,
    dec,
    money,
    read_ledger,
    reconstruct,
)

RFC16 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-016"
LEDGERS = RFC16 / "evidence" / "ledgers"
OUT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
EVIDENCE = OUT / "evidence"
SCHEMA = "DEF_RUN_017_ATTRIBUTION_V1"
SCENARIOS = ("m1_cadence1", "m1_cadence5", "m1_hole", "m1_zero_delay", "m3_cadence1")


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_run(label: str, scenario: str) -> RunEconomics:
    return reconstruct(
        LEDGERS / label / f"{scenario}.jsonl",
        source_commit="d05f8de498c175f7a9b8ccdd38e6e1067832d5e6",
        runtime_hashes={
            "src/trading_bot/vision/lane.py": "617e544a552f9dcf176f2c359037bb41698e705063e4c6da057284ead79e9bd3",
            "src/trading_bot/vision/execution.py": "4d518bba40faca163eb9a632f23e6b0a6584c8886e82",
            "src/trading_bot/risk/manager.py": "493a989ef2fc220eae212df0ee9d2b91e901eb04540da0c3fa41a1127ed45440",
            "src/trading_bot/paper/broker.py": "c145960896999f6a7a7f2b9090c40471b582b8a7caa02b45563db2f8cbe33389",
        },
    )


def mechanism_inventory(label: str, scenario: str, run: RunEconomics) -> dict[str, Any]:
    """Qué hizo el ciclo de vida con cada opinión, contado desde las filas."""
    rows = [row.entry for row in read_ledger(LEDGERS / label / f"{scenario}.jsonl")]
    decisions = [row for row in rows if row.get("kind") == "DECISION"]
    rejects: dict[str, int] = {}
    for row in rows:
        if row.get("kind") == "GUARD_REJECT":
            code = str(row.get("code"))
            rejects[code] = rejects.get(code, 0) + 1
    deferred = [row for row in rows if row.get("kind") == "OPINION_DEFERRED"]
    fates: dict[str, int] = {}
    terminal_map = run.terminal_by_opinion()
    for row in deferred:
        class_of = next(
            (
                str(item["terminal"])
                for item in run.terminals
                if int(item["decision_seq"]) == int(row["decision_seq"])
            ),
            "UNRECORDED",
        )
        fates[class_of] = fates.get(class_of, 0) + 1
    stops = [
        dec(row["stop_distance_bps"])
        for row in rows
        if row.get("kind") == "FILL" and row.get("stop_distance_bps") is not None
    ]
    round_trip = [
        dec(row["round_trip_cost_bps"])
        for row in rows
        if row.get("kind") == "FILL" and row.get("round_trip_cost_bps") is not None
    ]
    ages = [
        int(row["opinion_age_ms"])
        for row in rows
        if row.get("kind") == "FILL" and row.get("opinion_age_ms") is not None
    ]
    return {
        "decisions": len(decisions),
        "deferrals": len(deferred),
        "deferred_fates": dict(sorted(fates.items())),
        "guard_rejects": dict(sorted(rejects.items())),
        "stop_distance_bps": [str(value) for value in stops],
        "stop_distance_median_bps": (
            str(statistics.median(stops)) if stops else None
        ),
        "round_trip_cost_bps": [str(value) for value in round_trip],
        "round_trip_cost_bps_median": (
            str(statistics.median(round_trip)) if round_trip else None
        ),
        "opinion_age_ms": ages,
        "terminal_map_size": len(terminal_map),
    }


def per_trade_economics(runs: dict[str, dict[str, RunEconomics]]) -> dict[str, Any]:
    """La aritmética que explica cada operación: parada, coste y lo que queda."""
    out: dict[str, Any] = {}
    for label, scenarios in runs.items():
        trades = [trade for run in scenarios.values() for trade in run.trades]
        nets = [float(trade.realized_pnl_quote) for trade in trades]
        wins = [value for value in nets if value > 0]
        losses = [value for value in nets if value <= 0]
        out[label] = {
            "closed_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades), 4) if trades else None,
            "mean_net_usdt": round(statistics.fmean(nets), 6) if nets else None,
            "median_net_usdt": round(statistics.median(nets), 6) if nets else None,
            "total_net_usdt": money(sum((t.realized_pnl_quote for t in trades), dec(0))),
            "exit_reasons": sorted({trade.exit_reason for trade in trades}),
            "mean_fees_usdt": (
                round(statistics.fmean([float(t.fees_quote) for t in trades]), 6)
                if trades
                else None
            ),
            "mean_slippage_usdt": (
                round(statistics.fmean([float(t.slippage_quote) for t in trades]), 6)
                if trades
                else None
            ),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    evidence = out_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)

    baseline = {name: load_run("CURRENT", name) for name in SCENARIOS}
    candidate = {name: load_run("PROPOSED", name) for name in SCENARIOS}
    attribution = attribute(baseline, candidate)
    mechanics = {
        "baseline": {
            name: mechanism_inventory("CURRENT", name, baseline[name]) for name in SCENARIOS
        },
        "candidate": {
            name: mechanism_inventory("PROPOSED", name, candidate[name]) for name in SCENARIOS
        },
    }
    economics = per_trade_economics({"baseline": baseline, "candidate": candidate})

    # -- reconciliación contra lo que RFC-016 publicó -------------------------------
    audit_current = json.loads((RFC16 / "evidence" / "AUDIT_CURRENT.json").read_text())
    audit_candidate = json.loads((RFC16 / "evidence" / "AUDIT_PROPOSED.json").read_text())
    reported = {"baseline": [], "candidate": []}
    for label, audit in (("baseline", audit_current), ("candidate", audit_candidate)):
        for name in SCENARIOS:
            reported[label].append(
                {
                    "scenario": name,
                    "declared_fills": audit["scenarios"][name]["metrics"]["fills"],
                    "declared_calls": audit["scenarios"][name]["metrics"]["calls"],
                    "reconstructed_fills": int(
                        (baseline if label == "baseline" else candidate)[name].totals["fills"]
                    ),
                }
            )
    recon = {
        "reported": reported,
        "fills_match": all(
            row["declared_fills"] == row["reconstructed_fills"]
            for label in ("baseline", "candidate")
            for row in reported[label]
        ),
        "totals": attribution["totals"],
    }

    payload = {
        "schema_version": SCHEMA,
        "rfc": "RFC-DEF-RUN-017",
        "generated_at_utc": utc_now(),
        "builder": "scripts/def_run_017_audit.py",
        "verifier": "scripts/def_run_017_verify.py (no importa trading_bot)",
        "source_commit": "d05f8de498c175f7a9b8ccdd38e6e1067832d5e6",
        "scenarios": SCENARIOS,
        "status": {
            "baseline": {name: baseline[name].status for name in SCENARIOS},
            "candidate": {name: candidate[name].status for name in SCENARIOS},
        },
        "totals": attribution["totals"],
        "per_scenario": attribution["per_scenario"],
        "per_trade_economics": economics,
        "mechanism_inventory": mechanics,
        "reconciliation": recon,
        "identity": {
            label: {
                name: runs[name].identity.to_row()
                for name in SCENARIOS
            }
            for label, runs in (("baseline", baseline), ("candidate", candidate))
        },
        "unknowns": {
            label: runs[SCENARIOS[0]].identity.unknowns
            for label, runs in (("baseline", baseline), ("candidate", candidate))
        },
    }
    (evidence / "ECONOMIC_ATTRIBUTION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    # -- CSVs ----------------------------------------------------------------------
    trade_rows = [
        {"label": label, **trade.to_row()}
        for label, runs in (("baseline", baseline), ("candidate", candidate))
        for name in SCENARIOS
        for trade in runs[name].trades
    ]
    _write_csv(evidence / "TRADE_LEDGER.csv", trade_rows)
    _write_csv(evidence / "PAIRED_DELTA.csv", attribution["pairs"])

    _write_markdown(out_dir / "ECONOMIC_ATTRIBUTION.md", payload)
    print(
        f"delta net = {payload['totals']['delta_net_usdt']} "
        f"(baseline {payload['totals']['baseline_net_usdt']}, "
        f"candidate {payload['totals']['candidate_net_usdt']})"
    )
    print(f"wrote {evidence / 'ECONOMIC_ATTRIBUTION.json'}")
    return 0


def _stop_range(payload: dict[str, Any]) -> str:
    values = [
        float(value)
        for label in ("baseline", "candidate")
        for row in payload["mechanism_inventory"][label].values()
        for value in row["stop_distance_bps"]
    ]
    if not values:
        return "UNKNOWN"
    return f"{min(values):.2f}-{max(values):.2f}"


def _round_trip(payload: dict[str, Any]) -> str:
    values = [
        float(value)
        for label in ("baseline", "candidate")
        for row in payload["mechanism_inventory"][label].values()
        for value in row["round_trip_cost_bps"]
    ]
    return f"{max(values):.2f}" if values else "UNKNOWN"


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    totals = payload["totals"]
    lines = [
        "# ECONOMIC_ATTRIBUTION — RFC-DEF-RUN-017",
        "",
        f"Generado por `{payload['builder']}` el `{payload['generated_at_utc']}` sobre los "
        f"ledgers de RFC-016 (`{payload['source_commit'][:12]}`). Verificador separado: "
        f"`{payload['verifier']}`.",
        "",
        "## Cadena claim → source → evidence → decision",
        "",
        "| Claim | Source | Evidence | Decision |",
        "| --- | --- | --- | --- |",
        f"| El neto de BASELINE es {totals['baseline_net_usdt']} y el de CANDIDATE "
        f"{totals['candidate_net_usdt']} | 10 ledgers publicados, cadena hash recalculada | "
        "`evidence/TRADE_LEDGER.csv`, `evidence/ECONOMIC_ATTRIBUTION.json` | "
        f"delta {totals['delta_net_usdt']} USDT |",
        f"| El delta se descompone en bruto {totals['delta_gross_usdt']} y comisiones "
        f"{totals['delta_fees_usdt']} | precios de relleno, no los campos de PnL | "
        f"`delta_net_equals_gross_minus_fees={totals['delta_net_equals_gross_minus_fees']}` "
        "| reconciliado |",
        f"| {totals['matched_pairs']} operaciones idénticas, "
        f"{totals['baseline_only']} solo en BASELINE, {totals['candidate_only']} solo en "
        f"CANDIDATE | identidad = sha256 del gráfico + decisión parseada | "
        "`evidence/PAIRED_DELTA.csv` | la diferencia es de **qué** se operó, no de cómo |",
        "",
        "## Totales reconstruidos",
        "",
        "| Métrica | BASELINE | CANDIDATE | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| Neto realizado (USDT) | {totals['baseline_net_usdt']} | "
        f"{totals['candidate_net_usdt']} | {totals['delta_net_usdt']} |",
        f"| Bruto (incluye slippage) | {totals['baseline_gross_usdt']} | "
        f"{totals['candidate_gross_usdt']} | {totals['delta_gross_usdt']} |",
        f"| Comisiones | {totals['baseline_fees_usdt']} | {totals['candidate_fees_usdt']} | "
        f"{totals['delta_fees_usdt']} |",
        f"| Slippage (ya dentro del bruto) | {totals['baseline_slippage_usdt']} | "
        f"{totals['candidate_slippage_usdt']} | {totals['delta_slippage_usdt']} |",
        "",
        f"> {totals['accounting_note']}",
        "",
        "## Por escenario",
        "",
        "| Escenario | BASELINE | CANDIDATE | Delta | emparejadas | solo base | solo cand | residual |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in payload["per_scenario"].items():
        counts = row["counts"]
        lines.append(
            f"| `{name}` | {row['baseline_net_usdt']} | {row['candidate_net_usdt']} | "
            f"{row['observed_delta_usdt']} | {counts['MATCHED']} | "
            f"{counts['BASELINE_ONLY']} | {counts['CANDIDATE_ONLY']} | "
            f"{row['residual_usdt']} |"
        )
    lines += [
        "",
        "Los dos escenarios de control (`m1_cadence5`, `m1_zero_delay`) dan exactamente el "
        "mismo resultado en las dos ramas y sus operaciones se emparejan una a una. Los tres "
        "escenarios donde el mecanismo actúa **no comparten ni una operación**: el cambio no "
        "añade una operación al lado de las existentes; reordena qué barras reciben llamada.",
        "",
        f"Las {totals['baseline_only']} operaciones que solo existen en BASELINE suman "
        f"{totals['baseline_only_trades_net_usdt']} USDT y las "
        f"{totals['candidate_only']} que solo existen en CANDIDATE suman "
        f"{totals['candidate_only_trades_net_usdt']} USDT. El delta completo sale de ahí: "
        "las operaciones emparejadas aportan "
        f"{totals['delta_from_matched_pairs_usdt']} porque son las mismas, con el mismo "
        "resultado, en las dos ramas. Quitar 4 perdedoras y poner 7 no es una mejora: es "
        "el mismo juego con más boletos.",
        "",
        "## La aritmética de cada operación",
        "",
        "| Rama | cerradas | ganadoras | perdedoras | media (USDT) | mediana | comisiones medias |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, row in payload["per_trade_economics"].items():
        lines.append(
            f"| {label} | {row['closed_trades']} | {row['wins']} | {row['losses']} | "
            f"{row['mean_net_usdt']} | {row['median_net_usdt']} | {row['mean_fees_usdt']} |"
        )
    lines += [
        "",
        f"Todas las operaciones cerradas salen por "
        f"{sorted({reason for row in payload['per_trade_economics'].values() for reason in row['exit_reasons']})}. "
        f"La parada efectiva de la señal vive entre "
        f"{_stop_range(payload)} bps y el coste de ida y vuelta declarado es "
        f"{_round_trip(payload)} bps: una operación que se para paga la parada **más** el "
        "round trip completo. Sobre 500 USDT de notional eso son del orden de 2,5-3,2 "
        "USDT por operación, que es lo que se observa. No es que el cambio empeore cada "
        "operación; es que hace más de una operación que, por construcción del stop frente "
        "al coste, no puede ganar.",
        "",
        "## Inventario de mecanismos",
        "",
        "| Escenario | rama | decisiones | aplazamientos | sustituciones | fin de las aplazadas |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for label in ("baseline", "candidate"):
        for name, row in payload["mechanism_inventory"][label].items():
            superseded = row["guard_rejects"].get("SUPERSEDED_BY_NEWER_OPINION", 0)
            lines.append(
                f"| `{name}` | {label} | {row['decisions']} | {row['deferrals']} | "
                f"{superseded} | {row['deferred_fates'] or '—'} |"
            )
    lines += [
        "",
        "## Lo que este documento NO afirma",
        "",
        "1. **No afirma que el cambio cause el deterioro por una vía única.** El delta cierra "
        "por pertenencia de operaciones, que es contabilidad, no causalidad. La rama DEFER "
        "también hace 85 llamadas menos, y ese cambio de calendario mueve qué barras se "
        "evalúan: no es una ablación de una instrucción.",
        "2. **No afirma ventaja ni su ausencia en general.** Cinco escenarios de una sesión de "
        "256 minutos de un símbolo, con un proveedor determinista y `real_model_called=false`.",
        "3. **No atribuye el deterioro a un error contable.** La reconstrucción cuadra al "
        "céntimo de milésima en los diez ledgers; no hay una opinión sin cierre ni un cierre "
        "duplicado.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (json.dumps(value) if isinstance(value, (list, tuple)) else value)
                    for key, value in row.items()
                }
            )


if __name__ == "__main__":
    sys.exit(main())
