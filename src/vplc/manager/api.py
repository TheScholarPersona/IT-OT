"""REST API and web UI of the vPLC manager."""

from __future__ import annotations

import asyncio
import hmac
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..st import STCompileError, STError, check_source
from ..st.stdlib import FUNCTION_BLOCKS
from .service import Conflict, NotFound, PLCManager
from .store import Store

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
EXAMPLES_DIR = Path(os.environ.get("VPLC_EXAMPLES", Path(__file__).resolve().parents[3] / "examples"))


# ------------------------------------------------------------------ schemas
class PLCCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    cycle_ms: float = 10.0
    watchdog_ms: float = 200.0
    s7_enabled: bool = True
    opcua_enabled: bool = True
    s7_port: int | None = None
    opcua_port: int | None = None
    source: str | None = None


class ProgramUpload(BaseModel):
    source: str = Field(max_length=1_000_000)
    comment: str = Field(default="", max_length=500)
    warm: bool = True


class SourceCheck(BaseModel):
    source: str = Field(max_length=1_000_000)


Scalar = bool | int | float | str
Value = Scalar | list[bool | int | float]  # lists for ARRAY variables


class VariableWrite(BaseModel):
    value: Value


class VariablesWrite(BaseModel):
    values: dict[str, Value] = Field(min_length=1, max_length=1000)


def _json_value(v):
    """JSON cannot carry NaN/Infinity; send them as strings."""
    if isinstance(v, float) and not math.isfinite(v):
        return "NaN" if math.isnan(v) else ("Infinity" if v > 0 else "-Infinity")
    return v


def _changed(old, new) -> bool:
    if isinstance(old, float) and isinstance(new, float) and math.isnan(old) and math.isnan(new):
        return False
    return old != new or type(old) is not type(new)


