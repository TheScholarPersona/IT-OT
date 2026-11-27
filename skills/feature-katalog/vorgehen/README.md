# Vorgehen: Feature-Katalog einführen

Dieser Ablaufplan ist wiederverwendbar für jedes Projekt und jeden Stack. Er führt in **7 Schritten** von „kein
Katalog“ zu einem geprüften, in der CI verankerten Feature-Katalog. Jeder Schritt hat ein Ziel, konkrete Tätigkeiten,
eine Vorlage, ein Ergebnis und einen **Gate-Check**. Erst wenn der Gate-Check erfüllt ist, beginnt der nächste
Schritt.

Die Methode dahinter (Begriffe, Grundsätze, Regeln) steht in [../SKILL.md](../SKILL.md). Dieses Dokument
beschreibt nur, **was man in welcher Reihenfolge tut**.

```
 Schritt 1      2           3          4           5          6             7
 Klären ─★─► Inventar ─► Gliedern ─★─► Werkzeug ─► Pilot ─★─► Ausrollen ─★─► Betreiben
                                                    └──── je Bereich wiederholen ────┘
```

## Schnellstart

```bash
# Gerüst in ein Zielprojekt kopieren (überschreibt nichts)
skills/feature-katalog/vorgehen/scaffold.sh /pfad/zum/projekt
```

Das Skript legt `catalog/`, `docs/feature-katalog.md`, `docs/feature-katalog-steckbrief.md`, eine PR-Vorlage für
Nachweise und einen CI-Entwurf an. Danach geht es mit Schritt 1 weiter.

## Übersicht

| # | Schritt | Ergebnis | Vorlage | Richtwert Aufwand* |
|---|---|---|---|---|
| 1 | Klären ★ | bestätigter Steckbrief | [steckbrief.md](vorlagen/steckbrief.md) | 0,5 Tag |
| 2 | Inventar | Exportdateien, Liste aller Bestandteile | — | 0,5–2 Tage |
| 3 | Gliedern ★ | `catalog.yaml` mit Bereichen und `owns` | [catalog.yaml](vorlagen/catalog/catalog.yaml) | 0,5–1 Tag |
| 4 | Werkzeug | `check`/`build` lokal und in der CI | [ci-feature-katalog.yml](vorlagen/ci-feature-katalog.yml) | 1–3 Tage (0,5 mit vorhandenem Werkzeug) |
| 5 | Pilot ★ | ein Bereich auf Reifegrad 3 | [features/_beispiel.yaml](vorlagen/catalog/features/_beispiel.yaml) | 1–2 Tage |
| 6 | Ausrollen ★ | alle Bereiche `katalogisiert` | [pr-nachweis.md](vorlagen/pr-nachweis.md) | ca. 0,5 Tag je 10 Features + fehlende Tests |
| 7 | Betreiben | DoD, CODEOWNERS, Takt | [definition-of-done.md](vorlagen/definition-of-done.md) | laufend |

\* Richtwerte für ein mittelgroßes System (50–150 Features) mit Agenten-Unterstützung. Zum Kalibrieren nach dem Pilot
neu schätzen.

---

## Schritt 1 – Klären ★

**Ziel:** Alle Beteiligten haben dasselbe Bild davon, für wen der Katalog ist und was als Nachweis zählt.

**Tätigkeiten**
1. README, Doku, Build-Dateien und Tests sichten und den Stack bestimmen → Profil wählen (`../references/profile/`).
2. `docs/feature-katalog-steckbrief.md` aus der Vorlage **mit Vorschlägen** ausfüllen; offene Fragen sollen nur dort
   stehen bleiben, wo sich nichts ableiten lässt.
3. Steckbrief mit der Produktverantwortung durchgehen.

**Gate-Check**
- [ ] Zielgruppe, Rollen und Bedienwege sind festgelegt.
- [ ] Die Schnittstellenarten sind festgelegt, und jede hat eine vermutete Erkennung.
- [ ] Testarten, die als Nachweis zählen, sind festgelegt (und ob `manual` erlaubt ist).
- [ ] Der Zielreifegrad je Bereich (oder pauschal) ist festgelegt.
- [ ] Die Produktverantwortung hat den Steckbrief bestätigt.

---

## Schritt 2 – Inventar

**Ziel:** Jeder technisch erreichbare Bestandteil wird automatisch erkannt.

