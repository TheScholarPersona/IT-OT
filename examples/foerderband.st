(* Förderband mit Teilezählung, Losgröße und Störungsüberwachung. *)
PROGRAM Foerderband
VAR_INPUT
  Start, Stopp, Quittieren : BOOL;
  Sensor_Teil : BOOL;           (* Lichtschranke *)
  Losgroesse  : INT := 10;
END_VAR
VAR_OUTPUT
  Motor   : BOOL;
  Los_Fertig, Stoerung : BOOL;
  Teile   : INT;
  Gesamt  : UDINT;
END_VAR
VAR
  Zaehler : CTU;
  Teil    : R_TRIG;
  Laufzeit_Ohne_Teil : TON;
  Ein     : SR;
END_VAR

Ein(S1 := Start AND NOT Stoerung, R := Stopp OR Stoerung OR Los_Fertig);
Motor := Ein.Q1;

Teil(CLK := Sensor_Teil);
IF Teil.Q THEN Gesamt := Gesamt + 1; END_IF;

Zaehler(CU := Teil.Q, R := Quittieren, PV := Losgroesse);
Teile := Zaehler.CV;
Los_Fertig := Zaehler.Q;

(* Störung: Band läuft 10 s ohne dass ein Teil erkannt wird *)
Laufzeit_Ohne_Teil(IN := Motor AND NOT Sensor_Teil, PT := T#10s);
IF Laufzeit_Ohne_Teil.Q THEN
  Stoerung := TRUE;
END_IF;
IF Quittieren THEN
  Stoerung := FALSE;
END_IF;
END_PROGRAM
