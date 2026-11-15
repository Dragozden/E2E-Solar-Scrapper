# Requires Windows PowerShell 5.1+ and the ScheduledTasks module.
# This schedules a backup for the CURRENT LOGGED-ON USER. Docker Desktop
# must be running in that user's session; no admin account is required.
#
# From the repository root:
#   .\scripts\register_weekly_backup_task.ps1
#   .\scripts\register_weekly_backup_task.ps1 -MirrorDirectory 'F:\SolarBackups' -RetentionDays 90
#
# To inspect/trigger:
#   Get-ScheduledTask -TaskName 'E2E Solar - Weekly Verified Backup'
#   Start-ScheduledTask -TaskName 'E2E Solar - Weekly Verified Backup'
# To remove: Unregister-ScheduledTask -TaskName 'E2E Solar - Weekly Verified Backup' -Confirm:$false
[CmdletBinding()]
param(
    [ValidateSet('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')]
    [string]$DayOfWeek = 'Sunday',
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$At = '10:00',
    [string]$MirrorDirectory = '',
    [ValidateRange(0,36500)]
    [int]$RetentionDays = 0,
    [ValidateRange(4,1000)]
    [int]$KeepMinimum = 4,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$TaskName = 'E2E Solar - Weekly Verified Backup'
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$PythonExe = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$BackupScript = Join-Path $RepoRoot 'scripts\backup_automation.py'

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Brak $PythonExe. Uruchom 'uv sync --frozen' z katalogu projektu."
}
if (-not (Test-Path -LiteralPath $BackupScript -PathType Leaf)) {
    throw "Brak $BackupScript. Rozpakuj pliki Etapu 9.4."
}
if ($RetentionDays -gt 0 -and $RetentionDays -lt 30) {
    throw 'RetentionDays musi byc >=30. Domyslnie retencja jest wylaczona.'
}
if ($RetentionDays -gt 0 -and [string]::IsNullOrWhiteSpace($MirrorDirectory)) {
    throw 'Nie wlaczamy retencji bez osobnego katalogu MirrorDirectory.'
}

$Arguments = '"{0}" run' -f $BackupScript
if (-not [string]::IsNullOrWhiteSpace($MirrorDirectory)) {
    if (-not (Test-Path -LiteralPath $MirrorDirectory -PathType Container)) {
        throw 'Katalog MirrorDirectory musi juz istniec, np. na zaszyfrowanym dysku zewnetrznym.'
    }
    $Mirror = (Resolve-Path -LiteralPath $MirrorDirectory).Path
    $Arguments += ' --mirror-dir "{0}"' -f $Mirror
}
if ($RetentionDays -gt 0) {
    $Arguments += ' --retention-days {0} --keep-minimum {1}' -f $RetentionDays, $KeepMinimum
}

$ScheduledTime = [datetime]::ParseExact($At, 'HH:mm', [System.Globalization.CultureInfo]::InvariantCulture)
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Arguments -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $ScheduledTime
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing -and -not $Force) {
    throw "Zadanie juz istnieje. Aby zmienic harmonogram, dodaj -Force."
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Description 'Verified local PostgreSQL backup of E2E Solar; optional encrypted mirror and retention' `
    -Force:$Force | Out-Null

Write-Host "OK: zadanie '$TaskName' zarejestrowane dla $CurrentUser"
Write-Host "Harmonogram: $DayOfWeek $At (lokalna strefa czasowa Windows)"
Write-Host "Uwaga: Docker Desktop i komputer musza dzialac; uzytkownik musi byc zalogowany."
Write-Host "Test: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Raport: uv run --frozen python scripts/backup_automation.py status"
