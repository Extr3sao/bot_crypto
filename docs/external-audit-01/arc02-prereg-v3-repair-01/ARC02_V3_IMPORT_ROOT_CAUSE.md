# ARC02_V3_IMPORT_ROOT_CAUSE — why the V2 repair still failed independently

ROOT_CAUSE_IDENTIFIED = true

Basis:

* committed verifier evidence commit `00063237de21e3ed9273d84293f129f75003f126`,
  file `docs/external-audit-01/arc02-prereg-verification-v2-01/ARC02_V2_IMPORT_AUTHORITY_AUDIT.json`
  (execution/evidence authority; overrides any self-reported PASS);
* pre-repair local reproduction `ARC02_V3_IMPORT_DEFECT_REPRODUCTION.json`
  (`DEFECT_REPRODUCED = true`) executed in `.research/arc02-prereg-v3-repair-01`
  at base `6df96c66ac4ea2fe5413cf896befc1ce997cd6e5`.

The contamination itself ("an editable `.pth` exists") is NOT the root cause —
the repair contract explicitly requires working *under* contamination. The root
cause is which mechanisms of the V2 repair were insufficient, as itemized below.

---

## RC-1 — Evidence identity was never canonicalized (path-identity divergence)

The committed V2 audit records a hard contradiction:

* `authority_package_file` = `C:/Users/GVLLFR0035/Downloads/bot freebuff/.research/arc02-prereg-verifier-v2-01/src/trading_bot/__init__.py`
* `authority_target_root`  = `C:\Users\GVLLFR0035\Downloads\bot freebuff\.research\arc02-prereg-verifier-v2-01`
* `authority_package_within_target` = `false`  ← file is *inside* the target, yet judged outside

Mechanism: the V2 evidence emitter canonicalized paths to **forward-slash text**
(`_normal_path` replaces `\` with `/`), while the V2 helper scripts recomputed
containment with **naive text prefix tests**
(`str(pkg).startswith(str(target_root.resolve()))` — backslashes on Windows).
Two textual forms of the *same* directory therefore compare as different, and a
target-resident file recomputes as "outside target".

Reproduced pre-repair (F3 in `ARC02_V3_IMPORT_DEFECT_REPRODUCTION.json`):
`v2_style_startswith = false` while
`v3_style_pathlib_is_relative_to = true` for the identical emitted path.

Consequence: V2's PASS could not be *re-derivable* by an independent verifier.
Verification that depends on ad-hoc string comparison in helper scripts is not a
stable evidence format — the same fact flips depending on which separator an
intermediate layer happened to emit. The verifier correctly treated
`authority_package_within_target=false` as `PYTHON_IMPORT_AUTHORITY=FAIL`.

## RC-2 — "Wrong module already imported" was silently replaced, not failed

V2's `CheckoutImportAuthority.prepare()` **purged** any `trading_bot*` module in
`sys.modules` whose `__file__` was outside the target and then re-imported. The
V2 contract itself stated "a wrong checkout is an error, never a fallback", but
`prepare()` never raised on a wrong preloaded module: it deleted it and
continued, returning PASS.

Reproduced pre-repair (F2): with the main-checkout package preloaded via
`PYTHONPATH=main_src` (import-order attack, §11 of the work order), the V2
bootstrap returned `PASS` and `silently_replaced_wrong_preload = true`.

Mechanism: a **fail-silent purge** was used where the contract demanded
**fail-closed rejection**. A verifier that probes with a preloaded wrong module
(mandated by the work order) gets a PASS from a repair whose own spec says that
state is an error. This is the mechanism by which the import-order attack
defeated V2.

## RC-3 — V2 left contamination entries in `sys.path` (prepend, not purge)

V2 `prepare()` only removed entries *equal to* the target src and then
**prepended** the target src. The main checkout `src` — injected by the editable
`.pth` or `PYTHONPATH` — stayed in `sys.path` behind the target. Any mechanism
that bypasses the prepend (a direct `sys.path` manipulation, a submodule import
after list mutation, or an independent verifier that recomputes resolution
itself) re-exposes the main checkout. The committed audit recorded exactly this:
`main_checkout_src_in_sys_path_before_authority = true` and, in
`authority_sys_path_after`, the final entry is still
`...\bot freebuff\src` — the contaminant survived the repair.

Mechanism: **authority by ordering** (first match wins) instead of **authority
by absence** (first-party sources other than the target are removed from
resolution). Ordering is fragile; absence is checkable.

## RC-4 — Pytest authority ran at session start, after import exposure had already begun

The V2 `conftest.py` asserted authority at conftest import time. That is after
pytest has already started, after the rootdir was computed, and after any
plugin/`conftest` chain import could have bound `trading_bot` from the ambient
environment. It also validated but did not **establish** authority for the rest
of the session: nothing re-verified that the modules *later loaded during
collection* still resolved inside the target. And the committed V2 test
`test_arc02_import_authority.py` was a tautology
(`assert str(worktree_src) not in package_file or True`), providing zero
regression protection.

Mechanism: **validation at the wrong lifecycle point** plus a **non-asserting
test**, so the pytest entrypoint could pass while importing main-checkout code.

## RC-5 — Subprocesses inherited contamination with no authority channel

V2 scripts spawned `python -c` children with a copied `os.environ`: the child
re-received the contaminated `PYTHONPATH`/editable `.pth` environment and each
child had to re-derive authority by itself. There was no explicit
`target_root`/`expected_commit` authority channel passed to children, so the
"parent contaminated → child target correct or fail closed" property held only
by convention, not by construction.

---

## Synthesis

The V2 repair failed independently for five compounding mechanism reasons:

| #  | Mechanism (from work order §7 list)                                  | V2 behavior                                   |
|----|----------------------------------------------------------------------|-----------------------------------------------|
| RC-1 | path identity not canonical (comparison-level defect)               | emitter `/` vs recomputation `\`; PASS not re-derivable |
| RC-2 | package already imported before path correction → silent replace    | purge + reimport, PASS; contract says FAIL    |
| RC-3 | sys.path mutation leaves contamination in place (ordering authority)| main `src` still in `sys.path` after repair   |
| RC-4 | pytest guard validates too late; tautological test                  | session-start check only; no real assertion   |
| RC-5 | environment inheritance reintroduces main checkout in subprocesses  | children re-inherit contamination, no authority channel |

The V3 repair therefore: canonicalizes all path identity (`Path.resolve()` +
separator-normalized, containment via `pathlib` only — RC-1); fails closed on
wrong preloaded first-party modules instead of replacing them (RC-2); removes
all resolvable first-party contaminants from `sys.path` instead of merely
prepending (RC-3); installs a pytest guard that fails collection before any
evidence-producing test and continuously re-checks loaded critical modules,
backed by asserting tests (RC-4); and passes explicit
`target_root`/`expected_commit` into every authoritative subprocess (RC-5).
