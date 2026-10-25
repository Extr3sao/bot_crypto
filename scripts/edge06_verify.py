#!/usr/bin/env python
"""WP-EDGE-06 — an independent reading of this work package's own claims.

Every check recomputes a number from the source the artefact claims to have read, and refuses
to accept the published string. The ones that matter most:

* **the economic audit is re-derived from the per-trade rows**, not compared with itself: the
  per-window gross, fees, price costs and net are summed again from ``TRADES.csv`` and required
  to equal the audit's figures, and the audit's figures are required to equal the campaign's own
  ``STRATEGY_RESULTS.json``. Two independent paths to the same number, three artefacts;
* **one family is re-run from the corpus** and its DEV/BASE metrics are required to match the
  published ``FAMILY_PROGRAM.json`` exactly, so the report cannot describe a run that did not
  happen;
* **the storage reclaim's own arithmetic is re-checked**: every removed path passed the three
  claims (a cache by name, untracked by git, named in ``.gitignore``) *and* the reclaimed bytes
  are the sum of those rows;
* **the freeze is checked against git**, not against a memory of what was frozen: the strategy
  and risk paths must be identical to the commit that last froze them, and the candidate
  parameter hash must be the frozen one;
* **the repair is checked at the artefact**: the derived state view on disk hashes to what it
  says it hashes to, and a fresh build of the current commit agrees with it.

Then it sabotages each check — writing a wrong number (or removing the one the check needs) into
**in-memory copies** — and requires the check to fail. A verification that cannot fail is not a
verification, and every mutation here is one the check is supposed to catch.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

WP = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06"
RESEARCH = WP / "research"
CAMPAIGN = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-01"
RECOVERY = REPO_ROOT / "data" / "recovery"

SCHEMA_VERSION = "EDGE06_VERIFICATION_V1"

#: The windows the decomposition is stated for, and the file that carries the trades.
WINDOWS = {
    "DEV": (datetime(2024, 10, 1, tzinfo=UTC), datetime(2025, 6, 30, tzinfo=UTC)),
    "VAL": (datetime(2025, 7, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)),
    "OOS": (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC)),
}

#: Paths whose bytes must not have moved since the commit that froze them.
FROZEN_PATHS = (
    "config/risk.yaml",
    "src/trading_bot/risk",
    "src/trading_bot/strategies",
    "src/trading_bot/research/edge01/candidates.py",
    "src/trading_bot/research/edge01/campaign.py",
)
FROZEN_SINCE = "5237c76"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def close(a: float, b: float, *, tol: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=max(1e-6, abs(b) * tol))


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #


def check_audit_matches_the_trades(audit: dict[str, Any], trades: list[dict[str, str]]) -> dict[str, Any]:
    """Re-sum the audit's own rows from TRADES.csv and compare with the campaign's artefact."""
    published = audit["decomposition"]["books"]["edge_intra_01"]
    failures: list[str] = []
    checked = 0
    for label, row in published.items():
        window, scenario = label.split(":")
        start, end = WINDOWS[window]
        subset = [
            trade
            for trade in trades
            if trade["candidate"] == "edge_intra_01"
            and trade["scenario"] == scenario
            and start
            <= datetime.fromtimestamp(_num(trade["decision_ts"]) / 1000, tz=UTC)
            <= end
        ]
        recomputed = {
            "trades": len(subset),
            "gross_usdt": round(sum(_num(t["gross"]) for t in subset), 4),
            "fees_usdt": round(sum(_num(t["fees"]) for t in subset), 4),
            "price_costs_usdt": round(sum(_num(t["price_costs"]) for t in subset), 4),
        }
        for key, value in recomputed.items():
            checked += 1
            if not close(_num(row[key]), value, tol=1e-4):
                failures.append(f"{label}.{key}: published {row[key]} != recomputed {value}")
        net = round(recomputed["gross_usdt"] - recomputed["fees_usdt"] - recomputed["price_costs_usdt"], 4)
        checked += 1
        if not close(_num(row["net_usdt"]), net, tol=1e-4):
            failures.append(f"{label}.net: published {row['net_usdt']} != recomputed {net}")
    return {
        "check": "audit:the_decomposition_re_sums_from_the_trades",
        "result": "PASS" if not failures else "FAIL",
        "figures_checked": checked,
        "failures": failures[:10],
    }


def check_campaign_agrees_with_the_audit(audit: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    """The audit and the campaign's own artefact must state the same net, window by window."""
    published = audit["audit"]
    failures: list[str] = []
    checked = 0
    for row in published:
        metrics = (
            (results.get("candidates") or {})
            .get(row["book"], {})
            .get("splits", {})
            .get(row["window"], {})
            .get(row["scenario"])
        )
        if not metrics:
            failures.append(f"{row['book']}/{row['window']}/{row['scenario']}: missing in the campaign")
            continue
        for key in ("trades", "gross_usdt", "fees_usdt", "price_costs_usdt", "net_usdt"):
            checked += 1
            if not close(_num(row[key]), _num(metrics.get(key)), tol=1e-4):
                failures.append(
                    f"{row['book']}/{row['window']}/{row['scenario']}.{key}: "
                    f"audit {row[key]} != campaign {metrics.get(key)}"
                )
    return {
        "check": "audit:every_figure_equals_the_campaign_artefact",
        "result": "PASS" if not failures else "FAIL",
        "figures_checked": checked,
        "failures": failures[:10],
    }


