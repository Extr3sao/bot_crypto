"""DEF-RUN-018 / WP-018-03 — verificador B: reclasificar 017 desde sus bytes.

Este fichero no importa `def_run_017_verify`, ni `trading_bot.vision.economic_audit`, ni
ningún módulo del Builder. Reconstruye la contabilidad leyendo los JSONL y los CSV con
`json`, `csv` y `hashlib` de la biblioteca estándar. Compartir el *contrato* (qué es un
ledger, cómo se encadena, qué regla decide) es obligatorio; compartir el *código* de
recomputación destruiría la independencia que el RFC exige.

Qué no hace: no reescribe nada bajo `reports/ai-bots/RFC-DEF-RUN-017/`. Solo lee y emite
su propio dictamen. Un `PASS` aquí significa que **B** reprodujo las cifras; no significa
que la estrategia gane dinero.

Estados por comprobación: `PASS`, `FAIL`, `BLOCKED`, `UNRECOMPUTABLE`. La ausencia de un
artefacto crítico nunca produce `PASS`.

Uso::

    python scripts/def_run_018_verify_b.py
    python scripts/def_run_018_verify_b.py --root . --json out/INDEPENDENT_VERIFICATION.json
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = "DEF_RUN_018_INDEPENDENT_VERIFICATION_V1"
SUBJECT = "RFC-DEF-RUN-017"
TOL = Decimal("0.000001")
GENESIS = "0" * 64
SYMBOLS = ("AAVE/USDT", "UNI/USDT")
SEED = 17017
RESAMPLES = 2000


# --------------------------------------------------------------------------- utils


def num(value: Any) -> Decimal:
    return Decimal(str(value))


def same(left: Any, right: Any, tol: Decimal = TOL) -> bool:
    return abs(num(left) - num(right)) <= tol


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> tuple[Any, str | None]:
    if not path.is_file():
        return None, f"MISSING:{path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as error:
        return None, f"BAD_JSON:{error}"


def read_rows(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not path.is_file():
        return [], f"MISSING:{path}"
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except json.JSONDecodeError as error:
        return rows, f"BAD_JSON:{error}"
    return rows, None


def read_csv(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.is_file():
        return [], f"MISSING:{path}"
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle)), None


def check(code: str, state: str, detail: str, **extra: Any) -> dict[str, Any]:
    assert state in ("PASS", "FAIL", "BLOCKED", "UNRECOMPUTABLE")
    return {"code": code, "state": state, "detail": detail, **extra}


# --------------------------------------------------------------------------- ledger


def recompute_chain(rows: list[dict[str, Any]]) -> tuple[bool, str, str]:
    """Recalcula el encadenado desde cero. No llama a `trading_bot.vision.ledger`."""
    previous = GENESIS
    for index, row in enumerate(rows, start=1):
        entry = row.get("entry")
        if not isinstance(entry, dict):
            return False, f"NO_ENTRY_AT_{index}", previous
        if int(row.get("seq", -1)) != index:
            return False, f"SEQ_GAP_AT_{index}", previous
        if str(row.get("prev_sha256")) != previous:
            return False, f"BROKEN_LINK_AT_{index}", previous
        payload = json.dumps(
            {"seq": index, "prev_sha256": previous, "entry": entry},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if digest != str(row.get("sha256")):
            return False, f"TAMPERED_LINE_{index}", previous
        previous = digest
    return True, "INTACT", previous


def ledger_facts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Todo lo contable que el resumen afirma, derivado de la cadena."""
    entries = [row.get("entry") or {} for row in rows]
    kinds = Counter(str(entry.get("kind", "?")) for entry in entries)
    closes = [entry for entry in entries if entry.get("kind") == "CLOSE"]
    run_end = next((entry for entry in reversed(entries) if entry.get("kind") == "RUN_END"), None)
    net = sum((num(entry.get("pnl_net_usdt", 0)) for entry in closes), Decimal(0))
    gross = sum((num(entry.get("gross_pnl_usdt", 0)) for entry in closes), Decimal(0))
    fees = sum((num(entry.get("commissions_usdt", 0)) for entry in closes), Decimal(0))
    execution = sum((num(entry.get("execution_cost_usdt", 0)) for entry in closes), Decimal(0))
    return {
        "kinds": dict(kinds),
        "lines": len(entries),
        "fills": kinds.get("FILL", 0),
        "closed_trades": len(closes),
        "deferred_slots": kinds.get("OPINION_DEFERRED", 0),
        "net": net,
        "gross": gross,
        "fees": fees,
        "execution": execution,
        "costs": fees + execution,
        "run_end": run_end,
        "chain_head": str(rows[-1].get("sha256")) if rows else GENESIS,
        "close_days": sorted({str(entry.get("day_utc")) for entry in closes}),
    }


# --------------------------------------------------------------------------- procedencia

