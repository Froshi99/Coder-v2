"""Schleife: denselben Auftrag wieder und wieder – bis er sitzt, bis die Runden alle sind oder bis du stoppst.

    /loop 5m npm test und behebe, was rot ist     alle 5 Minuten, bis du stoppst
    /loop 3x /review                              dreimal hintereinander
    /loop bring die Tests zum Laufen              bis zu fünf Runden, endet früher, wenn nichts mehr zu tun ist
    /loop stop                                    Schluss

Damit die Schleife von allein endet, bekommt der Agent je Runde einen Zusatz: Ist nichts mehr zu tun, soll er
nur „LOOP-ENDE“ antworten. Coder liest das und hört auf – so läuft nichts endlos gegen eine fertige Aufgabe.
"""

import re
from dataclasses import dataclass, field

DEFAULT_ROUNDS = 5  # ohne Angabe: so oft höchstens
MAX_ROUNDS = 100
MAX_EVERY = 24 * 3600
STOP_WORD = "LOOP-ENDE"
STOP_RX = re.compile(r"\bloop[ _-]?ende\b", re.I)
# „5m", „30s", „2h" – oder „3x", „3×", „x3". Eine nackte Zahl zählt nicht: „/loop 3 Fehler beheben“ ist ein Auftrag.
EVERY_RX = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(s|sek|sec|m|min|h|std|stunden?|minuten?|sekunden?)$", re.I)
TIMES_RX = re.compile(r"^(?:(\d+)\s*[x×]|[x×]\s*(\d+))$", re.I)
UNIT = {"s": 1, "sek": 1, "sec": 1, "sekunde": 1, "sekunden": 1,
        "m": 60, "min": 60, "minute": 60, "minuten": 60,
        "h": 3600, "std": 3600, "stunde": 3600, "stunden": 3600}


class LoopError(ValueError):
    pass


@dataclass
class Loop:
    """Ein laufender Auftrag in Schleife."""

    task: str
    display: str = ""  # was im Chat steht, falls es vom Auftrag abweicht (/test statt des ausgeschriebenen Prompts)
    every: float | None = None  # Sekunden zwischen den Runden; None heißt: sofort weiter
    times: int | None = DEFAULT_ROUNDS  # Runden insgesamt; None heißt: bis du stoppst
    round: int = 0
    stopped_by: str = ""  # "user", "done", "rounds", "error"
    history: list = field(default_factory=list)

    @property
    def running(self) -> bool:
        return not self.stopped_by and (self.times is None or self.round < self.times)

    @property
    def label(self) -> str:
        where = f"Runde {self.round}" + (f" von {self.times}" if self.times else "")
        return where + (f" · alle {human(self.every)}" if self.every else "")

    def public(self) -> dict:
        return {"task": self.display or self.task, "round": self.round, "times": self.times,
                "every": self.every, "label": self.label}

    def prompt(self) -> str:
        """Der Auftrag für die nächste Runde, mit einem kurzen Hinweis auf die Schleife."""
        self.round += 1
        of = f" von {self.times}" if self.times else ""
        note = (f"[Schleife: Runde {self.round}{of}. Prüfe zuerst, was seit der letzten Runde offen ist, und mache "
                f"dort weiter. Ist die Aufgabe erledigt und nichts mehr zu tun, antworte nur mit {STOP_WORD}.]")
        return f"{self.task}\n\n{note}" if self.round > 1 else self.task

    def note(self, answer: str) -> None:
        """Nach jeder Runde: Hat der Agent Schluss gesagt?"""
        self.history.append(str(answer or "")[:200])
        if done(answer):
            self.stopped_by = "done"
        elif self.times is not None and self.round >= self.times:
            self.stopped_by = "rounds"

    def stop(self, why: str = "user") -> None:
        if not self.stopped_by:
            self.stopped_by = why

    @property
    def reason(self) -> str:
        return {"user": "abgebrochen", "done": "erledigt – der Agent hat nichts mehr gefunden",
                "rounds": "alle Runden durch", "error": "abgebrochen nach einem Fehler"}.get(self.stopped_by, "")


def done(answer: str) -> bool:
    """Der Agent sagt, dass nichts mehr zu tun ist – aber nur, wenn er es kurz macht und nicht bloß zitiert."""
    text = str(answer or "").strip()
    if not STOP_RX.search(text):
        return False
    return len(text) < 400 or bool(STOP_RX.search(text[-200:]))


def human(seconds: float | None) -> str:
    if not seconds:
        return "sofort"
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        value = seconds / 60
        return f"{value:.0f} min" if value == int(value) else f"{value:.1f} min"
    value = seconds / 3600
    return f"{value:.0f} h" if value == int(value) else f"{value:.1f} h"


def parse(rest: str) -> Loop:
    """„5m auftrag“, „3x auftrag“ oder nur „auftrag“ – alles andere wirft LoopError."""
    text = " ".join(str(rest or "").split())
    if not text:
        raise LoopError("So geht es: /loop 5m <auftrag>, /loop 3x <auftrag> oder /loop <auftrag>.")
    head, _, tail = text.partition(" ")
    every, times = None, DEFAULT_ROUNDS
    task = text
    hit = TIMES_RX.match(head)
    if hit:
        times = int(hit.group(1) or hit.group(2))
        task = tail.strip()
        if not 1 <= times <= MAX_ROUNDS:
            raise LoopError(f"Zwischen 1 und {MAX_ROUNDS} Runden.")
    else:
        span = EVERY_RX.match(head)
        if span:
            value = float(span.group(1).replace(",", "."))
            every = value * UNIT.get(span.group(2).lower(), 1)
            if not tail.strip():
                raise LoopError(f"Und was soll alle {human(every)} laufen? /loop {head} npm test")
            if not 5 <= every <= MAX_EVERY:
                raise LoopError("Der Abstand muss zwischen 5 Sekunden und 24 Stunden liegen.")
            times, task = None, tail.strip()
    if not task:
        raise LoopError("Und was soll in der Schleife laufen? /loop 5m npm test")
    return Loop(task=task, every=every, times=times)
