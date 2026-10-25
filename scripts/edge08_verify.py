#!/usr/bin/env python
"""WP-EDGE-08 — the independent verifier: re-derive the claims instead of trusting them.

    python scripts/edge08_verify.py             # verify, write VERIFICATION.json/.md
    python scripts/edge08_verify.py --self-test  # sabotage each check and require detection
    python scripts/edge08_verify.py --json       # print the payload, write nothing

What makes this a verifier rather than a summary:

* **the holdout claim is re-checked from the disk and from git**, not read from the manifest's own
  word: a shard of one of the six symbols anywhere outside ``data/edge08`` fails, and every tracked
  file that mentions a symbol is classified — a corpus shard or a result artefact mentioning one is
  a violation, whatever the registration says;
* **the corpus is re-hashed shard by shard**, the per-shard digests and the corpus digest are
  recomputed and compared with the manifest and with the registration, and the coverage the report
  published is recomputed from the bars themselves, on all three clocks;
* **the verdicts are recomputed from the checks the artefacts themselves published**, with an
  implementation written here rather than imported, so a document that says one thing and contains
  another fails;
* **the money is re-derived from the raw trade rows**: net, fees and cost-per-trade for a published
  cell are recomputed from the CSV the matrix was written with;
* **it has its own saboteur** — ``--self-test`` tampers with copies of the inputs in fourteen ways
  and requires the corresponding check to fail. A verifier that cannot fail is not evidence.

Read-only: it writes its own report and nothing else.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge01.data import load_1h, resample  # noqa: E402
from trading_bot.research.edge08.books import DECLARED_PARAMS, params_hash  # noqa: E402
from trading_bot.research.edge08.disjointness import disjointness_report  # noqa: E402
from trading_bot.research.edge08.registration import (  # noqa: E402
    COVERAGE_FLOOR_BARS,
    HOLDOUT_SYMBOLS,
    MIN_TRADES,
    SUPPORTED_CLOCKS,
    WINDOWS,
    WP,
)

MANIFEST = REPO_ROOT / "data" / "edge08" / "universe-1h" / "_FETCH_MANIFEST.json"
PREREG_JSON = WP / "PREREGISTRATION.json"
UNIVERSE_JSON = WP / "UNIVERSE.json"
QUALITY_JSON = WP / "quality" / "QUALITY_SCREEN.json"
ACTIVE_JSON = WP / "active" / "ACTIVE_SCREEN.json"
ECONOMICS_JSON = WP / "economics" / "ECONOMIC_MATRIX.json"
ECONOMICS_CSV = WP / "economics" / "ECONOMIC_TRADES.csv"
VALIDATION_JSON = WP / "validation" / "VALIDATION.json"
GATE_JSON = WP / "validation" / "GATE_STATUS.json"
PREREGISTER_SCRIPT = REPO_ROOT / "scripts" / "edge08_preregister.py"

SCHEMA_VERSION = "EDGE08_VERIFICATION_V1"
DECISIVE = "OOS"
VERDICT_ORDER = ("ADMIT_PAPER", "REJECT", "INSUFFICIENT_EVIDENCE", "REJECT_NO_GROSS_EDGE")


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def day_count(window: dict[str, int]) -> float:
    return max(1e-9, (window["end"] - window["start"]) / 86_400_000.0)


# -- live facts (re-derived, never read from a conclusion) ----------------------------- #
def recompute_shard_digests() -> dict[str, str]:
    manifest = read_json(MANIFEST)
    digests: dict[str, str] = {}
    for symbol in sorted(manifest.get("symbols") or {}):
        entry = (manifest["symbols"] or {})[symbol] or {}
        shard = REPO_ROOT / str(entry.get("shard") or "")
        digests[symbol] = sha256_file(shard) if shard.is_file() else ""
    return digests


def recompute_coverage() -> dict[str, dict[str, dict[str, int]]]:
    """Complete bars per asset per window on each clock, from the shards themselves."""
    manifest = read_json(MANIFEST)
    assets = [symbol[: len(symbol) - 4] for symbol in sorted(manifest.get("symbols") or {})]
    out: dict[str, dict[str, dict[str, int]]] = {
        timeframe: {window: {} for window in WINDOWS} for timeframe in SUPPORTED_CLOCKS
    }
    for asset in assets:
        hourly = load_1h(asset, corpus=MANIFEST.parent)
        series = {"1h": hourly}
        for timeframe in ("4h", "1d"):
            series[timeframe] = resample(hourly, timeframe)
        for timeframe, corpus in series.items():
            for window, bounds in WINDOWS.items():
                out[timeframe][window][asset] = sum(
                    1 for bar in corpus.bars if bounds["start"] <= bar.ts <= bounds["end"]
                )
    return out


def read_trade_rows() -> list[dict[str, str]]:
    if not ECONOMICS_CSV.is_file():
        return []
    with ECONOMICS_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run_preregister_check() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(PREREGISTER_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def live_facts() -> dict[str, Any]:
    return {
        "disjointness": disjointness_report(HOLDOUT_SYMBOLS),
        "shard_digests": recompute_shard_digests(),
        "coverage_live": recompute_coverage(),
        "trade_rows": read_trade_rows(),
        "preregister_check": run_preregister_check(),
        "manifest": read_json(MANIFEST),
        "universe_report": read_json(UNIVERSE_JSON),
        "preregistration": read_json(PREREG_JSON),
        "quality_screen": read_json(QUALITY_JSON),
        "active_screen": read_json(ACTIVE_JSON),
        "economics": read_json(ECONOMICS_JSON),
        "validation": read_json(VALIDATION_JSON),
        "gate_status": read_json(GATE_JSON),
    }


# -- the checks ------------------------------------------------------------------------ #
def check_a1_holdout_claim(facts: dict[str, Any]) -> dict[str, Any]:
    """The cross-section is unread: no corpus shard, no tracked artefact measured on it."""
    claim = facts["disjointness"]
    violations = claim.get("violations") or []
    stray = {
        symbol: paths
        for symbol, paths in (claim.get("shards_outside_the_cross_section") or {}).items()
        if paths
    }
    kinds = sorted({str(row.get("kind")) for row in violations})
    return {
        "statement": (
            "no corpus of this repository holds a bar of any of the six symbols, and every tracked "
            "mention of one is a catalogue, a fetch script, a test, documentation or this package"
        ),
        "passed": not violations and not stray and bool(claim.get("claim_holds")),
        "detail": {
            "symbols": claim.get("symbols"),
            "violations": violations,
            "violating_kinds": kinds,
            "shards_outside_the_cross_section": stray,
            "allowed_kinds": claim.get("allowed_kinds"),
            "method": claim.get("method"),
        },
    }


def check_a2_corpus_digest(facts: dict[str, Any]) -> dict[str, Any]:
    """The corpus digest recomputes from the shards, and the registration pinned the same one."""
    recomputed = facts["shard_digests"]
    manifest = facts["manifest"]
    published = {
        symbol: (entry or {}).get("sha256")
        for symbol, entry in sorted((manifest.get("symbols") or {}).items())
    }
    mismatched = {
        symbol: {"published": published.get(symbol), "recomputed": recomputed.get(symbol)}
        for symbol in sorted(set(published) | set(recomputed))
        if published.get(symbol) != recomputed.get(symbol)
    }
    digest = hashlib.sha256(json.dumps(recomputed, sort_keys=True).encode("utf-8")).hexdigest()
    registered = (facts["preregistration"].get("universe") or {}).get("corpus_digest")
    return {
        "statement": (
            "every shard's SHA-256 recomputes, the corpus digest follows from those shards, and "
            "the registration pinned the same digest"
        ),
        "passed": bool(recomputed)
        and not mismatched
        and digest == manifest.get("corpus_digest")
        and digest == registered,
        "detail": {
            "symbols": sorted(recomputed),
            "mismatched": mismatched,
            "corpus_digest_recomputed": digest,
            "corpus_digest_in_manifest": manifest.get("corpus_digest"),
            "corpus_digest_in_registration": registered,
        },
    }


def check_a3_coverage(facts: dict[str, Any]) -> dict[str, Any]:
    """The published coverage recomputes from the bars, on every clock and window."""
    live = facts["coverage_live"]
    report = facts["universe_report"].get("coverage") or {}
    mismatches: dict[str, Any] = {}
    for timeframe, windows in live.items():
        for window, per_asset in windows.items():
            published = ((report.get(timeframe) or {}).get("per_asset_bars_in_window") or {}).get(
                window
            ) or {}
            if published != per_asset:
                mismatches[f"{timeframe}/{window}"] = {
                    "published": published,
                    "recomputed": per_asset,
                }
    validation = facts["validation"]
    decisive_checks: dict[str, Any] = {}
    for timeframe, published in (validation.get("coverage") or {}).items():
        decisive_checks[timeframe] = {
            "published": published.get("bars_per_asset"),
            "recomputed": live.get(timeframe, {}).get(DECISIVE),
            "floor": published.get("floor_bars_per_asset"),
            "floor_is_registered": published.get("floor_bars_per_asset")
            == COVERAGE_FLOOR_BARS[timeframe],
        }
    decisive_ok = all(
        row["published"] == row["recomputed"] and row["floor_is_registered"]
        for row in decisive_checks.values()
    )
    return {
        "statement": (
            "the complete bars per asset the report published recompute from the shards on all "
            "three clocks, and the decisive-window floor is the registered one"
        ),
        "passed": bool(live) and not mismatches and decisive_ok,
        "detail": {"mismatches": mismatches, "decisive_window": decisive_checks},
    }


def check_a4_registration_matches_code(facts: dict[str, Any]) -> dict[str, Any]:
    """The registration re-renders from the code that obeys it, byte for byte."""
    check = facts["preregister_check"]
    published = facts["preregistration"].get("books") or {}
    recomputed = {arm: params_hash(params) for arm, params in sorted(DECLARED_PARAMS.items())}
    mismatched = {
        arm: {"published": (published.get(arm) or {}).get("params_hash"), "recomputed": value}
        for arm, value in recomputed.items()
        if (published.get(arm) or {}).get("params_hash") != value
    }
    return {
        "statement": (
            "`edge08_preregister.py --check` re-renders the committed registration from the code, "
            "and every registered parameter hash recomputes"
        ),
        "passed": check["exit_code"] == 0 and not mismatched and bool(recomputed),
        "detail": {
            "exit_code": check["exit_code"],
            "stdout": check["stdout"],
            "stderr": check["stderr"],
            "mismatched": mismatched,
        },
    }


def check_b1_books_are_the_registered_bytes(facts: dict[str, Any]) -> dict[str, Any]:
    """The books under test are the registered books, and the defect's hashes are gone."""
    books = facts["preregistration"].get("books") or {}
    current = {params_hash(params) for params in DECLARED_PARAMS.values()}
    superseded = {
        value
        for defect in (facts["quality_screen"].get("defects_fixed") or [])
        + (facts["active_screen"].get("defects_fixed") or [])
        for value in dict(defect.get("superseded_params_hashes") or {}).values()
    }
    missing = sorted(set(DECLARED_PARAMS) - set(books))
    recomputed = {arm: params_hash(params) for arm, params in sorted(DECLARED_PARAMS.items())}
    mismatched = {
        arm: {"published": (books.get(arm) or {}).get("params_hash"), "recomputed": value}
        for arm, value in recomputed.items()
        if (books.get(arm) or {}).get("params_hash") != value
    }
    # The artefact the verdict was computed on must say the same bytes as the registration: a run
    # that measured one book and published another would otherwise be invisible here.
    validation_mismatches = {
        arm: {
            "validation_params_hash": entry.get("params_hash"),
            "registered_params_hash": (books.get(arm) or {}).get("params_hash"),
        }
        for arm, entry in sorted((facts["validation"].get("arms") or {}).items())
        if entry.get("params_hash")
        and entry.get("params_hash") != (books.get(arm) or {}).get("params_hash")
    }
    return {
        "statement": (
            "the parameter hash of every book under test recomputes to the registered value, the "
            "reading artefact names the same bytes, and no superseded hash is still under test"
        ),
        "passed": not missing
        and bool(books)
        and not mismatched
        and not validation_mismatches
        and bool(superseded)
        and not (superseded & current),
        "detail": {
            "registered_books": sorted(books),
            "books_without_registration": missing,
            "mismatched_params_hashes": mismatched,
            "validation_artefact_mismatches": validation_mismatches,
            "superseded_hashes": sorted(superseded),
            "superseded_still_under_test": sorted(superseded & current),
        },
    }