**Tätigkeiten**
1. Je Schnittstellenart einen **Export-Test** schreiben, der die Liste aus dem laufenden System nach
   `catalog/discovered/<kind>.json` schreibt und fehlschlägt, wenn die Datei veraltet ist (Neuschreiben mit
   `UPDATE_SNAPSHOTS=1`). Ist das nicht möglich, bleibt die statische Erkennung laut Profil.
2. Testberichte je Testart probeweise als JUnit-XML erzeugen.
3. Lücken notieren, also was sich nicht erkennen lässt, im Steckbrief unter „Erkennungslücken“.

**Gate-Check**
- [ ] Jede Schnittstellenart hat eine Exportdatei oder eine begründete Lücke.
- [ ] Die Export-Tests laufen grün und schlagen bei veralteter Datei fehl (einmal ausprobiert).
- [ ] Je Testart entsteht ein JUnit-Bericht mit stabilen, sprechenden Testnamen.

---

## Schritt 3 – Gliedern ★

**Ziel:** eine fachliche Gliederung, in der jeder Bestandteil genau einem Bereich gehört.

**Tätigkeiten**
1. Bereiche nach Aufgabenfeldern der Rollen schneiden, **nicht** nach Paketen oder Diensten. Richtwert: 5–20 Bereiche.
2. `owns`-Präfixe je Schnittstellenart vergeben.
3. Betriebsbestandteile (Health, Metriken, API-Doku, Admin) in `exclusions` eintragen, jeweils mit Grund.
4. Gruppen als Leseführung anlegen.
5. Den Bereich `katalog` (Selbstbeschreibung, ohne `owns`) anlegen.

**Gate-Check**
- [ ] Kein Bestandteil ist unbeansprucht (`UNOWNED` = 0) oder doppelt beansprucht (`OWNED_TWICE` = 0).
- [ ] Jede Ausnahme hat einen Grund.
- [ ] Die Produktverantwortung erkennt sich in den Bereichsnamen wieder und hat die Gliederung bestätigt.

---

## Schritt 4 – Werkzeug

**Ziel:** Die Prüfung läuft automatisch.

**Tätigkeiten**
1. Ein vorhandenes Werkzeug einbinden oder eines nach `../references/werkzeug.md` bauen (Kern + Profil).
2. Den CI-Entwurf `.github/workflows/feature-katalog.yml` an die Testjobs des Projekts anpassen.
3. Tests des Werkzeugs als Nachweise des Bereichs `katalog` eintragen.

**Gate-Check**
- [ ] `check` läuft lokal und in der CI; ohne `--reports` meldet es „nur statisch geprüft“.
- [ ] `check` meldet für noch offene Bereiche nur `UNASSIGNED` als Hinweis, sonst keine Fehler.
- [ ] `build` erzeugt eine eigenständige `index.html`, und sie liegt als CI-Artefakt vor.

---

## Schritt 5 – Pilot ★

**Ziel:** Zuschnitt und Strenge an einem echten Bereich kalibrieren, bevor alles katalogisiert wird.

**Tätigkeiten**
1. Den Pilotbereich wählen: mittelgroß, mindestens zwei Bedienwege, mindestens eine Regel mit Fehlercode.
2. Für jedes Feature in dieser Reihenfolge arbeiten:
   1. den Satz „*Rolle* kann *Fähigkeit*, damit *Nutzen*“ formulieren, und wenn er nicht gelingt, ist es kein Feature;
   2. die fachliche Ebene schreiben (`summary`, `description`, `usage`, `rules`);
   3. die technische Ebene schreiben (`components`, `parts`, `emits`/`consumes`);
   4. die **Akzeptanzkriterien** formulieren: mindestens ein Effekt und jede Regel mit Code;
   5. die Tests sichten; passt einer → Nachweis mit `covers`, fehlt einer → Test schreiben oder in `review.yaml`.
3. `check` grün → `status: katalogisiert`.
4. Die Ansicht vorführen und die Konventionen in `docs/feature-katalog.md` festhalten.

