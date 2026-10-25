"""DEF-RUN-016 / WP-B — ¿queda alguna señal viva después de los costes reales?

No se ajusta ningún parámetro sobre la muestra con la que se evalúa. El corpus son los
ledgers ya publicados de ``EXP-003L`` (8 runs: 4 horizontes x 2 familias), cada uno un
replay determinista sobre el mismo tipo de mercado con el contrato de costes del repo.

El script:

* reconstruye, decisión a decisión, el stop **declarado** por la familia, el stop
  **efectivo** que el broker guardó, el objetivo, el coste de ida y vuelta y la relación
  beneficio/riesgo neta;
* mide la expectativa realizada por operación (en bps netos) y su sensibilidad al coste;
* separa la elección de alternativa (primer 60 % de cada run) de su evaluación (último
  40 %), de modo que la alternativa elegida no se elige sobre los datos con los que se
  juzga;
* cuenta los rechazos por familia, activo, régimen y horizonte.

No se toca ``config/risk.yaml`` ni se cambia ningún stop: el stop efectivo se lee del
``CLOSE`` que el broker escribió, y cuando difiere del declarado se publica la diferencia
en vez de corregirla.

Uso::

    python scripts/def_run_016_economics.py \
        --out reports/ai-bots/RFC-DEF-RUN-016/evidence/ECONOMICS.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.alpha15 import cost_for  # noqa: E402

CORPUS = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001" / "runs"
LIVE_CORPUS = REPO / "reports" / "ai-bots" / "EXP-003J-REAL-SIGNAL-PAPER-001" / "live"
SCHEMA = "DEF_RUN_016_ECONOMICS_V1"
STAKE_USDT = 500.0
DEV_SHARE = 0.60
MIN_TRADES_FOR_CHOICE = 20
SENSITIVITY = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percentiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "p10": None, "p50": None, "p90": None, "mean": None}
    ordered = sorted(float(value) for value in values)

    def at(quantile: float) -> float:
        index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
        return round(ordered[index], 6)

    return {
        "samples": len(ordered),
        "p10": at(0.10),
        "p50": at(0.50),
        "p90": at(0.90),
        "mean": round(statistics.fmean(ordered), 6),
    }


def _policy():
    return load_settings(config_dir=REPO / "config", env_file=None).risk


def _model_costs() -> dict[str, Any]:
    terms = cost_for("BTC/USDT", stake_usdt=STAKE_USDT)
    return {
        "stake_usdt": STAKE_USDT,
        "fee_bps_per_side": round(float(terms.fee_bps_per_side), 6),
        "half_spread_bps": round(float(terms.half_spread_bps), 6),
        "slippage_bps_per_side": round(float(terms.slippage_bps_per_side), 6),
        "impact_bps_per_side": round(float(terms.impact_bps_per_side), 6),
        "round_trip_bps": round(float(terms.round_trip_bps()), 6),
    }


def _read(path: Path) -> list[dict[str, Any]]:
    """Las filas del ledger con su número de secuencia, que es la identidad de una opinión."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        entry = dict(record["entry"])
        entry["seq"] = int(record["seq"])
        rows.append(entry)
    return rows


def _atr_from_rationale(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"ATR=([0-9.]+)", text)
    return float(match.group(1)) if match else None


