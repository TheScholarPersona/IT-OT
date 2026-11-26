(* Füllstandsregelung mit Zweipunktregler und simulierter Strecke.
   Ideal zum Testen von HMI/SCADA-Anbindungen über S7 oder OPC UA. *)
PROGRAM Tank
VAR_INPUT
  Automatik : BOOL := TRUE;
  Sollwert  : REAL := 60.0;    (* % *)
  Hysterese : REAL := 5.0;     (* % *)
  Abfluss   : REAL := 0.15;    (* %/Zyklus *)
END_VAR
VAR_OUTPUT
  Fuellstand : REAL := 20.0;   (* % *)
  Pumpe      : BOOL;
  Alarm_Hoch, Alarm_Tief : BOOL;
  Pumpenstarts : DINT;
END_VAR
VAR
  Zufluss : REAL := 0.4;
  Start   : R_TRIG;
  Alarm_Verz : TON;
END_VAR

IF Automatik THEN
  IF Fuellstand < Sollwert - Hysterese THEN
    Pumpe := TRUE;
  ELSIF Fuellstand > Sollwert + Hysterese THEN
    Pumpe := FALSE;
  END_IF;
END_IF;

Start(CLK := Pumpe);
IF Start.Q THEN Pumpenstarts := Pumpenstarts + 1; END_IF;

(* Simulation der Strecke *)
IF Pumpe THEN
  Fuellstand := Fuellstand + Zufluss;
END_IF;
Fuellstand := LIMIT(0.0, Fuellstand - Abfluss, 100.0);

Alarm_Verz(IN := Fuellstand > 95.0 OR Fuellstand < 5.0, PT := T#2s);
Alarm_Hoch := Alarm_Verz.Q AND Fuellstand > 95.0;
Alarm_Tief := Alarm_Verz.Q AND Fuellstand < 5.0;
END_PROGRAM
