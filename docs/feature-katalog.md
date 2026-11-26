# Feature-Katalog

Der Feature-Katalog zeigt geprüft, was die IT-OT vPLC kann – fachlich für das Produktteam, technisch für
die Entwicklung. Er steht in YAML unter `catalog/` (einzige Quelle) und wird in jeder CI gegen Code und
Testergebnisse geprüft.

**Ansicht:** [`docs/feature-katalog/index.html`](feature-katalog/index.html) – eine eigenständige HTML-Datei
(im Browser öffnen, kein Server nötig), dazu die Daten als `catalog.json`. Sie ist ein Stand zum Zeitpunkt des
letzten Commits; die jeweils aktuelle Ansicht erzeugt jeder CI-Lauf als Artefakt.

## Stand

| | |
|---|---|
| Features im Katalog | 45 in 10 Bereichen, alle per bestandenem Test nachgewiesen |
| Akzeptanzkriterien / Nachweise | jedes Kriterium mit mindestens einem bestandenen Nachweis |
| Prüfbestand | 6: Weboberfläche (5, bewusst ohne E2E-Tests), Zähler CTUD (ohne Test) |
| Bedienwege | `web`, `api`, `s7`, `opcua`, `node-red`, `cli`, `entwicklung` |
| Vergleich | Themenliste der Anforderung (`catalog/comparisons/themenliste.yaml`), jedes Feature eingestuft |
| Nachweisquellen | pytest (vPLC und Werkzeug), mocha (Node-RED-Paket) als JUnit-XML |

## Aufbau

```
catalog/
  catalog.yaml                 Bereiche, Gruppen, owns, Erkennungsquellen, Ausnahmen, Vergleiche
  features/<bereich>.yaml      Features mit Akzeptanzkriterien und Nachweisen
  review.yaml                  Prüfbestand (gleiches Format + state, reason)
  comparisons/themenliste.yaml Themen der Anforderung mit Stand und Lücken
  discovered/routes.json       Endpunkte der App, geschrieben von tests/test_catalog_export.py
  nachweis-review.md           Kriterium → Aktion → Zusicherung je Nachweis (Regel N7)
tools/feature_catalog/         Werkzeug (nicht Teil der ausgelieferten App) + eigene Tests
```

Erkannt werden ohne Änderung der Applikation:

| Bestandteil | Quelle |
|---|---|
| HTTP- und WebSocket-Endpunkte, Seiten | Exportdatei `catalog/discovered/routes.json` aus der laufenden FastAPI-App (Test) |
| CLI-Befehle | `add_parser(...)` in `src/vplc/__main__.py` (per `ast`) |
| Node-RED-Nodes und Editor-Endpunkte | `RED.nodes.registerType` / `RED.httpAdmin` in `node-red/nodes/vplc.js` |

Ein Bereich beansprucht Bestandteile über `owns` (Pfad-Präfixe; das längste Präfix gewinnt, ein Präfix gilt nur
für ganze Segmente).

## Befehle

```bash
# Testberichte erzeugen (wie in der CI)
pytest --junitxml=reports/pytest-junit.xml
(cd node-red && npm run test:junit)                       # → reports/nodered-junit.xml
pytest tools/feature_catalog/tests --junitxml=reports/catalog-junit.xml

# prüfen und Ansicht erzeugen
PYTHONPATH=tools python -m feature_catalog check --reports reports      # Exit-Code 1 bei Fehlern
PYTHONPATH=tools python -m feature_catalog build --reports reports      # → catalog/dist/index.html
PYTHONPATH=tools python -m feature_catalog build --reports reports --out docs/feature-katalog   # Stand im Repo aktualisieren
PYTHONPATH=tools python -m feature_catalog review > /tmp/review.md      # Tabelle für Regel N7

# nach Änderungen an Endpunkten die Exportdatei erneuern
UPDATE_SNAPSHOTS=1 pytest tests/test_catalog_export.py
```

Ohne `--reports` prüft das Werkzeug nur statisch und sagt das in der Ausgabe.

## Regeln für Nachweise

Ein grüner Test ist nicht automatisch ein Funktionsnachweis. Deshalb gilt:

1. Jedes Feature hat **Akzeptanzkriterien**, mindestens eines der Art `effekt`. Jede Regel mit Fehlercode
   (in Backticks, z. B. `` `409` ``) in `rules` erscheint als Kriterium der Art `regel` mit `code`.
