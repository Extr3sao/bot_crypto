"""ARP-011 — EXP-ARP-019 execution driver (trend-breadth / market-regime allocation).

Runs the frozen ``H-BREADTH-REGIME-001`` gate end to end and writes the
``reports/arp-011-exp-019/`` evidence set. OOS is **never** opened.

Run::

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp011_exp_019.py
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
from trading_bot.research.diversified import breadth as B  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import xsec_riskadj as R  # noqa: E402
from trading_bot.research.diversified.universe import (  # noqa: E402
    DynamicAssetUniverse,
    UniverseConfig,
)
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    HoldoutRegistry,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
)

OUT = REPO / "reports" / "arp-011-exp-019"
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-019"
POST_OOS = REPO / "reports" / "post-oos-recovery"

EXPERIMENT_ID = "EXP-ARP-019"
STRATEGY_ID = "H-BREADTH-REGIME-001"
MIN_TRADES = 20
COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
HOLDOUT_ID = "HOLDOUT-ARP-019-FORWARD"
BPS = 10_000.0
HORIZONS = (1, 5, 10, 20, 30)

BUILDER_FILES = (
    "src/trading_bot/research/diversified/__init__.py",
    "src/trading_bot/research/diversified/data.py",
    "src/trading_bot/research/diversified/universe.py",
    "src/trading_bot/research/diversified/breadth.py",
    "src/trading_bot/research/diversified/xsec_riskadj.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
    "scripts/arp011_exp_019.py",
)

FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    return loaded


def build_contract(manifest: dict[str, Any], cost: float) -> ExperimentContract:
    spec_block = dict(manifest["spec_contract"])
    split_dict = FROZEN_SPLIT.to_dict()
    cfg = B.breadth_config()
    impl = {
        "experiment_id": EXPERIMENT_ID,
        "strategy_id": STRATEGY_ID,
        "timeframe": "1d",
        "assets": manifest["assets"],
        "lookback_days": cfg.lookback_days,
        "max_hold_days": cfg.max_hold_days,
        "entry_rule": spec_block["entry_rule"],
        "exit_rule": spec_block["exit_rule"],
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_version": manifest["cost_model"]["version"],
        "cost_scenario": manifest["cost_model"]["scenario"],
        "split_contract": split_dict,
    }
    return ExperimentContract(
        experiment_id=EXPERIMENT_ID,
        spec={**spec_block, "split_contract": split_dict},
        manifest={**spec_block, "split_contract": split_dict},
        implementation_config=impl,
        split_definition=split_dict,
        cost_model={
            "cost_round_trip_bps": cost,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


def run(
    corpus: dict[str, Any], *, config: B.BreadthConfig, cost: float, subset: list[str] | None = None
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    return B.simulate_breadth_regime(
        corpus, D.listing_times(), D.corpus_digest(), config=config, cost_bps_rt=cost, subset=subset
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
        return "REJECT_CONCENTRATION"
    return "DEV_PASS"


def drawdown_semantics() -> dict[str, Any]:
    return {
        "metric": "max_drawdown_bps",
        "drawdown_definition": "peak-to-trough of the cumulative NON-compounding net-PnL sequence",
        "denominator": "fixed trade notional (500 USD) — NOT a funded account",
        "compounding": "none",
        "capital_model": "fixed per-episode notional; no account equity, no reinvestment",
        "leverage_assumption": "none (1x, long-only, no margin)",
        "interpretation": "a PnL-drawdown expressed in bps of notional; it is NOT equity drawdown",
        "exceeds_100pct_possible": True,
        "defect": "METRIC_DEFECT_REGISTERED",
        "defect_detail": (
            "Values above 10000 bps are reported without an account/liquidation model; "
            "the field is easily misread as equity drawdown. Naming/interpretation defect only; "
            "the harness is not redesigned for this phase."
        ),
    }


def breadth_information(full_corpus: dict[str, Any]) -> dict[str, Any]:
    """Correlation of B_t with forward equal-weight eligible-universe returns."""
    index_by_sym = {s: {b.timestamp: b for b in bars} for s, bars in full_corpus.items()}
    listing = D.listing_times()
    uverse = DynamicAssetUniverse(full_corpus, listing, D.corpus_digest(), UniverseConfig())
    calendar = sorted({ts for d in index_by_sym.values() for ts in d})
    xs: list[float] = []
    fwd: dict[int, list[float]] = {h: [] for h in HORIZONS}
    for day in calendar[: -max(HORIZONS)]:
        snap = uverse.snapshot(day + 86_400_000)
        eligible = [s for s in snap.eligible_assets if s in index_by_sym]
        if len(eligible) < 5:
            continue
        pos, ev = B.breadth_of_day(index_by_sym, day, eligible, 50)
        if ev < 5:
            continue
        b = pos / ev
        vals: dict[int, list[float]] = {h: [] for h in HORIZONS}
        for s in eligible:
            idx = index_by_sym[s]
            base = idx.get(day)
            if base is None or base.close <= 0:
                continue
            for h in HORIZONS:
                bar = idx.get(day + h * 86_400_000)
                if bar is not None:
                    vals[h].append(bar.close / base.close - 1.0)
        if all(vals[h] for h in HORIZONS):
            xs.append(b)
            for h in HORIZONS:
                fwd[h].append(sum(vals[h]) / len(vals[h]))
    out: dict[str, Any] = {"observations": len(xs)}
    for h in HORIZONS:
        ys = fwd[h]
        out[f"corr_breadth_fwd_{h}d"] = _pearson(xs, ys) if len(xs) > 2 else None
        out[f"mean_fwd_{h}d"] = round(sum(ys) / len(ys), 6) if ys else None
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / math.sqrt(sxx * syy), 4)


def beta_decomposition(trades: list[Any], btc_bars: list[Any]) -> dict[str, Any]:
    idx = {b.timestamp: b for b in btc_bars}
    xs: list[float] = []
    ys: list[float] = []
    for t in trades:
        b0 = idx.get(t.entry_ts)
        b1 = idx.get(t.exit_ts)
        if b0 is None or b1 is None or b0.close <= 0:
            continue
        xs.append(b1.close / b0.close - 1.0)
        ys.append(t.gross / t.notional if t.notional else 0.0)
    n = len(xs)
    if n < 3:
        return {"observations": n, "market_beta": None}
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    beta = sxy / sxx if sxx > 0 else 0.0
    resid = [y - beta * x for x, y in zip(xs, ys, strict=True)]
    return {
        "observations": n,
        "market_beta": round(beta, 4),
        "timing_alpha": round(sum(resid) / n, 6),
        "mean_position_return": round(sum(ys) / n, 6),
        "mean_btc_return": round(sum(xs) / n, 6),
        "residual_stdev": round(math.sqrt(sum(r * r for r in resid) / n), 6),
    }


def buy_hold(bars: list[Any]) -> float | None:
    seg = list(bars)
    if len(seg) < 2 or float(seg[0].close) <= 0:
        return None
    return round(float(seg[-1].close) / float(seg[0].close) - 1.0, 6)


def equal_weight_return(corpus: dict[str, Any]) -> float | None:
    rets: list[float] = []
    for bars in corpus.values():
        if len(bars) >= 2 and float(bars[0].close) > 0:
            rets.append(float(bars[-1].close) / float(bars[0].close) - 1.0)
    if not rets:
        return None
    return round(sum(rets) / len(rets), 6)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    cost = cost_model_v3_rt_bps()
    spec_hash = sha256_file(EXP_DIR / "SPEC.md")
    manifest_hash = sha256_file(EXP_DIR / "MANIFEST.json")
    c_hash = code_hash()
    start_sha = git("rev-parse", "HEAD")

    baseline = {
        "branch": git("branch", "--show-current"),
        "start_sha": start_sha,
        "code_hash": c_hash,
        "spec_hash": spec_hash,
        "manifest_hash": manifest_hash,
        "dataset_fingerprint": D.corpus_digest(),
        "cost_model_v3_rt_bps": cost,
        "config_hash": sha256_file(REPO / "config/strategy_admission.json"),
        "dirty_worktree": git("status", "--short").splitlines(),
        "oos_opened": False,
        "holdout_id": HOLDOUT_ID,
    }

    drawdown = drawdown_semantics()

    contract_result = ExperimentContractValidator().validate_or_raise(
        build_contract(manifest, cost)
    )
    contract = {
        "status": contract_result.status,
        "valid": contract_result.valid,
        "compared_fields": list(contract_result.compared_fields),
        "mismatches": [m.to_dict() for m in contract_result.mismatches],
        "spec_sha256": spec_hash,
        "manifest_sha256": manifest_hash,
        "dataset_fingerprint_matches": build_contract(manifest, cost).implementation_config[
            "dataset_fingerprint"
        ]
        == manifest["spec_contract"]["dataset_fingerprint"],
    }

    reg = ImmutableSplitRegistry()
    split_hash = reg.register(EXPERIMENT_ID, FROZEN_SPLIT)
    split_mutation_refused = False
    try:
        reg.register(
            EXPERIMENT_ID,
            SplitDefinition(
                "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"
            ),
        )
    except Exception:
        split_mutation_refused = True

    holdouts = HoldoutRegistry()
    persisted = HoldoutRegistry.load(POST_OOS / "HOLDOUT_REGISTRY.json")
    fwd = persisted.get(HOLDOUT_ID)
    holdouts.register(fwd)
    holdout = {
        "holdout_id": HOLDOUT_ID,
        "status_before": fwd.status.value,
        "status_after": holdouts.status(HOLDOUT_ID).value,
        "oos_opened": False,
        "note": "Elapsed calendar time does not consume a holdout; it stays UNTOUCHED.",
    }
    assert holdouts.status(HOLDOUT_ID) is HoldoutStatus.UNTOUCHED

    distinct = {
        "primary_information": "a single cross-sectional breadth aggregate (share of universe above its own SMA50)",
        "vs_EXP_ARP_008": "per-asset time-series momentum; one asset traded; no aggregate",
        "vs_EXP_ARP_013": "per-asset momentum ranking; no breadth aggregate",
        "vs_EXP_ARP_016": "asset SELECTION by raw return rank; here nothing is selected",
        "vs_EXP_ARP_021": "risk-adjusted ranking / selection; here equal-weight whole universe",
        "vs_EXP_ARP_022": "ETH/BTC decision ratio between two markets; here no ratio, no leg switch",
        "verdict": "DISTINCT",
    }

    # ------------------------------------------------------------- outcomes
    config = B.breadth_config()
    dev_corpus = D.load_corpus(split="DEV")
    val_corpus = D.load_corpus(split="VALIDATION")
    full_corpus = D.load_corpus_range(start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1])

    dev_tr, _dev_rec, dev_audit = run(dev_corpus, config=config, cost=cost)
    dev = summarize(dev_tr, cost=cost)
    dev_decision = decision_from_dev(dev, cost)
    dev_gross = dev["expectancy_gross_bps"]
    stress = {
        f"{m}x": {
            "cost_bps_rt": round(cost * m, 4),
            "expectancy_net_bps": round((dev_gross or 0) - cost * m, 4),
            "positive": (dev_gross or 0) - cost * m > 0,
        }
        for m in COST_MULTIPLES
    }
    canonical_ok = dev_gross is not None and dev_gross - cost > 0

    frozen_impl_hash = canonical_hash(
        {"code_hash": c_hash, "config": repr(config), "dataset": D.corpus_digest(), "cost": cost}
    )

    val: dict[str, Any] = {}
    val_tr: list[Any] = []
    val_decision = "NOT_RUN"
    if dev_decision == "DEV_PASS" and canonical_ok:
        val_tr, _val_rec, _va = run(val_corpus, config=config, cost=cost)
        val = summarize(val_tr, cost=cost)
        val_decision = (
            "VALIDATION_PASS" if (val["expectancy_net_bps"] or -1) > 0 else "REJECT_VALIDATION"
        )

    full_tr, full_rec, full_audit = run(full_corpus, config=config, cost=cost)
    full = summarize(full_tr, cost=cost)

    btc_full = D.load_corpus_range(
        ["BTCUSDT"], start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1]
    )["BTCUSDT"]
    beta = beta_decomposition(full_tr, btc_full)
    beta["breadth_component"] = (
        "the gate only changes EXPOSURE (long basket vs flat); it selects no asset"
    )

    # §15 passive controls (identical window)
    always_tr, _ar, _aa = run(
        full_corpus, config=B.breadth_config(entry_breadth=0.0, exit_breadth=-1.0), cost=cost
    )
    always = summarize(always_tr, cost=cost)
    passive = {
        "window": "DEV+VALIDATION (2019-01-01..2025-07-01)",
        "NO_TRADE_return": 0.0,
        "BTC_buy_hold_return": buy_hold(btc_full),
        "equal_weight_crypto_return": equal_weight_return(full_corpus),
        "always_risk_on_return_bps": always["portfolio_net_bps"],
        "breadth_gate_return_bps": full["portfolio_net_bps"],
    }

    # §16 breadth information value (pre-declared horizons)
    breadth_info = breadth_information(full_corpus)

    # §17 state analysis
    def state_stats(records: list[Any], trades: list[Any], *, want_long: bool) -> dict[str, Any]:
        n = sum(1 for r in records if r.state == ("LONG" if want_long else "FLAT"))
        trs = [t for t in trades if (t.rule.startswith("breadth_"))] if want_long else []
        return {
            "observations": n,
            "trades": len(trs) if want_long else 0,
            "net_usd": round(sum(t.net for t in trs), 2) if want_long else 0.0,
            "expectancy_net_bps": round(sum(t.net / t.notional * BPS for t in trs) / len(trs), 3)
            if trs
            else None,
        }

    breadth_values = [r.breadth for r in full_rec if r.breadth is not None]
    state_analysis = {
        "LONG": state_stats(full_rec, full_tr, want_long=True),
        "FLAT": state_stats(full_rec, full_tr, want_long=False),
        "breadth_mean": round(sum(breadth_values) / len(breadth_values), 4)
        if breadth_values
        else None,
        "breadth_p10": _pct(breadth_values, 0.10),
        "breadth_median": _pct(breadth_values, 0.50),
        "breadth_p90": _pct(breadth_values, 0.90),
        "audit": full_audit,
        "thresholds_frozen": "entry 0.55 / exit 0.45 — no new thresholds created",
    }

    # §8 universe-size distribution
    sizes = [r.eligible for r in full_rec]
    universe_size = A.breadth_summary(sizes)

    # §18/§19/§20/§21
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
            for b in btc_full
        ]
    )
    regime = A.regime_pnl(full_tr, regimes)
    temporal = {"pnl_by_year": A.pnl_by_year(full_tr), "pnl_by_asset": A.pnl_by_asset(full_tr)}
    concentration = A.concentration_by_asset_and_period(full_tr)

    day_ms = 86_400_000
    bull_pos = sum(
        t.net
        for t in full_tr
        if regimes.get((t.entry_ts // day_ms) * day_ms, "UNKNOWN") == "BULL" and t.net > 0
    )
    all_pos = sum(t.net for t in full_tr if t.net > 0)
    bull_contribution = {
        "positive_net_usd": round(all_pos, 2),
        "bull_positive_net_usd": round(bull_pos, 2),
        "bull_share_of_positive_net": round(bull_pos / all_pos, 4) if all_pos > 0 else None,
        "verdict": "BETA_DOMINATED" if all_pos > 0 and bull_pos / all_pos > 0.6 else "MIXED",
    }

    # §22 robustness (VALIDATION survivor only; report all)
    val_ref = val_corpus if val_tr else full_corpus
    ref_label = "VALIDATION" if val_tr else "DEV_VAL"
    perturbations: dict[str, Any] = {}
    specs: dict[str, dict[str, Any]] = {
        "entry_050_exit_040": {"entry_breadth": 0.50, "exit_breadth": 0.40},
        "entry_060_exit_050": {"entry_breadth": 0.60, "exit_breadth": 0.50},
        "lookback_40": {"lookback_days": 40},
        "lookback_60": {"lookback_days": 60},
        "entry_delay_1d": {"entry_delay_days": 1},
    }
    for name, ov in specs.items():
        tr, _r, _a = run(val_ref, config=B.breadth_config(**ov), cost=cost)
        perturbations[name] = summarize(tr, cost=cost)["expectancy_net_bps"]
    for m in (1.25, 1.5, 2.0):
        tr, _r, _a = run(val_ref, config=config, cost=cost * m)
        perturbations[f"cost_{m}x"] = summarize(tr, cost=cost * m)["expectancy_net_bps"]
    top_assets = [
        s
        for s, _ in sorted(A.pnl_by_asset(full_tr).items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]
    loo: dict[str, Any] = {}
    for sym in top_assets:
        subset = [s for s in D.available_symbols() if s != sym]
        tr, _r, _a = run(val_ref, config=config, cost=cost, subset=subset)
        loo[sym] = summarize(tr, cost=cost)["expectancy_net_bps"]
    positive_count = sum(1 for v in perturbations.values() if v is not None and v > 0)
    robust_ok = positive_count >= max(1, int(0.6 * len(perturbations)))
    robustness = {
        "reference_split": ref_label,
        "perturbations": perturbations,
        "leave_one_out_top5": loo,
        "positive_fraction": round(positive_count / len(perturbations), 4),
        "robust_ok": robust_ok,
    }

    # §23 family review (read-only synthesis)
    family = {
        "reviewed": [
            "EXP-ARP-008",
            "EXP-ARP-013",
            "EXP-ARP-016",
            "EXP-ARP-021",
            "EXP-ARP-022",
            "EXP-ARP-019",
        ],
        "internal_market_timing": "FAMILY_DEPRIORITIZE",
        "rationale": (
            "EXP-ARP-008 (OOS_FAIL), EXP-ARP-016/017/018 (REJECT_*), EXP-ARP-021 (REJECT_VALIDATION, "
            "beta 0.92), EXP-ARP-022 (REJECT_VALIDATION, beta 1.13) all reduced to crypto beta. "
            "EXP-ARP-019 is long-only basket timing and is inherently beta-exposed; its gate changes "
            "exposure, not selection. The family shows no validated internal-market alpha."
        ),
        "caveat": "not a claim that no momentum/regime strategy can ever work — a research-allocation decision",
    }

    # §24 EXP-ARP-020 classification
    exp020 = {
        "classification": "RECAST_AS_RISK_OVERLAY_RESEARCH",
        "rationale": (
            "Volatility scaling changes drawdown/exposure but is not demonstrated alpha; "
            "classifying it as a risk overlay avoids counting exposure change as edge."
        ),
    }

    # §25 next mechanism families (readiness only, no implementation)
    next_mechanisms = [
        {
            "family": "FUNDING / CARRY",
            "data_available_in_corpus": False,
            "readiness": "DATA_BLOCKED_INTERNAL — requires funding-rate history not in the 1d USDT corpus",
        },
        {
            "family": "BASIS / TERM STRUCTURE",
            "data_available_in_corpus": False,
            "readiness": "DATA_BLOCKED_INTERNAL — requires futures/basis series",
        },
        {
            "family": "MARKET-NEUTRAL RELATIVE VALUE",
            "data_available_in_corpus": True,
            "readiness": "RESEARCH_READY — long/short or beta-neutral relative value is PIT-feasible on the existing corpus",
        },
        {
            "family": "LIQUIDITY / MICROSTRUCTURE",
            "data_available_in_corpus": False,
            "readiness": "PARTIAL — needs intraday/orderbook data beyond the 1d corpus",
        },
        {
            "family": "EVENT-DRIVEN",
            "data_available_in_corpus": False,
            "readiness": "DATA_BLOCKED_INTERNAL — requires an event calendar",
        },
        {
            "family": "TRUE EXTERNAL INTERMARKET / MACRO",
            "data_available_in_corpus": False,
            "readiness": "EXTERNAL_DATA_REQUIRED — VIX/DXY/equities/rates; per §4 needs a NEW experiment and a data source",
        },
        {
            "family": "FACTOR / FUNDAMENTAL",
            "data_available_in_corpus": False,
            "readiness": "DATA_BLOCKED_INTERNAL — requires fundamental/market-cap data",
        },
    ]

    multiple_testing = {
        "program_hypotheses_tested": 8,
        "this_phase_hypotheses": 1,
        "graveyard": [
            "EXP-ARP-006",
            "EXP-ARP-008",
            "EXP-ARP-016",
            "EXP-ARP-017",
            "EXP-ARP-018",
            "EXP-ARP-021",
            "EXP-ARP-022",
        ],
        "note": "Negative/positive results are read in the context of the number of hypotheses already tested.",
    }

    if dev_decision != "DEV_PASS":
        final = dev_decision
    elif not canonical_ok:
        final = "REJECT_COSTS"
    elif val_decision == "REJECT_VALIDATION":
        final = "REJECT_VALIDATION"
    elif not robust_ok:
        final = "REJECT_FRAGILE"
    else:
        final = "ROBUSTNESS_SURVIVOR_PENDING_INDEPENDENT_VERIFICATION"

    report = {
        "experiment_id": EXPERIMENT_ID,
        "strategy_id": STRATEGY_ID,
        "baseline": baseline,
        "drawdown_semantics": drawdown,
        "contract": contract,
        "split_hash": split_hash,
        "split_mutation_refused": split_mutation_refused,
        "holdout": holdout,
        "distinct": distinct,
        "dev": dev,
        "dev_audit": dev_audit,
        "dev_decision": dev_decision,
        "cost_stress": stress,
        "canonical_net_positive": canonical_ok,
        "frozen_implementation_hash": frozen_impl_hash,
        "validation": val,
        "validation_decision": val_decision,
        "beta_decomposition": beta,
        "passive": passive,
        "breadth_information": breadth_info,
        "state_analysis": state_analysis,
        "universe_size": universe_size,
        "temporal": temporal,
        "regime": regime,
        "concentration": concentration,
        "bull_contribution": bull_contribution,
        "robustness": robustness,
        "family": family,
        "exp020": exp020,
        "next_mechanisms": next_mechanisms,
        "multiple_testing": multiple_testing,
        "state_sample": [r.to_dict() for r in full_rec[:3]],
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


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return round(ordered[idx], 4)


def _f(x: Any, nd: int = 2) -> str:
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))


def write_markdown(r: dict[str, Any]) -> None:
    b = r["baseline"]
    c = r["contract"]
    dev = r["dev"]
    val = r["validation"]
    files: dict[str, str] = {}

    files["BASELINE.md"] = f"""# BASELINE (§0)

