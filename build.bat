@echo off
REM Builds MinLauncher.exe (PyInstaller) and, if Inno Setup is installed, the installer.
setlocal
cd /d "%~dp0"

py -m pip install -r requirements.txt pyinstaller || goto :err
py -m PyInstaller --noconfirm --clean --windowed --name MinLauncher ^
  --icon assets\icon.ico min_launcher.py || goto :err
if not exist dist\MinLauncher\MinLauncher.exe (
  echo dist\MinLauncher\MinLauncher.exe is missing - antivirus may have quarantined it.
  echo Add an exclusion for this folder and re-run.
  goto :err
)

set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo.
  echo Built dist\MinLauncher\MinLauncher.exe
  echo Install Inno Setup 6 ^(https://jrsoftware.org/isdl.php^) and re-run to create the installer.
  goto :eof
)
"%ISCC%" installer.iss || goto :err
echo.
echo Installer: installer_output\
goto :eof

:err
echo Build failed.
exit /b 1
