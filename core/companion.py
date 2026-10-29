"""Companion fürs Terminal: ein Axolotl, das mitfiebert.

Es wohnt in ~/.coder/companion.json, heißt so, wie du es nennst, und kommentiert Tests, Fehler und das Urteil der
Kontrolle. Seine Sprüche kommen ohne Modellaufruf aus – es kostet keine Sekunde Rechenzeit.

Gezeichnet wird nur mit ASCII: In der alten Windows-Konsole haben Sonderzeichen unklare Breite und würden die Figur
verschieben. Die Kiemen bewegen sich zwischen zwei Bildern, die Augen blinzeln, und jede Stimmung hat ihr Gesicht.
In der Statuszeile steht dieselbe Figur als Miniatur.
"""

import json
import random
import time

from .config import HOME

PATH = HOME / "companion.json"
SPECIES = "Axolotl"
NAME = "Axo"
COLOR = "95"  # hellrosa, wie ein Axolotl
WIDTH = 16
FACE_ROW = 2

# Von vorn: flacher Kopf, links und rechts je drei Kiemenbüschel, darunter Körper und Schwanz.
# {L}/{R} sind die Augen, {M} der Mund. Zwei Bilder: die Kiemen wippen.
ART_FRAMES = [
    [
        "    .-------.",
        " \\\\/         \\//",
        " =|   {L}   {R}   |=",
        " //\\    {M}    /\\\\",
        "    '-------'",
        "     \\_____/",
    ],
    [
        "    .-------.",
        " //\\         /\\\\",
        " =|   {L}   {R}   |=",
        " \\\\/    {M}    \\//",
        "    '-------'",
        "     \\_____/",
    ],
]
MINI = ">({L}{M}{R})<"
# Augen links/rechts und Mund je Stimmung.
MOODS = {
    "idle": ("o", "o", "w"),
    "happy": ("^", "^", "w"),
    "think": ("o", "O", "~"),
    "work": (">", "<", "o"),
    "alert": ("O", "O", "o"),
    "ask": ("o", "O", "?"),
    "sad": ("x", "x", "n"),
    "sleep": ("-", "-", "z"),
    "proud": ("^", "^", "D"),
    "love": ("♥", "♥", "w"),
}
# Zeichen, die Consolas nicht hat – dort wird schlicht ersetzt.
BASIC_SWAP = {"♥": "*"}


def _plain(text: str, unicode_ok: bool) -> str:
    if unicode_ok:
        return text
    for bad, good in BASIC_SWAP.items():
        text = text.replace(bad, good)
    return text


LINES = {
    "hello": ["Na, was bauen wir heute?", "Bereit, wenn du es bist.", "*wedelt mit den Kiemen*",
              "Leg los – ich schau zu.", "Schön, dass du da bist!", "Der Code schläft nicht, ich auch nicht.",
              "Wasser warm, Kiemen frisch – los geht's."],
    "done": ["Fertig – {steps}, {time}.", "Erledigt in {time}.", "Geschafft! {steps}.", "Das war's. {time}.",
             "{steps} – und alles heil geblieben.", "Sitzt. {time}."],
    "long": ["Das war ein Brocken: {steps}, {time}.", "Puh. {time}. Aber es steht.",
             "Lange getaucht – {time}. Geschafft."],
    "answer": ["Gern geschehen.", "Hoffe, das hilft!", "Noch was?", "Sag Bescheid, wenn was fehlt."],
    "edit": ["Sauber editiert.", "Code angefasst – sieht gut aus.", "Datei geändert."],
    "tests_ok": ["Tests grün! *freudiges Blubbern*", "Alles grün. Herrlich.", "Tests bestanden.",
                 "Grün wie Algen. Weiter so."],
    "run_fail": ["Autsch, Exit {code}.", "Das knallte – wird schon.", "Rot. Nicht schlimm, das wächst nach.",
                 "Exit {code}. Kiemen hoch, weiter geht's."],
    "controller": ["{model} schaut drüber …", "Kontrolle läuft – Daumen drücken."],
    "verdict_done": ["Abgesegnet!", "Kontrolle sagt: passt.", "Geprüft und für gut befunden."],
    "verdict_continue": ["Da fehlt noch was – weiter geht's.", "Nachsitzen!", "Die Kontrolle ist streng. Gut so.",
                         "Fast. Noch eine Runde."],
    "ask": ["Brauch dein Okay.", "Darf ich?", "Kurz nachgefragt …"],
    "question": ["Da entscheidest besser du.", "Kurze Frage an dich.", "Zwei Wege – welcher?"],
    "plan": ["Plan steht. Umsetzen?", "So könnte es gehen.", "Erst denken, dann tippen."],
    "denied": ["Okay, lass ich.", "Verstanden, Kiemen weg.", "Finger weg, verstanden."],
    "cancel": ["Abgebrochen. Kein Ding.", "Gestoppt.", "Schon gut – Pause."],
    "error": ["Uff, das ging schief.", "Hoppla.", "Das war nichts. Nochmal?"],
    "watchdog": ["Das Modell hing – ich hab's neu gestartet.", "Kurz weggenickt, wieder da."],
    "recall": ["Mir fällt da was ein …", "Das hatten wir schon mal!", "Aus dem Gedächtnis gefischt."],
    "compact": ["Verlauf zusammengefasst – mehr Luft.", "Aufgeräumt. Das Wichtige bleibt."],
    "undo": ["Zurückgenommen. Als wäre nichts gewesen.", "Rückwärts geschwommen."],
    "image": ["Schönes Bild!", "Ich schau's mir an."],
    "pet": ["*blubb*", "Hehe, das kitzelt an den Kiemen!", "Mehr davon!", "*lächelt Axolotl-breit*"],
    "pet_often": ["Wir zwei, was?", "*schnurrt – geht das bei Axolotln?*", "Du bist mein Lieblingsmensch."],
    "pet_master": ["Ich würde für dich durch jeden Merge-Konflikt schwimmen.", "Beste Kiemenpflege im Umkreis.",
                   "*legt eine Kieme auf deine Hand*"],
    "bye": ["Bis bald!", "Tschüss – ich bewach den Code.", "Gute Nacht, Code.", "Mach's gut. Ich tauche ab."],
}
PET_TIERS = ((25, "pet_master"), (8, "pet_often"))


