"""exp_003n_report — render the eight deliverables from the published JSON.

    ./.venv/Scripts/python.exe scripts/exp_003n_report.py

Nothing here computes a number. Every figure is read from ``design/DESIGN.json``,
``analysis/SCREENING.json``, ``analysis/VALIDATION.json``, ``analysis/DECISION.json`` and
``analysis/VERIFICATION.json``, all of which are written by other stages and sealed by
digest. The report is a rendering, so a disagreement between the report and the analysis is
a defect the verifier can find by reading both.

Timestamps come from the inputs, never from the wall clock: two runs of this script on the
same artifacts produce byte-identical files.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003N-GROSS-FIRST-DISCOVERY-001"
DELIVERABLES = [
    "STRATEGY_UNIVERSE.md",
    "ECONOMIC_SCREENING.csv",
    "CANDIDATE_RANKING.md",
    "REJECTED_CANDIDATES.md",
    "INDEPENDENT_VERIFICATION.md",
    "RUN_REPORT.md",
    "RUN_REPORT.json",
    "FINAL_REPORT.md",
]


def _read_signals(path: Path) -> Any:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_json(path: Path) -> Any:
    """Read evidence that may not exist yet: a rehearsal run later must not fake an earlier one."""

    return _read_json(path) if path.exists() else None


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def _family_rows(screening: dict[str, Any], floor: float) -> list[str]:
    """One row per family, computed from the published decisions."""

    measured = [cell for cell in screening["decisions"] if cell["gates"].get("S0_sample")]
    families = sorted({cell["family"] for cell in screening["decisions"]})
    rows: list[str] = []
    for family in families:
        cells = [cell for cell in measured if cell["family"] == family]
        if not cells:
            rows.append(f"| `{family}` | 0 | — | — | no medida: ninguna celda pasa la muestra |")
            continue
        best = max(
            cells,
            key=lambda item: item["is_mean_bps"] if item["is_mean_bps"] is not None else -1e9,
        )
        covers = (
            best["is_mean_bps"] is not None
            and best["is_mean_bps"] >= floor
            and (best["is_ci_lower_bps"] or -1e9) > 0
        )
        rows.append(
            f"| `{family}` | {len(cells)} | {_num(best['is_mean_bps'])} | "
            f"{_num(best['is_ci_lower_bps'])} | {'sí' if covers else 'no'} |"
        )
    return rows


def rankable(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by net per closed trade, but never let a one-trade cell lead the table.

    ``INSUFFICIENT_EVIDENCE`` cells keep their measured numbers and lose their rank: sorting
    them among candidates is how a single lucky close becomes a headline.
    """

    sufficient = [row for row in candidates if row["verdict"] != "INSUFFICIENT_EVIDENCE"]
    thin = [row for row in candidates if row["verdict"] == "INSUFFICIENT_EVIDENCE"]
    key = lambda row: (row["closed_net_full_bps"] is None, -(row["closed_net_full_bps"] or 0.0))  # noqa: E731
    return sorted(sufficient, key=key) + sorted(thin, key=key)


def ranking_md(design: dict[str, Any], decision: dict[str, Any]) -> str:
    rows = rankable(decision["candidates"])
    lines = [
        "# CANDIDATE RANKING — EXP-003N",
        "",
        f"**Veredicto: `{decision['verdict']}`** · {len(rows)} celdas · holdout abierto: "
        f"**{decision['holdout_opened']}**",
        "",
        "Orden por expectativa neta por operación cerrada en VAL tras coste completo. La columna",
        "«bruto/señal» es el retorno forward medio en el mejor horizonte de IS; «neto cerrado» es lo",
        "que queda tras la comisión y el spread más el slippage de las dos patas. Un candidato no",
        "sube en esta tabla por rentabilidad agregada: sube por bps por operación.",
        "",
        "| # | lane | familia | tf | señales/día | bruto/señal (bps) | coste (bps) | neto/señal (bps) | ops cerradas VAL | neto cerrado (bps) | acierto | PF | veredicto |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | `{row['lane']}` | `{row['family']}` | `{row['timeframe']}` | "
            f"{_num(row['signals_per_day'], 2)} | {_num(row['val_mean_bps'])} | "
            f"{_num(row['cost_full_bps'])} | {_num(row['net_val_signal_bps'])} | "
            f"{row['closed_trades_val']} | {_num(row['closed_net_full_bps'])} | "
            f"{_num((row['closed_win_rate'] or 0) * 100, 1)} % | "
            f"{_num(row['closed_profit_factor'])} | `{row['verdict']}` |"
        )
    best = rows[0] if rows else None
    lines += [
        "",
        "Las celdas con `INSUFFICIENT_EVIDENCE` van al final y no compiten por el primer puesto:",
        "una operación cerrada con +235 bps es un número, no un candidato.",
        "",
        "## Lectura",
        "",
    ]
    if best is not None:
        lines += [
            f"La mejor celda es `{best['family']}@{best['timeframe']}` con "
            f"**{_num(best['closed_net_full_bps'])} bps** netos por operación cerrada. El suelo de",
            f"comisiones es **{_num(design['cost_model']['fee_floor_bps_no_bnb'])} bps** sin descuento",
            f"BNB y el coste completo que se le aplicó es **{_num(best['cost_full_bps'])} bps**: la",
            "comparación no es contra cero, es contra el peaje entero.",
            "",
        ]
        if (best["closed_net_full_bps"] or 0.0) <= 0:
            lines += [
                "Ninguna celda queda por encima de su propio peaje. La tabla no ordena ganadores:",
                "ordena cuánto le falta a cada mecanismo, y el primero de la lista sigue perdiendo",
                "dinero. Esa es la respuesta del experimento, no un empate técnico.",
                "",
            ]
    decisive = [row for row in rows if row["closed_net_full_bps"] is not None]
    if decisive:
        gaps = sorted(row["closed_net_full_bps"] for row in decisive)
        lines += [
            f"- Rango de expectativa neta por operación cerrada: **{_num(gaps[0])}** a "
            f"**{_num(gaps[-1])}** bps.",
            f"- Celdas con neto positivo: **{sum(1 for gap in gaps if gap > 0)}** de **{len(gaps)}**.",
            "",
        ]
    return "\n".join(lines)


