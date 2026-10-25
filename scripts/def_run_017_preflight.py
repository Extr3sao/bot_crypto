"""DEF-RUN-017 / WP-017-00 — preflight de solo lectura: ¿quién manda en el runtime?

Antes de reconstruir un euro hay que saber **qué código se ejecutó** y **si los bytes que lo
demuestran siguen existiendo**. Este script no escribe en el runtime, no importa
``trading_bot`` y no toca los ledgers: lee Git, hashea ficheros y publica tres artefactos.

1. ``RUNTIME_AUTHORITY_MAP.md`` — los entrypoints reales, qué módulos alcanza cada uno y qué
   etiqueta merece cada uno (``RUNTIME_AUTHORITATIVE``, ``RUNTIME_REACHABLE``, ``TEST_ONLY``,
   ``RESEARCH_ONLY``, ``EXPERIMENTAL``, ``LEGACY``, ``DEAD_CODE``).
2. ``BASELINE_LOCK.json`` — la identidad de BASELINE y CANDIDATE: commit, dataset, minutos,
   configuración por escenario, hashes de las fuentes de runtime y los números que cada
   captura declara. Si un campo no se puede comprobar, se escribe ``UNKNOWN``; nunca se
   rellena con una suposición.
3. ``PREFLIGHT_REPORT.md`` — el veredicto: ``PASS`` o ``BLOCKED_MISSING_EVIDENCE`` con la
   lista exacta de lo que falta.

Uso::

    python scripts/def_run_017_preflight.py \
        --out reports/ai-bots/RFC-DEF-RUN-017
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
RFC16 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-016"
RFC16_EVIDENCE = RFC16 / "evidence"
SCHEMA = "DEF_RUN_017_PREFLIGHT_V1"
REPORTED_COMMIT = "d05f8de"
SCENARIOS = ("m1_cadence1", "m1_cadence5", "m1_hole", "m1_zero_delay", "m3_cadence1")

#: Qué módulo hace qué, y con qué autoridad. La etiqueta es una afirmación verificable: se
#: apoya en los imports reales de ``vision/lane.py`` y en quién instancia ``VisionLane``.
RUNTIME_MAP: dict[str, tuple[str, str]] = {
    "src/trading_bot/vision/lane.py": (
        "RUNTIME_AUTHORITATIVE",
        "entrypoint del replay: decide, pide riesgo, ejecuta y escribe el ledger",
    ),
    "src/trading_bot/vision/execution.py": (
        "RUNTIME_AUTHORITATIVE",
        "precios de entrada/salida causales (apertura siguiente, stop intrabar, gap)",
    ),
    "src/trading_bot/vision/ledger.py": (
        "RUNTIME_AUTHORITATIVE",
        "cadena hash append-only que este RFC audita",
    ),
    "src/trading_bot/vision/chart.py": (
        "RUNTIME_AUTHORITATIVE",
        "renderiza el PNG que el proveedor recibe; su sha256 es la identidad de la opinión",
    ),
    "src/trading_bot/vision/clock.py": (
        "RUNTIME_AUTHORITATIVE",
        "cierre de barra y punto de información: la frontera point-in-time",
    ),
    "src/trading_bot/vision/contract.py": (
        "RUNTIME_AUTHORITATIVE",
        "contrato de la decisión (acción, stop, horizonte) y su parseo estricto",
    ),
    "src/trading_bot/vision/guards.py": (
        "RUNTIME_AUTHORITATIVE",
        "guardas pre-llamada; sus rechazos son opiniones terminales",
    ),
    "src/trading_bot/vision/prompt.py": (
        "RUNTIME_AUTHORITATIVE",
        "prompt determinista enviado con la imagen",
    ),
    "src/trading_bot/vision/provider.py": (
        "RUNTIME_AUTHORITATIVE",
        "interfaz del proveedor de visión",
    ),
    "src/trading_bot/vision/settings.py": (
        "RUNTIME_AUTHORITATIVE",
        "configuración del carril (timeframe, ventana, TTL, cadencia)",
    ),
    "src/trading_bot/vision/signal_sources.py": (
        "RUNTIME_REACHABLE",
        "proveedor `strategy_experimental` usado por el replay: la familia responde sobre las "
        "barras, no un modelo real",
    ),
    "src/trading_bot/paper/broker.py": (
        "RUNTIME_AUTHORITATIVE",
        "PaperBroker: rellenos, comisiones, stop/target y CLOSE con PnL",
    ),
    "src/trading_bot/risk/manager.py": (
        "RUNTIME_AUTHORITATIVE",
        "RiskManager: sizing, presupuesto de riesgo y el gate `stop_inside_costs`",
    ),
    "src/trading_bot/research/economic_recovery/alpha15.py": (
        "RUNTIME_REACHABLE",
        "`cost_for`: modelo de costes por tier que el carril cobra de verdad",
    ),
    "src/trading_bot/research/equity_drawdown.py": (
        "RUNTIME_REACHABLE",
        "máximo drawdown de la curva de equity del run",
    ),
    "src/trading_bot/paper/paper_cycle.py": (
        "RUNTIME_REACHABLE",
        "ciclo PAPER de 003G/015; no está en el camino de `VisionLane`, se ejecuta por "
        "`scripts/def_run_e2e_paper.py`",
    ),
    "scripts/def_run_016_audit.py": (
        "EXPERIMENTAL",
        "genera las capturas BASELINE/CANDIDATE de RFC-016 desde un worktree limpio",
    ),
    "scripts/def_run_016_verify.py": (
        "TEST_ONLY",
        "verificador independiente de RFC-016 (no importa `trading_bot`)",
    ),
    "src/trading_bot/vision/prospective.py": (
        "LEGACY",
        "sesión prospectiva de EXP-003J; conserva su propio camino y no interviene aquí",
    ),
    "src/trading_bot/intelligence/ai_bots/runner.py": (
        "LEGACY",
        "runner de bots previo a DEF-RUN; instancia el carril pero no participa en este replay",
    ),
}

DATASET_CANDIDATES = (
    "reports/ai-bots/DEF-RUN-PAPER/model-20261020T170635Z/market-1m/BTCUSDT.jsonl",
)
OOS_DATASET = "data/quote-feed-1m/SOURCE_MANIFEST.json"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        )
    except OSError:  # pragma: no cover - no git binary
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _git_bytes(args: list[str]) -> bytes | None:
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)
    return done.stdout if done.returncode == 0 else None


def stored_sha256(path: str, commit: str) -> str | None:
    """sha256 del objeto tal y como está guardado (LF, sin filtros)."""
    data = _git_bytes(["show", f"{commit}:{path}"])
    return None if data is None else hashlib.sha256(data).hexdigest()


def checkout_sha256(path: str, commit: str) -> str | None:
    """sha256 de los bytes que un checkout deja en disco (con ``core.autocrlf``).

    Es la única forma comparable con lo que un script hasheó al ejecutarse: el mismo
    fichero tiene dos hashes legítimos (objeto y checkout) y confundirlos convierte una
    coincidencia exacta en un falso ``MISMATCH``.
    """
    data = _git_bytes(["cat-file", "--filters", f"{commit}:{path}"])
    return None if data is None else hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_audit(manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, expected in sorted(manifest.get("evidence", {}).items()):
        path = REPO / relative
        if not path.is_file():
            missing.append(relative)
            rows.append({"path": relative, "state": "MISSING", "expected": expected})
            continue
        actual = sha256_file(path)
        state = "OK" if actual == expected.get("sha256") else "SHA256_MISMATCH"
        if state != "OK":
            mismatched.append(relative)
        rows.append(
            {
                "path": relative,
                "state": state,
                "bytes": path.stat().st_size,
                "expected_sha256": expected.get("sha256"),
                "actual_sha256": actual,
            }
        )
    return {
        "entries": len(rows),
        "missing": missing,
        "mismatched": mismatched,
        "rows": rows,
        "manifest_head": manifest.get("head"),
        "manifest_decision": manifest.get("decision"),
        "manifest_false_success": manifest.get("false_success"),
    }


def runtime_hashes(commit: str | None, captures: dict[str, Any]) -> dict[str, Any]:
    #: Las capturas guardan rutas de Windows (``src\\trading_bot\\...``); se normalizan
    #: antes de comparar para que el separador no decida el resultado.
    recorded: dict[str, dict[str, str | None]] = {}
    for path in RUNTIME_MAP:
        recorded[path] = {}
        for label in ("CURRENT", "PROPOSED"):
            declared = (captures.get(label) or {}).get("runtime_sha256") or {}
            recorded[path][label] = next(
                (value for key, value in declared.items() if key.replace("\\", "/") == path),
                None,
            )
    out: dict[str, Any] = {}
    for relative in RUNTIME_MAP:
        path = REPO / relative
        worktree = sha256_file(path) if path.is_file() else None
        checkout = checkout_sha256(relative, commit) if commit else None
        out[relative] = {
            "worktree_sha256": worktree,
            "checkout_sha256_at_audited_commit": checkout,
            "stored_blob_sha256_at_audited_commit": stored_sha256(relative, commit)
            if commit
            else None,
            "worktree_matches_audited_commit": worktree == checkout,
            "recorded_by_captures": recorded[relative],
        }
    return out


def capture_rows(label: str) -> dict[str, Any] | None:
    audit = load_json(RFC16_EVIDENCE / f"AUDIT_{label}.json")
    if audit is None:
        return None
    scenarios: dict[str, Any] = {}
    for name in SCENARIOS:
        declared = audit.get("scenarios", {}).get(name)
        if declared is None:
            continue
        metrics = declared.get("metrics", {})
        scenarios[name] = {
            "config": declared.get("config"),
            "dataset_bars": declared.get("series", {}).get("bars"),
            "dataset_bars_sha256": declared.get("series", {}).get("bars_sha256"),
            "declared_fills": metrics.get("fills"),
            "declared_calls": metrics.get("calls"),
            "declared_superseded": metrics.get("superseded"),
            "declared_deferred_slots": metrics.get("deferred_slots"),
            "declared_unrecorded": metrics.get("unrecorded"),
            "declared_duplicate_terminals": metrics.get("duplicate_terminals"),
            "published_ledger": f"reports/ai-bots/RFC-DEF-RUN-016/evidence/ledgers/{label}/{name}.jsonl",
        }
    return {
        "label": label,
        "commit": audit.get("commit"),
        "dirty_worktree": audit.get("dirty"),
        "lifecycle": audit.get("lifecycle"),
        "dataset": audit.get("dataset"),
        "runtime_sha256": audit.get("runtime_sha256"),
        "scenarios": scenarios,
    }


def dataset_state() -> dict[str, Any]:
    out: dict[str, Any] = {"minutes": {}, "oos": {}}
    for relative in DATASET_CANDIDATES:
        path = REPO / relative
        out["minutes"][relative] = (
            {"exists": True, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            if path.is_file()
            else {"exists": False}
        )
    manifest = load_json(REPO / OOS_DATASET)
    if manifest is not None:
        for _symbol, entry in sorted(manifest.get("symbols", {}).items()):
            relative = f"data/quote-feed-1m/{entry['file']}"
            path = REPO / relative
            actual = sha256_file(path) if path.is_file() else None
            out["oos"][relative] = {
                "exists": path.is_file(),
                "rows": entry.get("rows"),
                "declared_file_sha256": entry.get("file_sha256"),
                "actual_sha256": actual,
                "matches": actual == entry.get("file_sha256"),
                "first_minute_ms": entry.get("first_minute_ms"),
                "last_minute_ms": entry.get("last_minute_ms"),
                "source": entry.get("source"),
                "archives": [a.get("url") for a in entry.get("archives", [])],
            }
    return out


def build(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    status = [line for line in git("status", "--porcelain").splitlines() if line]
    commit_exists = git("cat-file", "-t", REPORTED_COMMIT) == "commit"
    ancestor = commit_exists and (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", REPORTED_COMMIT, "HEAD"],
            cwd=REPO,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    full_commit = git("rev-parse", REPORTED_COMMIT) if commit_exists else None

    manifest = load_json(RFC16_EVIDENCE / "ARTIFACT_MANIFEST.json")
    evidence = evidence_audit(manifest) if manifest else {"entries": 0, "rows": [],
                                                          "missing": ["ARTIFACT_MANIFEST.json"],
                                                          "mismatched": []}
    baseline = capture_rows("CURRENT")
    candidate = capture_rows("PROPOSED")
    data = dataset_state()

    # Los cinco ledgers de cada captura son la fuente primaria de este RFC: si falta uno,
    # no hay comparación que certificar.
    missing_ledgers = [
        f"ledgers/{label}/{name}.jsonl"
        for label in ("CURRENT", "PROPOSED")
        for name in SCENARIOS
        if not (RFC16_EVIDENCE / "ledgers" / label / f"{name}.jsonl").is_file()
    ]

    blocking: list[str] = []
    if not commit_exists:
        blocking.append(f"commit {REPORTED_COMMIT} no existe en el repositorio")
    elif not ancestor:
        blocking.append(f"commit {REPORTED_COMMIT} no es ancestro de HEAD")
    if manifest is None:
        blocking.append("falta ARTIFACT_MANIFEST.json de RFC-016")
    blocking.extend(f"evidencia ausente: {path}" for path in evidence["missing"])
    blocking.extend(f"sha256 no coincide: {path}" for path in evidence["mismatched"])
    blocking.extend(f"ledger ausente: {path}" for path in missing_ledgers)
    if baseline is None or candidate is None:
        blocking.append("faltan AUDIT_CURRENT.json / AUDIT_PROPOSED.json de RFC-016")
    for relative, state in data["oos"].items():
        if not state["exists"]:
            blocking.append(f"dataset OOS ausente: {relative}")
        elif not state["matches"]:
            blocking.append(f"dataset OOS con sha256 distinto del manifiesto: {relative}")

    identity_mismatch: list[str] = []
    if baseline and candidate:
        if baseline.get("dataset", {}).get("minutes_sha256") != candidate.get(
            "dataset", {}
        ).get("minutes_sha256"):
            identity_mismatch.append("BASELINE y CANDIDATE no usan los mismos minutos")
        if baseline.get("lifecycle") == candidate.get("lifecycle"):
            identity_mismatch.append(
                "las dos capturas declaran el mismo lifecycle: no hay variable investigada"
            )
        for name in SCENARIOS:
            left = baseline["scenarios"].get(name, {}).get("dataset_bars_sha256")
            right = candidate["scenarios"].get(name, {}).get("dataset_bars_sha256")
            if left != right:
                identity_mismatch.append(f"{name}: la serie de barras no es la misma")
    blocking.extend(identity_mismatch)

    #: Dos defectos de procedencia que sí se pueden demostrar desde los bytes publicados.
    #: No bloquean la reconstrucción (los ledgers dicen qué configuración corrió), pero
    #: impiden presentar esas capturas como "dos commits distintos".
    hashes = runtime_hashes(full_commit, {"CURRENT": baseline, "PROPOSED": candidate})
    ambiguous = [
        path
        for path, row in hashes.items()
        if row["recorded_by_captures"]["CURRENT"]
        and row["recorded_by_captures"]["CURRENT"]
        == row["recorded_by_captures"]["PROPOSED"]
    ]
    pre_rfc_lane = checkout_sha256("src/trading_bot/vision/lane.py", "4ea93d8")
    provenance = [
        {
            "id": "DEF-017-01",
            "finding": "AUDIT_*.runtime_sha256 describe el árbol en el momento de escribir "
            "el informe, no el módulo importado: ambas capturas declaran los mismos hashes "
            "aunque una corre en SUPERSEDE y otra en DEFER",
            "affected_paths": ambiguous,
            "consequence": "el campo no sirve para atribuir código; la identidad real está "
            "en la fila RUN del ledger (opinion_lifecycle) y en lane_module_sha256",
            "blocking": False,
        },
        {
            "id": "DEF-017-02",
            "finding": "AUDIT_*.commit = 4ea93d8 es el HEAD del repositorio, pero el carril "
            "importado era el árbol de trabajo cuyo contenido equivale a d05f8de "
            "(checkout sha256 = 617e544a para lane.py)",
            "baseline_label_is_not_historical_code": True,
            "pre_rfc_lane_checkout_sha256": pre_rfc_lane,
            "capture_lane_checkout_sha256": (baseline or {}).get("lane_module_sha256")
            or hashes["src/trading_bot/vision/lane.py"]["recorded_by_captures"]["CURRENT"],
            "consequence": "BASELINE no es el código histórico anterior a RFC-016: es el "
            "mismo carril nuevo forzado a SUPERSEDE. La variable investigada es el "
            "conmutador de ciclo de vida, no el conjunto del RFC",
            "blocking": False,
        },
    ]

    status_value = "PASS" if not blocking else "BLOCKED_MISSING_EVIDENCE"
    lock = {
        "schema_version": SCHEMA,
        "rfc": "RFC-DEF-RUN-017",
        "work_package": "WP-017-00",
        "generated_at_utc": utc_now(),
        "repository": {
            "branch": branch,
            "head": head,
            "reported_commit": REPORTED_COMMIT,
            "reported_commit_full": full_commit,
            "reported_commit_is_ancestor_of_head": bool(ancestor),
            "head_subject": git("log", "-1", "--pretty=%s"),
            "uncommitted_paths": len(status),
            "uncommitted_sample": status[:25],
        },
        "baseline": baseline,
        "candidate": candidate,
        "comparability": {
            "same_minutes": (baseline or {}).get("dataset", {}).get("minutes_sha256")
            == (candidate or {}).get("dataset", {}).get("minutes_sha256"),
            "variable_investigated": "vision.lane opinion lifecycle (SUPERSEDE vs DEFER)",
            "declared_confounds": [
                "el carril cambia también cuántas llamadas pagadas se hacen (815 -> 730); "
                "no es una ablación de una sola instrucción",
                "el proveedor es determinista y simulado: model_mode=NOT_CALLED",
                "una sola sesión de 256 minutos de un solo símbolo",
            ],
            "identity_violations": identity_mismatch,
            "provenance_findings": provenance,
        },
        "runtime_authority": {
            "map": {path: {"label": label, "why": why} for path, (label, why) in RUNTIME_MAP.items()},
            "hashes": runtime_hashes(
                full_commit, {"CURRENT": baseline, "PROPOSED": candidate}
            ),
        },
        "evidence": evidence,
        "datasets": data,
        "blocking": blocking,
        "status": status_value,
    }
    (out_dir / "BASELINE_LOCK.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    map_lines = [
        "# RUNTIME_AUTHORITY_MAP — RFC-DEF-RUN-017",
        "",
        f"Generado: `{lock['generated_at_utc']}` · rama `{branch}` · HEAD `{head}` · "
        f"commit auditado `{full_commit}`.",
        "",
        "Criterio: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > "
        "ASSUMPTION`. La etiqueta de cada módulo se apoya en los imports de "
        "`src/trading_bot/vision/lane.py` y en qué script instancia `VisionLane`.",
        "",
        "## Entrypoints reales",
        "",
        "| Entrypoint | Qué ejecuta | Estado |",
        "| --- | --- | --- |",
        "| `scripts/def_run_016_audit.py` | replay determinista de `VisionLane` sobre barras, "
        "con `strategy_experimental` y el broker/risk reales | ejecutado en RFC-016 |",
        "| `scripts/def_run_017_oos.py` | mismo carril sobre datos OOS congelados | este RFC |",
        "| `scripts/def_run_e2e_paper.py` | ciclo PAPER de `paper_cycle.py` | fuera del camino "
        "de `VisionLane` |",
        "| `src/trading_bot/intelligence/ai_bots/runner.py` | runner previo (LEGACY) | no usado |",
        "",
        "## Módulos y autoridad",
        "",
        "| Módulo | Etiqueta | Por qué |",
        "| --- | --- | --- |",
    ]
    for path, (label, why) in RUNTIME_MAP.items():
        map_lines.append(f"| `{path}` | **{label}** | {why} |")
    map_lines += [
        "",
        "## Lo que este mapa NO afirma",
        "",
        "- No afirma que `strategy_experimental` sea un modelo de visión: es una familia "
        "determinista que responde sobre las mismas barras. `model_mode = NOT_CALLED`.",
        "- No afirma que el pipeline sea el de producción: `live` está prohibido en este RFC "
        "y ningún proceso de este análisis abre una conexión de exchange.",
        "",
        "## Hashes de runtime",
        "",
        "| Módulo | sha256 del checkout en el commit auditado | sha256 en el árbol de trabajo | ¿Iguales? |",
        "| --- | --- | --- | --- |",
    ]
    for path, row in lock["runtime_authority"]["hashes"].items():
        map_lines.append(
            f"| `{path}` | `{row['checkout_sha256_at_audited_commit'] or 'AUSENTE'}` | "
            f"`{row['worktree_sha256'] or 'AUSENTE'}` | "
            f"{'sí' if row['worktree_matches_audited_commit'] else 'no'} |"
        )
    map_lines.append("")
    (out_dir / "RUNTIME_AUTHORITY_MAP.md").write_text(
        "\n".join(map_lines), encoding="utf-8", newline="\n"
    )

    report_lines = [
        "# PREFLIGHT_REPORT — RFC-DEF-RUN-017 (WP-017-00)",
        "",
        f"- **Estado:** `{status_value}`",
        f"- **Generado:** `{lock['generated_at_utc']}`",
        f"- **Rama:** `{branch}` · **HEAD:** `{head}`",
        f"- **Commit reportado por RFC-016:** `{REPORTED_COMMIT}` "
        f"({full_commit or 'no existe'}), ancestro de HEAD: "
        f"`{'sí' if ancestor else 'no'}`",
        f"- **Rutas modificadas en el árbol de trabajo:** {len(status)} "
        "(ajenas a este RFC, intactas)",
        "",
        "## Evidencia de RFC-016",
        "",
        f"- Manifiesto: {evidence['entries']} artefactos; ausentes "
        f"{len(evidence['missing'])}; sha256 alterados {len(evidence['mismatched'])}.",
        f"- Ledgers publicados: {10 - len(missing_ledgers)}/10.",
        "",
        "| Artefacto | Estado | bytes | sha256 |",
        "| --- | --- | ---: | --- |",
    ]
    for row in evidence["rows"]:
        report_lines.append(
            f"| `{row['path']}` | {row['state']} | {row.get('bytes', 0)} | "
            f"`{(row.get('actual_sha256') or '')[:16]}` |"
        )
    report_lines += [
        "",
        "## Comparabilidad BASELINE / CANDIDATE",
        "",
        "| Campo | BASELINE (`CURRENT`) | CANDIDATE (`PROPOSED`) |",
        "| --- | --- | --- |",
        f"| lifecycle | `{(baseline or {}).get('lifecycle')}` | "
        f"`{(candidate or {}).get('lifecycle')}` |",
        f"| commit | `{(baseline or {}).get('commit')}` | `{(candidate or {}).get('commit')}` |",
        f"| worktree sucio | `{(baseline or {}).get('dirty_worktree')}` | "
        f"`{(candidate or {}).get('dirty_worktree')}` |",
        f"| minutos sha256 | `{(baseline or {}).get('dataset', {}).get('minutes_sha256')}` | "
        f"`{(candidate or {}).get('dataset', {}).get('minutes_sha256')}` |",
        "",
        "Los dos escenarios **no** son dos commits: son el mismo commit con el módulo del carril "
        "sustituido en el árbol de trabajo para la captura CANDIDATE. La variable investigada "
        "es el ciclo de vida de la opinión; el precio pagado por ella es que también cambia "
        "cuántas llamadas se hacen.",
        "",
        "## Datos",
        "",
        "| Fichero | Existe | sha256 coincide con el manifiesto |",
        "| --- | --- | --- |",
    ]
    for relative, state in data["minutes"].items():
        report_lines.append(
            f"| `{relative}` | {state['exists']} | n/a (no hay manifiesto de minutos) |"
        )
    for relative, state in data["oos"].items():
        report_lines.append(
            f"| `{relative}` | {state['exists']} | {state['matches']} |"
        )
    report_lines += [
        "",
        "## Bloqueos",
        "",
    ]
    report_lines += [f"- {item}" for item in blocking] or ["- ninguno"]
    report_lines += [
        "",
        "## Consecuencia",
        "",
        "La identidad de ambos escenarios queda fijada por `BASELINE_LOCK.json`. Con el estado "
        f"`{status_value}`, la reconstrucción económica puede continuar sobre los bytes "
        "publicados; cualquier artefacto que falte en una reejecución posterior será "
        "`BLOCKED`, nunca regenerado en silencio.",
        "",
    ]
    (out_dir / "PREFLIGHT_REPORT.md").write_text(
        "\n".join(report_lines), encoding="utf-8", newline="\n"
    )

    print(f"status={status_value} blocking={len(blocking)} evidence={evidence['entries']}")
    for item in blocking:
        print(f"  BLOCKED: {item}")
    return 0 if status_value == "PASS" else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/ai-bots/RFC-DEF-RUN-017")
    args = parser.parse_args(argv)
    return build(REPO / args.out)


if __name__ == "__main__":
    sys.exit(main())
