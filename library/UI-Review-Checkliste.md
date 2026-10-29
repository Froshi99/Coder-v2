---
tags: [design, bibliothek, review]
aliases: [Design-Review, UI-Checkliste]
---
Vor dem Abschluss einer Oberfläche Punkt für Punkt durchgehen.

## Struktur
- [ ] Ist auf den ersten Blick klar, worum es geht und was die wichtigste Aktion ist?
- [ ] Gibt es pro Ansicht genau einen primären Button?
- [ ] Gruppieren Abstände Zusammengehöriges – ohne unnötige Rahmen und Karten?

## Typografie und Farbe
- [ ] Höchstens fünf bis sechs Schriftgrößen, konsistente Gewichte? ([[Typografie]])
- [ ] Eine Akzentfarbe, nur für Interaktion und Auswahl? ([[Farbe]])
- [ ] Alle Texte mit Kontrast ≥ 4,5 : 1 – auch im dunklen Design?

## Zustände
- [ ] Leer, lädt, Fehler, deaktiviert, sehr lange Inhalte, sehr viele Einträge? ([[Komponenten]])
- [ ] Hover, gedrückt und Tastaturfokus sichtbar?

## Layout
- [ ] Alles auf dem Abstandsraster, Kanten fluchten? ([[Layout und Abstände]])
- [ ] Funktioniert es bei 360 px und bei 1920 px Breite, ohne horizontales Scrollen?

## Zugänglichkeit
- [ ] Vollständig per Tastatur bedienbar, sinnvolle Tab-Reihenfolge? ([[Barrierefreiheit]])
- [ ] Icon-Buttons beschriftet, Bilder mit alt, Felder mit Label?
- [ ] `prefers-reduced-motion` berücksichtigt? ([[Bewegung]])

## Eigenständigkeit
- [ ] Nichts aus [[Kein AI-Slop]]: keine Deko-Verläufe, Emoji-Icons, Glow oder Floskeln?
- [ ] Texte konkret und kurz?