# ------------------------------------------------------------------ app
def create_app(data_dir: str | None = None, api_token: str | None = None,
               host: str | None = None) -> FastAPI:
    data_dir = data_dir or os.environ.get("VPLC_DATA", "data")
    api_token = api_token if api_token is not None else os.environ.get("VPLC_API_TOKEN") or None
    bind_host = host or os.environ.get("VPLC_PROTOCOL_HOST", "127.0.0.1")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = PLCManager(
            Store(data_dir),
            s7_base_port=int(os.environ.get("VPLC_S7_BASE_PORT", 10102)),
            opcua_base_port=int(os.environ.get("VPLC_OPCUA_BASE_PORT", 4840)),
            host=bind_host,
        )
        app.state.manager = manager
        await manager.restore()
        yield
        await manager.shutdown()

    app = FastAPI(title="IT-OT vPLC Manager", version=__version__, lifespan=lifespan)

    def manager(request: Request) -> PLCManager:
        return request.app.state.manager

    def user(
        authorization: str | None = Header(default=None),
        x_user: str | None = Header(default=None),
    ) -> str:
        if api_token:
            expected = f"Bearer {api_token}"
            if not authorization or not hmac.compare_digest(authorization, expected):
                raise HTTPException(401, "Ungültiges oder fehlendes API-Token")
        name = (x_user or "anonymous").strip()[:64]
        return name or "anonymous"

    @app.exception_handler(NotFound)
    async def _not_found(_, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def _conflict(_, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(STError)
    async def _st_error(_, exc: STError):
        errors = [e.to_dict() for e in exc.errors] if isinstance(exc, STCompileError) else [exc.to_dict()]
        return JSONResponse({"detail": "Programm enthält Fehler", "errors": errors}, status_code=422)

    # ------------------------------------------------------------ meta
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/info")
    async def info(_: str = Depends(user)):
        examples = sorted(p.stem for p in EXAMPLES_DIR.glob("*.st")) if EXAMPLES_DIR.exists() else []
        return {
            "version": __version__,
            "function_blocks": sorted(FUNCTION_BLOCKS),
            "examples": examples,
            "auth": bool(api_token),
        }

    @app.get("/api/examples/{name}", response_class=PlainTextResponse)
    async def example(name: str, _: str = Depends(user)):
        path = (EXAMPLES_DIR / f"{name}.st").resolve()
        if path.parent != EXAMPLES_DIR.resolve() or not path.exists():
            raise HTTPException(404, "Beispiel nicht gefunden")
        return path.read_text(encoding="utf-8")

    @app.post("/api/check")
    async def check(body: SourceCheck, _: str = Depends(user)):
        errors = check_source(body.source)
        return {"ok": not errors, "errors": errors}

    @app.get("/api/audit")
    async def audit(limit: int = 200, plc_id: str | None = None,
                    m: PLCManager = Depends(manager), _: str = Depends(user)):
        if plc_id:
            plc_id = m.get(plc_id).id
        return m.store.read_audit(plc_id, max(1, min(limit, 2000)))

    # ------------------------------------------------------------ PLCs
    @app.get("/api/plcs")
    async def list_plcs(m: PLCManager = Depends(manager), _: str = Depends(user)):
        return [plc.status() for plc in m.plcs.values()]

    @app.post("/api/plcs", status_code=201)
    async def create_plc(body: PLCCreate, m: PLCManager = Depends(manager), u: str = Depends(user)):
        try:
            plc = await m.create(u, **body.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return plc.status()

    @app.get("/api/plcs/{plc_id}")
    async def get_plc(plc_id: str, m: PLCManager = Depends(manager), _: str = Depends(user)):
        plc = m.get(plc_id)
        return {**plc.status(), "diagnostics": [d.to_dict() for d in plc.diagnostics]}

    @app.delete("/api/plcs/{plc_id}", status_code=204)
    async def delete_plc(plc_id: str, m: PLCManager = Depends(manager), u: str = Depends(user)):
        await m.delete(u, plc_id)

    @app.post("/api/plcs/{plc_id}/run")
    async def run(plc_id: str, m: PLCManager = Depends(manager), u: str = Depends(user)):
        try:
            m.run(u, plc_id)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
        return m.get(plc_id).status()

    @app.post("/api/plcs/{plc_id}/stop")
    async def stop(plc_id: str, m: PLCManager = Depends(manager), u: str = Depends(user)):
        m.stop(u, plc_id)
        return m.get(plc_id).status()

    @app.post("/api/plcs/{plc_id}/reset")
    async def reset(plc_id: str, m: PLCManager = Depends(manager), u: str = Depends(user)):
        m.reset(u, plc_id)
        return m.get(plc_id).status()

    @app.get("/api/plcs/{plc_id}/variables")
    async def variables(plc_id: str, m: PLCManager = Depends(manager), _: str = Depends(user)):
        return m.get(plc_id).variables()

    @app.put("/api/plcs/{plc_id}/variables/{name}")
    async def write_variable(plc_id: str, name: str, body: VariableWrite,
                             m: PLCManager = Depends(manager), u: str = Depends(user)):
        try:
            value = m.write_variable(u, plc_id, name, body.value)
        except KeyError:
            raise HTTPException(404, f"Variable '{name}' nicht gefunden") from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Ungültiger Wert: {e}") from None
        return {"name": name, "value": value}

    @app.put("/api/plcs/{plc_id}/variables")
    async def write_variables(plc_id: str, body: VariablesWrite,
                              m: PLCManager = Depends(manager), u: str = Depends(user)):
        try:
            values = m.write_variables(u, plc_id, body.values)
        except KeyError as e:
            raise HTTPException(404, f"Variable '{e.args[0]}' nicht gefunden") from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Ungültiger Wert: {e}") from None
        return {"values": values}

    @app.websocket("/api/plcs/{plc_id}/stream")
    async def stream(websocket: WebSocket, plc_id: str, interval_ms: int = 100,
                     variables: str | None = None, token: str | None = None):
        """Push variable changes to clients such as Node-RED.

        Messages: ``snapshot`` (on connect and after each program download),
        ``changes`` (only changed values) and ``status`` (mode changes).
        Authentication: ``Authorization: Bearer`` header or ``?token=``.
        """
        if api_token:
            header = websocket.headers.get("authorization", "")
            ok = hmac.compare_digest(header, f"Bearer {api_token}") or (
                token is not None and hmac.compare_digest(token, api_token))
            if not ok:
                await websocket.close(code=4401, reason="Ungültiges oder fehlendes API-Token")
                return
        m: PLCManager = websocket.app.state.manager
        try:
            plc = m.get(plc_id)
        except NotFound:
            await websocket.close(code=4404, reason=f"vPLC '{plc_id}' nicht gefunden")
            return
        await websocket.accept()
        interval = max(20, min(interval_ms, 60_000)) / 1000.0
        wanted = {v.strip().upper() for v in variables.split(",") if v.strip()} if variables else None

        def current() -> dict:
            vals = plc.values()
            if wanted is not None:
                vals = {k: v for k, v in vals.items() if k.upper() in wanted}
            return vals

        def status_of() -> dict:
            s = plc.status()
            return {k: s[k] for k in ("id", "name", "mode", "program", "program_version", "last_error")}

        def now() -> str:
            return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        async def send_snapshot() -> tuple[dict, dict]:
            vals, status = current(), status_of()
            known = {k.upper() for k in plc.values()}
            await websocket.send_json({
                "type": "snapshot", "ts": now(), "status": status,
                "values": {k: _json_value(v) for k, v in vals.items()},
                "unknown": sorted(w for w in wanted - known) if wanted else [],
            })
            return vals, status

        async def reader():
            # Drain incoming frames so that close/ping are handled; clients only listen.
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    return

        reader_task = asyncio.create_task(reader())
        try:
            last_vals, last_status = await send_snapshot()
            while not reader_task.done():
                await asyncio.sleep(interval)
                if plc.id not in m.plcs:
                    await websocket.close(code=4404, reason="vPLC wurde gelöscht")
                    break
                status = status_of()
                if status["program_version"] != last_status["program_version"] or \
                        status["program"] != last_status["program"]:
                    last_vals, last_status = await send_snapshot()
                    continue
                if status != last_status:
                    await websocket.send_json({"type": "status", "ts": now(), "status": status})
                    last_status = status
                vals = current()
                changes = {k: _json_value(v) for k, v in vals.items() if _changed(last_vals.get(k), v)}
                if changes:
                    await websocket.send_json({"type": "changes", "ts": now(), "values": changes})
                    last_vals = vals
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader_task.cancel()

    @app.get("/api/plcs/{plc_id}/s7-layout")
    async def s7_layout(plc_id: str, m: PLCManager = Depends(manager), _: str = Depends(user)):
        plc = m.get(plc_id)
        return plc.s7.layout() if plc.s7 else []

    # ------------------------------------------------------------ programs & versions
    @app.get("/api/plcs/{plc_id}/program")
    async def get_program(plc_id: str, m: PLCManager = Depends(manager), _: str = Depends(user)):
        plc = m.get(plc_id)
        return {"source": plc.source, "version": plc.program_version}

    @app.put("/api/plcs/{plc_id}/program")
    async def upload_program(plc_id: str, body: ProgramUpload,
                             m: PLCManager = Depends(manager), u: str = Depends(user)):
        return await m.upload_program(u, plc_id, body.source, body.comment, body.warm)

    @app.get("/api/plcs/{plc_id}/versions")
    async def versions(plc_id: str, m: PLCManager = Depends(manager), _: str = Depends(user)):
        plc_id = m.get(plc_id).id
        return [v.meta() for v in reversed(m.store.list_versions(plc_id))]

    @app.get("/api/plcs/{plc_id}/versions/{version}")
    async def version(plc_id: str, version: int, m: PLCManager = Depends(manager),
                      _: str = Depends(user)):
        plc_id = m.get(plc_id).id
        pv = m.store.get_version(plc_id, version)
        if pv is None:
            raise HTTPException(404, "Version nicht gefunden")
        return {**pv.meta(), "source": pv.source}

    @app.post("/api/plcs/{plc_id}/versions/{version}/activate")
    async def activate(plc_id: str, version: int, m: PLCManager = Depends(manager),
                       u: str = Depends(user)):
        return await m.activate_version(u, plc_id, version)

    @app.get("/api/plcs/{plc_id}/diff", response_class=PlainTextResponse)
    async def diff(plc_id: str, a: int, b: int, m: PLCManager = Depends(manager),
                   _: str = Depends(user)):
        return m.diff(plc_id, a, b)

    # ------------------------------------------------------------ web UI
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(WEB_DIR / "index.html")

    return app
