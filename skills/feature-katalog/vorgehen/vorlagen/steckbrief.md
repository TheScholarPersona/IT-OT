# Steckbrief Feature-Katalog: <System>

> Schritt 1 des Vorgehens. Vorschläge eintragen und markieren, was bestätigt ist (✅) und was offen ist (❓).

| | |
|---|---|
| Stand | <JJJJ-MM-TT> |
| Bestätigt durch | <Rolle, nicht Person, falls der Steckbrief öffentlich ist> |
| Profil(e) | <python / java-spring / javascript-typescript / ot-industrie / neu> |

## 1. Zielgruppe
Wer liest den Katalog, und wofür?

| Zielgruppe | Nutzt den Katalog für | |
|---|---|---|
| Produktteam | Überblick, Planung, Lücken | ❓ |
| Entwicklung | Wo steckt was, was ist belegt | ❓ |

## 2. Rollen
Wer nutzt das System? Woher werden die Rollen abgeleitet (Code, Konfiguration, von Hand)?

| Rolle (ID) | Beschreibung | Quelle | |
|---|---|---|---|
| | | | ❓ |

## 3. Bedienwege
| Bedienweg (ID) | Beschreibung | |
|---|---|---|
| `web` | Weboberfläche | ❓ |
| `api` | HTTP-API | ❓ |
| `entwicklung` | nur für Entwickler (Werkzeuge, Katalog selbst) | ✅ |

## 4. Schnittstellenarten
| `kind` | Beispiel | Erkennung (Export-Test / statisch) | `match` | |
|---|---|---|---|---|
| `endpoint` | `POST /api/…` | | `path` | ❓ |

**Erkennungslücken:** <was sich nicht automatisch erkennen lässt, und warum>

## 5. Nachweise
| Testart | zählt als Nachweis | Bericht | |
|---|---|---|---|
| `unit` | nur für reine Logik | `reports/unit-junit.xml` | ❓ |
| `integration` | ja | `reports/integration-junit.xml` | ❓ |
| `e2e` | ja | | ❓ |
| `manual` | nein / nur mit Protokoll | — | ❓ |

## 6. Struktur
- Dienste/Repositories: <eins | Liste>
- Vergleichssystem: <keins | System, Version, vollständig ja/nein>
- Zielreifegrad: <3 pauschal | je Bereich>
- Pilotbereich (Vorschlag): <id, Begründung>

## 7. Offene Fragen
1.
