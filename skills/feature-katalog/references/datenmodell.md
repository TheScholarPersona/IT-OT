# Datenmodell

```
catalog/
  catalog.yaml                 # Schnittstellenarten, Dienste, Bereiche, Gruppen, owns, Ausnahmen, Vergleichssysteme
  features/<bereich>.yaml      # Features je Bereich
  review.yaml                  # Prüfbestand (Feature-Format + state, reason)
  comparisons/<system>.yaml    # optional: Lücken gegenüber einem Vergleichssystem
  discovered/                  # Exportdateien (per Test erzeugt und aktuell gehalten)
docs/feature-katalog.md
```

## 1. `catalog/catalog.yaml`

```yaml
schemaVersion: 2
profiles: [python]                  # aktive Profile (Abschnitt Profile)

kinds:                              # Schnittstellenarten – konfigurierbar statt fest verdrahtet
  - id: endpoint
    title: HTTP-Endpunkt
    match: path                     # Präfix-Regel: path | dot | exact | glob
    source: catalog/discovered/openapi.json
  - id: stream
    title: WebSocket-Strom
    match: path
  - id: command
    title: CLI-Befehl
    match: exact
  - id: event
    title: Ereignis / Routing-Key
    match: dot
  - id: uiRoute
    title: Seite / Ansicht
    match: path

services:                           # nur bei mehreren Diensten
  - id: manager
    title: vplc-manager

channels: [web, api, cli, feldbus, integration, entwicklung]   # erlaubte Bedienwege
roles: [bediener, integrator, admin]                           # oder: aus dem Code abgeleitet (G5)

areas:
  - id: programme
    title: Programme
    summary: Steuerungsprogramme laden, versionieren und zurückrollen.
    status: katalogisiert           # offen | katalogisiert
    owns:
      endpoint: ["/api/plcs/{plc}/program", "/api/plcs/{plc}/versions"]
      command: ["check"]
    groups:
      - id: programme.versionen
        title: Versionen
        summary: Jeder Download wird nachvollziehbar gespeichert.

exclusions:
  endpoint:
    - { item: "GET /docs", reason: OpenAPI-Oberfläche, kein Feature }
```

### Präfix-Regeln (`match`)

| Regel | Passt | Passt nicht |
|---|---|---|
| `path` | `/v1/orders` auf `/v1/orders` und `/v1/orders/…` | `/v1/orders-export` |
| `dot` | `order.event` auf `order.event` und `order.event.created` | `order.events` |
| `exact` | nur der genaue Wert | — |
| `glob` | `ns=2;s=Tank_*` | — |

Bei mehreren Diensten wird ein Präfix mit `dienst:` qualifiziert (`manager:/api/plcs`). Pfadparameter werden vor dem
Vergleich normalisiert (`{id}`, `:id`, `<int:id>` → `{}`), ebenso Kontextpfad und Versionspräfix.

## 2. Feature (`catalog/features/<bereich>.yaml`)

```yaml
area: programme
features:
  - id: programme.rollback
    title: Programmversion zurückrollen
    group: programme.versionen
    summary: Stellt eine frühere Programmversion wieder her und lädt sie in die vPLC.
    description: |
      Fachliche Beschreibung ohne Code-Begriffe: wer, wann, wozu, mit welchem Ergebnis.
    roles: [admin]                         # weglassen, wenn aus dem Code ableitbar
    usage:
      - channel: web
        text: "Reiter *Versionen*, Schaltfläche **Wiederherstellen**."
      - channel: api
        text: "`POST /api/plcs/{plc}/versions/{n}/restore`"
    rules:
      - Nur im Zustand STOP möglich (`409`).
    dependsOn: [programme.download]
    technical:
      service: manager                     # Liste bei dienstübergreifenden Features
      components: [src/vplc/manager/service.py]
      parts:                               # Bestandteile je Schnittstellenart (kind-ID → Liste)
        endpoint: ["POST /api/plcs/{plc}/versions/{n}/restore"]
      emits: []                            # Ereignisse, die das Feature auslöst
      consumes: []
      settings: []                         # Konfigurationsschlüssel, die das Verhalten steuern
      notes: []
    acceptance:
      - id: version-aktiv
        kind: effekt
        text: Nach dem Zurückrollen ist Version 1 aktiv und als neue Version mit Verweis auf 1 protokolliert.
      - id: nur-in-stop
        kind: regel
        text: Im Zustand RUN wird das Zurückrollen abgelehnt.
        code: "409"
    evidence:
      - kind: integration
        file: tests/test_api.py
        test: test_restore_version_creates_new_version   # Testname laut Profil (Funktion, Methode, DisplayName, Titel)
        covers: [version-aktiv]
      - kind: integration
        file: tests/test_api.py
        test: test_restore_rejected_while_running
        covers: [nur-in-stop]
    comparisons: {}                        # { <system>: gleichwertig | besser | schlechter | fehlt-dort }
```

**Konventionen:** `id` = `<bereich>.<kebab-name>`, stabil, nie wiederverwendet. Werte mit Doppelpunkt stehen in
Anführungszeichen, mehrzeilige Werte mit `|`. Maschinelle Änderungen erfolgen nur per Round-Trip-Parser (Kommentare bleiben).

## 3. Prüfbestand (`catalog/review.yaml`)

Gleiches Format wie ein Feature plus:

| Feld | Werte |
|---|---|
| `state` | `geplant` (Katalog-first, noch nicht gebaut) · `unvollstaendig` (Fähigkeit nur teilweise vorhanden) · `deaktiviert` (vorhanden, abgeschaltet) · `nicht-nachgewiesen` (vorhanden, Kriterien ohne bestandenen Nachweis) · `nicht-einsehbar` (Code/Tests nicht zugänglich) |
| `reason` | Pflicht, ein Satz: warum, und was zum Nachweis fehlt |
| `owner` | optional: wer den Eintrag abbaut |

## 4. Vergleich (`catalog/comparisons/<system>.yaml`, optional)

```yaml
system: { id: wettbewerb-a, title: Wettbewerber A, version: "2025.2", complete: true }
gaps:                                      # Fähigkeiten, die dort vorhanden sind und hier fehlen
  - id: online-aenderung
    title: Programmänderung im RUN
    source: datenblatt                     # datenblatt | test | privat | hörensagen
```

Bei `complete: true` braucht jedes Feature eine Einstufung unter `comparisons` (`COMPARISON_MISSING`).
