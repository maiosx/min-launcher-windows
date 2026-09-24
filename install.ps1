# Script-based installer: no compiled .exe, so antivirus has nothing to quarantine.
# Creates a private Python venv, installs PyQt6, adds a Start Menu shortcut.
param([switch]$NoStartup, [switch]$NoLaunch)
$ErrorActionPreference = "Stop"

$src  = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA "Min Launcher"
$venv = Join-Path $dest "venv"

# Find Python 3
$py = $null
foreach ($cand in @("py", "python")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $py = $cand; break }
}
if (-not $py) { throw "Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and re-run." }

# Stop a running copy so files can be replaced
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*min_launcher.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $src "min_launcher.py") $dest -Force
Copy-Item (Join-Path $src "assets\icon.ico") $dest -Force

if (-not (Test-Path (Join-Path $venv "Scripts\pythonw.exe"))) {
    Write-Host "Creating virtual environment..."
    if ($py -eq "py") { & py -3 -m venv $venv } else { & python -m venv $venv }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}
Write-Host "Installing PyQt6..."
& (Join-Path $venv "Scripts\python.exe") -m pip install --quiet --upgrade pip PyQt6
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

$pythonw = Join-Path $venv "Scripts\pythonw.exe"
$script  = Join-Path $dest "min_launcher.py"

# Start Menu shortcut
$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "Min Launcher.lnk"
$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut($lnk)
$sc.TargetPath       = $pythonw
$sc.Arguments        = "`"$script`""
$sc.WorkingDirectory = $dest
$sc.IconLocation     = (Join-Path $dest "icon.ico")
$sc.Save()

if (-not $NoStartup) {
    & (Join-Path $venv "Scripts\python.exe") $script --install-startup
}

Write-Host ""
Write-Host "Installed to $dest"
Write-Host "Open it from the Start Menu or press Ctrl+Alt+Space once it is running."
if (-not $NoLaunch) { Start-Process $pythonw -ArgumentList "`"$script`" --background" }
