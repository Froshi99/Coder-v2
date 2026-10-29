#!/usr/bin/env python3
"""Coder — lokaler Coding-Agent für Ollama.

    python coder.py                 Desktop-Fenster (PyQt6 WebEngine, sonst Browser)
    python coder.py --browser       Oberfläche im Standardbrowser
    python coder.py --serve         Nur Server (z. B. für Zugriff aus dem LAN mit --host 0.0.0.0)
    python coder.py cli             Agent direkt im Terminal
    python coder.py test            Testreihen laufen lassen
    python coder.py -w PFAD         Workspace festlegen
"""

import argparse
import asyncio
import platform
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def pick_port(host: str, preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind((host, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Kein freier Port gefunden")


def start_server(host: str, port: int):
    import uvicorn
    from server.app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(host), host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Server konnte nicht starten")
        time.sleep(0.05)
    return server, thread


def system_dark() -> bool | None:
    """Systemthema, damit das Fenster ohne Aufblitzen im richtigen Look startet. None = unbekannt."""
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            return None
    return None


def run_desktop(url: str) -> int:
    try:
        from PyQt6.QtCore import QObject, QUrl, pyqtSignal
        from PyQt6.QtGui import QColor, QDesktopServices
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow
    except ImportError:
        print("PyQt6-WebEngine nicht gefunden – öffne den Browser.")
        return run_browser(url)

    from core import folders

    home = QUrl(url)

    def open_external(target) -> bool:
        if target.scheme() not in ("http", "https", "mailto"):
            return False
        QDesktopServices.openUrl(target)
        return True

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, target, nav_type, is_main_frame):
            # Nur Coder selbst bleibt im Fenster. Ein Dev-Server auf localhost:5173 aus dem Chat öffnet im Browser,
            # statt die Oberfläche zu ersetzen; hineingezogene Dateien öffnen gar nicht.
            if target.host() == home.host() and target.port() == home.port():
                return super().acceptNavigationRequest(target, nav_type, is_main_frame)
            open_external(target)
            return False

        def createWindow(self, _type):
            return LinkCatcher(self.profile(), self)  # Links mit target="_blank" öffnet Qt sonst gar nicht

    class LinkCatcher(QWebEnginePage):
        def acceptNavigationRequest(self, target, nav_type, is_main_frame):
            if open_external(target):
                self.deleteLater()
            return False

    class FolderDialog(QObject):
        """Qt-Dialoge müssen im UI-Thread laufen – der Server ruft aber aus seinem eigenen Thread."""
        requested = pyqtSignal(str, str, object)

        def __init__(self, window):
            super().__init__()
            self.parent_window = window
            self.waiting: list[dict] = []
            self.requested.connect(self._show)

        def _show(self, start, title, reply):
            reply["path"] = QFileDialog.getExistingDirectory(self.parent_window, title, start) or None
            reply["done"].set()

        def __call__(self, start, title):
            reply = {"path": None, "done": threading.Event()}
            self.waiting.append(reply)
            self.requested.emit(start, title, reply)
            reply["done"].wait()
            self.waiting.remove(reply)
            return reply["path"]

        def release(self):
            for reply in self.waiting:
                reply["done"].set()

    app = QApplication(sys.argv)
    app.setApplicationName("Coder")
    # Grund der Farbthemen (hell, dunkel) – wie in web/styles.css, damit das Fenster schon beim Laden passt
    PALETTE_BG = {"nord": ("#eceff4", "#2e3440"), "solarized": ("#fdf6e3", "#002b36"),
                  "gruvbox": ("#fbf1c7", "#282828"), "github": ("#f6f8fa", "#0d1117"),
                  "catppuccin": ("#eff1f5", "#1e1e2e"), "tokyo": ("#e1e2e7", "#1a1b26"),
                  "rosepine": ("#faf4ed", "#191724"),
                  "oled": ("#ffffff", "#000000"), "kontrast": ("#ffffff", "#000000"),
                  "farbenblind": ("#f6f6f4", "#111110")}
    dark = system_dark()
    # Die eigene Wahl aus den Einstellungen geht dem Systemthema vor – auch für Fensterrahmen und Startfarbe.
    settings_design = settings_palette = ""
    try:
        from core import config as config_mod
        saved = config_mod.load()
        settings_design = str(saved.get("design") or "")
        settings_palette = str(saved.get("palette") or "")
        if saved.get("theme") in ("light", "dark"):
            dark = saved["theme"] == "dark"
    except Exception:  # noqa: BLE001 – ohne Einstellung bleibt es beim Systemthema
        pass

    win = QMainWindow()
    win.setWindowTitle("Coder")
    win.resize(1340, 880)
    win.setMinimumSize(420, 520)
    view = QWebEngineView()
    page = Page(view)
    # kein weißes Aufblitzen – mit Farbthema gleich in dessen Grundfarbe
    start_bg = PALETTE_BG.get(settings_palette, ("#f2f2f5", "#0c0c0e"))[1 if dark else 0]
    page.setBackgroundColor(QColor(start_bg))
    view.setPage(page)
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)  # „Kopieren“-Knöpfe
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
    dialog = FolderDialog(win)
    folders.set_native_dialog(dialog)
    app.aboutToQuit.connect(dialog.release)
    # Qt WebEngine übernimmt das Windows-Thema nicht zuverlässig – deshalb explizit übergeben.
    # Das Design kommt gleich mit, damit beim ersten Start im Fenster nichts in der anderen Variante aufblitzt.
    query = [] if dark is None else [f"theme={'dark' if dark else 'light'}"]
    if settings_design and settings_design != "ruhig":
        query.append(f"design={settings_design}")
    if settings_palette in PALETTE_BG:
        query.append(f"palette={settings_palette}")
    view.setUrl(QUrl(f"{url}?{'&'.join(query)}" if query else url))
    win.setCentralWidget(view)

    if platform.system() == "Windows" and dark:
        try:
            import ctypes
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(win.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
        except (OSError, AttributeError):
            pass

    win.show()
    return app.exec()


def run_browser(url: str) -> int:
    webbrowser.open(url)
    print(f"Coder läuft auf {url}  (Strg+C beendet)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Coder — lokaler Coding-Agent für Ollama")
    parser.add_argument("mode", nargs="?", choices=["app", "cli", "test"], default="app")
    parser.add_argument("-w", "--workspace", help="Projektordner")
    parser.add_argument("-m", "--model", help="Ollama-Modell")
    parser.add_argument("--browser", action="store_true", help="Im Browser statt im App-Fenster öffnen")
    parser.add_argument("--serve", action="store_true", help="Nur den Server starten")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args, rest = parser.parse_known_args()

    if args.mode == "test":  # übrige Argumente gehören dem Läufer: python coder.py test design -v
        import subprocess
        runner = ROOT / "tests" / "run.py"
        if not runner.is_file():
            parser.error("Die Testreihen fehlen – der Ordner tests/ ist nicht dabei.")
        # Eigener Prozess: „tests" gibt es in manchen Umgebungen auch als installiertes Paket.
        return subprocess.call([sys.executable, str(runner), *rest], cwd=str(ROOT))
    if rest:
        parser.error(f"Unbekannte Angabe: {' '.join(rest)}")

    from core import config

    changes = {}
    if args.workspace:
        ws = Path(args.workspace.strip().strip("\"'")).expanduser().resolve()
        if not ws.is_dir():
            parser.error(f"Workspace existiert nicht: {ws}")
        reason = config.blocked_workspace(ws)
        if reason:
            parser.error(f"{ws} geht nicht als Workspace ({reason})")
        changes["workspace"] = str(ws)
    if args.model:
        changes["model"] = args.model
    if changes:
        config.update(changes)

    if args.mode == "cli":
        from core.cli import run
        try:
            return asyncio.run(run())
        except KeyboardInterrupt:
            return 130

    port = pick_port(args.host, args.port)
    start_server(args.host, port)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{port}/"

    if args.serve:
        print(f"Coder-Server läuft auf {url}  (Strg+C beendet)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    return run_browser(url) if args.browser else run_desktop(url)


if __name__ == "__main__":
    sys.exit(main())
