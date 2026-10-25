"""WP-EDGE-01 closure — the H6 retest entry and the out-of-sample trend review.

Two experiments, both frozen before they ran, both DEV-declared and both read
through the same pre-registered harness the WP already published (``SPLITS``,
``ADMISSION_CRITERIA``, the runtime risk budget read from ``config/risk.yaml``,
the modelled cost plane and the benchmark market context):

* **H6 — the retest entry** (`ABL-EDGE01-H6`, answering H2's diagnostic). H2
  measured the intraday book paying for the extension: 236 of 290 DEV fills landed
  at or past 0.25 ATR above the level the signal itself named, and only the fills
  closest to the level had positive gross. H6 turns that reading into an entry: the
  SAME frozen signals, executed three ways — the frozen market intent, the same plan
  crossed at market, and the same plan rested as a limit at the level. The ruleset is
  untouched (``params_delta`` is empty by construction); what changes is execution,
  and whether the limit ever fills is decided by the bars and published per order.

* **Trend 4h out of sample** (`OOS-EDGE01-TREND-4H`, answering H3). The frozen
  ``EDGE-TREND-01`` 4h ruleset is measured on VAL and OOS with no parameter touched,
  as a portfolio and as three single-asset books, against buy & hold on the same
  window and cost plane, decomposed by asset, by calendar period and by both regime
  labels, and judged against an explicit PAPER gate frozen before the decomposition
  ran.

Nothing here is wired into the PAPER runtime and nothing is promoted: a favourable
reading is a hypothesis to take back through the pre-registered process
(freeze, validate, measure OOS once), never a certification.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import campaign as C
from .candidates import FROZEN_PARAMS, PARAMS_HASH, TrendFollow
from .costs import cost_plane
from .data import ASSETS
from .features import market_regime_at
from .retest import RETEST_PARAMS, RetestEntry
from .simulator import buy_and_hold
from .simulator import run_portfolio as run_portfolio_sim

__all__ = [
    "OOS_TREND",
    "OOS_TREND_DECISION",
    "RETEST_H6",
    "RETEST_H6_DECISION",
    "oos_trend_verdict",
    "retest_verdict",
    "run_oos_trend",
    "run_retest_h6",
    "write_oos_trend_artifacts",
    "write_retest_h6_artifacts",
]

# --------------------------------------------------------------------------- #
# H6 — the retest entry
# --------------------------------------------------------------------------- #

RETEST_H6: dict[str, Any] = {
    "id": "ABL-EDGE01-H6",
    "answer_to": "H2",
    "base_candidate": "edge_intra_01",
    "variant_candidate": "edge_intra_01r",
    "split": "intraday",
    "timeframe": "15m",
    "horizon_minutes": 240.0,
    "primary_window": "DEV",
    "windows": ["DEV", "VAL", "OOS"],
    "scenario_plan": {"DEV": ["BASE", "2X_FEES"], "VAL": ["BASE"], "OOS": ["BASE", "2X_FEES"]},
    "question": (
        "H2 measured the intraday book paying for the extension: 236 of 290 DEV fills "
        "landed at or past 0.25 ATR above the broken level and only the fills closest "
        "to the level carried positive gross. Does entering on a resting limit AT the "
        "level — same signals, same stop, same target, same risk budget, same costs — "
        "improve the net expectancy, and are the orders actually filled?"
    ),
    "arms": {
        "frozen_market": (
            "the frozen EDGE-INTRA-01 ruleset, market entry at the next bar's open "
            "(the published WP arm, re-run here as the baseline of this experiment)"
        ),
        "plan_market": (
            "the SAME plans the retest arm would rest, crossed at market: it isolates "
            "how much of the difference is the plan's own gate numbers and how much is "
            "the execution price"
        ),
        "plan_limit": (
            "the same plans rested as limit buys at the broken level, live for the "
            "declared expiry, filled only if a bar trades at or through the level, at "
            "the level and never better"
        ),
    },
    "variant_params": RETEST_PARAMS,
    "unreachable_outcomes": {
        "cancelled_close_below_level": (
            "a bar that closes below the level has traded at or through it by construction "
            "(low <= close < level), so it fills first: the plan's own invalidation cannot "
            "cancel a resting order at that level. The branch stays in the book as a guard "
            "and the verifier checks that the outcome never appears"
        )
    },
}

#: Frozen BEFORE any arm ran. The economic reading (net, then expectancy per trade)
#: and the execution reading (fill rate, the sample floor) are kept APART on
#: purpose: a variant that improves the net but fills one order in ten is an
#: economics result with an execution problem, not two things to average.
RETEST_H6_DECISION: dict[str, Any] = {
    "primary_window": "DEV",
    "primary_scenario": "BASE",
    "baseline_arm": "frozen_market",
    "variant_arm": "plan_limit",
    "min_orders_placed": 100,
    "min_filled_trades": 50,
    "min_fill_rate": 0.40,
    "economic_rule": {
        "RETEST_UNPOWERED": "fewer orders placed or fills than the declared floors",
        "RETEST_IMPROVES_NET": "net AND expectancy per trade both better than the baseline",
        "RETEST_IMPROVES_EXPECTANCY_ONLY": "expectancy per trade better, net not better",
        "RETEST_DOES_NOT_HELP": "neither net nor expectancy better than the baseline",
    },
    "execution_rule": {
        "VIABLE": "at least the declared share of the placed orders was filled",
        "STARVED": "the plan cannot be executed often enough to matter, whatever its P&L",
    },
    "not_claimed": (
        "a favourable economic reading is a hypothesis for a new pre-registered run, "
        "not a promotion: nothing is wired into the PAPER runtime and the ruleset in "
        "candidates.FROZEN_PARAMS is unchanged"
    ),
}


def _order_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Outcomes of the planned limit orders, counted by the outcome they ended with."""
    outcomes: dict[str, int] = {}
    for row in rows:
        key = str(row.get("outcome"))
        outcomes[key] = outcomes.get(key, 0) + 1
    placed = len(rows)
    filled = int(outcomes.get("filled", 0))
    return {
        "orders_placed": placed,
        "orders_filled": filled,
        "orders_by_outcome": outcomes,
        "fill_rate": round(filled / placed, 6) if placed else None,
        "median_discount_bps": C._median(
            [float(row["discount_bps"]) for row in rows if row.get("discount_bps") is not None]
        ),
        "median_bars_resting": C._median([float(row.get("bars_resting") or 0) for row in rows]),
    }


