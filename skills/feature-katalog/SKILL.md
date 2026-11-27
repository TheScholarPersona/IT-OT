---
name: feature-katalog
description: Methodik und Vorgehensmodell für einen geprüften Feature-Katalog beliebiger Software – vom Webdienst über Microservice-Landschaften bis zu Bibliotheken, CLIs und OT-/Steuerungssoftware. YAML im Repository als einzige Quelle, automatischer Abgleich mit Code und Testberichten, Akzeptanzkriterien mit bestandenen Nachweisen, interaktive Ansicht, CI-Prüfung. Technologieneutraler Kern plus austauschbare Stack-Profile (Python, Java/Spring, JS/TS, OT). Verwenden, wenn ein Feature-Katalog angelegt, erweitert, geprüft, auf einen neuen Stack übertragen oder als Vorgehen eingeführt werden soll.
---

# Feature-Katalog – Methodik und Vorgehensmodell

Ein **Feature-Katalog** ist eine geprüfte Übersicht aller Fähigkeiten eines Systems. Er zeigt fachlich, *was* das
System kann, und technisch, *wo* das steckt und *womit* es belegt ist. Er gilt als geprüft, weil jede Aussage
entweder aus dem System abgeleitet oder durch einen bestandenen Test belegt ist. Was keines von beidem ist, steht
sichtbar im **Prüfbestand**.

Diese Datei beschreibt den **technologieneutralen Kern**: Begriffe, Grundsätze, Vorgehensmodell, Reifegrade und Rollen.
Alles Stack-Spezifische steht in **Profilen**:

| Datei | Inhalt | Lesen, wenn … |
|---|---|---|
| [vorgehen/README.md](vorgehen/README.md) | **Wiederverwendbarer Ablaufplan:** 7 Schritte mit Gate-Checks, Vorlagen, Agenten-Aufträgen; `vorgehen/scaffold.sh <projekt>` legt das Gerüst an | du in einem Projekt loslegst – **Einstieg** |
| [references/vorgehensmodell.md](references/vorgehensmodell.md) | Phasen mit Eingaben, Tätigkeiten, Ergebnissen und Gates, Varianten, Rollen, Kennzahlen | du den Katalog einführst oder eine Phase abschließt |
| [references/datenmodell.md](references/datenmodell.md) | YAML-Schema (`catalog.yaml`, Features, Prüfbestand, Vergleich), Schnittstellenarten | du YAML schreibst oder das Schema baust |
| [references/nachweisregeln.md](references/nachweisregeln.md) | Akzeptanzkriterien, Nachweisregeln N1–N9, Nachweisstufen, statische Testprüfung | du Nachweise einträgst oder prüfst |
| [references/werkzeug.md](references/werkzeug.md) | Architektur Kern + Adapter, Prüfregeln, Ansicht, CI, Selbstbeschreibung | du das Werkzeug baust oder erweiterst |
| [references/profile/](references/profile/) | `python.md`, `java-spring.md`, `javascript-typescript.md`, `ot-industrie.md`, `_vorlage.md` | du einen konkreten Stack bearbeitest oder ein neues Profil anlegst |

Schreibe Katalogtexte und Antworten in der Sprache des Projekts bzw. des Nutzers.

---

## 1. Begriffe (Metamodell)

```
Landschaft ─┬─ Dienst (optional, bei mehreren Repositories/Deployables)
            └─ Bereich ── Gruppe ── Feature ─┬─ Akzeptanzkriterium (effekt | regel) ◄── deckt ── Nachweis ──► Testfall ──► Testergebnis
                 │                            ├─ Bedienweg (web, api, messaging, batch, cli, feldbus, entwicklung …)
                 │                            └─ Bestandteil ──► Schnittstellenart (endpoint, event, job, command, uiRoute, …)
                 └─ owns: Präfixe je Schnittstellenart
```

