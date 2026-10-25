"""Generate the STRATEGY_* observability reports (§27) + RUN_REPORT (§28).

Status / churn / history come from the real EXP-STRAT-DYNAMIC-001 run. Health,
regime matrix and champion/challenger come from a deterministic in-memory demo
fixture (clearly labelled), because the offline experiment does not persist
per-cell health. Nothing here executes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.strategy_lifecycle.champion import ChallengerEvaluation  # noqa: E402
from trading_bot.strategy_lifecycle.contracts import (  # noqa: E402
    ContextKey,
    LifecycleState,
    StrategyDescriptor,
)
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem  # noqa: E402
from trading_bot.strategy_lifecycle.performance import (  # noqa: E402
    PerformanceObservation,
)

OUT = REPO / "reports" / "strategy-lifecycle"
EXP = REPO / "reports" / "strategy-dynamic" / "EXP-STRAT-DYNAMIC-001.json"


def _demo() -> dict[str, Any]:
    eco = DynamicStrategyEcosystem()
    assets = ("BTC", "ETH")
    for family in ("momentum", "mean_reversion", "trend"):
        eco.register(
            StrategyDescriptor(
                strategy_id=family,
                strategy_version=f"{family}@5m",
                family=family,
                assets=assets,
                timeframes=("5m",),
                supported_regimes=("TREND_UP", "TREND_DOWN", "RANGE"),
                runtime_implementation=f"trading_bot.research.families.{family}",
                lifecycle_state=LifecycleState.SHADOW,
            )
        )
    # Deterministic fixture: momentum strong in TREND_UP, weak in RANGE; etc.
    profiles = {
        "momentum": {"TREND_UP": 12.0, "TREND_DOWN": 6.0, "RANGE": -6.0},
        "mean_reversion": {"TREND_UP": -5.0, "TREND_DOWN": -3.0, "RANGE": 11.0},
        "trend": {"TREND_UP": 8.0, "TREND_DOWN": 9.0, "RANGE": -4.0},
    }
    for family, by_regime in profiles.items():
        for regime, value in by_regime.items():
            for i in range(120):
                win = i % 3 != 0
                net = value if win else -abs(value) / 3
                eco.performance.record(
                    PerformanceObservation(
                        context=ContextKey(family, "BTC", "5m", regime),
                        timestamp_ms=i * 300_000,
                        gross_bps=net + 5.0,
                        net_bps=net,
                        cost_bps=5.0,
                        notional_usdt=100.0,
                        correct=net > 0,
                    )
                )
    health_lines = [
        "# STRATEGY_HEALTH_REPORT",
        "",
        "Fixture: deterministic demo cells (not runtime evidence).",
        "",
    ]
    health_lines.append("| strategy | regime | state | score | flags |")
    health_lines.append("|---|---|---|---|---|")
    matrix: dict[str, dict[str, Any]] = {}
    for family in profiles:
        matrix[family] = {}
        for regime in ("TREND_UP", "RANGE"):
            report = eco.health_for(
                strategy_id=family, asset="BTC", timeframe="5m", regime=regime, now_ms=10**12
            )
            matrix[family][regime] = report.to_dict()
            health_lines.append(
                f"| {family} | {regime} | {report.health_state.value} | {report.score:.2f} | "
                f"{', '.join(report.degradation_flags) or '-'} |"
            )
    # Champion/challenger fixture.
    champ = ChallengerEvaluation(
        "momentum", 200, 12.0, 1.6, 60.0, window_net_bps=(40.0, 40.0, 40.0)
    )
    chal = ChallengerEvaluation("trend", 200, 18.0, 1.9, 80.0, window_net_bps=(60.0, 60.0, 60.0))
    assert eco.champion is not None
    comparison = eco.champion.compare(
        context=ContextKey("momentum", "BTC", "5m", "TREND_UP"),
        champion=champ,
        challengers=[chal],
        timestamp_ms=10**12,
    )
    return {"eco": eco, "health_lines": health_lines, "matrix": matrix, "comparison": comparison}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    demo = _demo()
    eco: DynamicStrategyEcosystem = demo["eco"]

    # Demo registry snapshot.
    (OUT / "STRATEGY_HEALTH_REPORT.md").write_text(
        "\n".join(demo["health_lines"]) + "\n", encoding="utf-8"
    )
    (OUT / "STRATEGY_HEALTH_REPORT.json").write_text(
        json.dumps(demo["matrix"], indent=2), encoding="utf-8"
    )

    # Regime matrix MD.
    lines = [
        "# STRATEGY_REGIME_MATRIX",
        "",
        "Fixture: net expectancy bps by strategy x regime.",
        "",
    ]
    lines.append("| strategy | regime | samples | net_expectancy_bps | profit_factor | health |")
    lines.append("|---|---|---|---|---|---|")
    for family, by_regime in demo["matrix"].items():
        for regime, row in sorted(by_regime.items()):
            lines.append(
                f"| {family} | {regime} | {row['metrics'].get('sample_count', 0):.0f} | "
                f"{row['metrics'].get('net_expectancy_bps', 0):.2f} | "
                f"{row['metrics'].get('profit_factor', 0):.2f} | {row['health_state']} |"
            )
    (OUT / "STRATEGY_REGIME_MATRIX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    comp = demo["comparison"]
    cc_lines = [
        "# STRATEGY_CHAMPION_CHALLENGER_REPORT",
        "",
        "Fixture: deterministic comparison (not runtime evidence).",
        "",
        f"- context: {comp.context}",
        f"- champion: {comp.champion_id}",
        f"- outcome: **{comp.outcome.value}**",
        f"- winner: {comp.winner_id}",
        "",
        "## challengers",
        "",
        "| strategy | samples | net_expectancy | profit_factor |",
        "|---|---|---|---|",
    ]
    for c in comp.challengers:
        cc_lines.append(
            f"| {c.strategy_id} | {c.sample_count} | {c.net_expectancy_bps:.2f} | "
            f"{(c.profit_factor or 0):.2f} |"
        )
    cc_lines += ["", "## evidence", *[f"- {e}" for e in comp.evidence], ""]
    (OUT / "STRATEGY_CHAMPION_CHALLENGER_REPORT.md").write_text(
        "\n".join(cc_lines), encoding="utf-8"
    )

    # Status / churn / history from the real experiment if present.
    if EXP.exists():
        exp = json.loads(EXP.read_text())
        meta = exp.get("dynamic_meta", {})
        status_lines = [
            "# STRATEGY_STATUS_REPORT",
            "",
            f"Source: EXP-STRAT-DYNAMIC-001 (`{exp.get('commit', '')}`).",
            "",
            "| strategy | final_state |",
            "|---|---|",
        ]
        for sid, state in sorted(meta.get("final_states", {}).items()):
            status_lines.append(f"| {sid} | {state} |")
        (OUT / "STRATEGY_STATUS_REPORT.md").write_text(
            "\n".join(status_lines) + "\n", encoding="utf-8"
        )

        churn = meta.get("churn", {})
        churn_lines = [
            "# STRATEGY_ACTIVATION_CHURN",
            "",
            f"Source: EXP-STRAT-DYNAMIC-001 (`{exp.get('commit', '')}`).",
            "",
            "```json",
            json.dumps(churn, indent=2),
            "```",
            "",
        ]
        (OUT / "STRATEGY_ACTIVATION_CHURN.md").write_text("\n".join(churn_lines), encoding="utf-8")

        hist_lines = [
            "# STRATEGY_LIFECYCLE_HISTORY",
            "",
            "| strategy | from | to | reasons |",
            "|---|---|---|---|",
        ]
        for t in meta.get("transitions", []):
            hist_lines.append(
                f"| {t['strategy_id']} | {t['from_state']} | {t['to_state']} | "
                f"{', '.join(t['reason_codes'])} |"
            )
        (OUT / "STRATEGY_LIFECYCLE_HISTORY.md").write_text(
            "\n".join(hist_lines) + "\n", encoding="utf-8"
        )
    else:
        (OUT / "STRATEGY_STATUS_REPORT.md").write_text(
            "# STRATEGY_STATUS_REPORT\n\nEXP-STRAT-DYNAMIC-001 output not found; "
            "run scripts/strategy_dynamic_experiment.py first.\n",
            encoding="utf-8",
        )

    # RUN_REPORT
    run = {
        "run_id": "strategy-lifecycle-report",
        "registry": eco.registry.as_dict(),
        "champion_challenger": comp.to_dict(),
        "regime_matrix": demo["matrix"],
    }
    (OUT / "RUN_REPORT.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (OUT / "RUN_REPORT.md").write_text(
        "\n".join(
            [
                "# RUN_REPORT — strategy lifecycle observability",
                "",
                f"- strategies registered: {eco.registry.strategy_ids()}",
                f"- champion/challenger outcome: {comp.outcome.value}",
                "- reports: STRATEGY_STATUS_REPORT, STRATEGY_HEALTH_REPORT, "
                "STRATEGY_REGIME_MATRIX, STRATEGY_CHAMPION_CHALLENGER_REPORT, "
                "STRATEGY_LIFECYCLE_HISTORY, STRATEGY_ACTIVATION_CHURN",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("wrote reports to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