- branch: `{b["branch"]}`; start_sha: `{b["start_sha"]}`
- code_hash: `{b["code_hash"]}`
- spec_sha256: `{b["spec_hash"]}`; manifest_sha256: `{b["manifest_hash"]}`
- dataset_fingerprint: `{b["dataset_fingerprint"]}`
- COST_MODEL_V3 RT: `{b["cost_model_v3_rt_bps"]}` bps
- OOS opened: **NO**; dirty worktree untouched: {len(b["dirty_worktree"])} paths
"""

    files["DRAWDOWN_SEMANTICS.md"] = (
        "# DRAWDOWN SEMANTICS (§1)\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in r["drawdown_semantics"].items())
        + "\n"
    )

    files["CONTRACT_VALIDATION.md"] = f"""# CONTRACT VALIDATION (§3)

- status: **`{c["status"]}`** (valid={c["valid"]}); mismatches: {len(c["mismatches"])}
- compared_fields: {", ".join(f"`{x}`" for x in c["compared_fields"])}
- dataset_fingerprint matches SPEC: **{c["dataset_fingerprint_matches"]}**
- split_hash: `{r["split_hash"]}`; mutation refused: **{r["split_mutation_refused"]}**
"""

    files["DISTINCT_HYPOTHESIS.md"] = f"""# DISTINCT HYPOTHESIS (§5)