def analyse_run(path: Path, *, policy: Any, model_cost_bps: float) -> dict[str, Any]:
    rows = _read(path)
    run = next((row for row in rows if row.get("kind") == "RUN"), None)
    if run is None:
        raise SystemExit(f"{path}: no RUN row")
    lane = run.get("lane") or {}
    dataset = run.get("dataset") or {}
    symbol = next(iter(dataset), "BTC/USDT")
    timeframe = str(lane.get("timeframe") or "")
    decisions = [row for row in rows if row.get("kind") == "DECISION"]
    #: El RUN de un replay de research declara el proveedor *visual* de la config
    #: (``gpt-4o-mini``) aunque la fuente sea la familia; la familia real está en la fila de
    #: cada decisión. Se lee de ahí en vez de suponer que el nombre del modelo es la
    #: estrategia.
    strategy = "unknown"
    for row in decisions:
        model = str((row.get("provider") or {}).get("model") or "")
        if "@" in model:
            strategy = model.split("@")[0]
            break
    outcomes = [row for row in rows if row.get("kind") == "DECISION_OUTCOME"]
    fills = [row for row in rows if row.get("kind") == "FILL"]
    closes = [row for row in rows if row.get("kind") == "CLOSE"]
    rejects = [row for row in rows if row.get("kind") == "GUARD_REJECT"]

    fill_by_seq = {int(row["decision_seq"]): row for row in fills}
    close_by_trade = {str(row.get("trade_id")): row for row in closes}
    outcome_by_seq: dict[int, dict[str, Any]] = {}
    for row in outcomes:
        outcome_by_seq.setdefault(int(row["decision_seq"]), row)

    default_target = float(policy.default_take_profit_pct)
    records: list[dict[str, Any]] = []
    for row in decisions:
        decision = row.get("decision") or {}
        action = str(decision.get("action") or "NO_TRADE")
        intent = row.get("intent")
        declared_stop = decision.get("stop_loss_pct")
        seq = int(row["seq"])
        context = (row.get("prompt") or {}).get("context") or {}
        atr_pct = context.get("atr_pct")
        if atr_pct is None:
            atr = _atr_from_rationale(decision.get("rationale"))
            last = decision.get("invalidation_price") or context.get("last_close")
            atr_pct = (float(atr) / float(last)) if atr and last else None
        record: dict[str, Any] = {
            "decision_seq": seq,
            "ts_ms": int(row["ts_ms"]),
            "action": action,
            "intent": intent,
            "actionable": intent in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"},
            "declared_stop_bps": (
                round(float(declared_stop) * 100.0, 6) if declared_stop is not None else None
            ),
            "declared_target_bps": (
                round(float(decision["take_profit_pct"]) * 100.0, 6)
                if decision.get("take_profit_pct") is not None
                else None
            ),
            "atr_pct": atr_pct,
            "trend_20_bars_pct": context.get("return_20_bars_pct"),
            "horizon_bars": decision.get("horizon_bars"),
            "fill": None,
            "outcome": None,
            "reject": None,
        }
        fill = fill_by_seq.get(seq)
        if fill is not None:
            entry = float(fill.get("entry_price") or fill.get("quote_price") or 0.0)
            stop = float(fill.get("stop_loss_price") or 0.0)
            target = float(fill.get("take_profit_price") or 0.0)
            stop_bps = abs(entry - stop) / entry * 10_000.0 if entry > 0 and stop > 0 else None
            target_bps = (
                abs(target - entry) / entry * 10_000.0 if entry > 0 and target > 0 else None
            )
            record["fill"] = {
                "position_id": str(fill.get("position_id") or ""),
                "side": fill.get("side"),
                "entry_price": entry,
                "notional_usdt": float(fill.get("notional_usdt") or STAKE_USDT),
                "effective_stop_bps": None if stop_bps is None else round(stop_bps, 6),
                "effective_target_bps": None if target_bps is None else round(target_bps, 6),
                "stop_source": fill.get("stop_source"),
                "quote_source": fill.get("quote_source") or fill.get("entry_quote_source"),
                "opinion_age_ms": fill.get("opinion_age_ms"),
            }
            record["cost_bps"] = round(
                float(fill.get("entry_commission_usdt") or 0.0)
                / max(float(fill.get("notional_usdt") or STAKE_USDT), 1.0)
                * 10_000.0,
                6,
            )
        outcome = outcome_by_seq.get(seq)
        if outcome is not None and outcome.get("approved") is False:
            record["outcome"] = {
                "approved": False,
                "blocked_by": outcome.get("risk_blocked_by"),
                "reason": outcome.get("risk_reason"),
            }
        for row_reject in rejects:
            if row_reject.get("decision_seq") == seq:
                record["reject"] = {"code": row_reject.get("code")}
                break
        records.append(record)

    trades: list[dict[str, Any]] = []
    for close in closes:
        entry = float(close.get("entry_price") or 0.0)
        quantity = float(close.get("quantity") or 0.0)
        notional = entry * quantity
        if notional <= 0:
            continue
        pnl_net = float(close.get("pnl_net_usdt") or 0.0)
        gross = float(close.get("gross_pnl_usdt") or 0.0)
        costs = float(close.get("commissions_usdt") or 0.0) + float(
            close.get("execution_cost_usdt") or 0.0
        )
        stop = float(close.get("stop_loss_price") or 0.0)
        target = float(close.get("take_profit_price") or 0.0)
        side = str(close.get("side") or "")
        stop_bps = abs(entry - stop) / entry * 10_000.0 if entry > 0 and stop > 0 else None
        target_bps = (
            abs(target - entry) / entry * 10_000.0 if entry > 0 and target > 0 else None
        )
        trades.append(
            {
                #: La identidad que comparten FILL y CLOSE es ``position_id``; ``trade_id``
                #: es otro espacio de nombres y emparejar por él dejaría la comparación
                #: stop declarado / stop efectivo vacía sin avisar.
                "position_id": str(close.get("position_id") or ""),
                "trade_id": str(close.get("trade_id") or ""),
                "ts_ms": int(close.get("ts_ms") or 0),
                "side": side,
                "entry_price": entry,
                "notional_usdt": round(notional, 6),
                "gross_bps": round(gross / notional * 10_000.0, 6),
                "cost_bps": round(costs / notional * 10_000.0, 6),
                "net_bps": round(pnl_net / notional * 10_000.0, 6),
                "stop_bps": None if stop_bps is None else round(stop_bps, 6),
                "target_bps": None if target_bps is None else round(target_bps, 6),
                "exit_reason": close.get("exit_reason"),
                "bars_held": close.get("bars_held"),
            }
        )

    stop_mismatch = [
        trade
        for trade in trades
        if trade["stop_bps"] is not None
        for record in records
        if record["fill"] and record["fill"]["position_id"] == trade["position_id"]
        and record["declared_stop_bps"] is not None
        and abs(trade["stop_bps"] - record["declared_stop_bps"])
        > max(0.5, 0.05 * record["declared_stop_bps"])
    ]
    declared_stops_live = [
        record
        for record in records
        if record["actionable"]
        and record["declared_stop_bps"] is not None
        and record["fill"] is not None
    ]
    stop_inside_costs = [
        record
        for record in declared_stops_live
        if record["declared_stop_bps"] <= model_cost_bps
    ]

    net_bps = [trade["net_bps"] for trade in trades]
    gross_bps = [trade["gross_bps"] for trade in trades]
    cost_bps = [trade["cost_bps"] for trade in trades]
    wins = [trade for trade in trades if trade["net_bps"] > 0]
    rr = [
        (trade["target_bps"], trade["stop_bps"])
        for trade in trades
        if trade["target_bps"] and trade["stop_bps"]
    ]
    rr_net = [round((target - model_cost_bps) / (stop + model_cost_bps), 6) for target, stop in rr]
    breakeven = [round((stop + model_cost_bps) / (stop + target), 6) for target, stop in rr]

    rejections = Counter()
    for record in records:
        if record["outcome"] and record["outcome"].get("blocked_by"):
            rejections[str(record["outcome"]["blocked_by"])] += 1
        if record["reject"]:
            rejections[str(record["reject"]["code"])] += 1
    rejected_actions = Counter(
        record["action"] for record in records if record["outcome"] or record["reject"]
    )

    regime = _by_regime(records, trades)
    split = _split(records, trades)

    return {
        "path": str(path.relative_to(REPO)),
        "asset": symbol,
        "timeframe": timeframe,
        "strategy": strategy,
        "window_bars": lane.get("window_bars"),
        "decision_every_bars": lane.get("decision_every_bars"),
        "dataset_bars": (dataset.get(symbol) or {}).get("bars"),
        "decisions": len(records),
        "actionable": len([record for record in records if record["actionable"]]),
        "fills": len([record for record in records if record["fill"]]),
        "closed_trades": len(trades),
        "declared_stop_bps": _percentiles(
            [record["declared_stop_bps"] for record in records if record["declared_stop_bps"]]
        ),
        "effective_stop_bps": _percentiles(
            [trade["stop_bps"] for trade in trades if trade["stop_bps"]]
        ),
        "effective_target_bps": _percentiles(
            [trade["target_bps"] for trade in trades if trade["target_bps"]]
        ),
        "declared_vs_effective_stop_mismatch": len(stop_mismatch),
        "declared_stop_at_or_below_model_cost": len(stop_inside_costs),
        "declared_stop_sample_with_fill": len(declared_stops_live),
        "model_cost_bps": model_cost_bps,
        "realised_cost_bps": _percentiles(cost_bps),
        "gross_bps": _percentiles(gross_bps),
        "net_bps": _percentiles(net_bps),
        "expectancy_bps_net": round(statistics.fmean(net_bps), 6) if net_bps else None,
        "expectancy_bps_gross": round(statistics.fmean(gross_bps), 6) if gross_bps else None,
        "win_rate": round(len(wins) / len(trades), 6) if trades else None,
        "net_rr": _percentiles([value for value in rr_net if value is not None]),
        "breakeven_win_rate": _percentiles(breakeven),
        "pnl_net_usdt": round(sum(float(trade["net_bps"]) / 10_000.0 * trade["notional_usdt"] for trade in trades), 6),
        "rejections": dict(sorted(rejections.items())),
        "rejected_actions": dict(sorted(rejected_actions.items())),
        "regime": regime,
        "dev_holdout": split,
        "sensitivity": _sensitivity(gross_bps, cost_bps),
        "breakeven_cost_multiplier": (
            round(statistics.fmean(gross_bps) / statistics.fmean(cost_bps), 6)
            if gross_bps and cost_bps and statistics.fmean(cost_bps) > 0
            else None
        ),
        "trades": trades,
    }


