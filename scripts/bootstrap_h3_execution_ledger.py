"""One-time Track A reconstruction: the two historical H3 execution attempts,
recorded into the ResearchExecutionLedger (append-only).

These attempts PRE-DATE the ledger (that gap is DEF-H3-EXEC-001); this script
materializes the forensic reconstruction as ledger rows so the experiment has
durable attempt semantics going forward. Timestamps of the historical events
are carried in the forensics document, not fabricated here — ledger rows are
timestamped at reconstruction time and marked reconstructed=true.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H3_DIR = ROOT / "docs" / "external-audit-01" / "h3-relative-value-01"
LEDGER_DIR = H3_DIR / "execution-ledger"
EXPERIMENT_ID = "H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01"
SPEC_SHA = "90c566993b9cdd6b42b9eac5b482f8a96657728cbfd8c04a2df3567b23848d50"
DATASET_SHA = json.dumps(
    {
        "BTCUSDT_1h.jsonl": "52a79db49893251d74c61bbda0a02948dffcce8b54f486d58ba2af1bb3595f4b",
        "ETHUSDT_1h.jsonl": "2a91389142f9377fc172bbc944003160a0ba3b9de41593a013b9369851684088",
    },
    sort_keys=True,
)
PREREG_COMMIT = "83b3acde3dc4c45f9680ab9be2f0a72eeeddeb41"

from trading_bot.research.execution_ledger import ResearchExecutionLedger  # noqa: E402


def main() -> int:
    existing = ResearchExecutionLedger(LEDGER_DIR, EXPERIMENT_ID)
    summary = existing.experiment_summary()
    if summary["execution_attempts"] > 0:
        print("ledger already bootstrapped; refusing to duplicate")
        return 2

    # ---- attempt 1: crashed during report-table construction (reconstructed) ----
    l1 = ResearchExecutionLedger(LEDGER_DIR, EXPERIMENT_ID)
    assert l1.acquire() == "ACQUIRED"
    a1 = l1.start_attempt(
        spec_sha256=SPEC_SHA,
        dataset_sha256=DATASET_SHA,
        prereg_commit=PREREG_COMMIT,
        code_commit="4ea37b3 (pre-execution; contains the comprehension bug)",
    )
    l1.finish_failed(
        a1.attempt_id,
        "UnboundLocalError in report-table construction (cost_per_trade_R "
        "comprehension) AFTER economic evaluation completed (features, trades, "
        "orthogonality replays, base B1 metrics, prereg sensitivity), BEFORE "
        "classification, marker or result persistence. Reconstruction: "
        "RESULT_COMPUTED_NOT_OBSERVED; no stdout metrics, no marker, no result; "
        "wall time not instrumented (minutes before attempt 2 at 20:16:48Z).",
    )
    l1.release()

    # ---- attempt 2: completed (recovery of attempt 1) ----
    l2 = ResearchExecutionLedger(LEDGER_DIR, EXPERIMENT_ID)
    assert l2.acquire() == "ACQUIRED"
    a2 = l2.start_attempt(
        spec_sha256=SPEC_SHA,
        dataset_sha256=DATASET_SHA,
        prereg_commit=PREREG_COMMIT,
        code_commit="4ea37b3 + uncommitted comprehension fix (committed as 8059ee9)",
        recovery_of_attempt_id=a1.attempt_id,
    )
    l2.finish_completed(a2.attempt_id, H3_DIR / "H3_RESULT.json")
    l2.release()

    final = ResearchExecutionLedger(LEDGER_DIR, EXPERIMENT_ID).experiment_summary()
    (LEDGER_DIR / "SUMMARY.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(json.dumps({k: final[k] for k in ("execution_attempts", "completed_executions", "failed_attempts")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
