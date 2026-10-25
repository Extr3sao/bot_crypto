"""WP-DEF-018-03 — B mide la procedencia del código sin creerle al productor.

Los casos de este fichero construyen el bloque a mano (no con
``trading_bot.vision.provenance``): el verificador tiene que sostener un ``PASS`` contra
Git, no contra el módulo que escribió el bloque. Cada control negativo rompe una sola
cosa, para que el motivo del ``FAIL`` diga cuál.

El dominio es aparte del sujeto 017 a propósito: el recuento de 383 comprobaciones del
paquete sellado no cambia porque se añada un control prospectivo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
CORE = (
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/provenance.py",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verifier = load_module("def_run_018_verify_b_prov", REPO / "scripts" / "def_run_018_verify_b.py")
gate = load_module("def_run_018_gate_prov", REPO / "scripts" / "def_run_018_gate.py")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for relative in CORE:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {relative}\nVALUE = 1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    return root


def make_block(
    root: Path,
    *,
    commit: str | None = None,
    paths: tuple[str, ...] = CORE,
    sha_overrides: dict[str, str] | None = None,
    declared: tuple[str, ...] | None = None,
    dirty: tuple[str, ...] = (),
    drop: str | None = None,
) -> dict[str, Any]:
    """Un bloque verosímil, escrito aquí y no por el productor."""
    head = commit or git(root, "rev-parse", "HEAD")
    files = {
        relative: {
            "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            "blob": git(root, "hash-object", "--", relative),
        }
        for relative in paths
        if relative != drop
    }
    files.update({name: {"sha256": digest, "blob": files[name]["blob"]}
                  for name, digest in (sha_overrides or {}).items() if name in files})
    return {
        "schema": "VISION_RUN_CODE_PROVENANCE_V1",
        "policy": "CLEAN_RUNTIME_PATHS",
        "captured_at_utc": "2026-10-21T00:00:00Z",
        "commit": head,
        "head_at_capture": head,
        "files": files,
        "runtime_paths": sorted(declared if declared is not None else paths),
        "missing_runtime_paths": [],
        "worktree": {
            "runtime_dirty": list(dirty),
            "dirty_outside_runtime": [],
            "dirty_outside_runtime_total": 0,
            "fully_clean": not dirty,
        },
        "unavailable_reasons": [],
    }


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


def ledger_with(tmp_path: Path, run_entry: dict[str, Any], name: str = "run.jsonl") -> Path:
    path = tmp_path / name
    chain_write(
        path,
        [run_entry, {"kind": "RUN_END", "net_realised_usdt": 0.0}],
    )
    return path


def states(payload: dict[str, Any]) -> dict[str, str]:
    return {item["code"]: item["state"] for item in payload["checks"]}


# --------------------------------------------------------------------------- B


def test_a_block_that_matches_git_passes(tmp_path):
    root = repository(tmp_path)
    ledger = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": make_block(root)})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "PASS", payload["ledgers"]
    assert payload["counts"] == {"PASS": 1, "FAIL": 0, "NOT_EVIDENCED": 0}
    #: diez controles por ledger: esquema, commit, política, cabeza, resolución, cobertura
    #: de ficheros, rutas mínimas, blobs, bytes y árbol de ejecución
    assert payload["checks_total"] == 10
    assert set(states(payload).values()) == {"PASS"}


def test_a_ledger_without_a_block_is_not_evidenced_not_failed(tmp_path):
    root = repository(tmp_path)
    ledger = ledger_with(tmp_path, {"kind": "RUN", "book_id": "def-run-017"})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "NOT_EVIDENCED"
    assert payload["ledgers"][0]["reasons"] == ["PRE_CONTROL_LEDGER"]
    assert payload["checks_total"] == 0, "no se inventan comprobaciones para un ledger histórico"


def test_a_commit_that_git_does_not_know_fails(tmp_path):
    root = repository(tmp_path)
    ledger = ledger_with(
        tmp_path, {"kind": "RUN", "code_provenance": make_block(root, commit="f" * 40)}
    )

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "FAIL"
    assert "COMMIT_RESOLVES" in payload["ledgers"][0]["reasons"]
    assert states(payload)["CODE_PROVENANCE_COMMIT_RESOLVES"] == "FAIL"


def test_edited_bytes_are_caught_even_when_the_blob_still_matches(tmp_path):
    """El blob ata el commit; el sha256 ata los bytes que *se ejecutaron*."""
    root = repository(tmp_path)
    target = CORE[2]
    block = make_block(root, sha_overrides={target: "0" * 64})
    ledger = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": block})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "FAIL"
    assert payload["ledgers"][0]["reasons"] == ["BYTES_AT_COMMIT"]
    assert states(payload)["CODE_PROVENANCE_BLOBS_AT_COMMIT"] == "PASS"


def test_a_dirty_runtime_is_not_provenance(tmp_path):
    root = repository(tmp_path)
    block = make_block(root, dirty=(CORE[0],))
    ledger = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": block})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "FAIL"
    assert payload["ledgers"][0]["reasons"] == ["WORKTREE_RUNTIME_CLEAN"]


def test_a_shrunk_file_list_cannot_certify_itself(tmp_path):
    """Si el productor declara solo lo que le conviene, B exige su propio mínimo."""
    root = repository(tmp_path)
    block = make_block(root, paths=(CORE[2],))
    ledger = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": block})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "FAIL"
    assert payload["ledgers"][0]["reasons"] == ["RUNTIME_PATHS_COVERED"]


def test_a_file_hashed_but_not_declared_fails(tmp_path):
    root = repository(tmp_path)
    block = make_block(root, declared=CORE[:-1])
    ledger = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": block})

    payload = verifier.code_provenance(root, [ledger])

    assert payload["status"] == "FAIL"
    assert "FILES_COVER_DECLARED" in payload["ledgers"][0]["reasons"]


def test_one_doubtful_ledger_cannot_hide_behind_a_good_one(tmp_path):
    root = repository(tmp_path)
    good = ledger_with(tmp_path, {"kind": "RUN", "code_provenance": make_block(root)}, "a.jsonl")
    bad = ledger_with(
        tmp_path, {"kind": "RUN", "code_provenance": make_block(root, commit="a" * 40)}, "b.jsonl"
    )
    old = ledger_with(tmp_path, {"kind": "RUN", "book_id": "def-run-017"}, "c.jsonl")

    payload = verifier.code_provenance(root, [good, bad, old])

    assert payload["status"] == "FAIL"
    assert payload["counts"] == {"PASS": 1, "FAIL": 1, "NOT_EVIDENCED": 1}
    #: un PASS junto a un histórico sigue sin ser un PASS global
    assert verifier.code_provenance(root, [good, old])["status"] == "NOT_EVIDENCED"


# --------------------------------------------------------------------------- gate


def gate_sandbox(tmp_path: Path, provenance: dict[str, Any]) -> Path:
    root = tmp_path / "gate"
    out = root / "reports" / "ai-bots" / "RFC-DEF-RUN-018"
    out.mkdir(parents=True)
    script = root / "scripts" / "def_run_018_verify_b.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "def_run_018_verify_b.py", script)
    (out / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "checks_total": 383,
                "summary": {"PASS": 383},
                "controls": [],
                "independence": {"imports_trading_bot": False, "reused_recomputation_code": []},
                "run_provenance": provenance,
            }
        ),
        encoding="utf-8",
    )
    (out / "INDEPENDENCE_AUDIT.json").write_text(
        json.dumps(
            {
                "independent": True,
                "state": "PASS",
                "reasons": [],
                "audited_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (out / "CLEAN_REPRO_RUN_REPORT.json").write_text(
        json.dumps(
            {
                "status": "CLEAN_CHECKOUT_REPRODUCED",
                "runtime_executed": True,
                "paper_validation": "PERFORMED",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_the_gate_turns_a_failed_commit_into_a_failure_of_integrity(tmp_path):
    root = gate_sandbox(
        tmp_path,
        {"status": "FAIL", "counts": {"FAIL": 1}, "checks_total": 10,
         "ledgers": [{"status": "FAIL", "reasons": ["COMMIT_RESOLVES"]}]},
    )

    decision = gate.decide(root)

    assert decision["technical_integrity"] == "FAIL"
    assert "CODE_PROVENANCE_FAILED" in decision["blockers"]
    assert any(item["code"] == "CODE_PROVENANCE_UNPROVEN" for item in decision["defects"])
    assert decision["paper_admission"] == "NO_GO"


def test_the_gate_declares_an_unproven_provenance_without_faking_a_pass(tmp_path):
    root = gate_sandbox(
        tmp_path, {"status": "NOT_EVIDENCED", "counts": {"NOT_EVIDENCED": 1}, "ledgers": []}
    )

    decision = gate.decide(root)

    assert decision["technical_detail"]["code_provenance"] == "NOT_EVIDENCED"
    assert any("code_provenance=NOT_EVIDENCED" in reason for reason in decision["reasons"])
    assert decision["paper_admission"] == "NO_GO"
