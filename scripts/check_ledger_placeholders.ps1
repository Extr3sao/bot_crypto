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
    # Patrones prohibidos (regex case-insensitive):
    # 1. `TSK-NNN placeholder` standalone (word-boundary)
    # 2. `(TSK-NNN placeholder o equivalente)` parenthetical
    $patterns = @(
        "TSK-\d+\s+placeholder\b",
        "\(TSK-\d+\s+placeholder\s+o\s+equivalente\)"
    )
    $hits = @()
    foreach ($re in $patterns) {
        $matches_in_file = Select-String -Path $Path -Pattern $re -CaseSensitive:$false
        foreach ($m in $matches_in_file) {
            $line = $m.Line
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
                LineNumber = $m.LineNumber
                Pattern    = $re
                Line       = $line
                File       = $Path
            }
        }
    }
    return $hits
}

function Invoke-SelfTest {
    Write-Host ">>> Self-test: failure case (expected: 1 hit)"
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        # Failure pattern
        @'
TSK-999 placeholder remains pending in ledger.
'@ | Set-Content -LiteralPath $tmp -Encoding utf8
        $fail = Get-OffendingMatches -Path $tmp
        if (@($fail).Count -lt 1) {
            Write-Error "Self-test FAIL: forbidden pattern not detected"
            return $false
        }
        Write-Host "  hit detected: $($fail[0].Line.Trim())"

        Write-Host ">>> Self-test: clean text (expected: 0 hits)"
        @'
TSK-021 se firmo en tasks/backlog.md (no es placeholder).
'@ | Set-Content -LiteralPath $tmp -Encoding utf8
        $clean = Get-OffendingMatches -Path $tmp
        if (@($clean).Count -ne 0) {
            Write-Error "Self-test FAIL: legitimate text flagged (false positive)"
            return $false
        }
        Write-Host "  clean text accepted"

        Write-Host ">>> Self-test: parenthetical ambiguity (expected: 1 hit)"
        @'
Cross-link: tasks/backlog.md ticket retroactivo (TSK-021 placeholder o equivalente).
'@ | Set-Content -LiteralPath $tmp -Encoding utf8
        $parens = Get-OffendingMatches -Path $tmp
        if (@($parens).Count -lt 1) {
            Write-Error "Self-test FAIL: parenthetical ambiguity not detected"
            return $false
        }
        Write-Host "  parenthetical detected"
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
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
        Write-Error "  $($h.File):$($h.LineNumber)  pattern='$($h.Pattern)'"
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