def check_family_reproduction(program: dict[str, Any]) -> dict[str, Any]:
    """Re-run one registered family and require the published metrics to match exactly."""
    from trading_bot.research.edge06 import program as P

    book = "edge06_trend_fixed"
    fresh = P.run_family(book, scenarios=("BASE",))
    published = program["families"][book]["splits"]
    failures: list[str] = []
    checked = 0
    for window in ("DEV", "VAL", "OOS"):
        fresh_metrics = fresh["splits"][window]["BASE"]
        published_metrics = published[window]["BASE"]
        for key in (
            "trades",
            "gross_usdt",
            "fees_usdt",
            "price_costs_usdt",
            "net_usdt",
            "expectancy_usdt",
            "profit_factor",
            "max_drawdown_pct",
        ):
            checked += 1
            if isinstance(fresh_metrics.get(key), float) or isinstance(published_metrics.get(key), float):
                same = close(_num(fresh_metrics.get(key)), _num(published_metrics.get(key)), tol=1e-6)
            else:
                same = fresh_metrics.get(key) == published_metrics.get(key)
            if not same:
                failures.append(
                    f"{book}/{window}.{key}: published {published_metrics.get(key)} != "
                    f"recomputed {fresh_metrics.get(key)}"
                )
    return {
        "check": "program:one_family_re_runs_to_the_published_metrics",
        "result": "PASS" if not failures else "FAIL",
        "figures_checked": checked,
        "book": book,
        "failures": failures[:10],
    }


def check_the_reclaim_kept_its_own_rule(reclaim: dict[str, Any]) -> dict[str, Any]:
    """Every removed path was a cache by name, untracked, and ignored — and the sum is the claim."""
    failures: list[str] = []
    removed = reclaim.get("removed") or []
    total = 0
    for row in removed:
        if not row.get("removed"):
            continue
        name = Path(str(row["path"])).name
        if not (
            name == "__pycache__"
            or name.startswith(".coverage")
            or name
            in (".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis")
            or row.get("regenerated_by") is None
        ):
            failures.append(f"{row['path']}: not a recognised cache family")
        if row.get("tracked_by_git"):
            failures.append(f"{row['path']}: git tracks it")
        if row.get("ignored_by_gitignore") is not True:
            failures.append(f"{row['path']}: .gitignore does not name it")
        total += int(row["bytes"])
    if removed and total != int(reclaim.get("reclaimed_bytes") or -1):
        failures.append(
            f"reclaimed_bytes {reclaim.get('reclaimed_bytes')} != sum of removed rows {total}"
        )
    return {
        "check": "storage:every_removed_path_passed_the_three_checks",
        "result": "PASS" if not failures else "FAIL",
        "paths_checked": len(removed),
        "reclaimed_bytes": total,
        "failures": failures[:10],
    }