def check_b2_screen_consequences(facts: dict[str, Any]) -> dict[str, Any]:
    """C0 recomputes, and the consequences registered with it were the ones followed."""
    rows: list[dict[str, Any]] = []
    for artefact in (facts["quality_screen"], facts["active_screen"]):
        for arm, entry in sorted((artefact.get("arms") or {}).items()):
            dev = (entry.get("rows") or {}).get("DEV") or {}
            screen = entry.get("screen") or {}
            recomputed = (
                bool(dev.get("trades")) and float(dev.get("gross_expectancy_usdt") or 0.0) > 0
            )
            rows.append(
                {
                    "arm": arm,
                    "published": bool(screen.get("passed")),
                    "recomputed": recomputed,
                    "dev_trades": dev.get("trades"),
                    "dev_gross_expectancy_usdt": dev.get("gross_expectancy_usdt"),
                }
            )
    mismatched = [row for row in rows if row["published"] != row["recomputed"]]
    validation = facts["validation"]
    not_read = set(validation.get("not_read_on_the_cross_section") or [])
    read = set(validation.get("read_on_the_cross_section") or [])
    stopped = {row["arm"] for row in rows if not row["recomputed"]}
    consequence_ok = stopped <= not_read and stopped.isdisjoint(read)
    verdict_ok = all(
        (validation.get("arms") or {}).get(arm, {}).get("verdict") == "REJECT_NO_GROSS_EDGE"
        for arm in stopped
    )
    for arm in stopped:
        cells = (validation.get("arms") or {}).get(arm, {}).get("cells") or {}
        if cells:
            verdict_ok = False
    return {
        "statement": (
            "the gross screen recomputes from its own DEV rows, every arm it stopped is absent "
            "from the cross-section reading, and each of those arms carries the registered verdict"
        ),
        "passed": bool(rows) and not mismatched and consequence_ok and verdict_ok,
        "detail": {
            "arms": rows,
            "mismatched": mismatched,
            "stopped_but_read": sorted(stopped & read),
            "stopped_arms": sorted(stopped),
        },
    }


