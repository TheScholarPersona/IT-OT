# Profil: Python (FastAPI, Django/DRF, Flask)

## 2. Erkennung
| `kind` | FastAPI | Django / DRF | Flask |
|---|---|---|---|
| `endpoint` | Test schreibt `app.openapi()` als JSON; oder `app.routes` (Methoden, Pfad, Endpunktfunktion) | `get_resolver().url_patterns` rekursiv (Pfad, Name, View) bzw. `manage.py spectacular` | `app.url_map.iter_rules()` |
| `stream` | `app.routes` mit `APIWebSocketRoute` | Channels-Routing (`URLRouter`) | Flask-Sock/-SocketIO-Handler |
| `uiRoute` | `TemplateResponse`-Routen, `StaticFiles`-Mounts | URL-Namen mit Template-Views | `render_template`-Views |
| `job` | APScheduler-Jobs, Celery (`app.tasks` im Test, Beat-Zeitplan) | Celery, `django-crontab` | Celery, RQ |
| `command` | click/typer-Gruppen (`cli.commands`), `argparse`-Subparser per `ast` | `django.core.management.get_commands()` | `app.cli.commands` |
| `event` | eigene Registrierung, Kafka/RabbitMQ-Topics (aiokafka, aio-pika, kombu) | Signals (zentral registrieren), Kafka/RabbitMQ | Blinker-Signals |

`settings`-Kandidaten sind Pydantic-Settings-Klassen und Umgebungsvariablen, die über `os.environ` per `ast` gelesen werden.

## 3. Rechte
FastAPI: `Depends`/`Security(scopes=…)` je Route (`route.dependant` im Test). DRF: `permission_classes`. Flask:
Dekoratoren statisch per `ast`. Am verlässlichsten ist ein Test, der je Endpunkt alle Rollen durchprobiert und die
Matrix exportiert.

## 4. Testberichte
`pytest --junitxml=reports/<art>-junit.xml`, je Testart eine eigene Datei (Marker `-m integration`, Verzeichnisse).
`classname` = Modulpfad mit Punkten plus ggf. Klasse (`tests.test_api.TestVersions`), `name` = Funktionsname, bei
Parametrisierung `name[param]`. Für die Zuordnung wird der Modulpfad aus `file` abgeleitet; `test` ist der
Funktionsname oder `Klasse::funktion`. pytest-bdd/behave → `scenario`, Playwright für Python → `e2e`.

## 5. Testkörper
Per `ast` nach `def`/`async def <name>` (ggf. in `class`) suchen, nicht per Textsuche. Der Körper ist der
Funktionsknoten plus aufgerufene Funktionen derselben Datei bzw. `conftest.py`-Fixtures, die der Test anfordert.

## 6. Zusicherungen
| Zusicherung | nur Status |
|---|---|
| `assert …`, `pytest.raises(…)`, `self.assertEqual`, `assertContains`, `pytest.approx` | nur `assert r.status_code == 200`, `assert x is not None`, `assert r.ok` |

## 7. Aufrufe
`client.post("/api/…")`, `client.get(f"/api/plcs/{plc.id}")` (f-String-Teile werden als Parameter gewertet),
`client.websocket_connect("/api/…/stream")`, Django `reverse("name", …)` über die exportierte URL-Namen-Tabelle,
`httpx`/`requests` gegen die Test-URL, `CliRunner().invoke(cli, ["check", …])` → `command`.

## 8. Werkzeug
`tools/feature_catalog/` als eigenes Paket (Dev-Abhängigkeit); Schema mit Pydantic v2
(`ConfigDict(extra="forbid")`); YAML mit `ruamel.yaml` (Round-Trip); Ansicht per `string.Template`/Jinja2; Tests mit
pytest; Aufruf `python -m feature_catalog check|build`.

## 9. CI
```yaml
- run: pytest -m "not integration" --junitxml=reports/unit-junit.xml
- run: pytest -m integration --junitxml=reports/integration-junit.xml
- run: pytest tools/feature_catalog/tests --junitxml=reports/catalog-junit.xml
- run: python -m feature_catalog check --reports reports
- run: python -m feature_catalog build --reports reports --out catalog/dist
- uses: actions/upload-artifact@v4
  with: { name: feature-katalog, path: catalog/dist }
```

## 10. Fallstricke
- `asyncio_mode`, nicht gestartete Event-Loops oder fehlende Dienste führen zu `skipped`, und das ist kein Nachweis.
- Pfadpräfixe aus `include_router(prefix=…)` und `root_path` werden einheitlich normalisiert.
- Fixtures, die den Effekt selbst herstellen (direkt in die DB schreiben, statt die API zu nutzen), verletzen N4.
