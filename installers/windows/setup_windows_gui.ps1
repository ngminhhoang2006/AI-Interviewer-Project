# AI Interviewer setup window for Windows (install / uninstall).
# Started by install_windows_gui.bat or uninstall_windows_gui.bat, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -STA -File setup_windows_gui.ps1 -Mode Install|Uninstall
# It is a front end: the real work is done by install_windows.ps1 / uninstall_windows.ps1
# (which must sit in the same folder as this file).
param(
    [ValidateSet('Install','Uninstall')][string]$Mode = 'Install'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

trap {
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'AI Interviewer', 'OK', 'Error')
    exit 1
}

$AppName    = 'AI Interviewer'
$AppId      = 'ai-interviewer'
$IsInstall  = ($Mode -eq 'Install')
$Here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigDir  = Join-Path $env:APPDATA $AppId
$PathFile   = Join-Path $ConfigDir 'install_path'
$Shortcut   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
$DefaultDir = Join-Path $env:LOCALAPPDATA $AppId
$PsExe      = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'

$ScriptName = if ($IsInstall) { 'install_windows.ps1' } else { 'uninstall_windows.ps1' }
$Script     = Join-Path $Here $ScriptName
if (-not (Test-Path -LiteralPath $Script)) {
    throw "Could not find $ScriptName next to this file.`nKeep all the installer files in the same folder."
}

# Where is the app installed right now? (same lookup order as the uninstaller)
function Find-InstallDir {
    $d = ''
    if (Test-Path $PathFile) { $d = (Get-Content $PathFile -Encoding UTF8 | Select-Object -First 1) }
    if ([string]::IsNullOrWhiteSpace($d) -and (Test-Path $Shortcut)) {
        $a = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut).Arguments
        if ($a -match '-File\s+"([^"]+)"') { $d = Split-Path -Parent $Matches[1] }
    }
    if ([string]::IsNullOrWhiteSpace($d) -and (Test-Path $DefaultDir)) { $d = $DefaultDir }
    return $d
}

# ------------------------------------------------------------------ window
$form = New-Object System.Windows.Forms.Form
$form.Text            = if ($IsInstall) { "$AppName Setup" } else { "$AppName - Uninstall" }
$form.ClientSize      = New-Object System.Drawing.Size(640, 524)
$form.StartPosition   = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox     = $false
$form.Font            = New-Object System.Drawing.Font('Segoe UI', 9)

function New-Label($text, $x, $y, $w, $h) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text; $l.Location = New-Object System.Drawing.Point($x, $y); $l.Size = New-Object System.Drawing.Size($w, $h)
    return $l
}
function New-Check($text, $x, $y, $checked) {
    $c = New-Object System.Windows.Forms.CheckBox
    $c.Text = $text; $c.Checked = $checked
    $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size(600, 24)
    return $c
}
function New-Button($text, $x, $y, $w) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text; $b.Location = New-Object System.Drawing.Point($x, $y); $b.Size = New-Object System.Drawing.Size($w, 32)
    return $b
}

$lblTitle = New-Label $(if ($IsInstall) { "Install $AppName" } else { "Uninstall $AppName" }) 20 15 600 30
$lblTitle.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)

$introText = if ($IsInstall) {
    "This installs $AppName and anything it needs (Git, Python 3.12, FFmpeg) if they are missing. " +
    "Windows may ask for permission during setup. The first install also downloads the AI and speech models (several GB), so it can take a while."
} else {
    "This removes $AppName from this PC. Git, Python, FFmpeg and Ollama are shared tools and are left in place."
}
$lblIntro = New-Label $introText 20 48 600 52

$lblDir = New-Label $(if ($IsInstall) { 'Install location:' } else { 'Installed in:' }) 20 108 600 20
$txtDir = New-Object System.Windows.Forms.TextBox
$txtDir.Location = New-Object System.Drawing.Point(20, 130); $txtDir.Size = New-Object System.Drawing.Size(490, 24)
$txtDir.Text = if ($IsInstall) { $DefaultDir } else { Find-InstallDir }
$btnBrowse = New-Button 'Browse...' 520 127 100

$lblHint = New-Label $(if ($IsInstall) { "If the folder already contains other files, the app goes into a new '$AppId' subfolder inside it." } else { '' }) 20 158 600 20
$lblHint.ForeColor = [System.Drawing.Color]::Gray