def recompute_verdict(entry: dict[str, Any]) -> str:
    """The registered decision rule, implemented here rather than imported (B-3)."""
    screen = entry.get("screen") or {}
    if not screen.get("passed"):
        return "REJECT_NO_GROSS_EDGE"
    checks = {check["id"]: check for check in entry.get("checks") or []}
    if not checks:
        return "INSUFFICIENT_EVIDENCE"
    failed = {cid for cid, check in checks.items() if not check.get("passed")}
    if not failed:
        return "ADMIT_PAPER"
    if "P1" in failed and checks.get("P2", {}).get("passed") and checks.get("P4", {}).get("passed"):
        return "INSUFFICIENT_EVIDENCE"
    if "P5" in failed and checks.get("P2", {}).get("passed"):
        return "INSUFFICIENT_EVIDENCE"
    return "REJECT"


def check_b3_verdicts_follow_from_their_checks(facts: dict[str, Any]) -> dict[str, Any]:
    validation = facts["validation"]
    mismatched: dict[str, Any] = {}
    for arm, entry in sorted((validation.get("arms") or {}).items()):
        if entry.get("verdict") == "NOT_APPLICABLE":
            continue
        recomputed = recompute_verdict(entry)
        if entry.get("verdict") != recomputed:
            mismatched[arm] = {"published": entry.get("verdict"), "recomputed": recomputed}
    power_ok = all(
        int((entry.get("decisive_window") or {}).get("trades") or 0) >= MIN_TRADES
        or entry.get("verdict") != "ADMIT_PAPER"
        for entry in (validation.get("arms") or {}).values()
    )
    return {
        "statement": (
            "each arm's verdict follows from the checks the arm itself published, and no arm is "
            "admitted without the registered minimum sample"
        ),
        "passed": bool(validation.get("arms")) and not mismatched and power_ok,
        "detail": {
            "verdicts": {
                arm: entry.get("verdict")
                for arm, entry in sorted((validation.get("arms") or {}).items())
            },
            "mismatched": mismatched,
            "unknown_verdicts": sorted(
                {
                    str(entry.get("verdict"))
                    for entry in (validation.get("arms") or {}).values()
                    if str(entry.get("verdict")) not in (*VERDICT_ORDER, "NOT_APPLICABLE")
                }
            ),
        },
    }


