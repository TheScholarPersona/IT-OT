"""Tests of the feature catalog tool (evidence for the area 'katalog')."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import yaml

from feature_catalog.analysis import analyse
from feature_catalog.discover import matches_prefix, python_test_calls
from feature_catalog.junit import read_reports
from feature_catalog.loader import load
from feature_catalog.view import catalog_data, write_view

REPO = Path(__file__).resolve().parents[3]

TESTS_PY = '''
def test_creates_item(client):
    body = client.post("/api/items", json={"name": "x"}).json()
    assert body["name"] == "x"


def test_rejects_duplicate(client):
    r = client.post("/api/items", json={"name": "x"})
    assert r.status_code == 409


def test_status_only(client):
    r = client.get("/api/items")
    assert r.status_code == 200


def test_without_assertion(client):
    client.get("/api/items")


def test_unrelated():
    assert 1 + 1 == 2
'''

CATALOG = {
    "schemaVersion": 1,
    "title": "Demo",
    "sources": {"routes": "catalog/discovered/routes.json", "testDirs": ["tests"]},
    "areas": [{
        "id": "demo", "title": "Demo", "summary": "Demo-Bereich", "status": "katalogisiert",
        "owns": {"endpoints": ["/api/items"]},
        "groups": [{"id": "demo.g", "title": "Gruppe"}],
    }],
    "comparisons": [],
}

FEATURE = {
    "id": "demo.anlegen", "title": "Anlegen", "group": "demo.g", "summary": "Legt an.",
    "usage": [{"channel": "api", "text": "POST /api/items"}],
    "technical": {"components": ["src/app.py"], "endpoints": ["POST /api/items", "GET /api/items"]},
    "acceptance": [{"id": "angelegt", "kind": "effekt", "text": "Ein Eintrag wird angelegt."}],
    "evidence": [{"kind": "integration", "file": "tests/test_items.py", "test": "test_creates_item", "covers": ["angelegt"]}],
}

ROUTES = [{"kind": "http", "path": "/api/items", "methods": ["GET", "POST"], "name": "items", "summary": ""}]


def make_repo(tmp_path: Path, features=None, catalog=None, routes=None, review=None, comparisons=None) -> Path:
    (tmp_path / "catalog" / "features").mkdir(parents=True)
    (tmp_path / "catalog" / "discovered").mkdir()
    (tmp_path / "catalog" / "comparisons").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("def create_item():\n    return {}\n", encoding="utf-8")
    (tmp_path / "tests" / "test_items.py").write_text(TESTS_PY, encoding="utf-8")
    (tmp_path / "catalog" / "catalog.yaml").write_text(yaml.safe_dump(catalog or CATALOG, allow_unicode=True), encoding="utf-8")
    (tmp_path / "catalog" / "discovered" / "routes.json").write_text(json.dumps(ROUTES if routes is None else routes), encoding="utf-8")
    feats = [FEATURE] if features is None else features
    (tmp_path / "catalog" / "features" / "demo.yaml").write_text(
        yaml.safe_dump({"area": "demo", "features": feats}, allow_unicode=True), encoding="utf-8")
    if review is not None:
        (tmp_path / "catalog" / "review.yaml").write_text(yaml.safe_dump({"features": review}, allow_unicode=True), encoding="utf-8")
    for cid, data in (comparisons or {}).items():
        (tmp_path / "catalog" / "comparisons" / f"{cid}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return tmp_path


def feature(**changes) -> dict:
    f = copy.deepcopy(FEATURE)
    f.update(changes)
    return f


def junit(tmp_path: Path, cases: dict[str, str]) -> Path:
    """cases: test name -> 'pass' | 'fail' | 'skip'."""
    d = tmp_path / "reports"
    d.mkdir(exist_ok=True)
    body = []
    for name, outcome in cases.items():
        inner = {"pass": "", "fail": '<failure message="boom"/>', "skip": '<skipped message="no docker"/>'}[outcome]
        body.append(f'<testcase classname="tests.test_items" name="{name}">{inner}</testcase>')
    (d / "pytest.xml").write_text(f'<testsuites><testsuite name="pytest">{"".join(body)}</testsuite></testsuites>', encoding="utf-8")
    return d


def codes(analysis, level=None) -> list[str]:
    return [f.code for f in analysis.findings if level is None or f.level == level]


# ------------------------------------------------------------------ real catalog
def test_real_catalog_has_no_errors():
    a = analyse(load(REPO))
    assert [f"{f.code}: {f.message}" for f in a.errors] == []


def test_assigns_every_discovered_component_to_an_area():
    a = analyse(load(REPO))
    excluded = {e.item for e in a.loaded.catalog.exclusions.endpoints}
    unowned = [item for (kind, item), area in a.owner.items() if area is None and item not in excluded]
    assert unowned == []
    assert "UNOWNED" not in codes(a)
    assert ("endpoints", "PUT /api/plcs/{plc_id}/program") in a.owner
    assert a.owner[("endpoints", "PUT /api/plcs/{plc_id}/program")] == "programme"


# ------------------------------------------------------------------ code alignment
def test_reports_unassigned_components_but_never_creates_features(tmp_path):
    f = feature(technical={"components": ["src/app.py"], "endpoints": ["POST /api/items"]})
    root = make_repo(tmp_path, features=[f])
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "catalog").rglob("*.yaml")}
    a = analyse(load(root))
    unassigned = [x for x in a.findings if x.code == "UNASSIGNED"]
    assert len(unassigned) == 1 and "GET /api/items" in unassigned[0].message
    assert unassigned[0].level == "error"  # area is 'katalogisiert'
    assert [fid for _, feat in a.loaded.features for fid in [feat.id]] == ["demo.anlegen"]
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "catalog").rglob("*.yaml")} == before


def test_reports_unowned_components(tmp_path):
    routes = ROUTES + [{"kind": "http", "path": "/api/other", "methods": ["GET"], "name": "o", "summary": ""}]
    a = analyse(load(make_repo(tmp_path, routes=routes)))
    assert any(x.code == "UNOWNED" and "GET /api/other" in x.message for x in a.findings)


def test_prefix_matches_whole_segments_only():
    assert matches_prefix("/v1/orders", "/v1/orders")
    assert matches_prefix("/v1/orders/{id}/lines", "/v1/orders")
    assert not matches_prefix("/v1/orders-export", "/v1/orders")
    assert not matches_prefix("/v1/order", "/v1/orders")


def test_reports_references_to_removed_items(tmp_path):
    f = feature(technical={"components": ["src/app.py", "src/gone.py"],
                           "endpoints": ["POST /api/items", "GET /api/items", "DELETE /api/items"]},
                dependsOn=["demo.gibt-es-nicht"],
                evidence=[{"kind": "unit", "file": "tests/test_items.py", "test": "test_renamed", "covers": ["angelegt"]}])
    a = analyse(load(make_repo(tmp_path, features=[f])))
    found = codes(a, "error")
    for code in ("UNKNOWN_ENDPOINT", "UNKNOWN_COMPONENT", "UNKNOWN_TEST", "UNKNOWN_DEPENDENCY"):
        assert code in found, code


# ------------------------------------------------------------------ evidence rules
def test_requires_evidence_and_an_effect_criterion(tmp_path):
    f = feature(evidence=[], acceptance=[{"id": "r", "kind": "regel", "text": "Regel"}])
    a = analyse(load(make_repo(tmp_path, features=[f])))
    assert "EVIDENCE_MISSING" in codes(a, "error")
    assert "ACCEPTANCE_MISSING" in codes(a, "error")
    assert a.features["demo.anlegen"].status == "teilweise"


def test_requires_a_passed_evidence_for_every_criterion(tmp_path):
    f = feature(acceptance=FEATURE["acceptance"] + [{"id": "zweites", "kind": "effekt", "text": "Noch etwas."}],
                evidence=FEATURE["evidence"] + [{"kind": "unit", "file": "tests/test_items.py", "test": "test_status_only", "covers": []}])
    root = make_repo(tmp_path, features=[f])
    a = analyse(load(root), read_reports(junit(tmp_path, {"test_creates_item": "pass", "test_status_only": "pass"}), root))
    assert any(x.code == "ACCEPTANCE_UNCOVERED" and "zweites" in x.message for x in a.findings)
    assert "EVIDENCE_UNLINKED" in codes(a, "error")
    assert a.features["demo.anlegen"].uncovered == ["zweites"]


def test_flags_failed_skipped_and_missing_evidence(tmp_path):
    f = feature(evidence=[
        {"kind": "integration", "file": "tests/test_items.py", "test": "test_creates_item", "covers": ["angelegt"]},
        {"kind": "integration", "file": "tests/test_items.py", "test": "test_rejects_duplicate", "covers": ["angelegt"]},
        {"kind": "integration", "file": "tests/test_items.py", "test": "test_status_only", "covers": ["angelegt"]},
    ])
    root = make_repo(tmp_path, features=[f])
    reports = read_reports(junit(tmp_path, {"test_creates_item": "fail", "test_rejects_duplicate": "skip"}), root)
    a = analyse(load(root), reports)
    found = codes(a, "error")
    assert {"EVIDENCE_FAILED", "EVIDENCE_SKIPPED", "EVIDENCE_NOT_RUN", "ACCEPTANCE_UNCOVERED"} <= set(found)
    assert a.features["demo.anlegen"].status == "teilweise"

    ok = analyse(load(root), read_reports(junit(tmp_path, {"test_creates_item": "pass",
                                                            "test_rejects_duplicate": "pass",
                                                            "test_status_only": "pass"}), root))
    assert ok.features["demo.anlegen"].status == "nachgewiesen"


def test_detects_evidence_without_assertion_status_only_or_unrelated(tmp_path):
    f = feature(evidence=[
        {"kind": "unit", "file": "tests/test_items.py", "test": "test_creates_item", "covers": ["angelegt"]},
        {"kind": "unit", "file": "tests/test_items.py", "test": "test_without_assertion", "covers": ["angelegt"]},
        {"kind": "unit", "file": "tests/test_items.py", "test": "test_status_only", "covers": ["angelegt"]},
        {"kind": "unit", "file": "tests/test_items.py", "test": "test_unrelated", "covers": ["angelegt"]},
    ])
    a = analyse(load(make_repo(tmp_path, features=[f])))
    by_code = {x.code: x.message for x in a.findings}
    assert "test_without_assertion" in by_code["EVIDENCE_NO_ASSERTION"]
    assert "test_status_only" in by_code["EVIDENCE_STATUS_ONLY"]
    assert "test_unrelated" in by_code["EVIDENCE_UNRELATED"]
    assert not any(x.code.startswith("EVIDENCE_") and "test_creates_item" in x.message for x in a.findings)


def test_requires_the_rule_code_as_assertion(tmp_path):
    f = feature(rules=["Doppelte Namen werden mit `409` abgelehnt.", "Leere Namen mit `422`."],
                acceptance=FEATURE["acceptance"] + [
                    {"id": "doppelt", "kind": "regel", "text": "Doppelt", "code": "409"}],
                evidence=FEATURE["evidence"] + [
                    {"kind": "unit", "file": "tests/test_items.py", "test": "test_creates_item", "covers": ["doppelt"]}])
    a = analyse(load(make_repo(tmp_path, features=[f])))
    assert any(x.code == "RULE_WITHOUT_ACCEPTANCE" and "422" in x.message for x in a.findings)
    assert any(x.code == "RULE_CODE_NOT_ASSERTED" and "409" in x.message for x in a.findings)

    f["evidence"][-1]["test"] = "test_rejects_duplicate"
    f["rules"] = f["rules"][:1]
    fixed = analyse(load(make_repo(tmp_path / "b", features=[f])))
    assert "RULE_CODE_NOT_ASSERTED" not in codes(fixed)
    assert "RULE_WITHOUT_ACCEPTANCE" not in codes(fixed)


def test_detects_calls_with_method_but_not_plain_path_lists(tmp_path):
    p = tmp_path / "test_calls.py"
    p.write_text('PATHS = ["/api/listed"]\n\ndef test_x(c, pid):\n'
                 '    c.get("/api/items")\n    c.put(f"/api/items/{pid}/name?x=1")\n'
                 '    c.websocket_connect(f"/api/items/{pid}/stream")\n', encoding="utf-8")
    calls = [(m, path) for m, path, _ in python_test_calls(p)]
    assert calls == [("GET", "/api/items"), ("PUT", "/api/items/{x}/name"), ("WS", "/api/items/{x}/stream")]
    routes = ROUTES + [{"kind": "http", "path": "/api/items/{id}", "methods": ["DELETE"], "name": "d", "summary": ""}]
    f = feature(technical={"components": ["src/app.py"],
                           "endpoints": ["POST /api/items", "GET /api/items", "DELETE /api/items/{id}"]})
    a = analyse(load(make_repo(tmp_path / "r", features=[f], routes=routes)))
    untested = [x.message for x in a.findings if x.code == "ENDPOINT_UNTESTED"]
    assert untested == ["Kein Test ruft DELETE /api/items/{id} erkennbar auf"]


def test_reads_mocha_reports_by_file_and_title(tmp_path):
    (tmp_path / "test").mkdir()
    spec = tmp_path / "test" / "x_spec.js"
    spec.write_text('it("writes a value", async () => { assert.strictEqual(1, 1); });\n', encoding="utf-8")
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "mocha.xml").write_text(
        f'<testsuites><testsuite name="s" file="{spec}"><testcase name="s writes a value" classname="writes a value">'
        '<failure message="nope"/></testcase></testsuite></testsuites>', encoding="utf-8")
    reports = read_reports(rep, tmp_path)
    assert reports.result("test/x_spec.js", "writes a value") == ("fehlgeschlagen", "nope")
    assert reports.result("test/x_spec.js", "other title")[0] == "nicht gelaufen"


# ------------------------------------------------------------------ schema, comparison, view
def test_rejects_unknown_fields_and_invalid_values(tmp_path):
    f = feature(colour="blau", usage=[{"channel": "fax", "text": "x"}])
    a = analyse(load(make_repo(tmp_path, features=[f])))
    messages = " | ".join(x.message for x in a.findings if x.code == "SCHEMA")
    assert "colour" in messages and "channel" in messages


def test_requires_classification_for_a_complete_comparison(tmp_path):
    cat = copy.deepcopy(CATALOG)
    cat["comparisons"] = [{"id": "markt", "title": "Markt", "complete": True}]
    comp = {"id": "markt", "title": "Markt", "topics": [{"id": "a", "title": "A", "status": "vorhanden"}]}
    a = analyse(load(make_repo(tmp_path, catalog=cat, comparisons={"markt": comp})))
    assert "COMPARISON_MISSING" in codes(a, "error")
    b = analyse(load(make_repo(tmp_path / "b", catalog=cat, comparisons={"markt": comp},
                               features=[feature(comparisons={"markt": "nope"})])))
    assert any(x.code == "SCHEMA" and "nope" in x.message for x in b.findings)
    c = analyse(load(make_repo(tmp_path / "c", catalog=cat, comparisons={"markt": comp},
                               features=[feature(comparisons={"markt": "a"})])))
    assert "COMPARISON_MISSING" not in codes(c)
    topic = catalog_data(c)["comparisons"][0]["topics"][0]
    assert topic["features"] == ["demo.anlegen"]


def test_builds_a_standalone_view(tmp_path):
    root = make_repo(tmp_path, review=[{**feature(id="demo.spaeter", title="Später", evidence=[], acceptance=[]),
                                        "state": "nicht-nachgewiesen", "reason": "noch kein Test"}])
    a = analyse(load(root))
    html_path, json_path = write_view(a, tmp_path / "dist")
    html = html_path.read_text(encoding="utf-8")
    assert not re.search(r"<script[^>]+src=|<link[^>]+href=\"http", html)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert [f["id"] for f in data["features"]] == ["demo.anlegen", "demo.spaeter"]
    assert data["features"][1]["inReview"] and data["stats"]["review"] == 1
    embedded = re.search(r"const DATA = (.*?);\n", html, re.S).group(1)
    assert json.loads(embedded.replace("<\\/", "</"))["title"] == "Demo"