if ($IsInstall) {
    $chk1 = New-Check 'Install Ollama if it is missing (needed for question generation and grading)' 20 184 $true
    $chk2 = $null
} else {
    $chk1 = New-Check 'Back up candidate data (uploads and database) to my Documents folder' 20 184 $true
    $chk2 = New-Check 'Also delete settings (secret key and email settings)' 20 210 $false
}

$lblStatus = New-Label 'Ready.' 20 244 600 20
$lblStatus.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(20, 266); $progress.Size = New-Object System.Drawing.Size(600, 18)
$progress.Style = 'Marquee'; $progress.MarqueeAnimationSpeed = 30; $progress.Visible = $false

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(20, 292); $txtLog.Size = New-Object System.Drawing.Size(600, 176)
$txtLog.Multiline = $true; $txtLog.ReadOnly = $true; $txtLog.ScrollBars = 'Vertical'
$txtLog.BackColor = [System.Drawing.Color]::White
$txtLog.Font = New-Object System.Drawing.Font('Consolas', 8.5)

$btnLaunch = New-Button "Open $AppName" 170 480 150
$btnLaunch.Enabled = $false; $btnLaunch.Visible = $IsInstall
$btnAction = New-Button $(if ($IsInstall) { 'Install' } else { 'Uninstall' }) 330 480 150
$btnClose  = New-Button 'Close' 490 480 130
$form.AcceptButton = $btnAction

$controls = @($lblTitle, $lblIntro, $lblDir, $txtDir, $btnBrowse, $lblHint, $chk1, $lblStatus, $progress, $txtLog, $btnLaunch, $btnAction, $btnClose)
if ($chk2) { $controls += $chk2 }
$form.Controls.AddRange($controls)

# ------------------------------------------------------------------ log handling
$script:proc    = $null
$script:posOut  = 0
$script:posErr  = 0
$script:carry   = @{ out = ''; err = '' }
$script:lines   = New-Object 'System.Collections.Generic.List[string]'
$script:lastKey = $null
$script:logFile = Join-Path $env:TEMP "$AppId-setup.out.log"
$script:errFile = Join-Path $env:TEMP "$AppId-setup.err.log"

