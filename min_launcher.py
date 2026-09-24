"""
Min Launcher for Windows 11
===========================
Fullscreen app launcher overlay (port of the Omarchy/Quickshell plugin).

* Apps: Start Menu shortcuts (.lnk) + packaged/Store apps (Get-StartApps)
* Web Apps: your own list, stored in %APPDATA%\\min-launcher\\web-apps.json
* Global hotkey (default Ctrl+Alt+Space), tray icon, single instance

Usage
-----
  pythonw min_launcher.py               show the launcher (starts it if needed)
  pythonw min_launcher.py --background  start hidden in the tray
  pythonw min_launcher.py --toggle      toggle a running instance
  pythonw min_launcher.py --install-startup / --uninstall-startup
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import (
    QAbstractNativeEventFilter, QEvent, QFileInfo, QPoint, QRect, QRectF, Qt,
    QThread, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QColor, QCursor, QDesktopServices, QFont, QFontMetrics,
    QGuiApplication, QIcon, QPainter, QPixmap,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QFileIconProvider, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
)

IS_WIN = sys.platform == "win32"
APP_NAME = "Min Launcher"
SERVER_NAME = "min-launcher-single-instance"
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "min-launcher"
WEB_APPS_FILE = CONFIG_DIR / "web-apps.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_HOTKEY = "ctrl+alt+space"

MAX_CONFIG_BYTES = 64 * 1024
MAX_WEB_ITEMS = 100
MAX_NAME_LENGTH = 128
MAX_URL_LENGTH = 2048

FONT_FAMILY = "Segoe UI Variable, Segoe UI, Inter, sans-serif"
C_TEXT = "#f0f0f2"
C_MUTED = "#8a8a96"
C_ACCENT = "#7c6af7"
C_HOVER = "#1c1c22"
C_BORDER = "#2a2a32"
C_DANGER = "#f87171"
DOT_PALETTE = ["#60a5fa", "#a78bfa", "#f472b6", "#34d399", "#fbbf24",
               "#fb7185", "#22d3ee", "#c084fc", "#4ade80", "#f97316"]

SECTION_ORDER = ["Development", "Graphics", "Internet", "Office", "Multimedia",
                 "System", "Utility", "Games", "Apps", "Web Apps"]

# Windows has no FreeDesktop categories, so sections are guessed from names.
# First match wins.
SECTION_KEYWORDS = [
    ("Games", r"steam|epic games|xbox|minecraft|battle\.net|gog galaxy|ubisoft|\bea app\b|\bgame"),
    ("Development", r"visual studio|vs code|\bcode\b|python|\bidle\b|\bgit\b|github|node\.?js|docker|android studio|jetbrains|pycharm|intellij|webstorm|clion|rider|neovim|\bvim\b|sublime|notepad\+\+|postman|\bwsl\b|ubuntu|arch|qt |cmake|rust|cargo|java|\bsdk\b"),
    ("Graphics", r"photoshop|gimp|\bpaint\b|inkscape|blender|krita|figma|illustrator|lightroom|affinity|photos"),
    ("Internet", r"chrome|firefox|\bedge\b|browser|brave|opera|vivaldi|outlook|\bmail\b|thunderbird|discord|slack|teams|zoom|telegram|whatsapp|signal|skype|filezilla|putty|remote desktop|vpn"),
    ("Office", r"\bword\b|excel|powerpoint|onenote|\boffice\b|libreoffice|acrobat|\bpdf\b|calendar|notion|obsidian|access|publisher"),
    ("Multimedia", r"spotify|\bvlc\b|media|music|video|\bobs\b|audacity|movies|itunes|camera|clipchamp|player|recorder|sound"),
    ("System", r"settings|control panel|task manager|terminal|powershell|command prompt|\bcmd\b|registry|device manager|services|event viewer|windows tools|defender|security|resource monitor|disk|hwmonitor|cpu-z|gpu|driver|nvidia|amd |intel|administrative|system"),
    ("Utility", r"calculator|notepad|7-zip|winrar|zip|archive|clock|sticky|snipping|character map|clipboard|magnifier|everything|powertoys|files|explorer"),
]
SKIP_NAME_RE = re.compile(r"uninstall|readme|release notes|documentation|\bhelp\b|license|website|manual", re.I)


# --------------------------------------------------------------------------- #
# Config / web apps
# --------------------------------------------------------------------------- #
def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "item"


def normalize_web_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name, url = str(raw.get("name") or ""), str(raw.get("url") or "")
    if len(name) > MAX_NAME_LENGTH or len(url) > MAX_URL_LENGTH:
        return None
    name, url = name.strip(), url.strip()
    if not name or not url:
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    return {"appId": "web." + slugify(name), "name": name, "subtext": "Web",
            "url": url, "kind": "web", "section": "Web Apps"}


def load_web_apps() -> list[dict]:
    try:
        if WEB_APPS_FILE.stat().st_size > MAX_CONFIG_BYTES:
            return []
        data = json.loads(WEB_APPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    source = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
    if not isinstance(source, list) or len(source) > MAX_WEB_ITEMS:
        return []
    out, seen = [], set()
    for raw in source:
        item = normalize_web_item(raw)
        if item and item["appId"] not in seen:
            seen.add(item["appId"])
            out.append(item)
    return out


def save_web_apps(apps: list[dict]) -> None:
    items = [{"name": a["name"], "url": a["url"]} for a in apps[:MAX_WEB_ITEMS]]
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        WEB_APPS_FILE.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
    except OSError as e:
        print("could not save web apps:", e, file=sys.stderr)


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- #
# App discovery
# --------------------------------------------------------------------------- #
def section_for(name: str, folder: str = "") -> str:
    hay = f"{name} {folder}"
    for title, pattern in SECTION_KEYWORDS:
        if re.search(pattern, hay, re.I):
            return title
    return "Apps"


def scan_start_menu() -> dict[str, dict]:
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    apps: dict[str, dict] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.lnk"):
            name = p.stem
            if SKIP_NAME_RE.search(name):
                continue
            rel = p.parent.relative_to(root)
            folder = "" if str(rel) == "." else rel.parts[0]
            apps.setdefault(name.lower(), {
                "appId": "lnk:" + str(p), "name": name[:MAX_NAME_LENGTH],
                "subtext": folder, "path": str(p), "kind": "lnk",
                "section": section_for(name, folder),
            })
    return apps


def scan_packaged_apps() -> dict[str, dict]:
    """Store/UWP apps (Calculator, Terminal, Settings, ...) via Get-StartApps."""
    if not IS_WIN:
        return {}
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
           "Get-StartApps | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=25, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        data = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    except Exception:
        return {}
    if isinstance(data, dict):
        data = [data]
    apps: dict[str, dict] = {}
    for d in data:
        name, app_id = str(d.get("Name") or ""), str(d.get("AppID") or "")
        if not name or "!" not in app_id or SKIP_NAME_RE.search(name):
            continue
        apps[name.lower()] = {
            "appId": "uwp:" + app_id, "name": name[:MAX_NAME_LENGTH], "subtext": "",
            "path": "", "aumid": app_id, "kind": "uwp", "section": section_for(name),
        }
    return apps


class ScanThread(QThread):
    done = pyqtSignal(list)

    def run(self):
        apps = scan_packaged_apps()
        apps.update(scan_start_menu())          # .lnk wins (has real icon)
        self.done.emit(sorted(apps.values(), key=lambda a: a["name"].lower()))


def launch_native(app: dict) -> None:
    try:
        if app["kind"] == "lnk":
            os.startfile(app["path"])  # type: ignore[attr-defined]
        elif app["kind"] == "uwp":
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app["aumid"]])
    except OSError as e:
        print("launch failed:", e, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Filtering / grouping
# --------------------------------------------------------------------------- #
def filter_apps(apps: list[dict], query: str) -> list[dict]:
    tokens = query.strip().lower().split()
    if not tokens:
        return apps
    out = []
    for a in apps:
        hay = " ".join(str(a.get(k, "")) for k in ("name", "subtext", "appId", "section", "url")).lower()
        if all(t in hay for t in tokens):
            out.append(a)
    return out


def build_sections(apps: list[dict]) -> list[tuple[str, list[dict]]]:
    buckets: dict[str, list[dict]] = {t: [] for t in SECTION_ORDER}
    for a in apps:
        buckets.setdefault(a.get("section") or "Apps", []).append(a)
    return [(t, buckets[t]) for t in SECTION_ORDER if buckets[t]]


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #
class Row(QWidget):
    activated = pyqtSignal(dict)
    removed = pyqtSignal(dict)
    hovered = pyqtSignal(dict)

    def __init__(self, app: dict, icon: QIcon | None, dot: str):
        super().__init__()
        self.app, self.icon, self.dot = app, icon, QColor(dot)
        self.selected = False
        self._hover = False
        self._minus_hover = False
        self.setFixedHeight(28)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, v: bool):
        if v != self.selected:
            self.selected = v
            self.update()

    def _minus_rect(self) -> QRect:
        return QRect(self.width() - 22, 5, 18, 18)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self.selected:
            p.setBrush(QColor(124, 106, 247, 51))
        elif self._hover:
            p.setBrush(QColor(C_HOVER))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)

        icon_rect = QRect(6, 6, 16, 16)
        if self.icon is not None and not self.icon.isNull():
            self.icon.paint(p, icon_rect)
        else:
            p.setBrush(self.dot)
            p.drawRoundedRect(QRectF(icon_rect), 3, 3)

        is_web = self.app["kind"] == "web"
        right = self.width() - (26 if is_web else 8)
        font = QFont()
        font.setFamilies([f.strip() for f in FONT_FAMILY.split(",")])
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(QColor(C_TEXT if (self.selected or self._hover) else C_MUTED))
        text = QFontMetrics(font).elidedText(self.app["name"], Qt.TextElideMode.ElideRight, right - 30)
        p.drawText(QRect(30, 0, right - 30, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        if is_web:
            r = self._minus_rect()
            if self._minus_hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(248, 113, 113, 51))
                p.drawRoundedRect(QRectF(r), 4, 4)
            p.setPen(QColor(C_DANGER if self._minus_hover else C_MUTED))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "−")

    def enterEvent(self, e):
        self._hover = True
        self.hovered.emit(self.app)
        self.update()

    def leaveEvent(self, e):
        self._hover = self._minus_hover = False
        self.update()

    def mouseMoveEvent(self, e):
        if self.app["kind"] == "web":
            over = self._minus_rect().contains(e.position().toPoint())
            if over != self._minus_hover:
                self._minus_hover = over
                self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.app["kind"] == "web" and self._minus_rect().contains(e.position().toPoint()):
            self.removed.emit(self.app)
        else:
            self.activated.emit(self.app)


class AddDialog(QFrame):
    submitted = pyqtSignal(str, str)
    cancelled = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(f"""
            AddDialog {{ background:#0c0c0e; border:1px solid {C_BORDER}; border-radius:14px; }}
            QLabel {{ color:{C_MUTED}; font-size:11px; }}
            QLineEdit {{ background:#121216; color:{C_TEXT}; border:1px solid {C_BORDER};
                         border-radius:8px; padding:8px 10px; font-size:13px; }}
            QLineEdit:focus {{ border-color:{C_ACCENT}; }}
            QPushButton {{ border:1px solid {C_BORDER}; border-radius:8px; color:{C_MUTED};
                           background:transparent; padding:8px 0; font-size:13px; }}
            QPushButton:hover {{ background:{C_HOVER}; }}
            QPushButton#add {{ background:{C_ACCENT}; color:white; border:none; font-weight:600; }}
            QPushButton#add:disabled {{ background:{C_HOVER}; color:#777; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        head = QLabel("Add Web App")
        head.setStyleSheet(f"color:{C_TEXT}; font-size:16px; font-weight:600;")
        lay.addWidget(head)
        lay.addWidget(QLabel("Title"))
        self.title = QLineEdit(maxLength=MAX_NAME_LENGTH)
        lay.addWidget(self.title)
        lay.addWidget(QLabel("URL"))
        self.url = QLineEdit(maxLength=MAX_URL_LENGTH)
        lay.addWidget(self.url)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFixedWidth(88)
        self.add = QPushButton("Add")
        self.add.setObjectName("add")
        self.add.setFixedWidth(88)
        row.addWidget(cancel)
        row.addWidget(self.add)
        lay.addLayout(row)
        self.title.returnPressed.connect(self.url.setFocus)
        self.url.returnPressed.connect(self._submit)
        self.title.textChanged.connect(self._validate)
        self.url.textChanged.connect(self._validate)
        cancel.clicked.connect(self.cancelled.emit)
        self.add.clicked.connect(self._submit)
        self._validate()

    def _validate(self):
        self.add.setEnabled(bool(self.title.text().strip() and self.url.text().strip()))

    def _submit(self):
        if self.add.isEnabled():
            self.submitted.emit(self.title.text().strip(), self.url.text().strip())

    def reset(self):
        self.title.clear()
        self.url.clear()
        self.title.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(e)


class Launcher(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("Launcher { background:#000; }")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.native_apps: list[dict] = []
        self.web_apps: list[dict] = load_web_apps()
        self.filtered: list[dict] = []
        self.rows: list[Row] = []
        self.selected = 0
        self.icon_cache: dict[str, QIcon] = {}
        self.icon_provider = QFileIconProvider()
        self.scan_thread: ScanThread | None = None
        self.last_scan = 0.0
        self.shown_at = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 32)
        outer.setSpacing(20)

        head = QVBoxLayout()
        head.setSpacing(4)
        title = QLabel("Apps")
        title.setStyleSheet(f"color:{C_TEXT}; font:600 26px '{FONT_FAMILY.split(',')[0]}';")
        self.count = QLabel("")
        self.count.setStyleSheet(f"color:{C_MUTED}; font-size:13px;")
        head.addWidget(title)
        head.addWidget(self.count)
        outer.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter apps…")
        self.search.setFixedHeight(34)
        self.search.setStyleSheet(f"""
            QLineEdit {{ background:#000; color:{C_TEXT}; border:1px solid {C_BORDER};
                         border-radius:8px; padding:0 12px; font-size:13px; }}
            QLineEdit:focus {{ border-color:{C_ACCENT}; }}
        """)
        self.search.textChanged.connect(self.apply_filter)
        self.search.installEventFilter(self)
        outer.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; }}
            QScrollBar:vertical {{ background:transparent; width:6px; }}
            QScrollBar::handle:vertical {{ background:{C_BORDER}; border-radius:3px; min-height:30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
        """)
        outer.addWidget(self.scroll, 1)

        hint = QLabel("↑↓ navigate  ·  Enter launch  ·  Esc close")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color:{C_MUTED}; font-size:11px;")
        outer.addWidget(hint)

        self.fab = QPushButton("+", self)
        self.fab.setFixedSize(48, 48)
        self.fab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fab.setStyleSheet(f"QPushButton {{ background:{C_ACCENT}; color:white; border:none; "
                               f"border-radius:24px; font-size:26px; font-weight:600; }}"
                               f"QPushButton:hover {{ background:#9081f9; }}")
        self.fab.clicked.connect(self.open_add_dialog)

        self.dim = QWidget(self)
        self.dim.setStyleSheet("background: rgba(0,0,0,166);")
        self.dim.hide()
        self.dialog = AddDialog(self.dim)
        self.dialog.setFixedWidth(420)
        self.dialog.submitted.connect(self.add_web_app)
        self.dialog.cancelled.connect(self.close_add_dialog)

        self.refresh_apps()

    # -- discovery ---------------------------------------------------------
    def start_scan(self):
        if self.scan_thread is not None and self.scan_thread.isRunning():
            return
        self.scan_thread = ScanThread()
        self.scan_thread.done.connect(self._scan_done)
        self.scan_thread.start()

    def _scan_done(self, apps: list):
        self.native_apps = apps
        self.last_scan = time.monotonic()
        self.refresh_apps()

    def all_apps(self) -> list[dict]:
        return self.native_apps + self.web_apps

    def refresh_apps(self):
        self.apply_filter()

    def apply_filter(self, *_):
        self.filtered = filter_apps(self.all_apps(), self.search.text())
        self.selected = min(self.selected, max(0, len(self.filtered) - 1))
        self.count.setText(f"{len(self.filtered)} items")
        self.rebuild()

    def icon_for(self, app: dict) -> QIcon | None:
        path = app.get("path")
        if not path:
            return None
        if path not in self.icon_cache:
            self.icon_cache[path] = self.icon_provider.icon(QFileInfo(path))
        return self.icon_cache[path]

    # -- layout ------------------------------------------------------------
    def rebuild(self):
        self.setUpdatesEnabled(False)
        content = QWidget()
        cols_layout = QHBoxLayout(content)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(0)
        sections = build_sections(self.filtered)
        ncols = max(2, min(4, self.scroll.viewport().width() // 220 or 2))
        columns = [QVBoxLayout() for _ in range(ncols)]
        heights = [0] * ncols
        for c in columns:
            c.setContentsMargins(14, 12, 14, 12)
            c.setSpacing(1)
            cols_layout.addLayout(c, 1)
        self.rows = []
        flat_index = {a["appId"]: i for i, a in enumerate(self.filtered)}
        dot_i = 0
        # keep flat row order == self.filtered order for keyboard nav
        row_by_id: dict[str, Row] = {}
        for title, apps in sections:
            k = heights.index(min(heights))
            col = columns[k]
            label = QLabel(title)
            label.setStyleSheet(f"color:{C_TEXT}; font-size:13px; font-weight:600; padding-bottom:6px;")
            col.addWidget(label)
            for a in apps:
                row = Row(a, self.icon_for(a), DOT_PALETTE[dot_i % len(DOT_PALETTE)])
                dot_i += 1
                row.activated.connect(self.launch)
                row.removed.connect(self.remove_web_app)
                row.hovered.connect(self.on_hover)
                col.addWidget(row)
                row_by_id[a["appId"]] = row
            col.addSpacing(18)
            heights[k] += len(apps) + 2
        for c in columns:
            c.addStretch(1)
        # rows in navigation order (grouped by section, as displayed)
        display_order = [a for _, apps in sections for a in apps]
        self.filtered = display_order
        self.rows = [row_by_id[a["appId"]] for a in display_order]
        self.scroll.setWidget(content)
        self.setUpdatesEnabled(True)
        self.selected = min(self.selected, max(0, len(self.rows) - 1))
        self.update_selection()

    def update_selection(self, scroll=False):
        for i, r in enumerate(self.rows):
            r.set_selected(i == self.selected)
        if scroll and self.rows:
            self.scroll.ensureVisible(0, self.rows[self.selected].mapTo(self.scroll.widget(), QPoint(0, 0)).y(), 0, 60)

    def on_hover(self, app: dict):
        for i, a in enumerate(self.filtered):
            if a["appId"] == app["appId"]:
                self.selected = i
                self.update_selection()
                return

    def move_selection(self, delta: int):
        n = len(self.rows)
        if n:
            self.selected = (self.selected + delta) % n
            self.update_selection(scroll=True)

    # -- actions -----------------------------------------------------------
    def launch(self, app: dict):
        if app["kind"] == "web":
            QDesktopServices.openUrl(QUrl(app["url"]))
        else:
            launch_native(app)
        self.dismiss()

    def launch_selected(self):
        if 0 <= self.selected < len(self.filtered):
            self.launch(self.filtered[self.selected])

    def add_web_app(self, name: str, url: str):
        item = normalize_web_item({"name": name, "url": url})
        if item:
            self.web_apps = [a for a in self.web_apps if a["appId"] != item["appId"]] + [item]
            save_web_apps(self.web_apps)
            self.apply_filter()
        self.close_add_dialog()

    def remove_web_app(self, app: dict):
        self.web_apps = [a for a in self.web_apps if a["appId"] != app["appId"]]
        save_web_apps(self.web_apps)
        self.apply_filter()

    def open_add_dialog(self):
        self.dim.setGeometry(self.rect())
        self.dim.raise_()
        self.dim.show()
        self.dialog.adjustSize()
        self.dialog.move((self.dim.width() - self.dialog.width()) // 2,
                         (self.dim.height() - self.dialog.height()) // 2)
        self.dialog.reset()

    def close_add_dialog(self):
        self.dim.hide()
        self.search.setFocus()

    # -- show / hide -------------------------------------------------------
    def toggle(self):
        self.dismiss() if self.isVisible() else self.present()

    def present(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.search.clear()
        self.selected = 0
        self.dim.hide()
        if time.monotonic() - self.last_scan > 60:
            self.start_scan()
        self.shown_at = time.monotonic()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        if IS_WIN:
            force_foreground(int(self.winId()))
        self.search.setFocus()
        self.apply_filter()

    def dismiss(self):
        self.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fab.move(self.width() - 76, self.height() - 76)
        self.dim.setGeometry(self.rect())
        if self.dim.isVisible():
            self.dialog.move((self.dim.width() - self.dialog.width()) // 2,
                             (self.dim.height() - self.dialog.height()) // 2)

    def changeEvent(self, e):
        if (e.type() == QEvent.Type.ActivationChange and self.isVisible()
                and not self.isActiveWindow() and time.monotonic() - self.shown_at > 0.6):
            self.dismiss()
        super().changeEvent(e)

    def mousePressEvent(self, e):
        self.dismiss()   # click on the empty backdrop closes, like the original

    def handle_key(self, e) -> bool:
        k = e.key()
        if k == Qt.Key.Key_Escape:
            if self.dim.isVisible():
                self.close_add_dialog()
            elif self.search.text():
                self.search.clear()
            else:
                self.dismiss()
        elif self.dim.isVisible():
            return False
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.move_selection(1)
        elif k in (Qt.Key.Key_Up, Qt.Key.Key_Backtab):
            self.move_selection(-1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.launch_selected()
        else:
            return False
        return True

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.Type.KeyPress and self.handle_key(ev):
            return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e):
        if not self.handle_key(e):
            super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
# Windows glue: foreground, hotkey, autostart
# --------------------------------------------------------------------------- #
def force_foreground(hwnd: int) -> None:
    """Windows blocks background apps from stealing focus; the ALT tap lifts that."""
    try:
        u = ctypes.windll.user32
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    mods = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8, "meta": 0x8}
    m, vk = 0, None
    for part in (p.strip().lower() for p in spec.split("+")):
        if part in mods:
            m |= mods[part]
        elif part == "space":
            vk = 0x20
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif re.fullmatch(r"f([1-9]|1[0-2])", part):
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    return (m, vk) if vk is not None and m else None


class HotkeyFilter(QAbstractNativeEventFilter):
    HOTKEY_ID = 0x4D4C  # "ML"

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False

    def register(self, spec: str) -> bool:
        parsed = parse_hotkey(spec)
        if not (IS_WIN and parsed):
            return False
        mods, vk = parsed
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.HOTKEY_ID, mods | 0x4000, vk))
        return self.registered

    def unregister(self):
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)

    def nativeEventFilter(self, event_type, message):
        if IS_WIN and event_type == b"windows_generic_MSG":
            import ctypes.wintypes as wt
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.HOTKEY_ID:  # WM_HOTKEY
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command() -> str:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else exe
    return f'"{exe}" "{Path(__file__).resolve()}" --background'


def startup_enabled() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "MinLauncher")
        return True
    except OSError:
        return False


def set_startup(enable: bool) -> None:
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, "MinLauncher", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, "MinLauncher")
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def make_app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(C_ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setBrush(QColor("white"))
    for x in (16, 34):
        for y in (16, 34):
            p.drawRoundedRect(x, y, 14, 14, 3, 3)
    p.end()
    return QIcon(pm)


def signal_running_instance(cmd: bytes) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(cmd)
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    args = set(sys.argv[1:])
    if "--install-startup" in args or "--uninstall-startup" in args:
        set_startup("--install-startup" in args)
        print("Startup entry", "added." if "--install-startup" in args else "removed.")
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if signal_running_instance(b"toggle" if "--toggle" in args or "--background" not in args else b"noop"):
        return 0

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    win = Launcher()
    win.start_scan()

    def on_connection():
        sock = server.nextPendingConnection()
        def read():
            if bytes(sock.readAll()).strip() == b"toggle":
                win.toggle()
        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)
    server.newConnection.connect(on_connection)

    hotkey = str(load_config().get("hotkey") or DEFAULT_HOTKEY)
    hk = HotkeyFilter(win.toggle)
    app.installNativeEventFilter(hk)
    hotkey_ok = hk.register(hotkey)
    app.aboutToQuit.connect(hk.unregister)

    tray = QSystemTrayIcon(make_app_icon(), app)
    tray.setToolTip(f"{APP_NAME} ({hotkey})" if hotkey_ok else APP_NAME)
    menu = QMenu()
    menu.addAction("Open", win.present)
    startup_action = QAction("Start with Windows", menu, checkable=True)
    startup_action.setChecked(startup_enabled())
    startup_action.toggled.connect(set_startup)
    menu.addAction(startup_action)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: win.toggle() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    app._keep = (server, hk, tray, menu, startup_action)  # keep references alive

    if IS_WIN and not hotkey_ok:
        tray.showMessage(APP_NAME, f"Could not register hotkey '{hotkey}' (in use or invalid). "
                         f"Edit {CONFIG_FILE} or use the tray icon.", QSystemTrayIcon.MessageIcon.Warning, 6000)

    if "--background" not in args:
        QTimer.singleShot(0, win.present)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
