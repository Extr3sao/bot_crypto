"""RFC-025 Part A — orthogonal data inventory, manifest, PIT audit, poisoning.

Read-only. Consumes repository data (``reports/microstructure-v1/data``) and
produces, under ``reports/orthogonal-data``:

    ORTHOGONAL_DATA_INVENTORY.md / .json
    DATASET_MANIFEST.json
    PIT_AUDIT.md / .json
    FUTURE_POISONING.md / .json

No network, no credentials, no holdout access.
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
from numpy.typing import NDArray

sys.path.insert(0, "scripts")
import sprint025_lib as OL

PROVIDER = "Binance USD-M / Spot (public REST)"
OUT = OL.ORTHO_OUT


# ---------------------------------------------------------------------------
# MANIFEST + integrity
# ---------------------------------------------------------------------------


def _integrity(times: NDArray[Any], expected_ms: int | None) -> dict[str, Any]:
    t = np.asarray(times, dtype=np.int64)
    dupes = int(t.shape[0] - np.unique(t).shape[0])
    ordered = bool(np.all(np.diff(t) > 0))
    gaps = 0
    worst = 0
    if expected_ms is not None and t.shape[0] > 1:
        d = np.diff(t)
        over = d[d > expected_ms]
        gaps = int(over.shape[0])
        worst = int(over.max()) if over.shape[0] else 0
    return {
        "rows": int(t.shape[0]),
        "duplicates": dupes,
        "strictly_ordered": ordered,
        "gaps": gaps,
        "worst_gap_ms": worst,
    }


def manifest() -> dict[str, Any]:
    files = [
        ("FUNDING_BTCUSDT.json", "BTCUSDT", "funding"),
        ("FUNDING_ETHUSDT.json", "ETHUSDT", "funding"),
        ("FUNDING_SOLUSDT.json", "SOLUSDT", "funding"),
        ("PREMIUM_BTCUSDT_5m.json", "BTCUSDT", "premium_index_5m"),
        ("PREMIUM_ETHUSDT_5m.json", "ETHUSDT", "premium_index_5m"),
        ("PREMIUM_SOLUSDT_5m.json", "SOLUSDT", "premium_index_5m"),
        ("KLINES_BTCUSDT_5m.json", "BTCUSDT", "spot_klines_5m"),
        ("KLINES_ETHUSDT_5m.json", "ETHUSDT", "spot_klines_5m"),
        ("KLINES_SOLUSDT_5m.json", "SOLUSDT", "spot_klines_5m"),
        ("OPENINTEREST_BTCUSDT.json", "BTCUSDT", "open_interest_5m"),
        ("OPENINTEREST_ETHUSDT.json", "ETHUSDT", "open_interest_5m"),
        ("OPENINTEREST_SOLUSDT.json", "SOLUSDT", "open_interest_5m"),
        ("BASIS_BTCUSDT.json", "BTCUSDT", "basis"),
        ("BASIS_ETHUSDT.json", "ETHUSDT", "basis"),
        ("BASIS_SOLUSDT.json", "SOLUSDT", "basis"),
    ]
    out: dict[str, Any] = {
        "provider": PROVIDER,
        "source_dir": str(OL.MICRO_DIR.relative_to(OL.REPO)),
        "files": {},
    }
    for name, asset, metric in files:
        path = OL.MICRO_DIR / name
        if not path.exists():
            out["files"][name] = {"status": "ABSENT"}
            continue
        payload = OL._load(name)
        rows = len(payload)
        if metric == "funding":
            first = int(payload[0]["fundingTime"]) if rows else None
            last = int(payload[-1]["fundingTime"]) if rows else None
        elif metric == "premium_index_5m" or metric == "spot_klines_5m":
            first = int(payload[0][0]) if rows else None
            last = int(payload[-1][0]) if rows else None
        elif metric == "open_interest_5m":
            first = int(payload[0]["timestamp"]) if rows else None
            last = int(payload[-1]["timestamp"]) if rows else None
        else:
            first = int(payload[0]["timestamp"]) if rows else None
            last = int(payload[-1]["timestamp"]) if rows else None
        out["files"][name] = {
            "asset": asset,
            "metric": metric,
            "rows": rows,
            "bytes": path.stat().st_size,
            "sha256": OL.sha256_file(path),
            "first_timestamp": first,
            "last_timestamp": last,
        }
    return out


# ---------------------------------------------------------------------------
# INVENTORY
# ---------------------------------------------------------------------------

INVENTORY: list[dict[str, Any]] = [
    {
        "data_id": "ORTHO-FUNDING",
        "metric": "funding_rate (perp, 8h)",
        "provider": "Binance USD-M /fapi/v1/fundingRate",
        "assets": list(OL.ASSETS),
        "start_time": "2026-03-01T00:00Z",
        "end_time": "2026-09-24T00:00Z",
        "frequency": "8h (median spacing 28800000 ms)",
        "timestamp_semantics": "fundingTime = funding PAYMENT time; the rate is known by then",
        "publication_semantics": "available_at = fundingTime (paid/realised rate)",
        "historical_depth": "full (624 points/asset, 2026-03-01..2026-09-24)",
        "pit_status": "AVAILABLE_PIT",
        "completeness": "10 expected points/week, regular cadence",
        "runtime_status": "research-only, read-only REST",
        "source_url": "https://fapi.binance.com/fapi/v1/fundingRate",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "AVAILABLE_PIT",
        "repo_file": "reports/microstructure-v1/data/FUNDING_<ASSET>.json",
    },
    {
        "data_id": "ORTHO-BASIS",
        "metric": "spot-perp basis proxy: premium index (mark-index)/index",
        "provider": "Binance USD-M /fapi/v1/premiumIndexKlines",
        "assets": list(OL.ASSETS),
        "start_time": "2026-03-01T00:00Z",
        "end_time": "2026-09-24T23:55Z",
        "frequency": "5m",
        "timestamp_semantics": "kline open time; close = 4th field of premium index",
        "publication_semantics": "available_at = close_time + 1 ms",
        "historical_depth": "full (59905 bars/asset)",
        "pit_status": "AVAILABLE_PIT",
        "completeness": "0 gaps on 5m grid",
        "runtime_status": "research-only, read-only REST",
        "source_url": "https://fapi.binance.com/fapi/v1/premiumIndexKlines",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "AVAILABLE_PIT",
        "repo_file": "reports/microstructure-v1/data/PREMIUM_<ASSET>_5m.json",
    },
    {
        "data_id": "ORTHO-TAKERFLOW",
        "metric": "taker buy/sell flow imbalance (spot aggTrade aggressor flow)",
        "provider": "Binance Spot /api/v3/klines (taker buy base volume)",
        "assets": list(OL.ASSETS),
        "start_time": "2026-03-01T00:00Z",
        "end_time": "2026-09-24T23:55Z",
        "frequency": "5m",
        "timestamp_semantics": "kline open time",
        "publication_semantics": "available_at = close_time + 1 ms",
        "historical_depth": "full (59905 bars/asset)",
        "pit_status": "AVAILABLE_PIT",
        "completeness": "0 gaps; flow_imbalance=(2*taker_buy-vol)/vol",
        "runtime_status": "research-only, read-only REST",
        "source_url": "https://api.binance.com/api/v3/klines",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "AVAILABLE_PIT",
        "repo_file": "reports/microstructure-v1/data/KLINES_<ASSET>_5m.json",
    },
    {
        "data_id": "ORTHO-OI",
        "metric": "open interest (sumOpenInterest, contract count)",
        "provider": "Binance USD-M /futures/data/openInterestHist",
        "assets": list(OL.ASSETS),
        "start_time": "2026-09-05T00:00Z",
        "end_time": "2026-10-03 (rolling 30d)",
        "frequency": "5m",
        "timestamp_semantics": "timestamp = sample time",
        "publication_semantics": "available_at = timestamp + period",
        "historical_depth": "INSUFFICIENT: only latest 30 days retained by the endpoint",
        "pit_status": "AVAILABLE_NEEDS_AUDIT but depth insufficient",
        "completeness": "covers HOLDOUT W7 + forward only; absent for DISCOVERY/VALIDATION",
        "runtime_status": "research-only",
        "source_url": "https://fapi.binance.com/futures/data/openInterestHist",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "INSUFFICIENT_HISTORY",
        "repo_file": "reports/microstructure-v1/data/OPENINTEREST_<ASSET>.json",
    },
    {
        "data_id": "ORTHO-BASIS-ENDPOINT",
        "metric": "basis (futuresPrice - indexPrice)",
        "provider": "Binance USD-M /futures/data/basis",
        "assets": list(OL.ASSETS),
        "start_time": None,
        "end_time": "rolling 30d",
        "frequency": "5m..1d",
        "timestamp_semantics": "timestamp",
        "publication_semantics": "available_at = timestamp + period",
        "historical_depth": "INSUFFICIENT: 30d retention; pagination returns the recent window repeated",
        "pit_status": "redundant with ORTHO-BASIS (mark-index)",
        "completeness": "download returned 0 usable rows for the W1-W7 range",
        "runtime_status": "research-only",
        "source_url": "https://fapi.binance.com/futures/data/basis",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "INSUFFICIENT_HISTORY",
        "repo_file": "reports/microstructure-v1/data/BASIS_<ASSET>.json",
    },
    {
        "data_id": "ORTHO-LIQ",
        "metric": "liquidation orders (long/short forced orders)",
        "provider": "Binance USD-M /fapi/v1/allForceOrders",
        "assets": list(OL.ASSETS),
        "start_time": None,
        "end_time": None,
        "frequency": "n/a (event stream)",
        "timestamp_semantics": "n/a — endpoint returns HTTP 404",
        "publication_semantics": "n/a",
        "historical_depth": "none accessible",
        "pit_status": "DATA_BLOCKED",
        "completeness": "probed 2026-10-04: HTTP 404 (no public historical endpoint)",
        "runtime_status": "not testable historically",
        "source_url": "https://fapi.binance.com/fapi/v1/allForceOrders",
        "license_access": "removed/deprecated",
        "cost": "n/a",
        "status": "DATA_BLOCKED",
        "repo_file": None,
    },
    {
        "data_id": "ORTHO-LSRATIO",
        "metric": "long/short account ratio and taker long/short volume ratio",
        "provider": "Binance USD-M /futures/data/globalLongShortAccountRatio, takerlongshortRatio",
        "assets": list(OL.ASSETS),
        "start_time": "2026-09-05 (approx)",
        "end_time": "rolling 30d",
        "frequency": "5m..1d",
        "timestamp_semantics": "timestamp = bucket time",
        "publication_semantics": "available_at = timestamp + period",
        "historical_depth": "INSUFFICIENT: 30d retention only",
        "pit_status": "depth insufficient for DISCOVERY/VALIDATION",
        "completeness": "overlaps HOLDOUT W7/forward only",
        "runtime_status": "research-only",
        "source_url": "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "INSUFFICIENT_HISTORY",
        "repo_file": None,
    },
    {
        "data_id": "ORTHO-ORDERBOOK",
        "metric": "order book imbalance (bookTicker / depth)",
        "provider": "Binance Spot/USD-M live REST + forward collector",
        "assets": list(OL.ASSETS),
        "start_time": "2026-09-28",
        "end_time": "2026-10-01 (forward captures)",
        "frequency": "~1-2 s forward snapshots",
        "timestamp_semantics": "exchange event time of each snapshot",
        "publication_semantics": "available_at = event time",
        "historical_depth": "NO historical endpoint existed; forward-only captures only",
        "pit_status": "FORWARD_ONLY",
        "completeness": "few days of forward captures under reports/microstructure-forward*/",
        "runtime_status": "not testable on W1-W7",
        "source_url": "https://fapi.binance.com/fapi/v1/depth (forward)",
        "license_access": "public, no key, no cost",
        "cost": "free",
        "status": "FORWARD_ONLY",
        "repo_file": "reports/microstructure-forward*/segments/binance/perp/<ASSET>/depth_snapshot/",
    },
    {
        "data_id": "ORTHO-CROSSEX",
        "metric": "cross-exchange spread / lead-lag / basis divergence",
        "provider": "multi-venue",
        "assets": list(OL.ASSETS),
        "start_time": None,
        "end_time": None,
        "frequency": "n/a",
        "timestamp_semantics": "n/a",
        "publication_semantics": "n/a",
        "historical_depth": "no synchronised historical multi-venue panel in repo",
        "pit_status": "DATA_BLOCKED",
        "completeness": "would require new infrastructure (out of §19 scope)",
        "runtime_status": "not attempted",
        "source_url": "multiple",
        "license_access": "n/a",
        "cost": "n/a",
        "status": "NOT_AVAILABLE",
        "repo_file": None,
    },
]


# ---------------------------------------------------------------------------
# PIT AUDIT
# ---------------------------------------------------------------------------


def pit_audit() -> dict[str, Any]:
    out: dict[str, Any] = {"provider": PROVIDER, "sources": {}}
    for asset in OL.ASSETS:
        kl = OL.load_klines(asset)
        p_avail, _ = OL.load_premium(asset)
        f_avail, _ = OL.load_funding(asset)
        oi_avail, _ = OL.load_oi(asset)
        out["sources"][f"{asset}|spot_klines_5m"] = {
            **_integrity(kl["avail"], OL.TF_MS + 1),
            "available_at_rule": "close_time + 1 ms",
            "utc_grid": True,
            "no_imputation": "missing stays NaN",
        }
        out["sources"][f"{asset}|premium_5m"] = {
            **_integrity(p_avail, OL.TF_MS + 1),
            "available_at_rule": "close_time + 1 ms",
            "utc_grid": True,
            "no_imputation": "missing stays NaN",
        }
        out["sources"][f"{asset}|funding_8h"] = {
            **_integrity(f_avail, None),
            "available_at_rule": "fundingTime (payment time)",
            "utc_grid": True,
            "no_imputation": "missing stays NaN",
        }
        out["sources"][f"{asset}|oi_5m"] = {
            **_integrity(oi_avail, OL.TF_MS + 1),
            "available_at_rule": "timestamp + period",
            "utc_grid": True,
            "no_imputation": "missing stays NaN",
        }
    # staleness: funding is only refreshed every 8h -> it is stale by design between payments
    f_avail, _ = OL.load_funding("BTCUSDT")
    d = np.diff(f_avail)
    out["staleness"] = {
        "funding_median_gap_ms": int(np.median(d)),
        "funding_max_gap_ms": int(d.max()),
        "note": "funding is a step function; stale between payments by construction (as-of used)",
    }
    return out


# ---------------------------------------------------------------------------
# FUTURE POISONING (adversarial A/B)
# ---------------------------------------------------------------------------


def future_poisoning() -> dict[str, Any]:
    rng = np.random.default_rng(20261025)
    out: dict[str, Any] = {
        "method": "poison every raw value strictly after T; features <= T must match"
    }
    per_asset: dict[str, Any] = {}
    for asset in OL.ASSETS:
        kl = OL.load_klines(asset)
        p_avail, p_val = OL.load_premium(asset)
        f_avail, f_rate = OL.load_funding(asset)
        n = kl["ts"].shape[0]
        T = int(n * 0.6)
        cut = int(kl["ts"][T]) + OL.TF_MS  # decision time of bar T (close of bar T)

        # A: normal
        fa = OL.features_from_arrays(
            kl["ts"], p_avail, p_val, f_avail, f_rate, kl["vol"], kl["taker_buy"]
        )
        # B: poison every raw sample with available_at > cut (i.e. unknowable at bar T)
        p_val_b = p_val.copy()
        pmask = p_avail > cut
        p_val_b[pmask] = rng.normal(0, 1.0, int(pmask.sum())) * 1e3
        vol_b = kl["vol"].copy()
        tb_b = kl["taker_buy"].copy()
        vol_b[T + 1 :] = rng.normal(0, 1.0, n - (T + 1)) * 1e6
        tb_b[T + 1 :] = 0.0
        f_rate_b = f_rate.copy()
        fmask = f_avail > cut
        f_rate_b[fmask] = rng.normal(0, 1.0, int(fmask.sum())) * 1.0
        fb = OL.features_from_arrays(kl["ts"], p_avail, p_val_b, f_avail, f_rate_b, vol_b, tb_b)

        diffs: dict[str, int] = {}
        maxd = 0.0
        for name in fa:
            a = fa[name][: T + 1]
            b = fb[name][: T + 1]
            finite = np.isfinite(a) | np.isfinite(b)
            if int(finite.sum()) == 0:
                diffs[name] = 0
                continue
            bad = int(
                np.sum(
                    finite & ~np.isclose(np.nan_to_num(a, nan=-1e18), np.nan_to_num(b, nan=-1e18))
                )
            )
            diffs[name] = bad
            va = a[finite]
            vb = b[finite]
            if va.shape[0]:
                maxd = max(maxd, float(np.max(np.abs(va - vb))))
        per_asset[asset] = {
            "T_index": T,
            "decision_time_ms": cut,
            "n_features_compared": int(T + 1),
            "mismatches_per_feature": diffs,
            "max_abs_diff": round(maxd, 10),
            "identical": bool(max(diffs.values()) == 0),
        }
    out["assets"] = per_asset
    out["verdict"] = (
        "NO_LOOKAHEAD" if all(v["identical"] for v in per_asset.values()) else "LOOKAHEAD_DETECTED"
    )
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    man = manifest()
    OL.write_json(OUT / "DATASET_MANIFEST.json", man)
    OL.write_json(
        OUT / "ORTHOGONAL_DATA_INVENTORY.json",
        {
            "provider_primary": PROVIDER,
            "sources": INVENTORY,
            "counts": _counts(),
        },
    )
    pit = pit_audit()
    OL.write_json(OUT / "PIT_AUDIT.json", pit)
    fp = future_poisoning()
    OL.write_json(OUT / "FUTURE_POISONING.json", fp)
    _write_markdowns(man, pit, fp)
    print("inventory sources:", len(INVENTORY))
    print("poisoning verdict:", fp["verdict"])
    print("manifest files:", len(man["files"]))


def _counts() -> dict[str, int]:
    c: dict[str, int] = {}
    for s in INVENTORY:
        c[s["status"]] = c.get(s["status"], 0) + 1
    return c


def _write_markdowns(man: dict[str, Any], pit: dict[str, Any], fp: dict[str, Any]) -> None:
    c = _counts()
    inv_lines = [
        "# ORTHOGONAL_DATA_INVENTORY — RFC-025 Part A",
        "",
        "> Máquina: `ORTHOGONAL_DATA_INVENTORY.json`. Fuentes auditadas en el",
        "> repositorio, los adaptadores y sondeo directo de endpoints públicos",
        f"> (2026-10-04). Estados: {c}.",
        "",
        "| data_id | metric | provider | depth | PIT | status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for s in INVENTORY:
        depth = s["historical_depth"] if isinstance(s["historical_depth"], str) else "-"
        inv_lines.append(
            f"| {s['data_id']} | {s['metric']} | {s['provider']} | {depth} | {s['pit_status']} | **{s['status']}** |"
        )
    inv_lines += [
        "",
        "## Prioridad de fuente (§6)",
        "",
        "1. **Datos ya en el repositorio** — usados: `reports/microstructure-v1/data/`",
        "   (funding/premium/klines completos, ya descargados y verificados).",
        "2. Endpoints oficiales de exchange — sondeados para completar/extender.",
        "3. Archivos oficiales — no necesarios.",
        "4. Proveedor público gratuito — no necesario.",
        "5. Fuente de pago — **no se contrata**; documentada como STOP.",
        "",
        "## Fuentes usables (PIT, cubren W1-W7)",
        "",
        "- **ORTHO-FUNDING** — funding 8h, 624 puntos/activo, histórico completo.",
        "- **ORTHO-BASIS** — premium index 5m (mark-index), 59 905 barras/activo.",
        "- **ORTHO-TAKERFLOW** — taker-buy spot por barra 5m, 59 905 barras/activo.",
        "",
        "## Fuentes no usables (honestas)",
        "",
        "- **ORTHO-OI / ORTHO-LSRATIO / ORTHO-BASIS-ENDPOINT** — retención 30d.",
        "- **ORTHO-LIQ** — endpoint 404 → DATA_BLOCKED.",
        "- **ORTHO-ORDERBOOK** — sin histórico → FORWARD_ONLY.",
        "- **ORTHO-CROSSEX** — sin panel multi-venue → NOT_AVAILABLE.",
        "",
        "No se fabrica ninguna serie (nada de libro desde OHLCV, nada de OI backtesteado).",
        "",
    ]
    OL.write_md(OUT / "ORTHOGONAL_DATA_INVENTORY.md", "\n".join(inv_lines))

    man_lines = [
        "# DATASET_MANIFEST — RFC-025",
        "",
        f"Provider: {man['provider']}. Directorio: `{man['source_dir']}`.",
        "",
        "| file | asset | metric | rows | bytes | sha256 (head) | first | last |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for name, d in man["files"].items():
        if "sha256" not in d:
            continue
        man_lines.append(
            f"| {name} | {d['asset']} | {d['metric']} | {d['rows']} | {d['bytes']} | "
            f"{d['sha256'][:12]}… | {d['first_timestamp']} | {d['last_timestamp']} |"
        )
    OL.write_md(OUT / "DATASET_MANIFEST.md", "\n".join(man_lines) + "\n")

    pit_lines = [
        "# PIT_AUDIT — RFC-025 Part A",
        "",
        "Regla: para decidir en `T` sólo se usan muestras con `available_at <= T`",
        "(join backward/as-of). Sin imputación: faltante = NaN (§21).",
        "",
        "| source | rows | dupes | ordered | gaps | worst_gap_ms | available_at |",
        "| --- | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for key, d in pit["sources"].items():
        pit_lines.append(
            f"| {key} | {d['rows']} | {d['duplicates']} | {d['strictly_ordered']} | {d['gaps']} | "
            f"{d['worst_gap_ms']} | {d['available_at_rule']} |"
        )
    pit_lines += [
        "",
        f"Staleness funding: {pit['staleness']['note']} (median gap {pit['staleness']['funding_median_gap_ms']} ms).",
        "",
    ]
    OL.write_md(OUT / "PIT_AUDIT.md", "\n".join(pit_lines))

    fp_lines = [
        "# FUTURE_POISONING — RFC-025 Part A",
        "",
        f"Método: {fp['method']}.",
        "",
        "| asset | T_index | features compared | mismatches | identical |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for asset, d in fp["assets"].items():
        mm = max(d["mismatches_per_feature"].values())
        fp_lines.append(
            f"| {asset} | {d['T_index']} | {d['n_features_compared']} | {mm} | **{d['identical']}** |"
        )
    fp_lines += ["", f"**Veredicto: {fp['verdict']}**.", ""]
    OL.write_md(OUT / "FUTURE_POISONING.md", "\n".join(fp_lines))


if __name__ == "__main__":
    main()
