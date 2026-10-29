---
tags: [design, bibliothek]
aliases: [Farben, Farbsystem, Dark Mode, Dunkles Design]
---
## Aufbau eines Farbsystems
1. **Neutraltöne zuerst.** 10–12 Stufen von fast Weiß bis fast Schwarz, leicht getönt (warm, kühl oder mit einem Hauch der Akzentfarbe) statt reinem Grau.
2. **Eine Akzentfarbe** für Interaktion: primäre Buttons, Links, Fokus, Auswahl – nicht für Dekoration.
3. **Semantische Farben:** Erfolg, Warnung, Fehler, Info – jeweils als Text-, Flächen- und Randvariante.
4. **Rollen statt Werte benennen:** `--text`, `--text-muted`, `--surface`, `--border`, `--accent`. Siehe [[Design-Tokens]].

## Regeln
- Große Flächen neutral, sekundäre Flächen leicht abgesetzt, Akzent sparsam (grob 60 · 30 · 10).
- Kein reines Schwarz auf reinem Weiß für viel Text – ein sehr dunkles Grau auf Weiß liest sich ruhiger.
- Kontrast: Text ≥ 4,5 : 1, großer Text und Bedienelemente ≥ 3 : 1.
- Status nie nur über Farbe zeigen – immer zusätzlich Icon oder Text.
- OKLCH (`oklch(55% 0.14 265)`) liefert gleichmäßigere Helligkeitsstufen als HSL.
- Verläufe nur, wenn sie etwas bedeuten (Skala, Tiefe) – nie als Ersatz für eine Idee. Siehe [[Kein AI-Slop]].
- Die Akzentfarbe aus dem Projekt ableiten (Logo, Branche, Inhalt) statt eine Framework-Standardfarbe zu nehmen.

## Dunkles Design
- Nicht invertieren. Hintergrund sehr dunkles Grau, kein reines Schwarz – außer bei bewusstem OLED-Look.
- Ebenen werden nach oben heller, statt mit Schatten abgesetzt zu werden.
- Akzentfarben heller und etwas weniger gesättigt als im hellen Design.
- Haupttext leicht gedimmt (etwa 90 % Weiß), Sekundärtext etwa 60 %.
- `prefers-color-scheme` respektieren und einen manuellen Umschalter anbieten.
