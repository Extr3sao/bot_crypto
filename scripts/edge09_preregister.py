#!/usr/bin/env python
"""WP-EDGE-09C — register the hypotheses before anything is measured.

    python scripts/edge09_preregister.py            # write the registration
    python scripts/edge09_preregister.py --check    # re-render and compare

The registration carries the hypotheses, the decision rules, the thresholds, the
venue scenarios, the holdouts this project has already spent, and the digests of
the code that will obey them. ``--check`` re-renders the artifact from the code
and fails if the committed file and the code disagree, which is what makes
"registered before measurement" a property rather than a promise.
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

from trading_bot.research.edge09 import (  # noqa: E402
    ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
    CLASSIFICATIONS,
    CONSUMED_HOLDOUTS,
    HYPOTHESES,
    LADDER,
    SCENARIOS_COMPARED,
    WP,
)
from trading_bot.research.edge09.registration import (  # noqa: E402
    FREQUENCY_HORIZONS_SECONDS,
    GRID_SECONDS,
    HORIZONS_SECONDS,
    MARKETS,
    MIN_GROSS_SAFETY_MULTIPLE,
    MIN_OBSERVATIONS,
    QUALITY_FREQUENCY_FLOOR_TRADES_PER_DAY,
    SCHEMA_VERSION,
    UNIVERSE,
    WHAT_THIS_CANNOT_SAY,
)

#: The code the registration binds. A digest here means the hypotheses were
#: fixed against a *version* of the pipeline, not against a moving target.
BOUND_FILES = (
    "src/trading_bot/research/edge09/registration.py",
    "src/trading_bot/research/edge09/panel.py",
    "src/trading_bot/research/edge09/gates.py",
    "src/trading_bot/research/edge09/experiments.py",
    "src/trading_bot/research/edge09/verdict.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-09C",
        "title": "RFC-EDGE-009 — market microstructure and economic edge, registered",
        "registered_before_reading": True,
        "universe": list(UNIVERSE),
        "markets": list(MARKETS),
        "grid_seconds": GRID_SECONDS,
        "horizons_seconds": list(HORIZONS_SECONDS),
        "frequency_horizons_seconds": list(FREQUENCY_HORIZONS_SECONDS),
        "thresholds": {
            "min_observations": MIN_OBSERVATIONS,
            "min_abs_ic": 0.01,
            "admission_safety_multiple": MIN_GROSS_SAFETY_MULTIPLE,
            "active_frequency_target_trades_per_day": ACTIVE_FREQUENCY_TARGET_TRADES_PER_DAY,
            "quality_frequency_floor_trades_per_day": QUALITY_FREQUENCY_FLOOR_TRADES_PER_DAY,
        },
        "tracks": {
            "ACTIVE": (
                "1 s entries with intraday holds; the registered objective is three executed "
                "trades a day across the aggregate universe, never forced"
            ),
            "QUALITY": (
                "5-minute to daily clock; its own floor is 0.05 trades a day and it is judged "
                "separately, never pooled with ACTIVE"
            ),
        },
        "ladder": [dict(row) for row in LADDER],
        "classifications": list(CLASSIFICATIONS),
        "scenarios_compared": list(SCENARIOS_COMPARED),
        "hypotheses": [hypothesis.as_dict() for hypothesis in HYPOTHESES],
        "consumed_holdouts": [dict(row) for row in CONSUMED_HOLDOUTS],
        "declared_limitations": list(WHAT_THIS_CANNOT_SAY),
        "bound_code": {relative: sha256_file(REPO_ROOT / relative) for relative in BOUND_FILES},
        "negative_control_rule": (
            "E-07 runs the identical pipeline on a feature destroyed by a deterministic "
            "shuffle; if it is classified positive, every other result of this package is void"
        ),
        "promotion": "NONE",
        "order_sent": False,
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-09C — pre-registration",
        "",
        "> Fixed before the cross-section of this package was read, and bound by digest to the "
        "code that obeys it. `--check` re-renders this artifact from that code.",
        "",
        "## 1. Universe, clock and thresholds",
        "",
        "| | |",
        "| --- | --- |",
        f"| Universe | {', '.join(payload['universe'])} |",
        f"| Markets | {', '.join(payload['markets'])} |",
        f"| Decision grid | {payload['grid_seconds']} s |",
        f"| Microstructure horizons | {payload['horizons_seconds']} s |",
        f"| Frequency horizons | {payload['frequency_horizons_seconds']} s |",
        f"| Minimum observations | {payload['thresholds']['min_observations']} |",
        f"| Minimum |IC| | {payload['thresholds']['min_abs_ic']} |",
        f"| Admission safety multiple | {payload['thresholds']['admission_safety_multiple']}x |",
        f"| ACTIVE target | {payload['thresholds']['active_frequency_target_trades_per_day']} executed trades/day |",
        f"| QUALITY floor | {payload['thresholds']['quality_frequency_floor_trades_per_day']} trades/day |",
        "",
        "## 2. Tracks, kept apart",
        "",
    ]
    for track, description in payload["tracks"].items():
        lines.append(f"- **{track}** — {description}")
    lines += [
        "",
        "## 3. The ladder, applied in order",
        "",
        "| Filter | Name | Rule |",
        "| --- | --- | --- |",
    ]
    for row in payload["ladder"]:
        lines.append(f"| {row['id']} | {row['name']} | {row['rule']} |")
    lines += [
        "",
        "## 4. Hypotheses, with the condition that kills each one",
        "",
    ]
    for hypothesis in payload["hypotheses"]:
        lines += [
            f"### `{hypothesis['id']}` — {hypothesis['title']} ({hypothesis['track']})",
            "",
            f"- **Statement.** {hypothesis['statement']}",
            f"- **Falsified if.** {hypothesis['falsified_if']}",
            f"- **Data required.** {hypothesis['data_requirement']}",
            f"- **Decided at.** {hypothesis['decided_at']}",
            f"- **Executable under this runtime.** {hypothesis['executable']}",
        ]
        if hypothesis["note"]:
            lines.append(f"- **Note.** {hypothesis['note']}")
        lines.append("")
    lines += [
        "## 5. Holdouts this project has already spent",
        "",
        "| Holder | What was spent | Evidence |",
        "| --- | --- | --- |",
    ]
    for row in payload["consumed_holdouts"]:
        what = row["what"]
        if row.get("symbols"):
            what += f" — symbols {row['symbols']}, window {row.get('window', '')}"
        lines.append(f"| {row['holder']} | {what} | `{row['evidence']}` |")
    lines += [
        "",
        "## 6. Bound code",
        "",
        "| File | SHA-256 |",
        "| --- | --- |",
    ]
    for relative, digest in payload["bound_code"].items():
        lines.append(f"| `{relative}` | `{digest[:16]}…` |")
    lines += [
        "",
        "## 7. What this package cannot say",
        "",
    ]
    for limitation in payload["declared_limitations"]:
        lines.append(f"- {limitation}")
    lines += [
        "",
        f"`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)

    payload = build()
    rendered_json = json.dumps(payload, indent=2) + "\n"
    rendered_md = render(payload)
    json_path = WP / "PREREGISTRATION.json"
    md_path = WP / "PREREGISTRATION.md"

    if options.check:
        mismatched = []
        if not json_path.is_file() or json_path.read_text(encoding="utf-8") != rendered_json:
            mismatched.append(str(json_path.relative_to(REPO_ROOT)))
        if not md_path.is_file() or md_path.read_text(encoding="utf-8") != rendered_md:
            mismatched.append(str(md_path.relative_to(REPO_ROOT)))
        for relative, digest in payload["bound_code"].items():
            if sha256_file(REPO_ROOT / relative) != digest:
                mismatched.append(relative)
        if mismatched:
            print(f"registration does NOT match the code: {mismatched}")
            return 1
        print("registration matches the code that obeys it")
        return 0

    WP.mkdir(parents=True, exist_ok=True)
    json_path.write_text(rendered_json, encoding="utf-8")
    md_path.write_text(rendered_md, encoding="utf-8")
    print(
        f"registered {len(payload['hypotheses'])} hypotheses, "
        f"{len(payload['ladder'])} filters, {len(payload['scenarios_compared'])} scenarios"
    )
    print(f"wrote {json_path.relative_to(REPO_ROOT)} and {md_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
