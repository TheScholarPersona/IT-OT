(* Kleines Lager mit 5 Fächern.
   Zeigt: TYPE … STRUCT (UDT), Arrays von Strukturen, STRING und String-Funktionen.
   Einlagern: Artikel, Menge und Fach setzen, dann Buchen auf TRUE.
   OPC UA: ns=2;s=Faecher[2].Artikel, ns=2;s=Meldung
   API:    PUT /api/plcs/Lager/variables/Auftrag  {"value": {"Artikel": "Schraube M6", "Menge": 50, "Fach": 2}} *)

TYPE
  Lagerfach : STRUCT
    Artikel : STRING[20];
    Menge   : INT;
    Gesperrt : BOOL;
  END_STRUCT;
  Buchung : STRUCT
    Artikel : STRING[20];
    Menge   : INT;      (* positiv = einlagern, negativ = auslagern *)
    Fach    : INT := 1;
  END_STRUCT;
END_TYPE

PROGRAM Lager
VAR_INPUT
  Auftrag : Buchung;
  Buchen  : BOOL;
END_VAR
VAR_OUTPUT
  Faecher : ARRAY[1..5] OF Lagerfach;
  Bestand : DINT;
  Meldung : STRING[60] := 'Bereit';
  Fehler  : BOOL;
END_VAR
VAR
  Flanke : R_TRIG;
  i : INT;
END_VAR

Flanke(CLK := Buchen);
IF Flanke.Q THEN
  Fehler := TRUE;
  IF Auftrag.Fach < 1 OR Auftrag.Fach > 5 THEN
    Meldung := CONCAT('Fach ungültig: ', INT_TO_STRING(Auftrag.Fach));
  ELSIF Faecher[Auftrag.Fach].Gesperrt THEN
    Meldung := CONCAT('Fach gesperrt: ', INT_TO_STRING(Auftrag.Fach));
  ELSIF Faecher[Auftrag.Fach].Menge > 0 AND Faecher[Auftrag.Fach].Artikel <> Auftrag.Artikel THEN
    Meldung := CONCAT('Fach belegt mit ', Faecher[Auftrag.Fach].Artikel);
  ELSIF Faecher[Auftrag.Fach].Menge + Auftrag.Menge < 0 THEN
    Meldung := 'Zu wenig Bestand';
  ELSE
    Faecher[Auftrag.Fach].Artikel := Auftrag.Artikel;
    Faecher[Auftrag.Fach].Menge := Faecher[Auftrag.Fach].Menge + Auftrag.Menge;
    IF Faecher[Auftrag.Fach].Menge = 0 THEN
      Faecher[Auftrag.Fach].Artikel := '';
    END_IF;
    Meldung := CONCAT(CONCAT(INT_TO_STRING(Auftrag.Menge), ' x '), Auftrag.Artikel);
    Fehler := FALSE;
  END_IF;
END_IF;

Bestand := 0;
FOR i := 1 TO 5 DO
  Bestand := Bestand + Faecher[i].Menge;
END_FOR;
END_PROGRAM
