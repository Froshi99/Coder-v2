---
tags: [design, bibliothek]
aliases: [Accessibility, a11y, Zugänglichkeit]
---
- **Kontrast:** Text ≥ 4,5 : 1; großer Text (ab 24 px, fett ab 19 px) und Bedienelemente ≥ 3 : 1.
- **Tastatur:** Alles ist mit Tab erreichbar und mit Enter oder Leertaste bedienbar; die Reihenfolge folgt der Optik. Esc schließt Dialoge und Menüs.
- **Sichtbarer Fokus:** `:focus-visible` mit deutlichem Ring (2 px in der Akzentfarbe, mit Abstand). Nie `outline: none` ohne Ersatz.
- **Semantik:** echte `<button>`, `<a href>`, `<label for>`; Überschriften ohne Sprünge; Landmarks wie `<header>`, `<nav>`, `<main>`.
- **Beschriftungen:** Icon-Buttons mit `aria-label`, Bilder mit sinnvollem `alt` (dekorative mit `alt=""`), Fehlermeldungen per `aria-describedby` am Feld.
- **Live-Inhalte:** Status mit `aria-live="polite"`, dringende Fehler mit `role="alert"`.
- **Zielgrößen:** mindestens 24 × 24 px, auf Touch 44 × 44 px.
- **Nicht nur Farbe:** Zustände zusätzlich mit Text oder Icon zeigen.
- **Zoom:** Das Layout hält 200 % Zoom und größere Systemschrift aus; Schriftgrößen in `rem`.
- **Bewegung:** `prefers-reduced-motion` respektieren, siehe [[Bewegung]].
