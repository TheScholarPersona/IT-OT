"""Arrays and user function blocks through S7, OPC UA and the REST API."""

import asyncio

import pytest
import snap7
from asyncua import Client, ua
from fastapi.testclient import TestClient
from snap7.util import get_bool, get_int, set_int

from vplc.io.s7 import build_layout, exposed_variables
from vplc.manager.api import create_app
from vplc.runtime import PLCConfig, VirtualPLC
from vplc.st import compile_source

SRC = """
FUNCTION_BLOCK Mittelwert
VAR_INPUT Neu : INT; END_VAR
VAR_OUTPUT Mittel : INT; END_VAR
VAR Summe : DINT; Anzahl : DINT; END_VAR
Summe := Summe + Neu; Anzahl := Anzahl + 1;
Mittel := DINT_TO_INT(Summe / Anzahl);
END_FUNCTION_BLOCK

PROGRAM Lager
VAR_INPUT Soll : ARRAY[0..3] OF INT := [10, 20, 30, 40]; END_VAR
VAR_OUTPUT Doppelt : ARRAY[0..3] OF INT; Belegt : ARRAY[1..10] OF BOOL; Mitte : INT; END_VAR
VAR i : INT; m : Mittelwert; END_VAR
FOR i := 0 TO 3 DO Doppelt[i] := Soll[i] * 2; END_FOR;
Belegt[10] := Soll[3] > 100;
m(Neu := Soll[0], Mittel => Mitte);
END_PROGRAM
"""


async def wait_for(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def test_s7_layout_of_arrays_like_tia_portal():
    entries, size = build_layout(exposed_variables(compile_source(SRC)))
    addr = {e.name: e.address(1) for e in entries}
    assert addr["Soll[0]"] == "DB1.DBW0" and addr["Soll[3]"] == "DB1.DBW6"
    assert addr["Doppelt[0]"] == "DB1.DBW8"
    assert addr["Belegt[1]"] == "DB1.DBX16.0" and addr["Belegt[10]"] == "DB1.DBX17.1"
    assert addr["Mitte"] == "DB1.DBW18"  # an array always ends on an even address
    assert size == 22  # Mitte (18..19) + i (20..21)


@pytest.fixture
async def plc(port_factory):
    p = VirtualPLC("arr", PLCConfig("Lager", s7_port=port_factory(), opcua_port=port_factory(),
                                    host="127.0.0.1", io_sync_ms=20))
    await p.start_services()
    await p.load_program(SRC, version=1)
    p.run()

    async def scanned():
        return p.stats.scan_count > 2
    assert await wait_for(scanned)
    await asyncio.sleep(0.05)
    yield p
    await p.shutdown()


async def test_array_elements_over_s7(plc):
    client = snap7.Client()
    client.connect("127.0.0.1", 0, 1, plc.config.s7_port)
    try:
        data = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
        assert [get_int(data, 8 + 2 * i) for i in range(4)] == [20, 40, 60, 80]
        buf = bytearray(2)
        set_int(buf, 0, 500)
        await asyncio.to_thread(client.db_write, 1, 6, buf)  # Soll[3]

        async def updated():
            d = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
            return get_int(d, 14) == 1000 and get_bool(d, 17, 1)
        assert await wait_for(updated)
        assert plc.program.variables["SOLL"].value == [10, 20, 30, 500]
    finally:
        client.disconnect()


async def test_arrays_over_opcua(plc):
    async with Client(f"opc.tcp://127.0.0.1:{plc.config.opcua_port}/vplc/") as client:
        ns = await client.get_namespace_index("urn:it-ot:vplc")
        assert await client.get_node(f"ns={ns};s=Doppelt").read_value() == [20, 40, 60, 80]
        await client.get_node(f"ns={ns};s=Soll").write_value(ua.Variant([1, 2, 3, 4], ua.VariantType.Int16))

        async def updated():
            return await client.get_node(f"ns={ns};s=Doppelt").read_value() == [2, 4, 6, 8]
        assert await wait_for(updated)


def test_arrays_and_function_blocks_through_the_api(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))
    with TestClient(create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")) as c:
        pid = c.post("/api/plcs", json={"name": "Lager", "source": SRC}).json()["id"]
        assert c.put(f"/api/plcs/{pid}/variables/Soll[2]", json={"value": 7}).json()["value"] == 7
        assert c.put(f"/api/plcs/{pid}/variables/Soll", json={"value": [1, 1, 1, 1]}).status_code == 200
        assert c.put(f"/api/plcs/{pid}/variables/Soll[9]", json={"value": 1}).status_code == 404
        assert c.put(f"/api/plcs/{pid}/variables/Soll", json={"value": [1, 2]}).status_code == 400
        assert c.put(f"/api/plcs/{pid}/variables", json={"values": {"Soll[0]": 5, "Soll[1]": 6}}).status_code == 200
        variables = {v["name"]: v for v in c.get(f"/api/plcs/{pid}/variables").json()}
        assert variables["Soll"]["value"] == [5, 6, 1, 1]
        assert variables["Soll"]["type"] == "ARRAY[0..3] OF INT"
        assert variables["Soll"]["s7_address"] == "DB1.DBW0 … (4 Elemente)"
        assert variables["m.MITTEL"]["section"] == "MITTELWERT"
