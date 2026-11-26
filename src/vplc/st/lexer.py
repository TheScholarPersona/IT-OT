"""Tokenizer for IEC 61131-3 Structured Text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import STSyntaxError

KEYWORDS = {
    "PROGRAM", "END_PROGRAM", "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
    "VAR_TEMP", "END_VAR", "CONSTANT", "RETAIN",
    "IF", "THEN", "ELSIF", "ELSE", "END_IF",
    "CASE", "OF", "END_CASE",
    "FOR", "TO", "BY", "DO", "END_FOR",
    "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT",
    "EXIT", "RETURN", "CONTINUE",
    "AND", "OR", "XOR", "NOT", "MOD",
    "TRUE", "FALSE",
}

TIME_UNITS = {"D": 86_400_000, "H": 3_600_000, "M": 60_000, "S": 1000, "MS": 1}


@dataclass
class Token:
    kind: str  # IDENT, KW, INT, REAL, TIME, OP, EOF
    value: object
    line: int
    col: int
    text: str = ""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<comment>\(\*.*?\*\)|//[^\n]*)
  | (?P<time>(?i:TIME|T)\#-?[0-9_.a-zA-Z]+)
  | (?P<based>(?:2|8|16)\#[0-9a-fA-F_]+)
  | (?P<typed>[A-Za-z_][A-Za-z0-9_]*\#)
  | (?P<real>[0-9][0-9_]*\.[0-9][0-9_]*(?:[eE][+-]?[0-9]+)?|[0-9][0-9_]*[eE][+-]?[0-9]+)
  | (?P<int>[0-9][0-9_]*)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>:=|=>|<=|>=|<>|\*\*|\.\.|[-+*/=<>&();:,.\[\]])
    """,
    re.VERBOSE | re.DOTALL,
)

_TIME_PART_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(MS|D|H|M|S)", re.IGNORECASE)


def parse_time_literal(text: str, line: int, col: int) -> int:
    body = text.split("#", 1)[1].replace("_", "")
    sign = 1
    if body.startswith("-"):
        sign, body = -1, body[1:]
    pos, total = 0, 0.0
    while pos < len(body):
        m = _TIME_PART_RE.match(body, pos)
        if not m:
            raise STSyntaxError(f"Ungültiges Zeitliteral '{text}'", line, col)
        total += float(m.group(1)) * TIME_UNITS[m.group(2).upper()]
        pos = m.end()
    if not body:
        raise STSyntaxError(f"Ungültiges Zeitliteral '{text}'", line, col)
    return sign * int(round(total))


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    pos, line, line_start = 0, 1, 0
    n = len(source)
    while pos < n:
        m = _TOKEN_RE.match(source, pos)
        col = pos - line_start + 1
        if not m:
            if source.startswith("(*", pos):
                raise STSyntaxError("Kommentar wird nicht geschlossen", line, col)
            raise STSyntaxError(f"Unerwartetes Zeichen '{source[pos]}'", line, col)
        kind = m.lastgroup
        text = m.group()
        if kind == "time":
            tokens.append(Token("TIME", parse_time_literal(text, line, col), line, col, text))
        elif kind == "based":
            base, digits = text.split("#")
            try:
                value = int(digits.replace("_", ""), int(base))
            except ValueError:
                raise STSyntaxError(f"Ungültige Zahl '{text}'", line, col) from None
            tokens.append(Token("INT", value, line, col, text))
        elif kind == "typed":
            tokens.append(Token("TYPED", text[:-1].upper(), line, col, text))
        elif kind == "real":
            tokens.append(Token("REAL", float(text.replace("_", "")), line, col, text))
        elif kind == "int":
            tokens.append(Token("INT", int(text.replace("_", "")), line, col, text))
        elif kind == "ident":
            upper = text.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KW", upper, line, col, text))
            else:
                tokens.append(Token("IDENT", text, line, col, text))
        elif kind == "op":
            tokens.append(Token("OP", text, line, col, text))
        # whitespace / comments: just advance, but keep line counting
        newlines = text.count("\n")
        if newlines:
            line += newlines
            line_start = pos + text.rfind("\n") + 1
        pos = m.end()
    tokens.append(Token("EOF", None, line, pos - line_start + 1))
    return tokens