# The child process writes in the console's OEM code page
try { $script:enc = [System.Text.Encoding]::GetEncoding([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage) }
catch { $script:enc = [System.Text.Encoding]::UTF8 }

function Read-Tail([string]$path, [string]$which) {
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    $fs = $null
    try {
        $fs  = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $pos = if ($which -eq 'out') { $script:posOut } else { $script:posErr }
        if ($fs.Length -le $pos) { return '' }
        [void]$fs.Seek($pos, [System.IO.SeekOrigin]::Begin)
        $buf = New-Object byte[] ($fs.Length - $pos)
        $n   = $fs.Read($buf, 0, $buf.Length)
        if ($which -eq 'out') { $script:posOut = $pos + $n } else { $script:posErr = $pos + $n }
        return $script:enc.GetString($buf, 0, $n)
    } catch { return '' } finally { if ($fs) { $fs.Dispose() } }
}

function Add-Log([string]$text, [string]$which, [bool]$final) {
    $text  = $script:carry[$which] + $text
    $parts = @($text -split "`r`n|`r|`n")
    if ($final) {
        $script:carry[$which] = ''
    } else {
        if ($parts.Count -le 1) { $script:carry[$which] = $text; return }
        $script:carry[$which] = $parts[$parts.Count - 1]
        $parts = $parts[0..($parts.Count - 2)]
    }
    $changed = $false
    foreach ($raw in $parts) {
        $l = ($raw -replace '\x1b\[[0-9;?]*[A-Za-z]', '').TrimEnd()
        if ([string]::IsNullOrWhiteSpace($l)) { continue }
        if ($l -match '^==>\s*(.+)$') { $lblStatus.Text = $Matches[1] }
        if ($l -match '\d+%') {
            # progress lines (e.g. model download): keep just one, updated in place
            $l   = $l -replace '[^\x20-\x7E]', ''
            $key = ($l -split ':')[0]
            if ($script:lastKey -eq $key -and $script:lines.Count -gt 0) { $script:lines[$script:lines.Count - 1] = $l }
            else { $script:lines.Add($l) }
            $script:lastKey = $key
        } else {
            $script:lastKey = $null
            $script:lines.Add($l)
        }
        $changed = $true
    }
    if ($script:lines.Count -gt 2000) { $script:lines.RemoveRange(0, $script:lines.Count - 2000) }
    if ($changed) {
        $txtLog.Lines = $script:lines.ToArray()
        $txtLog.SelectionStart = $txtLog.TextLength
        $txtLog.ScrollToCaret()
    }
}

function Set-Inputs([bool]$enabled) {
    $txtDir.Enabled = $enabled; $btnBrowse.Enabled = $enabled; $chk1.Enabled = $enabled
    if ($chk2) { $chk2.Enabled = $enabled }
}

function Finish {
    $progress.Visible = $false
    $code = $script:proc.ExitCode
    if ($code -eq 0) {
        $lblStatus.Text      = if ($IsInstall) { 'Installed successfully.' } else { 'Uninstalled.' }
        $lblStatus.ForeColor = [System.Drawing.Color]::ForestGreen
        $btnAction.Enabled   = $false
        if ($IsInstall) { $btnLaunch.Enabled = $true }
    } else {
        $lblStatus.Text      = 'Something went wrong - see the log below.'
        $lblStatus.ForeColor = [System.Drawing.Color]::Firebrick
        $btnAction.Text      = 'Try again'
        $btnAction.Enabled   = $true
        Set-Inputs $true
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 400
$timer.Add_Tick({
    if (-not $script:proc) { return }
    $done = $script:proc.HasExited
    Add-Log (Read-Tail $script:logFile 'out') 'out' $done
    Add-Log (Read-Tail $script:errFile 'err') 'err' $done
    if ($done) { $timer.Stop(); Finish }
})

# ------------------------------------------------------------------ actions
$btnBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = if ($IsInstall) { "Choose the folder to install $AppName into" } else { "Select the folder $AppName is installed in" }
    $dlg.ShowNewFolderButton = $IsInstall
    if ($txtDir.Text -and (Test-Path -LiteralPath $txtDir.Text)) { $dlg.SelectedPath = $txtDir.Text }
    if ($dlg.ShowDialog() -eq 'OK') { $txtDir.Text = $dlg.SelectedPath }
})

$btnAction.Add_Click({
    $dir = $txtDir.Text.Trim().Trim('"').TrimEnd('\')
    if ($IsInstall -and [string]::IsNullOrWhiteSpace($dir)) { $dir = $DefaultDir; $txtDir.Text = $dir }
    if (-not $IsInstall) {
        $ans = [System.Windows.Forms.MessageBox]::Show("Remove $AppName from this PC?", $AppName, 'YesNo', 'Question')
        if ($ans -ne 'Yes') { return }
    }

    Remove-Item $script:logFile, $script:errFile -Force -ErrorAction SilentlyContinue
    $script:posOut = 0; $script:posErr = 0; $script:carry = @{ out = ''; err = '' }
    $script:lines.Clear(); $script:lastKey = $null; $txtLog.Clear()

    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $Script), '-NoPrompt')
    if ($dir) { $psArgs += @('-Dir', ('"{0}"' -f $dir)) }
    if ($IsInstall) {
        if (-not $chk1.Checked) { $psArgs += '-SkipOllama' }
    } else {
        if ($chk1.Checked) { $psArgs += '-Backup' }
        if ($chk2.Checked) { $psArgs += '-DeleteConfig' }
    }

    Set-Inputs $false
    $btnAction.Enabled   = $false
    $lblStatus.ForeColor = [System.Drawing.SystemColors]::ControlText
    $lblStatus.Text      = 'Starting...'
    $progress.Visible    = $true

    $script:proc = Start-Process -FilePath $PsExe -ArgumentList $psArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $script:logFile -RedirectStandardError $script:errFile
    $null = $script:proc.Handle      # keeps ExitCode available after the process ends
    $timer.Start()
})

$btnLaunch.Add_Click({
    $d = if (Test-Path $PathFile) { (Get-Content $PathFile -Encoding UTF8 | Select-Object -First 1) } else { $txtDir.Text }
    $launcher = Join-Path $d 'launcher.ps1'
    if (Test-Path -LiteralPath $launcher) {
        Start-Process -FilePath $PsExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"{0}"' -f $launcher))
        $form.Close()
    } else {
        [void][System.Windows.Forms.MessageBox]::Show("Could not find the launcher. Open $AppName from the Start Menu instead.", $AppName)
    }
})

$btnClose.Add_Click({ $form.Close() })

$form.Add_FormClosing({
    param($sender, $e)
    if ($script:proc -and -not $script:proc.HasExited) {
        $ans = [System.Windows.Forms.MessageBox]::Show('It is still running. Stop it and close this window?', $AppName, 'YesNo', 'Warning')
        if ($ans -eq 'Yes') { & taskkill.exe /PID $script:proc.Id /T /F | Out-Null }
        else { $e.Cancel = $true }
    }
})

[void]$form.ShowDialog()
