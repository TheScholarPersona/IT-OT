# Vorgehensmodell im Detail

Jede Phase hat **Eingaben**, **Tätigkeiten**, **Ergebnisse** und ein **Ausgangskriterium**. Die Phasen 4 und 5 werden
je Bereich wiederholt. Phase 6 ist ein Dauerzustand.

```
 0 Klären ─★─► 1 Inventar ─► 2 Gliedern ─★─► 3 Werkzeug ─► 4 Pilot ─★─► 5 Ausrollen ─★─► 6 Betreiben
                    ▲                                                       │  (je Bereich)    │
                    └─────────────── neue Schnittstellenart / neuer Dienst ◄┴──────────────────┘
```

---

## Phase 0 – Klären ★

**Eingaben:** Repository(s), vorhandene Doku, Gespräch mit Produktverantwortung.

**Tätigkeiten:** Einen Steckbrief mit Vorschlägen erstellen, die der Nutzer nur bestätigen oder korrigieren muss.

| Punkt | Leitfrage | Beispiel |
|---|---|---|
| Zielgruppe | Wer liest den Katalog? | Produktteam, Vertrieb, Inbetriebnahme, Entwicklung |
| Rollen | Wer nutzt das System? | Bediener, Instandhaltung, Integrator, Administrator |
| Bedienwege | Wie wird es genutzt? | `web`, `api`, `messaging`, `batch`, `cli`, `feldbus`, `integration`, `entwicklung` |
| Schnittstellenarten | Was ist automatisch erkennbar? | `endpoint`, `stream`, `event`, `job`, `command`, `uiRoute`, `opcuaNode`, `node` |
| Nachweis-Testarten | Welche Tests zählen? | unit (nur reine Logik), integration, e2e, scenario, hil (Hardware-in-the-Loop) |
| Profile | Welche Stacks? | Python/FastAPI + JS (Node-RED) |
| Dienste | Ein Repository oder mehrere? | eins |
| Vergleich | Gegen welches System wird gemessen? | Wettbewerber, Vorgängerversion, Lastenheft |
| Zielreifegrad | Welche Stufe je Bereich? | 3, Kernbereiche 4 |

**Ergebnis:** bestätigter Steckbrief (als Kommentar in `catalog/catalog.yaml` oder in `docs/feature-katalog.md`).
**Ausgang:** Der Nutzer hat den Steckbrief bestätigt.

---

## Phase 1 – Inventar

**Eingaben:** Steckbrief, Profil(e).

**Tätigkeiten:**
1. Je Schnittstellenart die Erkennung aus dem Profil wählen. **Bevorzugt** wird ein Export-Test, der die Liste aus dem
   laufenden System schreibt (`catalog/discovered/<art>[-<dienst>].json`) und fehlschlägt, wenn die Datei veraltet ist
   (Neuschreiben per `UPDATE_SNAPSHOTS=1`). Der **Ausweichweg** ist statische Analyse.
2. Festhalten, was sich *nicht* erkennen lässt: Zuschnitt, Nutzen, Regeln und Bedienwege ohne technischen Anker.
3. Testberichte probeweise erzeugen (JUnit-XML o. ä.) und prüfen, ob Testnamen stabil und sprechend sind.

**Ergebnis:** Exportdateien, Rohliste aller Bestandteile, Liste der Erkennungslücken.
**Ausgang:** Jede Schnittstellenart aus dem Steckbrief hat eine Erkennung oder eine begründete Lücke.

---

## Phase 2 – Gliedern ★

**Tätigkeiten:**
1. Bereiche **fachlich** schneiden: Ein Bereich entspricht einem Aufgabenfeld einer Rolle, nicht einem Paket oder
   Microservice.
2. Je Bereich `owns`-Präfixe vergeben, sodass jeder Bestandteil genau einem Bereich gehört.
3. Betriebs- und Infrastrukturbestandteile (Health, Metriken, Swagger-UI, Admin) als begründete `exclusions` führen.
4. Gruppen als Leseführung anlegen, mit 3–10 Features je Gruppe als Richtwert.

**Zuschnitt-Heuristiken für Features:**
- Formuliere es als Satz „*Rolle* kann *Fähigkeit*, damit *Nutzen*“. Gelingt der Satz nicht, ist es kein Feature.
- Ein CRUD-Satz ist meist **mehrere** Features (anlegen ≠ ändern ≠ archivieren), wenn sich Regeln oder Rollen
  unterscheiden; sonst ist er **ein** Feature „verwalten“.
- Querschnitt (Audit, Rechte, Versionierung) ist eigenes Feature, wenn eine Rolle ihn bewusst nutzt, z. B. „Audit-Log
  einsehen“. Sonst wird er als Regel im jeweiligen Feature geführt.
- Dieselbe Fähigkeit über mehrere Bedienwege ist **ein** Feature mit mehreren `usage`-Einträgen.

**Ergebnis:** `catalog/catalog.yaml`. **Ausgang:** `UNOWNED` = 0 und Taxonomie vom Nutzer bestätigt.

---

## Phase 3 – Werkzeug

**Tätigkeiten:** Kern und Profil bauen bzw. ein vorhandenes Werkzeug einbinden ([werkzeug.md](werkzeug.md)) und
Testberichte in der CI je Testart getrennt ablegen. Danach wird der Bereich `katalog` angelegt (Selbstbeschreibung).

**Ergebnis:** `check` und `build` laufen lokal und in der CI. **Ausgang:** `check` meldet nur noch erwartete Befunde
(`UNASSIGNED` für noch nicht katalogisierte Bereiche als Hinweis).

