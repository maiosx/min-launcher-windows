# Min Launcher — Windows 10/11 port

The original is a Quickshell/Wayland (Omarchy) plugin and can't run on Windows,
so this is a PyQt6 rewrite with the same look and behaviour. Requires Python to be installed.

## Run
```
pip install PyQt6
pythonw min_launcher.py
```
Optionally run the install.bat for an automated installation.

- **Ctrl+Alt+Space** toggles it (change with `{"hotkey": "ctrl+shift+f1"}` in `%APPDATA%\min-launcher\config.json`; Win+Space etc. are reserved by Windows)
- Tray icon: Open / Start with Windows / Quit
- CLI: `--background` (start hidden), `--toggle`, `--install-startup`, `--uninstall-startup`

## Differences from the Omarchy version
- Apps come from Start Menu shortcuts + Store apps (`Get-StartApps`), launched via the shell
- Windows has no FreeDesktop categories, so sections are guessed from app names (edit `SECTION_KEYWORDS`)
- Web apps are saved to `%APPDATA%\min-launcher\web-apps.json` (same JSON format)
- Closes when it loses focus

Keys: type to filter · ↑↓/Tab move · Enter launch · Esc clear/close · **+** add web app · **−** remove it.
