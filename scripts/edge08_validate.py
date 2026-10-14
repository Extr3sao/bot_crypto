#!/usr/bin/env python
"""WP-EDGE-08E — the registered verdicts, on the unread cross-section.

Reads the screening artefacts first (they say which books are allowed to be read here at all),
then measures every arm that is allowed to be measured on the **cross-section** — six symbols whose
history no committed artefact has ever read — and computes the verdict from the criteria registered
in ``PREREGISTRATION.json`` and nothing else.

Two rules, both inherited and both kept:

* a book that failed the gross screen (C0) on the known universe is **not** read here: its holdout
  rows are absent, not zero, because measuring a setup that loses before any fee would only spend
  the cross-section;
* the three CURRENT arms are read for the comparison the mission asks for, on the same corpus and
  windows, with BASE only — they are already-closed registrations, they change no verdict, and
  their cost sensitivity is published in the economics matrix rather than recomputed here.

Usage::

    python scripts/edge08_validate.py            # runs the read arms, writes the verdicts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.artifacts import stamp, write_json, write_trades_csv  # noqa: E402
from trading_bot.research.edge08.books import (  # noqa: E402
    CURRENT_ARMS,
    DECLARED_PARAMS,
    PROPOSED_ARMS,
    build_current,
    build_proposed,
    params_hash,
)
from trading_bot.research.edge08.economics import (  # noqa: E402
    compare_arms,
    gate_status,
    run_arm_cells,
)
from trading_bot.research.edge08.registration import (  # noqa: E402
    COVERAGE_FLOOR_BARS,
    HOLDOUT_SYMBOLS,
    MULTIPLICITY,
    SCHEMA_VERSION,
    WINDOWS,
    WP,
)
from trading_bot.research.edge08.runner import COST_SCENARIOS  # noqa: E402
from trading_bot.research.edge08.universe import (  # noqa: E402
    coverage,
    cross_section_corpus,
    holdout_manifest,
)
from trading_bot.research.edge08.validation import (  # noqa: E402
    coverage_reading,
    verdict_payload,
)

OUTDIR = WP / "validation"
SCREEN_PATHS = {
    "QUALITY": WP / "quality" / "QUALITY_SCREEN.json",
    "ACTIVE": WP / "active" / "ACTIVE_SCREEN.json",
}


def screen_outcomes() -> dict[str, dict[str, Any]]:
    """C0's own readings, taken from the committed artefacts rather than remembered."""
    outcomes: dict[str, dict[str, Any]] = {}
    for _track, path in SCREEN_PATHS.items():
        if not path.is_file():
            raise SystemExit(f"missing {path.relative_to(REPO_ROOT)}: run scripts/edge08_screen.py first")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for arm, entry in payload["arms"].items():
            outcomes[arm] = dict(entry["screen"])
    return outcomes