def _by_regime(records: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    trade_by_position = {trade["position_id"]: trade for trade in trades}
    buckets: dict[str, list[float]] = defaultdict(list)
    for record in records:
        if not record["fill"]:
            continue
        trade = trade_by_position.get(record["fill"]["position_id"])
        if trade is None:
            continue
        atr = record.get("atr_pct")
        trend = record.get("trend_20_bars_pct")
        vol = "unknown" if atr is None else ("low" if atr < 0.15 else "mid" if atr < 0.4 else "high")
        direction = (
            "unknown"
            if trend is None
            else "up" if float(trend) > 0.1 else "down" if float(trend) < -0.1 else "flat"
        )
        buckets[f"vol:{vol}"].append(trade["net_bps"])
        buckets[f"trend:{direction}"].append(trade["net_bps"])
    return {
        key: {
            "trades": len(values),
            "expectancy_bps_net": round(statistics.fmean(values), 6),
            "win_rate": round(len([value for value in values if value > 0]) / len(values), 6),
        }
        for key, values in sorted(buckets.items())
    }


def _split(records: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"dev": None, "holdout": None}
    ordered = sorted(records, key=lambda record: record["ts_ms"])
    cut = max(1, int(len(ordered) * DEV_SHARE))
    dev_end = ordered[cut - 1]["ts_ms"]
    dev = [trade for trade in trades if trade["ts_ms"] <= dev_end]
    holdout = [trade for trade in trades if trade["ts_ms"] > dev_end]
    return {
        "dev_end_ms": dev_end,
        "dev": _summary(dev),
        "holdout": _summary(holdout),
    }


def _summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "expectancy_bps_net": None, "win_rate": None}
    values = [trade["net_bps"] for trade in trades]
    return {
        "trades": len(trades),
        "expectancy_bps_net": round(statistics.fmean(values), 6),
        "win_rate": round(len([value for value in values if value > 0]) / len(values), 6),
        "pnl_net_usdt": round(
            sum(value / 10_000.0 * trade["notional_usdt"] for value, trade in zip(values, trades)),
            6,
        ),
    }


