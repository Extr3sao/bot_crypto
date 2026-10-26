"""DEF-RUN-019 / WP-018-03 — un run real que declara su commit antes de decidir.

DEF-RUN-018 reprodujo cada cifra de 017 y aun así tuvo que publicar
``original_commit = null``: la cabecera ``RUN`` no versionaba el código. Este script
ejecuta el mismo carril sobre datos reales de Binance con la cabecera nueva y demuestra
dos cosas con bytes, no con una promesa:

1. el ledger del run lleva el commit completo, el blob y el sha256 de cada fichero que
   ejecutó, escritos antes de la primera decisión;
2. registrar eso **no cambia ninguna decisión ni ninguna cifra**: el mismo replay se
   ejecuta dos veces —una con raíz de código real y otra con una raíz sin Git— y todas
   las filas posteriores a ``RUN`` deben coincidir, igual que el resumen del cierre.

No verifica su propio resultado. El dictamen lo emite
``scripts/def_run_018_verify_b.py``, que reimplementa la comprobación y no importa el
módulo que produce el bloque.

Uso::

    python scripts/def_run_019_provenance_run.py --execute
    python scripts/def_run_019_provenance_run.py --report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-019"
EVIDENCE = OUT / "evidence"
DATASET = REPO / "data" / "quote-feed-1m" / "UNIUSDT_1m_2021-01-04_2021-02-17.json"
SOURCE_MANIFEST = REPO / "data" / "quote-feed-1m" / "SOURCE_MANIFEST.json"
OOS_PLAN = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017" / "evidence" / "oos" / "OOS_PLAN.json"
SCHEMA = "DEF_RUN_019_PROVENANCE_V1"

SYMBOL = "UNI/USDT"
ARCHIVE = "UNIUSDT"
DAY_UTC = "2021-02-09"
MINUTE_MS = 60_000
DAY_MS = 86_400_000
WINDOW_BARS = 22
WARMUP_BARS = 40
DATA_DELAY_MS = 3_620
DECISION_EVERY_BARS = 1
MAX_OPINION_AGE_MS = 60_000
EQUITY_USDT = 10_000.0
#: Las dos ramas comparten `book_id` a propósito: cambia solo la raíz de código. Si el
#: identificador de la rama entrase en `position_id`, la comparación fila a fila mediría
#: el nombre de la carpeta además de la economía.
BOOK_ID = "def-run-019"
COST_MULTIPLIER = 1.0
LIFECYCLE = "DEFER"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def day_start_ms(day: str = DAY_UTC) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp() * 1000)


def load_minutes() -> list[list[float]]:
    rows: list[list[float]] = json.loads(DATASET.read_text(encoding="utf-8"))
    rows.sort(key=lambda row: int(row[0]))
    return rows


def bars_between(rows: list[list[float]], start_ms: int, end_ms: int) -> list[Any]:
    from trading_bot.research.economic_recovery.experiments import Bar

    return [
        Bar(
            ts_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
        if start_ms <= int(row[0]) < end_ms
    ]


def plan(rows: list[list[float]]) -> dict[str, Any]:
    start = day_start_ms()
    observed = sum(1 for row in rows if start <= int(row[0]) < start + DAY_MS)
    #: El sha256 de estos bytes no se recalcula desde cero: se contrasta con la partición
    #: que RFC-DEF-RUN-017 congeló *antes* de mirar los resultados (``OOS_PLAN.json``), y
    #: con los archivos de origen que declara ``SOURCE_MANIFEST.json``.
    declared: str | None = None
    if OOS_PLAN.is_file():
        frozen = json.loads(OOS_PLAN.read_text(encoding="utf-8"))
        declared = ((frozen.get("datasets") or {}).get(SYMBOL) or {}).get("sha256")
    manifest = (
        json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        if SOURCE_MANIFEST.is_file()
        else {}
    )
    archives = ((manifest.get("symbols") or {}).get(ARCHIVE) or {}).get("archives") or []
    digest = sha256_file(DATASET)
    return {
        "symbol": SYMBOL,
        "day_utc": DAY_UTC,
        "dataset": {
            "path": DATASET.relative_to(REPO).as_posix(),
            "sha256": digest,
            "rows": len(rows),
            "declared_sha256": declared,
            "matches_oos_plan": None if declared is None else declared == digest,
            "source_archives": [
                {"bytes": item.get("bytes"), "sha256": item.get("sha256")}
                for item in archives
                if isinstance(item, dict)
            ],
        },
        "minutes_expected": DAY_MS // MINUTE_MS,
        "minutes_observed": observed,
        "warmup_bars": WARMUP_BARS,
        "fixed": {
            "timeframe": "1m",
            "window_bars": WINDOW_BARS,
            "warmup_bars": WARMUP_BARS,
            "decision_every_bars": DECISION_EVERY_BARS,
            "data_delay_ms": DATA_DELAY_MS,
            "max_opinion_age_ms": MAX_OPINION_AGE_MS,
            "equity_usdt": EQUITY_USDT,
            "cost_multiplier": COST_MULTIPLIER,
            "opinion_lifecycle": LIFECYCLE,
            "signal_source": "strategy_experimental",
            "strategy_id": "ema_crossover",
            "risk_config": "config/risk.yaml (sin cambios)",
        },
        "variable": "code_root: el repositorio real frente a un directorio sin Git",
    }


def run_once(label: str, *, code_root: Path) -> dict[str, Any]:
    """Un replay real. Lo único que cambia entre las dos ramas es la raíz de código."""
    from trading_bot.config.settings import load_settings
    from trading_bot.vision.lane import VisionLane
    from trading_bot.vision.ledger import read_entries, verify_chain
    from trading_bot.vision.settings import load_vision_config
    from trading_bot.vision.signal_sources import build_signal_provider

    rows = load_minutes()
    start = day_start_ms()
    series = bars_between(rows, start - WARMUP_BARS * MINUTE_MS, start + DAY_MS)

    directory = EVIDENCE / label
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / f"{DAY_UTC}.jsonl"
    for stale in (ledger, ledger.with_suffix(".jsonl.lock")):
        if stale.exists():
            stale.unlink()

    base = load_vision_config(env={})
    config = base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1m",
            window_bars=WINDOW_BARS,
            decision_every_bars=DECISION_EVERY_BARS,
            max_calls_per_run=100_000,
            max_estimated_spend_usd=50.0,
            data_delay_ms=DATA_DELAY_MS,
            max_opinion_age_ms=MAX_OPINION_AGE_MS,
        ),
    )
    provider = build_signal_provider(
        "strategy_experimental",
        series={SYMBOL: series},
        timeframe="1m",
        interval_ms=MINUTE_MS,
        window_bars=WINDOW_BARS,
        latency_ms=0,
        trace_path=None,
        mode="PAPER",
        strategy_id="ema_crossover",
    )
    lane = VisionLane(
        series={SYMBOL: list(series)},
        provider=provider,
        config=config,
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        book_id=BOOK_ID,
        equity=EQUITY_USDT,
        decision_every_bars=DECISION_EVERY_BARS,
        cost_multiplier=COST_MULTIPLIER,
        opinion_lifecycle=LIFECYCLE,
        decision_from_ms=start,
        code_root=code_root,
    )
    lane.run()

    entries = [row["entry"] for row in read_entries(ledger)]
    closes = [entry for entry in entries if entry.get("kind") == "CLOSE"]
    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    deferred = [entry for entry in entries if entry.get("kind") == "OPINION_DEFERRED"]
    decisions = [entry for entry in entries if entry.get("kind") == "DECISION"]
    net = sum(Decimal(str(entry["pnl_net_usdt"])) for entry in closes)
    gross = sum(Decimal(str(entry["gross_pnl_usdt"])) for entry in closes)
    costs = sum(
        Decimal(str(entry["commissions_usdt"])) + Decimal(str(entry["execution_cost_usdt"]))
        for entry in closes
    )
    head: dict[str, Any] = next(
        (entry for entry in entries if entry.get("kind") == "RUN"), {}
    )
    block = head.get("code_provenance") or {}
    return {
        "label": label,
        "code_root": str(code_root),
        "ledger": ledger.relative_to(REPO).as_posix(),
        "ledger_sha256": sha256_file(ledger),
        "chain": verify_chain(ledger),
        "rows": len(entries),
        "bars": len(series),
        "decisions": len(decisions),
        "fills": len(fills),
        "closed_trades": len(closes),
        "deferred_slots": len(deferred),
        "net_pnl_usdt": str(net),
        "gross_pnl_usdt": str(gross),
        "costs_usdt": str(costs),
        "code_provenance": {
            "present": bool(block),
            "schema": block.get("schema"),
            "policy": block.get("policy"),
            "commit": block.get("commit"),
            "head_at_capture": block.get("head_at_capture"),
            "files_hashed": len(block.get("files") or {}),
            "missing_runtime_paths": block.get("missing_runtime_paths"),
            "runtime_dirty": (block.get("worktree") or {}).get("runtime_dirty"),
            "dirty_outside_runtime_total": (
                (block.get("worktree") or {}).get("dirty_outside_runtime_total")
            ),
            "unavailable_reasons": block.get("unavailable_reasons"),
        },
    }


def compare(provenance_ledger: Path, control_ledger: Path) -> dict[str, Any]:
    """¿El bloque de procedencia cambió una sola decisión? Compara las filas, no el resumen."""

    def entries(path: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line)["entry"]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    left, right = entries(provenance_ledger), entries(control_ledger)
    differences: list[dict[str, Any]] = []
    if len(left) != len(right):
        differences.append({"kind": "ROW_COUNT", "left": len(left), "right": len(right)})
    for index, (a, b) in enumerate(zip(left, right, strict=False), start=1):
        #: ``recorded_at_utc`` es hora de pared y por construcción difiere entre corridas.
        #: En la cabecera se descarta además el bloque que es, precisamente, la variable.
        a_clean = {key: value for key, value in a.items() if key != "recorded_at_utc"}
        b_clean = {key: value for key, value in b.items() if key != "recorded_at_utc"}
        if a.get("kind") == "RUN":
            a_clean.pop("code_provenance", None)
            b_clean.pop("code_provenance", None)
        if a_clean != b_clean:
            differing = sorted(
                key
                for key in set(a_clean) | set(b_clean)
                if a_clean.get(key) != b_clean.get(key)
            )
            differences.append({"seq": index, "kind": a.get("kind"), "keys": differing[:8]})
    return {
        "rows_left": len(left),
        "rows_right": len(right),
        "identical_except_header_and_clock": not differences,
        "differences": differences[:10],
    }


def preflight() -> tuple[bool, dict[str, Any]]:
    """Un run con el runtime sucio no es admisible: sus bytes no están en ningún commit."""
    from trading_bot.vision.provenance import capture

    block = capture(REPO)
    return (not block["unavailable_reasons"], block)


def execute() -> int:
    admissible, block = preflight()
    if not admissible:
        print(
            "refused: la procedencia del código no es admisible en este instante "
            f"(commit={block['commit']} motivos={block['unavailable_reasons']} "
            f"runtime_dirty={block['worktree']['runtime_dirty']})"
        )
        return 2
    rows = load_minutes()
    frozen = plan(rows)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="def019-control-") as sandbox:
        provenance = run_once("provenance", code_root=REPO)
        control = run_once("control", code_root=Path(sandbox))
        comparison = compare(REPO / provenance["ledger"], REPO / control["ledger"])

    economic_unchanged = (
        comparison["identical_except_header_and_clock"]
        and provenance["net_pnl_usdt"] == control["net_pnl_usdt"]
        and provenance["fills"] == control["fills"]
        and provenance["closed_trades"] == control["closed_trades"]
    )
    artifacts = {}
    for relative in (provenance["ledger"], control["ledger"]):
        target = REPO / relative
        artifacts[relative] = {"sha256": sha256_file(target), "bytes": target.stat().st_size}
    artifacts[frozen["dataset"]["path"]] = {
        "sha256": frozen["dataset"]["sha256"],
        "bytes": DATASET.stat().st_size,
    }
    payload = {
        "schema_version": SCHEMA,
        "generated_at_utc": utc_now(),
        "builder": "scripts/def_run_019_provenance_run.py",
        "plan": frozen,
        "preflight": {
            "commit": block["commit"],
            "policy": block["policy"],
            "files_hashed": len(block["files"]),
            "runtime_dirty": block["worktree"]["runtime_dirty"],
            "dirty_outside_runtime_total": block["worktree"]["dirty_outside_runtime_total"],
            "admissible": admissible,
        },
        "runs": {"provenance": provenance, "control": control},
        "comparison": comparison,
        "economics_unchanged_by_the_record": economic_unchanged,
        "artifacts": artifacts,
        "limits": [
            "un solo símbolo y un solo día: demuestra el registro, no una ventaja económica",
            "el proveedor es la señal determinista `strategy_experimental`, no un modelo real",
            "las horas de pared difieren entre las dos ramas por construcción; se excluyen",
        ],
    }
    target = OUT / "RUN_REPORT.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"commit={provenance['code_provenance']['commit']} "
        f"files={provenance['code_provenance']['files_hashed']} "
        f"fills={provenance['fills']} closes={provenance['closed_trades']} "
        f"net={provenance['net_pnl_usdt']} economics_unchanged={economic_unchanged}"
    )
    print(
        f"control_commit={control['code_provenance']['commit']} "
        f"control_reasons={control['code_provenance']['unavailable_reasons']} "
        f"rows={provenance['rows']}/{control['rows']}"
    )
    print(f"wrote {target}")
    return 0 if economic_unchanged and provenance["code_provenance"]["commit"] else 1


def report() -> int:
    payload = json.loads((OUT / "RUN_REPORT.json").read_text(encoding="utf-8"))
    verification_path = OUT / "evidence" / "SEALED_AND_NEW_LEDGER_B.json"
    negative_path = OUT / "evidence" / "NEGATIVE_CONTROL_B.json"
    verification = (
        json.loads(verification_path.read_text(encoding="utf-8"))
        if verification_path.is_file()
        else None
    )
    negative = (
        json.loads(negative_path.read_text(encoding="utf-8"))
        if negative_path.is_file()
        else None
    )
    provenance = payload["runs"]["provenance"]
    control = payload["runs"]["control"]
    lines = [
        "# DEF-RUN-019 — procedencia del código en la cabecera RUN",
        "",
        f"Generado: {utc_now()} · builder `scripts/def_run_019_provenance_run.py`",
        "",
        "## Qué se ejecutó",
        "",
        f"- Datos reales: `{payload['plan']['dataset']['path']}` "
        f"(sha256 `{payload['plan']['dataset']['sha256'][:16]}…`, "
        f"{payload['plan']['dataset']['rows']} filas, "
        f"{payload['plan']['minutes_observed']}/1440 minutos del día observados).",
        f"- Replay: `{SYMBOL}` {DAY_UTC}, 1m, ventana {WINDOW_BARS}, "
        f"decisión por barra, coste x{COST_MULTIPLIER}, ciclo `{LIFECYCLE}`.",
        "- Dos ramas idénticas; solo cambia la raíz de código: el repositorio y un directorio",
        "  sin Git.",
        "",
        "## Cabecera RUN del run con procedencia",
        "",
        f"- commit: `{provenance['code_provenance']['commit']}`",
        f"- política: `{provenance['code_provenance']['policy']}`",
        f"- ficheros hasheados: {provenance['code_provenance']['files_hashed']}",
        f"- runtime sucio: {provenance['code_provenance']['runtime_dirty']}",
        "- rutas sucias fuera del runtime: "
        f"{provenance['code_provenance']['dirty_outside_runtime_total']}",
        f"- cadena: {provenance['chain']['ok']} ({provenance['chain']['lines']} líneas)",
        "",
        "## La rama de control",
        "",
        f"- commit: `{control['code_provenance']['commit']}`",
        f"- motivos: {control['code_provenance']['unavailable_reasons']}",
        "",
        "## Economía: el registro no movió nada",
        "",
        "| Rama | decisions | fills | closes | deferred | net USDT | gross USDT | costs USDT |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| provenance | {provenance['decisions']} | {provenance['fills']} | "
        f"{provenance['closed_trades']} | {provenance['deferred_slots']} | "
        f"{provenance['net_pnl_usdt']} | {provenance['gross_pnl_usdt']} | "
        f"{provenance['costs_usdt']} |",
        f"| control | {control['decisions']} | {control['fills']} | {control['closed_trades']} | "
        f"{control['deferred_slots']} | {control['net_pnl_usdt']} | {control['gross_pnl_usdt']} | "
        f"{control['costs_usdt']} |",
        "",
        f"- filas idénticas salvo cabecera y reloj: "
        f"**{payload['comparison']['identical_except_header_and_clock']}** "
        f"({payload['comparison']['rows_left']} filas)",
        f"- diferencias: {payload['comparison']['differences']}",
        "",
        "## Verificación independiente (B)",
        "",
    ]
    if verification is None:
        lines.append("- pendiente: no se ejecutó `def_run_018_verify_b.py --ledger`.")
    else:
        domain = verification["run_provenance"]
        lines += [
            f"- veredicto del sujeto 017: `{verification['result']}` "
            f"({verification['checks_total']} comprobaciones)",
            f"- procedencia de código: `{domain['status']}` {domain['counts']} "
            f"({domain['checks_total']} comprobaciones)",
            f"- commit visto por B: "
            f"`{next((item.get('commit') for item in domain['ledgers'] if item['status'] == 'PASS'), None)}`",
            "- ledgers históricos sin bloque: "
            f"{domain['counts']['NOT_EVIDENCED']} (no se les rellena un commit)",
        ]
    lines += ["", "## Control negativo (B)", ""]
    if negative is None:
        lines.append("- pendiente.")
    else:
        domain = negative["run_provenance"]
        tampered = next((item for item in domain["ledgers"] if item["status"] == "FAIL"), {})
        lines += [
            f"- ledger con el commit alterado y la cadena recalculada: "
            f"`{domain['status']}` {domain['counts']}",
            f"- motivos: {tampered.get('reasons')}",
        ]
    lines += [
        "",
        "## Artefactos",
        "",
        "| Fichero | sha256 | bytes |",
        "| --- | --- | --- |",
    ]
    for relative, info in sorted(payload["artifacts"].items()):
        lines.append(f"| `{relative}` | `{info['sha256']}` | {info['bytes']} |")
    lines.append("")
    (OUT / "RUN_REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {OUT / 'RUN_REPORT.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="ejecuta las dos ramas del replay")
    parser.add_argument("--report", action="store_true", help="compone RUN_REPORT.md")
    args = parser.parse_args(argv)
    if args.report:
        return report()
    return execute()


if __name__ == "__main__":
    sys.exit(main())