PROVENANCE_METHODS = ("DIRECT", "LEDGER_RECONSTRUCTION")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def series_digest(rows: Iterable[Iterable[Any]]) -> str:
    """Huella del dataset tal como la declara la cabecera `RUN`, reimplementada aquí.

    No se importa `trading_bot.vision.lane.series_digest`: validar la huella con la
    función que la produjo no sería verificar, sería repetirse.
    """
    payload = json.dumps(
        [
            [
                int(row[0]),
                round(float(row[1]), 8),
                round(float(row[2]), 8),
                round(float(row[3]), 8),
                round(float(row[4]), 8),
                round(float(row[5]), 8),
            ]
            for row in rows
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_ms(stamp: str) -> int:
    return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1000)


def provenance_reasons(
    run: dict[str, Any],
    rows: list[dict[str, Any]],
    dataset: list[list[Any]] | None,
    artifact_resumes: list[dict[str, Any]] | None,
) -> list[str]:
    """Motivos por los que la procedencia de un run **no** queda demostrada.

    La lista vacía es la única señal de PASS. Un run directo solo necesita hora de
    inicio real. Un run reconstruido desde el ledger —lo que 017 marcó con
    `resumed_from_ledger=true`— necesita enlazar su resumen con la cabecera `RUN`, el
    cierre `RUN_END`, la cadena y el dataset, y declarar el acto de reanudación con su
    commit. Ninguna comprobación se satisface por el nombre de un campo.
    """
    entries = [row.get("entry") or {} for row in rows]
    head = next((entry for entry in entries if entry.get("kind") == "RUN"), None)
    end = next((entry for entry in reversed(entries) if entry.get("kind") == "RUN_END"), None)
    reasons: list[str] = []
    if run.get("started_at_utc") is None:
        reasons.append("start=None")
    if run.get("resumed_from_ledger"):
        #: El marcador de 017 no demostraba nada: sin bloque no hay enlace al origen.
        reasons.append("legacy_resume_marker_without_provenance")
    provenance = run.get("provenance")
    if provenance is None:
        if artifact_resumes:
            reasons.append("artifact_declares_resume_but_run_has_no_provenance")
        return reasons
    if not isinstance(provenance, dict):
        return [*reasons, "provenance_not_an_object"]
    method = provenance.get("method")
    if method not in PROVENANCE_METHODS:
        reasons.append(f"method={method!r}")
    if head is None or end is None:
        return [*reasons, "ledger_without_RUN_or_RUN_END"]
    if provenance.get("run_id") != head.get("book_id"):
        reasons.append("run_id")
    if provenance.get("started_at_utc") != head.get("recorded_at_utc"):
        reasons.append("started_at_utc")
    if provenance.get("finished_at_utc") != end.get("recorded_at_utc"):
        reasons.append("finished_at_utc")
    if run.get("started_at_utc") != head.get("recorded_at_utc"):
        reasons.append("run_started_at_utc")
    if run.get("finished_at_utc") != end.get("recorded_at_utc"):
        reasons.append("run_finished_at_utc")
    chain = provenance.get("chain") or {}
    if int(chain.get("rows", -1)) != len(rows):
        reasons.append("chain_rows")
    if str(chain.get("head_sha256")) != str(rows[-1].get("sha256")):
        reasons.append("chain_head")
    if int(chain.get("run_end_seq", -1)) != int(rows[-1].get("seq", -1)):
        reasons.append("run_end_seq")
    if chain.get("ok") is not True:
        reasons.append("chain_ok")
    declared = provenance.get("dataset")
    if declared != head.get("dataset"):
        reasons.append("dataset_block")
    elif dataset is not None and isinstance(declared, dict):
        info = declared.get(str(run.get("symbol"))) or {}
        if not info:
            reasons.append("dataset_symbol")
        else:
            first = to_ms(str(info.get("first_open_utc")))
            count = int(info.get("bars", -1))
            window = [row for row in dataset if int(row[0]) >= first][:count]
            if len(window) != count:
                reasons.append("dataset_bars")
            elif series_digest(window) != str(info.get("sha256")):
                reasons.append("dataset_sha256")
            elif int(window[-1][0]) != to_ms(str(info.get("last_open_utc"))):
                reasons.append("dataset_last_open")
    config = {
        "lane": head.get("lane"),
        "provider": head.get("provider"),
        "risk_policy": head.get("risk_policy"),
        "cost_multiplier": head.get("cost_multiplier"),
        "equity_usdt": head.get("equity_usdt"),
    }
    if (
        str(provenance.get("config_sha256"))
        != hashlib.sha256(canonical(config).encode("utf-8")).hexdigest()
    ):
        reasons.append("config_sha256")
    if provenance.get("config") != config:
        reasons.append("config_block")
    resumes = provenance.get("resumes")
    if method == "LEDGER_RECONSTRUCTION":
        if not isinstance(resumes, list) or not resumes:
            reasons.append("resume_history_missing")
        elif artifact_resumes is not None and resumes != artifact_resumes:
            reasons.append("resume_history_disagrees_with_artifact")
    elif resumes not in ([], None):
        reasons.append("direct_run_has_resume_history")
    if isinstance(resumes, list) and resumes:
        if [int(item.get("attempt", 0)) for item in resumes] != list(range(1, len(resumes) + 1)):
            reasons.append("resume_attempt_sequence")
        stamps = [str(item.get("at_utc")) for item in resumes]
        if stamps != sorted(stamps):
            reasons.append("resume_timestamps_not_monotonic")
        commits = [str(item.get("at_commit") or "") for item in resumes]
        if any(
            len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit)
            for commit in commits
        ):
            reasons.append("resume_commit_missing")
    original = provenance.get("original_commit")
    source = str(provenance.get("original_commit_source") or "")
    if original is None:
        if not source:
            reasons.append("original_commit_source_missing")
    elif len(str(original)) != 40 or not source:
        reasons.append("original_commit_invalid")
    return reasons


# --------------------------------------------------------------------------- stats


def bootstrap(values: list[float], seed: int = SEED, resamples: int = RESAMPLES) -> dict[str, Any]:
    """Remuestreo por bloques (el día es el bloque), escrito aquí desde el método congelado."""
    if not values:
        return {"samples": 0, "mean": None, "ci95": None}
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        draw = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(draw) / len(draw))
    means.sort()
    return {
        "samples": len(values),
        "mean": round(sum(values) / len(values), 6),
        "ci95": [
            round(means[int(0.025 * len(means))], 6),
            round(means[int(0.975 * len(means)) - 1], 6),
        ],
        "days_positive": sum(1 for value in values if value > 0),
        "days_negative": sum(1 for value in values if value < 0),
        "days_flat": sum(1 for value in values if value == 0),
        "resamples": resamples,
        "seed": seed,
    }


def classify(
    net_defer: dict[str, float],
    net_supersede: dict[str, float],
    expectancy_defer: dict[str, float | None],
    ci95: dict[str, list[float] | None],
    symbols: Iterable[str],
) -> dict[str, bool | str]:
    symbols = tuple(symbols)
    better = all(net_defer[symbol] > net_supersede[symbol] for symbol in symbols)
    worse = all(net_defer[symbol] < net_supersede[symbol] for symbol in symbols)
    excludes = all(
        ci95.get(symbol) and (ci95[symbol][1] < 0 or ci95[symbol][0] > 0)  # type: ignore[index]
        for symbol in symbols
    )
    positive = all((expectancy_defer.get(symbol) or 0) > 0 for symbol in symbols)
    if better and excludes and positive:
        status = "EVIDENCED"
    elif worse and excludes:
        status = "NEGATIVE"
    elif not symbols:
        status = "INCONCLUSIVE"
    else:
        status = "NOT_EVIDENCED"
    return {
        "defer_better_in_both": better,
        "defer_worse_in_both": worse,
        "ci95_excludes_zero_in_both": excludes,
        "defer_expectancy_positive_in_both": positive,
        "economic_status": status,
    }


