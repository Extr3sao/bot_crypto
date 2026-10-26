"""DEF-RUN-017 / WP-017-05 — OOS sobre datos que el experimento original nunca vio.

El RFC-016 midió 256 minutos de BTC en una sesión de octubre de 2026. Ese dato no puede
decir si el ciclo de vida `DEFER` gana o pierde dinero: es una muestra. Este script ejecuta
el **mismo carril** (`VisionLane` + `PaperBroker` + `RiskManager` + `strategy_experimental`)
sobre minutos de Binance de enero-febrero de 2021, publicados y con sha256 verificado en
`data/quote-feed-1m/SOURCE_MANIFEST.json`.

Tres reglas que el script no se permite romper:

1. **La partición se congela antes de mirar.** `development / validation / untouched_test`
   se definen por índice cronológico de día y solo se ejecuta la última. No hay selección,
   así que no hay contaminación que corregir.
2. **No se toca nada del runtime.** Ni stop, ni sizing, ni gates, ni costes: lo único que
   cambia entre las dos ramas es `--lifecycle`.
3. **Cada día es un run independiente.** Se declara: equity inicial 10.000, sin arrastre de
   posiciones entre días. Eso permite remuestreo por bloques (día) y no inventa una
   continuidad que el replay no tiene.

Uso::

    python scripts/def_run_017_oos.py --plan
    python scripts/def_run_017_oos.py --execute --partition test --workers 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "DEF_RUN_017_OOS_V1"
DATA = REPO / "data" / "quote-feed-1m"
OUT = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
EVIDENCE = OUT / "evidence" / "oos"
SYMBOLS = ("UNI/USDT", "AAVE/USDT")
ARCHIVE = {"UNI/USDT": "UNIUSDT", "AAVE/USDT": "AAVEUSDT"}
LIFECYCLES = ("SUPERSEDE", "DEFER")
DAY_MS = 86_400_000
MINUTE_MS = 60_000
WINDOW_BARS = 22
WARMUP_BARS = 40
DATA_DELAY_MS = 3_620
DECISION_EVERY_BARS = 1
MAX_OPINION_AGE_MS = 60_000
EQUITY_USDT = 10_000.0
COST_MULTIPLIERS = (1.0, 2.0)
#: Días 1..27 desarrollo, 28..36 validación, 37..45 test intacto. Se declara aquí y no se
#: recalcula nunca a partir de los resultados.
SPLIT = {"development": (0, 27), "validation": (27, 36), "untouched_test": (36, 45)}


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(payload: Any) -> str:
    """JSON estable: la misma configuración produce el mismo sha256 en cualquier máquina."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def git_head() -> str | None:
    """Commit del árbol que ejecuta la reanudación. `None` si git no responde.

    Se registra como acto de la reanudación, no como origen del run: un ledger de 017
    no guarda el commit que lo escribió, y suponerlo sería inventar procedencia.
    """
    run = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = run.stdout.strip()
    return head if run.returncode == 0 and len(head) == 40 else None


def load_minutes(symbol: str) -> list[list[float]]:
    rows = json.loads((DATA / f"{ARCHIVE[symbol]}_1m_2021-01-04_2021-02-17.json").read_text())
    rows.sort(key=lambda row: int(row[0]))
    return rows


