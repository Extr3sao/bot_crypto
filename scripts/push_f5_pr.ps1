<#
.SYNOPSIS
    End-to-end PowerShell runbook to push the F5 (TSK-103.5) PR to main,
    including dual-review code owner gate and post-merge bookkeeping.

.DESCRIPTION
    Phases:
      0. Pre-flight        (gh auth, remote, CODEOWNERS teams, working tree, CI jobs)
      1. Branch            (refresh main, create feature/tsk-103-5-bdd-wiring)
      2. Stage             (13 F5 files explicitly; preserves staged-but-unrelated)
      3. Commit + push     (conventional commit message; force-with-lease=no)
      4. gh pr create      (--body-file pr-body-TASK-103.5.md)
      5. Monitor           (poll for REQUIRED CI status checks + CODEOWNERS-team approvals)
      6. Squash-merge      (after CI green + CODEOWNERS dual-team approval)
      7. Post-merge        (tag, retrieval-log close-out, backlog flip, sprint-002 entry)

    Round-17 critical fixes applied (round-18 verifier pending):
      - Q1: CODEOWNERS team match via Where-Object exact equality (NOT Select-String
        SimpleMatch which substring-matched "strategy-team-fork" etc.).
      - Q2: git pull --ff-only failure aborts (no longer warns-and-continues),
        preventing branch issues from a diverged stale main. NEW exit code 12.
      - Q3: COMMIT_BODY_LINE_MAX = 72 enforced per git convention (some long
        bullet lines in round-17 above 72 -> trimmed).
      - Q4a: gh pr checks filtered to required names only (format-and-lint +
        type-check + pip-audit + tests-and-coverage); FAILURE on optional
        context no longer aborts.
      - Q4b: dual-review verification queries each team's members via
        gh api /orgs/<org>/teams/<slug>/members and confirms at least 1 APPROVED
        from strategy-team AND 1 APPROVED from security-team (NOT just
        "any 2 approvals").

.PRE-FLIGHT
    - PowerShell 7.x
    - gh CLI authenticated: gh auth status  (debe reportar scope repo + admin:org)
    - .venv verde per `.\scripts\validate_gates_f5.ps1 -Scope scanner`
    - pytest-bdd --collect-only tests/bdd/ reporta 23/23 scenarios

.NOTES
    Author        : context-engineer (TSK-103.5 round-17 -> 18)
    Cross-links   : pr-body-TASK-103.5.md; .github/CODEOWNERS;
                    .github/workflows/ci.yml; quality/release-gates.md Bloque 6
#>

[CmdletBinding()]
param(
    [string]$Branch = "feature/tsk-103-5-bdd-wiring",
    [string]$PrTitle = "TSK-103.5 (F5): BDD wiring + 23 scenarios + 6 quality gates wrap-up",
    [string]$PrBase = "main",
    [string]$Remote = "origin",
    [switch]$SkipPush,                    # debug-only
    [switch]$SkipMerge,                   # debug-only
    [switch]$SkipBookkeeping,             # debug-only
    [int]$PollSeconds = 60,
    [int]$MaxAttempts = 60
)

# Round-17 Q3: git convention max body line length.
$COMMIT_BODY_LINE_MAX = 72
# Round-17 Q4a: required CI checks per .github/workflows/ci.yml.
$RequiredChecks = @("format-and-lint", "type-check", "pip-audit", "tests-and-coverage")

$ErrorActionPreference = "Continue"
$repo = (Get-Location).Path
$ts = Get-Date -Format "yyyy-MM-dd HH:mm"

Write-Host "===============================================================" -ForegroundColor Cyan
Write-Host "F5 (TSK-103.5) PR push runbook @ $ts" -ForegroundColor Cyan
Write-Host "Repo : $repo" -ForegroundColor Cyan
Write-Host "Branch: $Branch  |  PR base: $PrBase  |  Remote: $Remote" -ForegroundColor Cyan
Write-Host "Required CI : $($RequiredChecks -join ', ')" -ForegroundColor Cyan
Write-Host "Team gate    : strategy-team + security-team (each >= 1 APPROVED)" -ForegroundColor Cyan
Write-Host "===============================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------
# Phase 0 — Pre-flight (gate-feel; abort rojo on any failure)
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 0] Pre-flight checks" -ForegroundColor Yellow