| Begriff | Bedeutung |
|---|---|
| **Feature** | Eine nutzbare Fähigkeit aus Sicht einer Rolle. Nicht ein Endpunkt, nicht ein Modul, nicht eine Klasse. |
| **Bereich / Gruppe** | Fachliche Gliederung. Ein Bereich beansprucht über `owns` Präfixe von Bestandteilen. |
| **Bestandteil** | Ein automatisch erkennbares technisches Element, über das eine Fähigkeit erreichbar ist, z. B. `POST /v1/orders`, Routing-Key `order.created`, ein Cron-Job, ein CLI-Befehl, ein OPC-UA-Knoten oder ein exportiertes Bibliotheks-Symbol. |
| **Schnittstellenart** | Typ eines Bestandteils mit eigener Erkennung und Präfix-Regel. Sie ist im Katalog **konfigurierbar**, nicht fest verdrahtet. |
| **Bedienweg** | Wie eine Rolle das Feature nutzt. Jeder Bedienweg zählt gleich; ein Feature, das nur über die API erreichbar ist, ist nicht „unvollständig“. |
| **Akzeptanzkriterium** | Prüfbare Aussage über einen Effekt (`effekt`) oder eine fachliche Regel/Grenze (`regel`, optional mit Fehlercode). Es verbindet die Beschreibung mit dem Test. |
| **Nachweis** | Ein Verweis auf einen Testfall plus die Kriterien, die dieser Test abdeckt (`covers`). |
| **Prüfbestand** | Fähigkeiten, die existieren, aber (noch) nicht vollständig nachgewiesen, deaktiviert oder unvollständig sind, jeweils mit Grund. |
| **Profil** | Ein Stack-Adapter: Erkennung der Bestandteile, Lesen der Testberichte, Ermitteln des Testkörpers, Zusicherungsmuster, Aufruf-Heuristik. |
| **Exportdatei** | Eingecheckte, per Test aktuell gehaltene Liste von Bestandteilen aus dem laufenden System, z. B. OpenAPI, Routen, Knoten oder Befehle. |

---

## 2. Grundsätze

| Nr. | Grundsatz |
|---|---|
| G1 | **Eine Quelle der Wahrheit:** Der Katalog liegt als YAML unter `catalog/` im Repository. Ansicht, JSON und Statistik werden erzeugt, nie von Hand gepflegt. |
| G2 | **Nur Nachgewiesenes im Katalog:** Jedes Feature hat Akzeptanzkriterien. Jedes Kriterium hat einen Test, der die Fähigkeit auslöst, Effekt oder Regel zusichert und im letzten Lauf **bestanden** hat. Alles andere gehört in den Prüfbestand. Ein grüner Test allein ist kein Nachweis. |
| G3 | **Die Prüfung erfindet nichts:** Das Werkzeug meldet (Unzugeordnetes, tote Verweise, fehlende Nachweise), legt aber nie selbst Features an und schreibt keine Kriterien. |
| G4 | **Das System bleibt unverändert:** keine Annotationen und keine Abhängigkeit im Produktivcode. Neu sind nur Tests, Exportdateien, Werkzeug, CI und Doku. |
| G5 | **Ableiten statt abschreiben:** Rollen, Endpunkt-Beschreibungen, Testergebnisse und aufrufende Tests werden gelesen, nicht kopiert. Von Hand steht im YAML nur, was sich nicht ableiten lässt: Zuschnitt, Nutzen, Regeln, Kriterien und die Zuordnung der Nachweise. |
| G6 | **Zwei Ebenen je Feature:** eine fachliche Ebene für Produkt, Fachbereich und Betrieb und eine technische für die Entwicklung. |
| G7 | **Technologieneutraler Kern, austauschbare Profile:** Datenmodell, Regeln und Ansicht kennen keinen Stack. Alles Stack-Spezifische steckt im Profil. Mehrere Profile dürfen in einem Katalog zusammenwirken, z. B. Python-Backend, JS-Frontend und Node-RED-Nodes. |
| G8 | **Vollständigkeit ist prüfbar:** Jeder erkannte Bestandteil ist einem Feature zugeordnet, steht im Prüfbestand oder ist begründet ausgenommen. |
| G9 | **Kontinuierlich, nicht einmalig:** Der Katalog wird in jeder Änderung mitgepflegt und in jedem CI-Lauf geprüft. Ein veralteter Katalog ist ein Fehler, keine Dokumentationsschuld. |
| G10 | **Ehrlich vor vollständig:** Ein offenes Kriterium im Prüfbestand ist besser als ein Scheinnachweis. |

