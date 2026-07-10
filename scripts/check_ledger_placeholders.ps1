#!/usr/bin/env pwsh
#requires -Version 7

<#
.SYNOPSIS
    Reject commits que dejan `TSK-XXX placeholder` o
    `(TSK-XXX placeholder o equivalente)` pattern en tasks/decisions.md.

.DESCRIPTION
    Closes Q8 sub-nit del code-reviewer post TSK-021 commit (`de6613b`):
    pre-commit hook + CI gate que rechaza placeholder wording en el ledger.

    Detecta dos patrones (case-insensitive):
      1. `TSK-NNN placeholder` standalone (e.g., "TSK-021 placeholder")
      2. `(TSK-NNN placeholder o equivalente)` parenthetical ambiguity

    Allowlist mechanism: edite `$ALLOWLIST_PATTERNS` si surge un use-case
    legitimo que debe quedar visible despues del fix (e.g. un comentario
    retroactivo que explique un rename TSK-XXX -> TSK-YYY).

.PARAMETER SelfTest
    Run regression self-test (writes a temp file with forbidden pattern,
    asserts the guard rejects; replaces with clean text, asserts accepts).

.PARAMETER LedgerPath
    Path to the decisions.md ledger file. Default: tasks/decisions.md.

.EXAMPLE
    pwsh ./scripts/check_ledger_placeholders.ps1

.EXAMPLE
    pwsh ./scripts/check_ledger_placeholders.ps1 -SelfTest

.NOTES
    pwsh-only (no PowerShell 5.1 fallback) per ADR-0020: scripts/.ps1 nuevos
    usan pwsh 7+ features (`??` null-coalescing, etc.). El shebang y
    `#requires -Version 7` pinean este contract en runtime.
#>

[CmdletBinding()]
param(
    [switch]$SelfTest,
    [string]$LedgerPath = "tasks/decisions.md"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Allowlist: patterns que pueden quedar en el ledger despues del fix
# (e.g., explicaciones retroactivas de rename TSK-XXX -> TSK-YYY).
# Mantener vacio por default; agregar via PR si surge necesita legitima.
$ALLOWLIST_PATTERNS = @(
    # empty
)

function Get-OffendingMatches {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warning "Ledger path '$Path' not found; guard is a no-op (PASS)."
        return @()
    }
    # BOM-tolerant reading: [System.IO.File]::ReadAllLines() strips the UTF-8
    # BOM (EF BB BF) from the first line automatically. Select-String/Get-Content
    # BOM behavior varies across pwsh versions and Windows codepages; explicit
    # ReadAllLines is the cross-platform contract (closes Q8 sub-nit #1).
    $lines = [System.IO.File]::ReadAllLines($Path)
    # Patrones prohibidos (regex case-insensitive):
    # 1. `TSK-NNN placeholder` standalone (word-boundary)
    # 2. `(TSK-NNN placeholder o equivalente)` parenthetical
    # Patrones prohibidos (regex case-insensitive, friendly labels for output):
    # 1. `TSK-NNN placeholder` standalone (word-boundary)
    # 2. `(TSK-NNN placeholder o equivalente)` parenthetical
    $patterns = @(
        [pscustomobject]@{
            Pattern     = "TSK-\d+\s+placeholder\b"
            PatternName = "TSK-NNN placeholder standalone"
        },
        [pscustomobject]@{
            Pattern     = "\(TSK-\d+\s+placeholder\s+o\s+equivalente\)"
            PatternName = "parenthetical (TSK-NNN placeholder o equivalente)"
        }
    )
    $hits = @()
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $lineNumber = $i + 1
        $line = $lines[$i]
        foreach ($re in $patterns) {
            if ($line -match $re.Pattern) {
                # Allowlist: si la linea texto matchea algun pattern del allowlist, skip.
                $is_allowed = $false
                foreach ($allowed in $ALLOWLIST_PATTERNS) {
                    if ($line -match $allowed) {
                        $is_allowed = $true
                        break
                    }
                }
                if ($is_allowed) { continue }
                $hits += [pscustomobject]@{
                    LineNumber  = $lineNumber
                    Pattern     = $re.Pattern
                    PatternName = $re.PatternName
                    Line        = $line
                    File        = $Path
                }
            }
        }
    }
    return $hits
}