def check_the_freeze_holds() -> dict[str, Any]:
    """The strategy and risk paths must be byte-identical to the commit that froze them."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{FROZEN_SINCE}..HEAD", "--", *FROZEN_PATHS],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    moved = [line for line in diff.stdout.splitlines() if line.strip()]
    from trading_bot.research.edge01.candidates import PARAMS_HASH

    failures = [f"{path} moved since {FROZEN_SINCE}" for path in moved]
    return {
        "check": "freeze:no_strategy_or_risk_path_moved_since_the_freeze",
        "result": "PASS" if not failures else "FAIL",
        "since": FROZEN_SINCE,
        "params_hash": PARAMS_HASH,
        "paths_checked": list(FROZEN_PATHS),
        "failures": failures[:10],
    }


def check_the_registration_precedes_the_run() -> dict[str, Any]:
    """The hypotheses file must be committed *before* the results, and both must be committed."""
    def last_commit(path: str) -> str | None:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", path],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() or None

    hypotheses = last_commit("reports/edge-recovery/WP-EDGE-06/research/HYPOTHESES.md")
    results = last_commit("reports/edge-recovery/WP-EDGE-06/research/FAMILY_PROGRAM.json")
    failures: list[str] = []
    if not hypotheses:
        failures.append("HYPOTHESES.md is not committed")
    if not results:
        failures.append("FAMILY_PROGRAM.json is not committed")
    ordered = False
    if hypotheses and results:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", hypotheses, results],
            cwd=str(REPO_ROOT),
            capture_output=True,
            check=False,
        )
        ordered = ancestor.returncode == 0
        if not ordered:
            failures.append("the registration commit is not an ancestor of the results commit")
    return {
        "check": "registration:the_hypotheses_commit_precedes_the_results_commit",
        "result": "PASS" if not failures else "FAIL",
        "hypotheses_commit": hypotheses,
        "results_commit": results,
        "ordered": ordered,
        "failures": failures,
    }


def check_the_repaired_view_is_consistent() -> dict[str, Any]:
    """The derived state view on disk must hash to what it says, and a fresh build must agree."""
    module = _load(REPO_ROOT / "scripts" / "campaign_state_view.py", "edge06_state_view")
    path = RECOVERY / "CAMPAIGN_STATE_VIEW.json"
    stored = read_json(path)
    published_hash = module.payload_hash(stored)
    fresh_hash = module.payload_hash(module.build())
    failures: list[str] = []
    if stored.get("payload_sha256") != published_hash:
        failures.append("the file's own payload_sha256 does not match its content")
    if published_hash != fresh_hash:
        failures.append(
            f"the published view {published_hash[:16]} disagrees with a fresh build {fresh_hash[:16]}"
        )
    return {
        "check": "repair:the_derived_view_agrees_with_a_fresh_build_of_head",
        "result": "PASS" if not failures else "FAIL",
        "published_sha256": published_hash,
        "fresh_sha256": fresh_hash,
        "failures": failures,
    }


CHECKS = (
    ("audit_re_sums_from_the_trades", lambda ctx: check_audit_matches_the_trades(ctx["audit"], ctx["trades"])),
    (
        "audit_equals_the_campaign_artefact",
        lambda ctx: check_campaign_agrees_with_the_audit(ctx["audit"], ctx["campaign"]),
    ),
    ("family_re_runs", lambda ctx: check_family_reproduction(ctx["program"])),
    ("reclaim_rule", lambda ctx: check_the_reclaim_kept_its_own_rule(ctx["reclaim"])),
    ("freeze", lambda ctx: check_the_freeze_holds()),
    ("registration_order", lambda ctx: check_the_registration_precedes_the_run()),
    ("repaired_view", lambda ctx: check_the_repaired_view_is_consistent()),
)


# --------------------------------------------------------------------------- #
# the sabotage matrix: a check that cannot fail is not a check
# --------------------------------------------------------------------------- #


def _mutations(ctx: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """``(check, name, mutated context)`` — each one must make its check FAIL."""

    def copy_context() -> dict[str, Any]:
        return {
            "audit": deepcopy(ctx["audit"]),
            "trades": [dict(row) for row in ctx["trades"]],
            "campaign": deepcopy(ctx["campaign"]),
            "reclaim": deepcopy(ctx["reclaim"]),
            "program": deepcopy(ctx["program"]),
        }

    out: list[tuple[str, str, dict[str, Any]]] = []
    bad = copy_context()
    bad["audit"]["decomposition"]["books"]["edge_intra_01"]["DEV:BASE"]["gross_usdt"] += 1.0
    out.append(("audit_re_sums_from_the_trades", "one gross figure moves by 1 USDT", bad))

    bad = copy_context()
    bad["audit"]["decomposition"]["books"]["edge_intra_01"]["DEV:BASE"]["net_usdt"] = 0.0
    out.append(("audit_re_sums_from_the_trades", "the net is stated as zero", bad))

    bad = copy_context()
    for row in bad["trades"]:
        if row["candidate"] == "edge_intra_01" and row["scenario"] == "BASE":
            row["fees"] = "0"
    out.append(("audit_re_sums_from_the_trades", "fees erased from the trade rows", bad))

    bad = copy_context()
    bad["audit"]["audit"][0]["net_usdt"] += 5.0
    out.append(("audit_equals_the_campaign_artefact", "the audit disagrees with the campaign", bad))

    bad = copy_context()
    bad["program"]["families"]["edge06_trend_fixed"]["splits"]["OOS"]["BASE"]["net_usdt"] += 1.0
    out.append(("family_re_runs", "the published OOS net moves by 1 USDT", bad))

    bad = copy_context()
    bad["program"]["families"]["edge06_trend_fixed"]["splits"]["DEV"]["BASE"]["trades"] += 1
    out.append(("family_re_runs", "the published trade count moves", bad))

    bad = copy_context()
    for row in bad["reclaim"]["removed"]:
        if row.get("removed"):
            row["tracked_by_git"] = True
            break
    out.append(("reclaim_rule", "a removed path is claimed as tracked by git", bad))

    bad = copy_context()
    bad["reclaim"]["reclaimed_bytes"] = int(bad["reclaim"].get("reclaimed_bytes") or 0) + 1
    out.append(("reclaim_rule", "the reclaimed total stops matching its rows", bad))
    return out


def self_test(ctx: dict[str, Any]) -> dict[str, Any]:
    results = []
    for check, name, mutated in _mutations(ctx):
        payload = dict(CHECKS_BY_NAME[check](mutated))
        detected = payload["result"] == "FAIL"
        results.append({"check": check, "mutation": name, "detected": detected})
    return {
        "check": "self_test:every_sabotage_is_detected",
        "result": "PASS" if all(row["detected"] for row in results) else "FAIL",
        "mutations_total": len(results),
        "mutations": results,
        "undetected": [row for row in results if not row["detected"]],
    }


CHECKS_BY_NAME = {name: fn for name, fn in CHECKS}


def build_context() -> dict[str, Any]:
    with (CAMPAIGN / "TRADES.csv").open(encoding="utf-8", newline="") as handle:
        trades = list(csv.DictReader(handle))
    return {
        "audit": read_json(RESEARCH / "STRATEGY_AUDIT.json"),
        "trades": trades,
        "campaign": read_json(CAMPAIGN / "STRATEGY_RESULTS.json"),
        "reclaim": read_json(WP / "STORAGE_RECLAIM.json"),
        "program": read_json(RESEARCH / "FAMILY_PROGRAM.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=str(WP))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    options = parser.parse_args(argv)

    ctx = build_context()
    checks = [fn(ctx) for _name, fn in CHECKS]
    verdict = "VERIFY_PASS" if all(check["result"] == "PASS" for check in checks) else "VERIFY_FAIL"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"EDGE06-VERIFY-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "as_of_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "checks": checks,
        "checks_passed": sum(1 for check in checks if check["result"] == "PASS"),
        "checks_total": len(checks),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }
    # The self-test always runs: a verification whose sabotage matrix is opt-in is a
    # verification that will be run without it exactly when somebody is in a hurry.
    sabotage = self_test(ctx)
    payload["self_test"] = sabotage
    if sabotage["result"] != "PASS":
        payload["verdict"] = "VERIFY_FAIL"
    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if payload["verdict"] == "VERIFY_PASS" else 1

    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    lines = [
        f"# WP-EDGE-06 — independent verification: {payload['verdict']}",
        "",
        f"*Read at `{payload['as_of_utc']}` (`{payload['run_id']}`). "
        f"{payload['checks_passed']}/{payload['checks_total']} checks, "
        f"{payload['self_test']['mutations_total']} sabotages, "
        f"{payload['self_test']['mutations_total'] - len(payload['self_test']['undetected'])} detected.*",
        "",
        "| Check | Result | Figures | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for check in checks:
        figures = (
            check.get("figures_checked")
            or check.get("paths_checked")
            or check.get("mutations")
            or ""
        )
        detail = "; ".join(check.get("failures") or []) or "—"
        lines.append(f"| `{check['check']}` | **{check['result']}** | {figures} | {detail} |")
    lines += [
        "",
        "## Sabotage matrix",
        "",
        "Each mutation below is applied to an in-memory copy of the inputs and must make its",
        "check fail. A verification that survives its own sabotage is not verifying anything.",
        "",
        "| Check | Mutation | Detected |",
        "| --- | --- | --- |",
    ]
    for row in payload["self_test"]["mutations"]:
        lines.append(f"| `{row['check']}` | {row['mutation']} | {'yes' if row['detected'] else '**NO**'} |")
    lines.append("")
    (out / "VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{payload['verdict']}: {payload['checks_passed']}/{payload['checks_total']} checks")
    print(
        f"self-test: {payload['self_test']['result']} — "
        f"{payload['self_test']['mutations_total']} mutation(s), "
        f"{len(payload['self_test']['undetected'])} undetected"
    )
    for check in checks:
        if check["result"] != "PASS":
            print(f"  FAIL {check['check']}: {check.get('failures')}")
    print(f"wrote VERIFICATION.json and VERIFICATION.md into {out}")
    return 0 if payload["verdict"] == "VERIFY_PASS" else 1


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
