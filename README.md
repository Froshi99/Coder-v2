# Coder

Ein lokaler Coding-Agent im Stil von Claude Code – für Ollama, mit ruhiger Oberfläche und einem Terminal-Modus samt Axolotl.
Liest, sucht, bearbeitet Dateien, führt Befehle aus, sieht Bilder, malt welche und recherchiert im Netz – oder redet
im Chat-Modus einfach mit dir. Fragt nach, wenn eine Entscheidung bei dir liegt, und arbeitet so gründlich, wie du den
Aufwand einstellst. Alles läuft auf deinem Rechner.

## Start

```bash
pip install -r requirements.txt
python coder.py
```

| Befehl | Wirkung |
| --- | --- |
| `python coder.py` | App-Fenster (PyQt6 WebEngine, sonst Browser) |
| `python coder.py --browser` | Oberfläche im Standardbrowser |
| `python coder.py cli` | Agent direkt im Terminal |
| `python coder.py test` | Testreihen laufen lassen |
| `python coder.py -w C:\Projekte\app` | Workspace festlegen |
| `python coder.py -m qwen2.5-coder:14b` | Modell festlegen |
| `python coder.py --serve --host 0.0.0.0` | Nur Server, im LAN per IP-Adresse erreichbar – mit Anmeldung |
| `start.bat` | Doppelklick-Start unter Windows |
| `start_cmd.bat` | Doppelklick-Start im Terminalmodus |

## Was drin ist

**Drei Bereiche** – oben links: *Code*, *Chat*, *Editor*
- *Code* ist der Agent in deinem Projekt, mit Modi, Freigaben und allem, was unten steht
- *Chat* ist ein eigener Ort zum Reden und Recherchieren – mit eigener Chat-Liste, getrennt von den Code-Chats, ohne Projekt und ohne Dateien. Coder sucht im Netz, öffnet die Seiten und antwortet mit Quellen als Links; bei Einkäufen (Kleidung, Technik, Geschenke) mit Produkt, Shop, Preis und Größe, gern als Tabelle. Recherche braucht dort keine Freigabe – sie ist der Zweck. Unter *Einstellungen → Chat-Tab* kann ein eigenes Modell antworten, etwa ein Allrounder statt eines Code-Modells
- *Editor* sind die Dateien selbst – siehe unten
- Wechseln geht jederzeit, auch während der Agent arbeitet: Der Auftrag läuft weiter und steht in der Liste als „arbeitet“. Jeder Bereich merkt sich seinen letzten Chat
- **Inkognito** (Maske oben rechts im Tab *Chat*): Der Chat wird nirgends gesichert, steht in keiner Liste, nutzt kein Gedächtnis und schreibt nichts hinein. Verlässt du ihn, ist er weg – Coder fragt vorher nach. Eine kurz gerissene Verbindung übersteht er (zwei Minuten, nur im Speicher); einen Bericht als Datei gibt es aus ihm nicht
- Chats umbenennen: Doppelklick auf den Titel in der Liste (oder `F2`)
- Lange Chats öffnen schnell: Zu sehen sind erst die letzten 30 Aufträge, ältere auf Knopfdruck

**Persönlich: eigene Anweisungen und Antwortstil** (*Einstellungen → Persönlich*, `/anweisungen`)
- Dein **User-Prompt**: Was du hier über dich schreibst – wer du bist, was Coder wissen soll, wie er antworten und arbeiten soll –, liest er vor jedem Auftrag. Wie die „Persönlichen Einstellungen“ bei Claude oder `~/.claude/CLAUDE.md` bei Claude Code
- Drei Felder: *Für alles* gilt überall, *Zusätzlich im Code* nur beim Agent im Projekt und im Terminal (Sprache, Tests, Konventionen), *Zusätzlich im Chat* nur im Tab *Chat* (Größen, Budget, Wohnort). Je Feld bis 4000 Zeichen; darunter steht, wie viele Token das jeden Auftrag kostet
- **Antwortstil**: *Normal*, *Knapp* (Ergebnis zuerst), *Ausführlich* (mit Hintergrund und Alternativen), *Erklärend* (das Warum – zum Dazulernen), *Förmlich* (mit „Sie“). Weicht er vom Normalen ab, steht er als leiser Chip neben der Eingabe; wechseln geht auch mit `/stil knapp` oder in der Befehlspalette
- Die Anweisungen stehen am Ende des System-Prompts und gehen vor Ton, Sprache und Länge – aber nie vor den Regeln des Modus, der Werkzeuge oder der Sicherheit. Sub-Agents und die Kontrolle bekommen sie nicht: Sie reden nie mit dir
- **Jedes Konto hat seine eigenen**: Wer über die Freigabe dazukommt, sieht und bekommt nie deine Anweisungen und deinen Stil, sondern stellt sich seine eigenen ein – auch mit der Rolle *Nur Chat*
- Solange keine Anweisungen da sind, erinnert ein Hinweis auf der Startseite daran (mit × für immer weg)

**Eigene Prompts** (Knopf mit `/` in der Seitenleiste, `/prompts`)
- Fertige Aufträge, die du mit `/name` aufrufst: Was dahinter steht, setzt Coder für `$ARGUMENTS` ein, `$1`, `$2` sind einzelne Wörter. Ein Beispiel: `/wochenbericht KW 39`
- Anlegen, ändern, löschen im Fenster *Prompts* – mit **Probe**: Du tippst ein Beispiel und siehst sofort, was beim Modell ankommt. Jede eigene Nachricht im Verlauf lässt sich mit **Als Prompt** übernehmen (Name wird vorgeschlagen), die Eingabe über die Befehlspalette
- **Wo anbieten**: *Code*, *Chat* oder *Beide*. Im Tab *Chat* gibt es eigene eingebaute: `/mail`, `/compare`, `/tldr`, `/translate`. Ein Prompt nur für Code sagt im Chat-Tab, wo er hingehört, statt ins Leere zu laufen
- Gespeichert als Markdown wie bei Claude Code (`description`, `argument-hint`, dazu `tab`) in `~/.coder/commands` oder im Projekt unter `.coder/commands`. Namen, die Coder selbst benutzt (`/loop`, `/stil` …), sind gesperrt; einen eingebauten „anpassen“ legt eine eigene Fassung gleichen Namens an
- Die eigenen stehen beim Tippen von `/` ganz oben und auf der Startseite unter *Deine Prompts*. Anlegen dürfen nur Konten mit *Verwalten*; Gäste mit *Nur Chat* sehen die Prompts für den Tab Chat

**Agent**
- Werkzeuge: `read_file`, `list_dir`, `glob`, `grep`, `view_image`, `edit_file` (exakte Ersetzung mit Diff), `write_file`, `generate_image`, `run_command`, `web_search`, `web_fetch`, `web_research`, `memory_search`, `memory_read`, `memory_write`, `todo_write`, `ask_user` (Rückfrage)
- Terminal: PowerShell unter Windows, sonst bash – mit Timeout, echtem Exit-Code und UTF-8. Server und Watcher startet der Agent mit `background=true`; sie loggen nach `%TEMP%\coder-logs` und enden mit Coder
- Natives Ollama-Tool-Calling; für Modelle ohne Tool-Support automatisch ein Text-Protokoll (`<tool_call>`). Schreibt ein Modell seine Aufrufe als JSON in die Antwort – Qwen2.5-Coder tut das über Ollama oft –, erkennt Coder sie trotzdem und blendet sie aus dem Text aus
- Verzeiht typische Fehler kleiner Modelle: Parameternamen wie `file_path` oder `cmd`, aus `read_file` mitkopierte Zeilennummern, Leerzeichen am Zeilenende und eine einheitlich verschobene Einrückung in `edit_file` – nur bei eindeutigen Treffern, sonst meldet es den Fehler
- Schreibt ein Modell seine Aufrufe im XML-Stil (`<function=glob><parameter=pattern>…`), versteht Coder auch das – samt Zahlen und Ja/Nein-Werten, die dabei als Text ankommen
- `glob` versteht `**`, `{ts,tsx}` und `[!x]`, Muster ohne `/` suchen in allen Unterordnern; `grep` liefert auf Wunsch Kontextzeilen oder nur die Dateien. Abhängigkeits- und Build-Ordner werden übersprungen, `.github` nicht
- Kennt beim Start die oberste Ordnerebene des Workspace
- Projektanweisungen aus `CODER.md`, `AGENTS.md` oder `CLAUDE.md` im Workspace (`/init` legt eine an)

**Modi** (Umschalter oben rechts, im Terminal `Umschalt+Tab` oder `/mode`)
- *Chat* – einfach reden: fragen, erklären lassen, Ideen durchgehen. Coder liest dafür Dateien, sucht im Netz und nutzt das Gedächtnis, ändert aber nichts und führt nichts aus
  - Dateien, die du beim Namen nennst („Was macht app.py?“, `src/db.py`), liest er gleich mit – wie `@datei` in Claude Code. Unter deiner Nachricht steht „Mitgelesen: app.py“
  - Zeigt die Antwort eine Änderung an deinen Dateien, steht darunter **Im Modus Normal umsetzen**: ein Klick wechselt den Modus und lässt Coder die Änderung mit Freigabe anwenden
- *Normal* (Standard, früher „Fragen“) – liest frei; Änderungen, Befehle und Seitenabrufe brauchen eine Freigabe, mit Diff-Vorschau
- *Auto-Edit* – Dateien im Workspace frei, Befehle mit Freigabe
- *Planen* – nur lesen, bei offenen Entscheidungen nachfragen, dann einen Plan mit Dateien und Prüfschritten vorlegen. Darunter steht **Plan umsetzen**: mit Auto-Edit, jede Änderung einzeln freigeben – oder weiter planen
- *Autonom* – alles ohne Rückfrage, auch ohne Rückfragen des Agenten
- `Umschalt+Tab` wechselt im Terminal reihum Normal → Auto-Edit → Planen → Chat – wie in Claude Code. Autonom liegt bewusst nicht auf diesem Weg, dahin kommt man nur ausdrücklich