---

## 3. Vorgehensmodell im Überblick

Die Phasen werden **je Bereich** durchlaufen, nicht als Wasserfall für das ganze System. ★ = Abstimmung mit
Nutzer/Produktverantwortung (Gate). Details zu jeder Phase stehen in [references/vorgehensmodell.md](references/vorgehensmodell.md).

| Phase | Ziel | Ergebnis | Gate ★ |
|---|---|---|---|
| **0 Klären** | Rahmen festlegen | Steckbrief: Zielgruppe, Rollen, Bedienwege, Schnittstellenarten, Testarten als Nachweis, Profile, Dienste, Vergleichssystem | Steckbrief bestätigt |
| **1 Inventar** | Bestandteile automatisch erkennen | Exportdateien bzw. Erkennung je Schnittstellenart, Rohliste | — |
| **2 Gliedern** | Fachliche Taxonomie | `catalog.yaml` mit Bereichen, Gruppen, `owns`, Ausnahmen; es gibt keinen unbeanspruchten Bestandteil | Taxonomie bestätigt |
| **3 Werkzeug** | Prüfen und Anzeigen automatisieren | Kern, Profil(e), Testberichte in der CI, erste Ansicht | — |
| **4 Pilot** | Zuschnitt und Nachweis-Strenge kalibrieren | Ein Bereich vollständig katalogisiert, Ansicht vorgeführt | Zuschnitt und Strenge bestätigt |
| **5 Ausrollen** | Alle Bereiche katalogisieren | Fehlende Tests geschrieben oder Einträge im Prüfbestand; alle Bereiche `katalogisiert` | Abnahme (Abschnitt 6) |
| **6 Betreiben** | Katalog lebt mit dem System | CI-Gate, Pflegeregeln in der Definition of Done, Kennzahlen, Doku | regelmäßiges Review des Prüfbestands |

**Varianten** (Details im Vorgehensmodell):
- **Brownfield** (Standardfall): Das System existiert, der Katalog wird von innen nach außen aufgebaut, mit Inventar → Gliedern → Nachweisen.
- **Greenfield / Katalog-first:** Feature und Akzeptanzkriterien entstehen *vor* dem Code und dienen als Spezifikation (ATDD). Bis der Nachweis besteht, steht das Feature im Prüfbestand mit `state: geplant`.
- **Landschaft:** Es gibt einen Katalog je Produktlandschaft und nicht je Dienst. Jeder Dienst liefert Exportdateien und Testberichte als CI-Artefakt. Bestandteile werden mit dem Dienst qualifiziert (`dienst:…`).
- **Eingeschränkter Zugang:** Bei privaten Diensten, fehlender CI oder Testumgebungen ohne Hardware wird nicht geraten. Der Bereich bleibt `offen`, und Lücken werden mit Quelle gekennzeichnet.

---

## 4. Reifegrade

Ein Bereich oder der ganze Katalog lässt sich einer Stufe zuordnen. Das macht Fortschritt planbar und erlaubt, für
kleine Projekte bewusst auf einer niedrigeren Stufe zu bleiben (Tailoring).

