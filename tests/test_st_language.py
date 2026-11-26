"""Structured Text: lexer, parser, semantic checks and execution semantics."""

import math

import pytest

from vplc.st import PLCRuntimeError, STCompileError, STSyntaxError, check_source, compile_source


def run(body: str, decls: str = "", scans: int = 1, now_ms: int = 0):
    prog = compile_source(f"PROGRAM T\n{decls}\n{body}\nEND_PROGRAM")
    for i in range(scans):
        prog.execute(now_ms + i)
    return {v.name: v.value for v in prog.variables.values()}


def test_arithmetic_and_precedence():
    v = run("a := 2 + 3 * 4; b := (2 + 3) * 4; c := -7 / 2; d := -7 MOD 3; r := 2 ** 10;",
            "VAR a, b, c, d : INT; r : REAL; END_VAR")
    assert v == {"a": 14, "b": 20, "c": -3, "d": -1, "r": 1024.0}


def test_integer_overflow_wraps_like_a_plc():
    v = run("i := 32767; i := i + 1; b := 255; b := b + 1; u := 0; u := u - 1;",
            "VAR i : INT; b : BYTE; u : UINT; END_VAR")
    assert v == {"i": -32768, "b": 0, "u": 65535}


def test_real_is_float32():
    v = run("r := 0.1;", "VAR r : REAL; l : LREAL := 0.1; END_VAR")
    assert v["r"] != 0.1 and abs(v["r"] - 0.1) < 1e-7
    assert v["l"] == 0.1


def test_literals():
    v = run("", "VAR a : WORD := 16#FF_FF; b : BYTE := 2#1010; c : INT := INT#40000; "
                "t : TIME := T#1m30s250ms; t2 : TIME := t#1.5s; r : REAL := 1.5E2; END_VAR")
    assert v == {"a": 0xFFFF, "b": 10, "c": 40000 - 65536, "t": 90_250, "t2": 1500, "r": 150.0}


def test_boolean_and_bitwise_logic():
    v = run("x := TRUE AND NOT FALSE; y := TRUE XOR TRUE; z := FALSE OR TRUE & TRUE; "
            "w := 16#F0F0 AND 16#FF00; n := NOT w;",
            "VAR x, y, z : BOOL; w, n : WORD; END_VAR")
    assert v == {"x": True, "y": False, "z": True, "w": 0xF000, "n": 0x0FFF}


def test_if_elsif_else():
    src = "IF a > 10 THEN r := 1; ELSIF a > 5 THEN r := 2; ELSE r := 3; END_IF;"
    for a, expected in ((11, 1), (6, 2), (0, 3)):
        assert run(src, f"VAR a : INT := {a}; r : INT; END_VAR")["r"] == expected


def test_case_with_ranges_and_lists():
    src = "CASE s OF 1, 2: r := 10; 3..5: r := 20; -1: r := 30; ELSE r := 99; END_CASE;"
    for s, expected in ((1, 10), (2, 10), (4, 20), (-1, 30), (7, 99)):
        assert run(src, f"VAR s : INT := {s}; r : INT; END_VAR")["r"] == expected


def test_loops():
    v = run("""
        FOR i := 1 TO 10 DO sum := sum + i; END_FOR;
        FOR i := 10 TO 1 BY -3 DO down := down + 1; END_FOR;
        WHILE w < 5 DO w := w + 1; IF w = 3 THEN EXIT; END_IF; END_WHILE;
        REPEAT rep := rep + 1; UNTIL rep >= 4 END_REPEAT;
        FOR i := 1 TO 5 DO IF i MOD 2 = 0 THEN CONTINUE; END_IF; odd := odd + i; END_FOR;
    """, "VAR i, sum, down, w, rep, odd : INT; END_VAR")
    assert v["sum"] == 55 and v["down"] == 4 and v["w"] == 3 and v["rep"] == 4 and v["odd"] == 9


def test_return_ends_scan():
    v = run("a := 1; RETURN; a := 2;", "VAR a : INT; END_VAR")
    assert v["a"] == 1


