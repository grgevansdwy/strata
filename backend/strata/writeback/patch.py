"""Snippet write-back. The one module in Strata that can destroy user code; keep it boring.

Protocol (each step can abort; nothing touches disk until the last one):
  1. re-read the file, re-parse, locate the node; its current src_hash must equal the one the
     editor loaded, otherwise Conflict (never overwrite)
  2. the new snippet must parse on its own
  3. re-apply the node's original indentation (lines inside multi-line strings are left alone)
  4. splice by byte range, then the whole file must still parse
  5. run the repo's formatter if it has one configured
  6. confirm the file did not change while we worked, then atomic replace
"""

import ast
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from strata.indexer.ast_parser import Node, parse_file, protected_lines


class Conflict(Exception):
    def __init__(self, reason: str, current_source: str | None, current_src_hash: str | None):
        super().__init__(reason)
        self.reason = reason
        self.current_source = current_source
        self.current_src_hash = current_src_hash


class InvalidEdit(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class PatchResult:
    changed: bool
    node_id: str | None  # id of the node now occupying the edited position (may differ after a rename)
    formatted: bool = False


def find_node(root: Path, rel: str, node_id: str) -> tuple[bytes, Node | None]:
    source = (root / rel).read_bytes()
    try:
        pf = parse_file(rel, source)
    except SyntaxError:
        return source, None
    return source, next((n for n in pf.nodes if n.id == node_id), None)


def dedent_node(source: bytes, node: Node) -> str:
    """The snippet shown in the editor: the node's lines with its indentation removed."""
    text = source.decode("utf-8")
    protected = protected_lines(text)
    lines = text.splitlines(keepends=True)[node.start_line - 1 : node.end_line]
    out = []
    for lineno, line in enumerate(lines, start=node.start_line):
        line = line.replace("\r\n", "\n")
        if lineno not in protected and line.startswith(node.indent):
            line = line[len(node.indent) :]
        out.append(line)
    return "".join(out)


def reindent(snippet: str, indent: str) -> str:
    protected = protected_lines(snippet)
    out = []
    for lineno, line in enumerate(snippet.splitlines(keepends=True), start=1):
        if lineno in protected or not line.strip():
            out.append(line)
        else:
            out.append(indent + line)
    return "".join(out)


def apply_patch(root: Path, rel: str, node_id: str, expected_src_hash: str, new_source: str) -> PatchResult:
    path = root / rel
    stat_before = path.stat()

    # 1. locate and compare
    source, node = find_node(root, rel, node_id)
    if node is None:
        raise Conflict("node no longer exists in the file on disk", None, None)
    try:
        current = dedent_node(source, node)
    except UnicodeDecodeError:
        raise InvalidEdit("file is not UTF-8; open it in your editor instead")
    if node.src_hash != expected_src_hash:
        raise Conflict("the code changed on disk since you opened it", current, node.src_hash)

    new_source = new_source.replace("\r\n", "\n")
    if not new_source.endswith("\n"):
        new_source += "\n"
    if new_source == current:
        return PatchResult(changed=False, node_id=node_id)

    # 2. standalone parse
    if not new_source.strip():
        raise InvalidEdit("empty snippet; delete code in your editor instead")
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        raise InvalidEdit(f"{type(e).__name__}: {e.msg}", e.lineno)

    # 3. re-indent, matching the file's line endings
    snippet = reindent(new_source, node.indent)
    if b"\r\n" in source[node.start_byte : node.end_byte]:
        snippet = snippet.replace("\n", "\r\n")

    # 4. splice and re-parse the whole file
    new_file = source[: node.start_byte] + snippet.encode("utf-8") + source[node.end_byte :]
    try:
        ast.parse(new_file)
    except SyntaxError as e:
        raise InvalidEdit(f"edit breaks the file: {e.msg}", (e.lineno or node.start_line) - node.start_line + 1)

    # 5. formatter
    formatted = False
    fmt = _formatter_for(root, path)
    if fmt:
        result = subprocess.run(fmt, input=new_file, capture_output=True, timeout=30)
        if result.returncode == 0 and result.stdout:
            new_file, formatted = result.stdout, True

    # 6. last-moment race check + atomic replace
    stat_now = path.stat()
    if (stat_now.st_mtime_ns, stat_now.st_size) != (stat_before.st_mtime_ns, stat_before.st_size):
        raise Conflict("the file changed on disk while saving", None, None)
    _atomic_write(path, new_file, stat_before.st_mode)

    after = parse_file(rel, new_file)
    moved = next(
        (n for n in after.nodes if n.kind != "module" and n.start_line == node.start_line and n.indent == node.indent),
        None,
    )
    return PatchResult(changed=True, node_id=moved.id if moved else None, formatted=formatted)


def _formatter_for(root: Path, path: Path) -> list[str] | None:
    """Only format if the repo opted in via pyproject.toml; never impose a style."""
    d = path.parent
    while True:
        cfg = d / "pyproject.toml"
        if cfg.is_file():
            text = cfg.read_text()
            if "[tool.ruff" in text and shutil.which("ruff"):
                return ["ruff", "format", "--stdin-filename", str(path), "-"]
            if "[tool.black]" in text and shutil.which("black"):
                return ["black", "-q", "--stdin-filename", str(path), "-"]
        if d == root or d == d.parent:
            return None
        d = d.parent


def _atomic_write(path: Path, data: bytes, mode: int):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".strata")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
