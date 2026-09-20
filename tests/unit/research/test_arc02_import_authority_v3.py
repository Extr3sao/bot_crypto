"""ARC02 V3 import-authority adversarial suite (work order §19, cases A-K).

Every subprocess-based test spawns the real interpreter of this environment with
the real ambient contamination (shared venv editable ``.pth`` + explicit
``PYTHONPATH`` pointing at the main checkout) and proves target-only resolution
or fail-closed behavior. No test relies on cwd; no test skips.

These are builder-side checks only (never independent verification).

Case map (work order §19):
  A  main editable .pth + target V3            -> target PASS
  B  main PYTHONPATH before target             -> target PASS (authority holds)
  C  wrong trading_bot preloaded in sys.modules -> FAIL CLOSED
  D  pytest against target                     -> target files only
  E  subprocess from contaminated parent       -> target files only
  F  arbitrary cwd                             -> PASS
  G  wrong checkout                            -> FAIL CLOSED
  H  wrong commit                              -> FAIL CLOSED
  I  fresh detached V3 checkout                -> PASS
  J  wrong data root                           -> FAIL CLOSED
  K  empty data root                           -> FAIL CLOSED
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[3]
MAIN_REPO = Path(r"C:\Users\GVLLFR0035\Downloads\bot freebuff")
MAIN_SRC = MAIN_REPO / "src"
PY = sys.executable
SITE_PACKAGES = Path(sysconfig.get_paths()["purelib"])

EXPECTED_COMMIT = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=str(WORKTREE), text=True
).strip()

CONTAMINATED_ENV = {**os.environ, "PYTHONPATH": str(MAIN_SRC)}


def _run(code: str, *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "-c", code], cwd=str(cwd), env=env if env is not None else CONTAMINATED_ENV,
        capture_output=True, text=True,
    )


def _json_out(proc: subprocess.CompletedProcess) -> dict:
    for line in proc.stdout.splitlines():
        if line.startswith("JSON:"):
            return json.loads(line[5:])
    raise AssertionError(f"no JSON output; stdout={proc.stdout[-2000:]} stderr={proc.stderr[-2000:]}")


# --------------------------------------------------------------------------
# A: the shared venv editable .pth (main checkout) + this target -> target PASS
# --------------------------------------------------------------------------
def test_case_A_editable_pth_present_and_target_authority_passes():
    pth = list(SITE_PACKAGES.glob("__editable__*.pth"))
    assert pth, "expected the shared venv editable .pth to exist in this environment"
    contents = [p.read_text(encoding="utf-8", errors="replace") for p in pth]
    assert any(str(MAIN_SRC) in c for c in contents), "editable .pth must point at main src"
    code = """
import json, sys
sys.path.insert(0, {worktree!r})
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02(target_root={worktree!r}, expected_commit={commit!r})
print("JSON:" + json.dumps(ev.to_dict()))
""".format(worktree=str(WORKTREE), commit=EXPECTED_COMMIT)
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    assert proc.returncode == 0, proc.stderr[-3000:]
    d = _json_out(proc)
    assert d["package_within_target"] is True
    assert d["critical_all_within_target"] is True
    assert d["git_head"] == EXPECTED_COMMIT


# --------------------------------------------------------------------------
# B: PYTHONPATH=main src, imported order NOT violated -> authority holds
# --------------------------------------------------------------------------
def test_case_B_pythonpath_main_before_target_authority_passes():
    code = """
import json, sys
sys.path.insert(0, {worktree!r})
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02(target_root={worktree!r}, expected_commit={commit!r})
import trading_bot
d = ev.to_dict()
d["post_bootstrap_import_file"] = getattr(trading_bot, "__file__", None)
print("JSON:" + json.dumps(d))
""".format(worktree=str(WORKTREE), commit=EXPECTED_COMMIT)
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    assert proc.returncode == 0, proc.stderr[-3000:]
    d = _json_out(proc)
    assert d["package_within_target"] is True
    expected_pkg = (WORKTREE / "src" / "trading_bot" / "__init__.py").resolve()
    assert Path(d["post_bootstrap_import_file"]).resolve() == expected_pkg


# --------------------------------------------------------------------------
# C: wrong trading_bot preloaded -> FAIL CLOSED (import-order attack, §11)
# --------------------------------------------------------------------------
def test_case_C_wrong_preloaded_module_fails_closed():
    code = """
