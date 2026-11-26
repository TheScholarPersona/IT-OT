"""S7 data block layout and encoding."""

from vplc.io.s7 import build_layout, exposed_variables
from vplc.st import compile_source
from vplc.types import TYPES, coerce, decode, encode


def layout_of(decls: str):
    prog = compile_source(f"PROGRAM T\n{decls}\nEND_PROGRAM")
    return build_layout(exposed_variables(prog))


def test_layout_matches_non_optimized_tia_db():
    entries, size = layout_of(
        "VAR a, b : BOOL; c : INT; d : BOOL; e : BYTE; f : REAL; g : BYTE; h : DINT; END_VAR "
        "VAR_TEMP tmp : INT; END_VAR"
    )
    addr = {e.name: e.address(1) for e in entries}
    assert addr == {
        "a": "DB1.DBX0.0", "b": "DB1.DBX0.1", "c": "DB1.DBW2", "d": "DB1.DBX4.0",
        "e": "DB1.DBB5", "f": "DB1.DBD6", "g": "DB1.DBB10", "h": "DB1.DBD12",
    }
    assert size == 16


def test_bool_packing_over_byte_boundary():
    entries, size = layout_of("VAR " + " ".join(f"b{i} : BOOL;" for i in range(10)) + " END_VAR")
    assert entries[8].address(1) == "DB1.DBX1.0" and entries[9].address(1) == "DB1.DBX1.1"
    assert size == 2


def test_encode_decode_roundtrip_big_endian():
    buf = bytearray(16)
    encode(TYPES["INT"], -2, buf, 0)
    assert buf[0:2] == b"\xff\xfe"
    encode(TYPES["REAL"], coerce(TYPES["REAL"], 1.5), buf, 2)
    assert buf[2:6] == b"\x3f\xc0\x00\x00"
    encode(TYPES["BOOL"], True, buf, 6, 3)
    assert buf[6] == 0b1000 and decode(TYPES["BOOL"], buf, 6, 3) is True
    encode(TYPES["BOOL"], False, buf, 6, 3)
    assert buf[6] == 0
    encode(TYPES["UDINT"], 4_000_000_000, buf, 8)
    assert decode(TYPES["UDINT"], buf, 8) == 4_000_000_000