---

## Phase 4 – Pilot ★

**Tätigkeiten:**
1. Einen typischen Bereich wählen: mittelgroß, mehrere Bedienwege, mindestens eine Regel mit Fehlercode.
2. Ihn vollständig auf Reifegrad 3 bringen: Features, Kriterien, Nachweise und fehlende Tests.
3. Die Ansicht zeigen und den Zuschnitt sowie die Strenge der Nachweise bestätigen lassen. Liegen die Features zu fein,
   zu grob oder zu technisch? Reichen die Kriterien?

**Ergebnis:** ein Bereich `katalogisiert`, kalibrierte Konventionen (in `docs/feature-katalog.md` festhalten).
**Ausgang:** Nutzer bestätigt den Zuschnitt.

---

## Phase 5 – Ausrollen ★

**Tätigkeiten je Bereich:**
1. Features anlegen (fachlich, dann technisch).
2. Akzeptanzkriterien formulieren (mindestens ein Effekt und jede Regel mit Code).
3. Vorhandene Tests sichten. Passt ein Test → Nachweis mit `covers`. Fehlt einer → Test schreiben oder das Feature in den
   Prüfbestand.
4. `check` grün → `status: katalogisiert`.

**Reihenfolge:** Kernbereiche zuerst, `katalog` zuletzt fertigstellen.
**Ausgang:** Abnahme-Checkliste aus `SKILL.md` erfüllt.

---

## Phase 6 – Betreiben

**Pflegeregeln (in die Definition of Done übernehmen):**

| Ereignis | Pflicht |
|---|---|
| Neue Fähigkeit | Feature mit Kriterien und Nachweis, oder Eintrag im Prüfbestand mit `state: geplant` |
| Neuer Bestandteil | einem Feature zuordnen oder begründete Ausnahme (sonst `UNASSIGNED`) |
| Test umbenannt/verschoben | Nachweis anpassen (sonst `UNKNOWN_TEST`) |
| Fähigkeit entfernt | Feature löschen; **IDs nie wiederverwenden** |
| Fähigkeit vorübergehend aus | Prüfbestand, `state: deaktiviert` |
| Neue Schnittstellenart/neuer Dienst | zurück zu Phase 1 für diese Art bzw. diesen Dienst |

**Takt:** Der Prüfbestand wird je Release oder Sprint gesichtet (Abbau planen), Warnungen je PR. Kennzahlen siehe unten.

---

## Rollen (RACI)

| Tätigkeit | Produktverantwortung | Entwicklung | QS/Test | Katalog-Kurator | LLM-Agent |
|---|---|---|---|---|---|
| Steckbrief, Taxonomie | **A** | C | C | R | R (Vorschlag) |
| Feature-Zuschnitt, fachliche Texte | **A** | C | C | R | R (Entwurf) |
| Technische Ebene | I | **A** | I | C | R |
| Akzeptanzkriterien | **A** | C | R | C | R (Entwurf) |
| Nachweise zuordnen, Tests schreiben | I | R | **A** | C | R |
| Review der Nachweise (N7) | I | R | **A** | C | — (darf nicht selbst abnehmen) |
| Werkzeug, CI | I | **A** | C | R | R |
| Prüfbestand abbauen | **A** (Priorität) | R | R | C | R |

R = durchführend, A = verantwortlich, C = konsultiert, I = informiert. In kleinen Teams fallen Rollen zusammen. Wichtig
ist, dass **Nachweise nie nur von dem abgenommen werden, der sie eingetragen hat**.

---

## Kennzahlen

Das Werkzeug berechnet sie in `build` und gibt sie in der Ansicht und in `catalog.json` aus.

| Kennzahl | Formel | Zielwert |
|---|---|---|
| Zuordnungsquote | zugeordnete ÷ erkannte Bestandteile (ohne Ausnahmen) | 100 % |
| Nachweisquote | nachgewiesene Features ÷ (Katalog + Prüfbestand) | steigend |
| Kriterienabdeckung | Kriterien mit bestandenem Nachweis ÷ alle Kriterien | 100 % im Katalog |
| Prüfbestand nach Zustand | Anzahl je `state` | sinkend, keiner ohne `reason` |
| Offene Warnungen | `EVIDENCE_STATUS_ONLY`, `EVIDENCE_UNRELATED`, `ENDPOINT_UNTESTED` | 0 unbegründet |
| Reifegrad je Bereich | Stufe 0–5 | laut Steckbrief |
| Mutationswert (optional) | getötete ÷ Mutanten auf Kernkomponenten | ≥ Teamziel |

---

## Tailoring

| Projektgröße | Empfohlener Umfang |
|---|---|
| Klein (ein Repository, < 20 Features) | Phasen 0–2 und 4–5 zusammenlegen; ein Bereich je Aufgabenfeld; Ansicht optional als Markdown-Tabelle; Ziel Reifegrad 3 |
| Mittel | vollständiges Modell, ein Profil |
| Groß / Landschaft | Katalog-Repository, Artefakt-Sammlung je Dienst, Bereichsverantwortliche, Vergleichssysteme, Ziel Reifegrad 4 |
| Reguliert (Medizin, Safety, Bahn) | zusätzlich Rückverfolgbarkeit Anforderung → Feature → Kriterium → Test als exportierbarer Bericht; Nachweise nur aus freigegebenen Läufen; Review N7 dokumentiert |