def retest_verdict(arms: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered reading of the H6 comparison. Pure: metrics in, verdict out."""
    baseline = arms[str(decision["baseline_arm"])]
    variant = arms[str(decision["variant_arm"])]
    plan_market = arms.get("plan_market")
    orders = int(variant.get("orders_placed") or 0)
    fills = int(variant.get("orders_filled") or 0)
    fill_rate = float(variant.get("fill_rate") or 0.0)
    frozen_net = float(baseline.get("net_usdt") or 0.0)
    limit_net = float(variant.get("net_usdt") or 0.0)
    frozen_exp = float(baseline.get("expectancy_usdt") or 0.0)
    limit_exp = float(variant.get("expectancy_usdt") or 0.0)
    net_delta = limit_net - frozen_net
    exp_delta = limit_exp - frozen_exp
    reasons: list[str] = []
    if orders < int(decision["min_orders_placed"]):
        verdict = "RETEST_UNPOWERED"
        reasons.append(
            f"{orders} orders placed < the declared floor {decision['min_orders_placed']}"
        )
    elif fills < int(decision["min_filled_trades"]):
        verdict = "RETEST_UNPOWERED"
        reasons.append(
            f"{fills} fills < the declared floor {decision['min_filled_trades']}"
        )
    elif net_delta > 0.0 and exp_delta > 0.0:
        verdict = "RETEST_IMPROVES_NET"
        reasons.append(
            f"net {limit_net:,.2f} vs {frozen_net:,.2f} USDT ({net_delta:+,.2f}) and "
            f"expectancy {limit_exp:,.4f} vs {frozen_exp:,.4f} ({exp_delta:+,.4f})"
        )
    elif exp_delta > 0.0:
        verdict = "RETEST_IMPROVES_EXPECTANCY_ONLY"
        reasons.append(
            f"expectancy {limit_exp:,.4f} vs {frozen_exp:,.4f} ({exp_delta:+,.4f}) but net "
            f"{limit_net:,.2f} vs {frozen_net:,.2f} USDT ({net_delta:+,.2f}): the entry is "
            "better per trade and the book trades fewer of them"
        )
    else:
        verdict = "RETEST_DOES_NOT_HELP"
        reasons.append(
            f"net {net_delta:+,.2f} USDT and expectancy {exp_delta:+,.4f} per trade against "
            "the frozen market arm"
        )
    execution = "VIABLE" if fill_rate >= float(decision["min_fill_rate"]) else "STARVED"
    reasons.append(
        f"{fills}/{orders} orders filled ({fill_rate:.2%}) against the declared floor "
        f"{float(decision['min_fill_rate']):.0%} -> {execution}"
    )
    if plan_market is not None:
        reasons.append(
            "same plans crossed at market: net "
            f"{float(plan_market.get('net_usdt') or 0.0):,.2f} USDT, expectancy "
            f"{float(plan_market.get('expectancy_usdt') or 0.0):,.4f}"
        )
    return {
        "verdict": verdict,
        "execution": execution,
        "reason": " | ".join(reasons),
        "baseline_net_usdt": round(frozen_net, 4),
        "variant_net_usdt": round(limit_net, 4),
        "net_delta_usdt": round(net_delta, 4),
        "baseline_expectancy_usdt": round(frozen_exp, 6),
        "variant_expectancy_usdt": round(limit_exp, 6),
        "expectancy_delta_usdt": round(exp_delta, 6),
        "orders_placed": orders,
        "orders_filled": fills,
        "fill_rate": round(fill_rate, 6),
        "decision_rule": decision,
    }


def run_retest_h6() -> dict[str, Any]:
    """Run the H6 arms on DEV (decision) plus VAL and OOS (confirmation, no tuning)."""
    split_name = str(RETEST_H6["split"])
    timeframe = str(RETEST_H6["timeframe"])
    horizon = float(RETEST_H6["horizon_minutes"])
    corpus = C._load_corpus(split_name, timeframe)
    regime_rows, regime_meta = C._market_context_series()
    policy = C.load_risk_policy()
    scenario_plan: dict[str, list[str]] = RETEST_H6["scenario_plan"]
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)

    runs: dict[str, Any] = {}
    for window in RETEST_H6["windows"]:
        bounds = C.SPLITS[split_name][window]
        start, end = int(bounds["start"]), int(bounds["end"])
        window_minutes = (end - start) / 60_000.0
        for scenario in scenario_plan[window]:
            plane = base_plane.scaled(scenario)
            arms: dict[str, Any] = {}
            for arm_name, limit_entries, factory in (
                ("frozen_market", False, lambda: C.build_candidates()["edge_intra_01"]),
                ("plan_market", False, RetestEntry),
                ("plan_limit", True, RetestEntry),
            ):
                candidate = factory()
                sim = run_portfolio_sim(
                    candidate=candidate,
                    bars_by_asset=corpus.bars_by_asset,
                    plane=plane,
                    policy=policy,
                    context=corpus.context,
                    window_start_ts=start,
                    window_end_ts=end,
                    limit_entries=limit_entries,
                )
                for trade in sim.trades:
                    trade["market_context"] = market_regime_at(
                        regime_rows, int(trade["decision_ts"])
                    )
                metrics = C._metrics(
                    trades=sim.trades,
                    equity_curve=sim.equity_curve,
                    start_equity=policy.start_equity,
                    window_minutes=window_minutes,
                    timeframe=timeframe,
                    n_assets=len(ASSETS),
                )
                arms[arm_name] = {
                    "role": arm_name,
                    "candidate_id": str(candidate.id),
                    "limit_entries": limit_entries,
                    "params": dict(candidate.params),
                    "params_delta": C._params_delta(
                        FROZEN_PARAMS["edge_intra_01"], dict(candidate.params)
                    ),
                    "bars_evaluated": candidate.bars_evaluated,
                    "warmup_bars": candidate.warmup_bars,
                    "signal_count": len(sim.signals),
                    "signals_planning_a_limit": sum(
                        1 for signal in sim.signals if signal.get("entry_limit") is not None
                    ),
                    "refusals": C._funnel(sim.refusals),
                    "_trade_rows": sim.trades,
                    "_refusal_rows": sim.refusals,
                    "_signal_rows": sim.signals,
                    "_order_rows": sim.orders,
                    **metrics,
                    **_order_summary(sim.orders),
                }
            runs[f"{window}:{scenario}"] = {
                "window": window,
                "scenario": scenario,
                "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
                "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
                "window_start_ms": start,
                "window_end_ms": end,
                "window_days": round(window_minutes / 1440.0, 4),
                "plane": plane.to_dict(),
                "arms": arms,
            }

    primary_key = f"{RETEST_H6['primary_window']}:BASE"
    verdict = retest_verdict(
        runs[primary_key]["arms"],
        {**RETEST_H6_DECISION, "primary_window": RETEST_H6["primary_window"]},
    )
    confirmation: dict[str, Any] = {}
    for window in RETEST_H6["windows"]:
        if window == RETEST_H6["primary_window"]:
            continue
        run = runs[f"{window}:BASE"]
        arms = run["arms"]
        confirmation[window] = {
            "baseline_net_usdt": arms["frozen_market"]["net_usdt"],
            "variant_net_usdt": arms["plan_limit"]["net_usdt"],
            "net_delta_usdt": round(
                float(arms["plan_limit"]["net_usdt"]) - float(arms["frozen_market"]["net_usdt"]), 4
            ),
            "baseline_expectancy_usdt": arms["frozen_market"]["expectancy_usdt"],
            "variant_expectancy_usdt": arms["plan_limit"]["expectancy_usdt"],
            "fill_rate": arms["plan_limit"]["fill_rate"],
            "orders_placed": arms["plan_limit"]["orders_placed"],
            "trades": arms["plan_limit"]["trades"],
            "note": (
                "confirmatory window: the plan's rules were frozen before any of the three "
                "windows was run under H6 and nothing was re-tuned after reading it, but the "
                "diagnosis that motivated the plan came from DEV, so DEV is its design "
                "window and this one is evidence, not a decision"
            ),
        }
    stress = runs.get("OOS:2X_FEES")
    return {
        "run_id": "wp-edge-01-retest-h6",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": C._git_state(),
        "source_digest": C._source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_closure_experiments.py",
                "scripts/edge01_closure_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus; the DEV window "
            "decides, VAL and OOS confirm; 0 orders, 0 credentials, 0 network calls"
        ),
        "entrypoint": "scripts/edge01_closure_experiments.py --experiment h6",
        "verifier": "scripts/edge01_closure_verify.py --experiment h6",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **RETEST_H6,
            "assets": list(ASSETS),
            "frozen_params_baseline": FROZEN_PARAMS["edge_intra_01"],
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": C._sha256(C.RISK_CONFIG),
            "risk_policy": policy.to_dict(),
            "decision_rule": RETEST_H6_DECISION,
            "corpus_provenance": corpus.provenance,
        },
        "verdict": verdict,
        "runs": runs,
        "confirmation": confirmation,
        "oos_cost_stress": {
            "scenario": "2X_FEES",
            "baseline_net_usdt": stress["arms"]["frozen_market"]["net_usdt"],
            "variant_net_usdt": stress["arms"]["plan_limit"]["net_usdt"],
        }
        if stress
        else None,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "limitations": [
            (
                "the signals are the frozen candidate's, so this experiment cannot be "
                "better than the signals it inherits: it isolates the entry price, not "
                "the setup"
            ),
            (
                "a limit that fills only when price comes back is filled precisely when "
                "the breakout is failing — adverse selection. Without a historical order "
                "book the model cannot charge for it, so the fill is charged the SAME "
                "spread, slippage, impact and fee as a market entry and the limit is "
                "always filled at the level, never better"
            ),
            (
                "queue position is not modelled: a bar that merely touches the level is "
                "treated as a fill. That is the optimistic side of the fill rule, and it "
                "is why the fill rate is published per order rather than assumed"
            ),
            (
                "the expiry (8 bars of 15m) is declared here and was not tuned: a longer "
                "window would fill more orders at prices further from the diagnosis"
            ),
            (
                "the risk budget is consulted at the moment of the touch, so an order can "
                "be cancelled by a refusal the market arm would never have met; those "
                "orders are published with the refusal reason"
            ),
            "single corpus window per split; no historical order book; long side only (spot)",
        ],
    }


def write_retest_h6_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the H6 evidence: the three books, the orders, the signals and the verdict."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trade_rows: list[dict[str, Any]] = []
    refusal_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    for key, run in payload["runs"].items():
        for name, arm in run["arms"].items():
            for trade in arm["_trade_rows"]:
                trade_rows.append(
                    {
                        "run": key,
                        "arm": name,
                        "window": run["window"],
                        "scenario": run["scenario"],
                        "candidate": arm["candidate_id"],
                        "strategy": trade.get("candidate"),
                        **trade,
                    }
                )
            for refusal in arm["_refusal_rows"]:
                detail = refusal.get("detail") or {}
                refusal_rows.append(
                    {
                        "run": key,
                        "arm": name,
                        "candidate": arm["candidate_id"],
                        "source": refusal.get("source", "candidate"),
                        "reason": refusal.get("reason"),
                        "symbol": refusal.get("symbol", ""),
                        "decision_ts": refusal.get("decision_ts"),
                        "level": detail.get("level"),
                        "min_atr_pct": detail.get("min_atr_pct"),
                    }
                )
            for signal in arm["_signal_rows"]:
                evidence = signal.get("evidence") or {}
                gate = evidence.get("gate_at_limit") or {}
                signal_rows.append(
                    {
                        "run": key,
                        "arm": name,
                        "candidate": arm["candidate_id"],
                        "asset": signal.get("symbol"),
                        "bar_index": signal.get("bar_index"),
                        "decision_ts": signal.get("decision_ts"),
                        "regime": signal.get("regime"),
                        "entry_reference": signal.get("entry_reference"),
                        "entry_limit": signal.get("entry_limit"),
                        "limit_expiry_bars": signal.get("limit_expiry_bars"),
                        "stop": signal.get("stop"),
                        "target": (signal.get("targets") or [None])[0],
                        "breakout_entry_reference": evidence.get("breakout_entry_reference"),
                        "breakout_distance_atr": evidence.get("breakout_distance_atr"),
                        "atr": evidence.get("atr"),
                        "risk_reward": signal.get("risk_reward"),
                        "expected_gross_bps": signal.get("expected_gross_bps"),
                        "expected_cost_bps": signal.get("expected_cost_bps"),
                        "expected_net_bps": signal.get("expected_net_bps"),
                        "gate_at_limit_risk_reward": gate.get("risk_reward"),
                    }
                )
            for order in arm["_order_rows"]:
                order_rows.append(
                    {
                        "run": key,
                        "arm": name,
                        "window": run["window"],
                        "scenario": run["scenario"],
                        "candidate": arm["candidate_id"],
                        **order,
                    }
                )

    for name, table in (
        ("RETEST_TRADES.csv", trade_rows),
        ("RETEST_ORDERS.csv", order_rows),
        ("RETEST_SIGNALS.csv", signal_rows),
        ("RETEST_REFUSALS.csv", refusal_rows),
    ):
        path = outdir / name
        C._write_csv(path, table)
        written[name] = path

    context_path = outdir / "MARKET_CONTEXT.csv"
    C._write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "RETEST.md"
    md_path.write_text(_retest_markdown(payload), encoding="utf-8")
    written["RETEST.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "experiment": payload["experiment"],
        "market_context": payload["market_context"]["meta"],
        "verdict": payload["verdict"],
        "confirmation": payload["confirmation"],
        "oos_cost_stress": payload["oos_cost_stress"],
        "limitations": payload["limitations"],
        "runs": {
            key: {
                **run,
                "arms": {
                    name: C._public({k: v for k, v in arm.items() if not k.startswith("_")})
                    for name, arm in run["arms"].items()
                },
            }
            for key, run in payload["runs"].items()
        },
        "artifacts": {
            name: {"sha256": C._sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every H6 artefact except RETEST.json itself, which is the file "
            "carrying them"
        ),
    }
    json_path = outdir / "RETEST.json"
    json_path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written["RETEST.json"] = json_path
    return written


def _retest_markdown(payload: dict[str, Any]) -> str:
    exp = payload["experiment"]
    verdict = payload["verdict"]
    decision = exp["decision_rule"]
    git = payload["git"]
    primary = payload["runs"][f"{exp['primary_window']}:{decision['primary_scenario']}"]
    arm_names = ("frozen_market", "plan_market", "plan_limit")
    lines = [
        "# ABLACION DE MECANISMO - H6 (entrada por retest en el nivel)",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{exp['id']}` |",
        f"| responde a | `{exp['answer_to']}` |",
        f"| pregunta | {exp['question']} |",
        f"| candidato congelado | `{exp['base_candidate']}` |",
        f"| variante | `{exp['variant_candidate']}` (solo cambia la EJECUCION) |",
        f"| split / ventana primaria | `{exp['split']}` / `{exp['primary_window']}` |",
        f"| ventanas de confirmacion | {', '.join(decision_windows(exp))} |",
        f"| escenarios | DEV y OOS con `BASE` + `2X_FEES`; VAL con `BASE` |",
        f"| desde / hasta (primaria) | `{primary['window_start_utc']}` .. `{primary['window_end_utc']}` |",
        f"| dias | {primary['window_days']} |",
        f"| HEAD al ejecutar | `{git['head_commit']}` |",
        f"| huella del codigo ejecutado (sha256) | `{git['source_sha256']}` |",
        f"| params_hash (candidato congelado) | `{payload['params_hash']}` |",
        f"| veredicto economico | **`{verdict['verdict']}`** |",
        f"| lectura de ejecucion | **`{verdict['execution']}`** |",
        "",
        "Las tres ramas son el MISMO presupuesto de riesgo, los MISMOS costes y el MISMO",
        f"corpus. `{exp['base_candidate']}` cruza al open de la barra siguiente;",
        f"`{exp['variant_candidate']}` deja una orden limite en el nivel roto y solo se",
        "ejecuta si el precio vuelve. El ruleset congelado no se toca: `params_delta` de",
        "las tres ramas es el mismo diccionario vacio.",
        "",
        "## Veredicto",
        "",
        f"- `{verdict['verdict']}`: {verdict['reason']}",
        f"- regla congelada: {decision['economic_rule']}",
        f"- lectura de ejecucion: {decision['execution_rule']}",
        f"- no reclamado: {decision['not_claimed']}",
        "",
        f"## Ventana primaria ({exp['primary_window']}, `{decision['primary_scenario']}`)",
        "",
        "| rama | operaciones | neto | expectativa | profit factor | drawdown | exposicion |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in arm_names:
        arm = primary["arms"][name]
        lines.append(
            f"| `{name}` | {arm['trades']} | {_money(arm['net_usdt'])} | "
            f"{_money(arm['expectancy_usdt'])} | {_num(arm['profit_factor'])} | "
            f"{_num(arm['max_drawdown_pct'])}% | {_num(arm['exposure_pct_of_time'])}% |"
        )
    lines += [
        "",
        "| rama | senales | senales con limite | ordenes | rellenos | fill rate | "
        "descuento mediano (bps) | barras en reposo (mediana) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in arm_names:
        arm = primary["arms"][name]
        lines.append(
            f"| `{name}` | {arm['signal_count']} | {arm['signals_planning_a_limit']} | "
            f"{arm['orders_placed']} | {arm['orders_filled']} | {_pct(arm['fill_rate'])} | "
            f"{_num(arm['median_discount_bps'])} | {_num(arm['median_bars_resting'])} |"
        )
    limit_arm = primary["arms"]["plan_limit"]
    outcomes = limit_arm["orders_by_outcome"]
    lines += [
        "",
        "### Destino de cada orden planificada",
        "",
        "| desenlace | ordenes |",
        "|---|---|",
    ]
    for key in sorted(outcomes):
        lines.append(f"| `{key}` | {outcomes[key]} |")
    lines += [
        "",
        f"- `discount_bps` es lo que el plan se ahorra comprando en el nivel en vez de en",
        "  el cierre de ruptura; su mediana es el tamano de la apuesta que hace H6.",
        "",
        "## Confirmacion fuera de la ventana de diseno",
        "",
        "| ventana | neto baseline | neto plan_limit | delta | expectativa baseline | "
        "expectativa plan_limit | fill rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for window, block in payload["confirmation"].items():
        lines.append(
            f"| `{window}` | {_money(block['baseline_net_usdt'])} | "
            f"{_money(block['variant_net_usdt'])} | {_money(block['net_delta_usdt'])} | "
            f"{_money(block['baseline_expectancy_usdt'])} | "
            f"{_money(block['variant_expectancy_usdt'])} | {_pct(block['fill_rate'])} |"
        )
    stress = payload.get("oos_cost_stress")
    if stress:
        lines += [
            "",
            f"- estres de coste `{stress['scenario']}` en OOS: baseline "
            f"{_money(stress['baseline_net_usdt'])} / plan_limit "
            f"{_money(stress['variant_net_usdt'])} USDT",
        ]
    lines += [
        "",
        "Cada ventana de confirmacion lleva la misma nota que el JSON: las reglas del plan",
        "se congelaron antes de correr ninguna de las tres ventanas y no se re-ajusto nada",
        "despues, pero el diagnostico que motivo el plan sale de DEV, asi que DEV es su",
        "ventana de diseno y las otras dos son evidencia, no decision.",
        "",
        "## Artefactos de este experimento",
        "",
        "- `RETEST.json` — las tres ramas, el destino de cada orden y el veredicto",
        "- `RETEST_TRADES.csv` — operaciones ejecutadas por rama, ventana y escenario",
        "- `RETEST_ORDERS.csv` — una fila por orden planificada, con su desenlace",
        "- `RETEST_SIGNALS.csv` — senales del candidato con el plan de entrada",
        "- `RETEST_REFUSALS.csv` — rechazos por origen y motivo",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion",
        f"- verificado por `{payload['verifier']}` en un proceso aparte",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    return "\n".join(lines) + "\n"


def decision_windows(exp: dict[str, Any]) -> list[str]:
    """The windows other than the primary one, in the declared order."""
    return [window for window in exp["windows"] if window != exp["primary_window"]]


# --------------------------------------------------------------------------- #
# Out-of-sample review of the frozen 4h trend ruleset
# --------------------------------------------------------------------------- #

OOS_TREND: dict[str, Any] = {
    "id": "OOS-EDGE01-TREND-4H",
    "answer_to": "H3",
    "candidate": "edge_trend_01",
    "profile": "4h",
    "split": "trend",
    "timeframe": "4h",
    "horizon_minutes": 1440.0,
    "windows": ["DEV", "VAL", "OOS"],
    "scenario_plan": {"DEV": ["BASE"], "VAL": ["BASE"], "OOS": ["BASE", "2X_FEES"]},
    "decision_window": "OOS",
    "periods": {
        "2025H1": [2025, 1, 1, 2025, 7, 1],
        "2025H2": [2025, 7, 1, 2026, 1, 1],
        "2026Q1": [2026, 1, 1, 2026, 3, 1],
    },
    "question": (
        "EDGE-TREND-01 4h is positive on DEV (+1,921.1792 USDT) and positive on OOS, but "
        "H3 warned that the OOS net may be one fat trade rather than an edge. Is there "
        "enough out-of-sample evidence — per asset, per calendar period, per regime and "
        "against buy & hold, before and after cost stress — to justify taking this "
        "ruleset to PAPER?"
    ),
}

#: Frozen BEFORE the OOS decomposition ran; the WP's own ADMISSION_CRITERIA is applied
#: on top of it, not instead of it. Every requirement is a number so the reader can
#: disagree with the bar instead of with the label.
OOS_TREND_DECISION: dict[str, Any] = {
    "decision_window": "OOS",
    "periods_are": "calendar halves of the OOS window, declared before the run",
    "require_oos_net_positive": True,
    "require_oos_net_positive_under_2x_fees": True,
    "min_oos_trades": 30,
    "max_single_trade_share_of_net": 0.50,
    "min_positive_assets": 2,
    "require_drawdown_below_buy_and_hold": True,
    "min_positive_periods": 2,
    "meaning": {
        "SUFFICIENT_EVIDENCE_FOR_PAPER": "every requirement above met on OOS, plus the WP gate",
        "NOT_SUFFICIENT_EVIDENCE": "the sample is powered and at least one requirement fails",
        "UNPOWERED": "fewer than the declared minimum OOS trades: nothing is concluded",
    },
    "not_claimed": (
        "PAPER here means the evidence supports wiring the frozen ruleset into the paper "
        "pipeline; it is not a profitability claim, not a live-trading authorisation and "
        "not a certification. No capital is at risk in this experiment."
    ),
}


def _period_table(
    trades: list[dict[str, Any]], periods: dict[str, list[int]]
) -> list[dict[str, Any]]:
    """Net, expectancy and win rate per declared calendar period, from the trades."""
    rows: list[dict[str, Any]] = []
    for name, bounds in periods.items():
        start = C._ms(bounds[0], bounds[1], bounds[2])
        end = C._ms(bounds[3], bounds[4], bounds[5])
        subset = [t for t in trades if start <= int(t["decision_ts"]) < end]
        nets = [float(t["net"]) for t in subset]
        wins = [n for n in nets if n > 0]
        rows.append(
            {
                "period": name,
                "start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
                "end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
                "trades": len(subset),
                "net_usdt": round(sum(nets), 4),
                "expectancy_usdt": round(sum(nets) / len(nets), 6) if nets else None,
                "win_rate_pct": round(100.0 * len(wins) / len(subset), 4) if subset else None,
            }
        )
    return rows


def oos_trend_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Pre-registered PAPER gate for the frozen 4h trend ruleset. Pure function."""
    decision = OOS_TREND_DECISION
    window = str(decision["decision_window"])
    run = payload["runs"][f"{window}:BASE"]
    combined = run["combined"]
    stress = payload["runs"][f"{window}:2X_FEES"]["combined"]
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str, required: bool = True) -> None:
        checks.append({"criterion": name, "result": "PASS" if passed else "FAIL",
                       "required": required, "detail": detail})

    trades = int(combined["trades"])
    net = float(combined["net_usdt"] or 0.0)
    add("oos_net_positive", net > 0, f"OOS net {net:,.2f} USDT", decision["require_oos_net_positive"])
    stress_net = float(stress["net_usdt"] or 0.0)
    add(
        "oos_net_positive_under_2x_fees",
        stress_net > 0,
        f"OOS net with 2x fees {stress_net:,.2f} USDT",
        decision["require_oos_net_positive_under_2x_fees"],
    )
    add("oos_trades_floor", trades >= int(decision["min_oos_trades"]),
        f"{trades} OOS trades vs floor {decision['min_oos_trades']}")
    share = combined.get("largest_trade_share_of_net")
    add(
        "no_single_trade_carries_the_net",
        share is not None and float(share) <= float(decision["max_single_trade_share_of_net"]),
        f"largest trade is {share} of the OOS net (limit "
        f"{decision['max_single_trade_share_of_net']})",
    )
    positive_assets = [
        asset
        for asset, block in run["assets"].items()
        if float(block["net_usdt"] or 0.0) > 0
    ]
    add(
        "assets_positive",
        len(positive_assets) >= int(decision["min_positive_assets"]),
        f"{len(positive_assets)}/{len(run['assets'])} single-asset OOS books positive "
        f"({', '.join(positive_assets) or 'none'}) vs required {decision['min_positive_assets']}",
    )
    candidate_dd = float(combined["max_drawdown_pct"] or 0.0)
    buy_hold_dd = max(
        (float(block["max_drawdown_pct"] or 0.0) for block in run["buy_and_hold"].values()),
        default=0.0,
    )
    add(
        "drawdown_below_buy_and_hold",
        candidate_dd < buy_hold_dd,
        f"OOS max drawdown {candidate_dd:.2f}% vs the deepest buy & hold drawdown "
        f"{buy_hold_dd:.2f}%",
        decision["require_drawdown_below_buy_and_hold"],
    )
    positive_periods = [row["period"] for row in run["periods"] if float(row["net_usdt"]) > 0]
    add(
        "periods_positive",
        len(positive_periods) >= int(decision["min_positive_periods"]),
        f"{len(positive_periods)}/{len(run['periods'])} OOS periods positive "
        f"({', '.join(positive_periods) or 'none'}) vs required {decision['min_positive_periods']}",
    )

    failed = [check for check in checks if check["required"] and check["result"] == "FAIL"]
    if trades < int(decision["min_oos_trades"]):
        verdict = "UNPOWERED"
    elif failed:
        verdict = "NOT_SUFFICIENT_EVIDENCE"
    else:
        verdict = "SUFFICIENT_EVIDENCE_FOR_PAPER"
    reasons = [f"{check['criterion']}: {check['detail']}" for check in failed]
    if verdict == "UNPOWERED":
        reasons = [
            f"OOS sample {trades} trades < floor {decision['min_oos_trades']}: the measurement "
            "cannot support a conclusion"
        ]
    if verdict == "SUFFICIENT_EVIDENCE_FOR_PAPER":
        reasons = [
            "every declared requirement met on OOS, including the cost stress and the "
            "per-asset, per-period and drawdown comparisons"
        ]
    return {
        "verdict": verdict,
        "reasons": reasons,
        "checks": checks,
        "wp_admission": payload["wp_admission"],
        "decision_rule": decision,
    }


