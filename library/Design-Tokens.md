---
tags: [design, bibliothek, css]
aliases: [Tokens, CSS-Variablen, Design-System]
---
Ein kleines, vollständiges Grundgerüst als CSS-Variablen. Die Werte heißen nach ihrer Rolle, damit helles und dunkles Design nur die Tokens tauschen. Die Akzentfarbe ist ein Startwert – passe sie an das Projekt an (siehe [[Farbe]]).

```css
:root {
  /* Schrift */
  --font-sans: system-ui, -apple-system, "Segoe UI Variable", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "Cascadia Code", "SF Mono", "JetBrains Mono", Consolas, monospace;
  --text-xs: 0.75rem;    /* 12 px */
  --text-sm: 0.8125rem;  /* 13 px */
  --text-md: 0.875rem;   /* 14 px */
  --text-lg: 1rem;       /* 16 px */
  --text-xl: 1.25rem;    /* 20 px */
  --text-2xl: 1.5rem;    /* 24 px */
  --text-display: clamp(1.75rem, 1.2rem + 2vw, 2.5rem);

  /* Abstände: 4-px-Raster */
  --space-1: 4px;  --space-2: 8px;   --space-3: 12px;  --space-4: 16px;
  --space-6: 24px; --space-8: 32px;  --space-12: 48px; --space-16: 64px;

  /* Radien */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px; --radius-full: 999px;

  /* Farben – hell, leicht warme Neutraltöne */
  --bg: #f7f7f5;
  --surface: #ffffff;
  --surface-2: #efefec;
  --border: #e2e2de;
  --text: #1b1b1a;
  --text-muted: #5b5b55;
  --text-subtle: #75756e;
  --accent: #3355cc;
  --accent-hover: #2a47ad;
  --on-accent: #ffffff;
  --success: #1f7a3d;
  --warning: #9a5b00;
  --danger: #b42318;
  --focus-ring: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent);
  --shadow-popover: 0 8px 24px rgb(0 0 0 / 0.12), 0 2px 6px rgb(0 0 0 / 0.08);

  /* Bewegung */
  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);
  --duration-fast: 120ms;
  --duration: 200ms;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111110;
    --surface: #191918;
    --surface-2: #222220;
    --border: #30302d;
    --text: #ededea;
    --text-muted: #a6a69f;
    --text-subtle: #82827b;
    --accent: #7f9cf0;
    --accent-hover: #9cb3f4;
    --on-accent: #0e0e0d;
    --success: #5fcf80;
    --warning: #f0b440;
    --danger: #f2877d;
    --shadow-popover: 0 8px 24px rgb(0 0 0 / 0.5);
  }
}

*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 400 var(--text-md)/1.5 var(--font-sans);
  -webkit-font-smoothing: antialiased;
}

:focus-visible { outline: none; box-shadow: var(--focus-ring); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

## Hinweise
- `--text-subtle` erreicht auf `--surface-2` nur knapp 4 : 1 – für wichtige Texte `--text-muted` nehmen.
- Neue Werte erst als Token anlegen, dann benutzen – keine verstreuten Hex-Codes im CSS.
- Zusammenhänge: [[Typografie]] · [[Layout und Abstände]] · [[Bewegung]]
