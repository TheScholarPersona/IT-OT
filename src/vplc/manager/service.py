"""Manages the fleet of virtual PLCs: creation, programs, versions, audit."""

from __future__ import annotations

import difflib
import logging
import re
import socket
import uuid
from dataclasses import asdict

from ..runtime import RUN, PLCConfig, VirtualPLC
from ..st import STError, compile_source
from .store import Store

log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class PLCManager:
    def __init__(self, store: Store, s7_base_port: int = 10102, opcua_base_port: int = 4840,
                 host: str = "0.0.0.0"):
        self.store = store
        self.s7_base_port = s7_base_port
        self.opcua_base_port = opcua_base_port
        self.host = host
        self.plcs: dict[str, VirtualPLC] = {}

    # ------------------------------------------------------------ persistence
    def _persist(self) -> None:
        self.store.save_plcs([
            {
                "id": plc.id,
                "config": asdict(plc.config),
                "program_version": plc.program_version,
                "mode": plc.mode,
            }
            for plc in self.plcs.values()
        ])

    async def restore(self) -> None:
        """Recreate PLCs after a restart and bring them back into their last mode."""
        for entry in self.store.load_plcs():
            config = PLCConfig(**entry["config"])
            plc = VirtualPLC(entry["id"], config)
            self.plcs[plc.id] = plc
            await plc.start_services()
            version = entry.get("program_version")
            if version:
                pv = self.store.get_version(plc.id, version)
                if pv:
                    try:
                        await plc.load_program(pv.source, pv.version, warm=False)
                        if entry.get("mode") == RUN:
                            plc.run()
                    except STError as e:  # pragma: no cover - stored programs compiled before
                        plc.diag("error", f"Gespeichertes Programm ungültig: {e}")
        if self.plcs:
            log.info("Restored %d virtual PLC(s)", len(self.plcs))

    async def shutdown(self) -> None:
        for plc in self.plcs.values():
            await plc.shutdown()

    # ------------------------------------------------------------ lookup
    def get(self, plc_id: str) -> VirtualPLC:
        plc = self.plcs.get(plc_id)
        if plc is None:
            raise NotFound(f"vPLC '{plc_id}' nicht gefunden")
        return plc

    def _allocate(self, base: int, used: set[int]) -> int:
        port = base
        while port in used or not _port_free(port, self.host):
            port += 1
            if port > base + 1000:
                raise Conflict("Kein freier Port gefunden")
        return port

    # ------------------------------------------------------------ CRUD
    async def create(self, user: str, name: str, cycle_ms: float = 10.0,
                     watchdog_ms: float = 200.0, s7_enabled: bool = True,
                     opcua_enabled: bool = True, s7_port: int | None = None,
                     opcua_port: int | None = None, source: str | None = None) -> VirtualPLC:
        name = name.strip()
        if not _NAME_RE.match(name):
            raise ValueError("Name: 1–64 Zeichen, Buchstaben, Ziffern, Leerzeichen, _ . -")
        if any(p.config.name.lower() == name.lower() for p in self.plcs.values()):
            raise Conflict(f"Eine vPLC mit dem Namen '{name}' existiert bereits")
        if not 1 <= cycle_ms <= 10_000:
            raise ValueError("Zykluszeit muss zwischen 1 und 10000 ms liegen")
        if not cycle_ms <= watchdog_ms <= 60_000:
            raise ValueError("Zykluszeitüberwachung muss ≥ Zykluszeit und ≤ 60000 ms sein")
        used_s7 = {p.config.s7_port for p in self.plcs.values()}
        used_ua = {p.config.opcua_port for p in self.plcs.values()}
        for port, used in ((s7_port, used_s7), (opcua_port, used_ua)):
            if port is not None and (port in used or not 1 <= port <= 65535):
                raise Conflict(f"Port {port} ist bereits vergeben oder ungültig")
        config = PLCConfig(
            name=name,
            cycle_ms=cycle_ms,
            watchdog_ms=watchdog_ms,
            s7_enabled=s7_enabled,
            s7_port=s7_port or self._allocate(self.s7_base_port, used_s7),
            opcua_enabled=opcua_enabled,
            opcua_port=opcua_port or self._allocate(self.opcua_base_port, used_ua),
            host=self.host,
        )
        if source is not None:
            compile_source(source)  # validate before anything is created
        plc = VirtualPLC(uuid.uuid4().hex[:12], config)
        self.plcs[plc.id] = plc
        await plc.start_services()
        self.store.audit(user, "plc.create", plc.id, name=name,
                         s7_port=config.s7_port, opcua_port=config.opcua_port)
        if source is not None:
            await self.upload_program(user, plc.id, source, "Initiale Version")
        self._persist()
        return plc

    async def delete(self, user: str, plc_id: str) -> None:
        plc = self.get(plc_id)
        await plc.shutdown()
        del self.plcs[plc_id]
        self.store.delete_programs(plc_id)
        self.store.audit(user, "plc.delete", plc_id, name=plc.config.name)
        self._persist()

    # ------------------------------------------------------------ programs
    async def upload_program(self, user: str, plc_id: str, source: str, comment: str = "",
                             warm: bool = True) -> dict:
        plc = self.get(plc_id)
        program = compile_source(source)  # raises STError → caller reports 422
        versions = self.store.list_versions(plc_id)
        if versions and versions[-1].source == source:
            pv = versions[-1]  # unchanged: do not create a duplicate version
        else:
            pv = self.store.add_version(plc_id, source, user, comment, program.name)
        result = await plc.load_program(source, pv.version, warm=warm)
        self.store.audit(user, "program.download", plc_id, version=pv.version,
                         sha256=pv.sha256, comment=comment, warm=warm)
        self._persist()
        return {**result, "version": pv.meta()}

    async def activate_version(self, user: str, plc_id: str, version: int) -> dict:
        plc = self.get(plc_id)
        pv = self.store.get_version(plc_id, version)
        if pv is None:
            raise NotFound(f"Version {version} nicht gefunden")
        result = await plc.load_program(pv.source, pv.version)
        self.store.audit(user, "program.activate", plc_id, version=version, sha256=pv.sha256)
        self._persist()
        return {**result, "version": pv.meta()}

    def diff(self, plc_id: str, a: int, b: int) -> str:
        self.get(plc_id)
        va, vb = self.store.get_version(plc_id, a), self.store.get_version(plc_id, b)
        if va is None or vb is None:
            raise NotFound("Version nicht gefunden")
        return "".join(difflib.unified_diff(
            va.source.splitlines(keepends=True), vb.source.splitlines(keepends=True),
            fromfile=f"v{a} ({va.author}, {va.created})",
            tofile=f"v{b} ({vb.author}, {vb.created})",
        ))

    # ------------------------------------------------------------ operation
    def run(self, user: str, plc_id: str) -> None:
        plc = self.get(plc_id)
        plc.run()
        self.store.audit(user, "plc.run", plc_id)
        self._persist()

    def stop(self, user: str, plc_id: str) -> None:
        plc = self.get(plc_id)
        plc.stop()
        self.store.audit(user, "plc.stop", plc_id)
        self._persist()

    def reset(self, user: str, plc_id: str) -> None:
        plc = self.get(plc_id)
        plc.reset()
        self.store.audit(user, "plc.reset", plc_id)

    def write_variable(self, user: str, plc_id: str, name: str, value) -> object:
        plc = self.get(plc_id)
        result = plc.write_variable(name, value)
        self.store.audit(user, "variable.write", plc_id, variable=name, value=result)
        return result
