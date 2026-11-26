"""STRING and STRUCT/UDT: language, S7 layout, OPC UA and REST API."""

import asyncio

import pytest
import snap7
from asyncua import Client, ua
from fastapi.testclient import TestClient
from snap7.util import get_int, set_int

from vplc.io.s7 import build_layout, exposed_variables
from vplc.manager.api import create_app
from vplc.runtime import PLCConfig, VirtualPLC
from vplc.st import PLCRuntimeError, STSyntaxError, check_source, compile_source
from vplc.types import decode, get_type


def values(prog):
    return {v.name: v.value for v in prog.variables.values()}


def messages(source: str) -> str:
    return " | ".join(e["message"] for e in check_source(source))


# ------------------------------------------------------------------ STRING
def test_strings_literals_escapes_length_and_functions():
    prog = compile_source("""PROGRAM P
VAR
  Gruss : STRING := 'Hallo';
  Kurz : STRING[8];
  Esc : STRING := 'It$'s 100$$ $N$54';
  n, f : INT; r : REAL;
  a, b, c, d, e, g : STRING;
  gleich, kleiner : BOOL;
END_VAR
Kurz := CONCAT(Gruss, ' Welt!');
n := LEN(Gruss); f := FIND(Gruss, 'll');
a := LEFT(Gruss, 2); b := RIGHT(Gruss, 3); c := MID(Gruss, 3, 2);
d := INSERT(Gruss, '-', 2); e := DELETE(Gruss, 2, 2); g := REPLACE(Gruss, 'XY', 2, 1);
r := STRING_TO_REAL('3,5') + INT_TO_REAL(STRING_TO_INT(' 42 '));
gleich := Gruss = 'Hallo'; kleiner := 'Abc' < 'Abd';
END_PROGRAM""")
    prog.execute(0)
    v = values(prog)
    assert v["Kurz"] == "Hallo We"  # truncated to STRING[8]
    assert v["Esc"] == "It's 100$ \nT"
    assert (v["n"], v["f"]) == (5, 3)
    # IEC order: MID(IN, L, P) -> 3 characters from position 2
    assert (v["a"], v["b"], v["c"], v["d"], v["e"], v["g"]) == ("Ha", "llo", "all", "Ha-llo", "Hlo", "XYllo")
    assert v["r"] == 45.5 and v["gleich"] and v["kleiner"]
    assert prog.variables["KURZ"].type_label == "STRING[8]"


def test_string_conversions_both_ways():
    prog = compile_source("""PROGRAM P
VAR s1, s2, s3 : STRING; i : INT; END_VAR
s1 := INT_TO_STRING(-12); s2 := REAL_TO_STRING(2.5); s3 := BOOL_TO_STRING(TRUE);
i := STRING_TO_INT('17');
END_PROGRAM""")
    prog.execute(0)
    assert values(prog) == {"s1": "-12", "s2": "2.5", "s3": "TRUE", "i": 17}


def test_string_errors():
    prog = compile_source("PROGRAM P\nVAR s : STRING; END_VAR\ns := MID('abc', 1, 0);\nEND_PROGRAM")
    with pytest.raises(PLCRuntimeError, match="Position P beginnt bei 1"):
        prog.execute(0)
    prog = compile_source("PROGRAM P\nVAR i : INT; END_VAR\ni := STRING_TO_INT('zwölf');\nEND_PROGRAM")
    with pytest.raises(PLCRuntimeError, match="keine Zahl"):
        prog.execute(0)
    assert "Ungültige Länge in 'STRING[300]'" in messages("PROGRAM P VAR s : STRING[300]; END_VAR END_PROGRAM")
    with pytest.raises(STSyntaxError, match="Doppelte Anführungszeichen"):
        compile_source('PROGRAM P VAR s : STRING; END_VAR s := "x"; END_PROGRAM')


# ------------------------------------------------------------------ STRUCT
TYPES = """
TYPE
  Position : STRUCT
    X, Y : REAL;
    Name : STRING[10] := 'Start';
  END_STRUCT;
  Fach : STRUCT
    Menge : INT := 1;
    Ort : Position;
    Historie : ARRAY[0..2] OF INT := [7, 8, 9];
  END_STRUCT;
END_TYPE
"""

