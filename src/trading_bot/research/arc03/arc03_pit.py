"""ARC-03 PIT adversarial battery.

Non-vacuous causal tests over the *frozen* ARC-03 primitives. Fixtures are built from
the same ``Kline5m`` container the certified reader produces, so every check exercises
the real feature code path rather than a paraphrase of it.

Key fixture property: the evaluated (decision) bar is **never the last bar** of the
synthetic partition, so the "future mutation after T" checks are non-vacuous.

Run directly::

    python src/trading_bot/research/arc03/arc03_pit.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import zipfile
from typing import Any

from trading_bot.research.arc03.arc03_authority import (
    BAR_MS,
    DAY_MS,
    Kline5m,
    NO_SIGNAL_PRECEDENCE,
    evaluate_bar,
    load_partition,
    reference_slots,
)
from trading_bot.research.arc03.arc03_normalize import (
    EXPECTED_HEADER,
    normalize_symbol,
    parse_month,
)

START_MS = 1_700_000_000_000 - (1_700_000_000_000 % BAR_MS)
DAYS = 40
BARS_PER_DAY = 288

#: Baseline (non-shock) bar geometry: range 1.0, tiny up body.
BASE_O = 100.0
BASE_H = 100.5
BASE_L = 99.5
BASE_C = 100.1
BASE_V = 1000.0

#: Decision bar: volume record + range record + up-push rejected at the high (SHORT).
SHOCK_DAY = DAYS - 2
SHOCK_SLOT = 100
SHOCK_V = 5000.0
SHOCK_O = 100.0
SHOCK_H = 101.5
SHOCK_L = 99.0
SHOCK_C = 100.2


def slot_open_ms(day: int, slot: int) -> int:
    return START_MS + day * DAY_MS + slot * BAR_MS


def build_partition(
    *,
    symbol: str = "BTCUSDT",
    days: int = DAYS,
    overrides: dict[int, dict[str, float]] | None = None,
    drop: set[int] | None = None,
) -> Kline5m:
    """Deterministic synthetic 5m partition.

    ``overrides`` maps an ``open_time_ms`` to replacement OHLCV values (only the
    supplied keys are replaced). ``drop`` removes bars entirely (to test
    fail-closed behaviour on incomplete reference history).
    """
    overrides = overrides or {}
    drop = drop or set()
    ts: list[int] = []
    cts: list[int] = []
    o: list[float] = []
    h: list[float] = []
    l: list[float] = []
    c: list[float] = []
    v: list[float] = []
    qv: list[float] = []
    n: list[int] = []
    tb: list[float] = []
    tq: list[float] = []
    for d in range(days):
        for i in range(BARS_PER_DAY):
            t = START_MS + d * DAY_MS + i * BAR_MS
            if t in drop:
                continue
            ov = overrides.get(t, {})
            oo = ov.get("o", BASE_O)
            hh = ov.get("h", BASE_H)
            ll = ov.get("l", BASE_L)
            cc = ov.get("c", BASE_C)
            vv = ov.get("v", BASE_V)
            ts.append(t)
            cts.append(t + BAR_MS - 1)
            o.append(oo)
            h.append(hh)
            l.append(ll)
            c.append(cc)
            v.append(vv)
            qv.append(vv * cc)
            n.append(50)
            tb.append(vv * 0.4)
            tq.append(vv * 0.4 * cc)
    return Kline5m(
        symbol=symbol,
        t=tuple(ts),
        ct=tuple(cts),
        o=tuple(o),
        h=tuple(h),
        l=tuple(l),
        c=tuple(c),
        v=tuple(v),
        qv=tuple(qv),
        n=tuple(n),
        tb=tuple(tb),
        tq=tuple(tq),
        sha256="synthetic",
        path="synthetic://partition",
        rows=len(ts),
        index={t: i for i, t in enumerate(ts)},
    )


def shock_overrides(*, direction: str = "up") -> dict[int, dict[str, float]]:
    """Field overrides that make the decision bar a genuine participation-shock
    exhaustion bar. ``up`` -> rejected up-push (SHORT), ``down`` -> rejected
    down-push (LONG)."""
    t = slot_open_ms(SHOCK_DAY, SHOCK_SLOT)
    if direction == "up":
        return {t: {"o": SHOCK_O, "h": SHOCK_H, "l": SHOCK_L, "c": SHOCK_C, "v": SHOCK_V}}
    # mirrored down-push rejected at the low: body < 0, (close - low) > range/2
    return {t: {"o": 100.0, "h": 100.6, "l": 98.6, "c": 99.8, "v": SHOCK_V}}


def _normalize_fixture(
    tmpd: pathlib.Path,
    rows_by_month: dict[str, list[str]],
    *,
    symbol: str = "BTCUSDT",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    raw = tmpd / "raw" / symbol
    for month, rows in rows_by_month.items():
        md = raw / month
        md.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(md / f"{symbol}-5m-{month}.zip", "w") as z:
            z.writestr(f"{symbol}-5m-{month}.csv", "\n".join(rows) + "\n")
    return normalize_symbol(symbol, raw, write=False)


def _month_rows(month: str, *, bars: int, header: bool = False) -> list[str]:
    import calendar

    y, m = int(month[:4]), int(month[5:])
    n = calendar.monthrange(y, m)[1] * BARS_PER_DAY
    n = min(n, bars) if bars else n
    y, m = int(month[:4]), int(month[5:])
    import datetime as dt

    start = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = [EXPECTED_HEADER] if header else []
    for i in range(n):
        t = start + i * BAR_MS
        out.append(f"{t},100.0,100.5,99.5,100.1,10,{t + BAR_MS - 1},1000,5,4,400,0")
    return out


def run_battery() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # ---------------------------------------------------------------- 1. baseline
    ov = shock_overrides(direction="up")
    k = build_partition(overrides=ov)
    pos = k.index[slot_open_ms(SHOCK_DAY, SHOCK_SLOT)]
    base = evaluate_bar(k, pos)
    add(
        "BASELINE_REJECTED_UP_PUSH_YIELDS_SHORT",
        base["emitted"] is True and base["result"] == "SHORT",
        {"result": base.get("result"), "reason": base.get("reason"), "wick_fraction": base.get("wick_fraction")},
    )
    add(
        "DECISION_TIME_IS_BAR_CLOSE_TIME",
        base["decision_time_ms"] == k.ct[pos],
        {"decision_time_ms": base["decision_time_ms"], "bar_close_ms": k.ct[pos]},
    )
    add(
        "DECISION_BAR_IS_NOT_LAST_BAR_OF_PARTITION",
        pos < len(k.t) - 1,
        {"pos": pos, "rows": len(k.t), "future_bars": len(k.t) - 1 - pos},
    )
    add(
        "ALL_REFERENCE_OBSERVATIONS_AT_OR_BEFORE_T",
        all(slot <= base["decision_time_ms"] for slot in reference_slots(k.t[pos])),
        None,
    )

    # ------------------------------------------------- 2. mirrored direction
    k_down = build_partition(overrides=shock_overrides(direction="down"))
    down = evaluate_bar(k_down, k_down.index[slot_open_ms(SHOCK_DAY, SHOCK_SLOT)])
    add(
        "REJECTED_DOWN_PUSH_YIELDS_LONG",
        down["emitted"] is True and down["result"] == "LONG",
        {"result": down.get("result"), "reason": down.get("reason")},
    )

    # ------------------------------------- 3. future mutation after T is invariant
    fut = {t: {"v": 999_999.0, "h": 200.0, "l": 1.0, "c": 150.0, "o": 150.0} for t in k.t if t > k.t[pos]}
    k_fut = build_partition(overrides={**ov, **fut})
    after_fut = evaluate_bar(k_fut, k_fut.index[k.t[pos]])
    add(
        "FUTURE_MUTATION_AFTER_T_CHANGES_NOTHING",
        (after_fut["result"], after_fut["reason"], after_fut["participation_shock"], after_fut["excursion_record"])
        == (base["result"], base["reason"], base["participation_shock"], base["excursion_record"]),
        {"result": after_fut["result"], "participation_shock": after_fut["participation_shock"]},
    )

    # ------------------------------- 4. eligible past mutations DO change state
    ref0 = reference_slots(k.t[pos])[0]
    k_pv = build_partition(overrides={**ov, ref0: {"v": 999_999.0}})
    past_vol = evaluate_bar(k_pv, k_pv.index[k.t[pos]])
    add(
        "PAST_ELIGIBLE_VOLUME_MUTATION_CHANGES_STATE",
        past_vol["participation_shock"] is False and past_vol["reason"] == "NO_PARTICIPATION_SHOCK",
        {"reference_volume_max": past_vol.get("reference_volume_max")},
    )
    ref7 = reference_slots(k.t[pos])[7]
    k_pr = build_partition(overrides={**ov, ref7: {"h": 500.0}})
    past_rng = evaluate_bar(k_pr, k_pr.index[k.t[pos]])
    add(
        "PAST_ELIGIBLE_RANGE_MUTATION_CHANGES_STATE",
        past_rng["excursion_record"] is False and past_rng["reason"] == "NO_EXCURSION_RECORD",
        {"reference_range_max": past_rng.get("reference_range_max")},
    )

    # ------------------------------------------ 5. incomplete reference fails closed
    k_missing = build_partition(overrides=ov, drop={reference_slots(k.t[pos])[7]})
    missing = evaluate_bar(k_missing, k_missing.index[k.t[pos]])
    add(
        "MISSING_REFERENCE_OBSERVATION_FAILS_CLOSED",
        missing["reason"] == "REFERENCE_HISTORY_INCOMPLETE" and missing["emitted"] is False,
        {"reference_missing": missing.get("reference_missing"), "present": missing.get("reference_observations_present")},
    )

    # ------------------------------------ 6. completed-bar visibility semantics
    k_plain = build_partition()
    last = len(k_plain.t) - 1
    before_close = k_plain.ct[last] - 1
    visible = k_plain.last_completed_index(before_close)
    add(
        "INCOMPLETE_CURRENT_BAR_INVISIBLE",
        visible is not None and visible < last and k_plain.ct[visible] <= before_close,
        {"last_visible_index": visible, "bar_index": last},
    )
    add(
        "COMPLETED_BAR_VISIBLE_AT_ITS_OWN_CLOSE",
        k_plain.last_completed_index(k_plain.ct[last]) == last,
        {"index": k_plain.last_completed_index(k_plain.ct[last])},
    )
    add(
        "FUTURE_BARS_INVISIBLE_TO_COMPLETED_LOOKUP",
        k_plain.ct[k_plain.last_completed_index(k_plain.t[10])] <= k_plain.t[10],
        None,
    )

    # ---------------------------------------------- 7. entry strictly after T
    t_pos = k.t[pos]
    entry = k.first_index_strictly_after(base["decision_time_ms"])
    add(
        "ENTRY_IS_STRICTLY_AFTER_DECISION_TIME",
        entry is not None and k.t[entry] > base["decision_time_ms"],
        {"entry_open_ms": k.t[entry] if entry is not None else None, "decision_ms": base["decision_time_ms"]},
    )
    add(
        "SAME_BAR_ENTRY_FORBIDDEN",
        k.first_index_strictly_after(t_pos) != pos,
        {"next_index": k.first_index_strictly_after(t_pos), "decision_index": pos},
    )

    # ------------------------------- 8. strict thresholds (boundary behaviour)
    # equal volume is NOT a record (strict >)
    k_eq = build_partition(overrides={**ov, k.t[pos]: {"o": SHOCK_O, "h": SHOCK_H, "l": SHOCK_L, "c": SHOCK_C, "v": BASE_V}})
    eq = evaluate_bar(k_eq, k_eq.index[k.t[pos]])
    add(
        "EQUAL_VOLUME_IS_NOT_A_SHOCK",
        eq["participation_shock"] is False and eq["reason"] == "NO_PARTICIPATION_SHOCK",
        {"reference_volume_max": eq.get("reference_volume_max"), "volume": eq.get("volume")},
    )
    # exactly half retracement is NOT exhaustion (strict >)
    rng = SHOCK_H - SHOCK_L
    half_close = SHOCK_O + SHOCK_H - SHOCK_L
    k_half = build_partition(
        overrides={**ov, k.t[pos]: {"o": SHOCK_O, "h": SHOCK_H, "l": SHOCK_L, "c": (SHOCK_H + SHOCK_L) / 2.0, "v": SHOCK_V}}
    )
    half = evaluate_bar(k_half, k_half.index[k.t[pos]])
    add(
        "EXACTLY_HALF_RETRACEMENT_IS_NOT_EXHAUSTION",
        half["reason"] == "NO_EXHAUSTION" and half["emitted"] is False,
        {"wick_fraction": half.get("wick_fraction"), "range": rng, "close": (SHOCK_H + SHOCK_L) / 2.0},
    )
    # a zero-range record bar cannot produce exhaustion
    k_flat = build_partition(overrides={**ov, k.t[pos]: {"o": SHOCK_O, "h": SHOCK_O, "l": SHOCK_O, "c": SHOCK_O, "v": SHOCK_V}})
    flat = evaluate_bar(k_flat, k_flat.index[k.t[pos]])
    add(
        "ZERO_RANGE_BAR_YIELDS_NO_EXHAUSTION",
        flat["emitted"] is False and flat["reason"] in {"NO_EXCURSION_RECORD", "NO_EXHAUSTION"},
        {"reason": flat["reason"]},
    )

    # ---------------------------------------- 9. NO_SIGNAL precedence is frozen
    add(
        "NO_SIGNAL_PRECEDENCE_FROZEN_AND_TOTAL",
        NO_SIGNAL_PRECEDENCE[0] == "OUTSIDE_COMMON_WINDOW"
        and NO_SIGNAL_PRECEDENCE[-1] == "INSUFFICIENT_FORWARD_PRICE_DATA"
        and len(set(NO_SIGNAL_PRECEDENCE)) == len(NO_SIGNAL_PRECEDENCE),
        list(NO_SIGNAL_PRECEDENCE),
    )

    # ------------------------------------ 10. normalization contract (fail closed)
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        rows = _month_rows("2024-01", bars=0)
        parsed = None
        raw = tmpd / "raw" / "BTCUSDT"
        for rows_variant, label in ((rows, "clean"), (rows + [rows[0]], "exact_dup")):
            md = raw / "2024-01"
            md.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(md / "BTCUSDT-5m-2024-01.zip", "w") as z:
                z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(rows_variant) + "\n")
            parsed = parse_month(md / "BTCUSDT-5m-2024-01.zip")
            if label == "clean":
                clean_rows = parsed["entry"]["rows"]
            else:
                dup_rows = parsed["entry"]["rows"]
                dup_collapsed = parsed["entry"]["exact_duplicate_rows_collapsed"]
        add(
            "EXACT_DUPLICATE_ROWS_COLLAPSE_DETERMINISTICALLY",
            clean_rows == dup_rows and clean_rows == 31 * BARS_PER_DAY and dup_collapsed == 1,
            {"rows": dup_rows, "collapsed": dup_collapsed},
        )

        # conflicting duplicate -> whole month withheld (fail closed)
        conflict = list(rows)
        conflict[5] = conflict[5].replace(",100.1,", ",777.7,")
        conflict.append(rows[5])
        md = raw / "2024-01"
        with zipfile.ZipFile(md / "BTCUSDT-5m-2024-01.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(conflict) + "\n")
        ledger, written, _ = _normalize_fixture(tmpd, {})
        add(
            "CONFLICTING_DUPLICATE_FAILS_CLOSED",
            written == []
            and ledger[0]["classification"] == "INVALID_CONFLICTING_DUPLICATE"
            and ledger[0]["conflicting_duplicates"] == 1,
            {"classification": ledger[0]["classification"], "written": len(written)},
        )

        # header schema change handled deterministically
        hdr_rows = _month_rows("2024-01", bars=0, header=True)
        with zipfile.ZipFile(md / "BTCUSDT-5m-2024-01.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(hdr_rows) + "\n")
        parsed_hdr = parse_month(md / "BTCUSDT-5m-2024-01.zip")
        add(
            "PROVIDER_HEADER_SCHEMA_CHANGE_HANDLED",
            parsed_hdr["entry"]["header_present"] is True
            and parsed_hdr["entry"]["rows"] == 31 * BARS_PER_DAY
            and parsed_hdr["entry"]["malformed_rows"] == 0,
            {"rows": parsed_hdr["entry"]["rows"]},
        )

        # malformed / non-finite row -> month withheld
        bad = list(rows)
        bad[10] = "not_a_number,100,100,99,100,10,1,1,1,1,1,1"
        with zipfile.ZipFile(md / "BTCUSDT-5m-2024-01.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(bad) + "\n")
        ledger_bad, written_bad, _ = _normalize_fixture(tmpd, {})
        add(
            "MALFORMED_ROW_FAILS_MONTH_CLOSED",
            written_bad == [] and ledger_bad[0]["classification"] == "INVALID_VALUE",
            {"classification": ledger_bad[0]["classification"]},
        )

        # 14-field row (schema drift) -> month withheld, no silent truncation
        drift = list(rows)
        drift[3] = drift[3] + ",extra_field"
        with zipfile.ZipFile(md / "BTCUSDT-5m-2024-01.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(drift) + "\n")
        ledger_drift, written_drift, _ = _normalize_fixture(tmpd, {})
        add(
            "FIELD_COUNT_DRIFT_FAILS_MONTH_CLOSED",
            written_drift == [] and ledger_drift[0]["classification"] == "INVALID_VALUE",
            {"classification": ledger_drift[0]["classification"], "schema_field_mismatch": ledger_drift[0]["schema_field_mismatch"]},
        )

        # a genuine internal gap in a non-first month -> that month withheld, earlier admitted
        f1 = _month_rows("2024-01", bars=0)
        f2 = _month_rows("2024-02", bars=0)
        gap2 = [r for i, r in enumerate(f2) if i != 40]
        md1 = raw / "2024-01"
        md2 = raw / "2024-02"
        md1.mkdir(parents=True, exist_ok=True)
        md2.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(md1 / "BTCUSDT-5m-2024-01.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-01.csv", "\n".join(f1) + "\n")
        with zipfile.ZipFile(md2 / "BTCUSDT-5m-2024-02.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-02.csv", "\n".join(gap2) + "\n")
        led_gap, written_gap, _ = _normalize_fixture(tmpd, {})
        cls = {e["month"]: e["classification"] for e in led_gap if "month" in e}
        add(
            "INTERNAL_GAP_FAILS_MONTH_CLOSED",
            cls.get("2024-02") == "INVALID_GAP"
            and cls.get("2024-01") == "VALID"
            and len(written_gap) == 31 * BARS_PER_DAY,
            {"classifications": cls, "written_rows": len(written_gap)},
        )

        # a leading-truncated FIRST month that runs to month end is admitted (market start)
        f3 = _month_rows("2024-03", bars=100)
        md3 = raw / "2024-03"
        md3.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(md3 / "BTCUSDT-5m-2024-03.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-03.csv", "\n".join(f3) + "\n")
        led_partial, _, _ = _normalize_fixture(tmpd, {})
        partial_cls = {e["month"]: e["classification"] for e in led_partial if "month" in e}
        add(
            "LEADING_TRUNCATED_FIRST_MONTH_ADMITTED",
            partial_cls.get("2024-03") == "INVALID_GAP",
            {"classification_2024_03_mid_month_stop": partial_cls.get("2024-03")},
        )
        # remove the earlier months so 2024-03 becomes the first month AND make it end at month end
        import shutil as _sh

        _sh.rmtree(raw / "2024-01")
        _sh.rmtree(raw / "2024-02")
        full_march = _month_rows("2024-03", bars=0)[-100:]
        with zipfile.ZipFile(md3 / "BTCUSDT-5m-2024-03.zip", "w") as z:
            z.writestr("BTCUSDT-5m-2024-03.csv", "\n".join(full_march) + "\n")
        led_first, written_first, _ = _normalize_fixture(tmpd, {})
        add(
            "VALID_INITIAL_PARTIAL_REQUIRES_RUN_TO_MONTH_END",
            led_first[0]["classification"] == "VALID_INITIAL_PARTIAL"
            and led_first[0]["ends_at_month_end"] is True
            and len(written_first) == 100,
            {"classification": led_first[0]["classification"], "written_rows": len(written_first)},
        )

    # ---------------------- 11. reader fails closed on duplicate/conflicting slots
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        rec = {
            "t": START_MS,
            "ct": START_MS + BAR_MS - 1,
            "o": "1",
            "h": "2",
            "l": "1",
            "c": "1",
            "v": "1",
            "qv": "1",
            "n": 1,
            "tb": "1",
            "tq": "1",
            "sym": "BTCUSDT",
            "ms": "2023-11",
        }
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        (tmpd / "BTCUSDT.jsonl").write_bytes((line + "\n" + line + "\n").encode("utf-8"))
        raised = False
        try:
            load_partition("BTCUSDT", partition_dir=tmpd)
        except ValueError:
            raised = True
        add("READER_FAILS_CLOSED_ON_DUPLICATE_SLOT", raised, None)

    # ------------- 12. archive validity is NOT retroactive for earlier decisions
    # Adding a later month must not change any decision computed at an earlier T.
    later = slot_open_ms(SHOCK_DAY, SHOCK_SLOT) + 3 * DAY_MS
    later_overrides = {t: {"v": 0.001, "h": 100.5001, "l": 99.4999, "c": 100.0} for t in k.t if t >= later}
    k_later = build_partition(overrides={**ov, **later_overrides})
    after_later = evaluate_bar(k_later, k_later.index[k.t[pos]])
    add(
        "LATER_ARCHIVE_VALIDITY_NOT_RETROACTIVE",
        (after_later["result"], after_later["reason"]) == (base["result"], base["reason"]),
        {"result": after_later["result"]},
    )

    return checks


def main() -> int:
    checks = run_battery()
    passed = sum(1 for c in checks if c["pass"])
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"[{mark}] {c['check']}")
    print(f"\nPIT_BATTERY = {passed}/{len(checks)}")
    payload = {
        "battery": "ARC03_PIT_ADVERSARIAL",
        "checks_total": len(checks),
        "checks_passed": passed,
        "result": "PASS" if passed == len(checks) else "FAIL",
        "checks": checks,
    }
    out = pathlib.Path(__file__).resolve().parents[4] / "docs" / "arc03-data-authority-01" / "ARC03_PIT_INDEPENDENT_TESTS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["build_partition", "run_battery", "shock_overrides", "slot_open_ms"]