def test_functions_and_conversions():
    v = run("a := MAX(3, 9, 4); b := LIMIT(0, 150, 100); c := REAL_TO_INT(2.5); "
            "d := REAL_TO_INT(-2.6); r := SQRT(16.0); s := SEL(TRUE, 1, 2); m := ABS(-5); "
            "t := TO_DINT(T#2s);",
            "VAR a, b, c, d, s, m : INT; r : REAL; t : DINT; END_VAR")
    assert v == {"a": 9, "b": 100, "c": 2, "d": -3, "s": 2, "m": 5, "r": 4.0, "t": 2000}


def test_var_temp_is_reset_each_scan_and_var_keeps_value():
    v = run("tmp := tmp + 1; keep := keep + 1;", "VAR keep : INT; END_VAR VAR_TEMP tmp : INT; END_VAR", scans=3)
    assert v == {"keep": 3, "tmp": 1}


def test_case_insensitive_identifiers_and_comments():
    v = run("// Kommentar\n MOTOR := (* inline *) TRUE;", "VAR Motor : BOOL; END_VAR")
    assert v["Motor"] is True


def test_constants_in_initialisers():
    v = run("", "VAR CONSTANT MAX_N : INT := 10; HALF : INT := MAX_N / 2; END_VAR VAR x : INT := HALF + 1; END_VAR")
    assert v == {"MAX_N": 10, "HALF": 5, "x": 6}


# ------------------------------------------------------------------ errors
def test_syntax_error_has_position():
    with pytest.raises(STSyntaxError) as exc:
        compile_source("PROGRAM T\nVAR a : INT; END_VAR\na := 1\nEND_PROGRAM")
    assert exc.value.line == 4


def test_semantic_errors_are_collected():
    errors = check_source("""PROGRAM T
VAR CONSTANT K : INT := 1; END_VAR
VAR a : INT; t : TON; END_VAR
b := 1;
K := 2;
a := FOO(1);
t(XX := TRUE);
a := t.NOPE;
x : = 1;
END_PROGRAM""")
    assert len(errors) == 1  # syntax error stops parsing ("x : = 1")
    errors = check_source("""PROGRAM T
VAR CONSTANT K : INT := 1; END_VAR
VAR a : INT; t : TON; f : FANCY; END_VAR
b := 1;
K := 2;
a := FOO(1);
t(XX := TRUE);
a := t.NOPE;
EXIT;
END_PROGRAM""")
    messages = " | ".join(e["message"] for e in errors)
    assert len(errors) == 7, messages
    for fragment in ("FANCY", "'b'", "Konstante", "FOO", "XX", "NOPE", "EXIT"):
        assert fragment in messages
    assert [e["line"] for e in errors] == sorted(e["line"] for e in errors)


def test_division_by_zero_is_runtime_error():
    prog = compile_source("PROGRAM T VAR a, b : INT; END_VAR a := 1 / b; END_PROGRAM")
    with pytest.raises(PLCRuntimeError) as exc:
        prog.execute(0)
    assert "Division" in exc.value.message and exc.value.line == 1


def test_real_division_by_zero_gives_infinity():
    v = run("r := 1.0 / z;", "VAR r, z : REAL; END_VAR")
    assert math.isinf(v["r"])


def test_watchdog_stops_endless_loop():
    prog = compile_source("PROGRAM T VAR a : INT; END_VAR WHILE TRUE DO a := a + 1; END_WHILE; END_PROGRAM",
                          watchdog_ms=50)
    with pytest.raises(PLCRuntimeError) as exc:
        prog.execute(0)
    assert "Zykluszeitüberwachung" in exc.value.message


def test_compile_error_type():
    with pytest.raises(STCompileError):
        compile_source("PROGRAM T VAR a : INT; END_VAR a := b; END_PROGRAM")


def test_warm_restart_keeps_values():
    old = compile_source("PROGRAM T VAR a : INT; b : REAL; t : TON; END_VAR a := a + 1; END_PROGRAM")
    for i in range(5):
        old.execute(i)
    new = compile_source("PROGRAM T VAR a : INT; b : INT; c : BOOL; t : TON; END_VAR a := a + 10; END_PROGRAM")
    kept = new.transfer_state_from(old)
    assert "a" in kept and "t" in kept and "b" not in kept  # b changed type
    new.execute(10)
    assert new.variables["A"].value == 15
