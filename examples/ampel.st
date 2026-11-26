(* Fußgängerampel als Schrittkette.
   S7:     Anforderung = DB1.DBX0.0
   OPC UA: ns=2;s=Anforderung *)
PROGRAM Ampel
VAR CONSTANT
  T_GELB  : TIME := T#2s;
  T_ROT   : TIME := T#5s;
  T_RESET : TIME := T#1s;
END_VAR
VAR_INPUT
  Anforderung : BOOL;          (* Taster Fußgänger *)
END_VAR
VAR_OUTPUT
  Auto_Rot, Auto_Gelb, Auto_Gruen : BOOL;
  Fuss_Rot, Fuss_Gruen : BOOL;
  Zyklen : DINT;                (* Anzahl Fußgängerphasen *)
END_VAR
VAR
  Schritt : INT := 0;
  Timer   : TON;
  Taster  : R_TRIG;
  Angefordert : BOOL;
END_VAR

Taster(CLK := Anforderung);
IF Taster.Q THEN
  Angefordert := TRUE;
END_IF;

CASE Schritt OF
  0: (* Autos grün *)
     Auto_Gruen := TRUE; Auto_Gelb := FALSE; Auto_Rot := FALSE;
     Fuss_Rot := TRUE;  Fuss_Gruen := FALSE;
     IF Angefordert THEN
       Schritt := 10;
     END_IF;
  10: (* Autos gelb *)
     Auto_Gruen := FALSE; Auto_Gelb := TRUE;
     Timer(IN := TRUE, PT := T_GELB);
     IF Timer.Q THEN Timer(IN := FALSE); Schritt := 20; END_IF;
  20: (* Autos rot, Fußgänger grün *)
     Auto_Gelb := FALSE; Auto_Rot := TRUE;
     Fuss_Rot := FALSE; Fuss_Gruen := TRUE;
     Timer(IN := TRUE, PT := T_ROT);
     IF Timer.Q THEN Timer(IN := FALSE); Schritt := 30; END_IF;
  30: (* Räumzeit *)
     Fuss_Gruen := FALSE; Fuss_Rot := TRUE;
     Timer(IN := TRUE, PT := T_RESET);
     IF Timer.Q THEN
       Timer(IN := FALSE);
       Angefordert := FALSE;
       Zyklen := Zyklen + 1;
       Schritt := 0;
     END_IF;
ELSE
  Schritt := 0;
END_CASE;
END_PROGRAM
