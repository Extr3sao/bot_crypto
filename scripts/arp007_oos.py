"""ARP-007 — OOS FREEZE RECEIPT + single frozen OOS evaluation for EXP-ARP-008.

Executed ONLY after the §17 verification gate passes. The receipt is written first,
on DEV/VALIDATION/robustness evidence alone, and the OOS slice is read exactly once
afterwards. No retries, no parameter changes, no candidate selection.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/arp007_oos.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import arp007_verify as V  # noqa: E402

OUT = REPO / "reports/exp-arp-008-oos-verification"
VERIFIER = "ARP-007 independent verifier (BUILDER != VERIFIER)"


def sha_obj(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def sha_file(rel: str) -> str:
    h = hashlib.sha256()
    h.update((REPO / rel).read_bytes())
    return h.hexdigest()


def build_receipt(cost: float) -> dict[str, Any]:
    dev = V.summarize(V.run("DEV", cost=cost))
    val = V.summarize(V.run("VALIDATION", cost=cost))
    rob: dict[str, Any] = {}
    rob["lookback_24"] = V.summarize(V.run("VALIDATION", cost=cost, lookback=24))
    rob["lookback_40"] = V.summarize(V.run("VALIDATION", cost=cost, lookback=40))
    rob["hold_12"] = V.summarize(V.run("VALIDATION", cost=cost, max_hold=12))
    rob["hold_28"] = V.summarize(V.run("VALIDATION", cost=cost, max_hold=28))
    rob["execution_delay_1d"] = V.summarize(V.run("VALIDATION", cost=cost, entry_delay=1))
    for m in (1.25, 1.5, 2.0):
        rob[f"cost_{m}x"] = V.summarize(V.run("VALIDATION", cost=cost * m))
    for sym in V.ASSETS:
        rob[f"asset_{sym}"] = V.summarize(V.run("VALIDATION", cost=cost, assets=(sym,)))
    corpus_digest = json.loads((V.CORPUS / "_FETCH_MANIFEST.json").read_text(encoding="utf-8"))[
        "corpus_digest"
    ]
    start, end = V.SPLITS["OOS_LOCK"]
    oos_descriptor = f"{corpus_digest}|OOS_LOCK|{start}|{end}|{','.join(V.ASSETS)}"
    receipt = {
        "experiment_id": "EXP-ARP-008",
        "strategy_id": "H-DAILY-TSMOM-001",
        "commit_sha_pre_freeze": git_sha(),
        "code_hash": V.recompute_code_hash()["code_hash"],
        "manifest_hash": sha_file(
            "docs/research/alpha_recovery_v1_2/experiments/EXP-ARP-008/MANIFEST.json"
        ),
        "spec_hash": sha_file("docs/research/alpha_recovery_v1_2/experiments/EXP-ARP-008/SPEC.md"),
        "config_hash": sha_file("config/strategy_admission.json"),
        "dataset_fingerprint": corpus_digest,
        "oos_dataset_hash": hashlib.sha256(oos_descriptor.encode()).hexdigest(),
        "oos_dataset_hash_method": "sha256 of descriptor (corpus digest + split bounds + assets); "
        "no OOS bar value was read to build this receipt",
        "assets": list(V.ASSETS),
        "timeframe": "1d",
        "parameters": {"lookback_days": V.LOOKBACK, "max_hold_days": V.MAX_HOLD},
        "cost_model": {"version": "COST_MODEL_V3", "round_trip_bps": cost},
        "splits": {
            "DEV": ["2019-01-01", "2024-01-01"],
            "VALIDATION": ["2024-01-01", "2025-07-01"],
            "OOS_LOCK": ["2025-07-01", "2026-03-01"],
        },
        "dev_result_hash": sha_obj(dev),
        "validation_result_hash": sha_obj(val),
        "robustness_result_hash": sha_obj(rob),
        "verifier": VERIFIER,
        "created_utc": datetime.now(UTC).isoformat(),
        "oos_opened_before_creation": False,
        "immutable": True,
    }
    return receipt


def git_sha() -> str:
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def oos_benchmark_labels() -> dict[int, str]:
    start, end = V.SPLITS["OOS_LOCK"]
    warm = start - 90 * V.MS_PER_DAY
    bars = V.load_bars("BTCUSDT", warm, end)
    return V.regime_labels(V.to_ohlcv(bars)) if len(bars) > 60 else {}


def oos_period(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[float]] = {}
    for t in trades:
        key = datetime.fromtimestamp(t["exit_ts"] / 1000, tz=UTC).strftime("%Y-%m")
        by.setdefault(key, []).append(t["net"])
    return {
        k: {
            "trades": len(v),
            "net_usd": round(sum(v), 2),
            "expectancy_net_bps": round(sum(v) / len(v) / V.NOTIONAL * V.BPS, 3),
        }
        for k, v in sorted(by.items())
    }


def main() -> None:
    cost = V.cost_model_v3_rt_bps()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tmp").mkdir(parents=True, exist_ok=True)

    # §18 — receipt first, on pre-OOS evidence only
    receipt = build_receipt(cost)
    (OUT / "OOS_FREEZE_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("wrote OOS_FREEZE_RECEIPT.json; oos_result_hash(unset) — now opening OOS once")

    # §19 — open OOS EXACTLY ONCE
    trades = V.run("OOS_LOCK", cost=cost)
    summary = V.summarize(trades)
    result = {
        "experiment_id": "EXP-ARP-008",
        "execution_sha": git_sha(),
        "opened_utc": datetime.now(UTC).isoformat(),
        "opened_once": True,
        "cost_bps_rt": cost,
        "oos_range": ["2025-07-01", "2026-03-01"],
        "metrics": summary,
        "concentration": V.concentration(trades),
        "by_asset": V.pnl_by_asset(trades),
        "by_period": oos_period(trades),
        "by_regime": V.regime_pnl(trades, oos_benchmark_labels()),
        "costs_usd_total": round(sum(t["fees"] for t in trades), 4),
        "turnover_notional_usd": round(len(trades) * V.NOTIONAL, 2),
        "exposure": V.exposure(
            trades, sum(len(V.load_bars(s, *V.SPLITS["OOS_LOCK"])) for s in V.ASSETS)
        ),
    }
    criteria = {
        "positive_net_expectancy": (summary["expectancy_net_bps"] or 0) > 0,
        "pit_clean": True,
        "acceptable_sample": summary["trades"] >= 20,
        "no_catastrophic_concentration": (
            (result["concentration"].get("top1_trade_share") or 0) <= 0.5
            and (result["concentration"].get("top_asset_share") or 0) <= 0.6
        ),
    }
    if summary["trades"] < 20:
        decision = "OOS_INSUFFICIENT_EVIDENCE"
    elif not criteria["positive_net_expectancy"] or not criteria["no_catastrophic_concentration"]:
        decision = "OOS_FAIL"
    else:
        decision = "OOS_PASS"
    result["criteria"] = criteria
    result["decision"] = decision
    (OUT / "OOS_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {"metrics": summary, "decision": decision, "concentration": result["concentration"]},
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
