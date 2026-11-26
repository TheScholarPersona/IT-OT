"""S7comm server endpoint: exposes PLC variables as a classic (non-optimized) data block.

HMIs, SCADA systems and tools such as snap7, node-s7 or PLC4X can read and write
the variables with absolute addresses (e.g. ``DB1.DBX0.0``, ``DB1.DBW2``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..st.compiler import CompiledProgram, Variable
from ..types import IecType, decode, encode

log = logging.getLogger(__name__)

S7_CPU_RUN = 0x08
S7_CPU_STOP = 0x04


@dataclass
class S7Entry:
    name: str  # "Soll" or "Werte[3]" for array elements
    key: str  # upper-case variable name
    type: IecType
    byte: int
    bit: int
    writable: bool
    index: int | None = None  # array element index (declared index, e.g. 1 for ARRAY[1..5])

    @property
    def write_key(self) -> str:
        return self.key if self.index is None else f"{self.key}[{self.index}]"

    def address(self, db: int) -> str:
        t = self.type
        if t.kind == "bool":
            return f"DB{db}.DBX{self.byte}.{self.bit}"
        prefix = {1: "DBB", 2: "DBW", 4: "DBD"}.get(t.size)
        if prefix:
            return f"DB{db}.{prefix}{self.byte}"
        return f"DB{db}.DBB{self.byte} ({t.size} Byte)"


def build_layout(variables: list[Variable]) -> tuple[list[S7Entry], int]:
    """Assign S7 offsets like a non-optimized TIA Portal DB.

    BOOLs are packed bit by bit; every other type starts on a new byte and types
    larger than one byte are aligned to an even address. Arrays start and end on an
    even address; ARRAY OF BOOL is packed bit by bit inside.
    """
    entries: list[S7Entry] = []
    byte, bit = 0, 0
    for var in variables:
        t = var.type
        if getattr(var, "dims", None):
            if bit:
                byte, bit = byte + 1, 0
            byte += byte % 2
            low, high = var.dims
            for n, index in enumerate(range(low, high + 1)):
                name = f"{var.name}[{index}]"
                if t.kind == "bool":
                    entries.append(S7Entry(name, var.name.upper(), t, byte + n // 8, n % 8, var.writable, index))
                else:
                    entries.append(S7Entry(name, var.name.upper(), t, byte + n * t.size, 0, var.writable, index))
            length = high - low + 1
            byte += (length + 7) // 8 if t.kind == "bool" else length * t.size
            byte += byte % 2
            continue
        if t.kind == "bool":
            if bit == 8:
                byte, bit = byte + 1, 0
            entries.append(S7Entry(var.name, var.name.upper(), t, byte, bit, var.writable))
            bit += 1
            continue
        if bit:
            byte, bit = byte + 1, 0
        if t.size > 1 and byte % 2:
            byte += 1
        entries.append(S7Entry(var.name, var.name.upper(), t, byte, 0, var.writable))
        byte += t.size
    size = byte + (1 if bit else 0)
    size += size % 2
    return entries, max(size, 2)


def exposed_variables(program: CompiledProgram | None) -> list[Variable]:
    if program is None:
        return []
    return [v for v in program.variables.values() if v.section != "VAR_TEMP"]


class S7Endpoint:
    """Wraps a snap7 server instance that serves one data block."""

    def __init__(self, port: int, db_number: int = 1, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.db_number = db_number
        self.entries: list[S7Entry] = []
        self.size = 2
        self.db = bytearray(self.size)
        self.shadow = bytes(self.db)
        self._server = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        import snap7
        from snap7.type import SrvArea

        server = snap7.Server(log=False)
        server.register_area(SrvArea.DB, self.db_number, self.db)
        try:
            if self.host in ("0.0.0.0", ""):
                server.start(tcp_port=self.port)
            else:
                server.start_to(self.host, tcp_port=self.port)
        except Exception as exc:  # port in use, permissions ...
            self.error = f"S7-Server konnte nicht auf Port {self.port} starten: {exc}"
            try:
                server.destroy()
            except Exception:  # pragma: no cover
                pass
            raise RuntimeError(self.error) from exc
        self._server = server
        self.error = None
        log.info("S7 endpoint listening on port %s (DB%s)", self.port, self.db_number)

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.stop()
            self._server.destroy()
        finally:
            self._server = None

    def set_cpu_running(self, running: bool) -> None:
        if self._server is not None:
            try:
                self._server.set_cpu_status(S7_CPU_RUN if running else S7_CPU_STOP)
            except Exception:  # pragma: no cover - not supported by every snap7 build
                pass

    def configure(self, program: CompiledProgram | None) -> None:
        """(Re)build the DB layout for a newly loaded program."""
        from snap7.type import SrvArea

        self.entries, self.size = build_layout(exposed_variables(program))
        new_db = bytearray(self.size)
        if self._server is not None:
            self._server.unregister_area(SrvArea.DB, self.db_number)
            self._server.register_area(SrvArea.DB, self.db_number, new_db)
        self.db = new_db
        if program is not None:
            self.publish(program)
        else:
            self.shadow = bytes(self.db)

    def _lock(self):
        if self._server is not None:
            from snap7.type import SrvArea
            try:
                self._server.lock_area(SrvArea.DB, self.db_number)
                return True
            except Exception:
                return False
        return False

    def _unlock(self, locked: bool):
        if locked:
            from snap7.type import SrvArea
            self._server.unlock_area(SrvArea.DB, self.db_number)

    def collect_writes(self) -> dict[str, object]:
        """Return variables that S7 clients changed since the last publish."""
        locked = self._lock()
        try:
            current = bytes(self.db)
        finally:
            self._unlock(locked)
        if current == self.shadow:
            return {}
        writes: dict[str, object] = {}
        for e in self.entries:
            if not e.writable:
                continue
            new = decode(e.type, current, e.byte, e.bit)
            old = decode(e.type, self.shadow, e.byte, e.bit)
            if new != old and not (new != new and old != old):  # ignore NaN == NaN
                writes[e.write_key] = new
        return writes

    def publish(self, program: CompiledProgram) -> None:
        """Copy current variable values into the data block."""
        variables = program.variables
        locked = self._lock()
        try:
            for e in self.entries:
                var = variables.get(e.key)
                if var is None:
                    continue
                value = var.value if e.index is None else var.value[e.index - var.dims[0]]
                encode(e.type, value, self.db, e.byte, e.bit)
            self.shadow = bytes(self.db)
        finally:
            self._unlock(locked)

    def layout(self) -> list[dict]:
        return [
            {
                "name": e.name,
                "type": e.type.name,
                "address": e.address(self.db_number),
                "byte": e.byte,
                "bit": e.bit if e.type.kind == "bool" else None,
                "writable": e.writable,
            }
            for e in self.entries
        ]
