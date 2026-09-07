"""ADMISSION-FOUNDATION-01 bootstrap: seed registry + pre-register confirmation.

1. Registers the 5 currently certified POC01 runtime strategies as
   LEGACY_PAPER_BASELINE with HONEST evidence (they run certified in PAPER;
   no modern discovery/robustness/CV/WF gates exist — documented, not fabricated).
2. Registers the 3 EDGE-RESEARCH-002 discovery passers as
   DISCOVERY_PASS / CONFIRMATION_BLOCKED (SOL 100%, LONG 100%; no promotion).
3. Pre-registers the CONFIRMATION-PROTOCOL-V2 manifest for those passers with
   a FUTURE window (next complete UTC boundary: 2026-09-08T00:00Z, 14 complete
   UTC days per RFC-CONFIRMATION-PROTOCOL-V2) so that
   manifest_commit_time < window_start < execution_time is provable from git.
4. Seeds the asset admission contract records (XRP/DOGE, no promotion).

Idempotent: identical inputs produce identical hashes/records (G14/G15 style).
LIVE = 0; POC01 untouched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.admission import (
    DOGE_RECORD,
    XRP_RECORD,
    AdmissionState,
    ConfirmationManifest,
    EvidenceRef,
    StrategyRegistry,
    StrategyVersionRecord,
)

OUT = Path("reports/admission-foundation-01")
BASE_COMMIT = "3c274cc"

RUNTIME_STRATEGIES = ("momentum", "trend", "breakout", "mean_reversion", "volatility")

DISCOVERY_PASSERS = (
    {
        "strategy_id": "edge-002-ha-momentum",
        "family": "momentum",
        "config_sha256": "9edb1a21f177eecf",
        "stats": {"trade_count": 51, "net_expectancy": 0.249553, "net_profit_factor": 1.329317},
    },
    {
        "strategy_id": "edge-002-ha-breakout",
        "family": "breakout",
        "config_sha256": "85f271a615414fdd",
        "stats": {"trade_count": 36, "net_expectancy": 0.341706, "net_profit_factor": 1.371249},
    },
    {
        "strategy_id": "edge-002-hf-session-ema",
        "family": "ema_crossover",
        "config_sha256": "ce733e29c94b3639",
        "stats": {"trade_count": 34, "net_expectancy": 0.615557, "net_profit_factor": 1.791153},
    },
)


def git_commit_time() -> str:
    """Timestamp of the current HEAD commit (the manifest-carrying commit)."""
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%cI"], text=True
    ).strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    registry = StrategyRegistry()

    # 1) runtime strategies — honest LEGACY_PAPER_BASELINE
    for fam in RUNTIME_STRATEGIES:
        registry.register(
            StrategyVersionRecord(
                strategy_id=f"poc01-{fam}",
                version="v1",
                family=fam,
                source="POC01_RUNTIME",
                origin="certified multi-agent runtime (pre-registry)",
                assets=("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
                timeframes=("5m",),
                directions=("LONG", "SHORT"),
                config_sha256="PENDING_RETRO_ADMISSION",  # params live in certified runtime; not re-derived here
                code_sha256=BASE_COMMIT,
                created_at=now,
                admission_state=AdmissionState.LEGACY_PAPER_BASELINE,
                confirmation_status="NOT_RUN",
                discovery_status="NOT_RUN",
                robustness_status="NOT_RUN",
                cv_status="NOT_RUN",
                walk_forward_status="NOT_RUN",
                evidence_refs=(
                    EvidenceRef(
                        claim="paper_runtime_certified",
                        source="CERT-DEMO-PAPER-01 (a282fcc) + POC01 30/30 (57f300f lineage)",
                        evidence="runs certified in PAPER via the multi-agent chain",
                        decision="grandfathered LEGACY_PAPER_BASELINE",
                    ),
                ),
                notes=(
                    "Grandfathered: strategy predates the admission registry. It is "
                    "certified to RUN in the frozen POC01 PAPER plane, but has NO "
                    "modern discovery/robustness/CV/walk-forward/confirmation gates. "
                    "Evidence is NOT fabricated; retro-admission may run later "
                    "without touching the frozen campaign."
                ),
            )
        )

    # 2) discovery passers — DISCOVERY_PASS + CONFIRMATION_BLOCKED, no promotion
    for p in DISCOVERY_PASSERS:
        registry.register(
            StrategyVersionRecord(
                strategy_id=p["strategy_id"],
                version="v1",
                family=p["family"],
                source="EDGE-RESEARCH-002",
                origin="pre-registered orthogonal hypothesis execution",
                assets=("SOL/USDT:USDT",),
                timeframes=("5m",),
                directions=("LONG",),  # LONG concentration = 100% (preserved)
                config_sha256=p["config_sha256"],
                code_sha256="065a65f",
                created_at="2026-09-07T05:55:19+00:00",  # discovery results commit time
                admission_state=AdmissionState.DISCOVERY_PASS,
                discovery_status="PASS",
                confirmation_status="BLOCKED_CONFIRMATION_AUTHORITY",
                **p["stats"],
                regime_results={"note": "single-asset LONG discovery; regime metrics in discovery evidence"},
                evidence_refs=(
                    EvidenceRef(
                        claim="discovery_manifest+results",
                        source="feat/edge-research-002@065a65f",
                        evidence="docs/edge-research-002/evidence/DISCOVERY_RESULTS.json + HYPOTHESIS_RESULTS.json",
                        decision="DISCOVERY_PASS (3/36 passers)",
                    ),
                    EvidenceRef(
                        claim="confirmation blocked",
                        source="feat/edge-research-002@a647dfb",
                        evidence="docs/edge-research-002/evidence/CONFIRMATION_AUTHORITY_AUDIT.json",
                        decision="CONFIRMATION_BLOCKED (lock ordering unprovable)",
                    ),
                    EvidenceRef(
                        claim="stability evidence",
                        source="feat/edge-research-002@065a65f",
                        evidence="thirds/halves recorded in DISCOVERY_RESULTS.json",
                        decision="recorded; concentration risk NOT eliminated by pass",
                    ),
                ),
                notes="SOL concentration 100%; LONG concentration 100%; do NOT promote",
            )
        )

    registry.save(OUT / "STRATEGY_REGISTRY.json")

    # 3) Confirmation Protocol V2 — FUTURE window pre-registration
    window_start = "2026-09-08T00:00:00+00:00"  # next complete UTC boundary
    window_end = "2026-09-22T00:00:00+00:00"    # 14 complete UTC days (RFC §4)
    manifest = ConfirmationManifest(
        confirmation_id="CONF-EDGE-002-001",
        strategy_ids=tuple(p["strategy_id"] for p in DISCOVERY_PASSERS),
        created_at=git_commit_time(),  # the commit carrying this manifest
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()[:40],
        protocol_version="CONFIRMATION-PROTOCOL-V2",
        window_start=window_start,
        window_end=window_end,
        expected_bars=14 * 288,
        assets=("SOL/USDT:USDT",),
        timeframes=("5m",),
        data_source="binanceusdm-public (ccxt, no credentials)",
        acceptance_criteria={
            "source": "EDGE-RESEARCH-002 frozen v2 criteria (pre-registered)",
            "min_trades": 30,
            "net_expectancy_r_gt": 0.0,
            "net_pf_gt": 1.0,
            "stability": "thirds and halves sign-consistency",
            "note": "no parameter sweep; no direction change; no asset substitution",
        },
        cost_model_sha256="poc01-canonical-costs (fees entry+exit, slippage both sides)",
        candidate_config_sha256=tuple(p["config_sha256"] for p in DISCOVERY_PASSERS),
        window_status="COMMITTED",
        notes=(
            "Future data only: window starts AFTER this manifest's commit. "
            "R1 confirmation/holdout and EDGE windows are NOT reused. "
            "Single-use consumption guard applies."
        ),
    )
    manifest.verify_future_ordering(manifest_commit_time=manifest.created_at)
    (OUT / "CONFIRMATION_MANIFEST.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )

    # 4) asset contract records (no promotion)
    (OUT / "ASSET_ADMISSION_RECORDS.json").write_text(
        json.dumps(
            {"schema_version": "asset-admission-contract-v1", "records": [XRP_RECORD.to_dict(), DOGE_RECORD.to_dict()]},
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(f"registry: {len(registry.all_records())} records -> {OUT / 'STRATEGY_REGISTRY.json'}")
    print(f"manifest: {manifest.confirmation_id} window {window_start}..{window_end} "
          f"(commit {manifest.created_at} < start: OK)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
