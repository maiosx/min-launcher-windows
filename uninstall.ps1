$ErrorActionPreference = "SilentlyContinue"
$dest = Join-Path $env:LOCALAPPDATA "Min Launcher"

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*min_launcher.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 500

Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "MinLauncher"
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "Min Launcher.lnk") -Force
Remove-Item $dest -Recurse -Force

$ans = Read-Host "Also delete your saved web apps and settings? (y/N)"
if ($ans -match '^[yY]') { Remove-Item (Join-Path $env:APPDATA "min-launcher") -Recurse -Force }
Write-Host "Min Launcher removed."
