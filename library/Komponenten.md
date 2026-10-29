---
tags: [design, bibliothek]
aliases: [Components, Bausteine, Zustände]
---
Jede Komponente braucht alle Zustände: **normal · Hover · gedrückt · Tastaturfokus · deaktiviert · lädt · Fehler**.

## Buttons
- Hierarchie: ein **primärer** Button pro Ansicht (Akzentfarbe), sekundäre neutral mit Fläche oder Rand, tertiäre als reiner Text.
- Beschriftung als Verb: „Speichern“, „Datei hochladen“ – nicht „OK“ oder „Absenden“.
- Destruktive Aktionen rot und mit Bestätigung oder Rückgängig.
- Beim Laden die Breite halten, Spinner zeigen, erneutes Klicken verhindern.

## Eingaben
- Label immer sichtbar über dem Feld – ein Placeholder ist kein Label.
- Fehler direkt am Feld und konkret: „Mindestens 8 Zeichen“ statt „Ungültige Eingabe“.
- Passende Typen und Attribute: `type="email"`, `inputmode="numeric"`, `autocomplete`.

## Listen und Tabellen
- Ganze Zeile klickbar, wenn sie eine Aktion hat; Hover-Fläche als Rückmeldung.
- Tabellen: Kopfzeile fixiert, Zahlen rechtsbündig und tabellarisch, Sortierung sichtbar.
- Lange Texte mit `text-overflow: ellipsis` kürzen, den vollen Wert im `title`.

## Leere Zustände
Erklären, was hier erscheinen wird, und die eine nächste Aktion anbieten. Eine Illustration braucht es dafür nicht.

## Rückmeldung
- Toasts für kurze Bestätigungen (3–5 s) – nicht für Fehler, die man lesen muss.
- Fehler im Kontext zeigen. Dialoge nur, wenn eine Entscheidung nötig ist.
- Dauert etwas länger als etwa 300 ms: Skeleton oder Spinner; länger als 2 s: Fortschritt oder erklärender Text.

## Dialoge und Menüs
- Dialoge: Titel als Aufgabe oder Frage, primäre Aktion rechts, Esc schließt, Fokus bleibt im Dialog und kehrt danach zurück.
- Menüs und Popover: am Auslöser verankert, per Tastatur bedienbar, schließen bei Klick außerhalb.

## Navigation
- Aktuelle Seite eindeutig markiert, höchstens fünf bis sieben Hauptpunkte.
- Tastaturkürzel für häufige Aktionen; eine Befehlspalette (Strg/⌘ + K) für schnelle Nutzer.

Siehe [[Barrierefreiheit]] und [[Bewegung]].
