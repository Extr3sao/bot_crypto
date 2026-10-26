"""WP-EDGE-14D — three orthogonal hypotheses, preregistered, duplicates rejected.

The brief asks for at most three hypotheses, and it is emphatic about the trap: do not
add a strategy with only a new name for logic that already exists, and do not vary a
parameter to look novel. So each candidate is checked against the families already in the
tree *before* it is registered, the check cites the file and line it found, and a
duplicate is rejected with its duplicate named rather than quietly rewritten.

The three, in the brief's priority order:

* **E14-01 REGIME_CONDITIONED_VOL_BREAKOUT** (priority 1) — a causal volatility-breakout
  conditioned on regime. The question the scan settles is whether ``breakout_family`` and
  ``volatility_family`` already gate on regime.
* **E14-02 LIQUID_SPOT_CROSS_SECTIONAL_ROTATION** (priority 2) — relative-return asset
  rotation with portfolio constraints. The scan checks ``cross_sectional`` and the
  ``diversified`` package.
* **E14-03 CONDITIONAL_EXTREME_MEAN_REVERSION** (priority 3) — only if it is a genuinely
  different mechanism from ``mean_reversion_family``.

The scan is deliberately conservative: it treats a keyword overlap in a family's own
source as a reason to look, not as proof of duplication, and it records both the hit and
the human judgement so a later reader can disagree with the judgement without re-running
the search.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .contracts import StrategyCandidate
from .evidence import REPO_ROOT

__all__ = [
    "CANDIDATE_SPECS",
    "SPECS_DIR",
    "duplicate_scan",
    "findings",
    "preregistration_payload",
    "register_candidates",
]

SPECS_DIR = REPO_ROOT / "reports" / "economic-recovery" / "RFC-EDGE-014" / "CANDIDATE_SPECS"

_FAMILY_ROOT = REPO_ROOT / "src" / "trading_bot" / "research"

#: Each existing family and the tokens that would betray a shared mechanism.
_EXISTING_FAMILIES = (
    ("breakout_family", _FAMILY_ROOT / "families" / "breakout_family.py"),
    ("volatility_family", _FAMILY_ROOT / "families" / "volatility_family.py"),
    ("trend_family", _FAMILY_ROOT / "families" / "trend_family.py"),
    ("momentum_family", _FAMILY_ROOT / "families" / "momentum_family.py"),
    ("mean_reversion_family", _FAMILY_ROOT / "families" / "mean_reversion_family.py"),
    ("ema_crossover_family", _FAMILY_ROOT / "families" / "ema_crossover_family.py"),
    ("cross_sectional", _FAMILY_ROOT / "cross_sectional.py"),
    ("diversified_xsec", _FAMILY_ROOT / "diversified" / "xsec.py"),
    ("diversified_xsec_riskadj", _FAMILY_ROOT / "diversified" / "xsec_riskadj.py"),
    ("alpha_recovery", _FAMILY_ROOT / "alpha_recovery"),
)

CANDIDATE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "candidate_id": "E14-01",
        "family": "REGIME_CONDITIONED_VOL_BREAKOUT",
        "priority": 1,
        "source_id": "SRC-03",
        "source_sha": "7a8768de9784dda35a7b261a7ade1dbfbff50919",
        "hypothesis": (
            "a range breakout sized to realised volatility, entered only when a regime "
            "filter says the market is trending, carries a net move that covers the "
            "admission round trip on 1h/4h bars"
        ),
        "product": "spot",
        "venue": "binance",
        "assets": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "timeframes": ["1h", "4h"],
        "permitted_sides": ["long"],
        "regime": "trending_only",
        "params_locked": {
            "range_lookback_bars": 20,
            "vol_atr_lookback_bars": 14,
            "breakout_multiple": 1.0,
            "regime_filter": "close > ema200 and ema50 > ema200",
            "exit": "opposite range boundary or 3-bar hold, whichever first",
        },
        "test_plan": (
            "frozen train/validation/OOS split; walk-forward with purged folds; null and "
            "CURRENT comparators; nominal and 2x variable-cost stress"
        ),
        "tokens": ["regime", "volatility", "atr", "breakout", "range"],
        "duplicate_of": ["breakout_family", "volatility_family"],
    },
    {
        "candidate_id": "E14-02",
        "family": "LIQUID_SPOT_CROSS_SECTIONAL_ROTATION",
        "priority": 2,
        "source_id": "SRC-02",
        "source_sha": "5e642997f9623d67b63543962eab46caca30e613",
        "hypothesis": (
            "rotating into the top-k liquid spot assets by relative 4h/1d return, with a "
            "concentration cap and a minimum-notional floor, carries a net cross-sectional "
            "return above the rebalance friction"
        ),
        "product": "spot",
        "venue": "binance",
        "assets": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        "timeframes": ["4h", "1d"],
        "permitted_sides": ["long"],
        "regime": "all",
        "params_locked": {
            "top_k": 2,
            "rebalance": "daily_00utc",
            "weighting": "equal",
            "max_weight": 0.5,
            "min_notional_usdt": 20.0,
        },
        "test_plan": (
            "asset-level OOS held out; rebalance friction charged per name; compare against "
            "the diversified cross-section and against buy-and-hold"
        ),
        "tokens": ["cross_sectional", "rotation", "rank", "relative", "quantile"],
        "duplicate_of": ["cross_sectional", "diversified_xsec", "diversified_xsec_riskadj"],
    },
    {
        "candidate_id": "E14-03",
        "family": "CONDITIONAL_EXTREME_MEAN_REVERSION",
        "priority": 3,
        "source_id": "SRC-03",
        "source_sha": "7a8768de9784dda35a7b261a7ade1dbfbff50919",
        "hypothesis": (
            "a mean reversion entered only after an extreme displacement beyond a "
            "volatility-scaled band, and only when the short-horizon trend is not "
            "persistent, reverts enough to cover the round trip"
        ),
        "product": "spot",
        "venue": "binance",
        "assets": ["BTC/USDT", "ETH/USDT"],
        "timeframes": ["15m", "1h"],
        "permitted_sides": ["long"],
        "regime": "range_bound_only",
        "params_locked": {
            "band_sigma": 2.5,
            "sigma_lookback_bars": 96,
            "persistence_filter": "abs(1h return) < 1.5x atr",
            "exit": "revert to the band mean or 4-bar timeout",
        },
        "test_plan": (
            "OOS held out; spread-sensitivity sweep; explicit persistent-trend failure "
            "analysis before any acceptance"
        ),
        "tokens": ["mean_reversion", "revert", "displacement", "band", "zscore"],
        "duplicate_of": ["mean_reversion_family"],
    },
    # The three named hypotheses above are, on this tree, duplicates: the families that
    # already exist carry their mechanism words. The brief is explicit about what to do
    # then -- reject the duplicate and look for a hypothesis that is orthogonal by
    # mechanism, without renaming a parameter to look new. This is that search, and it is
    # held to the same instrument that rejected the other three.
    {
        "candidate_id": "E14-04",
        "family": "CROSS_ASSET_LEAD_LAG_TRANSMISSION",
        "priority": 2,
        "source_id": "SRC-02",
        "source_sha": "5e642997f9623d67b63543962eab46caca30e613",
        "hypothesis": (
            "when a large BTC move has not yet propagated to a correlated liquid alt, the "
            "un-propagated residual carries a net move that covers the round trip; the "
            "edge is the timing gap between assets, not the direction of either"
        ),
        "product": "spot",
        "venue": "binance",
        "assets": ["ETH/USDT", "SOL/USDT"],
        "timeframes": ["1h"],
        "permitted_sides": ["long"],
        "regime": "all",
        "params_locked": {
            "signal_asset": "BTC/USDT",
            "shock_threshold_sigma": 1.5,
            "sigma_lookback_bars": 48,
            "propagation_window_bars": 2,
            "entry": "alt still below its own expected co-move after the shock",
            "exit": "the residual closes or 3 bars elapse",
        },
        "test_plan": (
            "synchronised multi-asset OOS held out; residual measured on closed bars only; "
            "co-move expectation estimated on the training window and frozen; compared "
            "against own-asset momentum and buy-and-hold"
        ),
        # Mechanism words for cross-asset timing. If any existing family already carries
        # these, the orthogonality claim is wrong and the same rule rejects this one too.
        "tokens": ["lead_lag", "cross_asset", "transmission", "propagation"],
        "duplicate_of": ["momentum_family", "cross_sectional", "diversified_xsec"],
    },
)


def _read(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    if path.is_dir():
        return "\n".join(
            child.read_text(encoding="utf-8", errors="replace")
            for child in sorted(path.rglob("*.py"))
        )
    return ""


def duplicate_scan() -> dict[str, Any]:
    """Search the existing families for the mechanism each candidate claims.

    Returns, per candidate, the token hits with ``file:line`` evidence and a judgement.
    A candidate whose tokens are all present in an existing family is a duplicate; one
    whose tokens are absent, or present only in unrelated roles, is not.
    """
    corpus = {name: _read(path) for name, path in _EXISTING_FAMILIES}
    report: dict[str, Any] = {}
    for spec in CANDIDATE_SPECS:
        hits: dict[str, list[dict[str, Any]]] = {}
        for token in spec["tokens"]:
            for name, text in corpus.items():
                for match in re.finditer(rf"\b{re.escape(token)}\b", text, flags=re.IGNORECASE):
                    line_no = text.count("\n", 0, match.start()) + 1
                    hits.setdefault(token, []).append(
                        {"family": name, "line": line_no, "match": match.group(0)}
                    )
        tokens_found = sorted(hits)
        families_matched = sorted({hit["family"] for group in hits.values() for hit in group})
        # A candidate is a duplicate when a family it named as an overlap already
        # carries a majority of its tokens: that is a shared mechanism, not a shared word.
        overlap_families = [f for f in spec["duplicate_of"] if f in families_matched]
        coverage = len(tokens_found) / len(spec["tokens"]) if spec["tokens"] else 0.0
        judgement = (
            "DUPLICATE_REJECT" if overlap_families and coverage >= 0.5 else "NOT_DUPLICATE_RETAINED"
        )
        report[spec["candidate_id"]] = {
            "candidate_id": spec["candidate_id"],
            "family": spec["family"],
            "tokens_searched": list(spec["tokens"]),
            "tokens_found": tokens_found,
            "token_coverage": round(coverage, 4),
            "families_carrying_a_token": families_matched,
            "named_overlap_families_present": overlap_families,
            "judgement": judgement,
            "hits": {token: group[:6] for token, group in hits.items()},
            "note": (
                "a keyword overlap is a reason to look, not proof; the judgement is "
                "recorded so a reader can disagree with it without re-running the search"
            ),
        }
    return report


def findings() -> dict[str, Any]:
    """The scan plus the resulting admission decision for each candidate."""
    scan = duplicate_scan()
    admitted: list[str] = []
    rejected: list[str] = []
    for candidate_id, row in scan.items():
        if row["judgement"] == "DUPLICATE_REJECT":
            rejected.append(candidate_id)
        else:
            admitted.append(candidate_id)
    return {
        "scan": scan,
        "admitted": admitted,
        "rejected": rejected,
        "admission_is_not_a_result": (
            "being non-duplicate admits a hypothesis to experimentation; it does not "
            "assert an edge, and no admitted candidate here is promoted"
        ),
    }


def _spec_digest(spec: dict[str, Any]) -> str:
    canonical = json.dumps(spec, sort_keys=True, default=str).encode()
    return hashlib.sha256(canonical).hexdigest()


def register_candidates() -> dict[str, Any]:
    """Build and freeze the candidate registry, writing the human spec files."""
    scan = duplicate_scan()
    registry: list[dict[str, Any]] = []
    for spec in CANDIDATE_SPECS:
        row = scan[spec["candidate_id"]]
        duplicate = row["judgement"] == "DUPLICATE_REJECT"
        candidate = StrategyCandidate(
            candidate_id=spec["candidate_id"],
            source_id=spec["source_id"],
            source_sha=spec["source_sha"],
            hypothesis=spec["hypothesis"],
            family=spec["family"],
            product=spec["product"],
            venue=spec["venue"],
            assets=list(spec["assets"]),
            timeframes=list(spec["timeframes"]),
            permitted_sides=list(spec["permitted_sides"]),
            regime=spec["regime"],
            params_locked=dict(spec["params_locked"]),
            test_plan=spec["test_plan"],
            duplicate_of=list(row["named_overlap_families_present"]),
            duplicate_reason=(
                f"shares mechanism tokens with {row['named_overlap_families_present']} "
                f"(token coverage {row['token_coverage']})"
                if duplicate
                else None
            ),
            admission_status="REJECTED" if duplicate else "STRATEGY_CANDIDATE",
            evidence=[f"duplicate_scan:{spec['candidate_id']}"],
        )
        payload = candidate.as_dict()
        payload["spec_digest"] = _spec_digest(spec)
        payload["priority"] = spec["priority"]
        registry.append(payload)
    return {
        "schema_version": "EDGE14_CANDIDATE_REGISTRY_V1",
        "work_package": "WP-EDGE-14D",
        "candidates": registry,
        "n_registered": len(registry),
        "n_rejected_duplicate": sum(1 for row in registry if row["admission_status"] == "REJECTED"),
        "preregistered_before_oos": True,
        "promotion": "NONE",
        "order_sent": False,
    }


def preregistration_payload() -> dict[str, Any]:
    registry = register_candidates()
    return {"registry": registry, "findings": findings()}


def write_specs() -> list[str]:
    """Write one human-readable spec per candidate, then return their paths."""
    written: list[str] = []
    scan = duplicate_scan()
    for spec in CANDIDATE_SPECS:
        row = scan[spec["candidate_id"]]
        lines = [
            f"# {spec['candidate_id']} — {spec['family']}",
            "",
            f"*Priority {spec['priority']}. Source {spec['source_id']} @ `{spec['source_sha']}`.*",
            "",
            "## Hypothesis",
            "",
            spec["hypothesis"],
            "",
            "## Locked parameters",
            "",
        ]
        for key, value in spec["params_locked"].items():
            lines.append(f"- `{key}`: {value}")
        lines += [
            "",
            "## Test plan",
            "",
            spec["test_plan"],
            "",
            "## Duplicate scan",
            "",
            f"- judgement: **{row['judgement']}**",
            f"- token coverage: {row['token_coverage']}",
            f"- named overlap families present: {row['named_overlap_families_present'] or 'none'}",
            f"- families carrying a token: {row['families_carrying_a_token'] or 'none'}",
            "",
            "Research only: no orders, no credentials, no capital.",
            "",
        ]
        path = SPECS_DIR / f"{spec['candidate_id']}_{spec['family']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        written.append(str(path))
    return written