def build() -> dict[str, Any]:
    outcomes = screen_outcomes()
    read_arms = [arm for arm, screen in outcomes.items() if screen.get("passed")]
    skipped = [arm for arm, screen in outcomes.items() if not screen.get("passed")]

    scopes: dict[str, dict[str, Any]] = {arm: PROPOSED_ARMS[arm] for arm in read_arms}
    scopes.update({arm: CURRENT_ARMS[arm] for arm in CURRENT_ARMS})
    timeframes = sorted({scope["timeframe"] for scope in scopes.values()})
    corpora = {timeframe: cross_section_corpus(timeframe) for timeframe in timeframes}
    books = {
        **build_proposed(corpora[timeframes[0]].bars_by_asset),
        **build_current(corpora[timeframes[0]].bars_by_asset),
    }
    coverage_readings = {
        timeframe: coverage_reading(
            bars_per_asset=coverage(corpora[timeframe], WINDOWS["OOS"]), timeframe=timeframe
        )
        for timeframe in timeframes
    }
    manifest = holdout_manifest()

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08E",
        "as_of_utc": stamp(),
        "ground": (
            "the cross-section: "
            + ", ".join(HOLDOUT_SYMBOLS)
            + " — never the input of a committed measurement in this repository before this reading"
        ),
        "corpus_digest": manifest.get("corpus_digest"),
        "corpus_directory": "data/edge08/universe-1h",
        "windows": {name: dict(window) for name, window in WINDOWS.items()},
        "coverage": coverage_readings,
        "coverage_floor_bars_per_asset": COVERAGE_FLOOR_BARS,
        "read_on_the_cross_section": read_arms,
        "not_read_on_the_cross_section": skipped,
        "multiplicity": dict(MULTIPLICITY),
        "arms": {},
        "promotion": "NONE",
        "order_sent": False,
    }

    trade_rows: list[dict[str, Any]] = []
    matrices: dict[str, dict[str, Any]] = {}
    for arm, scope in sorted(scopes.items()):
        timeframe = scope["timeframe"]
        track = str(scope.get("track") or "CURRENT")
        is_current = arm in CURRENT_ARMS
        scenarios = ("BASE",) if is_current else COST_SCENARIOS
        cells = run_arm_cells(
            arm_id=arm,
            track=track,
            book=books[arm],
            corpus=corpora[timeframe],
            timeframe=timeframe,
            horizon_minutes=float(scope["horizon_minutes"]),
            windows=WINDOWS,
            scenarios=scenarios,
        )
        matrices[arm] = {"cells": cells}
        gate = gate_status(cells=cells, window_label="cross-section")
        entry: dict[str, Any] = {
            "track": track,
            "timeframe": timeframe,
            "horizon_minutes": scope["horizon_minutes"],
            "answers": scope.get("answers") or scope.get("already"),
            "params": dict(DECLARED_PARAMS.get(arm) or {}),
            "params_hash": params_hash(dict(DECLARED_PARAMS[arm])) if arm in DECLARED_PARAMS else None,
            "scenarios": list(scenarios),
            "cells": cells,
            "gate_status": gate,
            "narrative_only": is_current,
        }
        if is_current:
            entry["verdict"] = "NOT_APPLICABLE"
            entry["why"] = (
                "a CURRENT arm: already registered and measured by an earlier work package, read "
                "here as the baseline of the comparison; it answers to no criterion of this package"
            )
        else:
            verdict = verdict_payload(
                arm_id=arm,
                track=track,
                screen_verdict=outcomes[arm],
                cells=cells,
                coverage=coverage_readings[timeframe],
                gate=gate,
            )
            entry.update(verdict)
        payload["arms"][arm] = entry
        for window, scenario_cells in cells.items():
            for trade in (scenario_cells.get("BASE") or {}).get("trade_rows", []):
                trade_rows.append(
                    {**trade, "arm": arm, "track": track, "window": window, "scenario": "BASE"}
                )
        print(
            f"  {arm:<36} OOS net {cells['OOS']['BASE']['net_usdt']}  "
            f"trades {cells['OOS']['BASE']['trades']}  verdict {entry.get('verdict')}"
        )

    # Every proposed arm has a registered outcome, including the ones the screen stopped.
    for arm in skipped:
        track = PROPOSED_ARMS[arm]["track"]
        payload["arms"][arm] = verdict_payload(
            arm_id=arm,
            track=track,
            screen_verdict=outcomes[arm],
            cells=None,
            coverage=None,
            gate=None,
        )
        print(f"  {arm:<36} verdict REJECT_NO_GROSS_EDGE (not read: the screen stopped it)")

    payload["comparison"] = compare_arms(
        matrices=matrices,
        proposed=tuple(sorted(read_arms)),
        current=tuple(sorted(CURRENT_ARMS)),
    )
    stripped = 0
    for entry in payload["arms"].values():
        for scenarios in (entry.get("cells") or {}).values():
            for cell in scenarios.values():
                stripped += len(cell.pop("trade_rows", []) or [])
    payload["trade_rows_written_to_csv"] = stripped

    write_json(OUTDIR / "VALIDATION.json", payload)
    write_trades_csv(OUTDIR / "HOLDOUT_TRADES.csv", trade_rows)
    (OUTDIR / "VALIDATION.md").write_text(render(payload), encoding="utf-8")
    write_json(OUTDIR / "GATE_STATUS.json", gate_status_payload(payload))
    (OUTDIR / "GATE_STATUS.md").write_text(render_gate_status(payload), encoding="utf-8")
    return payload


