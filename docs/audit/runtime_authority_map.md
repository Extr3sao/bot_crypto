# Runtime authority map — Trading Agentic Portable

> Versioned record. Generated 2026-10-23T18:53:56Z while recovering the
> multi-agent audit after MT-0004 was blocked with `BLOCKED_SPEC`.
>
> This file exists because the audit corpus used to live in `reports/`, which
> `.gitignore:55` excludes (`reports/*`). Nothing under `reports/multiagent-audit`
> was ever committed (`git log --all --oneline -- reports/multiagent-audit`
> returns 0 commits), so a worktree reset destroyed every contract in it. The
> map below is derived from git objects and from imports in the tree, not from
> those lost notes.

## 1. How this map was produced

Every claim below is reproducible with a command in the same commit. The
commands are printed next to the claim; the revision is pinned by SHA because
`codepaper/supervisor-001` is a moving branch (it advanced twice during this
recovery: `60455b46` → `0e2ba09d` → `cc4f15f6`).

```bash
git rev-parse HEAD                                  # 0e2ba09d47625fd899bee4e4fd3a82a0232c2d29
git rev-list --left-right --count main...HEAD       # 0       299
git merge-base --is-ancestor 60455b46 HEAD          # exit 0 → MT-0003 is an ancestor
git log --all --oneline -- reports/multiagent-audit # (empty) never tracked
git log --all -S'MT-0004' --oneline                 # only 9c83e62a (MT-0002)
```

## 2. Branch inventory and the authority decision

| Ref | SHA | Date | Relation to `main` | Verdict |
|---|---|---|---|---|
| `main` | `1d2192b0` | 2026-10-12 | — | **Legacy.** Does not contain MT-0003: no `kill_switch_v2` importer, no `tests/unit/autonomous/test_decision_kill_switch.py`. |
| `codepaper/supervisor-001` | `cc4f15f6` (moving) | 2026-10-23 | 299 ahead, 0 behind | **Authoritative line of development.** Contains `9c83e62a` (MT-0002) and `60455b46` (MT-0003) in its ancestry. |
| `recovery/mt0003-kill-switch-60455b46` | `60455b46` | 2026-10-23 | 298 ahead | Preservation ref created in the blocked run so `git gc` could not prune MT-0003. Still points at the MT-0003 commit, not at a descendant. |
| `recovery/trunk-format-001` | `dc21870f` | 2026-10-23 | separate lane | Line-ending/format lane. Does not contain the MT token (`git grep MT-0004 recovery/trunk-format-001` → empty). |
| `audit/mt0004-negative-controls` | `0e2ba09d` | 2026-10-23 | 299 ahead | **This task.** New branch cut from `codepaper/supervisor-001@0e2ba09d`, pinned by SHA so later supervisor commits cannot silently change the baseline. |

`main` being 299 commits behind is not the only reason it loses: it also lacks
the control entirely. More commits alone would not have decided it — the
decisive test is reachability of the MT-0003 gate inside the tree, checked in
§3.

Worktrees in play at measurement time:

```text
.../bot freebuff            1d2192b0 [main]                          (dirty: other lanes)
.../bot freebuff/wt-sup001  0e2ba09d [codepaper/supervisor-001]      (dirty: other lanes)
.../ff-wt-base              1d2192b0 (detached)
.../ff-wt-trunkfmt          dc21870f [recovery/trunk-format-001]
.../ff-wt-mt0004            0e2ba09d [audit/mt0004-negative-controls]
```

No original branch was reset, deleted or rewritten. The dirty trees belong to
other lanes and were not staged, committed or reverted by this task.

## 3. Kill-switch reachability

```bash
grep -rn 'kill_switch_v2' --include='*.py' src scripts tests
# src/trading_bot/autonomous/decision.py:36   ← the only production importer
# tests/unit/autonomous/test_decision_kill_switch.py
grep -rn 'from trading_bot.paper.kill_switch import' --include='*.py' src scripts tests
# (empty)
```

