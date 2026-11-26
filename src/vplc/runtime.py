"""Virtual PLC runtime: cyclic program execution with S7 and OPC UA endpoints."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .io.opcua import OpcUaEndpoint
from .io.s7 import S7Endpoint
from .st import CompiledProgram, PLCRuntimeError, STError, compile_source
from .types import coerce, format_time

log = logging.getLogger(__name__)

RUN = "RUN"
STOP = "STOP"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class PLCConfig:
    name: str
    cycle_ms: float = 10.0
    watchdog_ms: float = 200.0
    s7_enabled: bool = True
    s7_port: int = 10102
    s7_db: int = 1
    opcua_enabled: bool = True
    opcua_port: int = 4840
    io_sync_ms: float = 50.0  # how often OPC UA is synchronised
    host: str = "0.0.0.0"


@dataclass
class ScanStats:
    scan_count: int = 0
    last_scan_us: float = 0.0
    max_scan_us: float = 0.0
    avg_scan_us: float = 0.0
    overruns: int = 0

    def record(self, us: float) -> None:
        self.scan_count += 1
        self.last_scan_us = us
        self.max_scan_us = max(self.max_scan_us, us)
        # exponential moving average – cheap and good enough for a status view
        self.avg_scan_us = us if self.scan_count == 1 else self.avg_scan_us * 0.95 + us * 0.05


@dataclass
class DiagEntry:
    ts: str
    level: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict:
        return {"ts": self.ts, "level": self.level, "message": self.message, "line": self.line}


class VirtualPLC:
    """One virtual PLC instance.

    The scan cycle follows the classic PLC model:
    read inputs (external writes) → execute program → write outputs.
    """

    def __init__(self, plc_id: str, config: PLCConfig, clock: Callable[[], float] = time.monotonic):
        self.id = plc_id
        self.config = config
        self.clock = clock
        self.mode = STOP
        self.program: CompiledProgram | None = None
        self.source: str = ""
        self.program_version: int | None = None
        self.stats = ScanStats()
        self.diagnostics: deque[DiagEntry] = deque(maxlen=200)
        self.last_error: dict | None = None
        self._pending: dict[str, object] = {}
        self._epoch = clock()
        self._task: asyncio.Task | None = None
        self._services = False
        self._lock = asyncio.Lock()
        self.s7 = S7Endpoint(config.s7_port, config.s7_db, config.host) if config.s7_enabled else None
        self.opcua = OpcUaEndpoint(config.opcua_port, config.name, config.host) if config.opcua_enabled else None

    # ------------------------------------------------------------ diagnostics
    def diag(self, level: str, message: str, line: int | None = None) -> None:
        self.diagnostics.appendleft(DiagEntry(_now_iso(), level, message, line))
        getattr(log, "error" if level == "error" else "info")("[%s] %s", self.config.name, message)

    def now_ms(self) -> int:
        return int((self.clock() - self._epoch) * 1000)

    # ------------------------------------------------------------ lifecycle
    async def start_services(self) -> None:
        """Start protocol endpoints and the background I/O loop (PLC stays in STOP)."""
        if self._services:
            return
        if self.s7:
            try:
                self.s7.start()
                self.s7.configure(self.program)
                self.s7.set_cpu_running(False)
            except RuntimeError as e:
                self.diag("error", str(e))
        if self.opcua:
            try:
                await self.opcua.start()
                await self.opcua.configure(self.program, self._program_label())
            except RuntimeError as e:
                self.diag("error", str(e))
        self._services = True
        self._task = asyncio.create_task(self._loop(), name=f"vplc-{self.id}")
        self.diag("info", "Dienste gestartet")

    async def shutdown(self) -> None:
        self.mode = STOP
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self.s7:
            self.s7.stop()
        if self.opcua:
            await self.opcua.stop()
        self._services = False

    def _program_label(self) -> str:
        if self.program is None:
            return ""
        version = f" v{self.program_version}" if self.program_version is not None else ""
        return f"{self.program.name}{version}"

    async def load_program(self, source: str, version: int | None = None, warm: bool = True) -> dict:
        """Compile and download a program. Raises STError if it does not compile."""
        program = compile_source(source, watchdog_ms=self.config.watchdog_ms)
        async with self._lock:
            was_running = self.mode == RUN
            kept: list[str] = []
            if warm and self.program is not None:
                kept = program.transfer_state_from(self.program)
            self.program = program
            self.source = source
            self.program_version = version
            self._pending.clear()
            if self.s7:
                self.s7.configure(program)
            if self.opcua and self.opcua.running:
                await self.opcua.configure(program, self._program_label())
        label = self._program_label()
        self.diag("info", f"Programm {label} geladen" + (" (Warmstart, Werte übernommen)" if kept else ""))
        return {"program": program.name, "version": version, "kept_values": kept, "running": was_running}

    def run(self) -> None:
        if self.program is None:
            raise RuntimeError("Kein Programm geladen")
        if self.mode == RUN:
            return
        self.mode = RUN
        self.last_error = None
        if self.s7:
            self.s7.set_cpu_running(True)
        self.diag("info", "Betriebszustand RUN")

    def stop(self, reason: str | None = None, level: str = "info") -> None:
        if self.mode == STOP and reason is None:
            return
        self.mode = STOP
        if self.s7:
            self.s7.set_cpu_running(False)
        self.diag(level, reason or "Betriebszustand STOP")

    def reset(self) -> None:
        """Cold restart: re-initialise every variable and function block."""
        if self.program is None:
            return
        fresh = compile_source(self.source, watchdog_ms=self.config.watchdog_ms)
        self.program = fresh
        if self.s7:
            self.s7.configure(fresh)
        self.diag("info", "Urlöschen / Kaltstart – alle Werte zurückgesetzt")

    # ------------------------------------------------------------ variables
    def write_variable(self, name: str, value) -> object:
        if self.program is None:
            raise KeyError(name)
        var = self.program.variables.get(name.upper())
        if var is None:
            raise KeyError(name)
        if not var.writable:
            raise PermissionError(f"'{var.name}' ist eine Konstante")
        coerced = coerce(var.type, value)
        if self.mode == RUN:
            self._pending[var.name.upper()] = coerced
        else:
            var.value = coerced
            if self.s7:
                self.s7.publish(self.program)
        return coerced

    def _apply_external(self, writes: dict[str, object]) -> None:
        if not writes or self.program is None:
            return
        for key, value in writes.items():
            var = self.program.variables.get(key)
            if var is None or not var.writable:
                continue
            try:
                var.value = coerce(var.type, value)
            except (ValueError, TypeError, OverflowError):
                self.diag("warning", f"Ungültiger Wert für {var.name} verworfen")

    def variables(self) -> list[dict]:
        if self.program is None:
            return []
        layout = {e["name"].upper(): e for e in self.s7.layout()} if self.s7 else {}
        out = []
        for key, var in self.program.variables.items():
            entry = layout.get(key)
            out.append({
                "name": var.name,
                "type": var.type.name,
                "section": var.section,
                "constant": var.constant,
                "retain": var.retain,
                "writable": var.writable,
                "value": var.value,
                "display": format_time(var.value) if var.type.kind == "time" else None,
                "s7_address": entry["address"] if entry else None,
                "opcua_node": f"ns=2;s={var.name}" if self.opcua and var.section != "VAR_TEMP" else None,
            })
        for fb in self.program.fbs.values():
            for member, value in fb.block.values.items():
                out.append({
                    "name": f"{fb.name}.{member}",
                    "type": (fb.block.INPUTS | fb.block.OUTPUTS)[member].name,
                    "section": fb.type_name,
                    "constant": False,
                    "retain": False,
                    "writable": False,
                    "value": value,
                    "display": format_time(value) if member in ("PT", "ET") else None,
                    "s7_address": None,
                    "opcua_node": None,
                })
        return out

    # ------------------------------------------------------------ scan cycle
    def scan_once(self) -> None:
        """Execute exactly one scan cycle (also used by tests)."""
        program = self.program
        if program is None:
            return
        if self.s7:
            self._apply_external(self.s7.collect_writes())
        if self._pending:
            pending, self._pending = self._pending, {}
            self._apply_external(pending)
        t0 = time.perf_counter()
        try:
            program.execute(self.now_ms())
        except PLCRuntimeError as e:
            self.last_error = e.to_dict()
            self.stop(f"Laufzeitfehler: {e.message}", level="error")
            self.diagnostics[0].line = e.line
        except STError as e:  # pragma: no cover - defensive
            self.last_error = e.to_dict()
            self.stop(f"Fehler: {e.message}", level="error")
        except Exception as e:  # pragma: no cover - interpreter bug, never crash the loop
            self.last_error = {"message": str(e), "line": None, "col": None}
            self.stop(f"Interner Fehler: {e!r}", level="error")
        finally:
            self.stats.record((time.perf_counter() - t0) * 1e6)
            if self.s7:
                self.s7.publish(program)

    async def _sync_opcua(self) -> None:
        if not (self.opcua and self.opcua.running):
            return
        try:
            writes = await self.opcua.collect_writes()
            if writes:
                if self.mode == RUN:
                    self._pending.update(writes)
                else:
                    self._apply_external(writes)
                    if self.s7 and self.program:
                        self.s7.publish(self.program)
            await self.opcua.publish(self.program, self.status())
        except Exception as e:  # pragma: no cover - keep the PLC alive
            self.diag("warning", f"OPC-UA-Synchronisation fehlgeschlagen: {e}")

    async def _loop(self) -> None:
        next_scan = self.clock()
        next_io = next_scan
        while True:
            cycle = self.config.cycle_ms / 1000.0
            now = self.clock()
            if self.mode == RUN:
                async with self._lock:
                    self.scan_once()
            elif self.s7 and self.program:
                # In STOP the DB stays accessible; accept writes from S7 clients.
                writes = self.s7.collect_writes()
                if writes:
                    self._apply_external(writes)
                    self.s7.publish(self.program)
            if now >= next_io:
                await self._sync_opcua()
                next_io = now + self.config.io_sync_ms / 1000.0
            if self.mode == RUN:
                next_scan += cycle
                delay = next_scan - self.clock()
                if delay < 0:
                    self.stats.overruns += 1
                    next_scan = self.clock()
                    delay = 0
            else:
                next_scan = self.clock() + 0.05
                delay = 0.05
            await asyncio.sleep(delay)

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        s = self.stats
        return {
            "id": self.id,
            "name": self.config.name,
            "mode": self.mode,
            "program": self.program.name if self.program else None,
            "program_version": self.program_version,
            "cycle_ms": self.config.cycle_ms,
            "watchdog_ms": self.config.watchdog_ms,
            "scan_count": s.scan_count,
            "last_scan_us": round(s.last_scan_us, 1),
            "avg_scan_us": round(s.avg_scan_us, 1),
            "max_scan_us": round(s.max_scan_us, 1),
            "overruns": s.overruns,
            "last_error": self.last_error,
            "s7": {
                "enabled": bool(self.s7),
                "running": bool(self.s7 and self.s7.running),
                "port": self.config.s7_port,
                "db": self.config.s7_db,
                "db_size": self.s7.size if self.s7 else 0,
                "rack": 0,
                "slot": 1,
                "error": self.s7.error if self.s7 else None,
            },
            "opcua": {
                "enabled": bool(self.opcua),
                "running": bool(self.opcua and self.opcua.running),
                "port": self.config.opcua_port,
                "endpoint": self.opcua.endpoint_url if self.opcua else None,
                "error": self.opcua.error if self.opcua else None,
            },
        }
