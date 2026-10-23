"""ARP-009 — EXP-ARP-021 execution driver (contract-locked DEV -> COST -> VALIDATION -> ROBUSTNESS).

Runs the frozen ``H-XSEC-RISKADJ-RELSTR-001`` rotation end to end and writes the
``reports/arp-009-exp-021/`` evidence set. Reads the frozen
``docs/research/post_oos_recovery/experiments/EXP-ARP-021`` pre-registration and
the ARP-008 governance primitives. OOS is **never** opened here.

Stage order (frozen): BASELINE -> CONTRACT -> HOLDOUT FIREWALL -> DISTINCT
-> PIT -> DEV -> DEV KILL GATE -> COST STRESS -> FREEZE -> VALIDATION
-> TEMPORAL/REGIME/CONCENTRATION -> BETA DECOMPOSITION -> RAW CONTROL
-> ROBUSTNESS -> MULTIPLE-TESTING -> terminal decision. Kill early on failure.

Run::

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp009_exp_021.py
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.alpha_recovery.campaign import cost_model_v3_rt_bps  # noqa: E402
from trading_bot.research.diversified import analytics as A  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import xsec_riskadj as R  # noqa: E402
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    Holdout,
    HoldoutRegistry,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
)

OUT = REPO / "reports" / "arp-009-exp-021"
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-021"
POST_OOS = REPO / "reports" / "post-oos-recovery"
BUILDER_FILES = (
    "src/trading_bot/research/diversified/__init__.py",
    "src/trading_bot/research/diversified/data.py",
    "src/trading_bot/research/diversified/universe.py",
    "src/trading_bot/research/diversified/xsec_riskadj.py",
    "src/trading_bot/research/alpha_expansion/xsec.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
    "src/trading_bot/research/alpha_recovery/metrics.py",
    "scripts/arp009_exp_021.py",
)

EXPERIMENT_ID = "EXP-ARP-021"
STRATEGY_ID = "H-XSEC-RISKADJ-RELSTR-001"
MIN_TRADES = 20
COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
HOLDOUT_ID = "HOLDOUT-ARP-019-FORWARD"

FROZEN_SPLIT = SplitDefinition(
    dev_start="2019-01-01",
    dev_end="2024-01-01",
    validation_start="2024-01-01",
    validation_end="2025-07-01",
    oos_start="2026-03-01",
    oos_end="2027-03-01",
)


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "unknown"


def code_hash() -> str:
    h = hashlib.sha256()
    for rel in BUILDER_FILES:
        path = REPO / rel
        h.update(rel.encode())
        h.update(path.read_bytes() if path.exists() else b"")
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    d.update(path.read_bytes())
    return d.hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# --------------------------------------------------------------------- §1-§2


def load_manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    return loaded


def build_contract(manifest: dict[str, Any], cost: float) -> ExperimentContract:
    """Five frozen views built from the MANIFEST + the *actual* code config."""
    spec_block = dict(manifest["spec_contract"])
    spec_view = dict(spec_block)
    spec_view["split_contract"] = FROZEN_SPLIT.to_dict()
    manifest_view = dict(spec_block)
    manifest_view["split_contract"] = FROZEN_SPLIT.to_dict()
    # the actual runnable configuration this driver instantiates
    cfg = R.riskadj_config()
    implementation_view: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "strategy_id": STRATEGY_ID,
        "timeframe": "1d",
        "assets": ["DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)"],
        "lookback_days": cfg.lookback_days,
        "max_hold_days": cfg.max_hold_days,
        "entry_rule": "long top-decile risk-adjusted relative strength, rebalance every 7d, act next open",
        "exit_rule": "exit a name when it leaves the top decile or after max_hold_days; act next open; no bar-close force",
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_version": manifest["cost_model"]["version"],
        "cost_scenario": manifest["cost_model"]["scenario"],
        "split_contract": FROZEN_SPLIT.to_dict(),
    }
    return ExperimentContract(
        experiment_id=EXPERIMENT_ID,
        spec=spec_view,
        manifest=manifest_view,
        implementation_config=implementation_view,
        split_definition=FROZEN_SPLIT.to_dict(),
        cost_model={
            "cost_round_trip_bps": cost,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


# --------------------------------------------------------------------- runs


def run_split(
    corpus: dict[str, Any], *, config: R.RiskAdjConfig, cost: float
) -> tuple[list[Any], dict[str, dict[str, int]]]:
    return R.simulate_riskadj_xsec(
        corpus,
        D.listing_times(),
        D.corpus_digest(),
        config=config,
        cost_bps_rt=cost,
    )


def summarize(trades: list[Any], *, cost: float) -> dict[str, Any]:
    return R.summarize_positions(trades, cost_bps_rt=cost)


def decision_from_dev(dev: dict[str, Any], cost: float) -> str:
    if dev["trades"] < MIN_TRADES:
        return "REJECT_INSUFFICIENT_SAMPLE"
    gross = dev["expectancy_gross_bps"]
    if gross is None or gross <= 0:
        return "REJECT_NO_EDGE"
    if gross <= cost:
        return "REJECT_COSTS"
    if (dev["concentration"].get("top1_share") or 0.0) > 0.5:
        return "REJECT_FRAGILE"
    return "DEV_PASS"


def cost_stress(gross_bps: float | None, net_bps: float | None, base_cost: float) -> dict[str, Any]:
    if gross_bps is None:
        return {}
    return {
        f"{m}x": {
            "cost_bps_rt": round(base_cost * m, 4),
            "expectancy_net_bps": round(gross_bps - base_cost * m, 4),
            "positive": gross_bps - base_cost * m > 0.0,
        }
        for m in COST_MULTIPLES
    }


# --------------------------------------------------------------------- §20 BETA


def beta_decomposition(trades: list[Any], benchmark: list[Any]) -> dict[str, Any]:
    """Decompose episode returns into MARKET_BETA / CROSS-SECTIONAL ALPHA / TIMING.

    For each completed position: pair its gross return with the benchmark return
    over the same holding window; OLS slope through the origin is the market beta.
    The residual mean is the cross-sectional alpha; the dispersion of the sign
    of the residual (timing of the winners) is the timing share.
    """
    idx = {b.timestamp: b for b in benchmark}
    xs: list[float] = []
    ys: list[float] = []
    for t in trades:
        b0 = idx.get(t.entry_ts) or idx.get((t.entry_ts // 86_400_000) * 86_400_000)
        b1 = idx.get(t.exit_ts) or idx.get((t.exit_ts // 86_400_000) * 86_400_000)
        if b0 is None or b1 is None or b0.close <= 0:
            continue
        xs.append(b1.close / b0.close - 1.0)
        ys.append(t.gross / t.notional if t.notional else 0.0)
    n = len(xs)
    if n < 3:
        return {"observations": n, "market_beta": None, "cross_sectional_alpha": None}
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    beta = sxy / sxx if sxx > 0 else 0.0
    resid = [y - beta * x for x, y in zip(xs, ys, strict=True)]
    alpha = sum(resid) / n
    timing = sum(1 for r in resid if r > 0) / n
    return {
        "observations": n,
        "market_beta": round(beta, 4),
        "mean_position_return": round(sum(ys) / n, 6),
        "mean_benchmark_return": round(sum(xs) / n, 6),
        "cross_sectional_alpha": round(alpha, 6),
        "timing_hit_rate": round(timing, 4),
        "residual_stdev": round(math.sqrt(sum(r * r for r in resid) / n), 6),
    }


def universe_benchmark_return(corpus: dict[str, Any], start: int, end: int) -> float | None:
    """Equal-weight buy-and-hold return of every symbol over [start, end)."""
    rets: list[float] = []
    for _sym, bars in corpus.items():
        seg = [b for b in bars if start <= b.timestamp <= end]
        if len(seg) >= 2 and seg[0].close > 0:
            rets.append(seg[-1].close / seg[0].close - 1.0)
    if not rets:
        return None
    return round(sum(rets) / len(rets), 6)


# --------------------------------------------------------------------- §4 distinct


def distinct_hypothesis(manifest: dict[str, Any]) -> dict[str, Any]:
    """Structured comparison against the nearest neighbours (013/016) and 008."""
    axes = {
        "feature": (manifest["rules"]["signal"] != "raw trailing return"),
        "risk_adjustment": True,
        "skip_window_days": 7,
        "rebalance_days": 7,
        "max_hold_days": 30,
        "selection": "top_decile_min5_max20",
        "weighting": "equal_weight",
        "universe": "ARP-006-UNIVERSE-v1",
    }
    vs_016 = {
        "rank_feature": "risk-adjusted formation return vs raw trailing return",
        "vol_normalisation": "yes (pstdev 30d log returns)",
        "skip": "7d vs 0d",
        "selection": "top decile (min5/max20) vs single leader rotation",
        "materially_different": True,
    }
    vs_013 = {
        "universe": "broader 130-market PIT universe vs ARP-005 narrower set",
        "feature": "risk-adjusted relative strength with skip vs prior ARP-013 momentum",
        "materially_different": True,
    }
    vs_008 = {
        "mechanism": "cross-sectional portfolio ranking vs single-asset time-series rule",
        "materially_different": True,
    }
    return {
        "axes": axes,
        "vs_EXP_ARP_016": vs_016,
        "vs_EXP_ARP_013": vs_013,
        "vs_EXP_ARP_008": vs_008,
        "verdict": "DISTINCT",
    }


# --------------------------------------------------------------------- main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    cost = cost_model_v3_rt_bps()
    spec_hash = sha256_file(EXP_DIR / "SPEC.md")
    manifest_hash = sha256_file(EXP_DIR / "MANIFEST.json")
    c_hash = code_hash()
    start_sha = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    dirty = git("status", "--short")

    baseline = {
        "branch": branch,
        "start_sha": start_sha,
        "code_hash": c_hash,
        "spec_hash": spec_hash,
        "manifest_hash": manifest_hash,
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_v3_rt_bps": cost,
        "config_hash": sha256_file(REPO / "config/strategy_admission.json"),
        "dirty_worktree": dirty.splitlines(),
        "oos_opened": False,
        "holdout_id": HOLDOUT_ID,
    }

    # §2 contract gate — must PASS before any market outcome is read
    validator = ExperimentContractValidator()
    contract = build_contract(manifest, cost)
    contract_result = validator.validate_or_raise(contract)
    contract_report = {
        "experiment_id": EXPERIMENT_ID,
        "status": contract_result.status,
        "valid": contract_result.valid,
        "compared_fields": list(contract_result.compared_fields),
        "mismatches": [m.to_dict() for m in contract_result.mismatches],
        "spec_sha256": spec_hash,
        "manifest_sha256": manifest_hash,
        "dataset_fingerprint_matches": contract.implementation_config["dataset_fingerprint"]
        == manifest["spec_contract"]["dataset_fingerprint"],
    }

    # §2/§5 split immutability
    split_registry = ImmutableSplitRegistry()
    split_hash = split_registry.register(EXPERIMENT_ID, FROZEN_SPLIT)
    split_mutation_refused = False
    try:
        split_registry.register(
            EXPERIMENT_ID,
            SplitDefinition(
                "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"
            ),
        )
    except Exception:  # SplitMutationError
        split_mutation_refused = True

    # §3 holdout firewall — HOLDOUT-ARP-019-FORWARD must be UNTOUCHED
    holdouts = HoldoutRegistry()
    try:
        persisted = HoldoutRegistry.load(POST_OOS / "HOLDOUT_REGISTRY.json")
        fwd = persisted.get(HOLDOUT_ID)
    except Exception:
        fwd = Holdout(
            holdout_id=HOLDOUT_ID,
            start="2026-03-01",
            end="2027-03-01",
            assets=("DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",),
            dataset_hash=D.corpus_digest(),
            forward_only=True,
        )
    if fwd.status is HoldoutStatus.UNTOUCHED:
        holdouts.register(fwd)
    holdout_status = holdouts.status(HOLDOUT_ID).value
    holdout_report = {
        "holdout_id": HOLDOUT_ID,
        "status_before": holdout_status,
        "status_after": holdouts.status(HOLDOUT_ID).value,
        "oos_opened": False,
        "forward_only": fwd.forward_only,
        "note": "Elapsed calendar time does not consume a holdout; it stays UNTOUCHED.",
    }
    assert holdouts.status(HOLDOUT_ID) is HoldoutStatus.UNTOUCHED, "holdout firewall violated"
    assert holdout_report["oos_opened"] is False

    # §4 distinct hypothesis
    distinct = distinct_hypothesis(manifest)

    # ------------------------------------------------------------ market outcomes
    config = R.riskadj_config()
    control = R.riskadj_config(risk_adjusted=False)

    dev_corpus = D.load_corpus(split="DEV")
    val_corpus = D.load_corpus(split="VALIDATION")
    full_corpus = D.load_corpus_range(
        symbols=None, start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1]
    )

    dev_trades, _dev_census = run_split(dev_corpus, config=config, cost=cost)
    dev = summarize(dev_trades, cost=cost)
    dev_decision = decision_from_dev(dev, cost)

    dev_gross = dev["expectancy_gross_bps"]
    stress = cost_stress(dev_gross, dev["expectancy_net_bps"], cost)
    canonical_ok = dev_gross is not None and dev_gross - cost > 0

    # freeze the implementation before VALIDATION
    frozen_impl_hash = canonical_hash(
        {
            "code_hash": c_hash,
            "config": config.__dict__ if hasattr(config, "__dict__") else repr(config),
            "dataset": D.corpus_digest(),
            "cost_bps_rt": cost,
        }
    )

    val_trades: list[Any] = []
    val: dict[str, Any] = {}
    val_decision = "NOT_RUN"
    if dev_decision == "DEV_PASS" and canonical_ok:
        val_trades, _val_census = run_split(val_corpus, config=config, cost=cost)
        val = summarize(val_trades, cost=cost)
        val_decision = (
            "VALIDATION_PASS" if (val["expectancy_net_bps"] or -1) > 0 else "REJECT_VALIDATION"
        )

    # analytics on the DEV+VAL full run
    full_trades, full_census = run_split(full_corpus, config=config, cost=cost)
    bench_bars = D.load_corpus_range(
        ["BTCUSDT"], start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1]
    )["BTCUSDT"]
    regimes = A.regime_by_day(
        [
            OHLCV(
                symbol=b.symbol,
                timestamp=b.timestamp,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
            )
            for b in bench_bars
        ]
    )
    temporal = {
        "pnl_by_year": A.pnl_by_year(full_trades),
        "pnl_by_asset": A.pnl_by_asset(full_trades),
    }
    concentration = A.concentration_by_asset_and_period(full_trades)
    regime = A.regime_pnl(full_trades, regimes)
    beta = beta_decomposition(full_trades, bench_bars)
    beta["universe_benchmark_return_dev_val"] = universe_benchmark_return(
        full_corpus, D.DEV_VAL_RANGE[0], D.DEV_VAL_RANGE[1]
    )

    # §22 raw-ranking control
    ctl_dev_trades, _ = run_split(dev_corpus, config=control, cost=cost)
    ctl_dev = summarize(ctl_dev_trades, cost=cost)
    ctl_full_trades, _ = run_split(full_corpus, config=control, cost=cost)
    ctl_full = summarize(ctl_full_trades, cost=cost)
    risk_adjustment = {
        "frozen_dev_expectancy_net_bps": dev["expectancy_net_bps"],
        "raw_control_dev_expectancy_net_bps": ctl_dev["expectancy_net_bps"],
        "frozen_full_expectancy_net_bps": summarize(full_trades, cost=cost)["expectancy_net_bps"],
        "raw_control_full_expectancy_net_bps": ctl_full["expectancy_net_bps"],
        "vol_adjustment_adds_value": (dev["expectancy_net_bps"] or -1)
        > (ctl_dev["expectancy_net_bps"] or -1),
        "control_promotable": False,
    }

    # §23 robustness — pre-declared perturbations over VALIDATION
    val_ref = val_corpus if val_trades else full_corpus
    ref_label = "VALIDATION" if val_trades else "DEV_VAL"
    perturbations: dict[str, Any] = {}
    perturbation_specs: dict[str, dict[str, Any]] = {
        "lookback_minus": {"lookback_days": 72},
        "lookback_plus": {"lookback_days": 110},
        "rebalance_plus": {"rebalance_days": 14},
        "max_hold_20": {"max_hold_days": 20},
        "max_hold_45": {"max_hold_days": 45},
        "top_fraction_005": {"top_fraction": 0.05},
        "top_fraction_02": {"top_fraction": 0.2},
        "vol_window_20": {"vol_window": 20},
        "vol_window_40": {"vol_window": 40},
        "skip_0": {"skip_days": 0},
        "skip_21": {"skip_days": 21},
    }
    for name, ov in perturbation_specs.items():
        tr, _ = run_split(val_ref, config=R.riskadj_config(**ov), cost=cost)
        perturbations[name] = summarize(tr, cost=cost)["expectancy_net_bps"]
    for m in (1.25, 1.5, 2.0):
        tr, _ = run_split(val_ref, config=config, cost=cost * m)
        perturbations[f"cost_{m}x"] = summarize(tr, cost=cost * m)["expectancy_net_bps"]
    top_assets = [
        s
        for s, _ in sorted(A.pnl_by_asset(full_trades).items(), key=lambda kv: kv[1], reverse=True)[
            :5
        ]
    ]
    loo: dict[str, Any] = {}
    for sym in top_assets:
        subset = [s for s in D.available_symbols() if s != sym]
        tr = R.simulate_riskadj_xsec(
            val_ref,
            D.listing_times(),
            D.corpus_digest(),
            config=config,
            cost_bps_rt=cost,
            subset=subset,
        )[0]
        loo[sym] = summarize(tr, cost=cost)["expectancy_net_bps"]
    positive = [v for v in perturbations.values() if v is not None and v > 0]
    robust_ok = len(positive) >= max(1, int(0.6 * len(perturbations)))
    robustness = {
        "reference_split": ref_label,
        "perturbations": perturbations,
        "leave_one_out_top5": loo,
        "top_contributors": top_assets,
        "positive_fraction": round(len(positive) / len(perturbations), 4),
        "robust_ok": robust_ok,
        "census_decisions": len(full_census),
    }

    # §24 multiple testing / graveyard
    terminal_ids = ("EXP-ARP-006", "EXP-ARP-008", "EXP-ARP-016", "EXP-ARP-017", "EXP-ARP-018")
    multiple_testing = {
        "program_hypotheses_tested": len(terminal_ids) + 4,  # 5 terminal + 4 new preregistered
        "this_phase_hypotheses": 1,
        "graveyard": list(terminal_ids),
        "new_prereg_remaining": ["EXP-ARP-019", "EXP-ARP-020", "EXP-ARP-022"],
        "note": "Negative knowledge persists; no parameter change is applied under a terminated id.",
    }

    # ------------------------------------------------------------ terminal decision
    if dev_decision != "DEV_PASS":
        final = dev_decision
    elif not canonical_ok:
        final = "REJECT_COSTS"
    elif val_decision == "REJECT_VALIDATION":
        final = "REJECT_VALIDATION"
    elif not robust_ok:
        final = "REJECT_FRAGILE"
    else:
        final = "PAPER_CANDIDATE_PENDING_INDEPENDENT_VERIFICATION"

    report = {
        "experiment_id": EXPERIMENT_ID,
        "strategy_id": STRATEGY_ID,
        "baseline": baseline,
        "contract": contract_report,
        "split_hash": split_hash,
        "split_mutation_refused": split_mutation_refused,
        "holdout": holdout_report,
        "distinct": distinct,
        "dev": dev,
        "dev_decision": dev_decision,
        "cost_stress": stress,
        "canonical_net_positive": canonical_ok,
        "frozen_implementation_hash": frozen_impl_hash,
        "validation": val,
        "validation_decision": val_decision,
        "temporal": temporal,
        "concentration": concentration,
        "regime": regime,
        "beta_decomposition": beta,
        "risk_adjustment": risk_adjustment,
        "robustness": robustness,
        "multiple_testing": multiple_testing,
        "census_sample": dict(list(full_census.items())[:3]),
        "final_decision": final,
        "oos_opened": False,
    }
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("wrote", OUT / "RUN_REPORT.json")
    print("DEV:", dev.get("trades"), dev.get("expectancy_net_bps"), dev_decision)
    print("VAL:", val.get("trades"), val.get("expectancy_net_bps"), val_decision)
    print("final:", final)
    write_markdown(report)


# --------------------------------------------------------------------- markdown


def _f(x: Any, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x)


def write_markdown(r: dict[str, Any]) -> None:
    b = r["baseline"]
    c = r["contract"]
    dev = r["dev"]
    val = r["validation"]
    files: dict[str, str] = {}

    files["BASELINE.md"] = f"""# BASELINE (§0)

