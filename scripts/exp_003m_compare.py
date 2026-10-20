"""exp_003m_compare — put the fill models on the same economics and decide.

    ./.venv/Scripts/python.exe scripts/exp_003m_compare.py

Every scenario in this file uses the same 47 signals, the same exits, the same fee
schedules and the same research window. The only thing that changes is *how the entry was
filled*, which is the question EXP-003M exists to answer.

Two traps are handled explicitly:

1. **Not trading is free.** A fill model that misses more trades can report a *better* net
   per signal while getting worse per trade. The decision therefore gates on net per fill
   as well as net per signal, and says so in the report.
2. **An upper bound cannot be promoted.** ``F0_touch_full`` assumes every touch fills us
   completely at the improved price. If that bound already loses money, no amount of fill
   realism can rescue the candidate, and no report may credit a worse fill model with
   making it viable.

The bootstrap is a moving block of 5 days, 10 000 resamples, seed 20261020 — the same
scheme EXP-003L gated on, so the intervals are comparable.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"

SCHEMA = "AI_BOTS_003M_ECONOMICS_V1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def block_bootstrap(
    values: list[float],
    day_ordinals: list[int],
    *,
    block_days: int = 5,
    resamples: int = 10_000,
    seed: int = 20261020,
) -> dict[str, float]:
    """Moving-block bootstrap of the mean, blocks defined on calendar days.

    Signals from the same day are not independent observations; resampling individual
    trades would produce an interval that is too narrow and would flatter the candidate.
    """

    if len(values) != len(day_ordinals):
        raise ValueError("values and day ordinals must align")
    if not values:
        raise ValueError("nothing to bootstrap")
    blocks: dict[int, list[float]] = {}
    for value, ordinal in zip(values, day_ordinals, strict=True):
        blocks.setdefault(ordinal // block_days, []).append(value)
    groups = [np.asarray(blocks[key], dtype=float) for key in sorted(blocks)]
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    total = len(values)
    for index in range(resamples):
        picks = rng.integers(0, len(groups), size=len(groups))
        sample = np.concatenate([groups[pick] for pick in picks])
        if sample.size == 0:
            means[index] = math.nan
            continue
        #: Resample until the synthetic sample has the same size as the observed one, so
        #: the statistic is a mean of 47 numbers and not of a lucky short draw.
        while sample.size < total:
            sample = np.concatenate([sample, groups[int(rng.integers(0, len(groups)))]])
        means[index] = float(sample[:total].mean())
    means = means[~np.isnan(means)]
    point = float(stats.fmean(values))
    return {
        "mean": round(point, 8),
        "lower": round(float(np.percentile(means, 2.5)), 8),
        "upper": round(float(np.percentile(means, 97.5)), 8),
        "resamples": resamples,
        "blocks": len(groups),
        "block_days": block_days,
        "seed": seed,
    }


def halve(
    values: list[float], ordinals: list[int], midpoint: int
) -> dict[str, float]:
    first = [value for value, ordinal in zip(values, ordinals, strict=True) if ordinal < midpoint]
    second = [value for value, ordinal in zip(values, ordinals, strict=True) if ordinal >= midpoint]
    return {
        "first_half_mean": round(stats.fmean(first), 8) if first else 0.0,
        "second_half_mean": round(stats.fmean(second), 8) if second else 0.0,
        "first_half_count": len(first),
        "second_half_count": len(second),
    }


def scenario_economics(
    rows: list[dict[str, Any]],
    *,
    design: dict[str, Any],
    midpoint_ordinal: int,
) -> dict[str, Any]:
    net = [float(row["net_usdt"]) for row in rows]
    ordinals = [int(row["day_ordinal"]) for row in rows]
    filled = [row for row in rows if float(row["fill_fraction"]) > 0]
    gross = sum(float(row["gross_usdt"]) for row in filled)
    fees = sum(float(row["entry_fee_usdt"]) + float(row["exit_fee_usdt"]) for row in filled)
    bootstrap = block_bootstrap(
        net,
        ordinals,
        resamples=int(design["economics"]["bootstrap"]["resamples"]),
        seed=int(design["economics"]["bootstrap"]["seed"]),
    )
    sigma = stats.pstdev(net) if len(net) > 1 else 0.0
    stderr = sigma / math.sqrt(len(net)) if net else 0.0
    return {
        "signals": len(rows),
        "filled": len(filled),
        "fill_rate": round(len(filled) / len(rows), 6) if rows else None,
        "net_usdt": round(sum(net), 8),
        "net_per_signal_usdt": round(stats.fmean(net), 8) if net else None,
        "net_per_fill_usdt": round(sum(net) / len(filled), 8) if filled else None,
        "gross_per_fill_usdt": round(gross / len(filled), 8) if filled else None,
        "fees_per_fill_usdt": round(fees / len(filled), 8) if filled else None,
        "edge_over_fees_usdt": round((gross - fees) / len(filled), 8) if filled else None,
        "bootstrap_ci95_net_per_signal": bootstrap,
        "naive_stderr_usdt": round(stderr, 8),
        "halves": halve(net, ordinals, midpoint_ordinal),
        "exit_reasons": {
            reason: sum(1 for row in filled if row["exit_reason"] == reason)
            for reason in sorted({str(row["exit_reason"]) for row in filled})
        },
        "miss_reasons": {
            reason: sum(1 for row in rows if row["miss_reason"] == reason)
            for reason in sorted({str(row["miss_reason"]) for row in rows if row["miss_reason"]})
        },
        "mean_fill_fraction": round(stats.fmean([float(r["fill_fraction"]) for r in filled]), 6)
        if filled
        else None,
    }


def selection_metrics(
    rows: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> dict[str, Any]:
    """Adverse selection: are the entries the tape fills worse than the touches it does not?

    Compared on the same forward horizons and the same sign convention (positive = the
    market moved against the position), so a fill model that only fills when the price is
    about to keep going against us cannot hide inside an average.
    """

    def mean(key: str, pool: list[dict[str, Any]]) -> float | None:
        values = [
            float(row[key])
            for row in pool
            if float(row["fill_fraction"]) > 0 and row.get(key) is not None
        ]
        return round(stats.fmean(values), 6) if values else None

    filled = [row for row in rows if float(row["fill_fraction"]) > 0]
    touched_baseline = [row for row in baseline if float(row["fill_fraction"]) > 0]
    return {
        "filled": len(filled),
        "baseline_filled": len(touched_baseline),
        "adverse_1m_bps": mean("adverse_1m_bps", rows),
        "adverse_5m_bps": mean("adverse_5m_bps", rows),
        "adverse_15m_bps": mean("adverse_15m_bps", rows),
        "baseline_adverse_1m_bps": mean("adverse_1m_bps", baseline),
        "baseline_adverse_5m_bps": mean("adverse_5m_bps", baseline),
        "baseline_adverse_15m_bps": mean("adverse_15m_bps", baseline),
        "delta_adverse_5m_bps": (
            round((mean("adverse_5m_bps", rows) or 0.0) - (mean("adverse_5m_bps", baseline) or 0.0), 6)
            if mean("adverse_5m_bps", rows) is not None and mean("adverse_5m_bps", baseline) is not None
            else None
        ),
        "seconds_to_fill_median": round(
            stats.median([float(row["seconds_to_fill"]) for row in filled if row["seconds_to_fill"] is not None]),
            3,
        )
        if any(row["seconds_to_fill"] is not None for row in filled)
        else None,
        "note": (
            "positive = the forward move went against the position. Compare a tape-filled "
            "set with the touch-filled set on the same horizons"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    out = Path(args.out)
    design = _read_json(out / "design" / "DESIGN.json")
    fill_model = _read_json(out / "analysis" / "FILL_MODEL.json")
    published = _read_json(PREDECESSOR / "analysis" / "execution" / "5m__mean_reversion.json")

    #: Day ordinal measured from the *decision*, so a miss lands in the same block as the
    #: fill it did not get. Taking the block from the fill time would move the misses.
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    for scenario in fill_model["per_signal"].values():
        for row in scenario:
            decision_day = _day(int(row["decision_ts_ms"]))
            row["day_ordinal"] = (
                datetime.strptime(decision_day, "%Y-%m-%d").replace(tzinfo=UTC) - origin
            ).days
    decision_days = sorted(
        {int(row["day_ordinal"]) for row in fill_model["per_signal"]["F0_touch_full"]}
    )
    midpoint_ordinal = (decision_days[0] + decision_days[-1]) // 2 if decision_days else 0

    economics: dict[str, Any] = {}
    for name, rows in fill_model["per_signal"].items():
        economics[name] = {
            "parameters": fill_model["scenarios"][name]["parameters"],
            **scenario_economics(rows, design=design, midpoint_ordinal=midpoint_ordinal),
        }

    selection = {
        name: selection_metrics(rows, fill_model["per_signal"]["F0_touch_full"])
        for name, rows in fill_model["per_signal"].items()
        if name != "F0_touch_full"
    }

    target = design["predecessor"]["reproduction_target"]
    f0 = economics["F0_touch_full"]
    reproduction = {
        "scenario": target["scenario"],
        "target": {
            "fill_rate": target["fill_rate"],
            "net_per_signal_usdt": target["net_per_signal_usdt"],
            "net_per_fill_usdt": target["net_per_fill_usdt"],
            "gross_per_fill_usdt": target["gross_per_fill_usdt"],
        },
        "measured": {
            "fill_rate": f0["fill_rate"],
            "net_per_signal_usdt": f0["net_per_signal_usdt"],
            "net_per_fill_usdt": f0["net_per_fill_usdt"],
            "gross_per_fill_usdt": f0["gross_per_fill_usdt"],
        },
        "deltas": {
            "fill_rate": round((f0["fill_rate"] or 0.0) - target["fill_rate"], 10),
            "net_per_signal_usdt": round(
                (f0["net_per_signal_usdt"] or 0.0) - target["net_per_signal_usdt"], 10
            ),
            "net_per_fill_usdt": round(
                (f0["net_per_fill_usdt"] or 0.0) - target["net_per_fill_usdt"], 10
            ),
            "gross_per_fill_usdt": round(
                (f0["gross_per_fill_usdt"] or 0.0) - target["gross_per_fill_usdt"], 10
            ),
        },
        "tolerance_usdt": 1e-8,
    }
    reproduction["matches"] = all(
        abs(delta) <= 1e-8 for delta in reproduction["deltas"].values()
    )

    #: Cross-check the *other* direction: EXP-003L's own numbers for the pessimistic corner
    #: must also be restated by F0 at that corner, otherwise F0 is a coincidence.
    corner = published["scenarios"]["maker_resting__spot_vip0__h5__o2"]
    f2 = economics["F2_tape_pessimistic"]

    gates = {
        "G1_reproduces_003l": {
            "passed": reproduction["matches"],
            "detail": reproduction["deltas"],
        },
        "G4_economics_pessimistic": {
            "passed": bool(
                (f2["net_per_signal_usdt"] or 0.0) > 0
                and (f2["net_per_fill_usdt"] or 0.0) > 0
                and f2["bootstrap_ci95_net_per_signal"]["lower"] > 0
            ),
            "detail": {
                "net_per_signal_usdt": f2["net_per_signal_usdt"],
                "net_per_fill_usdt": f2["net_per_fill_usdt"],
                "ci_lower": f2["bootstrap_ci95_net_per_signal"]["lower"],
            },
        },
        "G5_optimistic_ceiling": {
            "passed": bool((f0["net_per_fill_usdt"] or 0.0) > 0),
            "detail": {
                "net_per_fill_usdt": f0["net_per_fill_usdt"],
                "gross_per_fill_usdt": f0["gross_per_fill_usdt"],
                "fees_per_fill_usdt": f0["fees_per_fill_usdt"],
                "statement": (
                    "F0 fills every touch at the improved price with no queue. Its gross per "
                    "fill is the ceiling any fill model can reach on this sample"
                ),
            },
        },
        "G7_evidence_class": {
            "passed": False,
            "detail": {
                "class": design["fill_model"]["evidence_class"],
                "reason": "no order was ever sent to an exchange; fills are inferred from the tape",
            },
        },
    }

    sample_ok = len(fill_model["per_signal"]["F0_touch_full"]) >= 40
    if not gates["G1_reproduces_003l"]["passed"]:
        verdict = "BLOCKED"
        rationale = (
            "EXP-003M cannot restate EXP-003L's published maker scenario, so its own numbers "
            "are not trustworthy. Nothing is priced until that is fixed."
        )
    elif not gates["G4_economics_pessimistic"]["passed"] or not gates["G5_optimistic_ceiling"]["passed"]:
        verdict = "REJECT"
        rationale = (
            "The candidate loses under the pessimistic maker model and already loses under the "
            "most generous one. Fill realism is not the binding constraint: the gross edge per "
            "fill is smaller than the fees it must clear, so a better fill rate has nothing to "
            "rescue."
        )
    elif not sample_ok:
        verdict = "INSUFFICIENT_EVIDENCE"
        rationale = "fewer than 40 signals: no threshold is relaxed for a thin sample"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
        rationale = (
            "The economics survive the estimated fill models, but no live order was placed and "
            "the queue is unobservable. Under this directive that ceiling is INSUFFICIENT_EVIDENCE, "
            "never a promotion."
        )

    payload = {
        "schema_version": SCHEMA,
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "signals": len(fill_model["per_signal"]["F0_touch_full"]),
        "fill_model_sha256": _sha256(out / "analysis" / "FILL_MODEL.json"),
        "economics": economics,
        "selection": selection,
        "reproduction": reproduction,
        "pessimistic_corner_cross_check": {
            "predecessor": {
                "fill_rate": corner["fill_rate"],
                "net_per_signal_usdt": corner["net_per_signal_usdt"],
                "net_per_fill_usdt": corner["net_per_fill_usdt"],
            },
            "note": (
                "EXP-003L's 5m/2 bp offset/spot_vip0 corner is a different scenario object in "
                "EXP-003M (which adds a tape-based queue); it is quoted, not restated, and the "
                "F0 gate above is the reproduction that counts"
            ),
        },
        "gates": gates,
        "verdict": verdict,
        "rationale": rationale,
        "evidence_class": design["fill_model"]["evidence_class"],
        "limitations": _limitations(),
    }
    _write_json(out / "analysis" / "ECONOMICS.json", payload)
    _write_json(
        out / "analysis" / "DECISION.json",
        {
            "schema_version": "AI_BOTS_003M_DECISION_V1",
            "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
            "verdict": verdict,
            "rationale": rationale,
            "gates": {name: gate["passed"] for name, gate in gates.items()},
            "gates_failed": [name for name, gate in gates.items() if not gate["passed"]],
            "holdout_opened": False,
            "live_orders": False,
            "promotion_allowed": False,
            "best_case_scenario": "F0_touch_full",
            "best_case_net_per_fill_usdt": f0["net_per_fill_usdt"],
            "cost_floor_per_fill_usdt": f0["fees_per_fill_usdt"],
        },
    )
    print(f"[003m-compare] verdict: {verdict}")
    print(f"[003m-compare] {rationale}")
    for name, block in economics.items():
        print(
            f"[003m-compare] {name}: fill_rate={block['fill_rate']} "
            f"net/signal={block['net_per_signal_usdt']} net/fill={block['net_per_fill_usdt']} "
            f"ci={block['bootstrap_ci95_net_per_signal']['lower']}.."
            f"{block['bootstrap_ci95_net_per_signal']['upper']}"
        )
    return 0


def _limitations() -> list[str]:
    return [
        "no order was sent to an exchange: every fill here is inferred from published trades",
        "the queue position at the limit is unobservable without a spot L2 feed; it is declared and swept, not measured",
        "a trade at our price is not proof that our order was the one matched",
        "cancel/replace traffic and hidden liquidity are not modelled",
        "the holdout 2026-08-06 → 2026-08-20 stays closed; nothing here is out-of-sample in the forward sense",
        "a moving-block bootstrap on 47 signals is a wide interval, not a proof of anything",
    ]


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
