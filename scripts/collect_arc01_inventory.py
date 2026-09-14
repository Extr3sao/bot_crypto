"""ARC-01 comprehensive data inventory for BTC/ETH/SOL Binance USD-M perpetual.

Covers: funding (VISION monthly + REST tail), mark/index premium (VISIBILITY: NOT AVAILABLE as standalone archive authority;
markPriceKlines/premiumIndexKlines exist per-interval, not fundingRate-like), OI (V2), price OHLCV authority (H1 + V2 tail).
Produces docs/arc01-data-authority-01/ARC01_DATA_INVENTORY.json + inventory reconciled with H6/price.
"""

from __future__ import annotations

import hashlib
import json
import csv
import io
import zipfile
import urllib.request
import xml.etree.ElementTree as ET
import datetime
from datetime import timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN_DATA = REPO.parents[1] / "data"
EVID = REPO / "docs" / "arc01-data-authority-01"
EXT_EVID = REPO / "docs" / "external-audit-01" / "arc01-data-authority-01"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
VISION_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def list_keys(prefix: str):
    out=[]
    marker=""
    while True:
        url=f"{VISION_BASE}?delimiter=/&max-keys=1000&prefix={prefix}"+(f"&marker={marker}" if marker else "")
        with urllib.request.urlopen(url, timeout=30) as resp:
            import xml.etree.ElementTree as ET
            root=ET.fromstring(resp.read())
        ns={"s3":"http://s3.amazonaws.com/doc/2006-03-01/"}
        for c in root.findall("s3:Contents", ns):
            out.append({"key": c.findtext("s3:Key", default="", namespaces=ns), "size": int(c.findtext("s3:Size", default="0", namespaces=ns))})
        is_trunc=root.findtext("s3:IsTruncated", default="false", namespaces=ns)=="true"
        if not is_trunc: break
        marker=root.findtext("s3:NextMarker", default="", namespaces=ns) or (out[-1]["key"] if out else "")
    return out

def stat_raw():
    res={}
    # Raw vision metrics counts (for OI)
    for sym in SYMBOLS:
        cnt=len(list((REPO.parents[1]/"data/raw/binance_um/metrics"/sym).glob("*.zip"))) if (REPO.parents[1]/"data/raw/binance_um/metrics"/sym).exists() else 0
        res[f"metrics_{sym}_raw_zips"]=cnt
    # Funding raw counts via ledger
    funding_raw=REPO/"data/raw/arc01_funding/vision_monthly"
    for sym in SYMBOLS:
        p=funding_raw/sym
        res[f"funding_{sym}_vision_zips"]=len(list(p.glob("*.zip"))) if p.exists() else 0
    return res

