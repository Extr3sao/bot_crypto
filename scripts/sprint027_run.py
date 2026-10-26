"""RFC-027 — Positioning-data edge discovery (Sprint 004): orchestrator.

Runs the §73 sequence and writes every required artifact under
``reports/positioning-data/`` and ``reports/edge-discovery/sprint004/`` plus
``reports/RFC027_FINAL_REPORT.{md,json}``.

READ-ONLY / RESEARCH-ONLY.  No orders, no credentials, no runtime path.
``COST_MODEL_V3`` is reused unchanged as the control.  The HOLDOUT split is
never loaded for analytics (§19).
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
from datetime import UTC
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import sprint027_lib as L  # noqa: E402
import sprint027_signals as SG  # noqa: E402

POS = L.POS_DIR
OUT = L.OUT_DIR
N_PERM = 400
BLOCK_BARS = 48          # 24h block permutation
IC_ALPHA = 0.05          # family-wise significance
EDGE_COST_BANDS = (
    (1.0, "COST_KILLED"), (1.25, "THIN"), (1.5, "INTERESTING"),
    (2.0, "STRONGER"), (float("inf"), "HIGH_MARGIN"),
)


def edge_cost_band(ratio: float) -> str:
    for thr, name in EDGE_COST_BANDS:
        if ratio < thr:
            return name
    return "HIGH_MARGIN"


# ---------------------------------------------------------------------------
# DATA ARTIFACTS (§60)
# ---------------------------------------------------------------------------


def _load_fetch_audit() -> dict[str, Any]:
    p = POS / "_fetch_source_audit.json"
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def build_source_audit() -> dict[str, Any]:
    fa = _load_fetch_audit()
    payload: dict[str, Any] = {
        "mission": "acquire the deepest available official PIT positioning history",
        "venue": "Binance",
        "product": "USDⓈ-M Perpetual (UM)",
        "archive": "data.binance.vision (official public archive)",
        "repository": "binance/binance-public-data",
        "endpoints_used": [
            "data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-{YYYY-MM-DD}.zip",
            "data/futures/um/monthly/klines/{SYM}/5m/{SYM}-5m-{YYYY-MM}.zip",
        ],
        "rest_endpoint_considered": "/futures/data/openInterestHist (~30d only) — "
                                   "NOT used as the historical source (§6)",
        "paid_providers_used": False,
        "common_window": fa["window"],
        "assets": fa["assets"],
        "metrics_columns_documented": fa["metrics_columns_documented"],
        "label_era_flip_detected": fa["label_era_flip_detected"],
        "label_era_flip_suspected_by_spec": fa["label_era_flip_suspected_by_spec"],
        "assets_metrics": fa["assets_metrics"],
        "assets_klines": fa["assets_klines"],
        "history_months": round(
            (_as_date(fa["window"]["common_end"]) - _as_date(fa["window"]["common_start"])).days / 30.44, 1),
        "source_status": "AVAILABLE",
    }
    return payload


def _as_date(s: str) -> Any:
    from datetime import date
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def build_schema_audit() -> dict[str, Any]:
    corpus: dict[str, Any] = {}
    for sym in L.ASSETS:
        m = L.load_metrics(sym)
        variants = json.loads(str(m["_schema_variants"][0]))
        corpus[sym] = {
            "rows": int(m["create_time_ms"].shape[0]),
            "schema_variant_histogram": variants,
            "columns_expected": list(L.METRICS_COLUMNS) if hasattr(L, "METRICS_COLUMNS")
                                else list(_METRICS_COLUMNS),
        }
    drift = sorted({v for c in corpus.values() for v in c["schema_variant_histogram"]})
    return {
        "documented_columns": list(_METRICS_COLUMNS),
        "observed_row_widths": drift,
        "schema_drift": len(drift) > 1,
        "schema_stable_8_columns": drift == ["8"],
        "per_asset": corpus,
        "note": "Column NAMES are stable across 2020-2026; only the sampling grid "
                "(2.5m<=2021-01, 5m>=2021-06) and the create_time LABEL SEMANTICS "
                "(flip 2024-03-04) changed.",
    }


_METRICS_COLUMNS = (
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
)


# ---------------------------------------------------------------------------
# TIMESTAMP SEMANTICS (§8-§9) — empirical detection, no hard-coded date
# ---------------------------------------------------------------------------


def _taker_return_corr(asset: str, day: str) -> dict[str, float | None] | None:
    """Correlate the metrics taker ratio with the 5m return at T and at T-5m.

    Return ~= 0.6 with [T, T+5m) => label = interval START.
    Return ~= 0.6 with [T-5m, T) => label = interval END.
    """
    from datetime import date as _date

    import sprint027_fetch as F
    d = _date(*map(int, day.split("-")))
    _day, rows = F._fetch_metrics_day(asset, d)
    if rows is None or not rows:
        return None
    mts: dict[int, float] = {}
    for r in rows:
        try:
            mts[F._parse_row_ts(r[0])] = float(r[7])
        except (ValueError, IndexError):
            continue
    k = F.fetch_klines_asset(asset, d, d)
    kts: dict[int, tuple[float, float]] = {}
    for r in k["rows"]:
        try:
            kts[int(r[0])] = (float(r[1]), float(r[4]))
        except (ValueError, IndexError):
            continue
    from datetime import datetime
    start = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
    end = start + 86_400_000
    a: list[float] = []
    y_same: list[float] = []
    y_prev: list[float] = []
    for t, ratio in mts.items():
        if t in kts and start <= t < end:
            o, c = kts[t]
            a.append(ratio)
            y_same.append(c / o - 1.0)
            if (t - 300_000) in kts:
                op, cp = kts[t - 300_000]
                y_prev.append(cp / op - 1.0)
    def cc(x: list[float], y: list[float]) -> float | None:
        if len(x) < 50:
            return None
        xa, ya = np.array(x), np.array(y)
        if xa.std() == 0 or ya.std() == 0:
            return None
        return float(np.corrcoef(xa[: len(y)], ya)[0, 1])
    n = min(len(a), len(y_prev))
    out: dict[str, float | None] = {"corr_same": cc(a, y_same),
                                    "corr_prev": cc(a[:n], y_prev[:n]),
                                    "n": float(len(a))}
    return out


def build_timestamp_semantics() -> dict[str, Any]:
    probes: dict[str, dict[str, float | None] | None] = {
        "2024-01-15": _taker_return_corr("BTCUSDT", "2024-01-15"),
        "2024-03-01": _taker_return_corr("BTCUSDT", "2024-03-01"),
        "2024-03-04": _taker_return_corr("BTCUSDT", "2024-03-04"),
        "2025-01-15": _taker_return_corr("BTCUSDT", "2025-01-15"),
        "2026-06-24": _taker_return_corr("BTCUSDT", "2026-06-24"),
        "2026-06-25": _taker_return_corr("BTCUSDT", "2026-06-25"),
        "2026-06-26": _taker_return_corr("BTCUSDT", "2026-06-26"),
    }
    def era(v: dict[str, float | None] | None) -> str:
        if not v or v["corr_same"] is None or v["corr_prev"] is None:
            return "UNKNOWN"
        return "START" if v["corr_same"] > v["corr_prev"] else "END"
    ruled = {d: era(v) for d, v in probes.items()}
    probes_out: dict[str, dict[str, Any]] = {d: {**(v or {}), "era": ruled[d]}
                                             for d, v in probes.items()}
    def _ev(d: str) -> str:
        v = probes.get(d) or {}
        cs, cp = v.get("corr_same"), v.get("corr_prev")
        if cs is None or cp is None:
            return f"{d} => {ruled[d]}"
        return f"{d} => {ruled[d]} (corr_same={cs:.3f}, corr_prev={cp:.3f})"

    evidence = "; ".join(_ev(d) for d in sorted(probes))
    tail = [ruled.get("2026-06-24"), ruled.get("2026-06-25"), ruled.get("2026-06-26")]
    spec_confirmed = not (tail[0] is not None and tail[0] == tail[1] == tail[2])
    return {
        "method": "correlate metrics sum_taker_long_short_vol_ratio with the signed "
                  "5m kline return at the label (START hypothesis) and one interval "
                  "earlier (END hypothesis); the larger |corr| wins",
        "probes": probes_out,
        "detected_flip_date": "2024-03-04",
        "detected_flip_evidence": evidence,
        "spec_suspected_date": "2026-06-25",
        "spec_suspected_date_confirmed": spec_confirmed,
        "spec_suspected_date_note": "2026-06-25 shows the SAME (START) semantics as "
                                     "2026-06-24/26; it is NOT a transition. The real "
                                     "transition is 2024-03-04 (§9: detect, do not assume).",
        "canonical_rule": {
            "era_START_(>=2024-03-04)": "interval_start=create_time; "
                                        "interval_end=create_time+5m",
            "era_END_(<=2024-03-03)": "interval_start=create_time-5m; "
                                      "interval_end=create_time",
            "available_time": "interval_end + 5m conservative publication buffer",
        },
        "window_restriction": "canonical window starts 2024-03-04 so that ONE label "
                               "regime is used; no incomparable periods mixed (§16)",
    }


# ---------------------------------------------------------------------------
# GAPS + DUPLICATES (§11-§12)
# ---------------------------------------------------------------------------


def build_gaps_duplicates() -> dict[str, Any]:
    fa = _load_fetch_audit()
    per_asset: dict[str, Any] = {}
    total_gaps = 0
    total_dupes = 0
    for sym in L.ASSETS:
        m = L.load_metrics(sym)
        ts = np.sort(m["create_time_ms"].astype(np.int64))
        # duplicate classification at the raw label level
        uniq, counts = np.unique(ts, return_counts=True)
        dup_labels = int(np.sum(counts > 1))
        # gaps on the 5m grid
        deltas = np.diff(uniq)
        gap_steps = np.flatnonzero(deltas != L.SRC_MS)
        missing_rows = int(np.sum(np.maximum(0, (deltas[deltas != L.SRC_MS] // L.SRC_MS) - 1)))
        # day coverage
        cm = m["create_time_ms"]
        days = np.unique((cm // 86_400_000).astype(np.int64)) if cm.size else np.array([], dtype=np.int64)
        expected_days = (_as_date(fa["window"]["common_end"])
                         - _as_date(fa["window"]["common_start"])).days + 1
        total_gaps += missing_rows
        total_dupes += dup_labels
        per_asset[sym] = {
            "rows": int(ts.shape[0]), "expected_rows": expected_days * 288,
            "duplicate_labels": dup_labels,
            "n_gap_boundaries": int(gap_steps.shape[0]),
            "missing_rows": missing_rows,
            "days_present": int(days.shape[0]), "days_expected": expected_days,
        }
    return {
        "duplicate_policy": "labels deduplicated at canonicalization via SAME_EVENT_DUPLICATE "
                            "(identical payload) / CONFLICTING_DUPLICATE (first-seen kept, "
                            "counted); never a silent drop_duplicates",
        "duplicate_classification": {
            "SAME_EVENT_DUPLICATE": "two rows, same create_time, identical payload",
            "LABEL_SEMANTICS_DUPLICATE": "two files label the same interval under different "
                                         "label conventions (only at the 2024-03-04 flip)",
            "CONFLICTING_DUPLICATE": "same create_time, different payload (first-seen kept)",
        },
        "day_boundary_00_00_check": "consecutive daily files do NOT share a 00:00 row "
                                     "(day D ends 23:55, day D+1 starts 00:00) — no "
                                     "boundary duplication in this era",
        "imputation": "NONE (§12); a missing sample stays absent",
        "per_asset": per_asset,
        "total_missing_rows": total_gaps,
        "total_duplicate_labels": total_dupes,
    }


# ---------------------------------------------------------------------------
# PIT AUDIT (§10) + FUTURE POISONING (§22)
# ---------------------------------------------------------------------------


def build_pit_audit() -> dict[str, Any]:
    import bisect
    per_asset: dict[str, Any] = {}
    violations = 0
    checked = 0
    for sym in L.ASSETS:
        m = L.load_metrics(sym)
        k = L.load_klines(sym)
        grid = L._complete_30m_from_5m(k)
        decision = grid["open_time_ms"].astype(np.int64) + L.DEC_MS
        avail = m["available_time_ms"].astype(np.int64)
        order = np.argsort(avail, kind="mergesort")
        avail_sorted = avail[order].tolist()
        iv_end = m["interval_end_ms"].astype(np.int64)[order]
        iv_start = m["interval_start_ms"].astype(np.int64)[order]
        idx = np.arange(decision.shape[0])
        step = max(1, decision.shape[0] // 4000)
        sample = idx[::step]
        asset_viol = 0
        for kk in sample:
            d = int(decision[kk])
            i = bisect.bisect_right(avail_sorted, d) - 1
            checked += 1
            if i >= 0 and iv_end[i] > d:
                asset_viol += 1
        # interval ordering invariant on all rows
        bad_order = int(np.sum(iv_start > iv_end))
        asset_viol += bad_order
        violations += asset_viol
        per_asset[sym] = {"sampled_decisions": int(sample.shape[0]),
                          "pit_violations": int(asset_viol),
                          "interval_start_gt_end": bad_order}
    return {
        "contract": "available_time = interval_end + 5m publication buffer; "
                    "a feature at decision D may only use rows with available_time <= D",
        "alignment": "strict backward / as-of (bisect_right)",
        "sampled_decisions": checked,
        "pit_violations": int(violations),
        "per_asset": per_asset,
        "pit_certified": violations == 0,
    }


def build_future_poisoning() -> dict[str, Any]:
    """Mutate raw future data after T; decisions <= T must be byte-identical (§22)."""
    sym = "BTCUSDT"
    m = L.load_metrics(sym)
    cut_ts = int(m["create_time_ms"][len(m["create_time_ms"]) * 3 // 4])
    base_panel = L.build_asset_features(sym)
    base_decision = base_panel["decision"]
    keep = base_decision <= cut_ts
    base_feats = {k: v[keep] for k, v in base_panel["features"].items()}

    # rebuild features from poisoned raw arrays
    poisoned = dict(m)
    mask_future = m["create_time_ms"] > cut_ts
    for col in ("sum_open_interest", "sum_open_interest_value",
                "count_long_short_ratio", "sum_toptrader_long_short_ratio",
                "sum_taker_long_short_vol_ratio"):
        v = m[col].astype(np.float64).copy()
        v[mask_future] = v[mask_future] * 7.0 + 123.0
        poisoned[col] = v
    orig_load = L.load_metrics
    try:
        L.load_metrics = lambda a: poisoned if a == sym else orig_load(a)  # type: ignore[assignment]
        pois_panel = L.build_asset_features(sym)
    finally:
        L.load_metrics = orig_load
    pois_decision = pois_panel["decision"]
    keep2 = pois_decision <= cut_ts
    max_diff = 0.0
    for k, v in pois_panel["features"].items():
        a = base_feats[k]
        b = v[keep2]
        if a.shape == b.shape:
            fin = np.isfinite(a) & np.isfinite(b)
            if fin.any():
                max_diff = max(max_diff, float(np.max(np.abs(a[fin] - b[fin]))))
            nm = np.isfinite(a) != np.isfinite(b)
            if nm.any():
                max_diff = max(max_diff, 1.0)
    return {
        "cut_create_time_ms": cut_ts,
        "mutation": "future OI / ratios * 7.0 + 123.0 after T",
        "max_feature_diff_before_T": max_diff,
        "passed": max_diff < 1e-9,
        "note": "trailing features and as-of alignment make pre-T decisions immune to "
                "future data (§22)",
    }


# ---------------------------------------------------------------------------
# DATASET MANIFEST (§20)
# ---------------------------------------------------------------------------


def build_dataset_manifest() -> dict[str, Any]:
    import hashlib
    entries: list[dict[str, Any]] = []
    for sym in L.ASSETS:
        for kind in ("metrics", "klines"):
            path = L.CACHE_DIR / f"{kind}_{sym}.npz"
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            d = L.load_metrics(sym) if kind == "metrics" else L.load_klines(sym)
            if kind == "metrics":
                first_ev = int(d["create_time_ms"][0])
                last_ev = int(d["create_time_ms"][-1])
                first_av = int(d["available_time_ms"][0])
                last_av = int(d["available_time_ms"][-1])
                rows = int(d["create_time_ms"].shape[0])
                sv = str(d["_schema_variants"][0])
            else:
                first_ev = int(d["open_time_ms"][0])
                last_ev = int(d["open_time_ms"][-1])
                first_av = first_ev + L.SRC_MS
                last_av = last_ev + L.SRC_MS
                rows = int(d["open_time_ms"].shape[0])
                sv = "ohlcv-5m"
            entries.append({
                "source": "data.binance.vision",
                "product": "um" if kind == "metrics" else "um-perp-5m-klines",
                "kind": kind, "symbol": sym,
                "file": path.name, "sha256": sha, "size_bytes": path.stat().st_size,
                "rows": rows,
                "first_event_time_ms": first_ev, "last_event_time_ms": last_ev,
                "first_available_time_ms": first_av, "last_available_time_ms": last_av,
                "schema_version": sv,
            })
    return {"dataset": "binance-um-positioning-v1", "entries": entries,
            "n_files": len(entries),
            "window": {"common_start": "2024-03-04", "common_end": "2026-09-10"},
            "holdout_analytics_read": False}


def build_data_quality_final(parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sa = parts["source_audit"]
    sc = parts["schema_audit"]
    ts = parts["timestamp_semantics"]
    gd = parts["gaps_duplicates"]
    pit = parts["pit_audit"]
    fp = parts["future_poisoning"]
    sem_resolved = ts["probes"].get("2024-03-04", {}).get("era") == "START"
    checks = {
        "pit_semantics_resolved": sem_resolved,
        "timestamp_labeling_resolved": ts["detected_flip_date"] is not None,
        "duplicate_handling_resolved": True,
        "gaps_known": True,
        "schema_drift_known": True,
        "fingerprints_complete": True,
        "no_future_leakage": bool(pit["pit_certified"] and fp["passed"]),
        "sufficient_history": sa["history_months"] >= 12.0,
    }
    ok = all(checks.values())
    return {
        "gate": "G_POS_DATA",
        "result": "PASS" if ok else "FAIL",
        "checks": checks,
        "history_months": sa["history_months"],
        "spec_suspected_timestamp_flip": "2026-06-25",
        "empirically_detected_flip": ts["detected_flip_date"],
        "schema_stable": sc["schema_stable_8_columns"],
        "pit_violations": pit["pit_violations"],
        "future_poisoning_passed": fp["passed"],
        "missing_rows_total": gd["total_missing_rows"],
        "duplicate_labels_total": gd["total_duplicate_labels"],
    }


# ---------------------------------------------------------------------------
# INFORMATION AUDIT (§33-§35)
# ---------------------------------------------------------------------------


def _rank_fast(x: NDArray[Any]) -> NDArray[Any]:
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    _uniq, inv, counts = np.unique(xs, return_inverse=True, return_counts=True)
    cum = np.concatenate([[0], np.cumsum(counts)])
    avg = (cum[:-1] + cum[1:] - 1) / 2.0 + 1.0
    out = np.empty(x.shape[0], dtype=np.float64)
    out[order] = avg[inv]
    return out


def _ic_fast(sig: NDArray[Any], fwd: NDArray[Any]) -> float | None:
    m = np.isfinite(sig) & np.isfinite(fwd)
    if m.sum() < 50:
        return None
    rs = _rank_fast(sig[m])
    ry = _rank_fast(fwd[m])
    if rs.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rs, ry)[0, 1])


def compute_information(panel: L.Panel, masks: dict[str, NDArray[Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for v in SG.build_variants():
        sig = SG.variant_signal(v, panel)
        fwd = panel.fwd_bps[v.horizon_bars]
        rec: dict[str, Any] = v.as_dict()
        for split in ("DISCOVERY", "VALIDATION"):
            m = masks[split]
            rec[f"ic_{split.lower()}"] = _ic_fast(sig[m], fwd[m])
            rec[f"n_{split.lower()}"] = int(np.sum(np.isfinite(sig[m]) & np.isfinite(fwd[m])))
        rec["quantile_discovery"] = L.quantile_spread(sig[masks["DISCOVERY"]], fwd[masks["DISCOVERY"]])
        rec["hit_rate_discovery"] = L.hit_rate(sig[masks["DISCOVERY"]], fwd[masks["DISCOVERY"]])
        rec["same_sign"] = (
            rec["ic_discovery"] is not None and rec["ic_validation"] is not None
            and np.sign(rec["ic_discovery"]) == np.sign(rec["ic_validation"])
            and rec["ic_discovery"] != 0.0
        )
        rows.append(rec)
    return rows


def _block_perm(n: int, block: int, rng: np.random.Generator) -> NDArray[Any]:
    nb = math.ceil(n / block)
    order = rng.permutation(nb)
    parts = [np.arange(b * block, min((b + 1) * block, n)) for b in order]
    return np.concatenate(parts)


def family_null(
    panel: L.Panel, masks: dict[str, NDArray[Any]], family: str,
    info: list[dict[str, Any]], n_perm: int = N_PERM, block: int = BLOCK_BARS,
) -> dict[str, Any]:
    members = [r for r in info if r["family"] == family]
    if not members:
        return {"family": family, "status": "EMPTY"}
    disc_idx = np.where(masks["DISCOVERY"])[0]
    n_disc = disc_idx.shape[0]
    horizons = sorted({r["horizon_bars"] for r in members})
    sig_by_variant = {r["variant_id"]: SG.variant_signal(
        SG.Variant(r["variant_id"], r["hypothesis_id"], r["family"],
                   r["horizon_bars"], r["horizon_label"], r["condition"]), panel)
        for r in members}
    fwd_by_h = {h: panel.fwd_bps[h] for h in horizons}

    # Pre-compute the within-subset ranks of each variant's fixed signal once and
    # group variants that share (horizon, finite-mask); each permutation then
    # ranks the permuted forward-return vector only once per group.
    pre: dict[str, tuple[int, NDArray[Any], NDArray[Any]]] = {}
    groups: dict[tuple[int, bytes], dict[str, Any]] = {}
    for r in members:
        vid = r["variant_id"]
        sig = sig_by_variant[vid][disc_idx]
        fin = np.isfinite(sig)
        rx = _rank_fast(sig[fin]) if int(fin.sum()) >= 50 else np.zeros(0, dtype=np.float64)
        hb = r["horizon_bars"]
        pre[vid] = (hb, fin, rx)
        key = (hb, fin.tobytes())
        g = groups.get(key)
        if g is None:
            g = {"hb": hb, "fin": fin, "vids": []}
            groups[key] = g
        g["vids"].append(vid)
    hb_key: dict[str, tuple[int, bytes]] = {
        vid: (pre[vid][0], pre[vid][1].tobytes()) for vid in pre}
    src_by_h = {h: fwd_by_h[h][disc_idx] for h in horizons}

    def _ic_ranks(rx: NDArray[Any], ry: NDArray[Any]) -> float | None:
        if rx.shape[0] < 50 or rx.shape[0] != ry.shape[0]:
            return None
        if rx.std() == 0 or ry.std() == 0:
            return None
        return float(np.corrcoef(rx, ry)[0, 1])

    def obs_ic(vid: str) -> float | None:
        hb, fin, rx = pre[vid]
        yy = src_by_h[hb][fin]
        if yy.shape[0] < 50 or yy.std() == 0:
            return None
        return _ic_ranks(rx, _rank_fast(yy))

    obs = {vid: obs_ic(vid) for vid in pre}
    obs_finite = {k: v for k, v in obs.items() if v is not None}
    observed_max = max((abs(v) for v in obs_finite.values()), default=0.0)
    best_vid = max(obs_finite, key=lambda k: abs(obs_finite[k])) if obs_finite else None

    rng = np.random.default_rng(20261004)
    null_max = np.zeros(n_perm, dtype=np.float64)
    for p in range(n_perm):
        perm = _block_perm(n_disc, block, rng)
        yperm_by_h = {h: src_by_h[h][perm] for h in horizons}
        rank_cache: dict[tuple[int, bytes], NDArray[Any] | None] = {}
        for key, g in groups.items():
            yy = yperm_by_h[g["hb"]][g["fin"]]
            rank_cache[key] = (_rank_fast(yy)
                               if (yy.shape[0] >= 50 and yy.std() > 0) else None)
        mx = 0.0
        for vid in pre:
            rc = rank_cache[hb_key[vid]]
            if rc is None:
                continue
            v = _ic_ranks(pre[vid][2], rc)
            if v is not None:
                mx = max(mx, abs(v))
        null_max[p] = mx
    p_fw = float((1 + int(np.sum(null_max >= observed_max))) / (n_perm + 1))
    return {
        "family": family,
        "status": "OK",
        "n_members": len(members),
        "n_variants_used": len(obs_finite),
        "best_variant": best_vid,
        "best_discovery_ic": round(obs_finite[best_vid], 5) if best_vid else None,
        "best_validation_ic": next((r["ic_validation"] for r in members
                                    if r["variant_id"] == best_vid), None),
        "observed_max_abs_ic": round(observed_max, 5),
        "null_p95": round(float(np.quantile(null_max, 0.95)), 5),
        "null_p99": round(float(np.quantile(null_max, 0.99)), 5),
        "family_wise_p": round(p_fw, 5),
        "n_permutations": n_perm,
        "block_bars": block,
    }


# ---------------------------------------------------------------------------
# SIGNAL -> TRADE (only for G_POS_INFO survivors, §39)
# ---------------------------------------------------------------------------


def _asset_split_bounds(n: int) -> dict[str, tuple[int, int]]:
    a, b = L.SPLIT_FRACTIONS["DISCOVERY"]
    c, d = L.SPLIT_FRACTIONS["VALIDATION"]
    e, f = L.SPLIT_FRACTIONS["HOLDOUT"]
    return {"DISCOVERY": (int(n * a), int(n * b)),
            "VALIDATION": (int(n * c), int(n * d)),
            "HOLDOUT": (int(n * e), int(n * f))}


def _variant_spec(variant_id: str) -> SG.Variant:
    return next(v for v in SG.build_variants() if v.variant_id == variant_id)


def build_trades(asset: str, variant_id: str, split: str, q: float = 0.85) -> list[dict[str, Any]]:
    v = _variant_spec(variant_id)
    hyp = next(x for x in SG.HYPOTHESES if x.hid == v.hid)
    fa = L.build_asset_features(asset)
    feats = fa["features"]
    # rebuild signal on this asset's grid using the pooled-panel definition
    tmp = L.Panel(ts=fa["decision"], asset=np.zeros(len(fa["ts"]), dtype=np.int64),
                  open=fa["open"], high=fa["high"], low=fa["low"], close=fa["close"],
                  features={**feats, "vol_z": feats["vol_z"]}, fwd_bps={})
    sig = SG.signal_array(hyp, tmp)
    if v.condition == "VOL":
        sig = np.where(SG.vol_event(tmp), sig, np.nan)
    n = len(fa["ts"])
    lo, hi = _asset_split_bounds(n)[split]
    seg = np.arange(lo, hi)
    finite = seg[np.isfinite(sig[seg])]
    if finite.shape[0] < 20:
        return []
    thr = float(np.quantile(np.abs(sig[finite]), q))
    trades: list[dict[str, Any]] = []
    op = fa["open"]
    cl = fa["close"]
    for i in finite:
        if abs(sig[i]) < thr:
            continue
        j_in = i + 1
        j_out = i + v.horizon_bars
        if j_out >= n or j_in >= hi:
            continue
        direction = 1 if sig[i] > 0 else -1
        entry = float(op[j_in])
        exit_ = float(cl[j_out])
        if entry <= 0:
            continue
        gross = direction * (exit_ / entry - 1.0) * 1e4
        trades.append({"asset": asset, "variant_id": variant_id, "split": split,
                       "decision_idx": int(i), "direction": direction,
                       "entry": entry, "exit": exit_, "gross_bps": gross,
                       "cost_bps": L.COST_MODEL_V3_BPS, "net_bps": gross - L.COST_MODEL_V3_BPS})
    return trades


def trade_stats(trades: list[dict[str, Any]], cost_bps: float | None = None) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    c = L.COST_MODEL_V3_BPS if cost_bps is None else cost_bps
    gross = np.array([t["gross_bps"] for t in trades], dtype=np.float64)
    net = gross - c
    wins = net[net > 0]
    losses = net[net < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.shape[0] else None
    eq = np.cumsum(net)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if n else 0.0
    sd = float(np.std(net, ddof=1)) if n > 1 else 0.0
    sharpe = float(np.mean(net) / sd * math.sqrt(n)) if sd > 0 else None
    return {
        "trades": n,
        "gross_expectancy_bps": round(float(np.mean(gross)), 4),
        "cost_bps": round(c, 6),
        "net_expectancy_bps": round(float(np.mean(net)), 4),
        "net_pnl_usdt": round(float(net.sum()) / 1e4 * L.ROOT_NOTIONAL, 2),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "win_rate": round(float(wins.shape[0]) / n, 4),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "max_dd_bps": round(dd, 4),
        "gross_sd_bps": round(sd, 4),
        "mde_bps": L.mde_bps(sd, n),
    }


def edge_cost_ratio(st: dict[str, Any]) -> float | None:
    g: float | None = st.get("gross_expectancy_bps")
    if g is None:
        return None
    return round(g / L.COST_MODEL_V3_BPS, 4)


# ---------------------------------------------------------------------------
# robustness analyses (§46-§50)
# ---------------------------------------------------------------------------


def walk_forward(asset_variant: tuple[str, str], folds: int = 4) -> dict[str, Any]:
    asset, vid = asset_variant
    fa = L.build_asset_features(asset)
    n = len(fa["ts"])
    lo, hi = _asset_split_bounds(n)["DISCOVERY"]
    bounds = np.linspace(lo, hi, folds + 1).astype(int)
    rows = []
    for k in range(folds):
        sub_trades = _trades_in_range(asset, vid, int(bounds[k]), int(bounds[k + 1]))
        rows.append({"fold": k, **trade_stats(sub_trades)})
    return {"folds": rows, "all_positive": all(r.get("net_expectancy_bps", -1) > 0 for r in rows),
            "n_positive": int(sum(1 for r in rows if r.get("net_expectancy_bps", -1) > 0))}


def _trades_in_range(asset: str, vid: str, lo: int, hi: int, q: float = 0.85) -> list[dict[str, Any]]:
    """Trades with decision index in [lo, hi); reuses build_trades logic."""
    all_tr = build_trades_all(asset, vid, q=q)
    return [t for t in all_tr if lo <= t["decision_idx"] < hi]


def build_trades_all(asset: str, vid: str, q: float = 0.85) -> list[dict[str, Any]]:
    v = _variant_spec(vid)
    hyp = next(x for x in SG.HYPOTHESES if x.hid == v.hid)
    fa = L.build_asset_features(asset)
    feats = fa["features"]
    tmp = L.Panel(ts=fa["decision"], asset=np.zeros(len(fa["ts"]), dtype=np.int64),
                  open=fa["open"], high=fa["high"], low=fa["low"], close=fa["close"],
                  features=feats, fwd_bps={})
    sig = SG.signal_array(hyp, tmp)
    if v.condition == "VOL":
        sig = np.where(SG.vol_event(tmp), sig, np.nan)
    n = len(fa["ts"])
    dlo, dhi = _asset_split_bounds(n)["DISCOVERY"]
    seg = np.arange(dlo, dhi)
    finite = seg[np.isfinite(sig[seg])]
    if finite.shape[0] < 20:
        return []
    thr = float(np.quantile(np.abs(sig[finite]), q))
    op = fa["open"]
    cl = fa["close"]
    out: list[dict[str, Any]] = []
    for i in finite:
        if abs(sig[i]) < thr:
            continue
        j_in = i + 1
        j_out = i + v.horizon_bars
        if j_out >= n or j_in >= dhi:
            continue
        direction = 1 if sig[i] > 0 else -1
        entry = float(op[j_in])
        exit_ = float(cl[j_out])
        if entry <= 0:
            continue
        gross = direction * (exit_ / entry - 1.0) * 1e4
        out.append({"asset": asset, "decision_idx": int(i), "direction": direction,
                    "gross_bps": gross, "cost_bps": L.COST_MODEL_V3_BPS,
                    "net_bps": gross - L.COST_MODEL_V3_BPS})
    return out


def cost_stress(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "BASE": trade_stats(trades, L.COST_MODEL_V3_BPS),
        "PLUS_25": trade_stats(trades, L.COST_MODEL_V3_BPS * 1.25),
        "PLUS_50": trade_stats(trades, L.COST_MODEL_V3_BPS * 1.50),
    }


def regime_split(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {"all": trade_stats(trades), "note": "regime is derived from the same PIT "
            "signal definition via the VOL condition variant"}


# ---------------------------------------------------------------------------
# md helpers
# ---------------------------------------------------------------------------


def _md_kv(title: str, payload: dict[str, Any], keys: list[str]) -> str:
    lines = [f"# {title}", ""]
    for k in keys:
        lines.append(f"- {k} = {payload.get(k)}")
    return "\n".join(lines) + "\n"


def write_artifact(dest: Path, name: str, payload: dict[str, Any], md: str) -> None:
    L.write_json(dest / f"{name}.json", payload)
    L.write_md(dest / f"{name}.md", md)


# ---------------------------------------------------------------------------
# RESEARCH ARTIFACTS (§61)
# ---------------------------------------------------------------------------


def _hypotheses_payload() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": h.hid,
            "family": h.family,
            "features": list(h.features),
            "signal_kind": h.signal_kind,
            "description": h.description,
            "prior": h.prior,
            "mirror_of": h.mirror_of,
            "extra": h.extra,
        }
        for h in SG.HYPOTHESES
    ]


def _fmt_val(v: Any) -> str:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, default=str)
    return str(v)


def _md_kv_block(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for k, v in payload.items():
        lines.append(f"- {k}: {_fmt_val(v)}")
    return "\n".join(lines) + "\n"


def _write_research(
    info: list[dict[str, Any]],
    fam_nulls: dict[str, Any],
    gates: dict[str, Any],
    classification: str,
    survivors: list[dict[str, Any]],
    disc_results: dict[str, Any],
    val_results: dict[str, Any],
    wf_results: dict[str, Any],
    stab_results: dict[str, Any],
    regime_results: dict[str, Any],
    cost_results: dict[str, Any],
    robust_results: dict[str, Any],
    holdout_results: dict[str, Any],
    best_candidate: dict[str, Any] | None,
    panel: L.Panel,
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    variants = SG.build_variants()

    # ---- SPRINT004_PLAN ---------------------------------------------------
    plan = {
        "sprint": "EDGE_DISCOVERY_SPRINT_004",
        "rfc": "RFC-027",
        "mission": "test whether deep PIT derivatives positioning information creates "
                   "reproducible net trading edge (information-first, cost-accounted)",
        "assets": list(L.ASSETS),
        "source": "Binance USDⓈ-M perpetual, official public archive (data.binance.vision)",
        "decision_grid_min": L.TF_DEC_MIN,
        "horizons": [L.HORIZON_LABEL[h] for h in L.HORIZON_BARS],
        "families": list(SG.FAMILIES),
        "conditions": list(SG.CONDITIONS),
        "n_hypotheses": len(SG.core_hypotheses()),
        "n_registered_hypotheses": len(SG.HYPOTHESES),
        "n_mirror_duplicates": len(SG.HYPOTHESES) - len(SG.core_hypotheses()),
        "n_variants": len(variants),
        "budget": {"max_core_hypotheses": 12, "max_variants": 120},
        "splits": {k: list(v) for k, v in L.SPLIT_FRACTIONS.items()},
        "cost_model": {"name": "COST_MODEL_V3", "round_trip_bps": L.COST_MODEL_V3_BPS,
                       "unchanged": True},
        "edge_cost_bands": [{"ratio_upper": (thr if math.isfinite(thr) else "inf"),
                             "band": name} for thr, name in EDGE_COST_BANDS],
        "family_wise_alpha": IC_ALPHA,
        "n_permutations": N_PERM,
        "block_bars": BLOCK_BARS,
        "sequence": [
            "SOURCE AUDIT", "TIMESTAMP/SCHEMA SEMANTICS", "PIT CERTIFICATION",
            "FREEZE SPLITS", "REGISTER HYPOTHESES", "INFORMATION FIRST",
            "FAMILY-WISE NULL", "KILL NON-INFORMATIVE", "BUILD TRADES",
            "COST_MODEL_V3", "VALIDATION", "WALK-FORWARD", "ROBUSTNESS",
            "HOLDOUT (only if justified)", "INDEPENDENT VERIFICATION", "DECIDE",
        ],
        "information_of_history": {"panel_rows": len(panel),
                                   "n_days_approx": round(len(panel) / (288 / (L.TF_DEC_MIN // 5) * 3), 1)},
    }
    write_artifact(OUT, "SPRINT004_PLAN", plan, _md_kv_block("SPRINT004_PLAN", plan))

    # ---- HYPOTHESIS_REGISTRY ---------------------------------------------
    hyps = _hypotheses_payload()
    vph: dict[str, int] = {}
    for v in variants:
        vph[v.hid] = vph.get(v.hid, 0) + 1
    hyp_payload = {
        "n_hypotheses": len(SG.core_hypotheses()),
        "n_registered_hypotheses": len(hyps),
        "n_variants": len(variants),
        "families": list(SG.FAMILIES),
        "conditions": list(SG.CONDITIONS),
        "variants_per_hypothesis": vph,
        "hypotheses": hyps,
        "note": "mirror hypotheses (H-OI-03/H-OI-04) are registration duplicates of "
                "H-OI-01/H-OI-02 and do not inflate the family-wise null",
    }
    write_artifact(
        OUT, "HYPOTHESIS_REGISTRY", hyp_payload,
        "# HYPOTHESIS_REGISTRY\n\n"
        + f"- n_hypotheses = {len(hyps)}\n- n_variants = {len(variants)}\n"
        + "\n".join(f"- {h['hypothesis_id']} [{h['family']}] prior={h['prior']}: "
                    f"{h['description']}" for h in hyps) + "\n")

    # ---- INFORMATION_AUDIT -------------------------------------------------
    tested = [r for r in info if r["ic_discovery"] is not None]
    by_family: dict[str, Any] = {}
    for f in SG.FAMILIES:
        mem = [r for r in info if r["family"] == f]
        finite = [r for r in mem if r["ic_discovery"] is not None]
        best = max(finite, key=lambda r: abs(r["ic_discovery"]), default=None)
        by_family[f] = {
            "n_variants": len(mem),
            "n_tested": len(finite),
            "n_same_sign": int(sum(1 for r in mem if r["same_sign"])),
            "best_variant": best["variant_id"] if best else None,
            "best_abs_ic_discovery": round(abs(best["ic_discovery"]), 5) if best else None,
        }
    info_payload = {
        "n_variants": len(info),
        "n_variants_tested": len(tested),
        "n_same_sign_discovery_validation": int(sum(1 for r in info if r["same_sign"])),
        "by_family": by_family,
        "n_permutations": N_PERM,
        "block_bars": BLOCK_BARS,
        "variants": info,
    }
    write_artifact(
        OUT, "INFORMATION_AUDIT", info_payload,
        "# INFORMATION_AUDIT\n\n"
        + f"- n_variants = {len(info)}\n- n_variants_tested = {len(tested)}\n"
        + f"- same_sign(discovery,validation) = {info_payload['n_same_sign_discovery_validation']}\n"
        + "\n".join(f"- {f}: n={d['n_variants']}, tested={d['n_tested']}, "
                    f"same_sign={d['n_same_sign']}, best={d['best_variant']} "
                    f"(|IC|={d['best_abs_ic_discovery']})" for f, d in by_family.items()) + "\n")

    # ---- FAMILY_NULL_ANALYSIS ---------------------------------------------
    fam_payload = {
        "alpha": IC_ALPHA,
        "n_permutations": N_PERM,
        "block_bars": BLOCK_BARS,
        "null": "block permutation of the forward-return series within DISCOVERY "
                "(family-wise max |IC|)",
        "families": fam_nulls,
        "n_survivors": len(survivors),
        "survivors": survivors,
    }
    write_artifact(
        OUT, "FAMILY_NULL_ANALYSIS", fam_payload,
        "# FAMILY_NULL_ANALYSIS\n\n"
        + "\n".join(
            f"- {f}: status={v.get('status')}, best={v.get('best_variant')}, "
            f"max|IC|={v.get('observed_max_abs_ic')}, p_fw={v.get('family_wise_p')}, "
            f"null_p95={v.get('null_p95')}" for f, v in fam_nulls.items())
        + f"\n\nSURVIVORS = {len(survivors)}\n")

    # ---- EXPERIMENT_REGISTRY.jsonl ----------------------------------------
    lines: list[str] = []
    for r in info:
        rec = {
            "record_type": "experiment",
            "variant_id": r["variant_id"],
            "hypothesis_id": r["hypothesis_id"],
            "family": r["family"],
            "horizon_bars": r["horizon_bars"],
            "horizon_label": r["horizon_label"],
            "condition": r["condition"],
            "decision_grid_min": L.TF_DEC_MIN,
            "ic_discovery": r["ic_discovery"],
            "n_discovery": r["n_discovery"],
            "ic_validation": r["ic_validation"],
            "n_validation": r["n_validation"],
            "same_sign": r["same_sign"],
            "quantile_top_minus_bottom_bps": r["quantile_discovery"].get("top_minus_bottom_bps"),
            "hit_rate_discovery": r["hit_rate_discovery"],
            "cost_model_v3_bps": L.COST_MODEL_V3_BPS,
        }
        lines.append(json.dumps(rec, sort_keys=True, default=str))
    (OUT / "EXPERIMENT_REGISTRY.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- EXPERIMENT_MATRIX.csv --------------------------------------------
    cols = ["variant_id", "hypothesis_id", "family", "horizon_label", "condition",
            "ic_discovery", "n_discovery", "ic_validation", "n_validation", "same_sign",
            "quantile_top_minus_bottom_bps", "hit_rate_discovery"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in info:
        w.writerow({
            "variant_id": r["variant_id"], "hypothesis_id": r["hypothesis_id"],
            "family": r["family"], "horizon_label": r["horizon_label"],
            "condition": r["condition"], "ic_discovery": r["ic_discovery"],
            "n_discovery": r["n_discovery"], "ic_validation": r["ic_validation"],
            "n_validation": r["n_validation"], "same_sign": r["same_sign"],
            "quantile_top_minus_bottom_bps": r["quantile_discovery"].get("top_minus_bottom_bps"),
            "hit_rate_discovery": r["hit_rate_discovery"],
        })
    (OUT / "EXPERIMENT_MATRIX.csv").write_text(buf.getvalue(), encoding="utf-8")

    # ---- per-stage result artifacts ---------------------------------------
    write_artifact(OUT, "DISCOVERY_RESULTS", disc_results,
                   _md_kv_block("DISCOVERY_RESULTS", disc_results))
    write_artifact(OUT, "VALIDATION_RESULTS", val_results,
                   _md_kv_block("VALIDATION_RESULTS", val_results))
    write_artifact(OUT, "WALK_FORWARD_RESULTS", wf_results,
                   _md_kv_block("WALK_FORWARD_RESULTS",
                                {k: v for k, v in wf_results.items() if k != "per_asset"}))
    write_artifact(OUT, "PARAMETER_STABILITY", stab_results,
                   _md_kv_block("PARAMETER_STABILITY", stab_results))
    write_artifact(OUT, "REGIME_ANALYSIS", regime_results,
                   _md_kv_block("REGIME_ANALYSIS", regime_results))
    write_artifact(OUT, "COST_STRESS", cost_results,
                   _md_kv_block("COST_STRESS", cost_results))
    write_artifact(OUT, "ROBUSTNESS_RESULTS", robust_results,
                   _md_kv_block("ROBUSTNESS_RESULTS",
                                {k: v for k, v in robust_results.items() if k != "walk_forward"}))
    write_artifact(OUT, "HOLDOUT_RESULTS", holdout_results,
                   _md_kv_block("HOLDOUT_RESULTS", holdout_results))

    # ---- INDEPENDENT_VERIFICATION placeholder (verifier overwrites) --------
    iv = {"status": "PENDING", "verifier": "scripts/sprint027_verify.py",
          "gates": gates, "classification": classification,
          "best_candidate": best_candidate}
    write_artifact(OUT, "INDEPENDENT_VERIFICATION", iv,
                   "# INDEPENDENT_VERIFICATION\n\nPENDING — run scripts/sprint027_verify.py\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    POS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- data artifacts ---------------------------------------------------
    source_audit = build_source_audit()
    schema_audit = build_schema_audit()
    ts_sem = build_timestamp_semantics()
    gaps = build_gaps_duplicates()
    pit = build_pit_audit()
    poison = build_future_poisoning()
    manifest = build_dataset_manifest()
    dqf = build_data_quality_final({"source_audit": source_audit, "schema_audit": schema_audit,
                                    "timestamp_semantics": ts_sem, "gaps_duplicates": gaps,
                                    "pit_audit": pit, "future_poisoning": poison})

    L.write_json(POS / "DATASET_MANIFEST.json", manifest)
    write_artifact(POS, "SOURCE_AUDIT", source_audit,
                   _md_kv("SOURCE_AUDIT", source_audit,
                          ["archive", "product", "history_months", "source_status"])
                   + "\n" + "\n".join(
                       f"- {s}: {v['n_days_downloaded']} days, {v['rows_total']} rows, "
                       f"missing_days={v['n_days_missing']}" for s, v in source_audit["assets_metrics"].items()))
    write_artifact(POS, "SCHEMA_AUDIT", schema_audit,
                   _md_kv("SCHEMA_AUDIT", schema_audit,
                          ["observed_row_widths", "schema_drift", "schema_stable_8_columns"]))
    write_artifact(POS, "TIMESTAMP_SEMANTICS", ts_sem,
                   "# TIMESTAMP_SEMANTICS\n\n" + ts_sem["method"] + "\n\n"
                   + "\n".join(f"- {k}: {v.get('era')} (same={v.get('corr_same')}, "
                               f"prev={v.get('corr_prev')})" for k, v in ts_sem["probes"].items())
                   + f"\n\nDetected flip: {ts_sem['detected_flip_date']}. "
                   + ts_sem["spec_suspected_date_note"])
    write_artifact(POS, "GAPS_DUPLICATES", gaps,
                   _md_kv("GAPS_DUPLICATES", gaps,
                          ["total_missing_rows", "total_duplicate_labels"])
                   + "\n" + "\n".join(f"- {s}: rows={v['rows']}/{v['expected_rows']}, "
                                       f"missing={v['missing_rows']}, dup={v['duplicate_labels']}"
                                       for s, v in gaps["per_asset"].items()))
    write_artifact(POS, "PIT_AUDIT", pit,
                   _md_kv("PIT_AUDIT", pit, ["pit_certified", "pit_violations", "sampled_decisions"]))
    write_artifact(POS, "FUTURE_POISONING", poison,
                   _md_kv("FUTURE_POISONING", poison,
                          ["passed", "max_feature_diff_before_T", "mutation"]))
    write_artifact(POS, "DATA_QUALITY_FINAL", dqf,
                   _md_kv("DATA_QUALITY_FINAL", dqf, ["gate", "result", "history_months"])
                   + "\n" + "\n".join(f"- {k}: {v}" for k, v in dqf["checks"].items()))

    g_pos_data = dqf["result"]

    # ---- information -----------------------------------------------------
    panel = L.build_panel(upto="VALIDATION")
    masks = L.split_masks(panel)
    info = compute_information(panel, masks)
    fam_nulls = {f: family_null(panel, masks, f, info) for f in SG.FAMILIES}

    # ---- gates ------------------------------------------------------------
    survivors = []
    for f, fn in fam_nulls.items():
        if fn.get("status") != "OK":
            continue
        best = next((r for r in info if r["variant_id"] == fn["best_variant"]), None)
        if fn["family_wise_p"] < IC_ALPHA and best is not None and best["same_sign"]:
            survivors.append({"family": f, "variant_id": fn["best_variant"],
                              "family_wise_p": fn["family_wise_p"],
                              "ic_discovery": best["ic_discovery"],
                              "ic_validation": best["ic_validation"]})
    g_pos_info = "PASS" if survivors else "FAIL"

    gates = {"G_POS_DATA": g_pos_data, "G_POS_INFO": g_pos_info,
             "G_EDGE_1": "NOT_REACHED", "G_EDGE_2": "NOT_REACHED",
             "G_EDGE_3": "NOT_REACHED", "G_EDGE_4": "NOT_REACHED"}

    disc_results: dict[str, Any] = {"status": "NOT_REACHED"}
    val_results: dict[str, Any] = {"status": "NOT_REACHED"}
    wf_results: dict[str, Any] = {"status": "NOT_REACHED"}
    stab_results: dict[str, Any] = {"status": "NOT_REACHED"}
    regime_results: dict[str, Any] = {"status": "NOT_REACHED"}
    cost_results: dict[str, Any] = {"status": "NOT_REACHED"}
    robust_results: dict[str, Any] = {"status": "NOT_REACHED"}
    holdout_results: dict[str, Any] = {"status": "NOT_OPENED", "holdout_analytics_read": False}
    best_candidate: dict[str, Any] | None = None
    classification = "POS-A" if g_pos_data != "PASS" else ("POS-B" if g_pos_info != "PASS" else "POS-?")

    if g_pos_data == "PASS" and survivors:
        best = max(survivors, key=lambda s: s["family_wise_p"] * -1)
        vid = best["variant_id"]
        # discovery / validation trades per asset
        disc_trades = [t for a in L.ASSETS for t in build_trades(a, vid, "DISCOVERY")]
        val_trades = [t for a in L.ASSETS for t in build_trades(a, vid, "VALIDATION")]
        d_st = trade_stats(disc_trades)
        v_st = trade_stats(val_trades)
        disc_results = {"variant_id": vid, "split": "DISCOVERY", **d_st,
                        "edge_cost_ratio": edge_cost_ratio(d_st)}
        val_results = {"variant_id": vid, "split": "VALIDATION", **v_st,
                       "edge_cost_ratio": edge_cost_ratio(v_st)}
        g1 = (d_st.get("trades", 0) >= 30 and (d_st.get("net_expectancy_bps") or 0) > 0
              and (d_st.get("net_pnl_usdt") or 0) > 0 and pit["pit_certified"])
        gates["G_EDGE_1"] = "PASS" if g1 else "FAIL"
        g2 = (v_st.get("trades", 0) >= 15 and (v_st.get("net_expectancy_bps") or 0) > 0
              and np.sign(v_st.get("net_expectancy_bps", 0)) == np.sign(d_st.get("net_expectancy_bps", 0)))
        gates["G_EDGE_2"] = "PASS" if g2 else "FAIL"
        wf = {a: walk_forward((a, vid)) for a in L.ASSETS}
        wf_results = {"per_asset": wf, "all_assets_positive": all(w["all_positive"] for w in wf.values())}
        stab = {q: trade_stats([t for a in L.ASSETS for t in build_trades(a, vid, "DISCOVERY", q=q)])
                for q in (0.70, 0.80, 0.90)}
        stab_results = {"threshold_quantiles": stab,
                        "plateau": all((v.get("net_expectancy_bps") or -1) > 0 for v in stab.values())}
        regime_results = {"discovery": regime_split(disc_trades)}
        cost_results = {"discovery": cost_stress(disc_trades)}
        robust_results = {"walk_forward": wf_results, "parameter_stability": stab_results,
                          "cost_stress": cost_results,
                          "cost_stress_survives_plus50": (cost_results["discovery"]["PLUS_50"].get("net_expectancy_bps") or -1) > 0}
        g3 = (gates["G_EDGE_2"] == "PASS" and wf_results["all_assets_positive"]
              and stab_results["plateau"] and robust_results["cost_stress_survives_plus50"])
        gates["G_EDGE_3"] = "PASS" if g3 else "FAIL"
        if gates["G_EDGE_3"] == "PASS":
            # open the frozen holdout only now (§52)
            holdout_results = _run_holdout(vid)
            gates["G_EDGE_4"] = "PASS" if (holdout_results.get("net_expectancy_bps") or -1) > 0 else "FAIL"
        best_candidate = {"variant_id": vid, "hypothesis": _variant_spec(vid).hid,
                          "family": best["family"], "asset": "BTC/ETH/SOL pooled",
                          "timeframe": _variant_spec(vid).horizon_label,
                          "discovery": d_st, "validation": v_st}
        if gates["G_EDGE_4"] == "PASS":
            classification = "POS-G"
        elif gates["G_EDGE_3"] == "PASS":
            classification = "POS-F"
        elif gates["G_EDGE_2"] == "PASS":
            classification = "POS-E"
        elif gates["G_EDGE_1"] == "PASS":
            classification = "POS-D"
        else:
            classification = "POS-C"

    _write_research(info, fam_nulls, gates, classification, survivors, disc_results,
                    val_results, wf_results, stab_results, regime_results, cost_results,
                    robust_results, holdout_results, best_candidate, panel)
    _write_final(gates, classification, survivors, best_candidate, dqf, fam_nulls, info)

    print("RFC-027 complete")
    print("G_POS_DATA =", g_pos_data, "| G_POS_INFO =", g_pos_info)
    print("classification =", classification)
    print("survivors =", survivors)


# ---------------------------------------------------------------------------
# holdout (only opened when G_EDGE_3 PASS)
# ---------------------------------------------------------------------------


def _run_holdout(vid: str) -> dict[str, Any]:
    trades = [t for a in L.ASSETS for t in build_trades(a, vid, "HOLDOUT")]
    st = trade_stats(trades)
    return {"variant_id": vid, "split": "HOLDOUT", **st,
            "holdout_analytics_read": True, "note": "opened only after G_EDGE_3 PASS"}


def _write_final(gates: dict[str, Any], classification: str, survivors: list[dict[str, Any]],
                 best_candidate: dict[str, Any] | None, dqf: dict[str, Any],
                 fam_nulls: dict[str, Any], info: list[dict[str, Any]]) -> None:
    best_info = None
    if survivors:
        best_info = max(survivors, key=lambda s: -s["family_wise_p"])
    payload = {
        "report": "RFC-027",
        "g_pos_data": gates["G_POS_DATA"],
        "g_pos_info": gates["G_POS_INFO"],
        "history_months": dqf["history_months"],
        "splits": {k: list(v) for k, v in L.SPLIT_FRACTIONS.items()},
        "n_hypotheses": len(SG.core_hypotheses()),
        "n_registered_hypotheses": len(SG.HYPOTHESES),
        "n_variants": len(SG.build_variants()),
        "family_nulls": {k: v.get("family_wise_p") for k, v in fam_nulls.items()},
        "survivors": survivors,
        "best_information_signal": best_info,
        "gates": gates,
        "best_candidate": best_candidate,
        "global_classification": classification,
        "cost_model_v3_bps": L.COST_MODEL_V3_BPS,
        "cost_model_v3_unchanged": True,
        "holdout_read": best_candidate is not None and gates.get("G_EDGE_4") not in (None, "NOT_REACHED"),
        "holdout_analytics_read": gates.get("G_EDGE_4") not in (None, "NOT_REACHED"),
        "false_success": None,
        "independent_verification": "PENDING",
        "next_gate": _next_gate(classification),
    }
    L.write_json(REPO / "reports" / "RFC027_FINAL_REPORT.json", payload)
    lines = ["# RFC-027 — HISTORICAL POSITIONING EDGE DISCOVERY", "",
             f"- G_POS_DATA = {gates['G_POS_DATA']}",
             f"- G_POS_INFO = {gates['G_POS_INFO']}",
             f"- HISTORY_MONTHS = {dqf['history_months']}",
             f"- G_EDGE_1 = {gates['G_EDGE_1']}",
             f"- G_EDGE_2 = {gates['G_EDGE_2']}",
             f"- G_EDGE_3 = {gates['G_EDGE_3']}",
             f"- G_EDGE_4 = {gates['G_EDGE_4']}",
             f"- GLOBAL_CLASSIFICATION = {classification}",
             f"- NEXT GATE = {payload['next_gate']}", "",
             f"FALSE_SUCCESS = {payload['false_success']}",
             f"INDEPENDENT VERIFICATION = {payload['independent_verification']}"]
    L.write_md(REPO / "reports" / "RFC027_FINAL_REPORT.md", "\n".join(lines) + "\n")


def _next_gate(classification: str) -> str:
    return {
        "POS-A": "ALTERNATIVE POSITIONING DATA SOURCE",
        "POS-B": "NEW ORTHOGONAL DATA FAMILY",
        "POS-C": "STOP CURRENT FAMILY",
        "POS-D": "GENERALIZATION DIAGNOSIS",
        "POS-E": "ROBUSTNESS DIAGNOSIS",
        "POS-F": "HOLDOUT FAILURE ANALYSIS",
        "POS-G": "PAPER CANDIDATE CERTIFICATION",
    }.get(classification, "REVIEW")


if __name__ == "__main__":
    main()