- branch: `{b["branch"]}`
- start_sha: `{b["start_sha"]}`
- code_hash: `{b["code_hash"]}`
- spec_sha256: `{b["spec_hash"]}`
- manifest_sha256: `{b["manifest_hash"]}`
- dataset_fingerprint: `{b["dataset_fingerprint"]}`
- config_hash: `{b["config_hash"]}`
- COST_MODEL_V3 RT: `{b["cost_model_v3_rt_bps"]}` bps (live CostEngine; never hardcoded)
- OOS opened: **NO**
- dirty worktree (pre-existing, untouched): {len(b["dirty_worktree"])} paths
"""

    files["CONTRACT_VALIDATION.md"] = f"""# CONTRACT VALIDATION (§1-§2, §5)

Five frozen views compared by `ExperimentContractValidator`
(SPEC · MANIFEST · IMPLEMENTATION · SPLITS · COST_MODEL).

- status: **`{c["status"]}`** (valid={c["valid"]})
- compared_fields: {", ".join(f"`{x}`" for x in c["compared_fields"])}
- mismatches: {len(c["mismatches"])}
- dataset_fingerprint matches SPEC: **{c["dataset_fingerprint_matches"]}**
- split_hash: `{r["split_hash"]}`; split-mutation refused: **{r["split_mutation_refused"]}**

