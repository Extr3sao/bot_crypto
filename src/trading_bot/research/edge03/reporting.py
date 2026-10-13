"""EDGE-03 observability — the daily reading and the accumulated one.

An observation that nobody can read is not an observation. This module turns the run's
own ledger into two documents:

* a **daily report** for the day of the run (the newest UTC date the store covers), saying
  what was received, how good it was, what the frozen rulesets decided on it and what the
  hypothetical book looked like — with every number that is not a real trade labelled as
  one;
* a **cumulative report** for the whole forward window, which is the only place the number
  of independent observation days appears.

Both are generated from the artefacts the run already wrote (the ingest ledger, the store
manifest, the quality audit and the shadow payload), never from prose: if a number is in
the report it came out of a file next to it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .forward_plan import MIN_OBSERVATION_DAYS, OBSERVATION_COVERAGE

__all__ = [
    "cumulative_markdown",
    "daily_markdown",
    "observation_verdict",
    "write_observability",
]


def _iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def _day(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    return f"{value:,.{digits}f}"


def observation_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """The one verdict this lane is allowed to reach, from the declared floor.

    The verdict is about the OBSERVATION WINDOW, not about this run's delta: a lane that
    already holds its bars and adds none today is not stalled, it is up to date, and the
    run records ``no_new_data`` per series either way. Only a store that has never held a
    forward bar is stalled.
    """
    health = payload.get("health", {})
    days = health.get("observation_days", 0)
    stored = int(health.get("stored_bars") or 0)
    new_bars = int(health.get("new_bars") or 0)
    if stored == 0:
        state = "OBSERVATION_STALLED"
        reason = "the forward store holds no bar: no closed bar has ever been ingested"
    elif days < MIN_OBSERVATION_DAYS:
        state = "OBSERVATION_RUNNING"
        reason = (
            f"{days} independent observation day(s) accumulated, below the declared floor of "
            f"{MIN_OBSERVATION_DAYS}: the lane reports what it saw and claims nothing"
        )
    else:
        state = "OBSERVATION_AVAILABLE"
        reason = (
            f"{days} independent observation day(s) accumulated; the lane still promotes "
            "nothing (the forward pipeline does not read an admission criterion)"
        )
    return {
        "state": state,
        "reason": reason,
        "observation_days": days,
        "stored_bars": stored,
        "new_bars_this_run": new_bars,
        "observation_floor": MIN_OBSERVATION_DAYS,
        "coverage_required": OBSERVATION_COVERAGE,
        "parity": payload.get("parity", {}).get("verdict"),
        "promotion": "NONE",
        "not_claimed": (
            "a running forward pipeline is not evidence of an edge: no admission criterion is "
            "evaluated here, and no strategy is promoted"
        ),
    }


def _quality_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(payload.get("quality", {})):
        audit = payload["quality"][key]
        rows.append(
            {
                "series": key,
                "bars": audit.get("bars"),
                "first_ts": audit.get("first_ts"),
                "last_ts": audit.get("last_ts"),
                "gaps": audit.get("gap_count"),
                "missing_bars": audit.get("missing_bars"),
                "duplicates": audit.get("duplicates"),
                "out_of_order": audit.get("out_of_order"),
                "contiguous": audit.get("contiguous"),
            }
        )
    return rows


def _series_latency(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """How long after a bar closed the store learned about it: the lane's own latency."""
    rows: list[dict[str, Any]] = []
    for key in sorted(payload.get("latency", {})):
        rows.append({"series": key, **payload["latency"][key]})
    return rows


