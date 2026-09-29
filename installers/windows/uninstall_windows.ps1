# AI Interviewer uninstaller for Windows.
# Run via uninstall_windows.bat (double-click), or:
#   powershell -ExecutionPolicy Bypass -File uninstall_windows.ps1 [-Dir "D:\Apps\ai-interviewer"] [-NoPrompt [-Backup] [-DeleteConfig]]
# -Dir is only needed if the install location can't be detected automatically.
param(
    [Alias('d')][string]$Dir = '',
    [switch]$NoPrompt,      # never ask questions (used by the setup window)
    [switch]$Backup,        # with -NoPrompt: back up uploads/database to Documents
    [switch]$DeleteConfig   # with -NoPrompt: also delete the config folder
)
$ErrorActionPreference = 'Continue'

$AppName    = 'AI Interviewer'
$AppId      = 'ai-interviewer'
$Marker     = '.ai-interviewer-install'
$DefaultInstallDir = Join-Path $env:LOCALAPPDATA $AppId
$ConfigDir  = Join-Path $env:APPDATA $AppId
$PathFile   = Join-Path $ConfigDir 'install_path'
$Profile    = Join-Path $env:LOCALAPPDATA "$AppId-profile"
$Shortcut   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ask($q) { $a = Read-Host "$q [y/N]"; return ($a -match '^[Yy]') }

# ---------------------------------------------------------------- locate install folder
$InstallDir = $Dir

# 1) recorded by the installer  2) read from the Start Menu shortcut  3) default location
if ([string]::IsNullOrWhiteSpace($InstallDir) -and (Test-Path $PathFile)) {
    $InstallDir = (Get-Content $PathFile -Encoding UTF8 | Select-Object -First 1)
}
if ([string]::IsNullOrWhiteSpace($InstallDir) -and (Test-Path $Shortcut)) {
    $lnkArgs = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut).Arguments
    if ($lnkArgs -match '-File\s+"([^"]+)"') { $InstallDir = Split-Path -Parent $Matches[1] }
}
if ([string]::IsNullOrWhiteSpace($InstallDir) -and (Test-Path $DefaultInstallDir)) {
    $InstallDir = $DefaultInstallDir
}
if (-not $NoPrompt -and ([string]::IsNullOrWhiteSpace($InstallDir) -or -not (Test-Path -LiteralPath $InstallDir))) {
    $InstallDir = Read-Host 'Could not find the install folder. Enter it (blank to skip)'
}

if (-not [string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = $InstallDir.Trim().Trim('"')
    $InstallDir = [Environment]::ExpandEnvironmentVariables($InstallDir)
    if ($InstallDir -match '^~([\\/]|$)') { $InstallDir = $HOME + $InstallDir.Substring(1) }
    $InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir).TrimEnd('\','/')
}

# Safety: only ever delete a folder that clearly belongs to this app
$RemoveDir = $false
if ($InstallDir -and (Test-Path -LiteralPath $InstallDir)) {
    $root = [IO.Path]::GetPathRoot($InstallDir).TrimEnd('\','/')
    if ($InstallDir -eq $root -or $InstallDir -eq $env:USERPROFILE.TrimEnd('\','/')) {
        Write-Host "Refusing to delete '$InstallDir'." -ForegroundColor Yellow
    } elseif ((Test-Path -LiteralPath (Join-Path $InstallDir $Marker)) -or
              (Test-Path -LiteralPath (Join-Path $InstallDir '.git'))) {
        $RemoveDir = $true
    } else {
        Write-Host "'$InstallDir' doesn't look like an $AppId install (no marker file). Not deleting it." -ForegroundColor Yellow
    }
}

Write-Host "This will remove $AppName from your PC."
if ($RemoveDir) { Write-Host "Install folder: $InstallDir" }
if (-not $NoPrompt -and -not (Ask 'Continue?')) { Write-Host 'Cancelled.'; exit 0 }

Say 'Stopping server'
if ($RemoveDir) {
    $prefix = $InstallDir + '\'
    Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

if ($RemoveDir) {
    $uploads = Join-Path $InstallDir 'uploads'
    $db      = Join-Path $InstallDir 'database'
    if ((Test-Path $uploads) -or (Test-Path $db)) {
        Write-Host "`nFound user data (candidate uploads/reports and the accounts database)."
        $doBackup = if ($NoPrompt) { [bool]$Backup } else { Ask 'Save a backup copy to your Documents folder before deleting?' }
        if ($doBackup) {
            $backup = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ("$AppId-backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
            New-Item -ItemType Directory -Force -Path $backup | Out-Null
            if (Test-Path $uploads) { Copy-Item $uploads $backup -Recurse }
            if (Test-Path $db)      { Copy-Item $db $backup -Recurse }
            Write-Host "Backup saved to $backup"
        }
    }
}

Say 'Removing files'
Remove-Item $Shortcut -Force -ErrorAction SilentlyContinue
if ($RemoveDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $InstallDir) {
        Write-Host "Some files in $InstallDir could not be deleted (in use?). Close any related windows and delete the folder manually." -ForegroundColor Yellow
    }
}
Remove-Item $Profile -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $ConfigDir) {
    $doConfig = if ($NoPrompt) { [bool]$DeleteConfig } else { Ask "Also delete config ($ConfigDir, contains SECRET_KEY and email settings)?" }
    if ($doConfig) {
        Remove-Item $ConfigDir -Recurse -Force
    } else {
        Remove-Item $PathFile -Force -ErrorAction SilentlyContinue   # stale once the install folder is gone
        Write-Host "Kept $ConfigDir"
    }
}

Say 'Uninstalled.'
Write-Host 'Not removed (shared system tools): Git, Python, FFmpeg, Ollama and its models.'
Write-Host 'To remove them: winget uninstall <name>   |   Ollama models: ollama list, then ollama rm <model>'
exit 0
