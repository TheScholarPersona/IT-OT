"""Programs and versions: read the active program, inspect and reject versions."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from vplc.manager.api import create_app

PROG_V1 = "PROGRAM P\nVAR Zaehler : INT; END_VAR\nZaehler := Zaehler + 1;\nEND_PROGRAM\n"
PROG_V2 = "PROGRAM P\nVAR Zaehler : INT; END_VAR\nZaehler := Zaehler + 2;\nEND_PROGRAM\n"


@pytest.fixture
def client(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))
    with TestClient(create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")) as c:
        yield c


def _plc_with_two_versions(c) -> str:
    pid = c.post("/api/plcs", json={"name": "Linie2"}).json()["id"]
    c.put(f"/api/plcs/{pid}/program", json={"source": PROG_V1, "comment": "erste"}, headers={"X-User": "anna"})
    c.put(f"/api/plcs/{pid}/program", json={"source": PROG_V2, "comment": "doppelt"}, headers={"X-User": "ben"})
    return pid


def test_reads_active_program_source_and_version(client):
    pid = _plc_with_two_versions(client)
    active = client.get(f"/api/plcs/{pid}/program").json()
    assert active == {"source": PROG_V2, "version": 2}

    client.post(f"/api/plcs/{pid}/versions/1/activate")
    active = client.get(f"/api/plcs/{pid}/program").json()
    assert active == {"source": PROG_V1, "version": 1}


def test_shows_single_version_with_source_author_and_hash(client):
    pid = _plc_with_two_versions(client)
    v1 = client.get(f"/api/plcs/{pid}/versions/1").json()
    assert v1["source"] == PROG_V1
    assert v1["author"] == "anna" and v1["comment"] == "erste"
    assert v1["sha256"] == hashlib.sha256(PROG_V1.encode()).hexdigest()
    assert v1["program_name"] == "P"


def test_rejects_unknown_version_for_view_diff_and_activate(client):
    pid = _plc_with_two_versions(client)
    assert client.get(f"/api/plcs/{pid}/versions/9").status_code == 404
    assert client.get(f"/api/plcs/{pid}/diff?a=1&b=9").status_code == 404
    r = client.post(f"/api/plcs/{pid}/versions/9/activate")
    assert r.status_code == 404
    # the active program is unchanged after the rejected activation
    assert client.get(f"/api/plcs/{pid}/program").json()["version"] == 2