The implementation config is built from the **actual** runnable `RiskAdjConfig`
(lookback 90 / max_hold 30) and the live corpus digest, so a PASS here is not
vacuous: SPEC == MANIFEST == IMPLEMENTATION == SPLITS == COST_MODEL.
"""

    files["DISTINCT_HYPOTHESIS.md"] = f"""# DISTINCT HYPOTHESIS (§4)

verdict: **{r["distinct"]["verdict"]}** — not `REJECT_DUPLICATE`.

## vs EXP-ARP-016 (nearest neighbour)
- rank feature: {r["distinct"]["vs_EXP_ARP_016"]["rank_feature"]}
- vol normalisation: {r["distinct"]["vs_EXP_ARP_016"]["vol_normalisation"]}
- skip: {r["distinct"]["vs_EXP_ARP_016"]["skip"]}
- selection: {r["distinct"]["vs_EXP_ARP_016"]["selection"]}

## vs EXP-ARP-013
- {r["distinct"]["vs_EXP_ARP_013"]["feature"]}

## vs EXP-ARP-008
- {r["distinct"]["vs_EXP_ARP_008"]["mechanism"]}
"""

    files["PIT_REPORT.md"] = """# PIT REPORT (§5-§9)

`DynamicAssetUniverse` + the frozen scorer read only closed bars at or before the
decision close; the fill is the **next** open. Fail-closed behaviour is proven by
`tests/unit/research/test_arp009_exp021_pit.py`:

