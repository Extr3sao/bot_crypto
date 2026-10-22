"""WP-EDGE-00b independent verifier — the universe-exclusion fix (DEF-WP00-01).

Verification-only, builder != verifier. It re-derives the claim from three
independent sources that the builder cannot all have faked at once:

1. the *persisted artefacts* of a real-data run (traces, run report, daily
   report), parsed with this file's own reader;
2. the *committed source text* of the decision layer, read statically (no
   ``trading_bot`` import, no strategy execution): the branch and the mapping
   the fix claims must actually exist in the files;
3. the *frozen taxonomy*, re-implemented here: which scanner rejections are
   selection decisions and which are data shortfalls.

It then attacks itself: a set of mutations is applied to copies of both the
artefacts and the source tree, and every mutation must be detected. A green
result therefore cannot come from a check that is silently dead.

    python scripts/wp_edge_00b_verify.py [--base reports/edge-recovery]
                                         [--source-root .]

Writes ``WP-EDGE-00b_INDEPENDENT_VERIFICATION.json`` next to the base and prints
a verdict. Exit codes: 0 PASS, 1 FAIL.

Scope honesty: a separate process and a separate implementation, not a different
human or agent. It certifies that the runtime really classified the excluded
asset as a universe no-decision, that the exclusion was not dressed as success,
and that a corrupted artefact or a reverted source is caught. It does not and
cannot certify market performance (this WP produces none).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUN_REL = "runs/WP-EDGE-00b-universe-fix/wp-edge-00b-universe-fix"

#: The chain's genesis token, re-declared here on purpose: the verifier pins the
#: value it expects the store to start from instead of importing the store.
CHAIN_GENESIS = "genesis"

#: Canary the secret control injects into a copy of the evidence. Assembled at
#: runtime so the repository never contains a complete PEM header: secret
#: scanners (GitHub's included) flag the literal even when it is only a fixture.
_SECRET_CANARY = "-----BEGIN RSA" + " PRIVATE KEY-----\nMIIEowIBAAKCAQEA"

#: Scanner rejections that are SELECTION decisions (re-derived, not imported).
UNIVERSE_REJECTIONS = frozenset(
    {
        "not_whitelisted",
        "volume_below_threshold",
        "volume_below_threshold_for_live_min_10M",
        "spread_above_threshold",
        "atr_out_of_range",
        "price_below_threshold",
    }
)
#: Scanner rejections that are DATA shortfalls.
DATA_REJECTIONS = frozenset({"insufficient_history"})

#: Strategic classifications: the strategy itself was the reason (re-derived).
STRATEGIC_CLASSIFICATIONS = frozenset(
    {"COST_KILLED", "NO_ALPHA", "NO_GROSS_EDGE", "NO_PROPOSAL", "NOT_ADMITTED", "UNKNOWN_STRATEGY"}
)

SECRET_PATTERNS = {
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "api_key_literal": re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key)\s*[:=]\s*\S{20,}"
    ),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
    "generic_password": re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
}


def canonical_json(payload: dict[str, Any]) -> str:
    """Same documented canonical form as the runtime, re-implemented here."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def trace_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Suite:
    base: Path
    source_root: Path
    #: Where ``git`` is consulted. This is deliberately NOT ``source_root``: the
    #: negative controls copy the source text into a temp tree, and a check that
    #: failed there only because there is no repository would report a detection
    #: that has nothing to do with the mutation.
    git_root: Path
    checks: list[Check] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name, passed, detail))

    # -- artefact accessors ------------------------------------------------ #
    def run_dir(self) -> Path:
        return self.base / RUN_REL

    def traces(self) -> list[dict[str, Any]]:
        return read_jsonl(self.run_dir() / "traces.jsonl")

    def report(self) -> dict[str, Any]:
        payload: dict[str, Any] = read_json(self.run_dir() / "RUN_REPORT.json")
        return payload

    def daily(self) -> dict[str, Any]:
        payload: dict[str, Any] = read_json(self.run_dir() / "PAPER_DAILY_REPORT.json")
        return payload

    def source(self, rel: str) -> str:
        return (self.source_root / rel).read_text(encoding="utf-8")

    # -- checks ------------------------------------------------------------ #
    def run(self) -> bool:
        for method in (
            self.check_artifacts_present,
            self.check_source_declares_a_universe_class,
            self.check_source_branch_names_the_rejection,
            self.check_universe_is_not_a_data_class,
            self.check_kinds_rederived_from_traces,
            self.check_universe_traces_are_clean,
            self.check_universe_reason_is_the_scanner_one,
            self.check_active_assets_still_evaluated,
            self.check_no_orders_no_trades,
            self.check_trace_chain_intact,
            self.check_run_commit_is_ancestor,
            self.check_no_secret_material,
            self.check_honesty_labels,
        ):
            try:
                method()
            except Exception as exc:  # a missing or malformed artefact IS the failure
                self.record(
                    method.__name__.replace("check_", "").upper(),
                    False,
                    f"raised {type(exc).__name__}: {exc}",
                )
        return all(c.passed for c in self.checks)

    def check_artifacts_present(self) -> None:
        required = (
            self.run_dir() / "traces.jsonl",
            self.run_dir() / "RUN_REPORT.json",
            self.run_dir() / "RUN_REPORT.md",
            self.run_dir() / "PAPER_DAILY_REPORT.json",
        )
        missing = [p.name for p in required if not p.exists()]
        self.record(
            "ARTIFACTS_PRESENT",
            not missing,
            "all required artifacts present" if not missing else f"missing: {missing}",
        )

    def check_source_declares_a_universe_class(self) -> None:
        contracts = self.source("src/trading_bot/autonomous/contracts.py")
        decision = self.source("src/trading_bot/autonomous/decision.py")
        problems: list[str] = []
        if not re.search(r'^    NO_TRADE_UNIVERSE = "NO_TRADE_UNIVERSE"$', contracts, re.M):
            problems.append("contracts.NoTradeKind has no NO_TRADE_UNIVERSE")
        if 'UNIVERSE_FILTERED = "UNIVERSE_FILTERED"' not in decision:
            problems.append("decision.py has no UNIVERSE_FILTERED classification")
        self.record(
            "UNIVERSE_CLASS_DECLARED",
            not problems,
            "universe class + classification declared" if not problems else "; ".join(problems),
        )

    def check_source_branch_names_the_rejection(self) -> None:
        runtime = self.source("src/trading_bot/autonomous/runtime.py")
        problems: list[str] = []
        if 'if not bool(getattr(snap, "active", False)):' not in runtime:
            problems.append("runtime has no inactive-snapshot branch")
        if "classification_for_scanner_rejection" not in runtime:
            problems.append("the branch does not name the scanner rejection")
        if "scanner_rejected:" not in runtime:
            problems.append("the decision reason does not carry the scanner reason")
        # The branch must sit BEFORE the context build, or the old CONTEXT_ERROR
        # path would still win and the fix would be dead code.
        branch_at = runtime.find('if not bool(getattr(snap, "active", False)):')
        context_at = runtime.find("context = self._registry_obj.build_context(")
        if branch_at == -1 or context_at == -1 or branch_at > context_at:
            problems.append("the branch does not precede the context build")
        self.record(
            "UNIVERSE_BRANCH_PRESENT",
            not problems,
            "inactive snapshot short-circuits before the context build"
            if not problems
            else "; ".join(problems),
        )

    def check_universe_is_not_a_data_class(self) -> None:
        """Static taxonomy: the new class is not filed under the data classes."""
        decision = self.source("src/trading_bot/autonomous/decision.py")
        match = re.search(
            r"_DATA_CLASSIFICATIONS[^=]*=\s*frozenset\(\{([^}]*)\}\)", decision, re.S
        )
        if match is None:
            self.record("TAXONOMY_NOT_CONFLATED", False, "could not read _DATA_CLASSIFICATIONS")
            return
        data_classes = {item.strip().strip('"') for item in match.group(1).split(",")}
        problems: list[str] = []
        if "UNIVERSE_FILTERED" in data_classes:
            problems.append("UNIVERSE_FILTERED was added to the data classes")
        if "NO_MARKET_DATA" not in data_classes:
            problems.append("NO_MARKET_DATA is no longer a data class")
        # The universe reasons and the data reasons must stay disjoint.
        overlap = UNIVERSE_REJECTIONS & DATA_REJECTIONS
        if overlap:
            problems.append(f"taxonomy overlap: {sorted(overlap)}")
        self.record(
            "TAXONOMY_NOT_CONFLATED",
            not problems,
            "universe class is separate from the data classes"
            if not problems
            else "; ".join(problems),
        )

    def check_kinds_rederived_from_traces(self) -> None:
        traces = self.traces()
        report = self.report()
        kinds: dict[str, int] = {}
        for trace in traces:
            key = trace.get("no_trade_kind") or "TRADE"
            kinds[key] = kinds.get(key, 0) + 1
        totals = report.get("totals") or {}
        rederived = {
            name: count
            for name, count in kinds.items()
            if totals.get(f"no_trade_{name}") is not None
        }
        problems: list[str] = []
        for name, count in rederived.items():
            if int(totals[f"no_trade_{name}"]) != count:
                problems.append(f"{name}: traces={count} report={totals[f'no_trade_{name}']}")
        if int(totals.get("no_trade_NO_TRADE_UNIVERSE", 0)) < 1:
            problems.append("the run reports no universe exclusion to check")
        if int(totals.get("no_trade_NO_TRADE_DATA", 0)) != 0:
            problems.append("the inactive asset is STILL counted as a data no-decision")
        self.record(
            "KINDS_REDERIVED_FROM_TRACES",
            not problems,
            f"traces={len(traces)} kinds={kinds}"
            if not problems
            else "; ".join(problems),
        )

    def check_universe_traces_are_clean(self) -> None:
        """Every universe no-decision is a clean, named, order-free refusal."""
        problems: list[str] = []
        universe = [t for t in self.traces() if t.get("no_trade_kind") == "NO_TRADE_UNIVERSE"]
        if not universe:
            problems.append("no universe trace to check")
        for trace in universe:
            label = f"{trace.get('asset')}#{trace.get('sequence')}"
            if trace.get("classification") != "UNIVERSE_FILTERED":
                problems.append(f"{label}: classification={trace.get('classification')}")
            if trace.get("order_created") is not False:
                problems.append(f"{label}: order_created={trace.get('order_created')}")
            if trace.get("proposal") is not None:
                problems.append(f"{label}: carries a trade proposal")
            if (trace.get("market_context") or {}).get("active") is not False:
                problems.append(f"{label}: market_context.active is not False")
            if trace.get("verification", {}).get("verdict") == "PASS":
                problems.append(f"{label}: claims a verifier PASS it never had")
        self.record(
            "UNIVERSE_TRACES_CLEAN",
            not problems,
            f"{len(universe)} universe no-decision(s), no orders, no proposals"
            if not problems
            else "; ".join(problems),
        )

    def check_universe_reason_is_the_scanner_one(self) -> None:
        """The classification matches the scanner reason, both directions."""
        problems: list[str] = []
        universe = [t for t in self.traces() if t.get("no_trade_kind") == "NO_TRADE_UNIVERSE"]
        for trace in universe:
            reason = (trace.get("market_context") or {}).get("rejection_reason")
            if reason not in UNIVERSE_REJECTIONS:
                problems.append(f"universe trace carries reason {reason!r}")
            if not str(trace.get("reason", "")).startswith("scanner_rejected:"):
                problems.append(f"reason not attributed to the scanner: {trace.get('reason')!r}")
        # The other direction: a data shortfall must NOT be reported as universe.
        for trace in self.traces():
            reason = (trace.get("market_context") or {}).get("rejection_reason")
            if reason in DATA_REJECTIONS and trace.get("no_trade_kind") != "NO_TRADE_DATA":
                problems.append(f"{trace.get('asset')}: data shortfall not filed as DATA")
        self.record(
            "UNIVERSE_REASON_MATCHES_SCANNER",
            not problems,
            "selection reasons classified as universe; a data shortfall would stay DATA"
            if not problems
            else "; ".join(problems),
        )

    def check_active_assets_still_evaluated(self) -> None:
        """The fix must not have swallowed the normal decision path."""
        problems: list[str] = []
        active = [
            t
            for t in self.traces()
            if (t.get("market_context") or {}).get("active") is True
        ]
        if len(active) < 2:
            problems.append(f"only {len(active)} evaluated active asset(s)")
        for trace in active:
            label = f"{trace.get('asset')}#{trace.get('sequence')}"
            if trace.get("classification") not in STRATEGIC_CLASSIFICATIONS:
                problems.append(f"{label}: classification={trace.get('classification')}")
            if not trace.get("strategies_considered"):
                problems.append(f"{label}: no strategy was considered")
            if trace.get("no_trade_kind") != "NO_TRADE_STRATEGIC":
                problems.append(f"{label}: kind={trace.get('no_trade_kind')}")
        self.record(
            "ACTIVE_ASSETS_STILL_EVALUATED",
            not problems,
            f"{len(active)} active asset-cycles kept their strategic NO_TRADE"
            if not problems
            else "; ".join(problems),
        )

    def check_no_orders_no_trades(self) -> None:
        report = self.report()
        totals = report.get("totals") or {}
        daily = self.daily()
        problems: list[str] = []
        for key in ("orders_created", "paper_trades", "shadow_trades", "runtime_failures"):
            if int(totals.get(key, -1)) != 0:
                problems.append(f"{key}={totals.get(key)}")
        if int(report.get("production_actions", -1)) != 0:
            problems.append(f"production_actions={report.get('production_actions')}")
        if report.get("mode") != "paper":
            problems.append(f"mode={report.get('mode')}")
        if int(daily.get("decisions", 0)) != len(self.traces()):
            problems.append("daily report decision count differs from the traces")
        if any(t.get("order_created") for t in self.traces()):
            problems.append("a trace claims an order")
        self.record(
            "NO_ORDERS_NO_TRADES",
            not problems,
            "0 orders, 0 trades, 0 runtime failures, mode=paper"
            if not problems
            else "; ".join(problems),
        )

    def check_trace_chain_intact(self) -> None:
        traces = self.traces()
        previous = CHAIN_GENESIS
        broken: list[str] = []
        for trace in traces:
            body = dict(trace)
            recorded = str(body.pop("trace_hash", ""))
            prev = str(body.get("prev_hash", ""))
            if prev != previous:
                broken.append(f"{trace.get('decision_id')}: prev_hash mismatch")
            if trace_hash(body) != recorded:
                broken.append(f"{trace.get('decision_id')}: hash mismatch")
            previous = recorded
        runtime_chain = self.report().get("trace_chain") or {}
        if not runtime_chain.get("ok"):
            broken.append("runtime did not report an intact chain")
        self.record(
            "TRACE_CHAIN_INTACT",
            not broken,
            f"{len(traces)} records; recomputed chain intact"
            if not broken
            else "; ".join(broken),
        )

    def check_run_commit_is_ancestor(self) -> None:
        run_commit = str(self.report().get("commit") or "")
        problems: list[str] = []
        if len(run_commit) != 40:
            problems.append(f"run commit malformed: {run_commit!r}")
        else:
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", run_commit, "HEAD"],
                cwd=self.git_root,
                capture_output=True,
                text=True,
            )
            if ancestor.returncode != 0:
                problems.append(f"{run_commit} is not an ancestor of HEAD")
        self.record(
            "RUN_COMMIT_IS_ANCESTOR",
            not problems,
            f"run commit={run_commit[:12]} is an ancestor of HEAD"
            if not problems
            else "; ".join(problems),
        )

    def check_no_secret_material(self) -> None:
        hits: list[str] = []
        for path in sorted(self.run_dir().rglob("*")):
            if not path.is_file() or path.suffix in {".gz", ".zip", ".png", ".jpg"}:
                continue
            text = path.read_bytes().decode("utf-8", errors="replace")
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    hits.append(f"{path.name}:{name}")
        self.record(
            "NO_SECRET_MATERIAL",
            not hits,
            "no secret-shaped material in the run evidence" if not hits else f"hits: {hits}",
        )

    def check_honesty_labels(self) -> None:
        report = self.report()
        text = (self.run_dir() / "RUN_REPORT.md").read_text(encoding="utf-8")
        problems: list[str] = []
        if report.get("environment") != "ccxt:binance":
            problems.append(f"environment is not the real provider: {report.get('environment')}")
        if re.search(r"\bPROFITABLE\b", text, re.IGNORECASE):
            problems.append("the generated report claims profitability")
        if "NO_TRADE_UNIVERSE" not in text:
            problems.append("the generated report does not show the universe no-decision")
        self.record(
            "HONESTY_LABELS",
            not problems,
            "real-data run, universe no-decision visible, no profitability claim"
            if not problems
            else "; ".join(problems),
        )


