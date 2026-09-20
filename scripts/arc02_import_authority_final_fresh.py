import os, subprocess, sys
from pathlib import Path
import json

ROOT = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-v2-repair-01').resolve()
MAIN_SRC = Path('C:/Users/GVLLFR0035/Downloads/bot freebuff/src').resolve()

env = os.environ.copy()
env['PYTHONPATH'] = str(MAIN_SRC)
env['ARC02_EXPECTED_COMMIT'] = '3ebf5f54bba84300663a9de7f6b05c5b583bc9c6'

pytest_r = subprocess.run(
    [sys.executable, '-m', 'pytest', '-q', '--co', '-p', 'no:cacheprovider', 'conftest.py'],
    cwd=str(ROOT),
    env=env,
    text=True,
    capture_output=True,
)

result = {
    'cwd': str(ROOT),
    'pythonpath_main_src': str(MAIN_SRC),
    'expected_commit': env['ARC02_EXPECTED_COMMIT'],
    'pytest_returncode': pytest_r.returncode,
    'pytest_stdout': pytest_r.stdout.strip()[-1500:],
    'pytest_stderr_tail': pytest_r.stderr[-1500:] if pytest_r.stderr else None,
    'pytest_authority_pass': pytest_r.returncode == 0,
}

Path('ARC02_IMPORT_AUTHORITY.json').write_text(
    json.dumps(result, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)

print('pytest_returncode', pytest_r.returncode)
print('pytest_authority_pass', result['pytest_authority_pass'])
print('pytest_stderr_tail', result['pytest_stderr_tail'])
