"""Run reporting for the autonomous runtime (§14).

Writes, into ``reports/autonomous-paper/<run_id>/``:

* ``RUN_REPORT.json`` — everything machine-readable (totals, per-asset cycle
  rows, executions, outcomes, performance cells, hash-chain state);
* ``RUN_REPORT.md`` — the human summary, generated from the SAME object so
  the two can never disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

from .runtime import RunSummary

__all__ = ["render_markdown_report", "write_run_report"]


def write_run_report(summary: RunSummary, run_dir: Path | str) -> tuple[Path, Path]:
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "RUN_REPORT.json"
    md_path = directory / "RUN_REPORT.md"
    json_path.write_text(
        json.dumps(summary.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown_report(summary), encoding="utf-8")
    return md_path, json_path


def render_markdown_report(summary: RunSummary) -> str:
    totals = summary.totals()
    lines: list[str] = []
    lines.append(f"# RUN {summary.run_id}")
    lines.append("")
    lines.append("```text")
    lines.append(f"run_id:      {summary.run_id}")
    lines.append(f"commit:      {summary.commit}")
    lines.append(f"environment: {summary.environment}")
    lines.append(f"mode:        {summary.mode}")
    lines.append(f"assets:      {', '.join(summary.assets)}")
    lines.append(f"timeframe:   {summary.timeframe}")
    lines.append(f"cycles:      {summary.cycles}")
    lines.append(f"started:     {summary.started_at_ms}")
    lines.append(f"ended:       {summary.ended_at_ms}")
    lines.append("```")
    lines.append("")

    for cycle in summary.cycle_reports:
        lines.append(f"## Cycle {cycle.cycle} — session {cycle.session_id}")
        lines.append("")
        for row in cycle.assets:
            lines.append(f"### {row.symbol}")
            lines.append("")
            lines.append("```text")
            lines.append(f"Regime: {row.regime}")
            lines.append(f"Strategies evaluated: {len(row.strategies_considered)}")
            lines.append(f"Selected: {row.strategy_selected}")
            if row.expected_gross_edge_bps is not None:
                lines.append(f"Expected gross: {row.expected_gross_edge_bps:.2f} bps")
            if row.expected_cost_bps is not None:
                lines.append(f"Expected cost:  {row.expected_cost_bps:.2f} bps")
            if row.expected_net_edge_bps is not None:
                lines.append(f"Expected net:   {row.expected_net_edge_bps:.2f} bps")
            lines.append(f"Decision: {row.mode.value}")
            lines.append(f"Reason: {row.classification} ({row.reason})")
            lines.append(f"Verifier: {row.verifier_verdict}")
            lines.append(f"Risk: {row.risk_verdict}")
            lines.append(f"DecisionTrace persisted: {'YES' if row.trace_persisted else 'NO'}")
            lines.append(f"Order created: {'YES' if row.order_created else 'NO'}")
            lines.append("```")
            lines.append("")

    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    for key, value in totals.items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append(f"Trace chain: `{json.dumps(summary.chain, sort_keys=True)}`")
    lines.append("")
    lines.append(f"Production actions: {summary.production_actions}")
    lines.append("")

    if summary.outcomes:
        lines.append("## Outcomes resolved")
        lines.append("")
        lines.append(
            "| decision_id | strategy | asset | mode | gross bps | cost bps | net bps | correct |"
        )
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | --- |")
        for outcome in summary.outcomes:
            lines.append(
                f"| {outcome['decision_id']} | {outcome['strategy_id']} | {outcome['asset']} "
                f"| {outcome['mode']} | {outcome['gross_return_bps']:.4f} "
                f"| {outcome['estimated_cost_bps']:.4f} | {outcome['net_hypothetical_bps']:.4f} "
                f"| {outcome['direction_correct']} |"
            )
        lines.append("")

    if summary.performance:
        lines.append("## Strategy performance (experience learning)")
        lines.append("")
        lines.append(
            "| strategy | asset | regime | n | shadow n | paper n | gross bps | net bps "
            "| hit rate | PF | max DD bps | recent net bps |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for cell in summary.performance:
            pf = cell["profit_factor"]
            lines.append(
                f"| {cell['strategy_id']} | {cell['asset']} | {cell['regime']} "
                f"| {cell['sample_size']} | {cell['shadow_sample_size']} "
                f"| {cell['paper_sample_size']} | {cell['gross_expectancy_bps']:.4f} "
                f"| {cell['net_expectancy_bps']:.4f} | {cell['hit_rate']:.4f} "
                f"| {'n/a' if pf is None else f'{pf:.4f}'} | {cell['max_drawdown_bps']:.4f} "
                f"| {cell['recent_net_expectancy_bps']:.4f} |"
            )
        lines.append("")

    if summary.executions:
        lines.append("## Paper executions")
        lines.append("")
        for execution in summary.executions:
            lines.append(f"- {execution}")
        lines.append("")

    if summary.errors:
        lines.append("## Errors")
        lines.append("")
        for error in summary.errors:
            lines.append(f"- {error}")
        lines.append("")

    return "\n".join(lines) + "\n"