def daily_markdown(payload: dict[str, Any], day: str) -> str:
    """One observation day: what arrived, what was decided, what it would have paid."""
    day_rows = payload.get("daily", {}).get(day, {})
    lines = [
        f"# EDGE-03 forward observation — {day} (UTC)",
        "",
        f"Run `{payload.get('run_id')}` at {payload.get('generated_at_utc')}; "
        f"market instant {_iso(payload.get('observed_at_ms'))}.",
        "",
        "## Data received",
        "",
        "| series | bars stored | first bar (UTC) | last bar (UTC) | gaps | duplicates | contiguous |",
        "| --- | ---: | --- | --- | ---: | ---: | --- |",
    ]
    for row in _quality_rows(payload):
        lines.append(
            f"| `{row['series']}` | {row['bars']} | {_iso(row['first_ts'])} | "
            f"{_iso(row['last_ts'])} | {row['gaps']} | {row['duplicates']} | "
            f"{'yes' if row['contiguous'] else '**NO**'} |"
        )
    lines += [
        "",
        f"Bars on this date (all series): **{day_rows.get('bars', 0)}**; of those, fetched by "
        f"this run: **{day_rows.get('appended', 0)}**. Bars the run appended in total "
        f"(every date): **{day_rows.get('run_appended', 0)}**.",
        "",
    ]
    health = payload.get("health", {})
    if health.get("no_new_data_series"):
        lines += [
            "Series with no new closed bar at this instant: "
            + ", ".join(f"`{s}`" for s in health["no_new_data_series"])
            + ". That is a recorded result (`no_new_data`), not an error.",
            "",
        ]
    lines += ["## Strategies read on this date", ""]
    arms_today = _arms_for_day(payload, day)
    if not arms_today:
        lines.append("No arm printed anything on this date.")
    for arm in sorted(arms_today):
        summary = payload.get("shadow", {}).get("arm_summaries", {}).get(arm, {})
        row = arms_today[arm]
        lines.append(
            f"- `{arm}` ({summary.get('timeframe')}, {summary.get('scenario')}): "
            f"{row.get('signals', 0)} signal(s), {row.get('trades', 0)} hypothetical "
            f"fill(s), {row.get('refusals', 0)} refusal(s), net {_num(row.get('net_usdt'))} USDT"
        )
    lines += [
        "",
        "Every fill above is **hypothetical**: `order_sent: false`, no exchange client, no "
        "capital. A signal is a proposal the frozen ruleset printed, not a trade taken.",
        "",
        "## Signals and decisions on this date",
        "",
        f"- Signals printed: **{day_rows.get('signals', 0)}**",
        f"- Entries the budget refused: **{day_rows.get('refusals', 0)}**",
        f"- Hypothetical fills: **{day_rows.get('trades', 0)}**",
        "",
    ]
    if day_rows.get("refusal_mix"):
        lines += ["| refusal | count |", "| --- | ---: |"]
        for reason, count in sorted(day_rows["refusal_mix"].items()):
            lines.append(f"| `{reason}` | {count} |")
        lines.append("")
    lines += [
        "## Hypothetical book",
        "",
        f"- Equity (primary arm `{payload.get('shadow', {}).get('primary_arm')}`): "
        f"{_num(day_rows.get('equity'))} USDT of a 10,000 USDT start",
        f"- Cumulative net on this date: {_num(day_rows.get('cumulative_net_usdt'))} USDT",
        f"- Drawdown at the close of the date: {_num(day_rows.get('drawdown_pct'))} %",
        f"- Open exposure: {_num(day_rows.get('exposure_usdt'))} USDT "
        "(not reconstructed per day; the arm-level table in the cumulative report carries it)",
        "",
        "## Process state",
        "",
        "- Ingest outcomes: "
        + ", ".join(
            f"`{k}` {v}" for k, v in sorted(payload.get("health", {}).get("ingest_outcomes", {}).items())
        )
        or "- Ingest outcomes: —",
        f"- Errors raised by the run: **{len(payload.get('health', {}).get('errors', []))}**",
        "- Ingestion latency of the bars THIS run pulled (bar close → store), seconds: "
        + (
            ", ".join(
                f"`{row['series']}` {_num(row.get('fresh_samples'), 0)} sample(s) "
                f"min {_num(row.get('fresh_min_seconds'), 0)} / "
                f"median {_num(row.get('fresh_median_seconds'), 0)} / "
                f"max {_num(row.get('fresh_max_seconds'), 0)}"
                for row in _series_latency(payload)
                if row.get("fresh_samples")
            )
            or "this run pulled no new bar"
        ),
        "- Window latency over every stored bar, seconds (dominated by the one-time "
        "backfill of the frozen prefix, so it is NOT a feed latency): "
        + (
            ", ".join(
                f"`{row['series']}` max {_num(row.get('max_seconds'), 0)}"
                for row in _series_latency(payload)
            )
            or "no bar was recorded on this date"
        ),
        "",
        "## Observation days",
        "",
        f"- Independent observation days accumulated: "
        f"**{payload.get('health', {}).get('observation_days', 0)}** "
        f"(floor {MIN_OBSERVATION_DAYS}, coverage {OBSERVATION_COVERAGE:.0%}).",
        "",
    ]
    return "\n".join(lines)


