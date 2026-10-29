---
tags: [design, bibliothek]
aliases: [Animation, Motion, Übergänge]
---
Animation erklärt Veränderung: woher etwas kommt, wohin es geht, dass etwas passiert ist. Alles andere lenkt ab.

- **Dauer:** Rückmeldungen 100–150 ms, Ein- und Ausblenden 150–250 ms, größere Übergänge (Panels, Dialoge) 250–400 ms. Schließen etwas schneller als Öffnen.
- **Kurven:** Hereinkommen mit ease-out, etwa `cubic-bezier(0.2, 0.8, 0.2, 1)`; Hinausgehen mit ease-in; Bewegung auf der Stelle mit ease-in-out. Kein lineares Easing für Oberflächen, kein Federn in Arbeitswerkzeugen.
- **Was animieren:** nur `transform` und `opacity` – das bleibt flüssig. Nicht `width`, `height` oder `top`.
- **Sparsam:** Nicht jeder Hover braucht Bewegung; ein Farbwechsel reicht.
- **Rücksicht:** `@media (prefers-reduced-motion: reduce)` – Bewegung weglassen oder auf Überblendungen reduzieren.
- **Nachladende Inhalte** dürfen das Layout nicht springen lassen: Platz reservieren, dann sanft einblenden.

Siehe [[Komponenten]] und [[Barrierefreiheit]].
