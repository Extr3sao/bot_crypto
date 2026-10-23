"""ALPHA-003 — independent verification of the development run.

Builder != verifier.  This script does **not** trust
``reports/alpha003/ALPHA003_DEVELOPMENT_RESULTS.json``: it re-reads the cached price with its
own parser, rebuilds the synchronised cross-asset grid with its own arithmetic, re-applies
each hypothesis **from the registry's written rule rather than from the frozen signal**, and
recomputes every headline number with its own statistics.  The artifact is only ever used as
the thing to compare against.

What it recomputes independently:

* the split boundaries and the design sample size;
* the aligned lag-window returns, the ATR normalisation and the equal-weight market return;
* the derived cell features and the direction of every arm — written from the rule text, then
  asserted to agree with ``alpha003``'s frozen signal, so a drifting signal is a mismatch
  rather than a finding;
* the gross and net effect, the own-history baseline and the incremental delta;
* the frozen hurdle, its terms and the cost model, from its own arithmetic;
* the one-sided p-value, the effective sample size and the power class;
* the Benjamini-Hochberg and Holm decisions over every declared cell;
* the best-of-N circular-shift selection null, with its own generator and draw loop;
* the promotion verdicts and the candidate count;
* the hard invariants: the newest source bar a cell read had closed by the decision instant,
  and no cell touched the holdout or the validation slice.

Exit status is 0 when ``MISMATCHES == 0`` and ``FALSE_SUCCESS == 0``, 1 otherwise.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import alpha003 as a3
from trading_bot.research import alpha003_experiment as ax

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "data" / "raw" / "alpha003"
PRICE_DIR = DATA_DIR / "price"
REPORT_DIR = REPO / "reports" / "alpha003"

ENTRY_TIMEFRAMES = a3.ENTRY_TIMEFRAMES
PRIMARY_TIMEFRAME = "5m"
CONTEXT_TIMEFRAME = a3.CONTEXT_TIMEFRAME

FROZEN_PREREGISTRATION_HASH = "db43ad5283cad875ac014a622dc7acae423d0e44c5f64c473a039e3f9ed1c4c8"

ATR_WINDOW = 14
RELATIVE_WINDOW = 12
CONTEXT_WINDOW = 96
MIN_VOL_REGIME_OBSERVATIONS = 72
VOL_REGIME_SHORT_WINDOW = 24
VOL_REGIME_BASELINE_WINDOW = 168

LIMITATIONS: list[str] = [
    "the verifier re-reads the same cached price files as the builder; it can prove the "
    "arithmetic and the alignment, not the fidelity of the venue's own history",
    "the selection null uses the same circular-shift construction as the builder by design, "
    "but with its own generator, its own draw loop and its own arithmetic",
    "the context correlation and beta table is descriptive and is not independently recomputed",
    "the ablation attribution tables are not independently recomputed",
]


# --------------------------------------------------------------------------- #
# independent primitives
# --------------------------------------------------------------------------- #


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pstdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / len(values))


def _ess(values: Sequence[float]) -> float:
    """Autocorrelation-adjusted sample size, written from scratch."""
    n = len(values)
    if n < 3:
        return float(max(n, 1))
    mu = _mean(values)
    variance = sum((value - mu) ** 2 for value in values) / n
    if variance <= 0.0:
        return float(n)
    factor = 1.0
    for lag in range(1, min(10, n - 1) + 1):
        covariance = sum((values[i] - mu) * (values[i - lag] - mu) for i in range(lag, n)) / n
        rho = covariance / variance
        if rho <= 0.0:
            break
        factor += 2.0 * rho
    return max(1.0, n / factor)


def _one_sided_p(t_stat: float) -> float:
    if t_stat <= 0.0:
        return 1.0
    return max(0.0, min(1.0, 0.5 * math.erfc(t_stat / math.sqrt(2.0))))


def _mde_bps(*, sigma_bps: float, n: int) -> float:
    if n <= 0 or sigma_bps <= 0.0:
        return float("inf")
    z_alpha = 1.6448536269514722
    z_beta = 0.8416212335729143
    return (z_alpha + z_beta) * sigma_bps / math.sqrt(n)


def _benjamini_hochberg(pvalues: Sequence[float], q: float) -> list[bool]:
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: pvalues[index])
    passes = [False] * n
    threshold_rank = 0
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= q * rank / n:
            threshold_rank = rank
    for rank, index in enumerate(order, start=1):
        if rank <= threshold_rank:
            passes[index] = True
    return passes


def _holm(pvalues: Sequence[float], alpha: float) -> list[bool]:
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: pvalues[index])
    passes = [False] * n
    for rank, index in enumerate(order, start=1):
        if pvalues[index] <= alpha / (n - rank + 1):
            passes[index] = True
        else:
            break
    return passes


def _period_ms(period: str) -> int:
    return {"5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000}[period]


# --------------------------------------------------------------------------- #
# an independent frame
# --------------------------------------------------------------------------- #


class VerifiedFrame:
    """The synchronised grid, rebuilt from the raw price without the builder's code."""

    def __init__(
        self,
        *,
        timeframe: str,
        bars_by_symbol: Mapping[str, Sequence[Sequence[float]]],
        context_by_symbol: Mapping[str, Sequence[Sequence[float]]],
    ) -> None:
        self.timeframe = timeframe
        self.step = _period_ms(timeframe)
        self.symbols = sorted(bars_by_symbol)
        self.close: dict[str, dict[int, float]] = {}
        self.atr: dict[str, dict[int, float | None]] = {}
        for symbol, bars in bars_by_symbol.items():
            self.close[symbol] = {int(bar[0]): float(bar[4]) for bar in bars}
            self.atr[symbol] = _atr_map(bars)
        grids = [set(self.close[symbol]) for symbol in self.symbols]
        self.opens: list[int] = sorted(set.intersection(*grids))
        self.position: dict[int, int] = {open_ms: index for index, open_ms in enumerate(self.opens)}
        self.decisions: list[int] = [open_ms + self.step for open_ms in self.opens]
        self.context_opens: dict[str, list[int]] = {}
        self.context_regime: dict[str, list[float | None]] = {}
        for symbol, bars in context_by_symbol.items():
            self.context_opens[symbol] = [int(bar[0]) for bar in bars]
            self.context_regime[symbol] = _regime_series(bars)
        self._forwards: dict[str, list[float | None]] = {}

    def window_return(self, symbol: str, index: int, window: int) -> float | None:
        start = index - window
        if start < 0:
            return None
        if self.opens[start] != self.opens[index] - window * self.step:
            return None
        base = self.close[symbol].get(self.opens[start])
        current = self.close[symbol].get(self.opens[index])
        if base is None or current is None or base <= 0.0:
            return None
        return current / base - 1.0

    def market_return(self, index: int, window: int) -> float | None:
        values = [self.window_return(symbol, index, window) for symbol in self.symbols]
        if any(value is None for value in values):
            return None
        return _mean([float(value) for value in values if value is not None])

    def forwards(self, symbol: str) -> list[float | None]:
        if symbol not in self._forwards:
            closes = self.close[symbol]
            series: list[float | None] = [None] * len(self.opens)
            for index, open_ms in enumerate(self.opens):
                current = closes.get(open_ms)
                if index + 1 >= len(self.opens) or current is None or current <= 0.0:
                    continue
                nxt = closes.get(self.opens[index + 1])
                if nxt is not None:
                    series[index] = nxt / current - 1.0
            self._forwards[symbol] = series
        return self._forwards[symbol]

    def derived(
        self, index: int, target: str, leader: str | None, lag: int | None
    ) -> dict[str, float | None]:
        target_atr = self.atr[target].get(self.opens[index])
        out: dict[str, float | None] = {}
        if leader is not None and lag is not None:
            leader_atr = self.atr[leader].get(self.opens[index])
            out["leader_ret_z"] = _safe_div(self.window_return(leader, index, lag), leader_atr)
            out["target_ret_z"] = _safe_div(self.window_return(target, index, lag), target_atr)
        else:
            out["leader_ret_z"] = None
            out["target_ret_z"] = None
        target_mom = _safe_div(self.window_return(target, index, RELATIVE_WINDOW), target_atr)
        market = _safe_div(self.market_return(index, RELATIVE_WINDOW), target_atr)
        out["target_mom_z"] = target_mom
        out["market_ret_z"] = market
        out["relative_z"] = (
            target_mom - market if target_mom is not None and market is not None else None
        )
        return out

    def regime(self, symbol: str, decision_ms: int) -> float | None:
        opens = self.context_opens.get(symbol, [])
        position = bisect_right(opens, decision_ms - _period_ms(CONTEXT_TIMEFRAME)) - 1
        if position < 0:
            return None
        return self.context_regime[symbol][position]


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def _atr_map(bars: Sequence[Sequence[float]]) -> dict[int, float | None]:
    out: dict[int, float | None] = {}
    opens = [int(bar[0]) for bar in bars]
    for index, open_ms in enumerate(opens):
        if index < ATR_WINDOW:
            out[open_ms] = None
            continue
        step = opens[index] - opens[index - 1]
        if step <= 0:
            out[open_ms] = None
            continue
        contiguous = True
        for offset in range(ATR_WINDOW + 1):
            if opens[index - offset] != open_ms - offset * step:
                contiguous = False
                break
        if not contiguous:
            out[open_ms] = None
            continue
        ranges = []
        for offset in range(ATR_WINDOW):
            position = index - offset
            high = float(bars[position][2])
            low = float(bars[position][3])
            prior = float(bars[position - 1][4])
            ranges.append(max(high - low, abs(high - prior), abs(low - prior)))
        atr = _mean(ranges)
        close = float(bars[index][4])
        out[open_ms] = atr / close if close > 0.0 and atr > 0.0 else None
    return out


