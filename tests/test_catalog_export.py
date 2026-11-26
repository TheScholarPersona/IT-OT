"""Keeps catalog/discovered/routes.json in sync with the running app.

The feature catalog reads endpoints from this file instead of importing the
application. Regenerate with:  UPDATE_SNAPSHOTS=1 pytest tests/test_catalog_export.py
"""

import json
import os
from pathlib import Path

from starlette.routing import Mount, WebSocketRoute

from vplc.manager.api import create_app

SNAPSHOT = Path(__file__).resolve().parents[1] / "catalog" / "discovered" / "routes.json"
UI_PATHS = {"/"}  # served HTML page; static assets come as a Mount


def export_routes(tmp_path) -> list[dict]:
    app = create_app(data_dir=str(tmp_path), api_token="", host="127.0.0.1")
    routes = []
    for r in app.routes:
        if isinstance(r, Mount):
            routes.append({"kind": "ui", "path": r.path, "methods": ["GET"], "name": r.name, "summary": "statische Dateien"})
        elif isinstance(r, WebSocketRoute):
            routes.append({"kind": "ws", "path": r.path, "methods": ["WS"], "name": r.name,
                           "summary": (r.endpoint.__doc__ or "").strip().splitlines()[0] if r.endpoint.__doc__ else ""})
        else:
            methods = sorted(m for m in (r.methods or []) if m != "HEAD")
            kind = "ui" if r.path in UI_PATHS else "http"
            routes.append({"kind": kind, "path": r.path, "methods": methods, "name": r.name,
                           "summary": getattr(r, "summary", None) or ""})
    return sorted(routes, key=lambda x: (x["path"], x["methods"]))


def test_routes_snapshot_is_current(tmp_path):
    current = json.dumps(export_routes(tmp_path), indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8")
    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "catalog/discovered/routes.json ist veraltet – mit UPDATE_SNAPSHOTS=1 neu schreiben "
        "und den Feature-Katalog anpassen"
    )