def _ledger_rows(payload: dict[str, Any]) -> dict[str, int] | None:
    """How many ledger rows are on file, split into the two passes of a run.

    ``health.ingest_runs`` counts the *observation* pass only, so a report that stopped
    there would contradict a ledger that also holds the restart pass. The line is counted
    from the file when it exists and omitted when it does not, rather than estimated.
    """
    ingest = payload.get("ingest") or {}
    rel = ingest.get("ledger_path")
    if not rel:
        return None
    # src/trading_bot/research/edge03/reporting.py → the repository root
    path = Path(__file__).resolve().parents[4] / str(rel)
    if not path.is_file():
        return None
    total = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    observation = int((payload.get("health") or {}).get("ingest_runs") or 0)
    return {
        "total": total,
        "observation": observation,
        "restart": total - observation if total > observation else 0,
    }


def cumulative_markdown(payload: dict[str, Any]) -> str:
    """The whole forward window, with the observation length stated before any metric."""
    verdict = payload.get("verdict", observation_verdict(payload))
    health = payload.get("health", {})
    lines = [
        "# EDGE-03 forward observation — cumulative",
        "",
        f"Run `{payload.get('run_id')}` at {payload.get('generated_at_utc')}; "
        f"market instant {_iso(payload.get('observed_at_ms'))}.",
        "",
        f"**{verdict['state']}** — {verdict['reason']}",
        "",
        f"Promotion: **{verdict['promotion']}**. Risk parity: **{verdict.get('parity')}**.",
        "",
        "## What was observed",
        "",
        "| series | bars | first bar (UTC) | last bar (UTC) | observation days | gaps | duplicates |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    days = payload.get("observation", {})
    for row in _quality_rows(payload):
        obs = days.get(row["series"], {})
        lines.append(
            f"| `{row['series']}` | {row['bars']} | {_iso(row['first_ts'])} | "
            f"{_iso(row['last_ts'])} | {obs.get('observation_days', 0)} | {row['gaps']} | "
            f"{row['duplicates']} |"
        )
    lines += [
        "",
        f"Total independent observation days (densest 1h series): "
        f"**{health.get('observation_days', 0)}** of a declared floor of {MIN_OBSERVATION_DAYS}.",
        "",
        "## Ingest ledger",
        "",
        f"Observation pass: **{health.get('ingest_runs', 0)}** series attempted; "
        f"outcomes: "
        + ", ".join(f"`{k}` {v}" for k, v in sorted(health.get("ingest_outcomes", {}).items()))
        + ".",
        "",
    ]
    ledger_rows = _ledger_rows(payload)
    if ledger_rows is not None:
        lines += [
            f"Ledger rows on file: **{ledger_rows['total']}** "
            f"({ledger_rows['observation']} from the observation pass, "
            f"{ledger_rows['restart']} from the restart pass at the same instant).",
            "",
        ]
    latency_rows = _series_latency(payload)
    fresh_rows = [row for row in latency_rows if row.get("fresh_samples")]
    if fresh_rows:
        lines += [
            "## Ingestion latency of the bars this run pulled (bar close → store)",
            "",
            "| series | bars pulled | min s | median s | max s |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for row in fresh_rows:
            lines.append(
                f"| `{row['series']}` | {row.get('fresh_bars', 0)} | "
                f"{_num(row.get('fresh_min_seconds'), 0)} | "
                f"{_num(row.get('fresh_median_seconds'), 0)} | "
                f"{_num(row.get('fresh_max_seconds'), 0)} |"
            )
        lines += [
            "",
            "These are the bars stamped with this run's fetch instant — the lag a scheduled "
            "reader meets, measured from each bar's close to the moment it reached the store.",
            "",
        ]
    if latency_rows:
        lines += [
            "## Window latency over every stored bar (backfill included)",
            "",
            "| series | samples | fetches | min s | median s | max s |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in latency_rows:
            lines.append(
                f"| `{row['series']}` | {row.get('samples', 0)} | {row.get('fetch_instants', 0)} | "
                f"{_num(row.get('min_seconds'), 0)} | {_num(row.get('median_seconds'), 0)} | "
                f"{_num(row.get('max_seconds'), 0)} |"
            )
        lines += [
            "",
            "The first run fetched the whole window in one pass, so this table is the "
            "**backfill** distance (each bar's close to that run's instant), not a property "
            "of the feed. The table above is the one that answers \"how fresh is the store\".",
            "",
        ]

    restart = payload.get("restart_proof", {})
    if restart:
        lines += [
            "## Restart and duplicate proof",
            "",
            f"- A second ingest at the same instant produced "
            f"`{restart.get('second_run_outcome')}` for every series and appended "
            f"**{restart.get('second_run_appended', 0)}** bar(s).",
            f"- Store digests identical before and after the second run: "
            f"**{'yes' if restart.get('digests_unchanged') else 'NO'}**.",
            f"- Duplicate timestamps anywhere in the store: "
            f"**{restart.get('duplicate_timestamps', 0)}**.",
            f"- Duplicate (asset, instant, reason) refusals in the primary arm: "
            f"**{restart.get('duplicate_refusals', 0)}**.",
            "",
        ]
    lines += [
        "## Frozen rulesets, read forward",
        "",
        "| arm | timeframe | scenario | window bars | signals | hypothetical fills | net USDT | max DD % | exposure % |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in sorted(payload.get("shadow", {}).get("arm_summaries", {})):
        summary = payload["shadow"]["arm_summaries"][arm]
        if summary.get("status") == "no_forward_bars":
            lines.append(
                f"| `{arm}` | {summary.get('timeframe', '?')} | — | 0 | 0 | 0 | — | — | — |"
            )
            continue
        metrics = summary.get("metrics", {})
        lines.append(
            f"| `{arm}` | {summary.get('timeframe')} | {summary.get('scenario')} | "
            f"{summary.get('window_bars', 0)} | {summary.get('signal_count', 0)} | "
            f"{metrics.get('trades', 0)} | {_num(metrics.get('net_usdt'))} | "
            f"{_num(metrics.get('max_drawdown_pct'))} | "
            f"{_num(metrics.get('exposure_pct_of_time'))} |"
        )
    lines += [
        "",
        "Every fill in that table is hypothetical (no order was sent, no capital moved). "
        "The metrics are a reading of what the frozen rules printed on the new bars, not a "
        "claim about the future and not an admission criterion.",
        "",
        "## Refusal funnel (primary arm)",
        "",
    ]
    arms_summary = payload.get("shadow", {}).get("arm_summaries", {})
    primary_key = str(payload.get("shadow", {}).get("primary_arm"))
    primary = arms_summary.get(primary_key, {})
    mix = primary.get("refusal_mix") or {}
    if mix:
        lines += ["| refusal | count |", "| --- | ---: |"]
        for reason, count in sorted(mix.items()):
            lines.append(f"| `{reason}` | {count} |")
        lines.append("")
    else:
        lines += ["No refusal was recorded by the primary arm on the forward window.", ""]
    lines += [
        "## Risk parity with the runtime engine",
        "",
        f"Verdict: **{payload.get('parity', {}).get('verdict')}** over "
        f"{sum(int(v) for v in payload.get('parity', {}).get('counts', {}).values())} "
        "classified comparison(s) "
        + ", ".join(
            f"`{k}` {v}" for k, v in sorted(payload.get("parity", {}).get("counts", {}).items())
        )
        + ".",
        "",
    ]
    if payload.get("parity", {}).get("defects"):
        lines += ["**Defects**", ""]
        for defect in payload["parity"]["defects"][:20]:
            lines.append(f"- `{defect['case_id']}`: {defect['detail']}")
        lines.append("")
    lines += [
        "## Limitations",
        "",
        "- The forward window is short by construction. Nothing here is a profitability claim.",
        "- The intraday arms read BTC's 1h series as context, exactly as the frozen campaign "
        "did, extended with the forward 1h bars so the context covers the window.",
        "- The shadow runs the arm's declared execution (market, or resting limit for the "
        "`_limit` arm). It never sends an order and it never contacts a private endpoint.",
        "- Risk parity compares two engines on identical inputs; it says nothing about which "
        "limits are *right*, only about whether the two implementations agree.",
        "",
    ]
    return "\n".join(lines)


def _empty_day() -> dict[str, Any]:
    return {
        "bars": 0,
        "appended": 0,
        "signals": 0,
        "trades": 0,
        "refusals": 0,
        "net_usdt": 0.0,
        "refusal_mix": {},
        "by_series": {},
    }


def _daily_rollup(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Per-UTC-date rows for every date the store covers, from the arms' own ledgers."""
    days: dict[str, dict[str, Any]] = {}
    arm_days: dict[str, dict[str, Any]] = {}
    for key, obs in (payload.get("observation") or {}).items():
        for day, count in (obs.get("per_day_bars") or {}).items():
            row = days.setdefault(day, _empty_day())
            row["bars"] += int(count)
            row["by_series"][key] = int(count)
        for day, count in (obs.get("per_day_appended") or {}).items():
            days.setdefault(day, _empty_day())["appended"] += int(count)
    for arm, summary in payload.get("shadow", {}).get("arm_summaries", {}).items():
        if summary.get("status") != "observed":
            continue
        slot: dict[str, dict[str, float]] = {}
        arm_days[arm] = slot
        for row in summary.get("signals_detail", []):
            day = _day(int(row["decision_ts"]))
            days.setdefault(day, _empty_day())["signals"] += 1
            entry = slot.setdefault(day, {"signals": 0, "trades": 0, "refusals": 0, "net_usdt": 0.0})
            entry["signals"] += 1
        for row in summary.get("trades_detail", []):
            day = _day(int(row["decision_ts"]))
            total = days.setdefault(day, _empty_day())
            total["trades"] += 1
            total["net_usdt"] = round(total["net_usdt"] + float(row["net"]), 6)
            entry = slot.setdefault(day, {"signals": 0, "trades": 0, "refusals": 0, "net_usdt": 0.0})
            entry["trades"] += 1
            entry["net_usdt"] = round(entry["net_usdt"] + float(row["net"]), 6)
        for row in summary.get("refusals_detail", []):
            day = _day(int(row["decision_ts"]))
            total = days.setdefault(day, _empty_day())
            total["refusals"] += 1
            reason = f"{row.get('source', 'candidate')}:{row.get('reason')}"
            total["refusal_mix"][reason] = total["refusal_mix"].get(reason, 0) + 1
            entry = slot.setdefault(day, {"signals": 0, "trades": 0, "refusals": 0, "net_usdt": 0.0})
            entry["refusals"] += 1
    for row in payload.get("ingest", {}).get("ledger", []):
        if row.get("outcome") != "ingested":
            continue
        day = _day(int(row["run_at_ms"]))
        if day not in days:
            days[day] = _empty_day()
        days[day]["run_appended"] = days[day].get("run_appended", 0) + int(row.get("appended") or 0)

    # The primary arm's equity at the close of each date, and the drawdown it sat at: the
    # hypothetical book, stated per day so a reader does not have to reconstruct it.
    curve = payload.get("primary_equity_curve") or []
    start_equity = payload.get("shadow", {}).get("start_equity") or 10_000.0
    peak = float(start_equity)
    last_by_day: dict[str, float] = {}
    running_peak: dict[str, float] = {}
    for ts, equity in curve:
        peak = max(peak, float(equity))
        day = _day(int(ts))
        last_by_day[day] = float(equity)
        running_peak[day] = peak
    for day, equity in last_by_day.items():
        row = days.setdefault(day, _empty_day())
        row["equity"] = round(equity, 6)
        row["cumulative_net_usdt"] = round(equity - float(start_equity), 6)
        peak_today = running_peak.get(day) or equity
        row["drawdown_pct"] = round((peak_today - equity) / peak_today * 100.0, 6) if peak_today else None
    return days, arm_days


def _arms_for_day(payload: dict[str, Any], day: str) -> dict[str, Any]:
    """The per-arm rows for one date. ``daily_arms`` is published day-first."""
    return (payload.get("daily_arms") or {}).get(day) or {}


def write_observability(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    """Write the daily report, the per-date rollup and the cumulative report."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    daily, arm_days = _daily_rollup(payload)
    dates = sorted(daily)
    payload["daily"] = daily
    # Published day-first: the daily report asks "what did each arm do on THIS date", and a
    # rollup keyed by arm first cannot answer it (the report would look empty).
    day_first: dict[str, dict[str, Any]] = {}
    for arm, slot in arm_days.items():
        for day, row in slot.items():
            day_first.setdefault(day, {})[arm] = row
    payload["daily_arms"] = day_first
    newest = dates[-1] if dates else None
    if newest is not None:
        path = outdir / f"DAILY_{newest}.md"
        path.write_text(daily_markdown(payload, newest), encoding="utf-8")
        written["daily"] = path
    rollup = outdir / "DAILY_REPORTS.json"
    rollup.write_text(
        json.dumps(
            {"dates": dates, "days": daily, "arms": payload["daily_arms"]},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    written["daily_rollup"] = rollup
    cumulative = outdir / "CUMULATIVE.md"
    cumulative.write_text(cumulative_markdown(payload), encoding="utf-8")
    written["cumulative"] = cumulative
    payload["verdict"] = observation_verdict(payload)
    summary = outdir / "CUMULATIVE.json"
    summary.write_text(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "health": payload.get("health", {}),
                "observation": payload.get("observation", {}),
                "restart_proof": payload.get("restart_proof", {}),
                "parity": {
                    "verdict": payload.get("parity", {}).get("verdict"),
                    "counts": payload.get("parity", {}).get("counts", {}),
                    "defects": len(payload.get("parity", {}).get("defects", [])),
                },
                "dates": dates,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    written["summary"] = summary
    return written