# --------------------------------------------------------------------------- #
# negative controls: mutate a copy, expect the suite to fail
# --------------------------------------------------------------------------- #


def copy_tree(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wp00b-negative-"))
    shutil.copytree(src, tmp / "edge-recovery")
    return tmp / "edge-recovery"


def mutate(path: Path, fn: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = fn(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mutate_jsonl(path: Path, fn: Any) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rows = fn(rows)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _copy_source(root: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wp00b-source-"))
    target = tmp / "src/trading_bot/autonomous"
    target.mkdir(parents=True)
    for name in ("contracts.py", "decision.py", "runtime.py"):
        shutil.copy2(root / "src/trading_bot/autonomous" / name, target / name)
    return tmp


def negative_controls(base: Path, source_root: Path, git_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def verdict(mutated_base: Path, mutated_source: Path) -> bool:
        return Suite(
            base=mutated_base, source_root=mutated_source, git_root=git_root
        ).run()

    def control(name: str, mutate_fn: Any) -> None:
        copy = copy_tree(base)
        source = _copy_source(source_root)
        try:
            mutate_fn(copy, source)
            detected = not verdict(copy, source)
        except Exception:
            detected = True
        finally:
            shutil.rmtree(copy.parent, ignore_errors=True)
            shutil.rmtree(source, ignore_errors=True)
        results.append({"name": name, "detected": detected})

    def swap_kind(base_dir: Path, _src: Path) -> None:
        def apply(data: dict[str, Any]) -> dict[str, Any]:
            totals = dict(data["totals"])
            totals["no_trade_NO_TRADE_DATA"] = totals["no_trade_NO_TRADE_UNIVERSE"]
            totals["no_trade_NO_TRADE_UNIVERSE"] = 0
            return {**data, "totals": totals}

        mutate(base_dir / RUN_REL / "RUN_REPORT.json", apply)

    def reclassify_trace(base_dir: Path, _src: Path) -> None:
        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for row in rows:
                if row.get("no_trade_kind") == "NO_TRADE_UNIVERSE":
                    row["classification"] = "CONTEXT_ERROR"
                    break
            return rows

        mutate_jsonl(base_dir / RUN_REL / "traces.jsonl", apply)

    def inject_order_in_universe_trace(base_dir: Path, _src: Path) -> None:
        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for row in rows:
                if row.get("no_trade_kind") == "NO_TRADE_UNIVERSE":
                    row["order_created"] = True
                    break
            return rows

        mutate_jsonl(base_dir / RUN_REL / "traces.jsonl", apply)

    def call_a_strategic_trace_universe(base_dir: Path, _src: Path) -> None:
        def apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for row in rows:
                if row.get("no_trade_kind") == "NO_TRADE_STRATEGIC":
                    row["no_trade_kind"] = "NO_TRADE_UNIVERSE"
                    break
            return rows

        mutate_jsonl(base_dir / RUN_REL / "traces.jsonl", apply)

    def remove_the_source_branch(base_dir: Path, src: Path) -> None:
        path = src / "src/trading_bot/autonomous/runtime.py"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace('if not bool(getattr(snap, "active", False)):', "if False:"),
            encoding="utf-8",
        )

    def revert_the_classification(base_dir: Path, src: Path) -> None:
        path = src / "src/trading_bot/autonomous/decision.py"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('UNIVERSE_FILTERED = "UNIVERSE_FILTERED"', ""), encoding="utf-8")

    def inject_secret(base_dir: Path, _src: Path) -> None:
        path = base_dir / RUN_REL / "RUN_REPORT.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n" + _SECRET_CANARY + "\n",
            encoding="utf-8",
        )

    control("kind_swapped_to_data", swap_kind)
    control("universe_trace_reclassified", reclassify_trace)
    control("order_injected_in_universe_trace", inject_order_in_universe_trace)
    control("strategic_trace_called_universe", call_a_strategic_trace_universe)
    control("source_branch_neutralised", remove_the_source_branch)
    control("classification_reverted", revert_the_classification)
    control("secret_injected", inject_secret)
    return results


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="reports/edge-recovery")
    parser.add_argument("--source-root", default=".")
    args = parser.parse_args(argv)

    base = Path(args.base).resolve()
    source_root = Path(args.source_root).resolve()
    git_root = Path(__file__).resolve().parents[1]
    suite = Suite(base=base, source_root=source_root, git_root=git_root)
    ok = suite.run()
    controls = negative_controls(base, source_root, git_root)
    detected = sum(1 for c in controls if c["detected"])
    false_success = len(controls) - detected

    payload = {
        "artifact": "WP-EDGE-00b-INDEPENDENT-VERIFICATION",
        "claim": "an asset excluded by the scanner's universe filters is reported as a "
        "selection no-decision (NO_TRADE_UNIVERSE), not as a data outage (NO_TRADE_DATA)",
        "verifier": "scripts/wp_edge_00b_verify.py (separate process, artifact + source text, "
        "no runtime imports)",
        "generated_at_utc": __import__("datetime")
        .datetime.now(__import__("datetime").UTC)
        .isoformat(),
        "base": str(base),
        "run": RUN_REL,
        "source_root": str(source_root),
        "checks_passed": sum(1 for c in suite.checks if c.passed),
        "checks_total": len(suite.checks),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in suite.checks],
        "negative_controls_detected": detected,
        "negative_controls_total": len(controls),
        "negative_controls": controls,
        "false_success": false_success,
        "verdict": "PASS" if ok and false_success == 0 else "FAIL",
        "limitations": [
            "Separate process/implementation, not a different human or agent.",
            "Verifies the classification and the persisted evidence; it cannot certify "
            "profitability, and this run produces none.",
            "The source checks are static (text/AST-free) reads of three files, so they "
            "prove the branch exists, not that every call path reaches it.",
        ],
    }
    out = base / "WP-EDGE-00b_INDEPENDENT_VERIFICATION.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for check in suite.checks:
        print(f"[{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
    for control in controls:
        print(f"[{'SEEN' if control['detected'] else 'MISSED'}] negative: {control['name']}")
    print(
        f"-> {payload['verdict']} checks={payload['checks_passed']}/{payload['checks_total']} "
        f"negative={detected}/{len(controls)} false_success={false_success} :: {out}"
    )
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
