"""EDGE-03 shadow — the frozen rulesets, walked over bars that closed after the freeze.

The shadow is a *reading*, not a trade. It runs the same candidate objects the campaign
ran, on the same cost plane, over a window whose start is the first bar that opened after
the frozen end. Three properties are enforced here rather than assumed:

* **the frozen prefix is not rewritten.** The union series is ``frozen bars + forward
  bars``, and the loader refuses if a forward bar does not come after the frozen end or if
  the two series share a bar. A decision can therefore only exist in the forward window,
  while the candidate's warm-up still sees the same past the campaign fed it.
* **no decision is taken inside an open bar.** Bars reach this module through ``ingest``,
  which stores only closed ones, and the window's end is the last stored bar's open time,
  so nothing past it can be read.
* **every booked fill is hypothetical.** Trades carry ``hypothetical: true`` and
  ``order_sent: false``, and this module imports no exchange client at all.

The budget state behind each risk decision is captured as it happens (the same observer
technique WP-EDGE-02's audit used) and published next to the decision, because a refusal
without the state it was measured against is an assertion, not evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.edge01 import simulator as SIM
from trading_bot.research.edge01.campaign import load_risk_policy
from trading_bot.research.edge01.candidates import build_candidates, build_context
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import (
    ASSETS,
    BAR_MS,
    OHLCVBar,
    load_1h,
    load_15m,
    resample,
)
from trading_bot.research.edge01.retest import build_retest_variant

from .ingest import ForwardStore

__all__ = [
    "SHADOW_ARMS",
    "ShadowReader",
    "load_forward_bars",
    "run_shadow",
    "union_series",
]

#: arm id -> how it is built, which bar series it walks and how its intents execute.
SHADOW_ARMS: dict[str, dict[str, Any]] = {
    "edge_trend_01_4h": {
        "builder": "trend",
        "profile": "4h",
        "source": "1h",
        "limit": False,
        "primary": True,
    },
    "edge_trend_01_1d": {
        "builder": "trend",
        "profile": "1d",
        "source": "1h",
        "limit": False,
        "primary": False,
    },
    "edge_intra_01": {"builder": "intra_01", "source": "15m", "limit": False, "primary": False},
    "edge_intra_02": {"builder": "intra_02", "source": "15m", "limit": False, "primary": False},
    "edge_intra_01r_market": {
        "builder": "retest",
        "source": "15m",
        "limit": False,
        "primary": False,
    },
    "edge_intra_01r_limit": {
        "builder": "retest",
        "source": "15m",
        "limit": True,
        "primary": False,
    },
}

#: The intraday candidates read ONE higher-timeframe series for every asset; the frozen
#: campaign fed them BTC's 1h corpus, so the forward lane extends that same series rather
#: than inventing a per-asset context.
CONTEXT_ASSET = "BTC"

#: Hours a 1d/4h/15m reading is given, matching the campaign's own horizons.
HORIZON_MINUTES: dict[str, float] = {"4h": 1440.0, "1d": 4320.0, "15m": 240.0}


def _build(arm_id: str) -> Any:
    spec = SHADOW_ARMS[arm_id]
    kind = spec["builder"]
    if kind == "trend":
        return build_candidates()[f"edge_trend_01_{spec['profile']}"]
    if kind == "intra_01":
        return build_candidates()["edge_intra_01"]
    if kind == "intra_02":
        return build_candidates()["edge_intra_02"]
    if kind == "retest":
        return build_retest_variant()
    raise KeyError(f"unknown shadow arm {arm_id!r}")


def load_forward_bars(
    store: ForwardStore, timeframe: str, symbol: str, *, frozen_end_ms: int
) -> tuple[list[OHLCVBar], dict[str, Any]]:
    """Read one forward series and refuse anything that would reach back past the freeze."""
    rows = store.read(timeframe, symbol)
    bars: list[OHLCVBar] = []
    for row in rows:
        ts = int(row["ts"])
        if ts <= frozen_end_ms:
            raise AssertionError(
                f"forward store holds {timeframe} {symbol} bar {ts}, which is not after the "
                f"frozen end {frozen_end_ms}"
            )
        bars.append(
            OHLCVBar(
                ts=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    bars.sort(key=lambda b: b.ts)
    fetched = sorted({int(r["fetched_at_ms"]) for r in rows})
    provenance = {
        "timeframe": timeframe,
        "symbol": symbol,
        "bars": len(bars),
        "first_ts": bars[0].ts if bars else None,
        "last_ts": bars[-1].ts if bars else None,
        "store_sha256": store.sha256(timeframe, symbol),
        "source": rows[0]["source"] if rows else None,
        "fetched_at_ms": fetched[-1] if fetched else None,
    }
    return bars, provenance


def union_series(frozen: list[OHLCVBar], forward: list[OHLCVBar], *, label: str) -> list[OHLCVBar]:
    """``frozen + forward``, with the seam proved instead of assumed."""
    if not frozen:
        raise AssertionError(f"{label}: the frozen series is empty")
    if forward:
        if forward[0].ts <= frozen[-1].ts:
            raise AssertionError(
                f"{label}: the first forward bar {forward[0].ts} does not come after the "
                f"frozen end {frozen[-1].ts}"
            )
        overlap = {b.ts for b in frozen} & {b.ts for b in forward}
        if overlap:
            raise AssertionError(f"{label}: {len(overlap)} bar(s) exist in both series")
    return [*frozen, *forward]


def aggregate(bars: list[OHLCVBar], *, symbol: str, timeframe: str) -> list[OHLCVBar]:
    """Aggregate a 1h series up to 4h/1d with the project's own complete-bucket rule."""
    corpus = _as_corpus(bars, symbol=symbol)
    return list(resample(corpus, timeframe).bars)