**Rückfragen**
- Liegt eine Entscheidung wirklich bei dir – zwei sinnvolle Wege, eine fehlende Angabe, eine folgenreiche Wahl –, fragt der Agent mit `ask_user` nach: eine kurze Frage mit zwei bis vier Antworten, die empfohlene zuerst, auf Wunsch mit Mehrfachwahl
- In der App erscheint die Frage über der Eingabe: Antwort anklicken oder Ziffer drücken, eine eigene Antwort ins Feld (oder einfach in die Eingabe) schreiben, `Esc` überspringt – dann entscheidet der Agent selbst und sagt, was er angenommen hat
- Im Terminal eine Auswahl wie in Claude Code: `↑`/`↓` und `Enter`, Ziffern direkt, bei Mehrfachwahl `Leertaste`. Wer einfach lostippt, schreibt eine eigene Antwort. `Esc` überspringt, `Strg+C` hält den Agent an
- Was du geantwortet hast, steht im Chat unter dem Schritt, im Bericht (`/print`) und sieht auch die Kontrolle. Höchstens vier Rückfragen je Auftrag; in Schleifen, bei Sub-Agents und im Modus Autonom fragt niemand nach
- Was sich aus dem Code klären lässt, fragt der Agent nicht – und um Erlaubnis fragt er nie selbst, das macht die App

**Aufwand** (Regler neben der Eingabe, im Terminal `/effort`)
- *Niedrig* – kürzester Weg: nur das Nötigste lesen, kleinste Änderung, kein Denkmodus, keine Kontrolle, halbes Schrittlimit
- *Mittel* – wie bisher: prüft, wenn es wenig kostet
- *Hoch* – gründlich: liest mehr, Denkmodus an (bei Modellen, die das können), testet jede Änderung, anderthalbfaches Schrittlimit
- *Maximal* – plant, sucht die Ursache statt des Symptoms, ergänzt Tests, prüft den ganzen Diff; Kontrolle mit einer Nachbesserung mehr, doppeltes Schrittlimit
- gpt-oss bekommt seine eigenen Denkstufen (low, medium, high). Unter dem Regler steht, was die Stufe konkret heißt: Schritte, Denkmodus, Kontrolle
- Der Regler bleibt unauffällig neben der Eingabe. Auch die Messwerte unter einer Antwort sind gedimmt: sichtbar sind Tempo und Dauer, Token und Prompt-Größe erscheinen, wenn du die Antwort überfährst

**Sprechen statt tippen** (Mikrofon-Knopf neben der Eingabe, `Strg+D`, im Terminal `/diktat`)
- Knopf drücken, sprechen, wieder drücken: Der Text steht in der Eingabe – zum Lesen, Ändern und Abschicken. Nichts wird von allein gesendet
- Erkannt wird mit **Whisper** (faster-whisper) auf diesem Rechner. Kein Dienst, kein Konto, keine Aufnahme, die irgendwo landet – nur das Erkennungsmodell wird einmal geladen, und auch das erst, wenn du in den Einstellungen darauf tippst
- Während der Aufnahme zeigt der Knopf die Dauer und einen Pegel: Man sieht, dass das Mikrofon wirklich hört. `Esc` verwirft
- Fünf Größen zur Wahl, mit Platzbedarf: Winzig (75 MB) bis Sehr groß (3 GB). **Mittel** (484 MB) ist für Deutsch der Kompromiss; auf dem Prozessor braucht es für ein paar Sätze wenige Sekunden
- Gerechnet wird automatisch dort, wo Platz ist: Die Grafikkarte nur, wenn dort gerade nichts Großes liegt – sonst der Prozessor. Nach dem Diktat gibt Coder den VRAM gleich wieder her
- Coder gibt Whisper vorher die Fachwörter mit (`Commit`, `Repository`, `README`), damit daraus kein „Komitee" wird. Was Whisper in Stille hineinhört („Untertitel …"), wirft Coder weg
- Im Terminal nimmt `/diktat` auf, bis es still wird, und legt den Text in die Eingabe
- Es fehlen Pakete? Unter *Einstellungen → Sprechen statt tippen* steht die Zeile zum Nachrüsten: `pip install faster-whisper sounddevice`
- Diktiert wird an dem Rechner, auf dem Coder läuft. Über das Netz (`--host 0.0.0.0`) gibt es den Knopf gar nicht erst – es wäre das falsche Mikrofon

**Rückgängig**
- Coder sichert jede Datei, bevor ein Auftrag sie zum ersten Mal ändert – auch Änderungen von Sub-Agents und nach einem Abbruch
- Unter jedem Auftrag steht, welche Dateien sich geändert haben. **Rückgängig** stellt den Stand davor wieder her, im Terminal `/undo`
- Zurückgenommen wird immer der jüngste Auftrag zuerst. Dateien, die danach noch jemand geändert hat, bleiben unangetastet. Befehle im Terminal lassen sich nicht zurücknehmen
- Coder behält die letzten 30 Sicherungen je Chat; beim Löschen eines Chats verschwinden seine Sicherungen

**Editor** – ein eigener Bereich (`Strg+E`, oben *Editor*)
- Links wird die Seitenleiste zum Explorer: der Workspace als Baum, Abhängigkeits- und Build-Ordner bleiben weg, `.github` nicht. Neue Datei und neuer Ordner über die Knöpfe oben oder das Kontextmenü (rechte Maustaste): Der Name wird direkt im Baum eingetippt, wie in VS Code. `F2` benennt um, `Entf` löscht – Gelöschtes landet im Papierkorb von Coder (`~/.coder/trash`), nicht im Nichts
- Mehrere Dateien als Tabs; was nicht gespeichert ist, trägt einen Punkt statt des Kreuzes. Cursor, Auswahl und Scrollstand bleiben je Datei, die offenen Tabs auch über einen Neustart hinweg
- **Strg+P** öffnet eine Datei per Namen (Buchstaben in Reihenfolge reichen: `apjs` findet `web/app.js`), `:42` springt zu Zeile 42. **Strg+Umschalt+F** sucht in allen Dateien – als Text oder regulärer Ausdruck, mit oder ohne Groß-/Kleinschreibung; ein Klick auf einen Treffer springt an die Stelle
- **Strg+F** sucht in der Datei, **Strg+H** ersetzt – einzeln oder alle auf einmal. Treffer liegen farbig unter dem Text
- Beim Schreiben: `Enter` behält die Einrückung (nach `:` in Python oder einer offenen Klammer eine Stufe mehr), `Tab`/`Umschalt+Tab` rücken ganze Zeilen ein und aus, `Strg+/` kommentiert Zeilen ein und aus, `Alt+↑`/`↓` verschiebt Zeilen. Alles bleibt in der Rückgängig-Liste (`Strg+Z`)
- **Terminal** (`Strg+Ö`): Befehle im Workspace, die Ausgabe kommt Stück für Stück, Eingaben gehen an das laufende Programm, `Strg+C` oder *Stoppen* beendet es, `↑` holt frühere Befehle. **F5** führt die offene Datei aus (Python, Node, TypeScript, PowerShell, Batch, Go, Java …) und speichert sie vorher. Die Höhe lässt sich an der Kante ziehen
- **Git**: Geänderte Dateien stehen im Baum in Warnfarbe mit `M`, neue grün mit `U`, Ordner mit Änderungen tragen einen Punkt. Unten steht der Branch samt Commits vor und hinter dem Server
- **Vorschau**: Bilder (PNG, JPG, GIF, WebP, SVG …) zeigt der Editor mit ihren Maßen auf einem Schachbrett; Markdown lässt sich mit *Vorschau* (`Strg+Umschalt+V`) gerendert lesen – und auch aus der Vorschau speichern
- **Änderungen** (bei Dateien, die git als geändert kennt): der Unterschied zum letzten Commit, Zeile für Zeile – ein Klick auf eine Zeile springt in die Datei
- **Gehe zu Symbol** (`Strg+Umschalt+O`): Funktionen, Klassen und Überschriften der offenen Datei – Python, JavaScript/TypeScript, Go, Rust, Java, C-artige Sprachen, CSS, Shell und Markdown
- Im Terminal werden Fehlerstellen klickbar: `File "src/app.py", line 12` aus Python, `src/index.ts:4:7` aus Compilern und Lintern, `Datei.cs(10,5)` – ein Klick öffnet die Datei an der Stelle
- Klammern und Anführungszeichen schließen sich selbst, eine Auswahl wird eingeklammert, `Backspace` löscht ein leeres Paar. Schriftgröße nur im Editor: `Strg +`, `Strg -`, `Strg 0`
- **Auswahl an Coder** (Sprechblase oben rechts): Die markierten Zeilen gehen samt Pfad und Zeilennummern als Codeblock in die Eingabe im Tab *Code*
- Speichern merkt, wenn die Datei inzwischen woanders geändert wurde – vom Agent, von einem zweiten Nutzer, von einem anderen Programm – und fragt, statt die fremde Änderung still zu überschreiben. Ändert der Agent eine offene Datei, lädt sie sich neu; hast du selbst schon getippt, steht dort „Woanders geändert – neu laden“
- Farben: ein eigener kleiner Hervorheber für Python, JavaScript/TypeScript, HTML, CSS, JSON, Markdown, Shell, YAML, TOML, SQL, Go, Rust, Java und C-artige Sprachen – dieselben Farben wie in den Codeblöcken im Chat. Große Dateien färbt der Editor nur um den sichtbaren Bereich herum, damit Tippen flüssig bleibt
- Zeilenenden bleiben, wie sie waren: Eine Windows-Datei (CRLF) kommt nicht als „geändert“ an und wird beim Speichern nicht still auf LF umgeschrieben. Die Statuszeile zeigt Zeile, Spalte, Sprache und Zeilenende
- Gelesen und geschrieben wird nur im Workspace: Pfade mit `..`, absolute Pfade und Verknüpfungen nach draußen weist der Server ab, Binärdateien und alles über 2 MB ebenso

**Ergänzen beim Schreiben** (in der Dateiansicht)
- Beim Tippen erscheint eine Liste unter dem Cursor: Wörter, die in der Datei schon vorkommen, Schlüsselwörter der Sprache und – sobald ein `/` im Wort steht – Pfade aus dem Workspace. `↑`/`↓` wählen, `Enter` oder `Tab` übernimmt, `Esc` schließt. Sie ist sofort da: Dafür rechnet kein Modell
- Ruht das Tippen einen Moment, schreibt das Modell weiter: Der Vorschlag steht grau hinter dem Cursor, `Tab` übernimmt ihn, `Esc` verwirft ihn. Wer einfach weiterschreibt und dasselbe tippt, behält ihn – Zeichen für Zeichen. Gespeichert wird nur, was wirklich in der Datei steht
- Gefragt wird mit **Fill in the Middle**: Das Modell sieht, was vor *und* was hinter dem Cursor steht. Qwen-Coder, DeepSeek-Coder, CodeLlama, StarCoder/CodeGemma/Stable-Code und Codestral bekommen ihre eigenen Marken; meldet Ollama für ein Modell `insert`, baut es den Prompt selbst. Ein Modell ohne FIM wird im Chat gefragt – dann putzt Coder die Antwort: kein Zaun, keine Vorrede, und nichts doppelt, was hinter dem Cursor schon steht
- **Zum Ergänzen wird nie ein Modell geladen.** Ohne eigene Angabe nimmt Coder das Hauptmodell, aber nur, wenn es ohnehin im Speicher liegt. Unter *Einstellungen → Ergänzen & Cowork* lässt sich ein kleines, schnelles Modell dafür eintragen (etwa `qwen2.5-coder:1.5b`) – das wird bei Bedarf geladen
- Solange der Agent arbeitet, ergänzt niemand nebenher: Die Anfrage stünde hinter seiner in der Warteschlange und käme zu spät. In der Kopfzeile der Datei steht dann, warum es gerade still ist
- Abschalten geht in den Einstellungen; die Liste beim Tippen bleibt davon unberührt

