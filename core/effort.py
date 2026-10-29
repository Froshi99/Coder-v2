"""Aufwand: wie gründlich der Agent arbeitet – ein Regler statt vieler Einzelschalter.

Vier Stufen, jede ändert dasselbe Bündel:
- Denkmodus bei Modellen, die denken können (qwen3, deepseek-r1, gpt-oss …): Niedrig nie, Mittel nach der Einstellung
  „Gedanken“, Hoch und Maximal immer. gpt-oss kennt eigene Stufen und bekommt sie direkt.
- Schrittlimit: halb, wie eingestellt, anderthalbfach, doppelt – auch für Sub-Agents.
- Kontrolle: Niedrig lässt sie aus, Maximal gibt ihr eine Nachbesserung mehr.
- Arbeitsweise im System-Prompt: kürzester Weg bis alles belegt. Mittel ändert nichts am Prompt – so bleibt der
  Prompt-Cache vom Stand vor dem Regler gültig.
"""

LEVELS = ("low", "medium", "high", "max")
LABEL = {"low": "Niedrig", "medium": "Mittel", "high": "Hoch", "max": "Maximal"}
HINT = {
    "low": "Schnell: nur das Nötigste lesen, kleinste Änderung, ohne Denkmodus und Kontrolle",
    "medium": "Ausgewogen: prüft, wenn es wenig kostet – wie bisher",
    "high": "Gründlich: liest mehr, denkt nach, testet jede Änderung",
    "max": "Alles: plant, sucht die Ursache, ergänzt Tests, Kontrolle mit einer Runde mehr",
}
# Deutsche und kurze Namen, wie man sie im Terminal tippt.
ALIASES = {"niedrig": "low", "gering": "low", "schnell": "low", "l": "low", "mittel": "medium", "normal": "medium",
           "m": "medium", "med": "medium", "hoch": "high", "gründlich": "high", "h": "high", "maximal": "max",
           "maximum": "max", "x": "max", "xhigh": "max"}
STEP_FACTOR = {"low": 0.5, "medium": 1.0, "high": 1.5, "max": 2.0}

PROMPT = {
    "low": """
# Effort: low
The user wants speed. Take the shortest path: only the exploration you really need, the smallest change that solves the request, no refactoring on the side. Verify only when it is quick. Answer in one or two sentences.
""",
    "medium": "",
    "high": """
# Effort: high
Work thoroughly. Read the related code and its callers before changing anything, handle edge cases and errors, and verify every change by running the tests, a build or the changed program. Review your own diff before you report.
""",
    "max": """
# Effort: maximum
Take all the care the task needs. Plan with todo_write. Find the root cause instead of patching symptoms and check related code for the same problem. Add or extend tests where the project has them and run them. Verify every change, review the full diff, and report exactly what you verified.
""",
}
CHAT_PROMPT = {
    "low": "\n# Effort: low\nAnswer briefly and directly. Look things up only when you cannot answer otherwise.\n",
    "medium": "",
    "high": "\n# Effort: high\nAnswer thoroughly. When you are not sure, check the facts in the files or on the web first.\n",
    "max": ("\n# Effort: maximum\nGive a complete, carefully checked answer. Verify facts in the files or on the web, "
            "compare alternatives and name trade-offs and sources.\n"),
}


def parse(text: str | None) -> str | None:
    """„hoch“, „High“, „h“ → high. Unbekanntes → None."""
    word = str(text or "").strip().lower()
    return word if word in LEVELS else ALIASES.get(word)


def level(cfg: dict) -> str:
    value = str(cfg.get("effort") or "medium")
    return value if value in LEVELS else "medium"


def steps(cfg: dict, base: int | None = None) -> int:
    """Schrittlimit auf dieser Stufe – base ist das eingestellte Limit (oder das eines Sub-Agents)."""
    base = int(cfg.get("max_steps") or 50) if base is None else int(base)
    return max(5, round(base * STEP_FACTOR[level(cfg)]))


def think(cfg: dict, caps, model: str = ""):
    """Wert für Ollamas think: None bei Modellen ohne Denkmodus, bei gpt-oss eine Stufe, sonst an oder aus."""
    if "thinking" not in (caps or ()):
        return None
    lvl = level(cfg)
    if str(model).lower().startswith("gpt-oss"):
        # gpt-oss denkt immer; abschalten geht nicht, nur die Tiefe wählen.
        return {"low": "low", "medium": "medium"}.get(lvl, "high")
    if lvl == "low":
        return False
    if lvl == "medium":
        return bool(cfg.get("think"))
    return True


def controller_on(cfg: dict) -> bool:
    return bool(cfg.get("controller", True)) and level(cfg) != "low"


def controller_rounds(cfg: dict) -> int:
    rounds = int(cfg.get("controller_rounds", 2))
    return rounds + 1 if level(cfg) == "max" else rounds


def prompt(cfg: dict, chat: bool = False) -> str:
    return (CHAT_PROMPT if chat else PROMPT)[level(cfg)]