STRUCT_SOURCE = TYPES + """
PROGRAM Lager
VAR_INPUT Neu : Fach; END_VAR
VAR_OUTPUT Faecher : ARRAY[1..3] OF Fach; Summe : INT; END_VAR
VAR i : INT; Kopie : Fach; END_VAR
Faecher[2] := Neu;
Faecher[3].Ort.X := Faecher[3].Ort.X + 1.5;
Faecher[3].Historie[2] := 42;
Summe := 0;
FOR i := 1 TO 3 DO Summe := Summe + Faecher[i].Menge; END_FOR;
Kopie := Faecher[3];
Kopie.Menge := 99;
END_PROGRAM
"""


def test_structs_with_defaults_nesting_and_arrays_of_structs():
    prog = compile_source(STRUCT_SOURCE)
    prog.variables["NEU"].value["MENGE"] = 5
    prog.execute(0)
    prog.execute(1)
    v = values(prog)
    assert v["Faecher"][1]["MENGE"] == 5  # whole struct copied into the array
    assert v["Faecher"][2]["ORT"] == {"X": 3.0, "Y": 0.0, "NAME": "Start"}
    assert v["Faecher"][2]["HISTORIE"] == [7, 8, 42]
    assert v["Summe"] == 1 + 5 + 1
    assert v["Kopie"]["MENGE"] == 99 and v["Faecher"][2]["MENGE"] == 1  # copy, not alias
    assert prog.variables["FAECHER"].type_label == "ARRAY[1..3] OF Fach"


def test_struct_errors():
    text = messages(TYPES + """
TYPE Kreis : STRUCT Innen : Kreis; END_STRUCT; END_TYPE
FUNCTION_BLOCK B VAR_INPUT p : Position; END_VAR END_FUNCTION_BLOCK
FUNCTION F : Position F.X := 1.0; END_FUNCTION
PROGRAM P
VAR f : Fach; p : Position := 5; r : REAL; END_VAR
r := f.Gewicht;
r := f.Ort;
f := p;
r := r.X;
END_PROGRAM""")
    for fragment in ("Struktur enthält sich selbst (Kreis → Kreis)",
                     "als Ein- oder Ausgang von Bausteinen",
                     "Strukturen als Rückgabewert",
                     "Startwerte aus der Typdeklaration",
                     "Fach hat kein Feld 'Gewicht'",
                     "Struktur 'f.Ort' braucht ein Feld",
                     "Struktur 'f' kann nur ein gleichartiges Struktur (Fach) zugewiesen werden",
                     "'r' ist keine Struktur"):
        assert fragment in text, fragment


def test_warm_restart_keeps_structs_with_unchanged_layout():
    old = compile_source(STRUCT_SOURCE)
    old.execute(0)
    assert old.variables["FAECHER"].value[2]["ORT"]["X"] == 1.5
    new = compile_source(STRUCT_SOURCE.replace("+ 1.5", "+ 10.0"))
    assert "Faecher" in new.transfer_state_from(old)
    new.execute(1)
    assert new.variables["FAECHER"].value[2]["ORT"]["X"] == 11.5
    changed = compile_source(STRUCT_SOURCE.replace("Menge : INT := 1;", "Menge : DINT := 1;"))
    assert "Faecher" not in changed.transfer_state_from(old)  # layout changed: start fresh


# ------------------------------------------------------------------ interfaces
PROTO_SOURCE = TYPES + """
PROGRAM Anlage
VAR_INPUT Ziel : Position; Text : STRING[6] := 'Init'; END_VAR
VAR_OUTPUT Faecher : ARRAY[0..1] OF Fach; Echo : STRING; END_VAR
Faecher[0].Ort := Ziel;
Faecher[1].Menge := Faecher[1].Historie[0] * 10;
Echo := CONCAT(Text, '!');
END_PROGRAM
"""


def test_s7_layout_of_structs_and_strings():
    entries, size = build_layout(exposed_variables(compile_source(PROTO_SOURCE)))
    addr = {e.name: e.address(1) for e in entries}
    assert addr["Ziel.X"] == "DB1.DBD0" and addr["Ziel.Y"] == "DB1.DBD4"
    assert addr["Ziel.Name"] == "DB1.DBB8 (STRING, 12 Byte)"
    assert addr["Text"] == "DB1.DBB20 (STRING, 8 Byte)"
    assert addr["Faecher[0].Menge"] == "DB1.DBW28"
    assert addr["Faecher[0].Ort.X"] == "DB1.DBD30"
    assert addr["Faecher[0].Ort.Name"] == "DB1.DBB38 (STRING, 12 Byte)"
    assert addr["Faecher[0].Historie[0]"] == "DB1.DBW50"  # nested struct ends on 50 (even)
    assert addr["Faecher[0].Historie[2]"] == "DB1.DBW54"
    assert addr["Faecher[1].Menge"] == "DB1.DBW56"  # one Fach = 28 bytes
    assert addr["Echo"] == "DB1.DBB84 (STRING, 256 Byte)"
    assert size == 340


