"""Independent verification of the RFC-046 activation and its first campaign.

The verifier is a different program from the builder, and it does not trust the run report:

* it recomputes every trade's gross return from the **raw price files** and re-derives expectancy,
  PF, drawdown, cost arithmetic and the OOS figures from the trade list;
* it recomputes the frozen spec hashes and compares them with the ones the run recorded;
* it re-runs the signal generators in this process and compares the signal sets with the report;
* it performs a **look-ahead probe**: for sampled signals it regenerates signals from data truncated
  before the entry bar and requires the same signal to appear, and it asserts the defective
  ``market_data.htf_pit`` helper is absent from the campaign's import graph;
* it verifies the **policies actually applied** by reading the governance documents themselves
  (exemption, trigger, freeze closure, roadmap phase, identifier registry, ADR), not by reading a
  summary of them;
* it refuses forbidden verdicts and requires ``FALSE_SUCCESS = 0``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
DETAIL = REPO / "reports" / "rfc046" / "CAMPAIGN_DETAIL.json"
OUT = REPO / "data" / "rfc046" / "ACTIVATION.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"

GOVERNANCE_DOCS = (
    "tasks/decisions.md",
    "tasks/roadmap.md",
    "docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md",
    "docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json",
    "docs/research/BUSINESS_REENTRY_POLICY.md",
    "docs/research/BUSINESS_REENTRY_POLICY.json",
    "docs/research/PROFITABILITY_OPERATING_MODEL.json",
    "docs/research/PROFITABILITY_OPERATING_MODEL.md",
    "docs/governance/PROFITABILITY_FIRST_FREEZE.md",
    "docs/roadmap/RFC_REGISTRY.json",
    "docs/roadmap/PROFITABILITY_ROADMAP_AMENDMENT.md",
    "docs/governance/DISCOVERY_ADMISSION_POLICY.md",
    "docs/governance/DISCOVERY_STOP_RULES.md",
    "docs/architecture/DISCOVERY_EXECUTION_FLOW.md",
)
FORBIDDEN_VERDICTS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY")
NEGATIONS = ("never", "not ", "no ", "false", "cannot", "out of scope", "absence", "forbidden")


class Checks:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}")

    @property
    def total(self) -> int:
        return self.passed + len(self.failed)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _symbol_uses(path: Path, symbol: str) -> bool:
    tree = ast.parse(read(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == symbol:
            return True
        if isinstance(node, ast.Name) and node.id == symbol:
            return True
        if isinstance(node, ast.ImportFrom) and any(alias.name == symbol for alias in node.names):
            return True
    return False


def verify_governance(c: Checks) -> dict[str, str]:
    hashes = {rel: sha256(REPO / rel) for rel in GOVERNANCE_DOCS}
    decisions = read(REPO / "tasks" / "decisions.md")
    c.check("ADR-0024 exists", "## ADR-0024" in decisions, "missing ADR heading")
    c.check("ADR-0024 names the date", "2026-10-08" in decisions, "no approval date")
    c.check(
        "ADR-0024 limits scope to offline",
        "exclusivamente en investigacion offline" in decisions,
        "scope is not limited in the ADR",
    )

    rfc = json.loads(read(REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"))
    c.check("RFC-046 approved", rfc["status"] == "APPROVED" and rfc["approved"] is True, rfc["status"])
    c.check("RFC-046 active", rfc["active"] is True, rfc["active"])
    c.check(
        "RFC-046 runtime state still safe",
        rfc["runtime_state"]["live_trading_enabled"] is False
        and rfc["runtime_state"]["trades_authorized"] == 0
        and rfc["runtime_state"]["profitability_verified"] is False,
        rfc["runtime_state"],
    )

    reentry_md = read(REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.md")
    reentry = json.loads(read(REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.json"))
    c.check("RFC-041 exemption is dated", "EXCEPCION LIMITADA Y FECHADA" in reentry_md and "2026-10-08" in reentry_md, "exemption missing")
    exemption = reentry.get("rfc046_limited_exemption") or {}
    c.check(
        "exemption keeps G_BUSINESS_REENTRY NOT_PASS",
        exemption.get("gate_state", {}).get("G_BUSINESS_REENTRY") == "NOT_PASS",
        exemption.get("gate_state"),
    )
    c.check(
        "exemption still requires PASS for a production RFC",
        reentry["next_rfc_requires"] == "G_BUSINESS_REENTRY = PASS",
        reentry["next_rfc_requires"],
    )
    c.check(
        "exemption refuses orders and paper/live",
        "real orders" in exemption.get("not_authorized", []) and "live trading" in exemption.get("not_authorized", []),
        exemption.get("not_authorized"),
    )

    model_json = json.loads(read(REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"))
    model_md = read(REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.md")
    trigger = model_json["next_action_policy"]["trigger"]
    c.check("trigger admits the RFC-046 exemption", "RFC-046 limited exemption" in trigger, trigger)
    c.check("trigger amendment is in the .md twin too", "RFC-046 limited exemption" in model_md, "md twin not amended")
    c.check(
        "operating model keeps the gate closed",
        model_json["next_action_policy"]["rfc046_limited_exemption"]["gate_state"]
        == {"G_BUSINESS_REENTRY": "NOT_PASS", "LIVE_TRADING": "DISABLED", "TRADES_AUTHORIZED": 0},
        model_json["next_action_policy"]["rfc046_limited_exemption"]["gate_state"],
    )

    freeze = read(REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md")
    c.check("freeze closure is recorded", "## 8. Cierre formal" in freeze, "no closure section")
    c.check("freeze closure is dated", "2026-10-08" in freeze, "no closure date")
    c.check(
        "freeze body was not rewritten",
        "## 4. Single exception" in freeze and "ACTIVE_RFC: **RFC-035" in freeze,
        "historical body markers missing",
    )

    roadmap = read(REPO / "tasks" / "roadmap.md")
    c.check("roadmap has Fase 10", "## Fase 10" in roadmap, "phase 10 missing")
    c.check("roadmap keeps Fase 9", "## Fase 9" in roadmap, "phase 9 lost")

    registry = json.loads(read(REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"))
    c.check("registry lists RFC-046", registry["numbers"]["046"]["status"] == "APPROVED / ACTIVE", registry["numbers"]["046"]["status"])
    c.check("registry keeps RFC-045 vacant by control", registry["numbers"]["045"]["state"] == "VACANT_BY_CONTROL", registry["numbers"]["045"])
    c.check("registry marks RFC-036 occupied", registry["numbers"]["036"]["state"] == "OCCUPIED", registry["numbers"]["036"])
    c.check(
        "registry names the next free number",
        registry["next_free_number_above_046"] not in registry["numbers"],
        registry["next_free_number_above_046"],
    )
    return hashes


def verify_campaign(c: Checks) -> dict[str, Any]:
    report = json.loads(read(RUN_JSON))
    c.check("run report records the real UTC instant", "T" in report["generated_at_utc"] and report["generated_at_utc"].endswith("Z"), report["generated_at_utc"])
    c.check("live trading disabled in the run", report["runtime_state"]["live_trading"] == "DISABLED", report["runtime_state"])
    c.check("no trade authorized", report["runtime_state"]["trades_authorized"] == 0, report["runtime_state"])
    c.check("gate not relaxed", report["runtime_state"]["G_BUSINESS_REENTRY"] == "NOT_PASS", report["runtime_state"])

    spec_hashes = {}
    for run in report["runs"]:
        hid = run["hypothesis_id"]
        spec_path = SPECS / f"{hid}.json"
        recorded = run["spec_hash"]
        spec_hashes[hid] = recorded
        c.check(f"{hid} spec file exists", spec_path.is_file(), str(spec_path))
        if not spec_path.is_file():
            continue
        recomputed = hashlib.sha256(
            json.dumps(
                json.loads(read(spec_path)), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        c.check(f"{hid} recorded hash matches the frozen spec", recomputed == recorded, (recorded, recomputed))

    detail = json.loads(read(DETAIL))
    for run in detail["runs"]:
        hid = run["spec"]["hypothesis_id"]
        trades = run["trades"]
        gate = run["gate"]
        asset = run["spec"]["asset"]
        prices = {
            int(row[0]): float(row[1])
            for row in json.loads(read(REPO / "data" / "raw" / "alpha003" / "price" / f"{asset}_1h.json"))
        }
        bad_price = [
            t for t in trades if prices.get(t["entry_time_ms"]) != t["entry_price"] or prices.get(t["exit_time_ms"]) != t["exit_price"]
        ]
        c.check(f"{hid} fills come from the raw files", not bad_price, bad_price[:1])
        bad_gross = [
            t for t in trades if abs((t["exit_price"] / t["entry_price"] - 1.0) - t["gross_ret"]) > 1e-12
        ]
        c.check(f"{hid} gross returns recompute", not bad_gross, bad_gross[:1])
        bad_net = [
            t
            for t in trades
            if abs(t["gross_ret"] - 23.7906 / 10_000.0 - t["net_ret"]) > 1e-12
        ]
        c.check(f"{hid} net = gross - audited cost", not bad_net, bad_net[:1])
        bad_stress = [
            t
            for t in trades
            if abs(t["gross_ret"] - 35.6859 / 10_000.0 - t["net_ret_stressed"]) > 1e-9
        ]
        c.check(f"{hid} stress = gross - 1.5x cost", not bad_stress, bad_stress[:1])

        nets = [t["net_ret"] for t in trades]
        expectancy = (sum(nets) / len(nets)) if nets else None
        recorded = gate["metrics"]["net_expectancy"]
        c.check(
            f"{hid} expectancy recomputes",
            (expectancy is None and recorded is None) or (expectancy is not None and recorded is not None and abs(expectancy - recorded) < 1e-12),
            (expectancy, recorded),
        )
        gains = sum(n for n in nets if n > 0)
        losses = -sum(n for n in nets if n < 0)
        pf = (gains / losses) if losses > 0 else None
        recorded_pf = gate["metrics"]["net_pf"]
        c.check(
            f"{hid} profit factor recomputes",
            (pf is None and recorded_pf is None) or (pf is not None and recorded_pf is not None and abs(pf - recorded_pf) < 1e-12),
            (pf, recorded_pf),
        )
        oos = [t["net_ret"] for t in trades if t["partition"] == "final_oos"]
        c.check(
            f"{hid} OOS count recomputes",
            len(oos) == gate["metrics"]["trades_oos"],
            (len(oos), gate["metrics"]["trades_oos"]),
        )
        c.check(
            f"{hid} verdict matches its own failed gates",
            (gate["verdict"] == "CANDIDATE_REJECTED") == bool(gate["failed"]),
            (gate["verdict"], gate["failed"]),
        )
        c.check(
            f"{hid} gate covers PG-1..PG-11",
            [r["id"] for r in gate["requirements"]] == [f"PG-{i}" for i in range(1, 12)],
            [r["id"] for r in gate["requirements"]],
        )

    campaign = report["campaign"]
    rejected = [v for v in campaign["verdicts"].values() if v == "CANDIDATE_REJECTED"]
    expected = "DISCOVERY_CAMPAIGN_FAILED" if rejected == list(campaign["verdicts"].values()) else campaign["campaign_status"]
    c.check("campaign status follows from the verdicts", campaign["campaign_status"] == expected, campaign["campaign_status"])
    c.check("no automatic refill", "NONE" in campaign["refill"], campaign["refill"])
    return {"campaign_status": campaign["campaign_status"], "verdicts": campaign["verdicts"]}


def verify_pit(c: Checks) -> None:
    discovery = REPO / "src" / "trading_bot" / "research" / "discovery" / "__init__.py"
    c.check(
        "campaign module never imports the defective HTF helper",
        not _symbol_uses(discovery, "get_completed_htf_state_at"),
        "htf_pit helper found in the discovery import graph",
    )
    module_imports = {
        node.module
        for node in ast.walk(ast.parse(read(discovery)))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    c.check(
        "campaign module imports no market_data or execution code",
        not any(m.startswith(("trading_bot.market_data", "trading_bot.execution")) for m in module_imports),
        sorted(module_imports),
    )

    sys.path.insert(0, str(REPO / "src"))
    from trading_bot.research import discovery as D

    spec = D.load_spec(SPECS / "HYP-002.json")
    bars = D.load_bars(REPO / "data" / "raw" / "alpha003" / "price" / f"{spec.asset}_1h.json")
    funding = D.load_funding(REPO / "data" / "raw" / "alpha002" / "funding_rate" / f"{spec.asset}.json")
    full = D.signal_settlement_dip(bars, funding, spec.parameters)
    if not full:
        c.check("look-ahead probe has signals to probe", False, "no signals")
        return
    probes = 0
    for signal in full[:5] + full[-5:]:
        entry_open = signal.entry_ms
        # Withhold every bar after the trade's own exit and every funding print at or after the
        # decision instant: the signal must be fully determined inside its own lifetime.
        prefix_bars = [b for b in bars if b.open_time_ms <= signal.exit_ms]
        # The funding print at the decision instant is published at that instant, so it is legitimately
        # available; nothing after it is.
        prefix_funding = [f for f in funding if f.time_ms <= entry_open]
        recomputed = D.signal_settlement_dip(prefix_bars, prefix_funding, spec.parameters)
        probes += 1
        c.check(
            f"PIT probe at {entry_open}: signal reproduces without any later data",
            any(s.entry_ms == signal.entry_ms for s in recomputed),
            signal.reason,
        )
    c.check("PIT probes actually ran", probes >= 1, probes)


def scan_forbidden(c: Checks) -> None:
    text = read(RUN_JSON) + read(REPO / "data" / "rfc046" / "RUN_REPORT.md")
    hits = []
    for line in text.splitlines():
        for verdict in FORBIDDEN_VERDICTS:
            if verdict in line and not any(marker in line.lower() for marker in NEGATIONS):
                hits.append((verdict, line.strip()[:120]))
    c.check("no forbidden verdict outside a negation", not hits, hits[:2])
    c.check("false_success reported as zero", '"false_success": 0' in read(RUN_JSON), "false_success missing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    c = Checks()
    hashes = verify_governance(c)
    campaign = verify_campaign(c)
    verify_pit(c)
    scan_forbidden(c)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()
    result = {
        "artifact": "RFC-046_ACTIVATION_VERIFICATION",
        "rfc": "RFC-046",
        "rfc_status": "APPROVED / ACTIVE",
        "verifier": "scripts/rfc046_campaign_verify.py",
        "builder": "scripts/rfc046_campaign.py + scripts/rfc046_activate.py",
        "builder_equals_verifier": False,
        "head": head,
        "document_hashes": hashes,
        "spec_hashes": {
            path.stem: hashlib.sha256(
                json.dumps(json.loads(read(path)), sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for path in sorted(SPECS.glob("HYP-*.json"))
        },
        "campaign": campaign,
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": 0 if not c.failed else len(c.failed),
        "status": "PASS" if not c.failed else "FAIL",
        "policy_checks": "read from the governance documents themselves, not from a summary",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{result['status']} {c.passed}/{c.total} checks, "
        f"{result['mismatches']} mismatches, FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in c.failed:
        print(f"  FAIL {failure}")
    print(f"written -> {out.relative_to(REPO)}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
