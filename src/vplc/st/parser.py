"""Recursive-descent parser for a practical subset of IEC 61131-3 Structured Text."""

from __future__ import annotations

from . import ast
from .errors import STSyntaxError
from .lexer import Token, tokenize

_VAR_SECTIONS = {"VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_TEMP", "VAR_IN_OUT"}
_STMT_END = {
    "END_PROGRAM", "END_FUNCTION", "END_FUNCTION_BLOCK", "END_IF", "ELSIF", "ELSE", "END_CASE", "END_FOR",
    "END_WHILE", "UNTIL", "END_REPEAT",
}


class Parser:
    def __init__(self, source: str):
        self.tokens = tokenize(source)
        self.pos = 0

    # ------------------------------------------------------------ helpers
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def is_kw(self, *names: str) -> bool:
        return self.tok.kind == "KW" and self.tok.value in names

    def is_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.value in ops

    def error(self, message: str, tok: Token | None = None) -> STSyntaxError:
        t = tok or self.tok
        return STSyntaxError(message, t.line, t.col)

    def describe(self, t: Token) -> str:
        if t.kind == "EOF":
            return "Dateiende"
        return f"'{t.text or t.value}'"

    def expect_kw(self, name: str) -> Token:
        if not self.is_kw(name):
            raise self.error(f"{name} erwartet, gefunden {self.describe(self.tok)}")
        return self.advance()

    def expect_op(self, op: str) -> Token:
        if not self.is_op(op):
            raise self.error(f"'{op}' erwartet, gefunden {self.describe(self.tok)}")
        return self.advance()

    def expect_ident(self) -> Token:
        if self.tok.kind != "IDENT":
            raise self.error(f"Bezeichner erwartet, gefunden {self.describe(self.tok)}")
        return self.advance()

    def optional_semicolon(self) -> None:
        if self.is_op(";"):
            self.advance()

    # ------------------------------------------------------------ program organisation units
    def parse_source(self) -> ast.Program:
        """One PROGRAM plus any number of FUNCTION_BLOCKs and FUNCTIONs, in any order."""
        program: ast.Program | None = None
        fbs: list[ast.FunctionBlockDecl] = []
        functions: list[ast.FunctionDecl] = []
        while self.tok.kind != "EOF":
            if self.is_kw("PROGRAM"):
                if program is not None:
                    raise self.error("Nur ein PROGRAM je Quelltext erlaubt")
                program = self.parse_program()
            elif self.is_kw("FUNCTION_BLOCK"):
                fbs.append(self.parse_function_block())
            elif self.is_kw("FUNCTION"):
                functions.append(self.parse_function())
            else:
                raise self.error(f"PROGRAM, FUNCTION_BLOCK oder FUNCTION erwartet, gefunden {self.describe(self.tok)}")
        if program is None:
            raise self.error("PROGRAM erwartet – der Quelltext enthält kein Programm")
        program.function_blocks = fbs
        program.functions = functions
        return program

    def _decls(self) -> list[ast.VarDecl]:
        decls: list[ast.VarDecl] = []
        while self.is_kw(*_VAR_SECTIONS):
            decls.extend(self.parse_var_block())
        return decls

    def parse_program(self) -> ast.Program:
        start = self.expect_kw("PROGRAM")
        name = self.expect_ident().value
        decls = self._decls()
        body = self.parse_statements()
        self.expect_kw("END_PROGRAM")
        self.optional_semicolon()
        return ast.Program(name, decls, body, line=start.line, col=start.col)

    def parse_function_block(self) -> ast.FunctionBlockDecl:
        start = self.expect_kw("FUNCTION_BLOCK")
        name = self.expect_ident().value
        decls = self._decls()
        body = self.parse_statements()
        self.expect_kw("END_FUNCTION_BLOCK")
        self.optional_semicolon()
        return ast.FunctionBlockDecl(name, decls, body, line=start.line, col=start.col)

    def parse_function(self) -> ast.FunctionDecl:
        start = self.expect_kw("FUNCTION")
        name = self.expect_ident().value
        self.expect_op(":")
        if self.tok.kind != "IDENT":
            raise self.error(f"Rückgabetyp erwartet, gefunden {self.describe(self.tok)}")
        return_type = self.advance().value.upper()
        self.optional_semicolon()
        decls = self._decls()
        body = self.parse_statements()
        self.expect_kw("END_FUNCTION")
        self.optional_semicolon()
        return ast.FunctionDecl(name, return_type, decls, body, line=start.line, col=start.col)

    def parse_var_block(self) -> list[ast.VarDecl]:
        section_tok = self.advance()
        section = section_tok.value
        if section == "VAR_IN_OUT":
            raise self.error("VAR_IN_OUT wird noch nicht unterstützt", section_tok)
        constant = retain = False
        while self.is_kw("CONSTANT", "RETAIN"):
            if self.advance().value == "CONSTANT":
                constant = True
            else:
                retain = True
        decls: list[ast.VarDecl] = []
        while not self.is_kw("END_VAR"):
            names = [self.expect_ident()]
            while self.is_op(","):
                self.advance()
                names.append(self.expect_ident())
            self.expect_op(":")
            dims = None
            if self.is_kw("ARRAY"):
                dims = self.parse_array_dims()
            if self.tok.kind != "IDENT":
                raise self.error(f"Datentyp erwartet, gefunden {self.describe(self.tok)}")
            type_name = self.advance().value.upper()
            init = None
            if self.is_op(":="):
                self.advance()
                init = self.parse_array_init() if self.is_op("[") else self.parse_expr()
            self.expect_op(";")
            for n in names:
                decls.append(ast.VarDecl(
                    n.value, type_name, section, init, constant, retain, dims,
                    line=n.line, col=n.col,
                ))
        self.expect_kw("END_VAR")
        self.optional_semicolon()
        return decls

    def parse_array_dims(self) -> tuple[ast.Node, ast.Node]:
        self.expect_kw("ARRAY")
        self.expect_op("[")
        low = self.parse_expr()
        self.expect_op("..")
        high = self.parse_expr()
        if self.is_op(","):
            raise self.error("Mehrdimensionale Arrays werden noch nicht unterstützt")
        self.expect_op("]")
        self.expect_kw("OF")
        if self.is_kw("ARRAY"):
            raise self.error("Mehrdimensionale Arrays werden noch nicht unterstützt")
        return low, high

    def parse_array_init(self) -> ast.ArrayInit:
        start = self.expect_op("[")
        items: list[tuple[ast.Node | None, ast.Node]] = []
        while not self.is_op("]"):
            if self.tok.kind == "INT" and self.peek().kind == "OP" and self.peek().value == "(":
                count_tok = self.advance()
                self.advance()  # (
                value = self.parse_expr()
                self.expect_op(")")
                count = ast.Literal(count_tok.value, "ANY_INT", line=count_tok.line, col=count_tok.col)
                items.append((count, value))
            else:
                items.append((None, self.parse_expr()))
            if not self.is_op("]"):
                self.expect_op(",")
        self.advance()
        return ast.ArrayInit(items, line=start.line, col=start.col)

    # ------------------------------------------------------------ statements
    def parse_statements(self, case_body: bool = False) -> list[ast.Node]:
        stmts: list[ast.Node] = []
        while True:
            t = self.tok
            if t.kind == "EOF":
                return stmts
            if t.kind == "KW" and t.value in _STMT_END:
                return stmts
            if case_body and self._at_case_label():
                return stmts
            if self.is_op(";"):
                self.advance()
                continue
            stmts.append(self.parse_statement())

    def _at_case_label(self) -> bool:
        t = self.tok
        if t.kind == "INT":
            return True
        return t.kind == "OP" and t.value == "-" and self.peek().kind == "INT"

    def parse_statement(self) -> ast.Node:
        t = self.tok
        if t.kind == "KW":
            kw = t.value
            if kw == "IF":
                return self.parse_if()
            if kw == "CASE":
                return self.parse_case()
            if kw == "FOR":
                return self.parse_for()
            if kw == "WHILE":
                return self.parse_while()
            if kw == "REPEAT":
                return self.parse_repeat()
            if kw in ("EXIT", "CONTINUE", "RETURN"):
                self.advance()
                self.expect_op(";")
                cls = {"EXIT": ast.Exit, "CONTINUE": ast.Continue, "RETURN": ast.Return}[kw]
                return cls(line=t.line, col=t.col)
            raise self.error(f"Anweisung erwartet, gefunden {self.describe(t)}")
        if t.kind == "IDENT":
            ident = self.advance()
            if self.is_op("["):
                self.advance()
                index = self.parse_expr()
                self.expect_op("]")
                self.expect_op(":=")
                value = self.parse_expr()
                self.expect_op(";")
                target = ast.Index(ident.value, index, line=ident.line, col=ident.col)
                return ast.Assign(target, value, line=ident.line, col=ident.col)
            if self.is_op(":="):
                self.advance()
                value = self.parse_expr()
                self.expect_op(";")
                target = ast.Name(ident.value, line=ident.line, col=ident.col)
                return ast.Assign(target, value, line=ident.line, col=ident.col)
            if self.is_op("("):
                return self.parse_fb_call(ident)
            if self.is_op("."):
                raise self.error("Ausgänge von Funktionsbausteinen können nicht beschrieben werden")
            raise self.error(f"':=' oder '(' erwartet, gefunden {self.describe(self.tok)}")
        raise self.error(f"Anweisung erwartet, gefunden {self.describe(t)}")

    def parse_fb_call(self, ident: Token) -> ast.FBCall:
        self.expect_op("(")
        inputs: dict[str, ast.Node] = {}
        outputs: dict[str, ast.Name] = {}
        while not self.is_op(")"):
            param = self.expect_ident()
            key = param.value.upper()
            if self.is_op(":="):
                self.advance()
                inputs[key] = self.parse_expr()
            elif self.is_op("=>"):
                self.advance()
                target = self.expect_ident()
                outputs[key] = ast.Name(target.value, line=target.line, col=target.col)
            else:
                raise self.error("':=' oder '=>' erwartet (Parameter müssen benannt sein)")
            if not self.is_op(")"):
                self.expect_op(",")
        self.advance()
        self.expect_op(";")
        return ast.FBCall(ident.value, inputs, outputs, line=ident.line, col=ident.col)

    def parse_if(self) -> ast.If:
        start = self.expect_kw("IF")
        branches = []
        cond = self.parse_expr()
        self.expect_kw("THEN")
        branches.append((cond, self.parse_statements()))
        orelse: list[ast.Node] = []
        while True:
            if self.is_kw("ELSIF"):
                self.advance()
                cond = self.parse_expr()
                self.expect_kw("THEN")
                branches.append((cond, self.parse_statements()))
            elif self.is_kw("ELSE"):
                self.advance()
                orelse = self.parse_statements()
            else:
                break
        self.expect_kw("END_IF")
        self.optional_semicolon()
        return ast.If(branches, orelse, line=start.line, col=start.col)

    def parse_case_value(self) -> int:
        neg = False
        if self.is_op("-"):
            self.advance()
            neg = True
        t = self.tok
        if t.kind != "INT":
            raise self.error(f"Ganzzahl als CASE-Marke erwartet, gefunden {self.describe(t)}")
        self.advance()
        return -t.value if neg else t.value

    def parse_case(self) -> ast.Case:
        start = self.expect_kw("CASE")
        selector = self.parse_expr()
        self.expect_kw("OF")
        branches = []
        orelse: list[ast.Node] = []
        while not self.is_kw("END_CASE"):
            if self.is_kw("ELSE"):
                self.advance()
                orelse = self.parse_statements(case_body=True)
                continue
            labels = []
            while True:
                lt = self.tok
                low = self.parse_case_value()
                high = low
                if self.is_op(".."):
                    self.advance()
                    high = self.parse_case_value()
                labels.append(ast.CaseLabel(low, high, line=lt.line, col=lt.col))
                if self.is_op(","):
                    self.advance()
                    continue
                break
            self.expect_op(":")
            branches.append((labels, self.parse_statements(case_body=True)))
            if self.tok.kind == "EOF":
                raise self.error("END_CASE erwartet")
        self.expect_kw("END_CASE")
        self.optional_semicolon()
        return ast.Case(selector, branches, orelse, line=start.line, col=start.col)

    def parse_for(self) -> ast.For:
        start = self.expect_kw("FOR")
        v = self.expect_ident()
        self.expect_op(":=")
        begin = self.parse_expr()
        self.expect_kw("TO")
        end = self.parse_expr()
        step = None
        if self.is_kw("BY"):
            self.advance()
            step = self.parse_expr()
        self.expect_kw("DO")
        body = self.parse_statements()
        self.expect_kw("END_FOR")
        self.optional_semicolon()
        var = ast.Name(v.value, line=v.line, col=v.col)
        return ast.For(var, begin, end, step, body, line=start.line, col=start.col)

    def parse_while(self) -> ast.While:
        start = self.expect_kw("WHILE")
        cond = self.parse_expr()
        self.expect_kw("DO")
        body = self.parse_statements()
        self.expect_kw("END_WHILE")
        self.optional_semicolon()
        return ast.While(cond, body, line=start.line, col=start.col)

    def parse_repeat(self) -> ast.Repeat:
        start = self.expect_kw("REPEAT")
        body = self.parse_statements()
        self.expect_kw("UNTIL")
        cond = self.parse_expr()
        self.expect_kw("END_REPEAT")
        self.optional_semicolon()
        return ast.Repeat(body, cond, line=start.line, col=start.col)

    # ------------------------------------------------------------ expressions
    def _binary(self, sub, ops: set[str]):
        left = sub()
        while (self.tok.kind in ("OP", "KW")) and self.tok.value in ops:
            op_tok = self.advance()
            op = "AND" if op_tok.value == "&" else op_tok.value
            right = sub()
            left = ast.Binary(op, left, right, line=op_tok.line, col=op_tok.col)
        return left

    def parse_expr(self) -> ast.Node:
        return self._binary(self.parse_xor, {"OR"})

    def parse_xor(self):
        return self._binary(self.parse_and, {"XOR"})

    def parse_and(self):
        return self._binary(self.parse_eq, {"AND", "&"})

    def parse_eq(self):
        return self._binary(self.parse_rel, {"=", "<>"})

    def parse_rel(self):
        return self._binary(self.parse_add, {"<", ">", "<=", ">="})

    def parse_add(self):
        return self._binary(self.parse_mul, {"+", "-"})

    def parse_mul(self):
        return self._binary(self.parse_pow, {"*", "/", "MOD"})

    def parse_pow(self):
        return self._binary(self.parse_unary, {"**"})

    def parse_unary(self):
        t = self.tok
        if self.is_op("-"):
            self.advance()
            operand = self.parse_unary()
            if isinstance(operand, ast.Literal) and operand.type_name in ("ANY_INT", "ANY_REAL", "TIME"):
                operand.value = -operand.value
                return operand
            return ast.Unary("-", operand, line=t.line, col=t.col)
        if self.is_op("+"):
            self.advance()
            return self.parse_unary()
        if self.is_kw("NOT"):
            self.advance()
            return ast.Unary("NOT", self.parse_unary(), line=t.line, col=t.col)
        return self.parse_primary()

    def parse_primary(self) -> ast.Node:
        t = self.tok
        if t.kind == "INT":
            self.advance()
            return ast.Literal(t.value, "ANY_INT", line=t.line, col=t.col)
        if t.kind == "REAL":
            self.advance()
            return ast.Literal(t.value, "ANY_REAL", line=t.line, col=t.col)
        if t.kind == "TIME":
            self.advance()
            return ast.Literal(t.value, "TIME", line=t.line, col=t.col)
        if self.is_kw("TRUE", "FALSE"):
            self.advance()
            return ast.Literal(t.value == "TRUE", "BOOL", line=t.line, col=t.col)
        if t.kind == "TYPED":
            self.advance()
            neg = False
            if self.is_op("-"):
                self.advance()
                neg = True
            v = self.tok
            if v.kind in ("INT", "REAL"):
                self.advance()
                value = -v.value if neg else v.value
            elif v.kind == "KW" and v.value in ("TRUE", "FALSE") and not neg:
                self.advance()
                value = v.value == "TRUE"
            else:
                raise self.error(f"Wert nach '{t.text}' erwartet")
            return ast.Literal(value, t.value, line=t.line, col=t.col)
        if t.kind == "IDENT":
            self.advance()
            if self.is_op("("):
                self.advance()
                args: list[ast.Node] = []
                named: dict[str, ast.Node] = {}
                while not self.is_op(")"):
                    if self.tok.kind == "IDENT" and self.peek().kind == "OP" and self.peek().value == ":=":
                        pname = self.advance().value.upper()
                        self.advance()
                        named[pname] = self.parse_expr()
                    else:
                        if named:
                            raise self.error("Nach benannten Argumenten sind keine Positionsargumente erlaubt")
                        args.append(self.parse_expr())
                    if not self.is_op(")"):
                        self.expect_op(",")
                self.advance()
                return ast.Call(t.value.upper(), args, named, line=t.line, col=t.col)
            if self.is_op("["):
                self.advance()
                index = self.parse_expr()
                self.expect_op("]")
                return ast.Index(t.value, index, line=t.line, col=t.col)
            if self.is_op("."):
                self.advance()
                member = self.expect_ident()
                return ast.Member(t.value, member.value.upper(), line=t.line, col=t.col)
            return ast.Name(t.value, line=t.line, col=t.col)
        if self.is_op("("):
            self.advance()
            e = self.parse_expr()
            self.expect_op(")")
            return e
        raise self.error(f"Ausdruck erwartet, gefunden {self.describe(t)}")


def parse(source: str) -> ast.Program:
    return Parser(source).parse_source()
