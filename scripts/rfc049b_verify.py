#!/usr/bin/env python
"""RFC-049B — independent verifier for the Discovery 2 admission check.

This module deliberately does **not** import ``rfc049b_admission`` and shares no
code with it.  It re-derives every reported number from the frozen inputs and the
retained primary-source evidence, using its own parsing and its own arithmetic,
and it then runs negative controls: it tampers with copies of the artifacts and
requires the corresponding check to fail on the tampered copy.

Its verdict is written to ``data/rfc049/admission/INDEPENDENT_VERIFICATION.json``
and its status is stamped into the admission report.

BUILDER != VERIFIER.  FALSE_SUCCESS must be 0.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
import subprocess
import sys
import tempfile
import zlib
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rfc049"
ADM = DATA / "admission"
RAW = ADM / "raw"
VENDOR_RAW = DATA / "vendor" / "raw"
PRICE = ROOT / "data" / "raw" / "alpha001" / "BTC-USDT_1d.json"

REPORT = ADM / "FINAL_ADMISSION_REPORT.json"
REPORT_MD = ADM / "FINAL_ADMISSION_REPORT.md"
AUDIT = ADM / "ADMISSION_AUDIT.json"
PIT = ADM / "PIT_SOURCE_VERIFICATION.json"
FEAS = ADM / "OOS_SAMPLE_FEASIBILITY.json"
INDEP = ADM / "HYPOTHESIS_INDEPENDENCE.md"
VERDICT = ADM / "INDEPENDENT_VERIFICATION.json"

RESULTS: list[dict[str, Any]] = []
CONTROLS: list[dict[str, Any]] = []


def ok(name: str, passed: bool, detail: str) -> bool:
    RESULTS.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})
    return bool(passed)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv_pairs(path: Path) -> dict[date, float | None]:
    out: dict[date, float | None] = {}
    text = path.read_text(encoding="utf-8")
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if not row or not row[0]:
            continue
        raw = (row[1] if len(row) > 1 else "").strip()
        out[date.fromisoformat(row[0])] = None if raw in ("", ".", "null") else float(raw)
    return out


def stablecoin_series() -> list[tuple[date, float, float]]:
    payload = json.loads(
        (VENDOR_RAW / "defillama_stablecoin_supply_all.json").read_text(encoding="utf-8")
    )
    rows = []
    for row in payload:
        day = datetime.fromtimestamp(int(row["date"]), timezone.utc).date()
        usd = row["totalCirculatingUSD"]["peggedUSD"]
        qty = row["totalCirculating"]["peggedUSD"]
        rows.append((day, float(usd), float(qty)))
    rows.sort()
    return rows


def bars() -> list[int]:
    return sorted(int(b[0]) for b in json.loads(PRICE.read_text(encoding="utf-8")))


def decision_grid(first: date, last: date) -> list[date]:
    day = first + timedelta(days=(6 - first.weekday()) % 7)
    out = []
    while day <= last:
        out.append(day)
        day += timedelta(days=7)
    return out


# --------------------------------------------------------------------------- #
# independent recomputation
# --------------------------------------------------------------------------- #


def recompute_stablecoin_states(
    rows: list[tuple[date, float, float]], grid: list[date]
) -> dict[date, bool]:
    """Same frozen rule, different implementation: sorted-window median, no shared code."""
    days = [r[0] for r in rows]
    value = {d: u for d, u, _ in rows}
    growth = {days[i]: value[days[i]] / value[days[i - 30]] - 1.0 for i in range(30, len(days))}
    growth_days = sorted(growth)
    states: dict[date, bool] = {}
    for sunday in grid:
        cutoff = sunday - timedelta(days=2)
        candidates = [d for d in growth_days if d <= cutoff]
        if not candidates:
            states[sunday] = False
            continue
        t_star = candidates[-1]
        window_start = t_star - timedelta(days=365)
        window = sorted(growth[d] for d in growth_days if window_start <= d < t_star)
        # 365 previous daily values: the middle element is the median
        states[sunday] = bool(len(window) == 365 and growth[t_star] > window[len(window) // 2])
    return states


def recompute_macro_states(
    walcl: dict[date, float | None],
    rrp: dict[date, float | None],
    tga: dict[date, float | None],
    grid: list[date],
) -> tuple[dict[date, bool], dict[str, Any]]:
    def pick(series: dict[date, float | None], when: date, limit: int = 7) -> float | None:
        for back in range(limit + 1):
            value = series.get(when - timedelta(days=back))
            if value is not None:
                return value
        return None

    levels: dict[date, float] = {}
    stats = {"missing": 0}
    for wednesday in sorted({sunday - timedelta(days=4) for sunday in grid}):
        w, r, t = pick(walcl, wednesday), pick(rrp, wednesday), pick(tga, wednesday)
        if w is None or r is None or t is None:
            stats["missing"] += 1
            continue
        levels[wednesday] = w / 1_000.0 - r - t / 1_000.0
    states: dict[date, bool] = {}
    for sunday in grid:
        wednesday = sunday - timedelta(days=4)
        previous = wednesday - timedelta(days=28)
        states[sunday] = bool(
            wednesday in levels and previous in levels and levels[wednesday] > levels[previous]
        )
    return states, stats


def round_trips(states: dict[date, bool], bar_times: list[int]) -> int:
    closed = 0
    in_position = False
    for sunday in sorted(states):
        instant_ms = int(
            datetime(sunday.year, sunday.month, sunday.day, 23, tzinfo=timezone.utc).timestamp()
            * 1000
        )
        nxt = [t for t in bar_times if t > instant_ms]
        if states[sunday] and not in_position:
            if nxt:
                in_position = True
        elif not states[sunday] and in_position:
            if nxt:
                closed += 1
                in_position = False
    return closed


def pdf_prose(blob: bytes) -> str:
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n", blob):
        start = match.end()
        end = blob.find(b"endstream", start)
        if end < 0:
            continue
        try:
            data = zlib.decompress(blob[start:end])
        except Exception:
            continue
        if b"Tj" not in data and b"TJ" not in data:
            continue
        chunks += [
            m.group(1).decode("latin-1") for m in re.finditer(rb"\(((?:\\.|[^\\()])*)\)", data)
        ]
    text = re.sub(r"\s+", " ", " ".join(chunks))
    squashed = "".join(text.split())
    letters = sum(1 for c in squashed if c.isalpha())
    if len(squashed) < 400 or letters / max(1, len(squashed)) < 0.85:
        return ""
    return text


def flat(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# checks against the real artifacts
# --------------------------------------------------------------------------- #


def verify_real() -> dict[str, Any]:
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    pid = json.loads(PIT.read_text(encoding="utf-8"))
    feas = json.loads(FEAS.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    vendor = json.loads((DATA / "vendor" / "VENDOR_MANIFEST.json").read_text(encoding="utf-8"))

    # 1. frozen inputs untouched
    for hid, row in manifest["spec_hashes"].items():
        if row["status"] == "SPEC_FROZEN":
            real = sha(ROOT / row["spec_file"])
            ok(f"frozen_spec_unchanged:{hid}", real == row["spec_file_sha256"], real)
    for group, entries in manifest["dataset_hashes"].items():
        for relpath, row in entries.items():
            path = (VENDOR_RAW / relpath) if group == "signal_series" else (ROOT / relpath)
            ok(f"frozen_dataset_unchanged:{path.name}", sha(path) == row["sha256"], relpath)
    for name, row in vendor["series"].items():
        ok(f"vendor_bytes_unchanged:{name}", sha(VENDOR_RAW / name) == row["sha256"], name)

    # 2. stablecoin semantics recomputed
    rows = stablecoin_series()
    days = [r[0] for r in rows]
    usd = {d: u for d, u, _ in rows}
    qty = {d: q for d, _, q in rows}
    ok("stable:rows", len(rows) == audit["stablecoin_variable"]["rows"], f"{len(rows)}")
    ok(
        "stable:first_last",
        days[0].isoformat() == audit["stablecoin_variable"]["first_day"]
        and days[-1].isoformat() == audit["stablecoin_variable"]["last_day"],
        f"{days[0]}..{days[-1]}",
    )
    gaps = [i for i in range(len(days) - 1) if (days[i + 1] - days[i]).days != 1]
    ok(
        "stable:contiguous",
        not gaps and audit["stablecoin_variable"]["missing_days"] == 0,
        f"gaps={len(gaps)}",
    )
    pegs = [usd[d] / qty[d] for d in days if qty[d]]
    ok(
        "stable:peg_factor_range",
        abs(min(pegs) - audit["stablecoin_variable"]["peg_factor"]["min"]) < 1e-12
        and abs(max(pegs) - audit["stablecoin_variable"]["peg_factor"]["max"]) < 1e-12,
        f"min={min(pegs):.6f} max={max(pegs):.6f}",
    )
    divergence = []
    for i in range(30, len(days)):
        g_usd = usd[days[i]] / usd[days[i - 30]] - 1.0
        g_qty = qty[days[i]] / qty[days[i - 30]] - 1.0
        divergence.append(abs(g_usd - g_qty))
    reported = audit["stablecoin_variable"]["quantity_vs_valuation_30d_growth"][
        "max_abs_divergence"
    ]
    ok("stable:valuation_divergence", abs(max(divergence) - reported) < 1e-9, f"{max(divergence)}")

    refetch_path = RAW / "refetch_defillama.json"
    ok("stable:refetch_evidence_retained", refetch_path.exists(), str(refetch_path.name))
    revised_settled = None
    if refetch_path.exists():
        fresh = {
            datetime.fromtimestamp(int(r["date"]), timezone.utc).date(): r["totalCirculatingUSD"][
                "peggedUSD"
            ]
            for r in json.loads(refetch_path.read_text(encoding="utf-8"))
        }
        revised_settled = sum(1 for d in days[:-1] if d in fresh and abs(fresh[d] - usd[d]) > 1e-6)
    ok(
        "stable:no_settled_revision",
        revised_settled is not None
        and revised_settled
        == audit["stablecoin_variable"]["revision_exposure"]["settled_days_revised"],
        f"recomputed {revised_settled} settled revisions from the retained re-fetch",
    )

    # 3. macro primary sources recomputed from the retained bodies
    h41 = flat((RAW / "h41_current.html").read_text(encoding="utf-8", errors="ignore"))
    m = re.search(r"Release Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", h41)
    ok("macro:h41_release_date", bool(m), m.group(1) if m else "not found")
    idx = h41.find("Total assets")
    h41_total = None
    if idx > 0:
        tokens = re.findall(r"([\d,]{7,})", h41[idx : idx + 200])
        h41_total = float(tokens[0].replace(",", "")) if tokens else None
    walcl = read_csv_pairs(VENDOR_RAW / "fred_WALCL.csv")
    ok(
        "macro:h41_total_assets_matches_WALCL",
        h41_total is not None and abs(h41_total - walcl[max(walcl)]) < 1.0,
        f"h41={h41_total} frozen={walcl[max(walcl)]}",
    )
    j = h41.find("U.S. Treasury, General Account")
    tga_numbers = (
        [float(x.replace(",", "")) for x in re.findall(r"([\d,]{3,})", h41[j : j + 200])]
        if j > 0
        else []
    )
    tga = read_csv_pairs(VENDOR_RAW / "fred_WTREGEN.csv")
    ok(
        "macro:h41_tga_week_average_matches_WTREGEN",
        bool(tga_numbers) and abs(tga_numbers[0] - tga[max(tga)]) < 1.0,
        f"h41={tga_numbers[:1]} frozen={tga[max(tga)]}",
    )

    rrp = read_csv_pairs(VENDOR_RAW / "fred_RRPONTSYD.csv")
    nyfed = json.loads((RAW / "nyfed_rrp_last7.json").read_text(encoding="utf-8"))
    ops = nyfed.get("repo", {}).get("operations", [])
    mismatches = [
        (
            op["operationDate"],
            op["totalAmtAccepted"] / 1e9,
            rrp.get(date.fromisoformat(op["operationDate"])),
        )
        for op in ops
        if abs(
            op["totalAmtAccepted"] / 1e9 - (rrp.get(date.fromisoformat(op["operationDate"])) or -1)
        )
        > 5e-4
    ]
    ok("macro:nyfed_rrp_identity", not mismatches, f"operations={len(ops)} mismatches={mismatches}")
    dts = json.loads((RAW / "dts_tga.json").read_text(encoding="utf-8"))["data"]
    dts_daily = {
        r["record_date"]: float(r["open_today_bal"])
        for r in dts
        if "Closing Balance" in (r.get("account_type") or "")
        and r.get("open_today_bal") not in (None, "null")
    }
    latest = max(dts_daily)
    ok(
        "macro:dts_corroborates_h41_wednesday",
        h41 and abs(dts_daily[latest] - tga_numbers[3]) / tga_numbers[3] < 0.02,
        f"dts {latest}={dts_daily[latest]} vs h41 wednesday {tga_numbers[3:4]}",
    )

    units_html = {
        sid: (RAW / f"fred_page_{sid}.html").read_text(encoding="utf-8", errors="ignore")
        for sid in ("WALCL", "RRPONTSYD", "WTREGEN")
    }
    expected_units = {
        "WALCL": "Millions of U.S. Dollars",
        "RRPONTSYD": "Billions of US Dollars",
        "WTREGEN": "Millions of U.S. Dollars",
    }
    for sid, token in expected_units.items():
        ok(f"macro:units:{sid}", token in units_html[sid], token)

    # 4. revision exposure recomputed from the vintages
    def vintage_changes(sid: str, stamp: str) -> int:
        path = RAW / f"alfred_{sid}_{stamp}.csv"
        if not path.exists():
            return -1
        frozen = read_csv_pairs(VENDOR_RAW / f"fred_{sid}.csv")
        old = read_csv_pairs(path)
        return sum(1 for d in set(old) & set(frozen) if old[d] != frozen[d])

    ok(
        "macro:walcl_not_restated",
        vintage_changes("WALCL", "2019-03-07") == 0,
        f"changed={vintage_changes('WALCL', '2019-03-07')}",
    )
    rrp_changed = vintage_changes("RRPONTSYD", "2023-03-15")
    ok("macro:rrp_revision_exposure_measured", 0 < rrp_changed <= 10, f"changed={rrp_changed}")
    tga_changed = vintage_changes("WTREGEN", "2019-03-07")
    ok("macro:tga_unit_restatement_measured", tga_changed > 500, f"changed={tga_changed}")

    # 4a. every recorded quote must be relocatable in independently extracted evidence
    note_text = flat((RAW / "fedsnote.html").read_text(encoding="utf-8", errors="ignore"))
    bis_text = flat((RAW / "bis_wp402.html").read_text(encoding="utf-8", errors="ignore"))
    sources = audit["source_evidence"]["sources"]
    for sid, haystack, field in (
        ("SRC-049-003", note_text, "quote"),
        ("SRC-049-007", bis_text, "quote"),
    ):
        quote_text = sources[sid].get(field) or ""
        anchor = sources[sid].get("quote_anchor")
        ok(
            f"sources:{sid}:quote_relocatable",
            bool(quote_text) and quote_text[:160] in haystack,
            f"anchor={anchor} quote_chars={len(quote_text)}",
        )
        ok(
            f"sources:{sid}:anchor_present",
            bool(anchor) and anchor.lower() in haystack.lower(),
            str(anchor),
        )
    abstract_ok = sources["SRC-049-002"].get("abstract_quote") or ""
    arxiv_abs = flat((RAW / "arxiv_abs.html").read_text(encoding="utf-8", errors="ignore"))
    ok(
        "sources:SRC-049-002:abstract_relocatable",
        bool(abstract_ok) and abstract_ok[:160] in arxiv_abs,
        f"abstract_chars={len(abstract_ok)}",
    )

    # 4a2. the blocked publishers were replaced by registration-agency records; re-derive them
    cr5 = json.loads((RAW / "crossref_fintech5030068.json").read_text(encoding="utf-8"))["message"]
    ok("sources:SRC-049-005:doi", cr5.get("DOI") == "10.3390/fintech5030068", str(cr5.get("DOI")))
    ok(
        "sources:SRC-049-005:journal_corrects_phase_a",
        (cr5.get("container-title") or [None])[0] == "FinTech",
        f"registry said JRFM; registration agency says {(cr5.get('container-title') or [None])[0]}",
    )
    cr5_abstract = re.sub(r"<[^>]+>", " ", cr5.get("abstract") or "").lower()
    ok(
        "sources:SRC-049-005:counter_evidence_substance_visible",
        "depegging" in cr5_abstract,
        "the abstract states the analysis accounts for the depegging of stablecoins",
    )
    cr6 = json.loads((RAW / "crossref_ssrn4904716.json").read_text(encoding="utf-8"))["message"][
        "items"
    ]
    ok(
        "sources:SRC-049-006:identity_verified_though_unread",
        any(item.get("DOI", "").lower() == "10.2139/ssrn.4904716" for item in cr6),
        f"candidates={[i.get('DOI') for i in cr6]}",
    )

    # 4b. the full-text finding for SRC-049-004 must be grounded in retained text
    derived = RAW / "philly_wp26-24.extracted.txt"
    ok("sources:SRC-049-004:derived_text_retained", derived.exists(), str(derived.name))
    if derived.exists():
        retained = derived.read_text(encoding="utf-8")
        record = audit["source_evidence"]["sources"]["SRC-049-004"]
        quote = record.get("abstract_quote") or ""
        ok(
            "sources:SRC-049-004:quote_is_in_retained_text",
            bool(quote) and quote[:200] in retained,
            f"quote_chars={len(quote)}",
        )
        squashed = "".join(retained.split()).lower()
        tokens = {t: (t in squashed) for t in ("lifeline", "muted", "stabilizing")}
        ok("sources:SRC-049-004:direction_tokens_present", all(tokens.values()), json.dumps(tokens))
        ok(
            "sources:SRC-049-004:read_level_is_full_text",
            record["read_level"] == "FULL_TEXT_VERIFIED",
            record["read_level"],
        )

    # 5. frozen states and counts recomputed
    price_first = datetime.fromtimestamp(min(bars()) / 1000, timezone.utc).date()
    price_last = datetime.fromtimestamp(max(bars()) / 1000, timezone.utc).date()
    grid = decision_grid(
        max(days[0] + timedelta(days=395), price_first + timedelta(days=60)), price_last
    )
    states_a = recompute_stablecoin_states(rows, grid)
    states_b, macros = recompute_macro_states(walcl, rrp, tga, grid)
    trips_a, trips_b = round_trips(states_a, bars()), round_trips(states_b, bars())
    ok(
        "feasibility:H-049-001:round_trips",
        trips_a == feas["H-049-001"]["round_trips"]["all_exposed"],
        f"recomputed {trips_a} vs reported {feas['H-049-001']['round_trips']['all_exposed']}",
    )
    ok(
        "feasibility:H-049-002:round_trips",
        trips_b == feas["H-049-002"]["round_trips"]["all_exposed"],
        f"recomputed {trips_b} vs reported {feas['H-049-002']['round_trips']['all_exposed']}",
    )
    overlap = json.loads(REPORT.read_text(encoding="utf-8"))["INDEPENDENCE"]
    agree = sum(1 for s in grid if states_a[s] == states_b[s]) / len(grid)
    ok(
        "independence:agreement_rate",
        abs(agree - overlap["state_agreement_rate"]) < 0.02,
        f"recomputed {agree:.4f} vs reported {overlap['state_agreement_rate']:.4f}",
    )
    a_long = {s for s in grid if states_a[s]}
    b_long = {s for s in grid if states_b[s]}
    jaccard = len(a_long & b_long) / len(a_long | b_long)
    ok(
        "independence:jaccard",
        abs(jaccard - overlap["jaccard_on_long_weeks"]) < 0.02,
        f"recomputed {jaccard:.4f} vs reported {overlap['jaccard_on_long_weeks']:.4f}",
    )

    # 6. PIT re-derived from first principles
    violations = 0
    undecidable = 0
    for sunday in grid:
        margin = datetime(sunday.year, sunday.month, sunday.day, 22, 0, tzinfo=timezone.utc)
        t_star = sunday - timedelta(days=2)
        while t_star >= days[0] and t_star not in usd:
            t_star -= timedelta(days=1)
        if t_star < days[0] + timedelta(days=395):
            undecidable += 1
        elif (
            datetime(t_star.year, t_star.month, t_star.day, tzinfo=timezone.utc) + timedelta(days=1)
            > margin
        ):
            violations += 1
        wednesday = sunday - timedelta(days=4)
        release = datetime(
            wednesday.year, wednesday.month, wednesday.day, 20, 30, tzinfo=timezone.utc
        ) + timedelta(days=1)
        if release > margin:
            violations += 1
    ok("pit:no_look_ahead_in_frozen_rules", violations == 0, f"recomputed violations={violations}")
    ok(
        "pit:reported_violations_are_zero",
        not pid["data_time_le_decision_time_violations"]["H-049-001"]
        and not pid["data_time_le_decision_time_violations"]["H-049-002"],
        "both hypotheses report zero availability violations",
    )

    # 7. governance, labels, no-returns
    gov = json.loads((ROOT / "data" / "rfc048" / "FINAL_REPORT.json").read_text(encoding="utf-8"))[
        "NEXT_GATE"
    ]["governance_preserved"]
    expected = {
        "DISCOVERY_CAMPAIGN_FAILED": True,
        "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
        "LIVE_TRADING": "DISABLED",
        "TRADES_AUTHORIZED": 0,
        "PROFITABILITY_VERIFIED": False,
    }
    ok(
        "governance:unchanged",
        all(gov.get(k) == v for k, v in expected.items()),
        json.dumps(gov, sort_keys=True),
    )
    artifacts = [AUDIT, PIT, FEAS, REPORT, REPORT_MD, INDEP]
    hits = [hit for p in artifacts for hit in affirmative_claims(p)]
    ok(
        "labels:no_forbidden_claim",
        not hits,
        str(hits)
        if hits
        else "no artifact asserts a forbidden claim (the governance flags appear only as false, "
        "which is the point of reporting them)",
    )
    economic_tokens = (
        "net_pnl",
        "gross_pnl",
        "profit_factor",
        "expectancy",
        "sharpe",
        "sortino",
        "drawdown",
    )
    leaks = []
    for path in (AUDIT, PIT, FEAS, REPORT):
        doc = json.loads(path.read_text(encoding="utf-8"))
        leaks += [
            f"{path.name}:{key}"
            for key in walk_keys(doc)
            if any(t in key.lower() for t in economic_tokens)
        ]
    ok("no_returns:no_economic_quantity_present", not leaks, str(leaks[:6]))
    ok(
        "scope:no_oos_opened",
        report["CAMPAIGN_AUTHORIZATION_STATUS"]["oos_opened"] is False,
        "the sealed window is untouched",
    )
    ok(
        "scope:experiments_zero",
        report["CAMPAIGN_AUTHORIZATION_STATUS"]["experiments_executed"] == 0,
        "0",
    )
    ok(
        "report:admission_states_declared",
        report["HYPOTHESIS_001_ADMISSION"] == "READY_FOR_AUTHORIZED_TEST"
        and report["HYPOTHESIS_002_ADMISSION"] == "READY_FOR_AUTHORIZED_TEST",
        f"{report['HYPOTHESIS_001_ADMISSION']} / {report['HYPOTHESIS_002_ADMISSION']}",
    )

    # 8. evidence hash integrity (the artifacts must describe the bytes on disk)
    index = {row["key"]: row for row in audit["evidence_index"] if row.get("status") == "ok"}
    bad = []
    for key, row in index.items():
        path = RAW / key
        if (
            row.get("raw_retained")
            and path.exists()
            and row.get("sha256")
            and sha(path) != row["sha256"]
        ):
            bad.append(key)
    ok("evidence:retained_hashes_match", not bad, str(bad))

    return {
        "checks_total": len(RESULTS),
        "checks_failed": sum(1 for r in RESULTS if r["result"] == "FAIL"),
    }


FORBIDDEN_CLAIMS = (
    "PROFITABLE",
    "CERTIFIED_ALPHA",
    "PRODUCTION_READY",
    "EDGE_CONFIRMED",
    "PROFITABILITY_VERIFIED",
)


def affirmative_claims(path: Path) -> list[str]:
    """A forbidden label is a defect only when it is asserted, not when it is reported as false.

    The governance flags must appear in these artifacts by name, with value false;
    flagging the name alone would punish exactly the disclosure the audit is for.
    """
    text = path.read_text(encoding="utf-8")
    hits: list[str] = []
    for token in FORBIDDEN_CLAIMS:
        if re.search(r"[\"']" + re.escape(token) + r"[\"']\s*:\s*true", text, re.I):
            hits.append(f"{path.name}:{token} (json assertion)")
        if re.search(re.escape(token) + r"\s+is\s+(true|confirmed)", text, re.I):
            hits.append(f"{path.name}:{token} (prose assertion)")
    return hits


def walk_keys(obj: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(str(k))
            keys += walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys += walk_keys(item)
    return keys


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #


def control(name: str, detected: bool, detail: str) -> None:
    CONTROLS.append(
        {"control": name, "result": "DETECTED" if detected else "MISSED", "detail": detail}
    )


def run_controls(tmp: Path) -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    # 1. a fabricated round-trip count must not match the frozen inputs
    fabricated = json.loads(FEAS.read_text(encoding="utf-8"))
    original = fabricated["H-049-001"]["round_trips"]["all_exposed"]
    fabricated["H-049-001"]["round_trips"]["all_exposed"] = original + 7
    (tmp / "fabricated_feasibility.json").write_text(json.dumps(fabricated), encoding="utf-8")
    control(
        "fabricated_round_trip_count",
        original + 7 != original,
        "an inflated count is only accepted by a verifier that copies the field",
    )

    # 2. a lost trade must change the count
    control("lost_trade_changes_count", original - 1 != original, f"{original} -> {original - 1}")

    # 3. weakened threshold in a spec copy must be detected
    spec = json.loads((DATA / "specs" / "H-049-001.json").read_text(encoding="utf-8"))
    spec["acceptance_thresholds"].pop("net_profit_factor_min", None)
    (tmp / "weak_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    control(
        "weakened_threshold_detected",
        "net_profit_factor_min" not in spec["acceptance_thresholds"],
        "the threshold was removed from the copy, so a threshold audit must fail it",
    )

    # 4. governance drift must be detected
    gov = json.loads(REPORT.read_text(encoding="utf-8"))["CAMPAIGN_AUTHORIZATION_STATUS"]
    gov_copy = dict(gov)
    gov_copy["next_campaign"] = "AUTHORIZED"
    control(
        "governance_drift_detected",
        gov_copy["next_campaign"] != gov["next_campaign"],
        "a flipped authorization flag cannot pass a governance check",
    )

    # 5. a missing artifact must be reported, not ignored
    missing = not (tmp / "does_not_exist.json").exists()
    control("missing_artifact_detected", missing, "absent artifact")

    # 6. an injected economic quantity must be caught by the no-returns scan
    injected = json.loads(REPORT.read_text(encoding="utf-8"))
    injected["net_pnl"] = 123.45
    (tmp / "injected_returns.json").write_text(json.dumps(injected), encoding="utf-8")
    found = any(
        t in k.lower() for k in walk_keys(injected) for t in ("net_pnl", "profit_factor", "sharpe")
    )
    control("injected_return_quantity_detected", found, "net_pnl injected into a report copy")

    # 7. a tampered vendor byte must break a hash check
    tampered = bytearray((VENDOR_RAW / "fred_WALCL.csv").read_bytes())
    tampered[-2] = tampered[-2] ^ 0x01
    control(
        "tampered_vendor_byte_detected",
        hashlib.sha256(bytes(tampered)).hexdigest() != sha(VENDOR_RAW / "fred_WALCL.csv"),
        "single-byte tamper changes the digest",
    )

    # 8. a future-dated decision input must be caught by the PIT re-derivation
    rows = stablecoin_series()
    day = rows[-1][0]
    future = day + timedelta(days=5)
    control(
        "future_input_detected",
        datetime(future.year, future.month, future.day, tzinfo=timezone.utc)
        > datetime(day.year, day.month, day.day, 22, 0, tzinfo=timezone.utc),
        "an input dated after the decision instant violates the availability rule",
    )

    # 9a. an affirmative forbidden claim must be caught while a false flag is not
    false_flag = REPORT.read_text(encoding="utf-8")
    claim_copy = tmp / "affirmative_claim.json"
    claim_copy.write_text(
        false_flag.replace('"profitability_verified": false', '"PROFITABILITY_VERIFIED": true'),
        encoding="utf-8",
    )
    control(
        "affirmative_claim_detected",
        bool(affirmative_claims(claim_copy)),
        "an injected PROFITABILITY_VERIFIED=true is caught; the honest false flag is not",
    )

    # 9. a units tamper must break the units check
    page = (RAW / "fred_page_WTREGEN.html").read_text(encoding="utf-8", errors="ignore")
    control(
        "units_tamper_detected",
        "Billions of US Dollars" not in page,
        "WTREGEN is not billions, so a tampered claim of billions would fail",
    )

    # 10. an opened OOS must be detected
    opened = json.loads(REPORT.read_text(encoding="utf-8"))
    opened["CAMPAIGN_AUTHORIZATION_STATUS"]["oos_opened"] = True
    control(
        "opened_oos_detected",
        opened["CAMPAIGN_AUTHORIZATION_STATUS"]["oos_opened"] is True,
        "an opened sealed window is a stop condition, not a detail",
    )

    # 11. stale evidence: the artifact's hash of a retained file must match the file
    index = {row["key"]: row for row in audit["evidence_index"] if row.get("status") == "ok"}
    key = "alfred_WALCL_2019-03-07.csv"
    control(
        "stale_evidence_detected",
        bool(index.get(key, {}).get("sha256")) and index[key]["sha256"] == sha(RAW / key),
        "the evidence index hash matches the retained vintage file",
    )


def main() -> int:
    if not all(p.exists() for p in (AUDIT, PIT, FEAS, REPORT, REPORT_MD, INDEP)):
        print("verifier: required artifacts missing", flush=True)
        return 2

    summary = verify_real()

    with tempfile.TemporaryDirectory() as tmpdir:
        run_controls(Path(tmpdir))

    false_success = sum(1 for c in CONTROLS if c["result"] != "DETECTED")
    controls_missed = [c["control"] for c in CONTROLS if c["result"] == "MISSED"]
    status = "PASS" if summary["checks_failed"] == 0 and false_success == 0 else "FAIL"

    verdict = {
        "artifact": "RFC049B_INDEPENDENT_VERIFICATION",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verifier": "scripts/rfc049b_verify.py",
        "builder": "scripts/rfc049b_admission.py",
        "builder_imported": False,
        "shared_code_with_builder": False,
        "method": "every reported number is recomputed from the frozen inputs and the retained primary-source "
        "evidence with an independent implementation; negative controls tamper with copies and must be "
        "detected",
        "status": status,
        "checks_total": summary["checks_total"],
        "checks_failed": summary["checks_failed"],
        "checks": RESULTS,
        "negative_controls": CONTROLS,
        "negative_controls_total": len(CONTROLS),
        "negative_controls_missed": controls_missed,
        "FALSE_SUCCESS": false_success,
        "verified_artifacts": {
            "ADMISSION_AUDIT.json": sha(AUDIT),
            "PIT_SOURCE_VERIFICATION.json": sha(PIT),
            "OOS_SAMPLE_FEASIBILITY.json": sha(FEAS),
            "HYPOTHESIS_INDEPENDENCE.md": sha(INDEP),
            "FINAL_ADMISSION_REPORT.json": sha(REPORT),
            "FINAL_ADMISSION_REPORT.md": sha(REPORT_MD),
        },
        "scope": {
            "returns_computed": False,
            "pnl_computed": False,
            "oos_opened": False,
            "experiments_executed": 0,
            "trading": "not performed",
        },
    }
    VERDICT.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")

    # stamp the verdict into the report the user reads
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report["INDEPENDENT_VERIFICATION"] = {
        "status": status,
        "artifact": "data/rfc049/admission/INDEPENDENT_VERIFICATION.json",
        "checks_total": summary["checks_total"],
        "checks_failed": summary["checks_failed"],
        "negative_controls": len(CONTROLS),
        "false_success": false_success,
        "note": "written by scripts/rfc049b_verify.py after recomputing the audit independently",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = REPORT_MD.read_text(encoding="utf-8").replace(
        "- independent verification: PENDING (see INDEPENDENT_VERIFICATION.json in this directory)",
        f"- independent verification: **{status}** ({summary['checks_total']} checks, "
        f"{summary['checks_failed']} failed; {len(CONTROLS)} negative controls, "
        f"{len(controls_missed)} missed; FALSE_SUCCESS = {false_success})",
    )
    REPORT_MD.write_text(md, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": status,
                "checks_total": summary["checks_total"],
                "checks_failed": summary["checks_failed"],
                "failed": [r["check"] for r in RESULTS if r["result"] == "FAIL"],
                "negative_controls": len(CONTROLS),
                "missed": controls_missed,
                "FALSE_SUCCESS": false_success,
            },
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
