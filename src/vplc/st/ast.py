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
class Index(Node):
    """Array element access: name[index] (kept for compatibility; the parser emits Path)."""

    name: str
    index: Node


@dataclass
class Path(Node):
    """Access path: base followed by fields and indices, e.g. Lager[i].Menge or Motor.Q.

    steps: ("field", UPPER_NAME, declared_name) | ("index", expression, None)
    """

    base: str
    steps: list[tuple[str, object, object]]


@dataclass
class ArrayInit(Node):
    """Initial values of an array: [1, 2, 3(0)] -> items [(None, 1), (None, 2), (3, 0)]."""

    items: list[tuple[Node | None, Node]]


@dataclass
class Call(Node):
    func: str
    args: list[Node]
    named: dict[str, Node] = field(default_factory=dict)  # upper-case input name -> expression


# ---------------------------------------------------------------- statements
@dataclass
class Assign(Node):
    target: Name | Path
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
    dims: tuple[Node, Node] | None = None  # ARRAY[low..high] OF type_name


@dataclass
class TypeDecl(Node):
    """TYPE Name : STRUCT … END_STRUCT; END_TYPE"""

    name: str
    fields: list[VarDecl]


@dataclass
class FunctionBlockDecl(Node):
    name: str
    decls: list[VarDecl]
    body: list[Node]


@dataclass
class FunctionDecl(Node):
    name: str
    return_type: str
    decls: list[VarDecl]
    body: list[Node]


@dataclass
class Program(Node):
    name: str
    decls: list[VarDecl]
    body: list[Node]
    function_blocks: list[FunctionBlockDecl] = field(default_factory=list)
    types: list[TypeDecl] = field(default_factory=list)
    functions: list[FunctionDecl] = field(default_factory=list)
