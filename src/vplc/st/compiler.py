"""Compile a Structured Text AST into executable Python closures.

The compiler also performs the semantic checks a PLC engineering tool would
(undefined names, unknown types, writes to constants, recursion ...) and collects
*all* errors so that an editor can show them at once.

Program organisation units:

* ``PROGRAM`` – exactly one per source, its variables are the PLC's variables.
* ``FUNCTION_BLOCK`` – user function blocks with memory; every instance gets its
  own compiled copy of the body bound to its own variables.
* ``FUNCTION`` – stateless functions; compiled once, recursion is rejected.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable

from ..datatypes import (ArrayType, DataType, Elementary, StructField, StructType, is_elementary,
                         same_layout)
from ..types import IecType, coerce, get_type
from . import ast
from .errors import PLCRuntimeError, STCompileError, STError, STSemanticError
from .parser import parse
from .stdlib import FUNCTION_BLOCKS, FUNCTIONS, FunctionBlock

Expr = Callable[[], object]
Stmt = Callable[[], None]

MAX_ARRAY_LENGTH = 10_000


class _Exit(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    pass


# ====================================================================== variables
@dataclass
class Variable:
    name: str
    dtype: DataType
    section: str
    constant: bool = False
    retain: bool = False
    init: object = None
    value: object = None
    line: int = 0

    # -- compatibility helpers for elementary values and arrays of elementary values
    @property
    def type(self) -> IecType | None:
        """Elementary type (element type for arrays of elementary values), else None."""
        if isinstance(self.dtype, Elementary):
            return self.dtype.iec
        if isinstance(self.dtype, ArrayType) and isinstance(self.dtype.elem, Elementary):
            return self.dtype.elem.iec
        return None

    @property
    def dims(self) -> tuple[int, int] | None:
        return (self.dtype.low, self.dtype.high) if isinstance(self.dtype, ArrayType) else None

    @property
    def writable(self) -> bool:
        return not self.constant

    @property
    def is_array(self) -> bool:
        return isinstance(self.dtype, ArrayType)

    @property
    def is_elementary(self) -> bool:
        return isinstance(self.dtype, Elementary)

    @property
    def length(self) -> int:
        return self.dtype.length if self.is_array else 1

    @property
    def type_label(self) -> str:
        return self.dtype.label

    def same_shape(self, other: "Variable") -> bool:
        return same_layout(self.dtype, other.dtype)

    def coerce(self, value):
        """Convert an external value (scalar, list for arrays, dict for structs) to this type."""
        return self.dtype.coerce(value, self.value)

    def element_index(self, index: int) -> int:
        return self.dtype.position(index, self.name)

    def reset(self) -> None:
        self.value = self.dtype.copy(self.init)

    def snapshot(self):
        return self.dtype.copy(self.value)

    def display(self):
        """Value for JSON consumers: copies, struct fields with their declared names."""
        return self.dtype.display(self.value)


@dataclass
class FBInstance:
    name: str
    block: FunctionBlock
    line: int = 0

    @property
    def type_name(self) -> str:
        return self.block.TYPE_NAME


class _ProgRef:
    """Late-bound reference to the program: bodies are compiled before it exists."""

    prog: "CompiledProgram | None" = None


# ====================================================================== user POUs
class _VarView(Mapping):
    """``values`` of a user function block: its inputs and outputs, backed by variables."""

    def __init__(self, variables: dict[str, Variable], names: list[str]):
        self._vars = variables
        self._names = names

    def __getitem__(self, key: str):
        return self._vars[key].value

    def __setitem__(self, key: str, value) -> None:
        var = self._vars[key]
        var.value = coerce(var.type, value)

    def __iter__(self):
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


class UserFunctionBlock(FunctionBlock):
    """Instance of a FUNCTION_BLOCK declared in the source."""

    def __init__(self, variables: dict[str, Variable], fbs: dict[str, FBInstance], body: list[Stmt]):
        # deliberately not calling super().__init__: values are backed by variables
        self.variables = variables
        self.fbs = fbs
        self.body = body
        self.values = _VarView(variables, list(self.INPUTS) + list(self.OUTPUTS))

    def set_input(self, name: str, value) -> None:
        self.values[name] = value

    def execute(self, now_ms: int) -> None:
        for var in self.variables.values():
            if var.section == "VAR_TEMP":
                var.reset()
        try:
            for stmt in self.body:
                stmt()
        except _Return:
            pass

    def snapshot(self) -> dict:
        return {k: v.snapshot() for k, v in self.variables.items()}

    def transfer_from(self, other: "UserFunctionBlock") -> None:
        """Warm restart: keep values, but run the newly compiled code."""
        _transfer(self.variables, self.fbs, other.variables, other.fbs)


def _transfer(variables, fbs, old_variables, old_fbs) -> list[str]:
    kept = []
    for key, var in variables.items():
        old = old_variables.get(key)
        if old and old.same_shape(var) and not var.constant and var.section != "VAR_TEMP":
            var.value = old.snapshot()
            kept.append(var.name)
    for key, fb in fbs.items():
        old_fb = old_fbs.get(key)
        if not old_fb or old_fb.type_name != fb.type_name:
            continue
        if isinstance(fb.block, UserFunctionBlock) and isinstance(old_fb.block, UserFunctionBlock):
            fb.block.transfer_from(old_fb.block)
        elif not isinstance(fb.block, UserFunctionBlock) and not isinstance(old_fb.block, UserFunctionBlock):
            fb.block = old_fb.block
        else:
            continue
        kept.append(fb.name)
    return kept


@dataclass
class CompiledFunction:
    name: str
    inputs: list[str]  # upper-case input names in declaration order
    variables: dict[str, Variable]
    result: Variable
    body: list[Stmt] = field(default_factory=list)
    active: bool = False

    def invoke(self, args: dict[str, object]):
        for var in self.variables.values():
            var.reset()
        for key, value in args.items():
            self.variables[key].value = coerce(self.variables[key].type, value)
        self.active = True
        try:
            for stmt in self.body:
                stmt()
        except _Return:
            pass
        finally:
            self.active = False
        return self.result.value


# ====================================================================== program
@dataclass
class CompiledProgram:
    name: str
    variables: dict[str, Variable]  # upper-case name -> Variable (declaration order)
    fbs: dict[str, FBInstance]
    body: list[Stmt]
    watchdog_ms: float = 1000.0
    now_ms: int = 0
    function_blocks: list[str] = field(default_factory=list)  # user FB type names
    functions: list[str] = field(default_factory=list)  # user function names
    _deadline: float = field(default=0.0, repr=False)
    _ticks: int = field(default=0, repr=False)

    def execute(self, now_ms: int) -> None:
        """Run one scan cycle."""
        self.now_ms = now_ms
        self._deadline = time.monotonic() + self.watchdog_ms / 1000.0
        self._ticks = 0
        for var in self.variables.values():
            if var.section == "VAR_TEMP":
                var.reset()
        try:
            for stmt in self.body:
                stmt()
        except _Return:
            pass
        except (_Exit, _Continue):  # pragma: no cover - rejected at compile time
            pass
        except RecursionError:
            raise PLCRuntimeError("Ausdruck zu tief verschachtelt") from None
        except TypeError as e:  # e.g. comparing a STRING with a number
            raise PLCRuntimeError(f"Typfehler: {e}") from None

    def tick(self, line: int) -> None:
        self._ticks += 1
        if self._ticks & 0x3FF == 0 and time.monotonic() > self._deadline:
            raise PLCRuntimeError(
                f"Zykluszeitüberwachung ausgelöst (> {self.watchdog_ms:.0f} ms) – Endlosschleife?",
                line,
            )

    def transfer_state_from(self, other: "CompiledProgram") -> list[str]:
        """Warm restart after a program download: keep values of unchanged variables."""
        return _transfer(self.variables, self.fbs, other.variables, other.fbs)


# ====================================================================== unit compiler
class Unit:
    """State shared by all POU compilers of one source: declarations, errors, program reference."""

    def __init__(self, program: ast.Program):
        self.ast = program
        self.errors: list[STError] = []
        self.ref = _ProgRef()
        self.fb_decls: dict[str, ast.FunctionBlockDecl] = {}
        self.fn_decls: dict[str, ast.FunctionDecl] = {}
        self.fb_classes: dict[str, type[UserFunctionBlock]] = {}
        self.functions: dict[str, CompiledFunction] = {}
        self.type_decls: dict[str, ast.TypeDecl] = {}
        self.struct_types: dict[str, StructType] = {}
        self.resolving_types: list[str] = []
        self.instantiating: list[str] = []  # FB types being instantiated (recursion check)
        self.compiling_functions: list[str] = []

    def err(self, message: str, node: ast.Node) -> None:
        self.errors.append(STSemanticError(message, node.line, node.col))

    # ------------------------------------------------------------ declarations
    def register(self) -> None:
        for td in self.ast.types:
            key = td.name.upper()
            if key in FUNCTION_BLOCKS or get_type(key) or key in FUNCTIONS:
                self.err(f"'{td.name}' ist ein reservierter Name", td)
            elif key in self.type_decls:
                self.err(f"Typ '{td.name}' ist bereits deklariert", td)
            else:
                self.type_decls[key] = td
        for fb in self.ast.function_blocks:
            key = fb.name.upper()
            if key in FUNCTION_BLOCKS or get_type(key) or key in FUNCTIONS:
                self.err(f"'{fb.name}' ist ein reservierter Name", fb)
            elif key in self.fb_decls or key in self.fn_decls or key in self.type_decls:
                self.err(f"'{fb.name}' ist bereits deklariert", fb)
            else:
                self.fb_decls[key] = fb
        for fn in self.ast.functions:
            key = fn.name.upper()
            if key in FUNCTIONS or key in FUNCTION_BLOCKS or get_type(key):
                self.err(f"'{fn.name}' ist ein reservierter Name", fn)
            elif key in self.fb_decls or key in self.fn_decls or key in self.type_decls:
                self.err(f"'{fn.name}' ist bereits deklariert", fn)
            else:
                self.fn_decls[key] = fn

    def struct_type(self, key: str, where: ast.Node) -> StructType | None:
        st = self.struct_types.get(key)
        if st is not None:
            return st
        decl = self.type_decls[key]
        if key in self.resolving_types:
            loop = self.resolving_types[self.resolving_types.index(key):] + [key]
            self.err(f"Struktur enthält sich selbst ({' → '.join(self.type_decls[k].name for k in loop)})", where)
            return None
        self.resolving_types.append(key)
        try:
            pou = PouCompiler(self, "TYPE", decl.name)
            pou.declare(decl.fields)
            fields = tuple(StructField(k, v.name, v.dtype, v.init) for k, v in pou.variables.items())
            st = StructType(decl.name, fields)
            self.struct_types[key] = st
            return st
        finally:
            self.resolving_types.pop()

    def fb_class(self, key: str) -> type[UserFunctionBlock]:
        cls = self.fb_classes.get(key)
        if cls is None:
            decl = self.fb_decls[key]
            inputs, outputs = {}, {}
            for d in decl.decls:
                t = get_type(d.type_name)
                if d.section in ("VAR_INPUT", "VAR_OUTPUT") and t is not None and d.dims is None:
                    (inputs if d.section == "VAR_INPUT" else outputs)[d.name.upper()] = t
            cls = type(decl.name, (UserFunctionBlock,), {
                "TYPE_NAME": key, "INPUTS": inputs, "OUTPUTS": outputs, "DISPLAY_NAME": decl.name,
            })
            self.fb_classes[key] = cls
        return cls

    def instantiate_fb(self, key: str, where: ast.Node) -> UserFunctionBlock | None:
        decl = self.fb_decls[key]
        if key in self.instantiating:
            loop = self.instantiating[self.instantiating.index(key):] + [key]
            chain = " → ".join(self.fb_decls[k].name for k in loop)
            self.err(f"Funktionsbaustein enthält sich selbst ({chain})", where)
            return None
        self.instantiating.append(key)
        try:
            pou = PouCompiler(self, "FUNCTION_BLOCK", decl.name)
            pou.declare(decl.decls)
            body = [pou.stmt(s) for s in decl.body]
            cls = self.fb_class(key)
            return cls(pou.variables, pou.fbs, body)
        finally:
            self.instantiating.pop()

    def function(self, key: str, where: ast.Node) -> CompiledFunction | None:
        if key in self.compiling_functions:
            names = [self.fn_decls[k].name for k in self.compiling_functions[self.compiling_functions.index(key):]]
            chain = " → ".join(names + [self.fn_decls[key].name])
            self.err(f"Rekursive Funktionsaufrufe sind nicht erlaubt ({chain})", where)
            return None
        fn = self.functions.get(key)
        if fn is not None:
            return fn
        decl = self.fn_decls[key]
        self.compiling_functions.append(key)
        try:
            rtype = get_type(decl.return_type)
            if rtype is None:
                if decl.return_type in self.type_decls:
                    self.err("Strukturen als Rückgabewert werden noch nicht unterstützt", decl)
                else:
                    self.err(f"Unbekannter Rückgabetyp '{decl.return_type}'", decl)
                rtype = get_type("INT")
            pou = PouCompiler(self, "FUNCTION", decl.name)
            result = Variable(decl.name, Elementary(rtype), "RESULT", init=rtype.default, value=rtype.default,
                              line=decl.line)
            pou.variables[key] = result
            pou.declare(decl.decls)
            inputs = [k for k, v in pou.variables.items() if v.section == "VAR_INPUT"]
            fn = CompiledFunction(decl.name, inputs, pou.variables, result)
            fn.body = [pou.stmt(s) for s in decl.body]
            self.functions[key] = fn
            return fn
        finally:
            self.compiling_functions.pop()

    # ------------------------------------------------------------ entry point
    def compile(self) -> CompiledProgram:
        self.register()
        pou = PouCompiler(self, "PROGRAM", self.ast.name)
        pou.declare(self.ast.decls)
        body = [pou.stmt(s) for s in self.ast.body]
        # check types and POUs that the program never uses
        for key, decl in self.type_decls.items():
            if key not in self.struct_types:
                self.struct_type(key, decl)
        for key in self.fn_decls:
            if key not in self.functions:
                self.function(key, self.fn_decls[key])
        for key, decl in self.fb_decls.items():
            if key not in self.fb_classes:
                self.instantiate_fb(key, decl)
        prog = CompiledProgram(self.ast.name, pou.variables, pou.fbs, body,
                               function_blocks=[d.name for d in self.ast.function_blocks],
                               functions=[d.name for d in self.ast.functions])
        self.ref.prog = prog
        if self.errors:
            unique = {(e.line, e.col, e.message): e for e in self.errors}
            raise STCompileError(sorted(unique.values(), key=lambda e: (e.line or 0, e.col or 0)))
        return prog


# ====================================================================== POU compiler
class PouCompiler:
    """Compiles declarations and statements of one POU (program, FB instance or function)."""

    def __init__(self, unit: Unit, kind: str, name: str):
        self.unit = unit
        self.kind = kind  # PROGRAM | FUNCTION_BLOCK | FUNCTION
        self.pou_name = name
        self.variables: dict[str, Variable] = {}
        self.fbs: dict[str, FBInstance] = {}
        self.loop_depth = 0

    @property
    def ref(self) -> _ProgRef:
        return self.unit.ref

    def err(self, message: str, node: ast.Node) -> None:
        self.unit.err(message, node)

    # ------------------------------------------------------------ declarations
    def declare(self, decls: list[ast.VarDecl]) -> None:
        for d in decls:
            key = d.name.upper()
            if key in self.variables or key in self.fbs:
                self.err(f"'{d.name}' ist bereits deklariert", d)
                continue
            if self.kind == "FUNCTION" and d.section == "VAR_OUTPUT":
                self.err("VAR_OUTPUT ist in Funktionen nicht erlaubt; Ergebnis über den Funktionsnamen zuweisen", d)
                continue
            if d.type_name in FUNCTION_BLOCKS or d.type_name in self.unit.fb_decls:
                self.declare_fb(d, key)
                continue
            dtype = self.resolve_dtype(d)
            if dtype is None:
                continue
            if not is_elementary(dtype) and (
                    (d.section in ("VAR_INPUT", "VAR_OUTPUT") and self.kind != "PROGRAM")):
                self.err("Arrays und Strukturen als Ein- oder Ausgang von Bausteinen werden noch nicht unterstützt", d)
                continue
            init = self.initial_value(d, dtype)
            if init is None:  # error already reported; declare anyway to avoid follow-up errors
                init = dtype.default()
            self.variables[key] = Variable(
                d.name, dtype, d.section, d.constant, d.retain, init, dtype.copy(init), d.line)

    def declare_fb(self, d: ast.VarDecl, key: str) -> None:
        if self.kind == "FUNCTION":
            self.err("In Funktionen sind keine Funktionsbaustein-Instanzen erlaubt", d)
            return
        if self.kind == "TYPE":
            self.err("Strukturen können keine Funktionsbausteine enthalten", d)
            return
        if d.init is not None:
            self.err("Funktionsbaustein-Instanzen können nicht initialisiert werden", d)
        if d.dims is not None:
            self.err("Arrays von Funktionsbausteinen werden noch nicht unterstützt", d)
            return
        if d.section != "VAR":
            self.err("Funktionsbaustein-Instanzen müssen in VAR deklariert werden", d)
        if d.type_name in FUNCTION_BLOCKS:
            self.fbs[key] = FBInstance(d.name, FUNCTION_BLOCKS[d.type_name](), d.line)
            return
        block = self.unit.instantiate_fb(d.type_name, d)
        if block is not None:
            self.fbs[key] = FBInstance(d.name, block, d.line)

    def resolve_dtype(self, d: ast.VarDecl) -> DataType | None:
        """Data type of a declaration: elementary, STRING[n], STRUCT type, ARRAY of those."""
        t = get_type(d.type_name)
        if t is not None:
            base: DataType | None = Elementary(t)
        elif d.type_name in self.unit.type_decls:
            base = self.unit.struct_type(d.type_name, d)
            if base is None:
                return None
        else:
            if d.type_name.startswith("STRING["):
                self.err(f"Ungültige Länge in '{d.type_name}' (1 … 254)", d)
            else:
                hint = " (Funktionen werden aufgerufen, nicht deklariert)" if d.type_name in self.unit.fn_decls else ""
                self.err(f"Unbekannter Datentyp '{d.type_name}'{hint}", d)
            return None
        if d.dims is None:
            return base
        dims = self.array_dims(d)
        return None if dims is None else ArrayType(base, *dims)

    def array_dims(self, d: ast.VarDecl) -> tuple[int, int] | None:
        try:
            low, high = (self.const_eval(x) for x in d.dims)
        except STError as e:
            self.unit.errors.append(e)
            return None
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (low, high)):
            self.err("Array-Grenzen müssen ganzzahlige Konstanten sein", d)
            return None
        if high < low:
            self.err(f"Obere Array-Grenze {high} ist kleiner als die untere {low}", d)
            return None
        if high - low + 1 > MAX_ARRAY_LENGTH:
            self.err(f"Array mit mehr als {MAX_ARRAY_LENGTH} Elementen", d)
            return None
        return low, high

    def initial_value(self, d: ast.VarDecl, dtype: DataType):
        """Initial value from the declaration, or None after reporting an error."""
        if isinstance(dtype, StructType):
            if d.init is not None:
                self.err(f"Strukturvariablen erhalten ihre Startwerte aus der Typdeklaration von {dtype.name}", d.init)
                return None
            return dtype.default()
        if isinstance(dtype, Elementary):
            t = dtype.iec
            if isinstance(d.init, ast.ArrayInit):
                self.err(f"'{d.name}' ist kein Array", d.init)
                return None
            if d.init is None:
                if d.constant:
                    self.err(f"Konstante '{d.name}' benötigt einen Wert", d)
                return t.default
            try:
                return coerce(t, self.const_eval(d.init))
            except STError as e:
                self.unit.errors.append(e)
            except (ValueError, TypeError, OverflowError):
                self.err(f"Ungültiger Initialwert für '{d.name}'", d)
            return None
        # ARRAY
        if d.init is None:
            if d.constant:
                self.err(f"Konstante '{d.name}' benötigt einen Wert", d)
            return dtype.default()
        if not isinstance(dtype.elem, Elementary):
            self.err(f"Arrays von Strukturen erhalten ihre Startwerte aus der Typdeklaration", d.init)
            return None
        if not isinstance(d.init, ast.ArrayInit):
            self.err(f"Initialwert für Array '{d.name}' muss eine Liste [ … ] sein", d.init)
            return None
        t = dtype.elem.iec
        values = []
        try:
            for count, item in d.init.items:
                n = 1 if count is None else self.const_eval(count)
                values.extend([coerce(t, self.const_eval(item))] * n)
        except STError as e:
            self.unit.errors.append(e)
            return None
        except (ValueError, TypeError, OverflowError):
            self.err(f"Ungültiger Initialwert für '{d.name}'", d)
            return None
        if len(values) > dtype.length:
            self.err(f"{len(values)} Initialwerte für '{d.name}' mit {dtype.length} Elementen", d.init)
            return None
        return values + [t.default] * (dtype.length - len(values))

    def const_eval(self, node: ast.Node):
        """Evaluate an initial value; may reference previously declared constants."""
        n_errors = len(self.unit.errors)
        fn = self.expr(node, const=True)
        if len(self.unit.errors) > n_errors:
            raise self.unit.errors.pop()
        try:
            return fn()
        except PLCRuntimeError as e:
            raise STSemanticError(e.message, node.line, node.col) from None

    # ------------------------------------------------------------ expressions
    def expr(self, node: ast.Node, const: bool = False) -> Expr:
        if isinstance(node, ast.Literal):
            value = node.value
            if node.type_name not in ("ANY_INT", "ANY_REAL"):
                t = get_type(node.type_name)
                if t is None:
                    self.err(f"Unbekannter Datentyp '{node.type_name}#'", node)
                else:
                    value = coerce(t, value)
            return lambda: value
        if isinstance(node, ast.Name):
            key = node.name.upper()
            var = self.variables.get(key)
            if var is None:
                if key in self.fbs:
                    self.err(f"'{node.name}' ist ein Funktionsbaustein; Ausgang mit '.' angeben", node)
                elif key in self.unit.fn_decls:
                    self.err(f"Funktion '{node.name}' muss mit ( ) aufgerufen werden", node)
                else:
                    self.err(f"Unbekannte Variable '{node.name}'", node)
                return lambda: 0
            if not var.is_elementary:
                self.err(self._composite_message(node.name, var.dtype), node)
                return lambda: 0
            if const and not var.constant:
                self.err(f"Initialwert darf nur Konstanten verwenden, nicht '{node.name}'", node)
                return lambda: 0
            if const:
                value = var.value
                return lambda: value
            return lambda: var.value
        if isinstance(node, ast.Path):
            getter, dtype = self.path(node, const)
            if getter is None:
                return lambda: 0
            if not is_elementary(dtype):
                self.err(self._composite_message(self._path_text(node), dtype), node)
                return lambda: 0
            return getter
        if isinstance(node, ast.Unary):
            operand = self.expr(node.operand, const)
            if node.op == "-":
                return lambda: -operand()
            return lambda: _not(operand())
        if isinstance(node, ast.Binary):
            return self.binary(node, const)
        if isinstance(node, ast.Call):
            return self.call(node, const)
        self.err("Nicht unterstützter Ausdruck", node)  # pragma: no cover
        return lambda: 0

    @staticmethod
    def _composite_message(name: str, dtype: DataType) -> str:
        if isinstance(dtype, ArrayType):
            return f"Array '{name}' braucht einen Index, z. B. {name}[{dtype.low}]"
        return f"Struktur '{name}' braucht ein Feld, z. B. {name}.{dtype.fields[0].name}"

    @staticmethod
    def _path_text(node: ast.Path) -> str:
        out = node.base
        for kind, arg, display in node.steps:
            out += f".{display}" if kind == "field" else "[…]"
        return out

    def path(self, node: ast.Path, const: bool = False):
        """Compile an access path. Returns (getter, data type) or (None, None) after an error.

        The base is either a function block instance (one step: its input/output) or a
        variable (fields and indices in any depth).
        """
        base_key = node.base.upper()
        inst = self.fbs.get(base_key)
        if inst is not None:
            kind, member, display = node.steps[0]
            cls = type(inst.block)
            if kind != "field":
                self.err(f"'{node.base}' ist ein Funktionsbaustein, kein Array", node)
                return None, None
            if len(node.steps) > 1:
                self.err(f"Ausgänge von Funktionsbausteinen sind elementar ('{node.base}.{display}')", node)
                return None, None
            iec = cls.OUTPUTS.get(member) or cls.INPUTS.get(member)
            if iec is None:
                self.err(f"{getattr(cls, 'DISPLAY_NAME', inst.type_name)} hat keinen Parameter '{member}'", node)
                return None, None
            # Resolve the block at run time: a warm restart may swap it.
            return (lambda: inst.block.values[member]), Elementary(iec)
        var = self.variables.get(base_key)
        if var is None:
            self.err(f"Unbekannte Variable '{node.base}'", node)
            return None, None
        if const and not var.constant:
            self.err(f"Initialwert darf nur Konstanten verwenden, nicht '{node.base}'", node)
            return None, None
        steps, dtype, shown = [], var.dtype, node.base
        for kind, arg, display in node.steps:
            if kind == "field":
                f = dtype.field(arg) if isinstance(dtype, StructType) else None
                if f is None:
                    what = f"'{shown}' ist keine Struktur" if not isinstance(dtype, StructType) \
                        else f"{dtype.name} hat kein Feld '{display}'"
                    self.err(what, node)
                    return None, None
                steps.append(("f", arg, None))
                dtype, shown = f.dtype, f"{shown}.{f.name}"
            else:
                if not isinstance(dtype, ArrayType):
                    self.err(f"'{shown}' ist kein Array", node)
                    return None, None
                steps.append(("i", self.expr(arg, const), (dtype, shown)))
                dtype, shown = dtype.elem, f"{shown}[…]"
        line, col = node.line, node.col

        def get_container(upto: int):
            v = var.value
            for kind, a, info in steps[:upto]:
                if kind == "f":
                    v = v[a]
                else:
                    arr, name = info
                    try:
                        v = v[arr.position(int(a()), name)]
                    except IndexError as e:
                        raise PLCRuntimeError(str(e), line, col) from None
            return v

        n = len(steps)

        def getter():
            return get_container(n)
        getter.container = get_container  # used by assignments
        getter.steps = steps
        getter.var = var
        return getter, dtype

    def binary(self, node: ast.Binary, const: bool) -> Expr:
        left = self.expr(node.left, const)
        right = self.expr(node.right, const)
        op, line, col = node.op, node.line, node.col

        def runtime_error(msg: str):
            return PLCRuntimeError(msg, line, col)

        if op == "+":
            return lambda: left() + right()
        if op == "-":
            return lambda: left() - right()
        if op == "*":
            return lambda: left() * right()
        if op == "/":
            def div():
                a, b = left(), right()
                if isinstance(a, float) or isinstance(b, float):
                    if b == 0:
                        if a == 0 or math.isnan(a):
                            return math.nan
                        return math.copysign(math.inf, a) * math.copysign(1.0, b)
                    return a / b
                if b == 0:
                    raise runtime_error("Division durch 0")
                q = abs(a) // abs(b)
                return q if (a >= 0) == (b >= 0) else -q
            return div
        if op == "MOD":
            def mod():
                a, b = left(), right()
                if b == 0:
                    raise runtime_error("MOD durch 0")
                if isinstance(a, float) or isinstance(b, float):
                    return math.fmod(a, b)
                return int(math.fmod(a, b))
            return mod
        if op == "**":
            def power():
                try:
                    return float(left()) ** float(right())
                except (OverflowError, ZeroDivisionError):
                    return math.inf
                except ValueError:
                    return math.nan
            return power
        if op == "=":
            return lambda: left() == right()
        if op == "<>":
            return lambda: left() != right()
        if op == "<":
            return lambda: left() < right()
        if op == ">":
            return lambda: left() > right()
        if op == "<=":
            return lambda: left() <= right()
        if op == ">=":
            return lambda: left() >= right()
        if op == "AND":
            def and_():
                a = left()
                if isinstance(a, bool):
                    return a and bool(right())
                return int(a) & int(right())
            return and_
        if op == "OR":
            def or_():
                a = left()
                if isinstance(a, bool):
                    return a or bool(right())
                return int(a) | int(right())
            return or_
        if op == "XOR":
            def xor():
                a, b = left(), right()
                if isinstance(a, bool) and isinstance(b, bool):
                    return a != b
                return int(a) ^ int(b)
            return xor
        self.err(f"Unbekannter Operator '{op}'", node)  # pragma: no cover
        return lambda: 0

    def call(self, node: ast.Call, const: bool) -> Expr:
        if node.func in FUNCTION_BLOCKS or node.func in self.unit.fb_decls or node.func in self.fbs:
            self.err("Funktionsbausteine werden als Anweisung aufgerufen, nicht in Ausdrücken", node)
            return lambda: 0
        if node.func in self.unit.fn_decls:
            return self.user_call(node, const)
        spec = FUNCTIONS.get(node.func)
        if spec is None:
            self.err(f"Unbekannte Funktion '{node.func}'", node)
            return lambda: 0
        if node.named:
            self.err(f"Standardfunktion {node.func} erwartet Positionsargumente", node)
            return lambda: 0
        fn, min_args, max_args = spec
        n = len(node.args)
        if n < min_args or (max_args is not None and n > max_args):
            expected = str(min_args) if min_args == max_args else f"mindestens {min_args}"
            self.err(f"{node.func} erwartet {expected} Argument(e), erhalten {n}", node)
            return lambda: 0
        args = [self.expr(a, const) for a in node.args]
        line, col, name = node.line, node.col, node.func

        def call():
            try:
                return fn(*[a() for a in args])
            except PLCRuntimeError:
                raise
            except (TypeError, ValueError, OverflowError) as e:
                raise PLCRuntimeError(f"Fehler in {name}: {e}", line, col) from None
        return call

    def user_call(self, node: ast.Call, const: bool) -> Expr:
        if const:
            self.err("Funktionsaufrufe sind in Initialwerten nicht erlaubt", node)
            return lambda: 0
        fn = self.unit.function(node.func, node)
        if fn is None:
            return lambda: 0
        if len(node.args) > len(fn.inputs):
            self.err(f"{fn.name} hat {len(fn.inputs)} Eingänge, erhalten {len(node.args)} Argumente", node)
            return lambda: 0
        bound: list[tuple[str, Expr]] = []
        for key, arg in zip(fn.inputs, node.args):
            bound.append((key, self.expr(arg)))
        for key, arg in node.named.items():
            if key not in fn.inputs:
                self.err(f"{fn.name} hat keinen Eingang '{key}'", node)
                continue
            if any(k == key for k, _ in bound):
                self.err(f"Eingang '{key}' von {fn.name} doppelt angegeben", node)
                continue
            bound.append((key, self.expr(arg)))
        line, col = node.line, node.col

        def call():
            values = {k: e() for k, e in bound}  # evaluate arguments before the call
            try:
                return fn.invoke(values)
            except (ValueError, TypeError, OverflowError):
                raise PLCRuntimeError(f"Ungültiges Argument für {fn.name}", line, col) from None
        return call

    # ------------------------------------------------------------ statements
    def block(self, stmts: list[ast.Node]) -> Stmt:
        compiled = [self.stmt(s) for s in stmts]
        if not compiled:
            return lambda: None
        if len(compiled) == 1:
            return compiled[0]

        def run():
            for s in compiled:
                s()
        return run

    def target(self, name: ast.Name) -> Variable | None:
        """Elementary variable that a statement writes (assignment, FOR, FB output)."""
        var = self.variables.get(name.name.upper())
        if var is None:
            if name.name.upper() in self.fbs:
                self.err(f"Funktionsbaustein-Instanz '{name.name}' kann nicht zugewiesen werden", name)
            else:
                self.err(f"Unbekannte Variable '{name.name}'", name)
            return None
        if var.constant:
            self.err(f"Konstante '{name.name}' kann nicht beschrieben werden", name)
            return None
        return var

    def assigner(self, var: Variable, line: int, col: int):
        t = var.type

        def assign(value):
            try:
                var.value = coerce(t, value)
            except (ValueError, TypeError, OverflowError):
                raise PLCRuntimeError(
                    f"Wert {value!r} passt nicht in {t.name}-Variable '{var.name}'", line, col
                ) from None
        return assign

    def _composite_source(self, node: ast.Node, dtype: DataType, target: str):
        """Getter for the right-hand side of a whole-array/struct assignment, or None."""
        if isinstance(node, ast.Name):
            other = self.variables.get(node.name.upper())
            if other is not None and same_layout(other.dtype, dtype):
                return lambda: other.value
        elif isinstance(node, ast.Path) and node.base.upper() not in self.fbs:
            n_errors = len(self.unit.errors)
            getter, src_dtype = self.path(node)
            if getter is not None and same_layout(src_dtype, dtype):
                return getter
            del self.unit.errors[n_errors:]
        kind = "Array" if isinstance(dtype, ArrayType) else "Struktur"
        self.err(f"{kind} '{target}' kann nur ein gleichartiges {kind} ({dtype.label}) zugewiesen werden", node)
        return None

    def assign_stmt(self, node: ast.Assign) -> Stmt:
        line, col = node.line, node.col
        if isinstance(node.target, ast.Path):
            if node.target.base.upper() in self.fbs:
                self.err("Ein- und Ausgänge von Funktionsbausteinen werden beim Aufruf versorgt, nicht zugewiesen",
                         node.target)
                return lambda: None
            getter, dtype = self.path(node.target)
            if getter is None:
                self.expr(node.value)
                return lambda: None
            var = getter.var
            if var.constant:
                self.err(f"Konstante '{var.name}' kann nicht beschrieben werden", node.target)
                return lambda: None
            container, steps = getter.container, getter.steps
            last_kind, last_arg, last_info = steps[-1]
            n = len(steps)
            if is_elementary(dtype):
                value, t = self.expr(node.value), dtype.iec
            else:
                src = self._composite_source(node.value, dtype, self._path_text(node.target))
                if src is None:
                    return lambda: None
                value, t = (lambda: dtype.copy(src())), None

            def assign_path():
                v = value()
                parent = container(n - 1)
                if last_kind == "f":
                    key = last_arg
                else:
                    arr, name = last_info
                    try:
                        key = arr.position(int(last_arg()), name)
                    except IndexError as e:
                        raise PLCRuntimeError(str(e), line, col) from None
                try:
                    parent[key] = coerce(t, v) if t is not None else v
                except (ValueError, TypeError, OverflowError):
                    raise PLCRuntimeError(f"Wert {v!r} passt nicht in {t.name}", line, col) from None
            return assign_path
        var = self.target(node.target)
        if var is not None and not var.is_elementary:
            src = self._composite_source(node.value, var.dtype, var.name)
            if src is None:
                return lambda: None
            dtype = var.dtype

            def copy_whole():
                var.value = dtype.copy(src())
            return copy_whole
        value = self.expr(node.value)
        if var is None:
            return lambda: None
        assign = self.assigner(var, line, col)
        return lambda: assign(value())

    def stmt(self, node: ast.Node) -> Stmt:
        if isinstance(node, ast.Assign):
            return self.assign_stmt(node)
        if isinstance(node, ast.FBCall):
            return self.fb_call(node)
        if isinstance(node, ast.If):
            branches = [(self.expr(c), self.block(b)) for c, b in node.branches]
            orelse = self.block(node.orelse)

            def if_():
                for cond, body in branches:
                    if cond():
                        body()
                        return
                orelse()
            return if_
        if isinstance(node, ast.Case):
            selector = self.expr(node.selector)
            branches = [([(lb.low, lb.high) for lb in labels], self.block(b))
                        for labels, b in node.branches]
            orelse = self.block(node.orelse)

            def case():
                v = selector()
                for ranges, body in branches:
                    for lo, hi in ranges:
                        if lo <= v <= hi:
                            body()
                            return
                orelse()
            return case
        if isinstance(node, ast.For):
            return self.for_loop(node)
        if isinstance(node, ast.While):
            cond = self.expr(node.cond)
            body = self.loop_body(node.body)
            ref, line = self.ref, node.line

            def while_():
                prog = ref.prog
                while cond():
                    prog.tick(line)
                    try:
                        body()
                    except _Continue:
                        continue
                    except _Exit:
                        break
            return while_
        if isinstance(node, ast.Repeat):
            body = self.loop_body(node.body)
            cond = self.expr(node.cond)
            ref, line = self.ref, node.line

            def repeat():
                prog = ref.prog
                while True:
                    prog.tick(line)
                    try:
                        body()
                    except _Continue:
                        pass
                    except _Exit:
                        break
                    if cond():
                        break
            return repeat
        if isinstance(node, (ast.Exit, ast.Continue)):
            if self.loop_depth == 0:
                kw = "EXIT" if isinstance(node, ast.Exit) else "CONTINUE"
                self.err(f"{kw} ist nur innerhalb einer Schleife erlaubt", node)
                return lambda: None
            exc = _Exit if isinstance(node, ast.Exit) else _Continue

            def jump():
                raise exc()
            return jump
        if isinstance(node, ast.Return):
            def ret():
                raise _Return()
            return ret
        self.err("Nicht unterstützte Anweisung", node)  # pragma: no cover
        return lambda: None

    def loop_body(self, stmts: list[ast.Node]) -> Stmt:
        self.loop_depth += 1
        try:
            return self.block(stmts)
        finally:
            self.loop_depth -= 1

    def for_loop(self, node: ast.For) -> Stmt:
        var = self.target(node.var)
        if var is not None and (not var.is_elementary or var.type.kind != "int"):
            self.err(f"Laufvariable '{var.name}' muss ein Ganzzahltyp sein", node.var)
            var = None
        start = self.expr(node.start)
        end = self.expr(node.end)
        step = self.expr(node.step) if node.step is not None else (lambda: 1)
        body = self.loop_body(node.body)
        if var is None:
            return lambda: None
        assign = self.assigner(var, node.line, node.col)
        ref, line, col = self.ref, node.line, node.col

        def for_():
            prog = ref.prog
            s = step()
            if s == 0:
                raise PLCRuntimeError("FOR-Schleife mit Schrittweite 0", line, col)
            last = end()
            assign(start())
            while (var.value <= last) if s > 0 else (var.value >= last):
                prog.tick(line)
                try:
                    body()
                except _Continue:
                    pass
                except _Exit:
                    break
                nxt = var.value + s
                assign(nxt)
                if var.value != nxt:  # wrapped around the type range
                    break
        return for_

    def fb_call(self, node: ast.FBCall) -> Stmt:
        inst = self.fbs.get(node.instance.upper())
        if inst is None:
            key = node.instance.upper()
            if key in FUNCTIONS or key in self.unit.fn_decls:
                self.err(f"Rückgabewert der Funktion '{node.instance}' wird nicht verwendet", node)
            elif key in self.variables:
                self.err(f"'{node.instance}' ist kein Funktionsbaustein", node)
            else:
                self.err(f"Unbekannte Funktionsbaustein-Instanz '{node.instance}'", node)
            return lambda: None
        cls = type(inst.block)
        display = getattr(cls, "DISPLAY_NAME", inst.type_name)
        inputs = []
        for pname, expr in node.inputs.items():
            if pname not in cls.INPUTS:
                self.err(f"{display} hat keinen Eingang '{pname}'", node)
                continue
            inputs.append((pname, self.expr(expr)))
        outputs = []
        for pname, target in node.outputs.items():
            if pname not in cls.OUTPUTS:
                self.err(f"{display} hat keinen Ausgang '{pname}'", node)
                continue
            var = self.target(target)
            if var is not None and not var.is_elementary:
                self.err(f"'{var.name}' ist kein elementarer Wert und kann keinen Ausgang aufnehmen", target)
                var = None
            if var is not None:
                outputs.append((pname, self.assigner(var, target.line, target.col)))
        ref, line, col = self.ref, node.line, node.col

        def call():
            block = inst.block
            try:
                for pname, expr in inputs:
                    block.set_input(pname, expr())
            except (ValueError, TypeError, OverflowError):
                raise PLCRuntimeError(f"Ungültiger Eingangswert für {inst.name}", line, col) from None
            block.execute(ref.prog.now_ms)
            for pname, assign in outputs:
                assign(block.values[pname])
        return call


def _not(v):
    if isinstance(v, bool):
        return not v
    return ~int(v)


def compile_source(source: str, watchdog_ms: float = 1000.0) -> CompiledProgram:
    """Parse and compile ST source. Raises STSyntaxError or STCompileError."""
    program = parse(source)
    compiled = Unit(program).compile()
    compiled.watchdog_ms = watchdog_ms
    return compiled


def check_source(source: str) -> list[dict]:
    """Return a list of error dicts (empty if the program is valid)."""
    try:
        compile_source(source)
    except STCompileError as e:
        return [err.to_dict() for err in e.errors]
    except STError as e:
        return [e.to_dict()]
    return []
