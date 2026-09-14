"""ARC-01 funding authority — autonomous downloader.

P0: OFFICIAL Binance USD-M funding-rate history for BTCUSDT/ETHUSDT/SOLUSDT.

Dual source (both OFFICIAL BINANCE):
  PRIMARY (deep, byte-verified):  https://data.binance.vision  (data.binance.vision)
    data/futures/um/monthly/fundingRate/<SYMBOL>/<SYMBOL>-fundingRate-YYYY-MM.zip (+.CHECKSUM)
    -> calc_time, funding_interval_hours, last_funding_rate
  TAIL (recent, needed until month closes): public /fapi/v1/fundingRate via ccxt
    binanceusdm fetch_funding_rate_history (no creds, enableRateLimit)

Size safety: funding is tiny vs aggregated trade data (~80*800B per symbol monthly + REST tail).
Full common history is preferred. Selection depends ONLY on availability/provider history/disk safety,
never on observed returns. No threshold/BPS choice here.

Layers kept separate: RAW ZIP bytes (or REST rows materialized as RAW JSONL), NORMALIZED 8h settlements,
EVIDENCE (ledgers/manifest).

Every raw file gets: provider identity, symbol, period, size, SHA256, provider checksum when available.
Provider checksum sidecars are verified.

Public API pagination: /fapi/v1/fundingRate with startTime cursor anchored at deep start
(2019-09-10 for BTC, 2019-11-27 for ETH, 2020-09-13 for SOL); limit=1000.
startTime=0 / absent returns recent-only 500 rows (see carry-funding-deep-01 D1 fingerprint).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN_DATA = REPO.parents[1] / "data"  # shared authoritative processed OI/price lives here (read-only)
RAW_ROOT = REPO / "data" / "raw" / "arc01_funding"
PROC_ROOT = REPO / "data" / "processed" / "arc01_funding"
EVID_DIR = REPO / "docs" / "arc01-data-authority-01"
EXT_EVID = REPO / "docs" / "external-audit-01" / "arc01-data-authority-01"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
VISION_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
CCXT_SYMBOLS = {"BTCUSDT": "BTC/USDT:USDT", "ETHUSDT": "ETH/USDT:USDT", "SOLUSDT": "SOL/USDT:USDT"}

# Deep starts per symbol (from live fundimg probe and D1 fingerprint for BTC)
DEEP_STARTS = {
    "BTCUSDT": datetime(2019, 9, 10, 8, 0, 0, tzinfo=timezone.utc),
    "ETHUSDT": datetime(2019, 11, 27, 8, 0, 0, tzinfo=timezone.utc),
    "SOLUSDT": datetime(2020, 9, 13, 16, 0, 0, tzinfo=timezone.utc),
}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vision_list_keys(prefix: str) -> list[dict]:
    out: list[dict] = []
    marker = ""
    while True:
        url = f"{VISION_BASE}?delimiter=/&max-keys=1000&prefix={prefix}" + (f"&marker={marker}" if marker else "")
        with urllib.request.urlopen(url, timeout=30) as resp:
            root = ET.fromstring(resp.read())
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for c in root.findall("s3:Contents", ns):
            out.append({"key": c.findtext("s3:Key", default="", namespaces=ns), "size": int(c.findtext("s3:Size", default="0", namespaces=ns))})
        is_trunc = root.findtext("s3:IsTruncated", default="false", namespaces=ns) == "true"
        if not is_trunc:
            break
        marker = root.findtext("s3:NextMarker", default="", namespaces=ns) or (out[-1]["key"] if out else "")
    return out


def download_vision_funding():
    """Download ALL monthly fundingRate zips (+.CHECKSUM) for the three symbols, resumable."""
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    ledger: list[dict] = []
    for sym in SYMBOLS:
        prefix = f"data/futures/um/monthly/fundingRate/{sym}/"
        entries = vision_list_keys(prefix)
        # collect zip + checksum pairs
        zips = [e for e in entries if e["key"].endswith(".zip") and not e["key"].endswith(".CHECKSUM")]
        zips_sorted = sorted(zips, key=lambda e: e["key"])
        checks = {e["key"][:-len(".CHECKSUM")] + ".zip": e["key"] for e in entries if e["key"].endswith(".CHECKSUM")}
        print(f"[{sym}] fundingRate monthly zips={len(zips_sorted)} checks={len(checks)}")
        sym_dir = RAW_ROOT / "vision_monthly" / sym
        sym_dir.mkdir(parents=True, exist_ok=True)
        for entry in zips_sorted:
            key: str = entry["key"]
            zip_name = key.rsplit("/", 1)[-1]
            checksum_key = key + ".CHECKSUM"
            out_zip = sym_dir / zip_name
            out_chk = sym_dir / (zip_name + ".CHECKSUM")
            # If already cached and checksum matches provider CHECKSUM payload, skip re-download
            # Download checksum sidecar (tiny)
            try:
                chk_url = f"{VISION_BASE}/{checksum_key}"
                with urllib.request.urlopen(chk_url, timeout=30) as r:
                    chk_bytes = r.read()
                out_chk.write_bytes(chk_bytes)
                expect_sha = chk_bytes.decode(errors="replace").strip().split()[0]
            except Exception as e:
                print(f"  warn checksum fetch fail {sym} {zip_name}: {e}")
                expect_sha = ""
            if out_zip.exists() and expect_sha:
                actual = _sha256_file(out_zip)
                if actual == expect_sha:
                    ledger.append({"symbol": sym, "provider": "data.binance.vision:fundingRate/monthly", "key": key, "local": str(out_zip.relative_to(REPO)).replace("\\", "/"), "size": out_zip.stat().st_size, "sha256": actual, "provider_checksum": expect_sha, "status": "CACHED_VERIFIED"})
                    continue
                else:
                    print(f"  re-download sha mismatch {sym} {zip_name} cached {actual} != expect {expect_sha}")
            # Download zip
            url = f"{VISION_BASE}/{key}"
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            out_zip.write_bytes(data)
            actual = _sha256(data)
            if expect_sha and actual != expect_sha:
                raise RuntimeError(f"CHECKSUM FAIL {sym} {zip_name}: {actual} != {expect_sha}")
            # verify zip is readable and count rows
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                csv_bytes = z.read(z.namelist()[0])
                rows = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
            ledger.append({"symbol": sym, "provider": "data.binance.vision:fundingRate/monthly", "key": key, "local": str(out_zip.relative_to(REPO)).replace("\\", "/"), "size": len(data), "sha256": actual, "provider_checksum": expect_sha, "csv_rows": len(rows), "status": "DOWNLOADED_VERIFIED"})
            print(f"  {sym} {zip_name} rows={len(rows)} sha={actual[:12]}")
    return ledger


def download_rest_tail(vision_ledger: list[dict]):
    """Fetch REST tail after last vision monthly calc_time until now (live, completeness path).

    If vision monthly already reached within last hours (month close), tail is 0..few funding intervals.
    We store REST rows as RAW JSONL materialization alongside the vision ZIPs (separate layer).
    """
    import ccxt

    # Determine last vision calc_time per symbol (max calc_time across all monthly CSVs)
    last_vision_ms: dict[str, int] = {}
    for sym in SYMBOLS:
        sym_dir = RAW_ROOT / "vision_monthly" / sym
        max_ms = 0
        for zp in sorted(sym_dir.glob("*.zip")):
            with zipfile.ZipFile(zp) as z:
                txt = z.read(z.namelist()[0]).decode()
                for row in csv.DictReader(io.StringIO(txt)):
                    ms = int(row["calc_time"])
                    if ms > max_ms:
                        max_ms = ms
        last_vision_ms[sym] = max_ms
        print(f"[{sym}] last vision calc_time={max_ms} {datetime.fromtimestamp(max_ms/1000, tz=timezone.utc).isoformat() if max_ms else 'NONE'}")

    rest_dir = RAW_ROOT / "rest_tail"
    rest_dir.mkdir(parents=True, exist_ok=True)
    rest_ledger: list[dict] = []
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    try:
        for sym in SYMBOLS:
            ccxt_sym = CCXT_SYMBOLS[sym]
            since = last_vision_ms[sym] + 1 if last_vision_ms[sym] else int(DEEP_STARTS[sym].timestamp() * 1000)
            # Fetch paginated from since until now
            rows: list[dict] = []
            cursor = since
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            while cursor < now_ms:
                page = ex.fetch_funding_rate_history(ccxt_sym, since=cursor, limit=1000)
                if not page:
                    break
                rows.extend(page)
                last_t = int(page[-1]["timestamp"])
                if last_t <= cursor:
                    break
                cursor = last_t + 1
                if len(page) < 1000:
                    break
                if len(rows) > 20000:
                    break
            # Only keep rows after last vision (dedup vs archive later in normalization)
            filtered = [r for r in rows if int(r["timestamp"]) > last_vision_ms[sym]]
            out_path = rest_dir / f"{sym}_rest_tail.jsonl"
            payload = [json.dumps({"symbol": sym, "funding_time_ms": int(r["timestamp"]), "funding_rate": str(r["fundingRate"]), "markPrice": r["info"].get("markPrice", ""), "rateType": r["info"].get("rateType", ""), "provider": "binanceusdm:/fapi/v1/fundingRate"}, sort_keys=True, separators=(",", ":")) + "\n" for r in filtered]
            out_path.write_text("".join(payload), encoding="utf-8")
            sha = _sha256_file(out_path)
            rest_ledger.append({"symbol": sym, "provider": "binanceusdm:/fapi/v1/fundingRate (REST tail)", "since_ms": since, "since_iso": datetime.fromtimestamp(since/1000, tz=timezone.utc).isoformat().replace("+00:00","Z"), "until_ms": filtered[-1]["timestamp"] if filtered else None, "rest_rows": len(filtered), "fetched": len(rows), "last_vision_ms": last_vision_ms[sym], "local": str(out_path.relative_to(REPO)).replace("\\","/"), "sha256": sha, "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00","Z")})
            print(f"  REST tail {sym} rows={len(filtered)} since={since} sha={sha[:12]}")
    finally:
        try:
            ex.close()
        except Exception:
            pass
    return rest_ledger


def write_raw_ledgers(vision_ledger, rest_ledger):
    EVID_DIR.mkdir(parents=True, exist_ok=True)
    EXT_EVID.mkdir(parents=True, exist_ok=True)
    # Vision raw ledger JSONL (one per file)
    # Consolidated ledger JSON
    raw_ledger_path = EVID_DIR / "ARC01_FUNDING_RAW_LEDGER.jsonl"
    with raw_ledger_path.open("w", encoding="utf-8", newline="\n") as fh:
        for e in vision_ledger:
            fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
        for e in rest_ledger:
            fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
    # Also copy to external-audit path for portability
    (EXT_EVID / "ARC01_FUNDING_RAW_LEDGER.jsonl").write_bytes(raw_ledger_path.read_bytes())
    # JSON sidecars
    meta = {"vision_monthly_files": len([e for e in vision_ledger if e.get("symbol")]), "rest_tails": len(rest_ledger), "total_bytes_vision": sum(int(e.get("size",0)) for e in vision_ledger)}
    (EVID_DIR / "ARC01_FUNDING_RAW_LEDGER.json").write_text(json.dumps({"checkpoint":"ARC-01-FUNDING-AUTHORITY-01","vision": vision_ledger, "rest_tail": rest_ledger, "totals": meta}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (EXT_EVID / "ARC01_FUNDING_RAW_LEDGER.json").write_bytes((EVID_DIR / "ARC01_FUNDING_RAW_LEDGER.json").read_bytes())
    print(f"raw ledger: {raw_ledger_path} ({len(vision_ledger)+len(rest_ledger)} entries)")
    return raw_ledger_path


def main() -> int:
    print("=== ARC-01 funding download ===")
    vision_ledger = download_vision_funding()
    rest_ledger = download_rest_tail(vision_ledger)
    write_raw_ledgers(vision_ledger, rest_ledger)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
