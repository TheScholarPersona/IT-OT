"""REST API including versioning, diff, audit log and restore after restart."""

import pytest
from fastapi.testclient import TestClient

from vplc.manager.api import create_app

PROG_V1 = "PROGRAM P\nVAR Zaehler : INT; END_VAR\nZaehler := Zaehler + 1;\nEND_PROGRAM\n"
PROG_V2 = "PROGRAM P\nVAR Zaehler : INT; END_VAR\nZaehler := Zaehler + 2;\nEND_PROGRAM\n"


@pytest.fixture
def make_client(tmp_path, port_factory, monkeypatch):
    monkeypatch.setenv("VPLC_S7_BASE_PORT", str(port_factory()))
    monkeypatch.setenv("VPLC_OPCUA_BASE_PORT", str(port_factory()))

    def factory(token=None):
        return TestClient(create_app(data_dir=str(tmp_path), api_token=token or "", host="127.0.0.1"))
    return factory


def H(user="anna"):
    return {"X-User": user}


def test_full_lifecycle(make_client):
    with make_client() as c:
        r = c.post("/api/plcs", json={"name": "Linie1", "cycle_ms": 5}, headers=H())
        assert r.status_code == 201, r.text
        plc = r.json()
        pid = plc["id"]
        assert plc["mode"] == "STOP" and plc["s7"]["running"] and plc["opcua"]["running"]

        assert c.post(f"/api/plcs/{pid}/run", headers=H()).status_code == 409  # no program yet

        bad = c.put(f"/api/plcs/{pid}/program", json={"source": "PROGRAM P\nx := 1;\nEND_PROGRAM"}, headers=H())
        assert bad.status_code == 422 and bad.json()["errors"][0]["line"] == 2

        r = c.put(f"/api/plcs/{pid}/program", json={"source": PROG_V1, "comment": "erste"}, headers=H())
        assert r.status_code == 200 and r.json()["version"]["version"] == 1
        r = c.put(f"/api/plcs/{pid}/program", json={"source": PROG_V1}, headers=H())
        assert r.json()["version"]["version"] == 1  # unchanged source → no new version
        r = c.put(f"/api/plcs/{pid}/program", json={"source": PROG_V2, "comment": "schneller"}, headers=H("ben"))
        assert r.json()["version"]["version"] == 2

        assert c.post(f"/api/plcs/{pid}/run", headers=H()).json()["mode"] == "RUN"
        vars_ = c.get(f"/api/plcs/{pid}/variables", headers=H()).json()
        assert vars_[0]["name"] == "Zaehler" and vars_[0]["s7_address"] == "DB1.DBW0"

        versions = c.get(f"/api/plcs/{pid}/versions", headers=H()).json()
        assert [(v["version"], v["author"]) for v in versions] == [(2, "ben"), (1, "anna")]
        diff = c.get(f"/api/plcs/{pid}/diff?a=1&b=2", headers=H()).text
        assert "-Zaehler := Zaehler + 1;" in diff and "+Zaehler := Zaehler + 2;" in diff

        r = c.post(f"/api/plcs/{pid}/versions/1/activate", headers=H())
        assert r.status_code == 200
        assert c.get(f"/api/plcs/{pid}", headers=H()).json()["program_version"] == 1

        r = c.put(f"/api/plcs/{pid}/variables/Zaehler", json={"value": 42}, headers=H())
        assert r.status_code == 200
        assert c.put(f"/api/plcs/{pid}/variables/nope", json={"value": 1}, headers=H()).status_code == 404

        actions = [e["action"] for e in c.get(f"/api/audit?plc_id={pid}", headers=H()).json()]
        assert actions[0] == "variable.write"
        assert {"plc.create", "program.download", "program.activate", "plc.run"} <= set(actions)

        assert c.post("/api/plcs", json={"name": "linie1"}, headers=H()).status_code == 409
        assert c.post("/api/plcs", json={"name": "x", "cycle_ms": 0}, headers=H()).status_code == 400


def test_restore_after_restart(make_client):
    with make_client() as c:
        pid = c.post("/api/plcs", json={"name": "Persistenz", "source": PROG_V1}, headers=H()).json()["id"]
        c.post(f"/api/plcs/{pid}/run", headers=H())
    with make_client() as c:
        s = c.get(f"/api/plcs/{pid}", headers=H()).json()
        assert s["mode"] == "RUN" and s["program_version"] == 1


def test_check_endpoint_and_examples(make_client):
    with make_client() as c:
        info = c.get("/api/info").json()
        assert {"ampel", "tank", "foerderband"} <= set(info["examples"])
        for name in info["examples"]:
            src = c.get(f"/api/examples/{name}").text
            assert c.post("/api/check", json={"source": src}).json() == {"ok": True, "errors": []}
        assert c.get("/api/examples/..%2Fpyproject").status_code == 404


def test_token_auth(make_client):
    with make_client(token="geheim") as c:
        assert c.get("/api/plcs").status_code == 401
        assert c.get("/api/plcs", headers={"Authorization": "Bearer falsch"}).status_code == 401
        assert c.get("/api/plcs", headers={"Authorization": "Bearer geheim"}).status_code == 200
        assert c.get("/api/health").status_code == 200


def test_web_ui_is_served(make_client):
    with make_client() as c:
        r = c.get("/")
        assert r.status_code == 200 and "vPLC" in r.text
        assert c.get("/static/app.js").status_code == 200
