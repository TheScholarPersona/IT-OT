"""IEC 61131-3 elementary data types: value coercion and S7 byte encoding."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

STRING_DEFAULT_LENGTH = 254
STRING_MAX_LENGTH = 254  # S7: one byte each for maximum and actual length


@dataclass(frozen=True)
class IecType:
    name: str
    kind: str  # "bool" | "int" | "real" | "time" | "string"
    size: int  # bytes in an S7 (non-optimized) data block; BOOL = 0 (bit)
    signed: bool = True
    bits: int = 0
    opcua: str = ""  # asyncua VariantType name

    @property
    def default(self):
        if self.kind == "string":
            return ""
        if self.kind == "bool":
            return False
        if self.kind == "real":
            return 0.0
        return 0


def _int(name: str, bits: int, signed: bool, opcua: str) -> IecType:
    return IecType(name, "int", bits // 8, signed, bits, opcua)


TYPES: dict[str, IecType] = {
    "BOOL": IecType("BOOL", "bool", 0, False, 1, "Boolean"),
    "SINT": _int("SINT", 8, True, "SByte"),
    "INT": _int("INT", 16, True, "Int16"),
    "DINT": _int("DINT", 32, True, "Int32"),
    "LINT": _int("LINT", 64, True, "Int64"),
    "USINT": _int("USINT", 8, False, "Byte"),
    "UINT": _int("UINT", 16, False, "UInt16"),
    "UDINT": _int("UDINT", 32, False, "UInt32"),
    "ULINT": _int("ULINT", 64, False, "UInt64"),
    "BYTE": _int("BYTE", 8, False, "Byte"),
    "WORD": _int("WORD", 16, False, "UInt16"),
    "DWORD": _int("DWORD", 32, False, "UInt32"),
    "LWORD": _int("LWORD", 64, False, "UInt64"),
    "REAL": IecType("REAL", "real", 4, True, 32, "Float"),
    "LREAL": IecType("LREAL", "real", 8, True, 64, "Double"),
    # TIME is stored as signed milliseconds (S7: 32-bit, like S7 TIME).
    "TIME": IecType("TIME", "time", 4, True, 32, "Int32"),
}


def string_type(length: int = STRING_DEFAULT_LENGTH) -> IecType:
    """STRING[length]: S7 layout = max length byte, actual length byte, characters."""
    name = "STRING" if length == STRING_DEFAULT_LENGTH else f"STRING[{length}]"
    return IecType(name, "string", length + 2, False, length, "String")


TYPES["STRING"] = string_type()
_STRING_RE = re.compile(r"^STRING\[(\d+)\]$")


def get_type(name: str) -> IecType | None:
    m = _STRING_RE.match(name.upper())
    if m:
        length = int(m.group(1))
        return string_type(length) if 1 <= length <= STRING_MAX_LENGTH else None
    return TYPES.get(name.upper())


def coerce(t: IecType, value):
    """Convert a Python value to the canonical representation of type *t*.

    Integers wrap around like on a PLC, REAL is rounded to float32, STRING is
    truncated to its maximum length (characters outside Latin-1 become '?').
    """
    if t.kind == "string":
        if isinstance(value, bool):
            s = "TRUE" if value else "FALSE"
        elif isinstance(value, float):
            s = repr(value) if value != int(value) or abs(value) >= 1e16 else f"{value:.1f}"
        else:
            s = str(value)
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s[: t.bits]
    if t.kind == "bool":
        if isinstance(value, str):
            return value.strip().upper() in ("TRUE", "1", "ON")
        return bool(value)
    if t.kind == "real":
        v = float(value)
        if t.bits == 32:
            try:
                v = struct.unpack("<f", struct.pack("<f", v))[0]
            except OverflowError:
                v = float("inf") if v > 0 else float("-inf")
        return v
    # int / time
    if isinstance(value, bool):
        v = int(value)
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Ungültiger Wert für Ganzzahl")
        v = int(value)  # truncate toward zero
    else:
        v = int(value)
    mask = (1 << t.bits) - 1
    v &= mask
    if t.signed and v >= 1 << (t.bits - 1):
        v -= 1 << t.bits
    return v


_STRUCT = {
    ("int", 8, True): ">b", ("int", 8, False): ">B",
    ("int", 16, True): ">h", ("int", 16, False): ">H",
    ("int", 32, True): ">i", ("int", 32, False): ">I",
    ("int", 64, True): ">q", ("int", 64, False): ">Q",
    ("time", 32, True): ">i",
    ("real", 32, True): ">f", ("real", 64, True): ">d",
}


def encode(t: IecType, value, buf: bytearray, byte: int, bit: int = 0) -> None:
    """Write *value* into *buf* using S7 (big-endian) encoding."""
    if t.kind == "string":
        data = value.encode("latin-1", "replace")[: t.bits]
        buf[byte] = t.bits
        buf[byte + 1] = len(data)
        buf[byte + 2: byte + 2 + t.bits] = data.ljust(t.bits, b"\0")
        return
    if t.kind == "bool":
        if value:
            buf[byte] |= 1 << bit
        else:
            buf[byte] &= ~(1 << bit) & 0xFF
        return
    struct.pack_into(_STRUCT[(t.kind, t.bits, t.signed)], buf, byte, value)


def decode(t: IecType, buf: bytes | bytearray, byte: int, bit: int = 0):
    if t.kind == "string":
        length = min(buf[byte + 1], t.bits)
        return bytes(buf[byte + 2: byte + 2 + length]).decode("latin-1")
    if t.kind == "bool":
        return bool(buf[byte] >> bit & 1)
    return struct.unpack_from(_STRUCT[(t.kind, t.bits, t.signed)], buf, byte)[0]


def format_time(ms: int) -> str:
    """Format milliseconds as an IEC time literal, e.g. T#1m30s."""
    if ms == 0:
        return "T#0ms"
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    parts = []
    for unit, size in (("d", 86_400_000), ("h", 3_600_000), ("m", 60_000), ("s", 1000)):
        if ms >= size:
            parts.append(f"{ms // size}{unit}")
            ms %= size
    if ms:
        parts.append(f"{ms}ms")
    return f"T#{sign}{''.join(parts)}"
