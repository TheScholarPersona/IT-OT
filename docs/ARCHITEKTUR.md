# Architektur

```
        Browser (Web-UI)      Node-RED (vplc-Nodes)   CI/CD, Skripte
                │                     │                     │
                │ REST                │ REST + WebSocket    │
              ┌─▼─────────────────────▼─────────────────────▼──┐
              │  vPLC-Manager (FastAPI)                        │
              │  • PLCManager: Instanzen, Ports, Lebenszyklus  │
              │  • Store: Programmversionen, Audit-Log (Datei) │
              └───────┬───────────────────┬────────────────────┘
                      │                   │
           ┌──────────▼───────┐  ┌────────▼─────────┐
           │ VirtualPLC "A"   │  │ VirtualPLC "B"   │   … je Instanz:
           │  Scan-Zyklus     │  │                  │
           │  ┌────────────┐  │  │                  │
           │  │ ST-Programm│  │  │                  │
           │  └────────────┘  │  │                  │
           │  S7-Endpoint ────┼──┼── TCP 10102+ ────┼──►  HMI / SCADA / snap7 / PLC4X
           │  OPC-UA-Endpoint ┼──┼── TCP 4840+  ────┼──►  OPC-UA-Clients, MES, Historian
           └──────────────────┘  └──────────────────┘
```

## Module

| Modul | Aufgabe |
|---|---|
| `vplc/st/lexer.py`, `parser.py`, `ast.py` | Structured Text → abstrakter Syntaxbaum. Fehler mit Zeile und Spalte. SCL-Quellen aus dem TIA Portal werden automatisch erkannt; OB, DBs, FBs, FCs und UDTs werden zu einem Programm zusammengesetzt (globale DBs in allen Bausteinen sichtbar, DB-Startwerte als Startzuweisungen). |
| `vplc/st/compiler.py` | Semantische Prüfung (sammelt *alle* Fehler) und Übersetzung des AST in Python-Closures. Kein `eval`, kein generierter Python-Quelltext. Je Instanz eines eigenen Funktionsbausteins wird dessen Rumpf an die Instanzvariablen gebunden übersetzt; Funktionen einmal, Rekursion wird abgelehnt. |
| `vplc/st/stdlib.py` | IEC-Funktionsbausteine (Timer, Zähler, Flanken, Bistabile) und Funktionen. |
| `vplc/types.py` | Elementare Datentypen: Wertebereich/Überlauf, REAL als float32, STRING[n], S7-Kodierung (Big Endian). |
| `vplc/datatypes.py` | Zusammengesetzte Typen (ARRAY, STRUCT) und Zugriffspfade (`Lager[3].Menge`) – gemeinsame Grundlage für Compiler, S7, OPC UA und API. |
| `vplc/runtime.py` | `VirtualPLC`: Betriebsarten, Scan-Schleife, Zykluszeitmessung, Diagnosepuffer, Warm-/Kaltstart. |
| `vplc/io/s7.py` | S7comm-Server (python-snap7) mit DB-Layout wie ein nicht optimierter TIA-Portal-DB. |
| `vplc/io/opcua.py` | OPC-UA-Server (asyncua) mit Variablen- und Statusknoten. |
| `vplc/manager/` | REST-API, Persistenz, Versionsverwaltung, Audit-Log, Wiederherstellung nach Neustart. |
| `vplc/web/` | Weboberfläche (HTML/CSS/JS ohne Build-Schritt). |
| `node-red/` | Node-RED-Paket: `vplc in` (WebSocket-Stream), `vplc out`, `vplc control`, Konfigurations-Node. |

## Scan-Zyklus

1. **Eingänge übernehmen** – Schreibzugriffe von S7-Clients (Vergleich DB-Bytes gegen Schattenkopie),
   OPC-UA-Clients und REST-API werden gesammelt und *vor* dem Zyklus übernommen.
   Das Programm sieht damit während eines Zyklus konsistente Werte (Prozessabbild-Prinzip).
2. **Programm ausführen** – mit Zykluszeitüberwachung (Watchdog); Endlosschleifen führen zu STOP.
3. **Ausgänge veröffentlichen** – Werte in den S7-DB schreiben; OPC UA wird im Intervall
   `io_sync_ms` (Standard 50 ms) abgeglichen, um den Zyklus kurz zu halten.

Die Schleife plant gegen absolute Zeitpunkte, damit sich keine Drift aufsummiert; verpasste
Zeitpunkte zählen als *Überschreitung*.

## Designentscheidungen

* **Eigener Interpreter statt Fremd-Runtime** – volle Kontrolle über Semantik, Diagnose und
  Integration; keine Lizenzabhängigkeit. Der Compiler erzeugt Closures, ein typischer Zyklus
  der Beispielprogramme dauert 10–30 µs.
* **Ein Prozess, viele Instanzen (asyncio)** – einfach zu betreiben. Für harte Isolation und
  Skalierung ist ein Container je vPLC vorgesehen (siehe Roadmap); die `VirtualPLC`-Klasse ist
  dafür bereits eigenständig.
* **Nicht optimiertes DB-Layout** – absolute Adressen sind das, was bestehende HMIs und
  Treiber (snap7, node-s7, PLC4X, viele SCADA-Systeme) erwarten.
* **Warmstart beim Download** – Variablen mit gleichem Namen und Typ sowie
  FB-Instanzen behalten ihre Werte; so lässt sich im laufenden Betrieb nachladen.
* **Node-RED über die Manager-API statt nur über Feldprotokolle** – so stehen auch RUN/STOP,
  Downloads, Versionen und das Audit-Log zur Verfügung, und vPLCs werden per Name statt per
  Port angesprochen. Der Stream sendet nur Änderungen; der Manager prüft im eingestellten
  Intervall (≥ 20 ms). Für unveränderte Flows gegen reale Steuerungen bleiben OPC UA und S7 nutzbar.
* **Datei-Persistenz** – Versionen als JSON (inkl. SHA-256), Audit als JSON Lines.
  Austauschbar gegen PostgreSQL/Git, sobald Mandantenfähigkeit benötigt wird.

## Grenzen von v0.1

* Keine mehrdimensionalen Arrays, kein VAR_IN_OUT, keine Aufzählungstypen, kein WSTRING;
  Arrays und Strukturen nicht als Baustein-Ein-/Ausgang oder Rückgabewert.
* Kein Echtzeitbetriebssystem: Jitter im Bereich von Millisekunden; nicht für
  harte Echtzeit oder Sicherheitsfunktionen.
* S7: nur Datenbaustein-Zugriff (keine Bausteinliste, kein Upload/Download über S7).
* OPC UA ohne Verschlüsselung und Benutzerverwaltung.
