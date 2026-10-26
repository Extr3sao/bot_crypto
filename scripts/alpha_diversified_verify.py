"""ARP-006 §26-§27 — independent verification pass (BUILDER != VERIFIER).

Read-only reproduction of the load-bearing ARP-006 claims, using deliberately
different code paths from the pipeline where possible:

1. corpus digest recomputed straight from the raw shard bytes (not the manifest);
2. PIT listing time recomputed from each raw shard's first bar;
3. PIT/gate audit: every eligible asset's last bar must be <= the decision time and
   equal to the snapshot feature time, and the excluded set must be disjoint;
4. cost re-derived live from ``CostEngine`` (never hardcoded);
5. an **independent** re-implementation of EXP-ARP-008's daily TS-momentum signal
   that reads raw shards, computed from scratch, compared to RESULTS.json;
6. determinism check (two identical runs);
7. runtime-isolation grep: no runtime module may import the research package;
8. OOS firewall: no ARP-006 driver path reads the OOS_LOCK range.

Writes ``reports/alpha-diversified-v1/tmp/verify.json``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.autonomous.costs import CostEngine  # noqa: E402
from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.diversified import universe as U  # noqa: E402

OUT = REPO / "reports/alpha-diversified-v1"
DATA = OUT / "data"
DAY = 86_400_000


def raw_symbol(symbol: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((DATA / f"{symbol}.json").read_text(encoding="utf-8"))
    return data


def recompute_digest() -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in DATA.glob("*.json") if not p.name.startswith("_")):
        fh = hashlib.sha256(path.read_bytes()).hexdigest()
        h.update(fh.encode())
    return h.hexdigest()


def recompute_listing(symbol: str) -> int:
    return int(raw_symbol(symbol)[0]["ts"])


def independent_exp008(
    symbol: str,
    start: int,
    end: int,
    lookback: int = 30,
    max_hold: int = 20,
    cost_bps: float = 23.559016994374947,
    notional: float = 500.0,
) -> dict[str, Any]:
    """Fresh, from-scratch daily TS-momentum (long if close > close[-lookback])."""
    bars = [b for b in raw_symbol(symbol) if start <= b["ts"] < end]
    n = len(bars)
    trades: list[float] = []
    if n > lookback + 1:
        entry: float | None = None
        entry_i = 0
        pending_entry = False
        pending_due = 0
        pending_exit = False
        for i in range(n):
            close = bars[i]["close"]
            if entry is not None and pending_exit:
                trades.append(bars[i]["open"] / entry - 1.0)
                entry = None
                pending_exit = False
            if entry is None and pending_entry and i >= pending_due:
                entry = bars[i]["open"]
                entry_i = i
                pending_entry = False
            if entry is not None and i - entry_i >= max_hold:
                trades.append(close / entry - 1.0)
                entry = None
                pending_exit = False
            if i >= n - 1:
                break
            long_ok = i >= lookback and close > bars[i - lookback]["close"]
            if entry is None and not pending_entry and long_ok:
                pending_entry = True
                pending_due = i + 1
            elif entry is not None and not pending_exit and not long_ok:
                pending_exit = True
        if entry is not None:
            trades.append(bars[-1]["close"] / entry - 1.0)
    gross_usd = sum(r * notional for r in trades)
    fees = len(trades) * notional * cost_bps / 10_000.0
    return {
        "trades": len(trades),
        "gross_expectancy_bps": round(gross_usd / len(trades) / notional * 10_000.0, 3)
        if trades
        else None,
        "net_expectancy_bps": round((gross_usd - fees) / len(trades) / notional * 10_000.0, 3)
        if trades
        else None,
    }


def main() -> None:
    results = json.loads((OUT / "RESULTS.json").read_text(encoding="utf-8"))
    manifest = D.load_manifest()
    out: dict[str, Any] = {"checks": {}, "verified": True}

    def check(name: str, ok: bool, detail: object) -> None:
        out["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            out["verified"] = False

    # 1. digest
    digest = recompute_digest()
    check(
        "corpus_digest_independent",
        digest == manifest["corpus_digest"],
        {"recomputed": digest, "manifest": manifest["corpus_digest"]},
    )

    # 2. listing recompute
    mismatches = [
        s
        for s in manifest["symbols"]
        if recompute_listing(s) != manifest["symbols"][s]["listing_time"]
    ]
    check("listing_times_independent", not mismatches, {"mismatches": mismatches})

    # 3. PIT / gate audit on real snapshots
    corpus = D.load_corpus([s for s in manifest["symbols"]][:40])
    uverse = U.DynamicAssetUniverse(corpus, D.listing_times(), D.corpus_digest())
    violations = 0
    for T in (1_577_836_800_000, 1_704_067_200_000, 1_735_689_600_000):
        snap = uverse.snapshot(T)
        if set(snap.eligible_assets) & set(snap.excluded_assets):
            violations += 1
        for s in snap.eligible_assets:
            last = max(b.timestamp for b in corpus[s] if b.timestamp <= T)
            if last != snap.feature_time or last > T:
                violations += 1
    check("pit_eligible_last_bar_le_decision_time", violations == 0, {"violations": violations})

    # 4. cost re-derived live
    live_cost = CostEngine().evaluate(size_usd=500.0, horizon_minutes=30.0).round_trip_bps
    check(
        "cost_matches_live_engine",
        abs(float(live_cost) - results["cost_bps_rt"]) < 1e-9,
        {"live": float(live_cost), "results": results["cost_bps_rt"]},
    )

    # 5. independent EXP-ARP-008 re-derivation (same splits as the pipeline)
    dev_start, dev_end = D.SPLIT_RANGES["DEV"]
    val_start, val_end = D.SPLIT_RANGES["VALIDATION"]
    ind_dev = [independent_exp008(s, dev_start, dev_end) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    ind_val = [independent_exp008(s, val_start, val_end) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    dev_trades = sum(x["trades"] for x in ind_dev)
    dev_gross = sum((x["gross_expectancy_bps"] or 0) * x["trades"] for x in ind_dev) / dev_trades
    reported_dev = results["experiments"]["EXP-ARP-008"]["DEV"]
    check(
        "independent_exp008_dev_trades",
        dev_trades == reported_dev["trades"],
        {"independent": dev_trades, "reported": reported_dev["trades"]},
    )
    check(
        "independent_exp008_dev_gross_close",
        abs(round(dev_gross, 2) - (reported_dev["expectancy_gross_bps"] or 0)) < 1.0,
        {"independent": round(dev_gross, 3), "reported": reported_dev["expectancy_gross_bps"]},
    )
    val_trades = sum(x["trades"] for x in ind_val)
    val_net = (
        sum((x["net_expectancy_bps"] or 0) * x["trades"] for x in ind_val) / val_trades
        if val_trades
        else None
    )
    reported_val = results["experiments"]["EXP-ARP-008"]["VALIDATION"]
    check(
        "independent_exp008_val_net_close",
        val_trades == reported_val["trades"]
        and abs(round(val_net or 0, 1) - (reported_val["expectancy_net_bps"] or 0)) < 1.5,
        {
            "independent_trades": val_trades,
            "reported_trades": reported_val["trades"],
            "independent_net": round(val_net or 0, 3),
            "reported_net": reported_val["expectancy_net_bps"],
        },
    )

    out["independent_exp008"] = {"DEV": ind_dev, "VALIDATION": ind_val}

    # 6. determinism
    from trading_bot.research.diversified import daily as DL

    d3 = {s: D.load_symbol(s, "VALIDATION") for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
    a = DL.simulate_exp008(d3, cost_bps_rt=results["cost_bps_rt"])
    b = DL.simulate_exp008(d3, cost_bps_rt=results["cost_bps_rt"])
    check(
        "determinism_exp008",
        [t.as_dict() for t in a["BTCUSDT"]] == [t.as_dict() for t in b["BTCUSDT"]],
        {"trades": len(a["BTCUSDT"])},
    )

    # 7. runtime isolation
    grep = subprocess.run(
        ["grep", "-rl", "research.diversified", "src/trading_bot"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    offenders = [line for line in grep.stdout.splitlines() if "/diversified/" not in line and line]
    check("no_runtime_imports_research_diversified", not offenders, {"offenders": offenders})

    # 8. OOS firewall: driver never loads the OOS_LOCK split
    driver = (REPO / "scripts/alpha_diversified_v1.py").read_text(encoding="utf-8")
    loads_oos = '"OOS_LOCK"' in driver or "'OOS_LOCK'" in driver
    uses_dev_val = "DEV_VAL_RANGE" in driver
    check(
        "oos_not_read_by_driver",
        (not loads_oos) and uses_dev_val,
        {"loads_oos_split": loads_oos, "uses_dev_val_range": uses_dev_val},
    )

    (OUT / "tmp").mkdir(exist_ok=True)
    (OUT / "tmp/verify.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(out["checks"], indent=2))
    print("VERIFIED" if out["verified"] else "FAILED")


if __name__ == "__main__":
    main()