**Freigabe – andere an Coder lassen** (Personen-Symbol in der Seitenleiste)
- Über **VS Code**: unten das Panel *Ports* öffnen, *Port weiterleiten* und den Port von Coder eintragen (Standard `8765`). Rechtsklick → *Port-Sichtbarkeit* → *Öffentlich*: Bei *Privat* kommt nur dein eigenes GitHub-Konto durch. Coder selbst bleibt auf `127.0.0.1` – der Tunnel kommt von innen, keine Firewall-Regel nötig. Die Weiterleitung endet, wenn VS Code zugeht
- Jeder bekommt ein **eigenes Konto** als Einladung: Name und Rolle eintragen, den Link schicken – wer ihn öffnet, legt sein eigenes Passwort fest. Du kennst es nie; der Link gilt sieben Tage und nur einmal. *Neuer Link* setzt ein vergessenes Passwort zurück
- **Rollen**: *Nur Chat* (der Tab Chat, sonst nichts), *Lesen* (dazu Code-Chats in den Modi Chat und Planen, Dateien nur ansehen), *Mitarbeiten* (dazu Dateien ändern und Befehle nach Freigabe – auf diesem Rechner, aber nie *Autonom*), *Verwalten* (alles). *Ich selbst, unterwegs* ist dein eigenes Konto fürs Handy: dieselben Chats, dasselbe Gedächtnis
- Jeder sieht nur seine eigenen Chats. Gäste arbeiten im Workspace – oder in einem eigenen Ordner, den du ihnen gibst –, sehen dein Gedächtnis nicht, keine Einstellungen, keine Ordner außerhalb, keine Modelle zum Laden, kein Cowork und kein Mikrofon. Das prüft der Server, nicht nur die Oberfläche
- Wer gerade da ist, zeigt das Abzeichen am Knopf – live. Die weitergeleitete Adresse merkt sich Coder, sobald jemand darüber kommt; die Einladungslinks tragen sie dann schon
- Die Anfragen im LAN (`--host 0.0.0.0`) laufen genauso: Wer nicht an diesem Rechner sitzt, meldet sich an

**Kontext** – der Ring neben der Eingabe
- Er zeigt, wie voll das Kontextfenster ist. Ein Klick darauf öffnet die Aufteilung: *Auftrag* (Systemprompt, Projektanweisungen, Notizen aus dem Gedächtnis), *Werkzeuge*, *Verlauf*, *Ausgaben* der Werkzeuge und *Frei* – als Balken und als Liste mit Zahlen
- Darunter steht, was diese Sitzung bisher gekostet hat – Prompt, Antwort, Anfragen – und ein Knopf **Verlauf verdichten**. Von allein kürzt Coder Werkzeugausgaben ab 60 % und verdichtet den Verlauf ab 80 %

**Während der Arbeit schreiben**
- Drückst du `Enter`, während der Agent arbeitet, wartet die Nachricht über der Eingabe. Der Agent liest sie vor seinem nächsten Schritt – so lassen sich Wünsche nachschieben, ohne zu stoppen
- Mit × ziehst du sie zurück. Stoppst du den Agent, kommen wartende Nachrichten zurück in die Eingabe

**Neu laden, ohne abzubrechen**
- Ein laufender Auftrag gehört dem Chat, nicht dem Fenster: Lädt die Oberfläche neu, reißt die Verbindung kurz ab (Handy im LAN, Bildschirm aus) oder schließt du den Tab, arbeitet der Agent weiter
- Öffnest du den Chat wieder, siehst du ihn laufen – mit allem, was bisher geschah, der Zeit seit dem Auftrag und einer offenen Freigabe oder Rückfrage, die noch auf dich wartet. Ab da geht es live weiter
- In der Chatliste steht bei jedem Chat, der gerade im Hintergrund arbeitet, **arbeitet**
- Wartet eine Freigabe und kein Fenster sieht zu, gilt sie nach 15 Minuten als abgelehnt – ein vergessener Tab hält weder die Grafikkarte noch den Rechner endlos wach

**Cowork – mehrere Aufträge gleichzeitig** (`Strg+J`, Knopf in der Seitenleiste)
- Ein Brett für Aufträge, die nebeneinander laufen: aufschreiben, abschicken, weiterarbeiten. Zwei laufen gleichzeitig, der Rest wartet – bis vier lassen sich einstellen, mehr teilen sich auf einer Grafikkarte nur gegenseitig auf
- Jeder Auftrag legt vorher fest, was er darf: *Nur lesen und planen*, *Dateien ändern* (Befehle sind dann nicht verfügbar) oder *Alles, auch Befehle*. Am Brett sitzt niemand, der eine Freigabe erteilt – deshalb steht das vorher fest, und der Agent weiß es auch
- Auf Wunsch übernimmt ein Agent den Auftrag – `@bug-checker`, `@test-writer`, was installiert ist
- Jede Zeile zeigt, woran gerade gearbeitet wird, wie lange schon, wie viele Schritte und wie viele Dateien sich geändert haben. Aufgeklappt stehen die Schritte darunter, die Antwort und die geänderten Dateien
- Jeder Auftrag bekommt einen **eigenen Chat und eine eigene Sicherung**: **Im Chat öffnen** holt ihn ins Fenster und führt ihn dort weiter, **Rückgängig** nimmt genau seine Änderungen zurück, **Noch einmal** stellt ihn neu
- Das Brett gehört dem Server, nicht dem Fenster: Aufträge laufen weiter, wenn die Oberfläche neu lädt, und jedes offene Fenster sieht dasselbe. Am Knopf in der Seitenleiste steht, wie viele noch offen sind
- Rückfragen stellt hier niemand. Der Agent entscheidet selbst und schreibt in seine Antwort, was er angenommen hat
- Versucht ein Modell trotzdem etwas, das eine Freigabe bräuchte, wird nur dieser Schritt übersprungen – der Auftrag läuft weiter, und in der Antwort steht, was noch zu tun bleibt

**Kontrolle** – ein zweites Modell schaut dem Agent über die Schulter
- Nach jeder Aufgabe, bei der Dateien geändert oder Befehle ausgeführt wurden, prüft ein Kontrollmodell selbst nach: Es liest die Dateien, lässt Tests laufen und fällt ein Urteil
- Fehlt etwas, schickt es den Agent mit einer konkreten Anweisung weiter – höchstens so oft wie eingestellt (Standard: 2 Nachbesserungen)
- Bei langen Aufgaben sieht es zwischendurch nach dem Rechten (Standard: alle 10 Minuten) und hilft, wenn Aufrufe mehrmals hintereinander scheitern
- Standardmodell: **Mistral** (`mistral-nemo`, `mistral-small` …), falls installiert – sonst das Hauptmodell. Einstellbar unter *Einstellungen → Kontrolle* oder mit `/controller`
- Die Kontrolle arbeitet nur lesend und sieht auch Nachrichten, die du während der Arbeit nachgeschoben hast; für Befehle fragt sie wie jeder Agent um Freigabe

**Watchdog**
- Kommt länger nichts vom Modell (Standard: 3 Minuten), prüft Coder, ob die GPU noch rechnet und das Modell noch geladen ist. Hängt es wirklich, wird es entladen und neu geladen – bis zu zweimal
- Verfängt sich ein Modell in Endloswiederholungen, bricht Coder die Antwort ab und hakt nach

**Bilderkennung**
- Bilder hängen per Knopf, `Strg+V` oder Hineinziehen an der Nachricht (im Terminal: Bild ins Fenster ziehen oder `/image pfad`)
- Kann das Hauptmodell selbst sehen (z. B. `gemma4`, `gemma3`), bekommt es das Bild direkt. Sonst beschreibt ein Bildmodell das Bild vorher – samt aller sichtbaren Texte und Fehlermeldungen
- `view_image` lässt den Agent Screenshots und Diagramme im Workspace ansehen

**Bilder erzeugen**
- Ollama malt nicht. Coder spricht dafür mit dem Bilddienst, der auf deinem Rechner ohnehin dafür da ist: **ComfyUI** (Port 8188) oder eine **Stable-Diffusion-WebUI** – Automatic1111, Forge, reForge, SD.Next (Port 7860 oder 7801, gestartet mit `--api`)
- Gefunden wird er von allein. Läuft keiner, bekommt der Agent das Werkzeug gar nicht erst zu sehen und verspricht auch nichts
- **Noch keiner da?** Unter *Einstellungen → Bilder erzeugen* steht dann die Anleitung: Coder sucht zuerst auf der Platte nach einem Ordner, der schon da ist – dann muss man ihn nur starten – und zeigt sonst die Schritte mit Befehlen zum Kopieren. Heruntergeladen wird nichts von allein
- `generate_image` legt das Bild im Workspace ab – App-Icons, Logos, Texturen, Platzhalter, Hintergründe, Open-Graph-Bilder. Unter der Antwort steht es als Vorschau, mit Pfad, Seed und Modell; ein Klick zeigt es groß
- Mit `reference` wird ein vorhandenes Bild als Vorlage umgemalt (img2img), `strength` sagt, wie stark
- Zielformat nach Endung: `.png`, `.jpg`, `.webp` und `.ico` fürs Favicon (Umwandlung braucht Pillow)
- Bei ComfyUI baut Coder den Graphen selbst – es braucht keinen vorbereiteten Workflow, nur ein Checkpoint-Modell
- `/imagine <Beschreibung>` erzeugt eins direkt. Erzeugte Bilder lassen sich mit **Rückgängig** wieder entfernen
- Adresse, Modell, Größe und Rechenschritte stehen unter *Einstellungen → Bilder erzeugen*; dort steht auch, was gerade gefunden wurde