def check_b4_no_promotion(facts: dict[str, Any]) -> dict[str, Any]:
    offenders: list[dict[str, Any]] = []
    for name in (
        "preregistration",
        "quality_screen",
        "active_screen",
        "economics",
        "validation",
        "gate_status",
    ):
        payload = facts[name]
        if payload.get("promotion") not in (None, "NONE"):
            offenders.append({"artefact": name, "promotion": payload.get("promotion")})
        if payload.get("order_sent") not in (None, False):
            offenders.append({"artefact": name, "order_sent": payload.get("order_sent")})
    for arm, entry in sorted((facts["validation"].get("arms") or {}).items()):
        if entry.get("promotion") not in (None, "NONE") or entry.get("order_sent") not in (
            None,
            False,
        ):
            offenders.append(
                {
                    "artefact": f"validation:{arm}",
                    "promotion": entry.get("promotion"),
                    "order_sent": entry.get("order_sent"),
                }
            )
        for forbidden in ("size", "quantity", "qty", "order_id", "capital"):
            if forbidden in entry:
                offenders.append({"artefact": f"validation:{arm}", "field": forbidden})
    return {
        "statement": (
            "no artefact of this package promotes anything or carries a size, a quantity or an "
            "order: promotion is NONE and order_sent is false everywhere"
        ),
        "passed": not offenders,
        "detail": {"offenders": offenders},
    }