def _as_corpus(bars: list[OHLCVBar], *, symbol: str) -> Any:
    from trading_bot.research.edge01.data import Corpus

    return Corpus(symbol=symbol, timeframe="1h", bars=tuple(bars), sources=("union",), sha256="")


def _metrics(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[tuple[int, float]],
    start_equity: float,
    window_bars: int,
    bar_ms: int,
) -> dict[str, Any]:
    """The small, explicit summary a forward reading needs (no Sharpe over a few weeks).

    ``exposure_pct_of_time`` is the share of the window's asset-bar slots the book was
    actually in a position for, recomputed from the fills the arm booked: a reading that
    made money on one hour of exposure is a different object from one that was always in.
    """
    nets = [float(t["net"]) for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    peak = start_equity
    max_dd = 0.0
    for _ts, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    final = equity_curve[-1][1] if equity_curve else start_equity
    gross_loss = abs(sum(losses))
    total = sum(nets)
    largest = max(nets, key=abs) if nets else None
    return {
        "trades": len(trades),
        "net_usdt": round(total, 6),
        "gross_usdt": round(sum(float(t["gross"]) for t in trades), 6),
        "fees_usdt": round(sum(float(t["fees"]) for t in trades), 6),
        "price_costs_usdt": round(sum(float(t["price_costs"]) for t in trades), 6),
        "final_equity": round(final, 6),
        "return_pct": round((final / start_equity - 1.0) * 100.0, 6) if start_equity else None,
        "win_rate_pct": round(len(wins) / len(nets) * 100.0, 4) if nets else None,
        "profit_factor": round(sum(wins) / gross_loss, 6) if gross_loss else None,
        "expectancy_usdt": round(total / len(nets), 6) if nets else None,
        "max_drawdown_pct": round(max_dd, 6),
        "exposure_pct_of_time": (
            round(
                sum((float(t["exit_ts"]) - float(t["entry_ts"])) / bar_ms for t in trades)
                / window_bars
                * 100.0,
                6,
            )
            if window_bars
            else None
        ),
        "largest_trade_share_of_net": (
            round(largest / total, 6) if largest is not None and total else None
        ),
        "hypothetical": True,
        "order_sent": False,
    }


def _snapshot(
    *,
    arm: str,
    signal: Any,
    mid: float,
    positions: dict[str, Any],
    gate: Any,
    equity: float,
    ts: int,
) -> dict[str, Any]:
    """The budget state at the instant of a decision, in the terms both engines use."""
    open_notional = sum(p.qty * p.entry_fill for p in positions.values())
    drawdown_pct = (
        (gate.peak_equity - equity) / gate.peak_equity * 100.0 if gate.peak_equity > 0 else 0.0
    )
    return {
        "arm": arm,
        "asset": signal.symbol,
        "candidate": signal.candidate,
        "decision_ts": int(ts),
        "equity": round(float(equity), 6),
        "peak_equity": round(float(gate.peak_equity), 6),
        "drawdown_pct": round(drawdown_pct, 6),
        "open_positions_count": len(positions),
        "open_positions_notional": round(open_notional, 6),
        # Per-asset notional, so the parity harness can rebuild the same book for BOTH
        # engines instead of splitting one total evenly.
        "open_notional_by_asset": {
            asset: round(p.qty * p.entry_fill, 6) for asset, p in positions.items()
        },
        "open_assets": sorted(positions),
        "asset_held": signal.symbol in positions,
        "trades_today": int(gate.trades_today),
        "consecutive_losses": int(gate.consecutive_losses),
        "cooldown_until_ts": int(gate.cooldown_until_ts),
        "entry_mid": round(float(mid), 8),
        "stop": round(float(signal.stop), 8),
        "targets": [round(float(t), 8) for t in signal.targets],
        "stop_distance": round(float(mid) - float(signal.stop), 8),
        "timeframe": signal.decision_timeframe,
    }


@dataclass
class ShadowReader:
    """Runs the arms and remembers the budget state behind every risk decision."""

    repo_root: Path
    store: ForwardStore
    captures: list[dict[str, Any]] = field(default_factory=list)
    policy: Any = None
    _current_arm: str | None = None
    _original_enter: Any = None

    def __post_init__(self) -> None:
        self.repo_root = Path(self.repo_root)
        if self.policy is None:
            self.policy = load_risk_policy()

    # -- observer ----------------------------------------------------------
    def install(self) -> None:
        """Wrap ``simulator._enter`` so each decision publishes the budget it faced."""
        if self._original_enter is not None:  # pragma: no cover - idempotent by design
            return
        self._original_enter = SIM._enter
        reader = self
        original = self._original_enter

        def observed(signal: Any, **kwargs: Any) -> float:
            state = _snapshot(
                arm=reader._current_arm or "unknown",
                signal=signal,
                mid=kwargs["mid"],
                positions=kwargs["positions"],
                gate=kwargs["gate"],
                equity=kwargs["equity"],
                ts=kwargs["ts"],
            )
            result = kwargs["result"]
            before = len(result.refusals)
            delta = original(signal, **kwargs)
            refused = len(result.refusals) > before
            state["decision"] = "REFUSED" if refused else "APPROVED"
            state["reason"] = result.refusals[-1].get("reason") if refused else None
            state["entry_notional"] = round(abs(delta), 6) if not refused else None
            reader.captures.append(state)
            return float(delta)

        SIM._enter = observed

    def remove(self) -> None:
        if self._original_enter is not None:
            SIM._enter = self._original_enter
            self._original_enter = None

    # -- one arm -----------------------------------------------------------
    def run_arm(
        self,
        *,
        arm_id: str,
        bars_by_asset: dict[str, list[OHLCVBar]],
        window_start_ts: int,
        context: Any = None,
        scenario: str = "BASE",
        label: str | None = None,
    ) -> dict[str, Any]:
        """Run one arm under one cost scenario.

        ``label`` is what every published row calls this reading. It is scenario-qualified
        (``edge_trend_01_4h:BASE``) because three cost scenarios produce three different
        sets of fills, and a ledger whose rows all answer to the same name cannot be summed
        against the summary it belongs to.
        """
        label = label or arm_id
        candidate = _build(arm_id)
        single = len(bars_by_asset) == 1
        timeframe = getattr(candidate, "timeframe", "?")
        horizon = HORIZON_MINUTES[timeframe]
        plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon).scaled(scenario)
        # The captured state is labelled with the SAME scenario-qualified name the rows and
        # the summaries use, so a decision in the ledger can be traced to its reading.
        self._current_arm = label
        sim = SIM.run_portfolio(
            candidate=candidate,
            bars_by_asset=bars_by_asset,
            plane=plane,
            policy=self.policy,
            context=context,
            exit_ema=None,
            window_start_ts=window_start_ts,
            window_end_ts=None,
            limit_entries=bool(SHADOW_ARMS[arm_id]["limit"]),
        )
        refusal_mix: dict[str, int] = {}
        for refusal in sim.refusals:
            key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
            refusal_mix[key] = refusal_mix.get(key, 0) + 1
        trades = [{**t, "hypothetical": True, "order_sent": False, "arm": label} for t in sim.trades]
        orders = [{**o, "hypothetical": True, "order_sent": False, "arm": label} for o in sim.orders]
        signals = [
            {**s, "hypothetical": True, "order_sent": False, "arm": label} for s in sim.signals
        ]
        last_bar_ts = max((bars[-1].ts for bars in bars_by_asset.values() if bars), default=None)
        window_bars = sum(
            1 for bars in bars_by_asset.values() for bar in bars if bar.ts >= window_start_ts
        )
        return {
            "arm": label,
            "arm_id": arm_id,
            "scenario": scenario,
            "timeframe": timeframe,
            "single_asset_book": single,
            "plane": plane.to_dict(),
            "window_start_ts": window_start_ts,
            "window_end_ts": last_bar_ts,
            "window_bars": window_bars,
            "bars_seen": sim.bars_seen,
            "per_asset_bars": dict(sim.per_asset_bars),
            "signals": signals,
            "signal_count": len(signals),
            "refusals": sim.refusals,
            "refusal_mix": refusal_mix,
            "order_count": len(orders),
            "orders": orders,
            "trades": trades,
            "equity_curve": sim.equity_curve,
            "metrics": _metrics(
                trades=trades,
                equity_curve=sim.equity_curve,
                start_equity=self.policy.start_equity,
                window_bars=window_bars,
                bar_ms=BAR_MS[timeframe],
            ),
            "candidate_bars_evaluated": getattr(candidate, "bars_evaluated", None),
            "candidate_warmup_bars": getattr(candidate, "warmup_bars", None),
            "hypothetical": True,
            "order_sent": False,
            "exchange_client": None,
        }


