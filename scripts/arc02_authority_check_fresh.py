import os, sys, pathlib, subprocess

ROOT = pathlib.Path('.').resolve()
MAIN_SRC = pathlib.Path(r'C:\Users\GVLLFR0035\Downloads\bot freebuff\src').resolve()
env = os.environ.copy()
env['PYTHONPATH'] = str(MAIN_SRC)
env['ARC02_EXPECTED_COMMIT'] = '3ebf5f54bba84300663a9de7f6b05c5b583bc9c6'

script = r'''
import os, sys, pathlib
from scripts.arc02_import_bootstrap import bootstrap_arc02

ev = bootstrap_arc02()
target_root = pathlib.Path(os.environ['ARC02_TARGET_ROOT']).resolve()
pkg = pathlib.Path(ev.package_file).resolve()

print('TARGET_ROOT', target_root)
print('PKG', pkg)
print('PKG_WITHIN', str(pkg).startswith(str(target_root)))
print('HEAD', ev.git_head)
for m in ev.critical_module_files:
    print('MOD_WITHIN', pathlib.Path(m).resolve().is_relative_to(target_root))
'''

out = subprocess.run(
    [sys.executable, '-c', script],
    cwd=str(ROOT),
    env=env,
    text=True,
    capture_output=True,
)

print('STDOUT')
print(out.stdout)
print('STDERR')
print(out.stderr[-1200:] if out.stderr else 'none')
print('RC', out.returncode)