**Drei Designs**
- **Ruhig** (Standard): weiche Flächen, geräumige Typografie, blauer Akzent – ausgewogen für den Alltag
- **Terminal**: alles Monospace, keine Radien, Haarlinien statt Schatten, dichter Satz, Versal-Labels. Der Auftrag steht links hinter einem `>` wie ein wiederholter Befehl, die Eingabe hat denselben Prompt samt Blockcursor – der Chat liest sich als Sitzungsprotokoll
- **Papier**: getöntes Papier, Serife für Fließtext, mehr Durchschuss, schmalere Spalte, Überschriften als Versal-Labels. Für lange Erklärungen, die man wirklich liest; die Bedienelemente bleiben sachlich
- Alle drei benutzen dieselben Bausteine und gelten in jeder Ansicht – Chat, Modelle, Agents, Gedächtnis, Palette, Freigaben
- **Hell oder dunkel** steht daneben: *Automatisch* folgt dem System, sonst legst du es fest. Gilt auch fürs App-Fenster samt Rahmen
- **Farbthemen** legen bekannte Editor-Paletten über jedes Design, je hell und dunkel: Nord, Solarized, Gruvbox, GitHub, Catppuccin, Tokyo Night, Rosé Pine, **OLED** (im Dunkeln echtes Schwarz – auf OLED-Displays bleiben die Pixel aus), **Hoher Kontrast** (kräftige Kanten) und **Farbenblind** (Erfolg blau, Fehler orange nach Okabe-Ito). *Standard* lässt jedem Design seine eigenen Farben. Alle erfüllen dieselben Kontraste wie die Designs (Text 4,5:1) – wo das Original zu blass ist, ist nur die Helligkeit nachgezogen
- Umgestellt wird unter *Einstellungen → Aussehen* – die Vorschau läuft beim Auswählen mit, Abbrechen nimmt sie zurück. In der Palette `Strg+K` schalten „Design wechseln“ und „Farbthema wechseln“ reihum durch

**Schleife** – denselben Auftrag wieder und wieder
- `/loop 5m npm test und behebe, was rot ist` – alle 5 Minuten, bis du stoppst
- `/loop 3x /review` – dreimal hintereinander, der Befehl wird dabei wie beim Senden ausgeschrieben; `/loop <auftrag>` läuft bis zu fünf Runden
- Ein Abstand braucht seine Einheit (`30s`, `5m`, `2h`): `/loop 3 Fehler beheben` ist ein Auftrag, kein „alle 3 Sekunden“
- Ab der zweiten Runde weiß der Agent, dass er in einer Schleife läuft: Er sieht nach, was noch offen ist. Findet er nichts mehr, antwortet er `LOOP-ENDE` und Coder hört auf
- Über der Eingabe steht, in welcher Runde die Schleife ist; **Schleife beenden**, `/loop stop` oder `Strg+C` im Terminal machen Schluss

**Prompt schärfen** (Prepromter)
- Der Knopf **Schärfen** neben der Eingabe (im Terminal `/prompt <auftrag>`) macht aus einem hingeworfenen Satz einen genauen Auftrag: was sich ändern soll, wo es steht, woran man merkt, dass es läuft
- Geht es um ein Bild, kommt stattdessen ein englischer Bildprompt heraus – genau das, womit Stable Diffusion gut umgehen kann
- Das Ergebnis landet in der Eingabe, nicht beim Modell: Du liest es, änderst es und schickst es ab. Von allein ändert Coder nie, was du geschrieben hast
- Abschalten unter *Einstellungen → Aufträge & Bericht*

**Bericht zum Ausdrucken**
- `/print` (im Terminal `/print [datei]`) baut aus dem Chat eine einzelne HTML-Datei: Aufträge, Schritte, Diffs, erzeugte Bilder, geänderte Dateien – und ein Feld für Anmerkungen samt Unterschriften
- Gedacht für eine Abgabe oder ein Gespräch mit einem Prüfer: A4, schwarz auf weiß, Bilder eingebettet. Im Browser öffnen und mit `Strg+P` drucken
- Berichte liegen unter `~/.coder/reports`; der Name im Kopf kommt aus *Einstellungen → Aufträge & Bericht* – ohne Namen bleibt dort eine Linie zum Ausfüllen

**Gedächtnis** – verknüpfte Markdown-Notizen wie in Obsidian
- Tresore: Projekt (`.coder/memory`), global (`~/.coder/memory`) und die schreibgeschützte **Bibliothek** mit Leitfäden, die mit Coder kommt
- Passende Notizen werden automatisch zur Nachricht geholt – nach Bedeutung, wenn ein Embedding-Modell wie `nomic-embed-text` installiert ist, sonst nach Stichworten
- Ist der Grafikspeicher voll, rechnet das Embedding-Modell auf der CPU, statt das Chat-Modell aus dem VRAM zu drängen. Ein großer, neuer Tresor wird im Hintergrund fertig eingelesen
- Erledigte Aufgaben landen in der Notiz „Verlauf“ – so weiß Coder auch im nächsten Chat, was schon passiert ist
- `[[Titel]]` in einer Nachricht holt eine Notiz dazu; Tags, Backlinks, angeheftete Notizen
- Checklisten (`- [ ]` und `- [x]`) werden als Kästchen dargestellt – in Notizen wie in Antworten
- **Graph**: Mausrad zoomt, Ziehen verschiebt, Doppelklick oder `0` passt alles ein, `+`/`−` auch per Taste. Namen, die sich überdecken würden, warten, bis man heranzoomt oder auf ihren Punkt zeigt; Linien laufen unter der Schrift durch, nicht durch sie hindurch. Die Legende ist ein Filter – etwa „Bibliothek“ ausblenden, gemerkt fürs nächste Mal. Die zuletzt gelesene Notiz ist markiert
- Im Chat steht bei „Notiz gelesen“ und „Notiz gespeichert“ der Titel samt Link: ein Klick öffnet die Notiz im Gedächtnis
- Im Terminal: `/memory` zeigt alle Notizen mit Auszug, `/memory Titel` eine ganze Notiz, `/memory suche` findet nach Bedeutung

**Design-Bibliothek**
- Leitfäden zu Design-Prinzipien, Typografie, Farbe, Layout, Komponenten, Bewegung, Barrierefreiheit, Design-Tokens, einer Review-Checkliste – und „Kein AI-Slop“: woran man generische KI-Oberflächen erkennt und was man stattdessen macht
- `@ui-designer` und `/design` arbeiten danach; eine Kopie ins eigene Gedächtnis lässt sich anpassen

**Recherche**
- `web_research` sucht mit mehreren Suchanfragen parallel, liest die besten Seiten und liefert die passendsten Abschnitte mit nummerierten Quellen
- Websuche über DuckDuckGo ohne API-Schlüssel, mit Bing als Ausweich; gelesene Seiten bleiben 15 Minuten zwischengespeichert

**Agents**
- Coder gibt Teilaufgaben an Sub-Agents ab. Sie arbeiten mit eigenem Kontext und liefern einen Bericht; ihre Schritte erscheinen eingerückt im Chat
- Eingebaut: `@explorer`, `@planer`, `@bug-checker`, `@fix-it`, `@test-runner`, `@test-writer`, `@refactorer`, `@security-check`, `@perf-check`, `@ui-designer`, `@doku-writer`, `@commit-writer`, `@recherche`
- `@name` am Anfang einer Nachricht lässt einen Agent den ganzen Auftrag übernehmen
- Eigene Agents im Agents-Fenster oder als Markdown in `~/.coder/agents` bzw. `.coder/agents`; Agents aus Claude Code (`~/.claude/agents`) werden übernommen
- **Jeder Agent darf sein eigenes Modell haben**: ein kleines, schnelles fürs Suchen, ein großes fürs Prüfen. Im Agents-Fenster steht die Auswahl unter *Modell*, in der Datei als `model: qwen3:0.6b` im Frontmatter. Ohne Angabe arbeitet er mit dem Modell des Hauptagenten
- Das eigene Modell lädt wie ein Hilfsmodell: mit kleinerem Kontext, und ein großes Hauptmodell bleibt dabei im Speicher liegen. In der Agent-Liste steht es als Marke, im Chat rechts an seinem Schritt (`3 Schritte · 12 s · qwen3:0.6b`), im Terminal am Ergebnis und im Bericht zum Ausdrucken
- Ist das Modell auf diesem Rechner nicht installiert, sagt Coder es einmal und arbeitet mit dem Hauptmodell weiter – auch `model: sonnet` aus einer Claude-Code-Definition hält so niemanden auf

**Einstellungen** (`Strg+,`)
- Links die Bereiche *Persönlich*, *Modelle*, *Agent & Kontrolle*, *Gedächtnis*, *Aussehen*, *Eingabe & Editor*, *Bilder & System* – beim Scrollen leuchtet der, in dem du gerade bist. Auf dem Handy liegt die Leiste quer über dem Inhalt
- **Suche** oben rechts: „farb“ zeigt nur noch Farbthema und Terminalfarben, auch Werte aus den Auswahllisten werden gefunden. `Esc` leert erst die Suche, dann schließt es
- Sichern bleibt unten stehen (`Strg+S`). Ungesicherte Änderungen stehen daneben; wer mit ihnen schließt, wird gefragt – lange Anweisungen gehen nicht mit einem Klick daneben verloren
- Gäste sehen nur *Persönlich* und *Aussehen*
- Ein Wert, den eine Auswahl nicht anbietet (etwa 20 Rechenschritte aus `config.json`), steht als „eigener Wert“ darin, statt leer zu erscheinen und beim Sichern zu 0 zu werden

**Befehle**
- Fertige Aufgaben: `/init`, `/review`, `/test`, `/write-tests`, `/fix`, `/explain`, `/plan`, `/refactor`, `/security`, `/perf`, `/design`, `/docs`, `/commit`, `/research`, `/imagine`, `/remember`
- Für den Tab *Chat* (und beide): `/mail`, `/compare`, `/tldr`, `/translate`
- App: `/new`, `/compact`, `/undo`, `/agents`, `/prompts`, `/anweisungen`, `/stil`, `/memory`, `/workspace`, `/models`, `/settings`, `/print`
- Eigene Befehle – siehe *Eigene Prompts* oben – als Markdown in `~/.coder/commands` oder `.coder/commands` (auch `~/.claude/commands`); `$ARGUMENTS` wird durch den Text nach dem Befehl ersetzt. Gleichnamige eigene Befehle ersetzen die eingebauten
- Unter jeder eigenen Nachricht (beim Überfahren): *Kopieren*, *In die Eingabe*, *Als Prompt*
- In der Befehlspalette (`Strg+K`) außerdem: letzte Änderungen zurücknehmen, Chat als Markdown kopieren. Jede Antwort lässt sich unter ihren Messwerten kopieren

