"""AST node definitions for Structured Text."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


# ---------------------------------------------------------------- expressions
@dataclass
class Literal(Node):
    value: object
    type_name: str  # ANY_INT / ANY_REAL (untyped), BOOL, TIME or explicit type (INT#5)


@dataclass
class Name(Node):
    name: str


@dataclass
class Member(Node):
    obj: str  # FB instance name
    member: str


@dataclass
class Unary(Node):
    op: str  # "-", "NOT"
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Call(Node):
    func: str
    args: list[Node]


# ---------------------------------------------------------------- statements
@dataclass
class Assign(Node):
    target: Name
    value: Node


@dataclass
class FBCall(Node):
    instance: str
    inputs: dict[str, Node]  # upper-case input name -> expression
    outputs: dict[str, Name]  # upper-case output name -> target variable (=>)


@dataclass
class If(Node):
    branches: list[tuple[Node, list[Node]]]
    orelse: list[Node]


@dataclass
class CaseLabel(Node):
    low: int
    high: int


@dataclass
class Case(Node):
    selector: Node
    branches: list[tuple[list[CaseLabel], list[Node]]]
    orelse: list[Node]


@dataclass
class For(Node):
    var: Name
    start: Node
    end: Node
    step: Node | None
    body: list[Node]


@dataclass
class While(Node):
    cond: Node
    body: list[Node]


@dataclass
class Repeat(Node):
    body: list[Node]
    cond: Node


@dataclass
class Exit(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class Return(Node):
    pass


# ---------------------------------------------------------------- declarations
@dataclass
class VarDecl(Node):
    name: str
    type_name: str
    section: str  # VAR, VAR_INPUT, VAR_OUTPUT, VAR_TEMP
    init: Node | None = None
    constant: bool = False
    retain: bool = False


@dataclass
class Program(Node):
    name: str
    decls: list[VarDecl]
    body: list[Node]
