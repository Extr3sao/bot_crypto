"""Track H — fingerprint determinism proof for ALPHA-DATA-ADMISSION-01.

PROVES (not states):
1. Two independent normalizations of the REAL raw sample produce identical
   dataset fingerprints (run A == run B).
2. A one-record synthetic perturbation changes the fingerprint (C != A),
   without touching the real raw dataset.
3. Fingerprint is independent of record input order (canonical sort inside).

Emits docs/external-audit-01/data-admission-01/FINGERPRINT_DETERMINISM_REPORT.json.

DATA-ONLY: no signals, no performance metrics, no alpha artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

from trading_bot.research.data_contracts import SCHEMA_VERSION
from trading_bot.research.data_quality import (
    NORMALIZER_VERSION,
    fingerprint_open_interest,
    normalize_open_interest,
)
from trading_bot.research.source_readers import read_metrics_zip

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "binance_um" / "metrics" / "BTCUSDT"
OUT = (
    REPO
    / "docs"
    / "external-audit-01"
    / "data-admission-01"
    / "FINGERPRINT_DETERMINISM_REPORT.json"
)


def load_real_records():
    records = []
    days = sorted(p.name for p in RAW.glob("BTCUSDT-metrics-2026-09-0*.zip"))
    for name in days:
        records.extend(read_metrics_zip(RAW / name, "BTCUSDT"))
    return records


def main() -> None:
    records = load_real_records()

    # Run A
    stats_a = normalize_open_interest(records, decision_time_ms=2**62)
    fp_a = fingerprint_open_interest(
        records,
        asset="BTCUSDT",
        time_range_ms=(stats_a["time_min_ms"] or 0, stats_a["time_max_ms"] or 0),
        schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        source_file_hashes=sorted(p.name for p in RAW.glob("*.zip")),
    )

    # Run B: independent re-read + re-normalization
    records_b = load_real_records()
    stats_b = normalize_open_interest(records_b, decision_time_ms=2**62)
    fp_b = fingerprint_open_interest(
        records_b,
        asset="BTCUSDT",
        time_range_ms=(stats_b["time_min_ms"] or 0, stats_b["time_max_ms"] or 0),
        schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        source_file_hashes=sorted(p.name for p in RAW.glob("*.zip")),
    )

    # Run C: one-record synthetic perturbation (real raw files untouched)
    import dataclasses

    records_c = list(records)
    target_idx = len(records_c) // 2
    target = records_c[target_idx]
    original_value = target.open_interest_contracts
    records_c[target_idx] = dataclasses.replace(
        target, open_interest_contracts=original_value + 1.0
    )
    stats_c = normalize_open_interest(records_c, decision_time_ms=2**62)
    fp_c = fingerprint_open_interest(
        records_c,
        asset="BTCUSDT",
        time_range_ms=(stats_c["time_min_ms"] or 0, stats_c["time_max_ms"] or 0),
        schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        source_file_hashes=sorted(p.name for p in RAW.glob("*.zip")),
    )

    # Run D: same records, shuffled input order -> fingerprint must not change
    records_d = list(reversed(records))
    stats_d = normalize_open_interest(records_d, decision_time_ms=2**62)
    fp_d = fingerprint_open_interest(
        records_d,
        asset="BTCUSDT",
        time_range_ms=(stats_d["time_min_ms"] or 0, stats_d["time_max_ms"] or 0),
        schema_version=SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        source_file_hashes=sorted(p.name for p in RAW.glob("*.zip")),
    )

    report = {
        "checkpoint": "ALPHA-DATA-ADMISSION-01",
        "track": "H",
        "dataset": "open_interest sample BTCUSDT 2026-09-01..07 (21 files incl. ETH/SOL window; this proof uses BTCUSDT subset of 7 files)",
        "records_in_proof": len(records),
        "run_A_fingerprint": fp_a,
        "run_B_fingerprint": fp_b,
        "run_C_fingerprint": fp_c,
        "run_D_fingerprint_order_reversed": fp_d,
        "determinism_A_equals_B": fp_a == fp_b,
        "sensitivity_C_differs_from_A": fp_c != fp_a,
        "order_independence_D_equals_A": fp_d == fp_a,
        "perturbation": {
            "record_index": len(records) // 2,
            "method": "dataclasses.replace (records are frozen dataclasses; original list untouched)",
            "field": "open_interest_contracts",
            "original_value": original_value,
            "perturbed_value": original_value + 1.0,
            "real_raw_files_modified": False,
        },
        "conclusion": "PASS" if (fp_a == fp_b and fp_c != fp_a and fp_d == fp_a) else "FAIL",
        "normalizer_version": NORMALIZER_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "determinism_A_equals_B",
                    "sensitivity_C_differs_from_A",
                    "order_independence_D_equals_A",
                    "conclusion",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
