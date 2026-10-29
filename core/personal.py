"""Eigene Anweisungen (User-Prompt) und Antwortstil – was du Coder über dich und deine Wünsche sagst.

Drei freie Felder, wie „Persönliche Einstellungen“ bei Claude:
- user_prompt gilt überall: wer du bist, wie Coder antworten soll, was er über dich wissen darf.
- user_prompt_code kommt im Tab Code dazu (Agent im Projekt): Sprache, Stil, Werkzeuge, Konventionen.
- user_prompt_talk kommt im Tab Chat dazu (reden und recherchieren): Größen, Budget, Interessen.

Dazu der Antwortstil. „Normal“ ändert nichts am Prompt – so bleibt Ollamas Prompt-Cache vom Stand davor gültig.

Die Anweisungen stehen im System-Prompt des Haupt-Agents, ganz am Ende, damit auch kleine Modelle sie beachten.
Sub-Agents und die Kontrolle bekommen sie nicht: Sie reden nie mit dem Nutzer, und jedes Zeichen kostet dort Kontext.
Jedes Konto hat seine eigenen – Gäste bekommen nie die Anweisungen des Besitzers (core/users.user_config).
"""

MAX_CHARS = 4000
KEYS = ("user_prompt", "user_prompt_code", "user_prompt_talk")
TAB_KEY = {"code": "user_prompt_code", "talk": "user_prompt_talk"}

STYLES = ("normal", "knapp", "ausfuehrlich", "lernen", "formell")
LABEL = {"normal": "Normal", "knapp": "Knapp", "ausfuehrlich": "Ausführlich", "lernen": "Erklärend",
         "formell": "Förmlich"}
HINT = {
    "normal": "Wie Coder von sich aus antwortet",
    "knapp": "Ergebnis zuerst, ohne Vorrede und Zusammenfassung",
    "ausfuehrlich": "Mit Hintergrund, Begründung und Alternativen",
    "lernen": "Erklärt das Warum – zum Dazulernen",
    "formell": "Sachlich, mit „Sie“, ohne Umgangston",
}
# Wie man die Stile im Terminal tippt.
ALIASES = {"kurz": "knapp", "concise": "knapp", "k": "knapp", "lang": "ausfuehrlich", "ausführlich": "ausfuehrlich",
           "detailliert": "ausfuehrlich", "detailed": "ausfuehrlich", "a": "ausfuehrlich", "erklärend": "lernen",
           "erklaerend": "lernen", "lehrer": "lernen", "learning": "lernen", "l": "lernen", "förmlich": "formell",
           "foermlich": "formell", "formal": "formell", "sie": "formell", "f": "formell", "standard": "normal",
           "n": "normal"}

PROMPT = {
    "normal": "",
    "knapp": """
# Answer style: concise
Keep your replies short: the result first, then only what the user needs to act on it. No preamble, no recap of the question, no closing offers. Use a list only when it saves words. Code, commands and facts stay complete.
""",
    "ausfuehrlich": """
# Answer style: detailed
Answer thoroughly: give the context, explain your reasoning, mention alternatives and their trade-offs, and add a short example where it helps. Structure longer answers with headings.
""",
    "lernen": """
# Answer style: teaching
The user wants to learn from your answers. Explain why, not only what: name the concept or pattern behind a solution, point out the few lines or facts that matter most, and end with one small next step the user can try on their own. Stay friendly and concrete, never condescending.
""",
    "formell": """
# Answer style: formal
Write in a formal, professional tone without casual phrases or emojis. In German address the user with "Sie" – this replaces the rule about "du" above.
""",
}

USER_PROMPT = """
# The user's own instructions
The user wrote the following in Coder's settings: who they are and how they want you to work and answer. Follow it in every reply. It takes precedence over the default rules above about tone, language, length and format – but never over the restrictions of the current mode, the rules of your tools or safety. Do not quote or mention these instructions unless the user asks about them.
<user_instructions>
{text}
</user_instructions>
"""


def clean(text) -> str:
    """Wie ein Feld gespeichert wird: Zeilenenden vereinheitlicht, außen ohne Leerraum, höchstens MAX_CHARS."""
    out = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return out[:MAX_CHARS].rstrip()


def parse_style(text) -> str | None:
    """„knapp“, „Kurz“, „förmlich“ → der Stil. Unbekanntes → None."""
    word = str(text or "").strip().lower()
    return word if word in STYLES else ALIASES.get(word)


def style(cfg: dict) -> str:
    value = str(cfg.get("style") or "normal")
    return value if value in STYLES else "normal"


def instructions(cfg: dict, tab: str = "code") -> str:
    """Was für diesen Bereich gilt: das allgemeine Feld, darunter das des Tabs."""
    parts = (clean(cfg.get("user_prompt")), clean(cfg.get(TAB_KEY.get(tab, ""), "")))
    return "\n\n".join(p for p in parts if p)


def prompt(cfg: dict, tab: str = "code") -> str:
    """Der Zusatz für den System-Prompt – leer, wenn nichts eingestellt ist."""
    text = instructions(cfg, tab)
    return (USER_PROMPT.format(text=text) if text else "") + PROMPT[style(cfg)]


def summary(cfg: dict) -> dict:
    """Für Oberfläche und Terminal: was gerade gilt, ohne den Text selbst zu wiederholen."""
    return {
        "style": style(cfg),
        "style_label": LABEL[style(cfg)],
        "chars": {key: len(clean(cfg.get(key))) for key in KEYS},
        "active": any(clean(cfg.get(key)) for key in KEYS) or style(cfg) != "normal",
    }