def days_of(rows: list[list[float]]) -> list[int]:
    return sorted({int(row[0]) // DAY_MS for row in rows})


def plan() -> dict[str, Any]:
    rows = load_minutes(SYMBOLS[0])
    days = days_of(rows)
    partitions = {}
    for name, (start, stop) in SPLIT.items():
        selected = days[start:stop]
        partitions[name] = {
            "days": len(selected),
            "first_day_utc": datetime.fromtimestamp(selected[0] * 86400, tz=UTC).strftime(
                "%Y-%m-%d"
            )
            if selected
            else None,
            "last_day_utc": datetime.fromtimestamp(selected[-1] * 86400, tz=UTC).strftime(
                "%Y-%m-%d"
            )
            if selected
            else None,
        }
    return {
        "schema_version": SCHEMA,
        "generated_at_utc": utc_now(),
        "symbols": list(SYMBOLS),
        "lifecycles": list(LIFECYCLES),
        "cost_multipliers": list(COST_MULTIPLIERS),
        "total_days": len(days),
        "partitions": partitions,
        "executed_partition": "untouched_test",
        "datasets": {
            symbol: {
                "path": f"data/quote-feed-1m/{ARCHIVE[symbol]}_1m_2021-01-04_2021-02-17.json",
                "sha256": sha256_file(DATA / f"{ARCHIVE[symbol]}_1m_2021-01-04_2021-02-17.json"),
                "rows": len(load_minutes(symbol)),
            }
            for symbol in SYMBOLS
        },
        "fixed": {
            "timeframe": "1m",
            "window_bars": WINDOW_BARS,
            "warmup_bars": WARMUP_BARS,
            "data_delay_ms": DATA_DELAY_MS,
            "decision_every_bars": DECISION_EVERY_BARS,
            "max_opinion_age_ms": MAX_OPINION_AGE_MS,
            "equity_usdt": EQUITY_USDT,
            "signal_source": "strategy_experimental",
            "strategy_id": "ema_crossover",
            "risk_config": "config/risk.yaml (sin cambios)",
            "variable": "vision lane opinion_lifecycle",
        },
    }


def _bars(rows: list[list[float]], start_ms: int, end_ms: int):
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


def run_day(task: dict[str, Any]) -> dict[str, Any]:
    """Un día, un run, un ledger. Nada compartido con los demás días."""
    from trading_bot.config.settings import load_settings
    from trading_bot.vision.lane import VisionLane
    from trading_bot.vision.ledger import read_entries, verify_chain
    from trading_bot.vision.settings import load_vision_config
    from trading_bot.vision.signal_sources import build_signal_provider

    symbol = task["symbol"]
    lifecycle = task["lifecycle"]
    multiplier = float(task["cost_multiplier"])
    day = int(task["day"])
    day_start = day * DAY_MS
    day_end = day_start + DAY_MS
    rows = load_minutes(symbol)
    series = _bars(rows, day_start - WARMUP_BARS * MINUTE_MS, day_end)
    observed = sum(1 for row in rows if day_start <= int(row[0]) < day_end)
    expected = (day_end - day_start) // MINUTE_MS

    ledger_dir = EVIDENCE / "runs" / ARCHIVE[symbol] / lifecycle.lower() / f"cost-{multiplier:.1f}"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / f"{datetime.fromtimestamp(day * 86400, tz=UTC):%Y-%m-%d}.jsonl"
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
        series={symbol: series},
        timeframe="1m",
        interval_ms=MINUTE_MS,
        window_bars=WINDOW_BARS,
        latency_ms=0,
        trace_path=None,
        mode="PAPER",
        strategy_id="ema_crossover",
    )
    started = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lane = VisionLane(
        series={symbol: list(series)},
        provider=provider,
        config=config,
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        book_id=f"def-run-017-{ARCHIVE[symbol]}-{lifecycle.lower()}-{day}",
        equity=EQUITY_USDT,
        decision_every_bars=DECISION_EVERY_BARS,
        cost_multiplier=multiplier,
        opinion_lifecycle=lifecycle,
        decision_from_ms=day_start,
    )
    summary = lane.run()
    entries = [row["entry"] for row in read_entries(ledger)]
    closes = [entry for entry in entries if entry.get("kind") == "CLOSE"]
    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    net = sum(float(entry["pnl_net_usdt"]) for entry in closes)
    gross = sum(float(entry["gross_pnl_usdt"]) for entry in closes)
    costs = sum(
        float(entry["commissions_usdt"]) + float(entry["execution_cost_usdt"]) for entry in closes
    )
    terminal = [
        entry
        for entry in entries
        if entry.get("kind") in ("FILL", "GUARD_REJECT", "DECISION_OUTCOME")
    ]
    #: Los contadores del ciclo de vida se leen del ledger, no del resumen del runtime.
    #: El 2026-10-21 el resumen se leyó un nivel demasiado arriba
    #: (``execution.deferred_slots`` en vez de ``execution.opinions.deferred_slots``) y el
    #: informe del OOS publicó ``deferred_slots=0`` para una rama que aplazó 573 opiniones
    #: en un día: los bytes del ledger son la fuente, el resumen solo la comodidad.
    deferred = [entry for entry in entries if entry.get("kind") == "OPINION_DEFERRED"]
    superseded = [
        entry
        for entry in entries
        if entry.get("kind") == "GUARD_REJECT"
        and entry.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
    ]
    return {
        "schema_version": SCHEMA,
        "symbol": symbol,
        "lifecycle": lifecycle,
        "cost_multiplier": multiplier,
        "day": day,
        "day_utc": datetime.fromtimestamp(day * 86400, tz=UTC).strftime("%Y-%m-%d"),
        "minutes_expected": expected,
        "minutes_observed": observed,
        "missing_minutes": expected - observed,
        "warmup_bars": min(WARMUP_BARS, len(series)),
        "bars": len(series),
        "calls": int(summary.get("calls", 0)),
        "fills": len(fills),
        "closed_trades": len(closes),
        "deferred_slots": len(deferred),
        "deferred_slots_source": "ledger:OPINION_DEFERRED",
        "superseded": len(superseded),
        "price_calls": int(summary.get("calls", 0)),
        "gross_pnl_usdt": round(gross, 8),
        "costs_usdt": round(costs, 8),
        "net_pnl_usdt": round(net, 8),
        "exit_reasons": sorted({str(entry.get("exit_reason")) for entry in closes}),
        "drawdown_usdt": summary.get("drawdown_usdt"),
        "terminal_rows": len(terminal),
        "ledger": str(ledger.relative_to(REPO)),
        "ledger_sha256": sha256_file(ledger),
        "chain": verify_chain(ledger),
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
    }


def ledger_for(task: dict[str, Any]) -> Path:
    day = int(task["day"])
    return (
        EVIDENCE
        / "runs"
        / ARCHIVE[task["symbol"]]
        / str(task["lifecycle"]).lower()
        / f"cost-{float(task['cost_multiplier']):.1f}"
        / f"{datetime.fromtimestamp(day * 86400, tz=UTC):%Y-%m-%d}.jsonl"
    )


def ledger_provenance(
    rows: list[dict[str, Any]],
    *,
    method: str,
    resumes: list[dict[str, Any]],
    chain_ok: bool | None,
) -> dict[str, Any] | None:
    """Procedencia derivada de los bytes del ledger, no de lo que el resumen recuerde.

    El `--resume` de 017 publicó `resumed_from_ledger=true` y nada más: ni de qué run
    venía, ni con qué configuración, ni con qué dataset. El ledger sí lo guarda —cabecera
    `RUN` con `book_id`, dataset, lane, proveedor y política de riesgo, y cierre `RUN_END`
    con su hora de pared—; la reparación no añade datos: los enlaza y los firma.

    `original_commit` queda en `None` a propósito: el ledger no registra el commit que lo
    escribió y completarlo con el commit actual sería inventar el origen.
    """
    entries = [row.get("entry") or {} for row in rows]
    head = next((entry for entry in entries if entry.get("kind") == "RUN"), None)
    end = next((entry for entry in reversed(entries) if entry.get("kind") == "RUN_END"), None)
    if head is None or end is None:
        return None
    config = {
        "lane": head.get("lane"),
        "provider": head.get("provider"),
        "risk_policy": head.get("risk_policy"),
        "cost_multiplier": head.get("cost_multiplier"),
        "equity_usdt": head.get("equity_usdt"),
    }
    return {
        "method": method,
        "run_id": head.get("book_id"),
        "started_at_utc": head.get("recorded_at_utc"),
        "finished_at_utc": end.get("recorded_at_utc"),
        "dataset": head.get("dataset"),
        "config": config,
        "config_sha256": hashlib.sha256(canonical(config).encode("utf-8")).hexdigest(),
        "chain": {
            "ok": bool(chain_ok),
            "rows": len(rows),
            "head_sha256": str(rows[-1].get("sha256")),
            "run_end_seq": int(rows[-1].get("seq", len(rows))),
        },
        "resumes": list(resumes),
        "original_commit": None,
        "original_commit_source": "NOT_RECORDED_IN_LEDGER",
    }


def attach_provenance(
    result: dict[str, Any],
    *,
    method: str,
    resumes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Enlaza el resumen del run con los bytes que lo produjeron."""
    from trading_bot.vision.ledger import read_entries, verify_chain

    path = REPO / str(result["ledger"])
    rows = read_entries(path)
    chain = verify_chain(path)
    provenance = ledger_provenance(
        rows, method=method, resumes=list(resumes or []), chain_ok=chain.get("ok")
    )
    if provenance is None:
        return result
    result["provenance"] = provenance
    result["started_at_utc"] = provenance["started_at_utc"]
    result["finished_at_utc"] = provenance["finished_at_utc"]
    result["ledger_sha256"] = sha256_file(path)
    result["chain"] = chain
    return result


def result_from_ledger(
    task: dict[str, Any],
    path: Path,
    *,
    resumes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconstruye el resumen de un día ya ejecutado sin volver a pagarlo.

    Un reinicio no debe reejecutar 8 días de replay: el ledger ya está en disco y su
    último renglón es ``RUN_END``. Solo se aceptan ledgers terminados.
    """
    from trading_bot.vision.ledger import read_entries

    rows = read_entries(path)
    entries = [row["entry"] for row in rows]
    closes = [entry for entry in entries if entry.get("kind") == "CLOSE"]
    fills = [entry for entry in entries if entry.get("kind") == "FILL"]
    #: DEF-RUN-018: hasta ahora este resumen escribía `missing_minutes=0`, `bars=0` y
    #: `started_at_utc=null`. Sus contadores salían del ledger, pero su cobertura no:
    #: un día con 79 minutos ausentes se publicaba como completo. La cobertura se
    #: recalcula del dataset (el mismo criterio que `run_day`) y los tiempos de la
    #: propia cadena, para que un `--recount` no pueda volver a falsear metadatos.
    day_start = int(task["day"]) * DAY_MS
    day_end = day_start + DAY_MS
    minutes = load_minutes(task["symbol"])
    observed = sum(1 for row in minutes if day_start <= int(row[0]) < day_end)
    bars = sum(
        1 for row in minutes if day_start - WARMUP_BARS * MINUTE_MS <= int(row[0]) < day_end
    )
    run_end = next((entry for entry in reversed(entries) if entry.get("kind") == "RUN_END"), None)
    result = {
        "schema_version": SCHEMA,
        "symbol": task["symbol"],
        "lifecycle": task["lifecycle"],
        "cost_multiplier": float(task["cost_multiplier"]),
        "day": int(task["day"]),
        "day_utc": datetime.fromtimestamp(int(task["day"]) * 86400, tz=UTC).strftime("%Y-%m-%d"),
        "minutes_expected": DAY_MS // MINUTE_MS,
        "minutes_observed": observed,
        "missing_minutes": DAY_MS // MINUTE_MS - observed,
        "warmup_bars": min(WARMUP_BARS, bars),
        "bars": bars,
        "calls": sum(1 for entry in entries if entry.get("kind") == "DECISION"),
        "fills": len(fills),
        "closed_trades": len(closes),
        "deferred_slots": sum(1 for entry in entries if entry.get("kind") == "OPINION_DEFERRED"),
        "deferred_slots_source": "ledger:OPINION_DEFERRED",
        "superseded": sum(
            1
            for entry in entries
            if entry.get("kind") == "GUARD_REJECT"
            and entry.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
        ),
        "gross_pnl_usdt": round(sum(float(e["gross_pnl_usdt"]) for e in closes), 8),
        "costs_usdt": round(
            sum(float(e["commissions_usdt"]) + float(e["execution_cost_usdt"]) for e in closes),
            8,
        ),
        "net_pnl_usdt": round(sum(float(e["pnl_net_usdt"]) for e in closes), 8),
        "exit_reasons": sorted({str(e.get("exit_reason")) for e in closes}),
        "drawdown_usdt": next(
            (entry.get("drawdown_usdt") for entry in entries if entry.get("kind") == "RUN_END"),
            None,
        ),
        "terminal_rows": sum(
            1
            for entry in entries
            if entry.get("kind") in ("FILL", "GUARD_REJECT", "DECISION_OUTCOME")
        ),
        "ledger": str(path.relative_to(REPO)),
        "started_at_utc": entries[0].get("recorded_at_utc") if entries else None,
        "finished_at_utc": (run_end or {}).get("recorded_at_utc") or utc_now(),
    }
    #: La procedencia no se declara: se enlaza con la cabecera `RUN`, el cierre `RUN_END`
    #: y la cadena de sha256 que el verificador B puede recalcular por su cuenta.
    return attach_provenance(result, method="LEDGER_RECONSTRUCTION", resumes=resumes)


def stress_summary(partition: str, *, out_name: str) -> int:
    """Resume el estrés de costes x2 sin mezclarlo con la decisión primaria.

    El protocolo congela la decisión sobre coste x1,0; el x2 solo responde a otra pregunta:
    ¿el signo del delta sobrevive si el peaje se duplica? Se publica aparte, con su propia
    regla aplicada y `used_for_decision: false`, para que nadie lo lea como si fuera la
    rejilla primaria.
    """
    source = EVIDENCE / out_name
    if not source.is_file():
        raise SystemExit(f"missing {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    runs = payload["runs"]
    cells = aggregate(runs)
    per_day: dict[str, dict[str, float]] = {}
    for run in runs:
        key = f"{run['symbol']}|{run['day']}"
        per_day.setdefault(key, {})[run["lifecycle"]] = float(run["net_pnl_usdt"])
    deltas: dict[str, dict[str, Any]] = {}
    for symbol in sorted({run["symbol"] for run in runs}):
        values = [
            pair["DEFER"] - pair["SUPERSEDE"]
            for key, pair in sorted(per_day.items())
            if key.startswith(symbol + "|") and {"DEFER", "SUPERSEDE"} <= set(pair)
        ]
        deltas[symbol] = {
            "per_day_usdt": [round(value, 8) for value in values],
            **_bootstrap(values, seed=17017, resamples=2000),
        }

    def net(symbol: str, lifecycle: str) -> float | None:
        cell = cells.get(f"{symbol}|{lifecycle}|2.0")
        return None if cell is None else float(cell["net_pnl_usdt"])

    symbols = sorted(deltas)
    better = all(
        (net(s, "DEFER") is not None)
        and (net(s, "SUPERSEDE") is not None)
        and float(net(s, "DEFER")) > float(net(s, "SUPERSEDE"))
        for s in symbols
    )
    worse = all(
        (net(s, "DEFER") is not None)
        and (net(s, "SUPERSEDE") is not None)
        and float(net(s, "DEFER")) < float(net(s, "SUPERSEDE"))
        for s in symbols
    )
    separates = all(
        deltas[s].get("ci95") is not None and (deltas[s]["ci95"][1] < 0 or deltas[s]["ci95"][0] > 0)
        for s in symbols
    )
    positive = all(
        (cells.get(f"{s}|DEFER|2.0") or {}).get("expectancy_usdt", 0) > 0 for s in symbols
    )
    status = (
        "EVIDENCED"
        if (better and separates and positive)
        else "NEGATIVE"
        if (worse and separates)
        else "NOT_EVIDENCED"
    )
    result = {
        "schema_version": SCHEMA,
        "generated_at_utc": utc_now(),
        "partition": partition,
        "cost_multiplier": 2.0,
        "used_for_decision": False,
        "why": "robustez declarada en el protocolo: duplicar el peaje no puede convertir una "
        "señal en ventaja, pero puede cambiar qué operaciones pasan el gate de coste",
        "source": out_name,
        "runs": len(runs),
        "cells": cells,
        "paired_day_deltas": deltas,
        "chain_failures": sum(1 for run in runs if not (run.get("chain") or {}).get("ok")),
        "stress_status": status,
    }
    target = EVIDENCE / "OOS_STRESS_COST2.json"
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"stress_status={status} runs={len(runs)}")
    for key, cell in sorted(cells.items()):
        print(
            f"{key}: net={cell['net_pnl_usdt']} trades={cell['closed_trades']} "
            f"deferred={cell['deferred_slots']}"
        )
    print(f"wrote {target}")
    return 0


def recount(partition: str, *, out_name: str | None = None, source_path: Path | None = None) -> int:
    """Re-deriva los contadores de ciclo de vida leyendo los ledgers, sin repagar un día.

    El 2026-10-21 el informe del OOS salió con ``deferred_slots=0`` en la rama DEFER aunque
    sus ledgers contienen 573 líneas ``OPINION_DEFERRED`` en un solo día: ``run_day`` leía
    ``execution.deferred_slots`` de un resumen que anida el contador en
    ``execution.opinions.deferred_slots``. El PnL de esos runs es correcto y **no se toca**;
    lo que se sustituye son los contadores, y cada run recuerda de dónde vienen.

    Uso::

        python scripts/def_run_017_oos.py --recount --partition untouched_test
    """
    from trading_bot.vision.ledger import read_entries

    source = source_path or EVIDENCE / (out_name or f"OOS_RUNS_{partition}.json")
    if not source.is_file():
        raise SystemExit(f"missing {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    before_provenance = [run.get("provenance") for run in payload["runs"]]
    for run in payload["runs"]:
        path = REPO / str(run["ledger"])
        if not path.is_file():
            raise SystemExit(f"missing ledger for {run['ledger']}: cannot recount")
        entries = [row["entry"] for row in read_entries(path)]
        deferred = sum(1 for entry in entries if entry.get("kind") == "OPINION_DEFERRED")
        superseded = sum(
            1
            for entry in entries
            if entry.get("kind") == "GUARD_REJECT"
            and entry.get("code") == "SUPERSEDED_BY_NEWER_OPINION"
        )
        previous = (run.get("deferred_slots"), run.get("superseded"))
        run["deferred_slots"] = deferred
        run["superseded"] = superseded
        run["deferred_slots_source"] = "ledger:OPINION_DEFERRED"
        if previous != (deferred, superseded):
            changes.append(
                {
                    "ledger": run["ledger"],
                    "deferred_slots": [previous[0], deferred],
                    "superseded": [previous[1], superseded],
                }
            )
    payload["totals"] = aggregate(payload["runs"])
    payload["recount"] = {
        "at_utc": utc_now(),
        "reason": "contadores de ciclo de vida leídos del ledger, no del resumen del runtime",
        "pnl_untouched": True,
        "changed_runs": len(changes),
        "changes": changes,
        #: Recontar contadores no puede tocar la procedencia: si el bloque cambia, el
        #: propio artefacto lo delata.
        "provenance_unchanged": before_provenance
        == [run.get("provenance") for run in payload["runs"]],
    }
    source.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"recounted {len(payload['runs'])} runs, {len(changes)} changed -> {source}")
    for cell, data in sorted(payload["totals"].items()):
        print(
            f"{cell}: deferred={data['deferred_slots']} net={data['net_pnl_usdt']} "
            f"trades={data['closed_trades']}"
        )
    return 0


def _quiet_run(task: dict[str, Any]) -> dict[str, Any]:
    """El runtime escribe una línea por relleno; en 8 días eso es ruido, no evidencia.

    Se silencia la salida, no el cálculo. Debe ser de módulo: `spawn` no puede serializar
    una función local, y un `Pool` que falla al arrancar no es un experimento.
    """
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink):
        return run_day(task)


def execute(
    partition: str,
    workers: int,
    cost_multipliers: tuple[float, ...],
    *,
    resume: bool = False,
    out_name: str | None = None,
) -> int:
    frozen = plan()
    start, stop = SPLIT[partition]
    days = days_of(load_minutes(SYMBOLS[0]))[start:stop]
    tasks = [
        {
            "symbol": symbol,
            "lifecycle": lifecycle,
            "cost_multiplier": multiplier,
            "day": day,
        }
        for symbol in SYMBOLS
        for lifecycle in LIFECYCLES
        for multiplier in cost_multipliers
        #: El estrés de costes solo se ejecuta sobre UNI: duplicar todo el grid no añade
        #: información y multiplica el tiempo, y el modelo de costes es el mismo objeto.
        if multiplier == 1.0 or symbol == "UNI/USDT"
        for day in days
    ]
    print(f"partition={partition} days={len(days)} tasks={len(tasks)} workers={workers}")
    results: list[dict[str, Any]] = []
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    target = EVIDENCE / (out_name or f"OOS_RUNS_{partition}.json")
    history: list[dict[str, Any]] = []
    if target.is_file():
        previous = json.loads(target.read_text(encoding="utf-8"))
        history = list(previous.get("resumes") or [])

    if resume:
        finished: list[tuple[dict[str, Any], Path]] = []
        pending: list[dict[str, Any]] = []
        for task in tasks:
            path = ledger_for(task)
            if path.is_file() and path.read_text(encoding="utf-8").rstrip().endswith("}"):
                last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
                if (last.get("entry") or {}).get("kind") == "RUN_END":
                    finished.append((task, path))
                    continue
            pending.append(task)
        #: El acto de reanudar se registra antes de sobrescribir el artefacto anterior,
        #: para que quede su sha256 y no una promesa de que «ya estaba».
        history.append(
            {
                "attempt": len(history) + 1,
                "at_utc": utc_now(),
                "at_commit": git_head(),
                "source_artifact_sha256": sha256_file(target) if target.is_file() else None,
                "partition": partition,
                "ledgers_reused": len(finished),
                "ledgers_executed": len(pending),
            }
        )
        for task, path in finished:
            results.append(result_from_ledger(task, path, resumes=history))
        print(
            f"resume: {len(finished)} days already finished, {len(pending)} to run "
            f"(attempt {len(history)})",
            flush=True,
        )
        tasks = pending

    with mp.get_context("spawn").Pool(processes=workers) as pool:
        for index, result in enumerate(pool.imap_unordered(_quiet_run, tasks), start=1):
            results.append(result)
            print(
                f"[{index}/{len(tasks)}] {result['day_utc']} {result['symbol']} "
                f"{result['lifecycle']} x{result['cost_multiplier']:.1f}: "
                f"fills={result['fills']} net={result['net_pnl_usdt']}",
                flush=True,
            )
    for result in results:
        if "provenance" not in result:
            attach_provenance(result, method="DIRECT", resumes=[])
    results.sort(
        key=lambda row: (row["symbol"], row["lifecycle"], row["cost_multiplier"], row["day"])
    )
    payload = {
        "schema_version": SCHEMA,
        "plan": frozen,
        "partition": partition,
        "generated_at_utc": utc_now(),
        "workers": workers,
        "resumes": history,
        "runs": results,
        "totals": aggregate(results),
    }
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {target}")
    return 0


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_cell: dict[str, dict[str, Any]] = {}
    for run in runs:
        key = f"{run['symbol']}|{run['lifecycle']}|{run['cost_multiplier']:.1f}"
        cell = by_cell.setdefault(
            key,
            {
                "symbol": run["symbol"],
                "lifecycle": run["lifecycle"],
                "cost_multiplier": run["cost_multiplier"],
                "days": 0,
                "fills": 0,
                "closed_trades": 0,
                "gross_pnl_usdt": 0.0,
                "costs_usdt": 0.0,
                "net_pnl_usdt": 0.0,
                "calls": 0,
                "deferred_slots": 0,
                "missing_minutes": 0,
                "chain_failures": 0,
                "per_day_net": [],
            },
        )
        cell["days"] += 1
        for field in ("fills", "closed_trades", "calls", "deferred_slots", "missing_minutes"):
            cell[field] += int(run[field])
        for field in ("gross_pnl_usdt", "costs_usdt", "net_pnl_usdt"):
            cell[field] = round(cell[field] + float(run[field]), 8)
        if not run["chain"].get("ok"):
            cell["chain_failures"] += 1
        cell["per_day_net"].append(round(float(run["net_pnl_usdt"]), 8))
    for cell in by_cell.values():
        trades = cell["closed_trades"]
        cell["expectancy_usdt"] = round(cell["net_pnl_usdt"] / trades, 6) if trades else None
        cell["trades_per_day"] = round(trades / cell["days"], 4) if cell["days"] else None
        cell["days_with_trades"] = sum(1 for value in cell["per_day_net"] if value != 0.0)
    return by_cell


def _bootstrap(values: list[float], *, seed: int, resamples: int) -> dict[str, Any]:
    """Bootstrap por bloques (el día es el bloque) sobre los deltas diarios pareados."""
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


def aggregate_results(partition: str) -> int:
    """Agrega los runs y aplica la regla de decisión congelada en el protocolo."""
    source = EVIDENCE / f"OOS_RUNS_{partition}.json"
    if not source.is_file():
        raise SystemExit(f"missing {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    runs = payload["runs"]
    cells = aggregate(runs)

    per_day: dict[str, dict[str, float]] = {}
    for run in runs:
        if float(run["cost_multiplier"]) != 1.0:
            continue
        key = f"{run['symbol']}|{run['day']}"
        per_day.setdefault(key, {})[run["lifecycle"]] = float(run["net_pnl_usdt"])
    deltas: dict[str, dict[str, Any]] = {}
    for symbol in SYMBOLS:
        values = [
            pair["DEFER"] - pair["SUPERSEDE"]
            for key, pair in sorted(per_day.items())
            if key.startswith(symbol + "|") and {"DEFER", "SUPERSEDE"} <= set(pair)
        ]
        deltas[symbol] = {
            "per_day_usdt": [round(value, 8) for value in values],
            **_bootstrap(values, seed=17017, resamples=2000),
        }

    def cell(symbol: str, lifecycle: str) -> dict[str, Any]:
        return cells.get(f"{symbol}|{lifecycle}|1.0", {})

    net_def = {symbol: float(cell(symbol, "DEFER").get("net_pnl_usdt", 0.0)) for symbol in SYMBOLS}
    net_sup = {
        symbol: float(cell(symbol, "SUPERSEDE").get("net_pnl_usdt", 0.0)) for symbol in SYMBOLS
    }
    expectancy_def = {symbol: cell(symbol, "DEFER").get("expectancy_usdt") for symbol in SYMBOLS}
    better_both = all(net_def[symbol] > net_sup[symbol] for symbol in SYMBOLS)
    worse_both = all(net_def[symbol] < net_sup[symbol] for symbol in SYMBOLS)
    excludes_zero = all(
        (deltas[symbol]["ci95"] is not None)
        and (deltas[symbol]["ci95"][1] < 0 or deltas[symbol]["ci95"][0] > 0)
        for symbol in SYMBOLS
    )
    if better_both and excludes_zero and all((v or 0) > 0 for v in expectancy_def.values()):
        economic = "EVIDENCED"
    elif worse_both and excludes_zero:
        economic = "NEGATIVE"
    elif not runs:
        economic = "INCONCLUSIVE"
    else:
        economic = "NOT_EVIDENCED"

    chain_failures = sum(cell_count.get("chain_failures", 0) for cell_count in cells.values())
    result = {
        "schema_version": SCHEMA,
        "partition": partition,
        "generated_at_utc": utc_now(),
        "plan_sha256": hashlib.sha256((EVIDENCE / "OOS_PLAN.json").read_bytes()).hexdigest()
        if (EVIDENCE / "OOS_PLAN.json").is_file()
        else None,
        "cells": cells,
        "paired_day_deltas": deltas,
        "chain_failures": chain_failures,
        "decision": {
            "rule": "ECONOMIC_STATUS=EVIDENCED exige DEFER>SUPERSEDE en ambos símbolos, "
            "IC95 del delta diario sin cero y expectancy de DEFER positiva (coste x1.0)",
            "defer_better_in_both": better_both,
            "defer_worse_in_both": worse_both,
            "ci95_excludes_zero_in_both": excludes_zero,
            "defer_expectancy_positive_in_both": all(
                (value or 0) > 0 for value in expectancy_def.values()
            ),
            "net_supersede_usdt": net_sup,
            "net_defer_usdt": net_def,
            "economic_status": economic,
        },
    }
    target = EVIDENCE / "OOS_RESULTS.json"
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"economic_status={economic}")
    for symbol in SYMBOLS:
        print(
            f"{symbol}: supersede={net_sup[symbol]:.4f} defer={net_def[symbol]:.4f} "
            f"delta_mean={deltas[symbol]['mean']} ci95={deltas[symbol]['ci95']}"
        )
    print(f"wrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--partition", default="untouched_test", choices=sorted(SPLIT))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--cost-multipliers",
        default="1.0,2.0",
        help="multiplicadores del modelo de costes a ejecutar",
    )
    parser.add_argument("--resume", action="store_true", help="reutiliza ledgers terminados")
    parser.add_argument("--recount", action="store_true", help="re-deriva contadores del ledger")
    parser.add_argument("--stress", action="store_true", help="resume el estrés de coste x2")
    parser.add_argument(
        "--out-name",
        default=None,
        help="nombre del JSON de runs (por defecto OOS_RUNS_<partition>.json)",
    )
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(), indent=2, sort_keys=True))
        return 0
    if args.aggregate:
        return aggregate_results(args.partition)
    if args.recount:
        return recount(args.partition, out_name=args.out_name)
    if args.stress:
        if not args.out_name:
            parser.error("--stress exige --out-name con el JSON de runs del estrés")
        return stress_summary(args.partition, out_name=args.out_name)
    if not args.execute:
        parser.error("nada que hacer: usa --plan, --execute, --recount o --aggregate")
    multipliers = tuple(float(item) for item in args.cost_multipliers.split(",") if item)
    return execute(
        args.partition, args.workers, multipliers, resume=args.resume, out_name=args.out_name
    )


if __name__ == "__main__":
    sys.exit(main())
