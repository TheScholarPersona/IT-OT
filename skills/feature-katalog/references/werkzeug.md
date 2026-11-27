# Werkzeug: Kern + Adapter

Halte das Werkzeug klein, in der Größenordnung von 1500–2500 Zeilen inklusive Ansicht und Kern. Es wird **nicht** in
die ausgelieferte Anwendung eingebaut; es ist eine Dev-Abhängigkeit, ein eigenes Build-Modul oder ein eigenes
Repository. Vor jeder neuen Abhängigkeit werden Lizenz und Alter der Version geprüft.

## 1. Architektur

```
            ┌──────────────── Kern (stackneutral) ────────────────┐
 YAML ────► │ Schema ─► Modell ─► Analyse (Regeln) ─► Ansicht/JSON │ ──► catalog/dist/
            └────▲──────────────▲──────────────▲──────────────────┘
                 │ Bestandteile │ Testergebnisse│ Testkörper, Aufrufe
            ┌────┴──────┐ ┌─────┴──────┐ ┌──────┴────────┐
            │ Erkennung │ │ Bericht-   │ │ Testcode-     │   ◄── je Profil (Adapter)
            │ je kind   │ │ Leser      │ │ Analyse       │
            └───────────┘ └────────────┘ └───────────────┘
```

**Adapter-Schnittstelle**, die jedes Profil implementiert (sprachneutral beschrieben):

| Funktion | Eingabe | Ausgabe |
|---|---|---|
| `discover(kind)` | Repository, Exportdateien | Liste `{kind, service?, id, method?, title?, roles?, source}` |
| `read_reports(dir)` | Berichtsverzeichnis | Liste `{testart, file/klasse, name, status, dauer}` |
| `resolve_test(file, test)` | Nachweis aus YAML | Testfall vorhanden? Körper (Text + Helfer), Position |
| `assertions(body)` | Körper | Zusicherungen, reine Statusprüfungen |
| `calls(body)` | Körper | aufgerufene Bestandteile `{kind, id, method?}` (Heuristik) |

Der Kern kennt nur diese Strukturen. Ein neuer Stack bedeutet ein neues Profil und keine Änderung am Kern.
**JUnit-XML** ist das bevorzugte Austauschformat für Testergebnisse; andere Formate (TAP, Cucumber-JSON, CTRF,
TRX) wandelt der Bericht-Leser in dieselbe Struktur um.

## 2. Prüfregeln

| Code | Stufe | Wann |
|---|---|---|
| `SCHEMA` | Fehler | YAML ungültig oder Schema verletzt (unbekannte Felder sind Fehler) |
| `UNASSIGNED` | Fehler (katalogisiert) / Hinweis (offen) | erkannter Bestandteil ohne Feature, Prüfbestand oder Ausnahme |
| `UNOWNED` | Fehler | Bestandteil, den kein Bereich beansprucht |
| `OWNED_TWICE` | Fehler | Bestandteil passt auf Präfixe zweier Bereiche |
| `UNKNOWN_PART` | Fehler | Verweis auf nicht (mehr) erkannten Bestandteil (Meldung nennt die `kind`) |
| `UNKNOWN_COMPONENT` | Fehler | Quelldatei fehlt |
| `UNKNOWN_TEST` | Fehler | Testfall nicht (mehr) in der Datei |
| `UNKNOWN_DEPENDENCY` | Fehler | `dependsOn` ins Leere |
| `UNKNOWN_CHANNEL` / `UNKNOWN_ROLE` | Fehler | nicht im Steckbrief deklariert |
| `EVIDENCE_MISSING` | Fehler | Katalog-Feature ohne Nachweis |
| `ACCEPTANCE_MISSING` | Fehler | kein Kriterium der Art effekt (N1) |
| `RULE_WITHOUT_ACCEPTANCE` | Fehler | Fehlercode in `rules` ohne Regel-Kriterium (N1) |
| `EVIDENCE_UNLINKED` | Fehler | Nachweis ohne `covers` oder mit unbekannter Kriteriums-ID (N2) |
| `ACCEPTANCE_UNCOVERED` | Fehler | Kriterium ohne bestandenen Nachweis (N3) |
| `EVIDENCE_NO_ASSERTION` | Fehler | Testkörper ohne Zusicherung (N4) |
| `RULE_CODE_NOT_ASSERTED` | Fehler | Fehlercode nicht im abdeckenden Test (N6) |
| `EVIDENCE_STATUS_ONLY` | Warnung | nur Status/Existenz zugesichert (N4) |
| `EVIDENCE_UNRELATED` | Warnung | kein Bezug zu Bestandteilen des Features (N4) |
| `EVIDENCE_FAILED` / `EVIDENCE_SKIPPED` / `EVIDENCE_NOT_RUN` | Fehler | siehe Nachweisregeln §5 |
| `EVIDENCE_MANUAL_STALE` | Warnung | manueller Nachweis älter als die letzte Änderung der Komponenten |
| `REVIEW_WITHOUT_REASON` | Fehler | Prüfbestand ohne `state` oder `reason` |
| `COMPARISON_MISSING` | Fehler | Vergleichssystem `complete: true`, Feature ohne Einstufung |
| `PART_UNTESTED` | Warnung | kein Test ruft einen Bestandteil erkennbar auf (Heuristik) |
| `DISCOVERY_STALE` | Fehler | Exportdatei weicht vom laufenden System ab (vom Export-Test gemeldet) |