**Terminal** (`python coder.py cli` oder `start_cmd.bat`)
- **Wie Claude Code**: Begrüßung im Kasten, die Eingabe steht zwischen zwei Linien, darunter die Fußzeile mit dem Modus (`⏵⏵ Auto-Edit an`, `⏸ Planen an`, `◇ Chat`), rechts Aufwand, Bilder und Kontext ab 50 %. `Umschalt+Tab` wechselt den Modus – auch während der Agent arbeitet –, `?` zeigt die Tastenkürzel. Nach Enter bleibt nur `› Text` stehen
- **Auswahl statt Tippen**: Freigaben, Rückfragen und „Plan umsetzen?“ sind Listen wie in Claude Code – `› 1. Ja`, Beschreibung darunter, `↑`/`↓` und `Enter`, Ziffern direkt. Bei Freigaben gehen auch `j`, `i` (immer) und `n`
- **Antworten wie gesetzt**: Markdown erscheint Wort für Wort und bricht am Fensterrand zwischen Wörtern um, mit hängendem Einzug unter Aufzählungen. Fett, Code und Links sind sofort richtig, Tabellen stehen in Spalten, Codeblöcke haben einen Rahmen und – wenn Pygments installiert ist – Syntaxfarben
- Werkzeugaufrufe, die ein Modell als Text schreibt (`<function=…>`, JSON), laufen, stehen aber nicht im Terminal
- Schritte als `● Lesen app.py` mit Ergebnis darunter; Diffs mit Zeilennummern, − rot, + grün. Am Ende eines Auftrags: Schritte, Zeit, Token und Geschwindigkeit in einer Zeile
- **Eingabe** (Windows-Konsole): `Tab` vervollständigt `/Befehle`, `@Agents`, `[[Notizen]]`, Modelle und Pfade – beim Tippen von `/`, `@` oder `[[` zeigt eine Liste darunter, was passt. `↑`/`↓` blättern im Verlauf (bleibt über Neustarts), `Umschalt+Enter` macht eine neue Zeile, eingefügter Text mit Zeilenumbrüchen bleibt eine Nachricht, `Esc` leert die Zeile. Anderswo übernimmt die Zeile des Systems – mit readline-Vervollständigung, wo es sie gibt
- **Die Eingabe bleibt stehen** – auch während der Agent arbeitet. Unten im Fenster steht durchgehend der Rahmen mit deiner Zeile, darüber die Statuszeile (woran er gerade ist, wie lange schon, `Esc` stoppt), darunter die Fußzeile mit dem Modus. Die Ausgabe läuft darüber weiter
- **Während der Arbeit schreiben**: einfach weitertippen – der Text steht in der Eingabe, `Enter` reiht ihn ein („wartet: …“), der Agent liest ihn vor seinem nächsten Schritt. `Esc` leert die Zeile, angefangener Text steht nach dem Auftrag wieder da. Bei langen Nachrichten bleiben die letzten drei Zeilen sichtbar; in einem sehr flachen Fenster bleibt es bei der Statuszeile allein
- **Stoppen**: `Esc` oder `Strg+C` bricht die laufende Aufgabe ab (samt laufendem Befehl), zweimal `Strg+C` auf leerer Zeile beendet Coder. Auch wenn Coder aus einer Umgebung gestartet wurde, die Strg+C sonst verschluckt
- **Nichts aus Versehen**: Tasten, die kommen, während eine Freigabe oder Frage gerade erscheint und du noch tippst, zählen nicht – sie landen in deiner nächsten Nachricht. Nach der ersten bewussten Taste geht alles sofort, auch `↓` und gleich `Enter`
- Befehle, gegliedert unter `/help`: `/new`, `/resume`, `/retry`, `/compact`, `/diff`, `/undo`, `/todo`, `/loop`, `/prompt`, `/print`, `/commands`, `/agents`, `/memory`, `/image`, `/paste`, `/imagine`, `/open`, `/model`, `/mode`, `/effort`, `/anweisungen`, `/stil`, `/theme`, `/workspace`, `/controller`, `/think`, `/status`, `/buddy`, `/exit` – dazu alle fertigen Befehle wie `/review`. `/prompt` bietet nach dem Schärfen „bearbeiten“ an: der Text steht dann fertig in der Eingabe
- `/mode` versteht `chat`, `normal`, `auto`, `planen`, `autonom`; `/effort` `niedrig`, `mittel`, `hoch`, `max`
- `/anweisungen` zeigt deine eigenen Anweisungen; `/anweisungen text` setzt sie, `/anweisungen + text` hängt eine Zeile an, `/anweisungen code …` gilt nur fürs Projekt, `/anweisungen leeren` löscht. `/stil knapp` (oder `ausführlich`, `erklärend`, `förmlich`, `normal`) – dieselben Werte wie in der App
- **Farben** mit `/theme`: *Dunkel* (Standard), *Hell* für helle Terminals, *Farbenblind* hell und dunkel (Blau statt Grün, Orange statt Rot – auch in Diffs), *Schlicht* ohne Farben. *Automatisch* nimmt Hell, wenn das Terminal hellen Grund meldet (`COLORFGBG`); `CODER_THEME=hell` erzwingt es
- **Alte Konsole**: In Windows Terminal, VS Code & Co. nutzt Coder Symbole wie ⎿ ✦ ◆. Die klassische Konsole (`cmd.exe` mit Consolas) kann sie nicht zeichnen – dort nimmt Coder automatisch Zeichen, die Consolas hat (└ ◊ ♦ √). Erzwingen lässt es sich mit `CODER_GLYPHS=basic` bzw. `unicode`, `NO_COLOR=1` schaltet Farben ab
- **Axolotl:** Ein kleines Axolotl wohnt im Terminal – gezeichnet aus Zeichen, die jede Konsole hat, 16 Spalten breit, damit nichts verrutscht. Beim Arbeiten wippen die Kiemen, zwischendurch blinzelt es, und jede Lage hat ihr Gesicht: denken, fragen, stolz, müde. In der Statuszeile steht dieselbe Figur als Miniatur
- Es kommentiert Tests, Fehler, das Urteil der Kontrolle, Verdichten und Rückgängig – nie zweimal hintereinander mit demselben Spruch, und nach einem langen Lauf anders als nach einem kurzen. Beim Abbruch sagt es nichts: da soll klar dastehen, was passiert ist. `/buddy` zeigt es, `/buddy streicheln` (wer es oft streichelt, hört andere Sätze), `/buddy name Pixel`, `/buddy aus`

**Freigaben**
- Welche Aktionen fragen, legt der Modus fest (siehe oben). „Immer erlauben“ gilt bei Befehlen nur für Programm und Unterbefehl, etwa `npm test` oder `python -m pytest`, und nur in diesem Chat. Verkettete Befehle und alles, womit sich beliebiger Code ausführen oder Daten löschen lassen (`rm`, `curl`, `python -c`, Shells), fragen jedes Mal

**Workspace**
- Ordner wählen über die Workspace-Karte, den Ordner-Chip in der Eingabe oder `Strg+O`: Systemdialog, zuletzt verwendete Ordner oder direkt durchsuchen
- Jeder Chat bleibt an seinen Ordner gebunden; Systemordner und ganze Laufwerke sind gesperrt
- Links im App-Fenster – auch zu einem Dev-Server auf `localhost` – öffnen im Browser, die Oberfläche bleibt stehen

**PC wach halten** (*Einstellungen → Bilder & System*)
- Standard: kein Standby, **solange Coder offen ist**. Alternativ nur, während der Agent arbeitet, oder nie
- Der Bildschirm darf trotzdem ausgehen. Coder ändert keine Energieeinstellungen – die Anforderung endet spätestens mit Coder

**vLLM statt Ollama – mit denselben Modelldateien** (*Einstellungen → Modell-Server*)
- Ollama ist bequem, **vLLM** ist schnell: Es hält das Modell dauerhaft im VRAM und bedient mehrere Anfragen gleichzeitig. Coder spricht beides; umgestellt wird mit einem Klick
- **Kein zweiter Download.** Coder liest Ollamas Manifeste direkt von der Platte und weiß, welche GGUF-Datei zu `qwen2.5-coder:14b` gehört. Daraus baut es den fertigen Startbefehl – mit Pfad, Namen und Kontextlänge, zum Kopieren
- Unter Windows läuft vLLM nicht von allein: Es braucht Linux mit CUDA, also **WSL 2** oder **Docker** mit GPU-Durchgriff. Die Einstellungen zeigen beide Wege Schritt für Schritt. Gestartet wird nichts von allein
- Läuft eines, findet Coder es auf Port 8000 oder 8001 – oder unter der Adresse, die du einträgst. Danach arbeitet alles wie gewohnt: Werkzeuge, Diffs, Freigaben, Rückfragen, Denkmodus
- Was vLLM nicht kann, sagt Coder: Embeddings etwa bietet nicht jeder Server an – dann sucht das Gedächtnis nach Stichworten statt nach Bedeutung

**Optimiertes Laden für Ollama**
- Erkennt GPU, VRAM, RAM und CPU-Kerne, liest die Modellarchitektur und wählt `num_ctx` so, dass Gewichte und KV-Cache in den VRAM passen
- Entlädt andere Modelle vor dem Laden und misst danach die echte GPU-Verteilung; Kontroll- und Bildmodelle laden mit kleinerem Kontext, danach wird das Hauptmodell im Hintergrund wieder bereitgelegt

**Große Modelle: 30B, 70B, 120B**
- Passt ein Modell nicht in den VRAM, rechnet Coder mit: GPU, freier Arbeitsspeicher und – wenn beides nicht reicht – die Platte. In der Modell-Liste steht, was gilt: *Passt komplett in die GPU*, *GPU und Arbeitsspeicher*, *Läuft auf der CPU* oder *Zu groß – liest von der Platte*
- Dazu eine grobe Tempo-Schätzung in Token/s. Sie rechnet mit den **aktiven** Parametern: `gpt-oss:120b` nutzt je Token nur rund 5 seiner 117 Milliarden (Mixture-of-Experts) und bleibt dadurch benutzbar, während ein dichtes 70B-Modell bei gleichem Speicher zäh wird. In der Liste steht bei MoE-Modellen, wie viel davon aktiv ist
- Empfohlen wird nach Tempo statt nach Größe: Was ständig von der Platte nachgelesen wird, fällt ans Ende der Liste – auf einem Rechner mit viel RAM rückt dasselbe Modell nach vorn
- Reicht es nicht, sagt Coder es in Gigabyte – und was helfen würde: *„67,7 GB nötig, frei sind 27,0 GB (10,9 GB VRAM + 16,1 GB RAM) … mit rund 40,6 GB mehr Arbeitsspeicher wären es etwa 12,3 Token/s“*
- Beim ersten Auftrag mit einem langsamen Modell steht einmal im Chat, was dich erwartet
- Ein großes Hauptmodell wird nicht mehr für Hilfsmodelle verdrängt: Die Kontrolle läuft dann auf demselben Modell, und das Nachladen von Minuten entfällt
- Der Watchdog hält CPU-Rechnen nicht mehr für einen Hänger: Läuft ein Modell großteils außerhalb der GPU, zählt deren Ruhe nicht als Beweis – nur die harte Obergrenze greift noch
- Stabiler System-Prompt für den Prompt-Cache; alte Werkzeugausgaben ab 60 % kürzen, ab 80 % den Verlauf verdichten
- Mehr Kontext bei gleichem VRAM – einmalig für den Ollama-Server setzen und Ollama neu starten:

