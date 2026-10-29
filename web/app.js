"use strict";

/* ================================================================ Grundlagen */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const nf = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("de-DE", { weekday: "long" });
const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short" });

const state = {
  config: null,
  hardware: null,
  ollama: null,
  session: null,
  sessions: [],
  loaded: [],
  plan: null,
  busy: false,
  ws: null,
  live: null,           // streamende Agenten-Nachricht
  tools: new Map(),     // Werkzeug-ID -> Schritt-Element
  approvalId: null,
  renderQueued: false,
  runAgent: null,       // per @name angesprochener Agent des laufenden Auftrags
  runLabeled: false,
  ext: null,            // Agents und Befehle für den aktuellen Workspace
  modelLoading: false,
  loop: null,           // laufende Schleife
  sharpening: null,     // Text, der gerade geschärft wird
  question: null,       // offene Rückfrage des Agenten
  tab: "code",          // Bereich: code · talk (Chat) · ide (Editor)
  me: null,             // wer vor dem Fenster sitzt – Name, Rolle, erlaubte Modi (core/users.py)
};

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* privat */ } },
};

const forcedTheme = new URLSearchParams(location.search).get("theme");
// Dem System folgen – aber nur, solange niemand hell oder dunkel festgelegt hat.
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  if (["light", "dark"].includes(state.config?.theme)) return;
  document.documentElement.dataset.theme = e.matches ? "dark" : "light";
});

const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICONS = {
  incognito: svg('<path d="M3 11h18"/><path d="M5.5 11 7 5.5h10l1.5 5.5"/><circle cx="7.5" cy="16" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/><path d="M10 16h4"/>'),
  branch: svg('<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 5-6 4-11.5 8.5"/>'),
  eye: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.8"/>'),
  users: svg('<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M16 5.5a3 3 0 0 1 0 6M17.5 14.2A5.5 5.5 0 0 1 20.5 19"/>'),
  read_file: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
  list_dir: svg('<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5Z"/>'),
  glob: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  grep: svg('<path d="M4 6h16M4 12h9M4 18h6"/><circle cx="17.5" cy="16.5" r="3"/><path d="m22 21-2.3-2.3"/>'),
  edit_file: svg('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
  write_file: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>'),
  run_command: svg('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3M13 15h4"/>'),
  todo_write: svg('<path d="m4 7 2 2 3-3M4 16l2 2 3-3M13 8h7M13 17h7"/>'),
  check: svg('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  cross: svg('<path d="M6 6l12 12M18 6 6 18"/>'),
  chevron: svg('<path d="m9 6 6 6-6 6"/>'),
  trash: svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  alert: svg('<path d="M12 8v5M12 16.5h.01"/><path d="M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'),
  sparkle: svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5"/>'),
  arrow: svg('<path d="m9 6 6 6-6 6"/>'),
  web_search: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9s1.3-6.4 3.8-9Z"/>'),
  web_fetch: svg('<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>'),
  up: svg('<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>'),
  agent: svg('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/><circle cx="17.2" cy="9.3" r="2.4"/><path d="M16 14.3a4.3 4.3 0 0 1 4.9 4.2"/>'),
  command: svg('<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="m14 7.5-4 9"/>'),
  note: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>'),
  graph: svg('<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="m8.3 6.6 7.4-.6M7.1 9.1l3.8 6.8M16.9 8.2l-3.8 7.7"/>'),
  memory_write: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><path d="M14 3v5h5v2M17.5 13.5a1.6 1.6 0 0 1 2.3 2.3L15 20.6l-3 .8.8-3Z"/>'),
  pin: svg('<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3ZM12 14v6"/>'),
  back: svg('<path d="m15 6-6 6 6 6"/>'),
  image: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-8 9"/>'),
  generate_image: svg('<path d="M20 12.5v6A2.5 2.5 0 0 1 17.5 21h-11A2.5 2.5 0 0 1 4 18.5v-11A2.5 2.5 0 0 1 6.5 5H12"/><circle cx="9" cy="10.5" r="1.5"/><path d="m20 16.5-4.5-4.5L8 20"/><path d="M18 2.5v6M21 5.5h-6"/>'),
  controller: svg('<path d="M12 3 5 6v5.5c0 4.3 3 8.2 7 9.5 4-1.3 7-5.2 7-9.5V6Z"/><path d="m9 12 2 2 4-4"/>'),
  mode: svg('<path d="M12 3 5 6v5.5c0 4.3 3 8.2 7 9.5 4-1.3 7-5.2 7-9.5V6Z"/>'),
  redo: svg('<path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5"/>'),
  research: svg('<path d="M4 19V5a1 1 0 0 1 1-1h9l4 4v3"/><path d="M8 9h5M8 13h3"/><circle cx="16.5" cy="16.5" r="3"/><path d="m21 21-2.4-2.4"/>'),
  gear: svg('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  person: svg('<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'),
  style: svg('<path d="M4 7h16M4 12h10M4 17h13"/>'),
  minus: svg('<path d="M5 12h14"/>'),
  fit: svg('<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>'),
  sidebar: svg('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>'),
  cowork: svg('<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15M15 4.5v15"/>'),
  chip: svg('<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>'),
  compact: svg('<path d="M4 12h16M8 5l4 4 4-4M8 19l4-4 4 4"/>'),
  chat: svg('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12Z"/>'),
  undo: svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H12"/>'),
  ask_user: svg('<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.8c0 1.7-2.4 2.2-2.4 3.8M12 17h.01"/>'),
  plan: svg('<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>'),
  effort: svg('<path d="M4 18h3v-4H4ZM10.5 18h3V9h-3ZM17 18h3V5h-3Z"/>'),
  palette: svg('<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.8-1.7 1.7-1.7H16a5 5 0 0 0 5-5c0-4-4-7.2-9-7.2Z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>'),
};
ICONS.memory_search = ICONS.graph;
ICONS.memory_read = ICONS.note;
ICONS.folder = ICONS.list_dir;
ICONS.view_image = ICONS.image;
ICONS.web_research = ICONS.research;
// Diktieren in der Befehlspalette – ohne eigenes Zeichen stand dort „undefined“.
ICONS.mic = svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>');
const TOOL_LABEL = {
  read_file: "Gelesen", list_dir: "Ordner", glob: "Dateien gesucht", grep: "Code durchsucht",
  edit_file: "Bearbeitet", write_file: "Geschrieben", run_command: "Befehl", todo_write: "Aufgaben",
  web_search: "Web durchsucht", web_fetch: "Seite gelesen", web_research: "Recherchiert", view_image: "Bild angesehen",
  memory_search: "Gedächtnis durchsucht", memory_read: "Notiz gelesen", memory_write: "Notiz gespeichert",
  generate_image: "Bild erzeugt", ask_user: "Rückfrage",
};
const TOOL_VERB = {
  read_file: "Liest", list_dir: "Öffnet Ordner", glob: "Sucht Dateien", grep: "Durchsucht Code nach",
  edit_file: "Bearbeitet", write_file: "Schreibt", run_command: "Führt aus:", todo_write: "Plant die Aufgaben",
  web_search: "Sucht im Web nach", web_fetch: "Lädt", web_research: "Recherchiert:", view_image: "Sieht sich an:",
  memory_search: "Durchsucht das Gedächtnis nach", memory_read: "Liest die Notiz", memory_write: "Speichert die Notiz",
  generate_image: "Malt:", ask_user: "Fragt nach:",
};
const APPROVAL_TITLE = {
  edit_file: "Datei bearbeiten?", write_file: "Datei schreiben?", run_command: "Befehl ausführen?",
  web_fetch: "Webseite abrufen?", web_research: "Im Internet recherchieren?", generate_image: "Bild erzeugen?",
};
const agentName = (name) => (name === "kontrolle" ? "Kontrolle" : `@${name}`);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const gb = (bytes) => `${nf.format(bytes / 1024 ** 3)} GB`;
const kctx = (n) => (n >= 1024 ? `${Math.round(n / 1024)}K` : String(n));
const pct = (share) => `${Math.round((share || 0) * 100)} %`;
const basename = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || String(p || "");
// Pfade werden per direction:rtl vorn gekürzt – LRM-Zeichen halten „C:\“ und Endstriche dabei an ihrem Platz.
const ltr = (s) => `‎${s || ""}‎`;

function duration(seconds) {
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, "0")} min`;
}

function whenLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.floor((today - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (diffDays <= 0) return timeFmt.format(d);
  if (diffDays === 1) return "Gestern";
  if (diffDays < 7) return dayFmt.format(d);
  return dateFmt.format(d);
}

async function api(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/api/log")) {
    location.href = "/login"; // Anmeldung abgelaufen oder Konto gelöscht
    throw new Error("Bitte neu anmelden.");
  }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

let toastTimer;
function toast(text, { error = false, ms = 3200 } = {}) {
  const el = $("#toast");
  el.classList.toggle("error", error);
  el.classList.remove("leaving");
  el.innerHTML = `${error ? ICONS.alert : ""}<span>${esc(text)}</span>`;
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.add("leaving"); // ausblenden statt verschwinden
    toastTimer = setTimeout(() => {
      el.hidden = true;
      el.classList.remove("leaving");
    }, 240);
  }, ms);
}

/* ================================================================ Markdown */

// [[Titel]], [[Titel#Abschnitt]] und [[Titel|Anzeige]]: Links auf Notizen im Gedächtnis
const WIKILINK_RX = /\[\[([^[\]|#\n]+)(#[^[\]|\n]*)?(?:\|([^[\]\n]*))?\]\]/g;
const wikilink = (_, target, _section, alias) => `<a class="wikilink" data-note="${target.trim()}">${(alias || target).trim()}</a>`;

function inline(text) {
  return esc(text)
    .split(/(`[^`\n]+`)/g)
    .map((part, i) => i % 2
      ? `<code>${part.slice(1, -1)}</code>`
      : part
        .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        .replace(WIKILINK_RX, wikilink))
    .join("");
}

const RX = {
  fence: /^\s*```\s*([\w+#.-]*)\s*$/,
  heading: /^(#{1,4})\s+(.*)$/,
  list: /^\s*([-*+]|\d+[.)])\s+(.*)$/,
  quote: /^\s*>\s?(.*)$/,
  hr: /^\s*([-*_])(\s*\1){2,}\s*$/,
  table: /^\s*\|.*\|\s*$/,
  tableSep: /^\s*\|?\s*:?-{2,}/,
};
const isBlock = (l) => RX.fence.test(l) || RX.heading.test(l) || RX.list.test(l) || RX.quote.test(l) || RX.hr.test(l);

// Namen, wie sie in ```-Blöcken stehen, auf die Sprachen des Hervorhebers abbilden
const FENCE_LANG = {
  python: "py", py: "py", javascript: "js", js: "js", typescript: "js", ts: "js", jsx: "js", tsx: "js",
  json: "json", html: "html", xml: "html", svg: "html", vue: "html", css: "css", scss: "css", less: "css",
  markdown: "md", md: "md", bash: "sh", sh: "sh", shell: "sh", zsh: "sh", powershell: "sh", ps1: "sh",
  yaml: "yaml", yml: "yaml", toml: "toml", ini: "toml", sql: "sql", go: "go", golang: "go", rust: "rust",
  rs: "rust", java: "java", kotlin: "java", c: "c", cpp: "c", "c++": "c", cs: "c", csharp: "c", ruby: "py",
  rb: "py", php: "js", lua: "py",
};

function codeBlock(code, lang) {
  const kind = FENCE_LANG[String(lang || "").toLowerCase()] || "";
  return `<div class="code"><div class="code-head"><span>${esc(lang || "code")}</span>` +
    `<button type="button" data-copy>${ICONS.copy}<span>Kopieren</span></button></div>` +
    `<pre><code>${kind ? highlight(code, kind) : esc(code)}</code></pre></div>`;
}

function markdown(src) {
  src = String(src || "").replace(/<tool_call>[\s\S]*?(<\/tool_call>|$)/g, "");
  const lines = src.split("\n");
  let html = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if ((m = line.match(RX.fence))) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      html += codeBlock(buf.join("\n"), m[1]);
    } else if ((m = line.match(RX.heading))) {
      const n = m[1].length;
      html += `<h${n}>${inline(m[2])}</h${n}>`;
      i++;
    } else if (RX.hr.test(line)) {
      html += "<hr>";
      i++;
    } else if (RX.quote.test(line)) {
      const buf = [];
      while (i < lines.length && (m = lines[i].match(RX.quote))) { buf.push(m[1]); i++; }
      html += `<blockquote>${markdown(buf.join("\n"))}</blockquote>`;
    } else if (RX.list.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items = [];
      while (i < lines.length) {
        if ((m = lines[i].match(RX.list))) { items.push(m[2]); i++; }
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>${items.map((it) => {
        const task = it.match(/^\[([ xX])\]\s+([\s\S]*)$/); // Checkliste, wie sie in Notizen steht
        if (!task) return `<li>${inline(it)}</li>`;
        return `<li class="task${task[1] === " " ? "" : " done"}">${inline(task[2])}</li>`;
      }).join("")}</${tag}>`;
    } else if (RX.table.test(line) && RX.tableSep.test(lines[i + 1] || "")) {
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      let body = "";
      while (i < lines.length && RX.table.test(lines[i])) {
        body += `<tr>${cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`;
        i++;
      }
      html += `<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
    } else if (!line.trim()) {
      i++;
    } else {
      const buf = [lines[i++]];
      while (i < lines.length && lines[i].trim() && !isBlock(lines[i]) && !RX.table.test(lines[i])) buf.push(lines[i++]);
      html += `<p>${buf.map(inline).join("<br>")}</p>`;
    }
  }
  return html;
}

/* Unified Diff mit Zeilennummern */
function diffHtml(diff) {
  let oldN = 0;
  let newN = 0;
  const rows = [];
  for (const l of String(diff || "").split("\n")) {
    if (l.startsWith("+++") || l.startsWith("---")) continue;
    const hunk = l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
    if (hunk) {
      oldN = +hunk[1];
      newN = +hunk[2];
      if (rows.length || newN > 1) rows.push(`<div class="dl hunk">Ab Zeile ${Math.max(1, newN)}</div>`);
    } else if (l.startsWith("…")) {
      rows.push(`<div class="dl hunk">${esc(l)}</div>`);
    } else {
      let cls = "", sign = "", num;
      if (l.startsWith("+")) { cls = "add"; sign = "+"; num = newN++; }
      else if (l.startsWith("-")) { cls = "del"; sign = "−"; num = oldN++; }
      else { num = newN++; oldN++; }
      rows.push(`<div class="dl ${cls}"><span class="ln">${num}</span><span class="sg">${sign}</span><span class="cd">${esc(l.slice(1)) || " "}</span></div>`);
    }
  }
  return `<div class="diff">${rows.join("")}</div>`;
}

/* ================================================================ Scrollen & Dock */

const scroller = $("#scroll");
let stickToBottom = true;
scroller.addEventListener("scroll", () => {
  stickToBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
});
function scrollDown(force = false) {
  if (force || stickToBottom) {
    scroller.style.scrollBehavior = "auto";
    scroller.scrollTop = scroller.scrollHeight;
    scroller.style.scrollBehavior = "";
  }
}
new ResizeObserver(() => {
  document.documentElement.style.setProperty("--dock-h", `${$("#dock").offsetHeight}px`);
  scrollDown();
}).observe($("#dock"));

/* ================================================================ Verlauf */

const thread = $("#thread");

function updateEmpty() {
  $("#empty").hidden = thread.childElementCount > 0;
}

function addUser(text, images = []) {
  const el = document.createElement("div");
  el.className = "turn user";
  // @agent oder /befehl am Anfang hervorheben
  const lead = String(text).match(/^(\s*)([@/][\w:-]+)/);
  const html = (lead ? `${esc(lead[1])}<span class="mention">${esc(lead[2])}</span>${esc(text.slice(lead[0].length))}` : esc(text))
    .replace(WIKILINK_RX, wikilink);
  const pictures = images.length
    ? `<div class="user-images">${images.map((id) => `<button type="button" class="user-image" data-image="${esc(id)}" aria-label="Bild vergrößern"><img src="/api/images/${encodeURIComponent(id)}" alt="Angehängtes Bild" loading="lazy"></button>`).join("")}</div>`
    : "";
  // Unter der eigenen Nachricht, beim Überfahren: kopieren, noch einmal verwenden, als Prompt merken.
  const actions = `<div class="user-actions">
      <button type="button" data-user-act="copy">Kopieren</button>
      <button type="button" data-user-act="reuse" title="Den Text zurück in die Eingabe holen">In die Eingabe</button>
      ${roleAtLeast("admin") && serverHas("1.12.0") ? `<button type="button" data-user-act="prompt" title="Daraus einen eigenen /Prompt machen">Als Prompt</button>` : ""}
    </div>`;
  el.innerHTML = `${pictures}<div class="bubble">${html}</div>${String(text).trim() ? actions : ""}`;
  el.raw = String(text);
  thread.append(el);
  updateEmpty();
  return el;
}

function lastUserTurn() {
  const turns = $$(".turn.user", thread);
  return turns[turns.length - 1] || null;
}

function addVisionNote(el, vision) {
  if (!el || !vision?.model) return;
  const note = document.createElement("details");
  note.className = "turn-note";
  note.innerHTML = `<summary>Bild beschrieben von ${esc(vision.model)}</summary><div class="md">${markdown(vision.text || "")}</div>`;
  el.append(note);
}

// Chat: Dateien, die in der Nachricht genannt sind, hat Coder gleich mitgelesen.
function addFilesNote(el, files) {
  if (!el || !files?.length) return;
  const note = document.createElement("div");
  note.className = "turn-note";
  note.innerHTML = `Mitgelesen: ${files.map((f) => `<code>${esc(f)}</code>`).join(", ")}`;
  el.append(note);
}

function addRecallNote(el, titles) {
  if (!el || !titles?.length) return;
  const note = document.createElement("div");
  note.className = "turn-note";
  note.innerHTML = `Aus dem Gedächtnis: ${titles.map((t) => `<a class="wikilink" data-note="${esc(t)}">${esc(t)}</a>`).join(", ")}`;
  el.append(note);
}

function addAgent(id, agent = null) {
  const el = document.createElement("div");
  el.className = "turn agent";
  el.dataset.id = id || "";
  const label = agent ? `<div class="agent-label">${ICONS.agent}@${esc(agent)}</div>` : "";
  el.innerHTML = `${label}<div class="md"></div><ol class="steps"></ol><div class="receipt"></div>`;
  thread.append(el);
  updateEmpty();
  markLast();
  return el;
}

let bulkRender = false; // renderSession baut viele Blöcke auf einmal – markLast läuft dann einmal am Ende

function markLast() {
  if (bulkRender) return;
  const agents = $$(".turn.agent", thread);
  agents.forEach((a, i) => {
    a.classList.toggle("last", i === agents.length - 1);
    // Messwerte nur am Ende eines Agent-Laufs, nicht nach jedem Zwischenschritt
    a.classList.toggle("end", !a.nextElementSibling?.classList.contains("agent"));
  });
}

function setThinking(el, text, streaming) {
  let det = $(".thinking", el);
  if (!det) {
    det = document.createElement("details");
    det.className = "thinking";
    det.innerHTML = `<summary>${ICONS.chevron}<span></span></summary><div class="think-body"></div>`;
    el.prepend(det);
  }
  $("summary span", det).textContent = streaming ? "Denkt nach …" : "Gedankengang";
  $(".think-body", det).textContent = text;
}

// Messwerte bleiben im Hintergrund: sichtbar ist nur das Tempo, alles Weitere erscheint beim Überfahren
// der Antwort – so steht im Chat der Text und nicht die Statistik.
function setReceipt(el, s) {
  if (!s) return;
  const quiet = [];
  const more = [];
  if (s.tokens_per_s) quiet.push(`${nf.format(s.tokens_per_s)} tok/s`);
  if (s.total_s) quiet.push(`${nf.format(s.total_s)} s`);
  if (s.tokens) more.push(`${s.tokens} Token`);
  if (s.prompt_tokens) more.push(`Prompt ${nf.format(s.prompt_tokens)}`);
  if (s.load_s > 0.3) more.push(`geladen in ${nf.format(s.load_s)} s`);
  if (!quiet.length && more.length) quiet.push(more.shift());
  let html = quiet.map((p) => `<span>${esc(p)}</span>`).join("")
    + more.map((p) => `<span class="receipt-more">${esc(p)}</span>`).join("");
  if (s.done_reason === "length") html += `<span class="warn">Abgeschnitten – Kontext voll</span>`;
  if (el.raw?.trim()) html += `<button type="button" class="receipt-copy" data-copy-answer>Kopieren</button>`;
  const box = $(".receipt", el);
  box.title = [...quiet, ...more].join(" · ");
  box.innerHTML = html;
}

const FILE_TOOLS = new Set(["read_file", "edit_file", "write_file"]);

function addStep(parent, { id, name, summary, args = {} }) {
  if (name === "todo_write") return null; // die Aufgabenliste hat ihre eigene Karte über der Eingabe
  const controlled = name === "controller";
  const agent = name === "agent" || controlled;
  const el = document.createElement("li");
  el.className = `step running${agent ? " open" : ""}`;
  el.dataset.name = name;
  // Ein Sub-Agent zeigt seinen Namen und die Aufgabe; seine eigenen Schritte erscheinen eingerückt darunter.
  const label = controlled ? "Kontrolle"
    : agent ? `@${args.agent || String(summary).split(" · ")[0]}` : (TOOL_VERB[name] || name).replace(/:$/, "");
  const target = controlled ? [args.model, summary].filter(Boolean).join(" · ")
    : agent ? args.task || String(summary).split(" · ").slice(1).join(" · ") : summary;
  const body = agent
    ? `<div class="step-body agent-body"><ol class="steps sub-steps"></ol><div class="agent-live"></div><div class="agent-report md" hidden></div></div>`
    : `<div class="step-body" hidden></div>`;
  el.innerHTML = `
    <button class="step-head${agent ? " expandable" : ""}" type="button" aria-expanded="${agent}">
      <span class="step-dot">${ICONS[name] || ICONS.run_command}<span class="step-badge" hidden></span></span>
      <span class="step-label">${esc(label)}</span>
      <span class="step-target">${esc(target)}</span>
      <span class="step-stat"></span>
      <span class="step-chev">${ICONS.chevron}</span>
    </button>
    ${body}`;
  $(".step-head", el).addEventListener("click", () => toggleStep(el));
  if (FILE_TOOLS.has(name) && args.path) {
    const target = $(".step-target", el);
    target.classList.add("openable");
    target.title = "Datei öffnen";
    target.addEventListener("click", (e) => {
      e.stopPropagation();
      openFiles(String(args.path).replace(/\\/g, "/"));
    });
  }
  $(".steps", parent).append(el);
  state.tools.set(id, el);
  return el;
}

function toggleStep(el, open) {
  const body = $(".step-body", el);
  if (!body.innerHTML) return;
  const next = open ?? body.hidden;
  body.hidden = !next;
  el.classList.toggle("open", next);
  $(".step-head", el).setAttribute("aria-expanded", String(next));
}

function finishStep(el, { ok, output, display = {} }) {
  if (!el) return;
  el.classList.remove("running", "waiting");
  el.classList.add(ok ? "ok" : "fail");
  const badge = $(".step-badge", el);
  badge.hidden = false;
  badge.innerHTML = ok ? ICONS.check : ICONS.cross;

  const name = el.dataset.name;
  if (name === "agent" || name === "controller") return finishAgent(el, display);
  $(".step-label", el).textContent = TOOL_LABEL[name] || name;
  const stat = $(".step-stat", el);
  if (display.denied) stat.textContent = "Abgelehnt";
  else if (display.diff !== undefined) stat.innerHTML = `<span class="add">+${display.added || 0}</span> <span class="rem">−${display.removed || 0}</span>`;
  else if ((name === "read_file" || name === "memory_read") && display.lines !== undefined) stat.textContent = `${display.lines} Zeilen`;
  else if (name === "list_dir" && display.count !== undefined) stat.textContent = `${display.count} Einträge`;
  else if (name === "web_research" && display.count !== undefined) stat.textContent = `${display.count} ${display.count === 1 ? "Quelle" : "Quellen"}`;
  else if (name === "view_image" && display.model) stat.textContent = `mit ${display.model}`;
  else if (name === "generate_image" && display.width) stat.textContent = `${display.width}×${display.height} · ${display.seconds} s`;
  else if (name === "ask_user" && display.items) stat.textContent = display.limit ? "Nicht gefragt" : display.skipped ? "Übersprungen" : "Beantwortet";
  else if (display.count !== undefined) stat.textContent = `${display.count} Treffer`;
  else if (display.chars !== undefined) stat.textContent = `${nf.format(display.chars)} Zeichen`;
  else if (display.background) stat.textContent = display.exit_code == null ? `Läuft · PID ${display.pid}` : `Beendet · Exit ${display.exit_code}`;
  else if (display.timed_out) stat.textContent = "Zeitüberschreitung";
  else if (display.exit_code !== undefined) stat.textContent = display.exit_code === 0 ? "Erfolgreich" : `Exit ${display.exit_code}`;

  const body = $(".step-body", el);
  if (name === "ask_user" && display.items) {
    body.innerHTML = display.items.map((item) => answerHtml(item, display.items.length > 1)).join("");
    toggleStep(el, true);
  } else if (name === "generate_image" && display.image_id) {
    body.innerHTML = generatedImage(display);
    toggleStep(el, true);
  } else if (display.diff) {
    body.innerHTML = diffHtml(display.diff);
    toggleStep(el, display.diff.split("\n").length <= 40);
  } else if (output) {
    body.innerHTML = `<pre>${esc(output)}</pre>`;
    if (name === "run_command" && !ok && !display.denied) toggleStep(el, true);
  }
  // Gelesene und gespeicherte Notizen: ein Klick führt direkt hin.
  if ((name === "memory_read" || name === "memory_write") && display.note) {
    body.insertAdjacentHTML("beforeend", `<div class="step-note-link"><a class="wikilink" data-note="${esc(display.note)}" data-vault="${esc(display.vault || "")}">`
      + `„${esc(display.note)}“ im Gedächtnis öffnen</a><span>${esc(vaultLabel(display.vault || "project"))}</span></div>`);
  }
  $(".step-head", el).classList.toggle("expandable", !!body.innerHTML);
}

// Eine Rückfrage im Verlauf: was der Nutzer geantwortet hat – bei mehreren Fragen samt Frage.
function answerHtml(item, withQuestion) {
  const a = item.answer;
  const said = !a || a.skipped
    ? `<span class="qa-skip">Übersprungen – Coder hat selbst entschieden</span>`
    : [...(a.choices || []).map((c) => `<strong>${esc(c)}</strong>`), a.text ? `„${esc(a.text)}“` : ""].filter(Boolean).join(" · ");
  const question = withQuestion ? `<div class="qa-q">${esc(item.question)}</div>` : "";
  return `<div class="qa">${question}<div class="qa-a">${ICONS.arrow}<span>${said}</span></div></div>`;
}

// Ein erzeugtes Bild: Vorschau zum Vergrößern, darunter Pfad, Seed und Modell – und ein Link zum Sichern.
function generatedImage(d) {
  const id = encodeURIComponent(d.image_id);
  const file = String(d.path || "bild.png").split("/").pop();
  return `<figure class="gen-image">`
    + `<button type="button" data-image="${esc(d.image_id)}" aria-label="Bild vergrößern">`
    + `<img src="/api/images/${id}" alt="${esc(d.path || "Erzeugtes Bild")}" loading="lazy"></button>`
    + `<figcaption><span class="gen-path">${esc(d.path || "")}</span>`
    + `<span class="gen-meta">Seed ${esc(String(d.seed ?? "?"))} · ${esc(String(d.model || "?"))} · ${esc(String(d.backend || ""))}</span>`
    + `<a class="gen-save" href="/api/images/${id}" download="${esc(file)}">Speichern</a></figcaption></figure>`;
}

function finishAgent(el, display) {
  const body = $(".agent-body", el);
  const steps = display.steps || [];
  // Nach dem Neuladen gibt es keine Live-Schritte – dann aus dem gespeicherten Verlauf aufbauen.
  if (!$(".step", body)) for (const s of steps) finishStep(addStep(body, s), s);
  $$(".step.running, .step.waiting", body).forEach((s) => finishStep(s, { ok: false }));
  $(".agent-live", body).textContent = "";
  const report = $(".agent-report", body);
  report.innerHTML = display.report ? markdown(display.report) : "<p>Kein Bericht – der Agent wurde vorher beendet.</p>";
  report.hidden = false;
  const count = steps.filter((s) => s.name !== "todo_write").length;
  // Ein eigenes Modell des Agents steht dabei – aber nur, wenn es ein anderes ist als das des Hauptagenten.
  const eigenes = display.model && display.model !== state.config?.model ? display.model : "";
  $(".step-stat", el).textContent = [
    count ? `${count} ${count === 1 ? "Schritt" : "Schritte"}` : "",
    display.seconds ? duration(Math.round(display.seconds)) : "",
    eigenes,
  ].filter(Boolean).join(" · ");
}

const VERDICT = {
  done: ["Passt", "check"], continue: ["Nachbessern", "redo"], unclear: ["Kein klares Urteil", "alert"],
  error: ["Fehlgeschlagen", "alert"], stopped: ["Abgelehnt", "cross"],
};
const REASON = { end: "prüft das Ergebnis", interval: "schaut nach dem Rechten", stuck: "hilft aus der Sackgasse" };

function addController(ev) {
  const turn = addAgent("");
  turn.classList.add("control");
  return addStep(turn, { id: ev.id, name: "controller", summary: REASON[ev.reason] || "", args: { model: ev.model } });
}

function finishController(el, d) {
  if (!el) return;
  const [label, icon] = VERDICT[d.verdict] || VERDICT.unclear;
  finishStep(el, { ok: d.verdict === "done", display: { ...d, report: d.note || label } });
  el.classList.remove("ok", "fail");
  el.classList.add(`verdict-${d.verdict}`);
  $(".step-badge", el).innerHTML = ICONS[icon];
  const stat = $(".step-stat", el);
  stat.textContent = [label, stat.textContent].filter(Boolean).join(" · ");
  if (d.verdict === "done") toggleStep(el, false); // Abgesegnetes nimmt keinen Platz weg
}

function addError(message) {
  const el = document.createElement("div");
  el.className = "notice-error";
  el.setAttribute("role", "alert");
  el.innerHTML = `${ICONS.alert}<div><strong>Das hat nicht geklappt</strong>${esc(message)}</div>`;
  thread.append(el);
  updateEmpty();
  scrollDown(true);
}

function addNotice(text) {
  const el = document.createElement("div");
  el.className = "notice";
  el.textContent = text;
  thread.append(el);
  updateEmpty();
  scrollDown();
}

function addCompacted(summary) {
  const el = document.createElement("details");
  el.className = "compacted";
  el.innerHTML = `<summary>Verlauf verdichtet – Zusammenfassung anzeigen</summary><div class="md">${markdown(summary || "")}</div>`;
  thread.append(el);
  updateEmpty();
}

/* Geänderte Dateien eines Auftrags – die jüngsten lassen sich zurücknehmen */
function addChanges(ch) {
  if (!ch?.files?.length) return null;
  const el = document.createElement("div");
  el.className = `changes${ch.undone ? " undone" : ""}`;
  el.dataset.turn = ch.turn;
  const total = (key) => ch.files.reduce((n, f) => n + (f[key] || 0), 0);
  const count = ch.files.length;
  const counted = ch.files.some((f) => f.added != null); // nur Bilder oder Binärdateien: keine Zeilen zu zählen
  const rows = ch.files.slice(0, 8).map((f) => {
    const tag = f.created ? "neu" : f.deleted ? "gelöscht" : "";
    const stat = f.added == null ? "" : `<span class="add">+${f.added}</span> <span class="rem">−${f.removed}</span>`;
    return `<li><span class="changes-path" title="${esc(f.path)}">${esc(ltr(f.path))}</span>` +
      `${tag ? `<span class="changes-tag">${tag}</span>` : ""}<span class="changes-stat">${stat}</span></li>`;
  }).join("");
  const more = count > 8 ? `<li class="more">und ${count - 8} weitere</li>` : "";
  el.innerHTML = `
    <div class="changes-head">
      <span class="changes-icon">${ICONS.edit_file}</span>
      <span class="changes-title">${count} ${count === 1 ? "Datei" : "Dateien"} geändert</span>
      ${counted ? `<span class="changes-sum"><span class="add">+${total("added")}</span> <span class="rem">−${total("removed")}</span></span>` : ""}
      <span class="spacer"></span>
      <span class="changes-state">Zurückgenommen</span>
      <button type="button" class="btn ghost" data-undo title="Stellt die Dateien wie vor diesem Auftrag wieder her. Befehle im Terminal lassen sich nicht zurücknehmen.">${ICONS.undo}<span>Rückgängig</span></button>
    </div>
    <ul class="changes-files">${rows}${more}</ul>`;
  thread.append(el);
  updateEmpty();
  updateUndo();
  return el;
}

// Zurückgenommen wird immer der jüngste Auftrag zuerst – nur dort steht der Knopf.
function updateUndo() {
  const latest = $$(".changes", thread).reverse().find((b) => !b.classList.contains("undone"));
  $$(".changes", thread).forEach((b) => b.classList.toggle("undoable", b === latest && !state.busy));
}

function addUndoNotice(result) {
  const restored = result.restored || [];
  const skipped = result.skipped || [];
  let text = restored.length
    ? `Zurückgenommen: ${restored.slice(0, 6).join(", ")}${restored.length > 6 ? ` und ${restored.length - 6} weitere` : ""}.`
    : "Nichts zurückzunehmen – die Dateien waren schon im alten Zustand.";
  if (skipped.length) text += ` Nicht angefasst: ${skipped.map((s) => `${s.path} (${s.reason})`).join(", ")}.`;
  addNotice(text);
}

function undoLast() {
  if (state.busy) return toast("Erst den laufenden Auftrag stoppen, dann zurücknehmen.");
  const button = $(".changes.undoable [data-undo]", thread);
  if (button) button.disabled = true;
  send({ type: "undo" });
  clearTimeout(undoLast.timer);
  undoLast.timer = setTimeout(() => { // ein älterer Server kennt „undo“ noch nicht
    if (!button?.disabled) return;
    button.disabled = false;
    toast("Coder hat nicht geantwortet – nach einem Neustart von Coder klappt das.", { error: true });
  }, 8000);
}

/* Nachrichten während der Arbeit warten über der Eingabe, bis der Agent sie vor seinem nächsten Schritt liest. */
const queue = []; // { id, text, confirmed, timer }

function renderQueue() {
  const box = $("#queue");
  box.hidden = !queue.length;
  box.innerHTML = queue.map((q) => `
    <div class="queue-item${q.confirmed ? "" : " pending"}">
      <span class="queue-label">Wartet</span>
      <span class="queue-text" title="${esc(q.text)}">${esc(q.text)}</span>
      <button type="button" class="icon-btn" data-unqueue="${esc(q.id)}" aria-label="Zurückziehen" title="Zurückziehen – der Text kommt zurück in die Eingabe">${ICONS.cross}</button>
    </div>`).join("");
}

async function queueMessage() {
  const text = input.value.trim();
  if (!text) return;
  if (attachments.length) return toast("Bilder lassen sich erst anhängen, wenn der Agent fertig ist.");
  let prompt = text;
  if (text.startsWith("/")) {
    const head = text.split(/\s+/)[0];
    const name = head.slice(1).toLowerCase();
    if (BUILTIN_COMMANDS.some((c) => c.name === (COMMAND_ALIASES[name] || name) && builtinHere(c))) return toast("Das geht, sobald der Agent fertig ist.");
    const custom = (await loadExtensions().catch(() => null))?.commands.find((c) => c.name === name && offeredIn(c));
    if (custom) prompt = expandCommand(custom, text.slice(head.length).trim());
  }
  const item = { id: `q${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, text, confirmed: false };
  queue.push(item);
  renderQueue();
  hideSuggest();
  clearInput();
  send({ type: "send", text: prompt, ...(prompt === text ? {} : { display: text }), queue_id: item.id });
  item.timer = setTimeout(() => {
    if (!item.confirmed) dropQueued([item], "Coder hat die Nachricht nicht angenommen – sie steht wieder in der Eingabe.");
  }, 5000);
}

function takeFromQueue(id) {
  const at = queue.findIndex((q) => q.id === id);
  if (at < 0) return null;
  const [item] = queue.splice(at, 1);
  clearTimeout(item.timer);
  renderQueue();
  return item;
}

// Nicht gelesene Nachrichten gehen nie verloren: Sie kommen zurück in die Eingabe.
function dropQueued(items, message) {
  const texts = items.map((it) => takeFromQueue(it.id)?.text ?? it.display ?? it.text).filter(Boolean);
  if (!texts.length) return;
  input.value = [...texts, input.value.trim()].filter(Boolean).join("\n\n");
  autosize();
  updateSendState();
  if (message) toast(message);
}

function sessionMarkdown(s) {
  const out = [`# ${s.title || "Chat"}`, "", `Workspace: \`${s.workspace}\``, ""];
  for (const m of s.messages || []) {
    if (m.role === "user" && !m._nudge && !m._controller && !m._summary) {
      out.push("## Du", "", m._text ?? m.content, "");
    } else if (m.role === "assistant" && !m._quiet) {
      const text = (m._shown ?? m.content ?? "").trim();
      const calls = (m._calls || []).filter((c) => c.name !== "todo_write").map((c) => `- ${TOOL_LABEL[c.name] || c.name}: \`${summaryOf(c)}\``);
      if (text || calls.length) out.push("## Coder", "", ...(text ? [text, ""] : []), ...(calls.length ? [...calls, ""] : []));
    } else if (m._changes) {
      out.push(`_${m._changes.files.length} Dateien geändert: ${m._changes.files.map((f) => f.path).join(", ")}${m._changes.undone ? " (zurückgenommen)" : ""}_`, "");
    } else if (m._controller && m.role === "event") {
      out.push(`_Kontrolle (${m._controller.model}): ${m._controller.note || m._controller.verdict}_`, "");
    } else if (m.role === "tool" && m._name === "ask_user" && m._display?.items) {
      for (const item of m._display.items) {
        const a = item.answer;
        const said = !a || a.skipped ? "übersprungen" : [...(a.choices || []), a.text ? `„${a.text}“` : ""].filter(Boolean).join(", ");
        out.push(`> **Rückfrage:** ${item.question}  `, `> **Antwort:** ${said}`, "");
      }
    }
  }
  return out.join("\n");
}

async function copyChat() {
  if (!state.session?.id) return;
  try {
    await copyText(sessionMarkdown(await api(`/api/sessions/${state.session.id}`)));
    toast("Chat als Markdown kopiert");
  } catch (e) {
    toast(state.session.messages?.length || state.busy ? "Der Chat wird erst nach dem Auftrag gespeichert." : "Der Chat ist noch leer.", { error: true });
  }
}

// Nur für Chats, die noch keine gespeicherte Kurzfassung haben – sonst gilt die des Servers (m._summary).
function summaryOf(call) {
  const a = call.args || {};
  if (call.name === "generate_image") {
    const prompt = String(a.prompt || "").split(/\s+/).join(" ").slice(0, 160);
    return a.path ? `${prompt} → ${a.path}` : prompt;
  }
  return a.path || a.pattern || a.command || a.query || a.question || a.url || a.title
    || (a.todos ? `${a.todos.length} Aufgaben` : "");
}

// Lange Chats bauen sich nicht auf einmal auf: erst die letzten Runden, der Rest auf Knopfdruck. Sonst kostet
// jeder Wechsel in einen Chat mit Hunderten Antworten spürbar Zeit – vor allem fürs Layout.
const RENDER_TURNS = 30;       // so viele Aufträge stehen sofort da
const RENDER_ANSWERS = 150;    // … oder so viele Antworten des Agenten, was zuerst erreicht ist

function renderStart(msgs) {
  let turns = 0;
  let answers = 0;
  for (let i = msgs.length - 1; i > 0; i--) {
    const m = msgs[i];
    if (m.role === "assistant") answers++;
    if (m.role === "user" && m._text !== undefined && !m._queued) {
      turns++;
      if (turns >= RENDER_TURNS || answers >= RENDER_ANSWERS) return i;
    }
  }
  return 0;
}

// running: Der Auftrag läuft noch (Fenster neu geladen, Verbindung kurz weg) – dann bleiben offene Schritte offen,
// und die Antwort, die gerade entsteht, schreibt weiter, statt als abgebrochen dazustehen.
function renderSession(s, running = false, all = false) {
  thread.classList.add("instant");
  thread.innerHTML = "";
  state.tools.clear();
  state.live = null;
  let lastAgent = null;
  let streaming = null; // die Antwort, die beim Neuladen noch entstand
  let labeled = null; // der @Agent eines Auftrags steht nur über seiner ersten Antwort
  const msgs = s.messages || [];
  const from = all ? 0 : renderStart(msgs);
  if (from > 0) {
    const hidden = msgs.slice(0, from).filter((m) => m.role === "user" && m._text !== undefined && !m._queued).length;
    const more = document.createElement("button");
    more.type = "button";
    more.className = "older-turns";
    more.textContent = `${hidden} ${hidden === 1 ? "früheren Auftrag" : "frühere Aufträge"} zeigen`;
    more.addEventListener("click", () => {
      if (state.busy) return toast("Das geht, sobald der Agent fertig ist.");
      const fromBottom = scroller.scrollHeight - scroller.scrollTop;
      renderSession(state.session, false, true);
      scroller.scrollTop = scroller.scrollHeight - fromBottom; // dort bleiben, wo man war
    });
    thread.append(more);
  }
  bulkRender = true;
  try {
    for (const m of msgs.slice(from)) {
      if (m.role === "event") {
        if (m._controller) finishController(addController(m._controller), m._controller);
        if (m._changes) addChanges(m._changes);
        if (m._undo) addUndoNotice(m._undo);
      } else if (m.role === "user") {
        if (m._nudge || m._controller) continue; // interne Nachfragen an das Modell, nicht vom Nutzer
        labeled = null;
        if (m._summary) addCompacted(m.content.replace(/^\[.*?\]\n/, ""));
        else {
          const el = addUser(m._text ?? m.content, m._images || []);
          addVisionNote(el, m._vision);
          addRecallNote(el, m._recall);
          addFilesNote(el, m._files);
        }
      } else if (m.role === "assistant") {
        if (m._quiet) continue;
        const el = addAgent(m._id, m._agent && m._agent !== labeled ? m._agent : null);
        labeled = m._agent || labeled;
        if (m._thinking) setThinking(el, m._thinking, false);
        el.raw = m._shown ?? m.content;
        $(".md", el).innerHTML = markdown(el.raw);
        for (const c of m._calls || []) addStep(el, { ...c, summary: summaryOf(c) });
        setReceipt(el, m._stats);
        lastAgent = el;
        streaming = m._stats ? null : { id: m._id, el, text: el.raw || "", thinking: m._thinking || "" };
      } else if (m.role === "tool") {
        let step = state.tools.get(m._id);
        if (!step && lastAgent) step = addStep(lastAgent, { id: m._id, name: m._name, summary: m._summary || "", args: m._display || {} });
        // Die Kurzfassung des Servers kennt jedes Werkzeug – etwa den Titel bei „Notiz gelesen“.
        if (step && m._summary && m._name !== "agent") $(".step-target", step).textContent = m._summary;
        finishStep(step, { ok: m._ok, output: m.content, display: m._display || {} });
      }
      if (m.role !== "assistant" && m.role !== "event") streaming = null;
    }
  } finally {
    bulkRender = false;
  }
  if (running) {
    if (streaming?.id) state.live = streaming;
    // Wie lange es schon läuft und wie viele Schritte es waren – ab dem Auftrag, nicht ab dem Neuladen.
    const msgs = s.messages || [];
    const at = msgs.map((m) => m.role === "user" && m._text !== undefined).lastIndexOf(true);
    activity.resumeAt = at >= 0 && msgs[at]._ts ? msgs[at]._ts * 1000 : 0;
    activity.resumeSteps = msgs.slice(at + 1).reduce((n, m) => n + (m._calls || []).filter((c) => c.name !== "todo_write").length, 0);
  } else {
    state.tools.forEach((el) => { if (el.classList.contains("running")) finishStep(el, { ok: false }); });
  }
  // Endet der Chat mit einem Plan, lässt er sich auch nach dem Neuladen noch umsetzen.
  const tail = [...(s.messages || [])].reverse().find((m) => m.role === "user" || (m.role === "assistant" && (m.content || "").trim()));
  if (tail?._plan && tail._id) addPlanActions($(`.turn.agent[data-id="${tail._id}"]`, thread));
  else if (tail?._apply && tail._id) addApplyActions($(`.turn.agent[data-id="${tail._id}"]`, thread));
  markLast();
  updateUndo();
  renderTodos(s.todos || []);
  updateEmpty();
  updateTitle();
  if (thread.childElementCount) scrollDown(true);
  else scroller.scrollTop = 0; // leerer Chat: die Startseite von oben zeigen, nicht an ihr Ende springen
  requestAnimationFrame(() => requestAnimationFrame(() => thread.classList.remove("instant")));
}

function renderTodos(todos) {
  const el = $("#todos");
  const done = todos.filter((t) => t.status === "completed").length;
  if (!todos.length || (done === todos.length && !state.busy)) {
    el.hidden = true;
    return;
  }
  el.innerHTML = `
    <div class="todos-head">
      <span class="eyebrow">Aufgaben</span>
      <span class="todos-bar"><i style="width:${(done / todos.length) * 100}%"></i></span>
      <span class="todos-count">${done} von ${todos.length}</span>
    </div>
    <ul class="todo-list">${todos.map((t) =>
      `<li class="todo ${t.status}"><i>${t.status === "completed" ? ICONS.check : ""}</i><span>${esc(t.content)}</span></li>`).join("")}
    </ul>`;
  el.hidden = false;
}

function updateTitle() {
  const title = state.session?.title && state.session.title !== "Neuer Chat" ? state.session.title : "";
  $("#chatTitle").textContent = title || "Neuer Chat";
  document.title = title ? `${title} – Coder` : "Coder";
}

/* ================================================================ Agent Island */

const activity = { start: 0, timer: null, steps: 0, resumeAt: 0, resumeSteps: 0 };

function startActivity() {
  activity.start = activity.resumeAt || Date.now();
  activity.steps = activity.resumeSteps;
  activity.resumeAt = activity.resumeSteps = 0;
  $("#activity").hidden = false;
  setActivity("Denkt nach …");
  tickActivity();
  clearInterval(activity.timer);
  activity.timer = setInterval(tickActivity, 1000);
}

function tickActivity() {
  const secs = Math.round((Date.now() - activity.start) / 1000);
  const steps = activity.steps ? ` · ${activity.steps} ${activity.steps === 1 ? "Schritt" : "Schritte"}` : "";
  $("#activityMeta").textContent = duration(secs) + steps;
}

function setActivity(text, icon) {
  $("#activity").classList.toggle("waiting", icon === "alert");
  $("#activityText").textContent = text;
  $("#activityIcon").innerHTML = icon && ICONS[icon] ? ICONS[icon] : `<span class="spinner"></span>`;
}

function stopActivity() {
  clearInterval(activity.timer);
  $("#activity").hidden = true;
}

function alwaysButton(req) {
  if (req.always === null) return ""; // verkettete Befehle oder rm & Co. fragen jedes Mal
  const command = req.name === "run_command" && req.always;
  const label = command ? `Immer: ${req.always}` : "Immer erlauben";
  const title = command ? `Befehle, die mit „${req.always}“ beginnen, laufen in diesem Chat ohne Rückfrage`
    : "Diese Art von Aktion läuft in diesem Chat ohne Rückfrage";
  return `<button type="button" class="btn approval-always" data-d="always" title="${esc(title)}"><span>${esc(label)}</span></button>`;
}

function showApproval(req) {
  state.approvalId = req.id;
  const step = state.tools.get(req.id);
  if (step) {
    step.classList.remove("running");
    step.classList.add("waiting");
    const host = step.parentElement.closest('.step[data-name="agent"]');
    if (host) toggleStep(host, true); // die wartende Aktion eines Sub-Agents sichtbar machen
  }
  const box = $("#approval");
  const preview = req.preview?.diff ? `<div class="approval-preview">${diffHtml(req.preview.diff)}</div>` : "";
  box.innerHTML = `
    <div class="approval-head">
      <span class="approval-icon">${ICONS[req.name] || ICONS.alert}</span>
      <div class="approval-copy">
        ${req.agent ? `<div class="approval-agent">${esc(agentName(req.agent))} möchte</div>` : ""}
        <div class="approval-title">${esc(APPROVAL_TITLE[req.name] || `${req.name} ausführen?`)}</div>
        <code class="approval-target">${esc(req.summary)}</code>
      </div>
    </div>
    ${preview}
    <div class="approval-actions">
      <button type="button" class="btn ghost" data-d="deny">Ablehnen <kbd>Esc</kbd></button>
      <span class="spacer"></span>
      ${alwaysButton(req)}
      <button type="button" class="btn primary" data-d="allow">Erlauben <kbd>Strg ⏎</kbd></button>
    </div>`;
  $$("[data-d]", box).forEach((b) => b.addEventListener("click", () => answerApproval(b.dataset.d)));
  box.hidden = false;
  setActivity("Wartet auf deine Freigabe", "alert");
}

function answerApproval(decision) {
  if (!state.approvalId) return;
  send({ type: "permission", id: state.approvalId, decision });
  const step = state.tools.get(state.approvalId);
  if (step && decision !== "deny") {
    step.classList.remove("waiting");
    step.classList.add("running");
  }
  hideApproval();
  setActivity(decision === "deny" ? "Abgelehnt" : "Wird ausgeführt …");
}

function hideApproval() {
  state.approvalId = null;
  const box = $("#approval");
  box.hidden = true;
  box.innerHTML = "";
}

/* ================================================================ Rückfragen */

// Der Agent fragt nach: Antworten als Zeilen (Klick oder Ziffer), eine eigene Antwort – hier oder in der Eingabe –,
// oder Überspringen, dann entscheidet er selbst. Bei „multiple“ lassen sich mehrere wählen.
function showQuestion(q) {
  state.question = { ...q, picked: new Set() };
  const box = $("#question");
  const multi = !!q.multiple;
  const options = q.options || [];
  const head = [q.agent ? `${esc(agentName(q.agent))} fragt` : "", q.count > 1 ? `Frage ${q.index} von ${q.count}` : ""]
    .filter(Boolean).join(" · ");
  const rows = options.map((o, i) => `
      <button type="button" class="q-option" data-i="${i}"${multi ? ' role="checkbox" aria-checked="false"' : ""}>
        <kbd>${i + 1}</kbd>
        <span class="q-text"><span class="q-label">${esc(o.label)}${o.recommended ? " <em>empfohlen</em>" : ""}</span>${o.description ? `<span class="q-desc">${esc(o.description)}</span>` : ""}</span>
        ${multi ? `<span class="q-check">${ICONS.check}</span>` : ""}
      </button>`).join("");
  box.innerHTML = `
    <div class="question-head">
      <span class="question-icon">${ICONS.ask_user}</span>
      <div class="question-copy">
        ${head ? `<div class="question-meta">${head}</div>` : ""}
        <div class="question-title">${esc(q.question)}</div>
      </div>
    </div>
    ${rows ? `<div class="question-options"${multi ? ' role="group"' : ""}>${rows}</div>` : ""}
    <form class="question-other">
      <input class="question-text" placeholder="${options.length ? "Eigene Antwort …" : "Deine Antwort …"}" aria-label="Eigene Antwort" autocomplete="off" spellcheck="false">
      <button type="submit" class="btn${multi || !options.length ? " primary" : ""}">Antworten</button>
    </form>
    <div class="question-actions">
      <button type="button" class="btn ghost" data-q="skip">Überspringen <kbd>Esc</kbd></button>
      <span class="question-hint">${multi ? "Mehrere möglich · dann Antworten" : options.length ? "Klick oder Ziffer wählt" : ""}</span>
    </div>`;
  $$(".q-option", box).forEach((b) => b.addEventListener("click", () => pickOption(Number(b.dataset.i))));
  $(".question-other", box).addEventListener("submit", (e) => {
    e.preventDefault();
    answerQuestion({ text: $(".question-text", box).value });
  });
  $("[data-q=skip]", box).addEventListener("click", () => answerQuestion({ skipped: true }));
  box.hidden = false;
  setActivity("Wartet auf deine Antwort", "ask_user");
  updatePlaceholder();
  updateSendState();
  // Wer gerade in der Eingabe schreibt, behält den Fokus – Enter dort beantwortet die Frage.
  if (!input.value.trim()) ($(".q-option", box) || $(".question-text", box)).focus({ preventScroll: true });
  scrollDown();
}

function pickOption(i) {
  const q = state.question;
  const option = q?.options?.[i];
  if (!option) return;
  if (!q.multiple) return answerQuestion({ choices: [option.label] });
  if (q.picked.has(i)) q.picked.delete(i);
  else q.picked.add(i);
  const row = $(`#question .q-option[data-i="${i}"]`);
  row?.classList.toggle("on", q.picked.has(i));
  row?.setAttribute("aria-checked", String(q.picked.has(i)));
}

function answerQuestion({ choices = null, text = "", skipped = false } = {}) {
  const q = state.question;
  if (!q) return;
  const picked = choices ?? [...q.picked].sort((a, b) => a - b).map((i) => q.options[i].label);
  text = String(text || "").trim();
  if (!skipped && !picked.length && !text) {
    toast(q.multiple ? "Wähle mindestens eine Antwort – oder überspringe die Frage." : "Wähle eine Antwort oder schreib eine eigene.");
    return;
  }
  send({ type: "answer", id: q.id, choices: skipped ? [] : picked, text: skipped ? "" : text, skipped });
  hideQuestion();
  setActivity(skipped ? "Coder entscheidet selbst …" : "Denkt nach …");
}

function hideQuestion() {
  const box = $("#question");
  const hadFocus = box.contains(document.activeElement);
  state.question = null;
  box.hidden = true;
  box.innerHTML = "";
  updatePlaceholder();
  updateSendState();
  if (hadFocus) input.focus({ preventScroll: true });
}

/* Nach einem Plan: umsetzen – mit Auto-Edit oder jede Änderung einzeln freigeben – oder weiter planen. */
const PLAN_GO = "Setze den Plan jetzt Schritt für Schritt um und prüfe am Ende, ob alles läuft.";
const APPLY_GO = "Setze die Änderung aus deiner letzten Antwort jetzt im Projekt um und prüfe sie.";

// Chat: Die Antwort zeigt eine Änderung – umgesetzt wird sie erst im Modus Normal, mit Freigabe.
function addApplyActions(el) {
  if (!el || $(".plan-go", el)) return;
  $$(".plan-go", thread).forEach((b) => b.remove());
  const bar = document.createElement("div");
  bar.className = "plan-go apply-go";
  bar.innerHTML = `
    <span class="plan-go-text">${ICONS.chat}<span>Im Chat ändert Coder nichts.</span></span>
    <span class="plan-go-actions">
      <button type="button" class="btn primary small" data-apply="ask">Im Modus Normal umsetzen</button>
      <button type="button" class="btn ghost small" data-apply="keep">Nur reden</button>
    </span>`;
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-apply]");
    if (!b) return;
    if (b.dataset.apply === "keep") return bar.remove();
    if (state.busy) return toast("Der Agent arbeitet noch.");
    bar.remove();
    setMode("ask");
    addUser("Änderung umsetzen");
    scrollDown(true);
    state.runAgent = null;
    state.runLabeled = false;
    send({ type: "send", text: APPLY_GO, display: "Änderung umsetzen" });
    setBusy(true);
    setActivity("Denkt nach …");
  });
  $(".receipt", el).before(bar);
}

function addPlanActions(el) {
  if (!el || $(".plan-go", el)) return;
  $$(".plan-go", thread).forEach((b) => b.remove()); // nur der jüngste Plan lässt sich umsetzen
  const bar = document.createElement("div");
  bar.className = "plan-go";
  bar.innerHTML = `
    <span class="plan-go-text">${ICONS.plan}<span>Plan fertig – umsetzen?</span></span>
    <span class="plan-go-actions">
      <button type="button" class="btn primary small" data-plan="auto-edit">Mit Auto-Edit umsetzen</button>
      <button type="button" class="btn small" data-plan="ask">Jede Änderung freigeben</button>
      <button type="button" class="btn ghost small" data-plan="keep">Weiter planen</button>
    </span>`;
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-plan]");
    if (b) runPlan(b.dataset.plan, bar);
  });
  $(".receipt", el).before(bar);
}

function runPlan(choice, bar) {
  if (choice === "keep") {
    bar.remove();
    input.focus();
    toast("Schreib, was am Plan anders werden soll.");
    return;
  }
  if (state.busy) return toast("Der Agent arbeitet noch.");
  bar.remove();
  setMode(choice);
  addUser("Plan umsetzen");
  scrollDown(true);
  state.runAgent = null;
  state.runLabeled = false;
  send({ type: "send", text: PLAN_GO, display: "Plan umsetzen" });
  setBusy(true);
  setActivity("Denkt nach …");
}

/* ================================================================ Live-Stream */

let renderCost = 0; // wie lange das letzte Neusetzen der entstehenden Antwort gedauert hat

function queueRender() {
  if (state.renderQueued) return;
  state.renderQueued = true;
  // Höchstens ~15 Mal pro Sekunde neu setzen: weniger Umbruch-Flackern, Text und Knöpfe bleiben greifbar.
  // Wird eine Antwort lang und teuer, seltener – sonst bleibt zwischen den Bildern keine Zeit fürs Tippen.
  setTimeout(() => requestAnimationFrame(() => {
    state.renderQueued = false;
    const live = state.live;
    if (!live) return;
    const t0 = performance.now();
    const md = $(".md", live.el);
    md.innerHTML = markdown(live.text);
    renderCost = performance.now() - t0;
    const last = md.lastElementChild;
    // Nach den Messwerten ist die Antwort fertig – ein verspätetes Nachzeichnen setzt keinen Cursor mehr.
    if (last && !last.classList.contains("code") && !live.final) last.classList.add("cursor");
    if (live.thinking) setThinking(live.el, live.thinking, !live.text);
    scrollDown();
  }), Math.min(400, Math.max(60, renderCost * 4)));
}

const handlers = {
  session(ev) {
    const before = state.session;
    if (ev.session.workspace !== state.session?.workspace) state.ext = null; // Agents hängen am Ordner
    // Wer den Chat wechselt, während eine Nachricht noch wartet: Sie kommt zurück in die Eingabe.
    if (queue.length && state.session?.id !== ev.session.id) dropQueued([...queue], "Die wartende Nachricht steht wieder in der Eingabe.");
    for (const q of queue.splice(0)) clearTimeout(q.timer);
    renderQueue();
    state.session = ev.session;
    state.loop = null;
    renderLoop();
    const kind = kindOf(ev.session);
    const incognito = !!ev.session.incognito;
    if (before?.incognito && before.id !== ev.session.id && state.reconnecting) {
      toast("Die Verbindung war zu lange weg – der Inkognito-Chat ist nicht mehr da.", { error: true, ms: 6000 });
    }
    state.reconnecting = false;
    if (!incognito) { // ein Inkognito-Chat wird nirgends gemerkt – auch nicht als „zuletzt offen“
      store.set(`coder.session.${kind}`, ev.session.id);
      if (kind === "code") store.set("coder.session", ev.session.id);
    }
    $("#app").classList.toggle("incognito", incognito);
    $("#incognitoBar").hidden = !incognito;
    $("#incognitoBtn").setAttribute("aria-pressed", String(incognito));
    if (!ev.running) setBusy(false); // der vorige Chat darf weiterarbeiten – dieser hier ruht
    hideApproval();
    hideQuestion();
    renderSession(ev.session, !!ev.running);
    if (state.tab !== "ide" && state.tab !== kind) switchTab(kind, { open: false });
    renderSessions();
    updateWorkspace();
    setContext(null);
    updatePlaceholder();
    sessionArrived();
  },
  busy(ev) { setBusy(ev.busy); },
  term(ev) {
    if (ev.id !== term.id) return;
    if (ev.state === "start") {
      $("#termState").title = ev.cwd || "";
    } else if (ev.data) {
      termWrite(ev.data);
    } else if (ev.state === "error") {
      term.running = false;
      termWrite(`${ev.message}\n`, "term-bad");
      renderTermState();
    } else if (ev.state === "end") {
      term.running = false;
      const secs = nf.format((Date.now() - term.started) / 1000);
      const how = ev.code === 0 ? "Fertig" : ev.code === null ? "Beendet" : `Exit-Code ${ev.code}`;
      termWrite(`\n${how} · ${secs} s\n`, ev.code === 0 ? "term-ok" : "term-bad");
      renderTermState();
    }
  },
  title(ev) {
    if (state.session?.id === ev.id) {
      state.session.title = ev.title;
      updateTitle();
    }
    refreshSessions();
  },
  presence(ev) {
    shareUI.online = ev.online;
    renderPresence();
  },
  auth(ev) {
    toast(ev.message, { error: true, ms: 8000 });
    setTimeout(() => { location.href = "/login"; }, 2500);
  },
  cowork(ev) {
    if (ev.state === "board") {
      const at = Date.now();
      cowork.tasks = ev.tasks.map((t) => ({ ...t, _at: at }));
      cowork.parallel = ev.parallel;
      cowork.running = ev.running;
      cowork.queued = ev.queued;
      renderCowork();
    } else if (ev.state === "task") {
      const task = { ...ev.task, _at: Date.now() };
      const i = cowork.tasks.findIndex((t) => t.id === task.id);
      if (i < 0) cowork.tasks.push(task);
      else cowork.tasks[i] = task;
      cowork.running = ev.running;
      cowork.queued = ev.queued;
      paintTask(task);
      // Fertig heißt: Es gibt einen Chat dazu – der gehört in die Liste der Chats.
      if (task.status !== "queued" && task.status !== "running" && i >= 0
          && cowork.tasks[i].status !== ev.task.status) refreshSessions();
    } else if (ev.state === "undo") {
      toast(ev.ok ? `Zurückgenommen: ${(ev.restored || []).join(", ") || "nichts"}` : ev.message,
        { error: !ev.ok, ms: 4500 });
    } else if (ev.state === "rejected") {
      toast(ev.message, { error: true });
    }
  },
  loop(ev) {
    if (ev.state === "end") {
      state.loop = null;
      renderLoop();
      addNotice(`Schleife beendet nach ${ev.round} ${ev.round === 1 ? "Runde" : "Runden"} – ${ev.reason}.`);
      return;
    }
    state.loop = { ...ev, waiting: ev.state === "waiting" };
    renderLoop();
  },
  sharpened(ev) {
    state.sharpening = null;
    const btn = $("#sharpenBtn");
    btn.disabled = false;
    btn.classList.remove("busy");
    if (!ev.ok) return toast(ev.message || "Das Schärfen ging nicht.", { error: true });
    input.value = ev.text;
    autosize();
    updateSendState();
    input.focus();
    input.setSelectionRange(ev.text.length, ev.text.length);
    toast(ev.changed ? (ev.kind === "image" ? "Bildprompt geschärft – sieh ihn dir an" : "Auftrag geschärft – sieh ihn dir an")
      : "Der Auftrag war schon klar genug.");
  },
  report(ev) {
    if (!ev.ok) return toast(ev.message || "Der Bericht ging nicht.", { error: true });
    window.open(ev.url, "_blank", "noopener");
    toast("Bericht geöffnet – mit Strg+P drucken.");
  },
  status(ev) {
    setActivity(ev.text);
    setModelDot("busy");
  },
  model(ev) {
    state.plan = ev.plan;
    state.config.model = ev.model;
    const actual = ev.plan.actual;
    if (actual) state.loaded = [actual, ...state.loaded.filter((m) => m.name !== actual.name)];
    updateModelPill();
    updateStart();
  },
  profile(ev) { state.runAgent = ev.agent; },
  assistant_start(ev) {
    const label = state.runAgent && !state.runLabeled ? state.runAgent : null;
    state.runLabeled = state.runLabeled || !!label;
    state.live = { id: ev.id, el: addAgent(ev.id, label), text: "", thinking: "" };
    setActivity("Denkt nach …");
    scrollDown();
  },
  thinking(ev) {
    if (!state.live) return;
    state.live.thinking += ev.text;
    queueRender();
  },
  text(ev) {
    if (!state.live) return;
    if (!state.live.text) setActivity("Schreibt …");
    state.live.text += ev.text;
    queueRender();
  },
  stats(ev) {
    const live = state.live;
    if (!live) return;
    live.final = true;
    live.el.raw = live.text;
    $(".md", live.el).innerHTML = markdown(live.text);
    if (live.thinking) setThinking(live.el, live.thinking, false);
    setReceipt(live.el, ev.stats);
    markLast();
  },
  tool_call(ev) {
    const parent = state.live?.el || addAgent("");
    addStep(parent, ev);
    if (ev.name !== "todo_write") activity.steps++;
    tickActivity();
    if (ev.name === "agent") setActivity(`@${ev.args.agent} übernimmt`, "agent");
    else setActivity(`${TOOL_VERB[ev.name] || ev.name} ${ev.name === "todo_write" ? "" : ev.summary}`.trim(), ev.name);
    scrollDown();
  },
  permission(ev) { showApproval(ev); },
  question(ev) { showQuestion(ev); },
  plan_ready(ev) {
    addPlanActions($(`.turn.agent[data-id="${ev.id}"]`, thread));
    scrollDown();
  },
  apply_ready(ev) {
    addApplyActions($(`.turn.agent[data-id="${ev.id}"]`, thread));
    scrollDown();
  },
  tool_running() { },
  tool_result(ev) {
    finishStep(state.tools.get(ev.id), ev);
    if (state.approvalId === ev.id) hideApproval();
    if (ev.name === "memory_write") memoryUI.data = null; // neue Notiz: Liste und Vorschläge frisch laden
    setActivity("Denkt nach …");
    scrollDown();
  },
  todos(ev) {
    state.session.todos = ev.todos;
    renderTodos(ev.todos);
  },
  context(ev) { setContext(ev); },
  speech(ev) { onSpeech(ev); },
  compacted(ev) { addCompacted(ev.summary); },
  notice(ev) { addNotice(ev.text); },
  error(ev) { addError(ev.message); },
  controller(ev) {
    if (ev.state === "start") {
      state.live = null; // die nächste Antwort beginnt unter der Prüfung
      addController(ev);
      setActivity(`Kontrolle · ${ev.model} ${REASON[ev.reason] || "prüft"} …`, "controller");
    } else {
      finishController(state.tools.get(ev.id), ev);
      setActivity("Denkt nach …");
    }
    markLast();
    scrollDown();
  },
  recall(ev) { addRecallNote(lastUserTurn(), ev.notes); },
  files(ev) { addFilesNote(lastUserTurn(), ev.files); },
  vision(ev) { addVisionNote(lastUserTurn(), ev); },
  watchdog(ev) {
    addNotice(ev.text);
    setActivity(ev.text, "alert");
  },
  assistant_discard(ev) {
    if (state.live?.id !== ev.id) return;
    state.live.el.remove();
    state.live = null;
    markLast();
  },
  memory_changed() { memoryUI.data = null; },
  // Werkzeugaufrufe, die das Modell als Text geschrieben hat, verschwinden aus der Antwort
  assistant_text(ev) {
    if (state.live?.id !== ev.id) return;
    state.live.text = ev.text;
    queueRender();
  },
  changes(ev) {
    filesChanged((ev.files || []).map((f) => f.path));
    addChanges(ev);
    markLast();
    scrollDown();
  },
  undone(ev) {
    clearTimeout(undoLast.timer);
    const block = $$(".changes", thread).find((b) => b.dataset.turn === ev.turn);
    if (block) {
      block.classList.add("undone");
      $("[data-undo]", block).disabled = false;
    }
    addUndoNotice(ev);
    updateUndo();
    scrollDown();
  },
  undo_failed(ev) {
    clearTimeout(undoLast.timer);
    $$(".changes [data-undo]", thread).forEach((b) => (b.disabled = false));
    toast(ev.message, { error: true });
  },
  queued(ev) {
    const item = queue.find((q) => q.id === ev.id);
    if (!item) return;
    item.confirmed = true;
    clearTimeout(item.timer);
    renderQueue();
  },
  queue_rejected(ev) {
    const item = queue.find((q) => q.id === ev.id);
    if (item) dropQueued([item], ev.message);
  },
  queued_taken(ev) {
    const item = takeFromQueue(ev.id);
    addUser(item?.text ?? ev.text);
    markLast();
    scrollDown(true);
  },
  unqueued(ev) {
    if (!ev.ok) toast("Zu spät – der Agent hatte die Nachricht schon gelesen.");
  },
  queue_dropped(ev) {
    dropQueued(ev.items || [], "Nicht gesendet – die Nachricht steht wieder in der Eingabe.");
  },
  done(ev) {
    setBusy(false);
    hideApproval();
    hideQuestion();
    state.runAgent = null;
    state.runLabeled = false;
    $$(".md .cursor", thread).forEach((n) => n.classList.remove("cursor")); // auch an früheren Antworten
    state.live = null;
    state.tools.forEach((el) => { if (el.classList.contains("running") || el.classList.contains("waiting")) finishStep(el, { ok: false }); });
    $$(".turn.agent", thread).forEach((a) => { if (!a.textContent.trim() && !$(".step", a)) a.remove(); });
    markLast();
    if (state.session && ev.session) state.session.title = ev.session.title;
    updateTitle();
    refreshSessions();
    refreshLoaded();
    renderTodos(state.session?.todos || []);
    updateUndo();
  },
};

/* Ereignisse eines Sub-Agents landen eingerückt in seinem Schritt statt im Hauptverlauf. */
const subHandlers = {
  assistant_start(ev, host) {
    host.dataset.live = "";
    $(".agent-live", host).textContent = "";
  },
  text(ev, host) {
    host.dataset.live = (host.dataset.live || "").slice(-2000) + ev.text;
    $(".agent-live", host).textContent = host.dataset.live.replace(/\s+/g, " ").trim().slice(-160);
  },
  tool_call(ev, host) {
    addStep($(".agent-body", host), ev);
    const count = $$(".sub-steps > .step", host).length;
    $(".step-stat", host).textContent = `${count} ${count === 1 ? "Schritt" : "Schritte"}`;
    $(".agent-live", host).textContent = "";
    if (ev.name !== "todo_write") activity.steps++;
    tickActivity();
    setActivity(`${agentName(ev.agent)} · ${TOOL_VERB[ev.name] || ev.name} ${ev.summary}`.trim(), ev.name);
    scrollDown();
  },
  tool_result(ev) {
    finishStep(state.tools.get(ev.id), ev);
    if (state.approvalId === ev.id) hideApproval();
    if (ev.name === "memory_write") memoryUI.data = null;
    setActivity(`${agentName(ev.agent)} arbeitet …`, ev.agent === "kontrolle" ? "controller" : "agent");
    scrollDown();
  },
  status(ev) { setActivity(`${agentName(ev.agent)} · ${ev.text}`); },
};

/* ================================================================ WebSocket */

let reconnectDelay = 800;
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  state.ws = ws;
  let opened = false;
  ws.onopen = () => {
    opened = true;
    reconnectDelay = 800;
    const kind = state.tab === "talk" ? "talk" : "code";
    const remembered = store.get(`coder.session.${kind}`) || (kind === "code" ? store.get("coder.session") : "");
    state.reconnecting = !!state.session;
    send({ type: "open", session_id: state.session?.id || remembered, kind, incognito: !!state.session?.incognito });
  };
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.parent) {
      const host = state.tools.get(ev.parent);
      if (host) subHandlers[ev.type]?.(ev, host);
      return;
    }
    handlers[ev.type]?.(ev);
  };
  ws.onclose = (e) => {
    sessionArrived(); // wer auf den Chat wartet, wartet nicht ewig
    if (e.code === 4401) {
      location.href = "/login"; // nicht angemeldet – oder das Konto gibt es nicht mehr
      return;
    }
    // Ältere Server lehnen den Handshake ohne Anmeldung ab: Der Browser sieht dann nur 1006. Einmal nachfragen,
    // ob die Anmeldung noch gilt – sonst verbände sich das Fenster endlos neu, statt zur Anmeldung zu gehen.
    if (e.code === 1006 && !opened && state.me && !state.me.local) {
      fetch("/api/state", { cache: "no-store" }).then((r) => { if (r.status === 401) location.href = "/login"; }).catch(() => { });
    }
    if (term.running) {
      term.running = false;
      termWrite("\nVerbindung weg – der Befehl wurde beendet.\n", "term-bad");
      renderTermState();
    }
    setBusy(false);
    if (queue.length) dropQueued([...queue], "Verbindung unterbrochen – die Nachricht steht wieder in der Eingabe.");
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.6, 8000);
  };
}

function send(msg) {
  if (state.ws?.readyState === WebSocket.OPEN) {
    if (msg.type === "open" || msg.type === "new") expectSession();
    state.ws.send(JSON.stringify(msg));
  } else toast("Keine Verbindung zum Coder-Server.", { error: true });
}

// Ein Chat wird geöffnet: Bis er da ist, wartet das Senden (submit) – höchstens ein paar Sekunden.
function expectSession() {
  if (state.opening) return;
  let done;
  const wait = new Promise((resolve) => (done = resolve));
  const opening = { wait, done };
  state.opening = opening;
  setTimeout(() => sessionArrived(opening), 4000);
}
function sessionArrived(which = state.opening) {
  if (!which || state.opening !== which) return;
  state.opening = null;
  which.done();
}

/* ================================================================ Toolbar & Status */

function setBusy(busy) {
  state.busy = busy;
  $("#app").classList.toggle("busy", busy);
  $("#sendBtn").setAttribute("aria-label", busy ? "Stoppen" : "Senden");
  $("#sendBtn").title = busy ? "Stoppen (Esc)" : "Senden (Enter)";
  if (busy) startActivity();
  else stopActivity();
  updateSendState();
  updatePlaceholder();
  updateUndo();
  if (!busy) updateModelPill();
}

/* ================================================================ Kontext und Verbrauch */

// Woraus der Kontext besteht – dieselbe Reihenfolge wie im Balken.
const CTX_PARTS = [
  ["system", "Auftrag", "Systemprompt, Projektanweisungen, Notizen aus dem Gedächtnis"],
  ["tools", "Werkzeuge", "Beschreibungen der Werkzeuge, die das Modell aufrufen kann"],
  ["chat", "Verlauf", "deine Nachrichten und die Antworten"],
  ["output", "Ausgaben", "was Werkzeuge zurückgegeben haben – Dateien, Befehle, Suchen"],
];

function renderCtxPop() {
  const box = $("#ctxPop");
  const ev = state.context;
  if (!ev || !ev.max) {
    box.innerHTML = `<div class="effort-pop-head"><span class="eyebrow">Kontext</span></div>
      <p class="effort-hint">Wird nach der ersten Antwort gemessen.</p>`;
    return;
  }
  const parts = ev.parts || { chat: ev.used };
  const free = Math.max(0, ev.max - ev.used);
  const usage = ev.usage || {};
  const seg = CTX_PARTS.filter(([key]) => parts[key] > 0)
    .map(([key, label]) => `<i class="seg-${key}" style="width:${(parts[key] / ev.max) * 100}%" title="${esc(label)}"></i>`).join("")
    + `<i class="seg-free" style="width:${(free / ev.max) * 100}%"></i>`;
  const rows = CTX_PARTS.filter(([key]) => parts[key] > 0).map(([key, label, hint]) =>
    `<li title="${esc(hint)}"><i class="seg-${key}"></i><span>${esc(label)}</span><b>${nf.format(parts[key])}</b></li>`).join("")
    + `<li><i class="seg-free"></i><span>Frei</span><b>${nf.format(free)}</b></li>`;
  const used = [`${nf.format(usage.prompt || 0)} Prompt`, `${nf.format(usage.completion || 0)} Antwort`,
    usage.turns ? `${usage.turns} ${usage.turns === 1 ? "Anfrage" : "Anfragen"}` : ""].filter(Boolean).join(" · ");
  box.innerHTML = `
    <div class="effort-pop-head"><span class="eyebrow">Kontext</span>
      <span class="effort-pop-value">${nf.format(ev.used)} von ${nf.format(ev.max)} Token</span></div>
    <div class="ctx-stack" role="img" aria-label="Aufteilung des Kontexts">${seg}</div>
    <ul class="ctx-legend">${rows}</ul>
    <p class="effort-facts">Ab 80 % verdichtet Coder den Verlauf automatisch – ältere Werkzeugausgaben schon ab 60 %.</p>
    <div class="ctx-actions">
      <span class="effort-facts">Diese Sitzung: ${esc(used)}</span>
      <button type="button" class="btn small" data-ctx="compact">Verlauf verdichten</button>
    </div>`;
  $("[data-ctx=compact]", box)?.addEventListener("click", () => {
    if (state.busy) return toast("Der Agent arbeitet noch.");
    closeCtx();
    send({ type: "compact" });
    toast("Verlauf wird verdichtet …");
  });
}

function openCtx() {
  renderCtxPop();
  $("#ctxPop").hidden = false;
  $("#ctxMeter").setAttribute("aria-expanded", "true");
}

function closeCtx(refocus = false) {
  $("#ctxPop").hidden = true;
  $("#ctxMeter").setAttribute("aria-expanded", "false");
  if (refocus) $("#ctxMeter").focus({ preventScroll: true });
}

$("#ctxMeter").addEventListener("click", () => ($("#ctxPop").hidden ? openCtx() : closeCtx()));
document.addEventListener("mousedown", (e) => {
  if (!$("#ctxPop").hidden && !e.target.closest("#ctxPop, #ctxMeter")) closeCtx();
});

function setContext(ev) {
  state.context = ev;
  if (!$("#ctxPop").hidden) renderCtxPop();
  const meter = $("#ctxMeter");
  if (!ev || !ev.max) {
    $("#ctxBar").style.strokeDashoffset = 50.27;
    $("#ctxText").textContent = "Kontext";
    meter.classList.remove("high");
    meter.title = "Kontextauslastung – wird nach der ersten Antwort gemessen";
    return;
  }
  const ratio = Math.min(1, ev.used / ev.max);
  $("#ctxBar").style.strokeDashoffset = 50.27 * (1 - ratio);
  $("#ctxText").textContent = `${pct(ratio)} von ${kctx(ev.max)}`;
  meter.classList.toggle("high", ratio > 0.7);
  meter.title = `${nf.format(ev.used)} von ${nf.format(ev.max)} Token · verdichtet automatisch ab 80 %`;
}

function setModelDot(cls) {
  $("#modelDot").className = `dot ${cls || ""}`;
}

// Im Chat-Tab kann ein eigenes Modell antworten (Einstellungen → Chat-Tab).
function shownModel() {
  return (state.tab === "talk" && state.config?.talk_model) || state.config?.model;
}

function liveModel() {
  return state.loaded.find((m) => m.name === shownModel());
}

function updateModelPill() {
  const model = shownModel();
  $("#modelName").textContent = model || "Modell wählen";
  const live = liveModel();
  if (state.ollama && !state.ollama.ok) {
    setModelDot("off");
    $("#modelMeta").textContent = "Ollama offline";
  } else if (live) {
    const ctx = live.context_length || state.plan?.num_ctx;
    setModelDot(live.gpu_share >= 0.999 ? "ok" : "warn");
    $("#modelMeta").textContent = `${ctx ? kctx(ctx) + " · " : ""}${pct(live.gpu_share)} GPU`;
  } else {
    setModelDot("");
    $("#modelMeta").textContent = model ? "nicht geladen" : "";
  }
}

function updateStart() {
  const ws = currentWorkspace();
  const talk = state.tab === "talk";
  const incognito = talk && !!state.session?.incognito;
  $("#startTitle").textContent = incognito ? "Inkognito" : talk ? "Chat" : basename(ws) || "Coder";
  $("#startPath").textContent = incognito ? "Nichts wird gesichert – kein Verlauf, kein Gedächtnis"
    : talk ? "Reden und recherchieren – ohne Projekt, ohne Dateien" : ltr(ws);
  $("#startPath").title = talk ? "" : ws;
  const status = $("#startStatus");
  const live = liveModel();
  const model = shownModel();
  let dot = "", text;
  if (state.ollama && !state.ollama.ok) {
    dot = "off";
    text = "Ollama ist nicht erreichbar – starte Ollama";
  } else if (live) {
    dot = live.gpu_share >= 0.999 ? "ok" : "warn";
    const ctx = live.context_length || state.plan?.num_ctx;
    text = `${model} · ${ctx ? kctx(ctx) + " Kontext · " : ""}${pct(live.gpu_share)} GPU`;
  } else if (model) {
    text = `${model} · lädt beim ersten Senden`;
  } else {
    text = "Das beste Modell wird automatisch gewählt";
  }
  status.innerHTML = `<span class="dot ${dot}"></span><span>${esc(text)}</span>`;
  renderStartExtras();
}

// Unter den festen Zeilen: deine eigenen Prompts für diesen Tab – und solange keine Anweisungen da sind, ein Hinweis.
function renderStartExtras() {
  const own = (state.ext?.commands || []).filter((c) => c.editable && offeredIn(c));
  $("#startPrompts").hidden = !own.length || state.tab === "ide";
  // Lange Namen bekommen eine breitere Spalte – für alle Zeilen gleich, damit die Beschreibungen fluchten.
  const longest = Math.max(0, ...own.slice(0, 6).map((c) => c.name.length + 1));
  $("#ownPrompts").style.setProperty("--cmd-w", `${Math.min(220, Math.max(104, Math.ceil(longest * 8.2) + 6))}px`);
  $("#ownPrompts").innerHTML = own.slice(0, 6).map((c) => `
    <button class="cmd-row" data-prompt="/${esc(c.name)} "><code>/${esc(c.name)}</code><span>${esc(c.description)}</span>${ICONS.chevron}</button>`).join("")
    + (own.length > 6 ? `<button class="cmd-row more" data-open-prompts><code>…</code><span>Alle ${own.length} Prompts ansehen</span>${ICONS.chevron}</button>` : "");
  if (!state.ext && !renderStartExtras.loading && state.config && state.me !== undefined) {
    renderStartExtras.loading = true;
    loadExtensions().then(() => renderStartExtras()).catch(() => { }).finally(() => { renderStartExtras.loading = false; });
  }
  const c = state.config || {};
  const incognito = state.tab === "talk" && !!state.session?.incognito;
  const bare = !PERSONAL_KEYS.slice(1).some((k) => String(c[k] || "").trim());
  const hint = $("#startHint");
  hint.hidden = !serverHas("1.12.0") || !bare || incognito || store.get("coder.hint.personal") === "0";
  if (!hint.hidden && !hint.firstChild) {
    hint.innerHTML = `${ICONS.person}<span>Sag Coder, wer du bist und wie er antworten soll – das gilt dann in jedem Chat.</span>
      <button type="button" class="link-btn" data-hint-open>Eigene Anweisungen</button>
      <button type="button" class="icon-btn small" data-hint-close aria-label="Hinweis ausblenden" title="Ausblenden">${ICONS.cross}</button>`;
  }
}

function activeThumbRect() {
  const seg = $("#modeSeg");
  const active = $("button.on", seg);
  if (!active) return null;
  const box = seg.getBoundingClientRect();
  const r = active.getBoundingClientRect();
  return { x: r.left - box.left, w: r.width };
}

let thumbRect = null;
let thumbFrame = 0;
function drawThumb(rect) {
  thumbRect = rect;
  $("#segThumb").style.width = `${rect.w}px`;
  $("#segThumb").style.transform = `translateX(${rect.x}px)`;
}

function setMode(mode, persist = true) {
  const seg = $("#modeSeg");
  const thumb = $("#segThumb");
  const start = thumbRect || activeThumbRect(); // wo der Regler gerade steht, auch mitten in einer Bewegung
  seg.dataset.mode = mode;
  cancelAnimationFrame(thumbFrame);
  thumb.style.transition = "none";
  seg.classList.toggle("instant", !persist); // Laden und Größenänderung: ohne Bewegung
  $$("button", seg).forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  if (persist && start) {
    // Der Regler gleitet vom alten zum neuen Modus, während sich die Namen öffnen und schließen.
    // Das Ziel wird jedes Bild neu gemessen, weil die Knöpfe dabei ihre Breite ändern.
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 480);
      const eased = 1 - (1 - p) ** 4;
      const to = activeThumbRect();
      drawThumb({ x: start.x + (to.x - start.x) * eased, w: start.w + (to.w - start.w) * eased });
      if (p < 1) thumbFrame = requestAnimationFrame(step);
      else thumb.style.transition = "";
    };
    thumbFrame = requestAnimationFrame(step);
  } else {
    drawThumb(activeThumbRect());
    void seg.offsetWidth;
    seg.classList.remove("instant");
    thumb.style.transition = "";
  }
  if (persist && state.config && state.config.permission_mode !== mode) {
    state.config.permission_mode = mode;
    api("/api/config", { method: "POST", body: { permission_mode: mode } })
      .then(() => {
        if (mode === "yolo") toast("Autonom: Befehle laufen ohne Rückfrage.");
        else if (mode === "chat" && !serverHas("1.6.0")) {
          toast("Der Chat-Modus braucht einen Neustart von Coder – bis dahin fragt Coder vor Änderungen wie im Modus Normal.", { ms: 7000 });
        } else if (mode === "chat") toast("Chat: Coder redet, erklärt und schlägt nach – ändert nichts.");
      })
      .catch((e) => toast(e.message, { error: true }));
  }
  updatePlaceholder();
}

// Die Oberfläche kommt sofort, der Python-Server erst nach einem Neustart: Neues nur versprechen, wenn er es kann.
function serverHas(min) {
  const have = String(state.version || "0").split(".").map(Number);
  const want = min.split(".").map(Number);
  for (let i = 0; i < 3; i++) if ((have[i] || 0) !== (want[i] || 0)) return (have[i] || 0) > (want[i] || 0);
  return true;
}

function currentWorkspace() {
  // Der Agent arbeitet im Ordner des offenen Chats; neue Chats übernehmen den gewählten Workspace.
  return state.session?.workspace || state.config?.workspace || "";
}

function updateWorkspace() {
  const ws = currentWorkspace();
  const name = basename(ws);
  const title = `Workspace ändern (Strg+O)\n${ws}`;
  $("#workspaceName").textContent = name || "Workspace";
  $("#workspacePath").textContent = ltr(ws);
  $("#workspaceBtn").title = title;
  $("#wsChipName").textContent = name || "Workspace";
  $("#wsChip").title = title;
  $("#settingsWsPath").textContent = ltr(ws);

  const hw = state.hardware;
  const parts = [];
  if (hw?.gpus?.length) parts.push(`${hw.gpus[0].name.replace(/^NVIDIA (GeForce )?/, "")} · ${gb(hw.vram_total)}`);
  else if (hw) parts.push("CPU");
  if (state.ollama) parts.push(state.ollama.ok ? `Ollama ${state.ollama.version}` : "Ollama offline");
  $("#hwHint").textContent = parts.join(" · ");
  updateStart();
}

async function refreshLoaded() {
  try {
    const data = await api("/api/loaded");
    state.loaded = data.loaded;
    state.hardware = data.hardware;
    if (!state.busy && !state.modelLoading) { // sonst überschreibt die Abfrage „wird geladen …“
      updateModelPill();
      updateStart();
    }
  } catch { /* Server kurz weg */ }
}

/* ================================================================ Sidebar */

async function refreshSessions() {
  try {
    state.sessions = await api("/api/sessions");
    renderSessions();
  } catch { /* ignorieren */ }
}

function renderSessions() {
  const list = $("#sessionList");
  const q = $("#search").value.trim().toLowerCase();
  const startOfDay = new Date().setHours(0, 0, 0, 0) / 1000;
  const groups = [["Heute", startOfDay], ["Gestern", startOfDay - 86400], ["Letzte 7 Tage", startOfDay - 6 * 86400], ["Älter", -Infinity]];
  const buckets = groups.map(() => []);
  const kind = state.tab === "talk" ? "talk" : "code";
  for (const s of state.sessions) {
    if ((s.kind || "code") !== kind) continue; // Code und Chat haben je ihre eigene Liste
    if (q && !`${s.title} ${s.workspace}`.toLowerCase().includes(q)) continue;
    buckets[groups.findIndex(([, t]) => s.updated >= t)].push(s);
  }
  list.innerHTML = "";
  buckets.forEach((items, gi) => {
    if (!items.length) return;
    const head = document.createElement("div");
    head.className = "session-group eyebrow";
    head.textContent = groups[gi][0];
    list.append(head);
    for (const s of items) {
      const row = document.createElement("div");
      row.className = `session${state.session?.id === s.id ? " active" : ""}`;
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      row.title = `${s.title}\n${s.workspace}`;
      const meta = [whenLabel(s.updated), kind === "talk" ? "" : basename(s.workspace), s.model].filter(Boolean).join(" · ");
      const run = s.running && state.session?.id !== s.id ? `<span class="session-run">arbeitet</span> · ` : "";
      row.innerHTML = `
        <span class="session-text">
          <span class="session-title">${esc(s.title || "Ohne Titel")}</span>
          <span class="session-meta">${run}${esc(meta)}</span>
        </span>
        <button class="icon-btn del" type="button" aria-label="Chat löschen" title="Löschen">${ICONS.trash}</button>`;
      row.addEventListener("click", (e) => {
        if (e.target.closest(".del")) return deleteSession(s);
        if (!leavingIncognito()) return;
        send({ type: "open", session_id: s.id }); // ein laufender Auftrag arbeitet im Hintergrund weiter
        $("#app").classList.remove("open");
      });
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target === row) row.click();
        else if (e.key === "F2" && e.target === row) renameSession(s, row);
      });
      $(".session-title", row).addEventListener("dblclick", (e) => {
        e.stopPropagation();
        renameSession(s, row);
      });
      row.dataset.sid = s.id;
      list.append(row);
    }
  });
  if (!list.childElementCount) {
    list.innerHTML = `<div class="session-empty">${q ? "Keine passenden Chats." : kind === "talk" ? "Deine Gespräche erscheinen hier – getrennt von den Code-Chats." : "Deine Chats erscheinen hier."}</div>`;
  }
  // Arbeitet ein anderer Chat im Hintergrund, sieht die Liste ab und zu nach, ob er fertig ist.
  clearTimeout(renderSessions.poll);
  if (state.sessions.some((s) => s.running && s.id !== state.session?.id)) renderSessions.poll = setTimeout(refreshSessions, 5000);
}

// Umbenennen direkt in der Liste: Enter übernimmt, Esc oder Klick daneben lässt den alten Titel.
// Wer einen Inkognito-Chat mit Inhalt verlässt, verliert ihn – das fragen wir einmal nach.
function leavingIncognito() {
  if (!state.session?.incognito || !thread.childElementCount) return true;
  return confirm("Den Inkognito-Chat verlassen? Er wird nirgends gesichert und ist danach weg.");
}

function renameSession(s, row = $(`#sessionList [data-sid="${s.id}"]`)) {
  if (!serverHas("1.11.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  const title = row && $(".session-title", row);
  if (!title) {
    const name = prompt("Neuer Titel", s.title || "");
    if (name !== null) saveTitle(s, name);
    return;
  }
  const field = document.createElement("input");
  field.className = "session-rename";
  field.value = s.title || "";
  field.setAttribute("aria-label", "Titel des Chats");
  title.replaceWith(field);
  field.focus();
  field.select();
  let done = false;
  const finish = (keep) => {
    if (done) return;
    done = true;
    if (keep && field.value.trim() && field.value.trim() !== s.title) saveTitle(s, field.value);
    else renderSessions();
  };
  field.addEventListener("click", (e) => e.stopPropagation());
  field.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  });
  field.addEventListener("blur", () => finish(true));
}

async function saveTitle(s, name) {
  try {
    const res = await api(`/api/sessions/${s.id}`, { method: "PATCH", body: { title: name } });
    s.title = res.title;
    if (state.session?.id === s.id) {
      state.session.title = res.title;
      updateTitle();
    }
  } catch (e) {
    toast(e.message, { error: true });
  }
  refreshSessions();
}

async function deleteSession(s) {
  if (!confirm(`„${s.title}“ löschen?`)) return;
  try {
    await api(`/api/sessions/${s.id}`, { method: "DELETE" });
    if (state.session?.id === s.id) send({ type: "new", kind: kindOf(s) });
    refreshSessions();
  } catch (e) {
    toast(e.message, { error: true });
  }
}

/* ================================================================ Eingabe */

const input = $("#input");

function autosize() {
  input.style.height = "auto";
  // Leeres Feld nicht messen: Chromium zählt einen umbrechenden Placeholder mit.
  if (input.value) input.style.height = `${Math.min(input.scrollHeight, 240)}px`;
}
window.addEventListener("resize", autosize);

function updateSendState() {
  // Mit offener Rückfrage und Text wird aus „Stoppen“ „Antworten“ – ohne Text bleibt es beim Stoppen.
  const answering = !!(state.question && input.value.trim());
  $("#app").classList.toggle("answering", answering);
  const btn = $("#sendBtn");
  btn.setAttribute("aria-label", answering ? "Antworten" : state.busy ? "Stoppen" : "Senden");
  btn.title = answering ? "Antworten (Enter)" : state.busy ? "Stoppen (Esc)" : "Senden (Enter)";
  btn.disabled = !answering && !state.busy && !input.value.trim() && !attachments.some((a) => a.id);
}

/* ================================================================ Bilder anhängen */

const attachments = []; // { id, url, name, pending }
const MAX_IMAGES = 6;

async function imageData(file) {
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) throw new Error(`${file.name || "Das Bild"} lässt sich nicht lesen.`);
  const scale = Math.min(1, 1568 / Math.max(bitmap.width, bitmap.height)); // mehr Details erkennen Bildmodelle nicht
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  // Screenshots bleiben PNG – scharfe Schrift –, Fotos werden JPEG
  return canvas.toDataURL(file.type === "image/png" ? "image/png" : "image/jpeg", 0.9);
}

async function addImages(files) {
  const images = [...(files || [])].filter((f) => f.type.startsWith("image/"));
  for (const file of images) {
    if (attachments.length >= MAX_IMAGES) {
      toast(`Höchstens ${MAX_IMAGES} Bilder pro Nachricht.`);
      break;
    }
    const item = { id: null, url: URL.createObjectURL(file), name: file.name || "Bild", pending: true };
    attachments.push(item);
    renderAttachments();
    try {
      const saved = await api("/api/images", { method: "POST", body: { data: await imageData(file) } });
      item.id = saved.id;
    } catch (e) {
      const at = attachments.indexOf(item);
      if (at >= 0) attachments.splice(at, 1);
      URL.revokeObjectURL(item.url);
      toast(e.message, { error: true });
    }
    item.pending = false;
    renderAttachments();
  }
  if (images.length) input.focus();
  return images.length > 0;
}

function renderAttachments() {
  const box = $("#attachments");
  box.hidden = !attachments.length;
  box.innerHTML = attachments.map((a, i) => `
    <figure class="attachment${a.pending ? " pending" : ""}">
      <img src="${a.url}" alt="${esc(a.name)}">
      <button type="button" class="attachment-remove" data-remove="${i}" aria-label="${esc(a.name)} entfernen">${ICONS.cross}</button>
    </figure>`).join("");
  updateSendState();
}

$("#attachments").addEventListener("click", (e) => {
  const remove = e.target.closest("[data-remove]");
  if (!remove) return;
  const [item] = attachments.splice(Number(remove.dataset.remove), 1);
  if (item) URL.revokeObjectURL(item.url);
  renderAttachments();
  input.focus();
});
$("#attachBtn").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", (e) => {
  addImages(e.target.files);
  e.target.value = "";
});
input.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (!files.some((f) => f.type.startsWith("image/"))) return;
  e.preventDefault();
  addImages(files);
});

thread.addEventListener("click", (e) => {
  const image = e.target.closest("[data-image]");
  if (!image) return;
  const box = $("#lightbox");
  $("img", box).src = `/api/images/${encodeURIComponent(image.dataset.image)}`;
  box.hidden = false;
});
$("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });
thread.addEventListener("click", (e) => { if (e.target.closest("[data-undo]")) undoLast(); });
$("#queue").addEventListener("click", (e) => {
  const button = e.target.closest("[data-unqueue]");
  const item = button && takeFromQueue(button.dataset.unqueue);
  if (!item) return;
  send({ type: "unqueue", id: item.id });
  input.value = [input.value.trim(), item.text].filter(Boolean).join("\n\n");
  autosize();
  updateSendState();
  input.focus();
});

// tabs: wo der Befehl etwas bedeutet (ohne Angabe: überall). role: wer ihn braucht. optional: geht auch ohne Angabe.
const BUILTIN_COMMANDS = [
  { name: "new", description: "Neuer Chat", run: () => $("#newChat").click() },
  { name: "compact", description: "Verlauf verdichten und Kontext freimachen", run: () => send({ type: "compact" }) },
  { name: "undo", tabs: ["code"], description: "Dateiänderungen des letzten Auftrags zurücknehmen", run: () => undoLast() },
  { name: "agents", tabs: ["code"], role: "read", description: "Agents ansehen, anlegen und bearbeiten", run: () => openAgents() },
  { name: "prompts", description: "Eigene Prompts ansehen, anlegen und bearbeiten", run: () => openPrompts() },
  { name: "anweisungen", need: "1.12.0", description: "Eigene Anweisungen: wer du bist, wie Coder antworten soll",
    run: () => openSettings("set-personal") },
  { name: "stil", need: "1.12.0", hint: "[knapp|erklärend|…]", optional: true,
    description: "Antwortstil wechseln", run: (args) => (args ? setStyle(parseStyle(args), { loud: true }) : openSettings("set-personal")) },
  { name: "memory", tabs: ["code"], role: "admin", description: "Gedächtnis mit allen Notizen öffnen", run: () => openMemory() },
  { name: "workspace", tabs: ["code"], role: "admin", description: "Workspace wählen", run: () => openWorkspace() },
  { name: "models", role: "admin", description: "Modell wählen und laden", run: () => openModels() },
  { name: "settings", description: "Einstellungen", run: () => openSettings() },
  { name: "loop", tabs: ["code"], hint: "[5m|3x] <auftrag>", description: "Denselben Auftrag wiederholen – /loop stop beendet",
    run: (args) => startLoop(args) },
  { name: "prompt", tabs: ["code"], hint: "<auftrag>", description: "Den Auftrag schärfen lassen, bevor er losgeht",
    run: (args) => sharpen(args) },
  { name: "print", description: "Bericht zum Ausdrucken – für eine Abgabe oder den Prüfer",
    run: () => makeReport() },
];
const COMMAND_ALIASES = { clear: "new", model: "models", schleife: "loop", drucken: "print", bericht: "print",
  style: "stil", instructions: "anweisungen", userprompt: "anweisungen" };
const builtinHere = (c) => (!c.tabs || c.tabs.includes(promptTab())) && (!c.role || roleAtLeast(c.role))
  && (!c.need || serverHas(c.need));

function expandCommand(cmd, args) {
  const words = args ? args.split(/\s+/) : [];
  let text = cmd.template.replace(/\$ARGUMENTS/g, args).replace(/\$(\d)/g, (_, n) => words[n - 1] ?? "");
  if (args && !/\$ARGUMENTS|\$\d/.test(cmd.template)) text += `\n\n${args}`;
  return text;
}

/* ================================================================ Schleife, Schärfen, Bericht */

function startLoop(args) {
  if (!args) return toast("/loop 5m npm test · /loop 3x /review · /loop stop");
  if (/^(stop|aus|ende|halt)$/i.test(args.trim())) {
    if (!state.loop) return toast("Es läuft keine Schleife.");
    send({ type: "loop_stop" });
    return;
  }
  if (state.busy || state.loop) return toast("Erst den laufenden Auftrag stoppen.");
  send({ type: "loop", text: args });
}

function renderLoop() {
  const bar = $("#loopBar");
  const lp = state.loop;
  bar.hidden = !lp;
  if (!lp) return;
  $("#loopLabel").textContent = lp.waiting ? "Schleife wartet" : "Schleife";
  $("#loopText").textContent = `${lp.label} · ${lp.task}`;
}

$("#loopStop").addEventListener("click", () => send({ type: "loop_stop" }));

// Den Auftrag schärfen: das Ergebnis landet in der Eingabe, gesendet wird es erst, wenn du es willst.
function sharpen(text) {
  const raw = (text ?? input.value).trim();
  if (!raw) return toast("Schreib zuerst, was Coder tun soll.");
  if (state.busy) return toast("Das geht, sobald der Agent fertig ist.");
  if (state.sharpening) return;
  state.sharpening = raw;
  const btn = $("#sharpenBtn");
  btn.disabled = true;
  btn.classList.add("busy");
  send({ type: "sharpen", text: raw, kind: "auto" });
}

$("#sharpenBtn").addEventListener("click", () => sharpen());

function updateSharpenChip() {
  $("#sharpenBtn").hidden = state.config?.preprompt === false;
}

const DESIGNS = ["ruhig", "terminal", "papier"];

// Hell oder dunkel: die eigene Wahl schlägt die Übergabe aus dem App-Fenster, die schlägt das Systemthema.
function applyTheme(name) {
  const wanted = ["light", "dark"].includes(name) ? name : null;
  store.set("coder.theme", wanted || "auto");
  document.documentElement.dataset.theme = wanted
    || (["light", "dark"].includes(forcedTheme) ? forcedTheme
      : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  return wanted || "auto";
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  api("/api/config", { method: "POST", body: { theme: next } })
    .then((cfg) => { state.config = cfg; })
    .catch(() => { /* bleibt bis zum nächsten Start lokal */ });
  toast(next === "dark" ? "Dunkel" : "Hell");
}

// Aussehen umstellen. Gemerkt wird es zusätzlich lokal, damit beim nächsten Start nichts aufblitzt.
function applyDesign(name) {
  const design = DESIGNS.includes(name) ? name : "ruhig";
  document.documentElement.dataset.design = design;
  store.set("coder.design", design);
  return design;
}

const DESIGN_NAMEN = { ruhig: "Ruhig", terminal: "Terminal", papier: "Papier" };

// Reihum durch die Varianten – für den schnellen Vergleich, ohne die Einstellungen zu öffnen.
function toggleDesign() {
  const jetzt = document.documentElement.dataset.design || "ruhig";
  const next = DESIGNS[(DESIGNS.indexOf(jetzt) + 1) % DESIGNS.length];
  applyDesign(next);
  api("/api/config", { method: "POST", body: { design: next } })
    .then((cfg) => { state.config = cfg; })
    .catch(() => { /* bleibt bis zum nächsten Start lokal */ });
  toast(`Design: ${DESIGN_NAMEN[next]}`);
}

/* ================================================================ Aufwand */

const EFFORTS = ["low", "medium", "high", "max"];
const EFFORT_NAMES = { low: "Niedrig", medium: "Mittel", high: "Hoch", max: "Maximal" };
const EFFORT_HINT = {
  low: "Schnell: nur das Nötigste lesen, kleinste Änderung, ohne Denkmodus und Kontrolle.",
  medium: "Ausgewogen: prüft, wenn es wenig kostet – wie bisher.",
  high: "Gründlich: liest mehr, denkt nach, testet jede Änderung.",
  max: "Alles: plant, sucht die Ursache, ergänzt Tests, Kontrolle mit einer Runde mehr.",
};
const EFFORT_FACTOR = { low: 0.5, medium: 1, high: 1.5, max: 2 };

function currentEffort() {
  const level = state.config?.effort;
  return EFFORTS.includes(level) ? level : "medium";
}

// Was die Stufe konkret ändert – aus den Einstellungen gerechnet, nicht geschätzt.
function effortFacts(level) {
  const c = state.config || {};
  const steps = Math.max(5, Math.round((Number(c.max_steps) || 50) * EFFORT_FACTOR[level]));
  const think = { low: "aus", medium: c.think ? "an" : "aus", high: "an", max: "an" }[level];
  const rounds = (Number(c.controller_rounds) || 2) + (level === "max" ? 1 : 0);
  const control = c.controller === false || level === "low" ? "aus" : `bis ${rounds} Nachbesserungen`;
  return `Bis ${steps} Schritte · Denkmodus ${think} · Kontrolle ${control}`;
}

function updateEffortChip() {
  const level = currentEffort();
  const btn = $("#effortBtn");
  btn.dataset.level = String(EFFORTS.indexOf(level));
  $("#effortLabel").textContent = EFFORT_NAMES[level];
  btn.title = `Aufwand: ${EFFORT_NAMES[level]} – ${EFFORT_HINT[level]}`;
  const range = $("#effortRange");
  range.value = String(EFFORTS.indexOf(level));
  range.setAttribute("aria-valuetext", EFFORT_NAMES[level]);
  $("#effortValue").textContent = EFFORT_NAMES[level];
  $("#effortHint").textContent = EFFORT_HINT[level];
  $("#effortFacts").textContent = effortFacts(level);
}

function setEffort(level, { quiet = false } = {}) {
  if (!EFFORTS.includes(level) || !state.config) return;
  const before = currentEffort();
  state.config.effort = level;
  updateEffortChip();
  if (before === level) return;
  api("/api/config", { method: "POST", body: { effort: level } })
    .then((cfg) => { if (cfg.effort !== level) toast("Der laufende Server kennt den Aufwand noch nicht – nach einem Neustart von Coder geht es."); })
    .catch((e) => toast(e.message, { error: true }));
  if (!quiet) toast(`Aufwand: ${EFFORT_NAMES[level]}`);
}

// keyboard: Nur wer mit der Tastatur kommt, bekommt den Fokus auf den Regler – sonst bliebe ein Rahmen stehen.
function openEffort(keyboard = true) {
  updateEffortChip();
  $("#effortPop").hidden = false;
  $("#effortBtn").setAttribute("aria-expanded", "true");
  if (keyboard) $("#effortRange").focus({ preventScroll: true });
}

function closeEffort(refocus = false) {
  $("#effortPop").hidden = true;
  $("#effortBtn").setAttribute("aria-expanded", "false");
  if (refocus) $("#effortBtn").focus({ preventScroll: true });
}

$("#effortBtn").addEventListener("click", (e) => ($("#effortPop").hidden ? openEffort(e.detail === 0) : closeEffort()));
$("#effortRange").addEventListener("input", (e) => setEffort(EFFORTS[Number(e.target.value)] || "medium", { quiet: true }));
$("#effortRange").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    closeEffort(true);
  }
});
document.addEventListener("mousedown", (e) => {
  if (!$("#effortPop").hidden && !e.target.closest("#effortPop, #effortBtn")) closeEffort();
});

/* ================================================================ Farbthemen */

const COLOR_THEMES = ["standard", "nord", "solarized", "gruvbox", "github", "catppuccin", "tokyo", "rosepine", "oled", "kontrast", "farbenblind"];
const COLOR_NAMES = {
  standard: "Standard", nord: "Nord", solarized: "Solarized", gruvbox: "Gruvbox", github: "GitHub",
  catppuccin: "Catppuccin", tokyo: "Tokyo Night", rosepine: "Rosé Pine", oled: "OLED", kontrast: "Hoher Kontrast",
  farbenblind: "Farbenblind",
};

// Farben über jedes Design legen. Gemerkt wird auch lokal: So blitzt beim Start nichts auf – und ein älterer Server,
// der die Einstellung noch nicht kennt, nimmt sie einem nicht wieder weg.
function applyColors(name) {
  const palette = COLOR_THEMES.includes(name) ? name : "standard";
  if (palette === "standard") delete document.documentElement.dataset.palette;
  else document.documentElement.dataset.palette = palette;
  store.set("coder.palette", palette);
  return palette;
}

function savedColors(cfg) {
  return cfg && "palette" in cfg ? cfg.palette : store.get("coder.palette");
}

function cycleColors() {
  const now = document.documentElement.dataset.palette || "standard";
  const next = COLOR_THEMES[(COLOR_THEMES.indexOf(now) + 1) % COLOR_THEMES.length];
  applyColors(next);
  api("/api/config", { method: "POST", body: { palette: next } })
    .then((cfg) => { state.config = cfg; })
    .catch(() => { /* bleibt lokal */ });
  toast(`Farbthema: ${COLOR_NAMES[next]}`);
}

function makeReport() {
  if (!state.session?.id) return toast("In diesem Chat ist noch nichts passiert.");
  toast("Bericht wird gebaut …");
  send({ type: "report" });
}

function clearInput() {
  input.value = "";
  autosize();
  updateSendState();
}

async function submit() {
  // Gerade Tab gewechselt oder neuer Chat: erst den Chat abwarten – sonst setzt er den Verlauf zurück, nachdem die
  // Nachricht schon darin steht, und sie verschwindet vom Bildschirm.
  if (state.opening) await state.opening.wait;
  if (state.question && input.value.trim()) { // eine offene Rückfrage: der Text ist die Antwort
    answerQuestion({ text: input.value });
    clearInput();
    return;
  }
  if (state.busy) {
    send({ type: "cancel" });
    return;
  }
  if (attachments.some((a) => a.pending)) {
    toast("Das Bild wird noch vorbereitet …");
    return;
  }
  const images = attachments.filter((a) => a.id).map((a) => a.id);
  const text = input.value.trim() || (images.length ? "Was ist auf dem Bild zu sehen?" : "");
  if (!text) return;
  hideSuggest();
  let prompt = text;
  if (text.startsWith("/")) {
    const head = text.split(/\s+/)[0];
    const name = head.slice(1).toLowerCase();
    const builtin = BUILTIN_COMMANDS.find((c) => c.name === (COMMAND_ALIASES[name] || name) && builtinHere(c));
    if (builtin) {
      const args = text.slice(head.length).trim();
      if (builtin.hint && !args && !builtin.optional && builtin.name !== "loop") return toast(`/${builtin.name} ${builtin.hint}`);
      clearInput();
      builtin.run(args);
      return;
    }
    const custom = (await loadExtensions().catch(() => null))?.commands.find((c) => c.name === name);
    if (custom && !offeredIn(custom)) {
      return toast(`/${custom.name} gibt es nur im Tab ${custom.tab === "talk" ? "Chat" : "Code"}.`);
    }
    if (custom) prompt = expandCommand(custom, text.slice(head.length).trim());
  }
  if (state.ollama && !state.ollama.ok) {
    toast("Ollama ist nicht erreichbar. Starte Ollama und versuche es erneut.", { error: true });
    return;
  }
  addUser(text, images);
  scrollDown(true);
  state.runAgent = null;
  state.runLabeled = false;
  send({ type: "send", text: prompt, ...(prompt === text ? {} : { display: text }), ...(images.length ? { images } : {}) });
  setBusy(true);
  setActivity(liveModel() ? "Denkt nach …" : "Modell wird vorbereitet …");
  attachments.length = 0;
  renderAttachments();
  clearInput();
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
input.addEventListener("input", () => { autosize(); updateSendState(); updateSuggest(); });
input.addEventListener("keydown", (e) => {
  if (!$("#suggest").hidden && !e.isComposing) {
    const n = suggest.items.length;
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) {
      e.preventDefault();
      suggest.index = (suggest.index + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
      renderSuggest();
      return;
    }
    if ((e.key === "Enter" || e.key === "Tab") && n && !e.shiftKey) {
      e.preventDefault();
      pickSuggest();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // sonst würde Esc den laufenden Agent stoppen
      hideSuggest();
      return;
    }
  }
  if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  if (e.ctrlKey || e.metaKey) return; // Strg+Enter gehört der Freigabe
  e.preventDefault();
  if (state.question) { // eine offene Rückfrage: der Text ist die Antwort – leeres Enter stoppt nichts
    if (input.value.trim()) submit();
  } else if (state.busy) queueMessage(); // während der Arbeit: für den nächsten Schritt einreihen
  else submit();
});
// Alle Zeilen der Startseite – Häufige Aufgaben, die Beispiele im Chat und deine Prompts – setzen ihren Anfang ein.
$("#empty").addEventListener("click", (e) => {
  const row = e.target.closest("[data-prompt]");
  if (row) {
    input.value = row.dataset.prompt;
    autosize();
    updateSendState();
    updateSuggest();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    return;
  }
  if (e.target.closest("[data-hint-open]")) openSettings("set-personal");
  else if (e.target.closest("[data-hint-close]")) {
    store.set("coder.hint.personal", "0");
    $("#startHint").hidden = true;
  } else if (e.target.closest("[data-open-prompts]")) openPrompts();
});

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

document.addEventListener("click", async (e) => {
  const copy = e.target.closest(".code [data-copy], [data-copy-answer]"); // Knöpfe anderswo haben eigene Wege
  if (!copy) return;
  const answer = copy.hasAttribute("data-copy-answer");
  await copyText(answer ? copy.closest(".turn.agent")?.raw || "" : copy.closest(".code").querySelector("pre").textContent);
  const label = answer ? copy : $("span", copy);
  label.textContent = "Kopiert";
  setTimeout(() => (label.textContent = "Kopieren"), 1400);
});

/* ================================================================ @Agents und /Befehle */

const suggest = { kind: null, items: [], index: 0, start: 0, seq: 0 };

async function loadExtensions(force = false) {
  const ws = currentWorkspace();
  if (!force && state.ext?.ws === ws) return state.ext;
  const q = `?workspace=${encodeURIComponent(ws)}`;
  // Wer nur chatten darf, bekommt keine Agents – die Prompts für den Tab Chat aber schon.
  const agents = roleAtLeast("read") ? api(`/api/agents${q}`) : Promise.resolve({ agents: [], tools: [] });
  const [a, c] = await Promise.all([agents, api(`/api/commands${q}`)]);
  // Ältere Server kennen keinen Tab je Prompt: Dann gilt alles fürs Projekt, wie bisher.
  const commands = c.commands.map((cmd) => ({
    tab: "code", editable: ["global", "project"].includes(cmd.source) && /^[a-z0-9][a-z0-9_-]*$/.test(cmd.name), ...cmd,
  }));
  state.ext = { ws, agents: a.agents, tools: a.tools, commands };
  return state.ext;
}

// Was ein Tab anbietet: seine eigenen Prompts und die für beide. Der Editor gilt als Code.
const promptTab = (tab = state.tab) => (tab === "talk" ? "talk" : "code");
const offeredIn = (cmd, tab = state.tab) => (cmd.tab || "code") === "all" || (cmd.tab || "code") === promptTab(tab);

function suggestContext() {
  const caret = input.selectionStart;
  if (caret !== input.selectionEnd) return null;
  const before = input.value.slice(0, caret);
  let m = before.match(/\[\[([^[\]\n]*)$/);
  if (m) return { kind: "note", query: m[1].toLowerCase(), start: caret - m[1].length - 2 };
  m = before.match(/(^|\s)@([\w-]*)$/);
  if (m) return { kind: "agent", query: m[2].toLowerCase(), start: caret - m[2].length - 1 };
  m = before.match(/^\/([\w:-]*)$/);
  if (m) return { kind: "command", query: m[1].toLowerCase(), start: 0 };
  return null;
}

async function updateSuggest() {
  const ctx = suggestContext();
  if (!ctx) return hideSuggest();
  const seq = ++suggest.seq;
  let source;
  try {
    source = ctx.kind === "note" ? await loadNotes() : await loadExtensions();
  } catch {
    return hideSuggest();
  }
  if (seq !== suggest.seq) return;
  const rank = (a) => Object.keys(SOURCE_LABEL).indexOf(a.source); // eigene Agents vor den eingebauten
  let items;
  if (ctx.kind === "note") {
    items = source.notes.map((n) => ({ name: n.title, description: n.excerpt || n.tags.map((t) => `#${t}`).join(" "),
      hint: n.vault === "project" ? "" : vaultLabel(n.vault), icon: ICONS.note, prefix: "" }));
  } else if (ctx.kind === "agent") {
    items = [...source.agents].sort((x, y) => rank(x) - rank(y)).map((a) => ({ ...a, icon: ICONS.agent, prefix: "@" }));
  } else {
    // Deine eigenen Prompts zuerst, dann die Befehle der App, dann alles Mitgelieferte.
    const offered = source.commands.filter((c) => offeredIn(c));
    items = [...offered.filter((c) => c.editable), ...BUILTIN_COMMANDS.filter((c) => builtinHere(c)),
      ...offered.filter((c) => !c.editable)].map((c) => ({ ...c, icon: ICONS.command, prefix: "/" }));
  }
  const lower = (it) => it.name.toLowerCase();
  const fits = (it) => !ctx.query || lower(it).includes(ctx.query) || (it.description || "").toLowerCase().includes(ctx.query);
  const found = items.filter(fits).sort((x, y) => lower(y).startsWith(ctx.query) - lower(x).startsWith(ctx.query));
  Object.assign(suggest, { kind: ctx.kind, items: found.slice(0, 50), index: 0, start: ctx.start });
  renderSuggest();
}

function renderSuggest() {
  const box = $("#suggest");
  const rows = suggest.items.map((it, i) => `
    <button type="button" class="suggest-item" role="option" data-i="${i}" aria-selected="${i === suggest.index}">
      <span class="suggest-icon">${it.icon || ""}</span>
      <span class="suggest-name${suggest.kind === "note" ? " plain" : ""}">${it.prefix}${esc(it.name)}${it.hint ? ` <span class="suggest-hint">${esc(it.hint)}</span>` : ""}</span>
      <span class="suggest-desc">${esc(it.description)}</span>
    </button>`).join("");
  const foot = suggest.kind === "command"
    ? `<button type="button" class="suggest-foot" data-open-prompts>${ICONS.plus}<span>${roleAtLeast("admin") && serverHas("1.12.0") ? "Eigenen Prompt anlegen oder bearbeiten" : "Alle Prompts ansehen"}</span></button>`
    : "";
  box.innerHTML = `<div class="suggest-head eyebrow">${{ agent: "Agents", command: "Befehle und Prompts", note: "Notizen" }[suggest.kind]}</div>` +
    (rows || `<div class="suggest-empty">Nichts gefunden.</div>`) + foot;
  box.hidden = false;
  $(`[data-i="${suggest.index}"]`, box)?.scrollIntoView({ block: "nearest" });
}

function hideSuggest() {
  suggest.seq++;
  suggest.kind = null;
  $("#suggest").hidden = true;
}

function pickSuggest(i = suggest.index) {
  const item = suggest.items[i];
  if (!item) return hideSuggest();
  if (suggest.kind === "note") {
    const token = `[[${item.name}]] `;
    input.value = input.value.slice(0, suggest.start) + token + input.value.slice(input.selectionStart).replace(/^\]{0,2}\s?/, "");
    input.setSelectionRange(suggest.start + token.length, suggest.start + token.length);
  } else if (suggest.kind === "agent") {
    const token = `@${item.name} `;
    input.value = input.value.slice(0, suggest.start) + token + input.value.slice(input.selectionStart).replace(/^\s+/, "");
    input.setSelectionRange(suggest.start + token.length, suggest.start + token.length);
  } else if (item.run) {
    hideSuggest();
    clearInput();
    item.run();
    return;
  } else {
    input.value = `/${item.name} `;
  }
  hideSuggest();
  autosize();
  updateSendState();
  input.focus();
}

$("#suggest").addEventListener("mousedown", (e) => e.preventDefault()); // Fokus bleibt in der Eingabe
$("#suggest").addEventListener("click", (e) => {
  if (e.target.closest("[data-open-prompts]")) {
    hideSuggest();
    if (/^\/[\w:-]*$/.test(input.value.trim())) clearInput(); // nur der angefangene Befehl – der Rest bleibt stehen
    openPrompts();
    return;
  }
  const row = e.target.closest("[data-i]");
  if (row) pickSuggest(Number(row.dataset.i));
});
input.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== input) hideSuggest(); }, 150));

function updatePlaceholder() {
  const narrow = matchMedia("(max-width: 560px)").matches;
  const mode = state.config?.permission_mode;
  if (state.question) input.placeholder = narrow ? "Deine Antwort" : "Antwort schreiben – oder oben eine wählen";
  else if (state.busy) input.placeholder = narrow ? "Nachricht an den Agent" : "Weitere Nachricht – der Agent liest sie vor seinem nächsten Schritt";
  else if (state.tab === "talk" && state.session?.incognito) input.placeholder = narrow ? "Frag etwas – inkognito" : "Frag etwas – inkognito: nichts davon wird gesichert";
  else if (state.tab === "talk") input.placeholder = narrow ? "Frag etwas" : "Frag etwas oder lass recherchieren – Coder sucht im Netz und nennt die Quellen";
  else if (mode === "chat") input.placeholder = narrow ? "Frag etwas" : "Frag etwas – Coder erklärt, sucht und liest mit, ändert aber nichts";
  else if (mode === "plan") input.placeholder = narrow ? "Was soll geplant werden?" : "Was soll geplant werden? Coder liest, fragt nach und legt einen Plan vor";
  else input.placeholder = narrow ? "Aufgabe, @Agent oder /Befehl" : "Beschreibe eine Aufgabe – @ für Agents, / für Befehle";
}
window.addEventListener("resize", updatePlaceholder);

// [[Links]] im Chat und in Notizen öffnen die Notiz im Gedächtnis
document.addEventListener("click", (e) => {
  const link = e.target.closest(".wikilink");
  if (!link) return;
  e.preventDefault();
  const sheet = $("#memorySheet");
  const vault = link.dataset.vault || undefined;
  if (!sheet.hidden && !sheet.classList.contains("closing")) {
    setMemoryView("notes");
    showNote(link.dataset.note, vault);
  } else {
    openMemory({ title: link.dataset.note, vault });
  }
});

// Hineingezogene Dateien würden die App verlassen und die Datei öffnen – Bilder landen stattdessen in der Eingabe.
let dragDepth = 0;
const draggingFiles = (e) => !!e.dataTransfer?.types?.includes("Files");
document.addEventListener("dragenter", (e) => {
  if (!draggingFiles(e)) return;
  dragDepth++;
  $("#composer").classList.add("dropping");
});
document.addEventListener("dragleave", (e) => {
  if (!draggingFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("#composer").classList.remove("dropping");
});
document.addEventListener("dragover", (e) => { if (draggingFiles(e)) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("#composer").classList.remove("dropping");
  addImages(e.dataTransfer.files).then((added) => { if (!added) toast("Anhängen lassen sich nur Bilder."); });
});

/* ================================================================ Sheets */

let sheetReturnFocus = null;
function openSheet(id) {
  const el = $(id);
  clearTimeout(el.closeTimer); // schließt es gerade, bleibt es einfach offen
  el.classList.remove("closing");
  sheetReturnFocus = document.activeElement;
  el.hidden = false;
  // Fokus in den Dialog, damit Tab nicht hinter dem Schleier landet – ohne einen Knopf hervorzuheben.
  const sheet = $(".sheet", el);
  sheet.tabIndex = -1;
  sheet.focus({ preventScroll: true });
  return el;
}
function closeSheets() {
  const open = $$(".sheet-backdrop:not([hidden]):not(.closing)");
  // Wer lange an seinen Anweisungen geschrieben hat, verliert sie nicht mit einem Klick daneben oder Esc.
  if (settingsUI.dirty && open.some((b) => b.id === "settingsSheet")
    && !confirm("Deine Änderungen in den Einstellungen sind noch nicht gesichert. Verwerfen?")) return false;
  settingsUI.dirty = false;
  if (promptsUI.dirty && open.some((b) => b.id === "promptsSheet")
    && !confirm("Der Prompt ist noch nicht gesichert. Verwerfen?")) return false;
  promptsUI.dirty = false;
  // Die Design-Vorschau läuft live mit; wer die Einstellungen schließt, ohne zu sichern, bekommt das Alte zurück.
  if (open.some((b) => b.id === "settingsSheet") && state.config) {
    applyDesign(state.config.design);
    applyTheme(state.config.theme);
    applyColors(savedColors(state.config));
  }
  for (const backdrop of open) {
    backdrop.classList.add("closing"); // erst ausblenden, dann entfernen
    backdrop.closeTimer = setTimeout(() => {
      backdrop.hidden = true;
      backdrop.classList.remove("closing");
    }, 240);
  }
  if (open.length) sheetReturnFocus?.focus?.();
  return true;
}
$$(".sheet-backdrop").forEach((bd) => {
  bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeSheets(); });
  $$("[data-close]", bd).forEach((b) => b.addEventListener("click", () => closeSheets()));
});

async function openModels() {
  openSheet("#modelSheet");
  $("#hwStats").innerHTML = Array(3).fill(`<div class="stat"><div class="eyebrow">&nbsp;</div><div class="stat-skeleton"></div></div>`).join("");
  $("#modelList").innerHTML = `<div class="model-empty"><span class="spinner"></span></div>`;
  $("#envTips").innerHTML = "";
  try {
    renderModels(await api("/api/models"));
  } catch (e) {
    $("#hwStats").innerHTML = "";
    $("#modelList").innerHTML = `<div class="model-empty">${esc(e.message)}<br><br><button class="btn" type="button" id="retryModels">Erneut versuchen</button></div>`;
    $("#retryModels").addEventListener("click", openModels);
  }
}

// Wo ein Modell rechnet: ganz auf der GPU, geteilt mit dem RAM, nur CPU – oder zu groß für beides.
const FIT_TEXT = {
  gpu: "Passt komplett in die GPU", mixed: "GPU und Arbeitsspeicher", cpu: "Läuft auf der CPU",
  disk: "Zu groß – liest von der Platte",
};

function renderStats(hw) {
  const gpu = hw.gpus[0];
  const tiles = [
    ["Grafikkarte", gpu ? gpu.name.replace(/^NVIDIA (GeForce )?/, "") : "Keine", gpu ? `${gb(hw.vram_total)} VRAM` : "läuft auf der CPU"],
    ["VRAM frei", gpu ? gb(hw.vram_free) : "–", gpu ? `von ${gb(hw.vram_total)}` : ""],
    ["System", `${gb(hw.ram_total)} RAM`, `${hw.ram_free ? gb(hw.ram_free) + " frei · " : ""}${hw.cores} Kerne`],
  ];
  $("#hwStats").innerHTML = tiles.map(([label, value, sub]) =>
    `<div class="stat"><div class="eyebrow">${esc(label)}</div><div class="stat-value" title="${esc(value)}">${esc(value)}</div><div class="stat-sub">${esc(sub)}</div></div>`).join("");
}

function renderModels(data) {
  renderStats(data.hardware);
  const list = $("#modelList");
  if (!data.models.length) {
    list.innerHTML = `<div class="model-empty">Noch keine Modelle installiert.<br><br><code>ollama pull qwen3-coder:30b</code></div>`;
    return;
  }
  const body = list.closest(".sheet-body");
  const scrollTop = body.scrollTop;
  list.innerHTML = "";
  for (const m of data.models) {
    const p = m.profile;
    const plan = m.plan;
    const current = m.name === state.config.model;
    const share = m.loaded ? m.loaded.gpu_share : plan.gpu_share;
    const ctx = m.loaded?.context_length || plan.num_ctx;
    const caps = p.capabilities;
    const badges = [
      m.name === data.recommended ? `<span class="badge rec">Empfohlen</span>` : "",
      m.loaded ? `<span class="badge live">Geladen</span>` : "",
      caps.includes("tools") ? `<span class="badge">Tools</span>` : "",
      caps.includes("thinking") ? `<span class="badge">Denken</span>` : "",
      caps.includes("vision") ? `<span class="badge">Vision</span>` : "",
    ].join("");
    const moe = p.moe ? (p.active_params ? `MoE · ${nf.format(p.active_params / 1e9)}B aktiv` : "MoE") : "";
    const sub = [p.param_size, p.quant, gb(p.size), moe, `bis ${kctx(p.ctx_max)} Kontext`].filter(Boolean).join(" · ");
    // Wo die Gewichte liegen, entscheidet über das Tempo – bei großen Modellen mehr als die Größe selbst.
    const speed = plan.tokens_per_s ? `~${nf.format(plan.tokens_per_s)} Token/s` : "";
    const fitText = m.loaded
      ? [`Gemessen: ${pct(share)} auf der GPU`, `${kctx(ctx)} Kontext`, speed].filter(Boolean).join(" · ")
      : [FIT_TEXT[plan.fit] || `Etwa ${pct(share)} auf der GPU`, `${kctx(ctx)} Kontext`, `~${gb(plan.estimate_bytes)}`, speed]
        .filter(Boolean).join(" · ");
    const useClass = !current && m.name === data.recommended ? "btn primary" : "btn";

    const el = document.createElement("div");
    el.className = `model${current ? " current" : ""}`;
    el.innerHTML = `
      <div>
        <div class="model-title">${esc(m.name)} ${badges}</div>
        <div class="model-sub">${esc(sub)}</div>
      </div>
      <div class="model-actions">
        ${m.loaded && state.config?.backend !== "vllm" ? `<button class="btn ghost" type="button" data-unload>Entladen</button>` : ""}
        <button class="${useClass}" type="button" data-load>${current && m.loaded ? "Neu laden" : "Verwenden"}</button>
      </div>
      <div class="fit${plan.slow ? " slow" : ""}">
        <span>${fitText}</span>
        <div class="fit-bar" role="img" aria-label="${pct(share)} auf der GPU"><i class="${share >= 0.999 ? "" : "part"}" style="width:${Math.max(3, share * 100)}%"></i></div>
      </div>`;
    $("[data-load]", el).addEventListener("click", (e) => loadModel(m.name, e.currentTarget));
    $("[data-unload]", el)?.addEventListener("click", (e) => unloadModel(m.name, e.currentTarget));
    list.append(el);
  }
  renderTips(data);
  body.scrollTop = scrollTop; // nach „Verwenden“ nicht an den Anfang der Liste springen
}

function renderTips(data) {
  const current = data.models.find((m) => m.name === state.config.model) || data.models.find((m) => m.name === data.recommended);
  const notes = current ? current.plan.notes.filter((n) => !n.startsWith("OLLAMA_")) : [];
  const env = data.env || {};
  const win = data.hardware.os === "Windows";
  const wanted = { OLLAMA_FLASH_ATTENTION: "1", OLLAMA_KV_CACHE_TYPE: "q8_0", OLLAMA_NUM_PARALLEL: "1" };
  const missing = Object.entries(wanted).filter(([k, v]) => String(env[k] || "").toLowerCase() !== v);
  let html = "";
  if (notes.length) html += `<h3>${esc(current.name)}</h3><ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`;
  if (missing.length) {
    const cmds = missing.map(([k, v]) => (win ? `setx ${k} ${v}` : `export ${k}=${v}`));
    html += `<h3>Mehr Kontext bei gleichem VRAM</h3><ul>${cmds.map((c) => `<li><code>${esc(c)}</code></li>`).join("")}` +
      `<li>Danach Ollama neu starten. Der KV-Cache halbiert sich damit.</li></ul>`;
  }
  $("#envTips").innerHTML = html;
}

async function loadModel(name, btn) {
  state.modelLoading = true;
  $$("#modelList .btn").forEach((b) => (b.disabled = true));
  const width = btn.offsetWidth;
  btn.style.width = `${width}px`;
  btn.innerHTML = `<span class="spinner"></span>`;
  setModelDot("busy");
  $("#modelName").textContent = name;
  $("#modelMeta").textContent = "wird geladen …";
  try {
    const res = await api("/api/models/load", { method: "POST", body: { model: name } });
    state.config.model = name;
    state.plan = res.plan;
    state.loaded = res.loaded;
    const a = res.plan.actual;
    toast(`${name} ist bereit · ${pct(a ? a.gpu_share : res.plan.gpu_share)} GPU · ${kctx(res.plan.num_ctx)} Kontext · ${nf.format(res.plan.load_seconds)} s`);
    updateModelPill();
    updateStart();
    renderModels(await api("/api/models"));
  } catch (e) {
    toast(e.message, { error: true, ms: 5000 });
    updateModelPill();
    $$("#modelList .btn").forEach((b) => (b.disabled = false));
    btn.style.width = "";
    btn.textContent = "Verwenden";
  } finally {
    state.modelLoading = false;
  }
}

async function unloadModel(name, btn) {
  btn.disabled = true;
  try {
    const res = await api("/api/models/unload", { method: "POST", body: { model: name } });
    state.loaded = res.loaded;
    updateModelPill();
    updateStart();
    renderModels(await api("/api/models"));
  } catch (e) {
    toast(e.message, { error: true });
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- Einstellungen: Bereiche, Suche, Persönlich */

const settingsUI = { dirty: false, jumping: 0 };
// Was Gäste für sich selbst sichern dürfen (core/users.OWN_PREFS) – ab 1.12 auch Stil und eigene Anweisungen.
const PERSONAL_KEYS = ["style", "user_prompt", "user_prompt_code", "user_prompt_talk"];
const guestKeys = () => ["design", "theme", "palette", ...(serverHas("1.12.0") ? PERSONAL_KEYS : [])];

function openSettings(section) {
  const form = $("#settingsForm");
  const c = state.config;
  // Gäste stellen nur ihr Eigenes ein: Aussehen, Stil, Anweisungen. Der Rest gehört dem, der Coder verwaltet.
  const guest = !roleAtLeast("admin");
  const personal = serverHas("1.12.0");
  for (const sec of $$(".set-sec", form)) {
    sec.hidden = (guest && !("guest" in sec.dataset)) || (sec.id === "set-personal" && !personal);
  }
  for (const b of $$("#settingsNav [data-sec]")) b.hidden = $(`#${b.dataset.sec}`).hidden;
  $("#settingsSub").textContent = guest ? "Deine eigenen Einstellungen – alles andere stellt ein, wer Coder verwaltet."
    : "Gilt ab der nächsten Anfrage.";
  form.elements.palette.value = savedColors(c) || "standard"; // auch, wenn der Server das Farbthema noch nicht kennt
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "radio") { el.checked = String(c[el.name] ?? "normal") === el.value; continue; }
    if (!(el.name in c)) continue;
    if (el.type === "checkbox") el.checked = !!c[el.name];
    // Coder 1.2 speicherte „PC wach halten“ als an/aus – sonst bliebe die Auswahl leer und würde leer gesichert.
    else if (el.name === "keep_awake" && typeof c.keep_awake === "boolean") el.value = c.keep_awake ? "open" : "off";
    else {
      const value = String(c[el.name] ?? "");
      // Ein Wert, den die Auswahl nicht anbietet (von Hand in config.json, aus dem Terminal): als eigene Zeile
      // aufnehmen. Sonst stünde sie leer da – und beim Sichern würde aus 20 Rechenschritten eine 0.
      if (el.tagName === "SELECT" && value && ![...el.options].some((o) => o.value === value)) {
        el.append(new Option(`${value} (eigener Wert)`, value));
      }
      el.value = value;
    }
  }
  $$("textarea[data-counter]", form).forEach(updateCounter);
  $("#settingsSearch").value = "";
  filterSettings("");
  setSettingsDirty(false);
  openSheet("#settingsSheet");
  const target = section && !$(`#${section}`)?.hidden ? section : $$(".set-sec", form).find((s) => !s.hidden)?.id;
  form.scrollTop = 0;
  if (target) jumpToSection(target, { smooth: false, focus: section === "set-personal" });
  if (guest) return;
  loadModelOptions();
  loadImageBackend();
  loadVllm();
  micInfo(true).then(renderSpeech);
}

function setSettingsDirty(on) {
  settingsUI.dirty = on;
  const note = $("#settingsDirty");
  note.textContent = on ? "Noch nicht gesichert" : "";
  note.classList.toggle("on", on);
}

// Zeichen und ungefähre Token unter jedem Anweisungsfeld – der Prompt geht bei jedem Auftrag mit.
function updateCounter(area) {
  let count = area.nextElementSibling;
  if (!count?.classList.contains("field-count")) {
    count = document.createElement("span");
    count.className = "field-count";
    count.setAttribute("aria-live", "polite");
    area.after(count);
  }
  const len = area.value.trim().length;
  const max = Number(area.maxLength) || 4000;
  count.textContent = len ? `${nf.format(len)} von ${nf.format(max)} Zeichen · etwa ${nf.format(Math.ceil(len / 3.6))} Token` : "";
  count.classList.toggle("near", len > max * 0.9);
}

function jumpToSection(id, { smooth = true, focus = false } = {}) {
  const sec = $(`#${id}`);
  const form = $("#settingsForm");
  if (!sec || sec.hidden) return;
  if (sec.classList.contains("filtered")) { // gesucht und hier nichts gefunden: die Suche weicht dem Klick
    $("#settingsSearch").value = "";
    filterSettings("");
  }
  settingsUI.jumping = Date.now();
  markSection(id);
  form.scrollTo({ top: sectionTop(sec, form) - 4, behavior: smooth ? "smooth" : "auto" });
  if (focus) $("textarea, input:not([type=hidden]), select", sec)?.focus({ preventScroll: true });
}

// Wo ein Bereich im Scrollbereich beginnt – unabhängig davon, welches Element die Positionen trägt.
const sectionTop = (sec, form) => sec.getBoundingClientRect().top - form.getBoundingClientRect().top + form.scrollTop;

function markSection(id) {
  for (const b of $$("#settingsNav [data-sec]")) {
    const on = b.dataset.sec === id;
    if (on && b.getAttribute("aria-current") !== "true" && b.parentElement.scrollWidth > b.parentElement.clientWidth) {
      // Schmal liegt die Leiste quer: den aktiven Bereich dort in den Blick holen.
      b.parentElement.scrollTo({ left: b.offsetLeft - 16, behavior: "smooth" });
    }
    b.setAttribute("aria-current", String(on));
  }
}

// Der Bereich, dessen Überschrift gerade oben steht, leuchtet in der Leiste – außer kurz nach einem Klick dorthin.
function spySettings() {
  if (Date.now() - settingsUI.jumping < 700) return;
  const form = $("#settingsForm");
  const top = form.scrollTop + 48;
  const visible = $$(".set-sec", form).filter((s) => !s.hidden && !s.classList.contains("filtered"));
  if (!visible.length) return;
  let current = visible[0];
  for (const sec of visible) if (sectionTop(sec, form) <= top) current = sec;
  // Ganz unten angekommen: der letzte Bereich, auch wenn seine Überschrift nicht bis nach oben kommt.
  if (form.scrollTop + form.clientHeight >= form.scrollHeight - 4) current = visible[visible.length - 1];
  markSection(current.id);
}

function filterSettings(query) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const searching = words.length > 0;
  const form = $("#settingsForm");
  let total = 0;
  for (const sec of $$(".set-sec", form)) {
    const title = $(".set-title", sec).textContent.toLowerCase();
    let hits = 0;
    for (const group of $$(".list, .choice-grid", sec)) {
      let groupHits = 0;
      const label = group.previousElementSibling?.classList.contains("eyebrow") ? group.previousElementSibling : null;
      const context = `${title} ${label?.textContent || ""}`.toLowerCase();
      for (const row of group.children) {
        const note = row.matches(".row-note, .setup");
        const text = `${context} ${row.textContent} ${$("[name]", row)?.name || ""}`.toLowerCase();
        const hit = !searching || (!note && words.every((w) => text.includes(w)));
        row.classList.toggle("filtered", !hit);
        groupHits += hit && !note ? 1 : 0;
      }
      if (group.classList.contains("choice-grid") && searching) { // der Stil als Ganzes: ein Treffer zeigt alle
        const any = [...group.children].some((row) => !row.classList.contains("filtered"));
        group.querySelectorAll(".choice").forEach((row) => row.classList.toggle("filtered", !any));
      }
      group.classList.toggle("filtered", searching && !groupHits);
      label?.classList.toggle("filtered", searching && !groupHits);
      hits += groupHits;
    }
    $$(".set-lead, .set-note", sec).forEach((p) => p.classList.toggle("filtered", searching));
    sec.classList.toggle("filtered", searching && !hits);
    $(`#settingsNav [data-sec="${sec.id}"]`)?.classList.toggle("no-match", searching && !hits);
    if (!sec.hidden) total += hits;
  }
  const empty = $("#settingsEmpty");
  empty.hidden = !searching || total > 0;
  $("span", empty).textContent = query.trim();
  if (searching) form.scrollTop = 0;
  requestAnimationFrame(spySettings);
}

$("#settingsNav").addEventListener("click", (e) => {
  const b = e.target.closest("[data-sec]");
  if (b) jumpToSection(b.dataset.sec);
});
$("#settingsForm").addEventListener("scroll", () => requestAnimationFrame(spySettings), { passive: true });
$("#settingsSearch").addEventListener("input", (e) => filterSettings(e.target.value));
$("#settingsSearch").addEventListener("keydown", (e) => {
  if (e.key === "Escape" && e.target.value) { // erst die Suche leeren, dann das Fenster schließen
    e.preventDefault();
    e.stopPropagation();
    e.target.value = "";
    filterSettings("");
  } else if (e.key === "Enter") {
    e.preventDefault();
    const first = $$("#settingsForm .row:not(.filtered)").find((r) => r.offsetParent);
    $("input, select, textarea", first || document.createElement("i"))?.focus();
  }
});
$("#settingsForm").addEventListener("input", (e) => {
  if (e.target.matches("textarea[data-counter]")) updateCounter(e.target);
  setSettingsDirty(true);
});
$("#settingsForm").addEventListener("change", () => setSettingsDirty(true));
$("#settingsPrompts").addEventListener("click", () => { if (closeSheets()) openPrompts(); });

// Der Bilddienst für generate_image: läuft einer, und welche Checkpoints bietet er an?
/* Einrichten: was fehlt und wie man es bekommt – dieselbe Darstellung für Bilddienst, Diktat und vLLM. */
function renderSteps(box, steps) {
  box.hidden = !(steps && steps.length);
  box.innerHTML = (steps || []).map((s) => `
    <div class="setup-step">
      <h4>${esc(s.titel)}</h4>
      <div>${inlineText(s.text)}${s.url ? ` <a href="${esc(s.url)}" target="_blank" rel="noopener">Öffnen</a>` : ""}</div>
      ${s.command ? `<div class="setup-cmd"><pre>${esc(s.command)}</pre>
        <button type="button" class="btn ghost setup-copy" data-copy="${esc(s.command)}">Kopieren</button></div>` : ""}
    </div>`).join("");
}

function renderSetup(setup) {
  const box = $("#imageSetup");
  renderSteps(box, setup ? setup.steps : []);
  const da = setup && setup.installed;
  if (!da) return;
  // Ein Dienst, der schon auf der Platte liegt und nur gestartet werden muss, steht vor den Schritten.
  box.hidden = false;
  box.insertAdjacentHTML("afterbegin",
    `<div class="setup-found">${ICONS.check}<div><strong>${esc(da.label)}</strong> liegt schon hier:
      <code>${esc(da.path)}</code>. Starte es einmal – dann findet Coder es von allein.
      ${da.kind === "a1111" ? "Die WebUI braucht dazu <code>--api</code>." : ""}</div></div>
     <div class="setup-cmd"><pre>${esc(da.start)}</pre>
      <button type="button" class="btn ghost setup-copy" data-copy="${esc(da.start)}">Kopieren</button></div>`);
}

// Nur das Nötigste: `Code` und **fett**. Mehr Markdown braucht die Anleitung nicht.
function inlineText(text) {
  return esc(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

$("#imageSetup").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    btn.textContent = "Kopiert";
    setTimeout(() => (btn.textContent = "Kopieren"), 1400);
  } catch {
    toast("Kopieren ging nicht – markiere den Text und nimm Strg+C.", { error: true });
  }
});

async function loadImageBackend({ refresh = false } = {}) {
  const form = $("#settingsForm");
  const note = $("#imageStatus");
  const select = $("#imageModel");
  const wanted = String(state.config.image_model || "");
  const fill = (names) => {
    if (wanted && !names.includes(wanted)) names = [wanted, ...names];
    select.innerHTML = `<option value="">Erstes installiertes</option>`
      + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    select.value = wanted;
  };
  if (form.elements.image_backend.value === "off") {
    note.className = "row-note";
    note.textContent = "Aus – der Agent bekommt generate_image nicht angeboten.";
    fill([]);
    renderSetup(null);
    return;
  }
  note.className = "row-note";
  note.textContent = "Wird geprüft …";
  const url = form.elements.image_url.value.trim();
  const query = new URLSearchParams();
  if (refresh) query.set("refresh", "true");
  if (url) query.set("url", url);
  let data;
  try {
    data = await api(`/api/imagegen${query.toString() ? `?${query}` : ""}`);
  } catch (e) {
    note.textContent = e.message;
    fill([]);
    renderSetup(null);
    return;
  }
  const backend = data.backend;
  if (!backend) {
    note.textContent = data.hint || "Kein Bilddienst gefunden.";
    fill([]);
    renderSetup(data.setup || null);
    return;
  }
  renderSetup(null);
  const models = backend.models || [];
  note.className = "row-note found";
  note.textContent = `${backend.label} unter ${backend.url} · `
    + (models.length ? `${models.length} ${models.length === 1 ? "Modell" : "Modelle"}` : "kein Modell gefunden");
  fill(models);
}

let imageProbeTimer = 0;
let vllmProbeTimer = 0;
$("#settingsForm").addEventListener("input", (e) => {
  if (e.target.name === "design") document.documentElement.dataset.design = e.target.value;
  else if (e.target.name === "theme") applyTheme(e.target.value);
  else if (e.target.name === "palette") applyColors(e.target.value);
  else if (e.target.name === "image_backend") loadImageBackend({ refresh: true });
  else if (e.target.name === "speech_model") renderSpeech();
  else if (e.target.name === "backend") loadVllm({ refresh: true });
  else if (e.target.name === "vllm_url") {
    clearTimeout(vllmProbeTimer);
    vllmProbeTimer = setTimeout(() => loadVllm({ refresh: true }), 600);
  }
  else if (e.target.name === "image_url") {
    clearTimeout(imageProbeTimer);
    imageProbeTimer = setTimeout(() => loadImageBackend({ refresh: true }), 600);
  }
});

// Kontroll- und Bildmodell: Auswahl aus den installierten Modellen. „Automatisch“ nennt, wen Coder nehmen würde.
async function loadModelOptions() {
  let data;
  try {
    data = state.models && Date.now() - state.models.at < 60000 ? state.models.data : await api("/api/models");
    state.models = { at: Date.now(), data };
  } catch {
    return;
  }
  const roles = data.roles || {};
  for (const select of $$("#settingsForm select[data-models]")) {
    const vision = select.dataset.models === "vision";
    const names = data.models.filter((m) => !vision || m.profile.capabilities.includes("vision")).map((m) => m.name);
    const auto = vision ? roles.vision : ["complete", "talk"].includes(select.dataset.models) ? state.config.model : roles.controller;
    const current = String(state.config[select.name] || "");
    if (current && !names.includes(current)) names.unshift(current);
    select.innerHTML = `<option value="">${esc(auto ? `Automatisch · ${auto}` : "Automatisch")}</option>`
      + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    select.value = current;
  }
}

$("#settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const changes = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "radio") { if (el.checked) changes[el.name] = el.value; }
    else if (el.type === "checkbox") changes[el.name] = el.checked;
    else if (el.name === "temperature") changes[el.name] = el.value === "" ? null : Number(el.value);
    else if (["num_ctx", "max_auto_ctx", "max_steps", "command_timeout", "controller_rounds", "controller_interval", "watchdog", "image_size", "image_steps", "cowork_parallel"].includes(el.name)) {
      changes[el.name] = Number(el.value);
    }
    else changes[el.name] = el.value.trim();
  }
  if (!serverHas("1.12.0")) for (const key of PERSONAL_KEYS) delete changes[key]; // der alte Server kennt sie nicht
  if (!roleAtLeast("admin")) {
    const own = guestKeys();
    for (const key of Object.keys(changes)) if (!own.includes(key)) delete changes[key];
  }
  const submitBtn = $("button[type=submit]", form);
  submitBtn.disabled = true;
  try {
    state.config = await api("/api/config", { method: "POST", body: changes });
    applyDesign(state.config.design);
    applyTheme(state.config.theme);
    applyColors("palette" in state.config ? state.config.palette : changes.palette);
    updateSharpenChip();
    updateEffortChip();
    updateStyleChip();
    updateStart();
    state.ext = null; // Claude-Code-Erweiterungen können an- oder abgeschaltet worden sein
    memoryUI.data = null;
    setSettingsDirty(false);
    closeSheets();
    toast("Gesichert");
    loadState();
  } catch (err) {
    toast(err.message, { error: true, ms: 4500 });
  } finally {
    submitBtn.disabled = false;
  }
});

/* ---------------------------------------------------------------- vLLM: zweiter Modell-Server, dieselben Dateien */

async function loadVllm({ refresh = false } = {}) {
  const form = $("#settingsForm");
  const note = $("#vllmStatus");
  const box = $("#vllmSetup");
  const url = form.elements.vllm_url.value.trim();
  if (!serverHas("1.8.0")) {
    note.className = "row-note";
    note.textContent = "Dafür muss Coder einmal neu starten – dann kennt der Server auch vLLM.";
    renderSteps(box, []);
    return;
  }
  if (form.elements.backend.value !== "vllm") {
    note.className = "row-note";
    note.textContent = "Coder redet mit Ollama. vLLM lässt sich hier umstellen – die Modelldateien bleiben dieselben.";
    renderSteps(box, []);
    return;
  }
  note.className = "row-note";
  note.textContent = "Wird geprüft …";
  const query = new URLSearchParams();
  if (refresh) query.set("refresh", "true");
  if (url) query.set("url", url);
  let data;
  try {
    data = await api(`/api/vllm${query.toString() ? `?${query}` : ""}`);
  } catch (e) {
    note.textContent = e.message;
    renderSteps(box, []);
    return;
  }
  if (!data.server) {
    note.textContent = data.hint || "Kein vLLM erreichbar.";
    renderSteps(box, (data.setup || {}).steps || []);
    return;
  }
  renderSteps(box, []);
  const names = (data.server.models || []).map((m) => m.id);
  note.className = "row-note found";
  note.textContent = `vLLM ${data.server.version || ""} unter ${data.server.url} · `
    + (names.length ? names.join(", ") : "kein Modell geladen");
}

$("#vllmSetup").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    btn.textContent = "Kopiert";
    setTimeout(() => (btn.textContent = "Kopieren"), 1400);
  } catch {
    toast("Kopieren ging nicht – markiere den Text und nimm Strg+C.", { error: true });
  }
});

/* ================================================================ Workspace */

const picker = { seq: 0, timer: null };
const ROW_ARROW = ICONS.chevron.replace("<svg", '<svg class="row-arrow"');

function openWorkspace() {
  if (state.busy) return toast("Der Agent arbeitet noch – erst stoppen, dann den Ordner wechseln.");
  openSheet("#workspaceSheet");
  const field = $("#wsPath");
  field.value = currentWorkspace();
  $("#wsNative").hidden = !state.nativePicker;
  setPickerStatus("");
  browseFolder(field.value, true);
  field.focus();
  field.select();
  api("/api/folders/places").then(renderPlaces).catch(() => { /* Abkürzungen sind optional */ });
}

function setPickerStatus(text, error = false) {
  const el = $("#wsStatus");
  el.textContent = text;
  el.classList.toggle("error", error);
}

async function browseFolder(path, keepField = false) {
  const seq = ++picker.seq;
  let data;
  try {
    data = await api(`/api/folders?path=${encodeURIComponent(path)}`);
  } catch (e) {
    if (seq === picker.seq) setPickerStatus(e.message, true);
    return;
  }
  if (seq !== picker.seq) return;
  if (!keepField) $("#wsPath").value = data.path;
  const problem = data.error || (data.blocked ? `Geht nicht als Workspace: ${data.blocked}` : "");
  setPickerStatus(problem, !!problem);
  $("#wsUse").disabled = !!problem;
  if (!data.dirs) return; // Pfad ungültig: die letzte Liste bleibt stehen
  const rows = [];
  if (data.parent) {
    rows.push(`<button type="button" class="list-row" data-browse="${esc(data.parent)}">
      <span class="row-icon">${ICONS.up}</span>
      <span class="row-text"><strong>Übergeordneter Ordner</strong><span class="path">${esc(ltr(data.parent))}</span></span>
    </button>`);
  }
  for (const d of data.dirs) {
    rows.push(`<button type="button" class="list-row" data-browse="${esc(d.path)}">
      <span class="row-icon">${ICONS.folder}</span>
      <span class="row-text"><strong>${esc(d.name)}</strong></span>${ROW_ARROW}
    </button>`);
  }
  if (!data.dirs.length) rows.push(`<div class="ws-empty">Keine Unterordner</div>`);
  const list = $("#wsBrowser");
  list.innerHTML = rows.join("");
  list.scrollTop = 0;
}

function renderPlaces({ places = [], recent = [] }) {
  const current = currentWorkspace().toLowerCase();
  $("#wsRecentBlock").hidden = !recent.length;
  $("#wsRecent").innerHTML = recent.map((r) => `
    <button type="button" class="list-row" data-apply="${esc(r.path)}">
      <span class="row-icon">${ICONS.folder}</span>
      <span class="row-text"><strong>${esc(r.name)}</strong><span class="path">${esc(ltr(r.path))}</span></span>
      ${r.path.toLowerCase() === current ? `<span class="row-check" title="Aktueller Workspace">${ICONS.check}</span>` : ROW_ARROW}
    </button>`).join("");
  $("#wsPlaces").innerHTML = places.map((p) =>
    `<button type="button" class="chip" data-browse="${esc(p.path)}" title="${esc(p.path)}"><span>${esc(p.name)}</span></button>`).join("");
}

async function applyWorkspace(path) {
  const btn = $("#wsUse");
  btn.disabled = true;
  try {
    state.config = await api("/api/config", { method: "POST", body: { workspace: path } });
    closeSheets();
    // Ein Chat bleibt an seinen Ordner gebunden – ein anderer Ordner heißt: neuer Chat.
    if (state.session?.workspace !== state.config.workspace) send({ type: "new" });
    updateWorkspace();
    toast(`Workspace: ${basename(state.config.workspace)}`);
    input.focus();
  } catch (e) {
    setPickerStatus(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function pickNative() {
  const btn = $("#wsNative");
  btn.disabled = true;
  try {
    const { path } = await api("/api/folders/pick", { method: "POST", body: { start: $("#wsPath").value } });
    if (path) {
      $("#wsPath").value = path;
      await applyWorkspace(path);
    }
  } catch (e) {
    setPickerStatus(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

$("#wsForm").addEventListener("submit", (e) => {
  e.preventDefault();
  applyWorkspace($("#wsPath").value);
});
$("#wsForm").addEventListener("click", (e) => {
  const row = e.target.closest("[data-browse], [data-apply]");
  if (!row) return;
  if (row.dataset.apply) applyWorkspace(row.dataset.apply);
  else browseFolder(row.dataset.browse);
});
$("#wsPath").addEventListener("input", (e) => {
  clearTimeout(picker.timer);
  picker.timer = setTimeout(() => browseFolder(e.target.value, true), 250);
});
$("#wsNative").addEventListener("click", pickNative);

/* ================================================================ Gedächtnis */

const memoryUI = { data: null, ws: null, current: null, note: null, query: "", tag: null, view: "notes" };
const vaultLabel = (vault) => ({ project: "Projekt", global: "Global", library: "Bibliothek", missing: "Noch nicht angelegt" }[vault] || vault);

async function loadNotes(force = false) {
  const ws = currentWorkspace();
  if (!force && memoryUI.data && memoryUI.ws === ws) return memoryUI.data;
  memoryUI.data = await api(`/api/memory?workspace=${encodeURIComponent(ws)}`);
  memoryUI.ws = ws;
  return memoryUI.data;
}

function sinceLabel(ts) {
  const seconds = Date.now() / 1000 - ts;
  if (seconds < 60) return "gerade eben";
  if (seconds < 3600) return `vor ${Math.floor(seconds / 60)} Min.`;
  if (seconds < 86400) return `vor ${Math.floor(seconds / 3600)} Std.`;
  return whenLabel(ts);
}

async function openMemory(target = null) {
  const sheet = $("#memorySheet");
  if (sheet.hidden || sheet.classList.contains("closing")) openSheet("#memorySheet");
  setMemoryView("notes");
  try {
    await loadNotes(true);
  } catch (e) {
    $("#noteView").innerHTML = `<div class="note-empty"><p>${esc(e.message)}</p></div>`;
    return;
  }
  renderNoteList();
  const notes = memoryUI.data.notes;
  const remembered = notes.find((n) => n.id === memoryUI.current);
  if (target?.title) showNote(target.title, target.vault);
  else if (remembered) showNote(remembered.title, remembered.vault);
  else if (notes.length && !matchMedia("(max-width: 760px)").matches) showNote(notes[0].title, notes[0].vault);
  else renderNoteEmpty();
}

function noteRow(n) {
  const links = n.links.length + (n.backlinks || 0);
  const meta = [vaultLabel(n.vault), links ? `${links} ${links === 1 ? "Verbindung" : "Verbindungen"}` : "", sinceLabel(n.updated)]
    .filter(Boolean).join(" · ");
  return `<button type="button" class="note-row" data-note="${esc(n.title)}" data-vault="${n.vault}" aria-current="${memoryUI.current === n.id}">
    <span class="note-row-title">${n.pinned ? ICONS.pin : ""}<span>${esc(n.title)}</span></span>
    <span class="note-row-excerpt">${esc(n.excerpt)}</span>
    <span class="note-row-meta">${esc(meta)}</span>
  </button>`;
}

function renderNoteList() {
  const { notes, tags } = memoryUI.data;
  const query = memoryUI.query.toLowerCase();
  $("#noteTags").innerHTML = Object.entries(tags).slice(0, 14).map(([tag, count]) =>
    `<button type="button" class="tag-chip" data-tag="${esc(tag)}" aria-pressed="${memoryUI.tag === tag}" title="${count} ${count === 1 ? "Notiz" : "Notizen"}">#${esc(tag)}</button>`).join("");
  const visible = notes.filter((n) => (!memoryUI.tag || n.tags.includes(memoryUI.tag))
    && (!query || `${n.title} ${n.excerpt} ${n.tags.join(" ")}`.toLowerCase().includes(query)));
  const groups = [
    ["Angeheftet", visible.filter((n) => n.pinned)],
    ["Projekt", visible.filter((n) => !n.pinned && n.vault === "project")],
    ["Global", visible.filter((n) => !n.pinned && n.vault === "global")],
    ["Bibliothek", visible.filter((n) => !n.pinned && n.vault === "library")],
  ].filter(([, list]) => list.length);
  $("#noteList").innerHTML = groups.map(([label, list]) => `<span class="note-group eyebrow">${label}</span>${list.map(noteRow).join("")}`).join("")
    || `<div class="note-list-empty">${notes.length ? "Keine passenden Notizen." : "Noch keine Notizen."}</div>`;
}

async function showNote(title, vault) {
  const query = new URLSearchParams({ title, workspace: currentWorkspace() });
  if (vault && vault !== "missing") query.set("vault", vault);
  let note;
  try {
    note = await api(`/api/memory/note?${query}`);
  } catch {
    return editNote({ title, content: "", vault: "project", pinned: false, isNew: true }); // Link ins Leere: Notiz anlegen
  }
  memoryUI.current = note.id;
  memoryUI.note = note;
  $("#memoryBody").classList.add("reading");
  $$("#noteList .note-row").forEach((row) => row.setAttribute("aria-current", String(`${row.dataset.vault}:${row.dataset.note}` === note.id)));
  const tags = note.tags.map((t) => `<button type="button" class="tag-chip" data-tag="${esc(t)}">#${esc(t)}</button>`).join("");
  const backlinks = note.backlinks.length
    ? `<section class="note-backlinks"><span class="eyebrow">Verlinkt von</span><div class="list">${note.backlinks.map(noteRow).join("")}</div></section>`
    : "";
  $("#noteView").innerHTML = `
    <article class="note-read">
      <button type="button" class="btn ghost note-back" data-back>${ICONS.back}Notizen</button>
      <div class="note-meta"><span class="badge${note.vault === "library" ? " library" : ""}">${vaultLabel(note.vault)}</span>${note.pinned ? `<span class="badge rec">Angeheftet</span>` : ""}<span>${note.vault === "library" ? "Schreibgeschützt · kommt mit Coder" : `Geändert ${sinceLabel(note.updated)}`}</span></div>
      <h1 class="note-title">${esc(note.title)}</h1>
      <div class="note-tags">${tags}</div>
      <div class="md note-md">${markdown(note.content) || "<p>Diese Notiz ist noch leer.</p>"}</div>
      ${backlinks}
      <div class="note-actions">${note.vault === "library"
        ? `<button type="button" class="btn" data-note-copy>In mein Gedächtnis kopieren</button>`
        : `<button type="button" class="btn" data-note-edit>Bearbeiten</button>
        <button type="button" class="btn ghost" data-note-pin>${note.pinned ? "Lösen" : "Anheften"}</button>
        <span class="spacer"></span>
        <button type="button" class="btn ghost danger" data-note-delete>Löschen</button>`}
      </div>
    </article>`;
  // Links auf Notizen, die es noch nicht gibt, sind gestrichelt – ein Klick legt sie an
  const resolved = Object.fromEntries(Object.entries(note.resolved).map(([k, v]) => [k.toLowerCase(), v]));
  $$("#noteView .note-md .wikilink").forEach((a) => a.classList.toggle("missing", !resolved[a.dataset.note.toLowerCase()]));
  $("#noteView").scrollTop = 0;
}

function renderNoteEmpty() {
  memoryUI.current = null;
  $("#memoryBody").classList.remove("reading");
  const empty = !memoryUI.data?.notes.length;
  $("#noteView").innerHTML = `
    <div class="note-empty">${ICONS.graph}
      <strong>${empty ? "Noch keine Notizen" : "Wähle eine Notiz"}</strong>
      <p>${empty ? "Coder legt Notizen an, sobald er etwas Dauerhaftes lernt: Vorlieben, Entscheidungen, Lösungen. Oder du beginnst selbst."
        : "Links in einer Notiz führen direkt zur nächsten."}</p>
      ${empty ? `<button type="button" class="btn primary" data-note-create>Erste Notiz anlegen</button>` : ""}
    </div>`;
}

function editNote(note) {
  const isNew = !note || note.isNew;
  const n = note || { title: "", content: "", vault: "project", pinned: false };
  $("#memoryBody").classList.add("reading");
  $("#noteView").innerHTML = `
    <form class="note-edit" id="noteForm" autocomplete="off">
      <input class="note-title-input" name="title" value="${esc(n.title)}" placeholder="Titel der Notiz" maxlength="120" spellcheck="false">
      <div class="note-edit-bar">
        <div class="view-switch" role="radiogroup" aria-label="Tresor">
          <button type="button" role="radio" data-vault="project" aria-checked="${n.vault !== "global"}">Projekt</button>
          <button type="button" role="radio" data-vault="global" aria-checked="${n.vault === "global"}">Global</button>
        </div>
        <label><input type="checkbox" class="switch" name="pinned"${n.pinned ? " checked" : ""}>Angeheftet</label>
      </div>
      <textarea class="note-textarea" name="content" spellcheck="false" placeholder="Markdown. Verknüpfe mit [[Titel]], ordne mit #tags.">${esc(n.content || "")}</textarea>
      <p class="form-error" id="noteError" role="alert"></p>
      <div class="sheet-actions">
        <button type="button" class="btn ghost" data-note-cancel>Abbrechen</button>
        <button type="submit" class="btn primary">Sichern</button>
      </div>
    </form>`;
  const form = $("#noteForm");
  form.dataset.original = isNew ? "" : n.title;
  form.dataset.originalVault = isNew ? "" : n.vault;
  (n.title ? form.elements.content : form.elements.title).focus();
}

async function saveNote(form) {
  const body = {
    workspace: currentWorkspace(),
    title: form.elements.title.value,
    content: form.elements.content.value,
    vault: $("[data-vault][aria-checked=true]", form)?.dataset.vault || "project",
    pinned: form.elements.pinned.checked,
  };
  if (form.dataset.original) Object.assign(body, { original_title: form.dataset.original, original_vault: form.dataset.originalVault });
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  try {
    const note = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    showNote(note.title, note.vault);
    toast(`„${note.title}“ gesichert`);
  } catch (e) {
    $("#noteError").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

// Leitfäden der Bibliothek sind schreibgeschützt – eine Kopie im globalen Gedächtnis lässt sich anpassen.
async function copyNote(note) {
  try {
    const body = { workspace: currentWorkspace(), title: note.title, content: note.content, vault: "global" };
    const saved = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    editNote(saved);
    toast(`„${saved.title}“ liegt jetzt in deinem globalen Gedächtnis`);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

async function togglePin(note) {
  try {
    const body = { workspace: currentWorkspace(), title: note.title, vault: note.vault, content: note.content, pinned: !note.pinned };
    const saved = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    showNote(saved.title, saved.vault);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

async function deleteNote(note) {
  if (!confirm(`„${note.title}“ löschen?`)) return;
  try {
    const query = new URLSearchParams({ title: note.title, vault: note.vault, workspace: currentWorkspace() });
    await api(`/api/memory/note?${query}`, { method: "DELETE" });
    await loadNotes(true);
    renderNoteList();
    renderNoteEmpty();
    toast(`„${note.title}“ gelöscht`);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

function setMemoryView(view) {
  memoryUI.view = view;
  $$("#memorySheet .sheet-head .view-switch button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  $("#memoryBody").classList.toggle("graph-mode", view === "graph");
  $("#noteGraph").hidden = view !== "graph";
  $("#noteNew").hidden = view === "graph";
  if (view === "graph") renderGraph();
}

/* Kräftebasiertes Layout (Fruchterman-Reingold): verknüpfte Notizen ziehen sich an, alle anderen stoßen sich ab.
   Es rechnet in eigenen Koordinaten – wie groß der Graph erscheint, entscheidet erst die Ansicht. */
function layoutGraph(nodes, links) {
  const n = nodes.length;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const edges = links.map((l) => [index.get(l.source), index.get(l.target)])
    .filter(([a, b]) => a !== undefined && b !== undefined && a !== b);
  const k = 100;
  // Start auf einer Spirale statt zufällig: der Graph sieht bei jedem Öffnen gleich aus
  const pos = nodes.map((_, i) => [Math.cos(i * 2.4) * k * 0.5 * Math.sqrt(i + 1), Math.sin(i * 2.4) * k * 0.5 * Math.sqrt(i + 1)]);
  let temperature = k * 2;
  const reach = (k * 3) ** 2;
  for (let step = 0; step < 280; step++) {
    const disp = pos.map(() => [0, 0]);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i][0] - pos[j][0];
        const dy = pos[i][1] - pos[j][1];
        const d2 = dx * dx + dy * dy;
        // Nur Nachbarn stoßen sich ab: Sonst treibt ein dichter Cluster lose Notizen an den Rand,
        // und das Einpassen ins Fenster quetscht alles zusammen.
        if (d2 > reach) continue;
        const f = (k * k) / Math.max(d2, 1);
        disp[i][0] += dx * f; disp[i][1] += dy * f;
        disp[j][0] -= dx * f; disp[j][1] -= dy * f;
      }
    }
    for (const [a, b] of edges) {
      const dx = pos[a][0] - pos[b][0];
      const dy = pos[a][1] - pos[b][1];
      const f = Math.hypot(dx, dy) / k;
      disp[a][0] -= dx * f; disp[a][1] -= dy * f;
      disp[b][0] += dx * f; disp[b][1] += dy * f;
    }
    for (let i = 0; i < n; i++) {
      disp[i][0] -= pos[i][0] * 0.05; // sanfte Schwerkraft hält lose Notizen im Bild
      disp[i][1] -= pos[i][1] * 0.05;
      const len = Math.hypot(disp[i][0], disp[i][1]) || 1;
      const move = Math.min(len, temperature);
      pos[i][0] += (disp[i][0] / len) * move;
      pos[i][1] += (disp[i][1] / len) * move;
    }
    temperature = Math.max(0.5, temperature * 0.97);
  }
  return pos;
}

/* Die Ansicht: Zoomen und Verschieben ändern nur die Abstände, Punkte und Schrift behalten ihre Größe.
   Wer heranzoomt, sieht deshalb mehr Namen – nicht dieselben Namen größer. */
const GRAPH_MAX = 300;
const GRAPH_KINDS = [["project", "Projekt"], ["global", "Global"], ["library", "Bibliothek"], ["missing", "Noch nicht angelegt"]];
const graph = {
  nodes: [], pos: [], ends: [], r: [], widths: [], order: [], els: [], lines: [],
  view: { k: 1, x: 0, y: 0 }, fitK: 1, moved: false, raf: 0,
  hidden: new Set((store.get("coder.graph.hidden") || "").split(",").filter((v) => GRAPH_KINDS.some(([k]) => k === v))),
  pointers: new Map(), pan: null, pinch: null, dragged: false,
};

function graphSize() {
  const box = $("#noteGraph");
  return { w: box.clientWidth || 900, h: box.clientHeight || 560 };
}

function renderGraph() {
  const box = $("#noteGraph");
  if (!memoryUI.data) return;
  const all = memoryUI.data.graph;
  graph.nodes = graph.els = graph.lines = [];
  if (!all.nodes.length) {
    box.innerHTML = `<div class="graph-empty">Noch keine Notizen – der Graph wächst mit jeder Verknüpfung.</div>`;
    return;
  }
  const counts = {};
  for (const node of all.nodes) counts[node.vault] = (counts[node.vault] || 0) + 1;
  let nodes = all.nodes.filter((node) => !graph.hidden.has(node.vault));
  let keep = new Set(nodes.map((node) => node.id));
  let links = all.links.filter((l) => l.source !== l.target && keep.has(l.source) && keep.has(l.target));
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  for (const l of links) {
    degree.set(l.source, degree.get(l.source) + 1);
    degree.set(l.target, degree.get(l.target) + 1);
  }
  if (nodes.length > GRAPH_MAX) { // große Tresore: die am stärksten verknüpften Notizen
    nodes = [...nodes].sort((a, b) => degree.get(b.id) - degree.get(a.id)).slice(0, GRAPH_MAX);
    keep = new Set(nodes.map((node) => node.id));
    links = links.filter((l) => keep.has(l.source) && keep.has(l.target));
  }
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  graph.nodes = nodes;
  graph.ends = links.map((l) => [index.get(l.source), index.get(l.target)]);
  graph.pos = layoutGraph(nodes, links);
  graph.r = nodes.map((node) => 4 + Math.min(8, Math.sqrt(degree.get(node.id)) * 1.8));
  // Wer seinen Namen zuerst zeigen darf: die offene Notiz, angeheftete, dann die am stärksten verknüpften.
  const rank = (node) => (node.id === memoryUI.current ? 1e6 : 0) + (node.pinned ? 1e5 : 0) + degree.get(node.id) * 100 - node.title.length;
  graph.order = nodes.map((_, i) => i).sort((a, b) => rank(nodes[b]) - rank(nodes[a]));

  const lines = links.map((l) => `<line class="graph-link" data-a="${esc(l.source)}" data-b="${esc(l.target)}"/>`).join("");
  const dots = nodes.map((node, i) => {
    const label = node.title.length > 28 ? `${node.title.slice(0, 27)}…` : node.title;
    const classes = ["graph-node", node.vault, node.pinned && "pinned", node.id === memoryUI.current && "current"].filter(Boolean).join(" ");
    return `<g class="${classes}" data-id="${esc(node.id)}" data-title="${esc(node.title)}" data-vault="${node.vault}" tabindex="0" role="button" aria-label="${esc(node.title)} · ${vaultLabel(node.vault)}">`
      + `<title>${esc(node.title)}</title><circle r="${graph.r[i].toFixed(1)}"/><text y="${(graph.r[i] + 13).toFixed(1)}">${esc(label)}</text></g>`;
  }).join("");
  const canvas = nodes.length
    ? `<svg role="group" aria-label="Graph der Notizen"><g class="graph-links">${lines}</g><g class="graph-nodes">${dots}</g></svg>`
    : `<div class="graph-empty">Alles ausgeblendet – unten in der Legende wieder einblenden.</div>`;
  const legend = GRAPH_KINDS.filter(([vault]) => counts[vault]).map(([vault, label]) => {
    const on = !graph.hidden.has(vault);
    return `<button type="button" data-graph-vault="${vault}" aria-pressed="${on}" title="${on ? "Ausblenden" : "Einblenden"}"><i class="${vault}"></i>${label}<span class="graph-count">${counts[vault]}</span></button>`;
  }).join("");
  box.innerHTML = `${canvas}
    <div class="graph-legend" role="group" aria-label="Im Graph zeigen">${legend}</div>
    <div class="graph-tools"><span class="graph-hint">Scrollen zoomt · Ziehen verschiebt</span>
      <button type="button" class="icon-btn" data-graph-zoom="out" title="Verkleinern (−)" aria-label="Verkleinern">${ICONS.minus}</button>
      <button type="button" class="icon-btn" data-graph-zoom="in" title="Vergrößern (+)" aria-label="Vergrößern">${ICONS.plus}</button>
      <button type="button" class="icon-btn" data-graph-zoom="fit" title="Alles zeigen (0 oder Doppelklick)" aria-label="Alles zeigen">${ICONS.fit}</button>
    </div>`;
  graph.els = $$(".graph-node", box);
  graph.lines = $$(".graph-link", box);
  graph.widths = graph.els.map((el) => {
    const text = $("text", el);
    let width = 0;
    try { width = text.getComputedTextLength(); } catch { /* nicht gezeichnet */ }
    return width || text.textContent.length * 6.4;
  });
  fitGraph();
}

// Alles ins Bild: Rand für die Namen, unten Platz für Legende und Zoom.
function fitGraph() {
  if (!graph.nodes.length) return;
  const { w, h } = graphSize();
  const xs = graph.pos.map((p) => p[0]);
  const ys = graph.pos.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const side = Math.min(80, w * 0.12);
  const top = 40;
  const bottom = ($(".graph-legend", $("#noteGraph"))?.offsetHeight || 26) + 40; // schmal bricht die Legende um
  const k = Math.max(0.05, Math.min((w - side * 2) / Math.max(maxX - minX, 1), (h - top - bottom) / Math.max(maxY - minY, 1), 1.8));
  graph.view = {
    k,
    x: (w - (maxX - minX) * k) / 2 - minX * k,
    y: top + (h - top - bottom - (maxY - minY) * k) / 2 - minY * k,
  };
  graph.fitK = k;
  graph.moved = false;
  drawGraph();
}

function drawGraph() {
  graph.raf = 0;
  if (!graph.els.length) return;
  const { k, x, y } = graph.view;
  const at = graph.pos.map(([px, py]) => [px * k + x, py * k + y]);
  graph.els.forEach((el, i) => el.setAttribute("transform", `translate(${at[i][0].toFixed(1)} ${at[i][1].toFixed(1)})`));
  graph.lines.forEach((line, i) => {
    const [a, b] = graph.ends[i];
    line.setAttribute("x1", at[a][0].toFixed(1));
    line.setAttribute("y1", at[a][1].toFixed(1));
    line.setAttribute("x2", at[b][0].toFixed(1));
    line.setAttribute("y2", at[b][1].toFixed(1));
  });
  placeLabels(at);
}
const redrawGraph = () => { if (!graph.raf) graph.raf = requestAnimationFrame(drawGraph); };

// Wohin ein Name darf: unter den Punkt, sonst darüber, rechts oder links daneben.
// Jede Stelle: [Kasten], x, y und Ausrichtung des Textes relativ zum Punkt.
const LABEL_SPOTS = [
  (px, py, r, w) => [[px - w / 2, py + r + 2, px + w / 2, py + r + 16], 0, r + 13, "middle"],
  (px, py, r, w) => [[px - w / 2, py - r - 16, px + w / 2, py - r - 2], 0, -r - 5, "middle"],
  (px, py, r, w) => [[px + r + 3, py - 7, px + r + 5 + w, py + 7], r + 4, 4, "start"],
  (px, py, r, w) => [[px - r - 5 - w, py - 7, px - r - 3, py + 7], -r - 4, 4, "end"],
];

// Namen, die sich überdecken, über einem fremden Punkt oder unter Legende und Zoom lägen, warten –
// in der Reihenfolge ihrer Wichtigkeit. Heranzoomen schafft Platz, Überfahren zeigt sie sofort.
function placeLabels(at) {
  const box = $("#noteGraph");
  const { w, h } = graphSize();
  const origin = box.getBoundingClientRect();
  const hits = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  const dots = at.map(([px, py], i) => [px - graph.r[i], py - graph.r[i], px + graph.r[i], py + graph.r[i]]);
  const taken = $$(".graph-legend button, .graph-tools > *", box).map((el) => {
    const r = el.getBoundingClientRect();
    return [r.left - origin.left - 4, r.top - origin.top - 4, r.right - origin.left + 4, r.bottom - origin.top + 4];
  });
  for (const i of graph.order) {
    const [px, py] = at[i];
    const el = graph.els[i];
    let spot = -1;
    for (let s = 0; s < LABEL_SPOTS.length && spot < 0; s++) {
      const [b] = LABEL_SPOTS[s](px, py, graph.r[i], graph.widths[i] + 4);
      const inView = b[0] >= 0 && b[2] <= w && b[1] >= 0 && b[3] <= h;
      if (inView && !taken.some((t) => hits(t, b)) && !dots.some((d, j) => j !== i && hits(d, b))) {
        spot = s;
        taken.push(b);
      }
    }
    el.classList.toggle("quiet", spot < 0);
    if (spot >= 0 && el.spot !== spot) {
      const [, tx, ty, anchor] = LABEL_SPOTS[spot](px, py, graph.r[i], graph.widths[i]);
      const text = $("text", el);
      text.setAttribute("x", tx.toFixed(1));
      text.setAttribute("y", ty.toFixed(1));
      text.style.textAnchor = anchor; // als Stil – die Regel im Stylesheet schlägt sonst das Attribut
      el.spot = spot;
    }
  }
}

function zoomGraph(factor, px, py) {
  if (!graph.nodes.length) return;
  const { w, h } = graphSize();
  const v = graph.view;
  const cx = px ?? w / 2;
  const cy = py ?? h / 2;
  const k = Math.min(Math.max(v.k * factor, graph.fitK * 0.4), Math.max(graph.fitK * 12, 4));
  const f = k / v.k;
  graph.view = { k, x: cx - (cx - v.x) * f, y: cy - (cy - v.y) * f };
  graph.moved = true;
  redrawGraph();
}

// Beim Überfahren oder mit der Tastatur: die Notiz und ihre Nachbarn treten hervor, alles andere tritt zurück.
function focusGraphNode(node) {
  const box = $("#noteGraph");
  if (!node) {
    box.classList.remove("focus");
    return;
  }
  const id = node.dataset.id;
  const near = new Set([id]);
  graph.lines.forEach((line) => {
    const touches = line.dataset.a === id || line.dataset.b === id;
    line.classList.toggle("near", touches);
    if (touches) near.add(line.dataset.a).add(line.dataset.b);
  });
  graph.els.forEach((el) => el.classList.toggle("near", near.has(el.dataset.id)));
  box.classList.add("focus");
}

$$("#memorySheet .sheet-head .view-switch button").forEach((b) => b.addEventListener("click", () => setMemoryView(b.dataset.view)));
$("#noteSearch").addEventListener("input", (e) => {
  memoryUI.query = e.target.value.trim();
  if (memoryUI.data) renderNoteList();
});
$("#noteNew").addEventListener("click", () => editNote(null));
$("#memoryBtn").addEventListener("click", () => openMemory());
$("#memoryBody").addEventListener("submit", (e) => {
  if (e.target.id !== "noteForm") return;
  e.preventDefault();
  saveNote(e.target);
});
$("#memoryBody").addEventListener("click", (e) => {
  const tag = e.target.closest("[data-tag]");
  const row = e.target.closest(".note-row");
  const vault = e.target.closest("#noteForm [data-vault]");
  if (tag) {
    memoryUI.tag = memoryUI.tag === tag.dataset.tag ? null : tag.dataset.tag;
    renderNoteList();
    $("#memoryBody").classList.remove("reading");
  } else if (row) {
    showNote(row.dataset.note, row.dataset.vault);
  } else if (vault) {
    $$("#noteForm [data-vault]").forEach((b) => b.setAttribute("aria-checked", String(b === vault)));
  } else if (e.target.closest("[data-back]")) {
    $("#memoryBody").classList.remove("reading");
  } else if (e.target.closest("[data-note-edit]")) {
    editNote(memoryUI.note);
  } else if (e.target.closest("[data-note-pin]")) {
    togglePin(memoryUI.note);
  } else if (e.target.closest("[data-note-delete]")) {
    deleteNote(memoryUI.note);
  } else if (e.target.closest("[data-note-copy]")) {
    copyNote(memoryUI.note);
  } else if (e.target.closest("[data-note-create]")) {
    editNote(null);
  } else if (e.target.closest("[data-note-cancel]")) {
    if (memoryUI.current && memoryUI.note) showNote(memoryUI.note.title, memoryUI.note.vault);
    else renderNoteEmpty();
  }
});

const graphBox = $("#noteGraph");
const graphPoint = (e) => {
  const rect = graphBox.getBoundingClientRect();
  return [e.clientX - rect.left, e.clientY - rect.top];
};
graphBox.addEventListener("wheel", (e) => {
  if (!graph.nodes.length || !e.target.closest("svg")) return;
  e.preventDefault();
  const [px, py] = graphPoint(e);
  zoomGraph(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), px, py);
}, { passive: false });
// Ziehen verschiebt, zwei Finger zoomen. Erst ab ein paar Pixeln zählt es als Ziehen – sonst bleibt es ein Klick.
graphBox.addEventListener("pointerdown", (e) => {
  if (!e.target.closest("svg") || e.button > 0) return;
  graph.dragged = false;
  graph.pointers.set(e.pointerId, graphPoint(e));
  if (graph.pointers.size === 1) {
    graph.pan = { start: graphPoint(e), view: { ...graph.view } };
  } else if (graph.pointers.size === 2) {
    const [a, b] = [...graph.pointers.values()];
    graph.pinch = { dist: Math.max(1, Math.hypot(a[0] - b[0], a[1] - b[1])), k: graph.view.k };
    graph.pan = null;
  }
});
graphBox.addEventListener("pointermove", (e) => {
  if (!graph.pointers.has(e.pointerId)) return;
  const p = graphPoint(e);
  graph.pointers.set(e.pointerId, p);
  if (graph.pinch && graph.pointers.size >= 2) {
    const [a, b] = [...graph.pointers.values()];
    const k = graph.pinch.k * Math.hypot(a[0] - b[0], a[1] - b[1]) / graph.pinch.dist;
    zoomGraph(k / graph.view.k, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    graph.dragged = true;
    return;
  }
  if (!graph.pan) return;
  const dx = p[0] - graph.pan.start[0];
  const dy = p[1] - graph.pan.start[1];
  if (!graph.dragged && Math.hypot(dx, dy) < 4) return;
  if (!graph.dragged) {
    graph.dragged = true;
    graphBox.classList.add("panning");
    try { $("svg", graphBox).setPointerCapture(e.pointerId); } catch { /* Zeiger schon weg */ }
  }
  graph.view = { ...graph.view, x: graph.pan.view.x + dx, y: graph.pan.view.y + dy };
  graph.moved = true;
  redrawGraph();
});
const endGraphPointer = (e) => {
  graph.pointers.delete(e.pointerId);
  if (graph.pointers.size < 2) graph.pinch = null;
  if (!graph.pointers.size) {
    graph.pan = null;
    graphBox.classList.remove("panning");
  }
};
graphBox.addEventListener("pointerup", endGraphPointer);
graphBox.addEventListener("pointercancel", endGraphPointer);
graphBox.addEventListener("mouseover", (e) => {
  const node = e.target.closest(".graph-node");
  if (node && !graph.dragged) focusGraphNode(node);
});
graphBox.addEventListener("mouseout", (e) => {
  if (!e.relatedTarget?.closest?.(".graph-node")) focusGraphNode(null);
});
graphBox.addEventListener("focusin", (e) => focusGraphNode(e.target.closest(".graph-node")));
graphBox.addEventListener("focusout", () => focusGraphNode(null));
graphBox.addEventListener("click", (e) => {
  if (graph.dragged) {
    graph.dragged = false; // Ende eines Ziehens, kein Klick
    return;
  }
  const zoom = e.target.closest("[data-graph-zoom]");
  const vault = e.target.closest("[data-graph-vault]");
  const node = e.target.closest(".graph-node");
  if (zoom) {
    if (zoom.dataset.graphZoom === "fit") fitGraph();
    else zoomGraph(zoom.dataset.graphZoom === "in" ? 1.4 : 1 / 1.4);
  } else if (vault) {
    const kind = vault.dataset.graphVault;
    if (graph.hidden.has(kind)) graph.hidden.delete(kind);
    else graph.hidden.add(kind);
    store.set("coder.graph.hidden", [...graph.hidden].join(","));
    renderGraph();
    $(`[data-graph-vault="${kind}"]`, graphBox)?.focus();
  } else if (node) {
    setMemoryView("notes");
    showNote(node.dataset.title, node.dataset.vault);
  }
});
graphBox.addEventListener("dblclick", (e) => {
  if (e.target.closest("svg") && !e.target.closest(".graph-node")) fitGraph();
});
graphBox.addEventListener("keydown", (e) => {
  const node = e.target.closest(".graph-node");
  if ((e.key === "Enter" || e.key === " ") && node) {
    e.preventDefault();
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }
});
// + − 0 zoomen im Graph, solange nicht gerade in ein Feld getippt wird.
$("#memorySheet").addEventListener("keydown", (e) => {
  if (memoryUI.view !== "graph" || e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, textarea, select")) return;
  if (e.key === "+" || e.key === "=") zoomGraph(1.4);
  else if (e.key === "-") zoomGraph(1 / 1.4);
  else if (e.key === "0") fitGraph();
  else return;
  e.preventDefault();
});
new ResizeObserver(() => {
  if (graphBox.hidden || !graph.nodes.length) return;
  if (graph.moved) redrawGraph();
  else fitGraph();
}).observe(graphBox);

/* ================================================================ Agents */

const TOOL_GROUPS = [
  { id: "read", label: "Lesen", sub: "Dateien lesen und durchsuchen", icon: "read_file", tools: ["read_file", "list_dir", "glob", "grep"] },
  { id: "edit", label: "Bearbeiten", sub: "Dateien ändern und anlegen", icon: "edit_file", tools: ["edit_file", "write_file"] },
  { id: "terminal", label: "Terminal", sub: "Befehle, Tests und Builds", icon: "run_command", tools: ["run_command"] },
  { id: "web", label: "Internet", sub: "Suchen und Seiten lesen", icon: "web_search", tools: ["web_search", "web_fetch"] },
];
const SOURCE_LABEL = {
  project: "Dieses Projekt", "claude-project": "Dieses Projekt · Claude Code", global: "Eigene",
  claude: "Aus Claude Code", builtin: "Eingebaut",
};

function toolPills(tools) {
  if (tools == null) return `<span class="tool-pill">Alle Werkzeuge</span>`;
  const groups = TOOL_GROUPS.filter((g) => g.tools.some((t) => tools.includes(t)));
  return groups.map((g) => `<span class="tool-pill">${g.label}</span>`).join("") || `<span class="tool-pill">Keine Werkzeuge</span>`;
}

async function openAgents() {
  openSheet("#agentsSheet");
  $("#agentNew").hidden = false;
  $("#agentsBody").innerHTML = `<div class="model-empty"><span class="spinner"></span></div>`;
  try {
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentsBody").innerHTML = `<div class="model-empty">${esc(e.message)}</div>`;
  }
}

function renderAgents(ext) {
  $("#agentNew").hidden = false;
  const groups = Object.keys(SOURCE_LABEL)
    .map((source) => [source, ext.agents.filter((a) => a.source === source)])
    .filter(([, list]) => list.length);
  $("#agentsBody").innerHTML = groups.map(([source, list]) => `
    <section class="agents-group">
      <span class="eyebrow">${SOURCE_LABEL[source]}</span>
      <div class="list">${list.map((a) => `
        <div class="agent-row">
          <span class="agent-avatar" aria-hidden="true">${esc(a.name.replace(/[^a-z0-9]/gi, "").slice(0, 2))}</span>
          <div>
            <div class="agent-name">@${esc(a.name)}</div>
            <div class="agent-desc" title="${esc(a.description)}">${esc(a.description)}</div>
            <div class="agent-tools">${toolPills(a.tools)}${a.model
              ? `<span class="tool-pill model" title="Dieser Agent arbeitet mit ${esc(a.model)}">${esc(a.model)}</span>` : ""}</div>
          </div>
          <div class="agent-actions">
            <button class="btn ghost" type="button" data-agent-use="${esc(a.name)}">Ansprechen</button>
            <button class="btn" type="button" data-agent-edit="${esc(a.name)}">${a.editable ? "Bearbeiten" : "Anpassen"}</button>
          </div>
        </div>`).join("")}
      </div>
    </section>`).join("") + `
    <p class="agents-hint">Coder gibt Teilaufgaben selbst an passende Agents ab. Mit <code>@name</code> am Anfang einer Nachricht
    übernimmt ein Agent den ganzen Auftrag. Eigene Agents liegen als Markdown in <code>~/.coder/agents</code> oder im Projekt
    unter <code>.coder/agents</code>.</p>`;
}

function agentEditor(agent) {
  const a = agent || { name: "", description: "", prompt: "", tools: TOOL_GROUPS[0].tools, source: "global", editable: true };
  const isNew = !agent;
  const scope = a.editable ? a.source : "global";
  const has = (g) => a.tools == null || g.tools.some((t) => a.tools.includes(t));
  $("#agentNew").hidden = true;
  $("#agentsBody").innerHTML = `
    <form class="settings agent-editor" id="agentForm" autocomplete="off">
      <span class="eyebrow">${isNew ? "Neuer Agent" : a.editable ? "Agent bearbeiten" : `Anpassen – eigene Fassung von @${esc(a.name)}`}</span>
      <div class="list">
        <label class="row col"><span>Name</span>
          <span class="name-field"><span>@</span><input name="name" value="${esc(a.name)}" spellcheck="false" maxlength="40" placeholder="api-tester"></span>
        </label>
        <label class="row col"><span>Wann soll Coder ihn einsetzen?</span>
          <textarea name="description" rows="2" placeholder="Eine Zeile: wofür er da ist und was er liefert">${esc(a.description)}</textarea>
        </label>
      </div>
      <span class="eyebrow">Werkzeuge</span>
      <div class="choice-grid">${TOOL_GROUPS.map((g) => `
        <label class="choice"><input type="checkbox" name="tools" value="${g.id}"${has(g) ? " checked" : ""}>
          <span class="choice-card">${ICONS[g.icon]}<span><strong>${g.label}</strong><small>${g.sub}</small></span></span>
        </label>`).join("")}
      </div>
      <span class="eyebrow">Modell</span>
      <div class="list">
        <label class="row"><span>Womit er arbeitet<small>Ein kleines Modell sucht schnell, ein großes prüft gründlich. Leer: dasselbe wie der Hauptagent</small></span>
          <select name="model" id="agentModel" data-wide><option value="">Wie der Hauptagent</option></select></label>
      </div>
      <span class="eyebrow">Anweisungen</span>
      <textarea class="prompt" name="prompt" rows="10" spellcheck="false" placeholder="Du bist … Gehe so vor: …">${esc(a.prompt)}</textarea>
      <span class="eyebrow">Speichern für</span>
      <div class="choice-grid">
        <label class="choice"><input type="radio" name="scope" value="global"${scope === "global" ? " checked" : ""}>
          <span class="choice-card">${ICONS.agent}<span><strong>Alle Projekte</strong><small>~/.coder/agents</small></span></span></label>
        <label class="choice"><input type="radio" name="scope" value="project"${scope === "project" ? " checked" : ""}>
          <span class="choice-card">${ICONS.folder}<span><strong>Dieses Projekt</strong><small>.coder/agents im Workspace</small></span></span></label>
      </div>
      <p class="form-error" id="agentError" role="alert"></p>
      <div class="sheet-actions sticky">
        ${!isNew && a.editable ? `<button type="button" class="btn ghost danger" id="agentDelete">Löschen</button><span class="spacer"></span>` : ""}
        <button type="button" class="btn ghost" id="agentBack">Zurück</button>
        <button type="submit" class="btn primary">Sichern</button>
      </div>
    </form>`;
  const form = $("#agentForm");
  fillAgentModels(a.model || "");
  form.elements.name.focus();
  $("#agentBack").addEventListener("click", () => renderAgents(state.ext));
  $("#agentDelete")?.addEventListener("click", () => deleteAgent(a));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    saveAgent(form, a);
  });
}

// Die installierten Modelle in die Auswahl – ein Name aus einer fremden Definition bleibt trotzdem stehen.
async function fillAgentModels(wanted) {
  const select = $("#agentModel");
  if (!select) return;
  let names = [];
  try {
    const data = state.models && Date.now() - state.models.at < 60000 ? state.models.data : await api("/api/models");
    state.models = { at: Date.now(), data };
    names = data.models.map((m) => m.name);
  } catch {
    names = [];
  }
  if (wanted && !names.includes(wanted)) names.unshift(wanted);
  select.innerHTML = `<option value="">Wie der Hauptagent</option>`
    + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  select.value = wanted;
}

async function saveAgent(form, original) {
  const picked = new Set($$("input[name=tools]:checked", form).map((i) => i.value));
  const body = {
    name: form.elements.name.value.trim().replace(/^@/, "").toLowerCase(),
    description: form.elements.description.value,
    prompt: form.elements.prompt.value,
    // Alle Gruppen gewählt heißt: alle Werkzeuge, auch künftige
    tools: picked.size === TOOL_GROUPS.length ? null : TOOL_GROUPS.filter((g) => picked.has(g.id)).flatMap((g) => g.tools),
    model: form.elements.model?.value || "",
    scope: $("input[name=scope]:checked", form)?.value || "global",
    workspace: currentWorkspace(),
  };
  if (original.editable && original.name) Object.assign(body, { original: original.name, original_scope: original.source });
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  try {
    const saved = await api("/api/agents", { method: "POST", body });
    toast(`@${saved.name} gesichert`);
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentError").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function deleteAgent(agent) {
  if (!confirm(`@${agent.name} löschen?`)) return;
  try {
    const q = `?workspace=${encodeURIComponent(currentWorkspace())}`;
    await api(`/api/agents/${agent.source}/${encodeURIComponent(agent.name)}${q}`, { method: "DELETE" });
    toast(`@${agent.name} gelöscht`);
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentError").textContent = e.message;
  }
}

$("#agentsBody").addEventListener("click", (e) => {
  const use = e.target.closest("[data-agent-use]");
  const edit = e.target.closest("[data-agent-edit]");
  if (use) {
    closeSheets();
    input.value = `@${use.dataset.agentUse} ${input.value.replace(/^@[\w-]+\s*/, "")}`;
    autosize();
    updateSendState();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  } else if (edit) {
    agentEditor(state.ext.agents.find((a) => a.name === edit.dataset.agentEdit));
  }
});
$("#agentNew").addEventListener("click", () => agentEditor(null));
$("#agentsBtn").addEventListener("click", openAgents);

/* ================================================================ Syntaxfarben */

// Ein kleiner Hervorheber für die Dateiansicht und die Codeblöcke im Chat. Kein Fremdcode, keine Abhängigkeit:
// je Sprache ein Ausdruck für Kommentare, Zeichenketten, Schlüsselwörter, Zahlen und Aufrufe. Die Bausteine kommen
// aus echten regulären Ausdrücken (.source) – so bleibt das Maskieren lesbar.
const KEYWORDS = {
  py: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case self",
  js: "async await break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new of return static super switch this throw try typeof var void while yield null true false undefined interface type enum implements readonly public private protected",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false",
  rust: "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self static struct super trait true type unsafe use where while",
  java: "abstract boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long new package private protected public return short static super switch this throw throws try void while true false null var",
  c: "auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while class namespace template new delete public private protected virtual override nullptr true false",
  sh: "if then else elif fi for while do done case esac function return in export local readonly set unset echo cd exit source",
  sql: "select from where group by order having insert into values update set delete create table drop alter add index join left right inner outer on as distinct limit offset union all null not and or",
  yaml: "true false null yes no on off",
  toml: "true false",
};
const C_HASH = /#[^\n]*/.source;
const C_SLASH = /\/\/[^\n]*|\/\*[\s\S]*?\*\//.source;
const C_BLOCK = /\/\*[\s\S]*?\*\//.source;
const C_DASH = /--[^\n]*/.source;
const NEVER = /(?!)/.source;
const S_DQ = /"(?:[^"\\\n]|\\.)*"/.source;
const S_SQ = /'(?:[^'\\\n]|\\.)*'/.source;
const S_BT = /`(?:[^`\\]|\\.)*`/.source;
const S_TRIPLE = /"""[\s\S]*?"""|'''[\s\S]*?'''/.source;
const COMMENTS = {
  py: C_HASH, sh: C_HASH, yaml: C_HASH, toml: C_HASH, js: C_SLASH, go: C_SLASH, rust: C_SLASH, java: C_SLASH,
  c: C_SLASH, css: C_BLOCK, sql: C_DASH, json: NEVER,
};
const STRINGS = {
  py: [S_TRIPLE, S_DQ, S_SQ].join("|"),
  js: [S_BT, S_DQ, S_SQ].join("|"),
};
const NUMBERS = /\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b/.source;
const CALLS = /\b[A-Za-z_]\w*(?=\()/.source;
const EXT_LANG = {
  py: "py", pyw: "py", js: "js", mjs: "js", cjs: "js", jsx: "js", ts: "js", tsx: "js", json: "json", jsonc: "json",
  html: "html", htm: "html", xml: "html", svg: "html", vue: "html", css: "css", scss: "css", less: "css",
  md: "md", markdown: "md", sh: "sh", bash: "sh", zsh: "sh", ps1: "sh", bat: "sh", cmd: "sh", yml: "yaml",
  yaml: "yaml", toml: "toml", ini: "toml", cfg: "toml", sql: "sql", go: "go", rs: "rust", java: "java",
  c: "c", h: "c", cpp: "c", hpp: "c", cs: "c", kt: "java", swift: "java", rb: "py", php: "js", lua: "py",
};
const RX_CACHE = {};

function langOf(name) {
  const ext = String(name || "").split(".").pop().toLowerCase();
  return EXT_LANG[ext] || "";
}

function langRx(lang) {
  if (lang in RX_CACHE) return RX_CACHE[lang];
  let rx = null;
  if (lang === "html") {
    rx = new RegExp([/(?<com><!--[\s\S]*?-->)/.source, /(?<str>"[^"]*"|'[^']*')/.source,
      /(?<tag><\/?[A-Za-z][\w:-]*)/.source, /(?<attr>[\w:-]+(?==))/.source].join("|"), "g");
  } else if (lang === "md") {
    rx = new RegExp([/(?<kw>^#{1,6} [^\n]*)/.source, /(?<str>`[^`\n]*`)/.source, /(?<com>^> [^\n]*)/.source,
      /(?<fn>\[[^\]\n]*\]\([^)\n]*\))/.source].join("|"), "gm");
  } else if (KEYWORDS[lang] || lang === "json" || lang === "css") {
    const com = COMMENTS[lang] || NEVER;
    const str = STRINGS[lang] || STRINGS.py;
    const words = (KEYWORDS[lang] || "").split(" ").filter(Boolean);
    const kw = words.length ? `\\b(?:${words.join("|")})\\b` : NEVER;
    // SQL schreibt man groß oder klein – dort zählt die Schreibweise nicht.
    rx = new RegExp([`(?<com>${com})`, `(?<str>${str})`, `(?<kw>${kw})`, `(?<num>${NUMBERS})`,
      `(?<fn>${CALLS})`].join("|"), lang === "sql" ? "gi" : "g");
  }
  RX_CACHE[lang] = rx;
  return rx;
}

function highlight(src, lang) {
  const rx = langRx(lang);
  if (!rx) return esc(src);
  const out = [];
  let last = 0;
  let m;
  rx.lastIndex = 0;
  while ((m = rx.exec(src))) {
    if (!m[0]) {
      rx.lastIndex++;
      continue;
    }
    out.push(esc(src.slice(last, m.index)));
    const kind = Object.keys(m.groups || {}).find((k) => m.groups[k] !== undefined) || "";
    out.push(kind ? `<span class="tok-${kind}">${esc(m[0])}</span>` : esc(m[0]));
    last = m.index + m[0].length;
  }
  out.push(esc(src.slice(last)));
  return out.join("");
}

/* ================================================================ Dateien: Baum und Editor */

// Der Editor ist ein eigener Bereich (Tab „Editor“, Strg+E): links in der Seitenleiste der Explorer, rechts die
// offenen Dateien als Tabs, darunter auf Wunsch ein Terminal. Die aktive Datei steht in `files` (path, saved, eol,
// mtime, stale) – daran hängen Hervorheber und Ergänzer. Alle offenen Dateien liegen in `files.docs`.
const files = {
  path: null, saved: "", eol: "\n", mtime: 0, stale: false, writable: true,
  root: "",            // Workspace, dessen Baum gerade steht
  docs: new Map(),     // Pfad → { path, ws, saved, text, eol, mtime, stale, writable, top, left, start, end }
  order: [],           // Reihenfolge der Tabs
  open: new Set(),     // aufgeklappte Ordner
  tree: new Map(),     // Ordner → Einträge
  all: null,           // alle Pfade für die Schnellsuche (Strg+P)
  sel: "",             // markierte Zeile im Baum – Ziel für „Neue Datei“
  pending: null,       // Eingabezeile im Baum: { kind: "file"|"dir", dir } oder { rename: pfad }
};
const MAX_TABS = 24;

// Ein Textfeld kennt nur \n: Windows-Dateien kämen sonst gleich als „geändert" an und würden beim Speichern
// still auf LF umgeschrieben. Deshalb merken wir uns die Zeilenenden der Datei und schreiben sie zurück.
function eolOf(text) {
  const crlf = (text.match(/\r\n/g) || []).length;
  return crlf && crlf * 2 >= (text.match(/\n/g) || []).length ? "\r\n" : "\n";
}

// Der Text der aktiven Datei: aus dem Textfeld – oder, in der Markdown-Vorschau, aus dem Dokument.
function currentText() {
  const ta = $("#fileText");
  return ta ? ta.value : files.docs.get(files.path)?.text ?? files.saved;
}

function fileDirty() {
  return !!files.path && currentText() !== files.saved;
}

function docDirty(doc) {
  if (!doc) return false;
  return doc.path === files.path ? fileDirty() : doc.text !== doc.saved;
}

const IMAGE_RX = /\.(png|jpe?g|gif|webp|bmp|ico|svg)$/i;

const anyDirty = () => [...files.docs.values()].some(docDirty);
const parentOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const joinPath = (dir, name) => (dir ? `${dir}/${name}` : name);

// Der Ordner, in dem der Editor arbeitet: der des offenen Code-Chats, sonst der eingestellte Workspace.
function ideWorkspace() {
  return (state.session?.kind !== "talk" && state.session?.workspace) || state.config?.workspace || "";
}

async function openFiles(path = null) {
  // Der Editor braucht den neuen Server – bis zum Neustart sagen wir das, statt in 404 zu laufen.
  if (!serverHas("1.7.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  if (!roleAtLeast("read")) return toast("Dein Konto darf nur den Chat benutzen.", { error: true });
  if (state.tab !== "ide") await switchTab("ide");
  if (path) await openFile(path);
}

// Beim Wechsel in den Editor: Baum für den richtigen Ordner, zuletzt offene Dateien zurück.
async function enterIde() {
  const ws = ideWorkspace();
  $("#filesRoot").textContent = basename(ws) || ws || "Workspace";
  $("#filesRoot").title = ws;
  if (files.root !== ws) {
    files.root = ws;
    files.tree.clear();
    files.open.clear();
    files.all = null;
    files.sel = "";
    await loadTree("");
    await restoreTabs();
  } else if (!files.tree.has("")) {
    await loadTree("");
  }
  renderTree();
  renderTabs();
  if (files.path && $("#fileText")) paintCode();
  else renderEditor(null);
  renderStatus();
  scheduleGit();
}

async function loadTree(dir) {
  try {
    const data = await api(`/api/tree?path=${encodeURIComponent(dir)}&workspace=${encodeURIComponent(files.root || ideWorkspace())}`);
    files.tree.set(dir, data.entries);
  } catch (e) {
    toast(e.message, { error: true });
    files.tree.set(dir, []);
  }
}

function fileIconFor(name) {
  const lang = langOf(name);
  if (/\.(png|jpe?g|gif|webp|svg|ico|bmp)$/i.test(name)) return ICONS.image;
  return lang ? ICONS.read_file : ICONS.note;
}

const GIT_LABEL = { M: "Geändert", U: "Neu, noch nicht in git", A: "Hinzugefügt", D: "Gelöscht", R: "Umbenannt", C: "Konflikt" };

// Welche Dateien git als geändert kennt – färbt den Baum und nennt den Branch in der Statuszeile.
async function loadGit() {
  if (!serverHas("1.11.0") || !files.root) return;
  try {
    files.git = await api(`/api/git?workspace=${encodeURIComponent(files.root)}`);
  } catch {
    files.git = null;
  }
  files.gitDirs = new Set();
  for (const p of Object.keys(files.git?.files || {})) {
    for (let d = parentOf(p); d; d = parentOf(d)) files.gitDirs.add(d);
  }
  renderTree();
  renderStatus();
}

function scheduleGit() {
  clearTimeout(scheduleGit.timer);
  scheduleGit.timer = setTimeout(loadGit, 400);
}

function treeRow(entry, depth) {
  const open = files.open.has(entry.path);
  const git = files.git?.files?.[entry.path];
  const gitMark = git ? `<span class="git-mark" title="${esc(GIT_LABEL[git] || git)}">${esc(git)}</span>`
    : entry.dir && files.gitDirs?.has(entry.path) ? `<span class="git-dot" title="Enthält Änderungen"></span>` : "";
  const size = entry.size < 1024 ? `${entry.size} B` : `${Math.round(entry.size / 1024)} KB`;
  const doc = files.docs.get(entry.path);
  if (files.pending?.rename === entry.path) return treeInput(entry.dir ? "dir" : "file", depth, entry.name);
  const cls = ["file-row", entry.dir && "dir", files.path === entry.path && "on", open && "open",
    files.sel === entry.path && "sel", docDirty(doc) && "dirty", git && `git-${git}`].filter(Boolean).join(" ");
  return `<button type="button" class="${cls}" data-path="${esc(entry.path)}" data-dir="${entry.dir ? 1 : 0}"
    style="padding-left:${8 + depth * 14}px" title="${esc(entry.path)}">
    <span class="file-icon">${entry.dir ? ICONS.chevron : fileIconFor(entry.name)}</span>
    <span class="file-name">${esc(entry.name)}</span>
    ${entry.dir ? "" : `<span class="file-size">${size}</span>`}${gitMark}
  </button>`;
}

function treeInput(kind, depth, value = "") {
  return `<div class="file-row editing" style="padding-left:${8 + depth * 14}px">
    <span class="file-icon">${kind === "dir" ? ICONS.folder : ICONS.read_file}</span>
    <input class="file-input" id="treeInput" value="${esc(value)}" spellcheck="false" autocomplete="off"
      aria-label="${kind === "dir" ? "Name des Ordners" : "Name der Datei"}">
  </div>`;
}

function renderTree() {
  const rows = [];
  const pend = files.pending;
  const walk = (dir, depth) => {
    if (pend && !pend.rename && pend.dir === dir) rows.push(treeInput(pend.kind, depth));
    for (const entry of files.tree.get(dir) || []) {
      rows.push(treeRow(entry, depth));
      if (entry.dir && files.open.has(entry.path)) walk(entry.path, depth + 1);
    }
  };
  walk("", 0);
  $("#fileTree").innerHTML = rows.join("") || `<p class="file-empty">Der Ordner ist leer.</p>`;
  const field = $("#treeInput");
  if (field) {
    field.focus();
    const dot = pend?.rename ? field.value.lastIndexOf(".") : -1;
    field.setSelectionRange(0, dot > 0 ? dot : field.value.length); // wie in VS Code: den Namen ohne Endung
  }
}

async function toggleDir(path) {
  if (files.open.has(path)) files.open.delete(path);
  else {
    files.open.add(path);
    if (!files.tree.has(path)) await loadTree(path);
  }
  renderTree();
}

// Die Ordner auf dem Weg zu einer Datei aufklappen – man sieht, wo sie liegt.
async function revealPath(path) {
  let dir = "";
  for (const part of path.split("/").slice(0, -1)) {
    dir = joinPath(dir, part);
    if (!files.open.has(dir)) {
      files.open.add(dir);
      if (!files.tree.has(dir)) await loadTree(dir);
    }
  }
}

async function openFile(path, { line = 0, col = 1, len = 0 } = {}) {
  path = String(path).replace(/\\/g, "/").replace(/^\.\//, "");
  if (!files.docs.has(path) && IMAGE_RX.test(path) && serverHas("1.11.0")) {
    files.docs.set(path, { path, ws: files.root, kind: "image", saved: "", text: "", eol: "\n", mtime: Date.now(),
      stale: false, writable: false, top: 0, left: 0, start: 0, end: 0 });
    files.order.push(path);
    trimTabs();
    await revealPath(path);
  }
  if (!files.docs.has(path)) {
    let data;
    try {
      data = await api(`/api/file?path=${encodeURIComponent(path)}&workspace=${encodeURIComponent(files.root || ideWorkspace())}`);
    } catch (e) {
      return toast(e.message, { error: true, ms: 5000 });
    }
    path = data.path;
    if (!files.docs.has(path)) {
      const text = data.text.replace(/\r\n/g, "\n");
      files.docs.set(path, { path, ws: files.root, saved: text, text, eol: eolOf(data.text), mtime: data.mtime,
        stale: false, writable: data.writable !== false && roleAtLeast("code"), top: 0, left: 0, start: 0, end: 0 });
      files.order.push(path);
      trimTabs();
    }
    await revealPath(path);
  }
  activate(path);
  if (line) goToLine(line, col, len);
}

// Zu viele Tabs: die ältesten, unveränderten gehen zuerst.
function trimTabs() {
  while (files.order.length > MAX_TABS) {
    const old = files.order.find((p) => p !== files.path && !docDirty(files.docs.get(p)));
    if (!old) break;
    files.order.splice(files.order.indexOf(old), 1);
    files.docs.delete(old);
  }
}

// Stand der aktiven Datei in ihr Dokument zurücklegen – Text, Cursor und Scrollstand.
function stash() {
  const doc = files.docs.get(files.path);
  const ta = $("#fileText");
  if (!doc || !ta) return;
  doc.text = ta.value;
  doc.top = ta.scrollTop;
  doc.left = ta.scrollLeft;
  doc.start = ta.selectionStart;
  doc.end = ta.selectionEnd;
  doc.stale = files.stale;
}

function activate(path) {
  const doc = files.docs.get(path);
  if (!doc) return;
  if (files.path !== path) stash();
  files.path = doc.path;
  files.saved = doc.saved;
  files.eol = doc.eol;
  files.mtime = doc.mtime;
  files.stale = doc.stale;
  files.writable = doc.writable;
  files.sel = doc.path;
  renderEditor(doc.text);
  const ta = $("#fileText");
  if (ta) {
    ta.scrollTop = doc.top;
    ta.scrollLeft = doc.left;
    ta.setSelectionRange(doc.start, doc.end);
    if (state.tab === "ide") ta.focus({ preventScroll: true });
    syncScroll();
  }
  renderTabs();
  renderTree();
  saveTabs();
  if (!$("#findBar").hidden) runFind();
}

async function closeTab(path, force = false) {
  const doc = files.docs.get(path);
  if (!doc) return;
  if (!force && docDirty(doc) && !confirm(`„${basename(path)}“ ist nicht gespeichert. Trotzdem schließen?`)) return;
  const at = files.order.indexOf(path);
  files.order.splice(at, 1);
  files.docs.delete(path);
  if (files.path === path) {
    files.path = null;
    const next = files.order[Math.min(at, files.order.length - 1)];
    if (next) activate(next);
    else {
      renderEditor(null);
      renderTree();
    }
  }
  renderTabs();
  saveTabs();
}

function saveTabs() {
  if (!files.root) return;
  store.set(`coder.ide.${files.root}`, JSON.stringify({ order: files.order.slice(0, 12), active: files.path }));
}

async function restoreTabs() {
  let saved;
  try { saved = JSON.parse(store.get(`coder.ide.${files.root}`) || "null"); } catch { saved = null; }
  if (!saved?.order?.length) return;
  for (const path of saved.order.slice(0, 12)) {
    if (files.docs.has(path)) continue;
    try {
      const data = await api(`/api/file?path=${encodeURIComponent(path)}&workspace=${encodeURIComponent(files.root)}`);
      const text = data.text.replace(/\r\n/g, "\n");
      files.docs.set(data.path, { path: data.path, ws: files.root, saved: text, text, eol: eolOf(data.text),
        mtime: data.mtime, stale: false, writable: data.writable !== false && roleAtLeast("code"),
        top: 0, left: 0, start: 0, end: 0 });
      files.order.push(data.path);
    } catch { /* inzwischen gelöscht oder umbenannt */ }
  }
  const active = files.docs.has(saved.active) ? saved.active : files.order[0];
  if (active) {
    await revealPath(active);
    activate(active);
  }
}

function renderTabs() {
  const bar = $("#ideTabs");
  const names = new Map();
  for (const p of files.order) names.set(basename(p), (names.get(basename(p)) || 0) + 1);
  bar.innerHTML = files.order.map((p) => {
    const doc = files.docs.get(p);
    const name = basename(p);
    const dir = names.get(name) > 1 ? parentOf(p) : ""; // gleiche Namen: der Ordner unterscheidet
    const on = p === files.path;
    return `<div class="ide-tab${on ? " on" : ""}${docDirty(doc) ? " dirty" : ""}" role="tab" tabindex="${on ? 0 : -1}"
      aria-selected="${on}" data-tab-path="${esc(p)}" title="${esc(p)}">
      <span class="ide-tab-name">${esc(name)}</span>${dir ? `<span class="ide-tab-dir">${esc(basename(dir))}</span>` : ""}
      <button type="button" class="ide-tab-close" data-close-tab="${esc(p)}" aria-label="${esc(name)} schließen" title="Schließen (Strg+W)">${ICONS.cross}</button>
    </div>`;
  }).join("");
  bar.hidden = !files.order.length;
  // Ausführen und „an Coder geben“ brauchen eine offene Datei – ohne sind sie nur Deko, die nichts tut.
  for (const id of ["#runFile", "#askCoder"]) $(id).disabled = !files.path;
  $(".ide-tab.on", bar)?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function renderEditor(text = null) {
  const head = $("#fileHead");
  const body = $("#fileBody");
  if (!files.path) {
    head.innerHTML = "";
    head.hidden = true;
    body.innerHTML = `<div class="ide-empty">
      <p class="ide-empty-title">${esc(basename(files.root) || "Editor")}</p>
      <div class="ide-empty-keys">
        <span><kbd>Strg P</kbd>Datei öffnen</span>
        <span><kbd>Strg Umschalt F</kbd>In Dateien suchen</span>
        ${roleAtLeast("code") ? `<span><kbd>Strg Ö</kbd>Terminal</span>` : ""}
        <span><kbd>Strg E</kbd>Zurück hierher</span>
      </div>
    </div>`;
    renderStatus();
    return;
  }
  head.hidden = false;
  const doc = files.docs.get(files.path);
  const crumbs = files.path.split("/").map((part, i, all) =>
    `<span class="crumb${i === all.length - 1 ? " last" : ""}">${esc(part)}</span>`).join(`<span class="crumb-sep">/</span>`);
  const md = langOf(files.path) === "md";
  head.innerHTML = `
    <span class="file-title" title="${esc(files.path)}">${crumbs}</span>
    <span class="file-state" id="fileState"></span>
    <span class="file-hint" id="fileHint"></span>
    <span class="spacer"></span>
    ${files.git?.files?.[files.path] === "M" ? `<button type="button" class="btn ghost small${doc?.diff ? " on" : ""}" data-file="diff" title="Was sich seit dem letzten Commit geändert hat" aria-pressed="${!!doc?.diff}">${doc?.diff ? "Datei" : "Änderungen"}</button>` : ""}
    ${md && !doc?.diff ? `<button type="button" class="btn ghost small${doc?.preview ? " on" : ""}" data-file="preview" title="Vorschau (Strg+Umschalt+V)" aria-pressed="${!!doc?.preview}">${doc?.preview ? "Bearbeiten" : "Vorschau"}</button>` : ""}
    ${doc?.kind === "image" ? `<span class="file-badge" id="imageInfo">Bild</span>`
    : files.writable ? `<button type="button" class="btn ghost small" data-file="revert" hidden>Verwerfen</button>
    <button type="button" class="btn small" data-file="save" title="Speichern (Strg+S)" disabled>Speichern</button>`
    : `<span class="file-badge">Nur lesen</span>`}`;
  if (doc?.kind === "image") {
    // Bilder zeigt der Editor an – auf einem Schachbrett, damit Transparenz sichtbar bleibt.
    const src = `/api/raw?path=${encodeURIComponent(doc.path)}&workspace=${encodeURIComponent(doc.ws || files.root)}&v=${doc.mtime}`;
    body.innerHTML = `<div class="image-view"><img src="${esc(src)}" alt="${esc(basename(doc.path))}"></div>`;
    const img = $("img", body);
    img.addEventListener("load", () => {
      doc.size = `${img.naturalWidth} × ${img.naturalHeight} px`;
      const info = $("#imageInfo");
      if (info) info.textContent = doc.size;
      renderStatus();
    });
    img.addEventListener("error", () => { body.innerHTML = `<p class="file-empty">Das Bild lässt sich nicht anzeigen.</p>`; });
    renderStatus();
    return;
  }
  if (doc?.diff) {
    body.innerHTML = `<div class="diff-view"><p class="file-empty">Lädt die Änderungen …</p></div>`;
    showDiff(doc);
    renderStatus();
    return;
  }
  if (doc?.preview) {
    body.innerHTML = `<div class="md-preview"><div class="md">${markdown(doc.text)}</div></div>`;
    paintHead();
    renderStatus();
    return;
  }
  if (text !== null || !$("#fileText")) {
    if (text === null) text = doc?.text ?? "";
    body.innerHTML = `
      <div class="file-edit">
        <pre class="file-gutter" id="fileGutter" aria-hidden="true"></pre>
        <div class="file-code-wrap">
          <pre class="file-marks" id="fileMarks" aria-hidden="true"></pre>
          <pre class="file-code" id="fileCode" aria-hidden="true"><code></code></pre>
          <textarea id="fileText" spellcheck="false" autocomplete="off" wrap="off" aria-label="Inhalt von ${esc(files.path)}"></textarea>
          <div class="code-suggest" id="fileSuggest" role="listbox" aria-label="Vorschläge" hidden></div>
        </div>
      </div>`;
    const ta = $("#fileText");
    ta.value = text;
    ta.readOnly = !files.writable;
    view.lh = 0; // Design oder Schriftgröße können sich seit der letzten Datei geändert haben
    ta.addEventListener("input", () => {
      advanceGhost(ta);
      requestPaint();
      updateList();
      scheduleGhost();
      if (!$("#findBar").hidden) scheduleFind();
    });
    ta.addEventListener("scroll", () => {
      syncScroll();
      scrollPaint();
      placeList();
    });
    ta.addEventListener("keydown", (e) => {
      if (helperKey(e)) return;
      if (editorKey(e, ta)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveFile();
      }
    });
    for (const kind of ["keyup", "mouseup", "select", "focus"]) ta.addEventListener(kind, renderStatus);
    wireHelper(ta);
  }
  paintCode();
}

// Schriftgröße nur im Editor – Strg+Plus, Strg+Minus, Strg+0. Gemerkt fürs nächste Mal.
function editorZoom(step) {
  const now = Number(store.get("coder.editorSize")) || 12.5;
  const size = step === 0 ? 12.5 : Math.max(9, Math.min(24, now + step));
  store.set("coder.editorSize", String(size));
  applyEditorSize(size);
  toast(`Schrift im Editor: ${nf.format(size)} px`, { ms: 1200 });
}

function applyEditorSize(size = Number(store.get("coder.editorSize")) || 12.5) {
  $("#ide").style.setProperty("--editor-size", `${size}px`);
  view.lh = 0;
  helper.cw = 0;
  if ($("#fileText")) {
    paintCode();
    if (!$("#findBar").hidden) paintMarks();
  }
}

function syncScroll() {
  const ta = $("#fileText");
  if (!ta) return;
  for (const id of ["#fileCode", "#fileMarks"]) {
    const layer = $(id);
    if (!layer) continue;
    layer.scrollTop = ta.scrollTop;
    layer.scrollLeft = ta.scrollLeft;
  }
  $("#fileGutter").scrollTop = ta.scrollTop;
}

// Große Dateien färbt der Editor nur um den sichtbaren Ausschnitt herum – Leerraum davor und danach hält die
// Höhe, damit Scrollen und Cursor stimmen. Sonst kostet jede Taste bei ein paar Tausend Zeilen spürbar Zeit.
const VIRTUAL_LINES = 1500;   // ab so vielen Zeilen
const VIRTUAL_MARGIN = 200;   // so viele Zeilen über und unter dem sichtbaren Bereich werden mitgefärbt
const view = { from: 0, to: 0, frame: 0, lh: 0 };

function lineHeight() {
  if (!view.lh) view.lh = parseFloat(getComputedStyle($("#fileText")).lineHeight) || 20;
  return view.lh;
}

// Tippen in großen Dateien: höchstens einmal pro Bild malen.
function requestPaint() {
  const ta = $("#fileText");
  if (!ta || ta.value.length < 60_000) return paintCode();
  if (!view.frame) view.frame = requestAnimationFrame(() => { view.frame = 0; paintCode(); });
}

// Beim Scrollen: neu malen, sobald der sichtbare Bereich an den Rand des gefärbten Ausschnitts kommt.
function scrollPaint() {
  const ta = $("#fileText");
  if (!ta || !view.to) return;
  const lh = lineHeight();
  const first = Math.floor(ta.scrollTop / lh);
  const last = first + Math.ceil(ta.clientHeight / lh);
  if ((first < view.from + 20 && view.from > 0) || last > view.to - 20) requestPaint();
}

function paintCode() {
  const ta = $("#fileText");
  if (!ta) return;
  const value = ta.value;
  const all = value.split("\n");
  const lines = all.length;
  const code = $("#fileCode");
  const gutter = $("#fileGutter");
  let from = 0;
  let to = lines;
  let offset = 0; // Zeichen vor dem gefärbten Ausschnitt
  if (lines > VIRTUAL_LINES) {
    const lh = lineHeight();
    const first = Math.floor(ta.scrollTop / lh);
    from = Math.max(0, first - VIRTUAL_MARGIN);
    to = Math.min(lines, first + Math.ceil(ta.clientHeight / lh) + VIRTUAL_MARGIN);
    for (let i = 0; i < from; i++) offset += all[i].length + 1;
  }
  const slice = from || to < lines ? all.slice(from, to).join("\n") : value;
  let html = `${highlight(slice, langOf(files.path))}\n`;
  let numbers = Array.from({ length: to - from }, (_, i) => String(from + i + 1));
  if (helper.ghost && helper.at >= offset && helper.at <= offset + slice.length) {
    html = insertAt(html, helper.at - offset, `<span class="code-ghost">${esc(helper.ghost)}</span>`);
    const extra = (helper.ghost.match(/\n/g) || []).length;
    if (extra) numbers = ghostGutter(numbers, caretSpot(value, helper.at).line - from, extra);
  }
  const virtual = lines > VIRTUAL_LINES;
  view.from = virtual ? from : 0;
  view.to = virtual ? to : 0;
  // Der Leerraum steckt im Inhalt, nicht am Scroll-Container: Ein Innenabstand dort ließe den Container selbst
  // wachsen – er könnte nicht mehr scrollen, und Farben und Zeilennummern verrutschten.
  const inner = code.firstElementChild;
  const above = virtual ? `${from * lineHeight()}px` : "";
  const below = virtual ? `${(lines - to) * lineHeight()}px` : "";
  inner.style.paddingTop = above;
  inner.style.paddingBottom = below;
  inner.style.minWidth = virtual ? `${Math.max(0, ta.scrollWidth - 24)}px` : ""; // lange Zeilen außerhalb halten die Breite
  inner.innerHTML = html;
  if (virtual) gutter.innerHTML = `<span class="gutter-pad" style="padding-top:${above};padding-bottom:${below}">${numbers.join("\n")}</span>`;
  else gutter.textContent = numbers.join("\n");
  syncScroll();
  paintHead();
  renderStatus();
}

// Kopfzeile: „Nicht gespeichert“, Speichern und Verwerfen – auch in der Markdown-Vorschau.
function paintHead() {
  const hint = $("#fileHint");
  if (hint) hint.textContent = helper.hint;
  const dirty = fileDirty();
  const state = $("#fileState");
  if (state) {
    state.textContent = files.stale ? "Woanders geändert – neu laden" : dirty ? "Nicht gespeichert" : "";
    const revert = $('[data-file="revert"]');
    if (revert) {
      revert.hidden = !dirty && !files.stale;
      revert.textContent = files.stale && !dirty ? "Neu laden" : "Verwerfen";
    }
    const save = $('[data-file="save"]');
    if (save) save.disabled = !dirty;
    state.className = `file-state${files.stale ? " stale" : dirty ? " dirty" : ""}`;
    state.title = files.stale ? "Vom Agent geändert oder von jemand anderem gespeichert" : "";
  }
  $$(".file-row.on", $("#fileTree")).forEach((row) => row.classList.toggle("dirty", dirty));
  $(`.ide-tab.on`, $("#ideTabs"))?.classList.toggle("dirty", dirty);
}

// Der Unterschied zum letzten Commit, Zeile für Zeile – ein Klick auf eine Zeile springt in die Datei.
async function showDiff(doc) {
  let data;
  try {
    data = await api(`/api/git/diff?path=${encodeURIComponent(doc.path)}&workspace=${encodeURIComponent(doc.ws || files.root)}`);
  } catch (e) {
    data = { diff: "", error: e.message };
  }
  const box = $(".diff-view");
  if (!box || files.path !== doc.path || !doc.diff) return;
  if (!data.diff) {
    box.innerHTML = `<p class="file-empty">${esc(data.error || (data.untracked ? "Die Datei ist neu – git kennt noch keine frühere Fassung." : "Keine Änderungen seit dem letzten Commit."))}</p>`;
    return;
  }
  let newLine = 0;
  const rows = [];
  for (const line of data.diff.split(/\r?\n/)) { // git unter Windows schreibt CRLF
    if (/^(diff |index |--- |\+\+\+ |new file|deleted file|similarity|rename )/.test(line)) continue;
    const hunk = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)/);
    if (hunk) {
      newLine = Number(hunk[1]);
      rows.push(`<div class="diff-line hunk">${esc(line)}</div>`);
      continue;
    }
    const kind = line[0] === "+" ? "add" : line[0] === "-" ? "del" : "ctx";
    const at = kind === "del" ? "" : newLine;
    rows.push(`<div class="diff-line ${kind}"${at ? ` data-line="${at}"` : ""}><span class="diff-no">${at}</span><span class="diff-text">${esc(line.slice(1)) || " "}</span></div>`);
    if (kind !== "del") newLine++;
  }
  box.innerHTML = rows.join("") + (data.capped ? `<p class="file-empty">Gekürzt – die Änderung ist sehr groß.</p>` : "");
}

function toggleDiff() {
  const doc = files.docs.get(files.path);
  if (!doc) return;
  stash();
  doc.diff = !doc.diff;
  if (doc.diff) doc.preview = false;
  const path = files.path;
  files.path = null;
  activate(path);
}

function togglePreview() {
  const doc = files.docs.get(files.path);
  if (!doc || langOf(doc.path) !== "md") return;
  stash();
  doc.preview = !doc.preview;
  const path = files.path;
  files.path = null; // activate() baut neu auf, statt den Stand zurückzulegen
  activate(path);
}

async function saveFile({ force = false } = {}) {
  const doc = files.docs.get(files.path);
  if (!files.path || !files.writable || doc?.kind === "image") return;
  if (!fileDirty() && !force) return toast("Nichts zu speichern.");
  const value = currentText();
  const ta = { value }; // was gespeichert wird – auch wenn gerade die Vorschau statt des Textfelds dasteht
  try {
    const data = await api("/api/file", {
      method: "POST",
      body: { path: files.path, text: files.eol === "\n" ? ta.value : ta.value.replace(/\n/g, files.eol),
              workspace: doc?.ws || files.root, mtime: files.mtime, force },
    });
    files.saved = value;
    files.mtime = data.mtime;
    files.stale = false;
    if (doc) Object.assign(doc, { saved: value, mtime: data.mtime, stale: false });
    if (doc && !$("#fileText")) doc.text = value;
    paintCode();
    paintHead();
    renderTabs();
    scheduleGit();
    toast(`${files.path} gespeichert`);
  } catch (e) {
    // Jemand war schneller – der Agent, ein zweiter Nutzer, ein anderes Programm: nicht still überschreiben.
    if (/woanders geändert/.test(e.message) && confirm(`${files.path} wurde inzwischen woanders geändert.\n\nDeine Fassung trotzdem speichern und die andere überschreiben?`)) {
      return saveFile({ force: true });
    }
    toast(e.message, { error: true, ms: 5000 });
  }
}

function revertFile() {
  const ta = $("#fileText");
  if (files.stale) return reloadDoc(files.path);
  if (!ta) {
    const doc = files.docs.get(files.path);
    if (doc) doc.text = doc.saved;
    renderEditor(null);
    renderTabs();
    return;
  }
  ta.value = files.saved;
  files.stale = false;
  paintCode();
  renderTabs();
}

// Frisch von der Platte – Scrollstand und Cursor bleiben, soweit es die neue Fassung hergibt.
async function reloadDoc(path) {
  const doc = files.docs.get(path);
  if (!doc) return;
  try {
    const data = await api(`/api/file?path=${encodeURIComponent(path)}&workspace=${encodeURIComponent(doc.ws || files.root)}`);
    const text = data.text.replace(/\r\n/g, "\n");
    Object.assign(doc, { saved: text, text, eol: eolOf(data.text), mtime: data.mtime, stale: false });
    if (files.path === path) {
      stash();
      Object.assign(doc, { text, stale: false });
      files.path = null; // activate() soll neu aufbauen, nicht den alten Text zurücklegen
      activate(path);
    }
    renderTabs();
  } catch (e) {
    toast(e.message, { error: true });
  }
}

// Der Agent hat Dateien geändert: Offene ohne eigene Änderung werden neu geladen, die anderen fallen auf.
function filesChanged(paths) {
  if (!paths?.length) return;
  const changed = new Set(paths.map((p) => String(p).replace(/\\/g, "/")));
  for (const doc of files.docs.values()) {
    if (!changed.has(doc.path)) continue;
    if (docDirty(doc)) {
      doc.stale = true;
      if (doc.path === files.path) files.stale = true;
    } else reloadDoc(doc.path);
  }
  if (files.path) paintCode();
  // Neue Dateien sollen im Baum auftauchen: die betroffenen, schon geladenen Ordner neu einlesen.
  const dirs = new Set([...changed].map(parentOf).filter((d) => files.tree.has(d)));
  files.all = null;
  if (dirs.size) Promise.all([...dirs].map(loadTree)).then(renderTree);
  scheduleGit();
}

/* ---------------------------------------------------------------- Explorer: anlegen, umbenennen, löschen */

function targetDir() {
  const sel = files.sel || files.path || "";
  const entry = findEntry(sel);
  return entry?.dir ? sel : parentOf(sel);
}

function findEntry(path) {
  for (const entries of files.tree.values()) {
    const hit = entries.find((e) => e.path === path);
    if (hit) return hit;
  }
  return null;
}

async function startCreate(kind, dir = targetDir()) {
  if (!roleAtLeast("code")) return;
  if (dir && !files.open.has(dir)) {
    files.open.add(dir);
    if (!files.tree.has(dir)) await loadTree(dir);
  }
  files.pending = { kind, dir };
  renderTree();
}

function startRename(path) {
  if (!roleAtLeast("code") || !path) return;
  files.pending = { rename: path };
  renderTree();
}

async function fileOp(body) {
  return api("/api/fs", { method: "POST", body: { ...body, workspace: files.root } });
}

async function commitTreeInput() {
  const pend = files.pending;
  const field = $("#treeInput");
  if (!pend || !field) return;
  const name = field.value.trim().replace(/\\/g, "/");
  files.pending = null;
  if (!name || name === "." || name.split("/").includes("..")) return renderTree();
  try {
    if (pend.rename) {
      const from = pend.rename;
      if (name === basename(from)) return renderTree();
      const res = await fileOp({ op: "rename", path: from, to: joinPath(parentOf(from), name) });
      moveDocs(from, res.path);
      await loadTree(parentOf(from));
      if (parentOf(res.path) !== parentOf(from)) await loadTree(parentOf(res.path));
      files.sel = res.path;
    } else {
      const res = await fileOp({ op: pend.kind, path: joinPath(pend.dir, name) });
      await loadTree(parentOf(res.path));
      if (name.includes("/")) await revealPath(res.path);
      files.sel = res.path;
      if (pend.kind === "file") await openFile(res.path);
    }
    files.all = null;
    scheduleGit();
  } catch (e) {
    toast(e.message, { error: true });
  }
  renderTree();
}

// Umbenannt: offene Dateien darin behalten ihren Inhalt, bekommen aber den neuen Pfad.
function moveDocs(from, to) {
  const moved = (p) => (p === from ? to : p.startsWith(`${from}/`) ? to + p.slice(from.length) : p);
  const docs = new Map();
  for (const [p, doc] of files.docs) {
    doc.path = moved(p);
    docs.set(doc.path, doc);
  }
  files.docs = docs;
  files.order = files.order.map(moved);
  files.open = new Set([...files.open].map(moved));
  if (files.path) files.path = moved(files.path);
  renderTabs();
  if (files.path) renderEditor(null); // Kopfzeile mit neuem Pfad, der Text bleibt stehen
  saveTabs();
}

async function deletePath(path) {
  if (!roleAtLeast("code") || !path) return;
  const entry = findEntry(path);
  if (!confirm(`„${basename(path)}“${entry?.dir ? " samt Inhalt" : ""} löschen?\n\nEs landet im Papierkorb von Coder (~/.coder/trash).`)) return;
  try {
    await fileOp({ op: "delete", path });
  } catch (e) {
    return toast(e.message, { error: true });
  }
  for (const p of [...files.order]) {
    if (p === path || p.startsWith(`${path}/`)) await closeTab(p, true); // weg ist weg – nicht nach „Speichern?“ fragen
  }
  files.all = null;
  await loadTree(parentOf(path));
  renderTree();
  scheduleGit();
  toast(`${basename(path)} liegt im Papierkorb`);
}

// Das Kontextmenü im Baum – rechte Maustaste oder die Menü-Taste.
function showTreeMenu(x, y, path) {
  const entry = path ? findEntry(path) : null;
  const write = roleAtLeast("code");
  const items = [];
  if (entry && !entry.dir) items.push(["open", "Öffnen"]);
  if (write && (!entry || entry.dir)) items.push(["new-file", "Neue Datei …"], ["new-dir", "Neuer Ordner …"]);
  if (write && entry) items.push(["rename", "Umbenennen …", "F2"], ["delete", "Löschen", "Entf"]);
  if (entry) items.push(["copy", "Pfad kopieren"], ["chat", "In den Code-Chat"]);
  if (!items.length) return;
  const menu = $("#treeMenu");
  menu.innerHTML = items.map(([id, label, key]) =>
    `<button type="button" role="menuitem" data-menu="${id}"><span>${esc(label)}</span>${key ? `<kbd>${key}</kbd>` : ""}</button>`).join("");
  menu.dataset.path = path || "";
  menu.hidden = false;
  const w = menu.offsetWidth;
  const h = menu.offsetHeight;
  menu.style.left = `${Math.min(x, innerWidth - w - 8)}px`;
  menu.style.top = `${Math.min(y, innerHeight - h - 8)}px`;
  $("button", menu).focus();
}

function hideTreeMenu() {
  $("#treeMenu").hidden = true;
}

async function runTreeMenu(id, path) {
  hideTreeMenu();
  const entry = path ? findEntry(path) : null;
  const dir = entry ? (entry.dir ? path : parentOf(path)) : "";
  if (id === "open") openFile(path);
  else if (id === "new-file") startCreate("file", dir);
  else if (id === "new-dir") startCreate("dir", dir);
  else if (id === "rename") startRename(path);
  else if (id === "delete") deletePath(path);
  else if (id === "copy") copyText(path).then(() => toast("Pfad kopiert"));
  else if (id === "chat") {
    switchTab("code");
    insertIntoInput(`${input.value.trim()} ${path}`.trim() + " ");
  }
}

/* ---------------------------------------------------------------- Bearbeiten: Einrücken, Kommentieren, Zeilen */

// Wie getippt: execCommand bleibt in der Rückgängig-Liste des Textfelds – setRangeText nicht.
function editText(ta, start, end, text, selStart = null, selEnd = null) {
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(start, end);
  const ok = text ? document.execCommand("insertText", false, text) : document.execCommand("delete");
  if (!ok) {
    ta.setRangeText(text, start, end, "end");
    paintCode();
  }
  if (selStart !== null) ta.setSelectionRange(selStart, selEnd ?? selStart);
}

const LINE_COMMENT = { py: "#", sh: "#", yaml: "#", toml: "#", js: "//", go: "//", rust: "//", java: "//", c: "//", sql: "--" };

// Die ganzen Zeilen, die die Auswahl berührt.
function lineRange(value, start, end) {
  const from = value.lastIndexOf("\n", start - 1) + 1;
  let to = value.indexOf("\n", end > start && value[end - 1] === "\n" ? end - 1 : end);
  if (to < 0) to = value.length;
  return { from, to, lines: value.slice(from, to).split("\n") };
}

const PAIRS = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`" };

function editorKey(e, ta) {
  if (ta.readOnly) return false;
  const mod = e.ctrlKey || e.metaKey;
  const { selectionStart: s, selectionEnd: t, value } = ta;
  if (!mod && !e.altKey && e.key.length === 1) {
    const close = PAIRS[e.key];
    const next = value[t] || "";
    // Das schließende Zeichen steht schon da: darüber hinweg, statt es zu verdoppeln.
    if (s === t && next === e.key && (")]}".includes(e.key) || (close === e.key && helper.closed === s))) {
      e.preventDefault();
      ta.setSelectionRange(s + 1, s + 1);
      helper.closed = -1;
      return true;
    }
    if (close) {
      if (s !== t) { // Auswahl einklammern oder in Anführungszeichen setzen
        e.preventDefault();
        editText(ta, s, t, e.key + value.slice(s, t) + close, s + 1, t + 1);
        return true;
      }
      const quote = close === e.key;
      if (quote && /[\w\\]/.test(value[s - 1] || "")) return false; // don't, it's, \"
      if (next && !/[\s)\]},;:.]/.test(next)) return false;         // mitten im Wort nicht
      e.preventDefault();
      editText(ta, s, t, e.key + close, s + 1);
      helper.closed = s + 1;
      return true;
    }
  }
  if (e.key === "Backspace" && !mod && s === t && s > 0 && PAIRS[value[s - 1]] === value[s] && value[s]) {
    e.preventDefault(); // ein leeres Paar geht mit einem Tastendruck
    editText(ta, s - 1, s + 1, "", s - 1);
    return true;
  }
  if (e.key === "Tab" && !mod && !e.altKey) {
    e.preventDefault();
    const multi = value.slice(s, t).includes("\n");
    if (!multi && !e.shiftKey) {
      editText(ta, s, t, "  ");
      return true;
    }
    const r = lineRange(value, s, t);
    const lines = r.lines.map((l) => (e.shiftKey ? l.replace(/^( {1,2}|\t)/, "") : `  ${l}`));
    const text = lines.join("\n");
    editText(ta, r.from, r.to, text, multi ? r.from : Math.max(r.from, s + (text.length - (r.to - r.from))), multi ? r.from + text.length : null);
    return true;
  }
  if (e.key === "Enter" && !mod && !e.altKey && !e.shiftKey) {
    // Neue Zeile mit derselben Einrückung – nach „:“ (Python) oder einer offenen Klammer eine Stufe mehr.
    e.preventDefault();
    const lineStart = value.lastIndexOf("\n", s - 1) + 1;
    const before = value.slice(lineStart, s);
    let indent = before.match(/^[ \t]*/)[0];
    const lang = langOf(files.path);
    if (/[{[(]\s*$/.test(before) || (lang === "py" && /:\s*$/.test(before))) indent += "  ";
    editText(ta, s, t, `\n${indent}`);
    return true;
  }
  if (mod && (e.key === "/" || e.code === "Slash" || e.key === "#")) {
    const mark = LINE_COMMENT[langOf(files.path)];
    if (!mark) return false;
    e.preventDefault();
    const r = lineRange(value, s, t);
    const filled = r.lines.filter((l) => l.trim());
    const off = filled.length && filled.every((l) => l.trimStart().startsWith(mark));
    const lines = r.lines.map((l) => {
      if (!l.trim()) return l;
      if (off) return l.replace(new RegExp(`^(\\s*)${mark.replace(/[/]/g, "\\/")} ?`), "$1");
      return l.replace(/^(\s*)/, `$1${mark} `);
    });
    const text = lines.join("\n");
    editText(ta, r.from, r.to, text, r.from, r.from + text.length);
    return true;
  }
  if (e.altKey && !mod && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
    // Zeilen verschieben wie in VS Code.
    e.preventDefault();
    const r = lineRange(value, s, t);
    const up = e.key === "ArrowUp";
    if (up ? r.from === 0 : r.to >= value.length) return true;
    const block = value.slice(r.from, r.to);
    if (up) {
      const prevStart = value.lastIndexOf("\n", r.from - 2) + 1;
      const prev = value.slice(prevStart, r.from - 1);
      editText(ta, prevStart, r.to, `${block}\n${prev}`, s - prev.length - 1, t - prev.length - 1);
    } else {
      let nextEnd = value.indexOf("\n", r.to + 1);
      if (nextEnd < 0) nextEnd = value.length;
      const next = value.slice(r.to + 1, nextEnd);
      editText(ta, r.from, nextEnd, `${next}\n${block}`, s + next.length + 1, t + next.length + 1);
    }
    return true;
  }
  return false;
}

function goToLine(line, col = 1, len = 0) {
  const ta = $("#fileText");
  if (!ta) return;
  const lines = ta.value.split("\n");
  const n = Math.max(1, Math.min(line, lines.length));
  let at = 0;
  for (let i = 0; i < n - 1; i++) at += lines[i].length + 1;
  at += Math.max(0, Math.min(col - 1, lines[n - 1].length));
  ta.focus({ preventScroll: true });
  ta.setSelectionRange(at, at + len);
  const lh = parseFloat(getComputedStyle(ta).lineHeight) || 20;
  ta.scrollTop = Math.max(0, (n - 1) * lh - ta.clientHeight / 3);
  syncScroll();
  renderStatus();
}

/* ---------------------------------------------------------------- Suchen und Ersetzen in der Datei */

const finder = { hits: [], index: -1, case: false, regex: false, timer: 0 };
const MAX_FIND = 5000;

function openFind(replace = false) {
  if (!files.path) return;
  const bar = $("#findBar");
  const ta = $("#fileText");
  bar.hidden = false;
  $("#replaceRow").hidden = !(replace && files.writable);
  const picked = ta ? ta.value.slice(ta.selectionStart, ta.selectionEnd) : "";
  if (picked && !picked.includes("\n")) $("#findInput").value = picked;
  $("#findInput").focus();
  $("#findInput").select();
  runFind();
}

function closeFind() {
  $("#findBar").hidden = true;
  finder.hits = [];
  paintMarks();
  $("#fileText")?.focus();
}

function findRx(flags = "g") {
  const q = $("#findInput").value;
  if (!q) return null;
  try {
    return new RegExp(finder.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), finder.case ? flags : `${flags}i`);
  } catch {
    return undefined; // ungültiger Ausdruck
  }
}

function scheduleFind() {
  clearTimeout(finder.timer);
  finder.timer = setTimeout(() => runFind(true), 120);
}

function runFind(keep = false) {
  const ta = $("#fileText");
  const rx = findRx();
  finder.hits = [];
  if (ta && rx) {
    let m;
    while ((m = rx.exec(ta.value)) && finder.hits.length < MAX_FIND) {
      if (!m[0]) { rx.lastIndex++; continue; }
      finder.hits.push({ start: m.index, end: m.index + m[0].length });
    }
  }
  const at = ta ? ta.selectionStart : 0;
  if (!keep || finder.index >= finder.hits.length) finder.index = finder.hits.findIndex((h) => h.end > at);
  if (finder.index < 0 && finder.hits.length) finder.index = 0;
  $("#findCount").textContent = rx === undefined ? "Ungültiger Ausdruck" : !rx ? ""
    : finder.hits.length ? `${finder.index + 1} von ${finder.hits.length}${finder.hits.length >= MAX_FIND ? "+" : ""}` : "Keine Treffer";
  $("#findCount").classList.toggle("none", !!rx && !finder.hits.length || rx === undefined);
  paintMarks();
  if (!keep) showHit();
}

function paintMarks() {
  const layer = $("#fileMarks");
  const ta = $("#fileText");
  if (!layer || !ta) return;
  if (!finder.hits.length || $("#findBar").hidden) {
    layer.textContent = "";
    return;
  }
  const v = ta.value;
  const out = [];
  let last = 0;
  finder.hits.forEach((h, i) => {
    out.push(esc(v.slice(last, h.start)), `<mark class="${i === finder.index ? "on" : ""}">${esc(v.slice(h.start, h.end))}</mark>`);
    last = h.end;
  });
  out.push(esc(v.slice(last)), "\n");
  layer.innerHTML = out.join("");
  syncScroll();
}

function showHit() {
  const hit = finder.hits[finder.index];
  const ta = $("#fileText");
  if (!hit || !ta) return;
  ta.setSelectionRange(hit.start, hit.end);
  const { line } = caretSpot(ta.value, hit.start);
  const lh = parseFloat(getComputedStyle(ta).lineHeight) || 20;
  const y = line * lh;
  if (y < ta.scrollTop || y > ta.scrollTop + ta.clientHeight - lh * 2) ta.scrollTop = Math.max(0, y - ta.clientHeight / 3);
  syncScroll();
  renderStatus();
}

function stepFind(dir) {
  if (!finder.hits.length) return runFind();
  finder.index = (finder.index + dir + finder.hits.length) % finder.hits.length;
  $("#findCount").textContent = `${finder.index + 1} von ${finder.hits.length}`;
  paintMarks();
  showHit();
}

function replaceOne() {
  const ta = $("#fileText");
  const hit = finder.hits[finder.index];
  const rx = findRx("");
  if (!ta || !hit || !rx || !files.writable) return;
  const found = ta.value.slice(hit.start, hit.end);
  const text = found.replace(rx, $("#replaceInput").value);
  editText(ta, hit.start, hit.end, text, hit.start + text.length);
  runFind(true);
  showHit();
}

function replaceAll() {
  const ta = $("#fileText");
  const rx = findRx();
  if (!ta || !rx || !files.writable || !finder.hits.length) return;
  const count = finder.hits.length;
  const next = ta.value.replace(rx, $("#replaceInput").value);
  editText(ta, 0, ta.value.length, next, 0); // ein Schritt in der Rückgängig-Liste
  runFind(true);
  toast(`${count} ersetzt`);
}

/* ---------------------------------------------------------------- Statuszeile */

const LANG_NAMES = {
  py: "Python", js: "JavaScript", json: "JSON", html: "HTML", css: "CSS", md: "Markdown", sh: "Shell", yaml: "YAML",
  toml: "TOML", sql: "SQL", go: "Go", rust: "Rust", java: "Java", c: "C/C++",
};

function renderStatus() {
  const el = $("#ideStatus");
  if (!el || state.tab !== "ide") return;
  const ta = $("#fileText");
  const parts = [];
  const doc = files.docs.get(files.path);
  const git = files.git?.repo ? `<span class="status-branch" title="Branch${files.git.ahead ? ` · ${files.git.ahead} Commits vor` : ""}${files.git.behind ? ` · ${files.git.behind} Commits hinter` : ""} dem Server">${ICONS.branch}${esc(files.git.branch || "ohne Branch")}${files.git.ahead ? ` ↑${files.git.ahead}` : ""}${files.git.behind ? ` ↓${files.git.behind}` : ""}</span>`
    + (Object.keys(files.git.files || {}).length ? `<span>${Object.keys(files.git.files).length} geändert</span>` : "") : "";
  if (doc?.kind === "image") {
    parts.push(`<span>Bild${doc.size ? ` · ${esc(doc.size)}` : ""}</span>`);
  } else if (doc?.diff) {
    parts.push("<span>Änderungen seit dem letzten Commit</span>");
  } else if (doc?.preview) {
    parts.push("<span>Markdown-Vorschau</span>");
  } else if (files.path && ta) {
    const spot = caretSpot(ta.value, ta.selectionStart, 1);
    const sel = Math.abs(ta.selectionEnd - ta.selectionStart);
    parts.push(`<span>Zeile ${spot.line + 1}, Spalte ${spot.col + 1}${sel ? ` (${sel} ausgewählt)` : ""}</span>`);
    parts.push(`<span>${esc(LANG_NAMES[langOf(files.path)] || "Text")}</span>`);
    parts.push(`<span title="Zeilenenden – beim Speichern bleiben sie, wie sie waren">${files.eol === "\r\n" ? "CRLF" : "LF"}</span>`);
    parts.push("<span>UTF-8</span>", "<span>Leerzeichen: 2</span>");
    if (!files.writable) parts.push(`<span class="status-warn">Nur lesen</span>`);
  } else {
    parts.push(`<span>${esc(files.root || ideWorkspace())}</span>`);
  }
  const running = term.running ? `<span class="status-run">Terminal: läuft</span>` : "";
  el.innerHTML = `${git}${running}<span class="spacer"></span>${parts.join("")}`;
}

/* ---------------------------------------------------------------- Suche in allen Dateien */

const fileSearch = { timer: 0, seq: 0 };

function setExplorerView(view) {
  $$("#explorer [data-xview]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.xview === view)));
  $("#fileTree").hidden = view !== "files";
  $("#explorerActions").hidden = view !== "files";
  $("#filesRoot").hidden = view !== "files";
  $("#findFiles").hidden = view !== "search";
  if (view === "search") {
    $("#findFilesInput").focus();
    $("#findFilesInput").select();
  }
}

async function runFileSearch() {
  const q = $("#findFilesInput").value;
  const seq = ++fileSearch.seq;
  const list = $("#findFilesList");
  const count = $("#findFilesCount");
  if (!q.trim()) {
    list.innerHTML = "";
    count.textContent = "";
    return;
  }
  count.textContent = "Sucht …";
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&workspace=${encodeURIComponent(files.root || ideWorkspace())}`
      + `&regex=${$("#findRegex").getAttribute("aria-pressed")}&case=${$("#findCase").getAttribute("aria-pressed")}`);
    if (seq !== fileSearch.seq) return;
    const groups = new Map();
    for (const hit of data.hits) {
      if (!groups.has(hit.path)) groups.set(hit.path, []);
      groups.get(hit.path).push(hit);
    }
    count.textContent = data.hits.length
      ? `${data.hits.length}${data.capped ? "+" : ""} Treffer in ${groups.size} ${groups.size === 1 ? "Datei" : "Dateien"}`
      : "Keine Treffer";
    list.innerHTML = [...groups].map(([path, hits]) => `
      <div class="hit-file">
        <button type="button" class="hit-head" data-hit-path="${esc(path)}" title="${esc(path)}">
          <span class="hit-name">${esc(basename(path))}</span><span class="hit-dir">${esc(parentOf(path))}</span>
          <span class="hit-count">${hits.length}</span>
        </button>
        ${hits.map((h) => {
          const before = h.text.slice(Math.max(0, h.col - 1 - 30), h.col - 1);
          const match = h.text.slice(h.col - 1, h.col - 1 + h.len);
          const after = h.text.slice(h.col - 1 + h.len, h.col - 1 + h.len + 80);
          return `<button type="button" class="hit" data-hit-path="${esc(path)}" data-line="${h.line}" data-col="${h.col}" data-len="${h.len}">
            <span class="hit-line">${h.line}</span><span class="hit-text">${esc(before.trimStart())}<mark>${esc(match)}</mark>${esc(after)}</span></button>`;
        }).join("")}
      </div>`).join("");
  } catch (e) {
    if (seq === fileSearch.seq) count.textContent = e.message;
  }
}

/* ---------------------------------------------------------------- Terminal */

// Ein Befehl nach dem anderen, im Workspace, auf diesem Rechner. Was er ausgibt, kommt Stück für Stück über den
// WebSocket; was du tippst, während er läuft, bekommt er als Eingabe. Interaktive Vollbild-Programme gehen nicht.
const term = { id: null, running: false, started: 0, history: [], hpos: -1 };
const MAX_TERM_CHARS = 200_000;
const ANSI_RX = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]/g;
const RUNNERS = {
  py: 'python "{}"', pyw: 'python "{}"', js: 'node "{}"', mjs: 'node "{}"', cjs: 'node "{}"', ts: 'npx --yes tsx "{}"',
  sh: 'bash "{}"', ps1: 'powershell -NoProfile -ExecutionPolicy Bypass -File "{}"', bat: 'cmd /c "{}"', cmd: 'cmd /c "{}"',
  go: 'go run "{}"', java: 'java "{}"', rb: 'ruby "{}"', php: 'php "{}"', lua: 'lua "{}"',
};

function toggleTerminal(show = $("#idePanel").hidden) {
  if (!roleAtLeast("code")) return toast("Befehle darf dein Konto nicht ausführen.", { error: true });
  if (show && state.tab !== "ide") switchTab("ide");
  $("#idePanel").hidden = !show;
  store.set("coder.terminal", show ? "1" : "0");
  if (show) $("#termInput").focus();
  else $("#fileText")?.focus();
}

// Stellen in der Ausgabe, die auf eine Datei zeigen: Python-Tracebacks (File "x.py", line 3), Compiler und
// Linter (x.ts:4:7) und .NET/TypeScript (x.cs(4,7)). Ein Klick darauf springt im Editor an die Stelle.
const FILE_REF_RX = /File "([^"\n]+)", line (\d+)|((?:[A-Za-z]:[\\/])?[\w.\-\\/]*\.[A-Za-z][\w]{0,5})(?::(\d+)(?::(\d+))?|\((\d+),(\d+)\))/g;

function fileRefs(text) {
  const out = [];
  let m;
  FILE_REF_RX.lastIndex = 0;
  while ((m = FILE_REF_RX.exec(text))) {
    const path = m[1] || m[3];
    if (/\w:\/\//.test(text.slice(Math.max(0, m.index - 10), m.index + 4))) continue; // eine Adresse, keine Datei
    if (/^\d+(\.\d+)+$/.test(path)) continue; // eine Versionsnummer wie 1.2.3:4
    out.push({ start: m.index, end: m.index + m[0].length, path, line: Number(m[2] || m[4] || m[6]), col: Number(m[5] || m[7] || 1) });
  }
  return out;
}

// Ein Pfad aus der Ausgabe als Pfad im Workspace – oder null, wenn er woanders hinzeigt.
function workspacePath(raw, root) {
  const p = String(raw).replace(/\\/g, "/").replace(/^\.\//, "");
  const base = String(root || "").replace(/\\/g, "/").replace(/\/+$/, "");
  if (/^[A-Za-z]:\//.test(p) || p.startsWith("/")) {
    return base && p.toLowerCase().startsWith(`${base.toLowerCase()}/`) ? p.slice(base.length + 1) : null;
  }
  return p.startsWith("../") ? null : p;
}

function termWrite(text, cls = "") {
  const out = $("#termOut");
  const atEnd = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
  const clean = text.replace(ANSI_RX, "").replace(/\r(?!\n)/g, "\n");
  const box = cls ? document.createElement("span") : document.createDocumentFragment();
  if (cls) box.className = cls;
  let last = 0;
  for (const ref of cls ? [] : fileRefs(clean)) {
    const path = workspacePath(ref.path, files.root || ideWorkspace());
    if (!path) continue;
    box.append(clean.slice(last, ref.start));
    const link = document.createElement("a");
    link.className = "term-link";
    link.href = "#";
    link.textContent = clean.slice(ref.start, ref.end);
    link.dataset.path = path;
    link.dataset.line = ref.line;
    link.dataset.col = ref.col;
    link.title = `${path}, Zeile ${ref.line} öffnen`;
    box.append(link);
    last = ref.end;
  }
  box.append(clean.slice(last));
  out.append(box);
  // Nur das Ende behalten – ein Watcher kann stundenlang schreiben. Gezählt wird mit, statt jedes Mal alles zu lesen.
  term.chars = (term.chars || 0) + clean.length;
  while (term.chars > MAX_TERM_CHARS && out.firstChild) {
    term.chars -= out.firstChild.textContent.length;
    out.firstChild.remove();
  }
  if (atEnd) out.scrollTop = out.scrollHeight;
}

function runInTerminal(command) {
  command = command.trim();
  if (!command) return;
  if (!roleAtLeast("code")) return toast("Befehle darf dein Konto nicht ausführen.", { error: true });
  if (!serverHas("1.11.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  if (term.running) return toast("Es läuft noch ein Befehl – erst stoppen.", { error: true });
  if ($("#idePanel").hidden) toggleTerminal(true);
  term.id = `t${Date.now().toString(36)}`;
  term.running = true;
  term.started = Date.now();
  if (term.history.at(-1) !== command) term.history.push(command);
  term.hpos = -1;
  termWrite(`${$("#termOut").textContent ? "\n" : ""}> ${command}\n`, "term-cmd");
  send({ type: "term_start", id: term.id, command, workspace: files.root || ideWorkspace() });
  renderTermState();
}

function renderTermState() {
  $("#termStop").hidden = !term.running;
  $("#termState").textContent = term.running ? "läuft" : "";
  $("#termPrompt").textContent = term.running ? "›" : ">";
  $("#termInput").placeholder = term.running ? "Eingabe für den laufenden Befehl – Strg+C stoppt" : "Befehl im Workspace – ↑ holt frühere";
  $("#idePanel").classList.toggle("running", term.running);
  renderStatus();
}

async function runFile() {
  if (!files.path) return toast("Erst eine Datei öffnen.");
  const ext = files.path.split(".").pop().toLowerCase();
  const pattern = RUNNERS[ext];
  if (!pattern) return toast("Diese Datei lässt sich nicht direkt ausführen – im Terminal geht jeder Befehl.");
  if (fileDirty()) await saveFile();
  runInTerminal(pattern.replace("{}", files.path));
}

// Die Auswahl – oder die Datei – als Nachricht an den Agent im Tab Code.
function askCoder() {
  if (!files.path) return toast("Erst eine Datei öffnen.");
  if (!roleAtLeast("read")) return;
  const ta = $("#fileText");
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  let text = files.path;
  if (s !== e) {
    const a = caretSpot(ta.value, s).line + 1;
    const b = caretSpot(ta.value, e - 1).line + 1;
    const fence = files.path.split(".").pop().toLowerCase();
    text = `${files.path}:${a}${b > a ? `-${b}` : ""}\n\`\`\`${fence}\n${ta.value.slice(s, e).replace(/\n$/, "")}\n\`\`\`\n`;
  }
  switchTab("code");
  insertIntoInput(`${input.value.trim() ? `${input.value.trim()}\n` : ""}${text}${s !== e ? "" : " "}`);
}

/* ---------------------------------------------------------------- Verdrahtung */

$("#fileTree").addEventListener("click", (e) => {
  if (e.target.closest(".editing")) return;
  const row = e.target.closest("[data-path]");
  if (!row) return;
  files.sel = row.dataset.path;
  if (row.dataset.dir === "1") toggleDir(row.dataset.path);
  else openFile(row.dataset.path);
});
$("#fileTree").addEventListener("contextmenu", (e) => {
  e.preventDefault();
  const row = e.target.closest("[data-path]");
  if (row) files.sel = row.dataset.path;
  showTreeMenu(e.clientX, e.clientY, row?.dataset.path || "");
});
$("#fileTree").addEventListener("keydown", (e) => {
  if (e.target.id === "treeInput") {
    if (e.key === "Enter") { e.preventDefault(); commitTreeInput(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); files.pending = null; renderTree(); }
    return;
  }
  const row = e.target.closest("[data-path]");
  if (!row) return;
  if (e.key === "F2") { e.preventDefault(); startRename(row.dataset.path); }
  else if (e.key === "Delete") { e.preventDefault(); deletePath(row.dataset.path); }
  else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
    e.preventDefault();
    const r = row.getBoundingClientRect();
    showTreeMenu(r.left + 24, r.bottom, row.dataset.path);
  } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const rows = $$("#fileTree [data-path]");
    rows[Math.max(0, Math.min(rows.length - 1, rows.indexOf(row) + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  }
});
$("#fileTree").addEventListener("focusout", (e) => {
  // Klick daneben: anlegen wie mit Enter, wenn schon ein Name dasteht – sonst verwerfen.
  if (e.target.id === "treeInput" && files.pending) setTimeout(() => {
    if (!files.pending || document.activeElement?.id === "treeInput") return;
    if (e.target.value.trim()) commitTreeInput();
    else { files.pending = null; renderTree(); }
  }, 0);
});
$("#treeMenu").addEventListener("click", (e) => {
  const item = e.target.closest("[data-menu]");
  if (item) runTreeMenu(item.dataset.menu, $("#treeMenu").dataset.path);
});
$("#treeMenu").addEventListener("keydown", (e) => {
  const items = $$("#treeMenu button");
  const at = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.stopPropagation(); hideTreeMenu(); }
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
  }
});
document.addEventListener("mousedown", (e) => { if (!$("#treeMenu").hidden && !e.target.closest("#treeMenu")) hideTreeMenu(); });
window.addEventListener("blur", hideTreeMenu);

$("#explorerActions").addEventListener("click", (e) => {
  const kind = e.target.closest("[data-fs]")?.dataset.fs;
  if (kind) startCreate(kind);
});
$("#filesReload").addEventListener("click", async () => {
  files.tree.clear();
  files.all = null;
  await loadTree("");
  await Promise.all([...files.open].map(loadTree));
  renderTree();
  loadGit();
  for (const doc of files.docs.values()) if (!docDirty(doc) && doc.kind !== "image") reloadDoc(doc.path);
});
$("#filesCollapse").addEventListener("click", () => {
  files.open.clear();
  renderTree();
});
$("#explorer").addEventListener("click", (e) => {
  const view = e.target.closest("[data-xview]")?.dataset.xview;
  if (view) setExplorerView(view);
});
$("#findFilesForm").addEventListener("submit", (e) => {
  e.preventDefault();
  clearTimeout(fileSearch.timer);
  runFileSearch();
});
$("#findFilesInput").addEventListener("input", () => {
  clearTimeout(fileSearch.timer);
  fileSearch.timer = setTimeout(runFileSearch, 350);
});
for (const id of ["#findCase", "#findRegex", "#findInCase", "#findInRegex"]) {
  $(id).addEventListener("click", (e) => {
    const btn = e.currentTarget;
    const on = btn.getAttribute("aria-pressed") !== "true";
    btn.setAttribute("aria-pressed", String(on));
    if (id === "#findInCase") finder.case = on;
    if (id === "#findInRegex") finder.regex = on;
    if (id.startsWith("#findIn")) runFind();
    else runFileSearch();
  });
}
$("#findFilesList").addEventListener("click", (e) => {
  const hit = e.target.closest("[data-hit-path]");
  if (!hit) return;
  openFile(hit.dataset.hitPath, hit.dataset.line
    ? { line: Number(hit.dataset.line), col: Number(hit.dataset.col), len: Number(hit.dataset.len) } : {});
});

$("#ideTabs").addEventListener("click", (e) => {
  const close = e.target.closest("[data-close-tab]");
  if (close) return closeTab(close.dataset.closeTab);
  const tab = e.target.closest("[data-tab-path]");
  if (tab) activate(tab.dataset.tabPath);
});
$("#ideTabs").addEventListener("auxclick", (e) => {
  const tab = e.target.closest("[data-tab-path]");
  if (tab && e.button === 1) { e.preventDefault(); closeTab(tab.dataset.tabPath); }
});
$("#ideTabs").addEventListener("keydown", (e) => {
  const tab = e.target.closest("[data-tab-path]");
  if (!tab) return;
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(tab.dataset.tabPath); }
  else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    const tabs = $$("#ideTabs [data-tab-path]");
    tabs[(tabs.indexOf(tab) + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length]?.focus();
  }
});
$("#fileHead").addEventListener("click", (e) => {
  const what = e.target.closest("[data-file]")?.dataset.file;
  if (what === "save") saveFile();
  else if (what === "revert") revertFile();
  else if (what === "preview") togglePreview();
  else if (what === "diff") toggleDiff();
});
$("#fileBody").addEventListener("click", (e) => {
  const row = e.target.closest(".diff-line[data-line]");
  if (!row || !files.path) return;
  const doc = files.docs.get(files.path);
  if (doc) doc.diff = false;
  const line = Number(row.dataset.line);
  const path = files.path;
  files.path = null;
  activate(path);
  goToLine(line);
});
$("#findInput").addEventListener("input", () => runFind());
$("#findInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); stepFind(e.shiftKey ? -1 : 1); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeFind(); }
});
$("#replaceInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); if (e.ctrlKey || e.altKey) replaceAll(); else replaceOne(); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeFind(); }
});
$("#findPrev").addEventListener("click", () => stepFind(-1));
$("#findNext").addEventListener("click", () => stepFind(1));
$("#findClose").addEventListener("click", closeFind);
$("#replaceOne").addEventListener("click", replaceOne);
$("#replaceAll").addEventListener("click", replaceAll);

$("#runFile").addEventListener("click", runFile);
$("#askCoder").addEventListener("click", askCoder);
$("#termToggle").addEventListener("click", () => toggleTerminal());
$("#termClose").addEventListener("click", () => toggleTerminal(false));
$("#termClear").addEventListener("click", () => { $("#termOut").textContent = ""; term.chars = 0; $("#termInput").focus(); });
$("#termOut").addEventListener("click", (e) => {
  const link = e.target.closest(".term-link");
  if (!link) return;
  e.preventDefault();
  openFile(link.dataset.path, { line: Number(link.dataset.line), col: Number(link.dataset.col) });
});
$("#termStop").addEventListener("click", () => { if (term.running) send({ type: "term_stop", id: term.id }); });
$("#termForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const field = $("#termInput");
  const text = field.value;
  field.value = "";
  if (term.running) {
    termWrite(`${text}\n`, "term-echo");
    send({ type: "term_input", id: term.id, text: `${text}\n` });
  } else runInTerminal(text);
});
$("#termInput").addEventListener("keydown", (e) => {
  const field = e.currentTarget;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c" && term.running && field.selectionStart === field.selectionEnd) {
    e.preventDefault();
    send({ type: "term_stop", id: term.id });
  } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !term.running && term.history.length) {
    e.preventDefault();
    const n = term.history.length;
    term.hpos = e.key === "ArrowUp" ? (term.hpos < 0 ? n - 1 : Math.max(0, term.hpos - 1)) : term.hpos < 0 ? -1 : term.hpos + 1;
    if (term.hpos >= n) term.hpos = -1;
    field.value = term.hpos < 0 ? "" : term.history[term.hpos];
  } else if (e.key === "Escape") {
    e.stopPropagation();
    toggleTerminal(false);
  }
});
// Die Höhe des Terminals mit der Leiste darüber ziehen – gemerkt fürs nächste Mal.
$("#panelGrip").addEventListener("pointerdown", (e) => {
  const panel = $("#idePanel");
  const start = e.clientY;
  const from = panel.offsetHeight;
  const move = (ev) => {
    const h = Math.max(120, Math.min(innerHeight * 0.75, from + start - ev.clientY));
    $("#ide").style.setProperty("--panel-h", `${h}px`);
  };
  const up = () => {
    removeEventListener("pointermove", move);
    store.set("coder.panelH", $("#ide").style.getPropertyValue("--panel-h"));
  };
  addEventListener("pointermove", move);
  addEventListener("pointerup", up, { once: true });
});
if (store.get("coder.panelH")) $("#ide").style.setProperty("--panel-h", store.get("coder.panelH"));
if (store.get("coder.editorSize")) $("#ide").style.setProperty("--editor-size", `${Number(store.get("coder.editorSize"))}px`);
window.addEventListener("beforeunload", (e) => {
  if (anyDirty() || (state.session?.incognito && thread.childElementCount)) {
    e.preventDefault();
    e.returnValue = "";
  }
});

/* ================================================================ Ergänzen: Vorschläge bauen */

// Zwei Wege führen zu einem Vorschlag. Die Liste beim Tippen kommt aus der Datei selbst – Wörter, die schon
// dastehen, Schlüsselwörter der Sprache und Pfade aus dem Baum: sofort da, ohne Modell, ohne Grafikkarte.
// Der graue Text hinter dem Cursor kommt vom Modell (core/complete.py) und erscheint, wenn das Tippen ruht.
// Alles hier ist reine Rechnerei ohne Oberfläche – dadurch lässt es sich mit Node prüfen.

const MIN_WORD = 2;      // ab so vielen getippten Zeichen lohnt eine Liste
const MAX_SUGGEST = 8;   // mehr Zeilen liest ohnehin niemand
const WORD_RX = /[A-Za-z_$][\w$]*/g;
const WORD_CHAR = /[\w$]/;
// Was in einem Pfad vorkommen darf – Anführungszeichen und Klammern begrenzen ihn.
const PATH_CHAR = /[^\s"'`<>()[\]{},;:=]/;

// Das Wort links vom Cursor: ab wo es steht und wie es bisher heißt.
function wordAt(text, pos) {
  let start = pos;
  while (start > 0 && WORD_CHAR.test(text[start - 1])) start--;
  return { start, word: text.slice(start, pos) };
}

// Steht der Cursor in einem Pfad? Erst ab einem „/“ – sonst käme bei jedem Wort der halbe Ordner mit.
function pathAt(text, pos) {
  let start = pos;
  while (start > 0 && PATH_CHAR.test(text[start - 1])) start--;
  const word = text.slice(start, pos);
  return word.includes("/") ? { start, word } : null;
}

// Jedes Wort der Datei mit seiner Häufigkeit – was oft dasteht, ist meist auch gemeint.
function wordCounts(text) {
  const counts = new Map();
  let m;
  WORD_RX.lastIndex = 0;
  while ((m = WORD_RX.exec(text))) {
    if (m[0].length < 3) continue;
    counts.set(m[0], (counts.get(m[0]) || 0) + 1);
  }
  return counts;
}

// Wie gut ein Wort zum Getippten passt: Anfang schlägt Mitte, Mitte schlägt verstreute Buchstaben.
function scoreWord(candidate, typed) {
  if (candidate === typed) return 0; // steht schon da
  const c = candidate.toLowerCase();
  const t = typed.toLowerCase();
  if (c.startsWith(t)) return 100;
  if (c.includes(t)) return 40;
  let i = 0;
  for (const ch of c) {
    if (ch === t[i]) i++;
    if (i === t.length) return 20;
  }
  return 0;
}

function bestFirst(a, b) {
  return b.score - a.score || a.text.length - b.text.length || (a.text < b.text ? -1 : 1);
}

// Wörter der Datei und Schlüsselwörter der Sprache. Das gerade getippte Wort zählt nicht mit sich selbst.
function matchWords(typed, text, start, end, lang) {
  const out = [];
  const seen = new Set();
  for (const [word, count] of wordCounts(text.slice(0, start) + "\n" + text.slice(end))) {
    const score = scoreWord(word, typed);
    if (!score) continue;
    seen.add(word);
    out.push({ text: word, kind: "wort", score: score + Math.min(count, 5) });
  }
  for (const kw of (KEYWORDS[lang] || "").split(" ")) {
    if (!kw || seen.has(kw)) continue;
    const score = scoreWord(kw, typed);
    if (score) out.push({ text: kw, kind: "sprache", score });
  }
  return out.sort(bestFirst).slice(0, MAX_SUGGEST);
}

// Pfade aus dem Dateibaum: entweder der ganze Anfang passt oder der Dateiname am Ende.
function matchPaths(frag, paths) {
  const want = frag.toLowerCase();
  const base = want.split("/").pop();
  const out = [];
  for (const entry of paths) {
    const low = String(entry.path).toLowerCase();
    let score = 0;
    if (low.startsWith(want) && low !== want) score = 100;
    else if (base && low.split("/").pop().startsWith(base)) score = 40;
    else continue;
    out.push({ text: entry.dir ? `${entry.path}/` : entry.path, kind: "pfad", score });
  }
  return out.sort(bestFirst).slice(0, MAX_SUGGEST);
}

// Was an dieser Stelle zur Auswahl steht – oder nichts.
function suggestions(text, pos, lang, paths = []) {
  const inPath = pathAt(text, pos);
  if (inPath) {
    const items = matchPaths(inPath.word, paths);
    return items.length ? { ...inPath, items } : null;
  }
  const { start, word } = wordAt(text, pos);
  if (word.length < MIN_WORD) return null;
  const items = matchWords(word, text, start, pos, lang);
  return items.length ? { start, word, items } : null;
}

// Den grauen Vorschlag in die eingefärbte Fassung setzen: gezählt wird in Zeichen des Textes, nicht in
// Zeichen des HTML – Auszeichnungen und Maskierungen (&lt;) dürfen die Stelle nicht verschieben.
function insertAt(html, index, insert) {
  let count = 0;
  let i = 0;
  while (i < html.length && count < index) {
    if (html[i] === "<") {
      const close = html.indexOf(">", i);
      i = close < 0 ? html.length : close + 1;
      continue;
    }
    if (html[i] === "&") {
      const end = html.indexOf(";", i);
      if (end > 0 && end - i <= 6) {
        i = end + 1;
        count++;
        continue;
      }
    }
    i++;
    count++;
  }
  return html.slice(0, i) + insert + html.slice(i);
}

// Reicht der Vorschlag über mehrere Zeilen, rücken die Zeilen darunter nach unten – die Nummern müssen mit.
function ghostGutter(numbers, at, extra) {
  const out = numbers.slice();
  out.splice(at + 1, 0, ...Array(extra).fill(""));
  return out;
}

// Zeile und Spalte des Cursors. Tabulatoren zählen bis zum nächsten Vielfachen – so steht die Liste richtig.
function caretSpot(text, pos, tab = 2) {
  const before = text.slice(0, pos);
  const line = before.split("\n").length - 1;
  const current = before.slice(before.lastIndexOf("\n") + 1);
  let col = 0;
  for (const ch of current) col = ch === "\t" ? col + tab - (col % tab) : col + 1;
  return { line, col };
}

/* ================================================================ Ergänzen: Liste und Vorschlag im Editor */

// Der Zustand des Ergänzers. `at` ist die Stelle, für die der graue Vorschlag gilt: Wandert der Cursor
// woandershin, ist der Vorschlag hinfällig.
const helper = {
  list: null,   // offene Liste: { start, word, items, index }
  ghost: "",    // der graue Vorschlag vom Modell
  at: -1,
  hint: "",     // die kleine Zeile dazu in der Kopfzeile
  timer: 0,
  seq: 0,
  ctrl: null,   // laufende Anfrage – die nächste Eingabe bricht sie ab
  cw: 0,        // gemessene Zeichenbreite
};
const GHOST_DELAY = 350;  // so lange muss das Tippen ruhen, bevor das Modell gefragt wird
const GHOST_HINTS = {
  busy: "Der Agent arbeitet – Ergänzen pausiert",
  not_loaded: "Modell nicht im Speicher – Ergänzen wartet",
  off: "",
  timeout: "Das Modell hat zu lange gebraucht",
};

const ergaenzt = () => state.config?.complete !== false && serverHas("1.9.0");

// Alle Pfade, die der Baum schon kennt – mehr braucht die Liste nicht.
function treePaths() {
  const out = [];
  for (const entries of files.tree.values()) for (const e of entries) out.push({ path: e.path, dir: e.dir });
  return out;
}

function hideList() {
  helper.list = null;
  const box = $("#fileSuggest");
  if (box) box.hidden = true;
}

function clearGhost(repaint = true) {
  if (!helper.ghost && !helper.hint) return;
  helper.ghost = "";
  helper.at = -1;
  helper.hint = "";
  if (repaint) paintCode();
}

// Breite eines Zeichens in der Codeschrift – einmal gemessen, danach steht die Liste ohne Rechnerei richtig.
function charWidth() {
  if (helper.cw) return helper.cw;
  const code = $("#fileCode");
  if (!code) return 8;
  const probe = document.createElement("span");
  probe.textContent = "M".repeat(40);
  probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre";
  code.appendChild(probe);
  helper.cw = probe.getBoundingClientRect().width / 40 || 8;
  probe.remove();
  return helper.cw;
}

// Die Liste steht unter dem Cursor – am Rand rückt sie herein, unten klappt sie nach oben.
function placeList() {
  const ta = $("#fileText");
  const code = $("#fileCode");
  const box = $("#fileSuggest");
  if (!ta || !box || box.hidden) return;
  const cs = getComputedStyle(code);
  const lh = parseFloat(cs.lineHeight) || 20;
  const spot = caretSpot(ta.value, helper.list ? helper.list.start : ta.selectionStart);
  const x = (parseFloat(cs.paddingLeft) || 12) + spot.col * charWidth() - ta.scrollLeft;
  const y = (parseFloat(cs.paddingTop) || 12) + (spot.line + 1) * lh - ta.scrollTop;
  const wrap = ta.parentElement;
  box.style.left = `${Math.max(4, Math.min(x, wrap.clientWidth - box.offsetWidth - 8))}px`;
  box.style.top = y + box.offsetHeight <= wrap.clientHeight ? `${y}px` : `${Math.max(2, y - lh - box.offsetHeight)}px`;
}

const KIND_LABEL = { wort: "Datei", sprache: "Sprache", pfad: "Pfad" };

function renderList() {
  const box = $("#fileSuggest");
  const l = helper.list;
  if (!box || !l) return;
  box.innerHTML = l.items.map((item, i) => `
    <button type="button" class="code-item" role="option" data-i="${i}" aria-selected="${i === l.index}">
      <span class="code-item-name">${esc(item.text)}</span>
      <span class="code-item-kind">${esc(item.kind === "sprache" ? (langOf(files.path) || "Sprache") : KIND_LABEL[item.kind])}</span>
    </button>`).join("");
  box.hidden = false;
  placeList();
  const on = $(`[data-i="${l.index}"]`, box);
  if (on) on.scrollIntoView({ block: "nearest" });
}

function updateList() {
  const ta = $("#fileText");
  if (!ta || ta.selectionStart !== ta.selectionEnd) return hideList();
  const found = suggestions(ta.value, ta.selectionStart, langOf(files.path), treePaths());
  if (!found) return hideList();
  helper.list = { ...found, index: 0 };
  renderList();
}

function moveList(step) {
  const l = helper.list;
  if (!l) return;
  l.index = (l.index + step + l.items.length) % l.items.length;
  renderList();
}

function takeSuggestion(i) {
  const l = helper.list;
  const ta = $("#fileText");
  const item = l && l.items[i ?? l.index];
  if (!item || !ta) return false;
  hideList();
  clearGhost(false);
  ta.setRangeText(item.text, l.start, ta.selectionStart, "end");
  paintCode();
  scheduleGhost();
  ta.focus();
  return true;
}

// Den grauen Vorschlag übernehmen – er steht ja schon da, wo er hingehört.
function takeGhost() {
  const ta = $("#fileText");
  if (!ta || !helper.ghost || helper.at !== ta.selectionStart) return false;
  const text = helper.ghost;
  helper.ghost = "";
  helper.at = -1;
  helper.hint = "";
  hideList();
  ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, "end");
  paintCode();
  scheduleGhost();
  return true;
}

// Wer mit dem Vorschlag mittippt, behält ihn: Das getippte Zeichen fällt vorn weg, der Rest bleibt stehen.
function advanceGhost(ta) {
  if (!helper.ghost) return false;
  const pos = ta.selectionStart;
  if (pos === helper.at + 1 && ta.value[pos - 1] === helper.ghost[0]) {
    helper.ghost = helper.ghost.slice(1);
    helper.at = pos;
    return !!helper.ghost;
  }
  clearGhost(false);
  return false;
}

function scheduleGhost() {
  clearTimeout(helper.timer);
  if (!ergaenzt()) return;
  helper.timer = setTimeout(askGhost, GHOST_DELAY);
}

async function askGhost() {
  const ta = $("#fileText");
  if (!ta || !files.path || document.activeElement !== ta) return;
  const pos = ta.selectionStart;
  if (pos !== ta.selectionEnd) return;
  const value = ta.value;
  const seq = ++helper.seq;
  if (helper.ctrl) helper.ctrl.abort();
  helper.ctrl = new AbortController();
  try {
    const data = await api("/api/complete", {
      method: "POST",
      signal: helper.ctrl.signal,
      body: {
        path: files.path, workspace: currentWorkspace(),
        prefix: value.slice(0, pos), suffix: value.slice(pos),
        // Mitten in der Zeile reicht ein Stück Zeile; am Zeilenende darf es ein ganzer Block sein.
        multiline: !value.slice(pos).split("\n", 1)[0].trim(),
      },
    });
    // Inzwischen weitergetippt oder woanders geklickt? Dann ist die Antwort nichts mehr wert.
    if (seq !== helper.seq || ta.selectionStart !== pos || ta.value !== value) return;
    helper.ghost = String(data.text || "");
    helper.at = helper.ghost ? pos : -1;
    helper.hint = helper.ghost ? "Tab übernimmt" : (GHOST_HINTS[data.reason] || "");
    paintCode();
  } catch (e) {
    if (e.name !== "AbortError") helper.hint = "";
  }
}

// Tasten im Editor: Erst der Ergänzer, dann der Editor selbst (Tab rückt ein, Strg+S speichert).
function helperKey(e) {
  if (e.key === "Escape" && (helper.list || helper.ghost)) {
    e.preventDefault();
    e.stopPropagation(); // sonst schlösse Esc gleich das ganze Fenster
    hideList();
    clearGhost();
    return true;
  }
  if (helper.list) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      moveList(e.key === "ArrowDown" ? 1 : -1);
      return true;
    }
    if ((e.key === "Enter" || e.key === "Tab") && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      return takeSuggestion();
    }
  }
  if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.altKey && helper.ghost) {
    e.preventDefault();
    return takeGhost();
  }
  if (helper.ghost && (e.key.startsWith("Arrow") || ["Home", "End", "PageUp", "PageDown"].includes(e.key))) {
    clearGhost();
  }
  return false;
}

// Alles, was der Editor dem Ergänzer meldet – angelegt beim Öffnen einer Datei.
function wireHelper(ta) {
  helper.cw = 0;
  hideList();
  helper.ghost = "";
  helper.at = -1;
  helper.hint = "";
  ta.addEventListener("click", () => {
    hideList();
    clearGhost();
  });
  ta.addEventListener("blur", () => {
    clearTimeout(helper.timer);
    hideList();
    clearGhost();
  });
  const box = $("#fileSuggest");
  if (!box) return;
  // Mit gedrückter Maustaste bliebe der Fokus sonst nicht im Textfeld – und die Liste wäre schon weg.
  box.addEventListener("mousedown", (e) => e.preventDefault());
  box.addEventListener("click", (e) => {
    const row = e.target.closest("[data-i]");
    if (row) takeSuggestion(Number(row.dataset.i));
  });
}

/* ================================================================ Diktat: sprechen statt tippen */

// Das Mikrofon hat der Rechner, auf dem Coder läuft – die Oberfläche hat nur den Knopf. Aufnehmen, Pegel und
// Erkennen laufen deshalb über den WebSocket; aus dem LAN gibt es den Knopf gar nicht erst.
const mic = { state: "idle", info: null, seconds: 0, level: 0, wanted: "" };
const MIC_LABEL = { idle: "Sprechen", recording: "Hört zu", working: "Schreibt mit …", loading: "Lädt …" };

async function micInfo(force = false) {
  if (mic.info && !force) return mic.info;
  try {
    mic.info = await api("/api/speech");
  } catch {
    mic.info = { ok: false, local: false, enabled: false, note: "", models: [], inputs: [], missing: [] };
  }
  updateMic();
  return mic.info;
}

function micReady() {
  return !!(mic.info && mic.info.local && mic.info.enabled);
}

function paintLevel() {
  const on = mic.state === "recording" ? Math.min(4, Math.round(Math.sqrt(Math.max(0, mic.level)) * 4.4)) : 0;
  $$("#micLevel i").forEach((bar, i) => bar.classList.toggle("on", i < on));
}

function updateMic() {
  const chip = $("#micBtn");
  chip.hidden = !micReady();
  chip.classList.toggle("on", mic.state === "recording");
  chip.classList.toggle("busy", mic.state === "working");
  const secs = mic.seconds >= 60
    ? `${Math.floor(mic.seconds / 60)}:${String(Math.floor(mic.seconds % 60)).padStart(2, "0")}`
    : `${Math.max(0, Math.floor(mic.seconds))} s`;
  $("#micLabel").textContent = mic.state === "recording" ? secs : MIC_LABEL[mic.state] || "Sprechen";
  chip.title = mic.state === "recording"
    ? "Fertig – Text in die Eingabe (Strg D), Esc verwirft"
    : "Diktieren – sprechen statt tippen (Strg D)";
  chip.setAttribute("aria-pressed", mic.state === "recording" ? "true" : "false");
  paintLevel();
}

function toggleMic() {
  if (!micReady()) return;
  if (mic.state === "recording") return send({ type: "speech_stop" });
  if (mic.state !== "idle") return;
  if (!mic.info.ok) {
    toast(mic.info.note || "Das Diktat ist noch nicht eingerichtet.", { error: true, ms: 5000 });
    openSettings();
    return;
  }
  mic.state = "recording"; // sofort sichtbar – der Server bestätigt gleich darauf
  mic.seconds = 0;
  mic.level = 0;
  updateMic();
  send({ type: "speech_start" });
}

function cancelMic() {
  if (mic.state !== "recording") return false;
  mic.state = "idle";
  updateMic();
  send({ type: "speech_cancel" });
  return true;
}

function spokenIntoInput(text) {
  if (!text) return toast("Da war nichts zu verstehen.");
  const before = input.value.trim();
  insertIntoInput(before ? `${before} ${text}` : text);
}

function onSpeech(ev) {
  if (ev.state === "recording") {
    mic.state = "recording";
    if (typeof ev.level === "number") mic.level = ev.level;
    if (typeof ev.seconds === "number") mic.seconds = ev.seconds;
  } else if (ev.state === "working") {
    mic.state = "working";
    mic.level = 0;
  } else if (ev.state === "done") {
    mic.state = "idle";
    spokenIntoInput(String(ev.text || "").trim());
  } else if (ev.state === "loading") {
    speechProgress(ev);
  } else if (ev.state === "ready") {
    mic.info = ev.status ? { ...mic.info, ...ev.status } : null;
    micInfo(!ev.status);
    renderSpeech();
    toast("Erkennungsmodell ist da – das Diktat kann losgehen.");
  } else {
    mic.state = "idle";
    if (ev.message) toast(ev.message, { error: ev.state === "error", ms: ev.state === "error" ? 5000 : 2500 });
    if (ev.status) mic.info = { ...mic.info, ...ev.status };
    if (ev.state === "error" && !$("#settingsSheet").hidden) renderSpeech();
  }
  updateMic();
}

$("#micBtn").addEventListener("click", toggleMic);

/* ---------------------------------------------------------------- Einstellungen: Modell, Mikrofon, Anleitung */

function renderSpeech() {
  const info = mic.info;
  const note = $("#speechStatus");
  const setup = $("#speechSetup");
  const form = $("#settingsForm");
  if (!info) return;
  const wanted = form.elements.speech_model.value || info.model;
  const model = (info.models || []).find((m) => m.name === wanted);
  const select = $("#speechModel");
  select.innerHTML = (info.models || []).map((m) =>
    `<option value="${esc(m.name)}">${esc(m.label)} · ${m.mb >= 1024 ? `${(m.mb / 1024).toFixed(1)} GB` : `${m.mb} MB`}`
    + `${m.ready ? " · geladen" : ""} – ${esc(m.hint)}</option>`).join("");
  select.value = wanted;
  const picked = $("#speechInput");
  const mics = info.inputs || [];
  picked.innerHTML = `<option value="">Wie in Windows eingestellt${mics.find((m) => m.default) ? ` · ${esc(mics.find((m) => m.default).name)}` : ""}</option>`
    + mics.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join("");
  picked.value = String(state.config.speech_input || "");
  note.className = "row-note";
  if ((info.missing || []).length) {
    note.textContent = `Es fehlt: ${info.missing.join(" und ")}.`;
  } else if (!mics.length) {
    note.textContent = "Kein Mikrofon gefunden – ist eines angeschlossen und in Windows freigegeben?";
  } else if (model && !model.ready) {
    note.innerHTML = `<span>${esc(model.label)} ist noch nicht da – einmalig ${model.mb >= 1024 ? `${(model.mb / 1024).toFixed(1)} GB` : `${model.mb} MB`} laden, danach läuft alles ohne Netz.</span>`
      + ` <button type="button" class="btn small" id="speechFetch">Modell laden</button>`;
  } else {
    note.className = "row-note found";
    note.textContent = info.note || "Bereit.";
  }
  const steps = (info.missing || []).length ? [{
    titel: "Pakete nachrüsten",
    text: `Das Diktat braucht **faster-whisper** (erkennt die Sprache) und **sounddevice** (nimmt auf). `
      + `Beides sind Python-Pakete, die auf diesem Rechner bleiben.`,
    command: info.install || `pip install ${(info.missing || []).join(" ")}`,
  }, {
    titel: "Coder neu starten",
    text: "Danach findet Coder die Pakete und der Mikrofon-Knopf erscheint neben der Eingabe.",
  }] : [];
  renderSteps(setup, steps);
}

function speechProgress(ev) {
  const note = $("#speechStatus");
  const share = ev.total ? Math.round((100 * ev.done) / ev.total) : 0;
  note.className = "row-note";
  note.textContent = `${ev.model} wird geladen … ${share} %`;
}

$("#speechStatus").addEventListener("click", (e) => {
  if (!e.target.closest("#speechFetch")) return;
  const name = $("#settingsForm").elements.speech_model.value;
  send({ type: "speech_model", model: name });
  speechProgress({ model: name, done: 0, total: 1 });
});

$("#speechSetup").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    btn.textContent = "Kopiert";
    setTimeout(() => (btn.textContent = "Kopieren"), 1400);
  } catch {
    toast("Kopieren ging nicht – markiere den Text und nimm Strg+C.", { error: true });
  }
});

/* ================================================================ Cowork: mehrere Aufträge gleichzeitig */

// Das Brett liegt im Server (core/cowork.py): Die Aufträge laufen weiter, auch wenn dieses Fenster neu lädt.
// Hier steht nur, wie sie aussehen. Jeder Auftrag hat seinen eigenen Chat – „Im Chat öffnen“ holt ihn her.
const cowork = { tasks: [], parallel: 2, running: 0, queued: 0, open: new Set(), tick: 0 };
const CW_STATUS = { queued: "wartet", running: "läuft", done: "fertig", failed: "gescheitert", stopped: "gestoppt" };
const CW_MODES = { plan: "Nur lesen", edit: "Dateien ändern", all: "Alles" };
const cwDone = (t) => t.status !== "queued" && t.status !== "running";

// Die Sekunden laufen zwischen zwei Meldungen weiter – sonst stünde die Uhr still, während der Agent denkt.
function cwSeconds(task) {
  const extra = task.status === "running" && task._at ? (Date.now() - task._at) / 1000 : 0;
  return duration(Math.round((task.seconds || 0) + extra));
}

function cwMeta(task) {
  const parts = [CW_MODES[task.mode] || task.mode];
  if (task.agent) parts.push(`@${task.agent}`);
  if (task.steps) parts.push(`${task.steps} ${task.steps === 1 ? "Schritt" : "Schritte"}`);
  if (task.status !== "queued") parts.push(cwSeconds(task));
  if (task.files.length) parts.push(`${task.files.length} ${task.files.length === 1 ? "Datei" : "Dateien"}`);
  return parts.join(" · ");
}

function cwLine(task) {
  if (task.status === "queued") return "Wartet auf einen freien Platz.";
  if (task.status === "running") return task.activity || "Denkt nach …";
  if (task.status === "failed") return task.error || "Gescheitert.";
  if (task.status === "stopped") return "Gestoppt.";
  return task.answer ? task.answer.trim().split("\n")[0].slice(0, 160) : "Fertig.";
}

function taskCard(task) {
  const open = cowork.open.has(task.id);
  const files = task.files.map((f) => `<span class="ct-file" title="${esc(f.path)}">${esc(basename(f.path))}${
    f.added || f.removed ? `<small>+${f.added || 0}/−${f.removed || 0}</small>` : ""}</span>`).join("");
  const log = task.log.map((s) => `<li class="${s.ok === false ? "bad" : ""}">${esc(s.summary || s.name || "")}</li>`).join("");
  return `<article class="ct" data-task="${esc(task.id)}" data-status="${esc(task.status)}">
    <button type="button" class="ct-head" data-cw="toggle" aria-expanded="${open}">
      <span class="ct-mark">${task.status === "running" ? `<span class="spinner"></span>` : `<span class="ct-dot"></span>`}</span>
      <span class="ct-text">
        <span class="ct-title">${esc(task.title)}</span>
        <span class="ct-now">${esc(cwLine(task))}</span>
      </span>
      <span class="ct-meta">${esc(cwMeta(task))}</span>
      <span class="ct-chev">${ICONS.chevron}</span>
    </button>
    <div class="ct-detail"${open ? "" : " hidden"}>
      ${task.note ? `<p class="ct-note">${esc(task.note)}</p>` : ""}
      ${log ? `<ol class="ct-log">${log}</ol>` : ""}
      ${task.answer ? `<div class="md ct-answer">${markdown(task.answer)}</div>` : ""}
      ${files ? `<div class="ct-files">${files}${task.undone ? `<span class="ct-file undone">zurückgenommen</span>` : ""}</div>` : ""}
      <div class="ct-actions">
        ${task.session_id ? `<button type="button" class="btn ghost small" data-cw="open">Im Chat öffnen</button>` : ""}
        ${cwDone(task) ? `<button type="button" class="btn ghost small" data-cw="retry">Noch einmal</button>`
          : `<button type="button" class="btn ghost small" data-cw="stop">Stoppen</button>`}
        ${cwDone(task) && task.files.length && !task.undone
          ? `<button type="button" class="btn ghost small" data-cw="undo">Rückgängig</button>` : ""}
        <span class="spacer"></span>
        ${cwDone(task) ? `<button type="button" class="btn ghost small" data-cw="remove">Vom Brett nehmen</button>` : ""}
      </div>
    </div>
  </article>`;
}

function renderCowork() {
  const list = $("#coworkList");
  if (!list) return;
  list.innerHTML = cowork.tasks.length
    ? cowork.tasks.slice().reverse().map(taskCard).join("")
    : `<p class="cowork-empty">Noch nichts auf dem Brett. Schreib oben einen Auftrag – er läuft, während du hier weiterarbeitest.</p>`;
  updateCowork();
}

function paintTask(task) {
  const el = $(`[data-task="${task.id}"]`, $("#coworkList"));
  if (!el) return renderCowork();
  el.outerHTML = taskCard(task);
  updateCowork();
}

// Die Zeile über der Liste und das Abzeichen in der Seitenleiste.
function updateCowork() {
  // „Erledigte räumen“ nur, wenn es etwas zu räumen gibt – laufende und wartende bleiben ohnehin stehen.
  const clear = $("#coworkClear");
  if (clear) clear.disabled = !cowork.tasks.some(cwDone);
  const count = $("#coworkCount");
  if (count) {
    const teile = [];
    if (cowork.running) teile.push(`${cowork.running} ${cowork.running === 1 ? "läuft" : "laufen"}`);
    if (cowork.queued) teile.push(`${cowork.queued} wartet`);
    count.textContent = teile.join(" · ") || `gleichzeitig: ${cowork.parallel}`;
  }
  const badge = $("#coworkBadge");
  if (badge) {
    const offen = cowork.running + cowork.queued;
    badge.textContent = offen ? String(offen) : "";
    badge.hidden = !offen;
    $("#coworkBtn").classList.toggle("on", offen > 0);
  }
  cwTicker();
}

// Solange etwas läuft, zählt die Zeit auf den Karten sichtbar weiter.
function cwTicker() {
  const laeuft = cowork.tasks.some((t) => t.status === "running") && !$("#coworkSheet").hidden;
  if (laeuft && !cowork.tick) {
    cowork.tick = setInterval(() => {
      for (const task of cowork.tasks) {
        if (task.status !== "running") continue;
        const meta = $(`[data-task="${task.id}"] .ct-meta`, $("#coworkList"));
        if (meta) meta.textContent = cwMeta(task);
      }
    }, 1000);
  } else if (!laeuft && cowork.tick) {
    clearInterval(cowork.tick);
    cowork.tick = 0;
  }
}

async function openCowork() {
  if (!serverHas("1.9.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  openSheet("#coworkSheet");
  $("#coworkRoot").textContent = basename(currentWorkspace());
  $("#coworkRoot").title = currentWorkspace();
  send({ type: "cowork_board" });
  renderCowork();
  $("#coworkText").focus();
  try {
    const ext = await loadExtensions();
    const select = $("#coworkAgent");
    const wanted = select.value;
    select.innerHTML = `<option value="">Coder selbst</option>`
      + (ext.agents || []).map((a) => `<option value="${esc(a.name)}">@${esc(a.name)}</option>`).join("");
    select.value = wanted;
  } catch {
    /* ohne Agents geht es auch */
  }
}

function coworkAction(what, id) {
  const task = cowork.tasks.find((t) => t.id === id);
  if (!task) return;
  if (what === "toggle") {
    if (cowork.open.has(id)) cowork.open.delete(id);
    else cowork.open.add(id);
    paintTask(task);
  } else if (what === "open") {
    if (state.busy) return toast("Der Agent arbeitet noch in diesem Fenster. Erst stoppen.", { error: true });
    closeSheets();
    send({ type: "open", session_id: task.session_id });
  } else if (what === "stop") send({ type: "cowork_stop", id });
  else if (what === "retry") send({ type: "cowork_retry", id });
  else if (what === "undo") send({ type: "cowork_undo", id });
  else if (what === "remove") send({ type: "cowork_remove", id });
}

$("#coworkForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#coworkText").value.trim();
  if (!text) return;
  send({ type: "cowork_add", text, mode: $("#coworkMode").value, agent: $("#coworkAgent").value,
         workspace: currentWorkspace() });
  $("#coworkText").value = "";
  $("#coworkText").focus();
});
// Strg+Enter schickt den Auftrag ab – im Textfeld macht Enter eine neue Zeile.
$("#coworkText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    $("#coworkForm").requestSubmit();
  }
});
$("#coworkList").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-cw]");
  if (!btn) return;
  coworkAction(btn.dataset.cw, btn.closest("[data-task]")?.dataset.task);
});
$("#coworkClear").addEventListener("click", () => send({ type: "cowork_clear" }));
$("#coworkBtn").addEventListener("click", openCowork);

/* ================================================================ Bereiche: Code, Chat, Editor */

// Drei Bereiche in einem Fenster. Code ist der Agent im Projekt, Chat ein eigener Ort zum Reden und Recherchieren
// – mit eigenen Chats, ohne Projekt und Dateien –, Editor die Dateien selbst. Code und Chat teilen sich die
// Verbindung: Beim Wechsel öffnet das Fenster den zuletzt benutzten Chat dieses Bereichs. Ein laufender Auftrag
// arbeitet dabei weiter (er gehört dem Chat, nicht dem Fenster) und steht in der Liste als „arbeitet“.
const TABS = ["code", "talk", "ide"];
const TAB_NAMES = { code: "Code", talk: "Chat", ide: "Editor" };
const kindOf = (s) => (s?.kind === "talk" ? "talk" : "code");

function switchTab(tab, { open = true } = {}) {
  if (!TABS.includes(tab)) tab = "code";
  if (open && tab === "code" && state.tab === "talk" && !leavingIncognito()) return Promise.resolve();
  if (tab !== "talk" && !roleAtLeast("read")) tab = "talk"; // wer nur chatten darf, bleibt im Chat
  if (tab === "talk" && !serverHas("1.11.0")) {
    toast("Der Chat-Tab braucht einen Neustart von Coder.", { error: true });
    tab = "code";
  }
  if (tab === "ide" && state.tab !== "ide") store.set("coder.lastTab", state.tab); // Strg+E führt dorthin zurück
  state.tab = tab;
  $("#app").dataset.tab = tab;
  $$("#appTabs [data-tab]").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  store.set("coder.tab", tab);
  $("#ide").hidden = tab !== "ide";
  if (tab === "ide") {
    hideSuggest?.();
    return enterIde();
  }
  // Der passende Chat: der zuletzt offene dieses Bereichs – oder ein neuer.
  if (open && state.ws?.readyState === WebSocket.OPEN && kindOf(state.session) !== tab) {
    const sid = store.get(`coder.session.${tab}`) || (tab === "code" ? store.get("coder.session") : "");
    send(sid ? { type: "open", session_id: sid, kind: tab } : { type: "new", kind: tab });
  }
  renderSessions();
  updatePlaceholder();
  updateModelPill();
  updateStart();
  updateTitle();
  requestAnimationFrame(() => setMode(state.config?.permission_mode || "ask", false));
  if (!matchMedia("(max-width: 760px)").matches) input.focus({ preventScroll: true });
  return Promise.resolve();
}

$("#appTabs").addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tab]")?.dataset.tab;
  if (tab && tab !== state.tab) switchTab(tab);
});
$("#appTabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const tabs = $$("#appTabs [data-tab]").filter((b) => !b.hidden);
  const at = tabs.indexOf(document.activeElement);
  const next = tabs[(at + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
  next?.focus();
  next?.click();
});

/* ================================================================ Konten und Freigabe */

// Wer vor diesem Fenster sitzt: der Besitzer am Rechner (alles erlaubt) oder ein angemeldetes Konto mit Rolle.
// Ältere Server kennen keine Konten – dann gilt, was bisher galt: alles.
const ROLE_ORDER = ["chat", "read", "code", "admin"];

function roleAtLeast(role) {
  const have = state.me?.role || "admin";
  return ROLE_ORDER.indexOf(have) >= ROLE_ORDER.indexOf(role);
}

function applyRole() {
  const me = state.me;
  const root = document.documentElement;
  if (me?.role) root.dataset.role = me.role;
  else delete root.dataset.role;
  // Nur die Modi, die das Konto hergibt.
  const modes = me?.modes?.length ? me.modes : MODES;
  $$("#modeSeg button[data-mode]").forEach((b) => { b.hidden = !modes.includes(b.dataset.mode); });
  $$("#appTabs [data-tab]").forEach((b) => { b.hidden = b.dataset.tab !== "talk" && !roleAtLeast("read"); });
  const card = $("#meCard");
  card.hidden = !me || me.local;
  if (me && !me.local) {
    $("#meAvatar").textContent = (me.name || "?").slice(0, 1).toUpperCase();
    $("#meName").textContent = me.name;
    $("#meRole").textContent = me.self ? "Dein Konto · unterwegs" : me.role_label;
  }
}

$("#logoutBtn").addEventListener("click", async () => {
  if (anyDirty() && !confirm("Im Editor ist noch etwas nicht gespeichert. Trotzdem abmelden?")) return;
  try { await api("/api/logout", { method: "POST" }); } catch { /* ohnehin weg */ }
  location.href = "/login";
});

const shareUI = { data: null, link: "", online: [] };

// Das Abzeichen am Freigabe-Knopf zählt, wer von außen gerade da ist – live, ohne nachzufragen.
function renderPresence() {
  const guests = (shareUI.online || []).filter((o) => !o.local);
  const names = [...new Set(guests.map((o) => o.name))];
  const badge = $("#shareBadge");
  badge.hidden = !names.length;
  badge.textContent = names.length;
  $("#shareBtn").title = names.length ? `Freigabe · gerade da: ${names.join(", ")}` : "Freigabe: andere an Coder lassen";
  if (shareUI.data) {
    shareUI.data.online = shareUI.online;
    if (!$("#shareSheet").hidden) renderShare();
  }
}

async function openShare() {
  if (!roleAtLeast("admin")) return;
  if (!serverHas("1.11.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  openSheet("#shareSheet");
  $("#sharePublicUrl").value = state.config?.public_url || "";
  $("#shareLink").hidden = !shareUI.link;
  await loadShare();
}

async function loadShare() {
  try {
    shareUI.data = await api("/api/users");
  } catch (e) {
    return toast(e.message, { error: true });
  }
  renderShare();
}

function inviteUrl(path) {
  const base = (state.config?.public_url || shareUI.data?.url || "").replace(/\/+$/, "");
  return base ? `${base}${path}` : "";
}

function renderShare() {
  const d = shareUI.data;
  if (!d) return;
  const port = location.port || (location.protocol === "https:" ? "443" : "80");
  $("#sharePublicUrl").placeholder = d.url || "Noch keine gesehen – etwa https://…devtunnels.ms";
  const seen = d.tunnel ? `Zuletzt kam jemand über <code>${esc(d.tunnel)}</code> herein.` : "";
  $("#shareSteps").innerHTML = [
    `In VS Code das Panel <b>Ports</b> öffnen (unten, neben Terminal) und <b>Port weiterleiten</b> wählen: <code>${esc(port)}</code>. Coder selbst bleibt dabei auf diesem Rechner – der Tunnel kommt von innen.`,
    `Rechtsklick auf die Zeile → <b>Port-Sichtbarkeit</b> → <b>Öffentlich</b>. Bei „Privat“ kommt nur dein eigenes GitHub-Konto durch. Anmelden muss sich trotzdem jeder – bei Coder.`,
    `Die <b>weitergeleitete Adresse</b> kopieren und unten eintragen – oder sie einmal selbst öffnen, dann merkt Coder sie sich. ${seen}`,
    `Jemanden einladen und den Link schicken. Wer ihn öffnet, legt sein eigenes Passwort fest. Die Weiterleitung endet, wenn VS Code zugeht.`,
  ].map((s) => `<li>${s}</li>`).join("");
  const role = $("#inviteRole");
  if (!role.options.length) {
    role.innerHTML = d.roles.map((r) => `<option value="${r.id}">${esc(r.label)}</option>`).join("")
      + `<option value="self">Ich selbst, unterwegs</option>`;
    role.value = "chat";
  }
  const hint = d.roles.find((r) => r.id === role.value)?.hint
    || "Dein eigenes Konto für Handy oder Laptop: dieselben Chats, dasselbe Gedächtnis, alle Rechte.";
  $("#inviteRoleHint").textContent = hint;
  $("#shareUsers").innerHTML = d.users.length ? d.users.map((u) => `
    <div class="row share-user" data-user="${esc(u.name)}">
      <span class="share-avatar" aria-hidden="true">${esc(u.name.slice(0, 1).toUpperCase())}</span>
      <span class="share-who"><b>${esc(u.name)}</b>
        <small>${u.pending ? "Eingeladen – noch kein Passwort" : u.last_seen ? `Zuletzt da ${esc(whenLabel(u.last_seen))}` : "Noch nie angemeldet"}${u.self ? " · du selbst" : ""}</small></span>
      <select data-role-of="${esc(u.name)}" aria-label="Rolle von ${esc(u.name)}" ${u.self ? "disabled" : ""}>
        ${d.roles.map((r) => `<option value="${r.id}"${r.id === u.role ? " selected" : ""}>${esc(r.label)}</option>`).join("")}
      </select>
      <button type="button" class="btn ghost small" data-reinvite="${esc(u.name)}" title="Neuer Link – das alte Passwort gilt dann nicht mehr">Neuer Link</button>
      <button type="button" class="icon-btn small del" data-remove="${esc(u.name)}" aria-label="${esc(u.name)} entfernen" title="Konto löschen">${ICONS.trash}</button>
    </div>`).join("") : `<p class="row-note">Noch niemand eingeladen.</p>`;
  // Eine Zeile je Person – wer zwei Fenster offen hat, steht nicht doppelt da.
  const people = new Map();
  for (const o of d.online) {
    const key = o.local ? "\u0000local" : o.name.toLowerCase();
    const p = people.get(key) || { ...o, windows: 0, kinds: new Set(), busy: false, since: o.since };
    p.windows += 1;
    p.kinds.add(o.kind === "talk" ? "talk" : "code");
    p.busy = p.busy || o.busy;
    p.since = Math.min(p.since, o.since);
    people.set(key, p);
  }
  $("#shareOnline").innerHTML = [...people.values()].map((o) => `
    <div class="row share-user">
      <span class="share-avatar${o.local ? " me" : ""}" aria-hidden="true">${esc((o.name || "D").slice(0, 1).toUpperCase())}</span>
      <span class="share-who"><b>${o.local ? "Du, an diesem Rechner" : esc(o.name)}</b>
        <small>${o.windows > 1 ? `${o.windows} Fenster · ` : ""}${esc([...o.kinds].map((k) => TAB_NAMES[k]).join(" und "))} · seit ${esc(timeFmt.format(new Date(o.since * 1000)))}${o.busy ? " · arbeitet" : ""}</small></span>
    </div>`).join("") || `<p class="row-note">Gerade ist niemand verbunden.</p>`;
}

function showInviteLink(name, path) {
  const url = inviteUrl(path);
  shareUI.link = url || path;
  const box = $("#shareLink");
  box.hidden = false;
  box.innerHTML = `
    <p><b>Link für ${esc(name)}</b> – gilt sieben Tage und nur einmal. Schick ihn auf einem Weg, dem du traust.</p>
    <div class="setup-cmd"><pre>${esc(shareUI.link)}</pre>
      <button type="button" class="btn ghost setup-copy" data-copy="${esc(shareUI.link)}">Kopieren</button></div>
    ${url ? "" : `<p class="row-note">Die Adresse von außen fehlt noch – oben eintragen, dann steht hier der ganze Link. Bis dahin: die weitergeleitete Adresse aus VS Code und diesen Pfad dahinter.</p>`}`;
}

$("#shareBtn").addEventListener("click", openShare);
$("#incognitoBtn").addEventListener("click", () => {
  if (!serverHas("1.11.0")) return toast("Dafür muss Coder einmal neu starten.", { error: true });
  const on = !state.session?.incognito;
  if (!on && !leavingIncognito()) return;
  send({ type: "new", kind: "talk", incognito: on });
  if (on) toast("Inkognito: nichts wird gesichert, kein Gedächtnis.");
  input.focus();
});
$("#inviteRole").addEventListener("change", renderShare);
$("#shareInvite").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#inviteName").value.trim();
  const pick = $("#inviteRole").value;
  if (!name) return $("#inviteName").focus();
  try {
    const res = await api("/api/users", { method: "POST", body: { name, role: pick === "self" ? "admin" : pick, self: pick === "self" } });
    $("#inviteName").value = "";
    showInviteLink(res.user.name, res.path);
    await loadShare();
  } catch (err) {
    toast(err.message, { error: true, ms: 5000 });
  }
});
$("#shareUsers").addEventListener("change", async (e) => {
  const sel = e.target.closest("[data-role-of]");
  if (!sel) return;
  try {
    await api(`/api/users/${encodeURIComponent(sel.dataset.roleOf)}`, { method: "PATCH", body: { role: sel.value } });
    toast(`${sel.dataset.roleOf}: ${sel.selectedOptions[0].textContent}`);
  } catch (err) {
    toast(err.message, { error: true });
  }
  loadShare();
});
$("#shareUsers").addEventListener("click", async (e) => {
  const again = e.target.closest("[data-reinvite]")?.dataset.reinvite;
  const gone = e.target.closest("[data-remove]")?.dataset.remove;
  try {
    if (again) {
      const res = await api(`/api/users/${encodeURIComponent(again)}/invite`, { method: "POST" });
      showInviteLink(again, res.path);
    } else if (gone) {
      if (!confirm(`Das Konto „${gone}“ löschen? Seine Chats bleiben auf diesem Rechner liegen.`)) return;
      await api(`/api/users/${encodeURIComponent(gone)}`, { method: "DELETE" });
      toast(`${gone} kommt nicht mehr herein`);
    } else return;
  } catch (err) {
    return toast(err.message, { error: true });
  }
  loadShare();
});
$("#sharePublicUrl").addEventListener("change", async (e) => {
  const value = e.target.value.trim().replace(/\/+$/, "");
  if (value && !/^https?:\/\/[^/\s]+$/i.test(value)) return toast("Nur die Adresse, etwa https://abc123-8765.euw.devtunnels.ms", { error: true, ms: 5000 });
  try {
    state.config = await api("/api/config", { method: "POST", body: { public_url: value } });
    toast(value ? "Adresse gemerkt" : "Adresse entfernt – Coder nimmt die zuletzt gesehene");
  } catch (err) {
    toast(err.message, { error: true });
  }
});
$("#shareLink").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-copy]");
  if (btn) copyText(btn.dataset.copy).then(() => toast("Link kopiert"));
});

/* ================================================================ Persönlich: Antwortstil und eigene Anweisungen */

// Wie in core/personal.py: Normal ändert nichts am Prompt, die anderen fügen ein paar Zeilen an.
const STYLES = ["normal", "knapp", "ausfuehrlich", "lernen", "formell"];
const STYLE_NAMES = { normal: "Normal", knapp: "Knapp", ausfuehrlich: "Ausführlich", lernen: "Erklärend", formell: "Förmlich" };
const STYLE_HINT = {
  normal: "Wie Coder von sich aus antwortet", knapp: "Ergebnis zuerst, ohne Vorrede",
  ausfuehrlich: "Mit Hintergrund und Alternativen", lernen: "Erklärt das Warum – zum Dazulernen",
  formell: "Sachlich, mit „Sie“",
};
const STYLE_WORDS = {
  kurz: "knapp", concise: "knapp", "ausführlich": "ausfuehrlich", lang: "ausfuehrlich", detailliert: "ausfuehrlich",
  "erklärend": "lernen", erklaerend: "lernen", lernen: "lernen", "förmlich": "formell", foermlich: "formell",
  formal: "formell", sie: "formell", standard: "normal",
};

function parseStyle(text) {
  const word = String(text || "").trim().toLowerCase();
  return STYLES.includes(word) ? word : STYLE_WORDS[word] || null;
}

const currentStyle = () => (STYLES.includes(state.config?.style) ? state.config.style : "normal");

function setStyle(style, { loud = false } = {}) {
  if (!style) return toast(`Stile: ${STYLES.map((s) => STYLE_NAMES[s].toLowerCase()).join(", ")}`);
  if (!serverHas("1.12.0")) return toast("Der Antwortstil braucht einen Neustart von Coder.", { error: true });
  if (!state.config) return;
  const before = currentStyle();
  state.config.style = style;
  updateStyleChip();
  if (loud || before !== style) toast(`Antwortstil: ${STYLE_NAMES[style]}`);
  if (before === style) return;
  api("/api/config", { method: "POST", body: { style } })
    .then((cfg) => { state.config = { ...state.config, ...cfg }; updateStyleChip(); })
    .catch((e) => toast(e.message, { error: true }));
}

// Der Stil steht nur dann neben der Eingabe, wenn er vom Normalen abweicht – ein Klick führt zu den Einstellungen.
function updateStyleChip() {
  const chip = $("#styleChip");
  if (!chip) return;
  const style = currentStyle();
  chip.hidden = !serverHas("1.12.0") || style === "normal";
  $("#styleLabel").textContent = STYLE_NAMES[style];
  chip.title = `Antwortstil: ${STYLE_NAMES[style]} – ${STYLE_HINT[style]}. Klicken zum Ändern`;
}
$("#styleChip")?.addEventListener("click", () => openSettings("set-personal"));

/* ================================================================ Prompts: eigene /Befehle */

// Ein Prompt ist ein fertiger Auftrag mit Namen: /name setzt den Text ein, was danach steht, ersetzt $ARGUMENTS.
// Die Dateien liegen wie bei Claude Code als Markdown in ~/.coder/commands oder im Projekt (core/commands.py).
const PROMPT_TABS = { code: "Code", talk: "Chat", all: "Beide" };
const PROMPT_SOURCES = ["global", "project", "claude-project", "claude", "builtin"];
const promptsUI = { filter: "", tab: "all", dirty: false };
const canEditPrompts = () => roleAtLeast("admin") && serverHas("1.12.0");

async function openPrompts({ preset = null } = {}) {
  openSheet("#promptsSheet");
  $("#promptNew").hidden = !canEditPrompts();
  $("#promptsBody").innerHTML = `<div class="model-empty"><span class="spinner"></span></div>`;
  try {
    await loadExtensions(true);
  } catch (e) {
    $("#promptsBody").innerHTML = `<div class="model-empty">${esc(e.message)}</div>`;
    return;
  }
  if (preset && canEditPrompts()) promptEditor(null, preset);
  else renderPrompts();
}

function renderPrompts({ keepFocus = false } = {}) {
  promptsUI.dirty = false;
  $("#promptNew").hidden = !canEditPrompts();
  const body = $("#promptsBody");
  const all = state.ext?.commands || [];
  const q = promptsUI.filter.trim().toLowerCase();
  const fits = (c) => (promptsUI.tab === "all" || offeredIn(c, promptsUI.tab))
    && (!q || c.name.includes(q) || (c.description || "").toLowerCase().includes(q));
  const shown = all.filter(fits);
  const own = all.filter((c) => c.editable);
  const groups = PROMPT_SOURCES.map((src) => [src, shown.filter((c) => c.source === src)]).filter(([, list]) => list.length);
  const edit = canEditPrompts();
  const row = (c) => `
    <div class="plist-row">
      <div class="plist-main">
        <div class="plist-name">/${esc(c.name)}${c.hint ? ` <span class="suggest-hint">${esc(c.hint)}</span>` : ""}
          <span class="tab-badge tab-${esc(c.tab)}">${PROMPT_TABS[c.tab] || "Code"}</span></div>
        <div class="plist-desc" title="${esc(c.description)}">${esc(c.description)}</div>
      </div>
      <div class="plist-actions">
        <button class="btn ghost" type="button" data-prompt-use="${esc(c.name)}">Einsetzen</button>
        ${edit ? `<button class="btn" type="button" data-prompt-edit="${esc(c.name)}">${c.editable ? "Bearbeiten" : "Anpassen"}</button>` : ""}
      </div>
    </div>`;
  const intro = !own.length && edit && !q ? `
    <div class="prompt-empty">
      <strong>Noch keine eigenen Prompts</strong>
      <p>Leg Aufträge an, die du oft brauchst – etwa <code>/wochenbericht</code>, <code>/outfit</code> oder <code>/pr-text</code>.
      Auch jede Nachricht im Verlauf lässt sich mit „Als Prompt“ übernehmen.</p>
      <button class="btn primary" type="button" data-prompt-new>Ersten Prompt anlegen</button>
    </div>` : "";
  body.innerHTML = `
    <div class="prompt-tools">
      <label class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="promptFilter" type="search" placeholder="Prompts durchsuchen" autocomplete="off" spellcheck="false" aria-label="Prompts durchsuchen">
      </label>
      <div class="view-switch" role="tablist" aria-label="Bereich">
        ${["all", "code", "talk"].map((t) => `<button type="button" role="tab" data-prompt-tab="${t}" aria-selected="${promptsUI.tab === t}">${{ all: "Alle", code: "Code", talk: "Chat" }[t]}</button>`).join("")}
      </div>
    </div>
    ${intro}
    ${groups.map(([src, list]) => `
      <section class="agents-group">
        <span class="eyebrow">${SOURCE_LABEL[src] || src}</span>
        <div class="list">${list.map(row).join("")}</div>
      </section>`).join("") || (q || promptsUI.tab !== "all" ? `<div class="model-empty">Kein Prompt passt dazu.</div>` : "")}
    <p class="agents-hint">Tippe <code>/</code> in der Eingabe, um einen Prompt zu wählen. Was hinter dem Namen steht, setzt Coder für
    <code>$ARGUMENTS</code> ein. Eigene Prompts liegen als Markdown in <code>~/.coder/commands</code> oder im Projekt unter
    <code>.coder/commands</code> – Claude Code liest dieselben Dateien.</p>`;
  const filter = $("#promptFilter");
  filter.value = promptsUI.filter;
  if (keepFocus) {
    filter.focus();
    filter.setSelectionRange(filter.value.length, filter.value.length);
  }
}

function promptEditor(cmd, preset = {}) {
  const isNew = !cmd;
  const c = cmd || { name: "", description: "", hint: "", template: "", tab: state.tab === "talk" ? "talk" : "all", source: "global", editable: true };
  const scope = c.editable ? c.source : "global";
  const tab = isNew ? preset.tab || c.tab : c.tab || "code";
  $("#promptNew").hidden = true;
  $("#promptsBody").innerHTML = `
    <form class="settings agent-editor prompt-editor" id="promptForm" autocomplete="off">
      <span class="eyebrow">${isNew ? "Neuer Prompt" : c.editable ? "Prompt bearbeiten" : `Anpassen – eigene Fassung von /${esc(c.name)}`}</span>
      <div class="list">
        <label class="row col"><span>Name<small>So rufst du ihn auf: Kleinbuchstaben, Ziffern, - und _</small></span>
          <span class="name-field"><span>/</span><input name="name" spellcheck="false" maxlength="40" placeholder="wochenbericht" autocapitalize="off"></span>
        </label>
        <label class="row col"><span>Wofür<small>Eine Zeile – sie steht in der Liste, wenn du / tippst</small></span>
          <input name="description" maxlength="200" placeholder="Wochenbericht aus den Änderungen der letzten Tage"></label>
        <label class="row col"><span>Was nach dem Namen kommt<small>Nur ein Hinweis beim Tippen, etwa &lt;Thema&gt; oder [Datei]</small></span>
          <input name="hint" maxlength="80" placeholder="[Zeitraum]" spellcheck="false"></label>
      </div>
      <span class="eyebrow">Wo anbieten</span>
      <div class="choice-grid tab-grid">
        ${[["code", "Code", "Agent im Projekt und Terminal", ICONS.command], ["talk", "Chat", "Reden und recherchieren", ICONS.chat],
          ["all", "Beide", "Überall, wo du / tippst", ICONS.plus]].map(([value, label, sub, icon]) => `
        <label class="choice"><input type="radio" name="tab" value="${value}"${tab === value ? " checked" : ""}>
          <span class="choice-card">${icon}<span><strong>${label}</strong><small>${sub}</small></span></span></label>`).join("")}
      </div>
      <span class="eyebrow">Text</span>
      <textarea class="prompt" name="template" rows="9" spellcheck="true"
        placeholder="Schreib den Auftrag so, wie du ihn tippen würdest. $ARGUMENTS steht für das, was du hinter /name schreibst."></textarea>
      <div class="prompt-help">
        <span><code>$ARGUMENTS</code> wird zu allem hinter dem Namen, <code>$1</code>, <code>$2</code> zu einzelnen Wörtern. Ohne Platzhalter kommt es ans Ende.</span>
        <button type="button" class="btn small" id="promptArgs">$ARGUMENTS einsetzen</button>
      </div>
      <span class="eyebrow">Probe</span>
      <div class="prompt-probe">
        <label class="name-field"><span id="probeName">/name</span><input id="promptProbe" spellcheck="false" placeholder="Beispiel für das, was dahinter steht" aria-label="Beispiel"></label>
        <pre class="prompt-preview" id="promptPreview" aria-live="polite"></pre>
      </div>
      <span class="eyebrow">Speichern für</span>
      <div class="choice-grid">
        <label class="choice"><input type="radio" name="scope" value="global"${scope === "global" ? " checked" : ""}>
          <span class="choice-card">${ICONS.agent}<span><strong>Alle Projekte</strong><small>~/.coder/commands</small></span></span></label>
        <label class="choice"><input type="radio" name="scope" value="project"${scope === "project" ? " checked" : ""}>
          <span class="choice-card">${ICONS.list_dir}<span><strong>Dieses Projekt</strong><small>.coder/commands im Workspace</small></span></span></label>
      </div>
      <p class="form-error" id="promptError" role="alert"></p>
      <div class="sheet-actions sticky">
        ${!isNew && c.editable ? `<button type="button" class="btn ghost danger" id="promptDelete">Löschen</button>` : ""}
        <span class="spacer"></span>
        <button type="button" class="btn ghost" id="promptBack">Zurück</button>
        <button type="submit" class="btn primary">Sichern</button>
      </div>
    </form>`;
  const form = $("#promptForm");
  // Werte über .value – so kann nichts im Text das Formular zerlegen.
  form.elements.name.value = isNew ? preset.name || "" : c.name;
  form.elements.description.value = isNew ? preset.description || "" : c.description || "";
  form.elements.hint.value = isNew ? "" : c.hint || "";
  form.elements.template.value = isNew ? preset.template || "" : c.template || "";
  promptsUI.dirty = isNew && !!preset.template;
  const probe = () => {
    const name = form.elements.name.value.trim().replace(/^\//, "").toLowerCase() || "name";
    $("#probeName").textContent = `/${name}`;
    const template = form.elements.template.value;
    const args = $("#promptProbe").value.trim();
    $("#promptPreview").textContent = template.trim()
      ? expandCommand({ template }, args)
      : "Hier erscheint, was Coder bekommt.";
    $("#promptPreview").classList.toggle("empty", !template.trim());
  };
  probe();
  form.addEventListener("input", (e) => {
    if (e.target.id !== "promptProbe") promptsUI.dirty = true;
    probe();
  });
  $("#promptArgs").addEventListener("click", () => {
    const area = form.elements.template;
    const at = area.selectionStart ?? area.value.length;
    area.setRangeText("$ARGUMENTS", at, area.selectionEnd ?? at, "end");
    area.focus();
    promptsUI.dirty = true;
    probe();
  });
  (isNew && !form.elements.name.value ? form.elements.name : form.elements.template).focus();
  $("#promptBack").addEventListener("click", () => {
    if (promptsUI.dirty && !confirm("Der Prompt ist noch nicht gesichert. Verwerfen?")) return;
    renderPrompts();
  });
  $("#promptDelete")?.addEventListener("click", () => deletePrompt(c));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    savePrompt(form, isNew ? null : c);
  });
}

async function savePrompt(form, original) {
  const body = {
    name: form.elements.name.value.trim().replace(/^\//, "").toLowerCase(),
    description: form.elements.description.value.trim(),
    hint: form.elements.hint.value.trim(),
    template: form.elements.template.value,
    tab: $("input[name=tab]:checked", form)?.value || "all",
    scope: $("input[name=scope]:checked", form)?.value || "global",
    workspace: currentWorkspace(),
  };
  if (original?.editable) Object.assign(body, { original: original.name, original_scope: original.source });
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  $("#promptError").textContent = "";
  try {
    const saved = await api("/api/commands", { method: "POST", body });
    promptsUI.dirty = false;
    toast(`/${saved.name} gesichert – tippe /${saved.name} in der Eingabe`);
    await loadExtensions(true);
    renderPrompts();
    updateStart();
  } catch (e) {
    $("#promptError").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function deletePrompt(cmd) {
  if (!confirm(`/${cmd.name} löschen?`)) return;
  try {
    const q = `?workspace=${encodeURIComponent(currentWorkspace())}`;
    await api(`/api/commands/${cmd.source}/${encodeURIComponent(cmd.name)}${q}`, { method: "DELETE" });
    promptsUI.dirty = false;
    toast(`/${cmd.name} gelöscht`);
    await loadExtensions(true);
    renderPrompts();
    updateStart();
  } catch (e) {
    $("#promptError").textContent = e.message;
  }
}

// Einsetzen: /name in die Eingabe – im Tab, in dem der Prompt gilt. Aus dem Editor geht es zurück in den Chat.
function usePrompt(cmd) {
  if (!closeSheets()) return;
  const here = state.tab !== "ide" && offeredIn(cmd);
  const target = here ? state.tab : offeredIn(cmd, "code") && roleAtLeast("read") ? "code" : "talk";
  const put = () => insertIntoInput(`/${cmd.name} `);
  if (target === state.tab) put();
  else switchTab(target).then(() => setTimeout(put, 0));
}

// Eine Nachricht oder die Eingabe als Prompt übernehmen: Der Editor öffnet sich mit dem Text.
function saveAsPrompt(text) {
  const template = String(text || "").trim();
  if (!canEditPrompts()) return toast(serverHas("1.12.0") ? "Prompts anlegen darf nur, wer Coder verwaltet." : "Eigene Prompts brauchen einen Neustart von Coder.", { error: true });
  if (!template) return toast("Schreib zuerst etwas in die Eingabe – daraus wird der Prompt.");
  openPrompts({ preset: { template, name: promptNameFrom(template), tab: state.tab === "talk" ? "talk" : "code" } });
}

// Ein Namensvorschlag aus den ersten tragenden Wörtern: „Erklär mir kurz die Struktur“ → erklaer-struktur.
const NAME_FILLER = new Set(["bitte", "kurz", "eine", "einen", "einem", "einer", "diese", "diesem", "dieser", "dieses",
  "oder", "mich", "noch", "auch", "dann", "wenn", "dass", "please", "this", "that", "with", "from", "about"]);
function promptNameFrom(text) {
  const words = String(text || "").replace(/^[/@][\w:-]+\s*/, "").toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "").match(/[a-z0-9]+/g) || [];
  return words.filter((w) => w.length > 3 && !NAME_FILLER.has(w)).slice(0, 2).join("-").slice(0, 30);
}

$("#promptsBody").addEventListener("click", (e) => {
  const use = e.target.closest("[data-prompt-use]");
  const edit = e.target.closest("[data-prompt-edit]");
  const tab = e.target.closest("[data-prompt-tab]");
  const find = (name) => state.ext.commands.find((c) => c.name === name);
  if (use) usePrompt(find(use.dataset.promptUse));
  else if (edit) promptEditor(find(edit.dataset.promptEdit));
  else if (tab) {
    promptsUI.tab = tab.dataset.promptTab;
    renderPrompts();
  } else if (e.target.closest("[data-prompt-new]")) promptEditor(null);
});
$("#promptsBody").addEventListener("input", (e) => {
  if (e.target.id !== "promptFilter") return;
  promptsUI.filter = e.target.value;
  renderPrompts({ keepFocus: true });
});
$("#promptNew").addEventListener("click", () => promptEditor(null));
$("#promptsBtn").addEventListener("click", () => openPrompts());

/* ---------------------------------------------------------------- Eigene Nachrichten: kopieren, wiederverwenden, merken */

thread.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-user-act]");
  if (!btn) return;
  const text = btn.closest(".turn.user")?.raw || "";
  const act = btn.dataset.userAct;
  if (act === "copy") {
    await copyText(text);
    btn.textContent = "Kopiert";
    setTimeout(() => (btn.textContent = "Kopieren"), 1400);
  } else if (act === "reuse") {
    if (input.value.trim() && !confirm("Die Eingabe ist nicht leer. Ersetzen?")) return;
    insertIntoInput(text);
  } else if (act === "prompt") {
    saveAsPrompt(text);
  }
});

/* ================================================================ Globale Aktionen */

function toggleSidebar() {
  const app = $("#app");
  if (matchMedia("(max-width: 760px)").matches) {
    app.classList.toggle("open");
  } else {
    app.classList.toggle("collapsed");
    store.set("coder.sidebar", app.classList.contains("collapsed") ? "0" : "1");
  }
}

$("#newChat").addEventListener("click", () => {
  if (!leavingIncognito()) return;
  if (state.tab === "ide") switchTab("code", { open: false });
  send({ type: "new", kind: state.tab === "talk" ? "talk" : "code" }); // ein laufender Auftrag arbeitet weiter
  input.focus();
});
$("#modelBtn").addEventListener("click", openModels);
$("#settingsBtn").addEventListener("click", () => openSettings());
$("#workspaceBtn").addEventListener("click", openWorkspace);
$("#wsChip").addEventListener("click", openWorkspace);
$("#settingsWorkspace").addEventListener("click", () => { if (closeSheets()) openWorkspace(); });
// Das Formular im obersten offenen Fenster, das sich mit Strg+S sichern lässt.
function sheetForm() {
  const open = $$(".sheet-backdrop:not([hidden]):not(.closing)");
  const top = open[open.length - 1];
  return top ? $("#settingsForm, #promptForm, #agentForm", top) : null;
}
$("#search").addEventListener("input", renderSessions);
const MODES = ["chat", "ask", "auto-edit", "plan", "yolo"];
$("#modeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.classList.contains("on") && matchMedia("(max-width: 560px)").matches) {
    // Schmal ist nur der aktive Modus sichtbar: Tippen schaltet zum nächsten.
    const next = MODES[(MODES.indexOf(b.dataset.mode) + 1) % MODES.length];
    setMode(next);
    toast(`Modus: ${$(`#modeSeg [data-mode="${next}"]`).getAttribute("aria-label")}`);
    return;
  }
  setMode(b.dataset.mode);
});
$("#sidebarToggle").addEventListener("click", toggleSidebar);
$("#scrim").addEventListener("click", () => $("#app").classList.remove("open"));
window.addEventListener("resize", () => setMode(state.config?.permission_mode || "ask", false));

document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  const sheetOpen = $$(".sheet-backdrop:not([hidden])").length > 0;
  const key = e.key.toLowerCase();
  if (e.key === "Escape") {
    if (!$("#treeMenu").hidden) return hideTreeMenu();
    if (!$("#lightbox").hidden) return ($("#lightbox").hidden = true);
    if (!$("#palette").hidden) return closePalette();
    if (sheetOpen) return closeSheets();
    if (!$("#effortPop").hidden) return closeEffort(true);
    if (!$("#ctxPop").hidden) return closeCtx(true);
    if (state.tab === "ide") {
      if (!$("#findBar").hidden) closeFind();
      return; // im Editor beantwortet oder stoppt Esc nichts, was im Tab Code wartet
    }
    if (cancelMic()) return;
    if (state.question) return answerQuestion({ skipped: true });
    if (state.approvalId) return answerApproval("deny");
    if ($("#app").classList.contains("open")) return $("#app").classList.remove("open");
    if (state.busy) send({ type: "cancel" });
  } else if (state.question && !mod && !e.altKey && /^[1-9]$/.test(e.key) && !sheetOpen
    && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
    e.preventDefault();
    pickOption(Number(e.key) - 1);
  } else if (mod && (key === "s" || e.key === "Enter") && sheetOpen && sheetForm()) {
    e.preventDefault(); // Einstellungen und Prompt-Editor sichern wie ein Editor
    sheetForm().requestSubmit();
  } else if (mod && e.key === "Enter" && state.approvalId && !sheetOpen) {
    e.preventDefault();
    answerApproval("allow");
  } else if (mod && key === "n") {
    e.preventDefault();
    $("#newChat").click();
  } else if (mod && key === "m") {
    e.preventDefault();
    openModels();
  } else if (mod && key === "o") {
    e.preventDefault();
    if (!sheetOpen) openWorkspace();
  } else if (mod && key === "e" && !e.shiftKey) {
    e.preventDefault();
    if (state.tab === "ide") switchTab(store.get("coder.lastTab") || "code");
    else openFiles();
  } else if (mod && key === "p" && !e.shiftKey) {
    e.preventDefault();
    if (roleAtLeast("read")) openPalette("files");
  } else if (state.tab === "ide" && mod && e.shiftKey && key === "v") {
    e.preventDefault();
    togglePreview();
  } else if (mod && e.shiftKey && key === "f") {
    e.preventDefault();
    if (roleAtLeast("read")) openFiles().then(() => setExplorerView("search"));
  } else if (mod && (key === "ö" || e.code === "Backquote")) {
    e.preventDefault();
    toggleTerminal();
  } else if (state.tab === "ide" && !sheetOpen && e.key === "F5") {
    e.preventDefault();
    runFile();
  } else if (state.tab === "ide" && !sheetOpen && mod && (key === "f" || key === "h")) {
    e.preventDefault();
    openFind(key === "h");
  } else if (state.tab === "ide" && !sheetOpen && mod && e.shiftKey && key === "o") {
    e.preventDefault();
    if (files.path) openPalette("symbols");
  } else if (state.tab === "ide" && !sheetOpen && mod && ["+", "=", "-", "0"].includes(e.key)) {
    e.preventDefault(); // nur im Editor: die Schrift, nicht die ganze Seite
    editorZoom(e.key === "0" ? 0 : e.key === "-" ? -1 : 1);
  } else if (state.tab === "ide" && !sheetOpen && mod && key === "g") {
    e.preventDefault();
    openPalette("files", ":");
  } else if (state.tab === "ide" && !sheetOpen && mod && key === "w") {
    e.preventDefault(); // im App-Fenster; ein Browser behält Strg+W für sich
    if (files.path) closeTab(files.path);
  } else if (state.tab === "ide" && mod && key === "s" && document.activeElement?.id !== "fileText") {
    e.preventDefault();
    saveFile();
  } else if (mod && key === "d" && !e.shiftKey) {
    e.preventDefault();
    toggleMic();
  } else if (mod && key === "j") {
    e.preventDefault();
    openCowork();
  } else if (mod && key === "k") {
    e.preventDefault();
    togglePalette();
  } else if (mod && key === "b") {
    e.preventDefault();
    toggleSidebar();
  } else if (mod && e.key === ",") {
    e.preventDefault();
    openSettings();
  }
});

/* ================================================================ Befehlspalette */

const palette = { items: [], index: 0, returnFocus: null, mode: "all" };
const MODE_NAMES = { chat: "Chat", ask: "Normal", "auto-edit": "Auto-Edit", plan: "Planen", yolo: "Autonom" };
const PALETTE_GROUPS = ["Aktionen", "Befehle", "Agents", "Notizen", "Chats", "Modus", "Aufwand", "Stil", "Farbthema"];

function togglePalette() {
  if ($("#palette").hidden) openPalette();
  else closePalette();
}

async function openPalette(mode = "all", text = "") {
  palette.mode = mode;
  palette.returnFocus = document.activeElement;
  palette.index = 0;
  $("#palette").hidden = false;
  $("#paletteInput").value = text;
  $("#paletteInput").placeholder = mode === "files" ? "Datei öffnen – mit :Zahl zur Zeile springen"
    : mode === "symbols" ? "Funktion, Klasse oder Überschrift in dieser Datei" : "Aktion, Befehl, Agent, Notiz oder Chat";
  renderPalette();
  $("#paletteInput").focus();
  if (mode === "files") await loadAllFiles().catch((e) => toast(e.message, { error: true }));
  else await Promise.allSettled([roleAtLeast("read") && loadExtensions(), roleAtLeast("admin") && loadNotes()]);
  if (!$("#palette").hidden) renderPalette();
}

// Alle Dateien des Workspace für die Schnellsuche – einmal geholt, bis sich etwas ändert.
async function loadAllFiles() {
  const ws = files.root || ideWorkspace();
  if (files.all && files.allRoot === ws) return files.all;
  const data = await api(`/api/files?workspace=${encodeURIComponent(ws)}`);
  files.all = data.files;
  files.allRoot = ws;
  return files.all;
}

// Funktionen, Klassen und Überschriften der offenen Datei – für „Gehe zu Symbol“ (Strg+Umschalt+O).
const SYMBOL_RX = {
  py: /^[ \t]*(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_]\w*)/gm,
  js: /^[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?(?:async[ \t]+)?(function\*?|class|interface|type|enum)[ \t]+([A-Za-z_$][\w$]*)|^[ \t]*(?:export[ \t]+)?(const|let|var)[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*(?:async[ \t]*)?(?:\([^)\n]*\)|[A-Za-z_$][\w$]*)[ \t]*=>/gm,
  go: /^(func)[ \t]+(?:\([^)\n]*\)[ \t]*)?([A-Za-z_]\w*)|^(type)[ \t]+([A-Za-z_]\w*)/gm,
  rust: /^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?(fn|struct|enum|trait|impl|mod)[ \t]+([A-Za-z_]\w*)/gm,
  java: /^[ \t]*(?:(?:public|private|protected|static|final|abstract)[ \t]+)*(class|interface|enum|record)[ \t]+([A-Za-z_]\w*)/gm,
  c: /^[ \t]*(?:(?:public|private|protected|static|inline|virtual)[ \t]+)*(class|struct|enum|namespace)[ \t]+([A-Za-z_]\w*)/gm,
  md: /^(#{1,6})[ \t]+(.+)$/gm,
  css: /^()([^{}\n@/][^{}\n]*?)[ \t]*\{/gm,
  sh: /^[ \t]*(function)?[ \t]*([A-Za-z_][\w-]*)[ \t]*\(\)[ \t]*\{/gm,
};
const SYMBOL_KIND = { def: "Funktion", function: "Funktion", "function*": "Generator", fn: "Funktion", func: "Funktion",
  class: "Klasse", struct: "Struktur", enum: "Aufzählung", trait: "Trait", impl: "impl", interface: "Schnittstelle",
  type: "Typ", const: "Konstante", let: "Variable", var: "Variable", mod: "Modul", namespace: "Namensraum",
  record: "Record" };

function symbolsOf(text, lang) {
  const rx = SYMBOL_RX[lang];
  if (!rx) return [];
  const out = [];
  let m;
  let line = 1;
  let pos = 0;
  rx.lastIndex = 0;
  while ((m = rx.exec(text)) && out.length < 2000) {
    if (!m[0]) { rx.lastIndex++; continue; }
    const g = m.slice(1).filter((x) => x !== undefined);
    const [kind, name] = g.length >= 2 ? g : ["", g[0]];
    if (!name) continue;
    for (; pos < m.index; pos++) if (text.charCodeAt(pos) === 10) line++; // Zeilen mitzählen, nicht jedes Mal von vorn
    const md = lang === "md";
    out.push({ name: name.trim(), kind: md ? `Überschrift ${kind.length}` : SYMBOL_KIND[kind] || (lang === "css" ? "Regel" : kind || "Funktion"), line });
  }
  return out;
}

function symbolEntries() {
  const text = currentText();
  return symbolsOf(text, langOf(files.path)).map((sym) => ({
    group: "Symbole", icon: ICONS.command, label: sym.name, desc: `${sym.kind} · Zeile ${sym.line}`, mono: true,
    run: () => goToLine(sym.line),
  }));
}

function fileEntries() {
  const line = $("#paletteInput").value.trim().match(/^:(\d*)$/);
  if (line) {
    return files.path ? [{ group: "Dateien", icon: ICONS.arrow, label: line[1] ? `Zu Zeile ${line[1]} springen` : "Zeilennummer eingeben",
      desc: files.path, line: true, run: () => line[1] && goToLine(Number(line[1])) }] : [];
  }
  const open = files.order.slice().reverse();
  const rest = (files.all || []).filter((p) => !files.docs.has(p));
  return [...open, ...rest].map((p) => ({ group: "Dateien", icon: fileIconFor(p), label: basename(p), desc: parentOf(p),
    path: p, hint: files.docs.has(p) ? "offen" : "", run: () => openFiles(p) }));
}

function fileScore(entry, query) {
  const name = entry.label.toLowerCase();
  const path = entry.path.toLowerCase();
  if (name.startsWith(query)) return 100 - Math.min(name.length, 60) / 100;
  if (name.includes(query)) return 70;
  if (path.includes(query)) return 40;
  let pos = 0; // Buchstaben in Reihenfolge: „apjs“ findet „web/app.js“
  for (const ch of query.replace(/\s+/g, "")) {
    pos = path.indexOf(ch, pos);
    if (pos < 0) return 0;
    pos++;
  }
  return 10;
}

function closePalette() {
  $("#palette").hidden = true;
  palette.returnFocus?.focus?.();
}

function insertIntoInput(text) {
  input.value = text;
  autosize();
  updateSendState();
  input.focus();
  input.setSelectionRange(text.length, text.length);
}

function paletteEntries() {
  const action = (icon, label, run, hint = "") => ({ group: "Aktionen", icon: ICONS[icon], label, run, hint });
  const admin = roleAtLeast("admin");
  const reader = roleAtLeast("read");
  const entries = [
    action("plus", "Neuer Chat", () => $("#newChat").click(), "Strg N"),
    ...(state.tab !== "talk" ? [action("chat", "Zum Chat – reden und recherchieren", () => switchTab("talk"))] : []),
    ...(reader && state.tab !== "code" ? [action("command", "Zum Code – der Agent im Projekt", () => switchTab("code"))] : []),
    ...(reader ? [
      action("read_file", "Editor öffnen", () => openFiles(), "Strg E"),
      action("glob", "Datei öffnen …", () => setTimeout(() => openPalette("files"), 0), "Strg P"),
      action("grep", "In allen Dateien suchen", () => openFiles().then(() => setExplorerView("search")), "Strg Umschalt F"),
      ...(state.tab === "ide" && files.path ? [action("command", "Gehe zu Symbol in dieser Datei", () => setTimeout(() => openPalette("symbols"), 0), "Strg Umschalt O")] : []),
    ] : []),
    ...(roleAtLeast("code") ? [action("run_command", "Terminal im Editor", () => toggleTerminal(true), "Strg Ö")] : []),
    ...(admin ? [
      action("list_dir", "Workspace wählen", openWorkspace, "Strg O"),
      action("chip", "Modell wählen", openModels, "Strg M"),
      action("graph", "Gedächtnis öffnen", () => openMemory()),
      action("agent", "Agents verwalten", openAgents),
      action("users", "Freigabe – andere an Coder lassen", openShare),
      action("cowork", "Cowork – mehrere Aufträge gleichzeitig", openCowork, "Strg J"),
    ] : []),
    ...(micReady() ? [action("mic", "Diktieren – sprechen statt tippen", toggleMic, "Strg D")] : []),
    action("image", "Bild anhängen", () => $("#fileInput").click()),
    action("compact", "Verlauf verdichten", () => send({ type: "compact" })),
    action("undo", "Letzte Änderungen zurücknehmen", undoLast),
    action("copy", "Chat als Markdown kopieren", copyChat),
    action("note", "Bericht zum Ausdrucken – für eine Abgabe oder den Prüfer", makeReport),
    action("redo", "Auftrag in Schleife wiederholen", () => insertIntoInput("/loop "), "/loop"),
    action("sparkle", "Auftrag schärfen lassen", () => sharpen(), "/prompt"),
    action("command", "Prompts – eigene /Befehle ansehen und anlegen", () => openPrompts(), "/prompts"),
    ...(canEditPrompts() ? [action("plus", "Neuer Prompt", () => openPrompts().then(() => promptEditor(null)))] : []),
    ...(canEditPrompts() && input.value.trim() ? [action("memory_write", "Eingabe als Prompt sichern", () => saveAsPrompt(input.value))] : []),
    ...(serverHas("1.12.0") ? [action("person", "Eigene Anweisungen – wer du bist, wie Coder antworten soll", () => openSettings("set-personal"), "/anweisungen")] : []),
    action("sidebar", "Seitenleiste ein- oder ausblenden", toggleSidebar, "Strg B"),
    action("gear", "Einstellungen", () => openSettings(), "Strg ,"),
    action("chip", "Design wechseln – Ruhig, Terminal, Papier", toggleDesign),
    action("mode", "Hell oder dunkel umschalten", toggleTheme),
    action("palette", "Farbthema wechseln – Nord, Solarized, Gruvbox …", cycleColors),
    action("effort", "Aufwand einstellen", openEffort),
  ];
  for (const c of (state.ext?.commands || []).filter((c) => offeredIn(c))) {
    entries.push({ group: "Befehle", icon: ICONS.command, label: `/${c.name}`, mono: true, desc: c.description, run: () => usePrompt(c) });
  }
  for (const a of state.ext?.agents || []) {
    entries.push({ group: "Agents", icon: ICONS.agent, label: `@${a.name}`, mono: true, desc: a.description, run: () => insertIntoInput(`@${a.name} `) });
  }
  for (const n of memoryUI.data?.notes || []) {
    entries.push({ group: "Notizen", icon: ICONS.note, label: n.title, desc: vaultLabel(n.vault), run: () => openMemory({ title: n.title, vault: n.vault }) });
  }
  for (const s of state.sessions || []) {
    entries.push({
      group: "Chats", icon: ICONS.chat, label: s.title || "Ohne Titel",
      desc: [kindOf(s) === "talk" ? "Chat" : "Code", whenLabel(s.updated), kindOf(s) === "talk" ? "" : basename(s.workspace)].filter(Boolean).join(" · "),
      run: () => leavingIncognito() && send({ type: "open", session_id: s.id }),
    });
  }
  // Im Chat-Tab gibt es nichts zurückzunehmen, zu wiederholen oder als Auftrag zu schärfen.
  const codeOnly = new Set(["Letzte Änderungen zurücknehmen", "Auftrag in Schleife wiederholen", "Auftrag schärfen lassen"]);
  if (state.tab === "talk") entries.splice(0, entries.length, ...entries.filter((e) => !codeOnly.has(e.label)));
  if (state.session?.messages?.length && state.tab !== "ide") {
    entries.splice(1, 0, action("note", "Chat umbenennen", () => renameSession(state.session), "F2"));
  }
  for (const mode of MODES.filter((m) => !state.me?.modes?.length || state.me.modes.includes(m))) {
    if (state.tab === "talk") break; // der Chat-Tab hat keine Modi
    entries.push({ group: "Modus", icon: mode === "chat" ? ICONS.chat : ICONS.mode, label: MODE_NAMES[mode], desc: state.config?.permission_mode === mode ? "aktiv" : "", run: () => setMode(mode) });
  }
  for (const level of EFFORTS) {
    entries.push({ group: "Aufwand", icon: ICONS.effort, label: `Aufwand: ${EFFORT_NAMES[level]}`, desc: currentEffort() === level ? "aktiv" : EFFORT_HINT[level], run: () => setEffort(level) });
  }
  for (const style of serverHas("1.12.0") ? STYLES : []) {
    entries.push({ group: "Stil", icon: ICONS.style, label: `Antwortstil: ${STYLE_NAMES[style]}`, desc: currentStyle() === style ? "aktiv" : STYLE_HINT[style], run: () => setStyle(style, { loud: true }) });
  }
  const colors = document.documentElement.dataset.palette || "standard";
  for (const name of COLOR_THEMES) {
    entries.push({
      group: "Farbthema", icon: ICONS.palette, label: `Farbthema: ${COLOR_NAMES[name]}`, desc: colors === name ? "aktiv" : "",
      run: () => {
        applyColors(name);
        api("/api/config", { method: "POST", body: { palette: name } }).then((cfg) => { state.config = cfg; }).catch(() => { });
      },
    });
  }
  return entries;
}

function paletteScore(entry, query) {
  const label = entry.label.toLowerCase();
  const at = label.indexOf(query);
  if (at === 0 || (at === 1 && /^[/@]/.test(label))) return 100;
  if (at > 0) return 70 - Math.min(at, 40);
  if ((entry.desc || "").toLowerCase().includes(query)) return 20;
  let pos = 0; // Buchstaben in Reihenfolge: „nc“ findet „Neuer Chat“
  for (const ch of query) {
    pos = label.indexOf(ch, pos);
    if (pos < 0) return 0;
    pos++;
  }
  return 10;
}

function renderPalette() {
  const query = $("#paletteInput").value.trim().toLowerCase();
  const filesMode = palette.mode === "files" || palette.mode === "symbols";
  const entries = palette.mode === "symbols" ? symbolEntries() : filesMode ? fileEntries() : paletteEntries();
  const scorer = palette.mode === "files" ? fileScore : paletteScore;
  const items = filesMode && (!query || entries[0]?.line) ? entries.slice(0, 40) : query
    ? entries.map((entry) => [entry, scorer(entry, query)]).filter(([, score]) => score > 0)
      .sort((a, b) => b[1] - a[1]).slice(0, 40).map(([entry]) => entry)
    // Aktionen sind Coders eigene, überschaubare Liste – die gehört vollständig hin, nicht gekappt.
    : PALETTE_GROUPS.flatMap((group) => (group === "Aktionen" ? entries.filter((e) => e.group === group)
      : entries.filter((e) => e.group === group).slice(0, 5)));
  palette.items = items;
  palette.index = Math.max(0, Math.min(palette.index, items.length - 1));
  let group = null;
  $("#paletteList").innerHTML = items.map((item, i) => {
    const head = !query && !filesMode && item.group !== group ? `<span class="palette-group eyebrow">${item.group}</span>` : "";
    group = item.group;
    const desc = query && !filesMode ? [item.desc, item.group].filter(Boolean).join(" · ") : item.desc || "";
    return `${head}<button type="button" class="palette-item" role="option" data-i="${i}" aria-selected="${i === palette.index}">
      ${item.icon || ""}<span class="palette-label${item.mono ? " mono" : ""}">${esc(item.label)}</span>
      <span class="palette-desc">${esc(desc)}</span>${item.hint ? `<kbd>${esc(item.hint)}</kbd>` : "<span></span>"}
    </button>`;
  }).join("") || `<div class="palette-empty">${palette.mode === "files" && !files.all ? "Lädt die Dateien …"
    : palette.mode === "symbols" && !query ? "In dieser Datei hat Coder keine Funktionen oder Überschriften gefunden." : "Nichts gefunden."}</div>`;
  $(`#paletteList [data-i="${palette.index}"]`)?.scrollIntoView({ block: "nearest" });
}

function runPalette(i = palette.index) {
  const item = palette.items[i];
  if (!item) return;
  closePalette();
  item.run();
}

$("#paletteInput").addEventListener("input", () => {
  palette.index = 0;
  renderPalette();
});
$("#paletteInput").addEventListener("keydown", (e) => {
  const n = palette.items.length;
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) {
    e.preventDefault();
    palette.index = (palette.index + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
    $$("#paletteList .palette-item").forEach((row) => row.setAttribute("aria-selected", String(Number(row.dataset.i) === palette.index)));
    $(`#paletteList [data-i="${palette.index}"]`)?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    e.preventDefault();
    runPalette();
  }
});
$("#paletteList").addEventListener("mousedown", (e) => e.preventDefault());
$("#paletteList").addEventListener("click", (e) => {
  const row = e.target.closest("[data-i]");
  if (row) runPalette(Number(row.dataset.i));
});
$("#palette").addEventListener("mousedown", (e) => { if (e.target.id === "palette") closePalette(); });

/* ================================================================ Start */

async function loadState() {
  try {
    const s = await api("/api/state");
    state.config = s.config;
    state.version = s.version;
    applyDesign(s.config.design);
    applyTheme(s.config.theme);
    applyColors(savedColors(s.config));
    updateSharpenChip();
    updateEffortChip();
    micInfo(true);
    state.hardware = s.hardware;
    state.ollama = s.ollama;
    state.loaded = s.loaded;
    state.sessions = s.sessions;
    state.nativePicker = !!s.native_picker;
    state.me = s.me || null;
    applyRole();
    updateStyleChip();
    updateWorkspace();
    updateModelPill();
    setMode(s.config.permission_mode, false);
    renderSessions();
    if (!s.ollama.ok) toast("Ollama ist nicht erreichbar – starte Ollama.", { error: true, ms: 6000 });
  } catch (e) {
    toast(`Server nicht erreichbar: ${e.message}`, { error: true, ms: 6000 });
  }
}

(async function init() {
  if (store.get("coder.sidebar") === "0") $("#app").classList.add("collapsed");
  await loadState();
  const tab = store.get("coder.tab");
  await switchTab(TABS.includes(tab) ? tab : "code", { open: false }).catch(() => { });
  if (store.get("coder.terminal") === "1" && roleAtLeast("code")) $("#idePanel").hidden = false;
  connect();
  updatePlaceholder();
  autosize();
  updateSendState();
  setContext(null);
  input.focus();
  setInterval(() => { if (!state.busy) refreshLoaded(); }, 20000);
  document.fonts?.ready.then(() => setMode(state.config?.permission_mode || "ask", false));
})();