Welche Testart ein Bericht abdeckt, erkennt das Werkzeug am Inhalt (Klassen-/Modulpfad, Marker, Verzeichnis), nicht am
Dateinamen.

## 3. CLI

```
feature-catalog check [--reports DIR] [--strict]       # Exit 1 bei Fehlern; --strict: auch Warnungen
feature-catalog build [--reports DIR] --out DIR        # index.html + catalog.json + stats.json
feature-catalog explain <feature-id>                   # Kriterien, Nachweise, Ergebnisse, Befunde (für Reviews)
feature-catalog trace [--format csv|md]                # Rückverfolgbarkeit Feature → Kriterium → Test → Ergebnis
```

## 4. Ansicht

Die Ansicht ist eine eigenständige HTML-Datei ohne Server und ohne externe Skripte, mit eingebetteten Daten, dazu
`catalog.json`. Sie enthält:
- Kennzahlen und Reifegrad je Bereich,
- Navigation Bereich → Gruppe und die Reiter Katalog, Prüfbestand und Vergleich,
- Suche und Filter nach Rolle, Bedienweg, Dienst, Schnittstellenart, Nachweisstatus und Einstufung,
- eine Feature-Karte: fachliche Ebene sichtbar, technische Ebene aufklappbar (Bestandteile mit Zweck und Rollen,
  Ereignisse, Kriterien mit ihren Nachweisen und Ergebnissen, aufrufende Tests),
- hellen und dunklen Modus und eine auch mobil lesbare Darstellung.

## 5. CI (generisch)

```
Job test-<art>   (je Testart)  → Bericht als Artefakt (JUnit-XML)
Job export                     → Exportdateien prüfen (DISCOVERY_STALE)
Job katalog      needs: alle   → Berichte laden → check → build → Ansicht als Artefakt
```

Der Katalog-Job ist ein **Pflicht-Check** für den Hauptzweig. Die Tests des Werkzeugs liefern ebenfalls einen Bericht;
sie sind die Nachweise des Bereichs `katalog`. In Landschaften sammelt der Katalog-Job die Artefakte des jeweils
neuesten Hauptzweig-Laufs je Dienst ein.

## 6. Selbstbeschreibung: Bereich `katalog`

Der Bereich `katalog` hat kein `owns` und den Bedienweg `entwicklung`. Seine Features sind Datenmodell, Abgleich mit
dem Code, Nachweise im Testlauf, Ansicht und gegebenenfalls Vergleich. Die Nachweise sind Tests des Werkzeugs,
mindestens diese:
- Der echte Katalog hat keine Fehler.
- Jeder erkannte Bestandteil wird einem Bereich zugeordnet; ein doppelt beanspruchter wird gemeldet.
- Es entsteht eine eigenständige Ansicht.
- Je Feature wird mindestens ein Nachweis verlangt.
- Das Werkzeug legt nie selbst Features an.
- Verweise auf Entferntes werden gemeldet.
- Fehlgeschlagene, übersprungene und fehlende Nachweise werden gekennzeichnet.
- Aufrufe mit Methode werden erkannt, bloße Pfadlisten nicht.
- Für jedes Akzeptanzkriterium wird ein bestandener Nachweis verlangt.
- Nachweise ohne Zusicherung, mit reiner Statusprüfung oder ohne Bezug zum Feature werden erkannt.
- Der Fehlercode einer Regel wird als Zusicherung verlangt.
- Eine neue Schnittstellenart lässt sich allein per Konfiguration und Profil ergänzen.
