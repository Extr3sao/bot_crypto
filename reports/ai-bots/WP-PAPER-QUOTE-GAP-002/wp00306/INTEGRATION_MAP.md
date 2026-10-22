# Integration map — WP-003-06

What exists, what depends on what, and exactly what a reviewer has to read. Every sha and
count below was produced by a command run in this session against this checkout.

## 1. The four branches

```
origin/main        5e6f9632 ──┐
                             │  259 commits, never published (2026-09-25 → 2026-10-12)
                             ▼
recovery/trunk-sync 1d2192b0 ─┬── published, unchanged trunk
  (= local main)              │
                              ├── 6 commits ──▶ recovery/wp00303  baf5b560   (the port)
                              │                        │
                              │                        ├── abdf2146        (the evidence bundle)
                              │                        └── 08c5d9d2        (the verdict)  ◀ tip, published
                              │
                              └─ 244 commits ─▶ wp/isolation-005   624455c8   (PR #17, published)

fix/ci-smoke-pwsh   9682ee1b  ← 1 commit on top of origin/main 5e6f9632, published
```

| ref | sha | published | role |
| --- | --- | --------- | ---- |
| `origin/main` | `5e6f9632` | yes | the authority this project treats as `main` |
| `main` (local) | `1d2192b0` | **no** | 259 unpublished commits, never run by CI |
| `recovery/trunk-sync` | `1d2192b0` | yes (`origin/recovery/trunk-sync`) | a named, immutable reference to that trunk so a diff can be taken against it |
| `recovery/wp00303` | `08c5d9d2` | yes (`origin/recovery/wp00303`) | the deliverable: 6 port commits + evidence + verdict |
| `integration/wp00303-min` | `baf5b560` | no | superseded by `recovery/wp00303`; kept locally as the port's original head |
| `wp/isolation-005` | `624455c8` | yes | PR #17; not merged, not to be merged while gates are red |
| `fix/ci-smoke-pwsh` | `9682ee1b` | yes | one-file pipeline repair, independent of everything above |

`git merge-base --is-ancestor main wp/isolation-005` → true. **There is no divergence**: the
whole history is linear, zero merge commits in the 503-commit cohort.

## 2. What is independently reviewable, and what is not

`git diff recovery/trunk-sync..recovery/wp00303` is **8 commits, 23 code files, +4 472/−88,
plus the evidence bundle**. That is the unit a reviewer reads.

What that diff is **not**: an integration that stands on its own. `origin/main` has no
`src/trading_bot/autonomous/` directory at all, so the runtime this work package exercises
does not exist there. **The stacked PR depends on the 259-commit trunk.** Presenting it as
independent would be false, and it is not presented that way anywhere in these reports.

The two publishable artefacts are therefore offered as:

1. `fix/ci-smoke-pwsh` — independent of everything, reviewable against `origin/main` today.
2. `recovery/trunk-sync` → `recovery/wp00303` — a stacked review whose base is the trunk, not
   `origin/main`. It stays `BLOCKED` until the trunk decision in
   `TRUNK_SANITATION_PLAN.md` is taken.

## 3. Dependency layers of the port (L0 → L7)

Each layer was added because a *measured* failure demanded it, not by inspection.