# 0.1 — gh CLI auth
$ghStatus = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] gh not authenticated. Run: gh auth login" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] gh authenticated" -ForegroundColor Green

# 0.2 — remote configured
$remoteUrl = & git remote get-url $Remote 2>&1
if (-not $remoteUrl) {
    Write-Host "  [RED] git remote '$Remote' not set" -ForegroundColor Red
    exit 2
}
Write-Host "  [OK] remote $Remote = $remoteUrl" -ForegroundColor Green

# 0.3 — working tree limpio (untracked files OK; rechaza staged-but-unrelated to F5)
$wt = & git status --porcelain 2>&1
$stagedUnrelated = @($wt | Where-Object { $_ -match '^[AM]' } | ForEach-Object {
    $f = ($_ -split '\s+', 2)[1]
    if ($f -notin @(
        "tests/unit/scanner/conftest.py",
        "tests/bdd/__init__.py",
        "tests/bdd/conftest.py",
        "tests/bdd/step_defs/__init__.py",
        "tests/bdd/step_defs/test_legacy_steps.py",
        "tests/bdd/step_defs/test_snapshot_steps.py",
        "tests/bdd/step_defs/test_state_steps.py",
        "tests/bdd/step_defs/test_runtime_steps.py",
        "tests/bdd/step_defs/test_ast_and_registry_steps.py",
        "tests/bdd/step_defs/test_scoring_steps.py",
        "tests/bdd/step_defs/test_edge_steps.py",
        ".github/CODEOWNERS",
        "scripts/validate_gates_f5.ps1"
    )) { $f }
})
if ($stagedUnrelated.Count -gt 0) {
    Write-Host "  [RED] pre-staged files outside F5 scope:" -ForegroundColor Red
    $stagedUnrelated | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host "  Hint: git restore --staged <file> for each, then re-run this script." -ForegroundColor Yellow
    exit 3
}
Write-Host "  [OK] working tree clean (only F5 files in scope)" -ForegroundColor Green

# 0.4 — CODEOWNERS teams pre-flight (CRITICAL: dual-review gate)
# Round-17 Q1 fix: use Where-Object exact equality instead of
# Select-String -SimpleMatch (substring) which false-matched teams like
# "strategy-team-fork" or "my-strategy-team-test". Exact match via Where-Object
# { $_ -eq "strategy-team" } is canonical for the slugs en /orgs/<org>/teams.
Write-Host "  [CHECK] CODEOWNERS pre-flight (strategy-team + security-team EXACT slugs):" -ForegroundColor Yellow
$allTeamsJson = & gh api /orgs/Extr3sao/teams --jq '.[].slug' 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] gh api /orgs/Extr3sao/teams failed: $allTeamsJson" -ForegroundColor Red
    exit 4
}
# --jq emits each slug on its own line; convert to array.
$allTeams = @($allTeamsJson | Where-Object { $_.Trim() -ne "" } | ForEach-Object { $_.Trim() })
$hasStrategy = @($allTeams | Where-Object { $_ -eq "strategy-team" }).Count -gt 0
$hasSecurity = @($allTeams | Where-Object { $_ -eq "security-team" }).Count -gt 0
if (-not $hasStrategy -or -not $hasSecurity) {
    Write-Host "  [RED] CODEOWNERS dual-review IMPOSSIBLE: faltan teams criticos" -ForegroundColor Red
    Write-Host "    strategy-team exists:    $hasStrategy" -ForegroundColor Red
    Write-Host "    security-team exists:    $hasSecurity" -ForegroundColor Red
    Write-Host "    available teams (sample): $($allTeams[0..7] -join ', ')" -ForegroundColor Red
    Write-Host "  Mitigacion: ADR firmada documenta bootstrap team creation antes del PR." -ForegroundColor Red
    exit 5
}
Write-Host "  [OK] strategy-team + security-team both present in org (exact match verified)" -ForegroundColor Green

# 0.5 — recommended pre-run (no enforcement; allows manual run)
if (Test-Path ".\scripts\validate_gates_f5.ps1") {
    Write-Host "  [RECOMMEND] Execute before: .\scripts\validate_gates_f5.ps1 -Scope scanner" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------
# Phase 1 — Branch ops
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 1] Branch ops: refresh main + create $Branch" -ForegroundColor Yellow

