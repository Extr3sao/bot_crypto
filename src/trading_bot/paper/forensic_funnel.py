"""POC01 forensic funnel analysis (Track A2) — observation layer only.

ALPHA-DISCOVERY-AND-SHADOW-V2-01. Consumes canonical daily-report activity
payloads and produces:

- gate-by-gate conversion rates over the full funnel
  MARKET_SCAN -> SIGNAL -> PROPOSAL -> DEBATE -> SELECTED -> VERIFIED
  -> RISK -> PAPER;
- loss attribution: WHERE the frequency died (NO_SIGNAL, STRATEGY_FILTERING,
  AGENT_DECISION, RISK_COOLDOWN, MAX_POSITIONS, OTHER_RISK, NO_PAPER_FILL);
- strategy / asset / regime / risk-reason breakdowns.

Nothing here changes a gate, a threshold, or any runtime behavior: this is
diagnosis of recorded observations. Where the recorded artifacts do not
carry a dimension (e.g. per-strategy signal counts are not persisted by the
current runtime), the loss bucket is reported as NOT_RECORDED rather than
inferred — honest gaps over fabricated attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "FunnelGates",
    "FunnelLossAttribution",
    "GateConversion",
    "attribute_losses",
    "build_funnel",
]


class FunnelGates:
    """Canonical gate names in funnel order."""

    MARKET_SCAN = "MARKET_SCAN"
    SIGNAL = "SIGNAL"
    PROPOSAL = "PROPOSAL"
    DEBATE = "DEBATE"
    SELECTED = "SELECTED"
    VERIFIED = "VERIFIED"
    RISK = "RISK"
    PAPER = "PAPER"

    ORDER: tuple[str, ...] = (
        MARKET_SCAN,
        SIGNAL,
        PROPOSAL,
        DEBATE,
        SELECTED,
        VERIFIED,
        RISK,
        PAPER,
    )


@dataclass(frozen=True, slots=True)
class GateConversion:
    gate: str  # conversion INTO this gate
    count: int
    from_count: int
    rate: float  # count / from_count (1.0 for the first gate)


@dataclass(frozen=True, slots=True)
class FunnelLossAttribution:
    """Where frequency died, quantified at the bottleneck gate."""

    bottleneck_gate: str  # first gate where the funnel collapsed
    primary_loss_bucket: str  # NO_SIGNAL / STRATEGY_FILTERING / ... / NOT_RECORDED
    buckets: dict[str, int]  # loss bucket -> attributed counts
    by_strategy: dict[str, int]
    by_asset: dict[str, int]
    by_regime: dict[str, int]
    by_risk_reason: dict[str, int]
    notes: tuple[str, ...]


def build_funnel(activity: dict[str, Any]) -> list[GateConversion]:
    """Compute conversions from a daily-report ``activity`` payload.

    Accepted keys (as persisted by the runtime): market_scans,
    trade_proposals, debates, selected_decisions, no_trade,
    risk_accepts, risk_rejects, executed_paper_trades. Where the runtime
    does not persist an intermediate gate (signals, verified), the count
    is carried as ``None`` and the rate reported as ``None`` (NOT_RECORDED).
    """
    scans = int(activity.get("market_scans", 0) or 0)
    # SIGNAL count is not persisted by the current runtime -> NOT_RECORDED.
    signals_raw = activity.get("signals")
    signals: int | None = int(signals_raw) if signals_raw is not None else None
    proposals = int(activity.get("trade_proposals", 0) or 0)
    debates = int(activity.get("debates", 0) or 0)
    selected = int(activity.get("selected_decisions", 0) or 0)
    no_trade = int(activity.get("no_trade", 0) or 0)
    risk_accepts = int(activity.get("risk_accepts", 0) or 0)
    risk_rejects = int(activity.get("risk_rejects", 0) or 0)
    paper_trades = int(activity.get("executed_paper_trades", 0) or 0)

    verified_raw = activity.get("verified")
    # The decision packages record verifier outcomes; the daily payload
    # does not. Keep NOT_RECORDED unless the caller supplies it.
    verified: int | None = int(verified_raw) if verified_raw is not None else None

    risk_total = risk_accepts + risk_rejects
    counts: dict[str, int | None] = {
        FunnelGates.MARKET_SCAN: scans,
        FunnelGates.SIGNAL: signals,
        FunnelGates.PROPOSAL: proposals,
        FunnelGates.DEBATE: debates,
        FunnelGates.SELECTED: selected,
        FunnelGates.VERIFIED: verified,
        FunnelGates.RISK: risk_total,
        FunnelGates.PAPER: paper_trades,
    }

    conversions: list[GateConversion] = []
    prev: int | None = None
    for gate in FunnelGates.ORDER:
        count = counts[gate]
        if prev is None:
            rate = 1.0 if count is not None else None
        elif count is None or prev is None:
            rate = None
        else:
            rate = (count / prev) if prev > 0 else None
        conversions.append(
            GateConversion(
                gate=gate,
                count=count if count is not None else -1,
                from_count=prev if prev is not None else -1,
                rate=rate if rate is not None else -1.0,
            )
        )
        if count is not None:
            prev = count
    del signals, verified, no_trade
    return conversions


def attribute_losses(
    activity: dict[str, Any],
    *,
    by_strategy: dict[str, int] | None = None,
    by_asset: dict[str, int] | None = None,
    by_regime: dict[str, int] | None = None,
    risk_rejects_by_reason: dict[str, int] | None = None,
) -> FunnelLossAttribution:
    """Attribute the frequency failure to funnel buckets.

    Decision procedure (recorded data only, no inference):

    - scans > 0 and proposals == 0 -> the collapse is BEFORE the proposal
      gate: bucket ``NO_SIGNAL`` when scans produced no tradable signal
      (or ``STRATEGY_FILTERING`` if the caller supplies evidence that
      signals fired but strategies were filtered).
    - proposals > 0 and selected == 0 -> ``AGENT_DECISION``.
    - risk_rejects > 0 and risk_accepts == 0 -> reason buckets from
      ``risk_rejects_by_reason`` (RISK_COOLDOWN / MAX_POSITIONS / ...).
    - paper < risk_accepts -> ``NO_PAPER_FILL``.
    - Unrecordable splits are reported as ``NOT_RECORDED`` counts.
    """
    scans = int(activity.get("market_scans", 0) or 0)
    proposals = int(activity.get("trade_proposals", 0) or 0)
    selected = int(activity.get("selected_decisions", 0) or 0)
    risk_accepts = int(activity.get("risk_accepts", 0) or 0)
    risk_rejects = int(activity.get("risk_rejects", 0) or 0)
    paper = int(activity.get("executed_paper_trades", 0) or 0)
    reasons = dict(risk_rejects_by_reason or {})

    buckets: dict[str, int] = {}
    notes: list[str] = []

    if scans > 0 and proposals == 0:
        bottleneck = FunnelGates.PROPOSAL
        buckets["NO_SIGNAL"] = buckets.get("NO_SIGNAL", 0) + max(scans, 0)
        notes.append(
            "collapse before PROPOSAL gate: scans produced no proposals "
            "(NO_SIGNAL bucket; per-strategy signal counts not persisted -> "
            "NO_SIGNAL vs STRATEGY_FILTERING split is NOT_RECORDED)"
        )
        buckets["NOT_RECORDED"] = buckets.get("NOT_RECORDED", 0)
    elif proposals > 0 and selected == 0 and risk_rejects == 0:
        bottleneck = FunnelGates.SELECTED
        buckets["AGENT_DECISION"] = proposals
        notes.append("collapse at SELECTED: proposals existed but none selected")
    elif risk_rejects > 0 and risk_accepts == 0:
        bottleneck = FunnelGates.RISK
        total_reasons = sum(reasons.values()) or risk_rejects
        for reason, n in reasons.items():
            buckets[f"RISK_{reason}"] = n
        if not reasons:
            buckets["OTHER_RISK"] = risk_rejects
            notes.append("risk rejects present but per-reason counts not recorded")
        del total_reasons
    elif paper < risk_accepts:
        bottleneck = FunnelGates.PAPER
        buckets["NO_PAPER_FILL"] = risk_accepts - paper
        notes.append("risk-accepted candidates did not all become paper trades")
    else:
        bottleneck = FunnelGates.PAPER if paper > 0 else FunnelGates.PROPOSAL
        buckets["NO_SIGNAL"] = buckets.get("NO_SIGNAL", 0)
        if scans == 0:
            notes.append("no scans recorded for the day")

    return FunnelLossAttribution(
        bottleneck_gate=bottleneck,
        primary_loss_bucket=(
            max(buckets, key=lambda k: buckets[k]) if any(buckets.values()) else "NONE"
        ),
        buckets=buckets,
        by_strategy=dict(by_strategy or {}),
        by_asset=dict(by_asset or {}),
        by_regime=dict(by_regime or {}),
        by_risk_reason=dict(reasons),
        notes=tuple(notes),
    )
