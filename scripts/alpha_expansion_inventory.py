"""ARP-005 ALPHA EXPANSION §2 — inventory every research corpus (read-only).

Reports, per asset / timeframe: first_timestamp, last_timestamp, calendar_days,
bars, gaps, duplicates, provider and a sha256 fingerprint. Covers:

* the frozen baseline 5m corpus (``reports/strategy-baseline/data``);
* the isolated extended 5m corpus (``reports/alpha-recovery-v1-4/data``);
* the new expanded 1h corpus (``reports/alpha-expansion-v1/data``);
* the constructed 1d/4h/8h bars over the expansion splits.

Writes ``reports/alpha-expansion-v1/DATA_INVENTORY.json``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.alpha_expansion import data as D  # noqa: E402
from trading_bot.research.alpha_expansion import htf as H  # noqa: E402

BASELINE = REPO / "reports/strategy-baseline/data"
EXTENDED = REPO / "reports/alpha-recovery-v1-4/data"
EXPANSION = REPO / "reports/alpha-expansion-v1/data"
OUT = REPO / "reports/alpha-expansion-v1/DATA_INVENTORY.json"
PROVIDER = "BINANCE_PUBLIC_REST:/api/v3/klines"

TF_MS = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000, "8h": 28_800_000, "1d": 86_400_000}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit(rows: list[dict[str, Any]], tf_ms: int) -> dict[str, Any]:
    ts = sorted(int(r["ts"]) for r in rows)
    n = len(ts)
    dup = n - len(set(ts))
    expected = (ts[-1] - ts[0]) // tf_ms + 1 if n else 0
    return {
        "first_ts": ts[0] if ts else None,
        "last_ts": ts[-1] if ts else None,
        "bars": n,
        "expected_bars": expected,
        "gaps": max(0, expected - len(set(ts))),
        "duplicates": dup,
        "calendar_days": round((ts[-1] - ts[0]) / 86_400_000, 2) if n else 0.0,
    }


def _corpus_5m(root: Path, label: str, tf: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sym in SYMBOLS:
        rows: list[dict[str, Any]] = []
        shards: list[dict[str, str]] = []
        for p in sorted(root.glob(f"{sym}_*.json")):
            if "_5m_" in p.name:
                continue
            rows.extend(json.loads(p.read_text(encoding="utf-8")))
            shards.append({"file": p.name, "sha256": _sha(p)})
        if not rows:
            continue
        rec = {
            "asset": sym,
            "timeframe": tf,
            "provider": PROVIDER,
            "corpus": label,
            "shards": shards,
        }
        rec.update(_audit(rows, TF_MS[tf]))
        out[sym] = rec
    return out


def _expansion_1h() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sym in SYMBOLS:
        rows: list[dict[str, Any]] = []
        shards: list[dict[str, str]] = []
        for p in sorted(EXPANSION.glob(f"{sym}_*.json")):
            rows.extend(json.loads(p.read_text(encoding="utf-8")))
            shards.append({"file": p.name, "sha256": _sha(p)})
        if not rows:
            continue
        rec = {
            "asset": sym,
            "timeframe": "1h",
            "provider": PROVIDER,
            "corpus": "expansion",
            "shards": shards,
        }
        rec.update(_audit(rows, TF_MS["1h"]))
        rec["shards"] = shards
        out[sym] = rec
    return out


def _derived_htf() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for split in ("DEV", "VALIDATION", "OOS_LOCK"):
        for tf_h, tf in ((4, "4h"), (8, "8h"), (24, "1d")):
            rec: dict[str, Any] = {"split": split, "timeframe": tf, "assets": {}}
            for key, sym in D.SYMBOLS.items():
                bars = H.build_htf_bars(D.load_lower_bars(sym, split), tf_h)
                rows = [{"ts": b.open_ms} for b in bars]
                a = _audit(rows, TF_MS[tf])
                rec["assets"][key] = {
                    "first_ts": a["first_ts"],
                    "last_ts": a["last_ts"],
                    "bars": a["bars"],
                    "calendar_days": a["calendar_days"],
                    "gaps": a["gaps"],
                    "duplicates": a["duplicates"],
                }
            out[f"{split}_{tf}"] = rec
    return out


def main() -> int:
    doc = {
        "provider": PROVIDER,
        "baseline_5m": _corpus_5m(BASELINE, "baseline", "5m"),
        "extended_5m": _corpus_5m(EXTENDED, "extended", "5m"),
        "expansion_1h": _expansion_1h(),
        "expansion_derived_htf": _derived_htf(),
        "fingerprints": {
            "baseline_corpus": _baseline_digest(),
            "extended_corpus": _ext_digest(),
            "expansion_corpus": D.expansion_corpus_digest(),
        },
    }
    OUT.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print("wrote", OUT)
    return 0


def _baseline_digest() -> str:
    sys.path.insert(0, str(REPO / "src"))
    from trading_bot.research.alpha_recovery import campaign as C

    return C.corpus_digest()


def _ext_digest() -> str:
    from trading_bot.research.alpha_recovery import extended as E

    return E.ext_corpus_digest()


if __name__ == "__main__":
    raise SystemExit(main())
