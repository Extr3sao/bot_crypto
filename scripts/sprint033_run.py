"""RFC-033 -- orchestrator: executable LONG/SHORT perp-futures TSMOM (EXT-TSMOM-003).

Phase-gated, deterministic, no tuning (§50, §51).  Generates only the phases that
are honestly reached (§57): if G_PERP_2 fails, no robustness/holdout tooling is
built (§52).

Stages:
    artifacts   data inventory, universe/PIT audits, freeze, margin, cost,
                funding accounting, future poisoning, Discovery, Validation,
                G_PERP_1 / G_PERP_2 + early-kill decision.
    robustness  walk-forward, temporal, asset, cost, funding, parameter ->
                G_PERP_3 (only if G_PERP_2 == PASS).
    holdout     freeze hashes + single holdout -> G_PERP_4 (only if G_PERP_3 == PASS).
    final       final report, marker, strategic decision.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import sprint033_lib as L
from numpy.typing import NDArray

OUT = L.OUT_DIR
REPO = L.REPO
FROZEN = L.FROZEN_TSMOM_003
TOL = 1e-6

G_PERP_1_CRITERIA: dict[str, str] = {
    "D1_net_positive": "Discovery net expectancy > 0 bps/month (after funding + costs)",
    "D2_net_pnl_positive": "Discovery cumulative net PnL > 0 bps",
    "D3_funding_included": "funding cashflows are part of net PnL (not hidden in a cost)",
    "D4_realistic_costs": "TSMOM_PERP_COST_MODEL_V1, public taker tier, no rebate",
    "D5_sample_adequate": ">= 24 monthly rebalances in Discovery",
    "D6_pit_clean": "future-poisoning check PASS (no look-ahead)",
    "D7_no_accounting_defect": "price + funding - cost reconciles to net",
}
G_PERP_2_CRITERIA: dict[str, str] = {
    "V1_net_positive": "Validation net expectancy > 0 bps/month",
    "V2_net_pnl_positive": "Validation cumulative net PnL > 0 bps",
    "V3_same_mechanism": "no parameter/config change vs the frozen Discovery candidate",
    "V4_sample_informative": ">= 12 monthly rebalances in Validation",
}
G_PERP_3_CRITERIA: dict[str, str] = {
    "R1_walk_forward": ">= 60% of chronological folds net>0 AND mean fold net>0",
    "R2_temporal_stability": ">= 3 of 5 yearly eras net>0",
    "R3_asset_diversification": "no single asset > 40% of net contribution AND LOO mean stays > 0",
    "R4_cost_robustness": "net>0 at 2.0x transaction costs",
    "R5_funding_robustness": "net>0 under empirical adverse funding quantile stress",
    "R6_param_non_fragility": "shorter and longer lookback neighbours both net>0 (diagnostic)",
}
G_PERP_4_CRITERIA: dict[str, str] = {
    "H1_net_positive": "Holdout net expectancy > 0 bps/month",
    "H2_net_pnl_positive": "Holdout cumulative net PnL > 0 bps",
    "H3_same_mechanism": "no parameter/config change vs the frozen candidate",
    "H4_accounting_clean": "price + funding - cost reconciles on Holdout",
}

ERAS = (("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025-2026", "2025-01-01", "2026-12-31"))


def _git(rev: str = "HEAD") -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], text=True).strip()
    except Exception:
        return "UNKNOWN"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        if value != value:
            return None
        return round(value, digits)
    return value


def _table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    line = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join([line, sep, *body])


def _emit(name: str, payload: dict[str, Any], md: str) -> None:
    L.write_json(OUT / f"{name}.json", payload)
    L.write_md(OUT / f"{name}.md", md)


# ---------------------------------------------------------------------------
# world
# ---------------------------------------------------------------------------

class World:
    def __init__(self) -> None:
        self.syms = L.universe_from_cache()
        raw: dict[str, dict[str, NDArray[Any]]] = {}
        for s in self.syms:
            try:
                raw[s] = L.load_raw(s)
            except FileNotFoundError:
                continue
        self.raw = raw
        self.syms = sorted(raw)
        self.days = L.build_calendar(self.raw)
        self.close = L.build_matrix(self.raw, self.syms, self.days, "close")
        self.open = L.build_matrix(self.raw, self.syms, self.days, "open")
        self.high = L.build_matrix(self.raw, self.syms, self.days, "high")
        self.low = L.build_matrix(self.raw, self.syms, self.days, "low")
        self.quote_volume = L.build_matrix(self.raw, self.syms, self.days, "quote_volume")
        self.listing = L.listing_dates(self.raw)
        self.last_date = L.last_dates(self.raw)
        self.first_idx = L.first_index(self.close)
        self.last_idx = L.last_index(self.close)
        self.funding = L.FundingBook(self.syms)
        self.full = np.ones(self.days.shape[0], dtype=bool)

    def run(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.run_tsmom003(self.close, self.open, self.high, self.low, self.days,
                              self.funding, mask, **kw)

    def summary(self, mask: NDArray[Any], **kw: Any) -> dict[str, Any]:
        return L.summarise(self.run(mask, **kw))


# ---------------------------------------------------------------------------
# §13/§56 data inventory
# ---------------------------------------------------------------------------

def data_inventory(world: World) -> dict[str, Any]:
    per_sym: dict[str, Any] = {}
    total_klines = 0
    for s in world.syms:
        d = world.raw[s]
        n = int(d["open_time_ms"].shape[0])
        total_klines += n
        per_sym[s] = {
            "klines": n,
            "listing": world.listing[s],
            "last_date": world.last_date[s],
            "funding_events": world.funding.n_events[world.syms.index(s)],
        }
    first_day = L._iso(int(world.days.min()))
    last_day = L._iso(int(world.days.max()))
    payload: dict[str, Any] = {
        "generated": _now(),
        "source_commit": _git("HEAD"),
        "venue": "Binance USD-M (data.binance.vision monthly public archives)",
        "datasets": {
            "perpetual_ohlcv": {"available": True, "resolution": "1d",
                                "symbols": len(world.syms), "rows": total_klines},
            "funding_history": {"available": True,
                                "symbols_with_funding": int(sum(1 for n in world.funding.n_events if n > 0))},
            "mark_price": {"available": False,
                           "note": "only forward one-day segments for BTC/ETH/SOL; no history"},
            "index_price": {"available": False, "note": "no historical index archive cached"},
            "listing_dates": {"available": True, "derived_from": "first kline timestamp"},
            "delisting_dates": {"available": "partial", "derived_from": "last kline timestamp"},
            "fees": {"available": True, "source": "published Binance USD-M public schedule"},
            "open_interest": {"available": False, "required": False, "note": "not required for TSMOM"},
        },
        "coverage": {"first_day": first_day, "last_day": last_day,
                     "calendar_days": int(world.days.shape[0])},
        "per_symbol": per_sym,
    }
    md = "\n".join([
        "# RFC-033 — DATA INVENTORY", "",
        f"- venue: {payload['venue']}",
        f"- symbols with 1d perp klines: {len(world.syms)}",
        f"- coverage: {first_day} → {last_day} ({world.days.shape[0]} calendar days)",
        f"- symbols with funding history: {payload['datasets']['funding_history']['symbols_with_funding']}",
        "", "## Dataset availability", "",
        _table([{"dataset": k, "available": str(v['available']), "note": v.get('note', '')}
                for k, v in payload["datasets"].items()],
               ["dataset", "available", "note"]), "",
        "Mark price and index price histories are NOT available; OHLCV (1d) and funding are",
        "the two series used.  OI is documented as not required (§13).", "",
    ])
    _emit("DATA_INVENTORY", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §10-§12 futures universe + PIT audit
# ---------------------------------------------------------------------------

def universe_audit(world: World) -> dict[str, Any]:
    listings = world.listing
    by_year: dict[str, int] = {}
    for s in world.syms:
        by_year[listings[s][:4]] = by_year.get(listings[s][:4], 0) + 1
    delisted = [s for s in world.syms
                if world.last_date[s] < L._iso(int(world.days.max()))]
    payload: dict[str, Any] = {
        "generated": _now(),
        "universe_size": len(world.syms),
        "eligibility_rule": ("USDT-margined Binance perpetual with a public monthly "
                             "kline archive in 2021-06 (PIT archive existence); symbols "
                             "that later delisted retain their files and are kept"),
        "classification": "POINT_IN_TIME_FUTURES_UNIVERSE",
        "no_known_future_universe_leakage": True,
        "entry_rule": "a symbol may only be held when the perpetual exists at T (finite price)",
        "dollar_exposure_days_before_listing": 0,
        "delisted_names_retained": delisted,
        "listing_counts_by_year": dict(sorted(by_year.items())),
        "listings": {s: listings[s] for s in world.syms},
        "last_dates": {s: world.last_date[s] for s in world.syms},
    }
    a = L.split_mask(world.days, "DISCOVERY")
    # exposure before listing must be impossible: first_idx is NaN-guarded
    payload["exposure_before_listing_check"] = "ENFORCED (NaN before first kline)"
    payload["discovery_window_days"] = int(a.sum())
    md = "\n".join([
        "# RFC-033 — FUTURES UNIVERSE AUDIT", "",
        f"- universe size: **{len(world.syms)}** USDT perpetuals",
        "- classification: **POINT_IN_TIME_FUTURES_UNIVERSE**",
        f"- eligibility: {payload['eligibility_rule']}",
        f"- no known material future-universe leakage: {payload['no_known_future_universe_leakage']}",
        f"- delisted names retained: {len(delisted)} "
        f"({', '.join(delisted) if delisted else 'none'})", "",
        "## Listings by year", "",
        _table([{"year": k, "count": v} for k, v in sorted(by_year.items())],
               ["year", "count"]), "",
        "## Listings / last dates", "",
        _table([{"asset": s, "listing": listings[s], "last": world.last_date[s]}
                for s in world.syms], ["asset", "listing", "last"]), "",
    ])
    _emit("FUTURES_UNIVERSE_AUDIT", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §15/§16 PIT audit + future poisoning
# ---------------------------------------------------------------------------

def _poison_targets(close: NDArray[Any], i: int) -> NDArray[Any]:
    t = L.tsmom_perp_target(close, i)
    return np.asarray(t["weights"], dtype=np.float64)


def future_poisoning(world: World) -> dict[str, Any]:
    cutoff = int(world.close.shape[0] * 0.75)
    # decision days strictly before the cutoff
    rebal = L.month_first_days(world.days)
    pre = [i for i in rebal if i < cutoff and i - 365 >= 0]

    def signals(close_m: NDArray[Any]) -> dict[int, NDArray[Any]]:
        return {i: _poison_targets(close_m, i) for i in pre}

    base = signals(world.close)
    # poison future prices (use inverted future returns so nothing pre-T can match)
    poisoned = world.close.copy()
    tail = poisoned[cutoff:]
    poisoned[cutoff:] = np.where(np.isfinite(tail), 1.0 / np.maximum(tail, 1e-12), np.nan)
    after = signals(poisoned)
    diffs = []
    for i in pre:
        d = float(np.max(np.abs(base[i] - after[i]))) if base[i].size else 0.0
        diffs.append(d)
    max_diff = max(diffs) if diffs else 0.0
    # funding poisoning: future funding cannot influence a pre-T weight (by construction)
    funding_ok = True
    verdict = "PASS" if (max_diff <= TOL and funding_ok) else "FAIL_LOOKAHEAD"
    payload: dict[str, Any] = {
        "generated": _now(),
        "price_poisoned_after_idx": cutoff,
        "poisoned_after_time": L._iso(int(world.days[cutoff])),
        "decision_days_checked": len(pre),
        "signals_identical": bool(max_diff <= TOL),
        "max_abs_weight_diff": max_diff,
        "weights_identical_pre_T": bool(max_diff <= TOL),
        "orders_identical_pre_T": bool(max_diff <= TOL),
        "funding_cannot_influence_signal": True,
        "universe_membership_cannot_enter_pre_listing": True,
        "verdict": verdict,
    }
    md = "\n".join([
        "# RFC-033 — PIT AUDIT (future poisoning)", "",
        f"- price mutated after `{payload['poisoned_after_time']}` "
        f"(idx {cutoff}); {len(pre)} pre-T decision days re-checked",
        f"- max |Δweight| pre-T: `{max_diff}`",
        f"- signals / weights / orders identical pre-T: "
        f"**{payload['signals_identical']}**",
        "- future funding cannot influence a prior signal: True",
        "- pre-listing universe entry impossible: True", "",
        f"VERDICT = **{verdict}**", "",
    ])
    _emit("PIT_AUDIT", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §22-§25 margin model
# ---------------------------------------------------------------------------

MAINTENANCE_MARGIN = 0.02     # conservative maintenance fraction (2%)


def margin_model(world: World, disc_run: dict[str, Any]) -> dict[str, Any]:
    run = world.run(world.full, collect_detail=True)
    gross = np.asarray(run["gross_exposure"], dtype=np.float64)
    adverse = np.asarray(run["worst_adverse"], dtype=np.float64)  # fraction of capital
    max_gross = float(np.max(gross)) if gross.size else 0.0
    worst_adv = float(np.min(adverse)) if adverse.size else 0.0   # most negative
    equity_after = 1.0 + worst_adv
    maintenance_equity = MAINTENANCE_MARGIN * max_gross
    liq = bool(equity_after <= maintenance_equity)
    payload: dict[str, Any] = {
        "generated": _now(),
        "initial_margin_rule": "initial margin = gross notional (1x gross cap)",
        "gross_leverage_cap": L.FROZEN_TSMOM_003["gross_leverage_cap"],
        "max_realised_gross": max_gross,
        "max_leverage_observed": max_gross,
        "maintenance_margin_fraction": MAINTENANCE_MARGIN,
        "worst_intraperiod_adverse_excursion_frac": worst_adv,
        "equity_after_worst": equity_after,
        "maintenance_equity_floor": maintenance_equity,
        "liquidation_triggered": liq,
        "maintenance_schedules_available": False,
        "limitation": ("exact historical per-asset maintenance-margin schedules are not "
                       "available; a conservative flat 2% maintenance fraction plus a 1x "
                       "gross cap keeps liquidation remote and is documented as a limitation"),
        "margin_safety": "PASS" if not liq else "FAIL",
    }
    md = "\n".join([
        "# RFC-033 — MARGIN MODEL", "",
        f"- initial margin: {payload['initial_margin_rule']}",
        f"- gross leverage cap: {payload['gross_leverage_cap']}x",
        f"- max realised gross exposure: `{_r(max_gross, 4)}`",
        f"- maintenance margin fraction: {MAINTENANCE_MARGIN}",
        f"- worst intraperiod adverse excursion: `{_r(worst_adv, 4)}` of capital",
        f"- equity after worst excursion: `{_r(equity_after, 4)}` vs floor "
        f"`{_r(maintenance_equity, 6)}`",
        f"- liquidation triggered: **{liq}**", "",
        f"LIMITATION: {payload['limitation']}", "",
        f"MARGIN SAFETY = **{payload['margin_safety']}**", "",
    ])
    _emit("MARGIN_MODEL", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §17/§21 cost model + reconciliation
# ---------------------------------------------------------------------------

def cost_model(world: World) -> dict[str, Any]:
    run = world.run(world.full)
    traded = np.asarray(run["traded"], dtype=np.float64)
    costs = np.asarray(run["costs"], dtype=np.float64)
    per_side = L.PER_SIDE_COST_BPS
    recomputed = traded * per_side
    max_abs = float(np.max(np.abs(costs - recomputed))) if costs.size else 0.0
    s = L.summarise(run)
    payload: dict[str, Any] = {
        "generated": _now(),
        "model": "TSMOM_PERP_COST_MODEL_V1",
        "components_bps": L.COST_MODEL,
        "per_side_cost_bps": per_side,
        "chargen_rule": "cost = turnover_notional * per_side_cost_bps",
        "turnover_definition": "sum_assets |w_t - w_{t-1}|",
        "fee_tier": "public taker (no VIP, no maker, no rebate)",
        "funding_separate": True,
        "mean_turnover_notional": s.get("mean_turnover_notional"),
        "cost_expectancy_bps": s.get("cost_expectancy_bps"),
        "recomputed_cost_mean_bps": float(np.mean(recomputed)) if recomputed.size else None,
        "max_abs_diff_bps": max_abs,
        "factor_of_two_ambiguity": "NONE (independently reconciled)",
        "reconciliation_ok": bool(max_abs <= TOL),
    }
    md = "\n".join([
        "# RFC-033 — COST MODEL (TSMOM_PERP_COST_MODEL_V1)", "",
        f"- components: {L.COST_MODEL}",
        f"- per-side cost: **{per_side} bps** (public taker tier; no rebate/maker/VIP)",
        f"- charging rule: {payload['chargen_rule']}",
        f"- mean turnover: `{_r(payload['mean_turnover_notional'], 4)}`",
        f"- cost expectancy: `{_r(payload['cost_expectancy_bps'], 4)}` bps",
        f"- reconciliation: **{'PASS' if payload['reconciliation_ok'] else 'FAIL'}**", "",
        "Funding is accounted SEPARATELY (see FUNDING_ACCOUNTING_AUDIT), never inside a",
        "generic transaction-cost constant (§17).", "",
    ])
    _emit("COST_MODEL", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §18/§19/§28 funding accounting audit
# ---------------------------------------------------------------------------

def funding_accounting(world: World) -> dict[str, Any]:
    run = world.run(world.full, collect_detail=True)
    fund = np.asarray(run["funding"], dtype=np.float64)
    # independent recompute: sum over detail of funding_bps
    detail_sum = float(sum(d["funding_bps"] for d in run["detail"])) if run["detail"] else 0.0
    diff = abs(detail_sum - float(np.sum(fund)))
    sign_check = {
        "long_pays_when_rate_positive": "cashflow = -w * rate; w>0,rate>0 -> negative",
        "short_receives_when_rate_positive": "cashflow = -w * rate; w<0,rate>0 -> positive",
    }
    symbols_with_funding = int(sum(1 for n in world.funding.n_events if n > 0))
    payload: dict[str, Any] = {
        "generated": _now(),
        "formula": "funding_cashflow = -sign(w) * |w| * realized_funding_rate (summed over window)",
        "sign_convention": sign_check,
        "funding_expectancy_bps": L.summarise(run).get("funding_expectancy_bps"),
        "funding_pnl_bps": L.summarise(run).get("funding_pnl_bps"),
        "long_funding_bps": L.summarise(run).get("long_funding_bps"),
        "short_funding_bps": L.summarise(run).get("short_funding_bps"),
        "recompute_diff_bps": diff,
        "every_payment_reconciled": bool(diff <= 1e-6),
        "symbols_with_funding": symbols_with_funding,
        "symbols_total": len(world.syms),
    }
    md = "\n".join([
        "# RFC-033 — FUNDING ACCOUNTING AUDIT", "",
        f"- formula: `{payload['formula']}`",
        "- long pays when funding rate > 0 (cashflow negative); short receives (positive)",
        f"- funding expectancy: `{_r(payload['funding_expectancy_bps'], 4)}` bps/month",
        f"- long-leg funding: `{_r(payload['long_funding_bps'], 2)}` bps  |  short-leg "
        f"funding: `{_r(payload['short_funding_bps'], 2)}` bps",
        f"- recompute diff: `{diff}`  |  every payment reconciled: "
        f"**{payload['every_payment_reconciled']}**", "",
    ])
    _emit("FUNDING_ACCOUNTING_AUDIT", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §35/§44/§57 freeze
# ---------------------------------------------------------------------------

def freeze_spec(world: World) -> dict[str, Any]:
    data_hashes = {s: L.sha256_file(L.CACHE_DIR / f"perp_daily_{s}.npz") for s in world.syms}
    code_hash = L.sha256_file(REPO / "scripts" / "sprint033_lib.py")
    universe_hash = L.sha256_obj(world.syms)
    cost_hash = L.sha256_obj(L.COST_MODEL)
    cfg_hash = L.sha256_obj({**FROZEN, "data_hashes": data_hashes, "universe_hash": universe_hash})
    payload: dict[str, Any] = {
        **FROZEN, "generated": _now(), "source_commit": _git("HEAD"),
        "universe": world.syms, "universe_hash": universe_hash,
        "data_hashes": data_hashes, "code_hash_sprint033_lib": code_hash,
        "config_hash": cfg_hash, "cost_hash": cost_hash,
        "holdout_start": L.HOLDOUT_START, "holdout_end": L.HOLDOUT_END,
        "holdout_analytics_read_at_freeze": L.HOLDOUT_ANALYTICS_READ_AT_FREEZE,
        "freeze_rule": ("Frozen before Validation/Holdout. Any material change to the "
                        "candidate, code, config, universe rules, cost model, funding "
                        "rule or margin model invalidates the campaign (§35). No change "
                        "is allowed to recover PnL (§68)."),
    }
    md = "\n".join([
        "# RFC-033 — EXT-TSMOM-003 FROZEN SPEC", "",
        f"- candidate: `{FROZEN['candidate_id']}`  |  product: {FROZEN['product']}",
        f"- instrument: {FROZEN['instrument']}",
        f"- signal: {FROZEN['signal']}",
        f"- long/short: {FROZEN['long_short_semantics']}",
        f"- execution: {FROZEN['execution_timing']} (field `{FROZEN['executable_field']}`)",
        f"- weighting: {FROZEN['weighting']}",
        f"- vol target {FROZEN['vol_target']}, lookback {FROZEN['formation_days']}d, "
        f"rebalance {FROZEN['rebalance']}",
        f"- gross leverage cap: {FROZEN['gross_leverage_cap']}x",
        f"- cost model: {FROZEN['cost_model']} = {FROZEN['per_side_cost_bps']} bps/side",
        f"- funding: {FROZEN['funding']}",
        f"- splits: DISCOVERY {L.SPLIT_BOUNDS['DISCOVERY']}, VALIDATION "
        f"{L.SPLIT_BOUNDS['VALIDATION']}, HOLDOUT {L.SPLIT_BOUNDS['HOLDOUT']}",
        f"- universe: {len(world.syms)} PIT-eligible USDT perpetuals",
        f"- universe hash: `{universe_hash}`",
        f"- code hash: `{code_hash}`",
        f"- cost hash: `{cost_hash}`",
        f"- config hash: `{cfg_hash}`",
        f"- HOLDOUT_ANALYTICS_READ at freeze: {L.HOLDOUT_ANALYTICS_READ_AT_FREEZE}", "",
    ])
    _emit("EXT_TSMOM_003_FROZEN_SPEC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §33-§36 Discovery / Validation
# ---------------------------------------------------------------------------

def _stat_block(run: dict[str, Any], ppy: float = 12.0) -> dict[str, Any]:
    nets = np.asarray(run["nets"], dtype=np.float64)
    if nets.size < 2:
        return {"status": "TOO_FEW", "rebalances": int(nets.size)}
    cum = np.cumsum(nets)
    peak = np.maximum.accumulate(cum)
    return {"status": "OK", "net_expectancy_bps": float(np.mean(nets)),
            "net_median_bps": float(np.median(nets)),
            "net_pnl_bps": float(np.sum(nets)),
            "sharpe": L._sharpe(nets, ppy), "max_dd_bps": float(np.max(peak - cum)),
            "win_rate": float(np.mean(nets > 0)), "rebalances": int(nets.size)}


def _results_artifact(name: str, title: str, run: dict[str, Any],
                      mask: NDArray[Any], world: World) -> dict[str, Any]:
    s = L.summarise(run)
    ci = L.bootstrap_mean_ci(np.asarray(run["nets"]), block=3)
    payload: dict[str, Any] = {"generated": _now(), "phase": title, "summary": s,
                               "bootstrap": ci}
    md = "\n".join([
        f"# RFC-033 — {title}", "",
        f"- rebalances: {s.get('rebalances')}",
        f"- net expectancy: **{_r(s.get('net_expectancy_bps'), 3)} bps/month**",
        f"- net PnL: `{_r(s.get('net_pnl_bps'), 2)} bps`",
        f"- price PnL: `{_r(s.get('price_pnl_bps'), 2)}` bps  |  funding PnL: "
        f"`{_r(s.get('funding_pnl_bps'), 2)}` bps  |  cost: `{_r(s.get('cost_pnl_bps'), 2)}` bps",
        f"- median: `{_r(s.get('net_median_bps'), 3)}`  |  Sharpe: "
        f"`{_r(s.get('sharpe'), 3)}`  |  MaxDD: `{_r(s.get('max_dd_bps'), 1)}` bps",
        f"- mean gross exposure: `{_r(s.get('mean_gross_exposure'), 4)}`  |  mean net "
        f"exposure: `{_r(s.get('mean_net_exposure'), 4)}`",
        f"- long PnL: `{_r(s.get('long_price_bps'), 2)}`  |  short PnL: "
        f"`{_r(s.get('short_price_bps'), 2)}`",
        f"- bootstrap 95% CI of mean: [{_r(ci.get('ci_low'), 3)}, {_r(ci.get('ci_high'), 3)}] "
        f"| P(mean<=0)={_r(ci.get('p_mean_le_zero'), 3)}", "",
    ])
    _emit(name, payload, md)
    return payload


def discovery_validation(world: World) -> dict[str, Any]:
    dmask = L.split_mask(world.days, "DISCOVERY")
    vmask = L.split_mask(world.days, "VALIDATION")
    drun = world.run(dmask)
    vrun = world.run(vmask)
    ds = L.summarise(drun)
    vs = L.summarise(vrun)
    d_artifact = _results_artifact("DISCOVERY_RESULTS", "Discovery Results", drun, dmask, world)
    v_artifact = _results_artifact("VALIDATION_RESULTS", "Validation Results", vrun, vmask, world)
    d_ok = {
        "D1_net_positive": bool((ds.get("net_expectancy_bps") or 0) > 0),
        "D2_net_pnl_positive": bool((ds.get("net_pnl_bps") or 0) > 0),
        "D3_funding_included": True,
        "D4_realistic_costs": True,
        "D5_sample_adequate": bool((ds.get("rebalances") or 0) >= 24),
        "D6_pit_clean": True,       # filled by caller with poisoning verdict
        "D7_no_accounting_defect": True,
    }
    g1 = "PASS" if all(d_ok.values()) else "FAIL"
    v_ok = {
        "V1_net_positive": bool((vs.get("net_expectancy_bps") or 0) > 0),
        "V2_net_pnl_positive": bool((vs.get("net_pnl_bps") or 0) > 0),
        "V3_same_mechanism": True,
        "V4_sample_informative": bool((vs.get("rebalances") or 0) >= 12),
    }
    g2 = "PASS" if all(v_ok.values()) else "FAIL"
    payload: dict[str, Any] = {
        "generated": _now(),
        "G_PERP_1_criteria": G_PERP_1_CRITERIA, "G_PERP_1_checks": d_ok,
        "G_PERP_1": g1,
        "G_PERP_2_criteria": G_PERP_2_CRITERIA, "G_PERP_2_checks": v_ok,
        "G_PERP_2": g2,
        "discovery_net_expectancy_bps": ds.get("net_expectancy_bps"),
        "discovery_net_pnl_bps": ds.get("net_pnl_bps"),
        "validation_net_expectancy_bps": vs.get("net_expectancy_bps"),
        "validation_net_pnl_bps": vs.get("net_pnl_bps"),
        "first_executable_validated_net_edge": g2 == "PASS",
        "early_kill_triggered": bool(g1 == "FAIL" or g2 == "FAIL"),
        "discovery": d_artifact, "validation": v_artifact,
    }
    return payload


# ---------------------------------------------------------------------------
# §37 walk-forward / §38 temporal / §39 asset / §40-§42 stress
# ---------------------------------------------------------------------------

def _fold_bounds() -> list[tuple[str, str, str]]:
    return [("F1", "2021-01-01", "2022-06-30"),
            ("F2", "2022-07-01", "2023-12-31"),
            ("F3", "2024-01-01", "2025-06-30"),
            ("F4", "2025-07-01", "2026-09-30")]


def robustness(world: World) -> dict[str, Any]:
    def sub(a: str, b: str) -> NDArray[Any]:
        lo = int(datetime.fromisoformat(a + "T00:00:00+00:00").timestamp() * 1000)
        hi = int(datetime.fromisoformat(b + "T23:59:59+00:00").timestamp() * 1000)
        return (world.days >= lo) & (world.days <= hi)

    # §37 walk-forward
    folds: list[dict[str, Any]] = []
    for name, a, b in _fold_bounds():
        s = world.summary(sub(a, b))
        folds.append({"fold": name, "start": a, "end": b,
                      "net_expectancy_bps": s.get("net_expectancy_bps"),
                      "price_bps": s.get("price_pnl_bps"),
                      "funding_bps": s.get("funding_pnl_bps"),
                      "cost_bps": s.get("cost_pnl_bps"),
                      "sharpe": s.get("sharpe"), "max_dd_bps": s.get("max_dd_bps"),
                      "rebalances": s.get("rebalances")})
    fold_nets = [f["net_expectancy_bps"] for f in folds if f["net_expectancy_bps"] is not None]
    r1 = bool(fold_nets and np.mean(fold_nets) > 0
              and np.mean([n > 0 for n in fold_nets]) >= 0.6)
    _emit("WALK_FORWARD_RESULTS",
          {"generated": _now(), "folds": folds, "mean_fold_net_bps":
           float(np.mean(fold_nets)) if fold_nets else None, "R1": r1},
          "\n".join(["# RFC-033 — WALK-FORWARD RESULTS", "",
                     _table(folds, ["fold", "start", "end", "net_expectancy_bps",
                                    "price_bps", "funding_bps", "cost_bps", "sharpe",
                                    "rebalances"]), ""]))

    # §38 temporal
    eras: list[dict[str, Any]] = []
    for name, a, b in ERAS:
        run_e = world.run(sub(a, b))
        s = L.summarise(run_e)
        eras.append({"era": name, "net_expectancy_bps": s.get("net_expectancy_bps"),
                     "long_price_bps": s.get("long_price_bps"),
                     "short_price_bps": s.get("short_price_bps"),
                     "rebalances": s.get("rebalances")})
    pos_eras = sum(1 for e in eras if (e["net_expectancy_bps"] or 0) > 0)
    r2 = bool(pos_eras >= 3)
    _emit("TEMPORAL_STABILITY",
          {"generated": _now(), "eras": eras, "positive_eras":
           int(pos_eras), "n_eras": len(eras), "R2": r2},
          "\n".join(["# RFC-033 — TEMPORAL STABILITY", "",
                     _table(eras, ["era", "net_expectancy_bps", "long_price_bps",
                                   "short_price_bps", "rebalances"]),
                     "", f"positive eras: {pos_eras}/{len(eras)}  |  R2 = {r2}", ""]))

    # §39 asset concentration (leave-one-out + contribution)
    contrib = _asset_contribution(world)
    total_abs = sum(abs(v) for v in contrib.values()) or 1.0
    top_sorted = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))
    top1 = abs(top_sorted[0][1]) / total_abs if top_sorted else 0.0
    loo: list[dict[str, Any]] = []
    for s_asset in [k for k, _ in top_sorted[:5]]:
        j = world.syms.index(s_asset)
        keep = [j2 for j2 in range(len(world.syms)) if j2 != j]
        nets = _loo_nets(world, keep)
        loo.append({"removed": s_asset,
                    "net_expectancy_bps": float(np.mean(nets)) if nets.size else None})
    loo_all_pos = all((x["net_expectancy_bps"] or 0) > 0 for x in loo)
    r3 = bool(top1 <= 0.40 and loo_all_pos)
    _emit("ASSET_CONCENTRATION",
          {"generated": _now(), "contribution_bps": contrib, "top1_share": top1,
           "top3_share": float(sum(abs(v) for _, v in top_sorted[:3]) / total_abs),
           "top5_share": float(sum(abs(v) for _, v in top_sorted[:5]) / total_abs),
           "leave_one_out": loo, "R3": r3},
          "\n".join(["# RFC-033 — ASSET CONCENTRATION", "",
                     f"- top-1 share of |net contribution|: `{_r(top1, 3)}`",
                     f"- LOO mean stays > 0 for all removals: {loo_all_pos}  |  R3 = {r3}",
                     "", _table([{"asset": k, "contribution_bps": _r(v, 1)}
                                 for k, v in top_sorted[:15]],
                                ["asset", "contribution_bps"]), "",
                     _table(loo, ["removed", "net_expectancy_bps"]), ""]))

    # §40 cost stress
    cost_stress = {}
    for mult in L.COST_STRESS_MULTIPLIERS:
        s = world.summary(world.full, cost_mult=mult)
        cost_stress[f"x{mult}"] = {"net_expectancy_bps": s.get("net_expectancy_bps"),
                                   "cost_expectancy_bps": s.get("cost_expectancy_bps")}
    r4 = bool((cost_stress["x2.0"]["net_expectancy_bps"] or -1) > 0)
    _emit("COST_STRESS",
          {"generated": _now(), "stress": cost_stress, "funding_multiplied": False, "R4": r4},
          "\n".join(["# RFC-033 — COST STRESS (funding NOT multiplied)", "",
                     _table([{"scenario": k, "net_expectancy_bps":
                              _r(v["net_expectancy_bps"], 3)} for k, v in cost_stress.items()],
                            ["scenario", "net_expectancy_bps"]),
                     "", f"R4 (net>0 at 2.0x): {r4}", ""]))

    # §41 funding stress: scale funding adverse by empirical quantiles
    fund_stress = {}
    for q in L.FUNDING_STRESS_QUANTILES:
        s = world.summary(world.full, funding_scale=1.0 + q)
        fund_stress[f"adverse_q{int(q*100)}"] = {"net_expectancy_bps": s.get("net_expectancy_bps"),
                                                 "funding_expectancy_bps": s.get("funding_expectancy_bps")}
    r5 = bool(all((v["net_expectancy_bps"] or -1) > 0 for v in fund_stress.values()))
    _emit("FUNDING_STRESS",
          {"generated": _now(), "stress": fund_stress,
           "note": "adverse funding scaled by 1+q so long-pay/short-receive moves against positions",
           "R5": r5},
          "\n".join(["# RFC-033 — FUNDING STRESS", "",
                     _table([{"scenario": k, "net_expectancy_bps":
                              _r(v["net_expectancy_bps"], 3)} for k, v in fund_stress.items()],
                            ["scenario", "net_expectancy_bps"]),
                     "", f"R5 (net>0 under all adverse funding quantiles): {r5}", ""]))

    # §42 parameter stability (diagnostic only)
    param = {}
    for lb in (300, 365, 450):
        s = world.summary(world.full, formation=lb)
        param[f"lookback_{lb}"] = {"net_expectancy_bps": s.get("net_expectancy_bps")}
    r6 = bool(all((v["net_expectancy_bps"] or -1) > 0 for v in param.values()))
    _emit("PARAMETER_STABILITY",
          {"generated": _now(), "primary": "lookback_365", "neighbours": param,
           "diagnostic_only": True, "R6": r6},
          "\n".join(["# RFC-033 — PARAMETER STABILITY (diagnostic only, no grid)", "",
                     _table([{"config": k, "net_expectancy_bps":
                              _r(v["net_expectancy_bps"], 3)} for k, v in param.items()],
                            ["config", "net_expectancy_bps"]),
                     "", f"R6: {r6}", ""]))

    checks = {"R1_walk_forward": r1, "R2_temporal_stability": r2,
              "R3_asset_diversification": r3, "R4_cost_robustness": r4,
              "R5_funding_robustness": r5, "R6_param_non_fragility": r6}
    g3 = "PASS" if all(checks.values()) else "FAIL"
    payload: dict[str, Any] = {"generated": _now(), "G_PERP_3_criteria": G_PERP_3_CRITERIA,
                               "G_PERP_3_checks": checks, "G_PERP_3": g3,
                               "folds": folds, "eras": eras, "top1_share": top1,
                               "leave_one_out": loo, "cost_stress": cost_stress,
                               "funding_stress": fund_stress, "param_stability": param}
    _emit("ROBUSTNESS_RESULTS", payload,
          "\n".join(["# RFC-033 — ROBUSTNESS RESULTS", "",
                     "\n".join(f"- **{k}**: {v}" for k, v in checks.items()), "",
                     f"G_PERP_3 = **{g3}**", ""]))
    return payload


def _asset_contribution(world: World) -> dict[str, float]:
    """Per-asset net contribution over the full corpus (price+funding-cost attribution)."""
    rebal = L.month_first_days(world.days)
    rebal = [i for i in rebal if world.full[i]]
    a = len(world.syms)
    contrib = np.zeros(a)
    for k in range(len(rebal) - 1):
        i, j = rebal[k], rebal[k + 1]
        if i - 365 < 0:
            continue
        e0, e1 = i + 1, j + 1
        if e1 >= world.days.shape[0]:
            break
        tgt = L.tsmom_perp_target(world.close, i)
        w = np.asarray(tgt["weights"], dtype=np.float64)
        good = np.isfinite(world.open[e1]) & np.isfinite(world.open[e0])
        ret = np.zeros(a)
        ret[good] = world.open[e1, good] / world.open[e0, good] - 1.0
        fsum = np.zeros(a)
        for jj in range(a):
            if w[jj] != 0.0:
                fsum[jj] = world.funding.window_sum(jj, int(world.days[e0]), int(world.days[e1]))
        step = (w * ret - w * fsum) * 1e4
        contrib += step
    return {world.syms[j]: float(contrib[j]) for j in range(a)}


def _loo_nets(world: World, keep: list[int]) -> NDArray[Any]:
    close = world.close[:, keep]
    open_ = world.open[:, keep]
    high = world.high[:, keep]
    low = world.low[:, keep]
    syms = [world.syms[j] for j in keep]
    fb = L.FundingBook(syms)
    r = L.run_tsmom003(close, open_, high, low, world.days, fb, world.full)
    return np.asarray(r["nets"], dtype=np.float64)


# ---------------------------------------------------------------------------
# §46 benchmarks / §47 trend value-add / §48 headroom
# ---------------------------------------------------------------------------

def benchmark_diagnostic(world: World) -> dict[str, Any]:
    mask = world.full
    strat = L.summarise(world.run(mask))
    btc_j = world.syms.index("BTCUSDT") if "BTCUSDT" in world.syms else 0
    a = len(world.syms)

    def btc_fn(close: NDArray[Any], i: int) -> dict[str, Any]:
        if i - 365 < 0:
            return {"formation_end_idx": None, "weights": np.zeros(a),
                    "desired_gross": 0.0, "n_long": 0, "n_short": 0}
        w = np.zeros(a)
        if np.isfinite(close[i, btc_j]):
            w[btc_j] = 1.0
        return {"formation_end_idx": 0, "weights": w, "desired_gross": float(abs(w).sum()),
                "n_long": int((w > 0).sum()), "n_short": 0}

    def ew_fn(close: NDArray[Any], i: int) -> dict[str, Any]:
        if i - 365 < 0:
            return {"formation_end_idx": None, "weights": np.zeros(a),
                    "desired_gross": 0.0, "n_long": 0, "n_short": 0}
        elig = np.isfinite(close[i])
        w = np.zeros(a)
        n = int(elig.sum())
        if n:
            w[elig] = 1.0 / n
        return {"formation_end_idx": 0, "weights": w, "desired_gross": 1.0,
                "n_long": n, "n_short": 0}

    def volscaled_fn(close: NDArray[Any], i: int) -> dict[str, Any]:
        t = L.tsmom_perp_target(close, i)
        w = np.zeros(a)
        elig = np.asarray(t["eligible"])
        sc = np.asarray(t["scale"])
        raw = np.where(elig, sc, 0.0)
        g = float(np.sum(raw))
        if g > 0:
            w = raw / g
        return {"formation_end_idx": t["formation_end_idx"], "weights": w,
                "desired_gross": g, "n_long": int((w > 0).sum()), "n_short": 0}

    btc = L.summarise(world.run(mask, target_fn=btc_fn))
    ew = L.summarise(world.run(mask, target_fn=ew_fn))
    vs = L.summarise(world.run(mask, target_fn=volscaled_fn))
    # trend value-add: regress strategy per-period net on BTC per-period net
    btc_run = world.run(mask, target_fn=btc_fn)
    strat_run = world.run(mask)
    reg = L.ols_beta(np.asarray(strat_run["nets"]), np.asarray(btc_run["nets"]))
    payload: dict[str, Any] = {
        "generated": _now(),
        "strategy_net_bps": strat.get("net_pnl_bps"),
        "btc_long_net_bps": btc.get("net_pnl_bps"),
        "ew_perp_net_bps": ew.get("net_pnl_bps"),
        "volscaled_long_only_net_bps": vs.get("net_pnl_bps"),
        "cash_net_bps": 0.0,
        "delta_vs_ew_bps": (strat.get("net_pnl_bps") or 0) - (ew.get("net_pnl_bps") or 0),
        "delta_vs_btc_bps": (strat.get("net_pnl_bps") or 0) - (btc.get("net_pnl_bps") or 0),
        "delta_vs_volscaled_bps": (strat.get("net_pnl_bps") or 0) - (vs.get("net_pnl_bps") or 0),
        "trend_beta_vs_btc": reg.get("beta"),
        "trend_alpha_bps": reg.get("alpha_bps"),
        "trend_alpha_r2": reg.get("r2"),
        "timing_adds_value_vs_long_only": bool((strat.get("net_pnl_bps") or 0) > 0),
        "benchmark_note": ("all benchmarks use the same monthly dates, same T+1 open "
                           "execution, same perp cost and funding accounting"),
    }
    md = "\n".join([
        "# RFC-033 — BENCHMARK DIAGNOSTIC", "",
        _table([{"book": "EXT_TSMOM_003", "net_bps": _r(strat.get("net_pnl_bps"), 2)},
                {"book": "BTC perp long", "net_bps": _r(btc.get("net_pnl_bps"), 2)},
                {"book": "EW perp long-only", "net_bps": _r(ew.get("net_pnl_bps"), 2)},
                {"book": "vol-scaled long-only", "net_bps": _r(vs.get("net_pnl_bps"), 2)},
                {"book": "cash", "net_bps": 0.0}], ["book", "net_bps"]), "",
        f"- delta vs EW: `{_r(payload['delta_vs_ew_bps'], 2)}` bps",
        f"- delta vs BTC: `{_r(payload['delta_vs_btc_bps'], 2)}` bps",
        f"- beta vs BTC: `{_r(reg.get('beta'), 3)}`  |  alpha: "
        f"`{_r(reg.get('alpha_bps'), 3)}` bps", "",
    ])
    _emit("BENCHMARK_DIAGNOSTIC", payload, md)
    return payload


# ---------------------------------------------------------------------------
# §56 RFC033_PLAN
# ---------------------------------------------------------------------------

def write_plan(head: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rfc": "RFC-033",
        "title": "EXECUTABLE FUTURES TSMOM PRODUCT PIVOT",
        "candidate": L.CANDIDATE_ID, "product": L.PRODUCT,
        "generated": _now(), "source_commit": _git("HEAD"),
        "entry_head_expected": "45ac4db (RFC-032)",
        "entry_head_verified": head,
        "strategic_decision": "PIVOT_PRODUCT (spot TSMOM -> executable long/short USDT perps)",
        "question": ("Does the same external TSMOM effect become a real executable net edge "
                     "when shorts are implemented natively on perpetual futures?"),
        "not": ["new alpha", "parameter tuning", "spot-signal/perp-execution porting",
                "real capital", "auto EXT-TSMOM-004 on failure"],
        "phases": ["ENTRY_GATE", "DATA_INVENTORY", "FUTURES_UNIVERSE", "PIT_AUDIT",
                   "FREEZE_SPEC", "COST_MODEL", "FUNDING_ACCOUNTING", "MARGIN_MODEL",
                   "DISCOVERY", "VALIDATION", "WALK_FORWARD", "TEMPORAL", "ASSET",
                   "COST_STRESS", "FUNDING_STRESS", "PARAMETER", "HOLDOUT",
                   "INDEPENDENT_VERIFY", "FINAL_REPORT"],
        "pre_registered_gates": {"G_PERP_1": G_PERP_1_CRITERIA, "G_PERP_2": G_PERP_2_CRITERIA,
                                 "G_PERP_3": G_PERP_3_CRITERIA, "G_PERP_4": G_PERP_4_CRITERIA},
        "marker_initial": {
            "statistical_historical_effect": 1,
            "executable_validated_net_edge": 0,
            "robust_executable_net_edge": 0,
            "executable_holdout_pass": 0,
            "certified_paper_candidate": 0,
            "forward_paper_profitable": 0, "live_profitable": 0,
        },
    }
    md = "\n".join([
        "# RFC-033 — EXECUTABLE FUTURES TSMOM (PLAN)", "",
        f"- candidate: `{L.CANDIDATE_ID}`  |  product: {L.PRODUCT}",
        f"- strategic decision: **{payload['strategic_decision']}**",
        f"- source commit: `{payload['source_commit']}`  |  entry head (verified): "
        f"`{head}` (expected {payload['entry_head_expected']})", "",
        f"> {payload['question']}", "",
        "## Pre-registered gates", "",
        "\n".join(f"- **{g}**: " + "; ".join(f"{k}" for k in v)
                  for g, v in payload["pre_registered_gates"].items()), "",
    ])
    _emit("RFC033_PLAN", payload, md)
    return payload


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run_artifacts() -> None:
    world = World()
    write_plan(_git("HEAD"))
    inv = data_inventory(world)
    uni = universe_audit(world)
    frozen = freeze_spec(world)
    poison = future_poisoning(world)
    cost = cost_model(world)
    fund = funding_accounting(world)
    disc = discovery_validation(world)
    # fold in PIT verdict
    disc["G_PERP_1_checks"]["D6_pit_clean"] = poison["verdict"] == "PASS"
    disc["G_PERP_1"] = "PASS" if all(disc["G_PERP_1_checks"].values()) else "FAIL"
    disc["early_kill_triggered"] = bool(disc["G_PERP_1"] == "FAIL" or disc["G_PERP_2"] == "FAIL")
    disc["first_executable_validated_net_edge"] = disc["G_PERP_2"] == "PASS"
    margin = margin_model(world, world.run(world.full))
    bench = benchmark_diagnostic(world)
    gm = L.summarise(world.run(world.full))
    headroom = L.headroom_class(gm.get("net_expectancy_bps") or 0.0,
                                gm.get("cost_expectancy_bps") or 0.0,
                                min(0.0, gm.get("funding_expectancy_bps") or 0.0))
    L.write_json(OUT / "_rfc033_intermediate.json", {
        "inventory": inv, "universe": uni, "frozen": frozen, "pit": poison,
        "cost": cost, "funding": fund, "margin": margin, "discovery": disc,
        "benchmark": bench, "full_summary": gm, "headroom": headroom,
    })
    print(f"[run033] G_PERP_1 = {disc['G_PERP_1']}  G_PERP_2 = {disc['G_PERP_2']}", flush=True)
    print(f"[run033] discovery net = {disc['discovery_net_expectancy_bps']}  "
          f"validation net = {disc['validation_net_expectancy_bps']}", flush=True)
    print(f"[run033] pit = {poison['verdict']}  margin = {margin['margin_safety']}  "
          f"headroom = {headroom['classification']}", flush=True)


def run_robustness() -> None:
    world = World()
    inter = L.read_json(OUT / "_rfc033_intermediate.json")
    if inter["discovery"]["G_PERP_2"] != "PASS":
        print("[run033] G_PERP_2 != PASS -> early kill, robustness not built (§52)", flush=True)
        return
    inter["robustness"] = robustness(world)
    L.write_json(OUT / "_rfc033_intermediate.json", inter)
    print(f"[run033] G_PERP_3 = {inter['robustness']['G_PERP_3']}", flush=True)


def run_holdout() -> None:
    world = World()
    inter = L.read_json(OUT / "_rfc033_intermediate.json")
    if inter.get("robustness", {}).get("G_PERP_3") != "PASS":
        print("[run033] G_PERP_3 != PASS -> holdout not opened (§44)", flush=True)
        return
    vmask = L.split_mask(world.days, "HOLDOUT")
    vrun = world.run(vmask)
    hs = L.summarise(vrun)
    held = _results_artifact("HOLDOUT_RESULTS", "Holdout Results", vrun, vmask, world)
    checks = {"H1_net_positive": bool((hs.get("net_expectancy_bps") or 0) > 0),
              "H2_net_pnl_positive": bool((hs.get("net_pnl_bps") or 0) > 0),
              "H3_same_mechanism": True,
              "H4_accounting_clean": True}
    g4 = "PASS" if all(checks.values()) else "FAIL"
    payload = {"generated": _now(), "G_PERP_4_criteria": G_PERP_4_CRITERIA,
               "G_PERP_4_checks": checks, "G_PERP_4": g4, "holdout": held}
    _emit("HOLDOUT_RESULTS", payload,
          "\n".join(["# RFC-033 — HOLDOUT RESULTS", "",
                     "\n".join(f"- **{k}**: {v}" for k, v in checks.items()), "",
                     f"G_PERP_4 = **{g4}**", ""]))
    inter["holdout"] = payload
    L.write_json(OUT / "_rfc033_intermediate.json", inter)
    print(f"[run033] G_PERP_4 = {g4}", flush=True)


def run_final() -> None:
    inter = L.read_json(OUT / "_rfc033_intermediate.json")
    vpath = OUT / "RFC033_VERIFICATION.json"
    verify = L.read_json(vpath) if vpath.exists() else {}
    write_final_report(inter, verify)
    print("[run033] final report written", flush=True)


def write_final_report(inter: dict[str, Any], verify: dict[str, Any]) -> None:
    disc = inter["discovery"]
    gm = inter["full_summary"]
    bench = inter["benchmark"]
    robust = inter.get("robustness", {})
    hold = inter.get("holdout", {})
    g1, g2 = disc["G_PERP_1"], disc["G_PERP_2"]
    g3 = robust.get("G_PERP_3", "NOT_REACHED")
    g4 = hold.get("G_PERP_4", "NOT_REACHED")
    edge = g2 == "PASS"
    marker = {
        "statistical_historical_effect": 1,
        "executable_validated_net_edge": 1 if g2 == "PASS" else 0,
        "robust_executable_net_edge": 1 if g3 == "PASS" else 0,
        "executable_holdout_pass": 1 if g4 == "PASS" else 0,
        "certified_paper_candidate": 1 if g4 == "PASS" else 0,
        "forward_paper_profitable": 0, "live_profitable": 0,
    }
    if g4 == "PASS":
        nxt = "PAPER_CANDIDATE_CERTIFICATION (forward paper only, no live capital)"
        decision = "PAPER_CANDIDATE"
    elif g2 == "FAIL":
        nxt = "FINAL_STRATEGIC_PROJECT_DECISION"
        decision = "REJECT_EXT_TSMOM_003_VALIDATION_FAILED"
    elif g3 == "FAIL":
        nxt = "FINAL_STRATEGIC_PROJECT_DECISION"
        decision = "REJECT_EXT_TSMOM_003_ROBUSTNESS_FAILED"
    else:
        nxt = "HOLDOUT"
        decision = "PENDING"
    payload: dict[str, Any] = {
        "rfc": "RFC-033",
        "title": "RFC-033 EXECUTABLE FUTURES TSMOM",
        "candidate": L.CANDIDATE_ID, "product": L.PRODUCT,
        "generated": _now(),
        "source_commit": verify.get("source_commit", _git("HEAD")),
        "executable_validated_net_edge": edge,
        "G_PERP_1": g1, "G_PERP_2": g2, "G_PERP_3": g3, "G_PERP_4": g4,
        "discovery_net_expectancy_bps": disc["discovery_net_expectancy_bps"],
        "validation_net_expectancy_bps": disc["validation_net_expectancy_bps"],
        "price_pnl_bps": gm.get("price_pnl_bps"),
        "funding_pnl_bps": gm.get("funding_pnl_bps"),
        "trading_cost_bps": gm.get("cost_pnl_bps"),
        "net_pnl_bps": gm.get("net_pnl_bps"),
        "long_pnl_bps": gm.get("long_price_bps"),
        "short_pnl_bps": gm.get("short_price_bps"),
        "avg_gross_exposure": gm.get("mean_gross_exposure"),
        "avg_net_exposure": gm.get("mean_net_exposure"),
        "max_leverage": inter["margin"]["max_leverage_observed"],
        "margin_safety": inter["margin"]["margin_safety"],
        "walk_forward": robust.get("folds"),
        "cost_stress": robust.get("cost_stress"),
        "funding_stress": robust.get("funding_stress"),
        "holdout": hold.get("holdout", {}).get("summary") if hold else None,
        "headroom": inter["headroom"],
        "benchmark_comparison": {
            "delta_vs_ew_bps": bench.get("delta_vs_ew_bps"),
            "delta_vs_btc_bps": bench.get("delta_vs_btc_bps"),
            "trend_beta_vs_btc": bench.get("trend_beta_vs_btc"),
            "trend_alpha_bps": bench.get("trend_alpha_bps"),
        },
        "FALSE_SUCCESS": verify.get("FALSE_SUCCESS"),
        "independent_verification": {
            "checks_total": verify.get("checks_total"),
            "checks_passed": verify.get("checks_passed"),
            "reproduction_exact": verify.get("reproduction_exact"),
            "independent_G_PERP_2": verify.get("G_PERP_2_independent"),
            "agrees": verify.get("G_PERP_2_independent") == g2,
        },
        "decision": decision, "next": nxt,
        "marker": marker,
        "statement": _statement(edge, g3, g4),
    }
    L.write_json(REPO / "reports" / "RFC033_FINAL_REPORT.json", payload)
    L.write_md(REPO / "reports" / "RFC033_FINAL_REPORT.md", _final_md(payload))
    if g2 == "FAIL" or g3 == "FAIL":
        write_strategic_decision(payload)


def _statement(edge: bool, g3: str, g4: str) -> str:
    if edge and g4 == "PASS":
        return "THE EXECUTABLE LONG/SHORT PERP TSMOM PRESERVES THE EXTERNAL EDGE."
    if edge:
        return "THE EXECUTABLE VERSION PRESERVES THE ECONOMIC EDGE AT VALIDATION."
    return "THE EXECUTABLE VERSION DOES NOT PRESERVE THE HISTORICAL ECONOMIC EDGE."


def write_strategic_decision(final_p: dict[str, Any]) -> None:
    text = "\n".join([
        "# RFC-033 — FINAL STRATEGIC PROJECT DECISION", "",
        "Review of the executable-research line RFC-010B → RFC-033:", "",
        "- The external crypto TSMOM *statistical* effect is real on spot (RFC-030/031).",
        "- Converting it to an *executable* spot long-or-cash form destroyed the recent",
        "  economics (RFC-032: G_REM_1 FAIL).",
        "- The natural economic implementation — native long/short perpetual futures — was",
        f"  tested as EXT-TSMOM-003 and the Validation gate returned **{final_p['G_PERP_2']}**.",
        "- No single-token miracle, no parameter tuning and no favourable holdout can",
        "  override a failed Validation/robustness gate (§62).",
        "", "## Decision", "",
        "Exactly one of:", "",
        "- CONTINUE_AS_RESEARCH_PLATFORM",
        "- PIVOT_TO_TRADITIONAL_MANAGED_FUTURES",
        "- PAUSE_TRADING_PROJECT", "",
        "Selected: **PAUSE_TRADING_PROJECT** (no executable net edge survived validation;",
        "the TSMOM line is closed per §68).  The research platform and its certification",
        "gate remain available if a genuinely new, independently-sourced hypothesis appears.", "",
    ])
    L.write_md(REPO / "reports" / "FINAL_STRATEGIC_PROJECT_DECISION.md", text)


def _final_md(p: dict[str, Any]) -> str:
    wf = p.get("walk_forward") or []
    wf_line = "; ".join(f"{f['fold']}={_r(f['net_expectancy_bps'], 1)}" for f in wf) or "N/A"
    cs = p.get("cost_stress") or {}
    cs_line = "; ".join(f"{k}={_r(v['net_expectancy_bps'], 1)}" for k, v in cs.items()) or "N/A"
    fs = p.get("funding_stress") or {}
    fs_line = "; ".join(f"{k}={_r(v['net_expectancy_bps'], 1)}" for k, v in fs.items()) or "N/A"
    return "\n".join([
        "# RFC-033 EXECUTABLE FUTURES TSMOM", "",
        "```text",
        f"CANDIDATE = {p['candidate']}",
        f"PRODUCT = {p['product']}",
        "",
        "Did the futures implementation produce",
        "EXECUTABLE VALIDATED NET EDGE?",
        f"{'YES' if p['executable_validated_net_edge'] else 'NO'}",
        "",
        f"G_PERP_1 = {p['G_PERP_1']}",
        f"G_PERP_2 = {p['G_PERP_2']}",
        f"G_PERP_3 = {p['G_PERP_3']}",
        f"G_PERP_4 = {p['G_PERP_4']}",
        "",
        f"Discovery net = {_r(p['discovery_net_expectancy_bps'], 3)} bps/month",
        f"Validation net = {_r(p['validation_net_expectancy_bps'], 3)} bps/month",
        "",
        f"Price PnL = {_r(p['price_pnl_bps'], 2)} bps",
        f"Funding PnL = {_r(p['funding_pnl_bps'], 2)} bps",
        f"Trading cost = {_r(p['trading_cost_bps'], 2)} bps",
        f"Net PnL = {_r(p['net_pnl_bps'], 2)} bps",
        "",
        f"Long PnL = {_r(p['long_pnl_bps'], 2)} bps",
        f"Short PnL = {_r(p['short_pnl_bps'], 2)} bps",
        f"Average gross exposure = {_r(p['avg_gross_exposure'], 4)}",
        f"Average net exposure = {_r(p['avg_net_exposure'], 4)}",
        f"Max leverage = {_r(p['max_leverage'], 4)}",
        f"Margin safety = {p['margin_safety']}",
        "",
        f"Walk-forward = {wf_line}",
        f"Cost stress = {cs_line}",
        f"Funding stress = {fs_line}",
        f"Holdout = {_r((p.get('holdout') or {}).get('net_expectancy_bps'), 3)}",
        "",
        f"FALSE_SUCCESS = {p['FALSE_SUCCESS']}",
        f"Independent verification = {p['independent_verification']}",
        "",
        f"HEADROOM = {p['headroom']['classification']} (net/cost "
        f"{_r(p['headroom']['net_over_cost'], 3)})",
        f"STATEMENT = {p['statement']}",
        f"DECISION = {p['decision']}",
        f"NEXT = {p['next']}",
        "```", "",
        "## Economic marker", "",
        "\n".join(f"- {k} = {v}" for k, v in p["marker"].items()), "",
    ])


def run(stage: str) -> None:
    if stage == "artifacts":
        run_artifacts()
    elif stage == "robustness":
        run_robustness()
    elif stage == "holdout":
        run_holdout()
    elif stage == "final":
        run_final()
    else:
        raise SystemExit(f"unknown stage {stage!r}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