@pytest.fixture
async def plc(port_factory):
    p = VirtualPLC("st", PLCConfig("Anlage", s7_port=port_factory(), opcua_port=port_factory(),
                                   host="127.0.0.1", io_sync_ms=20))
    await p.start_services()
    await p.load_program(PROTO_SOURCE, version=1)
    p.run()
    for _ in range(100):
        if p.stats.scan_count > 2:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    yield p
    await p.shutdown()


async def test_structs_and_strings_over_s7(plc):
    client = snap7.Client()
    client.connect("127.0.0.1", 0, 1, plc.config.s7_port)
    try:
        data = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
        assert get_int(data, 56) == 70  # Faecher[1].Menge = Historie[0] * 10
        assert decode(get_type("STRING"), data, 84) == "Init!"
        buf = bytearray(8)
        buf[0], buf[1], buf[2:5] = 6, 3, b"Neu"
        await asyncio.to_thread(client.db_write, 1, 20, buf)  # Text
        val = bytearray(2)
        set_int(val, 0, 5)
        await asyncio.to_thread(client.db_write, 1, 50, val)  # Faecher[0].Historie[0]
        for _ in range(100):
            d = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
            if decode(get_type("STRING"), d, 84) == "Neu!":
                break
            await asyncio.sleep(0.02)
        assert decode(get_type("STRING"), d, 84) == "Neu!"
        assert plc.program.variables["FAECHER"].value[0]["HISTORIE"][0] == 5
    finally:
        client.disconnect()


async def test_structs_and_strings_over_opcua(plc):
    async with Client(f"opc.tcp://127.0.0.1:{plc.config.opcua_port}/vplc/") as client:
        ns = await client.get_namespace_index("urn:it-ot:vplc")
        assert await client.get_node(f"ns={ns};s=Faecher[1].Historie").read_value() == [7, 8, 9]
        assert await client.get_node(f"ns={ns};s=Echo").read_value() == "Init!"
        await client.get_node(f"ns={ns};s=Ziel.X").write_value(ua.Variant(2.5, ua.VariantType.Float))
        await client.get_node(f"ns={ns};s=Text").write_value("OPC")
        for _ in range(100):
            if await client.get_node(f"ns={ns};s=Faecher[0].Ort.X").read_value() == 2.5 and \
                    await client.get_node(f"ns={ns};s=Echo").read_value() == "OPC!":
                break
            await asyncio.sleep(0.02)
        assert await client.get_node(f"ns={ns};s=Faecher[0].Ort.X").read_value() == 2.5
        assert await client.get_node(f"ns={ns};s=Echo").read_value() == "OPC!"


def test_structs_and_strings_through_the_api(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))
    with TestClient(create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")) as c:
        pid = c.post("/api/plcs", json={"name": "Anlage", "source": PROTO_SOURCE}).json()["id"]
        r = c.put(f"/api/plcs/{pid}/variables/Ziel", json={"value": {"x": 1, "Name": "Ablage"}})
        assert r.status_code == 200 and r.json()["value"] == {"X": 1.0, "Y": 0.0, "Name": "Ablage"}
        assert c.put(f"/api/plcs/{pid}/variables/Faecher[1].Historie[2]", json={"value": 3}).status_code == 200
        assert c.put(f"/api/plcs/{pid}/variables/Text", json={"value": "zu lang für sechs"}).json()["value"] == "zu lan"
        assert c.put(f"/api/plcs/{pid}/variables/Ziel.Gewicht", json={"value": 1}).status_code == 404
        assert c.put(f"/api/plcs/{pid}/variables/Ziel", json={"value": {"Z": 1}}).status_code == 400
        v = {x["name"]: x for x in c.get(f"/api/plcs/{pid}/variables").json()}
        assert v["Ziel"]["value"] == {"X": 1.0, "Y": 0.0, "Name": "Ablage"}  # declared field names
        assert v["Faecher"]["value"][1]["Historie"] == [7, 8, 3]
        assert v["Ziel"]["type"] == "Position" and v["Text"]["type"] == "STRING[6]"
        assert v["Ziel"]["s7_address"] == "DB1.DBD0 … (Struktur)"
