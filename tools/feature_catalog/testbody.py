"""Static look at a test body: does the test exist, assert something, touch the feature?

Heuristics only – they support the review (rule N7), they do not replace it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class TestBody:
    found: bool
    text: str = ""  # body plus same-file helpers/fixtures it uses
    own_text: str = ""  # body only
    line: int = 0
    has_assertion: bool = False
    status_only: bool = False


_STATUS_ONLY_PY = re.compile(
    r"^(?:\S+\.status_code\s*==\s*\d+|\S+\s+is\s+not\s+None|\S+\.ok|True)$")


# ------------------------------------------------------------------ Python
@lru_cache(maxsize=None)
def _py_module(path: str):
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    return source, tree, funcs, classes


def _assertions_py(func: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            out.append(ast.unparse(node.test))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                text = ast.unparse(item.context_expr)
                if "raises" in text:
                    out.append(text)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr.startswith("assert"):
            out.append(ast.unparse(node))
    return out


def python_test(path: Path, test: str) -> TestBody:
    if not path.exists():
        return TestBody(False)
    source, tree, funcs, classes = _py_module(str(path))
    cls_name, _, func_name = test.rpartition("::")
    if cls_name:
        cls = classes.get(cls_name)
        func = next((n for n in (cls.body if cls else [])
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
    else:
        func = next((n for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
    if func is None:
        return TestBody(False)
    own = ast.get_source_segment(source, func) or ""
    # Same-file helpers and fixtures the test uses (called names, parameters)
    used = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}
    used |= {a.arg for a in func.args.args}
    texts, seen, queue = [own], {func.name}, list(used)
    while queue:
        name = queue.pop()
        helper = funcs.get(name)
        if helper is None or name in seen or name.startswith("test_"):
            continue
        seen.add(name)
        texts.append(ast.get_source_segment(source, helper) or "")
        queue.extend(n.id for n in ast.walk(helper) if isinstance(n, ast.Name))
        queue.extend(a.arg for a in helper.args.args)
    asserts = _assertions_py(func)  # only the test's own assertions count (N4)
    status_only = bool(asserts) and all(_STATUS_ONLY_PY.match(a.strip()) for a in asserts)
    return TestBody(True, "\n".join(texts), own, func.lineno, bool(asserts), status_only)


# ------------------------------------------------------------------ JavaScript (mocha)
_JS_ASSERT = re.compile(r"\bassert(?:\.\w+)?\s*\(|\bexpect\s*\(|\.should\b")
_JS_STATUS_ONLY = re.compile(r"assert\.(?:ok|strictEqual)\(\s*[\w.]*status(?:Code)?\b")


def _js_block(text: str, start: int) -> str:
    """Text from *start* to the matching closing brace of the first '{'."""
    i = text.find("{", start)
    if i < 0:
        return ""
    depth, j, quote = 0, i, None
    while j < len(text):
        ch = text[j]
        if quote:
            if ch == "\\":
                j += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
        j += 1
    return text[start:]


def js_test(path: Path, title: str) -> TestBody:
    if not path.exists():
        return TestBody(False)
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\bit\(\s*([\"'`])" + re.escape(title) + r"\1", text)
    if not m:
        return TestBody(False)
    body = _js_block(text, m.start())
    asserts = _JS_ASSERT.findall(body)
    status_only = bool(asserts) and all(_JS_STATUS_ONLY.search(line) for line in body.splitlines()
                                        if _JS_ASSERT.search(line))
    # helpers: top-level const/function definitions referenced by the body
    helpers = []
    for hm in re.finditer(r"^\s*(?:const|function|let)\s+(\w+)", text, re.M):
        if re.search(r"\b" + hm.group(1) + r"\b", body) and hm.start() < m.start():
            helpers.append(text[hm.start():hm.start() + 600])
    return TestBody(True, body + "\n" + "\n".join(helpers), body,
                    text.count("\n", 0, m.start()) + 1, bool(asserts), status_only)


def read_test(root: Path, file: str, test: str) -> TestBody:
    path = Path(root) / file
    if file.endswith(".py"):
        return python_test(path, test)
    return js_test(path, test)


# ------------------------------------------------------------------ feature terms
@lru_cache(maxsize=None)
def component_terms(path: str) -> frozenset[str]:
    """Names a test would use to touch a component: public top-level names, module stem."""
    p = Path(path)
    terms = {p.stem} if len(p.stem) > 3 else set()
    if not p.exists():
        return frozenset(terms)
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".py":
        tree = ast.parse(text)
        for node in tree.body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for n in names:
                if len(n) > 3 and not n.startswith("_"):
                    terms.add(n)
            if isinstance(node, ast.ClassDef):  # public methods are used by tests too
                terms.update(f.name for f in node.body
                             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and not f.name.startswith("_") and len(f.name) > 3)
    elif p.suffix == ".js":
        terms.update(re.findall(r"registerType\(\s*[\"']([^\"']+)", text))
    return frozenset(terms)


def endpoint_terms(endpoint: str) -> set[str]:
    """Static path segments that identify an endpoint in a test ('/versions', 'stream')."""
    path = endpoint.split(" ", 1)[-1]
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return {"/" + segments[-1]} if segments else set()


def touches(body: str, terms: set[str]) -> bool:
    for t in terms:
        if t.startswith("/"):
            if re.search(re.escape(t) + r"(?![\w-])", body):
                return True
        elif re.search(r"(?<![\w])" + re.escape(t) + r"(?![\w])", body):
            return True
    return False


# ------------------------------------------------------------------ review support (N7)
def review_lines(root: Path, file: str, test: str, terms: set[str],
                 code: str | None = None) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(action lines, assertion lines) of a test, each as (line number, source text)."""
    path = Path(root) / file
    if not path.exists():
        return [], []
    lines = path.read_text(encoding="utf-8").splitlines()
    if file.endswith(".py"):
        source, tree, funcs, classes = _py_module(str(path))
        cls_name, _, func_name = test.rpartition("::")
        scope = classes[cls_name].body if cls_name and cls_name in classes else tree.body
        func = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
        if func is None:
            return [], []
        start, end = func.lineno, func.end_lineno
        asserts = sorted({n.lineno for n in ast.walk(func)
                          if isinstance(n, ast.Assert)
                          or (isinstance(n, (ast.With, ast.AsyncWith)) and "raises" in ast.unparse(n.items[0].context_expr))})
    else:
        body = js_test(path, test)
        if not body.found:
            return [], []
        start, end = body.line, body.line + body.own_text.count("\n")
        asserts = [i for i in range(start, end + 1) if _JS_ASSERT.search(lines[i - 1])]
    actions = [i for i in range(start + 1, end + 1)
               if i not in asserts and touches(lines[i - 1], terms)]
    if code:  # assertions on the rule's error code first
        asserts = sorted(asserts, key=lambda i: code not in lines[i - 1])
    return ([(i, lines[i - 1].strip()) for i in actions[:2]],
            [(i, lines[i - 1].strip()) for i in asserts[:3]])