| layer | source | files | the failure that forced it |
| ----- | ------ | ----- | -------------------------- |
| L0 trunk | `1d2192b0` | the whole tree | `ModuleNotFoundError: trading_bot.autonomous.*`, `paper.*`, `risk.manager`, `scanner.*` — none of it exists in `origin/main` |
| L1 guard | `0bdda77d` | 7 (isolation, execution `__init__`, app, 3 market-data adapters, its test) | `ModuleNotFoundError: trading_bot.execution.isolation` |
| L2 corpus | `8e66e81b` | 4 (BTC/ETH/SOL holdout + fetch manifest) | the lab declares this corpus and checks its sha256 |
| L3 broker/decision | `b4ff5889`, `87b9c6af`, `5b86b656`, `96957a2b`, `86d4f126` | 6 | `AttributeError: 'PaperBroker' object has no attribute 'accounting_snapshot'` |
| L4 risk | `9dbbbaee`, `1869f535`, `5b86b656` | 1 (`risk/manager.py`) | **no exception**: `E2E-RESTART` digest differed (32 trades approved where the published run vetoed 81). A one-scenario validation would have missed it — this is why all three scenarios are compared |
| L5 lab | `06ba3183`, `e450a238` | 3 scripts | the measurement itself |
| L6 ops | `fe9b5e26` | 2 (`ops/__init__`, `windowless`) | 4 collection errors in the trunk: four committed tests import `trading_bot.ops` |
| L7 format | this line of work | 8 | `ruff format --check` flagged 8 of the ported files; formatting them adds **0** new debt and fixes 5 trunk files |

## 4. The two numbers that looked inconsistent (433 vs 428), reconciled

`ruff format --check .`, measured this session:

- `1d2192b0` (trunk): **433** files would be reformatted.
- `baf5b560` (trunk + port): **428**.

The 5-file delta is exactly the set of trunk files the port touches and reformats:

```
src/trading_bot/autonomous/contracts.py
src/trading_bot/autonomous/decision.py
src/trading_bot/autonomous/runtime.py
src/trading_bot/autonomous/supervisor.py
src/trading_bot/paper/reconciliation_v4.py
```

Set difference in both directions: 5 removed, **0** added. The 8 files touched by
`7e4971d1` are 5 of those trunk files plus 3 new files (`isolation.py`, `broker.py`,
`windowless.py`) that the trunk never counted.

Same treatment for the PR size. WP-003-05 measured **498 commits / 3 452 files / +2 722 984**
against head `afc01270`. The branch tip is now `624455c8`, five report commits later:
**503 / 3 463 / +2 725 201**. Both numbers are correct; each names a sha, and the baseline now
records which one.

## 5. `observability.vision_panel` — resolved, not ported

WP-003-05 recorded this as "no commit at all; one untracked file in six worktrees". That was
wrong on both counts, and the correction matters because it changes the owner:

- The module **is** committed: `e90a8ad3` "Version the quote-feed fixtures and the panel
  module the tests import" (172 lines), on `wp003i/reproducibility` and `wp003j/runtime`,
  reformatted at `26fd3955`.
- The test that imports it is `5fd791d8`, which is on `wp/isolation-005` but **not** in the
  trunk and **not** in the port — which is exactly why the port has **0** collection errors
  and the branch has 2.
- Two on-disk copies exist and they are **not** identical (`cabf5066…` vs `fc8e4cd3…`), so
  "pick one untracked copy" was never a safe move.
- A tolerant version of the test already exists at `a91cabea` on
  `exp/ai-bots/EXP-003I-THROUGHPUT-001`.

Reachability: nothing outside the test imports the module. Owner: the observability lane.
Decision for this work package: **do not incorporate it**. It is not orphan code to promote;
it is another lane's committed work plus another lane's test fix, and importing either would
have dragged a third lane's contract into a PAPER work package.

## 6. How to review this in five commands

```bash
git fetch origin
git log --oneline origin/recovery/trunk-sync..origin/recovery/wp00303   # 8 commits
git diff --stat origin/recovery/trunk-sync..origin/recovery/wp00303     # 23 code files + bundle
git worktree add --detach /tmp/verify origin/recovery/wp00303
cd /tmp/verify && python scripts/verify_paper_e2e.py \
  --lab reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/PAPER_E2E_LAB.json \
  --bundle reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303 --repo . \
  --evidence-sha "$(git rev-parse HEAD)" \
  --repeat reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/PAPER_E2E_LAB_REPEAT.json \
  --github-sync reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/GITHUB_SYNC.json \
  --negative-controls --json /tmp/verdict.json
```

Expected: `verdict: PASS`, 18 checks, 11 negative controls rejected. Run it on a clean
checkout — on a dirty tree `runtime_identity` will fail, correctly.
