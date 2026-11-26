"""Composite data types (ARRAY, STRUCT) on top of the elementary IEC types, plus access paths.

A value of an array is a Python list, a value of a struct a dict with upper-case
field names (in declaration order). Paths such as ``Achse.Pos`` or ``Lager[3].Menge``
address parts of a variable; they are used by the S7/OPC UA endpoints and the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .types import IecType, coerce

# ====================================================================== types


@dataclass(frozen=True)
class Elementary:
    iec: IecType

    @property
    def label(self) -> str:
        return self.iec.name

    def default(self):
        return self.iec.default

    def copy(self, value):
        return value

    def coerce(self, value, current=None):
        return coerce(self.iec, value)

    def display(self, value):
        return value

    def layout_key(self):
        return self.iec.name


@dataclass(frozen=True)
class ArrayType:
    elem: "DataType"
    low: int
    high: int

    @property
    def length(self) -> int:
        return self.high - self.low + 1

    @property
    def label(self) -> str:
        return f"ARRAY[{self.low}..{self.high}] OF {self.elem.label}"

    def default(self):
        return [self.elem.default() for _ in range(self.length)]

    def copy(self, value):
        return [self.elem.copy(v) for v in value]

    def display(self, value):
        return [self.elem.display(v) for v in value]

    def coerce(self, value, current=None):
        if not isinstance(value, (list, tuple)) or len(value) != self.length:
            raise ValueError(f"{self.label} erwartet eine Liste mit {self.length} Werten")
        currents = current if isinstance(current, list) else [None] * self.length
        return [self.elem.coerce(v, c) for v, c in zip(value, currents)]

    def position(self, index: int, name: str = "") -> int:
        if not self.low <= index <= self.high:
            raise IndexError(f"Index {index} außerhalb von {name}[{self.low}..{self.high}]")
        return index - self.low

    def layout_key(self):
        return ("ARRAY", self.low, self.high, self.elem.layout_key())


@dataclass(frozen=True)
class StructField:
    key: str  # upper-case
    name: str  # as declared
    dtype: "DataType"
    init: object = field(compare=False, hash=False)


@dataclass(frozen=True, eq=False)
class StructType:
    name: str
    fields: tuple[StructField, ...]

    @property
    def label(self) -> str:
        return self.name

    def field(self, key: str) -> StructField | None:
        key = key.upper()
        return next((f for f in self.fields if f.key == key), None)

    def default(self):
        return {f.key: f.dtype.copy(f.init) for f in self.fields}

    def copy(self, value):
        return {f.key: f.dtype.copy(value[f.key]) for f in self.fields}

    def display(self, value):
        """Copy with declared field names (for JSON: API, stream, Node-RED)."""
        return {f.name: f.dtype.display(value[f.key]) for f in self.fields}

    def coerce(self, value, current=None):
        """Accepts a dict; with *current* missing fields keep their value (partial write)."""
        if not isinstance(value, dict):
            raise ValueError(f"{self.name} erwartet ein Objekt mit Feldern")
        given = {k.upper(): v for k, v in value.items()}
        unknown = [k for k in given if self.field(k) is None]
        if unknown:
            raise ValueError(f"{self.name} hat kein Feld '{unknown[0]}'")
        base = current if isinstance(current, dict) else self.default()
        return {f.key: f.dtype.coerce(given[f.key], base.get(f.key)) if f.key in given else f.dtype.copy(base[f.key])
                for f in self.fields}

    def layout_key(self):
        return ("STRUCT", self.name, tuple((f.key, f.dtype.layout_key()) for f in self.fields))


DataType = Elementary | ArrayType | StructType


def is_elementary(dtype: DataType) -> bool:
    return isinstance(dtype, Elementary)


def is_leaf(dtype: DataType) -> bool:
    """Leaf for OPC UA: elementary value or array of elementary values."""
    return isinstance(dtype, Elementary) or (isinstance(dtype, ArrayType) and isinstance(dtype.elem, Elementary))


def same_layout(a: DataType, b: DataType) -> bool:
    return a.layout_key() == b.layout_key()


# ====================================================================== paths
_STEP_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*(-?\d+)\s*\]")
_BASE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)")

Step = tuple[str, object]  # ("field", KEY) | ("index", int)


def parse_path(text: str) -> tuple[str, list[Step]]:
    """'Lager[3].Menge' -> ('Lager', [('index', 3), ('field', 'MENGE')]). Raises KeyError."""
    m = _BASE_RE.match(text)
    if not m:
        raise KeyError(text)
    base, pos, steps = m.group(1), m.end(), []
    rest = text.rstrip()
    while pos < len(rest):
        sm = _STEP_RE.match(rest, pos)
        if not sm:
            raise KeyError(text)
        steps.append(("field", sm.group(1).upper()) if sm.group(1) else ("index", int(sm.group(2))))
        pos = sm.end()
    return base, steps


def resolve(dtype: DataType, steps: list[Step], name: str = "") -> DataType:
    """Type at the end of *steps*; KeyError for unknown fields, IndexError for bad indices."""
    for kind, arg in steps:
        if kind == "field":
            if not isinstance(dtype, StructType) or dtype.field(arg) is None:
                raise KeyError(f"{name}: kein Feld '{arg}'")
            dtype = dtype.field(arg).dtype
        else:
            if not isinstance(dtype, ArrayType):
                raise KeyError(f"{name}: kein Array")
            dtype.position(arg, name)
            dtype = dtype.elem
    return dtype


def _container_key(dtype: DataType, step: Step):
    kind, arg = step
    if kind == "field":
        return arg, dtype.field(arg).dtype
    return dtype.position(arg), dtype.elem


def get_at(value, dtype: DataType, steps: list[Step]):
    for step in steps:
        key, dtype = _container_key(dtype, step)
        value = value[key]
    return value


def set_at(root, dtype: DataType, steps: list[Step], new):
    """Set the value at *steps* inside *root* (in place); returns the new root."""
    if not steps:
        return new
    container = root
    for step in steps[:-1]:
        key, dtype = _container_key(dtype, step)
        container = container[key]
    key, _ = _container_key(dtype, steps[-1])
    container[key] = new
    return root


def format_path(base: str, dtype: DataType, steps: list[Step]) -> str:
    """Display form with declared field names: 'lager[3].MENGE' -> 'Lager[3].Menge'."""
    out = base
    for kind, arg in steps:
        if kind == "field":
            f = dtype.field(arg)
            out += "." + f.name
            dtype = f.dtype
        else:
            out += f"[{arg}]"
            dtype = dtype.elem
    return out


def leaves(dtype: DataType, path: str, steps: list[Step], stop_at_leaf_arrays: bool):
    """Yield (display path, steps, dtype) for every leaf below *dtype*.

    With *stop_at_leaf_arrays* arrays of elementary values are one leaf (OPC UA),
    otherwise every element is (S7).
    """
    if isinstance(dtype, Elementary) or (stop_at_leaf_arrays and is_leaf(dtype)):
        yield path, steps, dtype
    elif isinstance(dtype, ArrayType):
        for i in range(dtype.low, dtype.high + 1):
            yield from leaves(dtype.elem, f"{path}[{i}]", steps + [("index", i)], stop_at_leaf_arrays)
    else:
        for f in dtype.fields:
            yield from leaves(f.dtype, f"{path}.{f.name}", steps + [("field", f.key)], stop_at_leaf_arrays)
