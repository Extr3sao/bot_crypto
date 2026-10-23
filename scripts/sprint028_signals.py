"""RFC-028 — pre-registered carry hypotheses and their signals (§21-§29).

Information-first: each hypothesis maps PIT-safe trailing features to a
*signed* signal that would be positively informative **if the hypothesis
holds**.  The information audit measures its rank IC against the forward carry
target; the sign of the measured IC is the empirical direction.

Two families (§28 family-wise null):
    FUNDING  (C1..C5)  predicts FUTURE REALIZED FUNDING (bps).
    BASIS    (C6)      predicts the BASIS / residual PnL leg.

Budget: 13 core hypotheses x 6 horizons = 78 pre-registered variants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import sprint028_lib as L
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Hypothesis:
    hid: str
    family: str
    signal_kind: str
    core_feature: str
    target_kind: str
    description: str


HYPOTHESES: tuple[Hypothesis, ...] = (
    # ---- C1 funding persistence ------------------------------------------
    Hypothesis(
        "H-C1-MEAN3",
        "FUNDING",
        "f_mean_k",
        "f_mean_k",
        "funding",
        "trailing 24h funding mean predicts future funding",
    ),
    Hypothesis(
        "H-C1-MEAN9",
        "FUNDING",
        "f_mean_9",
        "f_mean_9",
        "funding",
        "trailing 72h funding mean predicts future funding",
    ),
    Hypothesis(
        "H-C1-MEAN21",
        "FUNDING",
        "f_mean_21",
        "f_mean_21",
        "funding",
        "trailing 7d funding mean predicts future funding",
    ),
    Hypothesis(
        "H-C1-PERSIST",
        "FUNDING",
        "f_persist_k",
        "f_persist_k",
        "funding",
        "trailing fraction of positive funding periods predicts funding",
    ),
    Hypothesis(
        "H-C1-LAST",
        "FUNDING",
        "f_last",
        "f_last",
        "funding",
        "last realized funding rate predicts future funding",
    ),
    # ---- C2 funding + basis ----------------------------------------------
    Hypothesis(
        "H-C2-BASISPOS",
        "FUNDING",
        "f_mean_k_basis_pos",
        "f_mean_k",
        "funding",
        "funding persistence restricted to positive-basis regime",
    ),
    Hypothesis(
        "H-C2-COMBINED",
        "FUNDING",
        "f_mean_k_basis_pos",
        "f_mean_k",
        "combined",
        "funding persistence + basis together predict total carry",
    ),
    # ---- C3 funding + OI --------------------------------------------------
    Hypothesis(
        "H-C3-OIUP",
        "FUNDING",
        "f_mean_k_oi_up",
        "f_mean_k",
        "funding",
        "funding persistence when OI is expanding",
    ),
    Hypothesis(
        "H-C3-OIDN",
        "FUNDING",
        "f_mean_k_oi_dn",
        "f_mean_k",
        "funding",
        "funding persistence when OI is contracting",
    ),
    # ---- C4 funding + crowding -------------------------------------------
    Hypothesis(
        "H-C4-CROWD",
        "FUNDING",
        "f_mean_k_crowd",
        "f_mean_k",
        "funding",
        "funding persistence under extreme long crowding",
    ),
    # ---- C5 funding + volatility -----------------------------------------
    Hypothesis(
        "H-C5-VOL",
        "FUNDING",
        "f_mean_k_vol",
        "f_mean_k",
        "funding",
        "funding persistence during volatility events",
    ),
    # ---- C6 basis convergence --------------------------------------------
    Hypothesis(
        "H-C6-BASIS",
        "BASIS",
        "neg_basis",
        "basis",
        "basis",
        "positive spot-perp basis converges (long spot / short perp)",
    ),
    Hypothesis(
        "H-C6-BASIS-MEAN",
        "BASIS",
        "neg_basis_mean",
        "basis_mean_k",
        "basis",
        "trailing positive basis mean predicts basis convergence",
    ),
)

FAMILIES = ("FUNDING", "BASIS")


@dataclass(frozen=True, slots=True)
class Variant:
    variant_id: str
    hid: str
    family: str
    horizon_key: str
    horizon_periods: int
    target_kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "hypothesis_id": self.hid,
            "family": self.family,
            "horizon_key": self.horizon_key,
            "horizon_periods": self.horizon_periods,
            "target_kind": self.target_kind,
        }


def build_variants() -> list[Variant]:
    out: list[Variant] = []
    for h in HYPOTHESES:
        for hk in L.HORIZON_ORDER:
            out.append(
                Variant(
                    variant_id=f"{h.hid}@{hk}",
                    hid=h.hid,
                    family=h.family,
                    horizon_key=hk,
                    horizon_periods=L.HORIZON_PERIODS[hk],
                    target_kind=h.target_kind,
                )
            )
    return out


def signal_array(h: Hypothesis, panel: L.CarryPanel) -> NDArray[Any]:
    f = panel.features
    k = h.signal_kind
    if k == "f_mean_k":
        return f["f_mean_k"]
    if k == "f_mean_9":
        return f["f_mean_9"]
    if k == "f_mean_21":
        return f["f_mean_21"]
    if k == "f_persist_k":
        return f["f_persist_k"]
    if k == "f_last":
        return f["f_last"]
    if k == "f_mean_k_basis_pos":
        return np.where(f["basis"] > 0, f["f_mean_k"], np.nan)
    if k == "f_mean_k_oi_up":
        return np.where(f["oi_chg"] > 0, f["f_mean_k"], np.nan)
    if k == "f_mean_k_oi_dn":
        return np.where(f["oi_chg"] < 0, f["f_mean_k"], np.nan)
    if k == "f_mean_k_crowd":
        return np.where(f["crowd_z"] > 1.0, f["f_mean_k"], np.nan)
    if k == "f_mean_k_vol":
        return np.where(f["vol_z"] > 1.0, f["f_mean_k"], np.nan)
    if k == "neg_basis":
        return -f["basis"]
    if k == "neg_basis_mean":
        return -f["basis_mean_k"]
    raise ValueError(f"unknown signal_kind {k}")


def variant_signal(v: Variant, panel: L.CarryPanel) -> NDArray[Any]:
    h = next(h for h in HYPOTHESES if h.hid == v.hid)
    return signal_array(h, panel)


def target_array(v: Variant, panel: L.CarryPanel) -> NDArray[Any]:
    h = next(hh for hh in HYPOTHESES if hh.hid == v.hid)
    p = v.horizon_periods
    if h.target_kind == "funding":
        return np.asarray(panel.fwd_funding[p], dtype=np.float64)
    if h.target_kind == "basis":
        return np.asarray(panel.fwd_basis_pnl[p], dtype=np.float64)
    if h.target_kind == "combined":
        return np.asarray(panel.fwd_funding[p] + panel.fwd_basis_pnl[p], dtype=np.float64)
    raise ValueError(f"unknown target_kind {h.target_kind}")


def entry_signal(v: Variant, panel: L.CarryPanel, rule: str, direction: int = 1) -> NDArray[Any]:
    """Pre-registered boolean entry rules for a strategy candidate (§29).

    The signal is the hypothesis's own (PIT-safe) signal, oriented by the sign
    of its discovery IC (``direction``).  A trade opens when that oriented
    signal is positive.

    RULE_POS : open purely on the oriented signal.
    RULE_BE  : additionally require the expected carry to cover the cost:
               funding hypotheses need ``f_mean_k * h >= round_trip``;
               basis hypotheses need ``|basis| >= round_trip``.
    """
    h = next(x for x in HYPOTHESES if x.hid == v.hid)
    s: NDArray[Any] = np.asarray(signal_array(h, panel), dtype=np.float64) * float(direction)
    if h.family == "BASIS":
        core = np.abs(np.asarray(panel.features[h.core_feature], dtype=np.float64))
    else:
        core = np.asarray(panel.features["f_mean_k"], dtype=np.float64) * v.horizon_periods
    if rule == "RULE_POS":
        return np.asarray(np.isfinite(s) & (s > 0.0), dtype=bool)
    if rule == "RULE_BE":
        return np.asarray(
            np.isfinite(s) & (s > 0.0) & np.isfinite(core) & (core >= L.ROUND_TRIP_COST_BPS),
            dtype=bool,
        )
    raise ValueError(f"unknown rule {rule}")


ENTRY_RULES = ("RULE_POS", "RULE_BE")
