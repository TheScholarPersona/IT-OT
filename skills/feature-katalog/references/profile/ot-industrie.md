# Profil: OT / Industrie (SPS-Laufzeiten, IEC 61131-3, Feldbus- und Industrieprotokolle)

Dieses Profil gilt für Software, die Steuerungslogik ausführt oder über Industrieprotokolle erreichbar ist, z. B.
virtuelle SPS, Gateways, SCADA/HMI-Backends oder Edge-Dienste. Es ergänzt das Profil der Implementierungssprache
(z. B. Python für eine Laufzeit in Python) um OT-spezifische Schnittstellenarten.

## 2. Erkennung
| `kind` | Bestandteil | Bevorzugt (Export-Test) | Ausweichweg |
|---|---|---|---|
| `opcuaNode` | Knoten-ID (`ns=2;s=<Name>`), Methoden | Test startet den Server, browst den Adressraum mit einem Client und exportiert Knoten, Datentyp und Zugriff | statische Analyse der Knotenerzeugung |
| `s7Area` | Bereich + Adresse (`DB1.DBX0.0`, `DB1.DBW2`) | Test exportiert das DB-Layout aus der Laufzeit | Layout-Berechnung im Code |
| `modbusRegister` | Coil/Register-Bereich | Test liest die Registerkarte aus | Mapping-Tabelle |
| `mqttTopic` | Topic (`match: glob` oder `dot` mit `/`) | Test abonniert `#` und protokolliert Topics | Konstanten im Code |
| `stlang` | Sprachkonstrukt bzw. Bibliotheksbaustein (`TON`, `CTU`, `IF`, `CASE`) | Test exportiert die Liste der registrierten Bausteine/Funktionen | Lexer-Schlüsselwörter, Bibliotheksregister |
| `mode` | Betriebsart/Zustandsübergang (`STOP→RUN`, Warm-/Kaltstart) | Zustandsautomat im Test aufzählen | Enum im Code |

Bei Sprachfeatures (Compiler/Interpreter) gliedert sich der Katalog nach **Sprachumfang**: Datentypen,
Kontrollstrukturen, Standardbausteine und Fehlerverhalten. Jeder registrierte Baustein ist ein Bestandteil; ein Feature
bündelt fachlich Zusammengehöriges (z. B. „Zeitglieder TON/TOF/TP“) mit je einem Kriterium pro Baustein.

## Bedienwege
Typisch sind `feldbus` (S7, Modbus, PROFINET), `opcua`, `integration` (Node-RED, MQTT), `engineering` (Editor,
Download, Diagnose), `web` (HMI) und `api`.

## Nachweise
- **Effekte zyklisch beobachten:** Ein Kriterium beschreibt einen Zustand nach *n* Zyklen oder nach einer simulierten
  Zeit (z. B. „Nach 3 s Simulationszeit ist `Q` TRUE“). Tests nutzen eine steuerbare Uhr statt `sleep`.
- **Über das Protokoll beobachten** (N5): Der Wert wird per S7-/OPC-UA-Client gelesen, nicht über die interne
  Variablentabelle, wenn das Feature den Protokollzugang verspricht.
- **Laufzeitfehler als Regel:** z. B. „Division durch 0 versetzt die CPU in STOP und schreibt einen Eintrag in den
  Diagnosepuffer“ mit `code` aus dem Diagnosepuffer.
- **Hardware-in-the-Loop** (`hil`) ist nur mit dem Ergebnis aus einem freigegebenen Lauf zulässig; fehlt die
  Testumgebung, gilt `skipped`, und das ist kein Nachweis.
- **Echtzeit/Zykluszeit:** Grenzen als Regel-Kriterium formulieren (z. B. Zykluszeitüberschreitung → Meldung) und nicht
  als Leistungsversprechen, das nur auf bestimmter Hardware gilt.

## Abgrenzung und Sicherheit
- Sicherheitsgerichtete Funktionen (IEC 61508/62061) werden nicht über diesen Katalog freigegeben. Der Katalog darf sie
  aufführen, verweist aber auf die Sicherheitsnachweise.
- Testdaten: nur erfundene Anlagen, Adressen und Variablennamen.

## Fallstricke
- Ports von Protokollservern in Tests dynamisch vergeben; feste Ports führen zu Konflikten und damit zu `error`.
- Zeitabhängige Tests ohne simulierte Uhr sind instabil, und ein instabiler Test ist kein belastbarer Nachweis.
- Adressräume ändern sich mit dem geladenen Programm. Exportiert wird deshalb für ein **festes Referenzprogramm**
  (z. B. aus `examples/`).
