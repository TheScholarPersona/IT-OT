"""Arrays, user FUNCTION_BLOCKs and FUNCTIONs in Structured Text."""

import pytest

from vplc.st import PLCRuntimeError, STCompileError, STSyntaxError, check_source, compile_source


def values(prog):
    return {v.name: v.value for v in prog.variables.values()}


def messages(source: str) -> str:
    return " | ".join(e["message"] for e in check_source(source))


# ------------------------------------------------------------------ arrays
def test_arrays_with_initial_values_indices_and_loops():
    prog = compile_source("""PROGRAM P
VAR
  Werte : ARRAY[0..5] OF INT := [1, 2, 3(10)];
  Bits : ARRAY[1..3] OF BOOL := [TRUE];
  i : INT; Summe : DINT;
END_VAR
Summe := 0;
FOR i := 0 TO 5 DO Summe := Summe + Werte[i]; END_FOR;
Werte[5] := Werte[0] + Werte[1];
Bits[3] := NOT Bits[1];
END_PROGRAM""")
    prog.execute(0)
    v = values(prog)
    assert v["Werte"] == [1, 2, 10, 10, 10, 3]
    assert v["Summe"] == 1 + 2 + 10 * 3 + 0
    assert v["Bits"] == [True, False, False]
    assert prog.variables["WERTE"].type_label == "ARRAY[0..5] OF INT"


def test_array_index_out_of_range_is_runtime_error():
    prog = compile_source("PROGRAM P\nVAR a : ARRAY[1..3] OF INT; i : INT := 4; END_VAR\na[i] := 1;\nEND_PROGRAM")
    with pytest.raises(PLCRuntimeError) as exc:
        prog.execute(0)
    assert "Index 4 außerhalb von a[1..3]" in exc.value.message and exc.value.line == 3


def test_whole_array_copy_requires_same_shape():
    prog = compile_source("PROGRAM P\nVAR a : ARRAY[0..2] OF INT := [1, 2, 3]; b : ARRAY[0..2] OF INT; END_VAR\n"
                          "b := a;\na[0] := 9;\nEND_PROGRAM")
    prog.execute(0)
    assert values(prog)["b"] == [1, 2, 3] and values(prog)["a"][0] == 9  # copy, not alias
    assert "gleichartiges Array" in messages(
        "PROGRAM P\nVAR a : ARRAY[0..2] OF INT; c : ARRAY[0..3] OF INT; END_VAR\nc := a;\nEND_PROGRAM")


def test_array_declaration_errors():
    text = messages("""PROGRAM P
VAR CONSTANT N : INT := 3; END_VAR
VAR
  a : ARRAY[0..N] OF INT := [1, 2, 3, 4, 5];
  b : ARRAY[5..1] OF INT;
  x : INT;
END_VAR
x := a;
x := x[1];
END_PROGRAM""")
    assert "5 Initialwerte für 'a' mit 4 Elementen" in text
    assert "kleiner als die untere" in text
    assert "braucht einen Index" in text
    assert "'x' ist kein Array" in text
    with pytest.raises(STSyntaxError):
        compile_source("PROGRAM P VAR m : ARRAY[0..1, 0..1] OF INT; END_VAR END_PROGRAM")


# ------------------------------------------------------------------ function blocks
FB_SOURCE = """
FUNCTION_BLOCK Zaehler
VAR_INPUT Takt : BOOL; Schritt : INT := 1; END_VAR
VAR_OUTPUT Stand : INT; Voll : BOOL; END_VAR
VAR Flanke : R_TRIG; Verz : TON; END_VAR
Flanke(CLK := Takt);
IF Flanke.Q THEN Stand := Stand + Schritt; END_IF;
Verz(IN := Stand >= 3, PT := T#100ms);
Voll := Verz.Q;
END_FUNCTION_BLOCK

PROGRAM P
VAR a, b : Zaehler; t : BOOL; StandB : INT; END_VAR
a(Takt := t);
b(Takt := t, Schritt := 2, Stand => StandB);
END_PROGRAM
"""


def test_user_function_block_instances_have_their_own_state():
    prog = compile_source(FB_SOURCE)
    for i in range(3):
        prog.variables["T"].value = True
        prog.execute(i * 10)
        prog.variables["T"].value = False
        prog.execute(i * 10 + 5)
    a, b = prog.fbs["A"].block, prog.fbs["B"].block
    assert a.values["STAND"] == 3 and b.values["STAND"] == 6
    assert values(prog)["StandB"] == 6
    assert not a.values["VOLL"]
    prog.execute(200)  # nested TON inside the FB runs on PLC time
    assert a.values["VOLL"] and b.values["VOLL"]
    assert prog.function_blocks == ["Zaehler"]


