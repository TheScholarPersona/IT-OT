# Profil: JavaScript / TypeScript (Node-Backends, Web-Frontends, Node-RED)

## 2. Erkennung
| `kind` | Bevorzugt → Ausweichweg |
|---|---|
| `endpoint` | NestJS: `SwaggerModule.createDocument` im Test; Express/Fastify: Router-Stack (`app._router.stack`, `fastify.printRoutes()`) im Test exportieren → statisch per TypeScript-Compiler-API/Babel (`app.get('/…')`) |
| `uiRoute` | Router-Konfiguration (React Router, Vue Router, Angular `Routes`, Next.js/Nuxt Dateisystem-Routen) |
| `event` | `EventEmitter`-Namen aus einer zentralen Konstante; Kafka/AMQP-Clients wie in anderen Profilen |
| `command` | `commander`/`yargs`-Befehle, `bin`-Einträge in `package.json` |
| `node` (Node-RED) | `RED.nodes.registerType("<typ>", …)` und `package.json` → `node-red.nodes`; Bestandteil = Node-Typ |
| `export` (Bibliothek) | öffentliche Exporte laut `package.json#exports` bzw. `.d.ts` (API Extractor) |

## 4. Testberichte
Jest `jest-junit`, Vitest `--reporter=junit`, Mocha `mocha-junit-reporter`, Playwright `--reporter=junit` (→ `e2e`),
Cypress `junit`-Reporter. `name` ist der verkettete `describe` › `it`-Titel; der Nachweis nennt den `it`-Titel oder
den vollständigen Pfad `describe > it`.

## 5. Testkörper
Den `it`/`test`-Aufruf mit passendem Titel per TypeScript-Compiler-API oder Babel-Parser finden; ersatzweise per
Klammerzählung den Block nach dem Titel. Lokale Helfer derselben Datei gehören dazu.

## 6. Zusicherungen
| Zusicherung | nur Status |
|---|---|
| `expect(…).toEqual/toMatchObject/toContain/toThrow`, `assert.*`, `should`, Playwright `toHaveText/toBeVisible` mit Fachinhalt | nur `expect(res.status).toBe(200)`, `toBeTruthy()`, `toBeDefined()`, `expect(page).toHaveURL` allein |

## 7. Aufrufe
`supertest(app).post("/api/…")`, `fetch(\`${base}/api/…\`, { method: "PUT" })`, `request.get("/…")`; Playwright
`page.goto("/…")` → `uiRoute`; Node-RED-Tests (`node-red-node-test-helper`) `helper.load(node, flow)` → `node`.

## 8. Werkzeug
Ein gemeinsames Werkzeug ist üblich: Im gemischten Repository liest das Python- oder Java-Werkzeug die JS-Berichte und
Exportdateien mit. Eine eigene TS-Umsetzung lohnt nur bei reinen JS-Projekten (Schema per zod/JSON-Schema, YAML per
`yaml`, Tests mit Vitest).

## 10. Fallstricke
- `it.skip`, `test.todo` und `.only`-Reste: `skipped` bzw. nicht gelaufen.
- Snapshot-Tests (`toMatchSnapshot`) sind nach N8 kein Nachweis ohne zusätzliche fachliche Zusicherung.
- Dynamische Titel (Template-Strings, `it.each`) werden ohne Parameter angegeben, und alle Instanzen müssen bestehen.
