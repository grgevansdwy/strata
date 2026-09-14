"""Python source -> nodes with byte spans, hashes, and raw references for edge building."""

import ast
import hashlib
import io
import tokenize
from dataclasses import dataclass, field

from strata.indexer.node_ids import module_id, symbol_id


@dataclass
class Node:
    id: str
    kind: str  # module | class | function | variable | import | block
    parent_id: str | None
    name: str
    file: str
    start_byte: int
    end_byte: int
    start_line: int  # 1-based, inclusive
    end_line: int
    indent: str
    ast_hash: str
    src_hash: str
    loc: int
    signature: str | None = None
    docstring: str | None = None
    ordinal: int = 0


@dataclass
class ImportBinding:
    """A local name bound by an import: `local` refers to `module` (dotted) or `module.symbol`."""

    local: str
    module: str  # absolute dotted module path as written (relative imports already resolved)
    symbol: str | None  # None for `import x` style bindings
    line: int
    node_id: str  # the node containing the import statement (an `import` node at module level)


@dataclass
class CallRef:
    """A call site or name reference inside a node, recorded syntactically; resolved later against the index."""

    src: str  # node id containing the call
    chain: list[str]  # e.g. ["self", "save"], ["db", "get_client"], ["helper"]
    line: int
    col: int  # column of the last name in the chain (for Jedi goto)
    enclosing_class: str | None  # qualname of the class if the call is inside a method
    is_call: bool = True  # False for a plain reference: `x = CONFIG`, `f(callback)`, `def g(c: Config)`


@dataclass
class ParsedFile:
    relpath: str
    nodes: list[Node]
    imports: list[ImportBinding] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)


