"""SQLite access. One connection, guarded by a lock; the API, watcher and workers share it."""

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 2  # bump when schema.sql changes; the index is rebuilt, summaries are kept

NODE_COLS = (
    "id, kind, parent_id, name, file, start_byte, end_byte, start_line, end_line, "
    "indent, ast_hash, src_hash, loc, signature, docstring, ordinal"
)


class DB:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        if self.conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            self.conn.executescript("DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS edges; DROP TABLE IF EXISTS files;")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.executescript((Path(__file__).parent / "schema.sql").read_text())

    # -- writes -------------------------------------------------------------------------------

    def replace_file_nodes(self, rel: str, nodes: list[dict], sha256: str, mtime: float):
        with self.lock:
            c = self.conn
            c.execute("BEGIN")
            c.execute("DELETE FROM nodes WHERE file = ?", (rel,))
            self._insert_nodes(nodes)
            c.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?)", (rel, sha256, mtime))
            c.execute("COMMIT")

    def remove_file(self, rel: str):
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.execute("DELETE FROM nodes WHERE file = ?", (rel,))
            self.conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            self.conn.execute("COMMIT")

    def replace_dirs(self, dirs: list[dict]):
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.execute("DELETE FROM nodes WHERE kind = 'dir'")
            self._insert_nodes(dirs)
            self.conn.execute("COMMIT")

    def _insert_nodes(self, nodes: list[dict]):
        cols = [c.strip() for c in NODE_COLS.split(",")]
        self.conn.executemany(
            f"INSERT INTO nodes ({NODE_COLS}) VALUES ({', '.join('?' * len(cols))})",
            [tuple(n.get(c) for c in cols) for n in nodes],
        )

    def replace_edges(self, tier: str, edges: list[tuple], src_file: str | None = None):
        """Replace all edges of a tier (optionally only those originating in one file)."""
        with self.lock:
            self.conn.execute("BEGIN")
            if src_file is None:
                self.conn.execute("DELETE FROM edges WHERE tier = ?", (tier,))
            else:
                self.conn.execute("DELETE FROM edges WHERE tier = ? AND src_file = ?", (tier, src_file))
            self.conn.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?)", edges)
            self.conn.execute("COMMIT")

    def upsert_summary(self, node_id, ast_hash, title, summary, entry_points, model, created_at):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO summaries VALUES (?, ?, ?, ?, ?, ?, ?)",
                (node_id, ast_hash, title, summary, entry_points, model, created_at),
            )

    # -- reads --------------------------------------------------------------------------------

    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def node(self, node_id: str) -> dict | None:
        rows = self._all(f"SELECT {NODE_COLS} FROM nodes WHERE id = ?", (node_id,))
        return rows[0] if rows else None

    def children(self, node_id: str) -> list[dict]:
        return self._all(
            f"SELECT {NODE_COLS} FROM nodes WHERE parent_id = ? "
            "ORDER BY CASE kind WHEN 'dir' THEN 0 WHEN 'module' THEN 1 ELSE 2 END, ordinal, name",
            (node_id,),
        )

    def file_nodes(self, rel: str) -> list[dict]:
        return self._all(f"SELECT {NODE_COLS} FROM nodes WHERE file = ? ORDER BY ordinal", (rel,))

    def all_nodes(self) -> list[dict]:
        return self._all(f"SELECT {NODE_COLS} FROM nodes")

    def graph_edges(self) -> list[dict]:
        """One row per (src, dst, kind); 'resolved' wins over 'inferred'. Module imports are left out."""
        return self._all(
            "SELECT src, dst, kind, MAX(tier) AS tier FROM edges WHERE kind != 'import' GROUP BY src, dst, kind"
        )

    def files(self) -> dict[str, dict]:
        return {r["path"]: r for r in self._all("SELECT * FROM files")}

    def summary(self, node_id: str) -> dict | None:
        rows = self._all("SELECT * FROM summaries WHERE node_id = ?", (node_id,))
        return rows[0] if rows else None

    def summaries(self, node_ids: list[str]) -> dict[str, dict]:
        if not node_ids:
            return {}
        q = ",".join("?" * len(node_ids))
        return {r["node_id"]: r for r in self._all(f"SELECT * FROM summaries WHERE node_id IN ({q})", node_ids)}
