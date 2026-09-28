# AI Interviewer uninstaller for Windows.
# Run via uninstall_windows.bat (double-click), or: powershell -ExecutionPolicy Bypass -File uninstall_windows.ps1
$ErrorActionPreference = 'Continue'

$AppName    = 'AI Interviewer'
$AppId      = 'ai-interviewer'
$InstallDir = Join-Path $env:LOCALAPPDATA $AppId
$ConfigDir  = Join-Path $env:APPDATA $AppId
$Profile    = Join-Path $env:LOCALAPPDATA "$AppId-profile"
$Shortcut   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ask($q) { $a = Read-Host "$q [y/N]"; return ($a -match '^[Yy]') }

Write-Host "This will remove $AppName from your PC."
if (-not (Ask 'Continue?')) { Write-Host 'Cancelled.'; exit 0 }

Say 'Stopping server'
Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "$InstallDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$uploads = Join-Path $InstallDir 'uploads'
$db      = Join-Path $InstallDir 'database'
if ((Test-Path $uploads) -or (Test-Path $db)) {
    Write-Host "`nFound user data (candidate uploads/reports and the accounts database)."
    if (Ask 'Save a backup copy to your Documents folder before deleting?') {
        $backup = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ("$AppId-backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        if (Test-Path $uploads) { Copy-Item $uploads $backup -Recurse }
        if (Test-Path $db)      { Copy-Item $db $backup -Recurse }
        Write-Host "Backup saved to $backup"
    }
}

Say 'Removing files'
Remove-Item $Shortcut -Force -ErrorAction SilentlyContinue
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Profile -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $InstallDir) {
    Write-Host "Some files in $InstallDir could not be deleted (in use?). Close any related windows and delete the folder manually." -ForegroundColor Yellow
}

if (Test-Path $ConfigDir) {
    if (Ask "Also delete config ($ConfigDir, contains SECRET_KEY and email settings)?") {
        Remove-Item $ConfigDir -Recurse -Force
    } else {
        Write-Host "Kept $ConfigDir"
    }
}

Say 'Uninstalled.'
Write-Host 'Not removed (shared system tools): Git, Python, FFmpeg, Ollama and its models.'
Write-Host 'To remove them: winget uninstall <name>   |   Ollama models: ollama list, then ollama rm <model>'
