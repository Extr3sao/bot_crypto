# EDGE-04 alert delivery: a desktop toast, and the receipt the OS keeps for it.
#
# Why this exists: the watchdog's exit code lives in the Task Scheduler's own database, and a
# green light in a database nobody queries is not an alert. This is the one channel on this host
# that can reach a person without elevation, without a credential and without an outbound
# connection -- and, crucially, it can prove it was received: Windows keeps every toast in the
# notification history, so the tag that was sent can be read back.
#
# The receipt is what separates "delivery" from "we wrote a file and hoped". If the tag is not in
# the history afterwards, this script says so, and the caller must not claim delivery.
#
# Usage:
#   powershell -NoProfile -File edge04_toast.ps1 -Tag EDGE04-... -Title "EDGE04 BLOCKED" -Body "..."
#   powershell -NoProfile -File edge04_toast.ps1 -Tag EDGE04-... -Mode history
#
# Requires: an interactive Windows session for the same user the scheduled task runs as. Without
# one the toast cannot be shown and the receipt check fails loudly instead of silently.

param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$Title = "EDGE04",
    [string]$Body = "",
    [string]$Group = "EDGE04",
    [ValidateSet("show", "history")][string]$Mode = "show"
)

$ErrorActionPreference = 'Stop'
$script:result = [ordered]@{
    mode       = $Mode
    tag        = $Tag
    shown      = $false
    receipt    = $false
    history    = 0
    error      = $null
    at_utc     = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

# The AUMID of Windows PowerShell: this script runs as PowerShell, so the toast is attributed to
# PowerShell and the same identity can read its own history back. No app registration, no admin.
$Aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

    if ($Mode -eq 'show') {
        $safeTitle = [System.Security.SecurityElement]::Escape($Title)
        $safeBody = [System.Security.SecurityElement]::Escape($Body)
        $xmlText = "<toast><visual><binding template=`"ToastGeneric`"><text>$safeTitle</text><text>$safeBody</text></binding></visual></toast>"
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($xmlText)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        $toast.Tag = $Tag
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($Aumid)
        $notifier.Show($toast)
        $script:result.shown = $true
        Start-Sleep -Milliseconds 800
    }

    $history = [Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory($Aumid)
    $script:result.history = @($history).Count
    $found = @($history | Where-Object { $_.Tag -eq $Tag })
    $script:result.receipt = ($found.Count -ge 1)
}
catch {
    $script:result.error = $_.Exception.Message
}

$script:result | ConvertTo-Json -Compress -Depth 3
if ($script:result.receipt) { exit 0 } else { exit 3 }