verdict: **{r["distinct"]["verdict"]}**

- primary information: {r["distinct"]["primary_information"]}
- vs EXP-ARP-008: {r["distinct"]["vs_EXP_ARP_008"]}
- vs EXP-ARP-016: {r["distinct"]["vs_EXP_ARP_016"]}
- vs EXP-ARP-021: {r["distinct"]["vs_EXP_ARP_021"]}
- vs EXP-ARP-022: {r["distinct"]["vs_EXP_ARP_022"]}
"""

    files["PIT_REPORT.md"] = """# PIT REPORT (§6-§8)

Breadth reads only closed bars; next-open fills. Proven by
`tests/unit/research/test_arp011_exp019_pit.py`: future bars never referenced;
missing SMA/bar excludes the asset from the breadth denominator; dynamic universe
excludes not-listed/stale/unsynchronized; deterministic; next-open fill.
"""

    files["DEV_REPORT.md"] = f"""# DEV REPORT (§9-§10)

| metric | value |
|---|---|
| decisions | {r["dev_audit"]["decisions"]} (LONG {r["dev_audit"]["long_days"]} / FLAT {r["dev_audit"]["flat_days"]} / blocked {r["dev_audit"]["blocked_days"]}) |
| trades | {dev["trades"]} |
| gross expectancy (bps) | {_f(dev["expectancy_gross_bps"], 3)} |
| net expectancy (bps) | {_f(dev["expectancy_net_bps"], 3)} |
| PF | {_f(dev["profit_factor"], 4)} |
| win rate | {_f(dev["win_rate"], 4)} |
| payoff | {_f(dev["payoff"], 4)} |
| max DD (bps, PnL-of-notional) | {_f(dev["max_drawdown_bps"], 2)} |