| Component | Classification | Evidence |
|---|---|---|
| `src/trading_bot/paper/kill_switch_v2.py` (`KillSwitch`, 5 states) | **RUNTIME_AUTHORITATIVE** | Imported by `autonomous/decision.py:36`; that is the object rule 0 reads. |
| `src/trading_bot/domain/enums/kill_switch.py` (state enum + allowed-action table) | **RUNTIME_AUTHORITATIVE** | Consumed by `kill_switch_v2`; `KILL_SWITCH_ALLOWED_ACTIONS` defines what each state permits. |
| `src/trading_bot/autonomous/decision.py` (`_kill_switch_no_trade`, rule 0) | **RUNTIME_AUTHORITATIVE** | Called at the top of both `intend` and `decide`. |
| `src/trading_bot/autonomous/runtime.py` | **RUNTIME_AUTHORITATIVE consumer** | `runtime.py:341` builds `DecisionEngine()` with no injected switch, so the runtime reads the process authority. |
| `src/trading_bot/risk/futures/integration.py` (`run_through_decision_engine`) | **RUNTIME_REACHABLE** | Builds `DecisionEngine()` at line 332, so it inherits rule 0. |
| `src/trading_bot/paper/kill_switch.py` (V0.3 `KillSwitch`) | **ORPHAN** | Zero importers in `src/`, `scripts/`, `tests/`. Two classes named `KillSwitch` in the codebase; only `kill_switch_v2` is wired. |
| `src/trading_bot/paper/paper_cycle.py` (`PaperCycleEngine`) | **RUNTIME_REACHABLE, gate absent** | Imported by `paper/harness.py:31` and `scripts/start_paper_trading.py:34`. Its imports (`grep -n '^from' paper_cycle.py`) include `risk.manager.RiskManager` and `risk.defensive_blocks` but **not** `autonomous.decision`, so rule 0 is not on that path. |
| `src/trading_bot/app.py` — `kill-switch`, `status` | **RUNTIME_REACHABLE, refuses** | Both are in `NOT_IMPLEMENTED_SUBCOMMANDS` (`app.py:66`) and `main` returns 2 with an empty stdout (`app.py:1392-1400`). No in-process activation surface exists. |
| `tests/unit/autonomous/test_decision_kill_switch.py` | **TEST_ONLY** | 35 cases over rule 0, including the real runtime. |
| `tests/unit/test_app_cli_contract.py` | **TEST_ONLY** | Drives `python -m trading_bot.app` in a subprocess; AST scan of `main`. |

### TEST_TARGET == RUNTIME_TARGET

Tests only prove something about the runtime if they import the tree under
test. Verified explicitly, not assumed:

```bash
uv run --frozen python -c "import trading_bot; print(trading_bot.__file__)"
# C:\...\ff-wt-mt0004\src\trading_bot\__init__.py
```

The `.venv` of this worktree is an editable install pointing at *this*
worktree's `src` (`.venv/Lib/site-packages/__editable__.crypto_scalping_agentic_bot-0.1.0.pth`),
and `PYTHONPATH` takes precedence over that `.pth` (verified with a sentinel
module), which is what makes the mutation harness in
`scripts/audit/negative_controls.py` able to test a mutated copy without
touching the working tree.

## 4. MT-0003 recovery

`60455b46` is an ancestor of this branch and the control is present in the
tree; nothing had to be cherry-picked.

```bash
uv run --frozen pytest tests/unit/autonomous/test_decision_kill_switch.py \
                       tests/unit/test_app_cli_contract.py -q
# 43 passed
```

Decision-engine order in this tree (first match wins): **0 kill switch**,
1 agent veto, 2 verifier, 3 no proposal, 4 unknown strategy, 5 binding risk
veto, 6 gross edge, 7 paper admission. Rule 0 reads no request field.

## 5. Declared gaps (still open — not closed by this task)

| Gap | Meaning | Status in this tree |
|---|---|---|
| **G-1** | Kill-switch state is not persisted; a restart boots `NORMAL` | Open. `_boot_kill_switch()` reads `TRADING_BOT_KILL_SWITCH` once at import; `KillSwitch` has no store. Pinned as executable truth by MT-0003's `test_the_state_does_not_survive_a_restart_and_that_is_the_declared_gap`. |
| **G-2** | No hot activation from the CLI | Open. `kill-switch` is a refusing stub; the only operator lever is the boot-time environment variable. |
| **G-3** | Live order paths that bypass `DecisionEngine` | Open. Not measured here; the CLI's live path was not exercised in this task. |
| **G-4** | Duplicate engine `paper/paper_cycle.py` | Open, and sharper than before: that module does not import `autonomous.decision`, so the robots started by `scripts/start_paper_trading.py` are not protected by rule 0. |

## 6. What this map cannot tell you

- **The original MT-0004 contract.** It is not in any git object. See
  `docs/audit/MT-0004-R1.md` §2.
- **Whether MT-0040 exists.** The identifier appears in no committed file and
  in no commit message (`git log --all -S'MT-0040'` → empty). Any reference to
  it is recollection, not evidence.
- **The live path.** `execution/live_gate.py` reads
  `settings.risk.kill_switch_enabled`, a *config boolean*, not the runtime
  state from `kill_switch_v2`. This is the mechanism behind G-3 and it was not
  exercised, so it is recorded as an untested claim, not a verified defect.