```bash
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

## Tastenkürzel

| Taste | Aktion |
| --- | --- |
| `Enter` / `Shift+Enter` | Senden – während der Arbeit: Nachricht für den nächsten Schritt einreihen / neue Zeile |
| `Strg+K` | Befehlspalette: Aktionen, Befehle, Agents, Notizen, Chats |
| `Esc` | Rückfrage überspringen, Freigabe ablehnen, Agent stoppen, Dialog schließen |
| `1` … `9` | Antwort auf eine Rückfrage wählen |
| `Strg+N` | Neuer Chat |
| `Strg+O` | Workspace wählen |
| `Strg+E` | Editor – und wieder zurück |
| `Strg+P` | Datei öffnen (im Editor), `:42` springt zu Zeile 42 |
| `Strg+Umschalt+F` | In allen Dateien suchen |
| `Strg+F` / `Strg+H` | In der Datei suchen / ersetzen |
| `Strg+S` | Datei speichern |
| `Strg+Ö` | Terminal im Editor |
| `F5` | Offene Datei ausführen |
| `Strg+/`, `Alt+↑`/`↓` | Zeilen kommentieren, verschieben |
| `Strg+Umschalt+V` | Markdown-Vorschau |
| `Strg+Umschalt+O` | Gehe zu Symbol in der Datei |
| `Strg +` / `Strg -` / `Strg 0` | Schriftgröße im Editor |
| `F2` | Datei oder Chat umbenennen |
| `Strg+J` | Cowork: mehrere Aufträge gleichzeitig |
| `Strg+D` | Diktieren – sprechen statt tippen |
| `Strg+B` | Seitenleiste ein- und ausblenden |
| `Strg+M` | Modelle |
| `Strg+,` | Einstellungen |
| `Strg+S` | In Einstellungen, Prompt- und Agent-Editor: sichern |
| `Strg+Enter` | Freigabe erteilen |
| `Strg+V` | Bild aus der Zwischenablage anhängen |

In der Eingabe: `@` für Agents, `/` für Befehle und Prompts (eigene zuerst), `[[` für Notizen – mit `↑`/`↓` wählen, `Enter` oder `Tab` übernimmt.

## Aufbau

```
coder.py            Start: App-Fenster, Browser, Server oder CLI
core/
  agent.py          Agent-Schleife, Berechtigungen, Watchdog, Kontextverdichtung, Nachrichten während der Arbeit
  checkpoints.py    Rückgängig: Sicherungen je Auftrag
  controller.py     Kontrolle durch ein zweites Modell
  effort.py         Aufwand: Denkmodus, Schrittlimit, Kontrolle und Arbeitsweise je Stufe
  personal.py       eigene Anweisungen (User-Prompt) und Antwortstil
  tools.py          Werkzeuge
  web.py            Websuche, Seitenabruf, Recherche
  vision.py         Bilder speichern und für Vision-Modelle vorbereiten
  imagegen.py       Bilder erzeugen mit ComfyUI oder einer Stable-Diffusion-WebUI
  memory.py         Gedächtnis: Notizen, Links, Tresore
  recall.py         Erinnern nach Bedeutung, Verlauf
  agents.py         Sub-Agents: eingebaute, eigene und aus Claude Code
  cowork.py         Cowork-Brett: mehrere Aufträge gleichzeitig, jeder mit eigenem Chat
  complete.py       Ergänzen in der Dateiansicht: der Vorschlag hinter dem Cursor (FIM)
  commands.py       fertige und eigene Slash-Befehle („Prompts“): laden, anlegen, löschen, Tab je Prompt
  folders.py        Ordnerauswahl: Durchsuchen, Orte, Systemdialog
  ollama.py         async Ollama-Client (Streaming, Embeddings)
  optimizer.py      Hardware-Erkennung, Ladeplan über GPU/RAM/Platte, Tempo-Schätzung, Modell-Ranking
  runtime.py        Laden, Messen, Rollen (Kontrolle, Bilder, Embeddings)
  power.py          PC wach halten
  sessions.py       Chats unter ~/.coder/sessions – mit Besitzer und Art (Code oder Chat-Tab)
  users.py          Konten, Rollen, Einladungen, Anmeldung – für die Freigabe
  config.py         Einstellungen unter ~/.coder/config.json
  cli.py            Terminal-Modus: Ereignisse, Befehle, Statuszeile
  termmd.py         Markdown fürs Terminal, Stück für Stück – und der Filter für Aufrufe im Text
  lineedit.py       Eingabezeile: Vervollständigen, Verlauf, Tippen während der Arbeit
  term.py           Farben, Zeichensätze (moderne und alte Konsole), Breiten
  companion.py      das Axolotl fürs Terminal
  speech.py         Diktat: aufnehmen und mit Whisper erkennen – alles auf diesem Rechner
  vllm.py           vLLM als Modell-Server, mit den GGUF-Dateien von Ollama
  loop.py           Schleife: denselben Auftrag wiederholen
  preprompt.py      Prompt schärfen – Auftrag oder Bildprompt
  report.py         Bericht zum Ausdrucken (A4, alles eingebettet)
library/            Design-Bibliothek (schreibgeschützter Tresor)
server/app.py       FastAPI + WebSocket, Tunnel-Erkennung, Rechte je Rolle, Terminal des Editors
web/                Oberfläche (HTML, CSS, JS – ohne Build, ohne CDN), login.html für Gäste
tests/
  run.py            Läufer: python coder.py test
  sandbox.py        eigener Spielplatz je Reihe (Temp statt ~/.coder)
  fakes.py          ComfyUI und Stable-Diffusion-WebUI nachgebaut
  fake_ollama.py    Ollama nachgebaut, mit vorgegebenen Zügen
  fake_vllm.py      vLLM nachgebaut: OpenAI-Format, Aufrufe in Bruchstücken
  conpty.py         unsichtbare Windows-Konsole für Tests mit echten Tasten
  serve.py          Oberfläche ohne Modell starten und anschauen
```

## So funktioniert der Server

Alles, was die Oberfläche kann, läuft über einen einzigen Server: `server/app.py`, eine FastAPI-App unter uvicorn.
App-Fenster, Browser und das Handy über die Freigabe sind nur verschiedene Fenster auf denselben Server – sie sehen
dieselben Chats, dieselben laufenden Aufträge und dasselbe Cowork-Brett. Nur der Terminalmodus (`python coder.py cli`)
braucht ihn nicht: Er ruft den Agent direkt auf.

```
 App-Fenster (PyQt6)   ─┐
 Browser               ─┼─►  LocalGuard  ─►  FastAPI (server/app.py)
 Handy, Gäste (Tunnel) ─┘    wer? darf er?   ├─ /api/…   Dateien, Chats, Modelle, Konten
                                             └─ /ws      Connection ─► Run ─► Agent
                                                                                │
                                Ollama / vLLM  ◄─  Runtime (core/runtime.py)  ◄─┘
```

**Start**
- `python coder.py` nimmt Port `8765` – ist der belegt, einen freien –, startet uvicorn in einem Hintergrund-Thread und wartet, bis der Server antwortet (höchstens 20 Sekunden). Erst dann öffnet sich das Fenster auf `http://127.0.0.1:<port>/`
- `--serve` startet nur den Server, ohne Fenster; `--port 9000` wählt einen anderen Port, `--host 0.0.0.0` macht ihn im LAN erreichbar. Welcher Port es geworden ist, steht bei `--serve` in der Ausgabe – genau den trägt man in VS Code unter *Ports* ein
- `create_app()` baut einmal auf, was allen Fenstern gemeinsam gehört: die **Runtime** (Einstellungen, Verbindung zu Ollama oder vLLM, Laden der Modelle), das **Cowork-Brett**, die **laufenden Aufträge** je Chat und **Share** (wer gerade da ist)
- Beim Beenden bekommt jede offene Freigabe ein Nein und jede Rückfrage ein „übersprungen“, laufende Aufträge brechen ab, Befehle im Editor-Terminal und Hintergrundprozesse des Agenten werden beendet, die Verbindung zum Modell-Server geschlossen

**Der Türsteher: `LocalGuard`**

Jede Anfrage – HTTP wie WebSocket – geht zuerst durch diese Middleware, bevor FastAPI sie überhaupt sieht:

1. **Host prüfen.** Erlaubt sind `127.0.0.1`, `localhost` und `::1`; mit `--host 0.0.0.0` auch IP-Adressen und der Rechnername; hinter einem Tunnel die Adressen der bekannten Dienste (`*.devtunnels.ms`, `*.github.dev`, ngrok, Cloudflare …). Alles andere bekommt 403 – das wehrt DNS-Rebinding ab
2. **Herkunft prüfen.** Ein Browser darf nur von der Coder-Oberfläche selbst kommen (`Origin` passt zu `Host`). WebSockets kennen keine Same-Origin-Regel – ohne diese Prüfung könnte jede offene Webseite Aufträge schicken und Freigaben erteilen
3. **Wer ist das?** Kommt die Anfrage von `127.0.0.1` und ohne `X-Forwarded-*`-Kopfzeilen, sitzt der Besitzer am Rechner: Rolle *Verwalten*, keine Anmeldung. Alle anderen weist das Cookie `coder_auth` aus, nachgeschlagen in `~/.coder/users.json`
4. **Ohne Konto** leiten Seiten auf `/login` um, die API antwortet 401, und ein WebSocket wird angenommen und sofort mit dem Code `4401` geschlossen – daran erkennt die Oberfläche, dass sie zur Anmeldung muss. (Ein Schließen vor dem Annehmen hätte den Handschlag abgelehnt: Der Browser sähe dann nur `1006` und verbände sich endlos neu.) Offen sind nur `/login`, `/api/login`, `/api/invite`, `/api/logout` und `/static/…`
5. Das Ergebnis hängt danach an der Anfrage (`request.state`): `user`, `local` (am Rechner, ohne Tunnel) und `secure` (über https)

Warum die Kopfzeilen zählen und nicht die Adresse: Die Portfreigabe von VS Code liefert jede Anfrage von `127.0.0.1`
aus und schreibt `Host` und `Origin` auf `localhost` um. Für den Server sähe ein Fremder aus wie du am Rechner – nur
`X-Forwarded-*` verrät den Tunnel. Dort schützt deshalb das Cookie: `SameSite=Lax` schickt es bei keiner Anfrage mit,
die eine fremde Seite auslöst.

**Rollen – geprüft bei jeder Anfrage**

Jeder Endpunkt fragt mit `need(request, "<rolle>")` nach der Mindeststufe; wer darunter liegt, bekommt 403. Jede Stufe
enthält die davor: *Nur Chat* → *Lesen* → *Mitarbeiten* → *Verwalten*.

| Bereich | Endpunkte | Mindestens |
| --- | --- | --- |
| Oberfläche, Anmeldung | `GET /`, `/static/…`, `/login`, `/api/login`, `/api/invite`, `/api/logout` | – |
| Zustand | `GET /api/state` (Version, Einstellung, eigene Rolle, Modell-Server, Hardware, geladene Modelle, Chats), `/api/loaded`, `/api/speech` | angemeldet |
| Chats | `GET /api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/{id}` | angemeldet – nur die eigenen |
| Bilder, Berichte | `POST /api/images`, `GET /api/images/{id}`, `GET /api/reports/{name}` | angemeldet – Berichte nur die eigenen |
| Einstellungen | `POST /api/config` | angemeldet – ohne *Verwalten* nur die eigenen Werte: Modus (im Rahmen der Rolle), Aufwand, Aussehen, Antwortstil, eigene Anweisungen |
| Prompts ansehen | `GET /api/commands` | Nur Chat – dann nur die für den Tab Chat, ohne Projekt und `~/.claude` |
| Modelle ansehen | `GET /api/models` | Nur Chat |
| Dateien lesen | `/api/tree`, `/api/file`, `/api/files`, `/api/search`, `/api/raw`, `/api/git`, `/api/git/diff`, `GET /api/agents` | Lesen |
| Dateien ändern | `POST /api/file`, `POST /api/fs`, `POST /api/complete` | Mitarbeiten |
| Verwalten | `/api/users…`, `/api/models/load`, `/api/models/unload`, `/api/memory…`, `/api/folders…`, `POST`/`DELETE /api/agents`, `POST`/`DELETE /api/commands`, `/api/imagegen`, `/api/vllm` | Verwalten |

- Fremde Chats und Berichte beantwortet der Server mit 404, nicht mit 403 – er verrät nicht einmal, dass es sie gibt
- Gäste arbeiten über `UserRuntime`: die Einstellung des Besitzers, darüber ihre eigenen Werte (`users.user_config`), bei jedem Zugriff frisch – eine geänderte Rolle gilt sofort. Das Gedächtnis ist für sie aus, ihr Ordner ist der, den du ihnen gegeben hast; was sie selbst als `workspace` mitschicken, zählt nicht
- Adressen und Namen aus der Einstellung (`ollama_url`, `image_url`, `report_author` …) bekommen Gäste gar nicht erst zu sehen – und die eigenen Anweisungen und den Stil des Besitzers auch nicht: Für sie zählen nur ihre eigenen
- Die Dateien der Oberfläche (`/static/…`) gehen mit `Cache-Control: no-cache` hinaus, `index.html` fragt sie mit der Version an (`app.js?v=1.12.0`). So mischt ein Browser nach einem Update nie alte Skripte mit neuer Seite
- Ordnerdialog des Systems, eigene Adressen für Bilddienst und vLLM prüfen, Mikrofon: nur wer wirklich am Rechner sitzt (`local`) – über einen Tunnel auch du selbst nicht

**Dateien: nur im Workspace**
- Jeder Pfad geht durch `inside()`: Er wird ganz aufgelöst – samt `..` und Verknüpfungen – und muss danach im Workspace liegen, sonst 400
- Lesen bis 2 MB, Binärdateien 415. Beim Speichern schickt der Editor den `mtime` vom Öffnen mit: Hat sich die Datei seither geändert, antwortet der Server 409, statt still zu überschreiben – erst mit `force` gilt der eigene Stand
- Löschen verschiebt nach `~/.coder/trash/<Zeitpunkt>/…`. Bilder für die Vorschau (`/api/raw`) gehen mit `Content-Security-Policy: sandbox` hinaus – ein SVG mit Skript bleibt ein Bild
- Suche in Dateien: höchstens 500 Treffer, Dateien über 1 MB werden übersprungen; die Schnellsuche kennt bis zu 20 000 Dateien. Platte und git laufen in Threads, damit kein anderes Fenster wartet

**Der WebSocket `/ws` – hier arbeitet der Agent**

Jedes Fenster hält genau eine WebSocket-Verbindung. Drei Dinge greifen ineinander:

```
 Fenster A ── Connection ─┐
                          ├── open ──►  Run (je Chat)  ── startet ──►  Agent (core/agent.py)
 Fenster B ── Connection ─┘                  ▲                              │
                                             └──── emit, ask, question ◄────┘
```

- **`Connection`** ist ein Fenster: der offene Chat, die Befehle im Editor-Terminal, ein laufendes Diktat
- **`Run`** gehört dem **Chat**, nicht dem Fenster: die Task des laufenden Auftrags, Nachrichten, die unterwegs dazukommen (`inbox`), offene Freigaben und Rückfragen (je ein Future) und die Fenster, die gerade zusehen (`listeners`). Der Server hält alle Runs nach Chat-ID
- **`Agent`** ist die Schleife aus `core/agent.py`. Vom Server kennt er nur drei Rückrufe: `run.emit` für jeden Schritt, `run.ask` für Freigaben, `run.question` für Rückfragen. `run.emit` schickt jeden Schritt an alle Fenster in `listeners`

Ein Auftrag, Schritt für Schritt:

1. Das Fenster verbindet sich und schickt `open` mit der Chat-ID (oder `new`). Fenster mit *Verwalten* bekommen vorab das Cowork-Brett (`cowork`) und die Anwesenheit (`presence`). Der Server antwortet mit `session` – dem ganzen Chat. Arbeitet der Chat gerade, kommen `busy` und der Stand dazu: Kontextring, Schleife, offene Freigaben und Rückfragen
2. `send` mit dem Text startet den Auftrag als eigene Task. Solange sie läuft, zählt `busy_agents` hoch – das Ergänzen im Editor schweigt dann – und der PC bleibt wach
3. Jeder Schritt geht an **alle** Fenster, die den Chat offen haben: `status`, `assistant_start`, `thinking` und `text` Stück für Stück, `tool_call`, `tool_running`, `tool_result`, `stats`, `context`, `changes` …
4. Braucht der Agent eine Freigabe, schickt der Server `permission` und wartet; das Fenster antwortet mit `permission` und `allow`, `always` oder `deny`. Rückfragen genauso: `question` hin, `answer` zurück
5. Ein `send`, während der Agent arbeitet, landet in der `inbox` (`queued`, höchstens acht). Der Agent liest sie vor seinem nächsten Schritt; was erst nach dem letzten Schritt kommt, wird der nächste Auftrag
6. Am Ende sichert der Server den Chat – in einem Thread, damit ein langer Chat die anderen Fenster nicht anhält – und schickt `done`. `cancel` bricht die Task ab: „Gestoppt.“, und wartende Nachrichten kommen als `queue_dropped` zurück in die Eingabe

**Fenster weg, Auftrag bleibt**
- Schließt sich das Fenster oder reißt die Verbindung, gibt `Connection.shutdown()` nur frei, was am Fenster hängt: Befehle im Terminal, Mikrofon, die Leitung. Der Run arbeitet weiter
- Die Oberfläche verbindet sich von selbst neu – nach 0,8 Sekunden, dann in wachsenden Abständen bis 8 Sekunden – und schickt wieder `open`. Damit hängt sie sich an den laufenden Auftrag
- Unterwegs sichert der Server den Chat nach jedem Werkzeugergebnis und jeder Modellantwort (`autosave`) – ein Absturz kostet nicht den ganzen Verlauf
- Wartet eine Freigabe oder Rückfrage und sieht niemand zu, gilt sie nach 15 Minuten als abgelehnt. Ein Inkognito-Chat bleibt nach einer gerissenen Verbindung 120 Sekunden im Speicher, dann ist er weg

**Nachrichten über den WebSocket**

Vom Fenster an den Server:

| Nachricht | Wirkung |
| --- | --- |
| `open`, `new` | Chat öffnen oder neu anlegen – `kind` ist `code` oder `talk` (Tab Chat), dazu `incognito` |
| `send` | Auftrag schicken – während der Agent arbeitet: einreihen |
| `unqueue` | Eingereihte Nachricht zurückziehen |
| `cancel` | Stoppen |
| `permission` | Freigabe beantworten: `allow`, `always` oder `deny` |
| `answer` | Rückfrage beantworten: `choices`, `text` oder `skipped` |
| `undo`, `compact` | Letzten Auftrag zurücknehmen, Verlauf verdichten |
| `loop`, `loop_stop` | Schleife starten, beenden |
| `sharpen`, `report` | Prompt schärfen, Bericht zum Ausdrucken |
| `term_start`, `term_input`, `term_stop` | Terminal im Editor |
| `speech_start`, `speech_stop`, `speech_cancel`, `speech_model` | Diktat |
| `cowork_add`, `cowork_stop`, `cowork_retry`, `cowork_remove`, `cowork_clear`, `cowork_undo`, `cowork_board` | Cowork-Brett – nur *Verwalten* |

Vom Server ans Fenster:

| Ereignis | Bedeutung |
| --- | --- |
| `session`, `busy`, `done`, `title` | Der offene Chat, ob er arbeitet, dass er fertig ist, ein neuer Titel |
| `status`, `assistant_start`, `thinking`, `text`, `tool_call`, `tool_running`, `tool_result`, `stats`, `context`, `todos`, `changes` … | Was der Agent gerade tut |
| `permission`, `question` | Der Agent wartet auf dich |
| `queued`, `queued_taken`, `queue_rejected`, `unqueued`, `queue_dropped` | Nachrichten, die während der Arbeit geschrieben wurden |
| `notice`, `error` | Hinweise und Fehler |
| `loop`, `sharpened`, `report`, `undone`, `undo_failed` | Antworten auf die Befehle oben |
| `term`, `speech`, `cowork` | Ausgabe im Terminal, Stand des Diktats, Cowork-Brett |
| `presence`, `auth` | Wer gerade da ist (nur an *Verwalten*); Konto gelöscht oder Zugang erneuert |

**Terminal im Editor**
- `term_start` startet einen echten Prozess im Workspace – PowerShell unter Windows, sonst bash. Die Ausgabe (stdout und stderr zusammen) kommt Stück für Stück als `term`, `term_input` schreibt nach stdin, `term_stop` beendet den ganzen Prozessbaum
- Höchstens drei Befehle je Fenster. Nach rund vier Millionen Zeichen Ausgabe zeigt das Terminal nichts mehr an, der Befehl läuft aber weiter
- Nur für *Mitarbeiten* und *Verwalten* – es ist ein Befehl auf deinem Rechner. Geht das Fenster, enden auch seine Befehle: Niemand könnte sie sonst noch sehen oder stoppen

**Mehrere Nutzer gleichzeitig**
- Ein Server, ein Modell-Server, eine Grafikkarte: Alle Aufträge teilen sich die Runtime. Laufen zwei gleichzeitig, teilen sie sich die Rechenzeit – jeder wird langsamer
- Jeder Chat trägt seinen Besitzer; Listen und Zugriffe filtern danach. Dein Konto *Ich selbst, unterwegs* zählt als du – dieselben Chats wie am Rechner
- Öffnen zwei Fenster denselben Chat, hängen beide am selben Run und sehen denselben Auftrag live
- `Share` kennt alle offenen Fenster: Kommt oder geht jemand, bekommen die Fenster mit *Verwalten* sofort `presence`. Wird ein Konto gelöscht oder sein Link erneuert, bekommen dessen Fenster `auth`, die Leitung geht zu, und die Oberfläche springt zur Anmeldung
- Kommt jemand über eine Portfreigabe, merkt sich der Server die Adresse von außen (`X-Forwarded-Host`) – daraus werden die Einladungslinks. Eine feste Adresse lässt sich im Freigabe-Blatt eintragen (`public_url`)

**Wo der Server seine Daten ablegt** – unter `~/.coder`, oder im Ordner aus `CODER_HOME`:

| Pfad | Inhalt |
| --- | --- |
| `config.json` | Einstellungen |
| `users.json` | Konten, Passwort-Hashes, Anmeldungen und Einladungen (nur als Hash) |
| `sessions/` | Chats |
| `checkpoints/` | Sicherungen für Rückgängig |
| `trash/` | Im Editor Gelöschtes |
| `reports/` | Berichte zum Ausdrucken |
| `images/` | Angehängte Bilder |
| `memory/`, `agents/`, `commands/` | Globales Gedächtnis, eigene Agents und Befehle |

Selbst nachsehen, ohne Modell: `python tests/serve.py` startet den echten Server mit nachgebautem Ollama in einem eigenen
Spielplatz. Am Rechner selbst – ohne Anmeldung – zeigt dann

```bash
curl.exe http://127.0.0.1:8778/api/state
```

den Zustand, wie ihn die Oberfläche beim Start liest. Die Testreihen `server`, `teilen`, `editor` und `chattab` prüfen
genau diese Wege.

## Tests

```bash
python coder.py test              # alles, rund 120 Sekunden
python coder.py test design cli   # nur diese Reihen
python coder.py test -v           # mit jeder einzelnen Prüfung
```

Zwanzig Reihen, zusammen 1419 Prüfungen – ohne Ollama, ohne GPU, ohne Internet:

| Reihe | Was sie prüft |
| --- | --- |
| `design` | Tokens aller drei Designs und aller Farbthemen, Kontraste (nachgerechnet, nicht geschätzt), tote Regeln, Umschalter, der Gedächtnis-Graph, Modi, Rückfrage und Aufwandsregler in der Oberfläche |
| `regress` | Werkzeuge, Aufruf-Erkennung im Text, Schemas, Befehle, Agents |
| `imagegen` | Bilder erzeugen gegen nachgebautes ComfyUI und nachgebaute Stable-Diffusion-WebUI |
| `report` | Der Bericht zum Ausdrucken, samt eingebetteten Bildern und Markdown |
| `cli` | Terminalmodus: Befehle, Schleife, Prepromter, Gedächtnis, Aufrufe im Text, eingereihte Nachrichten |
| `terminal` | Die Bausteine: Markdown Stück für Stück (gestückelt = am Stück), Aufruf-Filter, Eingabezeile, Zeichensätze |
| `konsole` | Der Terminalmodus in einer echten, unsichtbaren Windows-Konsole (ConPTY) – mit echten Tasten: Tab, Verlauf, Umschalt+Enter, Umschalt+Tab, Freigaben und Rückfragen als Auswahl, Plan umsetzen, Tippen während der Arbeit, Esc und Strg+C |
| `server` | Schleife (auch mit `/befehl`), Schärfen und Bericht über den WebSocket |
| `modelle` | Große Modelle: Ladeplan über GPU, RAM und Platte, aktive Parameter bei MoE (gpt-oss:120b, qwen3-coder:30b …), Tempo-Schätzung, Empfehlung, Watchdog |
| `sprechen` | Diktat: Aufnahme mit nachgebautem Mikrofon, Erkennung, Knopf, `/diktat`, und dass aus der Ferne niemand mithört |
| `vllm` | vLLM: Ollamas GGUF-Dateien finden, Startbefehl bauen, OpenAI-Format in beide Richtungen, ganze Agent-Schleife über einen nachgebauten vLLM |
| `dateien` | Die Datei-API (Baum, Lesen, Speichern – und dass nichts außerhalb des Workspace geht), die Aufteilung des Kontextfensters, das Maskottchen und der Hervorheber (im echten JavaScript, mit Node) |
| `ergaenzen` | Ergänzen: die Schreibweisen der FIM-Modelle, das Putzen der Antwort, der Weg über den Server (nichts nach draußen, kein Wecken, Vorrang für den Agent) und die Liste beim Tippen im echten JavaScript |
| `cowork` | Das Brett: Aufträge laufen parallel und in der Reihenfolge, jeder Modus darf genau seins, eigener Chat, Stoppen, Rückgängig, Wiederholen – auch über den WebSocket |
| `modi` | Chat, Normal, Planen, Autonom im Agent; Rückfragen von der Frage bis zur Antwort im Verlauf; Aufwand (Schritte, Denkmodus, Kontrolle, Prompt); dasselbe über den WebSocket und im Terminal; Terminal-Farben |
| `besser` | Aufträge überleben ein Neuladen des Fensters, Zeilenenden, Cowork, Ergänzen, Schleife |
| `teilen` | Mehrere Nutzer: ein nachgestellter VS-Code-Tunnel (Host und Origin auf localhost umgeschrieben), Einladung, Anmeldung, Sperre nach Fehlversuchen, Rollen am Server, jeder nur seine Chats, eigener Ordner, Berichte, Umbenennen, Anwesenheit, gelöschte Konten |
| `chattab` | Der Chat-Tab: nur Recherche-Werkzeuge, eigener Prompt, keine Kontrolle, eigenes Modell, getrennte Listen, Wechseln während der Agent arbeitet, und Inkognito: nichts auf der Platte, kein Gedächtnis, weg nach dem Verlassen |
| `persoenlich` | Eigene Anweisungen und Antwortstil vom Baustein bis zum Modell (Code, Chat, Terminal), getrennt je Konto; nichts davon für Sub-Agents und Kontrolle; eigene Prompts anlegen, umbenennen, verschieben, löschen, mit gesperrten Namen und Rechten je Rolle; `/anweisungen` und `/stil`; ein echter uvicorn, an dem ein WebSocket ohne Anmeldung mit 4401 endet |
| `editor` | Der Editor: alle Dateien, Suche in Dateien, anlegen/umbenennen/löschen samt Papierkorb, Konflikte beim Speichern, Bildvorschau, Git-Status und Diff, das Terminal mit Ausgabe, Eingabe und Stoppen, klickbare Fehlerstellen und Symbole (im echten JavaScript, mit Node) |

Ollama und die Bilddienste sind nachgebaut und antworten mit festen Zügen; jede Reihe läuft in einem eigenen
Prozess mit eigenem `CODER_HOME` unter `%TEMP%\coder-tests` – deine Chats, Notizen und Einstellungen bleiben unberührt.
Die Reihe `konsole` braucht Windows 10 (1809) oder neuer; anderswo wird sie übersprungen.

Die Oberfläche ohne Modell ansehen:

```bash
python tests/serve.py --design terminal
```

Das startet den echten Server mit der echten Agent-Schleife, nur Ollama und der Bilddienst sind nachgebaut.

## Sicherheit

- Der Server nimmt nur Anfragen an `127.0.0.1` an – und von Browsern nur solche, die von der Coder-Oberfläche selbst kommen. Eine andere Webseite, die im Browser offen ist, kann weder Aufträge schicken noch Freigaben erteilen; auch DNS-Rebinding wird abgewiesen
- Wer nicht an diesem Rechner sitzt – im LAN mit `--serve --host 0.0.0.0` oder über eine Portfreigabe in VS Code –, braucht ein Konto. Ein Tunnel liefert jede Anfrage von `127.0.0.1` aus und schreibt Host und Origin auf `localhost` um; Coder erkennt ihn an den `X-Forwarded-*`-Kopfzeilen und hält den Besucher deshalb nie für dich am Rechner
- Passwörter liegen nur als PBKDF2-Hash in `~/.coder/users.json`, Anmeldungen und Einladungen nur als SHA-256 ihres Schlüssels. Das Cookie ist `HttpOnly` und `SameSite=Lax` (hinter https auch `Secure`): Eine fremde Webseite kann damit weder Anfragen noch einen WebSocket öffnen. Nach fünf falschen Passwörtern wartet das Konto, jedes Mal doppelt so lange
- Rollen prüft der Server bei jeder Anfrage. *Mitarbeiten* heißt: Dateien ändern und Befehle nach Freigabe – auf deinem Rechner. Vergib es nur an Leute, denen du das zutraust
- Im Modus *Autonom* führt das Modell Befehle ohne Rückfrage aus. Nutze ihn nur in Projekten, bei denen das unkritisch ist
- Im Modus *Chat* kann das Modell nichts ändern und nichts ausführen – Webseiten liest es dort ohne Nachfrage