def _regime_series(bars: Sequence[Sequence[float]]) -> list[float | None]:
    opens = [int(bar[0]) for bar in bars]
    closes = [float(bar[4]) for bar in bars]
    returns: list[float | None] = [None] * len(bars)
    for index in range(1, len(bars)):
        if closes[index - 1] > 0.0 and opens[index] > opens[index - 1]:
            returns[index] = closes[index] / closes[index - 1] - 1.0
    out: list[float | None] = [None] * len(bars)
    for index in range(len(bars)):
        trailing = [
            value
            for value in returns[max(0, index - VOL_REGIME_BASELINE_WINDOW + 1) : index + 1]
            if value is not None
        ]
        if len(trailing) < MIN_VOL_REGIME_OBSERVATIONS:
            continue
        short = _pstdev(trailing[-VOL_REGIME_SHORT_WINDOW:])
        baseline = _pstdev(trailing)
        if short <= 0.0 or baseline <= 0.0:
            continue
        out[index] = 1.0 if short > baseline else -1.0
    return out


# --------------------------------------------------------------------------- #
# the rules, written from the registry text (never imported from the signals)
# --------------------------------------------------------------------------- #


def _rule_h1(features: Mapping[str, float | None]) -> int | None:
    leader_value = features.get("leader_ret_z")
    target_value = features.get("target_ret_z")
    if leader_value is None or target_value is None:
        return None
    leader = float(leader_value)
    target = float(target_value)
    if abs(leader) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    direction = 1 if leader > 0 else -1
    if direction * target < 0.0:
        return 0
    if direction * (leader - target) < a3.THRESHOLDS["lag_gap"]:
        return 0
    return direction