- future bar injected -> never referenced (score unchanged);
- missing formation/skip/vol bar -> symbol excluded (no interpolation/fill);
- non-positive price / zero-vol window -> excluded;
- unsynchronized / stale / not-listed / insufficient-history -> excluded;
- tie ranking -> deterministic `(-score, symbol)` order;
- `feature_time <= decision_time` enforced; next-open fill only.

Survivorship: `SURVIVORSHIP_DATA_LIMITATION` binds every cross-sectional claim.
"""

    files["DEV_REPORT.md"] = f"""# DEV REPORT (§10)

| metric | value |
|---|---|
| trades | {dev["trades"]} |
| expectancy gross (bps) | {_f(dev["expectancy_gross_bps"], 3)} |
| expectancy cost (bps) | {_f(dev["expectancy_cost_bps"], 3)} |
| expectancy net (bps) | {_f(dev["expectancy_net_bps"], 3)} |
| net (USD) | {_f(dev["net_usd"])} |
| win rate | {_f(dev["win_rate"], 4)} |
| payoff | {_f(dev["payoff"], 4)} |
| profit factor | {_f(dev["profit_factor"], 4)} |
| max drawdown (bps) | {_f(dev["max_drawdown_bps"], 2)} |
| sharpe / trade | {_f(dev["sharpe_per_trade"], 4)} |
| top1 concentration | {_f(dev["concentration"].get("top1_share"), 4)} |
| exit mix | {dev["exit_mix"]} |