| Stufe | Name | Erreicht, wenn … |
|---|---|---|
| 0 | Keiner | Es gibt keinen Katalog, oder er ist nur Prosa. |
| 1 | **Inventarisiert** | Alle Bestandteile werden erkannt und sind einem Bereich zugeordnet (`UNOWNED` = 0). |
| 2 | **Beschrieben** | Jeder Bestandteil gehört zu einem Feature mit fachlicher und technischer Ebene oder ist begründet ausgenommen (`UNASSIGNED` = 0). |
| 3 | **Nachgewiesen** | Jedes Kriterium hat einen im letzten CI-Lauf bestandenen Nachweis, und die statische Prüfung findet keinen Fehler. |
| 4 | **Belastbar** | Warnungen sind per Review geklärt, für Kernfeatures laufen Mutationstests, und der Prüfbestand wird regelmäßig abgebaut. |
| 5 | **Steuernd** | Der Katalog treibt Planung, Release Notes, Vergleiche mit anderen Systemen und Onboarding, und neue Features entstehen Katalog-first. |

Empfehlung: Stufe 3 für jeden Bereich mit `status: katalogisiert`, Stufe 4 für Kernbereiche.

---

## 5. Arbeitsweise als LLM-Agent

1. **Profil bestimmen:** Erkenne den Stack (Build-Dateien, Frameworks, Testwerkzeuge) und lies das passende Profil.
   Gibt es keines, lege nach `references/profile/_vorlage.md` ein neues an, bevor du das Werkzeug baust.
2. **Phase 0 nie überspringen:** Lege dem Nutzer einen Steckbrief mit *Vorschlägen* vor (Rollen, Bedienwege,
   Schnittstellenarten, Testarten) statt offener Fragen.
3. **Bestandteile zuerst automatisch erkennen** (Exportdatei per Test), erst dann gliedern. Gliedere nie nach der
   Code-Struktur, sondern nach Fachlichkeit.
4. **Kriterien vor Nachweisen:** Formuliere erst, *was* gelten muss, dann suche oder schreibe den Test. Lies jeden
   Testkörper. Gib im PR je neuem Nachweis eine Zeile an:
   *Kriterium → auslösende Aktion → Zusicherung (Datei:Zeile)*.
5. **Fehlt ein Test**, schreibe ihn (Testcode ist erlaubt) oder trage das Feature mit Grund in den Prüfbestand ein.
   Ändere nie Produktivcode, um einen Nachweis zu ermöglichen; ein dafür nötiger Umbau ist eine eigene, abgestimmte
   Aufgabe.
6. **Klein und inkrementell:** Liefere einen Bereich pro Schritt, mit grünem `check`, und zeige die Ansicht nach dem
   Pilot.
7. **Nur erfundene Beispieldaten** in Texten und Tests.

---

## 6. Abnahme

- [ ] `check` läuft ohne Fehler; jede Warnung ist begründet.
- [ ] Alle Bereiche sind `katalogisiert`, und jeder Bestandteil ist zugeordnet oder begründet ausgenommen (Reifegrad ≥ 2).
- [ ] Jedes Feature hat Akzeptanzkriterien: mindestens einen Effekt, und jede Regel mit Fehlercode erscheint als Kriterium.
- [ ] Jedes Kriterium hat einen Nachweis, der die Fähigkeit auslöst, Effekt bzw. Regel zusichert und im letzten
      CI-Lauf bestanden hat (Reifegrad ≥ 3).
- [ ] Der Prüfbestand ist leer, oder jeder Eintrag hat `state` und `reason`.
- [ ] Die Ansicht liegt als CI-Artefakt vor, mit Suche, Filtern, Navigation und aufklappbarer Technik.
- [ ] Der Bereich `katalog` beschreibt das Werkzeug selbst.
- [ ] `docs/feature-katalog.md` beschreibt Aufbau, Regeln, Pflege und aktuellen Stand (Reifegrad je Bereich).
- [ ] Der Produktivcode ist unverändert.
- [ ] Die Pflegeregeln stehen in der Definition of Done, und `catalog/` ist per CODEOWNERS reviewpflichtig.
