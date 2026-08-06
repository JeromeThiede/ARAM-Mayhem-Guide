# ARAM Mayhem — Champion & Augment Explorer (flache Version)

Eine einzelne `index.html` mit allen Daten eingebettet: pro Champion das Item-Build und ein **individuelles Ranking aller Augments** mit Suche und **Synergie-Modus**, der die Liste nach jeder Auswahl neu ordnet.

Kein Server, keine Unterordner nötig. Öffnet sich auch per Doppelklick lokal. Die Daten hält ein **GitHub-Actions-Workflow** automatisch aktuell.

## Dateien

```
index.html          # die komplette App inkl. eingebetteter Daten
scrape.py           # holt aktuelle Daten und schreibt sie in index.html
requirements.txt    # requests, beautifulsoup4
.nojekyll           # GitHub Pages: statische Auslieferung
.github/workflows/update.yml   # woechentliche Auto-Aktualisierung
```

Der Scraper ersetzt in `index.html` nur den Block zwischen `/*DATA_START*/` und `/*DATA_END*/`.

## Veroeffentlichen mit GitHub Pages

1. **Repo anlegen:** GitHub → **+** → **New repository**, Name z. B. `aram-mayhem`, **Public**, **Add a README file** anhaken, **Create repository**.
2. **Dateien hochladen:** **Add file → Upload files** → `index.html`, `scrape.py`, `requirements.txt` hineinziehen → **Commit changes**. (Meine `README.md` ersetzt die automatische — gewollt.)
3. **Workflow anlegen** (liegt technisch in einem Unterordner, den GitHub selbst erzeugt): **Add file → Create new file**, Name exakt `.github/workflows/update.yml`, Inhalt aus der Datei einfuegen → **Commit**.
4. **.nojekyll anlegen:** **Add file → Create new file**, Name `.nojekyll`, leer lassen → **Commit**.
5. **Pages aktivieren:** **Settings → Pages → Source:** „Deploy from a branch", Branch `main`, Ordner `/ (root)` → **Save**.
6. **Auto-Update erlauben:** **Settings → Actions → General → Workflow permissions →** „Read and write permissions" → **Save**.

Fertig. Live unter `https://DEIN-NAME.github.io/aram-mayhem/`.

## Auto-Update

`.github/workflows/update.yml` laeuft jeden Montag (und manuell ueber **Actions → Run workflow**): holt die aktuelle Augment-Liste, Win-/Pick-Raten und Top-Champions, schreibt sie in `index.html` und committet. Neue/entfernte Augments, geaenderte Rankings und damit neue Synergien fliessen automatisch ein. Intervall per `cron` in der yml aendern (https://crontab.guru).

## Manuell aktualisieren

```
pip install -r requirements.txt
python scrape.py
```

## Modell

Individuelles Ranking pro Champion aus (a) expliziten Top-Champion-Nennungen des Augments, (b) daraus abgeleiteter Rollen-Affinitaet, (c) globaler Meta-Staerke/Win-Rate. Synergie-Modus: gemeinsame Top-Champions + Rollen-Aehnlichkeit + Schluesselwort-Tags. Heuristik-Modell; exakte offizielle Builds/Combos sind je Champion verlinkt. Item-Builds sind rollenbasierte Referenzen mit Direktlink zum exakten Build.

*ARAM Mayhem ist nicht von Riot Games unterstuetzt. League of Legends und Riot Games sind Marken von Riot Games, Inc. Datengrundlage: arammayhem.com.*
