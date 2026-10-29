---
tags: [design, bibliothek]
aliases: [Layout, Abstände, Spacing, Raster, Responsive]
---
## Abstandsraster
- Basis 4 px: 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96. Keine Zwischenwerte wie 13 oder 22 px.
- **Nähe zeigt Zusammenhang:** Abstände innerhalb einer Gruppe deutlich kleiner als zwischen Gruppen, etwa 8 zu 24 px.
- Buttons und Eingaben: Höhe 32–40 px (Touch mindestens 44 px), horizontaler Innenabstand 12–16 px.

## Breiten und Raster
- Inhalt begrenzen: Textspalten etwa 65ch, App-Inhalte 960–1200 px, Formulare 400–560 px.
- Seiten: 12-Spalten-Raster. Apps: meist Seitenleiste (240–280 px) plus flexibler Inhalt.
- CSS Grid für zweidimensionale Layouts, Flexbox für Reihen. `gap` statt Außenabständen zwischen Geschwistern.

## Ausrichtung
- Alles richtet sich an wenigen Kanten aus. Linksbündig ist der Normalfall.
- Icons optisch zur Textzeile ausrichten, nicht nur rechnerisch.
- Zahlen in Tabellen rechtsbündig.

## Responsiv
- Von der schmalen Ansicht aus denken: eine Spalte, dann erweitern. Breakpoints nach Inhalt; typische Werte 640 · 768 · 1024 · 1280 px.
- Container Queries für Komponenten, die an verschiedenen Orten eingesetzt werden.
- Nichts scrollt horizontal außer Tabellen und Code – die in eigenen `overflow-x: auto`-Containern.
- Seitenränder auf dem Handy mindestens 16 px.

## Dichte
- Werkzeuge: kompakte Zeilen (32–40 px), feine Trennlinien, Tastaturbedienung.
- Inhalte und Marketing: großzügig, 64–120 px zwischen Abschnitten.

Siehe [[Design-Prinzipien]] und [[Komponenten]].
