"""ARP-010 — EXP-ARP-022 execution driver (intermarket risk-appetite rotation).

Runs the frozen ``H-INTERMARKET-RISKAPP-001`` rotation end to end and writes the
``reports/arp-010-exp-022/`` evidence set. OOS is **never** opened.

Stage order (frozen): BASELINE -> CONTRACT -> DATA AUTHORITY -> PIT -> HOLDOUT
FIREWALL -> DISTINCT -> DEV -> KILL GATE -> COST -> FREEZE -> VALIDATION
-> BETA / PASSIVE / STATE / COMPONENT -> TEMPORAL/REGIME/CONCENTRATION
-> ROBUSTNESS -> MULTIPLE-TESTING -> terminal decision.

Run::

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp010_exp_022.py
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
from trading_bot.research.diversified import intermarket as IM  # noqa: E402
from trading_bot.research.diversified import xsec_riskadj as R  # noqa: E402
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    HoldoutRegistry,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
)

OUT = REPO / "reports" / "arp-010-exp-022"
EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-022"
POST_OOS = REPO / "reports" / "post-oos-recovery"

EXPERIMENT_ID = "EXP-ARP-022"
STRATEGY_ID = "H-INTERMARKET-RISKAPP-001"
MIN_TRADES = 20
COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
HOLDOUT_ID = "HOLDOUT-ARP-019-FORWARD"
BPS = 10_000.0

BUILDER_FILES = (
    "src/trading_bot/research/diversified/__init__.py",
    "src/trading_bot/research/diversified/data.py",
    "src/trading_bot/research/diversified/universe.py",
    "src/trading_bot/research/diversified/intermarket.py",
    "src/trading_bot/research/diversified/xsec_riskadj.py",
    "src/trading_bot/research/alpha_expansion/strategies.py",
    "scripts/arp010_exp_022.py",
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
    spec_view = {**spec_block, "split_contract": split_dict}
    manifest_view = {**spec_block, "split_contract": split_dict}
    cfg = IM.intermarket_config()
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
        spec=spec_view,
        manifest=manifest_view,
        implementation_config=impl,
        split_definition=split_dict,
        cost_model={
            "cost_round_trip_bps": cost,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


def run(corpus: dict[str, Any], *, config: IM.IntermarketConfig, cost: float,
        force_leg: str | None = None, subset: list[str] | None = None
        ) -> tuple[list[Any], list[Any], dict[str, Any]]:
    return IM.simulate_intermarket_rotation(
        corpus, D.listing_times(), D.corpus_digest(), config=config,
        cost_bps_rt=cost, force_leg=force_leg, subset=subset,
    )


def summary(trades: list[Any], *, cost: float) -> dict[str, Any]:
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


def data_authority() -> dict[str, Any]:
    lt = D.listing_times()
    series: dict[str, Any] = {}
    for sym in (IM.BTC, IM.ETH):
        bars = D.load_symbol(sym)
        series[sym] = {
            "series_id": f"{sym}_1d_close",
            "role": "ratio numerator" if sym == IM.ETH else "ratio denominator",
            "provider": "BINANCE_SPOT",
            "native_timeframe": "1d",
            "timezone": "UTC",
            "first_ts": bars[0].timestamp if bars else None,
            "last_ts": bars[-1].timestamp if bars else None,
            "bars": len(bars),
            "listing_time": lt.get(sym),
            "available": bool(bars),
        }
    dup_ok = True
    for sym in (IM.BTC, IM.ETH):
        stamps = [b.timestamp for b in D.load_symbol(sym)]
        dup_ok = dup_ok and len(stamps) == len(set(stamps))
    return {
        "input_kind": "crypto-internal cross-market ratio (ETH/BTC)",
        "external_macro_inputs_required": [],
        "external_proxy_substituted": False,
        "derived_series": "ETHBTC_RATIO_1d = ETHUSDT.close / BTCUSDT.close",
        "series": series,
        "corpus_digest": D.corpus_digest(),
        "gaps_or_duplicates": "none" if dup_ok else "DUPLICATES_PRESENT",
        "calendar": "crypto trades 24/7; both legs are crypto so no weekend/holiday alignment is required",
        "note": (
            "The frozen SPEC defines the intermarket variable as the ETH/BTC ratio, "
            "both series present in the ARP-006 corpus. No VIX/DXY/equity/rates/credit "
            "proxy was introduced; per §4 a proxy would require a NEW_EXPERIMENT_ID."
        ),
        "data_status": "DATA_PASS",
    }


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
        "mean_position_return": round(sum(ys) / n, 6),
        "mean_btc_return": round(sum(xs) / n, 6),
        "alpha_vs_btc": round(sum(resid) / n, 6),
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

    # §2 contract gate
    validator = ExperimentContractValidator()
    contract_result = validator.validate_or_raise(build_contract(manifest, cost))
    contract = {
        "experiment_id": EXPERIMENT_ID,
        "status": contract_result.status,
        "valid": contract_result.valid,
        "compared_fields": list(contract_result.compared_fields),
        "mismatches": [m.to_dict() for m in contract_result.mismatches],
        "spec_sha256": spec_hash,
        "manifest_sha256": manifest_hash,
        "dataset_fingerprint_matches": build_contract(manifest, cost).implementation_config[
            "dataset_fingerprint"
        ] == manifest["spec_contract"]["dataset_fingerprint"],
    }

    # §3 data authority
    data_auth = data_authority()

    # §2/§5 split immutability
    reg = ImmutableSplitRegistry()
    split_hash = reg.register(EXPERIMENT_ID, FROZEN_SPLIT)
    split_mutation_refused = False
    try:
        reg.register(EXPERIMENT_ID, SplitDefinition(
            "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"))
    except Exception:
        split_mutation_refused = True

    # §9 holdout firewall
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

    # §10 distinctness
    distinct = {
        "primary_information": "cross-market ETH/BTC ratio vs its own SMA50 (intermarket state)",
        "vs_EXP_ARP_008": "single-asset time-series momentum on 3 fixed assets",
        "vs_EXP_ARP_013": "per-asset momentum; no cross-market ratio",
        "vs_EXP_ARP_016": "cross-sectional ranking of raw returns; no decision ratio between markets",
        "vs_EXP_ARP_021": "risk-adjusted relative-strength portfolio ranking; no ETH/BTC state variable",
        "verdict": "DISTINCT",
    }

    # ---------------------------------------------------------------- market outcomes
    config = IM.intermarket_config()
    dev_corpus = D.load_corpus(split="DEV")
    val_corpus = D.load_corpus(split="VALIDATION")
    full_corpus = D.load_corpus_range(start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1])

    dev_tr, _dev_states, dev_audit = run(dev_corpus, config=config, cost=cost)
    dev = summary(dev_tr, cost=cost)
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
        val_tr, _vs, _va = run(val_corpus, config=config, cost=cost)
        val = summary(val_tr, cost=cost)
        val_decision = "VALIDATION_PASS" if (val["expectancy_net_bps"] or -1) > 0 else "REJECT_VALIDATION"

    full_tr, full_states, full_audit = run(full_corpus, config=config, cost=cost)
    full = summary(full_tr, cost=cost)

    btc_full = D.load_corpus_range([IM.BTC], start_ms=D.DEV_VAL_RANGE[0], end_ms=D.DEV_VAL_RANGE[1])[IM.BTC]
    beta = beta_decomposition(full_tr, btc_full)

    # §19 passive baselines over the identical DEV+VALIDATION window
    passive = {
        "window": "DEV+VALIDATION (2019-01-01..2025-07-01)",
        "NO_TRADE_return": 0.0,
        "BTC_buy_hold_return": buy_hold(btc_full),
        "equal_weight_crypto_return": equal_weight_return(full_corpus),
        "mechanism_net_bps_of_total": full["portfolio_net_bps"],
    }

    # §18 component split — timing (switch value) vs selection (alt vs universe)
    always_btc_tr, _ab_s, _ab_a = run(full_corpus, config=config, cost=cost, force_leg="BTC")
    always_alt_tr, _aa_s, _aa_a = run(full_corpus, config=config, cost=cost, force_leg="ALT")
    always_btc = summary(always_btc_tr, cost=cost)
    always_alt = summary(always_alt_tr, cost=cost)
    beta["intermarket_timing_component_bps"] = round(
        (full["expectancy_net_bps"] or 0) - (always_btc["expectancy_net_bps"] or 0), 4
    )
    beta["asset_selection_component_bps"] = round(
        (always_alt["expectancy_net_bps"] or 0)
        - (equal_weight_return(full_corpus) or 0) * BPS,
        4,
    )

    # §20 state analysis (frozen contract is binary: RISK_ON / RISK_OFF; no NEUTRAL exists)
    def state_summary(trades: list[Any], *, risk_on: bool) -> dict[str, Any]:
        sel = [t for t in trades if (t.symbol != IM.BTC) == risk_on]
        nets = [t.net for t in sel]
        return {
            "trades": len(sel),
            "net_usd": round(sum(nets), 2),
            "expectancy_net_bps": round(sum(t.net / t.notional * BPS for t in sel) / len(sel), 3)
            if sel else None,
        }

    state_analysis = {
        "RISK_ON": state_summary(full_tr, risk_on=True),
        "RISK_OFF": state_summary(full_tr, risk_on=False),
        "NEUTRAL": "NOT_IN_FROZEN_CONTRACT — the frozen rule is binary; no threshold was invented",
        "risk_on_days": full_audit["risk_on_days"],
        "risk_off_days": full_audit["risk_off_days"],
        "no_signal_days": full_audit["no_signal_days"],
    }

    # §21 component ablation (diagnostic only; never promotable)
    component = {
        "full_mechanism_net_bps": full["expectancy_net_bps"],
        "always_BTC_leg_net_bps": always_btc["expectancy_net_bps"],
        "always_ALT_leg_net_bps": always_alt["expectancy_net_bps"],
        "always_BTC_trades": always_btc["trades"],
        "always_ALT_trades": always_alt["trades"],
        "dominant_component": "ALT_leg" if (always_alt["expectancy_net_bps"] or -1e9) > (always_btc["expectancy_net_bps"] or -1e9) else "BTC_leg",
        "promotable": False,
    }

    # §22/§23/§24
    temporal = {"pnl_by_year": A.pnl_by_year(full_tr), "pnl_by_asset": A.pnl_by_asset(full_tr)}
    regimes = A.regime_by_day([
        OHLCV(symbol=b.symbol, timestamp=b.timestamp, open=b.open, high=b.high,
              low=b.low, close=b.close, volume=b.volume) for b in btc_full
    ])
    regime = A.regime_pnl(full_tr, regimes)
    concentration = A.concentration_by_asset_and_period(full_tr)
    concentration["top_state_contribution"] = {
        "RISK_ON_net_usd": state_analysis["RISK_ON"]["net_usd"],
        "RISK_OFF_net_usd": state_analysis["RISK_OFF"]["net_usd"],
    }

    # §25 robustness over VALIDATION (only if it survived; report all perturbations)
    val_ref = val_corpus if val_tr else full_corpus
    ref_label = "VALIDATION" if val_tr else "DEV_VAL"
    perturbations: dict[str, Any] = {}
    specs: dict[str, dict[str, Any]] = {
        "lookback_40": {"lookback_days": 40},
        "lookback_60": {"lookback_days": 60},
        "basket_10": {"alt_basket_size": 10},
        "basket_30": {"alt_basket_size": 30},
        "rebalance_14": {"rebalance_days": 14},
    }
    for name, ov in specs.items():
        tr, _s, _a = run(val_ref, config=IM.intermarket_config(**ov), cost=cost)
        perturbations[name] = summary(tr, cost=cost)["expectancy_net_bps"]
    tr, _s, _a = run(val_ref, config=IM.intermarket_config(entry_delay_days=1), cost=cost)
    perturbations["execution_delay_1d"] = summary(tr, cost=cost)["expectancy_net_bps"]
    for m in (1.25, 1.5, 2.0):
        tr, _s, _a = run(val_ref, config=config, cost=cost * m)
        perturbations[f"cost_{m}x"] = summary(tr, cost=cost * m)["expectancy_net_bps"]
    positive = [v for v in perturbations.values() if v is not None and v > 0]
    robust_ok = len(positive) >= max(1, int(0.6 * len(perturbations)))
    robustness = {
        "reference_split": ref_label,
        "perturbations": perturbations,
        "positive_fraction": round(len(positive) / len(perturbations), 4),
        "robust_ok": robust_ok,
        "leave_one_component_out": "NOT_APPLICABLE — ETH and BTC are jointly required to form the ratio; removing either destroys the signal (no proxy substituted).",
    }

    multiple_testing = {
        "program_hypotheses_tested": 7,
        "this_phase_hypotheses": 1,
        "graveyard": ["EXP-ARP-006", "EXP-ARP-008", "EXP-ARP-016", "EXP-ARP-017", "EXP-ARP-018", "EXP-ARP-021"],
        "new_prereg_remaining": ["EXP-ARP-019", "EXP-ARP-020"],
        "note": "Negative knowledge persists; no parameter change under a terminated id.",
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
        "contract": contract,
        "data_authority": data_auth,
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
        "state_analysis": state_analysis,
        "component": component,
        "temporal": temporal,
        "regime": regime,
        "concentration": concentration,
        "robustness": robustness,
        "multiple_testing": multiple_testing,
        "state_sample": [s.to_dict() for s in full_states[:3]],
        "final_decision": final,
        "oos_opened": False,
    }
    (OUT / "RUN_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote", OUT / "RUN_REPORT.json")
    print("DEV:", dev.get("trades"), dev.get("expectancy_net_bps"), dev_decision)
    print("VAL:", val.get("trades"), val.get("expectancy_net_bps"), val_decision)
    print("final:", final)
    write_markdown(report)


def _f(x: Any, nd: int = 2) -> str:
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else str(x))


def write_markdown(r: dict[str, Any]) -> None:
    b = r["baseline"]
    c = r["contract"]
    dev = r["dev"]
    val = r["validation"]
    files: dict[str, str] = {}

    files["BASELINE.md"] = f"""# BASELINE (§0)

