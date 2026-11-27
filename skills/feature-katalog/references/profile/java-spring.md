# Profil: Java / Spring Boot (auch Microservice-Landschaften)

## 2. Erkennung
| `kind` | Bevorzugt → Ausweichweg |
|---|---|
| `endpoint` | **springdoc-openapi:** `@SpringBootTest` ruft `/v3/api-docs` ab und schreibt die Datei → **`RequestMappingHandlerMapping`** im Test (alle `RequestMappingInfo` mit Methoden, Pfaden, Controller) → statisch per **JavaParser** (`@RequestMapping`/`@GetMapping`… inkl. Klassen-Präfix und aufgelöster Konstanten) |
| HATEOAS | Index-/Link-Endpunkte als eigene Bestandteile oder begründete Ausnahme; Links sind keine Endpunkte |
| `event` (intern) | per `ApplicationEventPublisher.publishEvent(...)` veröffentlichte Klassen; `@EventListener`, `@TransactionalEventListener` (JavaParser oder ClassGraph im Test) |
| `event` (Messaging) | `@RabbitListener`, `RabbitTemplate.convertAndSend(exchange, routingKey, …)`, `@KafkaListener(topics)`, Spring Cloud Stream `spring.cloud.stream.bindings.*`; Bestandteil = Exchange + Routing-Key bzw. Topic, `match: dot` |
| `job` | `@Scheduled`, Quartz-Jobs, Spring-Batch-`Job`-Beans |
| `uiRoute` | Thymeleaf-`@Controller` mit View-Namen, oder Routen des getrennten Frontends (anderes Profil) |
| `command` | Spring Shell `@ShellMethod`, `CommandLineRunner` mit Argumenten |

`settings`-Kandidaten sind `@ConfigurationProperties`-Klassen.

## 3. Rechte
Die Rollen kommen aus `@PreAuthorize`/`@Secured`/`@RolesAllowed` (statisch) und aus der `SecurityFilterChain` mit
`requestMatchers(...).hasRole(...)`. Am verlässlichsten ist ein Test, der die Rechte-Matrix je Endpunkt exportiert.

## 4. Testberichte
Surefire `target/surefire-reports/TEST-*.xml` (Unit), Failsafe `target/failsafe-reports/TEST-*.xml` (`*IT`), Gradle
`build/test-results/<task>/TEST-*.xml`. `classname` ist der voll qualifizierte Klassenname, `name` der Methodenname bzw.
`@DisplayName`, bei `@ParameterizedTest` mit dem Zusatz `[1] …`. Für die Zuordnung wird der Klassenname aus `file`
abgeleitet (Pfad unter `src/test/java` → Paket.Klasse) und `test` gegen `name` verglichen (exakt, ohne
Parameter-Zusatz, oder über den `@Nested`-Pfad). Cucumber/JBehave → `scenario`.

## 5. Testkörper
JavaParser: Methode mit `@DisplayName("…")` oder Namen `<name>` finden; der Körper umfasst private Helfer derselben
Klasse und `@BeforeEach` nur, wenn diese den Effekt **nicht** selbst herstellen.

## 6. Zusicherungen
| Zusicherung | nur Status |
|---|---|
| `assertThat`, `assertEquals`, `assertThrows`, MockMvc `andExpect(jsonPath(…))`, RestAssured `.body(…)`, `verify` (nur N5-konform) | nur `andExpect(status().isOk())`, `.statusCode(200)`, `assertNotNull` |

## 7. Aufrufe
MockMvc `perform(get("/v1/…"))`, `post(API_X + "/{id}", id)`; RestAssured `.when().post("/v1/…")`; WebTestClient
`.post().uri("/v1/…")`; `TestRestTemplate.postForEntity(…)`. Paketweite `static final String`-Konstanten werden
aufgelöst. **Spring REST Docs** sind die beste Quelle: `target/generated-snippets/<name>/http-request.adoc` liefert
Methode und Pfad je Test.

## 8. Werkzeug
Ein eigenes Maven-/Gradle-Modul `feature-catalog`, das nicht im Boot-JAR landet, **oder** das Python-Werkzeug, wenn das
Team Python ohnehin nutzt. Schema mit Java-Records + Jackson (`FAIL_ON_UNKNOWN_PROPERTIES`) + Bean Validation; YAML mit
`jackson-dataformat-yaml` (nur lesen); JavaParser (Lizenz prüfen); Tests mit JUnit 5.

## 9. CI
```yaml
- run: ./mvnw -B verify
- uses: actions/upload-artifact@v4
  with:
    name: junit
    path: |
      **/target/surefire-reports/TEST-*.xml
      **/target/failsafe-reports/TEST-*.xml
      **/target/generated-snippets/**
- run: ./mvnw -B -pl feature-catalog exec:java -Dexec.args="check --reports reports"
```

## 10. Fallstricke
- `@Disabled` und fehlendes Docker (Testcontainers) führen zu `skipped`, und das ist kein Nachweis.
- `server.servlet.context-path` und Versionspräfixe werden normalisiert.
- Actuator, Swagger-UI und Admin werden als Ausnahmen geführt.
- Veraltete `target/`-Berichte führen zu `EVIDENCE_NOT_RUN`; vor dem Prüfen frisch bauen.
- Landschaft (z. B. OpenWMS): Bestandteile werden mit `dienst:` qualifiziert, und jeder Dienst lädt Exportdateien und
  Berichte als Artefakt hoch.