def _sensitivity(gross_bps: list[float], cost_bps: list[float]) -> dict[str, Any]:
    if not gross_bps or not cost_bps:
        return {}
    gross = statistics.fmean(gross_bps)
    cost = statistics.fmean(cost_bps)
    return {
        f"cost_x{multiplier:.1f}": round(gross - multiplier * cost, 6) for multiplier in SENSITIVITY
    }


def _live_corpus_audit(model_cost_bps: float) -> dict[str, Any]:
    """El número 4 114 de DEF-RUN-014, medido y corregido.

    Aquel informe sumó las decisiones de **todos** los ciclos publicados de
    ``EXP-003J/live``. Cada ciclo de ``ProspectiveSession`` vuelve a ejecutar el carril sobre
    la serie completa, así que la misma decisión aparece en todos los ciclos posteriores a
    su barra. Sumar filas cuenta la misma opinión muchas veces; aquí se publican las dos
    cifras y la identidad de las decisiones distintas.
    """
    sessions = []
    total_rows = 0
    distinct: dict[tuple[str, int, str], dict[str, Any]] = {}
    for directory in sorted(path for path in LIVE_CORPUS.glob("*") if path.is_dir()):
        meta_path = directory / "RUN_META.json"
        cycles = sorted((directory / "cycles").glob("cycle-*"))
        if not meta_path.is_file() or not cycles:
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        session_rows = 0
        session_distinct = 0
        for cycle in cycles:
            ledger = cycle / "ledger.jsonl"
            if not ledger.is_file():
                continue
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                entry = json.loads(line)["entry"]
                if entry.get("kind") != "DECISION":
                    continue
                session_rows += 1
                stop = (entry.get("decision") or {}).get("stop_loss_pct")
                if stop is None:
                    continue
                key = (directory.name, int(entry["decision_bar_ts_ms"]), str(entry.get("intent")))
                distinct.setdefault(
                    key,
                    {
                        "stop_bps": float(stop) * 100.0,
                        "session": directory.name,
                        "source": meta.get("signal_source"),
                    },
                )
        session_distinct = len([key for key in distinct if key[0] == directory.name])
        total_rows += session_rows
        sessions.append(
            {
                "session": directory.name,
                "signal_source": meta.get("signal_source"),
                "cycles": len(cycles),
                "decision_rows_all_cycles": session_rows,
                "distinct_decisions": session_distinct,
            }
        )
    stops = [item["stop_bps"] for item in distinct.values()]
    below = [stop for stop in stops if stop <= model_cost_bps]
    by_source: dict[str, Any] = {}
    for source in sorted({item["source"] or "unknown" for item in distinct.values()}):
        group = [item for item in distinct.values() if (item["source"] or "unknown") == source]
        group_stops = [item["stop_bps"] for item in group]
        by_source[source] = {
            "distinct_decisions": len(group),
            "stop_bps": _percentiles(group_stops),
            "at_or_below_model_cost": len(
                [stop for stop in group_stops if stop <= model_cost_bps]
            ),
            "below_share": round(
                len([stop for stop in group_stops if stop <= model_cost_bps])
                / len(group_stops),
                6,
            )
            if group_stops
            else None,
        }
    return {
        "sessions": sessions,
        "decision_rows_summed_over_cycles": total_rows,
        "distinct_decisions": len(distinct),
        "published_4114_is": "sum over every cycle ledger, not distinct opinions",
        "distinct_stop_bps": _percentiles(stops),
        "distinct_at_or_below_model_cost": len(below),
        "distinct_below_share": round(len(below) / len(stops), 6) if stops else None,
        "by_source": by_source,
        "inflation_factor": round(total_rows / len(distinct), 3) if distinct else None,
    }