def test_member_access_and_errors_of_user_function_blocks():
    src = FB_SOURCE.replace("b(Takt := t, Schritt := 2, Stand => StandB);",
                            "b(Takt := t, Gibts := 1);\nStandB := a.Stand + a.Nope;")
    text = messages(src)
    assert "Zaehler hat keinen Eingang 'GIBTS'" in text
    assert "Zaehler hat keinen Parameter 'NOPE'" in text


def test_warm_restart_keeps_fb_state_but_runs_new_code():
    old = compile_source(FB_SOURCE)
    for i in range(2):
        old.variables["T"].value = True
        old.execute(i)
        old.variables["T"].value = False
        old.execute(i)
    assert old.fbs["A"].block.values["STAND"] == 2
    new = compile_source(FB_SOURCE.replace("Stand := Stand + Schritt", "Stand := Stand + 100 * Schritt"))
    kept = new.transfer_state_from(old)
    assert "a" in kept
    new.variables["T"].value = True
    new.execute(10)
    assert new.fbs["A"].block.values["STAND"] == 102  # old value kept, new code used


# ------------------------------------------------------------------ functions
FN_SOURCE = """
FUNCTION Skaliere : REAL
VAR_INPUT Roh : INT; Max : REAL := 100.0; END_VAR
VAR Zwischen : REAL; END_VAR
Zwischen := Zwischen + INT_TO_REAL(Roh);  // no memory: starts at 0.0 on every call
Skaliere := Zwischen / 27648.0 * Max;
END_FUNCTION

FUNCTION Begrenze : INT
VAR_INPUT x, lo, hi : INT; END_VAR
IF x < lo THEN Begrenze := lo; RETURN; END_IF;
Begrenze := MIN(x, hi);
END_FUNCTION

PROGRAM P
VAR a, b, c : REAL; d, e : INT; END_VAR
a := Skaliere(27648);
b := Skaliere(Roh := 13824, Max := 50.0);
c := Skaliere(27648);
d := Begrenze(-5, 0, 10);
e := Begrenze(x := 42, lo := 0, hi := 10);
END_PROGRAM
"""


def test_user_functions_with_positional_named_and_default_arguments():
    prog = compile_source(FN_SOURCE)
    prog.execute(0)
    v = values(prog)
    assert v["a"] == 100.0 and v["b"] == 25.0 and v["c"] == 100.0  # c equals a: no memory
    assert v["d"] == 0 and v["e"] == 10  # RETURN leaves the function early
    assert prog.functions == ["Skaliere", "Begrenze"]


def test_function_call_errors():
    text = messages(FN_SOURCE.replace("e := Begrenze(x := 42, lo := 0, hi := 10);",
                                      "e := Begrenze(1, 2, 3, 4);\ne := Begrenze(y := 1);\ne := Begrenze;"))
    assert "Begrenze hat 3 Eingänge, erhalten 4 Argumente" in text
    assert "Begrenze hat keinen Eingang 'Y'" in text
    assert "muss mit ( ) aufgerufen werden" in text


def test_recursion_and_self_containing_function_blocks_are_rejected():
    text = messages("""
FUNCTION A : INT VAR_INPUT x : INT; END_VAR A := B(x); END_FUNCTION
FUNCTION B : INT VAR_INPUT x : INT; END_VAR B := A(x); END_FUNCTION
FUNCTION_BLOCK Kette VAR k : Kette; END_VAR END_FUNCTION_BLOCK
PROGRAM P VAR r : INT; END_VAR r := A(1); END_PROGRAM""")
    assert "Rekursive Funktionsaufrufe sind nicht erlaubt (A → B → A)" in text
    assert "Funktionsbaustein enthält sich selbst (Kette → Kette)" in text


def test_pou_declaration_errors():
    text = messages("""
FUNCTION_BLOCK TON END_FUNCTION_BLOCK
FUNCTION F : INT VAR_OUTPUT o : INT; END_VAR VAR t : TON; END_VAR F := 1; END_FUNCTION
FUNCTION F : INT F := 2; END_FUNCTION
PROGRAM P VAR x : F; END_VAR END_PROGRAM""")
    assert "'TON' ist ein reservierter Name" in text
    assert "VAR_OUTPUT ist in Funktionen nicht erlaubt" in text
    assert "keine Funktionsbaustein-Instanzen erlaubt" in text
    assert "'F' ist bereits deklariert" in text
    assert "Funktionen werden aufgerufen, nicht deklariert" in text
    with pytest.raises(STSyntaxError, match="kein Programm"):
        compile_source("FUNCTION F : INT F := 1; END_FUNCTION")
    with pytest.raises(STSyntaxError, match="Nur ein PROGRAM"):
        compile_source("PROGRAM A END_PROGRAM PROGRAM B END_PROGRAM")
    with pytest.raises(STCompileError):
        compile_source("FUNCTION_BLOCK X VAR_INPUT a : ARRAY[0..1] OF INT; END_VAR END_FUNCTION_BLOCK\n"
                       "PROGRAM P END_PROGRAM")
