"""ai_bots_verify — verificación independiente de los artefactos del RFC-AI-BOTS-002.

No importa el runner: lee JSON/JSONL/CSV y PNG del disco y vuelve a calcular sus
propios hashes. Los datos del run no se regeneran aquí; se comprueban.

Uso:
    ./.venv/Scripts/python scripts/ai_bots_verify.py
Salida: ``reports/ai-bots/RFC-AI-BOTS-002/INDEPENDENT_VERIFICATION.json`` y exit 0/1.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.vision.ledger import verify_chain  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-002"
BASELINE = "b17644a"

checks: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: Any = None) -> bool:
    checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    return ok


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --------------------------------------------------------------- 1. hash chains
def verify_ledgers() -> None:
    for bot in ("bot-vis-01", "bot-ctx-01"):
        ledger = OUT / "runs" / bot / f"{bot.upper()}_DECISIONS.jsonl"
        if not check(f"ledger_exists[{bot}]", ledger.exists(), str(ledger.name)):
            continue
        result = verify_chain(ledger)
        decisions = result.get("kinds", {}).get("DECISION", 0)
        check(
            f"ledger_chain_intact[{bot}]",
            bool(result.get("ok")),
            {"lines": result.get("lines"), "reason": result.get("reason"),
             "head": result.get("head_sha256")},
        )
        check(f"ledger_has_decisions[{bot}]", int(decisions) > 0, decisions)


# ------------------------------------------------------ 2. PNGs match manifests
def verify_snapshots() -> None:
    for bot in ("BOT-VIS-01", "BOT-CTX-01"):
        manifest_path = OUT / "runs" / bot.lower() / "VISION_SNAPSHOT_MANIFEST.json"
        if not check(f"manifest_exists[{bot}]", manifest_path.exists(), None):
            continue
        manifest = load_json(manifest_path)
        rows = manifest["snapshots"]
        attached = [row for row in rows if row["image_attached"]]
        if bot == "BOT-CTX-01":
            check("ctx_sends_no_image", not attached and manifest["image_mode"] == "text_only",
                  {"rows": len(rows), "attached": len(attached)})
            check("ctx_prompt_is_structured", manifest["prompt_version"] == "aibot-ctx-prompt/1",
                  manifest["prompt_version"])
            continue
        mismatched: list[str] = []
        missing: list[str] = []
        for row in attached:
            png = OUT / "runs" / bot.lower() / "snapshots" / f"{row['image_sha256']}.png"
            if not png.exists():
                missing.append(row["image_sha256"])
            elif sha256_file(png) != row["image_sha256"]:
                mismatched.append(row["image_sha256"])
        check("vis_sends_a_png_every_decision", len(attached) == len(rows) and bool(rows),
              {"rows": len(rows), "attached": len(attached)})
        check("vis_png_bytes_match_recorded_hash", not missing and not mismatched,
              {"missing": missing[:3], "mismatched": mismatched[:3]})
        check("vis_prompt_is_visual", manifest["prompt_version"] == "ai-vision-prompt/2",
              manifest["prompt_version"])


# ------------------------------------------------------- 3. traces and economics
def verify_traces() -> None:
    report = load_json(OUT / "RUN_REPORT.json")
    bench = {row["bot_id"]: row for row in csv.DictReader((OUT / "BOT_BENCHMARK.csv").open())}
    for bot_id, row in bench.items():
        invocations = load_jsonl(OUT / "runs" / bot_id.lower() / "MODEL_INVOCATIONS.jsonl")
        check(f"trace_count_matches_calls[{bot_id}]", len(invocations) == int(row["calls"]),
              {"rows": len(invocations), "calls": row["calls"]})
        check(
            f"trace_rows_name_the_bot[{bot_id}]",
            all(item["bot_id"] == bot_id for item in invocations),
            None,
        )
        if report["mode"] == "mock":
            statuses = {item["model_status"] for item in invocations}
            check(f"mock_is_never_called_real[{bot_id}]",
                  row["model_status"] == "MOCK_TEST" and "REAL_MODEL_CALL" not in statuses,
                  {"bench": row["model_status"], "trace": sorted(statuses)})
            check(f"mock_declares_not_evidence[{bot_id}]",
                  report["economics"] == "NOT_EVIDENCE", report["economics"])

        # Reconcile from the hash-chained ledger, not from the summary it also wrote:
        # net PnL must equal reference gross minus (commissions + execution cost).
        ledger = OUT / "runs" / bot_id.lower() / f"{bot_id}_DECISIONS.jsonl"
        closes = [
            record["entry"]
            for record in load_jsonl(ledger)
            if record["entry"].get("kind") == "CLOSE"
        ]
        ref_gross = sum(float(item["reference_gross_pnl_usdt"]) for item in closes)
        commissions = sum(float(item["commissions_usdt"]) for item in closes)
        execution = sum(float(item["execution_cost_usdt"]) for item in closes)
        net = sum(float(item["pnl_net_usdt"]) for item in closes)
        check(
            f"pnl_reconciles[{bot_id}]",
            abs((ref_gross - commissions - execution) - net) <= 1e-4
            and abs(net - float(row["net_realised_usdt"])) <= 1e-4
            and len(closes) == int(row["closed_trades"]),
            {"reference_gross": round(ref_gross, 6), "commissions": round(commissions, 6),
             "execution_cost": round(execution, 6), "net": round(net, 6),
             "bench_net": row["net_realised_usdt"], "closes": len(closes)},
        )


# --------------------------------------------------------- 4. registry defaults
def verify_registry() -> None:
    path = OUT / "BOT_CAPABILITY_REGISTRY.json"
    doc = load_json(path)
    ids = {row["bot_id"] for row in doc["bots"]}
    check("registry_has_both_bots", ids == {"BOT-VIS-01", "BOT-CTX-01"}, sorted(ids))
    forbidden = {"place_order", "modify_risk", "call_exchange", "withdraw"}
    bad = [
        row["bot_id"]
        for row in doc["bots"]
        if not forbidden.issubset(set(row["forbidden_actions"]))
    ]
    check("registry_forbids_execution_for_all", not bad, bad)


# --------------------------------------------- 5. no exchange/risk reachability
def verify_authority() -> None:
    banned = ("ccxt", "binance", "bybit", "okx", "exchange", "hyperliquid", "kraken")
    offenders: list[str] = []
    for package in ("src/trading_bot/vision", "src/trading_bot/intelligence/ai_bots"):
        for file in (REPO / package).rglob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    if any(token in name.lower() for token in banned):
                        offenders.append(f"{file.relative_to(REPO)}:{name}")
    check("bots_cannot_import_an_exchange", not offenders, offenders[:5])

    for file in (REPO / "src/trading_bot/intelligence/ai_bots").rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        check(
            f"bot_module_does_not_own_the_book[{file.name}]",
            not any(
                "paper.broker" in name or "risk.manager" in name
                for name in imported_names
            ),
            sorted(imported_names),
        )


def verify_risk_untouched() -> None:
    try:
        diff = subprocess.run(
            ["git", "diff", f"{BASELINE}..HEAD", "--", "config/risk.yaml"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - git always exists in this repo
        check("risk_policy_unchanged", False, str(exc))
        return
    check("risk_policy_unchanged_vs_baseline", diff.stdout.strip() == "",
          {"exit": diff.returncode, "diff_bytes": len(diff.stdout)})


# ------------------------------------------------ 6. live mode stays BLOCKED
def verify_live_is_blocked_without_a_key() -> None:
    env = {k: v for k, v in os.environ.items() if k != "VISION_API_KEY"}
    proc = subprocess.run(
        [sys.executable, "scripts/ai_bots_run.py", "--mode", "live", "--out",
         str(OUT / "blocked_live")],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    report_path = OUT / "blocked_live" / "RUN_REPORT.json"
    status = load_json(report_path)["status"] if report_path.exists() else None
    check(
        "live_without_key_is_blocked",
        proc.returncode == 2 and status == "BLOCKED",
        {"exit": proc.returncode, "status": status, "stdout": proc.stdout.strip()[:120]},
    )


# ------------------------------- 7. TEST_TARGET == RUNTIME_TARGET coverage
def verify_test_coverage_of_runtime() -> None:
    """Every package the run imports must have tests in the same tree."""
    script = (REPO / "scripts" / "ai_bots_run.py").read_text(encoding="utf-8")
    tree = ast.parse(script)
    imported = {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("trading_bot")
    }
    uncovered: list[str] = []
    for module in sorted(imported):
        parts = module.split(".")
        if len(parts) < 2 or parts[1] == "config":
            continue
        # TARGET MATTERS: the tests must live in the tree that mirrors the runtime
        # package, not merely mention the name somewhere.
        tests_root = REPO / "tests" / "unit" / parts[1]
        if not tests_root.exists():
            uncovered.append(f"{module} -> no tests/unit/{parts[1]}")
            continue
        needle = module.rsplit(".", 1)[-1]
        hit = any(
            needle in path.read_text(encoding="utf-8") for path in tests_root.rglob("*.py")
        )
        if not hit:
            uncovered.append(f"{module} -> tests/unit/{parts[1]} never names {needle}")
    check("runtime_imports_are_covered_by_tests", not uncovered, uncovered)


def main() -> int:
    verify_ledgers()
    verify_snapshots()
    verify_traces()
    verify_registry()
    verify_authority()
    verify_risk_untouched()
    verify_live_is_blocked_without_a_key()
    verify_test_coverage_of_runtime()

    failed = [item for item in checks if item["status"] != "PASS"]
    result = {
        "schema_version": "AIBOT_INDEPENDENT_VERIFICATION_V1",
        "verifier": "scripts/ai_bots_verify.py (reads artifacts, does not import the runner)",
        "builder_is_not_verifier": True,
        "artifact_root": str(OUT.relative_to(REPO)),
        "checks": checks,
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "verdict": "PASS" if not failed else "FAIL",
    }
    (OUT / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps({"verdict": result["verdict"], "passed": result["passed"],
                      "failed": len(failed), "failures": failed[:5]}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
