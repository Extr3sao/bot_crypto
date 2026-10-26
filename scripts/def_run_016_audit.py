"""DEF-RUN-016 — replay determinista del pipeline de opiniones, CURRENT contra PROPOSED.

El mismo dataset, la misma familia (`ema_crossover`), la misma política de riesgo, el mismo
modelo de costes y el mismo reloj. Lo único que cambia entre las dos capturas es el código
del carril: este script se ejecuta en un worktree limpio de ``HEAD`` para obtener CURRENT y
en el árbol de trabajo para obtener PROPOSED.

Cada escenario escribe su ledger y publica las métricas **derivadas del ledger**, no del
resumen: un verificador independiente puede recalcular todas ellas desde los bytes, y así
la comparación no depende de que el carril se crea sus propios números.

Uso::

    python scripts/def_run_016_audit.py --label PROPOSED \
        --out reports/ai-bots/RFC-DEF-RUN-016/evidence/AUDIT_PROPOSED.json
    python scripts/def_run_016_audit.py --compare BASELINE.json PROPOSED.json \
        --out reports/ai-bots/RFC-DEF-RUN-016/evidence/AUDIT_COMPARISON.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import read_entries  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402
from trading_bot.vision.signal_sources import build_signal_provider  # noqa: E402

SYMBOL = "BTC/USDT"
ARCHIVE_SYMBOL = "BTCUSDT"
SESSION = REPO / "reports" / "ai-bots" / "DEF-RUN-PAPER" / "model-20261020T170635Z"
MINUTES = SESSION / "market-1m" / f"{ARCHIVE_SYMBOL}.jsonl"
SCHEMA = "DEF_RUN_016_AUDIT_V1"
WINDOW_BARS = 22
STRATEGY = "ema_crossover"

#: Los escenarios son la misma sesión vista con cinco relojes distintos. El control
#: ``m1_zero_delay`` no colisiona nunca (la respuesta existe antes de la apertura), así que
#: las dos capturas deben ser idénticas ahí: si difieren, el cambio no es el pipeline.
SCENARIOS: dict[str, dict[str, Any]] = {
    "m1_cadence1": {
        "timeframe": "1m",
        "interval_ms": 60_000,
        "decision_every_bars": 1,
        "data_delay_ms": 3_620,
        "drop_bar": None,
        "why": "la sesión real: rejilla de 1 minuto, cadencia 1, 3.62 s de retraso de datos",
    },
    "m1_zero_delay": {
        "timeframe": "1m",
        "interval_ms": 60_000,
        "decision_every_bars": 1,
        "data_delay_ms": 0,
        "drop_bar": None,
        "why": "control: sin retraso de datos la respuesta precede a la apertura y no hay colisión",
    },
    "m3_cadence1": {
        "timeframe": "3m",
        "interval_ms": 180_000,
        "decision_every_bars": 1,
        "data_delay_ms": 3_620,
        "drop_bar": None,
        "why": "mismo mercado con un reloj más grueso: la colisión no depende del activo",
    },
    "m1_cadence5": {
        "timeframe": "1m",
        "interval_ms": 60_000,
        "decision_every_bars": 5,
        "data_delay_ms": 3_620,
        "drop_bar": None,
        "why": "control de cadencia: con 5 barras entre decisiones la orden ya se resolvió",
    },
    "m1_hole": {
        "timeframe": "1m",
        "interval_ms": 60_000,
        "decision_every_bars": 1,
        "data_delay_ms": 3_620,
        "drop_bar": 40,
        "why": "una barra ausente en el camino: el hueco no es una cotización",
    },
}


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        return ""


def load_minutes() -> tuple[list[dict[str, Any]], str]:
    if not MINUTES.is_file():
        raise SystemExit(f"missing session minutes: {MINUTES}")
    rows = [json.loads(line) for line in MINUTES.read_text(encoding="utf-8").splitlines() if line]
    rows.sort(key=lambda row: int(row["open_ms"]))
    return rows, _sha256(MINUTES)


def to_bars(minutes: list[dict[str, Any]], interval_ms: int) -> tuple[list[Bar], dict[str, Any]]:
    """Agrupa los minutos de la sesión en barras del reloj pedido.

    Solo se publica un grupo **completo**: un grupo al que le falta un minuto no es una
    barra, y agregarlo inventaría un OHLC que nadie observó. El descarte se declara.
    """
    per_bar = max(1, int(interval_ms) // 60_000)
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in minutes:
        opened = int(row["open_ms"])
        groups.setdefault(opened - opened % int(interval_ms), []).append(row)
    bars: list[Bar] = []
    incomplete = 0
    for bucket in sorted(groups):
        rows = groups[bucket]
        if len(rows) != per_bar:
            incomplete += 1
            continue
        bars.append(
            Bar(
                ts_ms=bucket,
                open=float(rows[0]["open"]),
                high=max(float(row["high"]) for row in rows),
                low=min(float(row["low"]) for row in rows),
                close=float(rows[-1]["close"]),
                volume=sum(float(row.get("volume") or 0.0) for row in rows),
            )
        )
    return bars, {
        "minutes": len(minutes),
        "minutes_per_bar": per_bar,
        "groups": len(groups),
        "incomplete_groups_discarded": incomplete,
        "bars": len(bars),
    }


def run_scenario(
    name: str,
    spec: dict[str, Any],
    minutes: list[dict[str, Any]],
    out_dir: Path,
    lifecycle: str,
) -> dict[str, Any]:
    bars, aggregate = to_bars(minutes, int(spec["interval_ms"]))
    dropped = None
    if spec.get("drop_bar") is not None:
        index = int(spec["drop_bar"])
        if index >= len(bars):  # pragma: no cover - scenario guard
            raise SystemExit(f"scenario {name}: drop_bar {index} is outside the series")
        dropped = int(bars[index].ts_ms)
        bars = [bar for position, bar in enumerate(bars) if position != index]
    if len(bars) <= WINDOW_BARS + 2:
        raise SystemExit(f"scenario {name}: only {len(bars)} bars, not enough to decide")

    directory = out_dir / name
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / "ledger.jsonl"
    #: El directorio es de este script: se limpia la salida anterior, incluido el lock que
    #: dejó una ejecución interrumpida. Un lock rancio no es un escritor vivo, y dejarlo
    #: convertiría una repetición en un fallo de arranque.
    for stale in (ledger, ledger.with_suffix(".jsonl.lock")):
        if stale.exists():
            stale.unlink()

    base = load_vision_config(env={})
    config = base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe=str(spec["timeframe"]),
            window_bars=WINDOW_BARS,
            decision_every_bars=int(spec["decision_every_bars"]),
            max_calls_per_run=500,
            max_estimated_spend_usd=50.0,
            data_delay_ms=int(spec["data_delay_ms"]),
            max_opinion_age_ms=0,
        ),
    )
    series = {SYMBOL: bars}
    provider = build_signal_provider(
        "strategy_experimental",
        series=series,
        timeframe=str(spec["timeframe"]),
        interval_ms=int(spec["interval_ms"]),
        window_bars=WINDOW_BARS,
        latency_ms=0,
        trace_path=directory / "SIGNAL_TRACE.jsonl",
        mode="PAPER",
        strategy_id=STRATEGY,
    )
    lane = VisionLane(
        series={SYMBOL: list(bars)},
        provider=provider,
        config=config,
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=ledger,
        book_id=f"def-run-016-{name}",
        decision_every_bars=int(spec["decision_every_bars"]),
        opinion_lifecycle=lifecycle,
    )
    summary = lane.run()
    rows = [dict(line["entry"], seq=int(line["seq"])) for line in read_entries(ledger)]
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    metrics = derive(rows, interval_ms=int(spec["interval_ms"]))
    return {
        "scenario": name,
        "why": spec["why"],
        "opinion_lifecycle": lifecycle,
        "config": {
            "timeframe": spec["timeframe"],
            "interval_ms": int(spec["interval_ms"]),
            "decision_every_bars": int(spec["decision_every_bars"]),
            "data_delay_ms": int(spec["data_delay_ms"]),
            "max_opinion_age_ms": int(config.lane.max_opinion_age_ms) or int(spec["interval_ms"]),
            "dropped_bar_open_ms": dropped,
            "strategy_id": STRATEGY,
            "signal_source": "strategy_experimental",
            "declared_provider_latency_ms": 0,
        },
        "series": {
            "bars": len(bars),
            "first_open_ms": int(bars[0].ts_ms),
            "last_open_ms": int(bars[-1].ts_ms),
            "bars_sha256": hashlib.sha256(
                "|".join(f"{int(b.ts_ms)}:{float(b.open)}" for b in bars).encode()
            ).hexdigest(),
            "aggregate": aggregate,
        },
        "ledger": {
            "path": str(ledger.relative_to(REPO)) if ledger.is_relative_to(REPO) else str(ledger),
            "sha256": _sha256(ledger),
            "rows": len(rows),
        },
        "metrics": metrics,
        "summary_view": {
            "calls": int(summary.get("calls", 0)),
            "fills": int(summary.get("fills", 0)),
            "costs_total_usdt": summary.get("costs_total_usdt"),
            "net_realised_usdt": summary.get("net_realised_usdt"),
            "execution_opinions": (summary.get("execution") or {}).get("opinions"),
            #: La declaración del propio carril sobre la contabilidad, para que el
            #: verificador pueda contrastarla con su reconstrucción desde los bytes en vez
            #: de aceptarla.
            "opinion_accounting": summary.get("opinion_accounting"),
            "stage_latency_ms": (summary.get("execution") or {}).get("stage_latency_ms"),
        },
    }


def derive(rows: list[dict[str, Any]], *, interval_ms: int) -> dict[str, Any]:
    """Everything below is recomputed from ledger rows. The verifier repeats this."""
    run = next((row for row in rows if row.get("kind") == "RUN"), None)
    if run is None:
        raise SystemExit("ledger has no RUN row")
    decisions = [row for row in rows if row.get("kind") == "DECISION"]
    actionable = [row for row in decisions if row.get("intent") in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}]

    fills = [row for row in rows if row.get("kind") == "FILL"]
    outcomes = [row for row in rows if row.get("kind") == "DECISION_OUTCOME"]
    rejects = [row for row in rows if row.get("kind") == "GUARD_REJECT"]
    deferred = [row for row in rows if row.get("kind") == "OPINION_DEFERRED"]

    def reject_code(code: str) -> list[dict[str, Any]]:
        return [row for row in rejects if row.get("code") == code]

    terminal: dict[int, str] = {}
    for row in fills:
        terminal[int(row["decision_seq"])] = "FILL"
    for row in outcomes:
        seq = int(row["decision_seq"])
        if terminal.get(seq) == "FILL":
            continue
        terminal[seq] = "RISK_BLOCKED" if not row.get("approved") else "GATE_BLOCKED"
    for row in rejects:
        seq = row.get("decision_seq")
        if seq is None:
            continue
        terminal[int(seq)] = str(row.get("code"))
    terminal_deferred = {
        int(row["decision_seq"]): int(row["pending_deferrals"]) for row in deferred
    }

    #: Contabilidad estructural: cuántas filas declaran cierre para cada opinión. El
    #: verificador lo vuelve a derivar desde los bytes; aquí se publica para que la captura
    #: pueda ser rechazada sin ejecutar el verificador.
    births = {int(row["seq"]) for row in actionable}
    events: dict[int, list[tuple[int, str]]] = {}

    def note(row: dict[str, Any], label: str) -> None:
        events.setdefault(int(row["decision_seq"]), []).append((int(row["seq"]), label))

    for row in fills:
        note(row, "FILL")
    for row in outcomes:
        executed = row.get("executed")
        if str(row.get("intent")) == "CLOSE":
            if executed is True:
                note(row, "CLOSED")
            elif executed is False:
                note(row, "GATED")
        elif row.get("approved") is False:
            note(row, "BLOCKED_BY_RISK")
        elif row.get("approved") is True and executed is False:
            note(row, "GATED")
    for row in rejects:
        if row.get("decision_seq") is not None:
            note(row, str(row.get("code")))

    duplicate_terminals = len(
        [seq for seq in births if len(events.get(seq, [])) > 1]
    )
    orphan_terminals = len([seq for seq in events if seq not in births])
    terminal_before_birth = len(
        [
            seq
            for seq in births
            if events.get(seq) and min(row_seq for row_seq, _ in events[seq]) < seq
        ]
    )
    approved_seqs = {
        int(row["decision_seq"])
        for row in outcomes
        if row.get("approved") is True and row.get("risk_gate") == "check_signal"
    }
    fills_without_approval = len(
        [row for row in fills if int(row["decision_seq"]) not in approved_seqs]
    )
    run_end_index = [index for index, row in enumerate(rows) if row.get("kind") == "RUN_END"]


    opinions = []
    for row in actionable:
        seq = int(row["seq"])
        opinions.append(
            {
                "decision_seq": seq,
                "decision_ts_ms": int(row["ts_ms"]),
                "decision_bar_open_ms": int(row["decision_bar_ts_ms"]),
                "intent": row["intent"],
                "deferrals": terminal_deferred.get(seq, 0),
                "terminal": terminal.get(seq, "PENDING_AT_END"),
            }
        )
    pending = [item for item in opinions if item["terminal"] == "PENDING_AT_END"]
    for item in pending:
        item["terminal"] = "PENDING_AT_END"

    provider_ms = [
        int(row["received_at_ms"]) - int(row["decision_ts_ms"])
        for row in fills
        if row.get("received_at_ms") is not None and row.get("decision_ts_ms") is not None
    ]
    quote_wait_ms = [
        int(row["quote_ts_ms"]) - int(row["received_at_ms"])
        for row in fills
        if row.get("quote_ts_ms") is not None and row.get("received_at_ms") is not None
    ]
    decision_to_quote_ms = [
        int(row["quote_ts_ms"]) - int(row["decision_ts_ms"])
        for row in fills
        if row.get("quote_ts_ms") is not None and row.get("decision_ts_ms") is not None
    ]
    data_to_decision_ms = [
        int(row["decision_ts_ms"]) - (int(row["decision_bar_open_ms"]) + interval_ms)
        for row in fills
        if row.get("decision_ts_ms") is not None and row.get("decision_bar_open_ms") is not None
    ]
    ages = [int(row["opinion_age_ms"]) for row in fills if row.get("opinion_age_ms") is not None]

    stale_fills = [
        row
        for row in fills
        if int(row["quote_ts_ms"]) < int(row["received_at_ms"])
        or int(row["quote_ts_ms"]) < int(row["decision_ts_ms"])
    ]
    max_age = int(((run.get("lane") or {}).get("max_opinion_age_ms")) or interval_ms)
    over_age_fills = [row for row in fills if int(row["opinion_age_ms"]) > max_age]

    wasted = [item for item in opinions if item["terminal"] in {
        "SUPERSEDED_BY_NEWER_OPINION",
        "LATE_RESPONSE",
    }]
    calls = len(decisions) + len([row for row in rows if row.get("kind") == "PROVIDER_FAILURE"])

    return {
        "calls": calls,
        "decision_rows": len(decisions),
        "actionable_opinions": len(actionable),
        "fills": len(fills),
        "deferred_slots": len(deferred),
        "superseded": len(reject_code("SUPERSEDED_BY_NEWER_OPINION")),
        "expired": len(reject_code("LATE_RESPONSE")),
        "data_gap": len(reject_code("DATA_GAP")),
        "risk_blocked": len([row for row in outcomes if row.get("approved") is False]),
        "pending_at_end": len(pending),
        "wasted_opinions": len(wasted),
        "executed_share": (len(fills) / len(actionable)) if actionable else None,
        "stale_fills": len(stale_fills),
        "over_age_fills": len(over_age_fills),
        "max_opinion_age_ms": max_age,
        #: Contabilidad estructural. El verificador la vuelve a derivar desde los bytes;
        #: publicarla aquí permite rechazar una captura sin ejecutar el verificador.
        "terminal": len([seq for seq in births if seq in events]),
        "unrecorded": len([seq for seq in births if seq not in events]),
        "ids_unique": len({int(row["seq"]) for row in decisions}) == len(decisions),
        "duplicate_terminals": duplicate_terminals,
        "orphan_terminals": orphan_terminals,
        "terminal_before_birth": terminal_before_birth,
        "fills_without_approval": fills_without_approval,
        "run_end_present": bool(run_end_index),
        "rows_after_run_end": (len(rows) - run_end_index[0] - 1) if run_end_index else 0,
        "stage_latency_ms": {
            "data_to_decision": _percentiles(data_to_decision_ms),
            "provider": _percentiles(provider_ms),
            "received_to_quote": _percentiles(quote_wait_ms),
            "decision_to_quote": _percentiles(decision_to_quote_ms),
            "opinion_age_at_fill": _percentiles(ages),
        },
        "opinions": opinions,
    }


def _percentiles(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(int(value) for value in values)

    def at(quantile: float) -> int:
        index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
        return ordered[index]

    return {
        "samples": len(ordered),
        "p50": at(0.50),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


#: The fields a CURRENT/PROPOSED comparison is allowed to move. Declared, so a change in
#: anything else is a defect and not a result.
COMPARED = (
    "calls",
    "actionable_opinions",
    "fills",
    "deferred_slots",
    "superseded",
    "expired",
    "data_gap",
    "risk_blocked",
    "pending_at_end",
    "wasted_opinions",
    "executed_share",
    "stale_fills",
    "over_age_fills",
)


def compare(baseline: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for name, base in baseline["scenarios"].items():
        prop = proposed["scenarios"].get(name)
        if prop is None:  # pragma: no cover - inputs are checked
            raise SystemExit(f"scenario {name} is missing from the proposed capture")
        same_series = base["series"]["bars_sha256"] == prop["series"]["bars_sha256"]
        same_config = base["config"] == prop["config"]
        delta = {
            field: {
                "current": base["metrics"].get(field),
                "proposed": prop["metrics"].get(field),
            }
            for field in COMPARED
        }
        scenarios[name] = {
            "same_series": same_series,
            "same_config": same_config,
            "lifecycle_current": base.get("opinion_lifecycle"),
            "lifecycle_proposed": prop.get("opinion_lifecycle"),
            "current": base["metrics"],
            "proposed": prop["metrics"],
            "delta": delta,
            "fill_delta": prop["metrics"]["fills"] - base["metrics"]["fills"],
            "call_delta": prop["metrics"]["calls"] - base["metrics"]["calls"],
        }
    total_current = sum(item["current"]["fills"] for item in scenarios.values())
    total_proposed = sum(item["proposed"]["fills"] for item in scenarios.values())
    return {
        "schema_version": "DEF_RUN_016_COMPARISON_V1",
        "generated_at_utc": _utc_now(),
        "baseline_commit": baseline.get("commit"),
        "proposed_commit": proposed.get("commit"),
        "same_dataset": baseline.get("dataset", {}).get("minutes_sha256")
        == proposed.get("dataset", {}).get("minutes_sha256"),
        "lifecycle_current": baseline.get("lifecycle"),
        "lifecycle_proposed": proposed.get("lifecycle"),
        "scenarios": scenarios,
        "fills_current": total_current,
        "fills_proposed": total_proposed,
        "verdict": (
            "IMPROVED"
            if total_proposed > total_current
            and all(item["same_series"] and item["same_config"] for item in scenarios.values())
            else "NOT_IMPROVED"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="PROPOSED")
    parser.add_argument(
        "--lifecycle",
        default="DEFER",
        choices=("DEFER", "SUPERSEDE"),
        help="DEFER is the fixed runtime; SUPERSEDE replays the pre-DEF-RUN-016 rule",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="*", default=None)
    parser.add_argument("--compare", nargs=2, type=Path, default=None)
    parser.add_argument("--work", type=Path, default=None)
    parser.add_argument(
        "--publish-ledgers",
        type=Path,
        default=None,
        help="copy each scenario ledger to <dir>/<label>/<name>.jsonl for the verifier",
    )
    args = parser.parse_args(argv)

    if args.compare:
        baseline = json.loads(args.compare[0].read_text(encoding="utf-8"))
        proposed = json.loads(args.compare[1].read_text(encoding="utf-8"))
        payload = compare(baseline, proposed)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(
            f"{payload['verdict']}: fills {payload['fills_current']} -> "
            f"{payload['fills_proposed']} (same dataset={payload['same_dataset']})"
        )
        return 0

    minutes, minutes_sha = load_minutes()
    names = args.scenarios or list(SCENARIOS)
    unknown = sorted(set(names) - set(SCENARIOS))
    if unknown:
        raise SystemExit(f"unknown scenario(s): {unknown}")

    with tempfile.TemporaryDirectory(prefix="def-run-016-") as shared:
        work = args.work or Path(shared)
        scenarios = {}
        for name in names:
            scenarios[name] = run_scenario(
                name, SCENARIOS[name], minutes, work, str(args.lifecycle).upper()
            )
            metrics = scenarios[name]["metrics"]
            print(
                f"{name}: calls={metrics['calls']} actionable={metrics['actionable_opinions']} "
                f"fills={metrics['fills']} deferred={metrics['deferred_slots']} "
                f"superseded={metrics['superseded']} expired={metrics['expired']} "
                f"stale={metrics['stale_fills']}"
            )
        payload = {
            "schema_version": SCHEMA,
            "label": args.label,
            "lifecycle": str(args.lifecycle).upper(),
            "generated_at_utc": _utc_now(),
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            #: Which copy of the package actually ran. A baseline capture that silently
            #: imported the working tree's lane would compare the fix with itself.
            "lane_module_path": str(Path(sys.modules["trading_bot.vision.lane"].__file__)),
            "lane_module_sha256": _sha256(
                Path(sys.modules["trading_bot.vision.lane"].__file__ or "")
            ),
            "dirty": bool(_git("status", "--porcelain")),
            "runtime_sha256": {
                str(path.relative_to(REPO)): _sha256(path)
                for path in (
                    REPO / "src" / "trading_bot" / "vision" / "lane.py",
                    REPO / "src" / "trading_bot" / "vision" / "execution.py",
                    REPO / "src" / "trading_bot" / "risk" / "manager.py",
                    REPO / "src" / "trading_bot" / "paper" / "broker.py",
                )
            },
            "dataset": {
                "path": str(MINUTES.relative_to(REPO)),
                "minutes_sha256": minutes_sha,
                "minutes": len(minutes),
                "first_open_ms": int(minutes[0]["open_ms"]),
                "last_open_ms": int(minutes[-1]["open_ms"]),
                "symbol": SYMBOL,
            },
            "scenarios": scenarios,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        if args.publish_ledgers is not None:
            #: El verificador recalcula cada métrica desde los bytes, así que los ledgers
            #: tienen que sobrevivir al directorio temporal de la captura. Se copian con
            #: el nombre plano que él espera; el contenido —y por tanto su sha256— no cambia.
            published = args.publish_ledgers / str(args.label).upper()
            published.mkdir(parents=True, exist_ok=True)
            for name in names:
                (published / f"{name}.jsonl").write_bytes(
                    (work / name / "ledger.jsonl").read_bytes()
                )
            print(f"published {len(names)} ledgers to {published}")
        print(f"wrote {args.out} ({args.label}, commit {payload['commit'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
