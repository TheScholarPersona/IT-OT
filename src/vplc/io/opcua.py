"""OPC UA server endpoint exposing the PLC variables and status."""

from __future__ import annotations

import logging
import math

from ..datatypes import ArrayType, Elementary, get_at, is_leaf
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
        self._nodes: dict[str, tuple] = {}  # PATH -> (node, variant type, var key, steps, dtype, path)
        self._roots: list = []
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
            self._roots.clear()

    async def configure(self, program: CompiledProgram | None, program_label: str = "") -> None:
        """Rebuild variable nodes after a program download.

        Elementary values and arrays of elementary values become variable nodes; structs and
        arrays of structs become folders whose children are named by path (e.g. Lager[2].Menge).
        """
        if self._server is None:
            return
        if self._roots:
            await self._server.delete_nodes(self._roots, recursive=True)
        self._roots.clear()
        self._nodes.clear()
        self._published.clear()
        for var in exposed_variables(program):
            node = await self._add(self._folder, var, var.dtype, var.name, var.name, [])
            self._roots.append(node)
        await self._status["Program"].write_value(program_label)

    async def _add(self, parent, var, dtype, path: str, browse: str, steps: list):
        from asyncua import ua

        if is_leaf(dtype):
            iec = dtype.iec if isinstance(dtype, Elementary) else dtype.elem.iec
            vtype = getattr(ua.VariantType, iec.opcua)
            value = dtype.copy(get_at(var.value, var.dtype, steps))
            node = await parent.add_variable(self._nid(path), browse, ua.Variant(value, vtype))
            if var.writable:
                await node.set_writable()
            key = path.upper()
            self._nodes[key] = (node, vtype, var.name.upper(), steps, dtype, path)
            self._published[key] = value
            return node
        folder = await parent.add_folder(self._nid(path), browse)
        if isinstance(dtype, ArrayType):
            for i in range(dtype.low, dtype.high + 1):
                await self._add(folder, var, dtype.elem, f"{path}[{i}]", f"{browse}[{i}]", steps + [("index", i)])
        else:
            for f in dtype.fields:
                await self._add(folder, var, f.dtype, f"{path}.{f.name}", f.name, steps + [("field", f.key)])
        return folder

    async def collect_writes(self) -> dict[str, object]:
        writes: dict[str, object] = {}
        for key, (node, _, _, _, _, path) in self._nodes.items():
            value = await node.read_value()
            if not _equal(value, self._published.get(key)):
                writes[path] = value
        return writes

    async def publish(self, program: CompiledProgram | None, status: dict) -> None:
        from asyncua import ua

        if self._server is None:
            return
        if program is not None:
            for key, (node, vtype, var_key, steps, dtype, _) in self._nodes.items():
                var = program.variables.get(var_key)
                if var is None:
                    continue
                current = get_at(var.value, var.dtype, steps)
                if not _equal(self._published.get(key), current):
                    value = dtype.copy(current)
                    await node.write_value(ua.Variant(value, vtype))
                    self._published[key] = value
        await self._status["Mode"].write_value(status["mode"])
        await self._status["ScanCount"].write_value(
            ua.Variant(status["scan_count"], ua.VariantType.UInt64))
        await self._status["CycleTimeUs"].write_value(
            ua.Variant(float(status["last_scan_us"]), ua.VariantType.Double))
