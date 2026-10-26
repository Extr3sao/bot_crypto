"""EXP-STRAT-DYNAMIC-001 — CURRENT_STATIC_ROUTER vs DYNAMIC_STRATEGY_ECOSYSTEM.

Both arms run on the SAME dataset, the SAME families, the SAME costs and the
SAME TP/SL/risk, because both consume the identical per-family trade stream
produced by ``scripts/multi_family_backtest.simulate_family``. The only thing
that differs is WHO is allowed to trade:

* STATIC  : one fixed family, always on (the current single-strategy router).
* DYNAMIC : every family is evaluated in shadow; the deterministic lifecycle
            controller promotes/demotes families from the evidence each family
            accumulates over time. Only ACTIVE families contribute to equity.

Windows follow the preregistered split: DEV = W1..W4, VAL = W5..W6, OOS = W7
(locked; reported but never used to choose anything).

This experiment DISCOVERS whether the dynamic architecture helps. It is not
tuned to make it win: if the dynamic arm does not beat the static arm under
comparable conditions, the report says DO_NOT_PROMOTE.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import multi_family_backtest as hb  # noqa: E402

from trading_bot.research.experiment_evidence import (  # noqa: E402
    build_manifest,
    fingerprint_files,
    make_run_id,
    write_run,
)
from trading_bot.strategy_lifecycle.config import (  # noqa: E402
    HealthPolicy,
    LifecyclePolicy,
)
from trading_bot.strategy_lifecycle.contracts import (  # noqa: E402
    ContextKey,
    ExecutionMode,
    LifecycleState,
)
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem  # noqa: E402
from trading_bot.strategy_lifecycle.performance import PerformanceObservation  # noqa: E402

EXPERIMENT_ID = "EXP-STRAT-DYNAMIC-001"
OUTDIR = REPO / "reports" / "strategy-dynamic"
DATA_DIR = REPO / "reports" / "strategy-baseline" / "data"
ASSET = "BTCUSDT"
WINDOWS = {
    "DEV": ["BTCUSDT_W1_2026-03.json", "BTCUSDT_W2_2026-04.json", "BTCUSDT_W3_2026-05.json", "BTCUSDT_W4_2026-06.json"],
    "VALIDATION": ["BTCUSDT_W5_2026-07.json", "BTCUSDT_W6_2026-08.json"],
    "OOS_LOCKED": ["BTCUSDT_W7_2026-09.json"],
}
FAMILIES = ["ema_crossover", "momentum", "breakout", "trend", "mean_reversion", "volatility"]
#: The experiment is fully deterministic; the seed is recorded for provenance.
SEED = 0

# Preregistered lifecycle policy for the experiment. It is deliberately stricter
# than a "last N trades" rule and identical for every family and window.
EXPERIMENT_POLICY = LifecyclePolicy(
    minimum_samples=40,
    minimum_expectancy_bps=0.0,
    minimum_profit_factor=1.0,
    maximum_drawdown_bps=250.0,
    minimum_stability=0.5,
    minimum_positive_windows=2,
    minimum_regime_samples=15,
    cost_adjusted_positive=True,
    # No IndependentVerifier runs in an offline loop; the runtime keeps this True.
    independent_verification_required=False,
    demotion_minimum_samples=25,
    demotion_expectancy_bps=-10.0,
    demotion_profit_factor=0.9,
    demotion_drawdown_bps=300.0,
    degrade_persistence=2,
    recovery_minimum_samples=40,
    recovery_minimum_expectancy_bps=0.0,
    activation_cooldown_ms=0,
    eligibility_dwell_ms=0,
    demotion_quiet_ms=0,
)
# Windows are owned by the performance store (DEF-VERIFY-004); the health policy
# carries only thresholds, so this no longer claims a window configuration it
# does not control.
EXPERIMENT_HEALTH = HealthPolicy(min_samples=20)


def _regime(bars: list[dict[str, Any]], i: int, lookback: int = 100) -> str:
    """Deterministic regime label from data available up to and including i (§25)."""
    start = max(0, i - lookback + 1)
    window = bars[start : i + 1]
    if len(window) < 2:
        return "RANGE"
    first, last = window[0]["close"], window[-1]["close"]
    ret = (last - first) / first
    highs = max(b["high"] for b in window)
    lows = min(b["low"] for b in window)
    rng = (highs - lows) / first
    if rng > 0 and abs(ret) / rng < 0.25:
        return "RANGE"
    return "TREND_UP" if ret >= 0 else "TREND_DOWN"


@dataclass
class Trade:
    family: str
    window: str
    entry_ts: int
    net: float
    notional: float
    regime: str

    @property
    def net_bps(self) -> float:
        return 0.0 if self.notional <= 0 else self.net / self.notional * 10_000.0


def _load_window(filename: str) -> list[dict[str, Any]]:
    path = REPO / "reports" / "strategy-baseline" / "data" / filename
    data: list[dict[str, Any]] = json.loads(path.read_text())
    return data


def _family_trades(family: str, window: str, bars: list[dict[str, Any]]) -> list[Trade]:
    sim = hb.simulate_family_legacy(family, ASSET, bars, 1.0, 1.0)
    out: list[Trade] = []
    for t in sim["trades"]:
        entry_ts = int(t["entry_ts"])
        idx = _ts_index(bars, entry_ts)
        out.append(
            Trade(
                family=family,
                window=window,
                entry_ts=entry_ts,
                net=float(t["net"]),
                notional=float(t["notional"]),
                regime=_regime(bars, idx),
            )
        )
    return out


def _ts_index(bars: list[dict[str, Any]], ts: int) -> int:
    lo, hi = 0, len(bars) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid]["ts"] < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _metrics(trades: list[Trade], eval_bars: int, tf_min: float = 5.0) -> dict[str, Any]:
    nets = [t.net for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    equity = hb.START_EQUITY
    peak = equity
    max_dd = 0.0
    curve = []
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0 if peak else 0.0)
        curve.append(equity)
    rets = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve)) if curve[i - 1] > 0]
    sharpe = None
    if len(rets) > 30:
        mu = mean(rets)
        sd = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5
        if sd > 0:
            bars_per_year = (60.0 / tf_min) * 24 * 365
            sharpe = round(mu / sd * (bars_per_year**0.5), 3)
    return {
        "trades": len(trades),
        "net": round(sum(nets), 2),
        "final_equity": round(equity, 2),
        "expectancy": round(mean(nets), 4) if nets else 0.0,
        "win_rate": round(100.0 * len(wins) / len(nets), 2) if nets else 0.0,
        "profit_factor": round(gw / gl, 4) if gl else None,
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_proxy": sharpe,
    }


def _run_family_streams() -> tuple[dict[str, list[Trade]], dict[str, int]]:
    streams: dict[str, list[Trade]] = {}
    bar_counts: dict[str, int] = {}
    for split, files in WINDOWS.items():
        for filename in files:
            bars = _load_window(filename)
            bar_counts[filename] = len(bars)
            for family in FAMILIES:
                streams.setdefault(filename, [])
                streams[filename].extend(_family_trades(family, split, bars))
    return streams, bar_counts


def _static_family(streams: dict[str, list[Trade]]) -> str:
    """Choose the single best family on DEV only (never VAL/OOS)."""
    dev_nets: dict[str, float] = defaultdict(float)
    for filename in WINDOWS["DEV"]:
        for t in streams[filename]:
            dev_nets[t.family] += t.net
    return max(sorted(dev_nets), key=lambda f: dev_nets[f])


def _dynamic(
    streams: dict[str, list[Trade]],
) -> tuple[dict[str, list[Trade]], dict[str, Any]]:
    eco = DynamicStrategyEcosystem(
        lifecycle_policy=EXPERIMENT_POLICY, health_policy=EXPERIMENT_HEALTH
    )
    for family in FAMILIES:
        from trading_bot.strategy_lifecycle.contracts import StrategyDescriptor

        eco.register(
            StrategyDescriptor(
                strategy_id=family,
                strategy_version=f"{family}@5m",
                family=family,
                assets=("BTC",),
                timeframes=("5m",),
                supported_regimes=("TREND_UP", "TREND_DOWN", "RANGE"),
                runtime_implementation=f"trading_bot.research.families.{family}",
                lifecycle_state=LifecycleState.SHADOW,
                provenance={"dataset": "strategy-baseline", "commit": _commit()},
            )
        )

    # Chronological stream across ALL windows (so the lifecycle learns over time).
    all_trades: list[Trade] = []
    for filename in [*WINDOWS["DEV"], *WINDOWS["VALIDATION"], *WINDOWS["OOS_LOCKED"]]:
        all_trades.extend(streams[filename])
    all_trades.sort(key=lambda t: (t.entry_ts, t.family))

    accepted: dict[str, list[Trade]] = defaultdict(list)
    transitions: list[dict[str, Any]] = []
    for t in all_trades:
        state = eco.registry.state_of(t.family)
        if state is LifecycleState.ACTIVE:
            accepted[t.window].append(t)
        # Every trade (active or shadow) is evidence for the family's own cell.
        eco.performance.record(
            PerformanceObservation(
                context=ContextKey(t.family, "BTC", "5m", t.regime),
                timestamp_ms=t.entry_ts,
                gross_bps=t.net_bps,
                net_bps=t.net_bps,
                cost_bps=0.0,
                notional_usdt=t.notional,
                correct=t.net > 0,
                execution_mode=ExecutionMode.SHADOW,
            )
        )
        decision = eco.lifecycle_decision(
            strategy_id=t.family,
            asset="BTC",
            timeframe="5m",
            regime=t.regime,
            now_ms=t.entry_ts,
            verification_passed=True,
        )
        if decision.changed:
            transitions.append(decision.to_dict())
    return accepted, {
        "transitions": transitions,
        "churn": eco.registry.churn(),
        "final_states": eco.lifecycle_map(FAMILIES),
    }


def _commit() -> str:
    try:
        import subprocess

        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO, check=True
        ).stdout.strip()
    except Exception:  # pragma: no cover
        return ""


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    streams, bar_counts = _run_family_streams()
    static_family = _static_family(streams)

    static_by_window: dict[str, list[Trade]] = defaultdict(list)
    for filename in streams:
        for t in streams[filename]:
            if t.family == static_family:
                static_by_window[t.window].append(t)

    dynamic_by_window, dynamic_meta = _dynamic(streams)

    def split_report(by_window: dict[str, list[Trade]]) -> dict[str, Any]:
        out = {}
        for split in WINDOWS:
            trades = by_window.get(split, [])
            eval_bars = sum(bar_counts[f] for f in WINDOWS[split])
            out[split] = _metrics(trades, eval_bars)
        return out

    static_report = split_report(static_by_window)
    dynamic_report = split_report(dynamic_by_window)

    def total(report: dict[str, Any]) -> float:
        return round(
            float(report["DEV"]["net"]) + float(report["VALIDATION"]["net"]), 2
        )

    static_val = total(static_report)
    dynamic_val = total(dynamic_report)
    dynamic_trades = sum(
        dynamic_report[s]["trades"] for s in ("DEV", "VALIDATION")
    )
    if dynamic_trades == 0:
        # An abstaining arm is NOT a winning arm. Zero trades demonstrates no
        # measurable value; it is reported as DO_NOT_PROMOTE, never as an
        # improvement over a losing static arm (that would be FALSE_SUCCESS).
        improved = False
        verdict = "DO_NOT_PROMOTE"
        note = (
            "dynamic arm abstained (0 trades): the preregistered evidence gate was "
            "not met for any family/regime cell, so no measurable value was "
            "demonstrated. Reported as DO_NOT_PROMOTE, not as an improvement."
        )
    elif dynamic_val > static_val:
        improved = True
        verdict = "PROMOTE_CANDIDATE"
        note = "dynamic DEV+VAL net exceeded static under identical economics"
    else:
        improved = False
        verdict = "DO_NOT_PROMOTE"
        note = "dynamic DEV+VAL net did not exceed static under identical economics"
    result: dict[str, Any] = {
        "experiment_id": "EXP-STRAT-DYNAMIC-001",
        "commit": _commit(),
        "asset": ASSET,
        "dataset": "reports/strategy-baseline/data (BTCUSDT W1..W7)",
        "splits": {k: v for k, v in WINDOWS.items()},
        "static_family": static_family,
        "families": FAMILIES,
        "economics": {
            "fees": hb.FEES, "slippage": hb.SLIP, "tp_pct": hb.TP_PCT,
            "risk_pct": hb.RISK_PCT, "start_equity": hb.START_EQUITY,
        },
        "static": static_report,
        "dynamic": dynamic_report,
        "dynamic_meta": dynamic_meta,
        "decision": {
            "dev_val_static_net": static_val,
            "dev_val_dynamic_net": dynamic_val,
            "dev_val_dynamic_trades": dynamic_trades,
            "dynamic_improved": improved,
            "verdict": verdict,
            "reason": note,
            "oos_locked": True,
            "note": (
                "OOS (W7) is reported for completeness but was never used to choose, "
                "tune or gate anything. Development used DEV; the comparison above "
                "uses DEV+VALIDATION only."
            ),
        },
        "chart": {
            "note": "see static/dynamic split tables",
        },
    }

    run_id = make_run_id(EXPERIMENT_ID, commit_sha=_commit())
    result["run_id"] = run_id
    result["verdict"] = verdict

    # Authoritative, immutable evidence lives under the run directory (§8).
    dataset_files = [
        DATA_DIR / f
        for f in [*WINDOWS["DEV"], *WINDOWS["VALIDATION"], *WINDOWS["OOS_LOCKED"]]
    ]
    manifest = build_manifest(
        experiment_id=EXPERIMENT_ID,
        run_id=run_id,
        script_path=Path(__file__),
        repo=REPO,
        config={
            "windows": WINDOWS,
            "families": FAMILIES,
            "seed": SEED,
            "economics": result["economics"],
        },
        dataset_fingerprint=fingerprint_files(dataset_files),
        seed=SEED,
        started_at=started_at,
        completed_at=datetime.now(UTC).isoformat(),
        result=result,
        decision=verdict,
    )
    markdown = _report_markdown(result)
    stdout_text = (
        json.dumps({k: result[k]["DEV"] for k in ("static", "dynamic")}, indent=2)
        + "\ndecision: "
        + json.dumps(result["decision"], indent=2)
        + f"\nFINAL_DECISION={verdict}\n"
    )
    run_dir = write_run(
        reports_root=OUTDIR,
        experiment_id=EXPERIMENT_ID,
        manifest=manifest,
        result=result,
        stdout_text=stdout_text,
        report_markdown=markdown,
    )
    # Top-level files are human-readable pointers, explicitly NON-EVIDENCE; the
    # authoritative artifact is the immutable run directory above.
    result["evidence_status"] = "POINTER / NON-EVIDENCE"
    result["authoritative_run_dir"] = run_dir.relative_to(REPO).as_posix()
    (OUTDIR / f"{EXPERIMENT_ID}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    (OUTDIR / f"{EXPERIMENT_ID}.md").write_text(markdown, encoding="utf-8")
    # A bare, ambiguous exp.log must never linger as if it were current evidence.
    stale_log = OUTDIR / "exp.log"
    if stale_log.exists():
        stale_log.unlink()
    print(stdout_text)
    return 0


def _report_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# EXP-STRAT-DYNAMIC-001 — static router vs dynamic ecosystem",
        "",
        f"- commit: `{result['commit']}`",
        f"- asset/dataset: {result['asset']} — {result['dataset']}",
        f"- static family (chosen on DEV only): `{result['static_family']}`",
        f"- economics: fees={result['economics']['fees']} slip={result['economics']['slippage']} "
        f"tp={result['economics']['tp_pct']} risk_pct={result['economics']['risk_pct']}",
        "",
        "## Metrics by split",
        "",
        "| split | arm | trades | net | expectancy | win_rate | PF | max_dd% | sharpe |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for split in ("DEV", "VALIDATION", "OOS_LOCKED"):
        for arm in ("static", "dynamic"):
            m = result[arm][split]
            lines.append(
                f"| {split} | {arm} | {m['trades']} | {m['net']} | {m['expectancy']} | "
                f"{m['win_rate']} | {m['profit_factor']} | {m['max_drawdown_pct']} | {m['sharpe_proxy']} |"
            )
    lines += [
        "",
        "## Activation churn",
        "",
        f"```json\n{json.dumps(result['dynamic_meta']['churn'], indent=2)}\n```",
        "",
        "## Decision",
        "",
        f"- DEV+VAL static net: {result['decision']['dev_val_static_net']}",
        f"- DEV+VAL dynamic net: {result['decision']['dev_val_dynamic_net']} "
        f"({result['decision'].get('dev_val_dynamic_trades', 0)} trades)",
        f"- verdict: **{result['decision']['verdict']}**",
        f"- {result['decision'].get('reason', result['decision']['note'])}",
        f"- {result['decision']['note']}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
