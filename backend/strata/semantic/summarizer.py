"""Bottom-up, lazy, cached summaries.

A node's summary waits for its children's summaries, so each level reads summaries of the level
below rather than raw code. Nothing is summarized until the UI shows it.
"""

import asyncio
import json
import logging
import os
import time
import urllib.request
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
LOCAL_PREFIX = "ollama:"  # e.g. STRATA_LEAF_MODEL=ollama:qwen2.5-coder:7b
OPENAI_PREFIX = "openai:"  # any OpenAI-compatible server (llama.cpp, vLLM...) at LLM_API_BASE
LOCAL_CONCURRENCY = 2  # one GPU; more parallel requests mostly just queue
SUMMARIZED_KINDS = ("function", "class", "module", "dir")  # variables, imports and blocks show their code instead


class Summarizer:
    def __init__(self, index: RepoIndex, broadcast: Callable[[dict], Awaitable[None]], client=None):
        self.index = index
        self.db: DB = index.db
        self.broadcast = broadcast
        if client is None and os.environ.get("ANTHROPIC_API_KEY"):
            client = anthropic.AsyncAnthropic()
        self.client = client
        self.leaf_model = os.environ.get("STRATA_LEAF_MODEL", LEAF_MODEL)
        self.branch_model = os.environ.get("STRATA_BRANCH_MODEL", BRANCH_MODEL)
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.llm_api_base = os.environ.get("LLM_API_BASE", "http://127.0.0.1:8080").rstrip("/").removesuffix("/v1")
        # Reasoning models spend most of their time thinking; a one-line label rarely needs it.
        self.llm_thinking = os.environ.get("STRATA_LLM_THINKING", "").lower() in ("1", "true", "yes")
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.local_sem = asyncio.Semaphore(LOCAL_CONCURRENCY)
        self.inflight: dict[tuple[str, str], asyncio.Task] = {}
        self.errors: dict[str, str] = {}  # node_id -> last error, cleared on success
        self.loop: asyncio.AbstractEventLoop | None = None  # set at startup; sync endpoints run in worker threads

    def model_for(self, node: dict) -> str:
        return self.leaf_model if node["kind"] == "function" else self.branch_model

    def usable(self, model: str) -> bool:
        return model.startswith((LOCAL_PREFIX, OPENAI_PREFIX)) or self.client is not None

    @property
    def enabled(self) -> bool:
        return self.usable(self.leaf_model) or self.usable(self.branch_model)

    def status(self, node: dict) -> str:
        """none | pending | error | disabled — the UI renders each differently."""
        if node["kind"] not in SUMMARIZED_KINDS:
            return "code"
        if (node["id"], node["ast_hash"]) in self.inflight:
            return "pending"
        if node["id"] in self.errors:
            return "error"
        return "none" if self.usable(self.model_for(node)) else "disabled"

    def request(self, node_ids: list[str]):
        """Fire-and-forget: queue summaries for nodes the UI just displayed."""
        if not self.enabled or self.loop is None:
            return
        for nid in node_ids:
            asyncio.run_coroutine_threadsafe(self.ensure(nid), self.loop)

    async def ensure(self, node_id: str) -> dict | None:
        node = self.db.node(node_id)
        if node is None or node["kind"] not in SUMMARIZED_KINDS:
            return None
        row = self.db.summary(node_id)
        if row and row["ast_hash"] == node["ast_hash"]:
            return row
        if not self.usable(self.model_for(node)):
            return None
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
            model = self.model_for(node)
            if node["kind"] == "function":
                source = self._source(node)
                data = await self._call(model, prompts.leaf_prompt(node, source), prompts.LEAF_SCHEMA)
            else:
                children = self.db.children(node["id"])
                child_rows = await asyncio.gather(*(self.ensure(c["id"]) for c in children))
                own = None if node["kind"] == "dir" else self._own_code(node, children)
                prompt = prompts.branch_prompt(node, own, list(zip(children, child_rows)))
                data = await self._call(model, prompt, prompts.BRANCH_SCHEMA)
            if len(data.get("summary", "").split()) < 3:
                raise RuntimeError(f"unusable summary from {model}: {data.get('summary')!r}")
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
        if model.startswith(LOCAL_PREFIX):
            async with self.local_sem:
                return await asyncio.to_thread(self._call_ollama, model.removeprefix(LOCAL_PREFIX), prompt, schema)
        if model.startswith(OPENAI_PREFIX):
            async with self.local_sem:
                return await asyncio.to_thread(self._call_openai, model.removeprefix(OPENAI_PREFIX), prompt, schema)
        async with self.sem:
            if model == "claude-opus-5":
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

    def _call_ollama(self, model: str, prompt: str, schema: dict) -> dict:
        # Schema-constrained decoding makes small models stop after one word ("Returns"), so a
        # single-sentence leaf summary is requested as plain text; branches still need JSON.
        plain = schema is prompts.LEAF_SCHEMA
        body = {
            "model": model,
            "messages": [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0},
        }
        if not plain:
            body["format"] = schema
        req = urllib.request.Request(
            f"{self.ollama_host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            reply = json.load(resp)
        if reply.get("done_reason") == "length":
            raise RuntimeError("summary was cut off (context/length limit)")
        content = reply["message"]["content"]
        if plain:
            line = next((l for l in content.strip().splitlines() if l.strip()), "")
            return {"summary": line.strip().strip('"').strip()}
        return json.loads(content)

    def _call_openai(self, model: str, prompt: str, schema: dict) -> dict:
        """OpenAI-compatible /v1/chat/completions. Same plain-text-leaf rule as _call_ollama."""
        plain = schema is prompts.LEAF_SCHEMA
        body = {
            "model": model,
            "messages": [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": self.llm_thinking},
        }
        if not plain:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "summary", "schema": schema}}
        req = urllib.request.Request(
            f"{self.llm_api_base}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            reply = json.load(resp)
        choice = reply["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("summary was cut off (context/length limit)")
        content = choice["message"].get("content") or ""
        if plain:
            line = next((l for l in content.strip().splitlines() if l.strip()), "")
            return {"summary": line.strip().strip('"').strip()}
        return json.loads(content)

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
