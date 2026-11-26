"""Error types raised while compiling or executing Structured Text."""

from __future__ import annotations


class STError(Exception):
    """Base class with optional source position."""

    def __init__(self, message: str, line: int | None = None, col: int | None = None):
        self.message = message
        self.line = line
        self.col = col
        where = f" (Zeile {line}, Spalte {col})" if line is not None else ""
        super().__init__(message + where)

    def to_dict(self) -> dict:
        return {"message": self.message, "line": self.line, "col": self.col}


class STSyntaxError(STError):
    """Invalid source text (lexer or parser)."""


class STSemanticError(STError):
    """Valid syntax, but undefined names, wrong types etc."""


class PLCRuntimeError(STError):
    """Error during a scan cycle; puts the PLC into STOP like a real CPU."""


class STCompileError(STError):
    """One or more errors found while compiling a program."""

    def __init__(self, errors: list[STError]):
        self.errors = errors
        first = errors[0]
        super().__init__(first.message, first.line, first.col)
        if len(errors) > 1:
            self.args = (f"{self} (+{len(errors) - 1} weitere Fehler)",)