2. Jeder Nachweis nennt unter `covers`, welche Kriterien er prüft.
3. Ein Feature ist erst **nachgewiesen**, wenn jedes Kriterium einen Nachweis hat, der im letzten Lauf bestanden hat.
   Übersprungene, fehlgeschlagene oder nicht gelaufene Tests zählen nie.
4. Der Test **löst die Fähigkeit aus und sichert den Effekt oder die Regel zu**. Statuscode oder „nicht leer“
   allein genügen nicht; Fehlercodes stehen als Zusicherung im Test.
5. Der Effekt wird **von außen beobachtet** (Antwort, Lese-Schnittstelle, S7/OPC UA, Stream), nicht über Mocks.
6. **Review-Pflicht:** Wer einen Nachweis einträgt oder ändert, liest den Testcode und bestätigt die Zeile in
   `catalog/nachweis-review.md` (neu erzeugen mit `review`).

Die statische Prüfung (Zusicherung vorhanden, nicht nur Status, Bezug zum Feature, Fehlercode im Test) ist eine
Heuristik und ersetzt das Review nicht.

### Prüfregeln

| Code | Stufe | Wann |
|---|---|---|
| `SCHEMA` | Fehler | YAML ungültig, unbekanntes Feld, falsche Gruppe/ID, unbekanntes Vergleichsthema |
| `UNASSIGNED` | Fehler (katalogisiert) / Hinweis (offen) | Bestandteil ohne Feature, Prüfbestand oder Ausnahme |
| `UNOWNED` | Fehler | Bestandteil, den kein Bereich beansprucht |
| `UNKNOWN_ENDPOINT` / `_COMMAND` / `_NODE` / `_UIROUTE` | Fehler | Verweis auf Entferntes |
| `UNKNOWN_COMPONENT` / `UNKNOWN_TEST` / `UNKNOWN_DEPENDENCY` | Fehler | Quelldatei, Test oder `dependsOn` fehlt |
| `EVIDENCE_MISSING` / `ACCEPTANCE_MISSING` | Fehler | kein Nachweis / kein Kriterium der Art effekt |
| `RULE_WITHOUT_ACCEPTANCE` | Fehler | Fehlercode in `rules` ohne Kriterium der Art regel |
| `EVIDENCE_UNLINKED` | Fehler | Nachweis ohne oder mit unbekanntem `covers` |
| `ACCEPTANCE_UNCOVERED` | Fehler | Kriterium ohne bestandenen Nachweis |
| `EVIDENCE_NO_ASSERTION` / `RULE_CODE_NOT_ASSERTED` | Fehler | keine Zusicherung / Fehlercode nicht zugesichert |
| `EVIDENCE_FAILED` / `_SKIPPED` / `_NOT_RUN` | Fehler | Testergebnis im Bericht |
| `COMPARISON_MISSING` | Fehler | Feature ohne Einstufung im Vergleich |
| `EVIDENCE_STATUS_ONLY` / `EVIDENCE_UNRELATED` | Warnung | nur Statusprüfung / kein Bezug erkannt – Review |
| `ENDPOINT_UNTESTED` | Warnung | kein Test ruft den Endpunkt erkennbar auf |

## Pflege

- **Neue Funktion:** Feature mit Akzeptanzkriterien und Nachweisen anlegen; Review-Tabelle neu erzeugen.
- **Neuer Endpunkt:** Exportdatei erneuern, dann einem Feature zuordnen oder als begründete Ausnahme führen.
- **Test umbenannt:** Nachweis anpassen (`UNKNOWN_TEST`).
- **Funktion entfernt:** Feature löschen; die ID nie wiederverwenden.
- **Ohne Test:** in `review.yaml` mit `state` und `reason` – lieber offen im Prüfbestand als ein Scheinnachweis.
- **Testnamen sind die Brücke zum Katalog:** sprechende Funktionsnamen (pytest) bzw. `it()`-Titel (mocha).

## Offene Punkte

- Weboberfläche: E2E-Tests (z. B. Playwright) würden die fünf Web-Features aus dem Prüfbestand holen.
- CTUD: Unit-Test in `tests/test_function_blocks.py` ergänzen.
- Reviewpflicht technisch absichern: Für `catalog/features/` einen Eintrag in `.github/CODEOWNERS` anlegen,
  sobald feststeht, wer Änderungen am Katalog freigibt.
- Optional für Kernfunktionen: Mutationstests (mutmut) auf Compiler und Runtime.
