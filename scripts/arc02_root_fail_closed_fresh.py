import os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-v2-repair-01').resolve()
MAIN_SRC = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/src').resolve()
env_base = os.environ.copy()
env_base['PYTHONPATH'] = str(MAIN_SRC)

helper_dir = str(Path(__file__).resolve().parent)

cases = {}

with tempfile.TemporaryDirectory() as td:
    def run_case(name: str, target_root: Path) -> dict:
        script = f"""
import os, sys
from pathlib import Path
target = Path({repr(str(target_root))})
os.environ['ARC02_TARGET_ROOT'] = str(target)
os.environ['ARC02_EXPECTED_COMMIT'] = '3ebf5f54bba84300663a9de7f6b05c5b583bc9c6'
sys.path.insert(0, {repr(helper_dir)})
from scripts.arc02_import_bootstrap import bootstrap_arc02
try:
    bootstrap_arc02(target_root=target)
    print('UNEXPECTED_OK')
except Exception as e:
    print('EXPECTED_FAIL', type(e).__name__, str(e)[:300])
"""
        r = subprocess.run(
            [sys.executable, '-c', script],
            cwd=str(ROOT),
            env=env_base,
            text=True,
            capture_output=True,
        )
        return {
            'returncode': r.returncode,
            'stdout': r.stdout.strip(),
            'stderr_tail': r.stderr[-1500:] if r.stderr else None,
            'expected_fail': r.stdout.strip().startswith('EXPECTED_FAIL'),
        }

    wrong_root = Path(td) / 'wrong'
    wrong_root.mkdir()
    cases['wrong_root'] = run_case('wrong_root', wrong_root)

    empty_root = Path(td) / 'empty'
    empty_root.mkdir()
    (empty_root / 'src').mkdir()
    cases['empty_root'] = run_case('empty_root', empty_root)

Path('ARC02_ROOT_FAIL_CLOSED.json').write_text(
    __import__('json').dumps(cases, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)

print('wrong_root_expected_fail', cases['wrong_root']['expected_fail'])
print('empty_root_expected_fail', cases['empty_root']['expected_fail'])