**Gate-Check**
- [ ] Der Pilotbereich ist auf Reifegrad 3, und `check` meldet keine Fehler.
- [ ] Jeder neue Nachweis ist im PR mit *Kriterium → Aktion → Zusicherung (Datei:Zeile)* belegt.
- [ ] Die Produktverantwortung hat den Zuschnitt bestätigt (Features nicht zu fein, nicht zu grob, nicht zu technisch).
- [ ] Die Entwicklung hat die Strenge der Nachweise bestätigt.
- [ ] Die Aufwandsschätzung für Schritt 6 ist anhand des Piloten aktualisiert.

---

## Schritt 6 – Ausrollen ★

**Ziel:** alle Bereiche katalogisiert.

**Tätigkeiten**
1. Die Bereiche nach Priorität abarbeiten (Kernbereiche zuerst), mit **ein Bereich = ein PR**.
2. Je Bereich das Vorgehen aus Schritt 5.2 anwenden.
3. Fehlende Tests sammeln und priorisieren: schreiben, wenn das Feature zum Kern gehört, sonst in den Prüfbestand mit
   Grund und `owner`.
4. Je PR die Vorlage [pr-nachweis.md](vorlagen/pr-nachweis.md) verwenden; Reviewer ist nicht, wer den Nachweis
   eingetragen hat.

**Gate-Check (Abnahme)**
- [ ] Die Abnahme-Checkliste in [../SKILL.md](../SKILL.md#6-abnahme) ist vollständig erfüllt.
- [ ] Die Reifegradbewertung ist durchgeführt ([reifegrad-bewertung.md](vorlagen/reifegrad-bewertung.md)).
- [ ] Der Prüfbestand ist mit Priorität und Verantwortlichen versehen.

---

## Schritt 7 – Betreiben

**Ziel:** Der Katalog veraltet nie.

**Tätigkeiten (einmalig)**
1. `check` als Pflicht-Check für den Hauptzweig einrichten.
2. Die Pflegeregeln in die Definition of Done übernehmen ([definition-of-done.md](vorlagen/definition-of-done.md)).
3. CODEOWNERS für `catalog/` einrichten ([CODEOWNERS](vorlagen/CODEOWNERS)).
4. Die PR-Vorlage aktivieren.

**Takt (laufend)**

| Wann | Was | Wer |
|---|---|---|
| jeder PR | `check` grün; Nachweise per Vorlage belegt | Autor, Reviewer |
| je Sprint/Release | Prüfbestand sichten und Abbau planen; Kennzahlen ansehen | Produktverantwortung, Kurator |
| je Quartal | Reifegrad neu bewerten; Konventionen und Profil nachschärfen | Kurator, Entwicklung |
| neue Schnittstellenart oder neuer Dienst | zurück zu Schritt 2 für diese Art bzw. diesen Dienst | Entwicklung |

---

## Aufträge für einen LLM-Agenten

Diese Aufträge können unverändert kopiert werden. Jeder bezieht sich auf genau einen Schritt und endet am Gate.

| Schritt | Auftrag |
|---|---|
| 1 | „Führe Schritt 1 des Feature-Katalog-Vorgehens aus: Bestimme den Stack, wähle das Profil und fülle `docs/feature-katalog-steckbrief.md` mit Vorschlägen. Leg mir den Steckbrief zur Bestätigung vor.“ |
| 2 | „Führe Schritt 2 aus: Schreibe je Schnittstellenart aus dem Steckbrief einen Export-Test nach `catalog/discovered/`, und melde Erkennungslücken. Ändere keinen Produktivcode.“ |
| 3 | „Führe Schritt 3 aus: Schlage eine fachliche Gliederung in `catalog/catalog.yaml` vor, sodass `UNOWNED` und `OWNED_TWICE` 0 sind. Leg sie mir als Tabelle Bereich → owns zur Bestätigung vor.“ |
| 4 | „Führe Schritt 4 aus: Binde das Werkzeug ein bzw. baue es nach `references/werkzeug.md`, und passe den CI-Entwurf an.“ |
| 5 | „Führe Schritt 5 für den Bereich `<id>` aus. Lies jeden Testkörper, bevor du ihn als Nachweis einträgst, und belege jeden Nachweis mit Kriterium → Aktion → Zusicherung (Datei:Zeile).“ |
| 6 | „Führe Schritt 6 für den Bereich `<id>` aus wie im Pilot, in einem PR mit der Vorlage `pr-nachweis.md`.“ |
| 7 | „Führe die Reifegradbewertung durch und aktualisiere den Stand in `docs/feature-katalog.md`.“ |