class Companion:
    def __init__(self, data: dict):
        self.data = data
        self._last: dict[str, str] = {}  # zuletzt gesagter Spruch je Ereignis – nichts zweimal hintereinander

    @property
    def name(self) -> str:
        return self.data.get("name") or NAME

    @property
    def species(self) -> str:
        return SPECIES

    @property
    def enabled(self) -> bool:
        return bool(self.data.get("enabled", True))

    @property
    def color(self) -> str:
        return COLOR

    @property
    def pets(self) -> int:
        return int(self.data.get("pets") or 0)

    @property
    def face_row(self) -> int:
        return FACE_ROW

    @classmethod
    def load(cls) -> "Companion":
        try:
            data = json.loads(PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("name"):
            # Frühere Versionen ließen Katzen, Eulen & Co. schlüpfen – Name und Streicheleinheiten ziehen mit um.
            buddy = cls({"name": str(data["name"])[:20], "species": SPECIES, "born": data.get("born") or time.time(),
                         "pets": int(data.get("pets") or 0), "enabled": data.get("enabled", True)})
            if data.get("species") != SPECIES or set(data) - set(buddy.data):
                buddy.save()
            return buddy
        buddy = cls.hatch()
        buddy.save()
        return buddy

    @classmethod
    def hatch(cls, name: str | None = None) -> "Companion":
        return cls({"name": name or NAME, "species": SPECIES, "born": time.time(), "pets": 0, "enabled": True})

    def save(self) -> None:
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ Gesicht

    def eyes(self, mood: str, tick: int = 0) -> tuple[str, str, str]:
        left, right, mouth = MOODS.get(mood, MOODS["idle"])
        if mood == "work":
            left, right = ("o", "o") if tick % 10 >= 5 else (left, right)  # schaut kurz auf
            mouth = "o" if tick % 6 < 3 else "O"  # atmet
        elif mood == "think" and (tick // 8) % 3 == 2:
            left, right = "O", "o"  # schaut zur anderen Seite
        elif mood == "sleep":
            mouth = "z" if tick % 8 < 4 else "Z"  # schnarcht leise
        if tick and tick % 30 in (0, 1) and mood not in ("sleep", "love", "sad"):
            left = right = "-"  # blinzeln
        return left, right, mouth

    def _fill(self, template: str, mood: str, tick: int, unicode_ok: bool = True) -> str:
        left, right, mouth = self.eyes(mood, tick)
        text = template.replace("{L}", left).replace("{R}", right).replace("{M}", mouth)
        return _plain(text, unicode_ok)

    def art(self, mood: str = "idle", tick: int = 0, unicode_ok: bool = True) -> list[str]:
        """Die ganze Figur. Bei Bewegung wippen die Kiemen – zwischen zwei Bildern."""
        frame = ART_FRAMES[1] if mood in ("work", "happy", "love", "proud") and (tick // 4) % 2 else ART_FRAMES[0]
        return [self._fill(line, mood, tick, unicode_ok).ljust(WIDTH) for line in frame]

    def face(self, mood: str = "idle", tick: int = 0, unicode_ok: bool = True) -> str:
        return self._fill(MINI, mood, tick, unicode_ok)

    # ------------------------------------------------------------------ Sprüche

    def line(self, event: str, **values) -> str:
        """Ein Spruch zum Ereignis – nie zweimal hintereinander derselbe."""
        if event == "pet":
            event = next((name for count, name in PET_TIERS if self.pets >= count), "pet")
        choices = LINES.get(event) or [""]
        if len(choices) > 1:
            choices = [c for c in choices if c != self._last.get(event)] or choices
        text = random.choice(choices)
        self._last[event] = text
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text

    def pet(self) -> None:
        self.data["pets"] = self.pets + 1
        self.save()