def run_shadow(
    *,
    repo_root: Path,
    store: ForwardStore,
    frozen_1h_end_ms: int,
    frozen_15m_end_ms: int,
    scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE"),
    assets: tuple[str, ...] = ASSETS,
) -> dict[str, Any]:
    """Read every declared arm over the forward window; publish decisions and budget state."""
    reader = ShadowReader(repo_root=repo_root, store=store)
    reader.install()
    arms: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    try:
        # ---- the 1h union, used directly by 4h/1d aggregation and as the intraday context
        union_1h: dict[str, list[OHLCVBar]] = {}
        for asset in assets:
            frozen = list(load_1h(asset).bars)
            forward, prov = load_forward_bars(store, "1h", asset, frozen_end_ms=frozen_1h_end_ms)
            provenance[f"1h:{asset}"] = {**prov, "frozen_last_ts": frozen[-1].ts}
            union_1h[asset] = union_series(frozen, forward, label=f"1h:{asset}")

        for profile in ("4h", "1d"):
            arm_id = f"edge_trend_01_{profile}"
            bars_by_asset: dict[str, list[OHLCVBar]] = {}
            last_frozen: dict[str, int] = {}
            for asset in assets:
                frozen_profile = aggregate(
                    list(load_1h(asset).bars), symbol=asset, timeframe=profile
                )
                if not frozen_profile:  # pragma: no cover - a corpus that cannot aggregate
                    raise AssertionError(f"{asset}: the frozen {profile} series is empty")
                last_frozen[asset] = frozen_profile[-1].ts
                bars_by_asset[asset] = aggregate(union_1h[asset], symbol=asset, timeframe=profile)
            start = max(last_frozen.values()) + BAR_MS[profile]
            if all(bars[-1].ts < start for bars in bars_by_asset.values()):
                arms[arm_id] = {
                    "arm": arm_id,
                    "status": "no_forward_bars",
                    "reason": (
                        f"no complete {profile} bucket opened after the frozen end "
                        f"{max(last_frozen.values())}"
                    ),
                    "hypothetical": True,
                    "order_sent": False,
                }
                continue
            for scenario in scenarios:
                arms[f"{arm_id}:{scenario}"] = reader.run_arm(
                    arm_id=arm_id,
                    bars_by_asset=bars_by_asset,
                    window_start_ts=start,
                    context=None,
                    scenario=scenario,
                    label=f"{arm_id}:{scenario}",
                )

        # ---- intraday arms: native 15m bars, with the extended 1h series as context
        if "15m" in {SHADOW_ARMS[a]["source"] for a in SHADOW_ARMS}:
            union_15m: dict[str, list[OHLCVBar]] = {}
            last_frozen_15m: dict[str, int] = {}
            for asset in assets:
                frozen = list(load_15m(asset).bars)
                forward, prov = load_forward_bars(
                    store, "15m", asset, frozen_end_ms=frozen_15m_end_ms
                )
                provenance[f"15m:{asset}"] = {**prov, "frozen_last_ts": frozen[-1].ts}
                union_15m[asset] = union_series(frozen, forward, label=f"15m:{asset}")
                last_frozen_15m[asset] = frozen[-1].ts
            context = build_context(
                list(union_1h[CONTEXT_ASSET]), timeframe="1h", fast=50, slow=200
            )
            start15 = max(last_frozen_15m.values()) + BAR_MS["15m"]
            forward_exists = any(bars[-1].ts >= start15 for bars in union_15m.values())
            for arm_id, spec in SHADOW_ARMS.items():
                if spec["source"] != "15m":
                    continue
                if not forward_exists:
                    arms[arm_id] = {
                        "arm": arm_id,
                        "status": "no_forward_bars",
                        "reason": (
                            "no 15m bar opened after the frozen end "
                            f"{max(last_frozen_15m.values())}"
                        ),
                        "hypothetical": True,
                        "order_sent": False,
                    }
                    continue
                for scenario in scenarios if not spec["limit"] else ("BASE",):
                    arms[f"{arm_id}:{scenario}"] = reader.run_arm(
                        arm_id=arm_id,
                        bars_by_asset=union_15m,
                        window_start_ts=start15,
                        context=context,
                        scenario=scenario,
                        label=f"{arm_id}:{scenario}",
                    )
    finally:
        reader.remove()

    primary = arms.get("edge_trend_01_4h:BASE", {})
    return {
        "arms": arms,
        "provenance": provenance,
        "decisions": reader.captures,
        "primary_arm": "edge_trend_01_4h:BASE",
        "primary_available": bool(primary and primary.get("status") != "no_forward_bars"),
        "context_note": (
            f"the intraday arms read the 1h series of {CONTEXT_ASSET}, exactly as the frozen "
            "campaign did, extended with the forward 1h bars so the context covers the window"
        ),
        "hypothetical": True,
        "order_sent": False,
    }
