# Roadmap

Schwerpunkt bleibt die **virtuelle SPS**. Die weiteren Themen bauen auf deren Bausteinen auf
(ST-Compiler, S7-/OPC-UA-Anbindung, Versionsspeicher, Audit-Log).

## Phase 1 – vPLC ausbauen (Hauptfokus)

| Thema | Inhalt |
|---|---|
| Sprachumfang | ✔ ARRAY (eindimensional), ✔ eigene FUNCTION/FUNCTION_BLOCK, ✔ mehrere POUs je Quelltext, ✔ STRUCT/UDT (verschachtelt, Arrays von Strukturen), ✔ STRING[n]. Offen: mehrdimensionale Arrays, VAR_IN_OUT, Aufzählungstypen, WSTRING, Tasks mit unterschiedlichen Zykluszeiten |
| SCL-Kompatibilität | ✔ SCL-Quellen aus dem TIA Portal (OB, DBs, FBs, FCs, UDTs, `#lokal`, `"Global"`, `REGION`). Offen: Anlauf-/Weckalarm-OBs, Startwerte in Instanz-DBs, eigene S7-DB-Nummern, Namen mit Sonderzeichen, PLCopen-XML-Import |
| Isolation | Ein Container je vPLC (Docker/Kubernetes-Operator), Ressourcenlimits, Neustartrichtlinien |
| Echtzeitnähe | Zyklusmessung mit Jitter-Statistik, optional C-/WASM-Backend für den Compiler, PREEMPT_RT-Hosts |
| Retain | Remanente Variablen dauerhaft speichern (`RETAIN`), Wiederanlauf nach Stromausfall |
| Simulation | Prozesssimulation (Anlagenmodell) an die vPLC koppeln → virtuelle Inbetriebnahme |
| OPC UA | Security-Policies (Basic256Sha256), Benutzer/Zertifikate, Methoden für RUN/STOP |

## Phase 2 – Daten & Betrieb

| Thema | Ansatz |
|---|---|
| **Automatische SPS-Backups** | Edge-Agent liest von realen S7-Steuerungen zyklisch Datenbausteine (snap7) und bei S7-300/400 auch Bausteine; vollständige Projektsicherung von S7-1200/1500 über TIA Portal Openness auf einer Engineering-Station. Sicherungen landen im Versionsspeicher; Wiederherstellung per Knopfdruck, auch in eine vPLC zum Testen. |
| **Versionsverwaltung** | Heute: Versionen mit Autor, Kommentar, Hash, Diff, Rollback. Nächster Schritt: Git als Backend, Branches/Freigaben, Abgleich „Online-Stand ↔ gespeicherter Stand“ mit Alarm bei Abweichung. |
| **PLC-Telemetrie** | OPC-UA-Subscriptions und S7-Polling → Zeitreihen-DB (TimescaleDB/InfluxDB), MQTT/Sparkplug B, Zyklus- und Zustandsdaten der vPLCs als Kennzahlen. Schnellstart heute schon möglich: `vplc in` → Node-RED → InfluxDB/MQTT-Nodes. |

## Phase 3 – Engineering & DevOps

| Thema | Ansatz |
|---|---|
| **Cloud Engineering** | Browser-IDE mit Monaco-Editor, Syntaxhervorhebung, Autovervollständigung über einen ST-Language-Server (auf Basis des vorhandenen Parsers), Online-Beobachtung im Editor, Haltepunkte in der vPLC. |
| **Industrial DevOps** | `vplc check` und ST-Unit-Tests (Testfälle laufen in einer frischen vPLC) in GitHub/GitLab-Pipelines; Deployment-Pipelines mit Freigabe-Workflow vom Test (vPLC) zur realen Steuerung. |
| **KI-Codeanalyse** | ST/SCL-Code mit einem LLM (z. B. Claude-API) erklären und dokumentieren: Bausteinbeschreibungen, Signalfluss, Schrittketten als Diagramm, Hinweise auf Risiken (z. B. fehlende Verriegelungen). Ergebnis als Kommentar/Doku in der Versionsverwaltung. |

## Phase 4 – Zugriff & Sicherheit

| Thema | Ansatz |
|---|---|
| **Remote Access** | Edge-Gateway baut ausschließlich ausgehende Verbindungen auf (WireGuard oder mTLS-Tunnel), Zugriff zeitlich begrenzt und pro Sitzung freigegeben, Sitzungsprotokoll im Audit-Log. |
| **OT-Cybersecurity** | Asset-Inventar (Typ, Firmware) der Steuerungen, Abgleich mit Hersteller-Advisories (CSAF/Siemens ProductCERT), Protokollierung aller Programmänderungen und Schreibzugriffe, Rollen und Rechte, Ausrichtung an IEC 62443. Grundlage: bestehendes Audit-Log und Token-Authentifizierung. |

## Querschnitt

* Benutzerverwaltung mit OIDC/SSO, Rollen (Betrachter, Bediener, Programmierer, Admin)
* Mandantenfähigkeit (Werke/Linien), PostgreSQL statt Dateispeicher
* Signierte Audit-Einträge (Hash-Kette) für Manipulationssicherheit