# --------------------------------------------------------------------------- verifier


def resolve_ledger(run: dict[str, Any], runs_root: Path) -> Path | None:
    raw = str(run.get("ledger") or "").replace("\\", "/")
    candidates: list[Path] = []
    if "runs/" in raw:
        candidates.append(runs_root / "runs" / raw.split("runs/", 1)[1])
    symbol = str(run.get("symbol", "")).replace("/", "")
    guess = (
        runs_root
        / "runs"
        / symbol
        / str(run.get("lifecycle", "")).lower()
        / f"cost-{float(run.get('cost_multiplier', 1.0)):.1f}"
        / f"{run.get('day_utc')}.jsonl"
    )
    candidates.append(guess)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def verify(
    root: Path,
    *,
    evidence: Path | None = None,
    runs_root: Path | None = None,
    rfc16: Path | None = None,
    rfc17_data: Path | None = None,
) -> dict[str, Any]:
    evidence = evidence or root / "reports" / "ai-bots" / SUBJECT / "evidence"
    rfc17_data = rfc17_data or root / "data" / "def-run-017"
    rfc16 = rfc16 or root / "data" / "def-run-016"
    runs_root = runs_root or evidence / "oos"
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    diffs: list[dict[str, Any]] = []

    # -- 1. plan congelado ---------------------------------------------------
    plan, error = read_json(evidence / "oos" / "OOS_PLAN.json")
    plan_hash = (
        sha256(evidence / "oos" / "OOS_PLAN.json")
        if (evidence / "oos" / "OOS_PLAN.json").is_file()
        else None
    )
    results, results_error = read_json(evidence / "oos" / "OOS_RESULTS.json")
    checks.append(
        check(
            "PLAN_PRESENT",
            "PASS" if plan is not None else "BLOCKED",
            error or "OOS_PLAN.json leído",
        )
    )
    checks.append(
        check(
            "REPORT_PRESENT",
            "PASS" if results is not None else "BLOCKED",
            results_error or "OOS_RESULTS.json leído",
        )
    )
    if results is None:
        return {
            "schema_version": SCHEMA,
            "result": "BLOCKED",
            "checks": checks,
            "errors": [results_error or "OOS_RESULTS.json ausente"],
            "independence": independence(),
        }
    assert plan is not None
    checks.append(
        check(
            "PLAN_HASH_FROZEN",
            "PASS" if str(results.get("plan_sha256")) == str(plan_hash) else "FAIL",
            f"publicado={results.get('plan_sha256')} recalculado={plan_hash}",
        )
    )
    checks.append(
        check(
            "PLAN_BOOTSTRAP_PARAMS",
            "PASS" if int(plan.get("bootstrap_resamples", 0)) == RESAMPLES else "FAIL",
            f"resamples={plan.get('bootstrap_resamples')} esperado={RESAMPLES}",
        )
    )
    checks.append(
        check(
            "PLAN_PARTITION_DECLARED",
            "PASS"
            if plan.get("executed_partition") == "untouched_test"
            and results.get("partition") == "untouched_test"
            else "FAIL",
            f"plan={plan.get('executed_partition')} resultados={results.get('partition')}",
        )
    )

    dataset_state = "PASS"
    dataset_detail: list[str] = []
    bars_by_symbol: dict[str, list[list[Any]]] = {}
    for symbol, declared in (plan.get("datasets") or {}).items():
        path = root / declared["path"]
        if not path.is_file():
            dataset_state = "BLOCKED"
            dataset_detail.append(f"{symbol}: MISSING")
            continue
        digest = sha256(path)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        bars = len(loaded)
        bars_by_symbol[symbol] = sorted(loaded, key=lambda row: int(row[0]))
        if digest != declared["sha256"] or bars != int(declared["rows"]):
            dataset_state = "FAIL"
        dataset_detail.append(f"{symbol}: sha256={digest[:12]} bars={bars}")
    checks.append(
        check("DATASETS_MATCH_PLAN", dataset_state, "; ".join(dataset_detail) or "sin datasets")
    )

    # -- 2. cada run, desde su ledger ---------------------------------------
    runs_payload, runs_error = read_json(evidence / "oos" / "OOS_RUNS_untouched_test.json")
    if runs_payload is None:
        checks.append(check("OOS_RUNS_PRESENT", "BLOCKED", runs_error or "ausente"))
        runs: list[dict[str, Any]] = []
    else:
        runs = list(runs_payload.get("runs") or [])
        checks.append(check("OOS_RUNS_PRESENT", "PASS", f"{len(runs)} runs declaradas"))

    recomputed: dict[tuple[str, str, float, str], dict[str, Any]] = {}
    deferred_failures: list[str] = []
    provenance_losses: list[str] = []
    zeroed_metadata: list[str] = []
    artifact_resumes = runs_payload.get("resumes") if runs_payload else None
    for run in runs:
        key = (
            str(run.get("symbol")),
            str(run.get("lifecycle")),
            float(run.get("cost_multiplier", 1.0)),
            str(run.get("day_utc")),
        )
        tag = "|".join(str(part) for part in key)
        path = resolve_ledger(run, runs_root)
        if path is None:
            checks.append(check(f"LEDGER_PRESENT_{tag}", "BLOCKED", "ledger no encontrado"))
            continue
        rows, row_error = read_rows(path)
        if row_error:
            checks.append(check(f"LEDGER_READ_{tag}", "BLOCKED", row_error))
            continue
        digest = sha256(path)
        checks.append(
            check(
                f"LEDGER_HASH_{tag}",
                "PASS" if digest == run.get("ledger_sha256") else "FAIL",
                f"publicado={run.get('ledger_sha256')} recalculado={digest}",
            )
        )
        intact, reason, _head = recompute_chain(rows)
        checks.append(check(f"CHAIN_{tag}", "PASS" if intact else "FAIL", reason))
        facts = ledger_facts(rows)
        if facts["run_end"] is None:
            checks.append(check(f"RUN_END_{tag}", "FAIL", "sin RUN_END"))
            continue
        facts["ledger"] = str(path)
        facts["key"] = key
        day_start_ms = int(
            datetime.fromisoformat(str(run.get("day_utc"))).replace(tzinfo=UTC).timestamp() * 1000
        )
        observed_minutes = sum(
            1
            for row in bars_by_symbol.get(str(run.get("symbol")), [])
            if day_start_ms <= int(row[0]) < day_start_ms + 86_400_000
        )
        facts["missing_minutes"] = 1440 - observed_minutes
        checks.append(
            check(
                f"MISSING_MINUTES_{tag}",
                "PASS"
                if facts["missing_minutes"] == int(run.get("missing_minutes", -1))
                else "FAIL",
                f"dataset={facts['missing_minutes']} publicado={run.get('missing_minutes')}",
            )
        )
        recomputed[key] = facts
        losses = provenance_reasons(
            run, rows, bars_by_symbol.get(str(run.get("symbol"))), artifact_resumes
        )
        if losses:
            provenance_losses.append(
                f"{tag}: start={run.get('started_at_utc')} bars={run.get('bars')} "
                f"observed={run.get('minutes_observed')} reasons={','.join(losses)}"
            )
        expected_minutes = int(run.get("minutes_expected", 1440) or 1440)
        if int(run.get("bars", -1) or 0) <= 0 or int(run.get("minutes_observed", 0) or 0) > (
            expected_minutes
        ):
            zeroed_metadata.append(
                f"{tag}: bars={run.get('bars')} observed={run.get('minutes_observed')}/"
                f"{expected_minutes}"
            )

        checks.append(
            check(
                f"DEFERRED_FROM_LEDGER_{tag}",
                "PASS"
                if str(facts["run_end"].get("deferred_slots_source", ""))
                == "ledger:OPINION_DEFERRED"
                or facts["deferred_slots"] == int(run.get("deferred_slots", -1))
                else "FAIL",
                f"ledger={facts['deferred_slots']} publicado={run.get('deferred_slots')}",
            )
        )
        if facts["deferred_slots"] != int(run.get("deferred_slots", -1)):
            deferred_failures.append(tag)
            diffs.append(
                {
                    "code": "DEFERRED_SLOT_MISMATCH",
                    "run": tag,
                    "ledger": facts["deferred_slots"],
                    "published": run.get("deferred_slots"),
                }
            )
        checks.append(
            check(
                f"FILLS_FROM_LEDGER_{tag}",
                "PASS" if facts["fills"] == int(run.get("fills", -1)) else "FAIL",
                f"ledger={facts['fills']} publicado={run.get('fills')}",
            )
        )
        checks.append(
            check(
                f"CLOSED_FROM_LEDGER_{tag}",
                "PASS" if facts["closed_trades"] == int(run.get("closed_trades", -1)) else "FAIL",
                f"ledger={facts['closed_trades']} publicado={run.get('closed_trades')}",
            )
        )
        checks.append(
            check(
                f"NET_FROM_LEDGER_{tag}",
                "PASS" if same(facts["net"], run.get("net_pnl_usdt")) else "FAIL",
                f"ledger={facts['net']} publicado={run.get('net_pnl_usdt')}",
            )
        )
        checks.append(
            check(
                f"GROSS_FROM_LEDGER_{tag}",
                "PASS" if same(facts["gross"], run.get("gross_pnl_usdt")) else "FAIL",
                f"ledger={facts['gross']} publicado={run.get('gross_pnl_usdt')}",
            )
        )
        checks.append(
            check(
                f"COSTS_IDENTITY_{tag}",
                "PASS"
                if same(facts["gross"] - facts["net"], facts["fees"])
                and same(facts["costs"], run.get("costs_usdt"))
                else "FAIL",
                f"bruto-neto={facts['gross'] - facts['net']} comisiones={facts['fees']} "
                f"costes={facts['costs']} publicado={run.get('costs_usdt')}",
            )
        )
        run_end_net = facts["run_end"].get("net_realised_usdt")
        checks.append(
            check(
                f"RUN_END_RECONCILES_{tag}",
                "PASS" if run_end_net is not None and same(run_end_net, facts["net"]) else "FAIL",
                f"RUN_END={run_end_net} suma_CLOSE={facts['net']}",
            )
        )
        checks.append(
            check(
                f"DAY_DECLARED_{tag}",
                "PASS"
                if not facts["close_days"] or facts["close_days"] == [str(run.get("day_utc"))]
                else "FAIL",
                f"CLOSE days={facts['close_days']} fichero={run.get('day_utc')}",
            )
        )

    checks.append(
        check(
            "RUN_PROVENANCE_COMPLETE",
            "PASS" if not provenance_losses else "FAIL",
            "; ".join(provenance_losses[:4])
            or "cada run enlaza su ledger: run_id, inicio, cierre, dataset, configuración, "
            "cadena y acto de reanudación",
        )
    )
    if runs:
        checks.append(
            check(
                "RUN_SET_COMPLETE",
                "PASS" if len(recomputed) == len(runs) == 32 else "FAIL",
                f"recomputadas={len(recomputed)} declaradas={len(runs)} esperadas=32",
            )
        )

    # -- 3. agregados por celda ---------------------------------------------
    cells = results.get("cells") or {}
    by_cell: dict[str, dict[str, Any]] = {}
    for (symbol, lifecycle, multiplier, _day), facts in recomputed.items():
        cell_key = f"{symbol}|{lifecycle}|{multiplier:.1f}"
        cell = by_cell.setdefault(
            cell_key,
            {
                "symbol": symbol,
                "lifecycle": lifecycle,
                "cost_multiplier": multiplier,
                "days": 0,
                "fills": 0,
                "closed_trades": 0,
                "calls": 0,
                "deferred_slots": 0,
                "missing_minutes": 0,
                "net": Decimal(0),
                "gross": Decimal(0),
                "fees": Decimal(0),
            },
        )
        cell["days"] += 1
        for field in ("fills", "closed_trades", "deferred_slots"):
            cell[field] += int(facts[field])
        cell["calls"] += int(facts["run_end"].get("calls", 0) or 0)
        cell["missing_minutes"] += int(facts.get("missing_minutes", 0))
        cell["net"] += facts["net"]
        cell["gross"] += facts["gross"]
        cell["fees"] += facts["fees"]

    expected_cells = {
        f"{symbol}|{lifecycle}|1.0" for symbol in SYMBOLS for lifecycle in ("DEFER", "SUPERSEDE")
    }
    absent_cells = sorted(expected_cells - set(cells))
    checks.append(
        check(
            "EXPECTED_CELLS_PRESENT",
            "PASS" if not absent_cells else "UNRECOMPUTABLE",
            "faltan: " + ", ".join(absent_cells) if absent_cells else "4 celdas primarias",
        )
    )
    for cell_key, published in sorted(cells.items()):
        mine = by_cell.get(cell_key)
        if mine is None:
            checks.append(
                check(
                    f"CELL_{cell_key}",
                    "UNRECOMPUTABLE",
                    "no hay ledgers para esta celda",
                )
            )
            diffs.append({"code": "CELL_MISSING", "cell": cell_key})
            continue
        problems = []
        for field, mine_key in (
            ("fills", "fills"),
            ("closed_trades", "closed_trades"),
            ("deferred_slots", "deferred_slots"),
            ("calls", "calls"),
            ("days", "days"),
            ("missing_minutes", "missing_minutes"),
            ("net_pnl_usdt", "net"),
            ("gross_pnl_usdt", "gross"),
        ):
            if not same(mine[mine_key], published.get(field)):
                problems.append(
                    f"{field}: ledger={mine[mine_key]} publicado={published.get(field)}"
                )
        expectancy = num(published.get("net_pnl_usdt", 0)) / max(
            1, int(published.get("closed_trades", 1) or 1)
        )
        if not same(expectancy, published.get("expectancy_usdt")):
            problems.append(
                f"expectancy: recalculada={expectancy} publicada={published.get('expectancy_usdt')}"
            )
        checks.append(
            check(
                f"CELL_{cell_key}",
                "PASS" if not problems else "FAIL",
                "; ".join(problems) or f"{mine['days']} días, net={mine['net']}",
            )
        )
        if problems:
            diffs.append({"code": "CELL_MISMATCH", "cell": cell_key, "problems": problems})

    defer_cells = {k: v for k, v in cells.items() if "|DEFER|" in k}
    checks.append(
        check(
            "DEFER_CELLS_HAVE_DEFERRALS",
            "PASS"
            if defer_cells
            and all(int(value.get("deferred_slots", 0)) > 0 for value in defer_cells.values())
            else "FAIL",
            "; ".join(f"{k}={v.get('deferred_slots')}" for k, v in sorted(defer_cells.items()))
            or "sin celdas DEFER",
        )
    )

    # -- 4. delta pareado y bootstrap ---------------------------------------
    per_day: dict[tuple[str, str], dict[str, float]] = {}
    for (symbol, lifecycle, multiplier, day), facts in recomputed.items():
        if multiplier != 1.0:
            continue
        per_day.setdefault((symbol, day), {})[lifecycle] = float(facts["net"])
    published_deltas = results.get("paired_day_deltas") or {}
    delta_check = "PASS"
    delta_detail: list[str] = []
    for symbol in SYMBOLS:
        values = [
            pair["DEFER"] - pair["SUPERSEDE"]
            for (sym, _day), pair in sorted(per_day.items())
            if sym == symbol and {"DEFER", "SUPERSEDE"} <= set(pair)
        ]
        published = published_deltas.get(symbol) or {}
        recomputed_boot = bootstrap(values)
        ok = (
            len(values) == len(published.get("per_day_usdt") or [])
            and all(
                same(mine, theirs, Decimal("0.000001"))
                for mine, theirs in zip(
                    [round(value, 8) for value in values],
                    published.get("per_day_usdt") or [],
                    strict=True,
                )
            )
            and same(recomputed_boot.get("mean"), published.get("mean"))
            and all(
                abs(float(a) - float(b)) <= 1e-6
                for a, b in zip(
                    recomputed_boot.get("ci95") or [0, 0],
                    published.get("ci95") or [0, 0],
                    strict=True,
                )
            )
            and int(published.get("seed", 0)) == SEED
            and int(published.get("resamples", 0)) == RESAMPLES
        )
        if not ok:
            delta_check = "FAIL"
            diffs.append(
                {
                    "code": "BOOTSTRAP_MISMATCH",
                    "symbol": symbol,
                    "recomputed": recomputed_boot,
                    "published": published,
                }
            )
        delta_detail.append(
            f"{symbol}: mean={recomputed_boot['mean']} ci95={recomputed_boot['ci95']} "
            f"n={len(values)}"
        )
        per_day[(symbol, "deltas")] = {"values": values}  # type: ignore[assignment]
    checks.append(check("PAIRED_DELTA_AND_BOOTSTRAP", delta_check, "; ".join(delta_detail)))

    # -- 5. regla de decisión ------------------------------------------------
    published_decision = results.get("decision") or {}
    net_def = {}
    net_sup = {}
    expectancy_def: dict[str, float | None] = {}
    ci95 = {}
    for symbol in SYMBOLS:
        cell_def = by_cell.get(f"{symbol}|DEFER|1.0") or {}
        cell_sup = by_cell.get(f"{symbol}|SUPERSEDE|1.0") or {}
        net_def[symbol] = float(cell_def.get("net", 0))
        net_sup[symbol] = float(cell_sup.get("net", 0))
        expectancy_def[symbol] = (
            float(cell_def["net"]) / int(cell_def["closed_trades"])
            if int(cell_def.get("closed_trades", 0) or 0)
            else None
        )
        ci95[symbol] = (published_deltas.get(symbol) or {}).get("ci95")
    reapplied = classify(net_def, net_sup, expectancy_def, ci95, SYMBOLS)
    matched = (
        all(
            reapplied[key] == published_decision.get(key)
            for key in reapplied
            if key in published_decision
        )
        and published_decision.get("economic_status") == reapplied["economic_status"]
    )
    checks.append(
        check(
            "DECISION_RULE_REAPPLIED",
            "PASS" if matched else "FAIL",
            f"reaplicada={reapplied['economic_status']} "
            f"publicada={published_decision.get('economic_status')}",
        )
    )
    if not matched:
        diffs.append(
            {
                "code": "DECISION_RULE_MISMATCH",
                "recomputed": reapplied,
                "published": published_decision,
            }
        )

    # -- 6. estrés x2 --------------------------------------------------------
    stress, stress_error = read_json(evidence / "oos" / "OOS_STRESS_COST2.json")
    stress_runs, _ = read_json(evidence / "oos" / "OOS_RUNS_untouched_test_cost2.json")
    checks.append(
        check(
            "STRESS_PRESENT",
            "PASS" if stress is not None and stress_runs is not None else "BLOCKED",
            stress_error or "estrés leído",
        )
    )
    if stress is not None and stress_runs is not None:
        declared_runs = list(stress_runs.get("runs") or [])
        cost2: dict[tuple[str, str, float, str], dict[str, Any]] = {}
        stress_problems: list[str] = []
        for run in declared_runs:
            stress_key = (
                str(run.get("symbol")),
                str(run.get("lifecycle")),
                float(run.get("cost_multiplier", 2.0)),
                str(run.get("day_utc")),
            )
            path = resolve_ledger(run, runs_root)
            if path is None:
                stress_problems.append(f"MISSING {stress_key}")
                continue
            rows, row_error = read_rows(path)
            if row_error:
                stress_problems.append(f"READ {stress_key}: {row_error}")
                continue
            intact, reason, _head = recompute_chain(rows)
            if not intact:
                stress_problems.append(f"CHAIN {stress_key}: {reason}")
                continue
            if sha256(path) != run.get("ledger_sha256"):
                stress_problems.append(f"HASH {stress_key}")
                continue
            cost2[stress_key] = ledger_facts(rows)
        checks.append(
            check(
                "STRESS_LEDGERS_RECOMPUTED",
                "PASS" if not stress_problems else "FAIL",
                "; ".join(stress_problems[:4]) or f"{len(cost2)} ledgers",
            )
        )
        checks.append(
            check(
                "STRESS_RUN_COUNT",
                "PASS" if int(stress.get("runs", 0)) == len(declared_runs) == 16 else "FAIL",
                f"declarado={stress.get('runs')} runs={len(declared_runs)}",
            )
        )
        checks.append(
            check(
                "STRESS_POST_HOC_FLAG",
                "PASS"
                if stress.get("used_for_decision") is False and stress.get("cost_multiplier") == 2.0
                else "FAIL",
                f"used_for_decision={stress.get('used_for_decision')} "
                f"multiplier={stress.get('cost_multiplier')}",
            )
        )
        checks.append(
            check(
                "STRESS_AFTER_PRIMARY",
                "PASS"
                if str(stress.get("generated_at_utc", ""))
                > str(results.get("generated_at_utc", ""))
                else "FAIL",
                f"estres={stress.get('generated_at_utc')} primario={results.get('generated_at_utc')}",
            )
        )
        pairs: dict[tuple[str, str], dict[str, float]] = {}
        for (symbol, lifecycle, _multiplier, day), facts in cost2.items():
            if symbol != "UNI/USDT":
                continue
            pairs.setdefault((symbol, day), {})[lifecycle] = float(facts["net"])
        values = [
            pair["DEFER"] - pair["SUPERSEDE"]
            for (_symbol, _day), pair in sorted(pairs.items())
            if {"DEFER", "SUPERSEDE"} <= set(pair)
        ]
        recomputed_boot = bootstrap(values)
        published_stress = (stress.get("paired_day_deltas") or {}).get("UNI/USDT") or {}
        stress_ok = (
            len(values) == 8
            and all(
                abs(float(a) - float(b)) <= 1e-6
                for a, b in zip(
                    recomputed_boot.get("ci95") or [0, 0],
                    published_stress.get("ci95") or [0, 0],
                    strict=True,
                )
            )
            and same(recomputed_boot.get("mean"), published_stress.get("mean"))
        )
        checks.append(
            check(
                "STRESS_DELTA_RECOMPUTED",
                "PASS" if stress_ok else "FAIL",
                f"media={recomputed_boot.get('mean')} ci95={recomputed_boot.get('ci95')}",
            )
        )
        cost2_def = next(
            (value for key, value in cost2.items() if key[1] == "DEFER" and key[0] == "UNI/USDT"),
            None,
        )
        cost2_sup = next(
            (
                value
                for key, value in cost2.items()
                if key[1] == "SUPERSEDE" and key[0] == "UNI/USDT"
            ),
            None,
        )
        net_def_c2 = sum(
            (
                value["net"]
                for key, value in cost2.items()
                if key[1] == "DEFER" and key[0] == "UNI/USDT"
            ),
            Decimal(0),
        )
        net_sup_c2 = sum(
            (
                value["net"]
                for key, value in cost2.items()
                if key[1] == "SUPERSEDE" and key[0] == "UNI/USDT"
            ),
            Decimal(0),
        )
        stress_decision = classify(
            {"UNI/USDT": float(net_def_c2)},
            {"UNI/USDT": float(net_sup_c2)},
            {"UNI/USDT": None},
            {"UNI/USDT": published_stress.get("ci95")},
            ("UNI/USDT",),
        )
        checks.append(
            check(
                "STRESS_STATUS_REAPPLIED",
                "PASS"
                if stress_decision["economic_status"] == stress.get("stress_status")
                else "FAIL",
                f"reaplicada={stress_decision['economic_status']} declarada={stress.get('stress_status')} "
                f"def={net_def_c2} sup={net_sup_c2}",
            )
        )
        del cost2_def, cost2_sup

    # -- 7. RFC-016: la cifra -8.116 sale de aquí ----------------------------
    attribution, attribution_error = read_json(evidence / "ECONOMIC_ATTRIBUTION.json")
    if attribution is None:
        checks.append(check("ATTRIBUTION_PRESENT", "BLOCKED", attribution_error or "ausente"))
    else:
        totals = attribution.get("totals") or {}
        per_scenario = attribution.get("per_scenario") or {}
        net_by_label: dict[str, Decimal] = {"baseline": Decimal(0), "candidate": Decimal(0)}
        fees_by_label: dict[str, Decimal] = {"baseline": Decimal(0), "candidate": Decimal(0)}
        gross_by_label: dict[str, Decimal] = {"baseline": Decimal(0), "candidate": Decimal(0)}
        close_index: dict[tuple[str, str], dict[str, Any]] = {}
        problems: list[str] = []
        for label, folder in (("baseline", "CURRENT"), ("candidate", "PROPOSED")):
            for scenario in sorted(per_scenario):
                path = rfc16 / "ledgers" / folder / f"{scenario}.jsonl"
                rows, row_error = read_rows(path)
                if row_error:
                    problems.append(f"{label}/{scenario}: {row_error}")
                    continue
                intact, reason, _head = recompute_chain(rows)
                if not intact:
                    problems.append(f"{label}/{scenario}: {reason}")
                facts = ledger_facts(rows)
                net_by_label[label] += facts["net"]
                fees_by_label[label] += facts["fees"]
                gross_by_label[label] += facts["gross"]
                declared = per_scenario[scenario]
                if not same(facts["net"], declared[f"{label}_net_usdt"]):
                    problems.append(
                        f"{label}/{scenario}: net ledger={facts['net']} "
                        f"publicado={declared[f'{label}_net_usdt']}"
                    )
                for row in rows:
                    entry = row.get("entry") or {}
                    if entry.get("kind") == "CLOSE":
                        close_index[(label, str(entry.get("position_id")))] = entry
        checks.append(
            check(
                "RFC16_LEDGER_RECOMPUTATION",
                "PASS" if not problems else "FAIL",
                "; ".join(problems[:6]) or f"{len(per_scenario)} escenarios x 2 etiquetas",
            )
        )
        for label in ("baseline", "candidate"):
            checks.append(
                check(
                    f"RFC16_TOTAL_{label.upper()}",
                    "PASS"
                    if same(net_by_label[label], totals.get(f"{label}_net_usdt"))
                    and same(fees_by_label[label], totals.get(f"{label}_fees_usdt"))
                    and same(gross_by_label[label], totals.get(f"{label}_gross_usdt"))
                    else "FAIL",
                    f"net={net_by_label[label]} (pub {totals.get(f'{label}_net_usdt')}) "
                    f"fees={fees_by_label[label]} gross={gross_by_label[label]}",
                )
            )
        delta_net = net_by_label["candidate"] - net_by_label["baseline"]
        checks.append(
            check(
                "ATTRIBUTION_DELTA",
                "PASS"
                if same(delta_net, totals.get("delta_net_usdt"))
                and same(
                    delta_net,
                    num(totals.get("delta_gross_usdt")) - num(totals.get("delta_fees_usdt")),
                )
                else "FAIL",
                f"candidato-baseline={delta_net} publicado={totals.get('delta_net_usdt')}",
            )
        )
        trade_rows, _trade_error = read_csv(evidence / "TRADE_LEDGER.csv")
        trade_problems: list[str] = []
        sums: dict[str, Decimal] = {"baseline": Decimal(0), "candidate": Decimal(0)}
        for trade in trade_rows:
            close = close_index.get((str(trade.get("label")), str(trade.get("position_id"))))
            if close is None:
                trade_problems.append(f"sin CLOSE para {trade.get('position_id')}")
                continue
            label = str(trade.get("label"))
            if label not in sums:
                trade_problems.append(f"label desconocida {label}")
                continue
            sums[label] += num(trade.get("realized_pnl_quote", 0))
            if not same(trade.get("realized_pnl_quote"), close.get("pnl_net_usdt")):
                trade_problems.append(f"pnl {trade.get('position_id')}")
            if not same(trade.get("fees_quote"), close.get("commissions_usdt")):
                trade_problems.append(f"fees {trade.get('position_id')}")
            if not same(trade.get("gross_pnl_quote"), close.get("gross_pnl_usdt")):
                trade_problems.append(f"gross {trade.get('position_id')}")
        if len(close_index) != len(trade_rows):
            trade_problems.append(f"{len(close_index)} CLOSE frente a {len(trade_rows)} filas")
        checks.append(
            check(
                "TRADE_LEDGER_FROM_CLOSES",
                "PASS" if not trade_problems else "FAIL",
                "; ".join(trade_problems[:6]) or f"{len(trade_rows)} filas",
            )
        )
        paired_rows, paired_error = read_csv(evidence / "PAIRED_DELTA.csv")
        per_scenario_sum: dict[str, Decimal] = {}
        for row in paired_rows:
            scenario = str(row.get("scenario"))
            per_scenario_sum[scenario] = per_scenario_sum.get(scenario, Decimal(0)) + num(
                row.get("realized_delta", 0)
            )
        mismatch = [
            scenario
            for scenario, value in per_scenario_sum.items()
            if not same(value, per_scenario.get(scenario, {}).get("observed_delta_usdt"))
        ]
        checks.append(
            check(
                "PAIRED_DELTA_ROWS_RECONCILE",
                "PASS" if not mismatch and len(paired_rows) == 16 else "FAIL",
                f"filas={len(paired_rows)} discrepan={mismatch[:4]}",
            )
        )
        del paired_error

    # -- 8. manifiestos ------------------------------------------------------
    manifest_problems: list[str] = []
    manifests = (
        (evidence / "ARTIFACT_MANIFEST.json", evidence.parent.parent.parent.parent),
        (rfc17_data / "ARTIFACT_MANIFEST.json", rfc17_data),
        (rfc16 / "ARTIFACT_MANIFEST.json", rfc16),
    )
    verified = 0
    for manifest_path, base in manifests:
        payload, error = read_json(manifest_path)
        if payload is None:
            manifest_problems.append(error or f"manifest ausente {manifest_path}")
            continue
        for relative, declared in (payload.get("artifacts") or {}).items():
            candidates = [base / relative, manifest_path.parent / relative]
            target = next((path for path in candidates if path.is_file()), None)
            if target is None:
                manifest_problems.append(f"MISSING {relative}")
                continue
            if sha256(target) != declared.get("sha256"):
                manifest_problems.append(f"HASH {relative}")
            verified += 1
    checks.append(
        check(
            "ARTIFACT_MANIFESTS",
            "PASS" if not manifest_problems else "FAIL",
            "; ".join(manifest_problems[:6]) or f"{verified} artefactos hasheados",
        )
    )

    # -- dictamen ------------------------------------------------------------
    states = Counter(item["state"] for item in checks)
    #: Un insumo ausente manda sobre los fallos que su ausencia provoca: BLOCKED es la
    #: lectura honesta de «no se puede recomputar», no un FAIL que parezca una discrepancia.
    if states["BLOCKED"]:
        result = "BLOCKED"
    elif states["FAIL"] or states["UNRECOMPUTABLE"]:
        result = "FAIL"
    else:
        result = "PASS"
    return {
        "schema_version": SCHEMA,
        "run_id": f"def-run-018-b-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subject": SUBJECT,
        "independence": independence(),
        "input_hashes": {
            "oos_plan": plan_hash,
            "oos_results": sha256(evidence / "oos" / "OOS_RESULTS.json")
            if (evidence / "oos" / "OOS_RESULTS.json").is_file()
            else None,
            "datasets": {
                symbol: sha256(root / declared["path"])
                for symbol, declared in (plan.get("datasets") or {}).items()
                if (root / declared["path"]).is_file()
            },
        },
        "recomputed_metrics": {
            "cells": {
                key: {
                    "net_pnl_usdt": str(value["net"]),
                    "gross_pnl_usdt": str(value["gross"]),
                    "fees_usdt": str(value["fees"]),
                    "fills": value["fills"],
                    "closed_trades": value["closed_trades"],
                    "deferred_slots": value["deferred_slots"],
                    "calls": value["calls"],
                    "days": value["days"],
                }
                for key, value in sorted(by_cell.items())
            },
            "decision": reapplied,
            "runs_recomputed": len(recomputed),
            "deferred_runs_with_mismatch": deferred_failures,
        },
        "expected_metrics": {
            "decision": published_decision.get("economic_status"),
            "cells": sorted(cells),
        },
        "differences": diffs,
        "defects": [
            *(
                [
                    {
                        "code": "RUN_PROVENANCE_INCOMPLETE",
                        "severity": "P1",
                        "economic_effect": "none_observed",
                        "detail": (
                            "Hay runs cuyo resumen no se puede enlazar con el ledger que los "
                            "produjo: falta el acto de reanudación, el run_id, la ventana del "
                            "dataset, la configuración o la cabeza de la cadena. 017 los marcó "
                            "con `resumed_from_ledger=true` y nada más, así que su origen no "
                            "era demostrable aunque su economía fuese correcta."
                        ),
                        "runs": provenance_losses,
                    }
                ]
                if provenance_losses
                else []
            ),
            *(
                [
                    {
                        "code": "RECOUNT_ZEROED_RUN_METADATA",
                        "severity": "P2",
                        "economic_effect": "none_observed",
                        "detail": (
                            "`result_from_ledger` publicó `bars=0` y contó líneas `DECISION` "
                            "como minutos observados (1441 en un día de 1440). La economía es "
                            "correcta; la cobertura publicada no. El camino de código ya "
                            "deriva cobertura y procedencia del ledger y del dataset, pero el "
                            "artefacto sellado de 017 conserva los valores antiguos y no se "
                            "reescribe."
                        ),
                        "runs": zeroed_metadata,
                    }
                ]
                if zeroed_metadata
                else []
            ),
        ],
        "bootstrap_seed": SEED,
        "bootstrap_resamples": RESAMPLES,
        "economic_delta": {
            "symbols": {
                symbol: {
                    "net_defer_usdt": str(by_cell.get(f"{symbol}|DEFER|1.0", {}).get("net", 0)),
                    "net_supersede_usdt": str(
                        by_cell.get(f"{symbol}|SUPERSEDE|1.0", {}).get("net", 0)
                    ),
                }
                for symbol in SYMBOLS
            }
        },
        "oos_decision": published_decision.get("economic_status"),
        "stress_classification": {
            "status": (stress or {}).get("stress_status"),
            "used_for_decision": (stress or {}).get("used_for_decision"),
            "confirmatory": False,
        },
        "controls": checks,
        "summary": dict(states),
        "checks_total": len(checks),
        "result": result,
        "errors": errors,
        "limitations": [
            "no reejecuta el runtime: lee los bytes del repliegue congelado",
            "los ledgers llevan hora de pared, así que su sha256 no es reproducible entre corridas",
            "la paridad de métricas económicas se exige a 1e-6; los sha256 se exigen exactos",
        ],
    }


