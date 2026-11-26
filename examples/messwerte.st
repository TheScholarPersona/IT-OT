(* Messwerterfassung mit gleitendem Mittelwert.
   Zeigt: ARRAY, eigener FUNCTION_BLOCK, eigene FUNCTION.
   S7:     Rohwerte = DB1.DBW0 … DB1.DBW6 (4 Kanäle)
   OPC UA: ns=2;s=Rohwerte (Array), ns=2;s=Mittelwerte *)

FUNCTION Skaliere : REAL
VAR_INPUT
  Roh : INT;              (* 0 … 27648 wie bei S7-Analogeingängen *)
  Bereich : REAL := 100.0;
END_VAR
Skaliere := INT_TO_REAL(Roh) / 27648.0 * Bereich;
END_FUNCTION

FUNCTION_BLOCK GleitenderMittelwert
VAR_INPUT
  Wert : REAL;
END_VAR
VAR_OUTPUT
  Mittel : REAL;
  Gefuellt : BOOL;          (* Puffer einmal voll *)
END_VAR
VAR CONSTANT
  N : INT := 8;
END_VAR
VAR
  Puffer : ARRAY[0..7] OF REAL;
  Pos : INT;
  Summe : REAL;
  k : INT;
END_VAR
Puffer[Pos] := Wert;
Pos := (Pos + 1) MOD N;
IF Pos = 0 THEN Gefuellt := TRUE; END_IF;
Summe := 0.0;
FOR k := 0 TO N - 1 DO
  Summe := Summe + Puffer[k];
END_FOR;
Mittel := Summe / INT_TO_REAL(N);
END_FUNCTION_BLOCK

PROGRAM Messwerte
VAR_INPUT
  Rohwerte : ARRAY[0..3] OF INT := [13824, 27648, 0, 6912];
  Grenzwert : REAL := 80.0;
END_VAR
VAR_OUTPUT
  Mittelwerte : ARRAY[0..3] OF REAL;
  Alarm : ARRAY[0..3] OF BOOL;
  Bereit : BOOL;
END_VAR
VAR
  Filter0, Filter1, Filter2, Filter3 : GleitenderMittelwert;
  i : INT;
END_VAR
Filter0(Wert := Skaliere(Rohwerte[0]));
Filter1(Wert := Skaliere(Rohwerte[1]));
Filter2(Wert := Skaliere(Rohwerte[2]));
Filter3(Wert := Skaliere(Roh := Rohwerte[3], Bereich := 100.0));
Mittelwerte[0] := Filter0.Mittel;
Mittelwerte[1] := Filter1.Mittel;
Mittelwerte[2] := Filter2.Mittel;
Mittelwerte[3] := Filter3.Mittel;
FOR i := 0 TO 3 DO
  Alarm[i] := Mittelwerte[i] > Grenzwert;
END_FOR;
Bereit := Filter0.Gefuellt AND Filter1.Gefuellt AND Filter2.Gefuellt AND Filter3.Gefuellt;
END_PROGRAM
