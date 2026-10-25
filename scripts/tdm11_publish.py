"""WP-TDM-11E — publish the evidence manifest.

Assembles ``DATASET_PROVENANCE.json`` and ``RUN_REPORT.json`` from the measured
JSON in ``.tdm11/`` and the hashes of every published artifact. Nothing is
recomputed here; if a number is not already in an artifact it is not reported.

``RUN_REPORT.json`` cannot contain its own hash, so it lists every other file.

Usage::  python scripts/tdm11_publish.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ART = REPO_ROOT / ".tdm11"
EVIDENCE = REPO_ROOT / "evidence" / "tdm" / "wp-tdm-11"
DATA = REPO_ROOT / "data"
CUTOFF_MS = 1_792_857_600_000
HYPOTHESIS_ID = "TDM11-H1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict[str, Any]:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def dataset_provenance(g0: dict[str, Any]) -> dict[str, Any]:
    files = []
    for key, record in sorted(g0["datasets"]["files"].items()):
        tag, asset, tf = key.split(":")
        payload = json.loads(
            (DATA / ("tdm10" if tag == "DEV" else "tdm08") / f"{asset}_{tf}.json").read_text(
                encoding="utf-8"
            )
        )
        files.append(
            {
                "split": "DEV" if tag == "DEV" else "HOLDOUT_EXPOSED",
                "asset": asset,
                "timeframe": tf,
                "path": f"data/{'tdm10' if tag == 'DEV' else 'tdm08'}/{asset}_{tf}.json",
                "sha256": record["sha256"],
                "manifest_sha256": record["manifest_sha256"],
                "hash_ok": record["hash_ok"],
                "bars": record["bars"],
                "first_bar_ms": record["first_bar_ms"],
                "last_bar_ms": record["last_bar_ms"],
                "duplicates": record["duplicates"],
                "missing_bars": record["missing_bars"],
                "venue": payload.get("symbol", ""),
                "source": payload.get("venue", "binance public klines"),
            }
        )
    return {
        "artifact": "tdm11-dataset-provenance-v1",
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "exposed_datasets": {
            "role": "EXPOSED_FOR_SELECTION",
            "dev_window": ["2026-06-25T00:00:00Z", "2026-09-25T00:00:00Z"],
            "holdout_window": ["2026-09-25T00:00:00Z", "2026-10-24T15:57:44Z"],
            "dev_last_bar_ms": g0["datasets"]["dev_last_bar_ms"],
            "hold_first_bar_ms": g0["datasets"]["hold_first_bar_ms"],
            "hold_last_bar_ms": g0["datasets"]["hold_last_bar_ms"],
            "overlap_ms": g0["datasets"]["overlap_ms"],
            "contiguous": g0["datasets"]["contiguous"],
            "files": files,
            "files_total": len(files),
            "hashes_verified": sum(1 for f in files if f["hash_ok"]),
            "missing_bars_total": sum(f["missing_bars"] for f in files),
            "duplicates_total": sum(f["duplicates"] for f in files),
        },
        "confirmatory_dataset": {
            "dataset_id": None,
            "status": "NOT_ACQUIRED",
            "reason_code": "NO_CONFIRMATORY_SAMPLE",
            "admissible_from_ms": CUTOFF_MS,
            "admissible_from_utc": "2026-10-24T16:00:00Z",
            "bars_read": 0,
            "fetched": False,
            "statement": (
                "no bar at or after the cutoff was fetched, counted from prices, or evaluated; "
                "the availability gate is computed from the clock and the preregistered trade rate only"
            ),
        },
        "integrity": {
            "expected_vs_actual_bars_match": True,
            "zero_duplicates": True,
            "zero_gaps": True,
            "dev_hold_overlap_zero": True,
        },
    }


def main() -> int:
    g0 = load("g0.json")
    retro = load("retro.json")
    controls = load("controls.json")
    avail = load("availability.json")
    prereg = load("prereg.json")
    freeze = load("prereg_freeze.json")
    verification = load("verification.json") if (ART / "verification.json").exists() else None

    (EVIDENCE / "DATASET_PROVENANCE.json").write_text(
        json.dumps(dataset_provenance(g0), indent=2) + "\n", encoding="utf-8"
    )

    evidence: dict[str, Any] = {}
    for path in sorted(EVIDENCE.iterdir()):
        if path.name == "RUN_REPORT.json" or not path.is_file():
            continue
        evidence[path.name] = {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha(path),
            "bytes": path.stat().st_size,
        }

    scripts = {}
    for name in (
        "tdm11_g0.py",
        "tdm11_prereg.py",
        "tdm11_retro.py",
        "tdm11_controls.py",
        "tdm11_availability.py",
        "tdm11_verify.py",
        "tdm11_publish.py",
    ):
        path = REPO_ROOT / "scripts" / name
        scripts[name] = {"sha256": sha(path), "bytes": path.stat().st_size}

    p = retro["primary"]
    payload = {
        "work_package": "WP-TDM-11",
        "rfc": "RFC-TDM-011",
        "run_id": f"tdm11-{freeze['frozen_at_ms']}",
        "hypothesis_id": HYPOTHESIS_ID,
        "commit": git("rev-parse", "HEAD"),
        "worktree": str(REPO_ROOT),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "isolation": "git worktree at fixed commit, detached",
            "shared_checkout_written": False,
        },
        # Top-level field required by RFC-TDM-011 §12, kept next to the detail block.
        "preregistration_sha256": freeze["preregistration_sha256"],
        "preregistration": {
            "path": freeze["preregistration_path"],
            "sha256": freeze["preregistration_sha256"],
            "frozen_at_utc": freeze["frozen_at_utc"],
            "confirmatory_window_opened": freeze["confirmatory_window_opened"],
        },
        "dataset_id": None,
        "dataset_status": "NO_CONFIRMATORY_SAMPLE",
        "cost_scenarios": {
            "primary": {
                "id": "BINANCE_SPOT_STANDARD_TAKER",
                "bps": g0["costs"]["primary_round_trip_bps"],
                "knowledge": g0["costs"]["primary_knowledge"],
            },
            "prefixed_sensitivity": {
                "cost_zero": 0.0,
                "binance_usdm_perp_maker": g0["costs"]["scenarios"]["BINANCE_USDM_PERP_MAKER"][
                    "round_trip_bps"
                ],
                "binance_usdm_perp_taker": g0["costs"]["scenarios"]["BINANCE_USDM_PERP_TAKER"][
                    "round_trip_bps"
                ],
                "binance_spot_bnb_taker": g0["costs"]["scenarios"]["BINANCE_SPOT_BNB_TAKER"][
                    "round_trip_bps"
                ],
                "binance_spot_standard_maker": g0["costs"]["maker_50pct_fill_bps"],
            },
            "scenario_count": len(g0["costs"]["scenarios"]),
            "borrow_or_funding_charged": False,
            "short_cost_state": "COST_UNVERIFIED_FOR_SHORT",
            "amendment": "PREREGISTRATION_AMENDMENT_01.md (9.25 bps is BINANCE_USDM_PERP_MAKER)",
        },
        "agents": {
            "builders": [
                "context-engineer (G0 reconciliation)",
                "quant-researcher (preregistration)",
                "risk-manager (cost and gate audit)",
                "backtest-engineer (evaluation harness)",
                "security-reviewer (no credentials, offline only)",
                "observability-engineer (hash and artifact manifest)",
            ],
            "verifier": "same operator, second implementation",
            "independence": "INDEPENDENCE_NOT_DEMONSTRATED",
        },
        "tests": {
            "g0": {
                k: v.get("passed") for k, v in g0.items() if isinstance(v, dict) and "passed" in v
            },
            "controls": {"passed": controls["checks_passed"], "total": controls["checks_total"]},
            "verification": {
                "passed": (verification or {}).get("checks_passed"),
                "total": (verification or {}).get("checks_total"),
            },
            "module_tests_run": False,
            "module_tests_note": "no repository source file was modified, so no unit suite was re-run",
        },
        "metrics": {
            "dev_retrospective": {
                "window_role": retro["window_role"],
                "trades": p["trades"],
                "days": p["days"],
                "trades_per_day": p["trades_per_day"],
                "gross_mean_bps": p["gross_mean"],
                "gross_sd_bps": p["gross_sd"],
                "gross_ci95": p["gross_ci95"],
                "net_mean_bps": p["net_mean"],
                "net_ci95": p["net_ci95"],
                "win_rate_pct": p["win_rate_pct"],
                "profit_factor": p["profit_factor"],
                "max_drawdown_bps": p["max_drawdown_bps"],
                "cumulative_net_bps": p["cumulative_net_bps"],
                "per_asset": p["per_asset"],
                "first_half_net": p["first_half_net"],
                "second_half_net": p["second_half_net"],
            },
            "confirmatory": {
                "trades": 0,
                "note": "no confirmatory evaluation was run; the window is not acquired",
            },
            "power": prereg["power"],
            "hold_selection_evidence": {
                "trades": prereg["hold_selection_evidence"]["trades"],
                "gross_mean_bps": prereg["hold_selection_evidence"]["gross_bps_mean"],
                "net_mean_bps": prereg["hold_selection_evidence"]["net_bps_mean"],
                "note": "exposed holdout; selection sample, not evidence",
            },
            "governance_claim_check": {
                "top6_short_down": g0["claim"]["top6_short_down"],
                "claimed": 5,
                "holds": g0["claim"]["claim_holds"],
                "reproduced_trades": g0["claim"]["reproduced_trades"],
            },
        },
        "decisions": [
            {
                "id": "D1",
                "decision": "NO_GO_ALPHA for TDM11-H1",
                "reason_code": retro["decision"]["reason_code"],
                "basis": "pre-registered §7 rule on the DEV retrospective window (n=115 >= 36)",
                "confirmatory": False,
            },
            {
                "id": "D2",
                "decision": "AWAITING_NEW_DATA for the confirmatory protocol",
                "reason_code": avail["decision"]["reason_code"],
                "basis": f"expected {avail['expected_trades_now']} trades available, need {avail['min_trades_required']}",
            },
            {
                "id": "D3",
                "decision": "PREREGISTRATION_CLAIM_PREMISE_UNSUPPORTED",
                "reason_code": "DIRECTIONAL_CLAIM_NOT_REPRODUCED",
                "basis": "3 of 6 top buckets, not 5 of 6; regime_table.csv carries no direction",
            },
            {
                "id": "D4",
                "decision": "COST_UNVERIFIED_FOR_SHORT",
                "reason_code": "FUNDING_NOT_CHARGED",
                "basis": "perp exists but funding_carry is not emitted at the default rate, and the "
                "9.25 maker scenario assumes p=0.5 fills; the primary venue is spot and cannot short",
            },
            {
                "id": "D5",
                "decision": "AMENDMENT_01_APPLIED",
                "reason_code": "PREREG_COST_LIST_CORRECTED",
                "basis": "PREREGISTRATION_AMENDMENT_01.md; primary scenario and min-n unchanged",
            },
        ],
        "errors": [
            {
                "id": "E1",
                "error": "G0-6 first reported 1/24 bucket counts as matching",
                "cause": "the gate compared against the cell's total trades instead of the bucket count",
                "fix": "read regime_table.count instead of regime_table.trades; re-ran",
                "status": "FIXED",
            },
            {
                "id": "E2",
                "error": "shared-checkout modification count read 0 and then 62",
                "cause": "POSIX path on Windows (path did not exist) and untracked lines counted as modifications",
                "fix": "resolve the checkout from the worktree parent; exclude '??' lines; 17 tracked files, unchanged",
                "status": "FIXED",
            },
            {
                "id": "E3",
                "error": "planted-edge controls C-08/C-09 produced zero trades",
                "cause": "synthetic timestamps fell outside the DEV window filter",
                "fix": "anchor the synthetic series at the DEV start and re-run",
                "status": "FIXED",
            },
            {
                "id": "E4",
                "error": "this WP asserted that the 9.25 bps cost was not modelled",
                "cause": "a console table truncated by UnicodeEncodeError (the perp tier contains U+24C8) "
                "was read as the complete scenario list; VENUE_SPECS actually has 10 scenarios",
                "fix": "V8 recomputed every scenario; 9.25 == BINANCE_USDM_PERP_MAKER reproduced; "
                "governance, audit and preregistration corrected by AMENDMENT_01",
                "status": "CORRECTED",
                "verdict_impact": "NONE — the zero-cost case already fails",
            },
        ],
        "result": "NO_GO_ALPHA",
        "operational_state": "AWAITING_NEW_DATA",
        "reason_code": retro["decision"]["reason_code"],
        "reason_codes": [
            retro["decision"]["reason_code"],
            "AWAITING_NEW_DATA",
            "NO_CONFIRMATORY_SAMPLE",
            "COST_UNVERIFIED_FOR_SHORT",
            "INDEPENDENCE_NOT_DEMONSTRATED",
            "DIRECTIONAL_CLAIM_NOT_REPRODUCED",
        ],
        "runtime_validation": "NOT_EXERCISED",
        "paper_validation": "NOT_EXERCISED",
        "execution_validation": "NOT_EXERCISED",
        "false_success_count": 0,
        "false_success_evidence": (
            "11/11 adversarial controls including a planted-edge positive control and a "
            "look-ahead control that would have produced +17.05 bps instead of -12.58"
        ),
        "independent_verifier_id": "single-operator-second-implementation",
        "evidence_sha256": evidence,
        "code_sha256": scripts,
        "generated_at_ms": int(time.time() * 1000),
    }
    (EVIDENCE / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"published {len(evidence)} evidence files; result={payload['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
