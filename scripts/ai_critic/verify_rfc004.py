"""verify_rfc004 — independent verification of the RFC-TAP-AI-BOTS-004 evidence.

This program must not import the code it audits. It reads only the published artifacts,
recomputes hashes from bytes, re-derives the economics from the run ledgers, and applies
the contract rules itself. ``--mutations`` rewrites copies of the report tree (re-sealing
hashes where a mutation should be caught by a *rule* rather than by a digest) and requires
each one to be rejected.

The expected upstream commit is a constant here on purpose: a manifest that agrees with
itself about a different commit is still the wrong commit.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_COMMIT = "e8f5503e9b86d5c2710b0c76b1f686703968c9df"
ECONOMIC_KEYS = (
    "fills",
    "closed_trades",
    "net_realised_usdt",
    "gross_realised_usdt",
    "costs_usdt",
    "final_equity_usdt",
    "risk_equity_usdt",
    "drawdown_pct",
    "equity_points",
)
VERDICTS = {"ACCEPT", "CHALLENGE", "ABSTAIN"}
FORBIDDEN_REVIEW_FIELDS = {
    "action", "amount", "direction", "execute", "gate", "leverage", "margin",
    "notional", "notional_usdt", "order", "order_type", "override_gate",
    "position_size", "price", "quantity", "qty", "risk_pct", "side", "size",
    "size_usdt", "stop", "stop_loss", "stop_loss_pct", "take_profit",
    "take_profit_pct", "target",
}
EVIDENCE_ID_RE = re.compile(r"^ev_[0-9a-f]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class Verdict:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, cid: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": cid, "ok": bool(ok), "detail": str(detail)[:600]})

    def failed(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if not check["ok"]]


def _arm_economics(root: Path, arm: str) -> dict[str, Any] | None:
    path = root / "runs" / arm / "BOT-CTX-01_DECISIONS.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line)["entry"] for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    endings = [row for row in rows if row.get("kind") == "RUN_END"]
    if not endings:
        return None
    return {key: endings[-1].get(key) for key in ECONOMIC_KEYS}


def _recompute_review_hash(row: dict[str, Any]) -> str:
    payload = dict(row)
    payload.pop("review_sha256", None)
    return canonical_sha256(payload)


def run_checks(root: Path) -> Verdict:
    v = Verdict()

    # ---------------------------------------------------------------- source pin
    manifest = load_json(root / "SOURCE_MANIFEST.json")
    v.check(
        "SRC-01", manifest.get("commit") == EXPECTED_COMMIT,
        f"manifest commit {manifest.get('commit')}",
    )
    v.check(
        "SRC-01b", manifest.get("commit_matches_pin") is True and manifest.get("license") == "Apache-2.0",
        f"pin flag={manifest.get('commit_matches_pin')} license={manifest.get('license')}",
    )
    files = manifest.get("files") or []
    v.check("SRC-02", len(files) > 5 and all(f.get("sha256") for f in files),
            f"{len(files)} files pinned")
    v.check(
        "SRC-03",
        all(item.get("identical_to_source") for item in (manifest.get("promoted_artifacts") or {}).values()),
        "promoted artifacts are byte-identical to their detailed sources",
    )

    # ------------------------------------------------------------ python trace
    trace = load_jsonl(root / "UPSTREAM_PYTHON_TRACE.jsonl")
    v.check("PY-01", len(trace) >= 7, f"{len(trace)} rows")
    v.check(
        "PY-01b",
        bool(trace) and all(
            row.get("model_status") == "STUB" and row.get("network_calls") == 0
            and row.get("orders") == 0 and row.get("source_commit") == EXPECTED_COMMIT
            for row in trace
        ),
        "every row declares STUB, zero network, zero orders, pinned commit",
    )
    sequences = [row.get("sequence") for row in trace]
    v.check("PY-02", sequences == list(range(1, len(trace) + 1)),
            f"sequences {sequences}")
    v.check("PY-02b", len({row.get("trace_id") for row in trace}) == len(trace),
            "trace ids unique")

    by_agent = {}
    for row in trace:
        by_agent.setdefault((row.get("agent"), row.get("response_type")), []).append(row)
    bull = by_agent.get(("Bull Researcher", "free_text"), [])
    bear = by_agent.get(("Bear Researcher", "free_text"), [])
    router = by_agent.get(("ConditionalLogic.should_continue_debate", None), [])
    manager = by_agent.get(("Research Manager", "structured_valid"), [])
    v.check("PY-03", bool(bull and bear and manager and len(router) >= 2),
            f"bull={len(bull)} bear={len(bear)} router={len(router)} manager={len(manager)}")
    if bull and bear and manager and len(router) >= 2:
        v.check("PY-03b", bull[0]["output_state_sha256"] == router[0]["input_state_sha256"],
                "bull output feeds the router")
        v.check("PY-03c", bear[0]["input_state_sha256"] == bull[0]["output_state_sha256"],
                "bear reviews the state the bull produced")
        v.check("PY-03d", bear[0]["output_state_sha256"] == manager[0]["input_state_sha256"],
                "manager consumes the debate state")
        v.check("PY-03e", router[0].get("router_decision") == "Bear Researcher"
                and router[1].get("router_decision") == "Research Manager",
                f"router decisions {router[0].get('router_decision')} -> {router[1].get('router_decision')}")
        v.check("PY-03f", bull[0].get("opening_marker") is True
                and bear[0].get("opponent_argument_present") is True,
                "bull opens; bear answers the real argument")
    fallback = by_agent.get(("Research Manager", "freetext_fallback"), [])
    no_struct = by_agent.get(("Research Manager", "no_structured_support"), [])
    schema = by_agent.get(("ResearchPlan.schema", "schema_rejected"), [])
    v.check("PY-04", bool(fallback and no_struct and schema),
            f"fallback={len(fallback)} no_structured={len(no_struct)} schema={len(schema)}")

    # ---------------------------------------------------------------- html source
    html_meta = load_json(root / "upstream" / "HTML_REPORT_SHA256.json")
    html_path = root / "upstream" / "report_tree" / "complete_report.html"
    final_state_path = root / "upstream" / "final_state.json"
    v.check("PY-05", html_path.exists() and final_state_path.exists(), "report tree present")
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        v.check("PY-05b", sha256_file(html_path) == html_meta.get("html_sha256"),
                "html bytes match the declared hash")
        v.check("PY-05c", "<script" not in html.lower(), "html carries no script")
        v.check("PY-05d", not any(f"<{tag}" in html.lower() for tag in ("img", "link", "iframe", "embed")),
                "html loads no remote asset")
        v.check("PY-05e", all(token in html for token in ("Bull Researcher", "Bear Researcher", "Research Manager")),
                "rendered sections exist")
        v.check("PY-05f", "Scripted upstream fixture turn 1" in html,
                "the debate text produced by the harness is in the page")
    if final_state_path.exists():
        state = load_json(final_state_path)
        v.check("PY-06", canonical_sha256(state) == html_meta.get("final_state_sha256"),
                "final state hash matches the renderer's input")

    # --------------------------------------------------------------------- REA
    rea = load_json(root / "REA_TARGET_EVIDENCE.json")
    log = load_jsonl(root / "REA_OPERATION_LOG.jsonl")
    v.check("REA-01", len(log) >= 3, f"{len(log)} operations logged")
    observed_ops = {"list_browser_targets", "inspect_web_page", "capture_web_screenshot"}
    observed_rows = [row for row in log if row.get("operation") in observed_ops]
    # ``doctor`` may exit non-zero for native engines that a web observation does not use;
    # its exit code is recorded in the dossier rather than hidden.
    v.check(
        "REA-01b",
        len(observed_rows) >= 3 and all(
            row.get("exit_code") == 0 and not row.get("not_executed") for row in observed_rows
        ),
        "every browser operation exited 0 and is not NOT_EXECUTED",
    )
    ids = [row.get("evidence_id") for row in log if row.get("evidence_id")]
    v.check("REA-01c", len(ids) >= 3 and len(set(ids)) == len(ids)
            and all(EVIDENCE_ID_RE.match(str(i)) for i in ids),
            f"{len(ids)} unique native evidence ids")
    v.check(
        "REA-01d",
        all(row.get("evidence_id") in ids for row in (rea.get("operations") or [])
            if row.get("evidence_id")),
        "the target dossier only names ids that the log contains",
    )
    v.check(
        "REA-01e",
        bool(rea.get("operations")) and all(
            row.get("exit_code") == 0 and row.get("not_executed") is False
            for row in rea.get("operations", [])
            if row.get("operation") in {"list_browser_targets", "inspect_web_page",
                                        "capture_web_screenshot"}
        ),
        "every observed operation in the dossier exited 0 and was executed",
    )
    v.check(
        "REA-02",
        html_path.exists() and rea.get("html_sha256") == sha256_file(html_path)
        and rea.get("html_sha256_matches_served") is True,
        "REA observed the same bytes that were rendered",
    )
    v.check(
        "REA-02b",
        str(rea.get("subject_url", "")).startswith("http://127.0.0.1:")
        and bool(rea.get("browser_target_id")),
        f"loopback target {rea.get('subject_url')} id={rea.get('browser_target_id')}",
    )
    v.check("REA-04", rea.get("reasoning_audited_by_rea") is False
            and rea.get("visual_observation_only") is True,
            "the dossier does not claim REA audited the reasoning")
    facts = rea.get("inspect_facts") or {}
    shot = rea.get("screenshot_facts") or {}
    v.check("REA-03", facts.get("scripts_total") == 0,
            f"scripts_total={facts.get('scripts_total')}")
    v.check("REA-03b", facts.get("required_headings_missing") == [],
            f"missing headings {facts.get('required_headings_missing')}")
    png_path = root / "rea" / "rea_complete_report.png"
    v.check("REA-03c", png_path.exists() and png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n",
            "screenshot is a PNG")
    if png_path.exists():
        v.check("REA-03d", shot.get("artifact_sha256") == sha256_file(png_path),
                "screenshot bytes match the declared artifact hash")
        v.check("REA-03e", shot.get("artifact_sha256_matches_saved") is True,
                "envelope artifact hash matches the saved PNG")

    # Raw REA stdout is the authentic envelope: a hand-edited summary cannot agree with it.
    raw_ok = True
    detail = []
    for row in log:
        path = root / "rea" / str(row.get("stdout_path") or "")
        if not path.exists():
            raw_ok = False
            detail.append(f"missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        if sha256_bytes(text.encode("utf-8")) != row.get("stdout_sha256"):
            raw_ok = False
            detail.append(f"stdout hash mismatch {path.name}")
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError:
            continue  # --version output is plain text
        if envelope.get("evidence_id") != row.get("evidence_id"):
            raw_ok = False
            detail.append(f"evidence id mismatch {path.name}")
    v.check("REA-05", raw_ok, "; ".join(detail))

    shot_raw = root / "rea" / "capture_web_screenshot.stdout.txt"
    if shot_raw.exists():
        envelope = json.loads(shot_raw.read_text(encoding="utf-8"))
        artifact = (envelope.get("normalized_result") or {}).get("artifact") or {}
        declared = shot.get("artifact_sha256")
        v.check("REA-05b", artifact.get("sha256") == declared,
                "the raw screenshot envelope matches the dossier")
        if png_path.exists() and artifact.get("data_base64"):
            decoded = base64.b64decode(artifact["data_base64"])
            v.check("REA-05c", sha256_bytes(decoded) == sha256_file(png_path),
                    "decoded REA artifact equals the saved PNG")
        inspect_raw = root / "rea" / "inspect_web_page.stdout.txt"
        if inspect_raw.exists():
            inspect_env = json.loads(inspect_raw.read_text(encoding="utf-8"))["normalized_result"]
            scripts = (inspect_env.get("scripts") or {}).get("total")
            headings = [
                node.get("name") for node in (inspect_env.get("accessibility") or {}).get("nodes", [])
                if node.get("role") == "heading" and node.get("name")
            ]
            v.check("REA-05d", scripts == 0 and all(
                h in headings for h in ("Bull Researcher", "Bear Researcher", "Research Manager")
            ), f"raw inspect: scripts={scripts}, headings={len(headings)}")
    else:
        v.check("REA-05b", False, "missing raw screenshot envelope")

    # ----------------------------------------------------------------- ablation
    ablation = load_json(root / "ABLATION_REPORT.json")
    arms = ablation.get("arms") or {}
    baseline = _arm_economics(root, "NO_CRITIC")
    repeat = _arm_economics(root, "NO_CRITIC_REPEAT")
    no_trade = _arm_economics(root, "NO_TRADE")
    v.check("ABL-01", baseline is not None and repeat is not None and no_trade is not None,
            "all three executed arms have run ledgers")
    if baseline and repeat:
        v.check("ABL-01b", baseline == repeat, "the repeated baseline is economically identical")
        v.check("ABL-01c", arms.get("NO_CRITIC", {}).get("economics") == baseline,
                "the report quotes the baseline ledger")
        v.check("ABL-01d", arms.get("SHADOW", {}).get("economics_identical_to_baseline") is True
                and arms.get("SHADOW", {}).get("applied_to_economics") is False,
                "SHADOW declares identical economics and no application")
    if no_trade:
        v.check("ABL-01e", no_trade["fills"] == 0, f"NO_TRADE fills={no_trade['fills']}")
    gated = arms.get("GATED_PAPER") or {}
    v.check("ABL-02", gated.get("executed") is False
            and gated.get("status") == "BLOCKED_GATED_PAPER_NOT_AUTHORIZED",
            f"GATED status={gated.get('status')}")
    value = ablation.get("value") or {}
    v.check("ABL-03", value.get("economic_value") == "UNMEASURED"
            and value.get("real_critic_model_called") is False
            and value.get("prospective_edge_verified") is False,
            f"value={value.get('economic_value')} real={value.get('real_critic_model_called')}")
    v.check("ABL-03b", str(value.get("recommendation", "")).startswith("DO_NOT_ADOPT")
            or value.get("recommendation") == "INCONCLUSIVE",
            f"recommendation={value.get('recommendation')}")
    v.check("ABL-03c", attribution_ok(ablation), "the ablation's ownership fields are coherent")

    # -------------------------------------------------------------- critic traces
    reviews = load_jsonl(root / "CRITIC_REVIEWS.jsonl")
    traces = load_jsonl(root / "DECISION_TRACE.jsonl")
    messages = load_jsonl(root / "AGENT_MESSAGES.jsonl")
    v.check("CRI-01", len(reviews) > 0, f"{len(reviews)} reviews")
    review_ok = True
    review_detail = []
    for row in reviews:
        if row.get("verdict") not in VERDICTS:
            review_ok = False
            review_detail.append(f"verdict {row.get('verdict')}")
        if row.get("review_sha256") != _recompute_review_hash(row):
            review_ok = False
            review_detail.append(f"hash {row.get('review_id')}")
        if set(row) & FORBIDDEN_REVIEW_FIELDS:
            review_ok = False
            review_detail.append(f"forbidden {sorted(set(row) & FORBIDDEN_REVIEW_FIELDS)}")
        if row.get("verdict") == "ACCEPT" and (
            not row.get("evidence_refs") or row.get("counter_evidence_refs")
            or row.get("abstain_reason")
        ):
            review_ok = False
            review_detail.append(f"accept shape {row.get('review_id')}")
        if row.get("verdict") == "CHALLENGE" and (
            not row.get("counter_evidence_refs")
            or set(row.get("counter_evidence_refs", [])) <= set(row.get("evidence_refs", []))
        ):
            review_ok = False
            review_detail.append(f"challenge shape {row.get('review_id')}")
        if row.get("verdict") == "ABSTAIN" and not row.get("abstain_reason"):
            review_ok = False
            review_detail.append(f"abstain reason {row.get('review_id')}")
    v.check("CRI-01b", review_ok, "; ".join(review_detail))

    by_review = {row.get("review_id"): row for row in reviews}
    trace_ok = True
    trace_detail = []
    for row in traces:
        review = by_review.get(row.get("review_id"))
        if review is None:
            trace_ok = False
            trace_detail.append(f"orphan trace {row.get('trace_id')}")
            continue
        if row.get("review_sha256") != review.get("review_sha256"):
            trace_ok = False
            trace_detail.append(f"review hash {row.get('trace_id')}")
        if row.get("proposal_sha256") != review.get("proposal_sha256"):
            trace_ok = False
            trace_detail.append(f"proposal hash {row.get('trace_id')}")
        if row.get("gate_action") not in {"ALLOW", "SUPPRESS_NEW_ENTRY"}:
            trace_ok = False
            trace_detail.append(f"gate action {row.get('gate_action')}")
        if row.get("mode") == "SHADOW_ONLY" and (row.get("gate_action") != "ALLOW"
                                                or row.get("economics_affected") is not False):
            trace_ok = False
            trace_detail.append(f"shadow acted {row.get('trace_id')}")
    v.check("CRI-02", len(traces) == len(reviews) and trace_ok, "; ".join(trace_detail))
    v.check("CRI-02b", all(row.get("economics_affected") is False for row in traces),
            "no shadow review touched the economy")
    v.check("CRI-03", len(messages) == 2 * len(reviews) and all(
        sha256_bytes(str(row.get("content")).encode("utf-8")) == row.get("content_sha256")
        for row in messages
    ), f"{len(messages)} messages, hashes recomputed")
    receipt_kinds = {row.get("receipt_kind") for row in reviews}
    v.check("CRI-04", "REAL" not in receipt_kinds, f"receipt kinds {sorted(receipt_kinds)}")

    review_rows = load_jsonl(root / "ABLATION_REVIEWS.jsonl")
    protective = [row for row in review_rows if row.get("intent") != "OPEN"]
    blocked = [row for row in protective if row.get("gate_action") != "ALLOW"]
    v.check("CRI-05", len(protective) > 0 and not blocked,
            f"{len(protective)} protective reviews, {len(blocked)} blocked")

    v.check("CLAIM-01", str(value.get("status", "")).upper() not in {"PASS", "CERTIFIED"},
            f"ablation status {value.get('status')}")
    v.check("CLAIM-02", value.get("prospective_edge_verified") is False
            and value.get("real_critic_model_called") is False,
            "no prospective or real-model claim")
    v.check("CLAIM-03", ablation.get("control", {}).get("false_success") == 0,
            "false_success is zero")

    # Every check collection must have subjects: all() over nothing is not a pass.
    v.check("EMPTY-01", len(trace) > 0 and len(reviews) > 0 and len(traces) > 0
            and len(messages) > 0 and len(review_rows) > 0 and len(log) > 0,
            "no check ran on an empty collection")
    return v


def attribution_ok(ablation: dict[str, Any]) -> bool:
    """The test target and the runtime target must be the same package."""
    control = ablation.get("control") or {}
    return (
        control.get("builder_is_not_verifier") is True
        and control.get("independent_verification_required") is True
        and ablation.get("test_target") == ablation.get("runtime_target")
        == "trading_bot.intelligence.ai_critic"
        and ablation.get("test_target_equals_runtime_target") is True
    )


def verify(root: Path) -> dict[str, Any]:
    v = run_checks(root)
    failed = v.failed()
    return {
        "schema_version": "TAP004_INDEPENDENT_VERIFICATION_V1",
        "verifier": "scripts/ai_critic/verify_rfc004.py",
        "imports_builder_modules": False,
        "root": "/".join(root.parts[-4:]) if len(root.parts) >= 4 else root.name,
        "checks_total": len(v.checks),
        "checks_passed": len(v.checks) - len(failed),
        "checks_failed": len(failed),
        "checks": v.checks,
        "failed": failed,
        "verdict": "PASS" if not failed else "FAIL",
        "false_success": 0,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --------------------------------------------------------------------- mutations


def _seal_review(row: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(row)
    row.pop("review_sha256", None)
    row["review_sha256"] = canonical_sha256(row)
    return row


def mutation_fake_evidence_id(root: Path) -> None:
    evidence = load_json(root / "REA_TARGET_EVIDENCE.json")
    fake = "ev_" + "0" * 64
    for row in evidence.get("operations", []):
        if row.get("evidence_id"):
            row["evidence_id"] = fake
    (root / "REA_TARGET_EVIDENCE.json").write_text(json.dumps(evidence), encoding="utf-8")
    # Make the log agree with the dossier, so the fake id is internally consistent and
    # only the authentic REA stdout can contradict it.
    log_path = root / "REA_OPERATION_LOG.jsonl"
    rows = load_jsonl(log_path)
    for row in rows:
        if row.get("evidence_id"):
            row["evidence_id"] = fake
    log_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    promoted = load_json(root / "SOURCE_MANIFEST.json")
    for name in ("REA_TARGET_EVIDENCE.json", "REA_OPERATION_LOG.jsonl"):
        promoted["promoted_artifacts"][name]["sha256"] = sha256_file(root / name)
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps(promoted), encoding="utf-8")


def mutation_foreign_commit(root: Path) -> None:
    foreign = "1" * 40
    manifest = load_json(root / "SOURCE_MANIFEST.json")
    manifest["commit"] = foreign
    manifest["commit_matches_pin"] = True
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("UPSTREAM_PYTHON_TRACE.jsonl", "REA_OPERATION_LOG.jsonl"):
        path = root / name
        rows = load_jsonl(path)
        for row in rows:
            row["source_commit"] = foreign
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    meta = load_json(root / "upstream" / "HTML_REPORT_SHA256.json")
    meta["source_commit"] = foreign
    (root / "upstream" / "HTML_REPORT_SHA256.json").write_text(json.dumps(meta), encoding="utf-8")


def mutation_not_executed(root: Path) -> None:
    evidence = load_json(root / "REA_TARGET_EVIDENCE.json")
    for row in evidence.get("operations", []):
        if row.get("operation") == "inspect_web_page":
            row["not_executed"] = True
            row["exit_code"] = 0
    (root / "REA_TARGET_EVIDENCE.json").write_text(json.dumps(evidence), encoding="utf-8")


def mutation_reasoning_claim(root: Path) -> None:
    evidence = load_json(root / "REA_TARGET_EVIDENCE.json")
    evidence["reasoning_audited_by_rea"] = True
    evidence["visual_observation_only"] = False
    (root / "REA_TARGET_EVIDENCE.json").write_text(json.dumps(evidence), encoding="utf-8")


def mutation_adopt_verified(root: Path) -> None:
    ablation = load_json(root / "ABLATION_REPORT.json")
    ablation["value"]["recommendation"] = "ADOPT_VERIFIED"
    ablation["value"]["status"] = "PASS"
    (root / "ABLATION_REPORT.json").write_text(json.dumps(ablation), encoding="utf-8")


def mutation_screenshot_bytes(root: Path) -> None:
    png = root / "rea" / "rea_complete_report.png"
    png.write_bytes(png.read_bytes() + b"corrupted")
    new_sha = sha256_file(png)
    evidence = load_json(root / "REA_TARGET_EVIDENCE.json")
    evidence["screenshot_facts"]["artifact_sha256"] = new_sha
    for row in evidence.get("operations", []):
        if row.get("screenshot_sha256"):
            row["screenshot_sha256"] = new_sha
    (root / "REA_TARGET_EVIDENCE.json").write_text(json.dumps(evidence), encoding="utf-8")


def mutation_resealed_contract_violation(root: Path) -> None:
    path = root / "CRITIC_REVIEWS.jsonl"
    rows = load_jsonl(path)
    row = next(r for r in rows if r.get("verdict") == "ACCEPT")
    row["counter_evidence_refs"] = [row["evidence_refs"][0]]
    rows[rows.index(next(r for r in rows if r.get("review_id") == row["review_id"]))] = _seal_review(row)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


MUTATIONS: list[tuple[str, Callable[[Path], None], str, str]] = [
    ("M1_fake_evidence_id", mutation_fake_evidence_id, "REA-05",
     "a forged evidence id cannot agree with the raw REA envelope"),
    ("M2_foreign_source_commit", mutation_foreign_commit, "SRC-01",
     "a self-consistent manifest still names the wrong commit"),
    ("M3_exit_zero_not_executed", mutation_not_executed, "REA-01e",
     "exit 0 with NOT_EXECUTED is not execution"),
    ("M4_rea_audited_reasoning", mutation_reasoning_claim, "REA-04",
     "REA observing a page cannot audit Python reasoning"),
    ("M5_adopt_verified_without_edge", mutation_adopt_verified, "ABL-03b",
     "ADOPT_VERIFIED without prospective evidence is refused"),
    ("M6_correct_id_wrong_bytes", mutation_screenshot_bytes, "REA-05b",
     "correct ids with different bytes are refused against the raw envelope"),
    ("M7_resealed_contract_violation", mutation_resealed_contract_violation, "CRI-01b",
     "a re-sealed review that cites counter-evidence as ACCEPT is refused by the rule"),
]


def run_mutations(root: Path) -> dict[str, Any]:
    results = []
    for name, mutate, expected_check, rule in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="tap004-mutation-") as tmp:
            copy_root = Path(tmp) / "report"
            shutil.copytree(root, copy_root)
            mutate(copy_root)
            report = verify(copy_root)
            failed_ids = [row["check"] for row in report["failed"]]
            results.append(
                {
                    "mutation": name,
                    "expected_check": expected_check,
                    "rule": rule,
                    "failed_checks": failed_ids,
                    "rejected": expected_check in failed_ids,
                    "rejected_by_rule": expected_check in failed_ids,
                    "verdict": report["verdict"],
                }
            )
    return {
        "schema_version": "TAP004_MUTATION_REPORT_V1",
        "mutations_total": len(results),
        "mutations_rejected": sum(1 for r in results if r["rejected"]),
        "all_rejected": all(r["rejected"] for r in results),
        "results": results,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--mutations", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    report = verify(root)
    if args.mutations:
        mutations = run_mutations(root)
        (root / "MUTATION_REPORT.json").write_text(
            json.dumps(mutations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        report["mutation_report"] = {
            "mutations_total": mutations["mutations_total"],
            "mutations_rejected": mutations["mutations_rejected"],
            "all_rejected": mutations["all_rejected"],
        }
        (root / "INDEPENDENT_VERIFICATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "verdict": report["verdict"],
            "checks": f"{report['checks_passed']}/{report['checks_total']}",
            "mutations": f"{mutations['mutations_rejected']}/{mutations['mutations_total']}",
            "failed": [row["check"] for row in report["failed"]],
        }, indent=2))
        return 0 if report["verdict"] == "PASS" and mutations["all_rejected"] else 2

    (root / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": report["verdict"],
                      "checks": f"{report['checks_passed']}/{report['checks_total']}",
                      "failed": [row["check"] for row in report["failed"]]}, indent=2))
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
