# PR-pipeline scripts (`scripts/`)

PowerShell scripts for the PR pipeline (`feat/tsk-0204-fase2-f3b-structlog` and
future PR-pipeline scripts). They automate: pre-flight, idempotency check,
label pre-create, `gh pr create`, all behind an idempotent design.

## Files

- **`open-pr-tsk-0204.ps1`** — opens the PR for `feat/tsk-0204-fase2-f3b-structlog`.
  Supports `-DryRun` for parse-tripwire + preflight smoke (exit codes `{0,1}`
  accepted). ADR-0020 anchors the pwsh-only contract enforced by the smoke CI
  job in `.github/workflows/ci.yml`.
- **`validate_local.ps1`**, **`validate_gates_f5.ps1`**, **`push_f5_pr.ps1`**,
  **`git_init_and_push.ps1`** — governance + quality-gate harnesses
  (see `quality/release-gates.md`).
- **`tsk-013.10-resweep.sh`** — bash TSK-013.10 re-sweep helper.
- **`check_bdd_fixtures.py`** — Python BDD fixture contract checker.

> Note: `open-pr-tsk-104-walk-forward.ps1` is the expected sibling for the
> TSK-104 walk-forward pipeline; it lives on the TSK-104 branch and will be
> cherry-picked in once that branch lands. Once present, mirror the
> `open-pr-tsk-0204.ps1` shape (add `[CmdletBinding()] + [switch]$DryRun`,
> JSON `[number,title,url]`, ADR-0020 header).

## Manual idempotency pre-check (before consuming a PAT)

The PR-pipeline scripts check `gh pr list ... --json number,title,url`
internally for idempotency. Before consuming a real `GH_TOKEN` (or pushing a
PR-pipeline script to open one), validate locally that **no PR exists for
the branch tip** with one of two independent **anonymous** probes. Both probes
work without `gh` authentication.

### Probe A — git plumbing (offline-capable, fastest)

`git ls-remote origin 'refs/pull/*/head'` returns every PR ref GitHub
maintains, each with its tip SHA. Filter for your branch tip:

```bash
# Replace <branch-tip-sha> with: git rev-parse HEAD
git ls-remote origin 'refs/pull/*/head' | grep <branch-tip-sha>
# Empty output => no PR points at this commit => safe to open.
```

If you see a non-empty line, a PR has been opened; inspect with
`gh pr view <N>` or the GitHub UI before proceeding.

### Probe B — GitHub REST API (cross-validate; metadata-rich)

```bash
curl -fsS \
  -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/Extr3sao/bot_crypto/pulls?state=all&head=Extr3sao:<branch>'
# Expected stdout for no PR: [
# ]
# Expected stdout for existing PRs: [{...PR objects...}]
```

`state=all` searches across `open` + `closed`. Use `state=open` if you only
want currently-open PRs.

> **Anonymity note**: the `Extr3sao:` prefix in `head=Extr3sao:<branch>` is
> mandatory for **anonymous** GitHub REST calls. Without auth context,
> GitHub cannot infer the owner from the URL path alone, so omitting the
> prefix yields `422 Unprocessable Entity`. If you authenticate (e.g.,
> supply `GITHUB_TOKEN` via `-H 'Authorization: Bearer ghp_…'`), the
> prefix becomes optional but is still recommended for clarity. (GitHub
> deprecated the legacy `Authorization: token …` form in November 2022.)

### Why both probes?

- **Probe A** is fully offline-capable, no API rate-limits, no auth required,
  works when `gh` isn't installed.
- **Probe B** returns full PR metadata (title, URL, author, state) — handy
  when you want to know the *which* PR already points at your SHA.