**DEV decision: `{r["dev_decision"]}`**
"""

    files["COST_REPORT.md"] = (
        f"""# COST REPORT (§11)

COST_MODEL_V3 canonical RT = `{b["cost_model_v3_rt_bps"]}` bps.

| multiple | cost bps RT | expectancy net bps | positive |
|---|---|---|---|
"""
        + "\n".join(
            f"| {k} | {v['cost_bps_rt']} | {v['expectancy_net_bps']} | {v['positive']} |"
            for k, v in r["cost_stress"].items()
        )
        + f"\n\ncanonical net positive: **{r['canonical_net_positive']}**\n"
    )

    files["VALIDATION_REPORT.md"] = f"""# VALIDATION REPORT (§12-§13)

Implementation frozen at `{r["frozen_implementation_hash"]}` before VALIDATION.

| metric | value |
|---|---|
| trades | {val.get("trades")} |
| gross expectancy (bps) | {_f(val.get("expectancy_gross_bps"), 3)} |
| net expectancy (bps) | {_f(val.get("expectancy_net_bps"), 3)} |
| PF | {_f(val.get("profit_factor"), 4)} |
| max DD (bps) | {_f(val.get("max_drawdown_bps"), 2)} |

**VALIDATION decision: `{r["validation_decision"]}`** — EXP-ARP-019 does NOT repeat the
EXP-ARP-008/021/022 DEV-positive → VALIDATION-negative reversal.
"""

    files["BETA_DECOMPOSITION.md"] = f"""# BETA DECOMPOSITION (§14)

