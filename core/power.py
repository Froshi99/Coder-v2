"""Hält den PC wach – ohne Energieoptionen zu ändern.

Einstellung keep_awake: „open“ – solange Coder offen ist, „work“ – nur während der Agent arbeitet, „off“ – nie.
Verhindert wird nur der Standby; der Bildschirm darf trotzdem ausgehen.

Windows: SetThreadExecutionState ist eine Anforderung dieses Prozesses; sie endet mit dem Freigeben oder spätestens
mit Coder. Wichtig: Anfordern und Freigeben müssen im selben Thread passieren – bei Coder ist das die Event-Loop.
macOS: caffeinate läuft so lange mit.
"""

import platform
import subprocess
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
MODES = ("open", "work", "off")


def mode(value) -> str:
    """Die Einstellung als Modus – das frühere An/Aus zählt als „open“ bzw. „off“."""
    if value is True:
        return "open"
    if value is False or value is None:
        return "off"
    text = str(value).strip().lower()
    return text if text in MODES else "open"


class KeepAwake:
    def __init__(self):
        self._users = 0
        self._held = False
        self._lock = threading.Lock()
        self._caffeinate: subprocess.Popen | None = None

    @property
    def active(self) -> bool:
        return self._users > 0

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> None:
        with self._lock:
            self._users += 1
            if self._users == 1:
                self._apply(True)

    def release(self) -> None:
        with self._lock:
            if not self._users:
                return
            self._users -= 1
            if not self._users:
                self._apply(False)

    def hold(self, on: bool) -> None:
        """Dauerhafte Anforderung, solange Coder offen ist. Wiederholtes Ein- oder Ausschalten schadet nicht."""
        if on and not self._held:
            self._held = True
            self.acquire()
        elif not on and self._held:
            self._held = False
            self.release()

    def _apply(self, on: bool) -> bool:
        try:
            if platform.system() == "Windows":
                import ctypes
                flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
                return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
            if platform.system() == "Darwin":
                if on and self._caffeinate is None:
                    self._caffeinate = subprocess.Popen(["caffeinate", "-i"])
                elif not on and self._caffeinate is not None:
                    self._caffeinate.terminate()
                    self._caffeinate = None
                return True
        except (OSError, AttributeError):
            pass
        return False


keep_awake = KeepAwake()