def check_b5_windows_and_digest(facts: dict[str, Any]) -> dict[str, Any]:
    prereg = facts["preregistration"]
    validation = facts["validation"]
    mismatches: dict[str, Any] = {}
    for window, bounds in WINDOWS.items():
        if (prereg.get("windows") or {}).get(window) != bounds:
            mismatches[f"prereg/{window}"] = {
                "published": (prereg.get("windows") or {}).get(window),
                "registered": bounds,
            }
        if (validation.get("windows") or {}).get(window) != bounds:
            mismatches[f"validation/{window}"] = {
                "published": (validation.get("windows") or {}).get(window),
                "registered": bounds,
            }
    digest_ok = (
        validation.get("corpus_digest")
        == facts["manifest"].get("corpus_digest")
        == (prereg.get("universe") or {}).get("corpus_digest")
    )
    return {
        "statement": (
            "the windows read are the registered windows on every artefact, and the cross-section "
            "read is the corpus the registration pinned"
        ),
        "passed": not mismatches and digest_ok,
        "detail": {"mismatches": mismatches, "digest_consistent": digest_ok},
    }


def check_b6_defects_published(facts: dict[str, Any]) -> dict[str, Any]:
    quality = facts["quality_screen"].get("defects_fixed") or []
    active = facts["active_screen"].get("defects_fixed") or []
    ids_quality = sorted(str(defect.get("id")) for defect in quality)
    ids_active = sorted(str(defect.get("id")) for defect in active)
    named = [
        defect
        for defect in quality + active
        if defect.get("superseded_params_hashes") and defect.get("cause") and defect.get("fix")
    ]
    affected = {
        arm for defect in named for arm in dict(defect.get("superseded_params_hashes") or {})
    }
    return {
        "statement": (
            "the defect the screen exposed is published in both screen artefacts with its cause, "
            "its fix and the parameters it superseded"
        ),
        "passed": bool(named) and ids_quality == ids_active and bool(affected),
        "detail": {
            "in_quality": ids_quality,
            "in_active": ids_active,
            "affected_arms": sorted(affected),
        },
    }


def check_b7_frequency_recomputes(facts: dict[str, Any]) -> dict[str, Any]:
    window = WINDOWS[DECISIVE]
    days = day_count(window)
    mismatches: dict[str, Any] = {}
    for arm, entry in sorted((facts["validation"].get("arms") or {}).items()):
        cell = ((entry.get("cells") or {}).get(DECISIVE) or {}).get("BASE")
        if not cell:
            continue
        frequency = cell.get("frequency") or {}
        recomputed = round(int(cell.get("trades") or 0) / days, 4)
        if frequency.get("trades_per_day_universe") != recomputed:
            mismatches[arm] = {
                "published": frequency.get("trades_per_day_universe"),
                "recomputed": recomputed,
            }
    read_any = any(
        ((entry.get("cells") or {}).get(DECISIVE) or {}).get("BASE")
        for entry in (facts["validation"].get("arms") or {}).values()
    )
    return {
        "statement": (
            "the trades-per-day the verdicts read recompute from the decisive window's own rows "
            "and its own length"
        ),
        "passed": not mismatches and bool(read_any),
        "detail": {"mismatches": mismatches, "decisive_window_days": round(days, 4)},
    }


