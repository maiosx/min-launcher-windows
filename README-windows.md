# Min Launcher — Windows 11 port

The original is a Quickshell/Wayland (Omarchy) plugin and can't run on Windows,
so this is a PyQt6 rewrite with the same look and behaviour.

## Run
```
pip install -r requirements.txt
pythonw min_launcher.py
```
- **Ctrl+Alt+Space** toggles it (change with `{"hotkey": "ctrl+shift+f1"}` in `%APPDATA%\min-launcher\config.json`; Win+Space etc. are reserved by Windows)
- Tray icon: Open / Start with Windows / Quit
- CLI: `--background` (start hidden), `--toggle`, `--install-startup`, `--uninstall-startup`

## Differences from the Omarchy version
- Apps come from Start Menu shortcuts + Store apps (`Get-StartApps`), launched via the shell
- Windows has no FreeDesktop categories, so sections are guessed from app names (edit `SECTION_KEYWORDS`)
- Web apps are saved to `%APPDATA%\min-launcher\web-apps.json` (same JSON format)
- Closes when it loses focus

Keys: type to filter · ↑↓/Tab move · Enter launch · Esc clear/close · **+** add web app · **−** remove it.

## Build the installer
On a Windows machine with Python 3.10+ and [Inno Setup 6](https://jrsoftware.org/isdl.php):
```
build.bat
```
This runs PyInstaller (`dist\MinLauncher\MinLauncher.exe`) and then Inno Setup, producing
`installer_output\MinLauncher-Setup-2.1.0.exe`. The installer is per-user (no admin needed),
adds a Start Menu entry, optionally starts with Windows, and removes everything on uninstall.

## Install without building an .exe (recommended if antivirus removes the packaged exe)
Double-click `install.bat` (needs Python 3.10+). It creates a private venv in
`%LOCALAPPDATA%\Min Launcher`, installs PyQt6, adds a Start Menu shortcut and enables
start-with-Windows (`install.bat -NoStartup` to skip). Remove it with `uninstall.bat`.
