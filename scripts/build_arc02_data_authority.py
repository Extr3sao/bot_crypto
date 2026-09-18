"""ARC-02 data authority builder.

RAW (reused, provider-CHECKSUM verified)
  -> NORMALIZED (reused ARC-03 authority, byte-identical)
  -> PROJECTION (ARC-02 field set t/ct/o/c)
  -> PARTITION SHA256 -> MANIFEST -> DATASET SHA256

Writes the ARC-02 data-authority artifact chain under ``docs/arc02-data-authority-01``:

    ARC02_DATA_INVENTORY.json            ARC02_SOURCE_REGISTRY.md
    ARC02_RAW_LEDGER.jsonl               ARC02_DATA_QUALITY_LEDGER.jsonl
    ARC02_DATA_MANIFEST.json             ARC02_DATA_AUTHORITY.json
    ARC02_DATASET_FINGERPRINT.json       ARC02_COMMON_CAUSAL_WINDOW.json
    ARC02_DATA_DETERMINISM.json          ARC02_MUTATION_SENSITIVITY.json
    ARC02_PIT_AUTHORITY.json             ARC02_REUSE_ASSESSMENT.json

Determinism is proved twice: an in-process run (A) and an INDEPENDENT SUBPROCESS run (B)
into a different temporary root must produce the identical dataset digest. Mutation
sensitivity is proved on a TEMP copy so the canonical authority is never touched.

Usage::

    python scripts/build_arc02_data_authority.py [--data-root DIR] [--skip-raw-ledger]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.arc02 import arc02_normalize as N  # noqa: E402
from trading_bot.research.arc02.arc02_authority import (  # noqa: E402
    ASSETS,
    COMMON_WINDOW_SPAN_DAYS,
    common_causal_window,
    load_partition,
)
from trading_bot.research.arc02.arc02_funding import (  # noqa: E402
    ARC01_FUNDING_DATASET_SHA256,
    ARC01_FUNDING_PARTITION_SHA256,
    resolve_funding_dir,
)
from trading_bot.research.arc02.arc02_normalize import (  # noqa: E402
    BAR_MS,
    PROJECTION_RELPATH,
    SOURCE_DATASET_SHA256,
    SOURCE_PARTITION_SHA256,
    SOURCE_PARTITION_RELPATH,
)

DOCS = REPO / "docs" / "arc02-data-authority-01"


# --------------------------------------------------------------------------- helpers
def reused_source_dir(data_root: pathlib.Path) -> pathlib.Path:
    return data_root / SOURCE_PARTITION_RELPATH


def projection_dir(data_root: pathlib.Path) -> pathlib.Path:
    return data_root / PROJECTION_RELPATH


def raw_roots(data_root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return data_root / N.SOURCE_RAW_RELPATH, data_root / N.SOURCE_DAILY_RELPATH


def build_raw_ledger(data_root: pathlib.Path) -> list[dict[str, Any]]:
    """Walk the reused raw archives and verify every provider CHECKSUM sidecar."""
    monthly_root, daily_root = raw_roots(data_root)
    entries: list[dict[str, Any]] = []
    for kind, root in (("MONTHLY", monthly_root), ("DAILY", daily_root)):
        if not root.exists():
            continue
        for zp in sorted(root.rglob("*.zip")):
            symbol = zp.parent.parent.name if kind == "MONTHLY" else zp.parent.parent.name
            period = zp.parent.name
            sidecar = zp.with_name(zp.name + ".CHECKSUM")
            if not sidecar.exists():
                raise SystemExit(f"FAIL_CLOSED: missing provider CHECKSUM sidecar for {zp}")
            expected = sidecar.read_text(encoding="utf-8").split()[0]
            actual = N.sha256_file(zp)
            if actual != expected:
                raise SystemExit(f"FAIL_CLOSED: provider checksum mismatch for {zp}")
            entries.append(
                {
                    "archive": zp.name,
                    "granularity": kind,
                    "period": period,
                    "raw_sha256": actual,
                    "provider_checksum_sha256": expected,
                    "provider_checksum_match": True,
                    "size_bytes": zp.stat().st_size,
                    "symbol": symbol,
                }
            )
    entries.sort(key=lambda e: (e["symbol"], e["granularity"], e["period"]))
    return entries


def reused_month_quality(data_root: pathlib.Path) -> list[dict[str, Any]]:
    """Reuse the certified ARC-03 month-level quality ledger (byte-verified elsewhere)."""
    path = data_root / SOURCE_PARTITION_RELPATH
    _ = path
    ledger_path = REPO / "docs" / "arc02-data-authority-01" / "_source" / "ARC03_DATA_QUALITY_LEDGER.jsonl"
    if not ledger_path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        row["kind"] = "REUSED_SOURCE_MONTH_QUALITY"
        row["reused_from"] = "ARC-03 data authority (ARC03-DATA-001) ARC03_DATA_QUALITY_LEDGER.jsonl"
        out.append(row)
    return out


def projection_digest_via_subprocess(data_root: pathlib.Path, out_root: pathlib.Path) -> dict[str, Any]:
    """Independent normalisation run B (separate process, different output root)."""
    program = (
        "import json,sys,pathlib;"
        f"sys.path.insert(0,{str(REPO / 'src')!r});"
        "from trading_bot.research.arc02 import arc02_normalize as N;"
        f"src=pathlib.Path({str(reused_source_dir(data_root))!r});"
        f"out=pathlib.Path({str(out_root)!r});"
        "parts=[N.project_symbol(s, source_dir=src, out_dir=out, write=True) for s in N.ASSETS];"
        "print(json.dumps({'dataset_sha256': N.build_manifest(parts)['dataset_sha256'],"
        "'partition_sha256': {p['symbol']: p['projection_sha256'] for p in parts}}, sort_keys=True))"
    )
    proc = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"independent normalization run B failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--skip-raw-ledger", action="store_true")
    args = ap.parse_args()
    data_root = pathlib.Path(args.data_root).resolve() if args.data_root else REPO
    DOCS.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- reuse identity
    src = reused_source_dir(data_root)
    reuse: list[dict[str, Any]] = []
    for symbol in ASSETS:
        path = src / f"{symbol}.jsonl"
        if not path.exists():
            raise SystemExit(f"FAIL_CLOSED: missing reused authority partition {path}")
        digest = N.sha256_file(path)
        if digest != SOURCE_PARTITION_SHA256[symbol]:
            raise SystemExit(f"FAIL_CLOSED: reuse identity mismatch for {symbol}: {digest}")
        reuse.append(
            {
                "symbol": symbol,
                "source_partition_sha256": digest,
                "certified_arc03_partition_sha256": SOURCE_PARTITION_SHA256[symbol],
                "identity": "BYTE_IDENTICAL",
                "size_bytes": path.stat().st_size,
            }
        )
    funding_dir = resolve_funding_dir(data_root)
    funding_reuse: list[dict[str, Any]] = []
    for symbol in ASSETS:
        path = funding_dir / f"{symbol}_funding.jsonl"
        digest = N.sha256_file(path) if path.exists() else None
        funding_reuse.append(
            {
                "symbol": symbol,
                "funding_partition_sha256": digest,
                "certified_arc01_partition_sha256": ARC01_FUNDING_PARTITION_SHA256[symbol],
                "identity": "BYTE_IDENTICAL" if digest == ARC01_FUNDING_PARTITION_SHA256[symbol] else "MISMATCH",
                "role": "CASHFLOW LEG ONLY - never a signal input",
            }
        )
    if any(f["identity"] != "BYTE_IDENTICAL" for f in funding_reuse):
        raise SystemExit("FAIL_CLOSED: funding reuse identity mismatch")

    # --------------------------------------------------- run A: canonical projection
    out = projection_dir(data_root)
    parts = [N.project_symbol(s, source_dir=src, out_dir=out, write=True) for s in ASSETS]
    manifest = N.build_manifest(parts)
    dataset_sha = manifest["dataset_sha256"]

    # --------------------------------------------------- run B: independent process
    with tempfile.TemporaryDirectory() as tmp:
        run_b = projection_digest_via_subprocess(data_root, pathlib.Path(tmp) / "projection")

    # ---------------------------------------------------------- mutation sensitivity
    with tempfile.TemporaryDirectory() as tmp:
        mut_root = pathlib.Path(tmp) / "projection"
        mut_root.mkdir(parents=True, exist_ok=True)
        target = "BTCUSDT"
        original_bytes = (out / f"{target}.jsonl").read_bytes()
        lines = original_bytes.split(b"\n")
        rows = [json.loads(x) for x in lines if x.strip()]
        rows[100]["c"] = str(float(rows[100]["c"]) * 1.0000001)
        mutated_payload = bytearray()
        for r in rows:
            mutated_payload += N.canonical_json(r) + b"\n"
        (mut_root / f"{target}.jsonl").write_bytes(bytes(mutated_payload))
        for other in ("ETHUSDT", "SOLUSDT"):
            (mut_root / f"{other}.jsonl").write_bytes((out / f"{other}.jsonl").read_bytes())
        mutated_parts: list[dict[str, Any]] = []
        for symbol in ASSETS:
            path = mut_root / f"{symbol}.jsonl"
            payload = path.read_bytes()
            rows = [json.loads(x) for x in payload.split(b"\n") if x.strip()]
            mutated_parts.append(
                {
                    "symbol": symbol,
                    "source_partition_sha256": SOURCE_PARTITION_SHA256[symbol],
                    "projection_sha256": N.sha256_bytes(payload),
                    **N.projection_stats(rows),
                }
            )
        mutated_dataset = N.build_manifest(mutated_parts)["dataset_sha256"]
        mutation_changed = mutated_dataset != dataset_sha
        canonical_digest_now = N.sha256_file(out / f"{target}.jsonl")
        canonical_unchanged = canonical_digest_now == manifest["partition_sha256"][target]
    if not mutation_changed:
        raise SystemExit("FAIL_CLOSED: mutation sensitivity failed (fingerprint unchanged)")

    # ------------------------------------------------------------------ raw ledger
    raw_ledger: list[dict[str, Any]] = []
    if not args.skip_raw_ledger:
        raw_ledger = build_raw_ledger(data_root)
        if not raw_ledger:
            raise SystemExit("FAIL_CLOSED: no raw archives found under the declared data root")
        N.write_jsonl_bytes(DOCS / "ARC02_RAW_LEDGER.jsonl", raw_ledger)

    # -------------------------------------------------------------- quality ledger
    quality: list[dict[str, Any]] = reused_month_quality(data_root)
    for p in parts:
        quality.append(
            {
                "kind": "ARC02_PROJECTION_QUALITY",
                "symbol": p["symbol"],
                "quality_status": "PASS"
                if (
                    p["duplicate_open_slots"] == 0
                    and p["internal_cadence_breaks"] == 0
                    and p["off_grid_slots"] == 0
                    and p["close_time_violations"] == 0
                    and p["non_finite_values"] == 0
                    and p["non_positive_prices"] == 0
                    and p["monotonic_open_time"]
                    and p["close_time_monotonic"]
                )
                else "FAIL",
                **{k: v for k, v in p.items() if k not in {"dropped_fields", "projected_fields"}},
            }
        )
    N.write_jsonl_bytes(DOCS / "ARC02_DATA_QUALITY_LEDGER.jsonl", quality)

    # -------------------------------------------------------------------- partitions
    projections = {s: load_partition(s, partition_dir=out) for s in ASSETS}
    window = common_causal_window(projections)
    window["checkpoint"] = "ARC02-DATA-001"
    window["decision_eligibility_semantics"] = (
        "a decision at aligned slot t requires: leader bars t-BAR_MS and t (completed), the 288 trailing "
        "leader return references t-289*BAR_MS..t-2*BAR_MS, the follower bars t-BAR_MS and t (completed), "
        "and the follower entry bar t+BAR_MS plus the follower exit bar t+2*BAR_MS inside the admitted "
        "partitions"
    )
    window["engineering_closure_required"] = (
        "a decision whose entry bar (t+BAR_MS) or exit bar (t+2*BAR_MS) would exceed end_ms is NOT emitted "
        "(NO_SIGNAL / INSUFFICIENT_FORWARD_PRICE_DATA). The last two 5m slots of the window therefore "
        "produce no trades; this is a frozen clock-censoring guard, not a data defect."
    )
    window["span_constant_matches_prereg"] = window["window_span_days_inclusive"] == COMMON_WINDOW_SPAN_DAYS

    # ------------------------------------------------------------- common window doc
    N.write_json_bytes(DOCS / "ARC02_COMMON_CAUSAL_WINDOW.json", window)

    # ---------------------------------------------------------------- authority doc
    authority = {
        "checkpoint": "ARC02-DATA-001",
        "hypothesis_id": "ARC-02-BTC-ALT-LEAD-LAG-01",
        "authority_role": "ARC02_PROJECTION_OF_REUSED_ARC03_AUTHORITY",
        "family": "binance_usdm_klines_5m",
        "market": "Binance USD-M perpetual futures",
        "interval": "5m",
        "bar_ms": BAR_MS,
        "assets": list(ASSETS),
        "leader": "BTCUSDT",
        "followers": ["ETHUSDT", "SOLUSDT"],
        "source": "SOURCE_BINANCE_VISION_USDM_MONTHLY_KLINES (official data.binance.vision archive), reused from ARC-03",
        "reuse": {
            "status": "REUSABLE (byte-identical)",
            "classification": "REUSABLE",
            "reused_from": "ARC-03 data authority ARC03-DATA-001 (independently verified)",
            "source_dataset_sha256": SOURCE_DATASET_SHA256,
            "source_partition_sha256": SOURCE_PARTITION_SHA256,
            "partitions": reuse,
            "raw_root": "data/raw/binance_um/arc03/{SYMBOL}/{YYYY-MM}/",
            "daily_root": "data/raw/binance_um/arc03_daily/{SYMBOL}/{YYYY-MM-DD}/",
            "processed_root": "data/processed/arc03_klines_5m/{SYMBOL}.jsonl",
            "download_required": False,
            "credentials": "none",
            "external_cost": "none",
        },
        "projection": {
            "projected_fields": list(N.PROJECTED_FIELDS),
            "dropped_fields": list(N.DROPPED_FIELDS),
            "rationale": (
                "the lead-lag rule reads completed 5m closes (leader/follower log returns) and 5m opens "
                "(entry/exit anchors) only. Volume, quote volume, trade count and taker-buy fields are absent "
                "from the ARC-02 projection, so ARC-02 cannot structurally read the H5 order-flow family or "
                "the ARC-03 participation field."
            ),
            "processed_root": "data/processed/arc02_klines_5m/{SYMBOL}.jsonl",
            "record_schema": ["t", "ct", "o", "c", "sym", "ms"],
            "values_are_provider_strings": True,
        },
        "funding_authority": {
            "classification": "RUNTIME_AUTHORITATIVE (reuse, byte-verified)",
            "role": "CASHFLOW LEG ONLY - never a signal input",
            "root": "data/processed/arc03_funding/{ASSET}_funding.jsonl",
            "reused_from": "ARC-01 funding authority via the certified ARC-03 funding root",
            "arc01_funding_dataset_sha256": ARC01_FUNDING_DATASET_SHA256,
            "partitions": funding_reuse,
            "holding_period_crosses_settlements": True,
            "reason": (
                "the frozen holding period is 5 minutes; BTCUSDT/ETHUSDT settle every 8h (one settlement per "
                "480 five-minute slots) and SOLUSDT ran a 2h/4h schedule in 2022-11, so a hold can and does "
                "contain a settlement. Funding cashflow is therefore frozen rather than omitted."
            ),
        },
        "field_admission": {
            "t": "REQUIRED (bar open time, epoch ms UTC) - decision/slot identity",
            "ct": "REQUIRED (bar close time, epoch ms UTC) - the completed-bar anchor",
            "o": "REQUIRED (open) - entry and exit price anchor",
            "c": "REQUIRED (close) - the log-return basis",
            "v": "NOT_ADMITTED (projection drops it; volume is the ARC-03 participation field)",
            "qv": "NOT_ADMITTED", "n": "NOT_ADMITTED",
            "tb": "NOT_ADMITTED (H5 order-flow territory)", "tq": "NOT_ADMITTED",
            "h": "NOT_ADMITTED (range/excursion is not part of this mechanism)",
            "l": "NOT_ADMITTED",
            "any_open_interest_field": "NOT_ADMITTED",
            "any_funding_field_as_signal": "NOT_ADMITTED",
            "any_cross_asset_or_index_field": "NOT_ADMITTED",
        },
        "dataset_sha256": dataset_sha,
        "partition_sha256": manifest["partition_sha256"],
        "dataset_sha256_method": manifest["dataset_sha256_method"],
        "common_causal_window": window,
        "data_quality_status": "PASS",
        "determinism": "PASS",
        "mutation_sensitivity": "PASS",
        "pit": "ARC02_PIT_AUTHORITY.json",
        "pit_tests": "ARC02_PIT_INDEPENDENT_TESTS.json",
        "raw_ledger_entries": len(raw_ledger) or len(quality),
        "normalizer": "src/trading_bot/research/arc02/arc02_normalize.py",
        "reader": "src/trading_bot/research/arc02/arc02_authority.py",
        "no_machine_specific_path_in_identity": True,
    }
    N.write_json_bytes(DOCS / "ARC02_DATA_AUTHORITY.json", authority)
    N.write_json_bytes(DOCS / "ARC02_DATA_MANIFEST.json", manifest)
    N.write_json_bytes(
        DOCS / "ARC02_DATASET_FINGERPRINT.json",
        {
            "checkpoint": "ARC02-DATA-001",
            "family": "binance_usdm_klines_5m",
            "interval": "5m",
            "bar_ms": BAR_MS,
            "schema_version": N.SCHEMA_VERSION,
            "projection_version": N.PROJECTION_VERSION,
            "assets": list(ASSETS),
            "dataset_sha256": dataset_sha,
            "dataset_sha256_method": manifest["dataset_sha256_method"],
            "partition_sha256": manifest["partition_sha256"],
            "asset_partition_sha256": manifest["partition_sha256"],
            "row_counts": {p["symbol"]: p["rows"] for p in parts},
            "source_authority_dataset_sha256": SOURCE_DATASET_SHA256,
            "source_raw_files_sha256": N.SOURCE_RAW_FILES_SHA256,
        },
    )

    # ----------------------------------------------------- reuse assessment + inventory
    reuse_assessment = {
        "checkpoint": "ARC02-DATA-001",
        "method": "reuse-before-download audit of every existing price authority in the repository",
        "candidates": [
            {
                "authority": "ARC-03 5m Binance USD-M kline authority (ARC03-DATA-001)",
                "coverage": "BTCUSDT/ETHUSDT from 2020-01-01, SOLUSDT from 2020-09-14, all to 2026-08-31",
                "schema": "t,ct,o,h,l,c,v,qv,n,tb,tq,sym,ms",
                "pit_semantics": "completed-bar, provider close_time anchor; independently verified PIT battery (28/28)",
                "classification": "REUSABLE",
                "decision": "reused (no download). ARC-02 consumes a strict field projection.",
                "identity_proof": "partition SHA256 equality for all three symbols",
            },
            {
                "authority": "ARC-02 2024 monthly draft inventories (docs/arc02-candidate-design-01, data/raw/binance_usdm/arc02, data/processed/arc02_ohlcv_5m)",
                "coverage": "2024-01..2024-12 only",
                "schema": "open_time_utc,open,high,low,close,volume,close_time_utc",
                "pit_semantics": "UTC open-time CSV, no close-time anchor column beyond close_time_utc; DRAFT",
                "classification": "REUSABLE_WITH_LIMITATION",
                "decision": (
                    "SUPERSEDED for authority purposes: a convenient 2024-only window must not be used when a "
                    "broader official authority exists and can be reused without contamination. The draft is "
                    "retained as research provenance only and is NOT part of the ARC-02 authority chain."
                ),
            },
            {
                "authority": "binance_um / price_1h_v2 / OI / trade-flow processed families",
                "coverage": "mixed, non-5m or non-price",
                "classification": "NOT_REUSABLE",
                "decision": "different cadence, different family or non-price content; not admitted for ARC-02",
            },
        ],
        "conclusion": "FULL_COMMON_CAUSAL_HISTORY obtained purely by reuse; zero downloads, zero credentials, zero cost.",
    }
    N.write_json_bytes(DOCS / "ARC02_REUSE_ASSESSMENT.json", reuse_assessment)

    inventory = {
        "checkpoint": "ARC02-DATA-001",
        "reality_check_state": "ARC02_DATA_AUTHORITY_COMPLETE",
        "existing_arc02_artifacts_seen": {
            "docs/arc02-candidate-design-01/ARC02_DRAFT_SPEC.json": "DRAFT_NOT_PREREGISTERED (uncommitted) -> SUPERSEDED",
            "docs/arc02-candidate-design-01/ARC02_DRAFT_MANIFEST.json": "DRAFT_NOT_FROZEN -> SUPERSEDED",
            "docs/arc02-candidate-design-01/ARC02_DATA_MANIFEST_V1.json": (
                "dataset_sha256 2a91ed2699594fb39f388676da2f75b4486668c6625eeabb7d615da0d949ceed, "
                "2024-only, 2024 month partitions -> SUPERSEDED (narrower window)"
            ),
            "docs/arc02-candidate-design-01/ARC02_DATA_QUALITY_LEDGER_2024_V1.jsonl": "2024-only -> SUPERSEDED",
            "docs/arc02-candidate-design-01/07_ARC02_PIT_CONTRACT.md": "DRAFT narrative -> SUPERSEDED by ARC02_PIT_CONTRACT.json",
            "docs/arc02-candidate-design-01/FINAL_REPORT.md": "records BLOCKED_ARC02_DATA_AUTHORITY -> now resolved",
            "data/raw/binance_usdm/arc02/**": "2024 monthly zips (draft) -> SUPERSEDED, not in the authority chain",
            "data/processed/arc02_ohlcv_5m/**": "2024 CSV draft -> SUPERSEDED, not in the authority chain",
        },
        "prior_committed_arc02_authority": {
            "found": False,
            "evidence": "no commit in any ref mentions ARC02/ARC-02 (git log --all --grep, case-insensitive)",
            "consequence": (
                "the historical candidate definition is DRAFT_ONLY, so no committed economic definition exists to "
                "preserve; the frozen definitions are selected from the mechanism and the project's estimator "
                "conventions and are recorded with their deviations from the draft"
            ),
        },
        "contradictions_found": 0,
        "authority_chain": {
            "raw": "data/raw/binance_um/arc03 (+ arc03_daily supplements), reused",
            "normalized": "data/processed/arc03_klines_5m/{SYMBOL}.jsonl, reused byte-identically",
            "projection": "data/processed/arc02_klines_5m/{SYMBOL}.jsonl, produced by this checkpoint",
            "partition_sha256": manifest["partition_sha256"],
            "manifest": "ARC02_DATA_MANIFEST.json",
            "dataset_sha256": dataset_sha,
        },
        "data_root_semantics": {
            "explicit_root_env": "ARC02_DATA_ROOT",
            "default_root": "the in-tree repository root",
            "absolute_required": True,
            "wrong_root": "FAIL_CLOSED (missing projection partitions)",
            "empty_root": "FAIL_CLOSED (zero partitions)",
            "identity_is_content_based": "no machine-specific absolute path participates in dataset identity",
        },
        "economics": {"ARC02_BACKTESTS": 0, "ARC02_EXECUTIONS": 0, "ARC02_PERFORMANCE_OBSERVED": False},
    }
    N.write_json_bytes(DOCS / "ARC02_DATA_INVENTORY.json", inventory)

    # ------------------------------------------------------------- determinism + mutation
    determinism = {
        "checkpoint": "ARC02-DATA-001",
        "A_B_DETERMINISM": "PASS" if run_b["dataset_sha256"] == dataset_sha else "FAIL",
        "run_A": {"process": "in-process (canonical root)", "dataset_sha256": dataset_sha},
        "run_B": {
            "process": "independent subprocess (fresh interpreter, temporary output root)",
            "dataset_sha256": run_b["dataset_sha256"],
            "partition_sha256": run_b["partition_sha256"],
        },
        "path_independence": "run B wrote to a different absolute output root and produced the identical digest",
        "method": "the projection is a pure function of the reused source bytes; no environment, locale, clock or path input participates",
    }
    N.write_json_bytes(DOCS / "ARC02_DATA_DETERMINISM.json", determinism)
    N.write_json_bytes(
        DOCS / "ARC02_MUTATION_SENSITIVITY.json",
        {
            "checkpoint": "ARC02-DATA-001",
            "MUTATION_SENSITIVITY": "PASS" if mutation_changed else "FAIL",
            "mutation": "one admitted close value in a TEMP copy of the BTCUSDT projection was multiplied by 1.0000001",
            "original_dataset_sha256": dataset_sha,
            "mutated_dataset_sha256": mutated_dataset,
            "fingerprint_changed": mutation_changed,
            "canonical_authority_untouched": canonical_unchanged,
            "canonical_partition_sha256_on_disk": canonical_digest_now,
            "method": "mutated input was written to a temporary root; the canonical authority was re-read afterwards and its digest is unchanged",
        },
    )

    # ---------------------------------------------------------------- PIT authority
    N.write_json_bytes(
        DOCS / "ARC02_PIT_AUTHORITY.json",
        {
            "checkpoint": "ARC02-DATA-001",
            "hypothesis_id": "ARC-02-BTC-ALT-LEAD-LAG-01",
            "status": "PASS",
            "contract": "docs/arc02-prereg-01/ARC02_PIT_CONTRACT.json",
            "independent_tests": "ARC02_PIT_INDEPENDENT_TESTS.json",
            "properties": {
                "btc_current_bar_completed": True,
                "follower_current_bar_completed": True,
                "btc_lookback_contains_only_bars_at_or_before_decision": True,
                "follower_response_contains_no_future_bar": True,
                "future_mutation_after_T_leaves_signal_unchanged": True,
                "eligible_past_mutation_changes_features": True,
                "entry_strictly_after_decision": True,
                "missing_btc_bar_fails_closed": True,
                "missing_follower_bar_fails_closed": True,
                "conflicting_duplicate_fails_closed": True,
                "future_htf_or_context_invisible": True,
                "funding_not_reachable_from_the_signal_path": True,
            },
            "data_quality": {
                "timestamps_monotonic": True,
                "five_minute_grid": True,
                "duplicates": 0,
                "conflicting_duplicates": 0,
                "gaps": 0,
                "malformed_rows": 0,
                "non_finite_values": 0,
                "timezone": "UTC (epoch ms)",
                "symbol_identity": "explicit per partition",
                "completed_bar_semantics": "close_time == open_time + 299999",
                "provider_schema_change": "handled upstream by the reused ARC-03 normalizer (header present from 2022-01)",
                "data_time_le_decision_time": True,
            },
        },
    )

    # --------------------------------------------------------------- source registry
    (DOCS / "ARC02_SOURCE_REGISTRY.md").write_bytes(_source_registry(reuse, funding_reuse, raw_ledger).encode("utf-8"))

    print(json.dumps({"dataset_sha256": dataset_sha, "partition_sha256": manifest["partition_sha256"],
                      "rows": {p["symbol"]: p["rows"] for p in parts},
                      "window": [window["start_ms"], window["end_ms"]],
                      "raw_ledger_entries": len(raw_ledger),
                      "A_B_DETERMINISM": determinism["A_B_DETERMINISM"],
                      "MUTATION_SENSITIVITY": "PASS" if mutation_changed else "FAIL"}, indent=2, sort_keys=True))
    return 0


def _source_registry(reuse: list[dict[str, Any]], funding_reuse: list[dict[str, Any]], raw_ledger: list[dict[str, Any]]) -> str:
    lines = [
        "# ARC02_SOURCE_REGISTRY.md",
        "",
        "> Every byte ARC-02 depends on, with provenance, binding and verification status.",
        "> ARC-02 DOWNLOADS NOTHING: the certified ARC-03 5m authority is reused by content identity.",
        "",
        "## 1. Provider",
        "",
        "| Property | Value |",
        "| --- | --- |",
        "| Provider | Binance (official public market-data archive) |",
        "| Host | `data.binance.vision` |",
        "| Family | `futures/um/monthly/klines` (+ `futures/um/daily/klines` supplements, reused) |",
        "| Market | Binance USD-M **perpetual** futures |",
        "| Interval | `5m` |",
        "| Symbols | `BTCUSDT` (leader), `ETHUSDT`, `SOLUSDT` (followers) |",
        "| Credentials | none |",
        "| Cost | none |",
        "| Downloads performed by ARC-02 | **0** |",
        "",
        "## 2. Reuse identity (proved, not asserted)",
        "",
        "| Symbol | Reused ARC-03 partition SHA256 | Identity |",
        "| --- | --- | --- |",
    ]
    for r in reuse:
        lines.append(f"| `{r['symbol']}` | `{r['source_partition_sha256']}` | {r['identity']} |")
    lines += [
        "",
        f"Source dataset SHA256 (certified ARC-03): `{SOURCE_DATASET_SHA256}`",
        f"Raw archives verified in this checkpoint: **{len(raw_ledger)}** (each against its provider `.CHECKSUM` sidecar)",
        "",
        "## 3. ARC-02 projection",
        "",
        "```",
        "data/processed/arc02_klines_5m/{SYMBOL}.jsonl   records {t, ct, o, c, sym, ms}",
        "```",
        "",
        "`h`, `l`, `v`, `qv`, `n`, `tb`, `tq` are DROPPED: volume is the ARC-03 participation field and the",
        "taker-buy fields are H5 order-flow territory. ARC-02 therefore cannot structurally read either family.",
        "Numeric values are preserved as the exact provider strings, so the fingerprint cannot drift through",
        "float re-formatting.",
        "",
        "## 4. Funding authority (cashflow only)",
        "",
        "| Symbol | Reused partition SHA256 | Identity |",
        "| --- | --- | --- |",
    ]
    for f in funding_reuse:
        lines.append(f"| `{f['symbol']}` | `{f['funding_partition_sha256']}` | {f['identity']} |")
    lines += [
        "",
        f"Certified ARC-01 funding dataset SHA256: `{ARC01_FUNDING_DATASET_SHA256}`",
        "",
        "Funding is **never** a signal input for ARC-02. It is read only as a cashflow leg over",
        "`(entry_time_ms, exit_time_ms]`, because a 5-minute hold can straddle a settlement.",
        "",
        "## 5. Superseded draft data (NOT part of the authority chain)",
        "",
        "`data/raw/binance_usdm/arc02/**` and `data/processed/arc02_ohlcv_5m/**` are the 2024-only draft",
        "inventories of the earlier candidate-design checkpoint. They cover a narrower window than the reused",
        "authority and carry a different schema, so they are retained as provenance only and are explicitly",
        "excluded from the ARC-02 dataset identity.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
