import os, shutil, subprocess, sys, tempfile
from pathlib import Path
import json

ROOT = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-v2-repair-01').resolve()
MAIN_SRC = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/src').resolve()

env_base = os.environ.copy()
env_base['PYTHONPATH'] = str(MAIN_SRC)
env_base['ARC02_EXPECTED_COMMIT'] = '3ebf5f54bba84300663a9de7f6b05c5b583bc9c6'

def run_from(cwd: Path, target_root: Path | None = None, extra_env=None) -> dict:
    env = {**env_base, **(extra_env or {})}
    target = target_root or ROOT
    script = (
        'import os, sys\n'
        'from pathlib import Path\n'
        f'sys.path.insert(0, {repr(str(ROOT))})\n'
        'from scripts.arc02_import_bootstrap import bootstrap_arc02\n'
        'bootstrap_arc02(target_root=Path(' + repr(str(target)) + '))\n'
    )
    r = subprocess.run(
        [sys.executable, '-c', script],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
    )
    return {
        'cwd': str(cwd),
        'target_root': str(target),
        'returncode': r.returncode,
        'stdout': r.stdout.strip()[-1500:],
        'stderr_tail': r.stderr[-1500:] if r.stderr else None,
    }

cases = {}
cases['cwd_different'] = run_from(Path.home())
cases['cwd_temp'] = run_from(Path(tempfile.gettempdir()))

with tempfile.TemporaryDirectory() as td:
    clean_tree = Path(td) / 'arc02-clean'
    shutil.copytree(ROOT, clean_tree, dirs_exist_ok=True)
    cases['clean_detached_tree'] = run_from(clean_root := clean_tree)
    cases['clean_detached_tree_cwd_root'] = run_from(clean_tree, target_root=clean_tree)

for k, v in cases.items():
    v['ok'] = v['returncode'] == 0

Path('ARC02_PORTABILITY_V2.json').write_text(
    json.dumps(cases, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)

print('cwd_different.ok', cases['cwd_different']['ok'])
print('cwd_temp.ok', cases['cwd_temp']['ok'])
print('clean_detached_tree.ok', cases['clean_detached_tree']['ok'])
print('clean_detached_tree_cwd_root.ok', cases['clean_detached_tree_cwd_root']['ok'])
