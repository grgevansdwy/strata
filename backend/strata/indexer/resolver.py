"""Background Jedi pass: confirms call targets across files and records them as `resolved` edges."""

import logging
from pathlib import Path

import jedi

from strata.indexer.repo_index import RepoIndex

log = logging.getLogger("strata.resolver")


def _project(root: Path) -> jedi.Project:
    # Monorepos keep packages under sub-roots (services/api/app); treat any dir with a
    # pyproject.toml as a sys.path entry so `from app.db import x` resolves.
    extra = sorted({str(p.parent) for p in root.rglob("pyproject.toml") if "node_modules" not in p.parts})
    return jedi.Project(str(root), added_sys_path=extra, smart_sys_path=True)


def resolve_file(index: RepoIndex, rel: str, project: jedi.Project | None = None) -> int:
    """Replace resolved edges originating in `rel`. Returns the number of edges written."""
    pf = index.parsed.get(rel)
    if pf is None:
        index.db.replace_edges("resolved", [], src_file=rel)
        return 0
    project = project or _project(index.root)
    path = index.root / rel
    script = jedi.Script(path.read_text(), path=str(path), project=project)
    edges = set()
    for call in pf.calls:
        try:
            defs = script.goto(call.line, call.col, follow_imports=True)
        except Exception:  # Jedi raises on odd corners of the language; an unresolved edge is fine.
            continue
        for d in defs:
            if d.module_path is None or d.line is None:
                continue
            try:
                target_rel = Path(d.module_path).resolve().relative_to(index.root).as_posix()
            except ValueError:
                continue  # stdlib / site-packages
            dst = _node_at(index, target_rel, d.name, d.line)
            if dst and dst != call.src:
                edges.add((call.src, dst, "call", "resolved", rel))
    index.db.replace_edges("resolved", sorted(edges), src_file=rel)
    return len(edges)


def _node_at(index: RepoIndex, rel: str, name: str, line: int) -> str | None:
    best = None
    for n in index.db.file_nodes(rel):
        if n["kind"] not in ("class", "function") or n["name"].split("@")[0] != name:
            continue
        if n["start_line"] <= line <= n["end_line"]:
            if best is None or n["loc"] < best["loc"]:
                best = n
    return best["id"] if best else None


def resolve_all(index: RepoIndex) -> int:
    project = _project(index.root)
    total = 0
    for rel in list(index.parsed):
        total += resolve_file(index, rel, project)
    log.info("jedi resolved %d call edges", total)
    return total
