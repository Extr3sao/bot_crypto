# RUNTIME_AUTHORITY_REPORT — what is authoritative, and what only looks authoritative

**Date:** 2026-10-21 · **Measured by:** this session · **Method:** `git`, `sha256sum`, and the
repository's own verifier executed from a clean worktree. No economics were executed.

---

## 1. The authoritative checkout

| Field | Value | How it was read |
| --- | --- | --- |
| Path | `C:\Users\GVLLFR0035\Downloads\bot freebuff` | `git rev-parse --show-toplevel` |
| Remote | `https://github.com/Extr3sao/bot_crypto.git` (`origin`, fetch + push) | `git remote -v` |
| Branch | `agent/ai-bots/RFC-TAP-AI-BOTS-003` | `git rev-parse --abbrev-ref HEAD` |
| HEAD | `277d1dfee40be91a3ce6024ce54be534d1de9bbc` — *Record what the sealed checkout can and cannot prove* (2026-10-21 00:19:57 +0200) | `git log -1` |
| Upstream branch | `origin/agent/ai-bots/RFC-TAP-AI-BOTS-003` at `fe9b5e2` (2026-10-18) — **13 commits ahead of it, 0 behind** | `git rev-list --count` |
| Working tree | **58 modified tracked files + 211 untracked entries** | `git status --porcelain` |

**The remote matters.** The `EXP-003N_preflight_blocked_20261020` package searched GitHub for
`Extr3sao/Bot-Trading`, found a repository last touched 2026-05-10, and concluded that no authoritative
checkout existed. The remote of this project is `bot_crypto`. That single wrong name is the origin of its
B01 and, in cascade, of its claim that nothing could be verified. A search for the wrong repository is not
evidence about the right one.

**13 commits of unpublished local work.** Local `HEAD` is ahead of its remote branch by 13 commits and
behind by none. Anything that exists only here — including the whole `EXP-003K/L/M/N` chain — is authority
*for this checkout* and is not recoverable from the remote. Treat the local branch as the only copy, not as
a cache.

## 2. Worktree topology

`git worktree list` returns **21 worktrees**:

| Where | HEAD | Branch | Reading |
| --- | --- | --- | --- |
| `Downloads/bot freebuff` | `277d1df` | `agent/ai-bots/RFC-TAP-AI-BOTS-003` | **the one this mission works in** |
| `Downloads/bot freebuff/.tmp/audit/baseline-wt` | `fefb077` | detached | a worktree *inside* the working tree; it makes `git status` noisy and can be committed by accident |
| `AppData/Local/Temp/003n-clean`, `003n-repro`, `003n-sealcheck` | `fefb077`, `cd3fc31`, `6b0dac1` | detached | leftovers from earlier inspections of the sealed experiment |
| `Downloads/bot-freebuff-exp003i` | `44671bb` | `exp/ai-bots/EXP-003I-THROUGHPUT-001` | a **separate lane**, not part of this chain; clean |
| 12 further `bot-freebuff-*` / `bot_crypto_0*` checkouts | various | various | one per prior work package or agent lane |

Two consequences:

1. **A run in one worktree says nothing about another.** `exp/ai-bots/EXP-003I-THROUGHPUT-001` at
   `44671bb` was clean while this tree carried 58 modified and 211 untracked entries. Any claim of the form
   "the repository is clean" must name the worktree.
2. **Detached worktrees at `cd3fc31` and `6b0dac1` are pre-seal states of `EXP-003N`.** They are useful for
   reproducing the verifier and dangerous as a source of "current" numbers, because `cd3fc31` predates the
   seal and `6b0dac1` predates the final report edits.

## 3. The cleanliness defect, stated plainly

`HEAD` is not the state the tests ran against. 58 tracked files differ from `HEAD` in this worktree,
including `src/trading_bot/paper/broker.py`, `src/trading_bot/vision/lane.py`,
`src/trading_bot/risk/manager.py`, `src/trading_bot/research/economic_recovery/alpha15.py`,
`docs/agentic/EXECUTION_CHECKPOINT.md`, `context/retrieval-log.md` and all of `data/st6/`.

This is not a criticism of the other agents: they are mid-work, and the shared-checkout convention of this
project tolerates it. It is a statement about **what a test result here means**:

- a test executed in this worktree proves something about *this worktree*, not about `HEAD`;
- therefore the `EXP-003N` verifier was re-executed **twice**: once here (convenient) and once from a fresh
  `git worktree add --detach 277d1df` outside the repository (authoritative). Both agreed; see
  `ECONOMIC_EVIDENCE_REPORT.md` §2. The clean-worktree run is the one this mission relies on.

The one dirty file that could have changed the verifier's answer was
`src/trading_bot/research/economic_recovery/alpha15.py`, which the verifier imports for `cost_for`. Its diff
against `HEAD` is **+39 lines, 0 deletions**, adding three `*_pre_pit` function bodies; `cost_for` and every
cost constant are untouched. The clean-worktree run removes the doubt rather than arguing about it.

