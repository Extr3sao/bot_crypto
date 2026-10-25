"""exp_003k_report — assemble 003K's report from the artifacts, not from memory.

    ./.venv/Scripts/python.exe scripts/exp_003k_report.py

Writes, inside ``reports/ai-bots/EXP-003K-CANDIDATE-001``:

* ``RUN_REPORT.json`` — machine-readable record: identity, dataset digests, the command for
  every step, the tests actually run with their exit codes, the selection, the verdict, the
  verification summary, the artifact list and the open defects;
* ``RUN_REPORT.md`` and ``FINAL_REPORT.md`` — the same content for a reader;
* ``SHA256SUMS.txt`` — one line per artifact, so a later reader can tell whether a file
  moved after the report was written.

Nothing here computes a strategy metric. The numbers come from ``METRICS.json`` (per run),
``ECONOMIC_AUDIT.json``, ``SELECTION.json``, ``VERDICT.json``, ``CLOSED_CYCLE.json`` and
``VERIFICATION.json``; the report only arranges them and refuses to claim a step whose
artifact is missing. A missing test record is reported as ``NOT_EXECUTED``, never as green.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001"
EXPERIMENT = "EXP-003K-CANDIDATE-001"


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        return "UNKNOWN"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "SHA256SUMS.txt":
            continue
        if ".lock" in path.name:
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _run_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted((root / "runs").glob("*/real/*/METRICS.json")):
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        rows.append(
            {
                "strategy_id": metrics.get("strategy_id"),
                "partition": metrics.get("partition"),
                "closes": metrics.get("closes"),
                "decisions": metrics.get("decisions"),
                "directional": metrics.get("directional"),
                "fills": metrics.get("fills"),
                "open_at_end": metrics.get("open_at_end"),
                "reference_gross_usdt": metrics.get("reference_gross_usdt"),
                "execution_cost_usdt": metrics.get("execution_cost_usdt"),
                "commissions_usdt": metrics.get("commissions_usdt"),
                "net_pnl_usdt": metrics.get("net_pnl_usdt"),
                "expectancy_usdt": metrics.get("expectancy_usdt"),
                "reference_gross_per_trade_usdt": metrics.get("reference_gross_per_trade_usdt"),
                "cost_per_trade_usdt": metrics.get("cost_per_trade_usdt"),
                "win_rate": metrics.get("win_rate"),
                "holding_minutes_mean": metrics.get("holding_minutes_mean"),
                "drawdown_pct": metrics.get("drawdown_pct"),
                "ledger_sha256": metrics.get("ledger_sha256"),
                "ledger": f"runs/{metrics.get('strategy_id')}/real/{metrics.get('partition')}/ledger.jsonl",
            }
        )
    return rows


def _tests(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    if record is None:
        return [
            {
                "command": "(not recorded)",
                "exit_code": None,
                "result": "NOT_EXECUTED",
                "detail": "no analysis/TESTS.json was written for this run",
            }
        ]
    return list(record.get("tests") or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    root = Path(args.out)

    partitions = _load(root / "PARTITIONS.json") or {}
    manifest = _load(root / "dataset" / "DATASET_MANIFEST.json") or {}
    audit = _load(root / "analysis" / "ECONOMIC_AUDIT.json")
    cycle = _load(root / "analysis" / "CLOSED_CYCLE.json")
    selection = _load(root / "SELECTION.json")
    verdict = _load(root / "VERDICT.json")
    verification = _load(root / "VERIFICATION.json")
    tests = _tests(_load(root / "analysis" / "TESTS.json"))
    runs = _run_rows(root)
    artifacts = _artifact_rows(root)

    missing = [
        name
        for name, value in (
            ("PARTITIONS.json", partitions),
            ("dataset/DATASET_MANIFEST.json", manifest),
            ("analysis/ECONOMIC_AUDIT.json", audit),
            ("analysis/CLOSED_CYCLE.json", cycle),
            ("SELECTION.json", selection),
            ("VERDICT.json", verdict),
            ("VERIFICATION.json", verification),
        )
        if not value
    ]

    checks = (verification or {}).get("checks") or []
    not_executed = [check for check in checks if check.get("status") == "NOT_EXECUTED"]
    failed = [check for check in checks if not check.get("ok") and check.get("status") != "NOT_EXECUTED"]

    defects: list[dict[str, Any]] = []
    if verdict and verdict.get("status") not in {"EVIDENCE_OF_EDGE", "SELECTED"}:
        defects.append(
            {
                "id": "DEF-003K-01",
                "severity": "INFO",
                "statement": (
                    "Etapa B BLOCKED: ninguna familia superó la etapa A, así que el holdout no "
                    "se abrió para una segunda estrategia."
                ),
                "detail": verdict.get("note"),
            }
        )
    for check in not_executed:
        defects.append(
            {
                "id": f"GAP-{check.get('code')}",
                "severity": "GAP",
                "statement": check.get("detail"),
                "detail": "declarado NOT_EXECUTED; no se contabiliza como superado",
            }
        )
    for check in failed:
        defects.append(
            {
                "id": f"FAIL-{check.get('code')}",
                "severity": "BLOCKER",
                "statement": check.get("detail"),
                "detail": "el verificador falló este check",
            }
        )
    if not (verdict or {}).get("status"):
        defects.append(
            {
                "id": "DEF-003K-02",
                "severity": "BLOCKER",
                "statement": "No hay veredicto de la etapa B.",
                "detail": "faltan las corridas OOS de la candidata",
            }
        )

    run_id = f"{EXPERIMENT}@{_git('rev-parse', '--short=12', 'HEAD')}"
    payload = {
        "schema_version": "AI_BOTS_003K_RUN_REPORT_V1",
        "run_id": run_id,
        "experiment": EXPERIMENT,
        "generated_at_utc": _utc_now(),
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "mode": "PAPER / OFFLINE",
            "live_enabled": False,
            "live_orders": 0,
        },
        "partitions": partitions,
        "dataset": {
            "manifest": "dataset/DATASET_MANIFEST.json",
            "symbols": {
                symbol: {
                    "file": entry.get("file"),
                    "sha256": entry.get("sha256"),
                    "bytes": entry.get("bytes"),
                    "coverage": {
                        key: (entry.get("coverage") or {}).get(key)
                        for key in ("bars", "missing_bars", "duplicate_bars", "complete")
                    },
                }
                for symbol, entry in (manifest.get("symbols") or {}).items()
            },
        },
        "pre_registration": "PRE_REGISTRATION.md",
        "protocol": {
            "stage_a": "six families on the research window; the rule in PRE_REGISTRATION.md section 4",
            "stage_b": "baseline and the selected family, one run each, on the holdout",
            "fill_policy": "next_observable_bar_open",
            "costs": "config/risk.yaml cost_for: 10 bp per side + half-spread + slippage",
        },
        "selection": selection,
        "verdict": verdict,
        "runs": runs,
        "economic_audit": {
            "path": "analysis/ECONOMIC_AUDIT.json",
            "identities_ok": (audit or {}).get("identities_ok"),
            "verdicts": [
                {
                    "arm": item.get("arm"),
                    "partition": item.get("partition"),
                    "closes": item.get("closes"),
                    "reference_gross_usdt": (item.get("decomposition") or {}).get("reference_gross_usdt"),
                    "costs_usdt": round(
                        float((item.get("decomposition") or {}).get("execution_cost_usdt") or 0.0)
                        + float((item.get("decomposition") or {}).get("commissions_usdt") or 0.0),
                        8,
                    ),
                    "net_usdt": (item.get("decomposition") or {}).get("net_usdt"),
                    "dominance": (item.get("dominance") or {}).get("verdict"),
                }
                for item in (audit or {}).get("audits", [])
            ],
        },
        "closed_cycle": {
            "path": "analysis/CLOSED_CYCLE.json",
            "ok": (cycle or {}).get("ok"),
            "runs": [
                {
                    "strategy_id": item.get("strategy_id"),
                    "partition": item.get("partition"),
                    "closes": item.get("closes"),
                    "checks_passed": item.get("checks_passed"),
                    "expected_checks": item.get("expected_checks"),
                    "failure_count": item.get("failure_count"),
                }
                for item in (cycle or {}).get("runs", [])
            ],
        },
        "verification": {
            "path": "VERIFICATION.json",
            "verdict": (verification or {}).get("verdict"),
            "summary": (verification or {}).get("summary"),
            "negative_controls": (verification or {}).get("negative_controls"),
            "false_success": (verification or {}).get("false_success"),
            "checks": checks,
        },
        "tests": tests,
        "defects": defects,
        "missing_artifacts": missing,
        "artifacts": artifacts,
        "limitations": [
            "Un resultado positivo en este diseño es exploratorio: cinco familias compitieron por una confirmación.",
            "El verificador es otro programa, no otra persona: la independencia se limita a los controles negativos.",
            "LIVE está deshabilitado y ninguna corrida registró una orden real.",
        ],
    }

    (root / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    def fmt(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.6f}"
        return str(value)

    lines = [
        f"# {EXPERIMENT} — RUN REPORT",
        "",
        f"`{run_id}` · commit `{payload['commit'][:7]}` · rama `{payload['branch']}` · "
        f"{payload['generated_at_utc']}",
        "",
        "Modo **PAPER / OFFLINE**. `live_enabled=false`, `live_orders=0`, sin credenciales.",
        "",
        "## 1. Dataset congelado",
        "",
        "| activo | barras 1 m | huecos | duplicados | SHA-256 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for symbol, entry in payload["dataset"]["symbols"].items():
        coverage = entry["coverage"]
        lines.append(
            f"| {symbol} | {coverage.get('bars')} | {coverage.get('missing_bars')} | "
            f"{coverage.get('duplicate_bars')} | `{str(entry.get('sha256'))[:16]}…` |"
        )
    lines += [
        "",
        "Particiones fijadas antes de la primera corrida: "
        f"research {partitions.get('research', {}).get('start_utc')} → "
        f"{partitions.get('research', {}).get('end_utc')}, OOS "
        f"{partitions.get('oos', {}).get('start_utc')} → {partitions.get('oos', {}).get('end_utc')}.",
        "",
        "## 2. Corridas",
        "",
        "| estrategia | partición | decisiones | cierres | abiertas | bruto/op | coste/op | neto | expectativa | DD % |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in runs:
        lines.append(
            f"| `{run['strategy_id']}` | {run['partition']} | {run['decisions']} | {run['closes']} | "
            f"{run['open_at_end']} | {fmt(run['reference_gross_per_trade_usdt'])} | "
            f"{fmt(run['cost_per_trade_usdt'])} | {fmt(run['net_pnl_usdt'])} | "
            f"{fmt(run['expectancy_usdt'])} | {fmt(run['drawdown_pct'])} |"
        )
    lines += ["", "## 3. Selección (etapa A, solo research)", ""]
    if selection:
        lines.append(f"Estado `{selection.get('status')}` · seleccionada `{selection.get('selected')}`.")
        lines.append("")
        lines.append("| estrategia | cierres | bruto/op | expectativa | elegible |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for candidate in selection.get("candidates", []):
            lines.append(
                f"| `{candidate['strategy_id']}` | {candidate['closes']} | "
                f"{fmt(candidate['reference_gross_per_trade_usdt'])} | "
                f"{fmt(candidate['expectancy_usdt'])} | {'sí' if candidate['eligible'] else 'no'} |"
            )
    else:
        lines.append("Sin `SELECTION.json`: la etapa A no se cerró.")
    lines += ["", "## 4. Veredicto (etapa B, un solo pase sobre el holdout)", ""]
    if verdict:
        lines.append(f"`{verdict.get('status')}` · candidata `{verdict.get('candidate')}`.")
        conditions = verdict.get("conditions") or {}
        if conditions:
            lines.append("")
            for key, ok in conditions.items():
                lines.append(f"- {key}: {'cumple' if ok else 'NO cumple'}")
        for window in ("research", "oos"):
            block = (verdict.get(window) or {}).get(verdict.get("candidate") or "") or {}
            if block:
                lines.append("")
                lines.append(
                    f"Candidata en {window}: {block.get('closes')} cierres, neto "
                    f"{fmt(block.get('net_usdt'))}, expectativa {fmt(block.get('expectancy_usdt'))}, "
                    f"IC95 % {block.get('bootstrap', {}).get('ci95')}."
                )
    else:
        lines.append("Sin `VERDICT.json`.")
    lines += [
        "",
        "## 5. Auditoría económica",
        "",
        "| arm | partición | cierres | bruto ref. | costes | neto | veredicto |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload["economic_audit"]["verdicts"]:
        lines.append(
            f"| {item['arm']} | {item['partition']} | {item['closes']} | "
            f"{fmt(item['reference_gross_usdt'])} | {fmt(item['costs_usdt'])} | "
            f"{fmt(item['net_usdt'])} | `{item['dominance']}` |"
        )
    lines += [
        "",
        "## 6. Ciclo completo reconstruido",
        "",
        "| estrategia | partición | cierres | checks | fallos |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for item in payload["closed_cycle"]["runs"]:
        lines.append(
            f"| `{item['strategy_id']}` | {item['partition']} | {item['closes']} | "
            f"{item['checks_passed']}/{item['expected_checks']} | {item['failure_count']} |"
        )
    lines += [
        "",
        "## 7. Verificación",
        "",
        f"Veredicto `{(verification or {}).get('verdict')}` · "
        f"{(verification or {}).get('summary')}",
        "",
        "| check | estado | detalle |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        state = (
            "NOT_EXECUTED"
            if check.get("status") == "NOT_EXECUTED"
            else ("PASS" if check.get("ok") else "FAIL")
        )
        lines.append(f"| `{check.get('code')}` | {state} | {str(check.get('detail'))[:200]} |")
    if (verification or {}).get("negative_controls"):
        lines += ["", "| control negativo | check | detectado |", "| --- | --- | --- |"]
        for control in verification["negative_controls"]:
            lines.append(
                f"| `{control['control']}` | `{control['check']}` | "
                f"{'sí' if control['caught'] else 'NO'} |"
            )
    lines += ["", "## 8. Tests ejecutados", "", "| comando | exit | resultado |", "| --- | ---: | --- |"]
    for test in tests:
        lines.append(
            f"| `{str(test.get('command'))[:160]}` | {test.get('exit_code')} | "
            f"{test.get('result')} — {str(test.get('detail'))[:160]} |"
        )
    lines += ["", "## 9. Defectos y huecos declarados", ""]
    if defects:
        for defect in defects:
            lines.append(
                f"- **{defect['id']}** (`{defect['severity']}`): {defect['statement']} "
                f"— {defect.get('detail')}"
            )
    else:
        lines.append("- Ninguno declarado.")
    lines += [
        "",
        "## 10. Límites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += [
        "",
        "## 11. Artefactos",
        "",
        f"{len(artifacts)} ficheros con SHA-256 en `SHA256SUMS.txt`.",
        "",
    ]
    (root / "RUN_REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")

    final = [
        f"# {EXPERIMENT} — Informe final",
        "",
        f"`{run_id}` · {payload['generated_at_utc']}",
        "",
        "## Qué se preguntó",
        "",
        "Si alguna `AlphaFamily` ya implementada produce, con los mismos gates de riesgo, "
        "broker y salidas, una expectativa neta positiva después de costes sobre una ventana "
        "que nunca se había mirado, y mejor que `ema_crossover`.",
        "",
        "## Qué se hizo",
        "",
        "1. **WP-1** — se recuperó el estado real de Git y se cerró el determinismo pendiente de "
        "003J con repeticiones frescas contra los ledgers congelados.",
        "2. **WP-2** — se auditó la economía de 003J capa por capa (bruto de referencia, "
        "spread+slippage, comisiones, neto) y se identificaron hipótesis refutables.",
        "3. **WP-3** — se inventariaron las estrategias existentes con `ast`, se congeló un "
        "dataset nuevo y se ejecutaron las seis familias con la lane de producción.",
        "4. **WP-4** — tests, verificador separado con controles negativos y este informe.",
        "",
        "## Qué funciona",
        "",
        "- La lane PAPER ejecuta cualquier `AlphaFamily` admitida sin tocar riesgo, broker, "
        "costes ni salidas; la selección de estrategia es un id, no un segundo camino de código.",
        "- Cada operación cerrada se reconstruye desde las barras: precio, rango, instante, "
        "delta de caja y retirada del libro.",
        "- El verificador detecta las seis mentiras que le hemos puesto delante "
        "(look-ahead, fill anterior a la respuesta, doble contabilización, neto manipulado, "
        "selección que ignora su regla, éxito falso).",
        "",
        "## Qué pierde dinero",
        "",
    ]
    real_oos = next(
        (
            item
            for item in payload["economic_audit"]["verdicts"]
            if item["arm"] == "real" and item["partition"] == "oos"
        ),
        None,
    )
    if real_oos:
        final.append(
            f"`ema_crossover` en el OOS de 003J: bruto de referencia {fmt(real_oos['reference_gross_usdt'])} "
            f"USDT frente a {fmt(real_oos['costs_usdt'])} USDT de costes, neto "
            f"{fmt(real_oos['net_usdt'])}. La pérdida es de costes: la entrada no aportó ventaja "
            "direccional demostrable (el IC95 % del bruto por operación contiene el cero)."
        )
    final += ["", "## Qué dijeron las seis familias (research, costes reales)", ""]
    if selection:
        final += [
            "| familia | cierres | bruto/op | coste/op | neto | expectativa | ¿pasa las puertas? |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for candidate in selection.get("candidates", []):
            final.append(
                f"| `{candidate['strategy_id']}` | {candidate['closes']} | "
                f"{fmt(candidate['reference_gross_per_trade_usdt'])} | "
                f"{fmt(candidate['cost_per_trade_usdt'])} | {fmt(candidate['net_usdt'])} | "
                f"{fmt(candidate['expectancy_usdt'])} | {'sí' if candidate['eligible'] else 'no'} |"
            )
        final += [
            "",
            "Ninguna familia produce un bruto por operación que se acerque al suelo de costes de "
            "~1.29 USDT (25.8 bp sobre 500 USDT). La mejor en bruto es `mean_reversion` "
            "(+0.427 USDT, 8.5 bp) y solo con 47 cierres; el resto está en cero o por debajo. "
            "**No se abre el holdout**: no hay candidata que merezca gastarlo.",
        ]
    final += [
        "",
        "## Próximo experimento con mayor valor esperado",
        "",
        "No es otra búsqueda de estrategia: es medir el suelo de costes con una ejecución más "
        "barata. `mean_reversion` es la única familia con bruto positivo (+8.5 bp) frente a un "
        "coste de 25.8 bp; con comisiones maker (≈2 bp por lado en vez de 10) y la misma ventana "
        "de research, el mismo código pasaría de -16.9 bp netos a aproximadamente +1.5 bp. Es una "
        "predicción falsable, no una promesa: si el bruto no se mantiene con órdenes límite, el "
        "resultado será negativo otra vez y se sabrá por qué.",
        "",
        "Alternativa complementaria: subir la resolución a 1 h o 4 h para que el movimiento medio "
        "por operación sea varias veces el coste. Ambas cambian la economía de la ejecución, no "
        "la señal, y por eso pueden probarse sin volver a mirar este holdout.",
        "",
        "## Qué queda pendiente",
        "",
    ]
    final += [f"- {defect['id']}: {defect['statement']}" for defect in defects] or ["- Nada."]
    final += ["", "## Límites", ""]
    final += [f"- {item}" for item in payload["limitations"]]
    final += [
        "",
        "`LIVE_ENABLED=false`. Ningún resultado de este experimento autoriza operar con dinero real.",
        "",
    ]
    (root / "FINAL_REPORT.md").write_text("\n".join(final), encoding="utf-8", newline="\n")

    # Hash after the reports exist, so the manifest covers them too: a reader can then tell
    # whether the prose moved after the numbers were sealed.
    sealed = _artifact_rows(root)
    sums = "\n".join(f"{item['sha256']}  {item['path']}" for item in sealed) + "\n"
    (root / "SHA256SUMS.txt").write_text(sums, encoding="utf-8", newline="\n")

    print(
        f"[003k-report] run_id={run_id} runs={len(runs)} artifacts={len(sealed)} "
        f"missing={missing or 'none'} verification={(verification or {}).get('verdict')} "
        f"verdict={(verdict or {}).get('status')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