def _cross_asset_published() -> dict[str, Any]:
    """La comparación multi-activo ya publicada, leída sin retocar una sola fila.

    Es el eje de activos que el corpus de ``EXP-003L`` no tiene (allí solo hay BTC/USDT).
    No se recalcula ni se reordena: se resume, y si alguna expectativa fuese positiva se
    publica como tal.
    """
    path = LIVE_CORPUS.parent / "METRICS_BY_ASSET.csv"
    if not path.is_file():
        return {"available": False}
    import csv

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    parsed = [
        {
            "arm": row["arm"],
            "partition": row["partition"],
            "symbol": row["symbol"],
            "decisions": int(row["decisions"]),
            "closes": int(row["closes"]),
            "expectancy_usdt": float(row["expectancy_usdt"]),
            "win_rate_pct": float(row["win_rate_pct"]),
            "net_realised_usdt": float(row["net_realised_usdt"]),
        }
        for row in rows
    ]
    oos = [row for row in parsed if row["partition"] == "oos"]
    return {
        "available": True,
        "path": str(path.relative_to(REPO)),
        "rows": parsed,
        "assets": sorted({row["symbol"] for row in parsed}),
        "arms": sorted({row["arm"] for row in parsed}),
        "all_expectancy_negative": all(row["expectancy_usdt"] < 0 for row in parsed),
        "oos_all_negative": bool(oos) and all(row["expectancy_usdt"] < 0 for row in oos),
        "best_row": max(parsed, key=lambda row: row["expectancy_usdt"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    policy = _policy()
    costs = _model_costs()
    paths = sorted(CORPUS.glob("*/*/*/*/ledger.jsonl"))
    if not paths:
        raise SystemExit(f"no EXP-003L ledger under {CORPUS}")

    runs = [analyse_run(path, policy=policy, model_cost_bps=costs["round_trip_bps"]) for path in paths]
    runs.sort(key=lambda run: (run["timeframe"], run["strategy"]))

    candidates = [
        run
        for run in runs
        if (run["dev_holdout"]["dev"] or {}).get("trades", 0) >= MIN_TRADES_FOR_CHOICE
    ]
    best = max(
        candidates,
        key=lambda run: run["dev_holdout"]["dev"]["expectancy_bps_net"],
        default=None,
    )
    holdout = (best or {}).get("dev_holdout", {}).get("holdout") or {}
    edge = (
        best is not None
        and holdout.get("expectancy_bps_net") is not None
        and holdout["expectancy_bps_net"] > 0
        and holdout.get("trades", 0) >= MIN_TRADES_FOR_CHOICE
    )

    payload = {
        "schema_version": SCHEMA,
        "generated_at_utc": _utc_now(),
        "corpus": {
            "root": str(CORPUS.relative_to(REPO)),
            "runs": len(runs),
            "decisions": sum(run["decisions"] for run in runs),
            "closed_trades": sum(run["closed_trades"] for run in runs),
            "stake_usdt": STAKE_USDT,
        },
        "costs": {
            **costs,
            "risk_policy": {
                "max_risk_per_trade_pct": float(policy.max_risk_per_trade_pct),
                "max_order_notional_usdt": float(policy.max_order_notional_usdt),
                "default_stop_loss_pct": float(policy.default_stop_loss_pct),
                "default_take_profit_pct": float(policy.default_take_profit_pct),
            },
        },
        "runs": [
            {key: value for key, value in run.items() if key != "trades"} for run in runs
        ],
        "selection": {
            "rule": (
                "the alternative with the best DEV expectancy (net of realised costs) among "
                f"runs with >= {MIN_TRADES_FOR_CHOICE} dev trades; DEV is the first "
                f"{int(DEV_SHARE * 100)} % of each run's decisions by time"
            ),
            "chosen": None
            if best is None
            else {"timeframe": best["timeframe"], "strategy": best["strategy"]},
            "dev": None if best is None else best["dev_holdout"]["dev"],
            "holdout": holdout or None,
            "holdout_evaluated_after_choice": True,
        },
        "alternatives": [
            {
                "timeframe": run["timeframe"],
                "strategy": run["strategy"],
                "trades": run["closed_trades"],
                "expectancy_bps_net": run["expectancy_bps_net"],
                "win_rate": run["win_rate"],
                "breakeven_win_rate": (run["breakeven_win_rate"] or {}).get("p50"),
                "net_rr_p50": (run["net_rr"] or {}).get("p50"),
                "dev_expectancy_bps_net": (run["dev_holdout"]["dev"] or {}).get(
                    "expectancy_bps_net"
                ),
                "holdout_expectancy_bps_net": (run["dev_holdout"]["holdout"] or {}).get(
                    "expectancy_bps_net"
                ),
            }
            for run in runs
        ],
        "verdict": "ECONOMIC_EDGE_EVIDENCED" if edge else "ECONOMIC_EDGE_NOT_EVIDENCED",
        "live_corpus_audit": _live_corpus_audit(costs["round_trip_bps"]),
        "cross_asset_published": _cross_asset_published(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"{payload['verdict']}: {payload['corpus']['decisions']} decisions, "
        f"{payload['corpus']['closed_trades']} closed trades; "
        f"chosen={(payload['selection']['chosen'])}; holdout={holdout}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