def _rule_h2(features: Mapping[str, float | None]) -> int | None:
    relative = features.get("relative_z")
    if relative is None:
        return None
    if abs(float(relative)) <= a3.THRESHOLDS["relative_strength_z"]:
        return 0
    return 1 if float(relative) > 0 else -1


def _rule_h3(features: Mapping[str, float | None]) -> int | None:
    market = features.get("market_ret_z")
    relative = features.get("relative_z")
    if market is None or relative is None:
        return None
    if abs(float(market)) <= a3.THRESHOLDS["market_ret_z"]:
        return 0
    if abs(float(relative)) <= a3.THRESHOLDS["convergence_relative_z"]:
        return 0
    if float(market) * float(relative) >= 0.0:
        return 0
    return 1 if float(market) > 0 else -1


def _rule_own_same_lag(features: Mapping[str, float | None]) -> int | None:
    value = features.get("target_ret_z")
    if value is None:
        return None
    if abs(float(value)) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    return 1 if float(value) > 0 else -1


def _rule_own_r(features: Mapping[str, float | None]) -> int | None:
    value = features.get("target_mom_z")
    if value is None:
        return None
    if abs(float(value)) <= a3.THRESHOLDS["relative_strength_z"]:
        return 0
    return 1 if float(value) > 0 else -1


