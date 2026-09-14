"""Owns the parsed view of a repo and keeps SQLite in sync with it, one file at a time."""

import hashlib
import threading
from dataclasses import asdict
from pathlib import Path

from strata.db.queries import DB
from strata.indexer.ast_parser import ParsedFile, parse_file, sha
from strata.indexer.edges import build_inferred_edges
from strata.indexer.node_ids import ROOT_ID, dir_id, module_id, parent_dir_id

IGNORED_DIRS = {"node_modules", "venv", "__pycache__", "site-packages", "build", "dist"}


def is_indexable(rel: str) -> bool:
    parts = rel.split("/")
    if not rel.endswith(".py"):
        return False
    return not any(p in IGNORED_DIRS or p.startswith(".") for p in parts[:-1]) and not parts[-1].startswith(".")


class RepoIndex:
    def __init__(self, root: Path, db: DB):
        self.root = root.resolve()
        self.db = db
        self.parsed: dict[str, ParsedFile] = {}
        self.errors: dict[str, str] = {}  # relpath -> syntax error message (old nodes are kept)
        self.lock = threading.RLock()

    def scan(self) -> list[str]:
        rels = []
        for path in self.root.rglob("*.py"):
            rel = path.relative_to(self.root).as_posix()
            if is_indexable(rel) and path.is_file():
                rels.append(rel)
        return sorted(rels)

    def index_all(self):
        with self.lock:
            stale = set(self.db.files()) - set(self.scan())
            for rel in stale:
                self.db.remove_file(rel)
            for rel in self.scan():
                self._index_file(rel)
            self._rebuild_dirs()
            self._rebuild_edges()

    def reindex_file(self, rel: str) -> dict:
        """Re-parse one file. Returns {added, removed, changed} node ids."""
        with self.lock:
            before = self._snapshot()
            path = self.root / rel
            if path.is_file() and is_indexable(rel):
                self._index_file(rel)
            else:
                self.parsed.pop(rel, None)
                self.errors.pop(rel, None)
                self.db.remove_file(rel)
            self._rebuild_dirs()
            self._rebuild_edges()
            after = self._snapshot()
        return {
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": sorted(k for k in after.keys() & before.keys() if after[k] != before[k]),
        }

    def _snapshot(self) -> dict[str, tuple]:
        return {n["id"]: (n["ast_hash"], n["src_hash"], n["parent_id"]) for n in self.db.all_nodes()}

    def _index_file(self, rel: str):
        path = self.root / rel
        source = path.read_bytes()
        try:
            pf = parse_file(rel, source)
        except (SyntaxError, ValueError) as e:
            # Keep the last good nodes: a half-saved file must not wipe the dashboard.
            self.errors[rel] = f"{type(e).__name__}: {e}"
            return
        self.errors.pop(rel, None)
        self.parsed[rel] = pf
        rows = []
        for n in pf.nodes:
            row = asdict(n)
            if n.kind == "module":
                row["parent_id"] = parent_dir_id(rel)
            rows.append(row)
        self.db.replace_file_nodes(rel, rows, hashlib.sha256(source).hexdigest(), path.stat().st_mtime)

    def _rebuild_dirs(self):
        modules = {n["id"]: n for n in self.db.all_nodes() if n["kind"] == "module"}
        children: dict[str, list[dict]] = {}
        dir_paths = {""}
        for m in modules.values():
            parts = m["file"].split("/")[:-1]
            for i in range(len(parts)):
                dir_paths.add("/".join(parts[: i + 1]))
            children.setdefault(m["parent_id"], []).append(m)

        dirs: dict[str, dict] = {}
        # Deepest first so a dir's hash can include its subdirs' hashes.
        for d in sorted(dir_paths, key=lambda p: -p.count("/") if p else 1):
            did = dir_id(d)
            kids = children.get(did, [])
            node = {
                "id": did,
                "kind": "dir",
                "parent_id": None if did == ROOT_ID else parent_dir_id(d),
                "name": d.rsplit("/", 1)[-1] if d else self.root.name,
                "ast_hash": sha("".join(sorted(k["id"] + k["ast_hash"] for k in kids))),
                "loc": sum(k["loc"] for k in kids),
                "ordinal": 0,
            }
            dirs[did] = node
            if did != ROOT_ID:
                children.setdefault(node["parent_id"], []).append(node)
        self.db.replace_dirs(list(dirs.values()))

    def _rebuild_edges(self):
        self.db.replace_edges("inferred", build_inferred_edges(self.parsed))

    def module_of(self, node_id: str) -> str:
        return module_id(node_id.partition("#")[0].removeprefix("repo://"))
