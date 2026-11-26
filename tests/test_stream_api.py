"""Integration API used by Node-RED: name lookup, bulk writes and WebSocket stream."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vplc.manager.api import create_app

PROG = """PROGRAM P
VAR_INPUT Start : BOOL; Soll : INT := 5; END_VAR
VAR_OUTPUT Ist : INT; END_VAR
VAR CONSTANT K : INT := 1; END_VAR
IF Start THEN Ist := Soll * 2; ELSE Ist := 0; END_IF;
END_PROGRAM
"""


@pytest.fixture
def make_client(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))

    def factory(token=""):
        return TestClient(create_app(data_dir=str(tmp_path), api_token=token, host="127.0.0.1"))
    return factory


def next_of(ws, kind, limit=50):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_name_lookup_and_bulk_write(make_client):
    with make_client() as c:
        pid = c.post("/api/plcs", json={"name": "Presse 1", "source": PROG}).json()["id"]
        assert c.get("/api/plcs/presse 1").json()["id"] == pid
        r = c.put("/api/plcs/Presse 1/variables", json={"values": {"Start": True, "Soll": 7}},
                  headers={"X-User": "node-red"})
        assert r.status_code == 200 and r.json()["values"] == {"Start": True, "Soll": 7}
        # all-or-nothing: one bad name rejects the whole write
        r = c.put(f"/api/plcs/{pid}/variables", json={"values": {"Soll": 9, "Nope": 1}})
        assert r.status_code == 404
        assert c.put(f"/api/plcs/{pid}/variables", json={"values": {"K": 2}}).status_code == 403
        values = {v["name"]: v["value"] for v in c.get(f"/api/plcs/{pid}/variables").json()}
        assert values["Soll"] == 7
        audit = c.get("/api/audit?plc_id=Presse 1").json()
        assert audit[0]["user"] == "node-red" and audit[0]["plc_id"] == pid


def test_stream_snapshot_changes_and_status(make_client):
    with make_client() as c:
        pid = c.post("/api/plcs", json={"name": "S", "source": PROG}).json()["id"]
        with c.websocket_connect(f"/api/plcs/{pid}/stream?interval_ms=20&variables=Ist,Start,Gibtsnicht") as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            assert snap["values"] == {"Start": False, "Ist": 0}
            assert snap["unknown"] == ["GIBTSNICHT"] and snap["status"]["mode"] == "STOP"

            c.post(f"/api/plcs/{pid}/run")
            assert next_of(ws, "status")["status"]["mode"] == "RUN"
            c.put(f"/api/plcs/{pid}/variables/Start", json={"value": True})
            changes = next_of(ws, "changes")["values"]
            while "Ist" not in changes:
                changes.update(next_of(ws, "changes")["values"])
            assert changes["Ist"] == 10

            c.put(f"/api/plcs/{pid}/program", json={"source": PROG.replace("Soll * 2", "Soll * 3")})
            snap = next_of(ws, "snapshot")
            assert snap["status"]["program_version"] == 2


def test_stream_requires_token_and_existing_plc(make_client):
    with make_client(token="t0ken") as c:
        h = {"Authorization": "Bearer t0ken"}
        pid = c.post("/api/plcs", json={"name": "A"}, headers=h).json()["id"]
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect(f"/api/plcs/{pid}/stream") as ws:
                ws.receive_json()
        assert exc.value.code == 4401
        with c.websocket_connect(f"/api/plcs/{pid}/stream?token=t0ken") as ws:
            assert ws.receive_json()["type"] == "snapshot"
        with c.websocket_connect(f"/api/plcs/{pid}/stream", headers=h) as ws:
            assert ws.receive_json()["type"] == "snapshot"
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/api/plcs/nix/stream", headers=h) as ws:
                ws.receive_json()
        assert exc.value.code == 4404