## 4. Artefacts that look authoritative and are not

| Artefact | Status | Why it is a hazard |
| --- | --- | --- |
| `FINAL_REPORT.md`, `RUN_REPORT.md`, `RUN_REPORT.json` **at the repository root** | tracked, modified, mtime 2026-09-30 | they are a *September* report at the top level of a project that has since produced `reports/ai-bots/EXP-003N`. A reader who opens the root `FINAL_REPORT.md` will read month-old conclusions as current. Nothing in them is used by this mission |
| `.ci/*` (36 untracked entries) | untracked | gate, adversarial and certification outputs from an unrelated certificate sprint; they are not evidence for any experiment in `reports/` |
| `scripts/_tmp_patch_*.py` (9 files), `.wp003i_gate_update.py`, `servers.txt` | untracked | scratch. One of them, `_tmp_patch_docs.py`, rewrites documentation; it must not be run against this mission's deliverables |
| `data/st6/ST6_*` (22 modified) | modified, uncommitted | the ST-6 forward collector's live state. The numbers move between reads. Any figure quoted from it must carry its read time |
| `reports/ai-bots/DIRECTIVE-2026-10-20/`, `EXP-003J-.../` | **untracked** | a completed run that exists only as files on this disk. `git ls-tree HEAD` does not see it, so a clean checkout loses it |

The last row is the most important. `EXP-003J-REAL-SIGNAL-PAPER-001` has a full `RUN_REPORT.json`, an
independent verification and a `SHA256SUMS.txt`, and it is **not in Git**. `EXP-003N` learned this lesson
the hard way: its own `SEAL.json` and eight deliverables were untracked at `cd3fc31`, and only became
authoritative when another agent committed them at `6b0dac1`. `EXP-003J` is currently in the `cd3fc31`
state. This mission does not commit another agent's run; it records the gap.

## 5. Data authority

Dataset bytes are **outside Git on purpose**: they are regenerable from published Binance endpoints and are
certified by digest, not by presence in the object store. Re-measured today:

| File | sha256 | Frozen in `DESIGN.json` |
| --- | --- | --- |
| `reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/BTCUSDT.1m.jsonl.gz` | `7fbdfefa12785bb025d525994466b5a64d5c0668d6ff997f5f7566bc42d13814` | `7fbdfefa…` ✅ |
| `…/ETHUSDT.1m.jsonl.gz` | `cf04dc37617a0998016fcd7edfb9b2a77c9aa5fa656bbb54422805a5964650a6` | `cf04dc37…` ✅ |
| `…/SOLUSDT.1m.jsonl.gz` | `33342aacc2ac75f897e2c9df2602a41d340c96ed08cd683dbd3871c3c7c60c32` | `33342aac…` ✅ |

`git ls-tree HEAD -- reports/ai-bots/EXP-003K-CANDIDATE-001` returns **nothing**: the dataset directory is
untracked. That is the intended design (bytes regenerable, digest frozen), and it is also the reason a clean
checkout cannot re-run `EXP-003N` without fetching or restoring those three files. The verifier reports this
as a blocked dataset, not as a pass.

## 6. What "TEST_TARGET == RUNTIME_TARGET" means here

The claim is true when, and only when, all of the following hold — each one was checked this session:

1. the code executed is the code at the named commit → **checked** by running from a detached worktree at
   `277d1df`;
2. the inputs executed against have the digests the design froze → **checked** (`7fbdfefa…` etc.);
3. the executed program is not the program that produced the numbers → **checked** by opening
   `scripts/exp_003n_verify.py`: it shares no module with `exp_003n_screen.py` or `exp_003n_pipeline.py`;
4. no write occurred into the sealed artefact → **checked**: the verifier refuses when `SEAL.json` is
   present (exit 4, measured), and the reproduction ran against a *copy* with the seal excluded;
5. the verifier is a person → **false**, and unchanged. `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON`.

Point 5 is not fixable by this mission and must not be dressed up. What was achieved is *program-level*
independence on a clean checkout, which is weaker than an external auditor and stronger than nothing.

## 7. Verdict of this report

**Authority is established for this checkout, at `277d1df`, on this branch, with a dirty worktree that is
irrelevant to every number this mission reports** — because every number was either re-derived from frozen
bytes or re-executed from a clean worktree.

**Refused:** treating the remote as the source of truth (41 commits behind), treating `cd3fc31` as current
(pre-seal), treating `Extr3sao/Bot-Trading` as this project (wrong repository), and treating root
`FINAL_REPORT.md` as current (2026-09-30).

**Open, recorded, not repaired:** `EXP-003J`'s report set is untracked; `data/st6/*` is live and uncommitted;
`.ci/*` and `scripts/_tmp_patch_*.py` are untracked scratch that a later reader could mistake for evidence.
Repairing them means committing another workstream's files, which this mission does not do.
