"""The whole repo as one graph: every class/function/variable/import/block is a box, edges are lines.

Roots are what nothing else points at, ranked so real entry points (`__main__`, pyproject scripts,
web routes) come first and the functions that reach the most code come next.
"""

import re
import tomllib
from collections import defaultdict, deque

from strata.indexer.edges import ModuleResolver
from strata.indexer.node_ids import symbol_id
from strata.indexer.repo_index import RepoIndex, is_indexable

GRAPH_KINDS = ("class", "function", "variable", "import", "block")
EDGE_RANK = {"call": 0, "uses": 1, "member": 2}  # one line per pair; the strongest relation labels it
# `@app.get(...)`, `@router.post`, `@click.command()`, `@celery.task`: a framework calls these.
ENTRY_DECORATOR = re.compile(
    r"^\s*@[\w.]*\b(get|post|put|patch|delete|head|options|route|api_route|websocket|command|group|task|"
    r"on_event|exception_handler|middleware|listener|callback|handler)\b"
)


def is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or "test" in parts[:-1] or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def script_targets(index: RepoIndex) -> set[str]:
    """Node ids named by `[project.scripts]` / `[tool.poetry.scripts]` in any pyproject.toml."""
    resolver = ModuleResolver(index.parsed)
    found = set()
    for path in index.root.rglob("pyproject.toml"):
        rel_dir = path.parent.relative_to(index.root).as_posix()
        if not is_indexable(f"{rel_dir}/x.py" if rel_dir != "." else "x.py"):
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            continue
        scripts = {**data.get("project", {}).get("scripts", {}), **data.get("tool", {}).get("poetry", {}).get("scripts", {})}
        for target in scripts.values():
            if not isinstance(target, str) or ":" not in target:
                continue
            module, _, attr = target.partition(":")
            rel = resolver.resolve(module.strip(), f"{rel_dir}/x.py")
            if rel:
                found.add(symbol_id(rel, attr.strip()))
    return found


def build_graph(index: RepoIndex) -> dict:
    nodes = {n["id"]: n for n in index.db.all_nodes() if n["kind"] in GRAPH_KINDS}
    pairs: dict[tuple[str, str], dict] = {}
    for e in index.db.graph_edges():
        if e["src"] not in nodes or e["dst"] not in nodes:
            continue
        key = (e["src"], e["dst"])
        best = pairs.get(key)
        if best is None or (EDGE_RANK[e["kind"]], e["tier"] != "resolved") < (EDGE_RANK[best["kind"]], best["tier"] != "resolved"):
            pairs[key] = e
    edges = list(pairs.values())
    out = defaultdict(set)
    incoming = set()
    for e in edges:
        out[e["src"]].add(e["dst"])
        incoming.add(e["dst"])

    scripts = script_targets(index) & nodes.keys()
    entry, functions, tests, other = [], [], [], []
    for nid, n in nodes.items():
        if n["kind"] == "block" and n["name"] == "__main__":
            entry.append(nid)
        elif nid in scripts:
            entry.append(nid)  # an entry point even if something (like a __main__ block) also calls it
        elif nid in incoming or n["kind"] == "import":  # an import nobody uses by name isn't worth a root
            continue
        elif is_test_file(n["file"]):
            tests.append(nid)
        elif n["kind"] == "function" and _decorated_as_entry(index, n):
            entry.append(nid)
        elif n["kind"] == "function":
            functions.append(nid)
        else:
            other.append(nid)

    reach = {nid: _reach(nid, out) for nid in entry + functions}
    by_place = lambda nid: (nodes[nid]["file"], nodes[nid]["start_line"])
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "roots": {
            "entry": sorted(entry, key=lambda nid: (-reach[nid], by_place(nid))),
            "functions": sorted(functions, key=lambda nid: (-reach[nid], by_place(nid))),
            "tests": sorted(tests, key=by_place),
            "other": sorted(other, key=by_place),
        },
    }


def _decorated_as_entry(index: RepoIndex, node: dict) -> bool:
    parsed = index.parsed.get(node["file"])
    if parsed is None:
        return False
    source = (index.root / node["file"]).read_bytes()[node["start_byte"] : node["end_byte"]].decode("utf-8", "replace")
    decorators = []
    for line in source.splitlines():
        if not line.lstrip().startswith("@"):
            break
        decorators.append(line)
    return any(ENTRY_DECORATOR.match(d) for d in decorators)


def _reach(start: str, out: dict[str, set[str]]) -> int:
    seen, queue = {start}, deque([start])
    while queue:
        for nxt in out[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return len(seen) - 1
