# Execution checkpoint — WP-003-07

**Why this file is here and not at `docs/agentic/EXECUTION_CHECKPOINT.md`:** that path does not
exist on `1d2192b0`. It exists only on `wp/isolation-005`, where it records the
integration/recovery lane (WP-003-05/06). Writing a second, divergent version of a lane-owned
document onto a trunk-sanitation branch would guarantee a conflict and would mix two lanes'
histories. The checkpoint therefore travels with the bundle it describes, and merging the two
views is a decision for whoever promotes either branch.

---

## Objective

Apply the project formatter to the trunk, prove it is representational, and change nothing else.
No logic, no rules, no thresholds, no `main`.

## Last commit

| ref | sha |
| --- | --- |
| base | `1d2192b0` (= `main` = `recovery/trunk-sync` = `origin/recovery/trunk-sync`) |
| format commit | `026ea574` |
| branch | `recovery/trunk-format-001` |
| evidence commit | `git log -1 --format=%H -- reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00307` |
| `origin/main` | `5e6f9632` (untouched) |

## Done

1. Base established and documented; ancestry verified; no history reconciled.
2. Format inventory reproduced: **433** at `1d2192b0`.
3. `ruff format` applied to **409** files, `+29 793 / −13 943`.
4. Equivalence proven from git objects: AST 408/409 strict and 409/409 modulo docstring
   whitespace, 7 305 comment tokens identical, control comments preserved, 152 literal rewrites
   value-preserving, **0** content changes, 1 declared 1-byte docstring residual.
5. Verifier written with **6 negative controls** that must each fire; 6/6 do.
6. Pin scanner written; **46** pinned Python paths found across 417 artefacts; **24** of them
   were in the formatted set and are now exempt, with the pinning artefact recorded per file.
7. Suite measured on both sides: **81 failed / 3213 passed / 31 skipped / 14 errors** on each;
   **0 new red nodes**, 95 identical.
8. Lint **100 → 100**, mypy **253/29 → 253/29**, collection **0 → 0**.
9. One inherited claim corrected: the trunk had **0** collection errors, not 4; no test
   references `trading_bot.ops` at this sha.

## Pending

- Nothing to run for this work package: the six pin tests that the first attempt broke are green.
- **Blocked on a decision (not on work):** whether to re-certify the 24 pinned files (then format
  them) or to exempt them permanently in the formatter configuration. Until then
  `ruff format --check .` is honestly **24**, not 0.
- CI is `NOT_PERFORMED`: the workflow only triggers on `main`, and no PR was opened because
  promoting to `main` is a later decision.

## Resume commands

```bash
cd "$(git rev-parse --show-toplevel)"
git rev-parse HEAD main origin/main            # expect 026ea574…-ish, 1d2192b0, 5e6f9632
git log --oneline -2
PY=../bot-freebuff-recovery-004/.venv/Scripts/python.exe   # or the repository .venv
"$PY" scripts/verify_trunk_format.py --base 1d2192b0 --head 026ea574 --expect-files 409
"$PY" scripts/verify_trunk_format.py --base 1d2192b0 --self-test      # 6/6 must fire
"$PY" -m ruff format --check .                 # 24, exactly the files in EXEMPTIONS.json
"$PY" -m ruff check .                          # 100
"$PY" -m mypy .                                # 253 in 29 files
PYTHONPATH=src "$PY" -m pytest -m "not slow and not market" -q --tb=no
                                               # 81 failed, 3213 passed, 14 errors
"$PY" scripts/find_python_pins.py --root .     # 46 pinned python paths
```

## Blockers and owners

| blocker | owner |
| --- | --- |
| re-certify or permanently exempt the 24 pinned files | the lane that owns `data/recovery/wp7` and `data/st6` |
| coverage 62.34 % vs 90 % | project owner (policy) |
| `pip-audit` 80 advisories | project owner (policy) |
| 95 pre-existing red research nodes | the research lane |
| CI run for this branch | needs a PR to `main`, i.e. a promotion decision |
