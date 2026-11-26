"""OPC UA server endpoint exposing the PLC variables and status."""

from __future__ import annotations

import logging
import math

from ..st.compiler import CompiledProgram
from .s7 import exposed_variables

log = logging.getLogger(__name__)

NAMESPACE = "urn:it-ot:vplc"


def _equal(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


class OpcUaEndpoint:
    def __init__(self, port: int, plc_name: str, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.plc_name = plc_name
        self._server = None
        self._ns = 2
        self._folder = None
        self._status = {}
        self._nodes: dict[str, tuple[object, object]] = {}  # key -> (node, variant type)
        self._published: dict[str, object] = {}
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def endpoint_url(self) -> str:
        host = "localhost" if self.host in ("0.0.0.0", "") else self.host
        return f"opc.tcp://{host}:{self.port}/vplc/"

    async def start(self) -> None:
        from asyncua import Server, ua

        # asyncua logs a lot at INFO level; keep the console readable.
        logging.getLogger("asyncua").setLevel(logging.WARNING)
        server = Server()
        await server.init()
        server.set_endpoint(f"opc.tcp://{self.host or '0.0.0.0'}:{self.port}/vplc/")
        server.set_server_name(f"IT-OT vPLC {self.plc_name}")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self._ns = await server.register_namespace(NAMESPACE)
        objects = server.nodes.objects
        root = await objects.add_folder(self._nid("PLC"), self.plc_name)
        status = await root.add_folder(self._nid("_Status"), "_Status")
        self._status = {
            "Mode": await status.add_variable(self._nid("_Status.Mode"), "Mode", "STOP"),
            "ScanCount": await status.add_variable(
                self._nid("_Status.ScanCount"), "ScanCount", 0, ua.VariantType.UInt64),
            "CycleTimeUs": await status.add_variable(
                self._nid("_Status.CycleTimeUs"), "CycleTimeUs", 0.0, ua.VariantType.Double),
            "Program": await status.add_variable(self._nid("_Status.Program"), "Program", ""),
        }
        self._folder = await root.add_folder(self._nid("Variables"), "Variables")
        try:
            await server.start()
        except Exception as exc:
            self.error = f"OPC-UA-Server konnte nicht auf Port {self.port} starten: {exc}"
            raise RuntimeError(self.error) from exc
        self._server = server
        self.error = None
        log.info("OPC UA endpoint listening on %s", self.endpoint_url)

    def _nid(self, ident: str):
        from asyncua import ua
        return ua.NodeId(ident, self._ns)

    async def stop(self) -> None:
        if self._server is None:
            return
        try:
            await self._server.stop()
        finally:
            self._server = None
            self._nodes.clear()

    async def configure(self, program: CompiledProgram | None, program_label: str = "") -> None:
        """Rebuild variable nodes after a program download."""
        from asyncua import ua

        if self._server is None:
            return
        for node, _ in self._nodes.values():
            await self._server.delete_nodes([node])
        self._nodes.clear()
        self._published.clear()
        for var in exposed_variables(program):
            vtype = getattr(ua.VariantType, var.type.opcua)
            node = await self._folder.add_variable(
                self._nid(var.name), var.name, ua.Variant(var.snapshot(), vtype)
            )
            if var.writable:
                await node.set_writable()
            key = var.name.upper()
            self._nodes[key] = (node, vtype)
            self._published[key] = var.snapshot()
        await self._status["Program"].write_value(program_label)

    async def collect_writes(self) -> dict[str, object]:
        writes: dict[str, object] = {}
        for key, (node, _) in self._nodes.items():
            value = await node.read_value()
            if not _equal(value, self._published.get(key)):
                writes[key] = value
        return writes

    async def publish(self, program: CompiledProgram | None, status: dict) -> None:
        from asyncua import ua

        if self._server is None:
            return
        if program is not None:
            for key, (node, vtype) in self._nodes.items():
                var = program.variables.get(key)
                if var is None:
                    continue
                if not _equal(self._published.get(key), var.value):
                    await node.write_value(ua.Variant(var.snapshot(), vtype))
                    self._published[key] = var.snapshot()
        await self._status["Mode"].write_value(status["mode"])
        await self._status["ScanCount"].write_value(
            ua.Variant(status["scan_count"], ua.VariantType.UInt64))
        await self._status["CycleTimeUs"].write_value(
            ua.Variant(float(status["last_scan_us"]), ua.VariantType.Double))