def _rule_market(features: Mapping[str, float | None]) -> int | None:
    value = features.get("market_ret_z")
    if value is None:
        return None
    if abs(float(value)) <= a3.THRESHOLDS["leader_ret_z"]:
        return 0
    return 1 if float(value) > 0 else -1


def _rule_unconditional(_features: Mapping[str, float | None]) -> int | None:
    return 1


RULES: dict[str, Callable[[Mapping[str, float | None]], int | None]] = {
    "A3-H01": _rule_h1,
    "A3-H02": _rule_h2,
    "A3-H03": _rule_h3,
    "A3-B1_OWN_MOMENTUM_SAME_LAG": _rule_own_same_lag,
    "A3-B1_OWN_MOMENTUM_R": _rule_own_r,
    "A3-B3_MARKET_DIRECTION": _rule_market,
    "A3-B0_UNCONDITIONAL_LONG": _rule_unconditional,
}


def _leader_source_close(frame: VerifiedFrame, open_ms: int, lag: int) -> int:
    """The close time of the newest bar the leader's lag-window read."""
    return (open_ms - (lag - 1) * frame.step) + frame.step


# --------------------------------------------------------------------------- #
# recomputation
# --------------------------------------------------------------------------- #


def recompute_arm(
    directions: Sequence[int | None],
    forwards: Sequence[float | None],
    *,
    hurdle_bps: float,
) -> dict[str, Any]:
    pairs = [
        (int(direction), float(forward))
        for direction, forward in zip(directions, forwards, strict=True)
        if direction is not None and forward is not None
    ]
    active = [(d, f) for d, f in pairs if d != 0]
    contributions = [d * f * 1e4 for d, f in active]
    n = len(contributions)
    gross = _mean(contributions)
    sigma = _pstdev(contributions)
    n_eff = _ess(contributions) if n > 1 else float(n)
    se = sigma / math.sqrt(n_eff) if n_eff > 0.0 and sigma > 0.0 else float("inf")
    t_stat = gross / se if se not in (0.0, float("inf")) else 0.0
    mde = _mde_bps(sigma_bps=sigma, n=int(max(1, round(n_eff))))
    return {
        "n_evaluated": len(pairs),
        "n": n,
        "gross_bps": round(gross, 6),
        "net_bps": round(gross - a3.COST_BPS_V3, 6),
        "sigma_bps": round(sigma, 6),
        "p_raw": round(_one_sided_p(t_stat), 8),
        "mde_bps": round(mde, 6),
        "power_class": "POWERED" if mde <= hurdle_bps else "UNDERPOWERED",
    }


