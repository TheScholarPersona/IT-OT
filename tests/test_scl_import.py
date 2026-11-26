"""Siemens SCL sources from the TIA Portal ("Generate source from blocks")."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vplc.manager.api import create_app
from vplc.st import PLCRuntimeError, STSyntaxError, check_source, compile_source
from vplc.st.parser import is_scl

EXAMPLE = (Path(__file__).resolve().parents[1] / "examples" / "pumpenstation.scl").read_text(encoding="utf-8")


def messages(source: str) -> str:
    return " | ".join(e["message"] for e in check_source(source))


def test_tia_source_compiles_and_runs_like_on_the_plc():
    prog = compile_source("﻿" + EXAMPLE)  # exported files may start with a BOM
    assert prog.dialect == "SCL" and prog.name == "Main"
    db = prog.variables["ANLAGE_DB"]
    # start values from the DATA_BLOCK BEGIN section (and kept for a cold restart)
    assert db.value["MAXDREHZAHL"] == 2400.0 and db.init["MAXDREHZAHL"] == 2400.0
    assert db.value["PUMPE"]["BEZEICHNUNG"] == "P-101"
    db.value["START"] = True
    for t in range(0, 1900, 100):
        prog.execute(t)
    assert not db.value["PUMPE"]["LAEUFT"]  # TON_TIME: start-up delay of 2 s
    for t in range(1900, 2600, 100):
        prog.execute(t)
    pumpe = db.display()["Pumpe"]
    assert pumpe["Laeuft"] and pumpe["Drehzahl"] == 1500.0  # FC_Skalieren: 13824/27648*3000
    assert pumpe["Betriebsstunden"] == 6
    db.value["SOLLWERT"] = 27648
    prog.execute(2700)
    assert db.value["PUMPE"]["DREHZAHL"] == 2400.0  # Void FC with VAR_OUTPUT limits the speed
    db.value["STOPP"] = True
    prog.execute(2800)
    assert not db.value["PUMPE"]["LAEUFT"]


SCL_ELEMENTS = """
TYPE Punkt : STRUCT x, y : Int; END_STRUCT; END_TYPE

FUNCTION_BLOCK "FB_Test"
TITLE = Testbaustein mit Sonderzeichen: äöü (100 %)
{ S7_Optimized_Access := 'TRUE' }
AUTHOR : 'Muster'
FAMILY : Demo
VERSION : 1.2
KNOW_HOW_PROTECT
   VAR_INPUT
      Takt : Bool;
   END_VAR
   VAR_OUTPUT
      Zaehlwert : Int;
      Maske : Word;
      Gross : DInt;
   END_VAR
   VAR
      Uhr : IEC_TIMER;
      Zaehler : CTU_INT;
      P : Punkt;
   END_VAR
BEGIN
	REGION Zählen – mit Umlauten und Satzzeichen!
	    #Zaehler(CU := #Takt, R := FALSE, PV := 100);
	    #Zaehlwert := #Zaehler.CV;
	END_REGION
	#Maske := W#16#00FF AND DW#16#F0F0;
	#Gross := L#100000;
	#P.x := #Zaehlwert;
END_FUNCTION_BLOCK

DATA_BLOCK "Test_DB" "FB_Test"
BEGIN
END_DATA_BLOCK

DATA_BLOCK "Werte"
VERSION : 0.1
NON_RETAIN
   STRUCT
      Puls : Bool;
      Ergebnis : Int;
      M : Word;
   END_STRUCT;
BEGIN
END_DATA_BLOCK

ORGANIZATION_BLOCK "Main"
TITLE = "Main Program Sweep (Cycle)"
BEGIN
	"Test_DB"(Takt := "Werte".Puls, Zaehlwert => "Werte".Ergebnis, Maske => "Werte".M);
END_ORGANIZATION_BLOCK
"""


def test_scl_syntax_elements():
    assert is_scl(SCL_ELEMENTS)
    prog = compile_source(SCL_ELEMENTS)
    werte = prog.variables["WERTE"]
    for _ in range(3):
        werte.value["PULS"] = True
        prog.execute(0)
        werte.value["PULS"] = False
        prog.execute(0)
    assert werte.value["ERGEBNIS"] == 3 and werte.value["M"] == 0x00F0
    fb = prog.fbs["TEST_DB"].block
    assert fb.variables["GROSS"].value == 100000 and fb.variables["P"].value["X"] == 3
    assert type(fb.fbs["UHR"].block).__name__ == "TON" and type(fb.fbs["ZAEHLER"].block).__name__ == "CTU"


def test_global_data_blocks_are_visible_in_blocks_but_locals_win():
    prog = compile_source("""
