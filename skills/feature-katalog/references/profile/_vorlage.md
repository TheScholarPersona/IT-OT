# Profil: <Stack-Name>

Vorlage für ein neues Stack-Profil. Ein Profil ist vollständig, wenn jeder Abschnitt ausgefüllt ist oder eine
begründete Lücke nennt. Der Kern (Datenmodell, Regeln, Ansicht) wird **nicht** geändert.

## 1. Geltungsbereich
Sprachen, Frameworks und Versionen; was ausdrücklich nicht abgedeckt ist.

## 2. Erkennung je Schnittstellenart
| `kind` | Bevorzugt (Export-Test aus laufendem System) | Ausweichweg (statisch) | Normalisierung |
|---|---|---|---|

## 3. Rollen und Rechte
Woher Rollen je Bestandteil abgeleitet werden; am verlässlichsten ist ein Test, der die Rechte-Matrix exportiert.

## 4. Testberichte
Format, Ablageort, Felder (`classname`/`name`), Parametrisierung und die Zuordnung `file` + `test` → Berichtseintrag.
Woran die Testart erkannt wird.

## 5. Testfall auflösen und Testkörper ermitteln
Wie geprüft wird, dass der Test existiert (Parser/AST, nicht Textsuche), und wie der Körper samt lokaler Helfer
ermittelt wird.

## 6. Zusicherungsmuster
| Zusicherung | nur Status (→ `EVIDENCE_STATUS_ONLY`) |
|---|---|

## 7. Aufruf-Heuristik
Muster, an denen ein Test-Aufruf eines Bestandteils erkannt wird; Auflösung von Konstanten, Routen-Namen usw.
Ein Pfad zählt nur zusammen mit einer Methode bzw. Aktion.

## 8. Werkzeug-Umsetzung
Ort, Schema-Bibliothek, YAML-Parser, CLI-Aufruf, Testframework des Werkzeugs.

## 9. CI-Ausschnitt

## 10. Fallstricke
