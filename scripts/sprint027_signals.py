"""RFC-027 — pre-registered positioning hypotheses and their signals (§25-§32).

Each hypothesis maps the PIT-safe trailing features to a *signed* signal that
would be positively predictive **if the hypothesis holds**.  The information
audit measures the rank correlation (IC) of that signal with the forward signed
return; the sign of the measured IC is the empirical direction (never assumed).

Budget (§25, §55): <= 12 core hypotheses, <= 120 variants.  Variants are
(horizon) x (condition); the two mirror hypotheses H-OI-03 / H-OI-04 are
registration duplicates of H-OI-01 / H-OI-02 and are marked ``mirror_of`` so
they never inflate the family null (they share the same |IC|).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import sprint027_lib as L
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Hypothesis:
    hid: str
    family: str
    features: tuple[str, ...]
    signal_kind: str
    description: str
    prior: str = "unspecified"
    mirror_of: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# registry (frozen BEFORE any result)
# ---------------------------------------------------------------------------

HYPOTHESES: tuple[Hypothesis, ...] = (
    # ---- family P0_oi : price x open interest -----------------------------
    Hypothesis(
        "H-OI-01", "P0_oi", ("ret1", "oi_z"), "sign_ret_oi_z",
        "price up + OI up -> continuation (and the down/down mirror)",
        prior="continuation"),
    Hypothesis(
        "H-OI-02", "P0_oi", ("ret1", "oi_z"), "sign_ret_neg_oi_z",
        "price up + OI down -> exhaustion / short-covering",
        prior="reversal"),
    Hypothesis(
        "H-OI-03", "P0_oi", ("ret1", "oi_z"), "neg_sign_ret_oi_z",
        "price down + OI up -> downside continuation",
        prior="continuation", mirror_of="H-OI-02"),
    Hypothesis(
        "H-OI-04", "P0_oi", ("ret1", "oi_z"), "neg_sign_ret_neg_oi_z",
        "price down + OI down -> liquidation exhaustion",
        prior="reversal", mirror_of="H-OI-01"),
    Hypothesis(
        "H-OI-ACCEL", "P0_oi", ("oi_accel",), "z_oi_accel",
        "OI acceleration (second difference) predicts continuation",
        prior="continuation"),
    Hypothesis(
        "H-OI-LEVEL", "P0_oi", ("oi_z",), "z_oi",
        "OI level z-score (positioning build-up) predicts drift",
        prior="unspecified"),
    Hypothesis(
        "H-OI-OI-VALUE", "P0_oi", ("oi_value",), "z_oi_value",
        "OI notional z-score predicts drift",
        prior="unspecified"),
    # ---- family P0_crowd : crowding / top-vs-global -----------------------
    Hypothesis(
        "H-CROWD-GLOBAL", "P0_crowd", ("ls_global",), "neg_z_ls_global",
        "extreme global crowd long/short -> reversal",
        prior="contrarian"),
    Hypothesis(
        "H-CROWD-TOP", "P0_crowd", ("ls_top",), "neg_z_ls_top",
        "extreme top-trader long/short -> reversal",
        prior="contrarian"),
    Hypothesis(
        "H-TOP-DIV", "P0_crowd", ("top_global_div",), "top_global_div",
        "top-trader vs global divergence -> continuation of the smart side",
        prior="continuation"),
    # ---- family P1_taker : aggressive flow --------------------------------
    Hypothesis(
        "H-TAKER-FADE", "P1_taker", ("taker",), "neg_z_taker",
        "extreme taker long/short volume ratio -> reversal",
        prior="contrarian"),
    Hypothesis(
        "H-TAKER-OI", "P1_taker", ("taker", "doi"), "z_taker_sign_doi",
        "aggressive flow that adds OI -> continuation; flow that closes -> fade",
        prior="unspecified"),
    Hypothesis(
        "H-TAKER-PERSIST", "P1_taker", ("taker_persist",), "neg_z_taker_persist",
        "persistent one-sided taker flow -> reversal (exhaustion)",
        prior="contrarian"),
)

FAMILIES = ("P0_oi", "P0_crowd", "P1_taker")
CONDITIONS = ("ALL", "VOL")   # VOL = signal gated by the certified vol context


def vol_event(panel: L.Panel) -> NDArray[Any]:
    """PIT-safe volatility context: trailing vol z-score > 1.0 (§31)."""
    vz = panel.features["vol_z"]
    return np.asarray(np.isfinite(vz) & (vz > 1.0), dtype=bool)


def _z(panel: L.Panel, name: str) -> NDArray[Any]:
    return L._rolling_z(panel.features[name], L.OI_Z_WIN)


def signal_array(h: Hypothesis, panel: L.Panel) -> NDArray[Any]:
    """Build the raw (unconditioned) signal for one hypothesis."""
    f = panel.features
    ret1 = f["ret1"]
    if h.signal_kind == "sign_ret_oi_z":
        return np.asarray(np.sign(ret1) * _z(panel, "oi"), dtype=np.float64)
    if h.signal_kind == "sign_ret_neg_oi_z":
        return np.asarray(np.sign(ret1) * (-_z(panel, "oi")), dtype=np.float64)
    if h.signal_kind == "neg_sign_ret_oi_z":
        return np.asarray((-np.sign(ret1)) * _z(panel, "oi"), dtype=np.float64)
    if h.signal_kind == "neg_sign_ret_neg_oi_z":
        return np.asarray(np.sign(ret1) * _z(panel, "oi"), dtype=np.float64)
    if h.signal_kind == "z_oi_accel":
        return L._rolling_z(f["oi_accel"], L.OI_Z_WIN)
    if h.signal_kind == "z_oi":
        return _z(panel, "oi")
    if h.signal_kind == "z_oi_value":
        return _z(panel, "oi_value")
    if h.signal_kind == "neg_z_ls_global":
        return -_z(panel, "ls_global")
    if h.signal_kind == "neg_z_ls_top":
        return -_z(panel, "ls_top")
    if h.signal_kind == "top_global_div":
        return L._rolling_z(f["top_global_div"], L.OI_Z_WIN)
    if h.signal_kind == "neg_z_taker":
        return -_z(panel, "taker")
    if h.signal_kind == "z_taker_sign_doi":
        return np.asarray(_z(panel, "taker") * np.sign(f["doi"]), dtype=np.float64)
    if h.signal_kind == "neg_z_taker_persist":
        return -L._rolling_z(f["taker_persist"], L.OI_Z_WIN)
    raise ValueError(f"unknown signal_kind {h.signal_kind}")


@dataclass(frozen=True, slots=True)
class Variant:
    variant_id: str
    hid: str
    family: str
    horizon_bars: int
    horizon_label: str
    condition: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id, "hypothesis_id": self.hid,
            "family": self.family, "horizon_bars": self.horizon_bars,
            "horizon_label": self.horizon_label, "condition": self.condition,
        }


def core_hypotheses() -> list[Hypothesis]:
    """Non-mirror hypotheses (the mirror duplicates never inflate the budget)."""
    return [h for h in HYPOTHESES if h.mirror_of is None]


def build_variants() -> list[Variant]:
    """<= 120 pre-registered variants: core hypotheses x horizons x conditions."""
    out: list[Variant] = []
    for h in core_hypotheses():
        for hb in L.HORIZON_BARS:
            for cond in CONDITIONS:
                out.append(Variant(
                    variant_id=f"{h.hid}@{L.HORIZON_LABEL[hb]}|{cond}",
                    hid=h.hid, family=h.family, horizon_bars=hb,
                    horizon_label=L.HORIZON_LABEL[hb], condition=cond,
                ))
    return out


def variant_signal(v: Variant, panel: L.Panel) -> NDArray[Any]:
    h = next(h for h in HYPOTHESES if h.hid == v.hid)
    s = signal_array(h, panel)
    if v.condition == "VOL":
        s = np.where(vol_event(panel), s, np.nan)
    return s
