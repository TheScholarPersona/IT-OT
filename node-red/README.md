# node-red-contrib-it-ot-vplc

Node-RED-Nodes für die [IT-OT vPLC](../README.md): Variablen virtueller SPSen live lesen und
schreiben, Betriebszustand steuern und Programme laden – ohne eigene S7- oder OPC-UA-Konfiguration.

| Node | Zweck |
|---|---|
| **vplc in** | Meldet Variablenänderungen per WebSocket-Push (nur bei Änderung, mit automatischer Wiederverbindung) |
| **vplc out** | Schreibt eine Variable (`msg.topic`/Node-Einstellung) oder mehrere auf einmal (`msg.payload = {Name: Wert}`, alles oder nichts) |
| **vplc control** | RUN, STOP, Kaltstart, Status, alle Variablen lesen, Programm prüfen/laden, Versionen auflisten/aktivieren |
| **vplc-server** | Konfiguration: Manager-URL, API-Token, Benutzername für das Audit-Log |

Getestet mit Node-RED 4.1 und 5.0, Node.js ≥ 18.

## Installation

```bash
cd ~/.node-red
npm install /pfad/zu/IT-OT/node-red      # oder: npm install node-red-contrib-it-ot-vplc-0.1.0.tgz
# Node-RED neu starten
```

Mit Docker Compose (im Repository-Wurzelverzeichnis) ist alles vorinstalliert:

```bash
VPLC_API_TOKEN=$(openssl rand -hex 24) docker compose up --build
# vPLC-Manager: http://localhost:8080   Node-RED: http://localhost:1880
```

Im Konfigurations-Node als URL `${VPLC_URL}` eintragen; das Token wird dann aus
`VPLC_API_TOKEN` übernommen, wenn das Feld leer bleibt.

## Beispiel

*Menü → Importieren → Beispiele → node-red-contrib-it-ot-vplc → tank-demo*

Voraussetzung: eine vPLC namens **Tank** mit dem Beispielprogramm `tank`
(Weboberfläche → Programm → Beispiel laden → In vPLC laden → RUN).

Der Flow zeigt RUN/STOP und Statusabfrage, Sollwerte einzeln und mehrere Variablen auf einmal
schreiben (mit Fehlerbehandlung über *catch*), Füllstand beobachten und Alarme ausfiltern.

## Nachrichten

**vplc in** (Ausgabe „je Variable“):

```json
{ "topic": "Fuellstand", "payload": 63.2, "plc": "Tank", "mode": "RUN", "initial": false }
```

**vplc out**:

```json
{ "topic": "Sollwert", "payload": 75 }
{ "payload": { "Automatik": false, "Pumpe": true } }
```

**vplc control** mit Aktion „aus msg.action“:

```json
{ "action": "download", "payload": "PROGRAM Tank ... END_PROGRAM", "comment": "Hysterese angepasst" }
```

Compilerfehler gehen an den *catch*-Node; `msg.errors` enthält Zeile, Spalte und Meldung.

## Alternative: direkt über OPC UA oder S7

Die vPLC spricht Standardprotokolle, deshalb funktionieren auch die bekannten Community-Nodes:

* **OPC UA** (`node-red-contrib-opcua`): Endpoint `opc.tcp://<host>:4840/vplc/`,
  Knoten `ns=2;s=<Variable>`, Security *None*.
* **S7** (`node-red-contrib-s7`): Rack 0, Slot 1, Port 10102 (bzw. der angezeigte Port),
  Adressen wie `DB1,X0.0` / `DB1,INT2` – die Registerkarte *Variablen* der Weboberfläche zeigt
  die S7-Adresse jeder Variable.

Die vPLC-Nodes sind vorzuziehen, wenn Node-RED auch RUN/STOP, Programm-Downloads oder das
Audit-Log nutzen soll oder die vPLC per Namen statt per Port/Adresse angesprochen werden soll.
Die direkten Protokolle sind sinnvoll, um einen Flow später unverändert gegen eine reale
Steuerung laufen zu lassen.

## Tests

```bash
npm install
npm test      # startet einen echten vPLC-Manager (Python) und eine Node-RED-Runtime
```
