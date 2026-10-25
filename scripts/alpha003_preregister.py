"""Write the committed ALPHA-003 preregistration and the ALPHA-002 closure record.

The preregistration is written to ``docs/research/alpha003/`` so that Git timestamps it: a
frozen registry that only exists in memory is not evidence.  The closure record states what
ALPHA-002 concluded, so the parent chain of this campaign is committed rather than implied.

The split is *not* computed here — it is computed by the development driver from the real,
fetched price span and reported back.  What is frozen here is the rule that produces it
(60/20/20 over the common calendar, holdout never read), so the boundaries cannot be chosen
after seeing a result.

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

from trading_bot.research.alpha003 import (  # noqa: E402
    CONTEXT_STATISTICS,
    COST_BPS_V3,
    ENTRY_TIMEFRAMES,
    HYPOTHESES,
    LEAD_LAGS,
    LEADER_TARGET_PAIRS,
    PREREGISTRATION,
    UNIVERSE,
    preregistration_hash,
)
from trading_bot.research.alpha003_experiment import (  # noqa: E402
    DISCOVERY_FRACTION,
    HOLDOUT_FRACTION,
    VALIDATION_FRACTION,
    cell_ids,
)
from trading_bot.research.alpha003_features import (  # noqa: E402
    FEATURE_CONFIG,
    feature_version,
)

OUT_DIR = REPO / "docs" / "research" / "alpha003"

CLOSURE: dict[str, Any] = {
    "campaign": "ALPHA-002",
    "title": "Derivatives Positioning & Order-Flow Alpha",
    "decision": "DEVELOPMENT COMPLETE",
    "verdict": "NO_ALPHA_WITH_UNTESTED_HYPOTHESES",
    "do_not_retune": True,
    "result": {
        "hypotheses_tested": 3,
        "A2-H01": "REJECT",
        "A2-H03": "REJECT",
        "A2-H02": "INCONCLUSIVE",
        "oos_candidates": 0,
        "holdout_read": False,
        "false_success": 0,
        "verifier": "PASS 61/61",
        "preregistration_hash": (
            "8b09f608256a31722b366f10e52513e9a347405d078138a9c350df1ad2439f6b"
        ),
    },
    "cause": {
        "binding_constraint": "the derivatives confirmation subtracted value",
        "baseline_delta_bps": {"A2-H01": -1.228127, "A2-H03": -1.224440, "A2-H02": -0.127502},
        "note": (
            "against the same rule with the derivatives confirmation removed, every"
            " fully-exercised mechanism did worse, i.e. participant data added nothing over the"
            " price condition it was built on"
        ),
        "untested_reason": (
            "A2-H02's frozen threshold (funding > 1e-4) was never strictly exceeded in the"
            " discovery slice — the maximum observed was exactly 1e-4 across all four assets —"
            " so it produced zero decisions and is recorded as INCONCLUSIVE, not negative"
        ),
    },
    "research_hypotheses_not_pursued": [
        "OI contraction may outperform OI expansion (the declared non-traded exhaustion contrast"
        " out-returned the expansion subset; recorded for a future campaign, not pursued here)",
    ],
    "evidence": {
        "preregistration": "docs/research/alpha002/ALPHA002_PREREGISTRATION.{md,json}",
        "development_results": "reports/alpha002/ALPHA002_DEVELOPMENT_RESULTS.{md,json}",
        "verification": "reports/alpha002/ALPHA002_VERIFICATION.{md,json}",
        "commit": "ea4d488",
    },
    "prohibited": [
        "retuning thresholds, horizons or the cost model on this family",
        "promoting an UNDERPOWERED cell to a candidate",
        "re-reading the ALPHA-002 holdout for an ALPHA-002 question",
    ],
}


def build_preregistration(disk: dict[str, Any]) -> dict[str, Any]:
    cells = cell_ids()
    return {
        "registry": PREREGISTRATION,
        "preregistration_hash": preregistration_hash(),
        "feature_version": feature_version(),
        "feature_config": FEATURE_CONFIG,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "cost_bps": COST_BPS_V3,
        "hypothesis_ids": [item["hypothesis_id"] for item in HYPOTHESES],
        "universe": list(UNIVERSE),
        "entry_timeframes": list(ENTRY_TIMEFRAMES),
        "leader_target_pairs": [list(pair) for pair in LEADER_TARGET_PAIRS],
        "lead_lags": list(LEAD_LAGS),
        "cells": cells,
        "cell_count": len(cells),
        "context_statistics": [dict(item) for item in CONTEXT_STATISTICS],
        "status": "FROZEN_AWAITING_RESULT",
        "discovery_status": (
            "not started: the registry, the thresholds, the feature construction constants and"
            " the split rule below are frozen before any cross-asset result is computed"
        ),
        "frozen_split": {
            "rule": (
                "a calendar split of the common price span, identical for every asset, pair, lag"
                " and timeframe, with the final fifth reserved and never read by development"
            ),
            "discovery_fraction": DISCOVERY_FRACTION,
            "validation_fraction": VALIDATION_FRACTION,
            "holdout_fraction": HOLDOUT_FRACTION,
            "holdout_lock": "HOLDOUT LOCKED during ALPHA-003 development",
        },
        "disk": disk,
    }


def disk_status() -> dict[str, Any]:
    import shutil

    usage = shutil.disk_usage(REPO)
    free_gib = usage.free / (1024**3)
    return {
        "total_gib": round(usage.total / (1024**3), 2),
        "used_gib": round(usage.used / (1024**3), 2),
        "free_gib": round(free_gib, 2),
        "used_fraction": round(usage.used / usage.total, 4),
        "note": (
            "the research dataset is generated under data/raw/alpha003 (gitignored); no existing"
            " data is removed"
        ),
    }


def render_preregistration(payload: dict[str, Any]) -> str:
    registry = payload["registry"]
    lines = [
        "# ALPHA-003 — PREREGISTRATION (frozen before any result)",
        "",
        f"`PREREGISTRATION_HASH = {payload['preregistration_hash']}`",
        f"`FEATURE_VERSION = {payload['feature_version']}`",
        "",
        f"- campaign: **{registry['campaign']} — {registry['title']}**",
        f"- question: {registry['question']}",
        f"- central question: {registry['central_question']}",
        f"- status: **{payload['status']}**",
        f"- universe: {', '.join(payload['universe'])}",
        f"- entry timeframes: {', '.join(payload['entry_timeframes'])} · context: "
        f"{registry['context_timeframe']} · forward horizon: {registry['forward_bars']} bar",
        "- leader -> target pairs: "
        + ", ".join(f"{a}->{b}" for a, b in payload["leader_target_pairs"]),
        f"- lead ladder: {payload['lead_lags']} entry bars",
        f"- cells: **{payload['cell_count']}** declared, and no cell outside this list is reported",
        f"- cost model: {registry['cost_model']['name']} at {payload['cost_bps']} bps, "
        f"inherited and not retuned",
        f"- machine learning used: **{registry['machine_learning']['used']}** "
        f"(prohibited: {', '.join(registry['machine_learning']['prohibited'])})",
        "",
        "## Relationship to the parent campaigns",
        "",
    ]
    parent = registry["parent"]
    for name, item in parent.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.extend(f"- {key}: {value}" for key, value in item.items())
        lines.append("")
    lines.extend(
        [
            "## The incremental definition (the whole campaign)",
            "",
            f"{registry['incremental_definition']}",
            "",
            "A cross-asset arm that merely replicates ordinary own-asset momentum is a failure of",
            "this campaign, and the arithmetic is written to say so.",
            "",
            "## Hypotheses",
            "",
        ]
    )
    for item in registry["hypotheses"]:
        lines.extend(
            [
                f"### {item['hypothesis_id']} — {item['name']} ({item['family_id']})",
                "",
                f"- mechanism: {item['mechanism']}",
                f"- direction rule: `{item['direction_rule']}`",
                f"- baseline arm (incremental measured against): `{item['baseline_arm']}`",
                f"- expected regime: {item['expected_regime']}",
                f"- invalidation: {item['invalidation']}",
                f"- timeframes: {', '.join(item['timeframes'])}",
                "",
            ]
        )
        if "direction_note" in item:
            lines.append(f"- direction note: {item['direction_note']}")
            lines.append("")
    lines.extend(["## Declared baselines", ""])
    for item in registry["baselines"]:
        lines.append(f"- **{item['baseline_id']}**: `{item['rule']}` — {item['role']}")
    lines.extend(["", "## Declared non-traded arms", ""])
    for arm in registry["non_traded_arms"]:
        lines.append(f"- **{arm['arm_id']}** ({arm['hypothesis_id']}) {arm['name']}: `{arm['rule']}`")
        lines.append(f"  - {arm['role']}")
    lines.extend(["", "## Frozen thresholds (ATR units)", "", "| threshold | value |", "| --- | --- |"])
    lines.extend(f"| {key} | {value} |" for key, value in sorted(registry["thresholds"].items()))
    lines.extend(["", "## Features (the only inputs a hypothesis may read)", ""])
    lines.extend(f"- `{item['name']}`: {item['definition']}" for item in registry["features"])
    lines.extend(["", "## Context statistics (reported, never inputs)", ""])
    lines.extend(f"- `{item['name']}`: {item['definition']}" for item in payload["context_statistics"])
    lines.extend(["", "## Feature construction constants", "", "| key | value |", "| --- | --- |"])
    lines.extend(f"| {key} | {value} |" for key, value in sorted(payload["feature_config"].items()))
    lines.extend(["", "## Statistical gate", ""])
    lines.extend(f"- {key}: {value}" for key, value in registry["statistical_gate"].items())
    lines.extend(["", "## Frozen split", ""])
    lines.extend(f"- {key}: {value}" for key, value in payload["frozen_split"].items())
    lines.extend(["", f"- {payload['discovery_status']}", ""])
    lines.extend(["## Disk at freeze time", ""])
    lines.extend(f"- {key}: {value}" for key, value in payload["disk"].items())
    lines.extend(["", "## Prohibitions", ""])
    lines.extend(f"- {item}" for item in registry["prohibitions"])
    lines.append("")
    return "\n".join(lines)


def render_closure(payload: dict[str, Any]) -> str:
    lines = [
        "# ALPHA-002 — CLOSURE DECISION",
        "",
        f"`{payload['decision']} = {payload['verdict']}` · do not retune",
        "",
        "## Result",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in payload["result"].items())
    lines.extend(["", "## Cause", ""])
    lines.extend(f"- {key}: {value}" for key, value in payload["cause"].items())
    lines.extend(["", "## Recorded research hypotheses (not pursued here)", ""])
    lines.extend(f"- {item}" for item in payload["research_hypotheses_not_pursued"])
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in payload["evidence"].items())
    lines.extend(["", "## Prohibited", ""])
    lines.extend(f"- {item}" for item in payload["prohibited"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="write the ALPHA-003 preregistration").parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    preregistration = build_preregistration(disk_status())
    (OUT_DIR / "ALPHA003_PREREGISTRATION.json").write_text(
        json.dumps(preregistration, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT_DIR / "ALPHA003_PREREGISTRATION.md").write_text(
        render_preregistration(preregistration), encoding="utf-8"
    )
    (OUT_DIR / "ALPHA002_CLOSURE.json").write_text(
        json.dumps(CLOSURE, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "ALPHA002_CLOSURE.md").write_text(render_closure(CLOSURE), encoding="utf-8")

    print(
        json.dumps(
            {
                "PREREGISTRATION_HASH": preregistration["preregistration_hash"],
                "FEATURE_VERSION": preregistration["feature_version"],
                "CELLS": preregistration["cell_count"],
                "HYPOTHESES": preregistration["hypothesis_ids"],
                "STATUS": preregistration["status"],
                "ALPHA002": f"{CLOSURE['decision']} = {CLOSURE['verdict']}",
                "WRITTEN": str(OUT_DIR.relative_to(REPO)).replace("\\", "/"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
