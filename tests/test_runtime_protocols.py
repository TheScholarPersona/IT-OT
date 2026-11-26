"""End-to-end: runtime with real S7 and OPC UA clients."""

import asyncio

import pytest
import snap7
from asyncua import Client, ua
from snap7.util import get_bool, get_dint, get_int, get_real, set_bool, set_int

from vplc.runtime import RUN, STOP, PLCConfig, VirtualPLC

SRC = """
PROGRAM Demo
VAR_INPUT Start : BOOL; Sollwert : INT := 50; END_VAR
VAR_OUTPUT Laeuft : BOOL; Zaehler : DINT; Halb : REAL; END_VAR
VAR CONSTANT Faktor : INT := 2; END_VAR
Laeuft := Start;
IF Start THEN Zaehler := Zaehler + 1; END_IF;
Halb := INT_TO_REAL(Sollwert) / INT_TO_REAL(Faktor);
END_PROGRAM
"""
# Layout: Start X0.0, Sollwert W2, Laeuft X4.0, Zaehler D6, Halb D10, Faktor W14


async def wait_for(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
async def plc(port_factory):
    p = VirtualPLC("t1", PLCConfig("Demo", s7_port=port_factory(), opcua_port=port_factory(),
                                   host="127.0.0.1", io_sync_ms=20))
    await p.start_services()
    await p.load_program(SRC, version=1)
    yield p
    await p.shutdown()


async def started(plc):
    plc.run()

    async def scanned():
        return plc.stats.scan_count > 2
    assert await wait_for(scanned)
    await asyncio.sleep(0.05)  # let the OPC UA sync publish the status once


async def test_s7_read_write(plc):
    await started(plc)
    client = snap7.Client()
    client.connect("127.0.0.1", 0, 1, plc.config.s7_port)
    try:
        data = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
        assert get_int(data, 2) == 50 and get_real(data, 10) == 25.0 and get_int(data, 14) == 2

        start = bytearray(1)
        set_bool(start, 0, 0, True)
        await asyncio.to_thread(client.db_write, 1, 0, start)
        sollwert = bytearray(2)
        set_int(sollwert, 0, 80)
        await asyncio.to_thread(client.db_write, 1, 2, sollwert)

        async def running():
            d = await asyncio.to_thread(client.db_read, 1, 0, plc.s7.size)
            return get_bool(d, 4, 0) and get_dint(d, 6) > 3 and get_real(d, 10) == 40.0
        assert await wait_for(running)

        # Writes to constants are ignored and overwritten again
        await asyncio.to_thread(client.db_write, 1, 14, bytearray(b"\x00\x09"))
        await asyncio.sleep(0.1)
        d = await asyncio.to_thread(client.db_read, 1, 14, 2)
        assert get_int(d, 0) == 2
    finally:
        client.disconnect()


async def test_opcua_read_write(plc):
    await started(plc)
    async with Client(f"opc.tcp://127.0.0.1:{plc.config.opcua_port}/vplc/") as client:
        ns = await client.get_namespace_index("urn:it-ot:vplc")
        assert await client.get_node(f"ns={ns};s=_Status.Mode").read_value() == RUN
        await client.get_node(f"ns={ns};s=Sollwert").write_value(ua.Variant(30, ua.VariantType.Int16))
        await client.get_node(f"ns={ns};s=Start").write_value(True)

        async def updated():
            halb = await client.get_node(f"ns={ns};s=Halb").read_value()
            z = await client.get_node(f"ns={ns};s=Zaehler").read_value()
            return halb == 15.0 and z > 0
        assert await wait_for(updated)

        with pytest.raises(ua.UaStatusCodeError):
            await client.get_node(f"ns={ns};s=Faktor").write_value(ua.Variant(5, ua.VariantType.Int16))


async def test_runtime_error_puts_plc_into_stop(plc):
    await plc.load_program("PROGRAM E VAR d : INT; r : INT; END_VAR\nr := 10 / d;\nEND_PROGRAM", version=2)
    plc.run()
    await asyncio.sleep(0.1)
    assert plc.mode == STOP
    assert plc.last_error["line"] == 2
    assert any("Division" in d.message for d in plc.diagnostics)


async def test_warm_download_keeps_values_while_running(plc):
    plc.write_variable("Start", True)
    plc.run()
    await asyncio.sleep(0.15)
    before = plc.program.variables["ZAEHLER"].value
    assert before > 0
    await plc.load_program(SRC.replace("Zaehler + 1", "Zaehler + 1000"), version=2)
    assert plc.mode == RUN
    await asyncio.sleep(0.05)
    assert plc.program.variables["ZAEHLER"].value >= before + 1000
    # The S7 layout survives the download
    assert [e["address"] for e in plc.s7.layout()][:2] == ["DB1.DBX0.0", "DB1.DBW2"]


async def test_write_variable_validation(plc):
    with pytest.raises(KeyError):
        plc.write_variable("gibtsnicht", 1)
    with pytest.raises(PermissionError):
        plc.write_variable("Faktor", 3)
    assert plc.write_variable("Sollwert", 70000) == 70000 - 65536  # INT wraps
