"""P5 / V4 — frozen H6 contract snapshot loaded programmatically from frozen authority.

V4 repair (V3-AUTH-001): this module previously hard-coded the superseded **V1**
preregistration paths and hashes (``oi-full-history-01/H6_SPEC.json``,
``f514fecf…``, ``345334c3…``) and a placeholder ``snapshot_sha256`` path that always
raised. All authority now resolves from the single versioned runtime binding
(``runtime_authority``); this module contains **no** hash or path literals.

No economic value is computed here. This module only extracts canonical frozen H6
semantics from the committed SPEC and MANIFEST so later implementation tracks can
compare runtime constants against the frozen spec (P6 drift guard).

Fail-closed while unbound (pre-freeze) / on hash drift.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.h6 import runtime_authority as _ra


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def spec_path() -> Path:
    """Frozen V4 spec path, resolved from the binding (repo-root relative)."""
    return _ra.current_binding().spec_file


def manifest_path() -> Path:
    """Frozen V4 manifest path, resolved from the binding."""
    return _ra.current_binding().manifest_file


def expected_spec_sha256() -> str:
    return _ra.current_binding().spec_sha256


def expected_manifest_sha256() -> str:
    return _ra.current_binding().manifest_sha256


def expected_dataset_sha256() -> str:
    return _ra.dataset_sha256_or_unbound()


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
    permutation_method: str
    permutation_seed: int
    permutation_draws: int
    orthogonality_max_abs_daily_correlation: float
    h5_pnl_correlation: str
    pit_oi_rule: str
    pit_price_rule: str
    pit_feature_rule: str
    pit_future_mutation_rule: str
    pit_data_time_leq_decision_time: bool
    archive_validity_role: str
    insufficient_sample_policy: str
    pass_requires: tuple[str, ...]
    fail_is_terminal: bool
    spec_sha256: str
    manifest_sha256: str
    dataset_sha256: str
    snapshot_sha256: str
    raw_snapshot: dict[str, Any] = field(repr=False, compare=False)


# The frozen robust z-score is z = (delta_oi - median) / (c * MAD) with c = 1.4826,
# the consistency constant that makes MAD comparable to a standard deviation under
# normality. V1's parser assumed one exact parenthesisation and silently produced the
# wrong operand for any other phrasing; this reads the coefficient directly.
_MAD_SCALE_RE = re.compile(r"(?P<c>\d+\.\d+)\s*\*\s*(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)")
_MAD_SCALE_CONSTANT = 1.4826


def _extract_mad_scale_factor(z_feature: dict[str, Any]) -> float:
    """Return the frozen 1.4826 MAD->sigma constant from the z_oi definition."""
    definition = str(z_feature.get("definition", ""))
    match = _MAD_SCALE_RE.search(definition)
    if match is None:
        raise RuntimeError(
            "frozen z_oi scale not recognized: no '<constant> * <symbol>' in definition"
        )
    coefficient = float(match.group("c"))
    if coefficient != _MAD_SCALE_CONSTANT:
        raise RuntimeError(
            f"frozen z_oi MAD scaling constant changed: {coefficient} != {_MAD_SCALE_CONSTANT}"
        )
    if not match.group("symbol").lower().endswith("mad"):
        raise RuntimeError(
            f"frozen z_oi scale applied to unexpected symbol: {match.group('symbol')!r}"
        )
    return coefficient


def _require_structured_permutation(gates: dict[str, Any]) -> dict[str, Any]:
    """V4 requires ``statistical_gates.permutation`` to be a structured block.

    V2 stored it as prose ("sign-flip permutation …, 10,000 draws, fixed seed
    20260911"); V3 dropped ``statistical_gates`` altogether, leaving the seed and
    draw count with no live frozen authority. V4 freezes them as typed fields.
    """
    perm = gates.get("permutation")
    if not isinstance(perm, dict):
        raise RuntimeError(
            "frozen statistical_gates.permutation must be a structured object "
            f"(V3-SPEC-001 regression); got {type(perm).__name__}"
        )
    for key in ("method", "draws", "seed"):
        if key not in perm:
            raise RuntimeError(f"frozen statistical_gates.permutation missing {key!r}")
    return perm


def load_frozen_h6_snapshot(verify: bool = True) -> FrozenH6Config:
    """Load the frozen V4 contract. Raises if unbound or drifted."""
    binding = _ra.current_binding()
    spec_bytes = binding.spec_file.read_bytes()
    manifest_bytes = binding.manifest_file.read_bytes()
    spec_sha = _sha256_bytes(spec_bytes)
    manifest_sha = _sha256_bytes(manifest_bytes)

    if verify and spec_sha != binding.spec_sha256:
        raise RuntimeError(f"H6 spec SHA256 drift: {spec_sha} != {binding.spec_sha256}")
    if verify and manifest_sha != binding.manifest_sha256:
        raise RuntimeError(
            f"H6 manifest SHA256 drift: {manifest_sha} != {binding.manifest_sha256}"
        )

    dataset_sha = (
        binding.dataset_sha256
        if binding.dataset_sha256 != _ra.UNBOUND
        else _ra.dataset_sha256_or_unbound()
    )
    return parse_frozen_spec(
        json.loads(spec_bytes.decode("utf-8")),
        spec_bytes=spec_bytes,
        spec_sha256=spec_sha,
        manifest_sha256=manifest_sha,
        dataset_sha256=dataset_sha,
    )


def parse_frozen_spec(
    spec: dict[str, Any],
    *,
    spec_bytes: bytes | None = None,
    spec_sha256: str = "",
    manifest_sha256: str = "",
    dataset_sha256: str = "",
) -> FrozenH6Config:
    """Parse a frozen H6 spec mapping into a config.

    Used by ``load_frozen_h6_snapshot`` (binding-driven, at runtime) and by the
    pre-freeze completeness validator (explicit path, builder-side). Performing
    the same parse in both places guarantees the artefact that gets frozen is the
    artefact the runtime can actually consume.
    """
    if spec_bytes is None:
        spec_bytes = json.dumps(spec, sort_keys=True).encode("utf-8")

    feature = spec["feature_transformations"]
    z_feature = next(f for f in feature if f["name"] == "z_oi")
    scale_factor = _extract_mad_scale_factor(z_feature)

    gates = spec["statistical_gates"]
    perm = _require_structured_permutation(gates)
    pit = spec["pit_rules"]

    snapshot = {
        "hypothesis_id": spec["hypothesis_id"],
        "mechanism_name": spec["mechanism"]["name"],
        "mechanism_family": spec["mechanism"]["family"],
        "mechanism_statement": spec["mechanism"]["statement"],
        "assets": tuple(spec["assets"]),
        "common_window_start": spec["common_window_utc"]["start"],
        "common_window_end": spec["common_window_utc"]["end"],
        "decision_bucket": spec["decision_timeframe"]["bucket"],
        "decision_time_semantics": spec["decision_timeframe"]["decision_time"],
        "primary_holding_horizon_hours": spec["decision_timeframe"][
            "primary_holding_horizon_hours"
        ],
        "entry_timing": spec["entry_timing"],
        "exit_timing": spec["exit_timing"],
        "stop_invalidation": spec["stop_invalidation"],
        "cooldown": spec["cooldown"],
        "oi_field_whitelist": tuple(spec["oi_field_whitelist"]),
        "rolling_window_length_hours": spec["rolling_windows"]["z_oi"]["length_hours"],
        "rolling_min_observations": spec["rolling_windows"]["z_oi"]["min_observations"],
        "rolling_center": spec["rolling_windows"]["z_oi"]["center"],
        "rolling_scale_factor": scale_factor,
        "threshold_expansion_z": spec["threshold_rule"]["expansion_condition"]
        .split("+")[-1]
        .strip()
        .rstrip(")"),
        "contraction_uses": spec["threshold_rule"]["contraction_condition"],
        "mad_zero_semantics": spec["threshold_rule"]["neutral_or_insufficient"],
        "price_direction_rule": spec["direction_semantics"]["LONG"].split("AND")[0].strip(),
        "cost_total_round_trip_bps": spec["cost_model"]["BASE_TOTAL_ROUND_TRIP_COST_BPS"],
        "cost_sensitivity_bps": tuple(spec["cost_model"]["COST_SENSITIVITY_BPS"]),
        "funding_policy": spec["funding_accounting"]["FUNDING_DISCOVERY_ACCOUNTING"],
        "funding_materiality_gate_before_promotion": spec["funding_accounting"][
            "funding_materiality_gate_before_promotion"
        ],
        "minimum_per_asset_trades": spec["minimum_N"]["per_asset_trades"],
        "minimum_pooled_trades": spec["minimum_N"]["pooled_trades"],
        "p_sharp_gt_0_min": float(gates["P_Sharp_greater_0_min"]),
        "permutation_p_max": float(gates["permutation_p_max"]),
        "sharpe_ci_excludes_zero": bool(gates["sharpe_ci_excludes_zero"]),
        "permutation_method": str(perm["method"]),
        "permutation_seed": int(perm["seed"]),
        "permutation_draws": int(perm["draws"]),
        "orthogonality_max_abs_daily_correlation": spec["orthogonality_gates"][
            "MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"
        ],
        "h5_pnl_correlation": spec["orthogonality_gates"]["H5_PNL_CORRELATION"],
        "pit_oi_rule": pit["oi"],
        "pit_price_rule": pit["price"],
        "pit_feature_rule": pit["features"],
        "pit_future_mutation_rule": pit["future_mutation"],
        "pit_data_time_leq_decision_time": bool(pit["data_time_leq_decision_time"]),
        "archive_validity_role": pit["archive_validity_role"],
        "insufficient_sample_policy": spec["insufficient_sample_policy"],
        "pass_requires": tuple(
            spec["pass_fail_semantics"]["PASS_requires"].replace("ALL of: ", "").split(", ")
        ),
        "fail_is_terminal": spec["pass_fail_semantics"]["FAIL_is_terminal"],
        "spec_sha256": spec_sha256,
        "manifest_sha256": manifest_sha256,
        "dataset_sha256": dataset_sha256,
        "snapshot_sha256": "",
        "raw_snapshot": spec,
    }

    # Deterministic content hash over the canonical snapshot (no placeholder paths).
    canonical = json.dumps(
        {k: v for k, v in snapshot.items() if k not in ("snapshot_sha256", "raw_snapshot")},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    snapshot["snapshot_sha256"] = _sha256_bytes(canonical + spec_bytes)

    return FrozenH6Config(**snapshot)


def frozen_snapshot_sha256() -> str:
    """Stable identifier for the frozen contract snapshot (spec bytes + semantics)."""
    return load_frozen_h6_snapshot().snapshot_sha256


__all__ = [
    "FrozenH6Config",
    "expected_dataset_sha256",
    "expected_manifest_sha256",
    "expected_spec_sha256",
    "frozen_snapshot_sha256",
    "load_frozen_h6_snapshot",
    "manifest_path",
    "parse_frozen_spec",
    "spec_path",
]


if __name__ == "__main__":  # pragma: no cover - diagnostic entry point
    cfg = load_frozen_h6_snapshot()
    print(json.dumps(cfg.__dict__ if hasattr(cfg, "__dict__") else cfg.describe()
                     if hasattr(cfg, "describe") else cfg, indent=2, default=str))
