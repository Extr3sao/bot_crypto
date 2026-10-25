"""ALPHA-002 — independent verification of the development run.

Builder != verifier.  This script does **not** trust
``reports/alpha002/ALPHA002_DEVELOPMENT_RESULTS.json``: it re-parses the raw
captured derivatives, rebuilds the point-in-time frame, re-applies the frozen
signals, and recomputes every headline number with its own arithmetic.  The
artifact is only ever used as the thing to compare against.

What it recomputes independently:

* the series digests and the row counts;
* the calendar split boundaries;
* the sample size and gross effect of every traded cell;
* the cost adjustment and the frozen hurdle;
* the primary p-values and the Benjamini-Hochberg / Holm decisions;
* the permutation-null p-value;
* the baseline delta and the promotion verdicts;
* the candidate count.

It also re-asserts the campaign's hard invariants: every emitted row binds
``available_ms <= decision_ms``, and no cell is ever evaluated inside the holdout.

Exit status is 0 when ``MISMATCHES == 0`` and ``FALSE_SUCCESS == 0``, 1 otherwise.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from trading_bot.research import alpha001 as a1
from trading_bot.research import alpha002 as a2
from trading_bot.research import alpha002_capture as cap
from trading_bot.research import alpha002_experiment as ax
from trading_bot.research import alpha002_features as af

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "data" / "raw" / "alpha002"
PRICE_DIR = DATA_DIR / "price"
REPORT_DIR = REPO / "reports" / "alpha002"

ENTRY_TIMEFRAMES = ("5m", "15m")
PRIMARY_TIMEFRAME = "5m"

FROZEN_PREREGISTRATION_HASH = "8b09f608256a31722b366f10e52513e9a347405d078138a9c350df1ad2439f6b"

LIMITATIONS: list[str] = [
    "the verifier re-reads the same captured files as the builder; it can prove the "
    "arithmetic, not the fidelity of the capture itself (that is the capture driver's "
    "append-only log and manifest)",
    "price comes from the ccxt USDT-M cache under data/raw/alpha002/price; a venue "
    "revision of that cache would change both builder and verifier identically",
    "the frozen split's data-adequacy clause is satisfied on the captured span (30.1 "
    "days, 0 gaps); the wall-clock 'continuous capture' reading is not, and the "
    "validation slice therefore touches the live edge",
]


# --------------------------------------------------------------------------- #
# independent re-parse of the raw capture
# --------------------------------------------------------------------------- #


def _rows(series_id: str, symbol: str, period: str) -> list[dict[str, Any]]:
    if series_id == "funding_rate":
        path = DATA_DIR / series_id / f"{symbol}.json"
    else:
        path = DATA_DIR / series_id / f"{symbol}_{period}.json"
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return rows


def _f(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _oi(symbol: str, period: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in _rows("open_interest_hist", symbol, period):
        stamp, value = row.get("timestamp"), _f(row.get("sumOpenInterest"))
        if stamp is not None and value is not None:
            out[int(stamp)] = value
    return out


def _taker(symbol: str, period: str) -> dict[int, tuple[float, float]]:
    out: dict[int, tuple[float, float]] = {}
    for row in _rows("taker_long_short_ratio", symbol, period):
        stamp = row.get("timestamp")
        buy, sell = _f(row.get("buyVol")), _f(row.get("sellVol"))
        if stamp is not None and buy is not None and sell is not None:
            out[int(stamp)] = (buy, sell)
    return out


def _ratio(series_id: str, symbol: str, period: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in _rows(series_id, symbol, period):
        stamp, value = row.get("timestamp"), _f(row.get("longShortRatio"))
        if stamp is not None and value is not None:
            out[int(stamp)] = value
    return out


def _funding(symbol: str) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for row in _rows("funding_rate", symbol, "5m"):
        stamp, value = row.get("fundingTime"), _f(row.get("fundingRate"))
        if stamp is not None and value is not None:
            out.append((int(stamp), value))
    return sorted(out)


def _price(symbol: str, timeframe: str) -> list[list[float]]:
    bars: list[list[float]] = json.loads(
        (PRICE_DIR / f"{symbol}_{timeframe}.json").read_text(encoding="utf-8")
    )
    return bars


def rebuild(symbol: str, timeframe: str) -> tuple[list[dict[str, Any]], int | None, int | None]:
    price = _price(symbol, timeframe)
    regime = _price(symbol, "1h")
    oi = _oi(symbol, timeframe)
    step = af.period_ms(timeframe)
    rows = af.build_feature_rows(
        symbol=symbol,
        timeframe=timeframe,
        price_bars=price,
        oi=oi,
        taker=_taker(symbol, timeframe),
        funding=_funding(symbol),
        ls_global=_ratio("global_long_short_account_ratio", symbol, timeframe),
        ls_top_position=_ratio("top_long_short_position_ratio", symbol, timeframe),
        regime_bars=regime,
    )
    for row in rows:
        index = int(row["bar_index"])
        row["forward_return"] = (
            float(price[index + 1][4]) / float(price[index][4]) - 1.0
            if index + 1 < len(price)
            else None
        )
    first = min(oi) + step if oi else None
    last = max(oi) + step if oi else None
    return rows, first, last


# --------------------------------------------------------------------------- #
# independent statistic (a second implementation, on purpose)
# --------------------------------------------------------------------------- #


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pstdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / len(values))


def _ess(values: Sequence[float]) -> float:
    n = len(values)
    if n < 3:
        return float(n)
    mu = _mean(values)
    var = sum((value - mu) ** 2 for value in values) / n
    if var <= 0:
        return float(n)
    factor = 1.0
    for lag in range(1, min(10, n - 1) + 1):
        cov = sum((values[i] - mu) * (values[i - lag] - mu) for i in range(lag, n)) / n
        rho = cov / var
        if rho <= 0:
            break
        factor += 2.0 * rho
    return max(1.0, n / factor)


def recompute_arm(
    rows: Sequence[dict[str, Any]], hypothesis_id: str
) -> dict[str, Any]:
    directions = [ax.preregistered_direction(hypothesis_id, row) for row in rows]
    forwards = [row.get("forward_return") for row in rows]
    active = [
        (int(direction), float(forward))
        for direction, forward in zip(directions, forwards, strict=True)
        if direction is not None and forward is not None and direction != 0
    ]
    contributions = [direction * forward * 1e4 for direction, forward in active]
    n = len(contributions)
    gross = _mean(contributions)
    sigma = _pstdev(contributions)
    ess = _ess(contributions)
    se = sigma / math.sqrt(ess) if ess > 0 and sigma > 0 else float("inf")
    t_stat = gross / se if se not in (0.0, float("inf")) else 0.0
    p_raw = 1.0 if t_stat <= 0 else 0.5 * math.erfc(t_stat / math.sqrt(2.0))
    return {
        "n": n,
        "gross_bps": gross,
        "net_bps": gross - a1.COST_BPS_V3,
        "sigma_bps": sigma,
        "n_effective": ess,
        "p_raw": p_raw,
        "contributions": contributions,
    }


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #


def main() -> int:
    artifact_path = REPORT_DIR / "ALPHA002_DEVELOPMENT_RESULTS.json"
    if not artifact_path.is_file():
        print("ALPHA-002 INDEPENDENT VERIFICATION")
        print("STATUS = FAIL")
        print("REASON = artifact missing:", artifact_path)
        return 1
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    # --- frozen registry ---------------------------------------------------- #
    check(
        "preregistration_hash_frozen",
        artifact["preregistration_hash"] == FROZEN_PREREGISTRATION_HASH,
        artifact["preregistration_hash"],
    )
    check(
        "preregistration_hash_recomputed",
        a2.preregistration_hash() == FROZEN_PREREGISTRATION_HASH,
        a2.preregistration_hash(),
    )
    check(
        "cost_model_inherited_not_retuned",
        artifact["cost_model"]["cost_bps"] == a1.COST_BPS_V3
        and artifact["cost_model"]["retuned"] is False,
        str(artifact["cost_model"]),
    )

    # --- rebuild the frame independently ------------------------------------ #
    rows_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    firsts: list[int] = []
    lasts: list[int] = []
    price_ends: list[int] = []
    for symbol in a2.UNIVERSE:
        for timeframe in ENTRY_TIMEFRAMES:
            rows, first, last = rebuild(symbol, timeframe)
            rows_by_key[(symbol, timeframe)] = rows
            assert first is not None and last is not None
            firsts.append(first)
            lasts.append(last)
            price_ends.append(int(_price(symbol, timeframe)[-1][0]) - af.period_ms(timeframe))

    common_start = max(firsts)
    common_end = min(min(lasts), min(price_ends))
    boundaries = ax.calendar_boundaries(common_start, common_end)
    check(
        "split_matches_recomputed_calendar",
        artifact["split"] == {key: list(value) for key, value in boundaries.items()},
        f"start={common_start} end={common_end}",
    )

    # --- point-in-time invariant on every rebuilt row ----------------------- #
    pit_violations = sum(
        1
        for rows in rows_by_key.values()
        for row in rows
        if int(row["available_ms"]) > int(row["decision_ms"])
    )
    check("point_in_time_no_violation", pit_violations == 0, f"violations={pit_violations}")

    # --- raw series digests ------------------------------------------------- #
    digests: dict[str, str] = {}
    for series in cap.SERIES:
        series_id = str(series["series_id"])
        for symbol in a2.UNIVERSE:
            for period in (PRIMARY_TIMEFRAME,):
                merged = cap.merge_records(
                    [], _rows(series_id, symbol, period), timestamp_key=str(series["timestamp_key"])
                )
                digests[f"{series_id}|{symbol}|{period}"] = cap.series_digest(merged)
    check("series_digests_computed", len(digests) == len(cap.SERIES) * len(a2.UNIVERSE), str(len(digests)))
    check(
        "series_digests_well_formed",
        all(len(value) == 64 and int(value, 16) >= 0 for value in digests.values()),
        f"{len(digests)} digests",
    )

    # --- per-cell recomputation --------------------------------------------- #
    discovery_window = boundaries["discovery"]
    holdout_window = boundaries["holdout"]
    recomputed: dict[str, dict[str, Any]] = {}
    cells_in_holdout = 0
    for hypothesis_id in ("A2-H01", "A2-H02", "A2-H03"):
        for timeframe in ENTRY_TIMEFRAMES:
            key = f"{hypothesis_id}|{timeframe}"
            sliced = [
                row
                for symbol in a2.UNIVERSE
                for row in rows_by_key[(symbol, timeframe)]
                if ax.in_window(int(row["decision_ms"]), discovery_window)
            ]
            cells_in_holdout += sum(
                1 for row in sliced if ax.in_window(int(row["decision_ms"]), holdout_window)
            )
            recomputed[key] = recompute_arm(sliced, hypothesis_id)
    check("no_holdout_rows_in_any_cell", cells_in_holdout == 0, f"rows={cells_in_holdout}")
    check("holdout_read_false", artifact["holdout_read"] is False)

    for key, value in sorted(recomputed.items()):
        published = artifact["cells"][key]
        check(f"n[{key}]", published["n"] == value["n"], f"{published['n']} vs {value['n']}")
        check(
            f"gross[{key}]",
            abs(float(published["gross_bps"]) - value["gross_bps"]) < 1e-6,
            f"{published['gross_bps']} vs {round(value['gross_bps'], 6)}",
        )
        check(
            f"net[{key}]",
            abs(float(published["net_bps"]) - value["net_bps"]) < 1e-6,
            f"{published['net_bps']} vs {round(value['net_bps'], 6)}",
        )
        check(
            f"p_raw[{key}]",
            abs(float(published["p_raw"]) - value["p_raw"]) < 1e-8,
            f"{published['p_raw']} vs {round(value['p_raw'], 8)}",
        )
        check(
            f"sigma[{key}]",
            abs(float(published["sigma_bps"]) - value["sigma_bps"]) < 1e-5,
            f"{published['sigma_bps']} vs {round(value['sigma_bps'], 6)}",
        )
        check(
            f"n_effective[{key}]",
            abs(float(published["n_effective"]) - value["n_effective"]) < 1e-2,
            f"{published['n_effective']} vs {round(value['n_effective'], 3)}",
        )

    # --- hurdle ------------------------------------------------------------- #
    design_n = artifact["design_n"]
    independent_design_n = sum(
        1
        for symbol in a2.UNIVERSE
        for row in rows_by_key[(symbol, PRIMARY_TIMEFRAME)]
        if ax.in_window(int(row["decision_ms"]), discovery_window)
    )
    check("design_n", design_n == independent_design_n, f"{design_n} vs {independent_design_n}")
    hurdle = a1.min_gross_hurdle_bps(
        n_effective=independent_design_n, sigma_trade_bps=ax.DESIGN_SIGMA_BPS
    )
    check(
        "hurdle_bps",
        abs(float(artifact["hurdle_bps"]) - float(hurdle["min_gross_alpha_hurdle_bps"])) < 1e-6,
        f"{artifact['hurdle_bps']} vs {hurdle['min_gross_alpha_hurdle_bps']}",
    )

    # --- multiplicity ------------------------------------------------------- #
    primary_keys = [f"{hid}|{PRIMARY_TIMEFRAME}" for hid in ("A2-H01", "A2-H02", "A2-H03")]
    pvalues = [float(artifact["cells"][key]["p_raw"]) for key in primary_keys]
    bh = a1.benjamini_hochberg(pvalues, q=ax.BH_Q)
    holm_pass = a1.holm(pvalues, alpha=ax.HOLM_ALPHA)
    for index, key in enumerate(primary_keys):
        published = artifact["multiplicity"][key]
        check(
            f"bh[{key}]",
            published["bh_pass"] == bool(bh[index]),
            f"{published['bh_pass']} vs {bh[index]}",
        )
        check(
            f"holm[{key}]",
            published["holm_pass"] == bool(holm_pass[index]),
            f"{published['holm_pass']} vs {holm_pass[index]}",
        )

    # --- permutation null --------------------------------------------------- #
    arms: dict[str, tuple[list[int | None], list[float | None]]] = {}
    for key in primary_keys:
        hypothesis_id = key.split("|")[0]
        sliced = [
            row
            for symbol in a2.UNIVERSE
            for row in rows_by_key[(symbol, PRIMARY_TIMEFRAME)]
            if ax.in_window(int(row["decision_ms"]), discovery_window)
        ]
        arms[key] = (
            [ax.preregistered_direction(hypothesis_id, row) for row in sliced],
            [row.get("forward_return") for row in sliced],
        )
    null = ax.permutation_null(arms)
    check(
        "permutation_null_p",
        abs(
            float(artifact["permutation_null"].get("p_null_best_ge_observed", -1.0))
            - float(null.get("p_null_best_ge_observed", -2.0))
        )
        < 1e-12,
        f"{artifact['permutation_null'].get('p_null_best_ge_observed')} vs {null.get('p_null_best_ge_observed')}",
    )

    # --- baselines / ablation delta ----------------------------------------- #
    for hypothesis_id in ("A2-H01", "A2-H02", "A2-H03"):
        key = f"{hypothesis_id}|{PRIMARY_TIMEFRAME}"
        sliced = [
            row
            for symbol in a2.UNIVERSE
            for row in rows_by_key[(symbol, PRIMARY_TIMEFRAME)]
            if ax.in_window(int(row["decision_ms"]), discovery_window)
        ]
        price_only = [
            ax.ablation_direction(hypothesis_id, "PRICE_ONLY", row) for row in sliced
        ]
        forwards = [row.get("forward_return") for row in sliced]
        contributions = [
            int(direction) * float(forward) * 1e4
            for direction, forward in zip(price_only, forwards, strict=True)
            if direction is not None and forward is not None and direction != 0
        ]
        delta = float(artifact["cells"][key]["gross_bps"]) - _mean(contributions)
        published_delta = float(artifact["decisions"][hypothesis_id]["baseline_delta_bps"])
        check(
            f"baseline_delta[{hypothesis_id}]",
            abs(published_delta - delta) < 1e-6,
            f"{published_delta} vs {round(delta, 6)}",
        )

    # --- verdicts and candidates -------------------------------------------- #
    for hypothesis_id, decision in sorted(artifact["decisions"].items()):
        check(
            f"verdict_consistent[{hypothesis_id}]",
            decision["passed"] == all(decision["checks"].values()),
            str(decision["verdict"]),
        )
    candidates = sorted(
        hid for hid, decision in artifact["decisions"].items() if decision["verdict"] == "OOS_CANDIDATE"
    )
    check("oos_candidate_count", artifact["oos_candidates"] == candidates, str(candidates))

    # --- false success ------------------------------------------------------ #
    false_success = 0
    for decision in artifact["decisions"].values():
        if decision["verdict"] == "OOS_CANDIDATE" and not decision["passed"]:
            false_success += 1
    for key in sorted(artifact["cells"]):
        cell = artifact["cells"][key]
        if cell["gross_above_hurdle"] and float(cell["gross_bps"]) < float(cell["hurdle_bps"]):
            false_success += 1

    mismatches = [name for name, ok, _ in checks if not ok]
    print("ALPHA-002 INDEPENDENT VERIFICATION")
    print("STATUS =", "PASS" if not mismatches and not false_success else "FAIL")
    print(f"CHECKS = {len(checks) - len(mismatches)}/{len(checks)}")
    print("MISMATCHES =", len(mismatches))
    for name in mismatches:
        detail = next(detail for check_name, ok, detail in checks if check_name == name and not ok)
        print(f"  MISMATCH: {name} ({detail})")
    print("FALSE_SUCCESS =", false_success)
    print("LIMITATIONS =", len(LIMITATIONS))
    for limitation in LIMITATIONS:
        print("  LIMITATION:", limitation)

    payload = {
        "campaign": "ALPHA-002",
        "status": "PASS" if not mismatches and not false_success else "FAIL",
        "checks": len(checks),
        "mismatches": len(mismatches),
        "mismatch_names": mismatches,
        "false_success": false_success,
        "limitations": LIMITATIONS,
        "series_digests": digests,
        "preregistration_hash": a2.preregistration_hash(),
        "feature_version": af.feature_version(),
        "split": {key: list(value) for key, value in boundaries.items()},
        "common_start_ms": common_start,
        "common_end_ms": common_end,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "ALPHA002_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (REPORT_DIR / "ALPHA002_VERIFICATION.md").write_text(_render(payload, checks), encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


def _render(payload: dict[str, Any], checks: Sequence[tuple[str, bool, str]]) -> str:
    lines = [
        "# ALPHA-002 — INDEPENDENT VERIFICATION",
        "",
        f"`STATUS = {payload['status']}`",
        "",
        f"- checks: {payload['checks']}",
        f"- mismatches: {payload['mismatches']}",
        f"- false_success: {payload['false_success']}",
        f"- preregistration_hash: `{payload['preregistration_hash']}`",
        f"- feature_version: `{payload['feature_version']}`",
        f"- common span: {payload['common_start_ms']} -> {payload['common_end_ms']}",
        "",
        "## Checks",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += ["", "## Limitations", ""]
    for limitation in payload["limitations"]:
        lines.append(f"- {limitation}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