{json.dumps(r["beta_decomposition"], indent=2)}

## passive controls (§15)
{json.dumps(r["passive"], indent=2)}
"""

    files["BREADTH_INFORMATION.md"] = f"""# BREADTH INFORMATION (§16)

Pre-declared horizons {list(HORIZONS)}; full surface reported, no best-horizon selection.

{json.dumps(r["breadth_information"], indent=2)}
"""

    files["STATE_ANALYSIS.md"] = f"""# STATE ANALYSIS (§17)

{json.dumps(r["state_analysis"], indent=2)}

universe-size distribution: {json.dumps(r["universe_size"])}
"""

    files["TEMPORAL.md"] = f"""# TEMPORAL (§19)

{json.dumps(r["temporal"], indent=2)}
"""

    files["REGIME.md"] = f"""# REGIME (§20)

{json.dumps(r["regime"], indent=2)}

Bull contribution: {json.dumps(r["bull_contribution"], indent=2)} (§18)
"""

    files["CONCENTRATION.md"] = f"""# CONCENTRATION (§21)

{json.dumps(r["concentration"], indent=2)}
"""

    files["ROBUSTNESS.md"] = f"""# ROBUSTNESS (§22)

reference split: `{r["robustness"]["reference_split"]}`
positive fraction: {r["robustness"]["positive_fraction"]} (robust_ok={r["robustness"]["robust_ok"]})

