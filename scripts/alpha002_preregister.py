"""Write the committed ALPHA-002 preregistration and the ALPHA-001 closure record.

The preregistration is written to ``docs/research/alpha002/`` so that Git timestamps
it: a frozen registry that only exists in memory is not evidence.  The closure
record states what ALPHA-001 concluded, why it is not re-tuned, and what would be
needed to reopen it.

Reads the live capture manifest, so the preregistration reports the real size of
the dataset it will be tested against rather than an intention.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha002 import (  # noqa: E402
    COST_BPS_V3,
    HYPOTHESES,
    PREREGISTRATION,
    preregistration_hash,
)

OUT_DIR = REPO / "docs" / "research" / "alpha002"
MANIFEST_PATH = REPO / "data" / "raw" / "alpha002" / "MANIFEST.json"

CLOSURE: dict[str, Any] = {
    "campaign": "ALPHA-001",
    "title": "Economic Alpha Discovery Campaign — OHLCV / technical family",
    "decision": "CLOSED",
    "verdict": "ACCEPT NO ALPHA",
    "do_not_retune": True,
    "result": {
        "families_tested": 6,
        "hypotheses_tested": 12,
        "admitted": 0,
        "gross_positive": 6,
        "net_positive_at_certified_cost": 0,
        "bh_fdr_survivors_q10": 0,
        "holm_survivors_alpha10": 0,
        "p_null_best_ge_observed": 0.765,
        "best_hypothesis": "A1-H09",
        "best_gross_bps": 18.575939,
        "frozen_hurdle_bps": 55.380903,
        "holdout_read": False,
        "false_success": 0,
        "verifier": "PASS 56/56",
    },
    "cause": {
        "binding_constraint": "EFFECT_SIZE_NOT_COST",
        "best_gross_bps": 18.575939,
        "non_cost_bar_bps": 25.642692,
        "admission_break_even_cost_bps": -5.653402,
        "note": (
            "even at zero cost the frozen bar needs 25.64 bps of gross and the best cell reached "
            "18.58; the certified cost would have to become a rebate of 5.65 bps per round trip "
            "for the frozen rule to admit anything"
        ),
    },
    "what_it_tells_the_system": (
        "under those twelve hypotheses and that methodology, the price signals tested do not "
        "contain enough edge on their own. This is information, not a failure: it removes a "
        "family from the search space without burning capital."
    ),
    "evidence": {
        "cost_frontier": "reports/alpha001/COST_FRONTIER.{md,json}",
        "final_report": "reports/alpha001/FINAL_REPORT.{md,json}",
        "verification": "reports/alpha001/ALPHA001_VERIFICATION.{md,json}",
        "gates": "reports/alpha001/GATES.json",
        "commits": ["040f6fc", "cb26974"],
    },
    "reopen_requires": [
        "a genuinely new information source, not a new parameter on the same series",
        "a preregistered hypothesis whose expected gross exceeds the frozen hurdle ex ante",
        "no re-use of the ALPHA-001 holdout for an ALPHA-001 question",
    ],
    "prohibited": [
        "retuning thresholds, horizons or the cost model on this family",
        "promoting an UNDERPOWERED cell to a candidate",
        "presenting a raw p-value as corrected evidence",
    ],
}


def capture_status() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"available": False, "note": "no capture manifest yet"}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    periodic = {
        key: value for key, value in manifest["records"].items() if not key.startswith("funding_rate")
    }
    return {
        "available": True,
        "captured_at_utc": manifest["generated_at_utc"],
        "series": manifest["totals"]["series_captured"],
        "rows": manifest["totals"]["rows"],
        "series_with_gaps": manifest["totals"]["series_with_gaps"],
        "retention_policy": manifest["retention_policy"],
        "derivative_series_span_days": min(
            (value["span_days"] for value in periodic.values()), default=0.0
        ),
        "funding_history_days": max(
            (
                value["span_days"]
                for key, value in manifest["records"].items()
                if key.startswith("funding_rate")
            ),
            default=0.0,
        ),
        "manifest": "data/raw/alpha002/MANIFEST.json",
        "capture_log": "data/raw/alpha002/CAPTURE_LOG.jsonl",
        "scheduler": {
            "task": "TradingAgentic-ALPHA002-Capture",
            "cadence": "every 15 minutes",
            "why": (
                "the venue retains these series for 30 days only, so a missed day is a day of "
                "information destroyed and no later run can recover it"
            ),
        },
    }


def build_preregistration() -> dict[str, Any]:
    return {
        "registry": PREREGISTRATION,
        "preregistration_hash": preregistration_hash(),
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "cost_bps": COST_BPS_V3,
        "hypothesis_ids": [item["hypothesis_id"] for item in HYPOTHESES],
        "data": capture_status(),
        "status": "FROZEN_AWAITING_DATA",
        "discovery_status": (
            "not started: the derivatives series only began existing on 2026-10-07, and the "
            "preregistered split is defined below before any result is observed"
        ),
        "frozen_split": {
            "rule": (
                "a calendar split of the captured span, identical for every series, with the "
                "final fifth reserved and never read by discovery"
            ),
            "discovery_fraction": 0.60,
            "validation_fraction": 0.20,
            "holdout_fraction": 0.20,
            "blocked_until": (
                "at least 30 days of continuous capture have accrued, so that the discovery and "
                "validation slices are both covered by real observations rather than by a "
                "retention edge"
            ),
        },
    }


def render_preregistration(payload: dict[str, Any]) -> str:
    registry = payload["registry"]
    lines = [
        "# ALPHA-002 — PREREGISTRATION (frozen before any result)",
        "",
        f"`PREREGISTRATION_HASH = {payload['preregistration_hash']}`",
        "",
        f"- campaign: **{registry['campaign']} — {registry['title']}**",
        f"- question: {registry['question']}",
        f"- status: **{payload['status']}**",
        f"- universe: {', '.join(registry['universe'])}",
        f"- entry timeframes: {', '.join(registry['entry_timeframes'])} · regime: "
        f"{registry['regime_timeframe']} · forward horizon: {registry['forward_bars']} bar",
        f"- cost model: {registry['cost_model']['name']} at {payload['cost_bps']} bps, "
        f"inherited and not retuned",
        "",
        f"- parent campaign: ALPHA-001, verdict **{registry['parent']['verdict']}**, binding "
        f"constraint **{registry['parent']['binding_constraint']}**",
        f"- {registry['parent']['not_reopened']}",
        "",
        "## Hypotheses",
        "",
    ]
    for item in registry["hypotheses"]:
        lines.extend(
            [
                f"### {item['hypothesis_id']} — {item['name']} ({item['family_id']})",
                "",
                f"- mechanism: {item['mechanism']}",
                f"- direction rule: `{item['direction_rule']}`",
                f"- expected regime: {item['expected_regime']}",
                f"- invalidation: {item['invalidation']}",
                f"- timeframes: {', '.join(item['timeframes'])} (regime {item['regime_timeframe']})",
                "",
            ]
        )
    lines.extend(["## Declared non-traded arms", ""])
    for arm in registry["non_traded_arms"]:
        lines.append(f"- **{arm['arm_id']}** ({arm['hypothesis_id']}) {arm['name']}: `{arm['rule']}`")
        lines.append(f"  - {arm['role']}")
    lines.extend(["", "## Frozen thresholds", "", "| threshold | value |", "| --- | --- |"])
    lines.extend(f"| {key} | {value} |" for key, value in sorted(registry["thresholds"].items()))
    lines.extend(["", "## Features (the only inputs a hypothesis may read)", ""])
    lines.extend(f"- `{item['name']}`: {item['definition']}" for item in registry["features"])
    lines.extend(["", "## Statistical gate", ""])
    gate = registry["statistical_gate"]
    lines.extend(f"- {key}: {value}" for key, value in gate.items())
    lines.extend(["", "## Data status", ""])
    data = payload["data"]
    if data["available"]:
        lines.extend(
            [
                f"- series captured: **{data['series']}** ({data['rows']} rows, "
                f"gaps: **{data['series_with_gaps']}**)",
                f"- derivatives span captured: **{data['derivative_series_span_days']:.2f} days**",
                f"- funding history captured: **{data['funding_history_days']:.2f} days**",
                f"- capture scheduler: {data['scheduler']['task']} ({data['scheduler']['cadence']})",
                f"- {data['scheduler']['why']}",
                f"- {data['retention_policy']}",
            ]
        )
    else:
        lines.append(f"- {data['note']}")
    lines.extend(["", "## Frozen split", ""])
    lines.extend(f"- {key}: {value}" for key, value in payload["frozen_split"].items())
    lines.extend(["", f"- {payload['discovery_status']}", ""])
    lines.extend(["", "## Prohibitions", ""])
    lines.extend(f"- {item}" for item in registry["prohibitions"])
    lines.append("")
    return "\n".join(lines)


def render_closure(payload: dict[str, Any]) -> str:
    result, cause = payload["result"], payload["cause"]
    lines = [
        "# ALPHA-001 — CLOSURE DECISION",
        "",
        f"`{payload['decision']} = {payload['verdict']}` · do not retune",
        "",
        "## Result",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in result.items())
    lines.extend(["", "## Cause", ""])
    lines.extend(f"- {key}: {value}" for key, value in cause.items())
    lines.extend(
        [
            "",
            "## What it tells the system",
            "",
            payload["what_it_tells_the_system"],
            "",
            "## Evidence",
            "",
        ]
    )
    lines.extend(f"- `{key}`: {value}" for key, value in payload["evidence"].items())
    lines.extend(["", "## Reopening requires", ""])
    lines.extend(f"- {item}" for item in payload["reopen_requires"])
    lines.extend(["", "## Prohibited", ""])
    lines.extend(f"- {item}" for item in payload["prohibited"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="write the ALPHA-002 preregistration").parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    preregistration = build_preregistration()
    (OUT_DIR / "ALPHA002_PREREGISTRATION.json").write_text(
        json.dumps(preregistration, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT_DIR / "ALPHA002_PREREGISTRATION.md").write_text(
        render_preregistration(preregistration), encoding="utf-8"
    )
    (OUT_DIR / "ALPHA001_CLOSURE.json").write_text(
        json.dumps(CLOSURE, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "ALPHA001_CLOSURE.md").write_text(render_closure(CLOSURE), encoding="utf-8")

    print(
        json.dumps(
            {
                "PREREGISTRATION_HASH": preregistration["preregistration_hash"],
                "HYPOTHESES": preregistration["hypothesis_ids"],
                "STATUS": preregistration["status"],
                "ALPHA001": f"{CLOSURE['decision']} = {CLOSURE['verdict']}",
                "WRITTEN": str(OUT_DIR.relative_to(REPO)).replace("\\", "/"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