def check_b8_money_is_internally_consistent(facts: dict[str, Any]) -> dict[str, Any]:
    mismatches: dict[str, Any] = {}
    for arm, entry in sorted((facts["validation"].get("arms") or {}).items()):
        cell = ((entry.get("cells") or {}).get(DECISIVE) or {}).get("BASE")
        if not cell:
            continue
        trades = int(cell.get("trades") or 0)
        net = float(cell.get("net_usdt") or 0.0)
        expectancy = cell.get("expectancy_usdt")
        interval = cell.get("expectancy_ci_90_usdt") or {}
        share = cell.get("largest_trade_share_of_net")
        problems: list[str] = []
        if trades and expectancy is not None and abs(float(expectancy) - net / trades) > 0.01:
            problems.append("expectancy does not equal net/trades")
        if (
            trades
            and interval.get("point") is not None
            and abs(float(interval["point"]) - net / trades) > 0.01
        ):
            problems.append("the bootstrap point is not the expectancy")
        if net <= 0 and share is not None:
            problems.append("a share of the net is published for a non-positive net")
        if net > 0 and share is None:
            problems.append("no share of the net is published for a positive net")
        if problems:
            mismatches[arm] = problems
    return {
        "statement": (
            "each decisive cell's money is internally consistent: expectancy is net over trades, "
            "the interval's point is that expectancy, and concentration is published exactly when "
            "the net is positive"
        ),
        "passed": not mismatches and bool(facts["validation"].get("arms")),
        "detail": {"mismatches": mismatches},
    }


def check_c1_gate_status(facts: dict[str, Any]) -> dict[str, Any]:
    rows = facts["gate_status"].get("rows") or []
    validation = facts["validation"].get("arms") or {}
    arms = sorted(validation)
    listed = sorted(str(row.get("arm")) for row in rows)
    mismatched = {
        str(row.get("arm")): {
            "gate_status": row.get("registered_verdict"),
            "validation": (validation.get(str(row.get("arm"))) or {}).get("verdict"),
        }
        for row in rows
        if row.get("registered_verdict")
        != (validation.get(str(row.get("arm"))) or {}).get("verdict")
    }
    loads = {str(row.get("arm")): row.get("cross_section_load") for row in rows}
    return {
        "statement": (
            "the gate status lists every arm this package registers, its verdict agrees with the "
            "validation, and the table says what it is: a status, not a permission"
        ),
        "passed": listed == arms
        and bool(rows)
        and not mismatched
        and all(value in ("read", "not read") for value in loads.values())
        and str(facts["gate_status"].get("promotion")) == "NONE"
        and facts["gate_status"].get("order_sent") is False,
        "detail": {
            "arms_in_validation": arms,
            "arms_in_gate_status": listed,
            "mismatched": mismatched,
            "load": loads,
        },
    }