def run_oos_trend() -> dict[str, Any]:
    """Measure the frozen 4h trend ruleset on DEV/VAL/OOS without touching a parameter."""
    split_name = str(OOS_TREND["split"])
    timeframe = str(OOS_TREND["timeframe"])
    profile = str(OOS_TREND["profile"])
    horizon = float(OOS_TREND["horizon_minutes"])
    corpus = C._load_corpus(split_name, timeframe)
    regime_rows, regime_meta = C._market_context_series()
    policy = C.load_risk_policy()
    scenario_plan: dict[str, list[str]] = OOS_TREND["scenario_plan"]
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)
    frozen_params = dict(FROZEN_PARAMS["edge_trend_01"])
    periods: dict[str, list[int]] = OOS_TREND["periods"]

    runs: dict[str, Any] = {}
    for window in OOS_TREND["windows"]:
        bounds = C.SPLITS[split_name][window]
        start, end = int(bounds["start"]), int(bounds["end"])
        window_minutes = (end - start) / 60_000.0
        for scenario in scenario_plan[window]:
            plane = base_plane.scaled(scenario)
            combined_candidate = TrendFollow(profile, dict(frozen_params))
            combined_sim = run_portfolio_sim(
                candidate=combined_candidate,
                bars_by_asset=corpus.bars_by_asset,
                plane=plane,
                policy=policy,
                window_start_ts=start,
                window_end_ts=end,
            )
            for trade in combined_sim.trades:
                trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
            combined = {
                **C._metrics(
                    trades=combined_sim.trades,
                    equity_curve=combined_sim.equity_curve,
                    start_equity=policy.start_equity,
                    window_minutes=window_minutes,
                    timeframe=timeframe,
                    n_assets=len(ASSETS),
                ),
                "params_hash": PARAMS_HASH,
                "refusals": C._funnel(combined_sim.refusals),
                "signals_printed": len(combined_sim.signals),
            }
            assets: dict[str, Any] = {}
            for asset in ASSETS:
                candidate = TrendFollow(profile, dict(frozen_params))
                sim = run_portfolio_sim(
                    candidate=candidate,
                    bars_by_asset={asset: corpus.bars_by_asset[asset]},
                    plane=plane,
                    policy=policy,
                    window_start_ts=start,
                    window_end_ts=end,
                )
                for trade in sim.trades:
                    trade["market_context"] = market_regime_at(
                        regime_rows, int(trade["decision_ts"])
                    )
                assets[asset] = {
                    **C._metrics(
                        trades=sim.trades,
                        equity_curve=sim.equity_curve,
                        start_equity=policy.start_equity,
                        window_minutes=window_minutes,
                        timeframe=timeframe,
                        n_assets=1,
                    ),
                    "refusals": C._funnel(sim.refusals),
                    "signals_printed": len(sim.signals),
                    "_trade_rows": sim.trades,
                }
            buy_hold = {
                asset: buy_and_hold(
                    bars=corpus.bars_by_asset[asset],
                    plane=plane,
                    start_equity=policy.start_equity,
                    window_start_ts=start,
                    window_end_ts=end,
                )
                for asset in ASSETS
            }
            runs[f"{window}:{scenario}"] = {
                "window": window,
                "scenario": scenario,
                "window_start_utc": datetime.fromtimestamp(start / 1000, tz=UTC).isoformat(),
                "window_end_utc": datetime.fromtimestamp(end / 1000, tz=UTC).isoformat(),
                "window_start_ms": start,
                "window_end_ms": end,
                "window_days": round(window_minutes / 1440.0, 4),
                "plane": plane.to_dict(),
                "combined": combined,
                "assets": assets,
                "buy_and_hold": buy_hold,
                "periods": _period_table(combined_sim.trades, periods),
                "_trade_rows": combined_sim.trades,
            }

    wp_splits: dict[str, Any] = {}
    for window in OOS_TREND["windows"]:
        wp_splits[window] = {
            scenario: runs[f"{window}:{scenario}"]["combined"]
            for scenario in scenario_plan[window]
        }
    wp_admission = C._gate(splits=wp_splits, criteria=C.ADMISSION_CRITERIA)
    payload: dict[str, Any] = {
        "run_id": "wp-edge-01-oos-trend-4h",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git": C._git_state(),
        "source_digest": C._source_digest(
            [
                "scripts/edge01_run.py",
                "scripts/edge01_verify.py",
                "scripts/edge01_closure_experiments.py",
                "scripts/edge01_closure_verify.py",
            ]
        ),
        "mode": (
            "deterministic backtest over the local historical corpus: DEV as the "
            "reference, VAL and OOS read once with the frozen ruleset; 0 orders, "
            "0 credentials, 0 network calls"
        ),
        "entrypoint": "scripts/edge01_closure_experiments.py --experiment oos",
        "verifier": "scripts/edge01_closure_verify.py --experiment oos",
        "params_hash": PARAMS_HASH,
        "experiment": {
            **OOS_TREND,
            "assets": list(ASSETS),
            "frozen_params": frozen_params,
            "risk_config_path": "config/risk.yaml",
            "risk_config_sha256": C._sha256(C.RISK_CONFIG),
            "risk_policy": policy.to_dict(),
            "decision_rule": OOS_TREND_DECISION,
            "wp_admission_criteria": C.ADMISSION_CRITERIA,
            "corpus_provenance": corpus.provenance,
        },
        "runs": runs,
        "wp_admission": wp_admission,
        "market_context": {
            "meta": regime_meta,
            "rows": [row.to_row() for row in regime_rows],
        },
        "limitations": [
            (
                "the ruleset is untuned and frozen: VAL and OOS were read for it in the WP "
                "campaign already, so the OOS numbers here are a decomposition of the "
                "published run, not a second independent sample"
            ),
            (
                "the candidate risks a fixed share of equity per trade and caps the order "
                "notional, while buy & hold is fully invested in one asset: the comparison "
                "is on the same window and cost plane, not on the same capital utilisation"
            ),
            (
                "the periods are calendar halves declared here; three periods over fourteen "
                "months is a decomposition, not a statistical test"
            ),
            (
                "the 4h corpus is aggregated from 1h and ends 2026-02-28, so the last OOS "
                "stretch is shorter than a full half-year and no bar exists after that date"
            ),
            "long side only (spot); no historical order book; nothing is wired into PAPER",
        ],
    }
    payload["verdict"] = oos_trend_verdict(payload)
    return payload


