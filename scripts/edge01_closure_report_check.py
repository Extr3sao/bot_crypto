"""Verify the WP-EDGE-01 closure deliverables against the artefacts they summarise.

    python scripts/edge01_closure_report_check.py [--dir reports/edge-recovery/WP-EDGE-01]
                                                  [--mode report|run-report|all]
                                                  [--json-out FILE]

Two records close this work package and both are prose or indexes over other people's numbers:

* ``FINAL_REPORT.md`` — the six questions of the closure, answered with figures taken from
  ``RUN_REPORT.json``, ``retest-h6/RETEST.json`` and ``oos-trend-4h/OOS_TREND.json``. A figure
  transcribed by hand can come from the wrong window, so this process *formats* every figure it
  needs from the artefacts and requires that exact string in the text (``--mode report``).
* ``closure/RUN_REPORT.json`` — the machine-readable record: verdicts, digest, commits, the push
  block and the recovery gate. It is re-derived here field by field, the hashes of the files it
  publishes are recomputed from disk, and every commit it lists must exist with the subject it
  claims (``--mode run-report``).

Like the other verifiers of this work package it imports nothing from ``trading_bot``, reads no
file the report does not cite, and exits non-zero the moment one claim has no source. Spanish
formatting is expected in the markdown: thousands separator ``.``, decimal ``,``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_DIR = Path("reports/edge-recovery/WP-EDGE-01")
#: A criterion whose JSON detail states a share, while the report renders a percentage.
SHARE_CRITERIA = {"no_single_trade_carries_the_net"}
#: The candidates the closure table lists, with the windows it quotes.
REPORT_BOOKS = (
    ("edge_intra_01", ("DEV", "VAL", "OOS")),
    ("edge_intra_02", ("DEV",)),
    ("edge_intra_02_no_fvg", ("DEV",)),
    ("edge_trend_01_4h", ("DEV", "VAL", "OOS")),
    ("edge_trend_01_1d", ("DEV",)),
)
#: One entry per experiment, so the record cannot point the verification at the wrong artefact.
EXPERIMENT_VERIFICATIONS = {
    "campaign (WP-EDGE-01)": "INDEPENDENT_VERIFICATION.json",
    "h6": "retest-h6/RETEST_VERIFICATION.json",
    "oos": "oos-trend-4h/OOS_TREND_VERIFICATION.json",
}


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def es(value: float, digits: int = 2) -> str:
    """Spanish number: thousands ``.``, decimal ``,``, explicit minus."""
    sign = "-" if value < 0 else ""
    body = f"{abs(value):,.{digits}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{sign}{body}"


def percentage(value: float) -> str:
    """A share as the report writes it: two decimals, or none when it is exact."""
    scaled = value * 100
    return es(scaled, 0 if abs(scaled - round(scaled)) < 1e-9 else 2) + "%"


def sign(value: float) -> str:
    return "+" if value > 0 else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# 1. every figure in the markdown report has a source
# --------------------------------------------------------------------------- #


def report_needles(directory: Path) -> list[tuple[str, str]]:
    """Every (label, figure) the report is required to contain, formatted from the artefacts."""
    campaign = load(directory / "RUN_REPORT.json")["results"]
    retest = load(directory / "retest-h6" / "RETEST.json")
    oos = load(directory / "oos-trend-4h" / "OOS_TREND.json")
    needles: list[tuple[str, str]] = []

    def want(label: str, needle: str) -> None:
        needles.append((label, needle))

    # section 1 — the five books
    for candidate, windows in REPORT_BOOKS:
        for window in windows:
            want(f"{candidate}/{window} net",
                 es(campaign[candidate]["splits"][window]["BASE"]["net_usdt"], 4))

    # section 2 — H6: the three arms, the order lifecycle, the confirmation windows
    dev = retest["runs"]["DEV:BASE"]["arms"]
    frozen, limit = dev["frozen_market"], dev["plan_limit"]
    for name, arm in (("frozen", frozen), ("plan_limit", limit)):
        want(f"h6 {name} trades", str(arm["trades"]))
        want(f"h6 {name} net", es(arm["net_usdt"], 2))
        want(f"h6 {name} expectancy", es(arm["expectancy_usdt"], 4))
        want(f"h6 {name} win rate", es(arm["win_rate_pct"], 2) + "%")
        want(f"h6 {name} profit factor", es(arm["profit_factor"], 4))
        want(f"h6 {name} drawdown", es(arm["max_drawdown_pct"], 2) + "%")
        want(f"h6 {name} exposure", es(arm["exposure_pct_of_time"], 2) + "%")
    outcomes = limit["orders_by_outcome"]
    want("h6 orders placed", str(limit["orders_placed"]))
    want("h6 fill rate", es(limit["fill_rate"] * 100, 2) + "%")
    for outcome in ("filled", "expired", "refused_by_risk_budget", "cancelled_window_end"):
        want(f"h6 outcome {outcome}", str(outcomes[outcome]))
    want("h6 verdict", retest["verdict"]["verdict"])
    want("h6 execution reading", retest["verdict"]["execution"])
    for window, block in retest["confirmation"].items():
        want(f"h6 {window} net delta", sign(block["net_delta_usdt"]) + es(block["net_delta_usdt"], 2))
        want(f"h6 {window} fill rate", es(block["fill_rate"] * 100, 2) + "%")
    oos_arms = retest["runs"]["OOS:BASE"]["arms"]
    for name, arm in (("variant", oos_arms["plan_limit"]), ("baseline", oos_arms["frozen_market"])):
        want(f"h6 OOS {name} net", es(arm["net_usdt"], 4))
        want(f"h6 OOS {name} trades", str(arm["trades"]))
        want(f"h6 OOS {name} win rate", es(arm["win_rate_pct"], 2) + "%")
    want("h6 expectancy delta per trade",
         es(limit["expectancy_usdt"] - frozen["expectancy_usdt"], 4))

    # section 3 — the OOS review: verdict, every criterion and its detail, the per-asset books
    decision = oos["verdict"]
    want("oos verdict", decision["verdict"])
    want("oos wp admission", decision["wp_admission"]["verdict"])
    for item in decision["checks"]:
        want(f"oos criterion {item['criterion']}", item["criterion"])
        for token in re.findall(r"-?\d+\.\d+|\b\d+\b", item["detail"]):
            value = float(token)
            if item["criterion"] in SHARE_CRITERIA:
                want(f"oos {item['criterion']} share {token}", percentage(value))
            else:
                want(f"oos {item['criterion']} ={token}",
                     es(value, 2) if "." in token else token)
    base = oos["runs"]["OOS:BASE"]
    want("oos combined net", sign(base["combined"]["net_usdt"]) + es(base["combined"]["net_usdt"], 2))
    stress = oos["runs"]["OOS:2X_FEES"]["combined"]
    want("oos 2x fees net", sign(stress["net_usdt"]) + es(stress["net_usdt"], 2))
    want("oos largest trade share", percentage(base["combined"]["largest_trade_share_of_net"]))
    for asset, block in base["assets"].items():
        want(f"oos asset {asset} net", sign(block["net_usdt"]) + es(block["net_usdt"], 2))
    for asset, block in oos["runs"]["OOS:2X_FEES"]["assets"].items():
        want(f"oos 2x fees asset {asset} net", es(block["net_usdt"], 2))
    drawdowns = sorted(block["max_drawdown_pct"] for block in base["buy_and_hold"].values())
    want("oos buy & hold deepest drawdown", es(drawdowns[-1], 2) + "%")
    want("oos buy & hold drawdown list", " / ".join(es(v, 2) + "%" for v in drawdowns))
    return needles


def report_figures(directory: Path, report_name: str) -> tuple[list[tuple[str, str]], int]:
    text = (directory / report_name).read_text(encoding="utf-8")
    needles = report_needles(directory)
    return [(label, needle) for label, needle in needles if needle not in text], len(needles)


# --------------------------------------------------------------------------- #
# 2. the machine-readable record is re-derived, hash by hash
# --------------------------------------------------------------------------- #


def check_run_report(directory: Path, root: Path) -> tuple[list[str], int]:
    """Re-derive closure/RUN_REPORT.json and recompute every digest it publishes."""
    record = load(directory / "closure" / "RUN_REPORT.json")
    campaign = load(directory / "RUN_REPORT.json")
    retest = load(directory / "retest-h6" / "RETEST.json")
    oos = load(directory / "oos-trend-4h" / "OOS_TREND.json")
    problems: list[str] = []
    checks = 0

    def claim(label: str, expected, actual) -> None:
        nonlocal checks
        checks += 1
        if expected != actual:
            problems.append(f"{label}: record {expected!r} != artefact {actual!r}")

    # deliverables: hash and size, recomputed from disk
    for entry in [record["deliverables"]["final_report"],
                  *record["deliverables"]["operations_csv"]]:
        path = root / entry["path"]
        exists = path.is_file()
        claim(f"deliverable present {entry['path']}", True, exists)
        if exists:
            claim(f"deliverable sha256 {entry['path']}", entry["sha256"], sha256(path))
            claim(f"deliverable bytes {entry['path']}", entry["bytes"], path.stat().st_size)

    # H6
    claim("h6 verdict", record["h6"]["verdict"], retest["verdict"]["verdict"])
    claim("h6 execution", record["h6"]["execution"], retest["verdict"]["execution"])
    claim("h6 primary window", record["h6"]["primary_window"],
          retest["experiment"]["primary_window"])
    claim("h6 params hash", record["h6"]["frozen_book_untouched"]["params_hash"],
          retest["params_hash"])
    claim("h6 source digest", record["h6"]["source_digest"],
          retest["source_digest"]["combined_sha256"])
    # the record stores a projection of each arm, so every field it did keep must agree
    for name, quoted in record["h6"]["dev_base_arms"].items():
        source = retest["runs"]["DEV:BASE"]["arms"][name]
        for field, value in quoted.items():
            claim(f"h6 {name}.{field}", value, source[field])
    for name in ("frozen_market", "plan_market", "plan_limit"):
        claim(f"h6 record quotes {name}", name in record["h6"]["dev_base_arms"], True)
    arms = retest["runs"]["DEV:BASE"]["arms"]
    claim("h6 control arm identity is real",
          record["h6"]["frozen_book_untouched"]["plan_market_reproduces_the_frozen_book"],
          arms["plan_market"]["net_usdt"] == arms["frozen_market"]["net_usdt"]
          and arms["plan_market"]["trades"] == arms["frozen_market"]["trades"])
    claim("h6 not promoted", record["h6"]["promoted"], False)

    # the OOS review
    decision = oos["verdict"]
    claim("oos verdict", record["oos_trend_4h"]["verdict"], decision["verdict"])
    claim("oos reasons", record["oos_trend_4h"]["reasons"], decision["reasons"])
    claim("oos checks", record["oos_trend_4h"]["checks"], decision["checks"])
    claim("oos wp admission", record["oos_trend_4h"]["wp_admission"], decision["wp_admission"])
    claim("oos source digest", record["oos_trend_4h"]["source_digest"],
          oos["source_digest"]["combined_sha256"])
    for run, block in record["oos_trend_4h"]["runs"].items():
        for field, value in block.items():
            claim(f"oos {run} {field}", value, oos["runs"][run]["combined"][field])
    for asset, block in record["oos_trend_4h"]["assets_oos_base"].items():
        for field in ("trades", "net_usdt", "expectancy_usdt"):
            claim(f"oos OOS:BASE {asset} {field}", block[field],
                  oos["runs"]["OOS:BASE"]["assets"][asset][field])
    for asset, block in record["oos_trend_4h"]["assets_oos_2x_fees"].items():
        for field in ("trades", "net_usdt", "expectancy_usdt"):
            claim(f"oos OOS:2X_FEES {asset} {field}", block[field],
                  oos["runs"]["OOS:2X_FEES"]["assets"][asset][field])
    claim("oos periods", record["oos_trend_4h"]["periods_oos"],
          oos["runs"]["OOS:BASE"]["periods"])
    claim("oos not promoted to paper", record["oos_trend_4h"]["promoted_to_paper"], False)

    # the frozen campaign
    frozen = record["frozen_measurement_reproduced"]
    claim("campaign verdicts", frozen["verdicts"],
          {key: value["verdict"] for key, value in campaign["results"].items()})
    claim("campaign source digest", frozen["campaign_source_sha256"],
          campaign["git"]["source_sha256"])
    claim("intraday DEV net", frozen["intraday_dev_net_usdt"],
          campaign["results"]["edge_intra_01"]["splits"]["DEV"]["BASE"]["net_usdt"])
    claim("trend 4h DEV net", frozen["trend_4h_dev_net_usdt"],
          campaign["results"]["edge_trend_01_4h"]["splits"]["DEV"]["BASE"]["net_usdt"])
    claim("trend 4h OOS net", frozen["trend_4h_oos_net_usdt"],
          campaign["results"]["edge_trend_01_4h"]["splits"]["OOS"]["BASE"]["net_usdt"])

    # the independent verifications the record cites
    for entry in record["verification"]["experiments"]:
        artifact = EXPERIMENT_VERIFICATIONS.get(entry["experiment"])
        claim(f"{entry['experiment']} names the right artefact", entry["artifact"], artifact)
        if artifact is None:
            continue
        source = load(directory / artifact)
        claim(f"{entry['experiment']} checks total", entry["checks"], source["total"])
        claim(f"{entry['experiment']} checks passed", entry["passed"], source["passed"])
        claim(f"{entry['experiment']} checks failed", entry["failed"], source["failed"])

    # the recovery gate cites the rehearsal taken at the commit this record names
    rehearsal = load(directory / "closure" / "CLEAN_CHECKOUT_REHEARSAL.json")
    gate = record["verification"]["recovery_gate"]
    claim("recovery gate status", gate["status"], rehearsal["status"])
    claim("recovery gate moved nothing", gate["published_paths_moved"],
          rehearsal["published_paths_moved"])
    claim("recovery gate artefacts identical", gate["artifacts_identical"],
          all(item["identical"] for item in rehearsal["artifacts"].values()))
    claim("recovery gate rehearsed commit is a real commit", 0,
          subprocess.run(["git", "cat-file", "-e", rehearsal["rehearsed_commit"]],
                         cwd=root, capture_output=True).returncode)

    # the figures check this process performs
    figures = load(directory / "closure" / "REPORT_FIGURES_CHECK.json")
    claim("figures check status", figures["status"], "PASS")
    claim("figures check counted none missing", figures["report"]["figures_missing"], 0)
    claim("figures check counted all present", figures["report"]["figures_checked"],
          len(report_needles(directory)))

    # commits: each listed sha exists and says what the record claims
    for entry in record["commits"]:
        found = subprocess.run(["git", "log", "-1", "--format=%s", entry["sha"]],
                               cwd=root, capture_output=True, text=True)
        claim(f"commit {entry['sha'][:8]} exists", found.returncode, 0)
        if found.returncode == 0:
            claim(f"commit {entry['sha'][:8]} subject", entry["subject"], found.stdout.strip())

    # publishing: a blocked push must not claim to have published anything
    push = record["push"]
    claim("push did not publish", push["published"], False)
    if push["status"] != "PUSHED":
        claim("push carries a failure message", bool(push.get("fatal_message")), True)
        claim("push carries an unlock procedure", bool(push.get("unlock_procedure")), True)
    return problems, checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="the work package folder")
    parser.add_argument("--report", default="FINAL_REPORT.md", help="the markdown report to audit")
    parser.add_argument("--mode", choices=("report", "run-report", "all"), default="all")
    parser.add_argument("--json-out", default=None, help="also write the outcome as JSON")
    args = parser.parse_args(argv)

    directory = Path(args.dir)
    root = Path(__file__).resolve().parents[1]
    outcome: dict[str, object] = {"dir": str(directory), "mode": args.mode}

    if args.mode in ("report", "all"):
        missing, total = report_figures(directory, args.report)
        outcome["report"] = {"report": args.report, "figures_checked": total,
                             "figures_missing": len(missing),
                             "missing": [f"[{label}] {needle!r}" for label, needle in missing]}
        print(f"report      : {directory / args.report}")
        print(f"figures     : {total - len(missing)}/{total} traceable to the artefacts")
        for label, needle in missing:
            print(f"  NOT FOUND [{label}] {needle!r}")
    if args.mode in ("run-report", "all"):
        problems, checked = check_run_report(directory, root)
        outcome["run_report"] = {"record": "closure/RUN_REPORT.json",
                                 "claims_checked": checked, "problems": problems}
        print(f"run-record  : {directory / 'closure' / 'RUN_REPORT.json'}")
        print(f"claims      : {checked - len(problems)}/{checked} re-derived from the artefacts")
        for problem in problems:
            print(f"  MISMATCH {problem}")

    report_ok = outcome.get("report", {}).get("figures_missing", 0) == 0
    record_ok = outcome.get("run_report", {}).get("problems", []) == []
    outcome["status"] = "PASS" if report_ok and record_ok else "FAIL"
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    return 0 if outcome["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