def check_c2_money_recomputes_from_the_rows(facts: dict[str, Any]) -> dict[str, Any]:
    """Recompute one published cell from the raw trade rows the CSV holds."""
    rows = [
        row
        for row in facts["trade_rows"]
        if row.get("window") == DECISIVE and row.get("scenario") == "BASE"
    ]
    if not rows:
        return {
            "statement": "a published cell recomputes from the raw trade rows",
            "passed": False,
            "detail": {"rows_available": 0},
        }
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("arm"))] = counts.get(str(row.get("arm")), 0) + 1
    arm = max(sorted(counts), key=lambda key: counts[key])
    subset = [row for row in rows if row.get("arm") == arm]
    net = sum(float(row.get("net") or 0.0) for row in subset)
    fees = sum(float(row.get("fees") or 0.0) for row in subset)
    price_costs = sum(float(row.get("price_costs") or 0.0) for row in subset)
    notional = sum(float(row.get("notional") or 0.0) for row in subset)
    cost_bps = round((fees + price_costs) / notional * 10_000.0, 4) if notional else None
    cell = (
        (((facts["economics"].get("arms") or {}).get(arm) or {}).get("cells") or {})
        .get(DECISIVE, {})
        .get("BASE", {})
    )
    published_net = cell.get("net_usdt")
    published_trades = cell.get("trades")
    published_cost = cell.get("total_cost_bps_per_trade")
    return {
        "statement": (
            "one published cell recomputes from the raw trade rows: the same trade count, the same "
            "net and the same cost per traded notional"
        ),
        "passed": published_trades == len(subset)
        and published_net is not None
        and abs(float(published_net) - net) < 0.02
        and published_cost is not None
        and cost_bps is not None
        and abs(float(published_cost) - cost_bps) < 0.01,
        "detail": {
            "arm": arm,
            "rows": len(subset),
            "recomputed_net_usdt": round(net, 4),
            "published_net_usdt": published_net,
            "recomputed_cost_bps": cost_bps,
            "published_cost_bps": published_cost,
        },
    }


CHECKS: tuple[tuple[str, Any], ...] = (
    ("A-1", check_a1_holdout_claim),
    ("A-2", check_a2_corpus_digest),
    ("A-3", check_a3_coverage),
    ("A-4", check_a4_registration_matches_code),
    ("B-1", check_b1_books_are_the_registered_bytes),
    ("B-2", check_b2_screen_consequences),
    ("B-3", check_b3_verdicts_follow_from_their_checks),
    ("B-4", check_b4_no_promotion),
    ("B-5", check_b5_windows_and_digest),
    ("B-6", check_b6_defects_published),
    ("B-7", check_b7_frequency_recomputes),
    ("B-8", check_b8_money_is_internally_consistent),
    ("C-1", check_c1_gate_status),
    ("C-2", check_c2_money_recomputes_from_the_rows),
)

SABOTAGES: dict[str, Any] = {
    "A-1": lambda f: f["disjointness"]["violations"].append(
        {
            "symbol": "AAVEUSDT",
            "path": "reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json",
            "kind": "result_artefact",
        }
    ),
    "A-2": lambda f: f["manifest"]["symbols"][
        next(iter(sorted(f["manifest"]["symbols"])))
    ].__setitem__("sha256", "0" * 64),
    "A-3": lambda f: f["universe_report"]["coverage"]["1d"]["per_asset_bars_in_window"][
        DECISIVE
    ].__setitem__(
        next(
            iter(
                sorted(f["universe_report"]["coverage"]["1d"]["per_asset_bars_in_window"][DECISIVE])
            )
        ),
        1,
    ),
    "A-4": lambda f: f["preregister_check"].__setitem__("exit_code", 1),
    "B-1": lambda f: f["preregistration"]["books"][
        next(iter(sorted(f["preregistration"]["books"])))
    ].__setitem__("params_hash", "0" * 64),
    "B-2": lambda f: next(
        entry for entry in f["quality_screen"]["arms"].values() if not entry["screen"]["passed"]
    )["screen"].__setitem__("passed", True),
    "B-3": lambda f: next(
        entry
        for arm, entry in sorted(f["validation"]["arms"].items())
        if entry.get("verdict") in ("REJECT", "INSUFFICIENT_EVIDENCE")
    ).__setitem__("verdict", "ADMIT_PAPER"),
    "B-4": lambda f: f["validation"].__setitem__("promotion", "PAPER"),
    "B-5": lambda f: f["validation"]["windows"][DECISIVE].__setitem__("start", 1_600_000_000_000),
    "B-6": lambda f: f["active_screen"].__setitem__("defects_fixed", []),
    "B-7": lambda f: next(
        entry
        for entry in f["validation"]["arms"].values()
        if ((entry.get("cells") or {}).get(DECISIVE) or {}).get("BASE")
    )["cells"][DECISIVE]["BASE"]["frequency"].__setitem__("trades_per_day_universe", 99.0),
    "B-8": lambda f: next(
        entry
        for entry in f["validation"]["arms"].values()
        if ((entry.get("cells") or {}).get(DECISIVE) or {}).get("BASE")
    )["cells"][DECISIVE]["BASE"].__setitem__("net_usdt", 123_456.78),
    "C-1": lambda f: f["gate_status"]["rows"].pop(),
    "C-2": lambda f: [
        row.__setitem__("net", float(row.get("net") or 0.0) + 1000.0) for row in f["trade_rows"]
    ],
}