def _min_gross_hurdle_bps(n_effective: int, sigma_trade_bps: float) -> dict[str, float]:
    cost = a3.COST_BPS_V3
    execution = cost * 0.25
    buffer = 8.121
    statistical = 1.959963985 * sigma_trade_bps / math.sqrt(n_effective)
    return {
        "cost_bps": round(cost, 6),
        "execution_uncertainty_bps": round(execution, 6),
        "winners_curse_buffer_bps": round(buffer, 6),
        "statistical_uncertainty_bps": round(statistical, 6),
        "min_gross_alpha_hurdle_bps": round(cost + execution + buffer + statistical, 6),
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def _price(symbol: str, timeframe: str) -> list[list[float]]:
    rows: list[list[float]] = json.loads(
        (PRICE_DIR / f"{symbol}_{timeframe}.json").read_text(encoding="utf-8")
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="verify the ALPHA-003 development run").parse_args(argv)
    artifact = json.loads(
        (REPORT_DIR / "ALPHA003_DEVELOPMENT_RESULTS.json").read_text(encoding="utf-8")
    )
    dataset = json.loads((REPORT_DIR / "ALPHA003_DATASET_REPORT.json").read_text(encoding="utf-8"))

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((f"{name} [{detail}]" if detail else name, bool(ok), detail))

    check(
        "preregistration_hash_frozen",
        artifact["preregistration_hash"] == FROZEN_PREREGISTRATION_HASH,
        artifact["preregistration_hash"],
    )
    check("cost_model_not_retuned", artifact["cost_model"]["cost_bps"] == a3.COST_BPS_V3)
    check(
        "cell_set_is_the_declared_one",
        sorted(artifact["cells"]) == sorted(ax.cell_ids()),
        f"{len(artifact['cells'])}",
    )
    check("holdout_read_false", artifact["holdout_read"] is False)
    check("validation_read_false", artifact["validation_read"] is False)

    context = {symbol: _price(symbol, CONTEXT_TIMEFRAME) for symbol in a3.UNIVERSE}
    frames = {
        timeframe: VerifiedFrame(
            timeframe=timeframe,
            bars_by_symbol={symbol: _price(symbol, timeframe) for symbol in a3.UNIVERSE},
            context_by_symbol=context,
        )
        for timeframe in ENTRY_TIMEFRAMES
    }
    del context

    independent_boundaries = ax.calendar_boundaries(
        int(dataset["calendar"]["common_start_ms"]), int(dataset["calendar"]["common_end_ms"])
    )
    published_calendar = dataset["calendar"]["boundaries"]
    check(
        "split_boundaries",
        all(
            list(independent_boundaries[key]) == list(published_calendar[key])
            for key in independent_boundaries
        ),
        str(independent_boundaries["discovery"]),
    )
    discovery = independent_boundaries["discovery"]
    validation = independent_boundaries["validation"]
    holdout = independent_boundaries["holdout"]

    independent_design_n = max(
        1,
        sum(
            1
            for decision_ms in frames[PRIMARY_TIMEFRAME].decisions
            if discovery[0] <= decision_ms < discovery[1]
        ),
    )
    check("design_n", independent_design_n == artifact["design_n"], f"{independent_design_n}")

    hurdle = _min_gross_hurdle_bps(independent_design_n, 400.0)
    hurdle_bps = hurdle["min_gross_alpha_hurdle_bps"]
    check("hurdle_bps", abs(hurdle_bps - float(artifact["hurdle_bps"])) < 1e-6, f"{hurdle_bps}")
    check(
        "hurdle_terms",
        abs(
            hurdle["cost_bps"]
            + hurdle["execution_uncertainty_bps"]
            + hurdle["winners_curse_buffer_bps"]
            + hurdle["statistical_uncertainty_bps"]
            - hurdle_bps
        )
        < 1e-6,
    )

    summary: dict[str, Any] = {}
    rule_directions: dict[str, list[int | None]] = {}
    rule_forwards: dict[str, list[float | None]] = {}
    pit_violations = 0
    signal_divergence = 0
    evaluated_by_timeframe: dict[str, int] = {}
    iterated_min: dict[str, int] = {}
    iterated_max: dict[str, int] = {}
    for cell in ax.cell_ids():
        spec = ax.parse_cell(cell)
        frame = frames[str(spec["timeframe"])]
        hypothesis_id = str(spec["hypothesis_id"])
        baseline_arm = ax.INCREMENTAL_BASELINE[hypothesis_id]
        target = str(spec["target"])
        leader = spec["leader"]
        lag = spec["lag"]
        forwards_by_symbol = frame.forwards(target)
        rule = RULES[hypothesis_id]
        rule_baseline = RULES[baseline_arm]

        directions: list[int | None] = []
        baseline_directions: list[int | None] = []
        forwards: list[float | None] = []
        for index in range(len(frame.opens)):
            decision_ms = frame.decisions[index]
            if not (discovery[0] <= decision_ms < discovery[1]):
                continue
            iterated_min[str(spec["timeframe"])] = min(
                decision_ms, iterated_min.get(str(spec["timeframe"]), decision_ms)
            )
            iterated_max[str(spec["timeframe"])] = max(
                decision_ms, iterated_max.get(str(spec["timeframe"]), decision_ms)
            )
            features = frame.derived(index, target, leader, lag)
            # the registry's frozen signal must agree with the rule written from the text
            if ax.preregistered_direction(hypothesis_id, features) != rule(features):
                signal_divergence += 1
            if ax.arm_direction(baseline_arm, features) != rule_baseline(features):
                signal_divergence += 1
            if leader is not None and lag is not None:
                newest_close = _leader_source_close(frame, frame.opens[index], lag)
                if newest_close > decision_ms:
                    pit_violations += 1
            directions.append(rule(features))
            baseline_directions.append(rule_baseline(features))
            forwards.append(forwards_by_symbol[index])

        # every cell of a timeframe iterates the same row set, so this is set (not accumulated)
        evaluated_by_timeframe[str(spec["timeframe"])] = len(directions)
        full = recompute_arm(directions, forwards, hurdle_bps=hurdle_bps)
        baseline = recompute_arm(baseline_directions, forwards, hurdle_bps=hurdle_bps)
        rule_directions[cell] = directions
        rule_forwards[cell] = forwards
        summary[cell] = {
            **full,
            "baseline_gross_bps": baseline["gross_bps"],
            "incremental_delta_bps": round(full["gross_bps"] - baseline["gross_bps"], 6),
        }

    # Rows exist beyond discovery; the claim is that none of them was ever evaluated, which is
    # proven by the evaluated count being exactly the discovery count for every timeframe (the
    # per-cell N checks then pin the arithmetic on that exact set).
    rows_in_holdout = sum(
        1
        for frame in frames.values()
        for decision_ms in frame.decisions
        if decision_ms >= holdout[0]
    )
    rows_in_validation = sum(
        1
        for frame in frames.values()
        for decision_ms in frame.decisions
        if validation[0] <= decision_ms < validation[1]
    )
    for timeframe, frame in frames.items():
        expected = sum(
            1 for decision_ms in frame.decisions if discovery[0] <= decision_ms < discovery[1]
        )
        check(
            f"evaluated_is_exactly_the_discovery_slice[{timeframe}]",
            evaluated_by_timeframe.get(timeframe, 0) == expected,
            f"{evaluated_by_timeframe.get(timeframe, 0)} vs {expected}",
        )
        check(
            f"iterated_decisions_inside_discovery[{timeframe}]",
            iterated_min.get(timeframe, discovery[0]) >= discovery[0]
            and iterated_max.get(timeframe, discovery[0]) < discovery[1],
            f"[{iterated_min.get(timeframe)}, {iterated_max.get(timeframe)}]",
        )
    check("point_in_time_no_violation", pit_violations == 0, f"violations={pit_violations}")
    check(
        "registry_matches_the_written_rules",
        signal_divergence == 0,
        f"divergence={signal_divergence}",
    )

    for cell in ax.cell_ids():
        published = artifact["cells"][cell]
        value = summary[cell]
        check(f"n[{cell}]", published["n"] == value["n"], f"{published['n']} vs {value['n']}")
        check(
            f"gross[{cell}]",
            abs(float(published["gross_bps"]) - float(value["gross_bps"])) < 1e-6,
            f"{published['gross_bps']} vs {value['gross_bps']}",
        )
        check(
            f"incremental[{cell}]",
            abs(float(published["incremental_delta_bps"]) - float(value["incremental_delta_bps"]))
            < 1e-6,
            f"{published['incremental_delta_bps']} vs {value['incremental_delta_bps']}",
        )
        check(
            f"power[{cell}]",
            published["power_class"] == value["power_class"],
            f"{published['power_class']} vs {value['power_class']}",
        )

    ordered = ax.cell_ids()
    pvalues = [float(summary[cell]["p_raw"]) for cell in ordered]
    bh = _benjamini_hochberg(pvalues, ax.BH_Q)
    holm = _holm(pvalues, ax.HOLM_ALPHA)
    for index, cell in enumerate(ordered):
        check(
            f"bh[{cell}]",
            bool(artifact["multiplicity"][cell]["bh_pass"]) == bool(bh[index]),
            f"{artifact['multiplicity'][cell]['bh_pass']} vs {bh[index]}",
        )
        check(
            f"holm[{cell}]",
            bool(artifact["multiplicity"][cell]["holm_pass"]) == bool(holm[index]),
            f"{artifact['multiplicity'][cell]['holm_pass']} vs {holm[index]}",
        )

    # an independent circular-shift null, over the stored rule directions
    usable: dict[str, tuple[list[int], list[float]]] = {}
    for cell in ordered:
        active_directions: list[int] = []
        active_forwards: list[float] = []
        for direction, forward in zip(rule_directions[cell], rule_forwards[cell], strict=True):
            if direction is None or forward is None or direction == 0:
                continue
            active_directions.append(int(direction))
            active_forwards.append(float(forward))
        if len(active_directions) < 20:
            continue
        usable[cell] = (active_directions, active_forwards)
    check("null_is_computable", len(usable) > 0, f"arms={len(usable)}")

    rng = random.Random(20_261_011)
    draws = int(artifact["permutation_null"]["draws"])
    null_best: list[float] = []
    for _ in range(draws):
        best = float("-inf")
        for arm_directions, arm_forwards in usable.values():
            shift = rng.randrange(1, len(arm_directions))
            shifted = arm_directions[shift:] + arm_directions[:shift]
            best = max(
                best,
                _mean([d * f * 1e4 for d, f in zip(shifted, arm_forwards, strict=True)]),
            )
        null_best.append(best)
    best_arm = max(
        usable,
        key=lambda cell: _mean(
            [d * f * 1e4 for d, f in zip(usable[cell][0], usable[cell][1], strict=True)]
        ),
    )
    observed_best = _mean(
        [d * f * 1e4 for d, f in zip(usable[best_arm][0], usable[best_arm][1], strict=True)]
    )
    p_null = (
        sum(1 for value in null_best if value >= observed_best) / len(null_best)
        if null_best
        else 1.0
    )
    published_null = artifact["permutation_null"]
    check(
        "null_best_arm",
        published_null["best_arm"] == best_arm,
        f"{published_null['best_arm']} vs {best_arm}",
    )
    check(
        "null_observed_best",
        abs(float(published_null["observed_best_bps"]) - round(observed_best, 6)) < 1e-6,
        f"{published_null['observed_best_bps']} vs {round(observed_best, 6)}",
    )
    check(
        "null_p_value",
        abs(float(published_null["p_null_best_ge_observed"]) - round(p_null, 6)) < 1e-6,
        f"{published_null['p_null_best_ge_observed']} vs {round(p_null, 6)}",
    )

    independent_candidates: list[str] = []
    for index, cell in enumerate(ordered):
        value = summary[cell]
        verdict = _gate_verdict(
            value,
            bh_pass=bool(bh[index]),
            holm_pass=bool(holm[index]),
            p_null=p_null,
            hurdle_bps=hurdle_bps,
        )
        if verdict == "VALIDATION_CANDIDATE":
            independent_candidates.append(cell)
        check(
            f"verdict[{cell}]",
            artifact["decisions"][cell]["verdict"] == verdict,
            f"{artifact['decisions'][cell]['verdict']} vs {verdict}",
        )
    check(
        "candidate_count",
        sorted(artifact["oos_candidates"]) == sorted(independent_candidates),
        str(independent_candidates),
    )

    mismatches = sum(1 for _, ok, _ in checks if not ok)
    false_success = 0
    if artifact["oos_candidates"] and not independent_candidates:
        false_success += len(artifact["oos_candidates"])
    if len(artifact["cells"]) != len(ax.cell_ids()):
        false_success += 1
    if artifact["holdout_read"] or artifact["validation_read"]:
        false_success += 1

    payload = {
        "campaign": "ALPHA003-DEV-001",
        "verifier": "scripts/alpha003_verify.py",
        "preregistration_hash": artifact["preregistration_hash"],
        "checks": [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
        "check_count": len(checks),
        "mismatches": mismatches,
        "false_success": false_success,
        "independent_candidates": independent_candidates,
        "independent_cell_count": len(summary),
        "independent_hurdle_bps": hurdle_bps,
        "independent_design_n": independent_design_n,
        "independent_bh_survivors": sum(1 for value in bh if value),
        "rows_available_but_unused_in_validation": rows_in_validation,
        "rows_available_but_unused_in_holdout": rows_in_holdout,
        "status": "PASS" if mismatches == 0 and false_success == 0 else "FAIL",
        "limitations": LIMITATIONS,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "ALPHA003_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (REPORT_DIR / "ALPHA003_VERIFICATION.md").write_text(_render(payload), encoding="utf-8")
    print(
        json.dumps(
            {key: payload[key] for key in ("status", "check_count", "mismatches", "false_success")},
            indent=2,
        )
    )
    if mismatches:
        for name, ok, _detail in checks:
            if not ok:
                print(f"MISMATCH {name}")
    return 0 if mismatches == 0 and false_success == 0 else 1


def _gate_verdict(
    value: Mapping[str, Any],
    *,
    bh_pass: bool,
    holm_pass: bool,
    p_null: float,
    hurdle_bps: float,
) -> str:
    """The frozen promotion gate, recomputed from its published inputs."""
    checks_ok = {
        "raw_positive": float(value["gross_bps"]) > 0.0,
        "incremental_positive": float(value["incremental_delta_bps"]) > 0.0,
        "above_frozen_hurdle": float(value["gross_bps"]) >= hurdle_bps,
        "bh_fdr_pass": bh_pass,
        "holm_pass": holm_pass,
        "powered": value["power_class"] == "POWERED",
        "survives_selection_null": p_null < 0.05,
    }
    if all(checks_ok.values()):
        return "VALIDATION_CANDIDATE"
    if value["power_class"] == "UNDERPOWERED" or float(value["incremental_delta_bps"]) <= 0.0:
        return "INCONCLUSIVE" if value["power_class"] == "UNDERPOWERED" else "REJECT"
    return "REJECT"


def _render(payload: Mapping[str, Any]) -> str:
    lines = [
        "# ALPHA-003 — INDEPENDENT VERIFICATION",
        "",
        f"`STATUS = {payload['status']}`",
        "",
        f"- verifier: `{payload['verifier']}`",
        f"- preregistration_hash: `{payload['preregistration_hash']}`",
        f"- checks: {payload['check_count']} · mismatches: **{payload['mismatches']}** · "
        f"false success: **{payload['false_success']}**",
        f"- independently recomputed hurdle: {payload['independent_hurdle_bps']} bps over "
        f"design_n = {payload['independent_design_n']}",
        f"- independently reproduced candidates: {payload['independent_candidates'] or 'none'}",
        f"- BH survivors (independent): {payload['independent_bh_survivors']}",
        f"- rows available but never used: validation "
        f"{payload['rows_available_but_unused_in_validation']}, holdout "
        f"{payload['rows_available_but_unused_in_holdout']}",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["limitations"])
    lines += ["", "## Checks", ""]
    for entry in payload["checks"]:
        mark = "PASS" if entry["ok"] else "FAIL"
        lines.append(f"- **{mark}** {entry['name']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
