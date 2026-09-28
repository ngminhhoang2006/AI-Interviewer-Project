# AI Interviewer installer for Windows 10/11.
# Run via install_windows.bat (double-click), or: powershell -ExecutionPolicy Bypass -File install_windows.ps1
$ErrorActionPreference = 'Stop'

$AppName  = 'AI Interviewer'
$AppId    = 'ai-interviewer'
$RepoUrl  = 'https://github.com/ngminhhoang2006/AI-Interviewer-Project.git'
$Port     = 5000

$InstallDir = Join-Path $env:LOCALAPPDATA $AppId
$ConfigDir  = Join-Path $env:APPDATA $AppId
$EnvFile    = Join-Path $ConfigDir 'env'
$Launcher   = Join-Path $InstallDir 'launcher.ps1'
$StartMenu  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$VenvPy     = Join-Path $InstallDir '.venv\Scripts\python.exe'

function Say($m)  { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Has($c)  { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
function Ask($q)  { $a = Read-Host "$q [Y/n]"; return ($a -eq '' -or $a -match '^[Yy]') }
function Winget-Install($id) {
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

# ---------------------------------------------------------------- dependencies
Say 'Checking dependencies'
if (-not (Has winget)) {
    throw 'winget was not found. Install "App Installer" from the Microsoft Store (or update Windows), then re-run.'
}
if (-not (Has git))    { Say 'Installing Git';     Winget-Install 'Git.Git' }
if (-not (Has py))     { Say 'Installing Python 3.12'; Winget-Install 'Python.Python.3.12' }
if (-not (Has ffmpeg)) { Say 'Installing FFmpeg';  Winget-Install 'Gyan.FFmpeg' }
if (-not (Has ollama)) {
    Write-Host 'Ollama is needed for question generation and grading.'
    if (Ask 'Install Ollama now?') { Say 'Installing Ollama'; Winget-Install 'Ollama.Ollama' }
    else { Write-Host 'Skipping. Install later from https://ollama.com' }
}
foreach ($c in 'git','py') { if (-not (Has $c)) { throw "$c is still not on PATH. Close this window, open a new one, and re-run the installer." } }

# ---------------------------------------------------------------- source code
Say "Fetching project into $InstallDir"
if (Test-Path (Join-Path $InstallDir '.git')) {
    git -C $InstallDir pull --ff-only
} else {
    git clone $RepoUrl $InstallDir
}
if ($LASTEXITCODE -ne 0) { throw 'git failed.' }

# ---------------------------------------------------------------- python venv
Say 'Creating virtual environment'
& py -3.12 -m venv (Join-Path $InstallDir '.venv') 2>$null
if ($LASTEXITCODE -ne 0) { & py -3 -m venv (Join-Path $InstallDir '.venv') }
if (-not (Test-Path $VenvPy)) { throw 'Could not create the virtual environment.' }
& $VenvPy -m pip install --upgrade pip

$ReqSrc    = Join-Path $InstallDir 'requirements.txt'
$ReqClean  = Join-Path $InstallDir '.requirements.clean.txt'
$ModelFile = Join-Path $InstallDir '.ollama_models.txt'

if (Test-Path $ReqSrc) {
    # Strip stdlib modules / model notes that pip rejects; use prebuilt webrtcvad wheels
    $filter = @'
import re, sys
src, dst, model_file = sys.argv[1:4]
std = set(getattr(sys, "stdlib_module_names", ())) | {
    "re", "unicodedata", "pathlib", "sys", "sqlite3", "os", "random", "time", "base64",
    "json", "shutil", "subprocess", "datetime", "collections", "threading", "io", "wave",
    "argparse",
}
skip = {"werkzeug"}
pkgs, models = [], []
for raw in open(src, encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
    if not m:
        continue
    name, rest = m.groups()
    if name.split(".")[0] in std or name.split(".")[0] in skip:
        continue
    if rest.startswith("("):
        note = rest.strip("() ")
        if name == "ollama" and note:
            models.append(note)
        rest = ""
    if name.lower() == "webrtcvad":
        name = "webrtcvad-wheels"   # avoids needing the MSVC build tools
    spec = (name + rest).strip()
    if spec not in pkgs:
        pkgs.append(spec)
open(dst, "w").write("\n".join(pkgs) + "\n")
open(model_file, "w").write("\n".join(models) + ("\n" if models else ""))
'@
    $filterPath = Join-Path $env:TEMP 'ai_interviewer_filter.py'
    Set-Content -Path $filterPath -Value $filter -Encoding UTF8
    & $VenvPy $filterPath $ReqSrc $ReqClean $ModelFile
    & $VenvPy -m pip install -r $ReqClean
} else {
    Write-Host 'No requirements.txt found; installing a minimal fallback set.'
    & $VenvPy -m pip install flask flask-login flask-mail flask-sqlalchemy itsdangerous markdown numpy ollama sherpa-onnx noisereduce webrtcvad-wheels sounddevice pymupdf sqlalchemy
    Set-Content -Path $ModelFile -Value ''
}
if ($LASTEXITCODE -ne 0) { throw 'pip install failed. See the messages above.' }

# Pull Ollama model(s) named in requirements.txt
if ((Has ollama) -and (Test-Path $ModelFile)) {
    $models = Get-Content $ModelFile | Where-Object { $_.Trim() }
    if ($models) {
        Say 'Pulling Ollama model(s)'
        foreach ($m in $models) {
            & ollama pull $m
            if ($LASTEXITCODE -ne 0) { Write-Host "Could not pull $m. Start Ollama, then run: ollama pull $m" -ForegroundColor Yellow }
        }
    }
}

# ---------------------------------------------------------------- config / secrets
Say 'Setting up config'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
if (-not (Test-Path $EnvFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    @"
# Loaded by the launcher. Keep this file private.
SECRET_KEY=$secret
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=
MAIL_PASSWORD=
"@ | Set-Content -Path $EnvFile -Encoding ASCII
    icacls $EnvFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    Write-Host "Created $EnvFile (fill in MAIL_USERNAME / MAIL_PASSWORD for email verification)"
} else {
    Write-Host "Keeping existing $EnvFile"
}

# ---------------------------------------------------------------- launcher
Say 'Writing launcher'
$launcherBody = @'
$InstallDir = '@INSTALL_DIR@'
$EnvFile    = '@ENV_FILE@'
$Port       = @PORT@
$Url        = "http://127.0.0.1:$Port"
$Profile    = Join-Path $env:LOCALAPPDATA '@APP_ID@-profile'

# Shortcuts started from Explorer may have a stale PATH (e.g. right after installing ffmpeg)
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
        }
    }
}

function Test-Up {
    try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true }
    catch { return [bool]$_.Exception.Response }
}

$server = $null
if (-not (Test-Up)) {
    $py   = Join-Path $InstallDir '.venv\Scripts\python.exe'
    $code = "import home_app; home_app.app.run(host='127.0.0.1', port=$Port, debug=False, threaded=True)"
    $server = Start-Process -FilePath $py -ArgumentList @('-c', "`"$code`"") `
        -WorkingDirectory (Join-Path $InstallDir 'apps') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $InstallDir 'server.log') `
        -RedirectStandardError  (Join-Path $InstallDir 'server.err.log')
    for ($i = 0; $i -lt 120; $i++) { if (Test-Up) { break }; Start-Sleep -Milliseconds 500 }
}

$browsers = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $browsers | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($browser) {
    # App-style window with its own profile, so we can wait until it is closed
    Start-Process -FilePath $browser -ArgumentList "--app=$Url", "--user-data-dir=`"$Profile`"" -Wait
} else {
    Start-Process $Url
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show('AI Interviewer is running in your browser. Click OK when you are finished to stop the server.', 'AI Interviewer')
}

if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
'@
$launcherBody = $launcherBody.Replace('@INSTALL_DIR@', $InstallDir).Replace('@ENV_FILE@', $EnvFile).Replace('@PORT@', "$Port").Replace('@APP_ID@', $AppId)
Set-Content -Path $Launcher -Value $launcherBody -Encoding UTF8

# ---------------------------------------------------------------- Start Menu shortcut
Say 'Creating Start Menu shortcut'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $StartMenu "$AppName.lnk"))
$lnk.TargetPath       = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments        = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$lnk.WorkingDirectory = $InstallDir
$lnk.Description      = 'AI-powered technical interview portal'
$lnk.Save()

Say 'Done!'
Write-Host "Open '$AppName' from the Start Menu."
Write-Host "Logs:   $InstallDir\server.log  (errors: server.err.log)"
Write-Host "Config: $EnvFile"
Write-Host 'Remove: run uninstall_windows.bat'
