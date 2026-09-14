"""FastAPI surface: one screen = one GET /api/node; edits via PATCH; live deltas over /ws."""

import argparse
import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from strata.db.queries import DB
from strata.indexer.node_ids import ROOT_ID, descendant_prefix
from strata.indexer.repo_index import RepoIndex
from strata.indexer.resolver import resolve_all, resolve_file
from strata.indexer.watcher import RepoWatcher
from strata.semantic.cache import view
from strata.semantic.summarizer import Summarizer
from strata.writeback.patch import Conflict, InvalidEdit, apply_patch, dedent_node, find_node

log = logging.getLogger("strata")
RECENT_S = 7 * 24 * 3600
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class PatchBody(BaseModel):
    expected_src_hash: str
    source: str


def default_db_path(repo: Path) -> Path:
    digest = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:8]
    d = Path.home() / ".strata"
    d.mkdir(exist_ok=True)
    return d / f"{repo.resolve().name}-{digest}.db"


def create_app(repo: Path, db_path: Path, watch: bool = True, resolve: bool = True) -> FastAPI:
    index = RepoIndex(repo, DB(db_path))
    sockets: set[WebSocket] = set()
    state = {"resolver": "pending" if resolve else "off"}

    async def broadcast(event: dict):
        for ws in list(sockets):
            try:
                await ws.send_json(event)
            except Exception:
                sockets.discard(ws)

    summarizer = Summarizer(index, broadcast)

    async def on_files_changed(rels: set[str]):
        delta = {"added": set(), "removed": set(), "changed": set()}
        for rel in sorted(rels):
            d = await asyncio.to_thread(index.reindex_file, rel)
            for k in delta:
                delta[k].update(d[k])
        await broadcast({
            "type": "delta",
            "files": sorted(rels),
            "errors": {r: index.errors[r] for r in rels if r in index.errors},
            **{k: sorted(v) for k, v in delta.items()},
        })
        # Refresh summaries people have already looked at; the rest stay lazy.
        summarizer.request([nid for nid in delta["changed"] if index.db.summary(nid)])
        if state["resolver"] == "done":
            for rel in rels:
                await asyncio.to_thread(resolve_file, index, rel)
            await broadcast({"type": "edges"})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t = time.time()
        await asyncio.to_thread(index.index_all)
        log.info("indexed %s in %.2fs (%d files)", repo, time.time() - t, len(index.parsed))
        watcher = None
        if watch:
            watcher = RepoWatcher(repo, asyncio.get_running_loop(), on_files_changed, lambda: list(index.parsed))
            watcher.start()

        async def run_resolver():
            await asyncio.to_thread(resolve_all, index)
            state["resolver"] = "done"
            await broadcast({"type": "edges"})

        if resolve:
            asyncio.ensure_future(run_resolver())
        yield
        if watcher:
            watcher.stop()

    app = FastAPI(title="Strata", lifespan=lifespan)

    def get_node(node_id: str) -> dict:
        node = index.db.node(node_id)
        if node is None:
            raise HTTPException(404, f"no such node: {node_id}")
        return node

    def cards(nodes: list[dict]) -> list[dict]:
        ids = [n["id"] for n in nodes]
        summaries = index.db.summaries(ids)
        callers = index.db.caller_counts(ids)
        kids = index.db.child_counts(ids)
        now = time.time()
        recent = [f for f, row in index.db.files().items() if now - row["mtime"] < RECENT_S]
        out = []
        for n in nodes:
            prefix = descendant_prefix(n["id"]).removeprefix("repo://")
            changed = any(f == n["file"] or (n["kind"] == "dir" and f.startswith(prefix)) for f in recent)
            out.append({
                "id": n["id"], "kind": n["kind"], "name": n["name"], "file": n["file"],
                "start_line": n["start_line"], "end_line": n["end_line"], "loc": n["loc"],
                "signature": n["signature"], "docstring": n["docstring"],
                "callers": callers.get(n["id"], 0), "children": kids.get(n["id"], 0),
                "changed_recently": changed,
                "summary": view(n, summaries.get(n["id"])),
                "summary_status": summarizer.status(n),
                "error": index.errors.get(n["file"]) if n["kind"] == "module" else None,
            })
        return out

    @app.get("/api/repo")
    def repo_info():
        return {
            "name": index.root.name, "root": str(index.root), "files": len(index.parsed),
            "errors": index.errors, "summaries_enabled": summarizer.enabled, "resolver": state["resolver"],
            "models": {
                "leaf": summarizer.leaf_model, "leaf_ready": summarizer.usable(summarizer.leaf_model),
                "branch": summarizer.branch_model, "branch_ready": summarizer.usable(summarizer.branch_model),
            },
        }

    @app.get("/api/node")
    def node_view(id: str = ROOT_ID):
        node = get_node(id)
        crumbs, cur = [], node
        while cur:
            crumbs.append({"id": cur["id"], "name": cur["name"], "kind": cur["kind"]})
            cur = index.db.node(cur["parent_id"]) if cur["parent_id"] else None
        children = index.db.children(id)
        summarizer.request([id] + [c["id"] for c in children])
        rel = index.db.relations(id)
        return {
            "node": {**cards([node])[0], "abs_path": str(index.root / node["file"]) if node["file"] else str(index.root)},
            "breadcrumb": list(reversed(crumbs)),
            "children": cards(children),
            "relations": rel,
        }

    @app.get("/api/source")
    def source(id: str):
        node = get_node(id)
        if not node["file"]:
            raise HTTPException(400, "directories have no source")
        data = (index.root / node["file"]).read_bytes()
        if node["kind"] == "module":
            text, src_hash = data.decode("utf-8", errors="replace"), node["src_hash"]
        else:
            # Re-parse from disk so the snippet and hash are never older than the file.
            data, fresh = find_node(index.root, node["file"], id)
            if fresh is None:
                raise HTTPException(409, "node not found in the file on disk (syntax error or removed)")
            text, src_hash = dedent_node(data, fresh), fresh.src_hash
            node = {**node, "start_line": fresh.start_line}
        return {"source": text, "src_hash": src_hash, "start_line": node["start_line"],
                "file": node["file"], "abs_path": str(index.root / node["file"])}

    @app.patch("/api/node")
    async def patch_node(id: str, body: PatchBody):
        node = get_node(id)
        if node["kind"] not in ("class", "function"):
            raise HTTPException(400, "only classes and functions are editable here")
        try:
            result = await asyncio.to_thread(apply_patch, index.root, node["file"], id, body.expected_src_hash, body.source)
        except Conflict as c:
            return JSONResponse(status_code=409, content={
                "reason": c.reason, "current_source": c.current_source, "current_src_hash": c.current_src_hash})
        except InvalidEdit as e:
            return JSONResponse(status_code=422, content={"message": e.message, "line": e.line})
        if result.changed:
            # Don't wait for the watcher: the editor needs fresh hashes before the next save.
            await on_files_changed({node["file"]})
        return {"changed": result.changed, "node_id": result.node_id, "formatted": result.formatted}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        sockets.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            sockets.discard(websocket)

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(prog="strata")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="index a repo and serve the dashboard")
    serve.add_argument("--repo", required=True, type=Path)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--db", type=Path)
    serve.add_argument("--no-watch", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    repo = args.repo.expanduser().resolve()
    app = create_app(repo, args.db or default_db_path(repo), watch=not args.no_watch)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
