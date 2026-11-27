# Ergänzung der Definition of Done: Feature-Katalog

Eine Änderung ist erst fertig, wenn zusätzlich gilt:

- [ ] **Neue Fähigkeit:** Ein Feature mit Akzeptanzkriterien und bestandenem Nachweis existiert, oder es steht im
      Prüfbestand mit `state` und `reason`.
- [ ] **Neuer Bestandteil** (Endpunkt, Ereignis, Befehl …): Er ist einem Feature zugeordnet oder als Ausnahme begründet.
- [ ] **Geänderte Regel oder geänderter Fehlercode:** Das Kriterium und der abdeckende Test sind angepasst.
- [ ] **Umbenannter oder verschobener Test:** Der Nachweis ist angepasst.
- [ ] **Entfernte Fähigkeit:** Das Feature ist gelöscht, und die ID wird nicht wiederverwendet.
- [ ] Der Katalog-Check in der CI ist grün.
- [ ] Neue Nachweise sind im PR mit *Kriterium → Aktion → Zusicherung (Datei:Zeile)* belegt und von einer zweiten
      Person geprüft.
