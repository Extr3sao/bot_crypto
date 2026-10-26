"""DEF-RUN-017 — atacar al verificador, no al runtime.

El verificador solo vale si **falla** cuando la evidencia está mal. Cada prueba copia la
evidencia publicada a un sandbox, introduce un defecto concreto y exige un código de fallo
con nombre. Los ataques que reescriben el ledger recalculan la cadena hash a propósito: así
se comprueba que las comprobaciones semánticas no dependen de que la cadena esté intacta.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
RFC16 = Path("reports/ai-bots/RFC-DEF-RUN-016")
RFC17 = Path("reports/ai-bots/RFC-DEF-RUN-017")
SCENARIO = "m1_cadence1"


OOS_FILES = (
    "OOS_PLAN.json",
    "OOS_RESULTS.json",
    "OOS_RUNS_untouched_test.json",
    "OOS_RUNS_untouched_test_cost2.json",
    "OOS_STRESS_COST2.json",
)


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "def_run_017_verify", REPO / "scripts" / "def_run_017_verify.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verifier = load_verifier()


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    #: Se copia el paquete de evidencia completo (ledgers, capturas y manifiesto): el
    #: manifiesto declara 14 artefactos y un sandbox a medias haría fallar el ancla externa
    #: por una razón que no es el defecto que se quiere probar.
    shutil.copytree(REPO / RFC16 / "evidence", root / RFC16 / "evidence")
    target = root / RFC17 / "evidence"
    target.mkdir(parents=True)
    for name in ("ECONOMIC_ATTRIBUTION.json", "TRADE_LEDGER.csv", "PAIRED_DELTA.csv"):
        shutil.copy2(REPO / RFC17 / "evidence" / name, target / name)
    #: El bloque OOS se copia entero salvo los 122 MB de ledgers diarios: el verificador
    #: emite el check de hashes de ledger solo cuando los bytes están, y eso se declara in
    #: ``oos.ledgers_in_checkout`` en lugar de fingir que se comprobó.
    (target / "oos").mkdir()
    for name in OOS_FILES:
        shutil.copy2(REPO / RFC17 / "evidence" / "oos" / name, target / "oos" / name)
    return root


def ledger_path(root: Path, label: str = "CURRENT", scenario: str = SCENARIO) -> Path:
    return root / RFC16 / "evidence" / "ledgers" / label / f"{scenario}.jsonl"


def records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rechain(path: Path, rows: list[dict[str, Any]]) -> None:
    """Reescribe el ledger con la cadena **válida**: el ataque no es un byte, es un dato."""
    prev = "0" * 64
    lines: list[str] = []
    for seq, row in enumerate(rows, start=1):
        entry = row["entry"]
        digest = hashlib.sha256(
            json.dumps(
                {"seq": seq, "prev_sha256": prev, "entry": entry},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        lines.append(
            json.dumps(
                {"seq": seq, "prev_sha256": prev, "entry": entry, "sha256": digest},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        prev = digest
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def codes(report: dict[str, Any]) -> set[str]:
    return {check["code"] for check in report["failed_checks"]}


# -- línea base -----------------------------------------------------------------


def test_the_published_evidence_passes(sandbox):
    report = verifier.verify(sandbox)
    assert report["status"] == "PASS", report["failed_checks"]
    assert report["checks"] >= 130
    assert report["totals"]["delta_net_usdt"] == "-8.11618174"


# -- ataques ---------------------------------------------------------------------


def test_the_versioned_package_alone_is_enough_for_a_clean_checkout(tmp_path):
    """Sin `reports/` (gitignored), la evidencia versionada debe bastar."""
    root = tmp_path / "clean"
    for package in (REPO / "data" / "def-run-016", REPO / "data" / "def-run-017"):
        relative = package.relative_to(REPO)
        if not package.is_dir():
            pytest.skip(f"package not built yet: {relative}")
        shutil.copytree(package, root / relative)
    report = verifier.verify(root)
    assert report["status"] == "PASS", report["failed_checks"]
    used = report["ledgers"]["CURRENT"][SCENARIO]["path"]
    assert "data" in Path(used).parts


def test_a_missing_ledger_blocks_instead_of_passing(sandbox):
    ledger_path(sandbox).unlink()
    with pytest.raises(verifier.Blocked) as error:
        verifier.verify(sandbox)
    assert error.value.code == "MISSING_LEDGER"


def test_a_single_altered_price_breaks_the_chain(sandbox):
    path = ledger_path(sandbox)
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if '"kind":"FILL"' in line:
            lines[index] = line.replace('"entry_price":', '"entry_price":9', 1)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert any(code.startswith("CHAIN_CURRENT") for code in codes(report))


def test_an_altered_fee_with_a_valid_chain_is_still_caught(sandbox):
    path = ledger_path(sandbox)
    rows = records(path)
    for row in rows:
        if row["entry"].get("kind") == "FILL":
            row["entry"]["entry_commission_usdt"] = 9.99
        if row["entry"].get("kind") == "CLOSE":
            row["entry"]["exit_commission_usdt"] = 9.99
            row["entry"]["commissions_usdt"] = 19.98
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert any(code.startswith("NET_FROM_CASH") for code in codes(report))


def test_a_duplicated_fill_is_caught_even_with_a_valid_chain(sandbox):
    path = ledger_path(sandbox)
    rows = records(path)
    index = next(i for i, row in enumerate(rows) if row["entry"].get("kind") == "FILL")
    rows.insert(index, json.loads(json.dumps(rows[index])))
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"ONE_FILL_PER_DECISION_CURRENT_{SCENARIO}" in codes(report)


def test_a_deleted_close_leaves_a_fill_without_its_terminal(sandbox):
    path = ledger_path(sandbox)
    rows = [row for row in records(path) if row["entry"].get("kind") != "CLOSE"]
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"NO_FILL_WITHOUT_CLOSE_CURRENT_{SCENARIO}" in codes(report)


def test_a_duplicated_close_is_caught(sandbox):
    path = ledger_path(sandbox)
    rows = records(path)
    index = next(i for i, row in enumerate(rows) if row["entry"].get("kind") == "CLOSE")
    rows.insert(index, json.loads(json.dumps(rows[index])))
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"ONE_CLOSE_PER_POSITION_CURRENT_{SCENARIO}" in codes(report)


def test_a_deleted_run_end_is_not_a_summary(sandbox):
    path = ledger_path(sandbox)
    rows = [row for row in records(path) if row["entry"].get("kind") != "RUN_END"]
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"RUN_END_LAST_CURRENT_{SCENARIO}" in codes(report)


def test_a_forged_run_end_number_is_refused(sandbox):
    path = ledger_path(sandbox)
    rows = records(path)
    for row in rows:
        if row["entry"].get("kind") == "RUN_END":
            row["entry"]["pnl_realised_usdt"] = 1234.5
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"RUN_END_NET_RECONCILED_CURRENT_{SCENARIO}" in codes(report)


def test_a_deleted_losing_trade_is_caught_by_the_counters(sandbox):
    """Borrar la operación perdedora entera deja el RUN_END mintiendo."""
    path = ledger_path(sandbox)
    rows = [
        row
        for row in records(path)
        if row["entry"].get("kind") not in ("FILL", "CLOSE")
    ]
    rechain(path, rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert f"RUN_END_COUNTERS_MATCH_EVENTS_CURRENT_{SCENARIO}" in codes(report)


def test_an_edited_attribution_report_is_caught(sandbox):
    path = sandbox / RFC17 / "evidence" / "ECONOMIC_ATTRIBUTION.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["totals"]["delta_net_usdt"] = "-1.00000000"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "ATTRIBUTION_DELTA_MATCHES" in codes(report)


def test_an_edited_trade_ledger_is_caught(sandbox):
    path = sandbox / RFC17 / "evidence" / "TRADE_LEDGER.csv"
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    rows[0]["realized_pnl_quote"] = "999.0"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "TRADE_LEDGER_NET_MATCHES_LEDGERS" in codes(report)


def test_an_edited_pair_delta_is_caught(sandbox):
    path = sandbox / RFC17 / "evidence" / "PAIRED_DELTA.csv"
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    rows[0]["realized_delta"] = "0.00000000"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "PAIRED_DELTA_RECONCILES_TO_DELTA" in codes(report)


def test_a_missing_manifest_blocks(sandbox):
    (sandbox / RFC16 / "evidence" / "ARTIFACT_MANIFEST.json").unlink()
    with pytest.raises(verifier.Blocked) as error:
        verifier.verify(sandbox)
    assert error.value.code == "MISSING_RFC16_MANIFEST"


def test_an_edited_rfc016_artifact_is_caught_by_its_manifest(sandbox):
    path = sandbox / RFC16 / "evidence" / "ECONOMICS.json"
    path.write_bytes(path.read_bytes().replace(b"1", b"2", 1))
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "RFC16_EVIDENCE_HASHES_MATCH" in codes(report)


def test_a_report_claiming_pass_over_broken_evidence_is_a_false_success(sandbox):
    ledger_path(sandbox).unlink(missing_ok=False)
    report_path = sandbox / RFC17 / "RUN_REPORT.json"
    report_path.write_text(
        json.dumps(
            {
                "technical_status": "PASS",
                "false_success": 0,
                "economics": {
                    "baseline_net_usdt": "-22.68341544",
                    "candidate_net_usdt": "-30.79959719",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with pytest.raises(verifier.Blocked):
        verifier.verify(sandbox)


def oos_results(root: Path) -> dict[str, Any]:
    return json.loads((root / RFC17 / "evidence" / "oos" / "OOS_RESULTS.json").read_text())


def write_oos_results(root: Path, payload: dict[str, Any]) -> None:
    (root / RFC17 / "evidence" / "oos" / "OOS_RESULTS.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_a_hand_written_evidence_status_is_caught(sandbox):
    """El estado económico no se declara: se recalcula con la regla congelada."""
    payload = oos_results(sandbox)
    payload["decision"]["economic_status"] = "EVIDENCED"
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_DECISION_RULE_REAPPLIED" in codes(report)


def test_a_deferral_arm_that_never_deferred_is_caught(sandbox):
    """El defecto real del 2026-10-21: `deferred_slots=0` en una rama que aplazó 4.700."""
    payload = oos_results(sandbox)
    payload["cells"]["UNI/USDT|DEFER|1.0"]["deferred_slots"] = 0
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_LIFECYCLE_ACTUALLY_DIFFERS" in codes(report)


def test_a_daily_delta_that_does_not_match_the_cells_is_caught(sandbox):
    payload = oos_results(sandbox)
    payload["paired_day_deltas"]["UNI/USDT"]["per_day_usdt"][0] += 1.0
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_PAIRED_DELTA_ARITHMETIC" in codes(report)


def test_a_widened_bootstrap_interval_is_caught(sandbox):
    """Ensanchar el IC a mano es la forma barata de fabricar un resultado."""
    payload = oos_results(sandbox)
    payload["paired_day_deltas"]["AAVE/USDT"]["ci95"] = [-100.0, 100.0]
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_BOOTSTRAP_REPRODUCED" in codes(report)


def test_a_plan_edited_after_the_results_is_caught(sandbox):
    """Si el plan cambia después, ``plan_sha256`` deja de anclar y el OOS deja de ser OOS."""
    path = sandbox / RFC17 / "evidence" / "oos" / "OOS_PLAN.json"
    plan = json.loads(path.read_text())
    plan["symbols"] = ["BTC/USDT"]
    path.write_text(json.dumps(plan), encoding="utf-8")
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_PLAN_HASH_ANCHORED" in codes(report)


def test_a_missing_oos_cell_is_caught(sandbox):
    payload = oos_results(sandbox)
    del payload["cells"]["UNI/USDT|DEFER|1.0"]
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_GRID_COMPLETE" in codes(report)


def test_a_cell_whose_days_do_not_add_up_is_caught(sandbox):
    payload = oos_results(sandbox)
    cell = payload["cells"]["AAVE/USDT|SUPERSEDE|1.0"]
    cell["per_day_net"] = [*cell["per_day_net"][:-1], cell["per_day_net"][-1] - 5.0]
    write_oos_results(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_CELL_ARITHMETIC" in codes(report)


def stress_payload(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / RFC17 / "evidence" / "oos" / "OOS_STRESS_COST2.json").read_text()
    )


def write_stress(root: Path, payload: dict[str, Any]) -> None:
    (root / RFC17 / "evidence" / "oos" / "OOS_STRESS_COST2.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_a_stress_block_that_claims_to_decide_is_caught(sandbox):
    """El estrés x2 no puede convertirse en la decisión por un campo booleano."""
    payload = stress_payload(sandbox)
    payload["used_for_decision"] = True
    write_stress(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_STRESS_NOT_DECISIVE" in codes(report)


def test_a_hand_written_stress_status_is_caught(sandbox):
    payload = stress_payload(sandbox)
    payload["stress_status"] = "EVIDENCED"
    write_stress(sandbox, payload)
    report = verifier.verify(sandbox)
    assert report["status"] == "FAIL"
    assert "OOS_STRESS_STATUS_REAPPLIED" in codes(report)


def test_the_stress_does_not_enter_the_primary_grid(sandbox):
    """Añadir el estrés no puede añadir celdas ni mover el estado económico primario."""
    report = verifier.verify(sandbox)
    assert report["status"] == "PASS"
    assert set(report["oos"]["cells"]) == {
        "UNI/USDT|DEFER|1.0",
        "UNI/USDT|SUPERSEDE|1.0",
        "AAVE/USDT|DEFER|1.0",
        "AAVE/USDT|SUPERSEDE|1.0",
    }
    assert report["oos"]["economic_status"] == "NOT_EVIDENCED"
    assert report["oos_stress"]["used_for_decision"] is False


def test_without_ledger_bytes_the_verifier_says_so_instead_of_passing_it(sandbox):
    """Un sandbox sin los JSONL no puede afirmar que los hashes de ledger cuadran."""
    report = verifier.verify(sandbox)
    assert report["status"] == "PASS"
    assert report["oos"]["ledgers_in_checkout"] is False
    assert "OOS_LEDGER_BYTES_MATCH_RECORD" not in set(report["check_codes"])


def test_the_cli_exit_code_is_not_zero_when_the_chain_is_broken(sandbox, tmp_path):
    path = ledger_path(sandbox)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"equity_usdt":10000.0', '"equity_usdt":9999.0')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    code = verifier.main(
        ["--root", str(sandbox), "--json", str(tmp_path / "verification.json")]
    )
    assert code == 1
    payload = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