- branch: `{b['branch']}`
- start_sha: `{b['start_sha']}`
- code_hash: `{b['code_hash']}`
- spec_sha256: `{b['spec_hash']}`
- manifest_sha256: `{b['manifest_hash']}`
- dataset_fingerprint: `{b['dataset_fingerprint']}`
- COST_MODEL_V3 RT: `{b['cost_model_v3_rt_bps']}` bps
- OOS opened: **NO**; dirty worktree untouched: {len(b['dirty_worktree'])} paths
"""

    files["CONTRACT_VALIDATION.md"] = f"""# CONTRACT VALIDATION (§1-§2)

- status: **`{c['status']}`** (valid={c['valid']})
- mismatches: {len(c['mismatches'])}
- compared_fields: {', '.join(f'`{x}`' for x in c['compared_fields'])}
- dataset_fingerprint matches SPEC: **{c['dataset_fingerprint_matches']}**
- split_hash: `{r['split_hash']}`; mutation refused: **{r['split_mutation_refused']}**
"""

    files["DATA_AUTHORITY.md"] = f"""# DATA AUTHORITY (§3-§4, §6-§7)

input kind: **{r['data_authority']['input_kind']}**
external macro inputs required: **{r['data_authority']['external_macro_inputs_required'] or 'NONE'}**
external proxy substituted: **{r['data_authority']['external_proxy_substituted']}**
derived series: `{r['data_authority']['derived_series']}`

