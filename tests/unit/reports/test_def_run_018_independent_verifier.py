"""RFC-DEF-018 / WP-018-04 — el verificador B y el gate tienen que saber fallar.

Los casos de este fichero no comprueban que B diga `PASS`: comprueban que **deja de
decirlo** cuando alguien toca un byte. El sandbox se construye con los resúmenes reales
de 017 y ledgers sintéticos compactos que reproducen sus cifras; así una mutación de un
contador o de un `CLOSE` se detecta sin copiar 200 MB de ledgers.

El caso 7 (`RUNTIME_VALIDATION`) es propiedad del gate, no de B: un test que pasa no es
un replay. El caso 8 (`independencia`) también: un «verificador B» que importa el
verificador A no es independiente.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
RFC17 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-017"
RFC18 = REPO / "reports" / "ai-bots" / "RFC-DEF-RUN-018"
EVIDENCE_FILES = (
    "ECONOMIC_ATTRIBUTION.json",
    "TRADE_LEDGER.csv",
    "PAIRED_DELTA.csv",
)
OOS_FILES = (
    "OOS_PLAN.json",
    "OOS_RESULTS.json",
    "OOS_STRESS_COST2.json",
    "OOS_RUNS_untouched_test.json",
    "OOS_RUNS_untouched_test_cost2.json",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verifier = load_module("def_run_018_verify_b", REPO / "scripts" / "def_run_018_verify_b.py")
gate = load_module("def_run_018_gate", REPO / "scripts" / "def_run_018_gate.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split(total: Decimal, parts: int) -> list[Decimal]:
    if parts <= 0:
        return []
    quantum = Decimal("0.00000001")
    each = (total / parts).quantize(quantum)
    values = [each] * parts
    values[-1] = total - each * (parts - 1)
    return values


def chain_write(path: Path, entries: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        payload = json.dumps(
            {"seq": index, "prev_sha256": previous, "entry": entry},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        lines.append(
            json.dumps(
                {"seq": index, "prev_sha256": previous, "entry": entry, "sha256": digest},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        previous = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_ledger(path: Path, run: dict[str, Any]) -> None:
    net = Decimal(str(run["net_pnl_usdt"]))
    gross = Decimal(str(run["gross_pnl_usdt"]))
    costs = Decimal(str(run["costs_usdt"]))
    commissions_total = gross - net
    execution_total = costs - commissions_total
    trades = int(run["closed_trades"])
    net_parts = split(net, trades)
    commission_parts = split(commissions_total, trades)
    execution_parts = split(execution_total, trades)
    entries: list[dict[str, Any]] = [{"kind": "RUN"}]
    for index in range(trades):
        entries.append({"kind": "FILL", "position_id": f"pos-{index}"})
    for index in range(trades):
        entries.append(
            {
                "kind": "CLOSE",
                "position_id": f"pos-{index}",
                "day_utc": run["day_utc"],
                "pnl_net_usdt": str(net_parts[index]),
                "gross_pnl_usdt": str(net_parts[index] + commission_parts[index]),
                "commissions_usdt": str(commission_parts[index]),
                "execution_cost_usdt": str(execution_parts[index]),
                "exit_reason": "stop_loss",
            }
        )
    for _ in range(int(run["deferred_slots"])):
        entries.append({"kind": "OPINION_DEFERRED"})
    entries.append(
        {
            "kind": "RUN_END",
            "calls": int(run["calls"]),
            "net_realised_usdt": str(net),
            "drawdown_usdt": 0.0,
        }
    )
    chain_write(path, entries)


@cache
def dataset_stamps(archive: str) -> tuple[int, ...]:
    rows = json.loads(
        (REPO / "data" / "quote-feed-1m" / f"{archive}_1m_2021-01-04_2021-02-17.json").read_text()
    )
    return tuple(int(row[0]) for row in rows)


def day_missing(symbol: str, day: str) -> int:
    start = int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp() * 1000)
    observed = sum(
        1
        for stamp in dataset_stamps(symbol.replace("/", ""))
        if start <= stamp < start + 86_400_000
    )
    return 1440 - observed


def build_pristine(root: Path) -> None:
    shutil.copytree(REPO / "data" / "def-run-016", root / "data" / "def-run-016")
    shutil.copytree(REPO / "data" / "def-run-017", root / "data" / "def-run-017")
    shutil.copytree(
        REPO / "data" / "quote-feed-1m",
        root / "data" / "quote-feed-1m",
        ignore=shutil.ignore_patterns("*.lock"),
    )
    evidence = root / "reports" / "ai-bots" / "RFC-DEF-RUN-017" / "evidence"
    evidence.mkdir(parents=True)
    for name in EVIDENCE_FILES:
        shutil.copyfile(RFC17 / "evidence" / name, evidence / name)
    (evidence / "oos").mkdir()
    for name in OOS_FILES:
        shutil.copyfile(RFC17 / "evidence" / "oos" / name, evidence / "oos" / name)

    cell_missing: dict[str, int] = {}
    for name in ("OOS_RUNS_untouched_test.json", "OOS_RUNS_untouched_test_cost2.json"):
        target = evidence / "oos" / name
        payload = json.loads(target.read_text(encoding="utf-8"))
        for run in payload["runs"]:
            # El fixture representa el mundo corregido: cobertura derivada del dataset y
            # sello temporal presente. El defecto real de 017 se prueba en su propio caso.
            missing = day_missing(run["symbol"], run["day_utc"])
            run["minutes_observed"] = 1440 - missing
            run["missing_minutes"] = missing
            run["started_at_utc"] = run.get("started_at_utc") or f"{run['day_utc']}T00:00:00Z"
            run["bars"] = 1480
            run.pop("resumed_from_ledger", None)
            if float(run["cost_multiplier"]) == 1.0:
                key = f"{run['symbol']}|{run['lifecycle']}|1.0"
                cell_missing[key] = cell_missing.get(key, 0) + missing
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        run_root = evidence / "oos"
        for run in payload["runs"]:
            symbol = run["symbol"].replace("/", "")
            path = (
                run_root
                / "runs"
                / symbol
                / run["lifecycle"].lower()
                / f"cost-{float(run['cost_multiplier']):.1f}"
                / f"{run['day_utc']}.jsonl"
            )
            build_ledger(path, run)
            run["ledger"] = str(path.relative_to(root)).replace("/", "\\")
            run["ledger_sha256"] = sha256(path)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    results_path = evidence / "oos" / "OOS_RESULTS.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for cell_key, cell in (results.get("cells") or {}).items():
        if float(cell.get("cost_multiplier", 1.0)) == 1.0:
            cell["missing_minutes"] = cell_missing.get(cell_key, cell.get("missing_minutes", 0))
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "schema_version": "DEF_RUN_018_FIXTURE_MANIFEST_V1",
        "artifacts": {
            str(path.relative_to(evidence)).replace("\\", "/"): {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(evidence.rglob("*"))
            if path.is_file() and path.name != "ARTIFACT_MANIFEST.json"
        },
    }
    (evidence / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


@pytest.fixture(scope="session")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("rfc018-pristine")
    build_pristine(root)
    return root


@pytest.fixture()
def sandbox(pristine: Path, tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    shutil.copytree(pristine, root)
    return root


def codes(payload: dict[str, Any]) -> set[str]:
    return {
        item["code"]
        for item in payload["controls"]
        if item["state"] in ("FAIL", "BLOCKED", "UNRECOMPUTABLE")
    }


def test_the_pristine_fixture_passes(pristine):
    payload = verifier.verify(pristine)
    failures = [item for item in payload["controls"] if item["state"] != "PASS"]
    assert not failures, failures[:3]
    assert payload["result"] == "PASS"
    #: 383 comprobaciones es el contrato de B: 32 runs por 10 controles, mas cadena, celdas,
    #: delta, bootstrap, regla y estrés. Un PASS con menos comprobaciones no es el mismo B.
    assert payload["checks_total"] == 383
    assert payload["oos_decision"] == "NOT_EVIDENCED"
    assert payload["stress_classification"]["used_for_decision"] is False


def test_zeroing_deferred_slots_is_caught(sandbox):
    """El defecto original de 017 no puede repetirse sin que B lo vea."""
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/OOS_RESULTS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cells"]["AAVE/USDT|DEFER|1.0"]["deferred_slots"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert "CELL_AAVE/USDT|DEFER|1.0" in codes(report)


def test_a_missing_primary_cell_is_uncomputable_not_pass(sandbox):
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/OOS_RESULTS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cells"].pop("UNI/USDT|DEFER|1.0")
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert "EXPECTED_CELLS_PRESENT" in codes(report)


def test_an_edited_close_in_a_rechained_ledger_is_caught(sandbox):
    target = next(
        (sandbox / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/runs").rglob("2021-02-09.jsonl")
    )
    entries = [
        json.loads(line)["entry"] for line in target.read_text(encoding="utf-8").splitlines()
    ]
    close = next(entry for entry in entries if entry["kind"] == "CLOSE")
    close["pnl_net_usdt"] = str(Decimal(close["pnl_net_usdt"]) + Decimal("25"))
    chain_write(target, entries)
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert any(
        item["code"].startswith("NET_FROM_LEDGER_") and item["state"] == "FAIL"
        for item in report["controls"]
    )


def test_a_reseeded_or_hand_written_decision_is_caught(sandbox):
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/OOS_RESULTS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["paired_day_deltas"]["AAVE/USDT"]["seed"] = 7
    payload["decision"]["economic_status"] = "EVIDENCED"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert "PAIRED_DELTA_AND_BOOTSTRAP" in codes(report)
    assert "DECISION_RULE_REAPPLIED" in codes(report)


def test_a_swapped_dataset_is_caught_by_sha256(sandbox):
    target = sandbox / "data" / "quote-feed-1m" / "AAVEUSDT_1m_2021-01-04_2021-02-17.json"
    rows = json.loads(target.read_text(encoding="utf-8"))
    rows[0][1] = float(rows[0][1]) + 1.0
    target.write_text(json.dumps(rows), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert "DATASETS_MATCH_PLAN" in codes(report)


def test_stress_cannot_be_promoted_to_decision(sandbox):
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/OOS_STRESS_COST2.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["used_for_decision"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["result"] == "FAIL"
    assert "STRESS_POST_HOC_FLAG" in codes(report)


def test_a_missing_dataset_blocks_instead_of_passing(sandbox):
    (sandbox / "data" / "quote-feed-1m" / "AAVEUSDT_1m_2021-01-04_2021-02-17.json").unlink()
    report = verifier.verify(sandbox)
    assert report["result"] == "BLOCKED"
    assert "DATASETS_MATCH_PLAN" in codes(report)


def test_the_recount_metadata_defect_is_visible_on_real_evidence():
    """El fixture está corregido; el paquete sellado no. B debe distinguir los dos defectos."""
    payload = verifier.verify(REPO)
    assert payload["result"] == "FAIL"
    #: 017 publicó ocho runs con `bars=0`, `started_at_utc=null` y 1441 minutos en un día
    #: de 1440. Procedencia y cobertura comparten causa pero no diagnóstico: B los separa.
    assert [item["code"] for item in payload["defects"]] == [
        "RUN_PROVENANCE_INCOMPLETE",
        "RECOUNT_ZEROED_RUN_METADATA",
    ]
    provenance, recount = payload["defects"]
    assert len(provenance["runs"]) == 8
    assert all("start=None" in item for item in provenance["runs"])
    assert len(recount["runs"]) == 8
    assert "RUN_PROVENANCE_COMPLETE" in codes(payload)


def test_recount_rebuild_keeps_dataset_coverage():
    """`result_from_ledger` ya no puede publicar un día completo sin sus minutos."""
    oos = load_module("def_run_017_oos", REPO / "scripts" / "def_run_017_oos.py")
    ledger = (
        REPO
        / "reports/ai-bots/RFC-DEF-RUN-017/evidence/oos/runs/UNIUSDT/supersede/cost-1.0/2021-02-11.jsonl"
    )
    day = int(datetime(2021, 2, 11).replace(tzinfo=UTC).timestamp() // 86400)
    facts = oos.result_from_ledger(
        {"symbol": "UNI/USDT", "lifecycle": "SUPERSEDE", "cost_multiplier": 1.0, "day": day},
        ledger,
    )
    assert facts["missing_minutes"] == 79
    assert facts["minutes_observed"] == 1361
    assert facts["bars"] > 1400
    assert facts["started_at_utc"] is not None


# --------------------------------------------------------------------------- gate


def write_gate_inputs(
    root: Path, *, technical: str = "PASS", economic: str = "NOT_EVIDENCED"
) -> None:
    out = root / "reports" / "ai-bots" / "RFC-DEF-RUN-018"
    out.mkdir(parents=True, exist_ok=True)
    (out / "BASELINE_017.json").write_text(
        json.dumps({"git": {"head": "a" * 40}}), encoding="utf-8"
    )
    (out / "EVIDENCE_SEAL.json").write_text(json.dumps({"commit": "b" * 40}), encoding="utf-8")
    oos = root / "reports" / "ai-bots" / "RFC-DEF-RUN-017" / "evidence" / "oos"
    oos.mkdir(parents=True, exist_ok=True)
    (oos / "OOS_RESULTS.json").write_text(
        json.dumps({"decision": {"economic_status": economic}}), encoding="utf-8"
    )
    controls = [{"code": "CHAIN", "state": "PASS", "detail": ""}]
    if technical == "FAIL":
        controls.append({"code": "NET_FROM_LEDGER_x", "state": "FAIL", "detail": ""})
    (out / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(
            {
                "result": technical,
                "checks_total": len(controls),
                "controls": controls,
                "summary": {"PASS": len(controls) - (technical == "FAIL")},
                "independence": {
                    "imports_trading_bot": False,
                    "reused_recomputation_code": [],
                    "source_sha256": "c" * 64,
                },
                "defects": [],
                "oos_decision": economic,
                "stress_classification": {
                    "status": "NEGATIVE",
                    "used_for_decision": False,
                    "confirmatory": False,
                },
            }
        ),
        encoding="utf-8",
    )
    verifier = root / "scripts" / "def_run_018_verify_b.py"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    source = (REPO / "scripts" / "def_run_018_verify_b.py").read_bytes()
    verifier.write_bytes(source)
    (out / "INDEPENDENCE_AUDIT.json").write_text(
        json.dumps(
            {
                "state": "PASS",
                "independent": True,
                "reasons": [],
                "audited_sha256": hashlib.sha256(source).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (out / "CLEAN_REPRO_RUN_REPORT.json").write_text(
        json.dumps(
            {
                "status": "CLEAN_CHECKOUT_REPRODUCED",
                "runtime_executed": True,
                "paper_validation": "NOT_PERFORMED",
                "paper_orders": 0,
                "live_orders": 0,
            }
        ),
        encoding="utf-8",
    )


def test_gate_never_promotes_a_not_evidenced_oos(sandbox):
    write_gate_inputs(sandbox)
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "PASS"
    assert decision["economic_evidence"] == "NOT_EVIDENCED"
    assert decision["paper_admission"] == "NO_GO"


def test_gate_rejects_a_verifier_that_wraps_the_builder(sandbox):
    write_gate_inputs(sandbox)
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-018/INDEPENDENT_VERIFICATION.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["independence"]["reused_recomputation_code"] = ["def_run_017_verify"]
    payload["independence"]["imports_trading_bot"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "BLOCKED"
    assert "INDEPENDENCE_NOT_PROVEN" in decision["blockers"]


def test_gate_does_not_accept_tests_as_runtime(sandbox):
    write_gate_inputs(sandbox)
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-018/CLEAN_REPRO_RUN_REPORT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime_executed"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "BLOCKED"
    assert decision["paper_admission"] == "NO_GO"


def test_gate_refuses_incomplete_provenance_and_exit_zero_is_not_a_verdict(sandbox):
    """Un FAIL de procedencia bloquea; y el código de salida no es el veredicto."""
    write_gate_inputs(sandbox, technical="FAIL")
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-018/INDEPENDENT_VERIFICATION.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["controls"].append(
        {"code": "RUN_PROVENANCE_COMPLETE", "state": "FAIL", "detail": "sin bloque"}
    )
    payload["summary"] = {"PASS": 1, "FAIL": 2}
    path.write_text(json.dumps(payload), encoding="utf-8")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "FAIL"
    assert decision["economic_evidence"] == "INVALID"
    assert decision["paper_admission"] == "NO_GO"
    assert decision["false_success"] == 0
    #: sin --strict el gate sale 0 porque se ejecutó, no porque aprobase; con --strict
    #: distingue. Quien lea solo el exit code sin `--strict` se equivoca, y eso es visible.
    assert gate.main(["--root", str(sandbox)]) == 0
    written = json.loads(
        (sandbox / "reports/ai-bots/RFC-DEF-RUN-018/ADMISSION_DECISION.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["technical_integrity"] == "FAIL"
    assert gate.main(["--root", str(sandbox), "--strict"]) == 3


def test_a_technical_pass_does_not_upgrade_economic_evidence(sandbox):
    write_gate_inputs(sandbox, economic="EVIDENCED")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "PASS"
    assert decision["paper_admission"] == "NO_GO"
    assert decision["paper_validation"] == "NOT_PERFORMED"


# --------------------------------------------------- auditoría de independencia AST

AUDITOR = REPO / "scripts" / "def_run_018_independence_audit.py"


@cache
def auditor():
    return load_module("def_run_018_independence_audit", AUDITOR)


def test_prose_mentions_are_not_dependencies():
    """El falso positivo original: la prosa de B hablaba de los módulos del Builder."""
    source = (
        '"""No importa `from trading_bot.vision import economic_audit` ni def_run_017_verify."""\n'
        "# import trading_bot\n"
        "import json\n"
        "\n"
        'MESSAGE = "from trading_bot import ledger"\n'
    )
    result = auditor().audit_source(source)
    assert result["independent"] is True
    assert result["forbidden"] == []
    assert result["imports"] == ["json"]


def test_from_import_with_alias_is_a_dependency():
    result = auditor().audit_source("from trading_bot.vision import ledger as led\n")
    assert result["independent"] is False
    assert "FORBIDDEN_IMPORT" in result["reasons"]
    assert result["forbidden"] == ["trading_bot.vision"]


def test_plain_imports_and_third_party_are_classified():
    result = auditor().audit_source("import def_run_017_verify\nimport numpy\nimport json\n")
    assert result["forbidden"] == ["def_run_017_verify"]
    #: los dos son ajenos a la biblioteca estándar; el prohibido también se lista ahí.
    assert result["non_stdlib"] == ["def_run_017_verify", "numpy"]
    assert result["independent"] is False


def test_literal_dynamic_import_is_resolved_and_blocked():
    source = 'import importlib\nimportlib.import_module("trading_bot.vision.ledger")\n'
    result = auditor().audit_source(source)
    assert result["forbidden"] == ["trading_bot.vision.ledger"]
    assert result["independent"] is False
    assert result["dynamic_imports"][0]["state"] == "RESOLVED_LITERAL"


def test_unresolvable_dynamic_import_fails_closed():
    source = "import importlib\ndef go(name):\n    return importlib.import_module(name)\n"
    result = auditor().audit_source(source)
    assert result["independent"] is False
    assert "UNRESOLVED_DYNAMIC_IMPORT" in result["reasons"]
    assert result["uncertain"] is True


def test_syntax_error_fails_closed_without_raising():
    result = auditor().audit_source("def broken(:\n")
    assert result["state"] == "FAIL"
    assert result["independent"] is False
    assert result["reasons"] == ["SYNTAX_ERROR"]


def test_relative_import_fails_closed():
    result = auditor().audit_source("from . import helper\n")
    assert "RELATIVE_IMPORT" in result["reasons"]
    assert result["independent"] is False


def test_the_real_verifier_b_is_independent():
    result = auditor().audit_path(REPO / "scripts" / "def_run_018_verify_b.py")
    assert result["state"] == "PASS"
    assert result["independent"] is True
    assert result["forbidden"] == []


def test_gate_requires_the_external_audit(sandbox):
    write_gate_inputs(sandbox)
    (sandbox / "reports/ai-bots/RFC-DEF-RUN-018/INDEPENDENCE_AUDIT.json").unlink()
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "BLOCKED"
    assert "MISSING_INDEPENDENCE_AUDIT" in decision["blockers"]


def test_gate_rejects_an_audit_of_another_revision(sandbox):
    write_gate_inputs(sandbox)
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-018/INDEPENDENCE_AUDIT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["audited_sha256"] = "d" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "BLOCKED"
    assert "INDEPENDENCE_NOT_PROVEN" in decision["blockers"]


def test_gate_rejects_an_audit_that_found_reuse(sandbox):
    write_gate_inputs(sandbox)
    path = sandbox / "reports/ai-bots/RFC-DEF-RUN-018/INDEPENDENCE_AUDIT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({"state": "FAIL", "independent": False, "reasons": ["FORBIDDEN_IMPORT"]})
    path.write_text(json.dumps(payload), encoding="utf-8")
    decision = gate.decide(sandbox)
    assert decision["technical_integrity"] == "BLOCKED"
    assert decision["technical_detail"]["independence_demonstrated"] is False
