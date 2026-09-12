"""P5 — frozen H6 contract snapshot loaded programmatically from frozen authority.

No economic value is computed here. This module only extracts canonical
frozen H6 semantics from the committed SPEC and MANIFEST so later
implementation tracks can compare runtime constants against the frozen spec
(P6 drift guard).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPEC_PATH = Path("docs/external-audit-01/oi-full-history-01/H6_SPEC.json")
MANIFEST_PATH = Path(
    "docs/external-audit-01/oi-full-history-01/H6_MANIFEST.json"
)

EXPECTED_SPEC_SHA256 = (
    "f514fecf42b52d2e1c2946cac9dee94b2570d485cb236b9a6c663f46f5bbf148"
)
EXPECTED_MANIFEST_SHA256 = (
    "345334c3107860a5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc"
)
EXPECTED_DATASET_SHA256 = (
    "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"
)


@dataclass(frozen=True, slots=True)
class FrozenH6Config:
    hypothesis_id: str
    mechanism_name: str
    mechanism_family: str
    mechanism_statement: str
    assets: tuple[str, ...]
    common_window_start: str
    common_window_end: str
    decision_bucket: str
    decision_time_semantics: str
    primary_holding_horizon_hours: int
    entry_timing: str
    exit_timing: str
    stop_invalidation: str
    cooldown: str
    oi_field_whitelist: tuple[str, ...]
    rolling_window_length_hours: int
    rolling_min_observations: int
    rolling_center: str
    rolling_scale_factor: float
    threshold_expansion_z: float
    contraction_uses: str
    mad_zero_semantics: str
    price_direction_rule: str
    cost_total_round_trip_bps: int
    cost_sensitivity_bps: tuple[int, ...]
    funding_policy: str
    funding_materiality_gate_before_promotion: bool
    minimum_per_asset_trades: int
    minimum_pooled_trades: int
    p_sharp_gt_0_min: float
    permutation_p_max: float
    sharpe_ci_excludes_zero: bool
    permutation_seed: int
    permutation_draws: int
    orthogonality_max_abs_daily_correlation: float
    h5_pnl_correlation: str
    pit_oi_rule: str
    pit_price_rule: str
    pit_future_mutation_rule: str
    archive_validity_role: str
    insufficient_sample_policy: str
    pass_requires: tuple[str, ...]
    fail_is_terminal: bool
    spec_sha256: str
    manifest_sha256: str
    dataset_sha256: str
    snapshot_sha256: str
    raw_snapshot: dict[str, Any] = field(repr=False, compare=False)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_h6_snapshot() -> FrozenH6Config:
    spec_sha = _sha256(SPEC_PATH)
    manifest_sha = _sha256(MANIFEST_PATH)
    dataset_sha = _sha256(
        Path(
            "data/processed/oi_full_history/"
            "OI_FULL_HISTORY_DATASET_MANIFEST.json"
        )
    )

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    if spec_sha != EXPECTED_SPEC_SHA256:
        msg = f"H6 spec SHA256 drift: {spec_sha=}"
        raise RuntimeError(msg)
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        msg = f"H6 manifest SHA256 drift: {manifest_sha=}"
        raise RuntimeError(msg)

    feature = spec["feature_transformations"]
    z_feature = next(f for f in feature if f["name"] == "z_oi")
    scaling_raw = z_feature["definition"].split("(")[1].split(")")[0]
    scale_parts = [p.strip() for p in scaling_raw.split("*")]
    if len(scale_parts) != 2 or scale_parts[0] != "1.4826":
        raise RuntimeError("frozen z_oi scale not recognized")
    scale_factor = float(scale_parts[1])

    snapshot = {
        "hypothesis_id": spec["hypothesis_id"],
        "mechanism_name": spec["mechanism"]["name"],
        "mechanism_family": spec["mechanism"]["family"],
        "mechanism_statement": spec["mechanism"]["statement"],
        "assets": tuple(spec["assets"]),
        "common_window_start": spec["common_window_utc"]["start"],
        "common_window_end": spec["common_window_utc"]["end"],
        "decision_bucket": spec["decision_timeframe"]["bucket"],
        "decision_time_semantics": spec["decision_timeframe"][
            "decision_time"
        ],
        "primary_holding_horizon_hours": spec[
            "decision_timeframe"
        ]["primary_holding_horizon_hours"],
        "entry_timing": spec["entry_timing"],
        "exit_timing": spec["exit_timing"],
        "stop_invalidation": spec["stop_invalidation"],
        "cooldown": spec["cooldown"],
        "oi_field_whitelist": tuple(spec["oi_field_whitelist"]),
        "rolling_window_length_hours": spec["rolling_windows"]["z_oi"][
            "length_hours"
        ],
        "rolling_min_observations": spec["rolling_windows"]["z_oi"][
            "min_observations"
        ],
        "rolling_center": spec["rolling_windows"]["z_oi"]["center"],
        "rolling_scale_factor": scale_factor,
        "threshold_expansion_z": spec["threshold_rule"][
            "expansion_condition"
        ].split("+")[-1].strip().rstrip(")"),
        "contraction_uses": spec["threshold_rule"][
            "contraction_condition"
        ],
        "mad_zero_semantics": spec["threshold_rule"]["neutral_or_insufficient"],
        "price_direction_rule": spec["direction_semantics"]["LONG"].split(
            "AND"
        )[0].strip(),
        "cost_total_round_trip_bps": spec["cost_model"][
            "BASE_TOTAL_ROUND_TRIP_COST_BPS"
        ],
        "cost_sensitivity_bps": tuple(spec["cost_model"][
            "COST_SENSITIVITY_BPS"
        ]),
        "funding_policy": spec["funding_accounting"][
            "FUNDING_DISCOVERY_ACCOUNTING"
        ],
        "funding_materiality_gate_before_promotion": spec[
            "funding_accounting"
        ]["funding_materiality_gate_before_promotion"],
        "minimum_per_asset_trades": spec["minimum_N"]["per_asset_trades"],
        "minimum_pooled_trades": spec["minimum_N"]["pooled_trades"],
        "p_sharp_gt_0_min": spec["statistical_gates"][
            "P_Sharp_greater_0_min"
        ],
        "permutation_p_max": spec["statistical_gates"]["permutation_p_max"],
        "sharpe_ci_excludes_zero": spec["statistical_gates"][
            "sharpe_ci_excludes_zero"
        ],
        "permutation_seed": spec["statistical_gates"]["permutation"][
            "fixed seed 20260911"
        ]
        if "fixed seed 20260911" in spec["statistical_gates"]["permutation"]
        else 20260911,
        "permutation_draws": int(
            spec["statistical_gates"]["permutation"]
            .get("draws", 10000)
            .split()[0]
        ),
        "orthogonality_max_abs_daily_correlation": spec[
            "orthogonality_gates"
        ]["MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"],
        "h5_pnl_correlation": spec["orthogonality_gates"][
            "H5_PNL_CORRELATION"
        ],
        "pit_oi_rule": spec["pit_rules"]["oi"],
        "pit_price_rule": spec["pit_rules"]["price"],
        "pit_future_mutation_rule": spec["pit_rules"]["future_mutation"],
        "archive_validity_role": spec["common_window_utc"][
            "archive_validity_vs_decision_eligibility"
        ]["ARCHIVE_DAY_VALIDITY"],
        "insufficient_sample_policy": spec["insufficient_sample_policy"],
        "pass_requires": tuple(
            spec["pass_fail_semantics"]["PASS_requires"]
            .replace("ALL of: ", "")
            .split(", ")
        ),
        "fail_is_terminal": spec["pass_fail_semantics"]["FAIL_is_terminal"],
        "spec_sha256": spec_sha,
        "manifest_sha256": manifest_sha,
        "dataset_sha256": dataset_sha,
        "raw_snapshot": spec,
    }

    snapshot["snapshot_sha256"] = _sha256(
        Path(f"/tmp/h6_snapshot_{snapshot['spec_sha256']}.tmp")
    )  # placeholder; real path chosen at runtime

    raise RuntimeError("placeholder sha path is not valid; compute lazily")


if __name__ == "__main__":
    raise RuntimeError("Snapshot hash is computed lazily in P6")