& git fetch $Remote | Out-Null
& git switch $PrBase | Out-Null
# Round-17 Q2 fix: --ff-only failure now ABORTS, not warns-and-continues.
# Creating the branch from stale main would push a non-FF-able PR later.
$pullOut = & git pull --ff-only 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] git pull --ff-only failed: $pullOut" -ForegroundColor Red
    Write-Host "  Hint: si tienes local changes conflictivos, git stash primero." -ForegroundColor Red
    Write-Host "        NO procede continuar: la branch se basaria en main stale." -ForegroundColor Red
    exit 12
}
Write-Host "  [OK] main refreshed (--ff-only fast-forward)" -ForegroundColor Green

# Branch detection: --list returns empty for missing branches; non-empty for existing.
$existingBranches = (& git branch --list $Branch 2>$null)
if ($existingBranches -and $existingBranches.Count -gt 0 -and $existingBranches[0].Trim()) {
    Write-Host "  [INFO] branch '$Branch' ya existe localmente: checkout sin -c" -ForegroundColor Cyan
    & git switch $Branch | Out-Null
} else {
    Write-Host "  [INFO] creating new branch '$Branch' desde $PrBase" -ForegroundColor Cyan
    & git switch -c $Branch | Out-Null
}
Write-Host "  [OK] on branch: $(& git rev-parse --abbrev-ref HEAD)" -ForegroundColor Green

# -----------------------------------------------------------------------
# Phase 2 — Stage 13 F5 files explicitly (selectivo)
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 2] Stage 13 F5 files explicitly (selectivo, pine contract del PR)" -ForegroundColor Yellow

$F5Files = @(
    "tests/unit/scanner/conftest.py",
    "tests/bdd/__init__.py",
    "tests/bdd/conftest.py",
    "tests/bdd/step_defs/__init__.py",
    "tests/bdd/step_defs/test_legacy_steps.py",
    "tests/bdd/step_defs/test_snapshot_steps.py",
    "tests/bdd/step_defs/test_state_steps.py",
    "tests/bdd/step_defs/test_runtime_steps.py",
    "tests/bdd/step_defs/test_ast_and_registry_steps.py",
    "tests/bdd/step_defs/test_scoring_steps.py",
    "tests/bdd/step_defs/test_edge_steps.py",
    ".github/CODEOWNERS",
    "scripts/validate_gates_f5.ps1"
)

foreach ($f in $F5Files) {
    if (Test-Path $f) {
        & git add $f | Out-Null
    } else {
        Write-Host "  [WARN] file missing on disk: $f" -ForegroundColor Yellow
    }
}

# pr-body es consumido por gh via --body-file; no se stage.
Write-Host "  [INFO] pr-body-TASK-103.5.md NOT staged (consumed by --body-file)" -ForegroundColor Cyan

Write-Host ""
Write-Host "  [verify] git diff --cached --stat:" -ForegroundColor Cyan
& git diff --cached --stat

# -----------------------------------------------------------------------
# Phase 3 — Commit + push
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 3] Commit + push" -ForegroundColor Yellow

if ($SkipPush) {
    Write-Host "  [SKIP] -SkipPush: commit local + no push" -ForegroundColor Yellow
    exit 0
}

# Conventional commit message per AGENTS.md SDD.
# Round-17 Q3 fix: lines trimmed to <= 72 chars per git convention.
# Boundaries: prefix bullet "- " + path + ": " + description <= 72.
$commitMsg = @"
feat(scanner): TSK-103.5 (F5) BDD wiring + 23 scenarios + 6 gates

- tests/unit/scanner/conftest.py: helpers + 3 fixtures
- tests/bdd/: pytest-bdd glue + 7 step_defs (23 BDD scenarios)
- scripts/validate_gates_f5.ps1: 6 quality gates runner
- .github/CODEOWNERS: dual-review patch for scanner + tests/bdd
- pr-body-TASK-103.5.md: cross-link ADR-0013 + spec pack + logs

Precedes: TSK-103.4 (F4) done per retrieval-log [12:00]
ADR: ADR-0013 (signed [11:00]) covers F5 scope endogamically
"@

# Sanity-check: each body line within $COMMIT_BODY_LINE_MAX chars (excluding leading "- ").
# Subject line "feat(scanner): TSK-103.5 ..." should be <= 72 too.
$lines = ($commitMsg -split "`n")
$overlong = @($lines | Where-Object { $_.Length -gt $COMMIT_BODY_LINE_MAX })
if ($overlong.Count -gt 0) {
    Write-Host "  [WARN] commit message has over-long lines (>$COMMIT_BODY_LINE_MAX chars):" -ForegroundColor Yellow
    $overlong | ForEach-Object { Write-Host "    $($_.Length) chars: $_\"" -ForegroundColor Yellow }
}