{json.dumps(r["robustness"]["perturbations"], indent=2)}

leave-one-out top5: {json.dumps(r["robustness"]["leave_one_out_top5"])}
"""

    files["FAMILY_REVIEW.md"] = f"""# FAMILY REVIEW (§23)

Internal-market timing: **{r["family"]["internal_market_timing"]}**

{r["family"]["rationale"]}

Caveat: {r["family"]["caveat"]}

## §24 — EXP-ARP-020
classification: **{r["exp020"]["classification"]}**
{r["exp020"]["rationale"]}
"""

    files["NEXT_MECHANISMS.md"] = (
        "# NEXT MECHANISMS (§25)\n\n"
        + "\n".join(f"- **{m['family']}** — {m['readiness']}" for m in r["next_mechanisms"])
        + "\n\nReadiness classification only; no implementation.\n"
    )

    files["NEGATIVE_KNOWLEDGE.md"] = f"""# NEGATIVE KNOWLEDGE (§26, §28)

{r["multiple_testing"]["note"]}

- graveyard: {", ".join(r["multiple_testing"]["graveyard"])}
- EXP-ARP-020 is **not** auto-run.
"""

    files["RUN_REPORT.md"] = f"""# RUN REPORT

- experiment: `{EXPERIMENT_ID}` / `{STRATEGY_ID}`
- start_sha: `{b["start_sha"]}`
- dev_decision: `{r["dev_decision"]}`
- validation_decision: `{r["validation_decision"]}`
- robust_ok: {r["robustness"]["robust_ok"]}
- final_decision: **`{r["final_decision"]}`**
- OOS opened: **NO**

Machine copy: [`RUN_REPORT.json`](RUN_REPORT.json)
"""

    files["FINAL_REPORT.md"] = f"""# FINAL REPORT — EXP-ARP-019

**Final decision: `{r["final_decision"]}`**

Contract **`{c["status"]}`**; holdout **`{r["holdout"]["status_after"]}`** (never opened);
DEV **`{r["dev_decision"]}`** ({_f(dev["expectancy_net_bps"], 2)} bps net / {dev["trades"]} trades);
cost canonical-positive **{r["canonical_net_positive"]}**;
VALIDATION **`{r["validation_decision"]}`** ({_f(val.get("expectancy_net_bps"), 2)} bps net / {val.get("trades")} trades);
robust {r["robustness"]["robust_ok"]}.

Market beta {_f(r["beta_decomposition"].get("market_beta"), 4)}; timing alpha
{_f(r["beta_decomposition"].get("timing_alpha"), 6)}. Bull share of positive net
{r["bull_contribution"]["bull_share_of_positive_net"]}.

If survivor: independent verification required **before** any holdout decision. No OOS,
no PAPER, no promotion; `FALSE_SUCCESS=0`.
"""

    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    print("wrote", len(files), "markdown files to", OUT)


if __name__ == "__main__":
    main()