import json, os, sys
import trading_bot  # wrong checkout via PYTHONPATH
target = os.environ["ARC02_TARGET_ROOT"]
sys.path.insert(0, target)
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02(target_root=target, expected_commit={commit!r})
    print("JSON:" + json.dumps({{"result": "PASS", "unexpected": True}}))
except Exception as exc:
    print("JSON:" + json.dumps({{"result": "FAIL_CLOSED", "error": str(exc)[:400]}}))
""".format(commit=EXPECTED_COMMIT)
    env = {**CONTAMINATED_ENV, "ARC02_TARGET_ROOT": str(WORKTREE)}
    proc = _run(code, cwd=Path(tempfile.gettempdir()), env=env)
    d = _json_out(proc)
    assert d["result"] == "FAIL_CLOSED", d
    assert "PRELOADED_WRONG_FIRST_PARTY_MODULE" in d["error"]


# --------------------------------------------------------------------------
# D: pytest against target imports target files only (guard enforces §12)
# --------------------------------------------------------------------------
def test_case_D_pytest_authority_guard_active():
    # The running session itself proves this: conftest established authority.
    import trading_bot

    pkg_file = Path(trading_bot.__file__).resolve()
    assert pkg_file == WORKTREE / "src" / "trading_bot" / "__init__.py"
    # and the guard re-verification hooks exist
    conftest_text = (WORKTREE / "conftest.py").read_text(encoding="utf-8")
    assert "pytest_collection" in conftest_text
    assert "PYTEST_AUTHORITY_FAIL_CLOSED" in conftest_text


# --------------------------------------------------------------------------
# E: subprocess from contaminated parent -> target files only (§13)
# --------------------------------------------------------------------------
def test_case_E_subprocess_receives_explicit_authority_and_resolves_target():
    from trading_bot.research.import_authority import subprocess_authority_env

    env = subprocess_authority_env(
        target_root=WORKTREE, expected_commit=EXPECTED_COMMIT, base=CONTAMINATED_ENV
    )
    code = """
import json, os, sys
sys.path.insert(0, os.environ["ARC02_TARGET_ROOT"])
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02()
import trading_bot
d = ev.to_dict()
d["post_import_file"] = getattr(trading_bot, "__file__", None)
print("JSON:" + json.dumps(d))
"""
    proc = _run(code, cwd=Path(tempfile.gettempdir()), env=env)
    assert proc.returncode == 0, proc.stderr[-3000:]
    d = _json_out(proc)
    assert d["package_within_target"] is True
    expected_pkg = (WORKTREE / "src" / "trading_bot" / "__init__.py").resolve()
    assert Path(d["post_import_file"]).resolve() == expected_pkg


def test_case_E2_subprocess_without_authority_contract_fails_closed_under_preload():
    # A contaminated child that imports trading_bot BEFORE bootstrapping must
    # fail closed when the bootstrap finally runs (case C semantics, §13).
    from trading_bot.research.import_authority import subprocess_authority_env

    code = """
import json, os, sys
import trading_bot  # contamination binds the MAIN checkout
target = os.environ["ARC02_TARGET_ROOT"]
sys.path.insert(0, target)
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02()
    print("JSON:" + json.dumps({"result": "PASS"}))
except Exception:
    print("JSON:" + json.dumps({"result": "FAIL_CLOSED"}))
