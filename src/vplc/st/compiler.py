"""Compile a Structured Text AST into executable Python closures.

The compiler also performs the semantic checks a PLC engineering tool would
(undefined names, unknown types, writes to constants ...) and collects *all*
errors so that an editor can show them at once.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

from ..types import IecType, coerce, get_type
from . import ast
from .errors import PLCRuntimeError, STCompileError, STError, STSemanticError
from .parser import parse
from .stdlib import FUNCTION_BLOCKS, FUNCTIONS, FunctionBlock

Expr = Callable[[], object]
Stmt = Callable[[], None]


class _Exit(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    pass


@dataclass
class Variable:
    name: str
    type: IecType
    section: str
    constant: bool = False
    retain: bool = False
    init: object = None
    value: object = None
    line: int = 0

    @property
    def writable(self) -> bool:
        return not self.constant


@dataclass
class FBInstance:
    name: str
    block: FunctionBlock
    line: int = 0

    @property
    def type_name(self) -> str:
        return self.block.TYPE_NAME


@dataclass
class CompiledProgram:
    name: str
    variables: dict[str, Variable]  # upper-case name -> Variable (declaration order)
    fbs: dict[str, FBInstance]
    body: list[Stmt]
    watchdog_ms: float = 1000.0
    now_ms: int = 0
    _deadline: float = field(default=0.0, repr=False)
    _ticks: int = field(default=0, repr=False)

    def execute(self, now_ms: int) -> None:
        """Run one scan cycle."""
        self.now_ms = now_ms
        self._deadline = time.monotonic() + self.watchdog_ms / 1000.0
        self._ticks = 0
        for var in self.variables.values():
            if var.section == "VAR_TEMP":
                var.value = var.init
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
        kept = []
        for key, var in self.variables.items():
            old = other.variables.get(key)
            if old and old.type == var.type and not var.constant and var.section != "VAR_TEMP":
                var.value = old.value
                kept.append(var.name)
        for key, fb in self.fbs.items():
            old_fb = other.fbs.get(key)
            if old_fb and old_fb.type_name == fb.type_name:
                fb.block = old_fb.block
                kept.append(fb.name)
        return kept


class Compiler:
    def __init__(self, program: ast.Program):
        self.ast = program
        self.errors: list[STError] = []
        self.variables: dict[str, Variable] = {}
        self.fbs: dict[str, FBInstance] = {}
        self.loop_depth = 0
        self.prog: CompiledProgram | None = None

    def err(self, message: str, node: ast.Node) -> None:
        self.errors.append(STSemanticError(message, node.line, node.col))

    # ------------------------------------------------------------ declarations
    def declare(self) -> None:
        for d in self.ast.decls:
            key = d.name.upper()
            if key in self.variables or key in self.fbs:
                self.err(f"'{d.name}' ist bereits deklariert", d)
                continue
            if d.type_name in FUNCTION_BLOCKS:
                if d.init is not None:
                    self.err("Funktionsbaustein-Instanzen können nicht initialisiert werden", d)
                if d.section != "VAR":
                    self.err("Funktionsbaustein-Instanzen müssen in VAR deklariert werden", d)
                self.fbs[key] = FBInstance(d.name, FUNCTION_BLOCKS[d.type_name](), d.line)
                continue
            t = get_type(d.type_name)
            if t is None:
                self.err(f"Unbekannter Datentyp '{d.type_name}'", d)
                continue
            init = t.default
            if d.init is not None:
                try:
                    init = coerce(t, self.const_eval(d.init))
                except STError as e:
                    self.errors.append(e)
                except (ValueError, TypeError, OverflowError):
                    self.err(f"Ungültiger Initialwert für '{d.name}'", d)
            elif d.constant:
                self.err(f"Konstante '{d.name}' benötigt einen Wert", d)
            self.variables[key] = Variable(
                d.name, t, d.section, d.constant, d.retain, init, init, d.line
            )

    def const_eval(self, node: ast.Node):
        """Evaluate an initial value; may reference previously declared constants."""
        n_errors = len(self.errors)
        fn = self.expr(node, const=True)
        if len(self.errors) > n_errors:
            raise self.errors.pop()
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
                else:
                    self.err(f"Unbekannte Variable '{node.name}'", node)
                return lambda: 0
            if const and not var.constant:
                self.err(f"Initialwert darf nur Konstanten verwenden, nicht '{node.name}'", node)
                return lambda: 0
            if const:
                value = var.value
                return lambda: value
            return lambda: var.value
        if isinstance(node, ast.Member):
            inst = self.fbs.get(node.obj.upper())
            if inst is None:
                self.err(f"Unbekannte Funktionsbaustein-Instanz '{node.obj}'", node)
                return lambda: 0
            block_cls = type(inst.block)
            if node.member not in block_cls.OUTPUTS and node.member not in block_cls.INPUTS:
                self.err(f"{inst.type_name} hat keinen Parameter '{node.member}'", node)
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
        if node.func in FUNCTION_BLOCKS or node.func.upper() in self.fbs:
            self.err("Funktionsbausteine werden als Anweisung aufgerufen, nicht in Ausdrücken", node)
            return lambda: 0
        spec = FUNCTIONS.get(node.func)
        if spec is None:
            self.err(f"Unbekannte Funktion '{node.func}'", node)
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

    def stmt(self, node: ast.Node) -> Stmt:
        if isinstance(node, ast.Assign):
            var = self.target(node.target)
            value = self.expr(node.value)
            if var is None:
                return lambda: None
            assign = self.assigner(var, node.line, node.col)
            return lambda: assign(value())
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
            prog_ref, line = self, node.line

            def while_():
                prog = prog_ref.prog
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
            prog_ref, line = self, node.line

            def repeat():
                prog = prog_ref.prog
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
        if var is not None and var.type.kind != "int":
            self.err(f"Laufvariable '{var.name}' muss ein Ganzzahltyp sein", node.var)
            var = None
        start = self.expr(node.start)
        end = self.expr(node.end)
        step = self.expr(node.step) if node.step is not None else (lambda: 1)
        body = self.loop_body(node.body)
        if var is None:
            return lambda: None
        assign = self.assigner(var, node.line, node.col)
        prog_ref, line, col = self, node.line, node.col

        def for_():
            prog = prog_ref.prog
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
            if node.instance.upper() in FUNCTIONS:
                self.err(f"Rückgabewert der Funktion '{node.instance}' wird nicht verwendet", node)
            elif node.instance.upper() in self.variables:
                self.err(f"'{node.instance}' ist kein Funktionsbaustein", node)
            else:
                self.err(f"Unbekannte Funktionsbaustein-Instanz '{node.instance}'", node)
            return lambda: None
        cls = type(inst.block)
        inputs = []
        for pname, expr in node.inputs.items():
            if pname not in cls.INPUTS:
                self.err(f"{inst.type_name} hat keinen Eingang '{pname}'", node)
                continue
            inputs.append((pname, self.expr(expr)))
        outputs = []
        for pname, target in node.outputs.items():
            if pname not in cls.OUTPUTS:
                self.err(f"{inst.type_name} hat keinen Ausgang '{pname}'", node)
                continue
            var = self.target(target)
            if var is not None:
                outputs.append((pname, self.assigner(var, target.line, target.col)))
        prog_ref, line, col = self, node.line, node.col

        def call():
            block = inst.block
            try:
                for pname, expr in inputs:
                    block.set_input(pname, expr())
            except (ValueError, TypeError, OverflowError):
                raise PLCRuntimeError(f"Ungültiger Eingangswert für {inst.name}", line, col) from None
            block.execute(prog_ref.prog.now_ms)
            for pname, assign in outputs:
                assign(block.values[pname])
        return call

    # ------------------------------------------------------------ entry point
    def compile(self) -> CompiledProgram:
        self.declare()
        prog = CompiledProgram(self.ast.name, self.variables, self.fbs, [])
        self.prog = prog
        prog.body = [self.stmt(s) for s in self.ast.body]
        if self.errors:
            self.errors.sort(key=lambda e: (e.line or 0, e.col or 0))
            raise STCompileError(self.errors)
        return prog


def _not(v):
    if isinstance(v, bool):
        return not v
    return ~int(v)


def compile_source(source: str, watchdog_ms: float = 1000.0) -> CompiledProgram:
    """Parse and compile ST source. Raises STSyntaxError or STCompileError."""
    program = parse(source)
    compiled = Compiler(program).compile()
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