DATA_BLOCK "Global" VAR Wert : Int := 7; END_VAR BEGIN END_DATA_BLOCK
FUNCTION "Lies" : Int BEGIN #Lies := "Global".Wert; END_FUNCTION
FUNCTION "Lokal" : Int VAR Global : Int := 1; END_VAR BEGIN #Lokal := #Global; END_FUNCTION
ORGANIZATION_BLOCK "Main" VAR_TEMP a, b : Int; END_VAR
BEGIN #a := "Lies"(); #b := "Lokal"(); "Global".Wert := #a + #b; END_ORGANIZATION_BLOCK""")
    prog.execute(0)
    assert prog.variables["GLOBAL"].value["WERT"] == 8


def test_scl_errors():
    with pytest.raises(STSyntaxError, match="ORGANIZATION_BLOCK fehlt"):
        compile_source('DATA_BLOCK "D" VAR a : Int; END_VAR BEGIN END_DATA_BLOCK')
    with pytest.raises(STSyntaxError, match="Nur ein ORGANIZATION_BLOCK"):
        compile_source('ORGANIZATION_BLOCK "A" BEGIN END_ORGANIZATION_BLOCK ORGANIZATION_BLOCK "B" BEGIN END_ORGANIZATION_BLOCK')
    with pytest.raises(STSyntaxError, match="GOTO"):
        compile_source('ORGANIZATION_BLOCK "A" BEGIN GOTO M1; END_ORGANIZATION_BLOCK')
    with pytest.raises(STSyntaxError, match="nur Buchstaben, Ziffern"):
        compile_source('ORGANIZATION_BLOCK "Main Cycle" BEGIN END_ORGANIZATION_BLOCK')
    text = messages("""
FUNCTION_BLOCK "FB" VAR_INPUT x : Int; END_VAR BEGIN END_FUNCTION_BLOCK
FUNCTION "Nix" : Void VAR_INPUT a : Int; END_VAR BEGIN END_FUNCTION
DATA_BLOCK "I" "FB" BEGIN x := 5; END_DATA_BLOCK
ORGANIZATION_BLOCK "Main" VAR_TEMP r : Int; END_VAR
BEGIN #r := "Nix"(a := 1); #r := "Fehlt".x; END_ORGANIZATION_BLOCK""")
    assert "Startwerte in Instanz-Datenbausteinen" in text
    assert "liefert keinen Wert (VOID)" in text
    assert "Unbekannte Variable 'Fehlt'" in text


def test_scl_only_syntax_is_rejected_in_plain_structured_text():
    with pytest.raises(STSyntaxError, match="nur in SCL"):
        compile_source("PROGRAM P VAR x : INT; END_VAR #x := 1; END_PROGRAM")


def test_scl_through_api_with_start_values_and_cold_restart(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))
    with TestClient(create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")) as c:
        assert "pumpenstation" in c.get("/api/info").json()["examples"]
        source = c.get("/api/examples/pumpenstation").text
        check = c.post("/api/check", json={"source": source}).json()
        assert check == {"ok": True, "errors": [], "dialect": "SCL"}
        pid = c.post("/api/plcs", json={"name": "Station", "source": source}).json()["id"]
        status = c.get(f"/api/plcs/{pid}").json()
        assert status["program"] == "Main" and status["dialect"] == "SCL"
        assert any("SCL aus TIA Portal" in d["message"] for d in status["diagnostics"])
        assert c.put(f"/api/plcs/{pid}/variables/Anlage_DB.MaxDrehzahl", json={"value": 100}).status_code == 200
        c.post(f"/api/plcs/{pid}/reset")
        v = {x["name"]: x for x in c.get(f"/api/plcs/{pid}/variables").json()}
        assert v["Anlage_DB"]["value"]["MaxDrehzahl"] == 2400.0  # DB start value, not the declaration's 2500
        assert v["Anlage_DB"]["s7_address"].startswith("DB1.DBX0.0")
        assert v["Pumpe1_DB.LAEUFT"]["section"] == "FB_PUMPE"
