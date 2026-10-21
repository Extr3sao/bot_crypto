"""WP-003P-05 — compare a published run with a run produced by a clean checkout.

    python scripts/exp_003p_checkout_compare.py \\
        --published reports/ai-bots/EXP-003P-PAPER-EXECUTION-001 \\
        --reproduced ../003p-checkout/reports/ai-bots/EXP-003P-PAPER-EXECUTION-001 \\
        --install-command "uv pip sync <frozen freeze file>" \\
        --requirements /tmp/003p_baseline_requirements.txt

Why this exists: the rehearsal's own ``--checkout-check`` flag cannot prove a reproduction,
because a process that rewrites the directory it then reads from compares a file with
itself. This program takes **two directories** it did not write and compares what is in
them, so the verdict does not depend on the code under test.

What counts as the same:

* the **content** digests (ledger, order lifecycle, protocol, config) must be byte-equal;
* the two JSONL traces must be row-for-row equal **after normalising the commit field they
  bind**, because a trace that records its own commit cannot be byte-identical across two
  commits — that field is the one legitimate difference;
* the verifier's per-check outcomes and the controls' effective classes must match;
* the reconciliation verdicts must match.

A missing file is ``FAILED``, not "not comparable": a reproduction that produced fewer
artifacts than the baseline did not reproduce it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from exp_003p_contract import RUN_ID, git, read_json, write_json  # noqa: E402

#: Digests that describe what the runtime did, not which commit it was built from. These
#: must be byte-identical or the two runs did different things.
CONTENT_DIGESTS = (
    "protocol_sha256",
    "config_digest",
    "ledger_digest_runtime",
    "ledger_digest_scenario",
    "lifecycle_csv_sha256",
)

#: Digests that bind `commit_sha` inside the envelopes they cover, so a trace produced at
#: another commit cannot carry the same hash by construction. They are compared, reported,
#: and — when they differ — justified by the row-by-row comparison below rather than
#: required. Equal is better; equal-by-row is the fallback.
COMMIT_BOUND_DIGESTS = (
    "execution_trace_sha256",
    "scenario_trace_sha256",
    "store_digest_runtime",
    "store_digest_scenario",
    "run_digest",
)

TRACES = ("EXECUTION_TRACE.jsonl", "SCENARIO_TRACE.jsonl")


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _normalise_trace(path: Path) -> list[str] | None:
    """Rows as canonical JSON with the commit they bind replaced by a token.

    ``chain_digest`` is recomputed by the runtime over the envelope that includes
    ``commit_sha``, so it cascades from that one field. Comparing the rows without the
    commit and without the cascade is the only comparison that can distinguish "the same
    execution at another commit" from "a different execution".
    """

    if not path.exists():
        return None
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["commit_sha"] = "<COMMIT>"
        if "chain_digest" in row:
            row["chain_digest"] = "<CHAIN>"
        rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return rows


def _checks(path: Path) -> dict[str, list[bool]] | None:
    if not path.exists():
        return None
    payload = read_json(path)
    grouped: dict[str, list[bool]] = {}
    for check in payload.get("checks") or []:
        grouped.setdefault(str(check.get("check_id")), []).append(bool(check.get("passed")))
    return grouped


def compare(published: Path, reproduced: Path) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    failures: list[str] = []

    published_digests = read_json(published / "DIGESTS.json") if (published / "DIGESTS.json").exists() else {}
    reproduced_digests = (
        read_json(reproduced / "DIGESTS.json") if (reproduced / "DIGESTS.json").exists() else {}
    )
    for key in CONTENT_DIGESTS:
        left = published_digests.get(key)
        right = reproduced_digests.get(key)
        same = left is not None and left == right
        comparisons[f"digest:{key}"] = {"identical": same, "published": left, "reproduced": right}
        if not same:
            failures.append(f"digest:{key}")

    for key in COMMIT_BOUND_DIGESTS:
        left = published_digests.get(key)
        right = reproduced_digests.get(key)
        comparisons[f"commit_bound:{key}"] = {
            "byte_identical": left is not None and left == right,
            "published": left,
            "reproduced": right,
        }

    for name in TRACES:
        left_rows = _normalise_trace(published / name)
        right_rows = _normalise_trace(reproduced / name)
        same = left_rows is not None and left_rows == right_rows
        comparisons[f"trace:{name}"] = {
            "identical_after_commit_normalisation": same,
            "byte_identical": (published / name).exists()
            and (reproduced / name).exists()
            and _sha256(published / name) == _sha256(reproduced / name),
            "rows_published": None if left_rows is None else len(left_rows),
            "rows_reproduced": None if right_rows is None else len(right_rows),
        }
        if not same:
            failures.append(f"trace:{name}")

    for name in ("ORDER_LIFECYCLE.csv", "ORDER_LIFECYCLE.json", "METRICS.json"):
        left = _sha256(published / name)
        right = _sha256(reproduced / name)
        same = left is not None and left == right
        comparisons[f"file:{name}"] = {"identical": same, "published": left, "reproduced": right}
        if not same:
            failures.append(f"file:{name}")

    published_checks = _checks(published / "VERIFICATION.json")
    reproduced_checks = _checks(reproduced / "VERIFICATION.json")
    same_checks = published_checks is not None and published_checks == reproduced_checks
    comparisons["verification"] = {
        "identical_outcomes": same_checks,
        "checks": len(published_checks or {}),
        "passed": sorted(k for k, v in (reproduced_checks or {}).items() if all(v)),
    }
    if not same_checks:
        failures.append("verification")

    published_controls = (
        read_json(published / "NEGATIVE_CONTROLS.json")
        if (published / "NEGATIVE_CONTROLS.json").exists()
        else {}
    )
    reproduced_controls = (
        read_json(reproduced / "NEGATIVE_CONTROLS.json")
        if (reproduced / "NEGATIVE_CONTROLS.json").exists()
        else {}
    )

    def _classes(payload: dict[str, Any]) -> dict[str, str]:
        return {
            str(control.get("id")): str(control.get("observed_class") or control.get("observed"))
            for control in payload.get("controls") or []
        }

    same_controls = _classes(published_controls) == _classes(reproduced_controls) and bool(
        published_controls
    )
    comparisons["controls"] = {
        "identical_classes": same_controls,
        "effective_published": published_controls.get("controls_effective"),
        "effective_reproduced": reproduced_controls.get("controls_effective"),
    }
    if not same_controls:
        failures.append("controls")

    published_recon = read_json(published / "RECONCILIATION.json")
    reproduced_recon = read_json(reproduced / "RECONCILIATION.json")
    same_recon = published_recon.get("result") == reproduced_recon.get("result") and (
        published_recon.get("runtime") or {}
    ).get("result") == (reproduced_recon.get("runtime") or {}).get("result")
    comparisons["reconciliation"] = {
        "identical": same_recon,
        "published": published_recon.get("result"),
        "reproduced": reproduced_recon.get("result"),
    }
    if not same_recon:
        failures.append("reconciliation")

    comparisons["dataset"] = {
        "files": len(read_json(published / "evidence" / "BASELINE.json").get("dataset", {}).get("files") or {}),
        "digests_match": (
            (read_json(published / "evidence" / "BASELINE.json").get("dataset") or {}).get("files")
            == (read_json(reproduced / "evidence" / "BASELINE.json").get("dataset") or {}).get("files")
        ),
    }
    if not comparisons["dataset"]["digests_match"]:
        failures.append("dataset")

    return {"comparisons": comparisons, "differences": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003P clean-checkout reproduction gate")
    parser.add_argument("--published", required=True)
    parser.add_argument("--reproduced", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--install-command", default="not recorded")
    parser.add_argument("--requirements", default=None)
    parser.add_argument("--worktree", default=None)
    parser.add_argument("--checkout-commit", default=None)
    args = parser.parse_args(argv)

    published = Path(args.published)
    reproduced = Path(args.reproduced)
    out = Path(args.out) if args.out else published / "evidence" / "CLEAN_CHECKOUT_REPRODUCTION.json"

    if published.resolve() == reproduced.resolve():
        print("[003p-compare] REFUSED — the two directories are the same one")
        return 2

    payload: dict[str, Any] = {
        "schema_version": "AI_BOTS_003P_CHECKOUT_REPRODUCTION_V1",
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": args.checkout_commit or git("rev-parse", "HEAD"),
        "published_tree": str(published),
        "reproduced_tree": str(reproduced),
        "worktree": args.worktree,
        "method": (
            "git worktree add --detach <commit>; dependencies installed from the committed "
            "uv.lock; the 003K dataset read from the checkout itself; every phase re-run "
            "there; the two directories then compared by this program"
        ),
        "install_command": args.install_command,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "network_used_for_data": False,
        },
    }
    if args.requirements:
        requirements = Path(args.requirements)
        payload["requirements"] = {
            "path": str(requirements),
            "sha256": _sha256(requirements) if requirements.exists() else None,
            "lines": (
                len(requirements.read_text(encoding="utf-8").splitlines())
                if requirements.exists()
                else None
            ),
        }

    result = compare(published, reproduced)
    payload.update(result)
    payload["verdict"] = "REPRODUCED" if not result["differences"] else "FAILED"
    payload["detail"] = (
        "every content digest, trace row, verifier outcome, control class and reconciliation "
        "verdict matched"
        if payload["verdict"] == "REPRODUCED"
        else f"differences: {', '.join(result['differences'])}"
    )
    write_json(out, payload)
    print(
        f"[003p-compare] {payload['verdict']} "
        f"differences={result['differences']} out={out}"
    )
    return 0 if payload["verdict"] == "REPRODUCED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
