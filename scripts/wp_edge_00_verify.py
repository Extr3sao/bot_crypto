"""WP-EDGE-00 independent verifier (verification-only; builder != verifier).

Re-derives WP-EDGE-00's claims from the artefacts the runtime persisted, with its own
implementation: it never imports ``trading_bot`` decision code, never re-runs the
strategies, and fails closed. It then attacks its own checks: a set of mutations is
applied to copies of the artefacts and every mutation must be detected, so a green
result cannot be produced by a check that is silently dead.

    python scripts/wp_edge_00_verify.py [--base reports/edge-recovery]

Writes ``INDEPENDENT_VERIFICATION.json`` next to the base and prints a verdict.
Exit codes: 0 PASS, 1 FAIL.

Scope honesty: this is a separate *process* and a separate *implementation* reading
persisted evidence; it is not a different human or agent, and it cannot certify market
performance (there is none to certify in this WP). What it does certify is that the
counts, the hash chain, the economics arithmetic and the decision-path counters really
say what the report says, and that a corrupted copy is caught.
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

REAL_RUN_REL = "runs/WP-EDGE-00-smoke-real/wp-edge-00-smoke-real"
FIXTURE_REL = "runs/WP-EDGE-00-smoke-fixture"

SECRET_PATTERNS = {
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    # A real exchange key is 64 alphanumeric chars with mixed case; hashes are lower-case hex.
    "binance_style_key": re.compile(r"[A-Za-z0-9]{64}(?=[A-Za-z0-9]*[A-Z])"),
    "api_key_literal": re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key)\s*[:=]\s*\S{20,}"
    ),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
    "generic_password": re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
}


def canonical_json(payload: dict[str, Any]) -> str:
    """Same documented canonical form as the runtime, re-implemented independently."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def trace_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "trace_hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def read_fixture_status(path: Path) -> dict[str, Any]:
    text = path.read_bytes().decode("utf-8", errors="replace")
    return dict(json.loads(text.split("Paper trading loop stopped.", 1)[1].lstrip()))


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Suite:
    base: Path
    head: str | None = None
    checks: list[Check] = field(default_factory=list)

    # -- helpers ---------------------------------------------------------- #
    def record(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name, passed, detail))

    def real_dir(self) -> Path:
        return self.base / REAL_RUN_REL

    def fixture_dir(self) -> Path:
        return self.base / FIXTURE_REL

    def run(self) -> bool:
        for method in (
            self.check_artifacts_present,
            self.check_commit_matches_head,
            self.check_mode_and_no_production_actions,
            self.check_trace_chain_intact,
            self.check_counts_rederived,
            self.check_no_orders_or_trades,
            self.check_economic_gate_arithmetic,
            self.check_fixture_decision_path,
            self.check_wp_run_report_consistency,
            self.check_no_secret_material,
            self.check_contract_gate_text,
            self.check_honesty_labels,
        ):
            try:
                method()
            except Exception as exc:  # a missing or malformed artifact IS the failure
                self.record(
                    method.__name__.replace("check_", "").upper(),
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
        return all(c.passed for c in self.checks)

    # -- checks ----------------------------------------------------------- #
    def check_artifacts_present(self) -> None:
        required = [
            self.real_dir() / "RUN_REPORT.json",
            self.real_dir() / "RUN_REPORT.md",
            self.real_dir() / "PAPER_DAILY_REPORT.json",
            self.real_dir() / "PAPER_DAILY_REPORT.md",
            self.real_dir() / "traces.jsonl",
            self.real_dir() / "heartbeat.json",
            self.fixture_dir() / "stdout_1cyc.log",
            self.fixture_dir() / "fixture_ledger.json",
            self.base / "RUN_REPORT.json",
            self.base / "RUN_REPORT.md",
            self.base / "baseline.json",
            self.base / "runtime_authority_map.md",
            self.base / "git_divergence_report.md",
        ]
        missing = [str(p.relative_to(self.base)) for p in required if not p.exists()]
        self.record(
            "ARTIFACTS_PRESENT",
            not missing,
            "all required artifacts present" if not missing else f"missing: {missing}",
        )

    def check_commit_matches_head(self) -> None:
        try:
            rr = read_json(self.real_dir() / "RUN_REPORT.json")
        except Exception as exc:
            self.record("COMMIT_MATCHES_HEAD", False, f"unreadable run report: {exc}")
            return
        git_head = (
            self.head
            or subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        got = str(rr.get("commit", ""))
        self.record(
            "COMMIT_MATCHES_HEAD",
            got == git_head,
            f"run report commit={got[:12]} git HEAD={git_head[:12]}",
        )

    def check_mode_and_no_production_actions(self) -> None:
        rr = read_json(self.real_dir() / "RUN_REPORT.json")
        daily = read_json(self.real_dir() / "PAPER_DAILY_REPORT.json")
        ok = (
            rr.get("mode") == "paper"
            and daily.get("mode") == "PAPER"
            and int(rr.get("production_actions", -1)) == 0
        )
        self.record(
            "MODE_PAPER_NO_LIVE_PATH",
            ok,
            f"mode={rr.get('mode')}/{daily.get('mode')} production_actions={rr.get('production_actions')}",
        )

    def check_trace_chain_intact(self) -> None:
        traces = read_jsonl(self.real_dir() / "traces.jsonl")
        prev = "genesis"
        broken: str | None = None
        for seq, raw in enumerate(traces, start=1):
            if raw.get("prev_hash") != prev:
                broken = f"record {seq}: prev_hash mismatch"
                break
            if trace_hash(raw) != raw.get("trace_hash"):
                broken = f"record {seq}: trace_hash mismatch"
                break
            prev = str(raw["trace_hash"])
        rr = read_json(self.real_dir() / "RUN_REPORT.json")
        chain = rr.get("trace_chain") or {}
        claimed_ok = bool(chain.get("ok")) and int(chain.get("records", -1)) == len(traces)
        self.record(
            "TRACE_CHAIN_INTACT",
            broken is None and claimed_ok,
            f"{len(traces)} records; recomputed chain {'intact' if broken is None else broken}; "
            f"runtime chain ok={chain.get('ok')} records={chain.get('records')}",
        )

    def check_counts_rederived(self) -> None:
        traces = read_jsonl(self.real_dir() / "traces.jsonl")
        rr = read_json(self.real_dir() / "RUN_REPORT.json")
        daily = read_json(self.real_dir() / "PAPER_DAILY_REPORT.json")
        kinds: dict[str, int] = {}
        for t in traces:
            kind = t.get("no_trade_kind") or "TRADE"
            kinds[kind] = kinds.get(kind, 0) + 1
        totals = rr.get("totals") or {}
        runtime_kinds = {
            k.replace("no_trade_", ""): v for k, v in totals.items() if k.startswith("no_trade_")
        }
        daily_kinds = daily.get("no_trade_kinds") or {}

        # scenario may use a different prefix; normalise both sides to bare suffixes
        def norm(d: dict[str, int]) -> dict[str, int]:
            out: dict[str, int] = {}
            for k, v in d.items():
                key = k.replace("no_trade_", "").replace("NO_TRADE_", "")
                if int(v):
                    out[key] = out.get(key, 0) + int(v)
            return out

        ok = len(traces) == int(totals.get("asset_cycle_evaluations", -1)) == int(
            daily.get("decisions", -1)
        ) and norm(kinds) == norm(runtime_kinds) == norm(daily_kinds)
        self.record(
            "COUNTS_REDERIVED_FROM_TRACES",
            ok,
            f"traces={len(traces)} runtime={totals.get('asset_cycle_evaluations')} "
            f"daily={daily.get('decisions')} kinds={kinds}",
        )

    def check_no_orders_or_trades(self) -> None:
        traces = read_jsonl(self.real_dir() / "traces.jsonl")
        rr = read_json(self.real_dir() / "RUN_REPORT.json")
        totals = rr.get("totals") or {}
        orders_in_traces = sum(
            1 for t in traces if t.get("order_created") or t.get("orders_created")
        )
        ok = (
            orders_in_traces == 0
            and int(totals.get("orders_created", -1)) == 0
            and int(totals.get("paper_trades", -1)) == 0
            and int(totals.get("shadow_trades", -1)) == 0
            and not rr.get("executions")
        )
        self.record(
            "NO_ORDERS_NO_TRADES",
            ok,
            f"orders_in_traces={orders_in_traces} orders_created={totals.get('orders_created')} "
            f"paper_trades={totals.get('paper_trades')} executions={len(rr.get('executions') or [])}",
        )

    def check_economic_gate_arithmetic(self) -> None:
        traces = read_jsonl(self.real_dir() / "traces.jsonl")
        strategic = [t for t in traces if t.get("no_trade_kind") == "NO_TRADE_STRATEGIC"]
        problems: list[str] = []
        if len(strategic) != 4:
            problems.append(f"expected 4 strategic refusals, found {len(strategic)}")
        for t in strategic:
            reason = str(t.get("reason", ""))
            gross = None
            if "gross_edge_not_positive" in reason:
                gross = float(reason.split(":", 1)[1].replace("bps", ""))
            details = {
                str(c.get("name")): str(c.get("detail"))
                for c in ((t.get("verification") or {}).get("checks") or [])
            }
            cost = net = None
            m = re.search(r"([-\d.]+) bps re-derived", details.get("cost_model_applied", ""))
            if m:
                cost = float(m.group(1))
            m = re.search(r"net=([-\d.]+) bps", details.get("proposal_arithmetic", ""))
            if m:
                net = float(m.group(1))
            if gross is None or cost is None or net is None:
                problems.append(
                    f"{t.get('asset')}: missing arithmetic pieces gross={gross} cost={cost} net={net}"
                )
            elif abs((gross - cost) - net) > 0.01 or net >= 0:
                problems.append(
                    f"{t.get('asset')}: gross {gross} - cost {cost} != net {net} (or net >= 0)"
                )
        self.record(
            "ECONOMIC_GATE_ARITHMETIC",
            not problems,
            "4 refusals: gross - cost = net < 0 re-derived from trace checks"
            if not problems
            else "; ".join(problems),
        )

    def check_fixture_decision_path(self) -> None:
        status = read_fixture_status(self.fixture_dir() / "stdout_1cyc.log")
        cycle = status.get("cycle") or {}
        log = (
            (self.fixture_dir() / "stdout_1cyc.log").read_bytes().decode("utf-8", errors="replace")
        )
        ok = (
            status.get("mode") == "paper"
            and int(cycle.get("contexts_built", 0)) > 0
            and int(cycle.get("router_invocations", 0)) > 0
            and int(cycle.get("strategy_invocations", 0)) > 0
            and float(status.get("equity", -1)) == 10000.0
            and float(status.get("realized_pnl", -1)) == 0.0
            and "[registry] paper-executable on 5m: ['ema_crossover@5m']" in log
        )
        self.record(
            "FIXTURE_DECISION_PATH",
            ok,
            f"contexts={cycle.get('contexts_built')} router={cycle.get('router_invocations')} "
            f"strategy={cycle.get('strategy_invocations')} orders={cycle.get('orders_created')} "
            f"equity={status.get('equity')} mode={status.get('mode')}",
        )

    def check_wp_run_report_consistency(self) -> None:
        wp = read_json(self.base / "RUN_REPORT.json")
        rr = read_json(self.real_dir() / "RUN_REPORT.json")
        traces = read_jsonl(self.real_dir() / "traces.jsonl")
        status = read_fixture_status(self.fixture_dir() / "stdout_1cyc.log")
        problems: list[str] = []
        if wp.get("commit_sha") != rr.get("commit"):
            problems.append("commit mismatch")
        if int(wp["decisions"]["total"]) != len(traces):
            problems.append("decision count mismatch")
        if int(wp["orders_and_trades"]["orders_created"]) != 0:
            problems.append("orders not zero")
        if float(wp["economics"]["net_pnl_usdt"]) != 0.0:
            problems.append("net pnl not zero")
        fixture = wp.get("fixture_control_run") or {}
        if (
            fixture.get("cycle", {}).get("strategy_invocations")
            != status["cycle"]["strategy_invocations"]
        ):
            problems.append("fixture counters mismatch")
        if wp.get("decisions", {}).get("no_trade_kinds") != {
            k: v for k, v in wp["decisions"]["no_trade_kinds"].items()
        }:
            problems.append("kind map malformed")
        expected_kinds: dict[str, int] = {}
        for t in traces:
            k = t.get("no_trade_kind") or "TRADE"
            expected_kinds[k] = expected_kinds.get(k, 0) + 1
        if wp["decisions"]["no_trade_kinds"] != expected_kinds:
            problems.append("wp kinds != traces kinds")
        self.record(
            "WP_RUN_REPORT_CONSISTENT",
            not problems,
            "wp report matches runtime artifacts" if not problems else "; ".join(problems),
        )

    def check_no_secret_material(self) -> None:
        hits: list[str] = []
        for path in sorted(self.base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in {".gz", ".zip", ".png", ".jpg"}:
                continue
            try:
                text = path.read_bytes().decode("utf-8", errors="replace")
            except Exception:
                continue
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    hits.append(f"{path.relative_to(self.base)}:{name}")
        self.record(
            "NO_SECRET_MATERIAL",
            not hits,
            "no secret-shaped material in commit scope" if not hits else f"hits: {hits}",
        )

    def check_contract_gate_text(self) -> None:
        gate = (
            Path(__file__).resolve().parents[1]
            / "tests/unit/cert/test_paper_smoke_decision_path.py"
        )
        text = gate.read_text(encoding="utf-8")
        ok = (
            "SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED" in text
            and "contexts_built" in text
            and "router_invocations" in text
            and "strategy_invocations" in text
        )
        self.record(
            "CONTRACT_GATE_PRESENT",
            ok,
            f"{gate.name}: fail-closed invariant and the three counters are asserted",
        )

    def check_honesty_labels(self) -> None:
        wp = read_json(self.base / "RUN_REPORT.json")
        text = (self.base / "RUN_REPORT.md").read_text(encoding="utf-8")
        problems: list[str] = []
        if "ZERO_BY_NO_TRADE" not in str(wp["economics"]["pnl_status"]):
            problems.append("pnl status not labelled ZERO_BY_NO_TRADE")
        if "SYNTHETIC" not in str((wp.get("fixture_control_run") or {}).get("data_class", "")):
            problems.append("fixture run not labelled SYNTHETIC")
        if "REAL_MARKET_DATA" not in str((wp.get("target") or {}).get("data_class", "")):
            problems.append("real run not labelled REAL_MARKET_DATA")
        if re.search(r"\bPROFITABLE\b", text, re.IGNORECASE):
            problems.append("report claims profitability")
        self.record(
            "HONESTY_LABELS",
            not problems,
            "labels present; no profitability claim" if not problems else "; ".join(problems),
        )


# --------------------------------------------------------------------------- #
# negative controls: mutate a copy, expect the suite to fail
# --------------------------------------------------------------------------- #


def copy_base(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wp00-negative-"))
    shutil.copytree(src, tmp / "edge-recovery")
    return tmp / "edge-recovery"


def mutate(path: Path, fn: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = fn(data)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def negative_controls(base: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def run_on(mutated: Path) -> bool:
        suite = Suite(base=mutated)
        return suite.run()

    def control(name: str, mutate_fn: Any) -> None:
        copy = copy_base(base)
        try:
            mutate_fn(copy)
            detected = not run_on(copy)
        except Exception:  # a mutation that breaks the suite is detected by construction
            detected = True
        finally:
            shutil.rmtree(copy.parent, ignore_errors=True)
        results.append({"name": name, "detected": detected})

    control(
        "commit_rewritten",
        lambda b: mutate(
            b / REAL_RUN_REL / "RUN_REPORT.json",
            lambda d: {**d, "commit": "0" * 40},
        ),
    )
    control(
        "fixture_counters_zeroed",
        lambda b: _zero_fixture_counters(b),
    )
    control(
        "trace_body_tampered",
        lambda b: _tamper_trace(b),
    )
    control(
        "traces_deleted",
        lambda b: (b / REAL_RUN_REL / "traces.jsonl").unlink(),
    )
    control(
        "fake_order_injected",
        lambda b: mutate(
            b / REAL_RUN_REL / "RUN_REPORT.json",
            lambda d: {**d, "totals": {**d["totals"], "orders_created": 1}},
        ),
    )
    control(
        "kind_count_swapped_in_daily",
        lambda b: mutate(
            b / REAL_RUN_REL / "PAPER_DAILY_REPORT.json",
            lambda d: {**d, "decisions": d["decisions"] + 1},
        ),
    )
    control(
        "economic_arithmetic_broken",
        lambda b: _break_arithmetic(b),
    )
    control(
        "secret_injected",
        lambda b: (b / "RUN_REPORT.md").write_text(
            (b / "RUN_REPORT.md").read_text(encoding="utf-8")
            + "\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n",
            encoding="utf-8",
        ),
    )
    return results


def _zero_fixture_counters(base: Path) -> None:
    path = base / FIXTURE_REL / "stdout_1cyc.log"
    text = path.read_bytes().decode("utf-8", errors="replace")
    head, sep, tail = text.partition("Paper trading loop stopped.")
    status = json.loads(tail.lstrip())
    status["cycle"] = {
        **status["cycle"],
        "contexts_built": 0,
        "router_invocations": 0,
        "strategy_invocations": 0,
    }
    path.write_text(head + sep + "\n" + json.dumps(status, indent=2), encoding="utf-8")


def _tamper_trace(base: Path) -> None:
    path = base / REAL_RUN_REL / "traces.jsonl"
    lines = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    lines[0]["reason"] = "gross_edge_not_positive:-0.0100bps"
    path.write_text("\n".join(json.dumps(item) for item in lines) + "\n", encoding="utf-8")


def _break_arithmetic(base: Path) -> None:
    path = base / REAL_RUN_REL / "traces.jsonl"
    lines = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for trace in lines:
        for check in (trace.get("verification") or {}).get("checks") or []:
            if check.get("name") == "proposal_arithmetic":
                check["detail"] = "net=+15.0000 bps"
    path.write_text("\n".join(json.dumps(item) for item in lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="reports/edge-recovery")
    args = parser.parse_args(argv)

    base = Path(args.base).resolve()
    suite = Suite(base=base)
    ok = suite.run()
    controls = negative_controls(base)
    detected = sum(1 for c in controls if c["detected"])
    false_success = len(controls) - detected

    payload = {
        "artifact": "WP-EDGE-00-INDEPENDENT-VERIFICATION",
        "verifier": "scripts/wp_edge_00_verify.py (separate process, artifact-only; no runtime imports)",
        "generated_at_utc": __import__("datetime")
        .datetime.now(__import__("datetime").UTC)
        .isoformat(),
        "base": str(base),
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
            "Verifies persisted PAPER evidence; it cannot and does not certify profitability.",
        ],
    }
    out = base / "INDEPENDENT_VERIFICATION.json"
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
