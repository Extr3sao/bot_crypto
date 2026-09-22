"""H5 implementation verifier (Track H) — INDEPENDENT re-derivation.

Does NOT treat the H5 engine as the source of truth. Re-derives from the
committed H5_SPEC.json text, on deterministic fixtures, with a naive pure-
Python reference implementation:

    OFI / zOFI / participation -> direction -> entry ts -> stop -> exit
    -> gross R -> cost R -> net R

then imports the engine and requires EXACT agreement. Also cross-checks the
engine's frozen constants against the spec file values (drift gate).
Writes H5_IMPLEMENTATION_VERIFICATION.json next to the spec.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research import h5_orderflow as eng  # noqa: E402  (comparison target only)

OUT = ROOT / "docs" / "external-audit-01" / "h5-orderflow-imbalance-01"
SPEC_PATH = OUT / "H5_SPEC.json"
SPEC_SHA_EXPECTED = "c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023"
TOL = 1e-9


# ---------------------------------------------------------------------------
# Independent reference implementation (straight from the spec text)
# ---------------------------------------------------------------------------


def ref_features(rows: list[dict], t: int) -> tuple[float, float] | None:
    """Return (zOFI_t, P_t) using ONLY bars <= t, or None when NO_SIGNAL."""
    vol_t = rows[t]["volume"]
    if vol_t <= 0:
        return None
    ofi_t = 2.0 * rows[t]["taker_buy"] / vol_t - 1.0
    window = rows[t - 335 : t + 1]
    if len(window) < 336 or any(r["volume"] <= 0 for r in window):
        return None
    ofis = [2.0 * r["taker_buy"] / r["volume"] - 1.0 for r in window]
    mean = sum(ofis) / 336.0
    var = sum((o - mean) ** 2 for o in ofis) / 336.0
    std = math.sqrt(var)
    if std <= 0:
        return None
    sma_trades = sum(r["ntrades"] for r in window) / 336.0
    if sma_trades <= 0:
        return None
    return (ofi_t - mean) / std, rows[t]["ntrades"] / sma_trades


def ref_decisions(rows: list[dict]) -> list[tuple[int, str]]:
    """All qualifying decisions: (decision_index, direction)."""
    out: list[tuple[int, str]] = []
    for t in range(335, len(rows) - 1):
        f = ref_features(rows, t)
        if f is None:
            continue
        z, p = f
        if p < 1.5:
            continue
        if z >= 2.5:
            out.append((t, "LONG"))
        elif z <= -2.5:
            out.append((t, "SHORT"))
    return out


def ref_trades(rows: list[dict]) -> list[dict]:
    """Naive frozen simulation: 12-bar horizon, ATR14 stop, cooldown 4, 10 bps RT."""
    trades: list[dict] = []
    busy_until = -1
    for t, direction in ref_decisions(rows):
        if t <= busy_until:
            continue
        if t + 12 > len(rows) - 1:
            continue  # incomplete tail
        # ATR14 = mean TR over bars t-13..t (bars t-12..t have TR vs prev close)
        trs = []
        for i in range(t - 12, t + 1):
            trs.append(
                max(
                    rows[i]["high"] - rows[i]["low"],
                    abs(rows[i]["high"] - rows[i - 1]["close"]),
                    abs(rows[i]["low"] - rows[i - 1]["close"]),
                )
            )
        atr = sum(trs) / len(trs)
        entry = rows[t + 1]["open"]
        stop = entry - atr if direction == "LONG" else entry + atr
        exit_price, exit_at = rows[t + 12]["close"], t + 12
        for j in range(t + 1, t + 13):
            hit = rows[j]["low"] <= stop if direction == "LONG" else rows[j]["high"] >= stop
            if hit:
                exit_price, exit_at = stop, j
                break
        move = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
        risk_frac = atr / entry
        gross_r = move / atr
        cost_r = 0.001 / risk_frac
        trades.append(
            {
                "decision_index": t,
                "direction": direction,
                "entry_index": t + 1,
                "entry_price": entry,
                "stop_price": stop,
                "exit_index": exit_at,
                "exit_price": exit_price,
                "gross_r": gross_r,
                "cost_r": cost_r,
                "net_r": gross_r - cost_r,
            }
        )
        busy_until = t + 12 + 4
    return trades


# ---------------------------------------------------------------------------
# Deterministic fixture (pure python, deliberately non-trivial)
# ---------------------------------------------------------------------------


def fixture_rows() -> list[dict]:
    rows: list[dict] = []
    price = 50.0
    vol_base, tr_base = 800.0, 120.0
    for i in range(600):
        # near-flat baseline flow so shocks are extreme in the trailing window
        share = 0.5 + 0.01 * math.sin(i / 13.0)
        if i % 89 == 40:
            share = 1.0  # extreme buy bar -> OFI = +1
        if i % 97 == 61:
            share = 0.0  # extreme sell bar -> OFI = -1
        volume = vol_base * (1.0 + 0.2 * math.sin(i / 31.0))
        taker = volume * share
        ntrades = tr_base * (1.0 + 0.3 * math.sin(i / 23.0))
        if i % 89 == 40 or i % 97 == 61:
            ntrades = tr_base * 12.0  # participation burst
        o = price
        c = price * (1.0 + 0.004 * math.sin(i / 9.0))
        h = max(o, c) * 1.002
        lo = min(o, c) * 0.998
        rows.append(
            {
                "ts": 1_600_000_000_000 + i * 3_600_000,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": volume,
                "ntrades": ntrades,
                "taker_buy": taker,
            }
        )
        price = c
    return rows


def main() -> int:
    report: dict[str, object] = {
        "verifier": "scripts/h5_implementation_verifier.py",
        "tolerance": TOL,
    }

    # -- spec integrity (verifier loads the COMMITTED artifact) --
    spec_bytes = SPEC_PATH.read_bytes()
    spec_sha = hashlib.sha256(spec_bytes).hexdigest()
    report["spec_sha256"] = spec_sha
    report["spec_sha_matches_prereg"] = spec_sha == SPEC_SHA_EXPECTED
    spec = json.loads(spec_bytes)

    # -- engine constants vs spec text (drift gate) --
    z_thr = 2.5
    p_thr = 1.5
    lookback = 336
    hold = int(spec["direction_rules"]["max_holding_period_bars"])
    cooldown = int(spec["direction_rules"]["cooldown_bars"])
    rt_bps = float(spec["cost_model"]["round_trip_bps"])
    checks = {
        "Z_ENTRY==2.5": z_thr == eng.Z_ENTRY,
        "P_GATE==1.5": p_thr == eng.P_GATE,
        "LOOKBACK==336": lookback == eng.LOOKBACK_BARS,
        "HOLD_BARS==spec": hold == eng.HOLD_BARS,
        "COOLDOWN==spec": cooldown == eng.COOLDOWN_BARS,
        "COST_RT_BPS==spec": rt_bps == eng.COST_RT_BPS,
        "ATR_PERIOD==14": eng.ATR_PERIOD == 14,
        "MIN_TOTAL==30": int(spec["minimum_n"]["total_trades"]) == eng.MIN_TOTAL_TRADES,
        "MIN_DIRECTION==15": int(spec["minimum_n"]["direction_cell"]) == eng.MIN_DIRECTION_CELL,
        "MIN_ASSET==10": int(spec["minimum_n"]["asset_cell"]) == eng.MIN_ASSET_CELL,
        "SEED==20260910": eng.SEED == 20260910,
        "PF_NET_MIN==1.15": eng.PF_NET_MIN == 1.15,
        "P_SHARPE_MIN==0.90": eng.P_SHARPE_MIN == 0.90,
        "PERM_P_MAX==0.05": eng.PERM_P_MAX == 0.05,
    }
    report["constant_drift_checks"] = checks

    # -- fixture re-derivation vs engine --
    rows = fixture_rows()
    ts = [r["ts"] for r in rows]
    op = [r["open"] for r in rows]
    hi = [r["high"] for r in rows]
    lo = [r["low"] for r in rows]
    cl = [r["close"] for r in rows]
    vol = [r["volume"] for r in rows]
    ntr = [r["ntrades"] for r in rows]
    tbv = [r["taker_buy"] for r in rows]

    ref = ref_trades(rows)
    import numpy as np

    feat = eng.compute_features(np.asarray(vol), np.asarray(ntr), np.asarray(tbv))
    got, skipped, blocked = eng.simulate_h5(
        np.asarray(ts, dtype=np.int64),
        np.asarray(op),
        np.asarray(hi),
        np.asarray(lo),
        np.asarray(cl),
        np.asarray(vol),
        np.asarray(ntr),
        np.asarray(tbv),
        "FIXTURE",
        feat=feat,
    )
    fields = (
        "decision_index",
        "direction",
        "entry_index",
        "entry_price",
        "stop_price",
        "exit_index",
        "exit_price",
        "gross_r",
        "cost_r",
        "net_r",
    )
    mismatches: list[str] = []
    if len(ref) != len(got):
        mismatches.append(f"trade count: ref={len(ref)} engine={len(got)}")
    else:
        for a, b in zip(ref, got, strict=False):
            for f in fields:
                va, vb = a[f], getattr(b, f)
                if isinstance(va, float):
                    ok = abs(va - float(vb)) <= TOL * max(1.0, abs(va))
                else:
                    ok = va == vb
                if not ok:
                    mismatches.append(f"trade@{a['decision_index']}.{f}: ref={va!r} engine={vb!r}")
    report["fixture_trades_ref"] = len(ref)
    report["fixture_trades_engine"] = len(got)
    report["fixture_trade_comparison_meaningful"] = len(ref) >= 5
    report["fixture_skipped_incomplete_engine"] = skipped
    report["fixture_blocked_cooldown_engine"] = blocked
    report["fixture_field_mismatches"] = mismatches[:20]
    report["fixture_mismatch_count"] = len(mismatches)

    # -- spot re-derivation of 3 features by hand --
    spot: list[bool] = []
    for t in (400, 445, 520):
        rf = ref_features(rows, t)
        zf, pf = feat["zofi"][t], feat["part"][t]
        if rf is None:
            spot.append(not (math.isfinite(zf) and math.isfinite(pf)))
        else:
            spot.append(abs(rf[0] - float(zf)) <= TOL and abs(rf[1] - float(pf)) <= TOL)
    report["feature_spot_checks_ok"] = all(spot)

    all_ok = (
        report["spec_sha_matches_prereg"]
        and all(checks.values())
        and not mismatches
        and all(spot)
        and len(ref) >= 5  # the comparison must be non-vacuous
    )
    report["VERDICT"] = "PASS" if all_ok else "FAIL"

    (OUT / "H5_IMPLEMENTATION_VERIFICATION.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "spec_sha_matches_prereg",
                    "fixture_trades_ref",
                    "fixture_trades_engine",
                    "fixture_mismatch_count",
                    "feature_spot_checks_ok",
                    "VERDICT",
                )
            }
        )
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