"""
    env = subprocess_authority_env(
        target_root=WORKTREE, expected_commit=EXPECTED_COMMIT, base=CONTAMINATED_ENV
    )
    proc = _run(code, cwd=Path(tempfile.gettempdir()), env=env)
    d = _json_out(proc)
    assert d["result"] == "FAIL_CLOSED"


# --------------------------------------------------------------------------
# F: arbitrary cwd -> PASS
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cwd", [Path.home(), Path(tempfile.gettempdir()), Path("/").resolve()])
def test_case_F_arbitrary_cwd_passes(cwd):
    code = """
import json, sys
from scripts.arc02_import_bootstrap import bootstrap_arc02
ev = bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
"""
    # derive authority from script location: run the bootstrap module by path
    code = """
import json, importlib.util, sys
spec = importlib.util.spec_from_file_location("arc02_boot", {boot!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ev = m.bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
""".format(boot=str(WORKTREE / "scripts" / "arc02_import_bootstrap.py"))
    proc = _run(code, cwd=cwd)
    assert proc.returncode == 0, proc.stderr[-3000:]
    d = _json_out(proc)
    assert d["package_within_target"] is True
    assert d["critical_all_within_target"] is True


# --------------------------------------------------------------------------
# G: wrong checkout -> FAIL CLOSED (§15: commit identity matters)
# --------------------------------------------------------------------------
def test_case_G_wrong_checkout_fails_closed(tmp_path):
    """A full, valid git checkout of the repo at the WRONG commit must fail closed
    when the V3 bootstrap is pointed at it (§15: commit identity matters)."""
    clone = tmp_path / "wrong-checkout"
    subprocess.run(
        ["git", "clone", "--no-checkout", "--quiet", str(MAIN_REPO), str(clone)],
        check=True, capture_output=True,
    )
    wrong_commit = "3ebf5f54bba84300663a9de7f6b05c5b583bc9c6"  # V1 prereg commit
    subprocess.run(
        ["git", "checkout", "--quiet", wrong_commit], cwd=str(clone),
        check=True, capture_output=True,
    )
    code = """
import json, importlib.util
spec = importlib.util.spec_from_file_location("arc02_boot", {boot!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
try:
    m.bootstrap_arc02(target_root={target!r}, expected_commit={commit!r})
    print("JSON:" + json.dumps({{"result": "PASS"}}))
except Exception as exc:
    print("JSON:" + json.dumps({{"result": "FAIL_CLOSED", "error": str(exc)[:300]}}))
""".format(boot=str(WORKTREE / "scripts" / "arc02_import_bootstrap.py"), target=str(clone), commit=EXPECTED_COMMIT)
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    d = _json_out(proc)
    assert d["result"] == "FAIL_CLOSED"
    # Either refusal mode is fail-closed: the wrong checkout may lack the V3
    # contract entirely, or carry it with a mismatching git identity.
    assert ("git HEAD mismatch" in d["error"]) or ("cannot load import authority contract" in d["error"])


def test_case_G2_non_git_directory_fails_closed(tmp_path):
    """A look-alike tree with no git identity is refused (never accepted by appearance)."""
    fake = tmp_path / "wrong-checkout"
    (fake / "src" / "trading_bot" / "research").mkdir(parents=True)
    (fake / "src" / "trading_bot" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "src" / "trading_bot" / "research" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "src" / "trading_bot" / "research" / "import_authority.py").write_text(
        (WORKTREE / "src" / "trading_bot" / "research" / "import_authority.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_scripts = fake / "scripts"
    fake_scripts.mkdir()
    (fake_scripts / "arc02_import_bootstrap.py").write_text(
        (WORKTREE / "scripts" / "arc02_import_bootstrap.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    code = """
import json, sys
sys.path.insert(0, {target!r})
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02(target_root={target!r}, expected_commit={commit!r})
    print("JSON:" + json.dumps({{"result": "PASS"}}))
except Exception as exc:
    print("JSON:" + json.dumps({{"result": "FAIL_CLOSED", "error": str(exc)[:200]}}))
""".format(target=str(fake), commit=EXPECTED_COMMIT)
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    d = _json_out(proc)
    assert d["result"] == "FAIL_CLOSED"
    assert ("git HEAD mismatch" in d["error"]) or ("cannot determine git HEAD" in d["error"])


# --------------------------------------------------------------------------
# H: wrong commit -> FAIL CLOSED
# --------------------------------------------------------------------------
def test_case_H_wrong_commit_fails_closed():
    code = """
import json, sys
sys.path.insert(0, {target!r})
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02(target_root={target!r}, expected_commit="0" * 40)
    print("JSON:" + json.dumps({{"result": "PASS"}}))
except Exception as exc:
    print("JSON:" + json.dumps({{"result": "FAIL_CLOSED", "error": str(exc)[:200]}}))
""".format(target=str(WORKTREE))
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    d = _json_out(proc)
    assert d["result"] == "FAIL_CLOSED"
    assert "git HEAD mismatch" in d["error"]


# --------------------------------------------------------------------------
# I: fresh V3 checkout -> PASS
# --------------------------------------------------------------------------
def test_case_I_fresh_v3_tree_passes(tmp_path):
    """Pre-commit form: a byte copy of this (V3) tree — including the .git link —
    bootstraps from an arbitrary cwd with no ambient help. The true detached
    fresh worktree form is validated post-commit (§24 builder crosscheck)."""
    copy = tmp_path / "fresh-v3-copy"
    shutil.copytree(WORKTREE, copy, symlinks=True)
    code = """
import json, importlib.util
spec = importlib.util.spec_from_file_location("arc02_boot", {boot!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ev = m.bootstrap_arc02()
print("JSON:" + json.dumps(ev.to_dict()))
""".format(boot=str(copy / "scripts" / "arc02_import_bootstrap.py"))
    proc = _run(code, cwd=Path(tempfile.gettempdir()))
    assert proc.returncode == 0, proc.stderr[-3000:]
    d = _json_out(proc)
    assert d["package_within_target"] is True
    assert d["git_head"] == EXPECTED_COMMIT
    assert d["target_root"].endswith("fresh-v3-copy")


# --------------------------------------------------------------------------
# J/K: wrong data root and empty data root FAIL CLOSED (§16)
# --------------------------------------------------------------------------
def test_case_J_wrong_data_root_fails_closed(tmp_path):
    from trading_bot.research.arc02 import arc02_authority as A

    wrong = tmp_path / "definitely_not_the_data_root"
    wrong.mkdir()
    with pytest.raises(FileNotFoundError):
        A.load_partition("BTCUSDT", partition_dir=wrong)


def test_case_K_empty_data_root_fails_closed(tmp_path):
    from trading_bot.research.arc02 import arc02_authority as A

    with pytest.raises(FileNotFoundError):
        A.load_partition("BTCUSDT", partition_dir=tmp_path)


def test_case_J2_wrong_data_root_via_env_fails_closed(monkeypatch, tmp_path):
    from trading_bot.research.arc02 import arc02_authority as A

    monkeypatch.setenv("ARC02_DATA_ROOT", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        A.load_partition("BTCUSDT")


# --------------------------------------------------------------------------
# Contract-level unit checks (no subprocess): canonical identity + frozen class
# --------------------------------------------------------------------------
def test_canonical_identity_is_separator_stable():
    from trading_bot.research.import_authority import norm, within

    back = str(WORKTREE / "src" / "trading_bot" / "__init__.py")
    fwd = back.replace("\\", "/")
    assert norm(back) == norm(fwd)
    assert within(back, WORKTREE / "src") is True


def test_within_rejects_prefix_deception(tmp_path):
    from trading_bot.research.import_authority import within

    sibling = tmp_path / "target-evil"
    sibling.mkdir()
    real = tmp_path / "target"
    real.mkdir()
    assert within(sibling, real) is False


def test_frozen_authority_rejects_mutation():
    from trading_bot.research.import_authority import CheckoutImportAuthority

    a = CheckoutImportAuthority(
        target_root=WORKTREE, expected_commit=EXPECTED_COMMIT, package_name="trading_bot"
    )
    with pytest.raises(AttributeError):
        a.expected_commit = "0" * 40
