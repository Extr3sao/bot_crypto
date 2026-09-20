# ARC02 Import Authority Root Cause

## Summary

PYTHON_IMPORT_AUTHORITY failure came from environmental authority leakage, not
from ARC-02 economics. When code in the ARC-02 worktree ran without an explicit
authority contract, Python resolved `trading_bot` to the main checkout `src`
because the shared environment already contained that source path.

## Source

- editable install `.pth` in the shared virtualenv:
  `__editable__.crypto_scalping_agentic_bot-0.1.0.pth` points at the main
  `src` directory.
- ambient PYTHONPATH contamination in adversarial test environments.
- syspath/site-packages resolution order before any worktree-local authority
  bootstrap.

## Mechanism

1. The shared environment exposes the main `src` as a first-party package source.
2. `import trading_bot` uses normal import resolution, which can return the main
   checkout package if no explicit worktree checkout precedence is enforced.
3. Scripts, tests and subprocesses may therefore import the wrong checkout without
   failing loudly.
4. In contaminated environments the authority contract itself could previously be
   loaded through mechanisms that depend on `sys.modules` state, causing a
   secondary load failure even when the intended file path was correct.

## Affected commands

- pytest sessions in the ARC-02 worktree
- ARC-02 scripts that import `trading_bot` without bootstrap
- ARC-02 subprocess launchers and verifier/portability harnesses
- any process that inherits the main-repo editable install and expects the ARC-02
  checkout to be authoritative

## Affected tests

- any test whose import resolution is not pinned to the ARC-02 checkout
- any test that runs under contaminated PYTHONPATH without the conftest/authority
  guard
- portability/clean-worktree negative controls for wrong-root and empty-root cases

## Runtime impact

Without the authority contract, runtime behavior can appear correct while actually
running against the wrong checkout source. That invalidates the verifier premise
that TEST_TARGET == AUDITED_TARGET.

## Verifier impact

The previous verifier failure mode was consistent with this root cause: the verifier
could not trust that the code under test was the audited target, so its authority
conclusion could not be accepted.

## Fix orientation

- Pin first-party package authority to the audited checkout explicitly.
- Fail closed on wrong checkout, wrong commit, wrong root or empty root.
- Keep third-party dependencies importable.
- Make the authority contract loadable even in contaminated environments by
- avoiding runtime decorator machinery that assumes ideal `sys.modules` state.
- Use checkout-local deterministic authorities for git HEAD, path derivation and
  script bootstrap.

## Classification

SOURCE: environment/.pth/PYTHONPATH
MECHANISM: Python import resolution precedence
AFFECTED_COMMANDS: pytest, ARC-02 scripts, subprocess launchers, verifier harnesses
AFFECTED_TESTS: any ARC-02 test/run not pinned to the audited checkout
RUNTIME_IMPACT: can silently run wrong checkout code
VERIFIER_IMPACT: broke TEST_TARGET == AUDITED_TARGET trust
