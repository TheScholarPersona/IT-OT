## Feature-Katalog: <Bereich>

### Änderungen
- Neue Features: <Anzahl> · geänderte: <Anzahl> · in den Prüfbestand verschoben: <Anzahl>
- Neue Tests: <Anzahl> (nur Testcode, kein Produktivcode)

### Nachweise (Regel N7)
Eine Zeile je neuem oder geändertem Nachweis. Der Reviewer prüft jede Zeile gegen den Testcode.

| Feature | Kriterium | Auslösende Aktion | Zusicherung (Datei:Zeile) | geprüft |
|---|---|---|---|---|
| `bereich.feature` | `kriterium-id` | `POST /api/…` mit … | `tests/test_x.py:42` – `assert body["state"] == "CREATED"` | ☐ |

### Prüfbestand
| Feature | state | reason |
|---|---|---|

### Checkliste
- [ ] `check --reports …` ohne Fehler; Warnungen unten begründet
- [ ] Jedes Feature hat mindestens ein Effekt-Kriterium, und jede Regel mit Code ist ein Kriterium.
- [ ] Ich habe jeden Testkörper gelesen; kein Nachweis prüft nur Status oder Gemocktes.
- [ ] Bereich auf `katalogisiert` gesetzt (falls vollständig)

### Begründete Warnungen
-
