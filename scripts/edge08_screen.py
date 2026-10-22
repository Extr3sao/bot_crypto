#!/usr/bin/env python
"""WP-EDGE-08B / 08C — screen one track of books on the known universe.

The known universe (BTC/ETH/SOL) is the **screening ground**: it has been read so many times that
nothing measured on it can be evidence, and it is used here for exactly one decision — whether a
book is worth reading on the cross-section at all.

For each book of the track this script:

1. runs it on ``DEV``, ``VAL`` and ``OOS`` of the known universe at its own clock, with the frozen
   cost plane, risk policy and simulator;
2. applies the registered **gross screen C0** to ``DEV``: gross expectancy > 0. A book that loses
   before any fee cannot be repaired by a fee, so it is *not* read on the cross-section — its
   holdout rows stay absent rather than zero;
3. publishes the **frequency** it reaches (trades/day across the universe and per asset, mean
   holding time) next to the money, because the mission's frequency question and the money question
   are answered by different numbers and this package refuses to blur them.

Usage::

    python scripts/edge08_screen.py --track QUALITY
    python scripts/edge08_screen.py --track ACTIVE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.artifacts import stamp, write_json, write_trades_csv  # noqa: E402
from trading_bot.research.edge08.books import (  # noqa: E402
    DECLARED_PARAMS,
    PROPOSED_ARMS,
    build_proposed,
    params_hash,
)
from trading_bot.research.edge08.registration import (  # noqa: E402
    FREQUENCY_TARGETS,
    SCHEMA_VERSION,
    WINDOWS,
    WP,
)
from trading_bot.research.edge08.screens import (  # noqa: E402
    DEFECTS_FIXED,
    screen_arm,
    screen_row,
    screen_verdict,
)
from trading_bot.research.edge08.universe import known_corpus  # noqa: E402

TRACK_DIRS = {"QUALITY": WP / "quality", "ACTIVE": WP / "active"}
BARRIER = (
    REPO_ROOT
    / "reports"
    / "edge-recovery"
    / "WP-EDGE-07"
    / "active-research"
    / "COST_BARRIER_ACTIVE.json"
)


def barrier_reference() -> dict[str, Any]:
    """The cost barrier WP-EDGE-07 measured, cited by digest rather than remembered."""
    if not BARRIER.is_file():
        return {"available": False}
    payload = json.loads(BARRIER.read_text(encoding="utf-8"))
    return {
        "available": True,
        "path": str(BARRIER.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(BARRIER.read_bytes()).hexdigest(),
        "round_trip_bps": payload.get("round_trip_bps")
        or payload.get("cost", {}).get("round_trip_bps"),
        "note": (
            "the measured barrier this track is judged against: the fraction of the open-to-open "
            "move a perfect call must capture merely to break even, per holding horizon"
        ),
    }


def build(*, track: str) -> dict[str, Any]:
    arms = {arm: scope for arm, scope in PROPOSED_ARMS.items() if scope["track"] == track}
    if not arms:
        raise SystemExit(f"no registered book for track {track!r}")
    timeframes = sorted({scope["timeframe"] for scope in arms.values()})
    corpora = {timeframe: known_corpus(timeframe) for timeframe in timeframes}
    # One book object per arm, reused across windows: the feature state is cached by the identity
    # of the bar list, so re-running a window costs the simulation and not the indicators.
    books = build_proposed(corpora[timeframes[0]].bars_by_asset)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08B" if track == "QUALITY" else "WP-EDGE-08C",
        "track": track,
        "as_of_utc": stamp(),
        "ground": "the known universe (BTC/ETH/SOL) — the screening ground, never the evidence",
        "corpora": {
            timeframe: {
                asset: {
                    "bars": len(bars),
                    "first_ts": bars[0].ts if bars else None,
                    "last_ts": bars[-1].ts if bars else None,
                }
                for asset, bars in sorted(corpus.bars_by_asset.items())
            }
            for timeframe, corpus in corpora.items()
        },
        "windows": {name: dict(window) for name, window in WINDOWS.items()},
        "frequency_target_per_day": FREQUENCY_TARGETS[track],
        "barrier_reference": barrier_reference(),
        "arms": {},
        "defects_fixed": DEFECTS_FIXED,
        "promotion": "NONE",
        "order_sent": False,
    }

    trades_rows: list[dict[str, Any]] = []
    for arm, scope in sorted(arms.items()):
        timeframe = scope["timeframe"]
        rows: dict[str, dict[str, Any]] = {}
        for window_name in ("DEV", "VAL", "OOS"):
            screen = screen_arm(
                arm_id=arm,
                book=books[arm],
                corpus=corpora[timeframe],
                window=WINDOWS[window_name],
                timeframe=timeframe,
                horizon_minutes=scope["horizon_minutes"],
                scenario="BASE",
            )
            rows[window_name] = screen_row(screen, track=track)
            for trade in screen["trades"]:
                trades_rows.append(
                    {
                        **trade,
                        "arm": arm,
                        "track": track,
                        "window": window_name,
                        "scenario": "BASE",
                    }
                )
        payload["arms"][arm] = {
            "track": track,
            "timeframe": timeframe,
            "horizon_minutes": scope["horizon_minutes"],
            "answers": scope["answers"],
            "params": dict(DECLARED_PARAMS[arm]),
            "params_hash": params_hash(dict(DECLARED_PARAMS[arm])),
            "rows": rows,
            "screen": screen_verdict(rows),
        }

    payload["forward_to_the_cross_section"] = sorted(
        arm for arm, entry in payload["arms"].items() if entry["screen"]["passed"]
    )
    payload["rejected_before_the_cross_section"] = sorted(
        arm for arm, entry in payload["arms"].items() if not entry["screen"]["passed"]
    )
    outdir = TRACK_DIRS[track]
    name = f"{track}_SCREEN"
    write_json(outdir / f"{name}.json", payload)
    write_trades_csv(outdir / f"{track}_TRADES.csv", trades_rows)
    (outdir / f"{name}.md").write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict[str, Any]) -> str:
    track = payload["track"]
    lines = [
        f"# WP-EDGE-08 — the {track} track, screened on the known universe",
        "",
        f"*Read at `{payload['as_of_utc']}` (`{payload['schema_version']}`). Ground: "
        f"{payload['ground']}.*",
        "",
        "## 1. The screen that decides whether the cross-section is read at all",
        "",
        "**C0** — gross expectancy > 0 on `DEV`. A setup that loses money before any fee cannot be "
        "repaired by a fee, so a book that fails C0 is not read on the cross-section: its holdout "
        "rows are absent, not zero.",
        "",
        "| Arm | DEV trades | DEV gross/trade (USDT) | DEV net (USDT) | C0 | Consequence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        screen = entry["screen"]
        lines.append(
            f"| `{arm}` | {screen['dev_trades']} | {screen['dev_gross_expectancy_usdt']} | "
            f"{screen['dev_net_usdt']} | {'PASS' if screen['passed'] else 'FAIL'} | "
            f"{screen['consequence']} |"
        )
    lines += [
        "",
        f"Forward to the cross-section: {payload['forward_to_the_cross_section'] or '**none**'}; "
        f"rejected before it: {payload['rejected_before_the_cross_section'] or 'none'}.",
        "",
        "## 2. Every window, money first and frequency beside it",
        "",
    ]
    for arm, entry in sorted(payload["arms"].items()):
        lines += [
            f"### `{arm}` — {entry['answers']}",
            "",
            f"Clock `{entry['timeframe']}`, horizon {entry['horizon_minutes']:.0f} min, params hash "
            f"`{entry['params_hash'][:16]}…`.",
            "",
            "| Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % |"
            " Sharpe | Cost bps/trade | Trades/day | Per asset/day | Hold (h) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for window, row in entry["rows"].items():
            lines.append(
                f"| {window} | {row['trades']} | {row['gross_usdt']} | {row['fees_usdt']} | "
                f"{row['price_costs_usdt']} | **{row['net_usdt']}** | {row['expectancy_usdt']} | "
                f"{row['profit_factor']} | {row['max_drawdown_pct']} | {row['sharpe_annualised']} | "
                f"{row['total_cost_bps_per_trade']} | {row['trades_per_day_universe']} | "
                f"{row['trades_per_day_per_asset']} | {row['mean_hold_hours']} |"
            )
        dev = entry["rows"]["DEV"]
        lines += [
            "",
            f"- Exits on DEV: {dev['exit_reason_mix']}; refusals by reason: {dev['funnel']}.",
            f"- Expectancy interval on DEV (90 %, block bootstrap): "
            f"{dev['expectancy_ci_90_usdt']}; positive time blocks: "
            f"{dev['positive_time_blocks']} of 3.",
            "",
        ]
    lines += [
        "## 3. The frequency question, answered with numbers",
        "",
        f"The {track} track's registered target is "
        f"**{payload['frequency_target_per_day']} trades a day across the universe**. "
        + (
            "Measured on `OOS`: "
            + ", ".join(
                f"`{arm}` {entry['rows']['OOS']['trades_per_day_universe']}"
                for arm, entry in sorted(payload["arms"].items())
            )
            + "."
            if payload["arms"]
            else ""
        ),
        "",
    ]
    barrier = payload["barrier_reference"]
    if barrier.get("available"):
        lines += [
            f"Context, cited rather than remembered: "
            f"`{barrier['path']}` (sha256 `{(barrier['sha256'] or '')[:16]}…`) measured the round "
            f"trip at {barrier['round_trip_bps']} bps and the capture fraction a perfect call needs "
            f"merely to break even, per holding horizon. {barrier['note']}.",
            "",
        ]
    lines += [
        "## 4. Defects found by running this screen, and fixed before the registration",
        "",
    ]
    for defect in payload.get("defects_fixed") or []:
        superseded = "".join(
            f"`{arm}` `{str(value)[:16]}…` "
            for arm, value in dict(defect.get("superseded_params_hashes") or {}).items()
        )
        lines += [
            f"### `{defect['id']}`",
            "",
            f"- **Symptom.** {defect['symptom']}",
            f"- **Cause.** {defect['cause']}",
            f"- **Fix.** {defect['fix']}",
            f"- **Superseded parameter hashes.** {superseded}",
            f"- **Found.** {defect['found']}.",
            f"- **What did not happen.** {defect['what_did_not_happen']}.",
            f"- **Evidence.** {defect['evidence']}.",
            "",
        ]
    lines += [
        "## 5. What this screen does not say",
        "",
        "- Passing C0 is **not** evidence of an edge: it is a gross test on a window every earlier "
        "work package has read, and its only job is to keep a hopeless book from spending the "
        "cross-section.",
        "- Nothing here promotes, sizes or executes: `promotion: NONE`, `order_sent: false`.",
        "- The frequency reading is reported for every book and is never a reason to force a trade: "
        "a book that cannot reach its track's target says so with a number.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--track", choices=("QUALITY", "ACTIVE"), required=True)
    options = parser.parse_args(argv)
    payload = build(track=options.track)
    print(
        f"{options.track}: forward to the cross-section {payload['forward_to_the_cross_section']}"
    )
    for arm, entry in sorted(payload["arms"].items()):
        screen = entry["screen"]
        print(
            f"  {arm:<36} C0={'PASS' if screen['passed'] else 'FAIL'}  "
            f"dev net={screen['dev_net_usdt']}  gross/trade={screen['dev_gross_expectancy_usdt']}  "
            f"trades/day(OOS)={entry['rows']['OOS']['trades_per_day_universe']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
