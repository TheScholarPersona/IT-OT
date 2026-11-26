"""Standard function blocks: timers, edges, counters, bistables."""

from vplc.st import compile_source


def make(decls: str, body: str):
    return compile_source(f"PROGRAM T\nVAR {decls} END_VAR\n{body}\nEND_PROGRAM")


def val(prog, name):
    return prog.variables[name.upper()].value


def test_ton():
    p = make("start, q : BOOL; et : TIME; t : TON;", "t(IN := start, PT := T#100ms, Q => q, ET => et);")
    p.variables["START"].value = True
    p.execute(1000)
    assert not val(p, "q")
    p.execute(1099)
    assert not val(p, "q") and val(p, "et") == 99
    p.execute(1100)
    assert val(p, "q") and val(p, "et") == 100
    p.variables["START"].value = False
    p.execute(1200)
    assert not val(p, "q") and val(p, "et") == 0


def test_tof():
    p = make("x, q : BOOL; t : TOF;", "t(IN := x, PT := T#50ms); q := t.Q;")
    p.variables["X"].value = True
    p.execute(0)
    assert val(p, "q")
    p.variables["X"].value = False
    p.execute(10)
    assert val(p, "q")
    p.execute(59)
    assert val(p, "q")
    p.execute(60)
    assert not val(p, "q")


def test_tp():
    p = make("x, q : BOOL; t : TP;", "t(IN := x, PT := T#50ms); q := t.Q;")
    p.variables["X"].value = True
    p.execute(0)
    assert val(p, "q")
    p.variables["X"].value = False  # pulse continues even if IN drops
    p.execute(30)
    assert val(p, "q")
    p.execute(50)
    assert not val(p, "q")


def test_edges():
    p = make("x, r, f : BOOL; rt : R_TRIG; ft : F_TRIG;", "rt(CLK := x); ft(CLK := x); r := rt.Q; f := ft.Q;")
    seq = [(False, False, False), (True, True, False), (True, False, False), (False, False, True), (False, False, False)]
    for x, r, f in seq:
        p.variables["X"].value = x
        p.execute(0)
        assert (val(p, "r"), val(p, "f")) == (r, f)


def test_ctu_and_reset():
    p = make("pulse, reset, q : BOOL; cv : INT; c : CTU;", "c(CU := pulse, R := reset, PV := 3, Q => q, CV => cv);")
    for _ in range(3):
        p.variables["PULSE"].value = True
        p.execute(0)
        p.variables["PULSE"].value = False
        p.execute(0)
    assert val(p, "cv") == 3 and val(p, "q")
    p.variables["RESET"].value = True
    p.execute(0)
    assert val(p, "cv") == 0 and not val(p, "q")


def test_ctd():
    p = make("pulse, load : BOOL; c : CTD;", "c(CD := pulse, LD := load, PV := 2);")
    p.variables["LOAD"].value = True
    p.execute(0)
    p.variables["LOAD"].value = False
    for _ in range(2):
        p.variables["PULSE"].value = True
        p.execute(0)
        p.variables["PULSE"].value = False
        p.execute(0)
    assert p.fbs["C"].block.values["CV"] == 0 and p.fbs["C"].block.values["Q"]


def test_sr_rs():
    p = make("s, r : BOOL; a : SR; b : RS;", "a(S1 := s, R := r); b(S := s, R1 := r);")
    p.variables["S"].value = True
    p.variables["R"].value = True
    p.execute(0)
    assert p.fbs["A"].block.values["Q1"] is True   # set dominant
    assert p.fbs["B"].block.values["Q1"] is False  # reset dominant


def test_ctud_counts_up_and_down_with_load_and_reset():
    p = make("up, down, load, reset : BOOL; c : CTUD;", "c(CU := up, CD := down, R := reset, LD := load, PV := 2);")
    fb = p.fbs["C"].block.values

    def pulse(name):
        p.variables[name].value = True
        p.execute(0)
        p.variables[name].value = False
        p.execute(0)

    pulse("UP")
    pulse("UP")
    assert fb["CV"] == 2 and fb["QU"] and not fb["QD"]
    pulse("DOWN")
    pulse("DOWN")
    assert fb["CV"] == 0 and fb["QD"] and not fb["QU"]
    p.variables["UP"].value = p.variables["DOWN"].value = True  # simultaneous edges cancel out
    p.execute(0)
    assert fb["CV"] == 0
    p.variables["UP"].value = p.variables["DOWN"].value = False
    pulse("LOAD")
    assert fb["CV"] == 2 and fb["QU"]
    pulse("RESET")
    assert fb["CV"] == 0