function Invoke-SelfTest {
    # Per-fixture try/finally: each test case gets its own dedicated temp
    # file and a paired cleanup block. If one case fails mid-way (e.g., a
    # `Write-Error` under `$ErrorActionPreference = "Stop"`), prior fixtures
    # are still cleaned up by their own finally blocks — no fixture leak
    # on early abort or partial test run (closes Q8 sub-nit #2).
    $fixtures = @(
        @{
            Label       = "failure case (expected: 1 hit)"
            Content     = "TSK-999 placeholder remains pending in ledger.`n"
            MinHits     = 1
            MaxHits     = 1
            PassText    = "hit detected"
            ShowDetails = $true
        },
        @{
            Label       = "clean text (expected: 0 hits)"
            Content     = "TSK-021 se firmo en tasks/backlog.md (no es placeholder).`n"
            MinHits     = 0
            MaxHits     = 0
            PassText    = "clean text accepted"
            ShowDetails = $false
        },
        # Parenthetical fixture co-fires BOTH patterns: pattern 1 matches the
        # inner `TSK-021 placeholder` (followed by `)` word-boundary) and
        # pattern 2 matches the full parenthetical. Assert exact 2-hit count
        # so the label and assertion align (reviewer sub-nit).
        @{
            Label       = "parenthetical ambiguity (expected: 2 hits, both patterns)"
            Content     = "Cross-link: tasks/backlog.md ticket retroactivo (TSK-021 placeholder o equivalente).`n"
            MinHits     = 2
            MaxHits     = 2
            PassText    = "parenthetical detected"
            ShowDetails = $true
        }
    )

    $total = $fixtures.Count
    $i = 1
    foreach ($fx in $fixtures) {
        Write-Host ">>> Self-test: $($fx.Label)"
        $tmp = [System.IO.Path]::GetTempFileName()
        try {
            Set-Content -LiteralPath $tmp -Value $fx.Content -Encoding utf8
            $matches = Get-OffendingMatches -Path $tmp
            $count = @($matches).Count
            $minOk = ($count -ge $fx.MinHits)
            $maxOk = ($count -le $fx.MaxHits)
            if (-not ($minOk -and $maxOk)) {
                Write-Warning "Self-test ABORTED at fixture #$i/$total ($($fx.Label))"
                Write-Error "Self-test FAIL on '$($fx.Label)': got $count hits (expected min=$($fx.MinHits) max=$($fx.MaxHits))"
                return $false
            }
            if (-not $fx.ShowDetails) {
                Write-Host "  $($fx.PassText)"
            } else {
                # Print the matched pattern_name + pattern explicitly to disambiguate
                # which pattern fired (PatternName: friendly label; Pattern: raw regex).
                Write-Host "  $($fx.PassText): pattern_name='$($matches[0].PatternName)' pattern='$($matches[0].Pattern)' line='$($matches[0].Line.Trim())'"
            }
        } finally {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
        $i++
    }

    Write-Host "Self-test PASS"
    return $true
}

if ($SelfTest) {
    $ok = Invoke-SelfTest
    if (-not $ok) {
        exit 1
    }
    exit 0
}

$hits = Get-OffendingMatches -Path $LedgerPath
if (@($hits).Count -gt 0) {
    Write-Host ""
    Write-Error "Ledger placeholder grep-guard REJECTED the working tree."
    foreach ($h in @($hits)) {
        Write-Error "  $($h.File):$($h.LineNumber)  pattern_name='$($h.PatternName)' pattern='$($h.Pattern)'"
        Write-Error "    > $($h.Line.Trim())"
    }
    Write-Host ""
    Write-Error "Fix: replace 'placeholder' wording con a ticket concreto en tasks/backlog.md."
    Write-Error "Cada TSK-XXX reference debe apuntar a una entry firmado (Estado != placeholder)."
    Write-Error "Si el placeholder es legitimo (e.g., retroactivo explaining rename),"
    Write-Error "agregar el patron a `$ALLOWLIST_PATTERNS en este script."
    exit 1
}

Write-Host "OK: ledger is clean of placeholder wording (Landmark: Q8 sub-nit closed)"
exit 0
