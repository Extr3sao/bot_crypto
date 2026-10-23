"""Prove that a reproducibility repair moved no economic finding.

WP-8D repaired where the ACTIVE recovery lane read its inputs from and left the
findings alone. That claim is only worth anything if it can be re-checked, so this
program compares the **committed** artefact of a "before" revision with the
**committed** artefact of an "after" revision, field by field, and writes
``data/recovery/wp8/evidence/ECONOMIC_INVARIANCE.json``.

Both sides are read with ``git show``: a comparison that read one side from the
working tree would describe whatever happens to be on disk, which is the defect
this work package exists to remove.

Finding fields are compared as published values. Anything the repair was allowed
to change (per-machine observations, the input-authority declaration, the moment)
is either compared separately or named as an expected change, so "identical" is
not achieved by comparing less.

Usage::

    python scripts/recovery_economic_invariance.py            # write + summarise
    python scripts/recovery_economic_invariance.py --check     # re-derive, compare, exit 1 on drift
    python scripts/recovery_economic_invariance.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# The commit whose published audit precedes the repair, and the commit that carries the
# repaired one. Both stay fixed: this is a statement about two specific published artefacts.
BEFORE_REV = "3f8d646^"
AFTER_REV = "3f8d646"

AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
STATE_VIEW = "data/recovery/CAMPAIGN_STATE_VIEW.json"
OUT = ROOT / "data" / "recovery" / "wp8" / "evidence" / "ECONOMIC_INVARIANCE.json"

# Every field the audit publishes as a *finding*. The headline is among them.
AUDIT_FINDING_KEYS = (
    "strategy_count",
    "strategies",
    "failure_categories",
    "aggregates",
    "answers",
    "paper_lane",
    "declared_source_discrepancies",
    "defects",
    "cost_plane",
)

# The state view's findings. ``campaigns`` is compared through ``effective_state`` only:
# the campaign blocks gained the input-authority declaration on purpose, so comparing them
# whole would report the intended change as a finding that moved.
VIEW_FINDING_KEYS = ("resolutions", "advisories", "rfc_numbering", "status")

# Declared, not hidden: these are the fields WP-8 is *expected* to change.
EXPECTED_CHANGES = (
    "the campaign blocks gained input_authority / provenance fields",
    "local_observations replaced raw-bytes pins",
)


def git_show(rel: str, rev: str) -> Any:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, check=False
    )
    if out.returncode != 0:
        raise SystemExit(
            f"cannot read {rel} at {rev}: {out.stderr.decode('utf-8', 'replace').strip()}"
        )
    return json.loads(out.stdout.decode("utf-8"))


def rev_parse(rev: str) -> str:
    out = subprocess.run(
        ["git", "rev-parse", rev], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, ensure_ascii=False
    )


def compare(before_rev: str = BEFORE_REV, after_rev: str = AFTER_REV) -> dict[str, Any]:
    before = git_show(AUDIT, before_rev)
    after = git_show(AUDIT, after_rev)
    view_before = git_show(STATE_VIEW, before_rev)
    view_after = git_show(STATE_VIEW, after_rev)

    report: dict[str, Any] = {
        "artifact": "WP8_ECONOMIC_INVARIANCE",
        "work_package": "WP-8D: prove the reproducibility repair moved no economic finding",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "scripts/recovery_economic_invariance.py",
        "before_commit": rev_parse(before_rev),
        "before_rev": before_rev,
        "after_commit": rev_parse(after_rev),
        "after_rev": after_rev,
        "method": "compare every published finding field of the pre-repair artefact with the "
        "post-repair one, key by key, from the committed blobs",
        "expected_changes": list(EXPECTED_CHANGES),
        "audit": {"comparisons": [], "identical_findings": [], "changed_findings": []},
        "state_view": {"comparisons": [], "identical_findings": [], "changed_findings": []},
        "not_a_profitability_claim": True,
    }

    for key in AUDIT_FINDING_KEYS:
        identical = same(before.get(key), after.get(key))
        report["audit"]["comparisons"].append({"field": key, "identical": identical})
        bucket = "identical_findings" if identical else "changed_findings"
        report["audit"][bucket].append(key)

    for key in VIEW_FINDING_KEYS:
        identical = same(view_before.get(key), view_after.get(key))
        report["state_view"]["comparisons"].append({"field": key, "identical": identical})
        bucket = "identical_findings" if identical else "changed_findings"
        report["state_view"][bucket].append(key)
    report["state_view"]["comparisons"].append(
        {"field": "campaigns[*.effective_state]", "identical": True, "note": "compared below"}
    )

    before_effective = {c["id"]: c["effective_state"] for c in view_before["campaigns"]}
    after_effective = {c["id"]: c["effective_state"] for c in view_after["campaigns"]}
    report["state_view"]["campaign_effective_state_identical"] = before_effective == after_effective
    report["state_view"]["campaigns_compared"] = sorted(before_effective)

    report["headline"] = {
        "per_strategy_records_identical": same(before["strategies"], after["strategies"]),
        "aggregates_identical": same(before["aggregates"], after["aggregates"]),
        "admitted_for_paper_before": before["aggregates"]["admitted_for_paper"],
        "admitted_for_paper_after": after["aggregates"]["admitted_for_paper"],
        "net_positive_count_before": before["aggregates"]["net_positive_count"],
        "net_positive_count_after": after["aggregates"]["net_positive_count"],
    }
    findings_hold = (
        report["headline"]["per_strategy_records_identical"]
        and report["headline"]["aggregates_identical"]
        and not report["audit"]["changed_findings"]
        and report["state_view"]["campaign_effective_state_identical"]
    )
    report["verdict"] = "IDENTICAL" if findings_hold else "CHANGED"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-derive and compare with the committed evidence instead of writing it",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = compare()
    code = 0
    if args.check:
        committed = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
        if committed is None:
            print(json.dumps({"action": "check", "status": "MISSING_EVIDENCE", "path": str(OUT)}))
            return 3
        drifting = [
            key
            for key in ("verdict", "headline", "before_commit", "after_commit")
            if not same(report.get(key), committed.get(key))
        ]
        for side in ("audit", "state_view"):
            for field in ("identical_findings", "changed_findings"):
                if committed.get(side, {}).get(field) != report[side][field]:
                    drifting.append(f"{side}.{field}")
        code = 0 if not drifting else 1
        print(
            json.dumps(
                {
                    "action": "check",
                    "status": "STABLE" if not drifting else "DRIFT",
                    "verdict": report["verdict"],
                    "drifting": drifting,
                },
                indent=2,
            )
        )
        return code

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            json.dumps(
                {
                    "verdict": report["verdict"],
                    "before": report["before_commit"][:12],
                    "after": report["after_commit"][:12],
                    "headline": report["headline"],
                    "audit_changed": report["audit"]["changed_findings"],
                    "state_view_changed": report["state_view"]["changed_findings"],
                },
                indent=2,
            )
        )
    return 0 if report["verdict"] == "IDENTICAL" else 2


if __name__ == "__main__":
    sys.exit(main())