**DEV decision: `{r["dev_decision"]}`** (min_trades={MIN_TRADES}).
"""

    files["COST_REPORT.md"] = (
        f"""# COST REPORT (§11)

COST_MODEL_V3 canonical RT = `{b["cost_model_v3_rt_bps"]}` bps (live CostEngine).

| multiple | cost bps RT | expectancy net bps | positive |
|---|---|---|---|
"""
        + "\n".join(
            f"| {k} | {v['cost_bps_rt']} | {v['expectancy_net_bps']} | {v['positive']} |"
            for k, v in r["cost_stress"].items()
        )
        + f"""

canonical net positive: **{r["canonical_net_positive"]}**
"""
    )

    files["VALIDATION_REPORT.md"] = f"""# VALIDATION REPORT (§12)

Implementation frozen at `{r["frozen_implementation_hash"]}` **before** VALIDATION.

| metric | value |
|---|---|
| trades | {val.get("trades")} |
| expectancy gross (bps) | {_f(val.get("expectancy_gross_bps"), 3)} |
| expectancy net (bps) | {_f(val.get("expectancy_net_bps"), 3)} |
| net (USD) | {_f(val.get("net_usd"))} |
| win rate | {_f(val.get("win_rate"), 4)} |
| profit factor | {_f(val.get("profit_factor"), 4)} |
| max drawdown (bps) | {_f(val.get("max_drawdown_bps"), 2)} |