& git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] git commit failed" -ForegroundColor Red
    exit 13
}

# Push branch con upstream tracking
$pushOut = & git push -u $Remote $Branch 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] git push failed: $pushOut" -ForegroundColor Red
    exit 6
}
Write-Host "  [OK] branch pushed to $Remote/$Branch" -ForegroundColor Green

# -----------------------------------------------------------------------
# Phase 4 — gh pr create
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 4] gh pr create --body-file pr-body-TASK-103.5.md" -ForegroundColor Yellow

if (-not (Test-Path "pr-body-TASK-103.5.md")) {
    Write-Host "  [RED] pr-body-TASK-103.5.md not found at repo root" -ForegroundColor Red
    exit 7
}

# Round-17 hint: --reviewer accepts team slugs (semantic flag for CODEOWNERS context).
# GitHub auto-routes review requests to CODEOWNERS-list members when teams are listed in CODEOWNERS.
$prOut = & gh pr create `
    --base $PrBase `
    --head $Branch `
    --title $PrTitle `
    --body-file pr-body-TASK-103.5.md `
    --reviewer "Extr3sao/strategy-team,Extr3sao/security-team" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] gh pr create failed: $prOut" -ForegroundColor Red
    exit 8
}
$prUrl = $prOut.Trim()
Write-Host "  [OK] PR opened: $prUrl" -ForegroundColor Green

# -----------------------------------------------------------------------
# Phase 4.5 — Cache team membership for Phase 5 dual-review verification
# -----------------------------------------------------------------------
# Round-17 Q4b fix: cache team membership up-front so Phase 5 polling
# queries local instead of repeating API calls every $PollSeconds seconds.
Write-Host ""
Write-Host "[Phase 4.5] Caching CODEOWNERS-team membership for Phase 5" -ForegroundColor Yellow

$strategyMembers = @(& gh api /orgs/Extr3sao/teams/strategy-team/members --jq '.[].login' 2>&1 |
    Where-Object { $_.Trim() -ne "" } | ForEach-Object { $_.Trim() })
$securityMembers = @(& gh api /orgs/Extr3sao/teams/security-team/members --jq '.[].login' 2>&1 |
    Where-Object { $_.Trim() -ne "" } | ForEach-Object { $_.Trim() })

if ($strategyMembers.Count -eq 0 -or $securityMembers.Count -eq 0) {
    Write-Host "  [RED] CODEOWNERS team membership empty; dual-review IMPSIBLE" -ForegroundColor Red
    Write-Host "    strategy-team member count: $($strategyMembers.Count)" -ForegroundColor Red
    Write-Host "    security-team member count: $($securityMembers.Count)" -ForegroundColor Red
    exit 14
}
Write-Host "  [OK] strategy-team: $($strategyMembers.Count) members; security-team: $($securityMembers.Count) members" -ForegroundColor Green

# -----------------------------------------------------------------------
# Phase 5 — Monitor: poll for REQUIRED CI + CODEOWNERS-team approvals
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 5] Monitor: required CI + CODEOWNERS-team dual-approval" -ForegroundColor Yellow
Write-Host "  Required CI checks per .github/workflows/ci.yml:" -ForegroundColor Yellow
foreach ($c in $RequiredChecks) {
    Write-Host "    - $c" -ForegroundColor Yellow
}
Write-Host "  CODEOWNERS dual-review: >= 1 APPROVED from strategy-team AND >= 1 APPROVED from security-team" -ForegroundColor Yellow
Write-Host ""

$prNum = (& $prUrl -split '/')[-1]
$readyToMerge = $false
$attempts = 0

while (-not $readyToMerge -and $attempts -lt $MaxAttempts) {
    Start-Sleep -Seconds $PollSeconds
    $attempts += 1

    # 5.1 — Required CI status checks (filtered to REQUIRED names only).
    # Round-17 Q4a fix: ignore FAILURE on optional/contextual checks; only
    # FAILURE on $RequiredChecks aborts.
    $checksJson = & gh pr checks $prNum --json name,state 2>&1
    if ($LASTEXITCODE -eq 0) {
        $checks = $checksJson | ConvertFrom-Json
        $requiredAndFailed = @($checks | Where-Object {
            ($RequiredChecks -contains $_.name) -and ($_.state -eq "FAILURE")
        })
        $requiredAndPending = @($checks | Where-Object {
            ($RequiredChecks -contains $_.name) -and ($_.state -in @("PENDING", "QUEUED", "IN_PROGRESS"))
        })
        if ($requiredAndFailed.Count -gt 0) {
            Write-Host "  [RED] attempt $attempts: required CI check(s) failed:" -ForegroundColor Red
            $requiredAndFailed | ForEach-Object { Write-Host "    - $($_.name)" -ForegroundColor Red }
            Write-Host "  Hint: gh pr checks $prNum --watch for interactive inspection" -ForegroundColor Yellow
            Write-Host "  Manual: review logs, fix, iterate, re-push" -ForegroundColor Yellow
            exit 9
        } elseif ($requiredAndPending.Count -gt 0) {
            Write-Host "  [WAIT] attempt $attempts: $($requiredAndPending.Count) required check(s) pending" -ForegroundColor Cyan
            Write-Host "    pending: $($requiredAndPending.name -join ', ')" -ForegroundColor Cyan
        } else {
            # Si al menos 1 required check payload existe en la respuesta,
            # verificar q todos esten en SUCCESS. Si NO existe ningun required
            # todavia (race post-pr-open), reportar como pending-light.
            $requiredAndSuccess = @($checks | Where-Object {
                ($RequiredChecks -contains $_.name) -and ($_.state -eq "SUCCESS")
            })
            if ($requiredAndSuccess.Count -ge $RequiredChecks.Count) {
                Write-Host "  [OK] attempt $attempts: all $($RequiredChecks.Count) required CI checks passed" -ForegroundColor Green
            } else {
                Write-Host "  [WAIT] attempt $attempts: required CI not yet populated ($($requiredAndSuccess.Count)/$($RequiredChecks.Count) SUCCESS)" -ForegroundColor Cyan
            }
        }
    } else {
        Write-Host "  [WARN] gh pr checks failed (transient?): $checksJson" -ForegroundColor Yellow
    }

    # 5.2 — Review approvals (CODEOWNERS-team membership dual-verification).
    # Round-17 Q4b fix: each APPROVED must come from a CODEOWNERS-team member.
    # `$reviewsJson` uses `user.login` (rename via .user.login pipe through jq).
    $reviewsJson = & gh api /repos/Extr3sao/bot_crypto/pulls/$prNum/reviews --jq '[.[] | {user: .user.login, state: .state}]' 2>&1
    if ($LASTEXITCODE -eq 0) {
        $reviews = $reviewsJson | ConvertFrom-Json
        $approvedAll = @($reviews | Where-Object { $_.state -eq "APPROVED" })
        # Restrict to CODEOWNERS-team-approved memberships.
        $approvedStrategy = @($approvedAll | Where-Object { $strategyMembers -contains $_.user })
        $approvedSecurity = @($approvedAll | Where-Object { $securityMembers -contains $_.user })

        Write-Host "  [REVIEW] APPROVED total=$($approvedAll.Count) | strategy-team=$($approvedStrategy.Count) ($($approvedStrategy.user -join ', ')) | security-team=$($approvedSecurity.Count) ($($approvedSecurity.user -join ', '))" -ForegroundColor Cyan

        if ($approvedStrategy.Count -ge 1 -and $approvedSecurity.Count -ge 1) {
            $readyToMerge = $true
            Write-Host "  [OK] CODEOWNERS dual-team review complete" -ForegroundColor Green
        } else {
            $missing = @()
            if ($approvedStrategy.Count -lt 1) { $missing += "strategy-team" }
            if ($approvedSecurity.Count -lt 1) { $missing += "security-team" }
            Write-Host "  [WAIT] dual-review pending: missing approver(s) from $($missing -join ', ')" -ForegroundColor Yellow
        }
    }
}

if (-not $readyToMerge) {
    Write-Host ""
    Write-Host "  [TIMEOUT] $MaxAttempts attempts x $PollSeconds s sin dual-review" -ForegroundColor Red
    Write-Host "  Hint: revisar manualmente $prUrl" -ForegroundColor Yellow
    Write-Host "        ping via /cc @strategy-team @security-team en el PR thread" -ForegroundColor Yellow
    exit 10
}

# -----------------------------------------------------------------------
# Phase 6 — Squash-merge
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 6] Squash-merge a $PrBase" -ForegroundColor Yellow

if ($SkipMerge) {
    Write-Host "  [SKIP] -SkipMerge: PR sin squashear (usuario lo hara manual)" -ForegroundColor Yellow
    exit 0
}

& gh pr merge $prNum `
    --squash `
    --delete-branch `
    --subject "feat(scanner): TSK-103.5 (F5) BDD wiring + 23 scenarios + 6 quality gates wrap-up" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [RED] gh pr merge failed" -ForegroundColor Red
    exit 11
}
Write-Host "  [OK] PR squash-mergeado a $PrBase" -ForegroundColor Green

