# Nachweisregeln: Test ≠ Funktionsnachweis

Ein bestandener Test ist nicht automatisch ein Funktionsnachweis. Er kann nur einen Statuscode prüfen, etwas
Benachbartes testen oder das Ergebnis über Mocks selbst herstellen. Deshalb gelten diese Regeln unabhängig vom Stack.

## 1. Akzeptanzkriterien

| Art | Bedeutung | Gutes Beispiel | Schwaches Beispiel |
|---|---|---|---|
| `effekt` | Die Fähigkeit wirkt mit beobachtbarem Ergebnis. | „Nach dem Download mit RUN ist `Ausgang` nach drei Zyklen TRUE.“ | „Der Download funktioniert.“ |
| `regel` | Fachliche Regel oder Grenze, ggf. mit Fehlercode. | „Ein Programm mit Syntaxfehler wird mit Zeile und Spalte abgelehnt (`422`).“ | „Fehler werden behandelt.“ |

Gute Kriterien sind **konkret** (Werte, Zustände), **von außen beobachtbar** und **einzeln prüfbar**.

## 2. Regeln N1–N9

| Nr. | Regel |
|---|---|
| N1 | Jedes Katalog-Feature hat mindestens ein Kriterium der Art **effekt**. Jede Regel mit Fehlercode aus `rules` erscheint als Kriterium der Art **regel**. |
| N2 | Jeder Nachweis nennt unter `covers` die Kriterien, die er prüft. Ein Nachweis ohne `covers` zählt nicht. |
| N3 | Ein Feature ist erst **nachgewiesen**, wenn **jedes** Kriterium mindestens einen im letzten Lauf bestandenen Nachweis hat. Sonst gilt es als *teilweise nachgewiesen* und gehört in den Prüfbestand. |
| N4 | **Wirkt und prüft:** Der Test löst die Fähigkeit über einen Bestandteil des Features aus (Endpunkt, Seite, Ereignis, Befehl, Knoten, Komponente) und sichert einen erwarteten Effekt oder die Regel zu. Statuscode, „nicht null“ oder „Seite lädt“ genügen allein nicht. |
| N5 | **Von außen beobachtet:** Der Effekt wird über Antwort, Lese-Schnittstelle, Ereignis, Protokoll oder Oberfläche beobachtet, nicht nur über Aufrufe an Mocks des eigenen Codes. Rein mock-basierte Unit-Tests zählen nur für reine Berechnungs- oder Entscheidungslogik. |
| N6 | Bei Regel-Kriterien mit `code` kommt der Code im Test als Zusicherung vor. |
| N7 | **Review-Pflicht:** Wer einen Nachweis einträgt oder ändert, liest den Testcode. Ein Agent gibt im PR je neuem Nachweis an: *Kriterium → auslösende Aktion → Zusicherung (Datei:Zeile)*. `catalog/features/` ist per CODEOWNERS reviewpflichtig. |
| N8 | **Kein Nachweis** sind Smoke-Tests, Snapshot-Tests ohne fachliche Zusicherung, übersprungene Tests und Tests, die nur prüfen, was sie selbst gemockt haben. |
| N9 | Für Kernfeatures empfohlen: **Mutationstests** auf den Komponenten. Überlebende Mutanten in abgedeckten Pfaden zeigen zu schwache Zusicherungen. |

## 3. Nachweisstufen (Testarten)

Je höher die Stufe, desto näher ist der Test an der echten Nutzung. Für jedes Kriterium soll die **niedrigste Stufe**
gewählt werden, auf der N4 und N5 erfüllbar sind. Höhere Stufen sind ergänzend.

| Stufe | Art | Taugt für | Typische Grenze |
|---|---|---|---|
| U | `unit` | reine Logik, Berechnungen, Parser, Zustandsautomaten | keine Effekte über Systemgrenzen |
| I | `integration` | API, Persistenz, Messaging, Protokolle im Prozess oder mit Testcontainern | ohne echte Oberfläche/Hardware |
| E | `e2e` | Bedienweg `web`, Zusammenspiel mehrerer Dienste | langsam, Flakiness beobachten |
| S | `scenario` | fachliche Abläufe (Gherkin, BDD) | Schrittdefinitionen auf N5 prüfen |
| H | `hil` / `sil` | Hardware- bzw. Software-in-the-Loop, Feldbus, Echtzeit | Testumgebung knapp → Ergebnis aus freigegebenem Lauf |
| M | `manual` | nur mit Protokoll (Datum, Version, Prüfer) und nur, wenn der Steckbrief das erlaubt | veraltet bei jeder Änderung → Warnung bei jedem Release |

## 4. Statische Prüfung des Testkörpers

Diese Prüfung ist eine Heuristik, die das Review ergänzt und nicht ersetzt. Das Profil liefert, wie der **Körper**
eines Tests ermittelt wird (AST, Parser, Klammerzählung) und welche Muster als Zusicherung bzw. als reine Statusprüfung
gelten.

| Prüfung | Befund |
|---|---|
| Der Körper (samt Test-Helfern derselben Datei) enthält keine Zusicherung | `EVIDENCE_NO_ASSERTION` (Fehler) |
| Er sichert nur Status/Existenz zu | `EVIDENCE_STATUS_ONLY` (Warnung) |
| Er nennt keinen Bestandteil und keine Komponente des Features | `EVIDENCE_UNRELATED` (Warnung) |
| Bei einem Regel-Kriterium mit `code` fehlt der Code | `RULE_CODE_NOT_ASSERTED` (Fehler) |

## 5. Ergebnis im Testlauf

| Zustand im Bericht | Wirkung |
|---|---|
| bestanden (alle Instanzen bei Parametrisierung) | zählt |
| `failure` / `error` | `EVIDENCE_FAILED` |
| `skipped` (auch fehlende Testumgebung) | `EVIDENCE_SKIPPED`, **zählt nie** |
| Testart lief, Test kam nicht vor | `EVIDENCE_NOT_RUN` |
| Kein Bericht übergeben | nur statische Prüfung, und die Ausgabe sagt das ausdrücklich |
