"""Bottom-up, lazy, cached summaries.

A node's summary waits for its children's summaries, so each level reads summaries of the level
below rather than raw code. Nothing is summarized until the UI shows it.
"""

import asyncio
import json
import logging
import os
import time
from typing import Awaitable, Callable

import anthropic

from strata.db.queries import DB
from strata.indexer.repo_index import RepoIndex
from strata.semantic import prompts
from strata.semantic.cache import view

log = logging.getLogger("strata.summarizer")

LEAF_MODEL = "claude-haiku-4-5"  # high volume, low stakes
BRANCH_MODEL = "claude-opus-5"  # low volume; these are the labels people actually read
CONCURRENCY = 4


class Summarizer:
    def __init__(self, index: RepoIndex, broadcast: Callable[[dict], Awaitable[None]], client=None):
        self.index = index
        self.db: DB = index.db
        self.broadcast = broadcast
        if client is None and os.environ.get("ANTHROPIC_API_KEY"):
            client = anthropic.AsyncAnthropic()
        self.client = client
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.inflight: dict[tuple[str, str], asyncio.Task] = {}
        self.errors: dict[str, str] = {}  # node_id -> last error, cleared on success

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def status(self, node: dict) -> str:
        """none | pending | error | disabled — the UI renders each differently."""
        if (node["id"], node["ast_hash"]) in self.inflight:
            return "pending"
        if node["id"] in self.errors:
            return "error"
        return "none" if self.enabled else "disabled"

    def request(self, node_ids: list[str]):
        """Fire-and-forget: queue summaries for nodes the UI just displayed."""
        if not self.enabled:
            return
        for nid in node_ids:
            asyncio.ensure_future(self.ensure(nid))

    async def ensure(self, node_id: str) -> dict | None:
        node = self.db.node(node_id)
        if node is None:
            return None
        row = self.db.summary(node_id)
        if row and row["ast_hash"] == node["ast_hash"]:
            return row
        key = (node_id, node["ast_hash"])
        if key not in self.inflight:
            task = asyncio.ensure_future(self._generate(node))
            self.inflight[key] = task
            task.add_done_callback(lambda _: self.inflight.pop(key, None))
        try:
            return await asyncio.shield(self.inflight[key])
        except Exception:
            return None

    async def _generate(self, node: dict) -> dict | None:
        try:
            if node["kind"] == "function":
                source = self._source(node)
                data = await self._call(LEAF_MODEL, prompts.leaf_prompt(node, source), prompts.LEAF_SCHEMA)
                model = LEAF_MODEL
            else:
                children = self.db.children(node["id"])
                child_rows = await asyncio.gather(*(self.ensure(c["id"]) for c in children))
                own = None if node["kind"] == "dir" else self._own_code(node, children)
                prompt = prompts.branch_prompt(node, own, list(zip(children, child_rows)))
                data = await self._call(BRANCH_MODEL, prompt, prompts.BRANCH_SCHEMA)
                model = BRANCH_MODEL
        except Exception as e:
            self.errors[node["id"]] = f"{type(e).__name__}: {e}"
            log.warning("summary failed for %s: %s", node["id"], e)
            await self.broadcast({"type": "summary_error", "node_id": node["id"], "error": self.errors[node["id"]]})
            raise

        self.errors.pop(node["id"], None)
        # Stored under the hash it was generated from: if the code moved on meanwhile it shows stale.
        self.db.upsert_summary(
            node["id"],
            node["ast_hash"],
            data.get("title"),
            data["summary"],
            json.dumps(data.get("entry_points", [])),
            model,
            time.time(),
        )
        row = self.db.summary(node["id"])
        current = self.db.node(node["id"])
        if current:
            await self.broadcast({"type": "summary", "node_id": node["id"], **view(current, row)})
        return row

    async def _call(self, model: str, prompt: str, schema: dict) -> dict:
        async with self.sem:
            if model == BRANCH_MODEL:
                response = await self.client.beta.messages.create(
                    model=model,
                    max_tokens=4000,
                    system=prompts.SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                response = await self.client.messages.create(
                    model=model,
                    max_tokens=1000,
                    system=prompts.SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined to summarize this code")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("summary was cut off (max_tokens)")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    def _source(self, node: dict) -> str:
        data = (self.index.root / node["file"]).read_bytes()
        return data[node["start_byte"] : node["end_byte"]].decode("utf-8", errors="replace")

    def _own_code(self, node: dict, children: list[dict]) -> str:
        """The node's lines minus its members' spans (imports, constants, class attributes...)."""
        data = (self.index.root / node["file"]).read_bytes()
        lines = data[node["start_byte"] : node["end_byte"]].decode("utf-8", errors="replace").splitlines()
        hidden = set()
        for c in children:
            hidden.update(range(c["start_line"], c["end_line"] + 1))
        return "\n".join(l for i, l in enumerate(lines, start=node["start_line"]) if i not in hidden)