def sha(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()[:16]


def dotted_module_name(relpath: str) -> str:
    parts = relpath[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def line_offsets(source: bytes) -> list[int]:
    """offsets[i] = byte offset where 1-based line i starts; offsets[n+1] = len(source)."""
    offsets = [0, 0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"


def _chain(expr: ast.expr) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; None if the expression isn't a pure dotted name."""
    chain = []
    while isinstance(expr, ast.Attribute):
        chain.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    chain.append(expr.id)
    return chain[::-1]


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _statement_kind(stmt: ast.stmt, in_class: bool) -> tuple[str, str] | None:
    """(kind, local name) for a statement that gets its own node, else None.

    At module level every statement is a node, so every line of a file belongs to some box. In a class
    body only assignments are (dataclass fields, class constants); methods are handled as functions.
    """
    targets = []
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
    if targets and all(isinstance(n, (ast.Name, ast.Tuple, ast.List, ast.Starred)) for t in targets for n in [t]):
        return "variable", ",".join(names)
    if in_class:
        return None
    if isinstance(stmt, ast.Import):
        return "import", "import:" + ",".join(a.name for a in stmt.names).replace(".", "/")
    if isinstance(stmt, ast.ImportFrom):
        return "import", "import:" + ("." * stmt.level + (stmt.module or "")).replace(".", "/")
    if (
        isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.Compare)
        and ast.unparse(stmt.test).replace("'", '"') == '__name__ == "__main__"'
    ):
        return "block", "__main__"
    return "block", "block"


def parse_file(relpath: str, source: bytes) -> ParsedFile:
    """Raises SyntaxError if the file does not parse."""
    tree = ast.parse(source, filename=relpath)
    offsets = line_offsets(source)
    lines = source.splitlines(keepends=True)
    total_lines = len(lines)
    mod_id = module_id(relpath)
    doc = ast.get_docstring(tree)
    nodes = [
        Node(
            id=mod_id,
            kind="module",
            parent_id=None,  # filled in by the indexer (parent dir)
            name=relpath.rsplit("/", 1)[-1],
            file=relpath,
            start_byte=0,
            end_byte=len(source),
            start_line=1,
            end_line=max(total_lines, 1),
            indent="",
            ast_hash=sha(ast.dump(tree)),
            src_hash=sha(source),
            loc=total_lines,
            docstring=doc.strip().split("\n")[0] if doc else None,
        )
    ]
    parsed = ParsedFile(relpath=relpath, nodes=nodes)
    package = dotted_module_name(relpath)
    if not relpath.endswith("__init__.py"):
        package = package.rpartition(".")[0]

    def add_node(child, kind: str, local: str, parent_id: str, qual: str, used: dict, signature, docstring) -> Node:
        n = used.get(local, 0) + 1
        used[local] = n
        local = local if n == 1 else f"{local}@{n}"
        child_qual = f"{qual}.{local}" if qual else local
        start_line = child.decorator_list[0].lineno if getattr(child, "decorator_list", None) else child.lineno
        end_line = child.end_lineno
        start_b, end_b = offsets[start_line], offsets[end_line + 1]
        span = source[start_b:end_b]
        first = lines[start_line - 1]
        indent = first[: len(first) - len(first.lstrip())].decode()
        node = Node(
            id=symbol_id(relpath, child_qual),
            kind=kind,
            parent_id=parent_id,
            name=local,
            file=relpath,
            start_byte=start_b,
            end_byte=end_b,
            start_line=start_line,
            end_line=end_line,
            indent=indent,
            ast_hash=sha(ast.dump(child)),
            src_hash=sha(span),
            loc=end_line - start_line + 1,
            signature=signature,
            docstring=docstring,
            ordinal=len(nodes),
        )
        nodes.append(node)
        return node

    def visit(ast_node: ast.AST, parent_id: str, qual: str, enclosing_class: str | None, used: dict):
        """Walk a module, class or function body. `parent_id`/`qual`/`used` describe that scope."""
        in_body = isinstance(ast_node, (ast.Module, ast.ClassDef))
        for child in ast.iter_child_nodes(ast_node):
            if in_body and isinstance(child, ast.stmt) and not _is_docstring(child) and not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) and (found := _statement_kind(child, isinstance(ast_node, ast.ClassDef))):
                kind, local = found
                first_line = lines[child.lineno - 1].decode("utf-8", errors="replace").strip()
                node = add_node(child, kind, local, parent_id, qual, used, first_line[:160], None)
                visit_expr(child, node.id, parent_id, qual, enclosing_class, used)
            else:
                visit_expr(child, parent_id, parent_id, qual, enclosing_class, used)

    def visit_expr(child: ast.AST, src: str, parent_id: str, qual: str, enclosing_class: str | None, used: dict):
        """Record calls, references and imports under `src`. Defs found here still belong to the scope."""
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(child)
            is_class = isinstance(child, ast.ClassDef)
            node = add_node(
                child, "class" if is_class else "function", child.name, parent_id, qual, used,
                _signature(child), doc.strip().split("\n")[0] if doc else None,
            )
            child_qual = node.id.partition("#")[2]
            visit(child, node.id, child_qual, child_qual if is_class else enclosing_class, {})
            return
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            _record_import(child, src)
        if isinstance(child, ast.Call) and (chain := _chain(child.func)):
            _record_ref(chain, child.func, src, enclosing_class, True)
            for sub in ast.iter_child_nodes(child):
                if sub is not child.func:
                    visit_expr(sub, src, parent_id, qual, enclosing_class, used)
            return
        if isinstance(child, (ast.Name, ast.Attribute)) and isinstance(child.ctx, ast.Load) and (chain := _chain(child)):
            if chain not in (["self"], ["cls"]):
                _record_ref(chain, child, src, enclosing_class, False)
            return
        for sub in ast.iter_child_nodes(child):
            visit_expr(sub, src, parent_id, qual, enclosing_class, used)

    def _record_ref(chain: list[str], expr: ast.expr, src: str, enclosing_class: str | None, is_call: bool):
        # Column of the last identifier, so Jedi's goto lands on the target name.
        col = expr.end_col_offset - len(chain[-1])
        parsed.calls.append(CallRef(src, chain, expr.end_lineno, col, enclosing_class, is_call))

    def _record_import(stmt: ast.Import | ast.ImportFrom, node_id: str):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    parsed.imports.append(ImportBinding(alias.asname, alias.name, None, stmt.lineno, node_id))
                    continue
                # `import a.b` binds `a`, and makes `a.b` reachable as a dotted chain.
                parts = alias.name.split(".")
                for i in range(1, len(parts) + 1):
                    dotted = ".".join(parts[:i])
                    parsed.imports.append(ImportBinding(dotted, dotted, None, stmt.lineno, node_id))
            return
        base = stmt.module or ""
        if stmt.level:
            pkg_parts = package.split(".") if package else []
            keep = len(pkg_parts) - (stmt.level - 1)
            prefix = ".".join(pkg_parts[: max(keep, 0)])
            base = f"{prefix}.{base}".strip(".") if base else prefix
        for alias in stmt.names:
            if alias.name == "*":
                continue
            parsed.imports.append(ImportBinding(alias.asname or alias.name, base, alias.name, stmt.lineno, node_id))

    visit(tree, mod_id, "", None, {})
    return parsed


def protected_lines(source: str) -> set[int]:
    """1-based line numbers that begin *inside* a multi-line string or f-string.

    Their leading whitespace is string content, so dedent/re-indent must not touch them.
    """
    protected: set[int] = set()
    fstring_starts: list[int] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:
                protected.update(range(tok.start[0] + 1, tok.end[0] + 1))
            elif tok.type == getattr(tokenize, "FSTRING_START", -1):
                fstring_starts.append(tok.start[0])
            elif tok.type == getattr(tokenize, "FSTRING_END", -1) and fstring_starts:
                start = fstring_starts.pop()
                if not fstring_starts and tok.end[0] > start:
                    protected.update(range(start + 1, tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return protected
