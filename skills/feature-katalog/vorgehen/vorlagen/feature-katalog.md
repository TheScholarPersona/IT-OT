# Feature-Katalog

Der Katalog beschreibt, was dieses System kann, fachlich und technisch, und belegt jede Fähigkeit mit einem bestandenen
Test.

- **Quelle:** `catalog/` (YAML). Ansicht und Kennzahlen werden erzeugt, nie von Hand gepflegt.
- **Ansicht:** CI-Artefakt `feature-katalog` → `index.html`.
- **Methode:** Grundsätze, Nachweisregeln und Reifegrade (Verweis auf die Methodik bzw. den Skill).

## Lokal prüfen
```bash
# Tests mit Berichten erzeugen (je Testart), dann:
<werkzeug> check --reports reports
<werkzeug> build --reports reports --out catalog/dist
```

## Konventionen (aus dem Pilot)
- Zuschnitt: <was ein Feature ist, Beispiele für zu fein/zu grob>
- Kriterien: <Detailgrad, Beispiele>
- Testnamen: <Konvention>

## Pflege
Siehe Definition of Done. Fehlt ein Nachweis, kommt das Feature in `catalog/review.yaml` mit Grund und nicht in den
Katalog.

## Stand
| Bereich | Status | Reifegrad | Features | Prüfbestand |
|---|---|---|---|---|
