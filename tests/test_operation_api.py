"""Operating a vPLC via REST and CLI: delete, stop, cold restart, status, S7 layout, check, serve."""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from vplc.__main__ import main as cli_main
from vplc.manager.api import create_app

ROOT = Path(__file__).resolve().parents[1]
PROG = """PROGRAM P
VAR_INPUT Soll : INT := 5; END_VAR
VAR Zaehler : DINT; Merker : BOOL; END_VAR
Zaehler := Zaehler + 1;
END_PROGRAM
"""


@pytest.fixture
def client(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))
    with TestClient(create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")) as c:
        yield c


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_deletes_plc_together_with_its_versions(client):
    pid = client.post("/api/plcs", json={"name": "Weg", "source": PROG}).json()["id"]
    listed = client.get("/api/plcs").json()
    assert [(p["id"], p["name"], p["program"]) for p in listed] == [(pid, "Weg", "P")]
    assert client.delete(f"/api/plcs/{pid}").status_code == 204
    assert client.get(f"/api/plcs/{pid}").status_code == 404
    assert client.get(f"/api/plcs/{pid}/versions").status_code == 404
    assert [p["name"] for p in client.get("/api/plcs").json()] == []
    actions = [e["action"] for e in client.get("/api/audit").json()]
    assert actions[0] == "plc.delete"


def test_stop_halts_the_scan_cycle(client):
    pid = client.post("/api/plcs", json={"name": "Halt", "source": PROG, "cycle_ms": 2}).json()["id"]
    client.post(f"/api/plcs/{pid}/run")
    assert wait_until(lambda: client.get(f"/api/plcs/{pid}").json()["scan_count"] > 5)
    stopped = client.post(f"/api/plcs/{pid}/stop").json()
    assert stopped["mode"] == "STOP"
    count = client.get(f"/api/plcs/{pid}").json()["scan_count"]
    time.sleep(0.1)
    assert client.get(f"/api/plcs/{pid}").json()["scan_count"] == count


def test_cold_restart_resets_all_values_to_initial_values(client):
    pid = client.post("/api/plcs", json={"name": "Kalt", "source": PROG}).json()["id"]
    client.put(f"/api/plcs/{pid}/variables", json={"values": {"Soll": 42, "Merker": True, "Zaehler": 99}})
    client.post(f"/api/plcs/{pid}/reset")
    values = {v["name"]: v["value"] for v in client.get(f"/api/plcs/{pid}/variables").json()}
    assert values == {"Soll": 5, "Zaehler": 0, "Merker": False}


def test_status_reports_cycle_statistics_and_diagnostics(client):
    pid = client.post("/api/plcs", json={"name": "Diag", "source": PROG, "cycle_ms": 5}).json()["id"]
    client.post(f"/api/plcs/{pid}/run")
    assert wait_until(lambda: client.get(f"/api/plcs/{pid}").json()["scan_count"] > 3)
    s = client.get(f"/api/plcs/{pid}").json()
    assert s["mode"] == "RUN" and s["cycle_ms"] == 5
    assert s["avg_scan_us"] > 0 and s["max_scan_us"] >= s["avg_scan_us"]
    assert s["s7"]["running"] and s["s7"]["rack"] == 0 and s["s7"]["slot"] == 1
    assert s["opcua"]["endpoint"].endswith("/vplc/")
    messages = [d["message"] for d in s["diagnostics"]]
    assert "Betriebszustand RUN" in messages and any("geladen" in m for m in messages)


def test_s7_layout_lists_absolute_addresses(client):
    pid = client.post("/api/plcs", json={"name": "Layout", "source": PROG}).json()["id"]
    layout = client.get(f"/api/plcs/{pid}/s7-layout").json()
    assert [(e["name"], e["address"]) for e in layout] == [
        ("Soll", "DB1.DBW0"), ("Zaehler", "DB1.DBD2"), ("Merker", "DB1.DBX6.0")]


def test_cli_check_reports_errors_with_line_and_column(tmp_path, capsys):
    good = tmp_path / "gut.st"
    good.write_text(PROG, encoding="utf-8")
    bad = tmp_path / "fehler.st"
    bad.write_text("PROGRAM X\nVAR a : INT; END_VAR\nb := 1;\nEND_PROGRAM\n", encoding="utf-8")
    assert cli_main(["check", str(good)]) == 0
    assert capsys.readouterr().out.strip().endswith("OK")
    assert cli_main(["check", str(bad)]) == 1
    out = capsys.readouterr().out
    assert f"{bad}:3:1: Unbekannte Variable 'b'" in out


def test_cli_serve_starts_manager_and_persists_data(tmp_path, port_factory):
    port = port_factory()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
           "VPLC_S7_BASE_PORT": str(port_factory()), "VPLC_OPCUA_BASE_PORT": str(port_factory())}
    proc = subprocess.Popen([sys.executable, "-m", "vplc", "serve", "--port", str(port), "--data", str(tmp_path)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"

        def up():
            try:
                return httpx.get(f"{base}/api/health").status_code == 200
            except httpx.HTTPError:
                return False
        assert wait_until(up, timeout=15)
        r = httpx.post(f"{base}/api/plcs", json={"name": "CLI", "source": PROG})
        assert r.json()["program"] == "P"
        assert (tmp_path / "plcs.json").exists() and (tmp_path / "audit.jsonl").exists()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