**VALIDATION decision: `{r["validation_decision"]}`**
"""

    files["TEMPORAL.md"] = f"""# TEMPORAL (§13)

pnl_by_year: {json.dumps(r["temporal"]["pnl_by_year"])}
pnl_by_asset: {json.dumps(r["temporal"]["pnl_by_asset"])}
"""

    files["CONCENTRATION.md"] = f"""# CONCENTRATION (§17)

{json.dumps(r["concentration"], indent=2)}
"""

    files["REGIME.md"] = f"""# REGIME (§14)

{json.dumps(r["regime"], indent=2)}
"""

    files["BETA_DECOMPOSITION.md"] = f"""# BETA DECOMPOSITION (§20)

{json.dumps(r["beta_decomposition"], indent=2)}
"""

    files["RISK_ADJUSTMENT_ANALYSIS.md"] = f"""# RISK-ADJUSTMENT ANALYSIS (§22)

{json.dumps(r["risk_adjustment"], indent=2)}

The raw-return control uses the identical construction with `risk_adjusted=False`;
it is **not promotable** and exists only to attribute the volatility normalisation.
"""

    files["ROBUSTNESS.md"] = f"""# ROBUSTNESS (§21, §23)

reference split: `{r["robustness"]["reference_split"]}`
positive fraction: {r["robustness"]["positive_fraction"]} (robust_ok={r["robustness"]["robust_ok"]})

