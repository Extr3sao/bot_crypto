"""WP-DEF-018-03 — la procedencia del código se escribe antes, no se reconstruye después.

El hueco que este fichero cierra es concreto: RFC-DEF-018 reprodujo los runs de 017 y aun
así tuvo que publicar ``original_commit = null`` porque la cabecera ``RUN`` no guardaba el
commit. Los casos de aquí exigen tres cosas distintas, y las tres a la vez:

* el bloque se escribe **en la primera línea** del ledger, antes de cualquier decisión;
* contiene hechos (commit completo, blob y sha256 de cada fichero que ejecuta) y no una
  declaración de buena fe;
* cuando no hay repositorio, fichero ausente o árbol sucio en el runtime, lo dice en
  ``unavailable_reasons`` en vez de producir un bloque que parezca completo.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries, verify_chain
from trading_bot.vision.provenance import (
    PROVENANCE_PATHS,
    capture,
    dirty_paths,
    resolve_head,
)
from trading_bot.vision.provider import ReplayProvider
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
HOUR_MS = 3_600_000
START_MS = 1_770_000_000_000

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


# --------------------------------------------------------------------------- fixtures


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def repository(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for name, body in (files or {"a.py": "A = 1\n", "b.py": "B = 2\n"}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    return root


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- captura


def test_a_run_records_the_commit_and_the_bytes_it_will_execute(tmp_path):
    root = repository(tmp_path)
    block = capture(root, paths=("a.py", "b.py"))

    assert block["schema"] == "VISION_RUN_CODE_PROVENANCE_V1"
    assert block["commit"] == git(root, "rev-parse", "HEAD")
    assert block["head_at_capture"] == block["commit"]
    assert block["files"]["a.py"] == {
        "sha256": sha256(root / "a.py"),
        "blob": git(root, "hash-object", "--", "a.py"),
    }
    assert block["worktree"]["runtime_dirty"] == []
    assert block["unavailable_reasons"] == [], (
        "un bloque limpio no declara excusas: la lista vacía es la señal utilizable"
    )
    #: el bloque no lleva reloj propio, así que dos corridas idénticas escriben lo mismo
    assert "captured_at_utc" not in block


def test_a_dirty_runtime_file_is_disclosed_and_disqualifies_the_block(tmp_path):
    root = repository(tmp_path)
    (root / "a.py").write_text("A = 99\n", encoding="utf-8")

    block = capture(root, paths=("a.py", "b.py"))

    assert block["worktree"]["runtime_dirty"] == ["a.py"]
    assert "RUNTIME_PATHS_DIRTY" in block["unavailable_reasons"]
    #: el blob del árbol ya no es el del commit: es exactamente lo que hay que ver
    assert block["files"]["a.py"]["blob"] != git(root, "rev-parse", "HEAD:a.py")


def test_dirt_outside_the_runtime_is_disclosed_without_invalidating_the_commit(tmp_path):
    """La política es ``CLEAN_RUNTIME_PATHS`` y se publica; no se finge un árbol limpio."""
    root = repository(tmp_path)
    (root / "notes.md").write_text("trabajo de otro agente\n", encoding="utf-8")
    (root / "b.py").write_text("B = 3\n", encoding="utf-8")

    block = capture(root, paths=("a.py",))

    assert block["worktree"]["runtime_dirty"] == []
    assert block["worktree"]["dirty_outside_runtime_total"] == 2
    assert block["worktree"]["fully_clean"] is False
    assert block["unavailable_reasons"] == []


def test_a_missing_runtime_file_is_recorded_not_dropped_silently(tmp_path):
    root = repository(tmp_path)

    block = capture(root, paths=("a.py", "missing.py"))

    assert block["missing_runtime_paths"] == ["missing.py"]
    assert "missing.py" not in block["files"]
    assert "RUNTIME_PATH_MISSING" in block["unavailable_reasons"]


def test_a_directory_that_is_not_a_repository_has_no_commit_to_declare(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("A = 1\n", encoding="utf-8")

    block = capture(plain, paths=("a.py",))

    assert block["commit"] is None
    assert block["head_at_capture"] is None
    assert "NOT_A_REPOSITORY" in block["unavailable_reasons"]
    assert resolve_head(plain) is None
    assert dirty_paths(plain) == []


# --------------------------------------------------------------------------- el lane


def flat_profile(count: int = 48) -> list[Bar]:
    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        bars.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
                volume=100.0,
            )
        )
    return bars


NO_TRADE = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"NO_TRADE",'
    '"confidence":0.2,"horizon_bars":4,"stop_loss_pct":null,"take_profit_pct":null,'
    '"invalidation":null,"rationale":"nothing actionable"}'
)


def vision_config():
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1h",
            window_bars=30,
            decision_every_bars=5,
            max_calls_per_run=50,
            max_estimated_spend_usd=5.0,
        ),
    )


def run_lane(tmp_path: Path, *, code_root: Path) -> list[dict]:
    lane = VisionLane(
        series={"BTC/USDT": flat_profile()},
        provider=ReplayProvider(lambda _request: NO_TRADE),
        config=vision_config(),
        risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
        ledger_path=tmp_path / "ledger.jsonl",
        book_id="wp-def-018-03",
        code_root=code_root,
    )
    lane.run()
    return read_entries(tmp_path / "ledger.jsonl")


def test_the_commit_is_written_in_the_first_line_before_any_decision(tmp_path):
    head = resolve_head(REPO)
    assert head is not None, "estas pruebas se ejecutan dentro del repositorio"

    rows = run_lane(tmp_path, code_root=REPO)

    assert rows[0]["entry"]["kind"] == "RUN", "el bloque pertenece a la cabecera, no al cierre"
    block = rows[0]["entry"]["code_provenance"]
    assert block["commit"] == head
    assert block["head_at_capture"] == head
    assert set(PROVENANCE_PATHS) <= set(block["files"])
    assert block["files"]["src/trading_bot/vision/lane.py"]["sha256"] == sha256(
        REPO / "src/trading_bot/vision/lane.py"
    )
    #: sigue siendo un ledger: el control nuevo no rompe la cadena ni su recuento de tipos
    assert verify_chain(tmp_path / "ledger.jsonl")["ok"] is True


def test_a_run_outside_a_repository_declares_the_gap_instead_of_inventing_a_commit(tmp_path):
    rows = run_lane(tmp_path, code_root=tmp_path / "nowhere")

    block = rows[0]["entry"]["code_provenance"]
    assert block["commit"] is None
    assert "NOT_A_REPOSITORY" in block["unavailable_reasons"]
    #: el run no se cae: registrar la ausencia es un resultado, no una excepción
    assert rows[-1]["entry"]["kind"] == "RUN_END"
