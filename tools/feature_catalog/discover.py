"""Discover the components of the application without changing it.

* HTTP/WebSocket endpoints and UI routes: JSON export written by a test
  (``tests/test_catalog_export.py``) from the running FastAPI app.
* CLI sub-commands: ``add_parser("name")`` calls found with ``ast``.
* Node-RED node types and admin endpoints: ``RED.nodes.registerType`` /
  ``RED.httpAdmin.<method>`` in the package sources.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .schema import Sources


@dataclass
class Discovered:
    endpoints: dict[str, str] = field(default_factory=dict)  # "GET /x" -> source/description
    commands: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)
    uiRoutes: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def kinds(self) -> dict[str, dict[str, str]]:
        return {"endpoints": self.endpoints, "commands": self.commands,
                "nodes": self.nodes, "uiRoutes": self.uiRoutes}


def endpoint_path(endpoint: str) -> str:
    """'GET /api/x' -> '/api/x'."""
    return endpoint.split(" ", 1)[1] if " " in endpoint else endpoint


def matches_prefix(path: str, prefix: str) -> bool:
    """'/a/b' matches '/a/b' and '/a/b/…', not '/a/b-export'."""
    if prefix == "/":
        return path == "/"
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _express_to_template(path: str) -> str:
    return re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", path)


def discover(root: Path, sources: Sources) -> Discovered:
    d = Discovered()
    root = Path(root)

    if sources.routes:
        path = root / sources.routes
        if not path.exists():
            d.problems.append(f"Exportdatei {sources.routes} fehlt – Export-Test ausführen")
        else:
            for r in json.loads(path.read_text(encoding="utf-8")):
                desc = r.get("summary") or r.get("name") or ""
                if r["kind"] == "ui":
                    d.uiRoutes[r["path"]] = desc
                else:
                    for method in r["methods"]:
                        d.endpoints[f"{method} {r['path']}"] = desc

    for rel in sources.cliModules:
        path = root / rel
        if not path.exists():
            d.problems.append(f"CLI-Modul {rel} fehlt")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_parser" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                name = f"{sources.cliName} {node.args[0].value}".strip()
                help_kw = next((k.value.value for k in node.keywords
                                if k.arg == "help" and isinstance(k.value, ast.Constant)), "")
                d.commands[name] = help_kw

    for rel in sources.nodeRedFiles:
        path = root / rel
        if not path.exists():
            d.problems.append(f"Node-RED-Datei {rel} fehlt")
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"RED\.nodes\.registerType\(\s*[\"']([^\"']+)[\"']", text):
            d.nodes[m.group(1)] = rel
        for m in re.finditer(r"RED\.httpAdmin\.(get|post|put|delete)\(\s*[\"']([^\"']+)[\"']", text):
            d.endpoints[f"{m.group(1).upper()} {_express_to_template(m.group(2))}"] = f"Node-RED-Admin ({rel})"
    return d


# ------------------------------------------------------------------ test calls
_CALL_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE",
                 "patch": "PATCH", "websocket_connect": "WS"}


def _string_template(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("{x}")
        return "".join(parts)
    return None


def python_test_calls(path: Path) -> list[tuple[str, str, int]]:
    """Endpoint calls in a pytest file: (METHOD, path template, line).

    Only calls with an explicit HTTP method count (client.get("/x")); bare path
    strings do not.
    """
    calls = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return calls
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method = _CALL_METHODS.get(node.func.attr)
        if not method or not node.args:
            continue
        tpl = _string_template(node.args[0])
        if tpl and tpl.startswith("/"):
            calls.append((method, tpl.split("?", 1)[0], node.lineno))
    return calls


_JS_CALL_RE = re.compile(
    r"""request\(\s*["'](GET|POST|PUT|DELETE|PATCH)["']\s*,\s*[`"']([^`"']+)[`"']""")


_JS_SUPERTEST_RE = re.compile(r"""\.(get|post|put|delete|patch)\(\s*[`"'](/[^`"']*)[`"']""")


def js_test_calls(path: Path) -> list[tuple[str, str, int]]:
    """Endpoint calls in a mocha file: client.request("GET", "/x") or supertest .get("/x")."""
    calls = []
    text = path.read_text(encoding="utf-8")
    found = [(m.group(1), m.group(2), m.start()) for m in _JS_CALL_RE.finditer(text)]
    found += [(m.group(1).upper(), m.group(2), m.start()) for m in _JS_SUPERTEST_RE.finditer(text)]
    for method, raw, pos in found:
        tpl = re.sub(r"\$\{[^}]*\}", "{x}", raw).split("?", 1)[0]
        calls.append((method, tpl, text.count("\n", 0, pos) + 1))
    return calls


def call_matches(call_path: str, template: str) -> bool:
    """Compare a called path (may contain {x}) with an endpoint template."""
    a = [s for s in call_path.split("/") if s != ""]
    b = [s for s in template.split("/") if s != ""]
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y or y.startswith("{") or "{" in x:
            continue
        return False
    return True