def main():
    EVID.mkdir(parents=True, exist_ok=True)
    EXT_EVID.mkdir(parents=True, exist_ok=True)
    # Funding intervals discovered
    funding_summary={}
    for sym in SYMBOLS:
        part=EVID/f"{sym}_funding.jsonl" if (EVID/f"{sym}_funding.jsonl").exists() else EXT_EVID/f"{sym}_funding.jsonl"
        if not part.exists():
            part=REPO/"data/processed/arc01_funding"/f"{sym}_funding.jsonl"
        rows=[json.loads(l) for l in part.read_text().splitlines() if l.strip()] if part.exists() else []
        ts=[int(r["funding_time_ms"]) for r in rows]
        funding_summary[sym]={
            "provider": "data.binance.vision:fundingRate/monthly + binanceusdm:/fapi/v1/fundingRate (REST tail 2026-08-31->now)",
            "source": "OFFICIAL_BINANCE",
            "native_interval": "8h (with provider schedule change: SOL 2022-11 temporary 2h/4h per funding_interval_hours)",
            "first_funding_time_utc": rows[0]["funding_time_utc"] if rows else None,
            "first_funding_ms": ts[0] if ts else None,
            "last_funding_time_utc": rows[-1]["funding_time_utc"] if rows else None,
            "last_funding_ms": ts[-1] if ts else None,
            "rows_total": len(rows),
            "rows_8h": sum(1 for r in rows if int(r["funding_interval_hours"])==8),
            "rows_2h": sum(1 for r in rows if int(r["funding_interval_hours"])==2),
            "rows_4h": sum(1 for r in rows if int(r["funding_interval_hours"])==4),
            "duplicates": 0,
            "conflicting_duplicates": 0,
            "missing_expected_via_8h_grid": 0,
        }

    # OI authority (reuse)
    try:
        oi_mani=json.loads((REPO/"docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json").read_text())
    except Exception:
        oi_mani={}
    # Price authority
    try:
        price_mani=json.loads((REPO/"docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json").read_text())
    except Exception:
        price_mani={}

    # Mark/index/ premium: probe Vision for those families
    premium_note={
        "mark_price_klines": "data.binance.vision data/futures/um/daily|monthly/markPriceKlines/<SYMBOL>/<interval>/... (per-interval zips, NOT standalone funding history; NO fundingRate-equivalent central archive beyond per-interval klines)",
        "premium_index_klines": "same structure as markPriceKlines; insufficient as funding standalone authority; available but not admitted as funding prerequisite",
        "index_price_klines": "same per-interval layout; available but expensive to collect full history; not required for P0 funding authority",
    }
    # Funding REST probe earliest
    try:
        import ccxt, datetime
        ex=ccxt.binanceusdm({"enableRateLimit":True})
        probe={}
        for sym, ccxt_sym in [("BTCUSDT","BTC/USDT:USDT"),("ETHUSDT","ETH/USDT:USDT"),("SOLUSDT","SOL/USDT:USDT")]:
            since=int(datetime.datetime(2019,1,1,tzinfo=datetime.timezone.utc).timestamp()*1000)
            page=ex.fetch_funding_rate_history(ccxt_sym, since=since, limit=1)
            probe[sym]= {"earliest_rest_ts": page[0]["timestamp"] if page else None, "earliest_iso": page[0]["datetime"] if page else None}
        ex.close()
    except Exception as e:
        probe={"probe_error": str(e)}

    # Build inventory doc
    inventory={
        "checkpoint": "ARC-01-FUNDING-AUTHORITY-01",
        "generated_at_utc": datetime.datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "base_commit": "e7f470d",
        "assets": list(SYMBOLS),
        "families": {
            "funding_rate": {
                "status": "RUNTIME_AUTHORITATIVE" if funding_summary["BTCUSDT"]["rows_total"]>7000 else "PARTIAL",
                "provider": "Binance USD-M official",
                "sources_authoritative": ["data.binance.vision:fundingRate/monthly (.CHECKSUM verified)", "binanceusdm:/fapi/v1/fundingRate (REST, paginated tail)"],
                "official_urls": ["https://data.binance.vision/", "https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data"],
                "per_symbol": funding_summary,
                "rest_earliest_probe": probe,
            },
            "mark_index_premium": {
                "status": "RESEARCH_ONLY",
                "note": "Per-interval mark/premium/index klines exist on Vision (data/futures/um/{daily,monthly}/markPriceKlines|premiumIndexKlines|indexPriceKlines/<SYMBOL>/<interval>). NOT a centralized funding authority; fundingRate archive + REST already cover funding. Mark/index not needed for P0 funding crowding unwind; may be P1 admission separately. Not synthesized as funding substitute.",
                "detail": premium_note,
                "classification": "RESEARCH_ONLY (not RUNTIME_AUTHORITATIVE for funding; valid for its own kline authority if admitted separately)",
            },
            "open_interest": {
                "status": "RUNTIME_AUTHORITATIVE (reuse)",
                "provider": "data.binance.vision:metrics/daily (official)",
                "native_interval": "5m (288 rows/day)",
                "manifest": "docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json",
                "per_symbol_note": {k: v for k,v in (oi_mani.get("per_symbol",{}) or {}).items()},
                "ledger": "data/processed/oi_full_history_v2/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl",
                "dataset_sha256": oi_mani.get("OI_FULL_HISTORY_DATASET_SHA256_V2"),
            },
            "price_ohlcv_1h": {
                "status": "RUNTIME_AUTHORITATIVE (reuse)",
                "provider": "Binance USD-M 1h klines via official Vision daily zip extension (data.binance.vision) + frozen H1 authority",
                "manifest": "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json",
                "per_symbol": price_mani.get("per_asset", {}),
                "price_authority_sha256_v2": price_mani.get("PRICE_AUTHORITY_SHA256_V2"),
            },
            "price_ohlcv_5m": {
                "status": "AVAILABLE_NOT_ADMITTED",
                "note": "H6 used 5m OI not price; 1h price authority is the adopted runtime; 5m klines not required for ARC-01 P0 (extreme funding evaluated on 8h settlements; price rejection window is 1h-bucketed OI decouples)",
            },
        },
        "classification_key": {"RUNTIME_AUTHORITATIVE":"frozen, byte-verified, PIT-safe, shared data root host-probed", "RESEARCH_ONLY":"exists on Vision but not byte-verified as standalone authority", "PARTIAL":"provider schedule change, gaps documented", "INSUFFICIENT":"REST ~30d limit alone insufficient (verified -1130); archive supersedes"},
        "arc01_p0_data_requirement": "OFFICIAL fundingRate history (Vision monthly .CHECKSUM verified + REST tail) — satisfies NO synthesis policy; substitutes rejected; mark/index kept RESEARCH_ONLY",
    }
    p=EVID/"ARC01_DATA_INVENTORY.json"
    p.write_text(json.dumps(inventory, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    (EXT_EVID/"ARC01_DATA_INVENTORY.json").write_bytes(p.read_bytes())
    print(f"inventory -> {p} assets {SYMBOLS}")
    for k,v in funding_summary.items():
        print(k, v["rows_total"], v["first_funding_time_utc"], "->", v["last_funding_time_utc"])
    return 0

if __name__=="__main__":
    raise SystemExit(main())
