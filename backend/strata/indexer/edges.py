"""Inferred edges straight from the AST: import graph + call sites matched against the index.

Everything here is syntactic. Dynamic dispatch, getattr, DI etc. are invisible, which is why these
edges are labeled `inferred` and the Jedi pass (resolver.py) upgrades what it can confirm.
"""

from collections import defaultdict

from strata.indexer.ast_parser import ParsedFile, dotted_module_name
from strata.indexer.node_ids import module_id, symbol_id

Edge = tuple[str, str, str, str, str]  # src, dst, kind, tier, src_file


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.split("/"), b.split("/")):
        if x != y:
            break
        n += 1
    return n


class ModuleResolver:
    """Maps dotted import paths to indexed files, tolerating unknown sys.path roots.

    `from app.db import x` inside services/api/app/main.py matches services/api/app/db.py because
    `app.db` is a dotted suffix of `services.api.app.db`. Ties go to the file nearest the importer.
    """

    def __init__(self, relpaths):
        self.by_suffix: dict[str, list[str]] = defaultdict(list)
        for rel in relpaths:
            parts = dotted_module_name(rel).split(".")
            for i in range(len(parts)):
                self.by_suffix[".".join(parts[i:])].append(rel)

    def resolve(self, dotted: str, from_rel: str) -> str | None:
        cands = self.by_suffix.get(dotted)
        if not cands:
            return None
        return max(cands, key=lambda rel: (_common_prefix_len(rel, from_rel), -len(rel)))


def build_inferred_edges(parsed: dict[str, ParsedFile]) -> list[Edge]:
    resolver = ModuleResolver(parsed)
    known_ids = {n.id for pf in parsed.values() for n in pf.nodes}
    kinds = {n.id: n.kind for pf in parsed.values() for n in pf.nodes}
    edges: set[Edge] = set()

    for rel, pf in parsed.items():
        src_mod = module_id(rel)
        # A class or function points at what it defines: fields, methods, nested functions.
        for n in pf.nodes:
            if kinds.get(n.parent_id) in ("class", "function"):
                edges.add((n.parent_id, n.id, "member", "inferred", rel))
        # Names bound by a module-level import statement; the fallback target for anything external.
        import_nodes = {b.local: b.node_id for b in pf.imports if kinds.get(b.node_id) == "import"}
        # local name -> ("module", relpath) | ("symbol", node_id)
        bindings: dict[str, tuple[str, str]] = {}
        for b in pf.imports:
            if b.symbol is None:
                target = resolver.resolve(b.module, rel)
                if target:
                    bindings[b.local] = ("module", target)
                    _add_import(edges, src_mod, target, rel)
                continue
            sub = resolver.resolve(f"{b.module}.{b.symbol}" if b.module else b.symbol, rel)
            if sub and sub != rel:
                bindings[b.local] = ("module", sub)
                _add_import(edges, src_mod, sub, rel)
                continue
            target = resolver.resolve(b.module, rel) if b.module else None
            if target:
                _add_import(edges, src_mod, target, rel)
                sid = symbol_id(target, b.symbol)
                if sid in known_ids:
                    bindings[b.local] = ("symbol", sid)

        for call in pf.calls:
            dst = _resolve_call(call, rel, bindings, known_ids, kinds) or import_nodes.get(call.chain[0])
            if dst and dst != call.src and kinds.get(dst) != "module":
                kind = "call" if call.is_call and kinds.get(dst) in ("function", "class") else "uses"
                edges.add((call.src, dst, kind, "inferred", rel))
    return sorted(edges)


def _add_import(edges: set, src_mod: str, target_rel: str, rel: str):
    dst = module_id(target_rel)
    if dst != src_mod:
        edges.add((src_mod, dst, "import", "inferred", rel))


def _member(owner_id: str, rest: list[str], known_ids: set, kinds: dict) -> str | None:
    """Follow `Class.method` style attribute chains from a class or module node."""
    node = owner_id
    for attr in rest:
        if kinds.get(node) == "module":
            cand = node + "#" + attr
        elif kinds.get(node) == "class":
            cand = node + "." + attr
        else:
            return None
        if cand not in known_ids:
            return None
        node = cand
    return node


def _resolve_call(call, rel, bindings, known_ids, kinds) -> str | None:
    chain = call.chain
    if chain[0] in ("self", "cls") and call.enclosing_class and len(chain) >= 2:
        cand = symbol_id(rel, f"{call.enclosing_class}.{chain[1]}")
        return cand if cand in known_ids else None

    # Lexical scope: nested defs, then enclosing classes' siblings, then module top level.
    src_qual = call.src.partition("#")[2]
    scope = src_qual.split(".") if src_qual else []
    for depth in range(len(scope), -1, -1):
        base = ".".join(scope[:depth] + [chain[0]])
        cand = symbol_id(rel, base)
        if cand in known_ids:
            # `CONFIG.url`, `Config.from_env()`: an unknown attribute still points at the owner.
            return (_member(cand, chain[1:], known_ids, kinds) or cand) if len(chain) > 1 else cand

    # Imported names: longest dotted prefix that is bound (handles `import a.b; a.b.f()`).
    for k in range(len(chain), 0, -1):
        binding = bindings.get(".".join(chain[:k]))
        if not binding:
            continue
        kind, target = binding
        rest = chain[k:]
        owner = module_id(target) if kind == "module" else target
        if not rest:
            return owner if kind == "symbol" else None
        return _member(owner, rest, known_ids, kinds) or (owner if kind == "symbol" else None)
    return None