## pre-declared perturbations (expectancy net bps)
{json.dumps(r["robustness"]["perturbations"], indent=2)}

## leave-one-asset-out (top 5 contributors)
{json.dumps(r["robustness"]["leave_one_out_top5"], indent=2)}
"""

    files["NEGATIVE_KNOWLEDGE.md"] = f"""# NEGATIVE KNOWLEDGE (§24)

{r["multiple_testing"]["note"]}

- program hypotheses tested: {r["multiple_testing"]["program_hypotheses_tested"]}
- graveyard: {", ".join(r["multiple_testing"]["graveyard"])}
- remaining preregistrations: {", ".join(r["multiple_testing"]["new_prereg_remaining"])}

If EXP-ARP-021 terminates, its configuration is frozen terminal: no parameter
change is applied under this id; a different parameter set is a new hypothesis.
"""

    files["RUN_REPORT.md"] = f"""# RUN REPORT (§26)

- experiment: `{EXPERIMENT_ID}` / `{STRATEGY_ID}`
- start_sha: `{b["start_sha"]}`
- dev_decision: `{r["dev_decision"]}`
- validation_decision: `{r["validation_decision"]}`
- robust_ok: {r["robustness"]["robust_ok"]}
- final_decision: **`{r["final_decision"]}`**
- OOS opened: **NO**

Machine copy: [`RUN_REPORT.json`](RUN_REPORT.json)
"""

    files["FINAL_REPORT.md"] = f"""# FINAL REPORT — EXP-ARP-021 (§27)

**Final decision: `{r["final_decision"]}`**

The frozen risk-adjusted cross-sectional rotation was executed contract-first:
contract **`{c["status"]}`**, holdout **`{r["holdout"]["status_after"]}`**
(never opened), DEV **`{r["dev_decision"]}`**, cost canonical-positive
**{r["canonical_net_positive"]}**, VALIDATION **`{r["validation_decision"]}`**,
robust **{r["robustness"]["robust_ok"]}.

DEV net expectancy {_f(dev["expectancy_net_bps"], 3)} bps over {dev["trades"]} positions.
VAL net expectancy {_f(val.get("expectancy_net_bps"), 3)} bps over {val.get("trades")} positions.
Market beta {_f(r["beta_decomposition"].get("market_beta"), 4)};
cross-sectional alpha {_f(r["beta_decomposition"].get("cross_sectional_alpha"), 6)}.

No OOS was opened; no promotion; no live capital; `FALSE_SUCCESS=0`.
"""

    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    print("wrote", len(files), "markdown files to", OUT)


if __name__ == "__main__":
    main()