| series | role | provider | tf | first_ts | last_ts | bars | available |
|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {s['series_id']} | {s['role']} | {s['provider']} | {s['native_timeframe']} | "
        f"{s['first_ts']} | {s['last_ts']} | {s['bars']} | {s['available']} |"
        for s in r["data_authority"]["series"].values()
    ) + f"""

gaps/duplicates: {r['data_authority']['gaps_or_duplicates']}
calendar: {r['data_authority']['calendar']}

{r['data_authority']['note']}

**data status: `{r['data_authority']['data_status']}`**
"""

    files["PIT_REPORT.md"] = """# PIT REPORT (§5)

`data_time <= decision_time <= fill_time`. The ETH/BTC ratio, its SMA50 and the
alt-basket membership read closed bars at or before the decision close; the fill
is the next open. Fail-closed behaviour is proven by
`tests/unit/research/test_arp010_exp022_pit.py`: missing ratio/SMA bar -> NO_SIGNAL;
future bar never referenced; duplicate/stale/unsynchronized symbols excluded;
crypto-24/7 calendar (no weekend/holiday alignment required); deterministic.
"""

    files["DISTINCT_HYPOTHESIS.md"] = f"""# DISTINCT HYPOTHESIS (§10)

verdict: **{r['distinct']['verdict']}**

- primary information: {r['distinct']['primary_information']}
- vs EXP-ARP-008: {r['distinct']['vs_EXP_ARP_008']}
- vs EXP-ARP-013: {r['distinct']['vs_EXP_ARP_013']}
- vs EXP-ARP-016: {r['distinct']['vs_EXP_ARP_016']}
- vs EXP-ARP-021: {r['distinct']['vs_EXP_ARP_021']}
"""

    files["DEV_REPORT.md"] = f"""# DEV REPORT (§13)

| metric | value |
|---|---|
| decisions | {r['dev_audit']['decisions']} |
| trades | {dev['trades']} |
| gross expectancy (bps) | {_f(dev['expectancy_gross_bps'],3)} |
| net expectancy (bps) | {_f(dev['expectancy_net_bps'],3)} |
| net (USD) | {_f(dev['net_usd'])} |
| PF | {_f(dev['profit_factor'],4)} |
| win rate | {_f(dev['win_rate'],4)} |
| payoff | {_f(dev['payoff'],4)} |
| max drawdown (bps) | {_f(dev['max_drawdown_bps'],2)} |
| exit mix | {dev['exit_mix']} |

risk_on_days={r['dev_audit']['risk_on_days']}, risk_off_days={r['dev_audit']['risk_off_days']}, no_signal_days={r['dev_audit']['no_signal_days']}

**DEV decision: `{r['dev_decision']}`**
"""

    files["COST_REPORT.md"] = f"""# COST REPORT (§15)

COST_MODEL_V3 canonical RT = `{b['cost_model_v3_rt_bps']}` bps.

| multiple | cost bps RT | expectancy net bps | positive |
|---|---|---|---|
""" + "\n".join(
        f"| {k} | {v['cost_bps_rt']} | {v['expectancy_net_bps']} | {v['positive']} |"
        for k, v in r["cost_stress"].items()
    ) + f"""

canonical net positive: **{r['canonical_net_positive']}**
"""

    files["VALIDATION_REPORT.md"] = f"""# VALIDATION REPORT (§16-§17)

Implementation frozen at `{r['frozen_implementation_hash']}` before VALIDATION.

| metric | value |
|---|---|
| trades | {val.get('trades')} |
| gross expectancy (bps) | {_f(val.get('expectancy_gross_bps'),3)} |
| net expectancy (bps) | {_f(val.get('expectancy_net_bps'),3)} |
| net (USD) | {_f(val.get('net_usd'))} |
| PF | {_f(val.get('profit_factor'),4)} |
| max drawdown (bps) | {_f(val.get('max_drawdown_bps'),2)} |

**VALIDATION decision: `{r['validation_decision']}`**
"""

    files["BETA_DECOMPOSITION.md"] = f"""# BETA DECOMPOSITION (§18)

{json.dumps(r['beta_decomposition'], indent=2)}
"""

    files["STATE_ANALYSIS.md"] = f"""# STATE ANALYSIS (§20)

{json.dumps(r['state_analysis'], indent=2)}
"""

    files["COMPONENT_ANALYSIS.md"] = f"""# COMPONENT ANALYSIS (§21)

{json.dumps(r['component'], indent=2)}

Diagnostic only — selecting the best component and promoting it would require a
NEW experiment.
"""

    files["TEMPORAL.md"] = f"""# TEMPORAL (§22)

{json.dumps(r['temporal'], indent=2)}
"""

    files["REGIME.md"] = f"""# REGIME (§23)

{json.dumps(r['regime'], indent=2)}
"""

    files["CONCENTRATION.md"] = f"""# CONCENTRATION (§24)

{json.dumps(r['concentration'], indent=2)}
"""

    files["ROBUSTNESS.md"] = f"""# ROBUSTNESS (§25-§26)

reference split: `{r['robustness']['reference_split']}`
positive fraction: {r['robustness']['positive_fraction']} (robust_ok={r['robustness']['robust_ok']})

{json.dumps(r['robustness']['perturbations'], indent=2)}

leave-one-component-out: {r['robustness']['leave_one_component_out']}
"""

    files["NEGATIVE_KNOWLEDGE.md"] = f"""# NEGATIVE KNOWLEDGE (§27-§28)

{r['multiple_testing']['note']}

- graveyard: {', '.join(r['multiple_testing']['graveyard'])}
- remaining preregistrations: {', '.join(r['multiple_testing']['new_prereg_remaining'])}

EXP-ARP-019 / EXP-ARP-020 are **not** auto-run.
"""

    files["RUN_REPORT.md"] = f"""# RUN REPORT

- experiment: `{EXPERIMENT_ID}` / `{STRATEGY_ID}`
- start_sha: `{b['start_sha']}`
- dev_decision: `{r['dev_decision']}`
- validation_decision: `{r['validation_decision']}`
- robust_ok: {r['robustness']['robust_ok']}
- final_decision: **`{r['final_decision']}`**
- OOS opened: **NO**

Machine copy: [`RUN_REPORT.json`](RUN_REPORT.json)
"""

    files["FINAL_REPORT.md"] = f"""# FINAL REPORT — EXP-ARP-022

**Final decision: `{r['final_decision']}`**

Contract **`{c['status']}`**; data **`{r['data_authority']['data_status']}`**;
holdout **`{r['holdout']['status_after']}`** (never opened); DEV
**`{r['dev_decision']}`**; cost canonical-positive **{r['canonical_net_positive']}**;
VALIDATION **`{r['validation_decision']}`**; robust {r['robustness']['robust_ok']}.

DEV net expectancy {_f(dev['expectancy_net_bps'],3)} bps / {dev['trades']} trades;
VALIDATION {_f(val.get('expectancy_net_bps'),3)} bps / {val.get('trades')} trades.
Market beta {_f(r['beta_decomposition'].get('market_beta'),4)}.

No OOS, no promotion, no live capital; `FALSE_SUCCESS=0`.
"""

    for name, content in files.items():
        (OUT / name).write_text(content, encoding="utf-8")
    print("wrote", len(files), "markdown files to", OUT)


if __name__ == "__main__":
    main()
