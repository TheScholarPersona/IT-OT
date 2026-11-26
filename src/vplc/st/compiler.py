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
    type: IecType  # element type for arrays
    section: str
    constant: bool = False
    retain: bool = False
    init: object = None
    value: object = None
    line: int = 0
    dims: tuple[int, int] | None = None  # (low, high) for ARRAY[low..high] OF type

    @property
    def writable(self) -> bool:
        return not self.constant

    @property
    def is_array(self) -> bool:
        return self.dims is not None

    @property
    def length(self) -> int:
        return self.dims[1] - self.dims[0] + 1 if self.dims else 1

    @property
    def type_label(self) -> str:
        if self.dims:
            return f"ARRAY[{self.dims[0]}..{self.dims[1]}] OF {self.type.name}"
        return self.type.name

    def same_shape(self, other: "Variable") -> bool:
        return self.type == other.type and self.dims == other.dims

    def coerce(self, value):
        """Convert an external value (scalar, or list for arrays) to this variable's type."""
        if self.dims is None:
            return coerce(self.type, value)
        if not isinstance(value, (list, tuple)) or len(value) != self.length:
            raise ValueError(f"{self.type_label} erwartet eine Liste mit {self.length} Werten")
        return [coerce(self.type, v) for v in value]

    def element_index(self, index: int) -> int:
        low, high = self.dims
        if not low <= index <= high:
            raise IndexError(f"Index {index} außerhalb von {self.name}[{low}..{high}]")
        return index - low

    def reset(self) -> None:
        self.value = list(self.init) if self.dims else self.init

    def snapshot(self):
        return list(self.value) if self.dims else self.value


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
        self.instantiating: list[str] = []  # FB types being instantiated (recursion check)
        self.compiling_functions: list[str] = []

    def err(self, message: str, node: ast.Node) -> None:
        self.errors.append(STSemanticError(message, node.line, node.col))

    # ------------------------------------------------------------ declarations
    def register(self) -> None:
        for fb in self.ast.function_blocks:
            key = fb.name.upper()
            if key in FUNCTION_BLOCKS or get_type(key) or key in FUNCTIONS:
                self.err(f"'{fb.name}' ist ein reservierter Name", fb)
            elif key in self.fb_decls or key in self.fn_decls:
                self.err(f"'{fb.name}' ist bereits deklariert", fb)
            else:
                self.fb_decls[key] = fb
        for fn in self.ast.functions:
            key = fn.name.upper()
            if key in FUNCTIONS or key in FUNCTION_BLOCKS or get_type(key):
                self.err(f"'{fn.name}' ist ein reservierter Name", fn)
            elif key in self.fb_decls or key in self.fn_decls:
                self.err(f"'{fn.name}' ist bereits deklariert", fn)
            else:
                self.fn_decls[key] = fn

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
                self.err(f"Unbekannter Rückgabetyp '{decl.return_type}'", decl)
                rtype = get_type("INT")
            pou = PouCompiler(self, "FUNCTION", decl.name)
            result = Variable(decl.name, rtype, "RESULT", init=rtype.default, value=rtype.default, line=decl.line)
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
        # check POUs that the program never uses
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
            t = get_type(d.type_name)
            if t is None:
                hint = " (Funktionen werden aufgerufen, nicht deklariert)" if d.type_name in self.unit.fn_decls else ""
                self.err(f"Unbekannter Datentyp '{d.type_name}'{hint}", d)
                continue
            dims = None
            if d.dims is not None:
                dims = self.array_dims(d)
                if dims is None:
                    continue
                if d.section in ("VAR_INPUT", "VAR_OUTPUT") and self.kind != "PROGRAM":
                    self.err("Arrays als Ein- oder Ausgang von Bausteinen werden noch nicht unterstützt", d)
                    continue
            init = self.initial_value(d, t, dims)
            if init is None:  # error already reported; declare anyway to avoid follow-up errors
                init = [t.default] * (dims[1] - dims[0] + 1) if dims else t.default
            self.variables[key] = Variable(
                d.name, t, d.section, d.constant, d.retain, init,
                list(init) if dims else init, d.line, dims)

    def declare_fb(self, d: ast.VarDecl, key: str) -> None:
        if self.kind == "FUNCTION":
            self.err("In Funktionen sind keine Funktionsbaustein-Instanzen erlaubt", d)
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

    def initial_value(self, d: ast.VarDecl, t: IecType, dims):
        if dims is None:
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
        length = dims[1] - dims[0] + 1
        values = []
        if d.init is not None:
            if not isinstance(d.init, ast.ArrayInit):
                self.err(f"Initialwert für Array '{d.name}' muss eine Liste [ … ] sein", d.init)
                return None
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
            if len(values) > length:
                self.err(f"{len(values)} Initialwerte für '{d.name}' mit {length} Elementen", d.init)
                return None
        elif d.constant:
            self.err(f"Konstante '{d.name}' benötigt einen Wert", d)
        return values + [t.default] * (length - len(values))

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
            if var.is_array:
                self.err(f"Array '{node.name}' braucht einen Index, z. B. {node.name}[0]", node)
                return lambda: 0
            if const and not var.constant:
                self.err(f"Initialwert darf nur Konstanten verwenden, nicht '{node.name}'", node)
                return lambda: 0
            if const:
                value = var.value
                return lambda: value
            return lambda: var.value
        if isinstance(node, ast.Index):
            return self.index_read(node, const)
        if isinstance(node, ast.Member):
            inst = self.fbs.get(node.obj.upper())
            if inst is None:
                self.err(f"Unbekannte Funktionsbaustein-Instanz '{node.obj}'", node)
                return lambda: 0
            block_cls = type(inst.block)
            if node.member not in block_cls.OUTPUTS and node.member not in block_cls.INPUTS:
                self.err(f"{getattr(block_cls, 'DISPLAY_NAME', inst.type_name)} hat keinen Parameter '{node.member}'", node)
                return lambda: 0
            member = node.member
            # Resolve the block at run time: a warm restart may swap it.
            return lambda: inst.block.values[member]
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

    def array_var(self, name: str, node: ast.Node) -> Variable | None:
        var = self.variables.get(name.upper())
        if var is None:
            self.err(f"Unbekannte Variable '{name}'", node)
            return None
        if not var.is_array:
            self.err(f"'{name}' ist kein Array", node)
            return None
        return var

    def index_read(self, node: ast.Index, const: bool) -> Expr:
        var = self.array_var(node.name, node)
        index = self.expr(node.index, const)
        if var is None:
            return lambda: 0
        if const and not var.constant:
            self.err(f"Initialwert darf nur Konstanten verwenden, nicht '{node.name}'", node)
            return lambda: 0
        line, col = node.line, node.col

        def read():
            try:
                return var.value[var.element_index(int(index()))]
            except IndexError as e:
                raise PLCRuntimeError(str(e), line, col) from None
        return read

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

    def assign_stmt(self, node: ast.Assign) -> Stmt:
        if isinstance(node.target, ast.Index):
            var = self.array_var(node.target.name, node.target)
            if var is not None and var.constant:
                self.err(f"Konstante '{var.name}' kann nicht beschrieben werden", node.target)
                var = None
            index = self.expr(node.target.index)
            value = self.expr(node.value)
            if var is None:
                return lambda: None
            t, line, col = var.type, node.line, node.col

            def assign_element():
                v = value()
                try:
                    i = var.element_index(int(index()))
                    var.value[i] = coerce(t, v)
                except IndexError as e:
                    raise PLCRuntimeError(str(e), line, col) from None
                except (ValueError, TypeError, OverflowError):
                    raise PLCRuntimeError(f"Wert {v!r} passt nicht in {t.name}-Element von '{var.name}'", line, col) from None
            return assign_element
        var = self.target(node.target)
        if var is not None and var.is_array:
            # whole-array copy: a := b with identical shape
            src = node.value
            other = self.variables.get(src.name.upper()) if isinstance(src, ast.Name) else None
            if other is None or not other.is_array or not other.same_shape(var):
                self.err(f"Array '{var.name}' kann nur ein gleichartiges Array zugewiesen werden", node)
                return lambda: None

            def copy_array():
                var.value = list(other.value)
            return copy_array
        value = self.expr(node.value)
        if var is None:
            return lambda: None
        assign = self.assigner(var, node.line, node.col)
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
        if var is not None and (var.type.kind != "int" or var.is_array):
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
