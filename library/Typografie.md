---
tags: [design, bibliothek]
aliases: [Schrift, Schriften, Type]
---
Typografie trägt den größten Teil eines Interfaces. Wer sie beherrscht, braucht kaum Dekoration.

## Schriften
- **System-Stack für Apps:** `system-ui, -apple-system, "Segoe UI Variable", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` – schnell, vertraut, sauber gerendert.
- **Code und Zahlenkolonnen:** `ui-monospace, "Cascadia Code", "SF Mono", "JetBrains Mono", Consolas, monospace`.
- Höchstens zwei Familien. Eine eigene Schrift nur, wenn sie Charakter bringt (Marke, Editorial) – dann sparsam, meist nur für Überschriften.
- Webfonts: `font-display: swap`, nur benötigte Schnitte laden, variable Fonts bevorzugen, immer mit Fallback-Stack.

## Größen
- **Apps:** 12 · 13 · 14 · 16 · 20 · 24 px. Fließtext 14–15 px, längere Texte 16–18 px.
- **Marketing und Editorial:** modulare Skala, etwa Faktor 1,25: 16 · 20 · 25 · 31 · 39 · 49 px. Große Überschriften mit `clamp()` fließend skalieren.
- Fünf bis sechs Stufen reichen für ein ganzes Produkt.

## Zeilen
- Zeilenlänge 45–75 Zeichen (`max-width: 65ch`).
- Zeilenhöhe: Fließtext 1,5–1,6 · UI-Text 1,3–1,45 · große Überschriften 1,05–1,2.
- Absätze mit Abstand trennen, nicht mit Einzug.

## Gewicht, Laufweite, Details
- Gewichte: 400 für Text, 500–600 für Beschriftungen und Buttons, 600–700 für Überschriften. Kein 300 unter 16 px.
- Große Überschriften leicht enger (`letter-spacing: -0.01em` bis `-0.02em`), kleine Versal-Labels leicht weiter (`0.04em` bis `0.08em`).
- Messwerte und Tabellen: `font-variant-numeric: tabular-nums`.
- Echte Satzzeichen: „deutsche Anführungszeichen“, Gedankenstrich – statt Bindestrich, geschütztes Leerzeichen zwischen Zahl und Einheit.
- Hierarchie zuerst über Gewicht und Textfarbe aufbauen, erst dann über Größe.

## Textfarben
Drei Stufen genügen: primär, sekundär, tertiär – alle mit ausreichendem Kontrast (siehe [[Barrierefreiheit]]). Eine fertige Skala steht in [[Design-Tokens]].