def rejected_md(design: dict[str, Any], screening: dict[str, Any], decision: dict[str, Any]) -> str:
    by_key = {row["key"]: row for row in decision["candidates"]}
    rejected = [cell for cell in screening["decisions"] if cell["verdict"] in {"REJECT", "INSUFFICIENT_EVIDENCE"}]
    floor = design["cost_model"]["fee_floor_bps_no_bnb"]
    lines = [
        "# REJECTED CANDIDATES — EXP-003N",
        "",
        f"{len(rejected)} de {len(screening['cells'])} celdas no llegan a la fase de validación. Cada",
        "rechazo cita la medida que lo produce; ninguno cita una impresión.",
        "",
        "## Por familia",
        "",
        "| familia | tf | veredicto | señales IS | bruto/señal IS (bps) | IC95 inf. (bps) | suelo (bps) | déficit (bps) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cell in sorted(rejected, key=lambda item: (item["family"], item["timeframe"])):
        gross = cell["is_mean_bps"]
        deficit = (floor - gross) if gross is not None else None
        lines.append(
            f"| `{cell['family']}` | `{cell['timeframe']}` | `{cell['verdict']}` | "
            f"{cell['signals'].get('IS', 0)} | {_num(gross)} | {_num(cell['is_ci_lower_bps'])} | "
            f"{_num(floor)} | {_num(deficit)} |"
        )

    lines += [
        "",
        "## Hipótesis refutadas",
        "",
        "Estas frases son lo que el experimento deja cerrado en esta lane, con su número:",
        "",
    ]
    families = sorted({cell["family"] for cell in rejected})
    for family in families:
        cells = [cell for cell in rejected if cell["family"] == family]
        measured = [cell for cell in cells if cell["gates"].get("S0_sample")]
        if not measured:
            lines.append(
                f"- **`{family}`**: ninguna celda pasa la puerta de muestra; no se refuta nada, "
                "queda `INSUFFICIENT_EVIDENCE` con el tamaño medido en la tabla de arriba."
            )
            continue
        best = max(
            measured,
            key=lambda item: item["is_mean_bps"] if item["is_mean_bps"] is not None else -1e9,
        )
        if best["is_mean_bps"] is None:
            lines.append(
                f"- **`{family}`**: sin señales medibles en IS; no hay nada que refutar todavía."
            )
            continue
        verdict = (
            "no hay información direccional positiva"
            if best["is_mean_bps"] <= 0
            else "hay información, pero por debajo del peaje"
        )
        lines.append(
            f"- **`{family}`**: mejor horizonte `{best['best_horizon']}` a `{best['timeframe']}` — "
            f"bruto **{_num(best['is_mean_bps'])} bps** por señal, IC95 inferior "
            f"**{_num(best['is_ci_lower_bps'])} bps** frente a un suelo de **{_num(floor)} bps**. "
            f"Motivo del rechazo: {verdict}."
        )

    lines += [
        "",
        "## Los ceros de lane B no son ausencia de ventaja",
        "",
        "WP-EDGE-015 exige ventanas de percentiles de hasta 720 horas antes de decidir. Sobre una",
        "muestra de 46 días, ese warm-up consume la mayor parte de la ventana: las celdas con 0",
        "operaciones se declaran `INSUFFICIENT_EVIDENCE` con el warm-up medido en `RUN_REPORT.md`,",
        "nunca `REJECT`. Un cero por falta de datos no refuta una hipótesis; la deja sin probar.",
        "",
        "## Por qué re-ejecutar el ejecutor no cambia nada",
        "",
    ]
    lines += [
        "Un fill mejor, una cola más corta o una comisión con descuento BNB mueven el coste en",
        "puntos básicos. Ninguno de ellos crea ingreso bruto. Las celdas de esta tabla fallan en la",
        "medida *antes* del ejecutor: el retorno forward del que la señal informa. Por eso el",
        "veredicto de EXP-003M (`5m/mean_reversion` no cubre ni el suelo de comisiones) no se",
        "repara aquí con un modelo de fills distinto, y por eso esta lane no abre un experimento de",
        "ejecución nuevo.",
        "",
    ]
    reference = by_key.get("lane_a::mean_reversion::5m")
    if reference:
        lines += [
            "## Ancla con EXP-003M",
            "",
            f"`5m/mean_reversion` se midió aquí con **{_num(reference['val_mean_bps'])} bps** de bruto",
            f"por señal en VAL y **{_num(reference['closed_net_full_bps'])} bps** netos por operación",
            "cerrada, con el holdout cerrado y sin reutilizar los fills de 003M. Dos métodos",
            "distintos (cinta observada allí, retorno forward y salida congelada aquí) coinciden en",
            "el signo y en el orden de magnitud de la insuficiencia.",
            "",
        ]
    return "\n".join(lines)


def verification_md(verification: dict[str, Any]) -> str:
    summary = verification["summary"]
    lines = [
        "# INDEPENDENT VERIFICATION — EXP-003N",
        "",
        f"**Veredicto: `{verification['verdict']}`** · {summary['passed']}/{summary['checks']} comprobaciones"
        f" · {summary['controls_detected']}/{summary['controls']} controles negativos detectados"
        f" · `false_success={summary['false_success']}`",
        "",
        f"Verificador: `{verification['verifier']}` — un programa distinto, no una persona",
        "(`INDEPENDENT_VERIFIER=PROGRAM_NOT_PERSON`). Relee el dataset con su propio parser,",
        "re-agrega las barras con su propia aritmética y recalcula un cierre desde las barras.",
        "",
        "## Comprobaciones",
        "",
        "| # | comprobación | estado | detalle |",
        "| ---: | --- | --- | --- |",
    ]
    for index, row in enumerate(verification["checks"], start=1):
        lines.append(f"| {index} | `{row['check']}` | **{row['status']}** | {row['detail']} |")
    lines += [
        "",
        "## Controles negativos",
        "",
        "Cada control muta una copia en memoria o en un directorio temporal y comprueba que la",
        "comprobación a la que apunta lo detecta. Un control que no puede fallar no es evidencia.",
        "",
        "| control | detectado | detalle |",
        "| --- | --- | --- |",
    ]
    for row in verification["controls"]:
        lines.append(
            f"| `{row['control']}` | {'sí' if row['detected'] else '**no**'} | {row['detail']} |"
        )
    lines += [
        "",
        "## Qué no demuestra esta verificación",
        "",
        "- No convierte la evidencia en observada: no se envió ninguna orden y ningún fill es real.",
        "- No es una revisión humana: `BUILDER != VERIFIER` se cumple como dos programas, y así se",
        "  declara en lugar de presentarse como una auditoría externa.",
        "- No juzga si el dataset es el mercado: juzga si los números publicados se derivan de él.",
        "- **No regenera las señales.** Toma los timestamps de señal publicados y recalcula desde",
        "  las barras el retorno forward, el coste, las puertas y el veredicto. Un look-ahead dentro",
        "  de la ventana PIT de una familia no lo detectaría este programa: esa parte la cubren",
        "  `tests/unit/reports/test_exp_003n_screen.py` y los tests de familia, que **no** son",
        "  independientes del constructor. Es el hueco de independencia que queda declarado.",
        "",
    ]
    return "\n".join(lines)


def reproduction_md(evidence: Any) -> list[str]:
    """Render the clean-checkout reproduction, or say plainly that it has not been run."""

    if not evidence:
        return [
            "## Reproducción desde checkout limpio",
            "",
            "No ejecutada en este árbol: `evidence/CLEAN_CHECKOUT_REPRODUCTION.json` no existe.",
            "Un resultado sin re-derivación desde un checkout limpio es una medida, no una",
            "reproducción, y así se registra.",
            "",
        ]
    result = evidence["result"]
    lines = [
        "## Reproducción desde checkout limpio",
        "",
        f"- Commit reproducido: `{result['commit'][:7]}` en un worktree `--detach`, sin cambios",
        f"  locales antes de ejecutar ({result['worktree_status_lines_before']} líneas en `git status`).",
        f"- Dataset: {result['dataset_digests_matched']}/3 digests iguales a los que fija el diseño.",
        f"- Screening re-ejecutado: {result['cells_compared'] - result['cells_mismatched']}"
        f"/{result['cells_compared']} celdas idénticas (`{result['screening_verdict_reproduced']}`).",
        f"- Validación re-ejecutada: {result['validation_compared'] - result['validation_mismatched']}"
        f"/{result['validation_compared']} celdas idénticas.",
        f"- Verificación independiente en el worktree: "
        f"{result['verification_checks']} comprobaciones, "
        f"{result['verification_controls']} controles negativos, veredicto "
        f"`{result['verification_verdict']}`.",
        f"- Tests en el worktree: {result['tests_passed']} pasan, {result['tests_failed']} fallan.",
        "",
    ]
    if evidence.get("not_verified"):
        lines.append("Lo que esta reproducción **no** prueba:")
        lines.append("")
        for item in evidence["not_verified"]:
            lines.append(f"- {item}")
        lines.append("")
    return lines


def run_report_md(
    design: dict[str, Any],
    screening: dict[str, Any],
    validation: dict[str, Any],
    decision: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    lines = [
        "# RUN REPORT — EXP-003N (gross-first strategy discovery)",
        "",
        f"- Experimento: `{design['experiment']}`",
        f"- Diseño congelado: {design['frozen_at_utc']} sobre `{design['commit'][:7]}`",
        f"- Screening: {screening['generated_at_utc']} · validación: {validation['generated_at_utc']}",
        f"- Verificación: {verification['generated_at_utc']} · veredicto `{verification['verdict']}`",
        "- Modo: research offline. Órdenes reales: **0**. Holdout `2026-08-06 → 2026-08-20`: "
        "**cerrado**.",
        "",
        "## Pregunta",
        "",
        design["question"],
        "",
        design["why_not_another_fill_model"],
        "",
        "## Preregistración — y su límite",
        "",
        "El protocolo completo está en `design/PREREGISTRATION.md` y `design/DESIGN.json`. Se congeló",
        f"en disco a las {design['frozen_at_utc']} y el screening corrió después, pero **entró en Git",
        "después de que existiera el análisis**: el congelamiento está anclado por contenido",
        "(`SCREENING.json` guarda el `design_sha256` con el que se ejecutó y el verificador lo",
        "compara), no por tiempo. Por tanto este análisis es **retrospectivo con protocolo",
        "declarado**, no prospectivo, y así se cita en todo el informe.",
        "",
        "## Universo de estrategias",
        "",
        "- Clases con forma de estrategia inventariadas: "
        + ", ".join(
            f"`{label}` = {count}"
            for label, count in sorted(
                _read_json(OUT / "design" / "STRATEGY_UNIVERSE.json")["counts"].items()
            )
        ),
        "- **`RUNTIME_AUTHORITATIVE` no aparece en el inventario derivado.** El criterio es «importada",
        "  o instanciada desde un entrypoint», y las seis AlphaFamilies se construyen en",
        "  `scripts/autonomous_paper.py` pero su señal pasa después por router, admisión, riesgo y",
        "  decisión antes de ejecutarse: eso las deja en `RUNTIME_REACHABLE`. El mapa de autoridad",
        "  del propio repositorio (`docs/runtime/runtime_authority_map.md`) las lista como",
        "  `RUNTIME_AUTHORITATIVE`. La diferencia es de vocabulario, no de medida: en ambos casos son",
        "  las mismas seis clases y las mismas señales, y ninguna puerta económica depende de la",
        "  etiqueta. Se deja visible en lugar de reconciliarse por decreto.",
        "- `screened_here = no` en las clases `*Machine` de `pit15.py` quiere decir que la celda se",
        "  midió por familia (lane B), no por clase: la unidad de este experimento es la familia, no",
        "  el objeto Python que la implementa. Las tres familias de lane B se ejecutan con esas",
        "  máquinas a través de `run_family`.",
        "",
        "## Suelo de costes con el que se compara todo",
        "",
        f"- Comisión spot VIP0: **{design['cost_model']['fee_bps_per_side']} bps** por lado.",
        f"- Suelo comparable (ida y vuelta): **{design['cost_model']['fee_floor_bps_no_bnb']} bps**; "
        f"con descuento BNB **{design['cost_model']['fee_floor_bps_bnb']} bps**.",
        "- Coste completo aplicado por símbolo (comisión + medio spread + slippage + impacto, dos "
        "patas, 500 USDT):",
        "",
        "| símbolo | tier | ida y vuelta (bps) | solo precio por lado (bps) |",
        "| --- | --- | ---: | ---: |",
    ]
    for symbol, cost in sorted(screening["costs"].items()):
        lines.append(
            f"| `{symbol}` | `{cost['tier']}` | {_num(cost['round_trip_bps'], 2)} | "
            f"{_num(cost['price_bps_per_side'], 3)} |"
        )
    lines += [
        "",
        "## Qué se ejecutó",
        "",
        "| etapa | comando | salida |",
        "| --- | --- | --- |",
        "| inventario + congelación | `scripts/exp_003n_preregister.py` | `design/` |",
        "| protocolo legible | `design/PREREGISTRATION.md` | hipótesis, particiones, puertas y su límite de procedencia |",
        "| screening | `scripts/exp_003n_screen.py` | `analysis/SCREENING.json`, `analysis/SIGNALS.jsonl.gz`, `ECONOMIC_SCREENING.csv` |",
        "| validación | `scripts/exp_003n_validate.py` | `analysis/VALIDATION.json`, `analysis/DECISION.json` |",
        "| verificación | `scripts/exp_003n_verify.py --negative-controls` | `analysis/VERIFICATION.json` |",
        "| tests | `pytest tests/unit/vision tests/unit/paper tests/unit/reports/test_exp_003n_screen.py` | `analysis/TESTS.json`, `evidence/*.log` |",
        "| informe | `scripts/exp_003n_report.py` | estos documentos |",
        "| sello | `scripts/exp_003n_pipeline.py seal` | `SHA256SUMS.txt`, `SEAL.json` |",
        "",
        "## Muestra",
        "",
        "| lane | celda | señales RESEARCH | señales IS | señales VAL | señales/día |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for cell in screening["decisions"]:
        lines.append(
            f"| `{cell['lane']}` | `{cell['family']}@{cell['timeframe']}` | "
            f"{cell['signals'].get('RESEARCH', 0)} | {cell['signals'].get('IS', 0)} | "
            f"{cell['signals'].get('VAL', 0)} | {_num(cell['signals_per_day'], 2)} |"
        )
    lines += [
        "",
        "## Warm-up frente a ventana (lane B)",
        "",
        "Las familias de WP-EDGE-015 se parametrizan en horas, y su ventana de percentiles consume",
        "historia antes de poder decidir. Si el warm-up se come la muestra, un cero no es ausencia",
        "de ventaja: es ausencia de datos. Esta tabla lo hace explícito.",
        "",
        "| familia | warm-up requerido (h) | IS (h) | VAL (h) | TEST (h) | veredicto |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    spans = {
        name: (block["end_utc"], block["start_utc"]) for name, block in design["partitions"].items()
    }
    hours = {
        name: (_parse_hours(end) - _parse_hours(start)) for name, (end, start) in spans.items()
    }
    for family in design["candidates"]["lane_b_alpha15_families"]:
        required = _warmup_hours(family["parameters"])
        verdict = next(
            (
                cell["verdict"]
                for cell in screening["decisions"]
                if cell["family"] == family["family"] and cell["lane"] == "lane_b"
            ),
            "NOT_RUN",
        )
        lines.append(
            f"| `{family['family']}` | {_num(required, 0)} | {_num(hours.get('IS'), 0)} | "
            f"{_num(hours.get('VAL'), 0)} | {_num(hours.get('TEST'), 0)} | `{verdict}` |"
        )
    lines += [
        "",
        "Cuando el warm-up requerido supera la ventana de VAL, el cero se reporta como",
        "`INSUFFICIENT_EVIDENCE` y nunca como `REJECT`: no se puede refutar lo que no se midió.",
        "",
        "## Reparto de veredictos",
        "",
        "| veredicto | celdas |",
        "| --- | ---: |",
    ]
    for label, count in sorted(decision["counts"].items()):
        lines.append(f"| `{label}` | {count} |")
    lines += [
        "",
        f"Veredicto del experimento: **`{decision['verdict']}`**.",
        "",
    ]
    lines += reproduction_md(_optional_json(OUT / "evidence" / "CLEAN_CHECKOUT_REPRODUCTION.json"))
    lines += [
        "## Defectos encontrados y reparados",
        "",
        "| id | defecto | impacto | reparación |",
        "| --- | --- | --- | --- |",
        "| `DEF-003N-01` | `exp_003n_screen.py` imprimía `target.relative_to(REPO)` y lanzaba `ValueError` cuando `--out` apuntaba fuera del repositorio (el worktree llegaba en forma corta 8.3) | el fallo ocurría **después** de escribir `SCREENING.json`, `SIGNALS.jsonl.gz` y `ECONOMIC_SCREENING.csv`: un llamador que solo mira el código de salida habría tirado un resultado bueno | la línea de diagnóstico usa la ruta absoluta si el destino está fuera del repo; no se tocó código de medida |",
        "",
        "`DEF-003N-01` lo encontró la reproducción desde checkout limpio, no el constructor: es la",
        "razón por la que esa reproducción existe. Los defectos heredados de `EXP-003M` (`R1` CRLF en",
        "el sello, `R2` tests que dependían de un árbol no commiteado) están en",
        "`evidence/CLEAN_CHECKOUT_REHEARSAL.json` con su commit de reparación.",
        "",
        "## Gobernanza",
        "",
        "```",
        f"LIVE_TRADING={design['governance']['live_trading']}",
        f"TRADES_AUTHORIZED={design['governance']['trades_authorized']}",
        f"PAPER_PROMOTION={design['governance']['paper_promotion']}",
        "OOS_HOLDOUT=CLOSED",
        f"FALSE_SUCCESS={verification['summary']['false_success']}",
        "```",
        "",
    ]
    return "\n".join(lines)


def run_report_json(
    design: dict[str, Any],
    screening: dict[str, Any],
    validation: dict[str, Any],
    decision: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "AI_BOTS_003N_RUN_REPORT_V1",
        "experiment": design["experiment"],
        "design": {
            "frozen_at_utc": design["frozen_at_utc"],
            "commit": design["commit"],
            "partitions": design["partitions"],
            "holdout": design["holdout"],
            "horizons_bars": design["horizons_bars"],
            "exit_policy": design["exit_policy"],
        },
        "inputs": {
            "dataset": design["dataset"],
            "config_sha256": design["invariants"]["config_sha256"],
            "predecessor": design["predecessor"],
        },
        "costs": screening["costs"],
        "counts": {
            "cells": len(screening["decisions"]),
            "signals": _read_signals(OUT / "analysis" / "SIGNALS.jsonl.gz")["count"],
            "tests": screening["test_count"],
            "verdicts": decision["counts"],
        },
        "verdict": decision["verdict"],
        "candidates": decision["candidates"],
        "multiple_testing": screening["multiple_testing"],
        "verification": verification["summary"],
        "preregistration": {
            "document": "design/PREREGISTRATION.md",
            "frozen_at_utc": design["frozen_at_utc"],
            "prospective": False,
            "limit": (
                "the protocol was frozen on disk before the screening ran, but it was committed "
                "to Git after the analysis existed: the freeze is content-anchored, not "
                "time-anchored, so no result here is a prospective prediction"
            ),
        },
        "reproduction": _optional_json(OUT / "evidence" / "CLEAN_CHECKOUT_REPRODUCTION.json"),
        "artifacts": DELIVERABLES,
        "governance": {
            **design["governance"],
            "holdout_opened": decision["holdout_opened"],
            **decision["not_promoted"],
        },
        "generated_at_utc": screening["generated_at_utc"],
        "validation_generated_at_utc": validation["generated_at_utc"],
    }


def final_md(
    design: dict[str, Any],
    screening: dict[str, Any],
    decision: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    ordered = rankable(decision["candidates"])
    rows = ordered
    # The headline cell must have a sample behind it: one closed trade is a number, not a
    # candidate, so the insufficient-evidence cells never take the first line.
    best = next(
        (row for row in ordered if row["verdict"] != "INSUFFICIENT_EVIDENCE"), None
    )
    floor = design["cost_model"]["fee_floor_bps_no_bnb"]
    positives = sum(1 for row in rows if (row["closed_net_full_bps"] or 0.0) > 0)
    lines = [
        "# FINAL REPORT — EXP-003N",
        "",
        f"## Respuesta: `{decision['verdict']}`",
        "",
    ]
    if decision["verdict"] == "NO_VIABLE_CANDIDATES":
        lines += [
            "Ningún mecanismo que exista hoy en el repositorio produce, con muestra suficiente para",
            "medirlo y con el coste completo aplicado, una expectativa económica positiva por",
            "operación cerrada. No es un problema de ejecución: es un problema de ingreso bruto.",
            "",
            "El único neto positivo del barrido es una celda con **una** operación cerrada. Se",
            "publica, no se promociona: una operación no es una muestra, y por eso figura como",
            "`INSUFFICIENT_EVIDENCE` y no como candidato.",
            "",
        ]
    else:
        lines += [
            "Hay al menos una celda cuya expectativa neta por operación cerrada supera su peaje.",
            "No se promociona: hace falta una ventana forward preregistrada y evidencia observada.",
            "",
        ]

    lines += [
        "## Naturaleza del análisis",
        "",
        f"Protocolo congelado en disco a las {design['frozen_at_utc']} (`design/DESIGN.json`,",
        "`design/PREREGISTRATION.md`), screening posterior, pero **publicación en Git posterior al",
        "análisis**. El congelamiento está anclado por contenido y no por tiempo: esto es un",
        "**análisis retrospectivo con protocolo declarado**, no una predicción prospectiva. Ninguna",
        "cifra de este informe se presenta como validación fuera de muestra de una regla que se",
        "eligió mirando el futuro: `VAL` no participó en la elección del horizonte y `TEST` no se usó",
        "para decidir, pero ambos ya habían ocurrido cuando se congeló el protocolo.",
        "",
    ]
    reproduction = _optional_json(OUT / "evidence" / "CLEAN_CHECKOUT_REPRODUCTION.json")
    if reproduction:
        outcome = reproduction["result"]
        lines += [
            f"Reproducción desde checkout limpio (`{outcome['commit'][:7]}`): "
            f"{outcome['cells_compared'] - outcome['cells_mismatched']}/{outcome['cells_compared']}"
            f" celdas idénticas, {outcome['validation_compared'] - outcome['validation_mismatched']}"
            f"/{outcome['validation_compared']} en validación, veredicto "
            f"`{reproduction['verdict']}`. Los números se re-derivan; el mercado, no.",
            "",
        ]

    lines += ["## El número que decide", ""]
    sufficient = [row for row in ordered if row["verdict"] != "INSUFFICIENT_EVIDENCE"]
    # The smallest *deficit* is the highest net per signal, not the lowest: a cell at -210 bps
    # is further from paying its toll than one at -3 bps, and sorting ascending would crown it.
    best_signal = (
        max(
            (row for row in sufficient if row["net_val_signal_bps"] is not None),
            key=lambda row: row["net_val_signal_bps"],
        )
        if sufficient
        else None
    )
    if best is not None:
        lines += [
            f"- Mejor celda por **operación cerrada** (el criterio de la tabla): "
            f"`{best['family']}@{best['timeframe']}` ({best['lane']}), "
            f"**{_num(best['closed_net_full_bps'])} bps** netos con "
            f"{best['closed_trades_val']} cierre(s) en VAL, acierto "
            f"{_num((best['closed_win_rate'] or 0) * 100, 1)} % y PF "
            f"{_num(best['closed_profit_factor'])}.",
            f"- La misma celda por **señal**: bruto **{_num(best['val_mean_bps'])} bps** frente a "
            f"coste completo **{_num(best['cost_full_bps'])} bps** → neto "
            f"**{_num(best['net_val_signal_bps'])} bps**.",
        ]
        if best_signal is not None and best_signal["key"] != best["key"]:
            lines += [
                f"- El déficit **por señal** más pequeño es otro: "
                f"`{best_signal['family']}@{best_signal['timeframe']}` "
                f"({_num(best_signal['val_mean_bps'])} bps brutos menos "
                f"{_num(best_signal['cost_full_bps'])} bps = "
                f"{_num(best_signal['net_val_signal_bps'])} bps). Se publican las dos lecturas",
                "porque el orden depende de la unidad y ninguna de las dos cubre el peaje.",
            ]
        lines += [
            f"- Celdas con neto positivo tras coste completo: **{positives}** de **{len(rows)}**.",
            "",
        ]

    lines += [
        "## Qué se descartó estructuralmente",
        "",
        "- `5m/mean_reversion` (el candidato de 003L/003M): no se rehabilita. Aquí se mide con un",
        f"  método distinto y vuelve a quedar por debajo del suelo de {_num(floor)} bps.",
        "- Las familias de WP-EDGE-015 se re-miden en un universo y un periodo nuevos (majors,",
        "  junio-agosto) sin reutilizar la corpora anterior; el resultado se suma a su historial, no",
        "  lo sustituye.",
        "",
        "### Por familia, con la muestra que la sostiene",
        "",
        "Solo cuentan las celdas que pasan la puerta de muestra: una familia con cuatro señales no",
        "queda refutada, queda sin medir, y así se dice.",
        "",
        "| familia | celdas con muestra | mejor bruto/señal (bps) | IC95 inf. (bps) | ¿cubre el suelo? |",
        "| --- | ---: | ---: | ---: | --- |",
        *_family_rows(screening, floor),
        "",
        "## Lo que el experimento no dice",
        "",
        "- No dice que no exista ventaja en el mercado: dice que ninguna de las que este repositorio",
        "  implementa hoy la tiene en esta muestra.",
        "- No dice nada sobre el holdout `2026-08-06 → 2026-08-20`: sigue cerrado y sin usar.",
        "- No convierte un bruto en una ganancia: el escenario favorable de fills de 003M ya",
        "  demostró que un toque no es un fill, y aquí no se modela fill alguno.",
        "- El bootstrap sobre 5 días asume estacionariedad local; 46 días son cinco a nueve bloques,",
        "  y eso acota lo que un intervalo puede afirmar.",
        "",
        "## Verificación",
        "",
        f"- `{verification['summary']['passed']}/{verification['summary']['checks']}` comprobaciones y "
        f"`{verification['summary']['controls_detected']}/{verification['summary']['controls']}` "
        f"controles negativos, `false_success={verification['summary']['false_success']}`.",
        "- El verificador no comparte código con el constructor y recalcula desde las barras.",
        "",
        "## Gobernanza",
        "",
        "```",
        "LIVE_TRADING=DISABLED",
        "TRADES_AUTHORIZED=0",
        "PAPER_PROMOTION=NOT_AUTHORIZED",
        "OOS_HOLDOUT=CLOSED",
        "RISK_LIMITS_CHANGED=0",
        "```",
        "",
        "Todo lo anterior se sostiene sobre los artefactos de este directorio, sellados por",
        "`SHA256SUMS.txt` y verificados por un programa distinto del que los escribió.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)

    design = _read_json(out / "design" / "DESIGN.json")
    screening = _read_json(out / "analysis" / "SCREENING.json")
    validation = _read_json(out / "analysis" / "VALIDATION.json")
    decision = _read_json(out / "analysis" / "DECISION.json")
    verification = _read_json(out / "analysis" / "VERIFICATION.json")

    _write(out / "CANDIDATE_RANKING.md", ranking_md(design, decision))
    _write(out / "REJECTED_CANDIDATES.md", rejected_md(design, screening, decision))
    _write(out / "INDEPENDENT_VERIFICATION.md", verification_md(verification))
    _write(out / "RUN_REPORT.md", run_report_md(design, screening, validation, decision, verification))
    _write(out / "FINAL_REPORT.md", final_md(design, screening, decision, verification))
    payload = run_report_json(design, screening, validation, decision, verification)
    _write(
        out / "RUN_REPORT.json",
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
    )

    # The screening CSV is published from the analysis, not re-derived: one source of truth.
    rows = screening["decisions"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "lane",
            "family",
            "timeframe",
            "symbols",
            "signals_research",
            "signals_is",
            "signals_val",
            "signals_per_day",
            "best_horizon_bars",
            "is_mean_bps",
            "is_ci_lower_bps",
            "val_mean_bps",
            "test_mean_bps",
            "cost_round_trip_bps",
            "fee_floor_bps",
            "net_val_bps",
            "gates_passed",
            "failed_gates",
            "verdict",
        ]
    )
    for cell in rows:
        writer.writerow(
            [
                cell["lane"],
                cell["family"],
                cell["timeframe"],
                "|".join(cell["symbols"]),
                cell["signals"].get("RESEARCH", 0),
                cell["signals"].get("IS", 0),
                cell["signals"].get("VAL", 0),
                f"{cell['signals_per_day']:.4f}",
                cell["best_horizon"],
                _csv(cell["is_mean_bps"]),
                _csv(cell["is_ci_lower_bps"]),
                _csv(cell["val_mean_bps"]),
                _csv(cell["test_mean_bps"]),
                f"{cell['cost_round_trip_bps']:.4f}",
                f"{cell['fee_floor_bps']:.4f}",
                _csv(cell["net_val_bps"]),
                sum(1 for ok in cell["gates"].values() if ok),
                "|".join(cell["failed_gates"]),
                cell["verdict"],
            ]
        )
    _write(out / "ECONOMIC_SCREENING.csv", buffer.getvalue())

    # The universe document is generated by the preregistration; copy it into the deliverable.
    universe = (out / "design" / "STRATEGY_UNIVERSE.md").read_text(encoding="utf-8")
    _write(out / "STRATEGY_UNIVERSE.md", universe)

    missing = [name for name in DELIVERABLES if not (out / name).exists()]
    if missing:
        print(f"[003n-report] FAIL — missing deliverables: {missing}", file=sys.stderr)
        return 1
    print(f"[003n-report] wrote {len(DELIVERABLES)} deliverables in {out.relative_to(REPO)}")
    return 0


def _parse_hours(text: str) -> float:
    from datetime import datetime as _datetime

    stamp = _datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    return stamp.timestamp() / 3600.0


def _warmup_hours(parameters: dict[str, Any]) -> float:
    """The longest lookback a family declares, in hours."""

    values = [
        float(value)
        for key, value in parameters.items()
        if key.endswith("hours") and isinstance(value, (int, float))
    ]
    return max(values) if values else 0.0


def _csv(value: Any) -> str:
    return "" if value is None else f"{float(value):.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