def write_oos_trend_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the OOS review: trades, per-asset and per-period tables, buy & hold, JSON."""
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    trade_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []
    hold_rows: list[dict[str, Any]] = []
    for key, run in payload["runs"].items():
        for trade in run["_trade_rows"]:
            trade_rows.append(
                {
                    "run": key,
                    "book": "combined",
                    "window": run["window"],
                    "scenario": run["scenario"],
                    **trade,
                }
            )
        for asset, block in run["assets"].items():
            for trade in block.get("_trade_rows") or []:
                trade_rows.append(
                    {
                        "run": key,
                        "book": asset,
                        "window": run["window"],
                        "scenario": run["scenario"],
                        **trade,
                    }
                )
        for asset, block in run["assets"].items():
            asset_rows.append(
                {
                    "run": key,
                    "window": run["window"],
                    "scenario": run["scenario"],
                    "asset": asset,
                    "trades": block["trades"],
                    "net_usdt": block["net_usdt"],
                    "expectancy_usdt": block["expectancy_usdt"],
                    "win_rate_pct": block["win_rate_pct"],
                    "profit_factor": block["profit_factor"],
                    "max_drawdown_pct": block["max_drawdown_pct"],
                    "exposure_pct_of_time": block["exposure_pct_of_time"],
                    "signals_printed": block["signals_printed"],
                }
            )
        combined = run["combined"]
        for label, block in sorted((combined.get("by_regime") or {}).items()):
            regime_rows.append(
                {
                    "run": key,
                    "window": run["window"],
                    "scenario": run["scenario"],
                    "label_kind": "candidate_trend_state",
                    "label": label,
                    "trades": block["trades"],
                    "net_usdt": block["net"],
                    "win_rate_pct": block["win_rate"],
                }
            )
        for label, block in sorted((combined.get("by_market_context") or {}).items()):
            regime_rows.append(
                {
                    "run": key,
                    "window": run["window"],
                    "scenario": run["scenario"],
                    "label_kind": "benchmark_market_context",
                    "label": label,
                    "trades": block["trades"],
                    "net_usdt": block["net"],
                    "win_rate_pct": block["win_rate"],
                }
            )
        for row in run["periods"]:
            period_rows.append(
                {"run": key, "window": run["window"], "scenario": run["scenario"], **row}
            )
        for asset, block in run["buy_and_hold"].items():
            hold_rows.append(
                {
                    "run": key,
                    "window": run["window"],
                    "scenario": run["scenario"],
                    "asset": asset,
                    **{k: v for k, v in block.items() if not k.startswith("_")},
                }
            )

    for name, table in (
        ("OOS_TREND_TRADES.csv", trade_rows),
        ("OOS_TREND_ASSETS.csv", asset_rows),
        ("OOS_TREND_PERIODS.csv", period_rows),
        ("OOS_TREND_REGIMES.csv", regime_rows),
        ("BUY_AND_HOLD.csv", hold_rows),
    ):
        path = outdir / name
        C._write_csv(path, table)
        written[name] = path

    context_path = outdir / "MARKET_CONTEXT.csv"
    C._write_csv(context_path, payload["market_context"]["rows"])
    written["MARKET_CONTEXT.csv"] = context_path

    md_path = outdir / "OOS_TREND.md"
    md_path.write_text(_oos_trend_markdown(payload), encoding="utf-8")
    written["OOS_TREND.md"] = md_path

    body: dict[str, Any] = {
        "run_id": payload["run_id"],
        "generated_at_utc": payload["generated_at_utc"],
        "git": payload["git"],
        "source_digest": payload["source_digest"],
        "mode": payload["mode"],
        "entrypoint": payload["entrypoint"],
        "verifier": payload["verifier"],
        "params_hash": payload["params_hash"],
        "experiment": payload["experiment"],
        "market_context": payload["market_context"]["meta"],
        "verdict": payload["verdict"],
        "limitations": payload["limitations"],
        "runs": {
            key: {
                **{k: v for k, v in run.items() if not k.startswith("_")},
                "assets": {
                    asset: {k: v for k, v in block.items() if not k.startswith("_")}
                    for asset, block in run["assets"].items()
                },
            }
            for key, run in payload["runs"].items()
        },
        "artifacts": {
            name: {"sha256": C._sha256(path), "bytes": path.stat().st_size}
            for name, path in written.items()
        },
        "artifact_note": (
            "digests cover every OOS artefact except OOS_TREND.json itself, which is the "
            "file carrying them"
        ),
    }
    json_path = outdir / "OOS_TREND.json"
    json_path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written["OOS_TREND.json"] = json_path
    return written


def _oos_trend_markdown(payload: dict[str, Any]) -> str:
    exp = payload["experiment"]
    verdict = payload["verdict"]
    decision = exp["decision_rule"]
    git = payload["git"]
    window = str(decision["decision_window"])
    run = payload["runs"][f"{window}:BASE"]
    hold_run = payload["runs"][f"{window}:2X_FEES"]
    lines = [
        "# REVISION FUERA DE MUESTRA - EDGE-TREND-01 4h",
        "",
        "| | |",
        "|---|---|",
        f"| experimento | `{exp['id']}` |",
        f"| responde a | `{exp['answer_to']}` |",
        f"| pregunta | {exp['question']} |",
        f"| candidato congelado | `{exp['candidate']}` ({exp['profile']}) |",
        f"| split | `{exp['split']}` |",
        f"| ventana de decision | `{window}` |",
        f"| desde / hasta | `{run['window_start_utc']}` .. `{run['window_end_utc']}` |",
        f"| dias | {run['window_days']} |",
        f"| HEAD al ejecutar | `{git['head_commit']}` |",
        f"| huella del codigo ejecutado (sha256) | `{git['source_sha256']}` |",
        f"| params_hash | `{payload['params_hash']}` |",
        f"| veredicto | **`{verdict['verdict']}`** |",
        "",
        "Ningun parametro se toca: el ruleset es el mismo diccionario congelado con el que",
        "se publico la campana, y las tres ventanas se miden con el mismo presupuesto de",
        "riesgo, el mismo plano de costes y el mismo corpus.",
        "",
        "## Veredicto",
        "",
        f"- **`{verdict['verdict']}`**",
    ]
    lines += [f"- {reason}" for reason in verdict["reasons"]]
    lines += [
        f"- regla: {decision['meaning']}",
        f"- no reclamado: {decision['not_claimed']}",
        "",
        f"## Cumplimiento de la regla en `{window}`",
        "",
        "| criterio | resultado | detalle |",
        "|---|---|---|",
    ]
    for check in verdict["checks"]:
        lines.append(
            f"| `{check['criterion']}` | **{check['result']}** | {check['detail']} |"
        )
    lines += [
        "",
        f"- regla de admision del WP ({C.ADMISSION_CRITERIA['note'].split('.')[0]}): "
        f"**`{verdict['wp_admission']['verdict']}`** — "
        + ("; ".join(verdict["wp_admission"]["reasons"]) or "sin motivos"),
        "",
        "## Cartera combinada por ventana y escenario",
        "",
        "| ventana | escenario | operaciones | neto | expectativa | profit factor | "
        "drawdown | exposicion | mayor operacion / neto |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key in ("DEV:BASE", "VAL:BASE", "OOS:BASE", "OOS:2X_FEES"):
        block = payload["runs"][key]["combined"]
        lines.append(
            f"| `{payload['runs'][key]['window']}` | `{payload['runs'][key]['scenario']}` | "
            f"{block['trades']} | {_money(block['net_usdt'])} | "
            f"{_money(block['expectancy_usdt'])} | {_num(block['profit_factor'])} | "
            f"{_num(block['max_drawdown_pct'])}% | {_num(block['exposure_pct_of_time'])}% | "
            f"{_num(block['largest_trade_share_of_net'])} |"
        )
    lines += [
        "",
        f"## Activos por separado y en conjunto en `{window}` (BASE)",
        "",
        "| libro | operaciones | neto | expectativa | win rate | drawdown | exposicion |",
        "|---|---|---|---|---|---|---|",
    ]
    combined = run["combined"]
    lines.append(
        f"| BTC+ETH+SOL (conjunto) | {combined['trades']} | {_money(combined['net_usdt'])} | "
        f"{_money(combined['expectancy_usdt'])} | {_num(combined['win_rate_pct'])}% | "
        f"{_num(combined['max_drawdown_pct'])}% | {_num(combined['exposure_pct_of_time'])}% |"
    )
    for asset, block in run["assets"].items():
        lines.append(
            f"| {asset} (libro propio) | {block['trades']} | {_money(block['net_usdt'])} | "
            f"{_money(block['expectancy_usdt'])} | {_num(block['win_rate_pct'])}% | "
            f"{_num(block['max_drawdown_pct'])}% | {_num(block['exposure_pct_of_time'])}% |"
        )
    lines += [
        "",
        f"## Contra buy & hold en `{window}` (BASE)",
        "",
        "| activo | candidato neto | candidato retorno | candidato drawdown | b&h retorno | "
        "b&h drawdown |",
        "|---|---|---|---|---|---|",
    ]
    for asset in ASSETS:
        block = run["assets"][asset]
        hold = run["buy_and_hold"][asset]
        lines.append(
            f"| {asset} | {_money(block['net_usdt'])} | {_num(block['return_pct'])}% | "
            f"{_num(block['max_drawdown_pct'])}% | {_num(hold.get('return_pct'))}% | "
            f"{_num(hold.get('max_drawdown_pct'))}% |"
        )
    lines += [
        "",
        f"## Periodos declarados en `{window}` (BASE)",
        "",
        "| periodo | operaciones | neto | expectativa | win rate |",
        "|---|---|---|---|---|",
    ]
    for row in run["periods"]:
        lines.append(
            f"| `{row['period']}` | {row['trades']} | {_money(row['net_usdt'])} | "
            f"{_money(row['expectancy_usdt'])} | {_num(row['win_rate_pct'])}% |"
        )
    lines += [
        "",
        f"## Regimenes en `{window}` (BASE)",
        "",
        "| etiqueta | tipo | operaciones | neto | win rate |",
        "|---|---|---|---|---|",
    ]
    for label, block in sorted((combined.get("by_regime") or {}).items()):
        lines.append(
            f"| `{label}` | estado de tendencia del candidato | {block['trades']} | "
            f"{_money(block['net'])} | {_num(block['win_rate'])}% |"
        )
    for label, block in sorted((combined.get("by_market_context") or {}).items()):
        lines.append(
            f"| `{label}` | contexto de benchmark | {block['trades']} | "
            f"{_money(block['net'])} | {_num(block['win_rate'])}% |"
        )
    lines += [
        "",
        f"- con el coste estresado (`{hold_run['scenario']}`) el conjunto da "
        f"{_money(hold_run['combined']['net_usdt'])} USDT en `{window}`",
        "",
        "## Artefactos de este experimento",
        "",
        "- `OOS_TREND.json` — cartera, libros por activo, periodos, buy & hold y veredicto",
        "- `OOS_TREND_TRADES.csv` — operaciones de la cartera combinada por ventana y escenario",
        "- `OOS_TREND_ASSETS.csv` — metrica por activo y ventana, con libro propio",
        "- `OOS_TREND_PERIODS.csv` — desglose por periodo declarado",
        "- `OOS_TREND_REGIMES.csv` — desglose por estado de tendencia y por contexto de benchmark",
        "- `BUY_AND_HOLD.csv` — la referencia, en la misma ventana y con el mismo plano de costes",
        "- `MARKET_CONTEXT.csv` — la serie de benchmark",
        f"- verificado por `{payload['verifier']}` en un proceso aparte",
        "",
        "## Limites",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    return "\n".join(lines) + "\n"


def _money(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.2f}"


def _num(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.4f}"


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"