def gate_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The gate table: every arm, its registered verdict, and the frozen gate's own reading."""
    rows = []
    for arm, entry in sorted(payload["arms"].items()):
        gate = entry.get("gate_status") or {}
        rows.append(
            {
                "arm": arm,
                "track": entry["track"],
                "registered_verdict": entry.get("verdict"),
                "failed": entry.get("failed"),
                "frozen_gate_verdict": gate.get("verdict"),
                "frozen_gate_power": gate.get("power"),
                "cross_section_load": (
                    "read" if entry.get("read_on_the_cross_section") else "not read"
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": payload["as_of_utc"],
        "rows": rows,
        "note": (
            "GATE_STATUS is a status table, not a permission: `promotion` is NONE and `order_sent` "
            "is false for every arm in this package, and an ADMIT_PAPER verdict would mean a paper "
            "lane and nothing else"
        ),
        "promotion": "NONE",
        "order_sent": False,
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08E — the verdicts, on the cross-section nobody had read",
        "",
        f"*Read at `{payload['as_of_utc']}` (`{payload['schema_version']}`). Ground: "
        f"{payload['ground']}.*",
        "",
        f"Corpus digest `{(payload['corpus_digest'] or '')[:16]}…`, from "
        f"`{payload['corpus_directory']}`.",
        "",
        "## 1. Coverage of the decisive window",
        "",
        "| Clock | Floor bars/asset | Bars/asset | Enough |",
        "| --- | --- | --- | --- |",
    ]
    for timeframe, reading in payload["coverage"].items():
        lines.append(
            f"| {timeframe} | {reading['floor_bars_per_asset']} | {reading['bars_per_asset']} | "
            f"{reading['enough']} ({'none below floor' if reading['enough'] else reading['assets_below_floor']}) |"
        )
    lines += [
        "",
        "## 2. The registered verdicts",
        "",
        "| Arm | Track | Verdict | Failed criteria | Trades (OOS) | Net (OOS) | Net @2x fees |"
        " Trades/day | Frozen gate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        base = ((entry.get("cells") or {}).get("OOS") or {}).get("BASE") or {}
        stress = ((entry.get("cells") or {}).get("OOS") or {}).get("2X_FEES") or {}
        gate = (entry.get("gate_status") or {}).get("verdict")
        lines.append(
            f"| `{arm}` | {entry['track']} | **{entry.get('verdict')}** | "
            f"{', '.join(entry.get('failed') or []) or '—'} | {base.get('trades')} | "
            f"{base.get('net_usdt')} | {stress.get('net_usdt')} | "
            f"{(base.get('frequency') or {}).get('trades_per_day_universe')} | {gate} |"
        )
    lines += [
        "",
        f"Read on the cross-section: {payload['read_on_the_cross_section'] or '**none**'}. "
        f"Not read (the screen stopped them before the cross-section): "
        f"{payload['not_read_on_the_cross_section'] or 'none'}.",
        "",
        "## 3. Every criterion, per arm that was read",
        "",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        if not entry.get("read_on_the_cross_section"):
            lines += [
                f"### `{arm}` — {entry.get('verdict')}",
                "",
                f"{entry.get('why')}",
                "",
            ]
            continue
        lines += [
            f"### `{arm}` — **{entry.get('verdict')}**",
            "",
            f"{entry.get('why')}",
            "",
            "| # | Criterion | Value | Passed |",
            "| --- | --- | --- | --- |",
        ]
        for check in entry.get("checks") or []:
            lines.append(
                f"| {check['id']} | {check['statement']} | {check['value']} | {check['passed']} |"
            )
        decisive = entry.get("decisive_window") or {}
        lines += [
            "",
            f"Decisive window readings: {decisive.get('trades')} trades, net "
            f"{decisive.get('net_usdt')} USDT, expectancy {decisive.get('expectancy_usdt')}, PF "
            f"{decisive.get('profit_factor')}, DD {decisive.get('max_drawdown_pct')} %, "
            f"expectancy interval {decisive.get('expectancy_ci_90_usdt')}.",
            "",
            f"Per market context: {decisive.get('by_market_context_detail')}; exits "
            f"{decisive.get('exit_reason_mix')}; serial dependence "
            f"{decisive.get('serial_dependence')}.",
            "",
        ]
    lines += ["## 4. CURRENT vs PROPOSED on the cross-section", ""]
    for window, block in (payload.get("comparison") or {}).items():
        if window == "note":
            continue
        lines += [
            f"### {window}",
            "",
            "| Group | Arm | Trades | Net | Expectancy | PF | DD % | Trades/day |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in block["rows"]:
            lines.append(
                f"| {row['group']} | `{row['arm']}` | {row['trades']} | {row['net_usdt']} | "
                f"{row['expectancy_usdt']} | {row['profit_factor']} | {row['max_drawdown_pct']} | "
                f"{row['trades_per_day_universe']} |"
            )
        lines.append("")
    lines += [
        (payload.get("comparison") or {}).get("note", "") + ".",
        "",
        "## 5. What these verdicts are not",
        "",
        "- They are not a permission to trade: `promotion: NONE`, `order_sent: false`. An "
        "`ADMIT_PAPER` verdict means a paper lane and nothing else, and the risk-manager's and the "
        "release gate's own conditions still apply to it.",
        "- They are not tuned: the parameters are the registered bytes (hashes in "
        "`PREREGISTRATION.json`), and a book that failed is reported with its numbers rather than "
        "re-parameterised and re-run on this window.",
        "- Six symbols are six symbols: a transfer measured on them is evidence about them.",
        "",
    ]
    return "\n".join(lines)


def render_gate_status(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08 — gate status",
        "",
        f"*As of `{payload['as_of_utc']}`. `promotion: NONE`, `order_sent: false`.*",
        "",
        "| Arm | Track | Registered verdict | Failed | Frozen gate | Power | Cross-section load |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(payload["arms"].items()):
        arm, entry = row
        gate = entry.get("gate_status") or {}
        lines.append(
            f"| `{arm}` | {entry['track']} | **{entry.get('verdict')}** | "
            f"{', '.join(entry.get('failed') or []) or '—'} | {gate.get('verdict') or '—'} | "
            f"{gate.get('power') or '—'} | "
            f"{'read' if entry.get('read_on_the_cross_section') else 'not read'} |"
        )
    lines += [
        "",
        "The frozen admission gate is the yardstick earlier work packages were judged by, reported "
        "here with `OOS` := the cross-section's decisive window for comparability. The registered "
        "verdict is the one ``PREREGISTRATION.json`` defines, and it is the one that counts.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    payload = build()
    verdicts: dict[str, int] = {}
    for entry in payload["arms"].values():
        verdict = str(entry.get("verdict"))
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    print(f"verdicts: {verdicts}")
    print(f"wrote {OUTDIR.relative_to(REPO_ROOT)} (VALIDATION.json/md, GATE_STATUS.json/md, HOLDOUT_TRADES.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