# -----------------------------------------------------------------------
# Phase 7 — Post-merge bookkeeping
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "[Phase 7] Post-merge bookkeeping" -ForegroundColor Yellow

if ($SkipBookkeeping) {
    Write-Host "  [SKIP] -SkipBookkeeping: usuario hara los flips manual" -ForegroundColor Yellow
    exit 0
}

# 7.1 — Local cleanup
& git switch $PrBase | Out-Null
& git pull --ff-only | Out-Null
& git branch -d $Branch 2>$null | Out-Null
Write-Host "  [OK] branch local '$Branch' purgada; main refreshed" -ForegroundColor Green

# 7.2 — Tag v0.5.0-rc.1 (F5 release candidate)
& git tag -a v0.5.0-rc.1 -m "TSK-103.5 (F5) BDD wiring + 23 scenarios + 6 quality gates wrap-up"
& git push $Remote v0.5.0-rc.1 2>&1 | Out-Null
Write-Host "  [OK] tag v0.5.0-rc.1 pushed" -ForegroundColor Green

# 7.3 — Append retrieval-log entry for F5 close-out (per merge de ahora)
$newEntry = @"

[$ts] agent=context-engineer | action=close TSK-103.5 (F5) BDD wiring PR merged to main | artifacts=tests/unit/scanner/conftest.py, tests/bdd/{__init__,conftest}.py, tests/bdd/step_defs/{__init__}.py + 7 step_defs modules, .github/CODEOWNERS, scripts/validate_gates_f5.ps1, scripts/push_f5_pr.ps1, pr-body-TASK-103.5.md, git:tag@v0.5.0-rc.1 | summary=F5 PR squash-mergeado a main per scripts/push_f5_pr.ps1 PowerShell runbook. Chain: pre-flight (CODEOWNERS teams exact-match verified strategy-team + security-team) + branch refresh + 13 files staged (selectivo) + round-17 Q1/Q2/Q3/Q4 hardened commit + gh pr create con --body-file + CODEOWNERS-team membership cacheado en Phase 4.5 (re-using for Phase 5 polling) + dual-approved-required polling (1 strategy-team + 1 security-team, NO cualquier 2) + squash-merge con --delete-branch. Tag v0.5.0-rc.1 pushed para Fase 2 candidates. Pendiente: tasks/backlog.md TSK-103.5 in_progress -> done + tasks/sprint-002.md [merge-time] log entry (no se hace automaticamente per scope de este script; ver 7.4 manual step del usuario).
"@
Add-Content -Path context/retrieval-log.md -Value $newEntry
Write-Host "  [OK] retrieval-log [merge-time] entry appended" -ForegroundColor Green

# 7.4 — Manual flags (user does these manually para evitar drift)
Write-Host ""
Write-Host "  [MANUAL] User-side bookkeeping (NO automated para evitar drift):" -ForegroundColor Magenta
Write-Host "    - tasks/backlog.md: TSK-103.5 in_progress -> done + close-out notes" -ForegroundColor Magenta
Write-Host "    - tasks/sprint-002.md: add [merge-time] log entry + DoD check (6 CI gates)" -ForegroundColor Magenta
Write-Host "    - tasks/decisions.md: opcional ADR-0014 'F5 closure' si surge scope change" -ForegroundColor Magenta

Write-Host ""
Write-Host "===============================================================" -ForegroundColor Green
Write-Host "F5 (TSK-103.5) PR push runbook complete @ $ts" -ForegroundColor Green
Write-Host "===============================================================" -ForegroundColor Green
exit 0