def imported_modules(source: str) -> set[str]:
    """Imports reales del fuente: `Import`/`ImportFrom` con sus alias, vía `ast`.

    Buscar cadenas no medía dependencias: «from trading_bot» aparecía en la prosa de
    este fichero y bastaba para publicar `imports_trading_bot=true` en un verificador
    que no importa nada del Builder. Aquí se parsea, no se busca.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
    return modules


def independence() -> dict[str, Any]:
    """Autodeclaración medida con `ast`; el gate no la usa para aprobar.

    La autoridad es `INDEPENDENCE_AUDIT.json`, que produce el auditor externo
    `scripts/def_run_018_independence_audit.py`. Este campo existe para que un desacuerdo
    entre lo que B dice y lo que el auditor mide sea visible y bloquee.
    """
    forbidden = ("trading_bot", "def_run_017_verify", "economic_audit")
    modules = imported_modules(Path(__file__).read_text(encoding="utf-8"))
    hits = sorted(
        name
        for name in modules
        if any(name == token or name.startswith(f"{token}.") for token in forbidden)
    )
    return {
        "shared_with_builder": "specification and input bytes only",
        "imports_trading_bot": bool(hits),
        "reused_recomputation_code": hits,
        "imports": sorted(modules),
        "measured_by": "ast.parse del propio fuente",
        "statement": (
            "B lee JSONL/CSV con la biblioteca estándar y reimplementa cadena, contabilidad, "
            "delta pareado, bootstrap y regla de decisión; no importa el verificador A ni el "
            "módulo de auditoría del Builder."
        ),
        "source_sha256": sha256(Path(__file__)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", default=None)
    parser.add_argument("--md", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    payload = verify(root)
    json_path = (
        Path(args.json)
        if args.json
        else root / "reports" / "ai-bots" / "RFC-DEF-RUN-018" / "INDEPENDENT_VERIFICATION.json"
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.md:
        lines = [
            "# INDEPENDENT_VERIFICATION — verificador B",
            "",
            f"Resultado: **{payload['result']}** · {payload['checks_total']} comprobaciones · "
            f"{payload.get('summary')}",
            "",
            "| Código | Estado | Detalle |",
            "| --- | --- | --- |",
        ]
        for item in payload["controls"]:
            detail = str(item["detail"]).replace("|", "/")[:160]
            lines.append(f"| `{item['code']}` | {item['state']} | {detail} |")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(
        f"result={payload['result']} checks={payload['checks_total']} "
        f"summary={payload.get('summary')} -> {json_path}"
    )
    if payload["result"] == "PASS":
        return 0
    return 2 if payload["result"] == "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