- Cross-validate: if Probe A returns **empty AND Probe B returns `[]`**, the
  idempotency claim is **high-confidence but not infallible**. Documented
  edge cases that can cause the probes to disagree (or both to miss a PR):
  - **Ref-cache lag**: rare in steady-state, but possible during burst writes
    (GitHub's ref advertisement can briefly lag by a few seconds).
  - **PRs against forks**: fork PRs surface via the upstream PR view, not
    `refs/pull/*/head`, so Probe A can miss them while Probe B still surfaces
    them.
  - **Force-pushed-away PR tips**: PRs whose tip SHA has been force-pushed
    away live as `state=closed` PRs whose `refs/pull/<N>/head` is gone; Probe
    B still finds them via `state=all`, Probe A misses them.
  - **Renamed branch heads**: if the branch was renamed after the PR was
    opened, Probe B's `head=Extr3sao:<branch>` filter looks up by *current*
    name (not the head ref recorded in the PR). Probe with the original head
    ref as recorded in the PR's URL (`/pull/<N>`), or drop the `head=` filter
    and inspect `pulls?state=all` to find which PR(s) the SHA points at.
  In any disagreement, resolve with `git ls-remote origin 'refs/pull/<N>/head'`
  + `gh pr view <N>` for the candidate PR number(s).

### Encoding note

`git ls-remote` returns lines of the form `<sha>\t<ref>`. The `\t` is a
literal TAB byte (control character, not printable). When piping through
`grep`, do not assume whitespace formatting in the output — use ripgrep or
`awk -F'\t'` if you need explicit column parsing.

## Automated smoke (CI)

The `smoke-pr-pipeline` job in `.github/workflows/ci.yml` exercises the
PowerShell script's parser via `PSParser` (regression tripwire) AND runs the
`pwsh -DryRun` mode. Without `$GH_TOKEN`, the script exits 1 at
`gh auth status` (auth-gate). With `$GH_TOKEN` (e.g. a future
`secrets.PR_PIPELINE_SMOKE_PAT`), the script reaches the idempotency check
and exits 0 at the `-DryRun` early-exit. **Neither path produces a real PR
or label side-effect** — both are smoke-passing.

The two anonymous probes above let a developer maintainer triple-check
idempotency **before** running the script — useful when promoting a branch
to live runs for the first time, or when in doubt about whether a previous
attempt actually opened a PR.

## PowerShell prerequisites

Per ADR-0020 (pwsh-only workflow scripts), all new `*.ps1` here MUST be
invokable under `pwsh` (PowerShell 7+) without Windows PowerShell 5.1
fallback. Install on Windows:

```powershell
# First-class install paths (any one works):
# 1. Microsoft Store
# 2. winget
winget install --id Microsoft.PowerShell --accept-package-agreements
# 3. choco (legacy name still works; modern equivalent is just `pwsh`)
choco install powershell-core

# Verify
pwsh --version   # expect 7.x
```

Invocation pattern:

```powershell
# PowerShell 7+ (canonical; required post-ADR-0020 for any new *.ps1)
pwsh  -NoProfile -File .\scripts\open-pr-tsk-0204.ps1 [-DryRun]

# Windows PowerShell 5.1 (DEPRECATED post-ADR-0020: TSK-013.10 backlog will
# remove this fallback entirely; new scripts MUST target pwsh 7+ exclusively)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\open-pr-tsk-0204.ps1
```

See the root `README.md` "Windows hosts" section for the full rationale
(canary patterns avoided: `$scope:`-after-variable, `@"..."@` with
`$variable` interpolated, double-quote terminator inside long here-strings).

## Cross-references

- **ADR-0017** — branch-protection `gh api` apply (auth-gated precedent; the
  `<HANDLER_PLACEHOLDER>` pattern).
- **ADR-0020** — pwsh-only workflow scripts (this directory's policy anchor).
- **`README.md`** (root) — Windows hosts pwsh-preference section.
- **`quality/release-gates.md`** — quality-gate contract for branch protection.
- **`.github/workflows/ci.yml`** — `smoke-pr-pipeline` job that exercises
  this directory's scripts in CI.
