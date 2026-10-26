"""RFC-038 BLOCK B (§16-§26) -- adversarial null validity audit + valid nulls.

RFC-037 rejected MF-TREND-001 partly because a MARKET-LABEL PERMUTATION gave
p ~= 0.11-0.24 (> 0.05).  Before accepting that as evidence against the trend we
must check whether that null answers the right question, and construct at least
one MARKET-PRESERVING null that does.

Pre-registered null families (MAX 3, §23-§24), all evaluated on the SAME
return-space statistic RFC-037 used (for comparability):

  NULL-1 MARKET_LABEL_PERMUTATION   -- is the signal->market IDENTITY informative?
  NULL-2 BLOCK_CIRCULAR_SHIFT       -- is the signal->TIMING alignment informative?
                                       (shared shift preserves cross-market dependence)
  NULL-3 SIGN_RANDOMISATION         -- does the trend SIGN carry information?

Seeds / simulation counts are fixed before execution.  No strategy change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import rfc037_adversarial as ADV  # noqa: E402

OUT = REPO / "reports" / "managed-futures-decision"
OUT.mkdir(parents=True, exist_ok=True)

CAP = ADV.CAP
WINDOWS = ADV.WINDOWS
N_SIMS = 1000
SEED = 20261005
MIN_LAG = 252               # block shift at least one momentum lookback
BLOCK = 252                 # block length for the block-permutation variant


def _stats(observed: float, null: NDArray[Any]) -> dict[str, Any]:
    std = float(np.std(null, ddof=1)) if null.size > 1 else 0.0
    med = float(np.median(null))
    return {
        "observed": observed,
        "null_median": med,
        "null_mean": float(np.mean(null)),
        "null_std": std,
        "null_p95": float(np.quantile(null, 0.95)),
        "null_p99": float(np.quantile(null, 0.99)),
        "p_null_ge_observed": float(np.mean(null >= observed)),
        "effect_size_vs_null_median": (observed - med) / std if std > 0 else None,
        "n_sims": int(null.size),
    }


def _label_perm(R: NDArray[Any], W: NDArray[Any], obs: float) -> dict[str, Any]:
    M = R.shape[1]
    rng = np.random.default_rng(SEED)
    null = np.empty(N_SIMS)
    for s in range(N_SIMS):
        p = rng.permutation(M)
        null[s] = float((W * R[:, p]).sum()) * CAP
    return _stats(obs, null)


def _circular_shift_shared(R: NDArray[Any], W: NDArray[Any], obs: float) -> dict[str, Any]:
    T = R.shape[0]
    rng = np.random.default_rng(SEED)
    null = np.empty(N_SIMS)
    lo, hi = MIN_LAG, T - MIN_LAG
    for s in range(N_SIMS):
        q = int(rng.integers(lo, hi)) if hi > lo else 0
        null[s] = float((W * np.roll(R, q, axis=0)).sum()) * CAP
    return _stats(obs, null)


def _circular_shift_independent(R: NDArray[Any], W: NDArray[Any], obs: float) -> dict[str, Any]:
    T, M = R.shape
    rng = np.random.default_rng(SEED)
    null = np.empty(N_SIMS)
    lo, hi = MIN_LAG, T - MIN_LAG
    for s in range(N_SIMS):
        Rs = np.empty_like(R)
        for j in range(M):
            q = int(rng.integers(lo, hi)) if hi > lo else 0
            Rs[:, j] = np.roll(R[:, j], q)
        null[s] = float((W * Rs).sum()) * CAP
    return _stats(obs, null)


def _block_permutation_shared(R: NDArray[Any], W: NDArray[Any], obs: float) -> dict[str, Any]:
    T = R.shape[0]
    starts = list(range(0, T, BLOCK))
    if len(starts) < 3:
        return {"status": "TOO_FEW_BLOCKS"}
    bounds = [(s, min(s + BLOCK, T)) for s in starts]
    rng = np.random.default_rng(SEED)
    null = np.empty(N_SIMS)
    for s in range(N_SIMS):
        order = rng.permutation(len(bounds))
        # permute the RETURN timeline only (W stays aligned to its dates); the block
        # order is shared across markets so cross-market dependence is preserved.
        idx = np.concatenate([np.arange(bounds[b][0], bounds[b][1]) for b in order])
        null[s] = float((W * R[idx, :]).sum()) * CAP
    return _stats(obs, null)


def _sign_randomisation(R: NDArray[Any], W: NDArray[Any], obs: float) -> dict[str, Any]:
    M = R.shape[1]
    rng = np.random.default_rng(SEED)
    null = np.empty(N_SIMS)
    for s in range(N_SIMS):
        g = np.where(rng.random(M) < 0.5, 1.0, -1.0)
        null[s] = float((W * g * R).sum()) * CAP
    return _stats(obs, null)


def run() -> dict[str, Any]:
    md = ADV.MarketData()
    out: dict[str, Any] = {}
    for name, (lo_s, hi_s) in WINDOWS.items():
        R, W, _ = ADV.weight_matrix(md, ADV.d2o(lo_s), ADV.d2o(hi_s))
        obs = float((W * R).sum()) * CAP
        out[name] = {
            "observed": obs,
            "n_markets": int(R.shape[1]),
            "n_days": int(R.shape[0]),
            "NULL-1_MARKET_LABEL_PERMUTATION": _label_perm(R, W, obs),
            "NULL-2_BLOCK_CIRCULAR_SHIFT_shared": _circular_shift_shared(R, W, obs),
            "NULL-2_BLOCK_CIRCULAR_SHIFT_independent": _circular_shift_independent(R, W, obs),
            "NULL-2b_BLOCK_PERMUTATION_shared": _block_permutation_shared(R, W, obs),
            "NULL-3_SIGN_RANDOMISATION": _sign_randomisation(R, W, obs),
        }
    return out


def registry() -> dict[str, Any]:
    """Pre-registered randomization registry (§23)."""
    return {
        "statistic": ("return-space proxy sum(W * R) * CAP on the frozen weight matrix "
                      "(same construction as RFC-037; multipliers/costs are applied by "
                      "the real engine and are NOT in this proxy -- documented limitation)"),
        "capital": CAP,
        "n_sims": N_SIMS,
        "seed": SEED,
        "min_lag_days": MIN_LAG,
        "block_days": BLOCK,
        "families": {
            "NULL-1_MARKET_LABEL_PERMUTATION": {
                "purpose": "test whether the signal->market IDENTITY assignment is informative",
                "preserves": ["per-market marginal return distribution", "per-market realized vol",
                              "per-market serial dependence", "cross-market eigen-spectrum"],
                "destroys": ["signal->return pairing by market identity",
                             "consistency between a position's risk scaling and the vol of the "
                             "series it is applied to"],
                "expected_interpretation": ("p>0.05 alone does NOT invalidate the trend; the null "
                                            "is partially mis-specified (risk scaling broken)"),
            },
            "NULL-2_BLOCK_CIRCULAR_SHIFT": {
                "purpose": "test whether the signal->TIMING alignment is informative",
                "preserves": ["per-market return distribution", "volatility clustering",
                              "market identity", "cost structure (weights unchanged)",
                              "cross-market dependence (shared shift)"],
                "destroys": ["signal(t) -> return(t+k) temporal alignment"],
                "expected_interpretation": ("the cleanest market-preserving null; a small p-value "
                                            "supports the trend edge"),
            },
            "NULL-3_SIGN_RANDOMISATION": {
                "purpose": "test whether the trend SIGN carries information beyond random +/-",
                "preserves": ["weight magnitudes (vol scaling)", "market identity",
                              "cross-market dependence"],
                "destroys": ["trend direction"],
                "expected_interpretation": ("a small p-value means the realized long/short "
                                            "direction is informative"),
            },
        },
        "primary_families": ["NULL-1_MARKET_LABEL_PERMUTATION",
                             "NULL-2_BLOCK_CIRCULAR_SHIFT",
                             "NULL-3_SIGN_RANDOMISATION"],
        "rule": "at most three primary families; no adding nulls until a favourable p appears",
    }


def validity() -> dict[str, Any]:
    return {
        "NULL-1_MARKET_LABEL_PERMUTATION": {
            "valid": False,
            "classification": "NULL_MODEL_PARTIALLY_INVALID",
            "rationale": ("permuting market labels relocates each market's risk weight onto a "
                          "different return series, so the ex-ante vol scaling no longer matches "
                          "the traded series. The resulting null worlds are not internally "
                          "consistent alternative economies, so its p-value is not a clean "
                          "rejection of the trend edge."),
        },
        "NULL-2_BLOCK_CIRCULAR_SHIFT": {
            "valid": True,
            "classification": "NULL_MODEL_VALID",
            "rationale": ("a shared circular shift keeps every market's own series and the whole "
                          "cross-market dependence structure intact and only breaks the "
                          "signal->future temporal alignment. This is the appropriate null for "
                          "'no trend edge'."),
        },
        "NULL-3_SIGN_RANDOMISATION": {
            "valid": True,
            "classification": "NULL_MODEL_VALID",
            "rationale": ("flipping the trend sign keeps position magnitudes and cross-market "
                          "structure and isolates the information in the realized direction."),
        },
    }


def main() -> int:
    res = run()
    payload = {"registry": registry(), "validity": validity(), "results": res}
    (OUT / "NULL_MODEL_AUDIT_RAW.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    for w, d in res.items():
        print(f"=== {w}  observed={d['observed']:,.0f} ===")
        for k in ("NULL-1_MARKET_LABEL_PERMUTATION", "NULL-2_BLOCK_CIRCULAR_SHIFT_shared",
                  "NULL-2_BLOCK_CIRCULAR_SHIFT_independent", "NULL-2b_BLOCK_PERMUTATION_shared",
                  "NULL-3_SIGN_RANDOMISATION"):
            s = d[k]
            print(f"  {k:42s} p={s['p_null_ge_observed']:.3f} med={s['null_median']:>14,.0f} "
                  f"p95={s['null_p95']:>14,.0f} eff={s['effect_size_vs_null_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