def verify(facts: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for check_id, function in CHECKS:
        try:
            outcome = function(facts)
        except Exception as exc:  # a check that cannot run is a failure, not a pass
            outcome = {
                "statement": getattr(function, "__doc__", "") or "",
                "passed": False,
                "detail": {"error": f"{type(exc).__name__}: {exc}"},
            }
        results.append({"id": check_id, **outcome})
    passed = sum(1 for row in results if row["passed"])
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_utc": now_utc(),
        "checks": results,
        "passed": passed,
        "total": len(results),
        "result": "PASS" if passed == len(results) else "FAIL",
        "failing": [row["id"] for row in results if not row["passed"]],
    }


def self_test(facts: dict[str, Any]) -> dict[str, Any]:
    baseline = verify(facts)
    detections: list[dict[str, Any]] = []
    for check_id, sabotage in SABOTAGES.items():
        mutated = copy.deepcopy(facts)
        try:
            sabotage(mutated)
            result = verify(mutated)
            detected = check_id in result["failing"]
            detail: Any = next(row for row in result["checks"] if row["id"] == check_id)["detail"]
        except Exception as exc:  # a sabotage that cannot even be applied is not a detection
            detected = False
            detail = {"error": f"{type(exc).__name__}: {exc}"}
        detections.append({"check": check_id, "detected": detected, "detail": detail})
    return {
        "baseline_result": baseline["result"],
        "baseline_failing": baseline["failing"],
        "sabotages": detections,
        "detected": sum(1 for row in detections if row["detected"]),
        "total": len(detections),
        "result": "PASS"
        if all(row["detected"] for row in detections) and baseline["result"] == "PASS"
        else "FAIL",
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08 — independent verification",
        "",
        f"*Run at `{payload['as_of_utc']}` (`{payload['schema_version']}`). Result: "
        f"**{payload['result']}** — {payload['passed']}/{payload['total']} checks passed.*",
        "",
        "| # | Check | Result |",
        "| --- | --- | --- |",
    ]
    for row in payload["checks"]:
        lines.append(
            f"| {row['id']} | {row['statement']} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines += ["", "## What each check re-derived", ""]
    for row in payload["checks"]:
        detail = row.get("detail") or {}
        lines.append(f"### {row['id']} — {'PASS' if row['passed'] else 'FAIL'}")
        lines.append("")
        lines.append(f"{row['statement']}.")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(detail, indent=2, ensure_ascii=False, sort_keys=True, default=str))
        lines.append("```")
        lines.append("")
    if payload.get("self_test"):
        test = payload["self_test"]
        lines += [
            "## Sabotage self-test",
            "",
            f"Baseline {test['baseline_result']}; {test['detected']}/{test['total']} sabotages "
            f"detected; result **{test['result']}**.",
            "",
            "| Check sabotaged | Detected |",
            "| --- | --- |",
        ]
        for row in test["sabotages"]:
            lines.append(f"| {row['check']} | {row['detected']} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the payload and write nothing")
    parser.add_argument("--self-test", action="store_true", help="sabotage each check")
    parser.add_argument("--no-self-test", action="store_true", help="skip the sabotage self-test")
    options = parser.parse_args(argv)

    facts = live_facts()
    payload = verify(facts)
    if options.self_test or not options.no_self_test:
        payload["self_test"] = self_test(facts)

    if options.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0 if payload["result"] == "PASS" else 1

    (WP / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (WP / "VERIFICATION.md").write_text(render(payload), encoding="utf-8")
    print(
        f"verification {payload['result']} ({payload['passed']}/{payload['total']})"
        + (
            f"; self-test {payload['self_test']['result']} "
            f"({payload['self_test']['detected']}/{payload['self_test']['total']} sabotages detected)"
            if payload.get("self_test")
            else ""
        )
    )
    for row in payload["checks"]:
        if not row["passed"]:
            print(f"  FAILED {row['id']}: {json.dumps(row['detail'], default=str)[:400]}")
    return (
        0
        if payload["result"] == "PASS" and payload.get("self_test", {}).get("result") == "PASS"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
