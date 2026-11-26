# IT-OT vPLC

Virtuelle SPS als Software: Structured-Text-Programme (IEC 61131-3) laufen zyklisch wie auf
einer echten Steuerung und sind über **S7comm** und **OPC UA** erreichbar. Ein Manager mit
REST-API und Weboberfläche verwaltet beliebig viele vPLC-Instanzen inklusive
Programmversionen und Audit-Log.

> Status: **MVP / v0.1** – geeignet für Entwicklung, virtuelle Inbetriebnahme, HMI-/SCADA-Tests
> und Schulung. Nicht für sicherheitsgerichtete oder produktive Steuerungsaufgaben.

## Funktionen

| Bereich | Umfang in v0.1 |
|---|---|
| **Runtime** | Zyklische Bearbeitung (Eingänge lesen → Programm → Ausgänge schreiben), einstellbare Zykluszeit, Zykluszeitüberwachung, Betriebsarten RUN/STOP, Warm- und Kaltstart, Diagnosepuffer, Laufzeitfehler (z. B. Division durch 0) führen wie bei einer CPU in STOP |
| **Sprache** | Structured Text: `PROGRAM`, `VAR`/`VAR_INPUT`/`VAR_OUTPUT`/`VAR_TEMP`/`CONSTANT`, `IF`/`CASE`/`FOR`/`WHILE`/`REPEAT`/`EXIT`/`CONTINUE`/`RETURN`, alle Operatoren, Literale (`16#FF`, `T#1m30s`, `INT#5` …) |
| **Datentypen** | BOOL, SINT, INT, DINT, LINT, USINT, UINT, UDINT, ULINT, BYTE, WORD, DWORD, LWORD, REAL (32 Bit), LREAL, TIME – Überlauf wie auf der SPS |
| **Bibliothek** | TON, TOF, TP, R_TRIG, F_TRIG, CTU, CTD, CTUD, SR, RS; ABS, SQRT, LN, LOG, EXP, SIN…ATAN, MIN, MAX, LIMIT, SEL, MUX, SHL, SHR, TRUNC, alle `*_TO_*`-Konvertierungen |
| **S7comm** | snap7-kompatibler Server je vPLC, Variablen als nicht optimierter DB (`DB1.DBX0.0`, `DB1.DBW2` …), Rack 0 / Slot 1 |
| **OPC UA** | Server je vPLC, Knoten `ns=2;s=<Variable>` plus `_Status` (Mode, ScanCount, CycleTimeUs, Program) |
| **Manager** | REST-API, Web-UI mit Editor und Fehleranzeige, Live-Variablen, Beobachten/Steuern |
| **Versionen** | Jeder Download wird als Version gespeichert (Autor, Zeitpunkt, Kommentar, SHA-256), Diff, Rollback |
| **Audit** | Append-only-Protokoll aller Aktionen (Anlegen, Download, RUN/STOP, Variablenschreiben …) |

## Schnellstart

```bash
pip install -e ".[dev]"
vplc serve                 # http://127.0.0.1:8080
```

Oder mit Docker:

```bash
VPLC_API_TOKEN=$(openssl rand -hex 24) docker compose up --build
```

Dann in der Weboberfläche eine vPLC anlegen, unter *Programm* ein Beispiel laden (z. B. `ampel`),
**In vPLC laden** und **RUN** klicken.

### Verbinden

```python
import snap7                                 # S7comm
c = snap7.Client(); c.connect("127.0.0.1", 0, 1, 10102)
print(c.db_read(1, 0, 4))

from asyncua.sync import Client             # OPC UA
with Client("opc.tcp://127.0.0.1:4840/vplc/") as ua:
    print(ua.get_node("ns=2;s=Auto_Gruen").read_value())
```

Die S7-Adresse und den OPC-UA-Knoten jeder Variablen zeigt die Registerkarte *Variablen*.

### Kommandozeile

```bash
vplc check examples/ampel.st     # Syntax- und Semantikprüfung, z. B. für CI-Pipelines
```

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `VPLC_DATA` | `data` | Verzeichnis für Konfiguration, Programmversionen und Audit-Log |
| `VPLC_API_TOKEN` | – | Wenn gesetzt, verlangt die API `Authorization: Bearer <token>` |
| `VPLC_PROTOCOL_HOST` | `127.0.0.1` | Bind-Adresse für S7- und OPC-UA-Server (`0.0.0.0` für Netzwerkzugriff) |
| `VPLC_S7_BASE_PORT` | `10102` | Erster Port für S7comm (Port 102 erfordert Root-Rechte) |
| `VPLC_OPCUA_BASE_PORT` | `4840` | Erster Port für OPC UA |

## Sicherheitshinweise

* S7comm kennt keine Authentifizierung, OPC UA läuft in v0.1 ohne Security-Policy.
  Die Protokoll-Server binden daher standardmäßig nur an `127.0.0.1`.
  Im Netzwerk nur in segmentierten OT-Netzen betreiben (siehe [Roadmap](docs/ROADMAP.md)).
* Ohne `VPLC_API_TOKEN` ist die REST-API offen; der Benutzername im Audit-Log
  (`X-User`-Header) ist dann nicht authentifiziert.

## Entwicklung

```bash
pytest            # 40 Tests: Sprache, Funktionsbausteine, S7-Layout, S7/OPC-UA-End-to-End, REST-API
```

Aufbau und Designentscheidungen: [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) ·
Weitere Ausbaustufen: [docs/ROADMAP.md](docs/ROADMAP.md)
