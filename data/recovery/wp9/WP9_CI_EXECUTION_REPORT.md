# WP-9A — CI runtime certification

> `BLOCKED` · runner `LOCAL` · generated `2026-10-11T21:01:40Z`

## 1. The verdict, first

`CI_CERTIFIED = False`. CI_CERTIFIED requires a run id from a real runner; this audit has none and will not invent one. What is claimed instead is stated per workflow below.

Local sequence: 12 step(s), 0 failed, attempted=True.

Blocked by:

1. this environment cannot authenticate to the remote: the dry-run push reports `fatal: Cannot prompt because user interactivity has been disabled.` — no `gh` CLI, no token in the environment, and the credential helper cannot prompt
2. the workflows are not on the default branch, so Actions has never registered them: .github/workflows/cost-barrier-gate.yml, .github/workflows/recovery-determinism.yml (GitHub reports 1 registered workflow(s): .github/workflows/ci.yml)
3. the commit that carries these workflows is 256 commits ahead of the remote: running them on a runner means publishing this history to a public repository, which is a governance decision and not a side effect of an audit

## 2. The workflows, read as the runner reads them

### `.github/workflows/recovery-determinism.yml` — recovery-determinism

* job `recovery-determinism` on `ubuntu-latest` (github-hosted: True, timeout: 30 min)
  * 11 steps, 7 that run commands, referenced paths all tracked: True
* problems: none

### `.github/workflows/cost-barrier-gate.yml` — Cost-barrier drift gate

* job `cost-barrier-gate` on `ubuntu-latest` (github-hosted: True, timeout: 30 min)
  * 9 steps, 5 that run commands, referenced paths all tracked: True
* problems: none

## 3. What GitHub actually has

* repository: `Extr3sao/bot_crypto` (public), default branch `main`
* registered workflows: 1 — `.github/workflows/ci.yml` (active)
* remote head `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` vs local `5348fcd55ab9ef404c676d8aada8daa8c85b9785`: 256 commit(s) local-only, 0 remote-only
* the workflows on the default branch: `.github/workflows/recovery-determinism.yml` **absent**, `.github/workflows/cost-barrier-gate.yml` **absent**

## 4. The publish probe

`git push --dry-run origin HEAD:refs/heads/wp9-ci-probe-do-not-create` (creates no ref: `False`)

```text
fatal: Cannot prompt because user interactivity has been disabled.
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```

## 5. The declared sequence, executed here

| workflow | step | exit | seconds |
| --- | --- | ---: | ---: |
| `.github/workflows/recovery-determinism.yml` | Sync dependencies | 0 | 0.11 |
| `.github/workflows/recovery-determinism.yml` | Prepare the evidence directory | 0 | 0.062 |
| `.github/workflows/recovery-determinism.yml` | Verify the committed input bundle | 0 | 0.532 |
| `.github/workflows/recovery-determinism.yml` | The repair moved no economic finding | 0 | 0.437 |
| `.github/workflows/recovery-determinism.yml` | Lane contract tests and determinism regressions | 0 | 70.563 |
| `.github/workflows/recovery-determinism.yml` | Clean-checkout rehearsal (scope full) | 0 | 142.687 |
| `.github/workflows/recovery-determinism.yml` | Independent verification of the published artefacts | 0 | 2.141 |
| `.github/workflows/cost-barrier-gate.yml` | Sync dependencies | 0 | 0.125 |
| `.github/workflows/cost-barrier-gate.yml` | Verify and materialize the declared inputs | 0 | 0.265 |
| `.github/workflows/cost-barrier-gate.yml` | Reproduce the artefacts (full reproduction) | 0 | 3.422 |
| `.github/workflows/cost-barrier-gate.yml` | Adversarial verification of the gate | 0 | 106.329 |
| `.github/workflows/cost-barrier-gate.yml` | Certification record | 0 | 171.421 |

## 6. What this does and does not claim

* **does**: the workflows parse, their steps name only tracked paths, no step softens itself, the trigger filters are not dead, and the declared command sequence passes on this machine with these exit codes;
* **does not**: that any of it ran on a GitHub runner, that the runners' images carry the pinned Python and `uv`, or that a clean Ubuntu checkout behaves like this one. `TEST_TARGET == RUNTIME_TARGET` holds here between the declared commands and this workstation, not between this workstation and `ubuntu-latest`.

