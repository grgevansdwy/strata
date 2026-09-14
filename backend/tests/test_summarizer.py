"""Summarizer behavior with a fake client: ordering, caching, and staleness. No network."""

import asyncio
import json
from types import SimpleNamespace

from strata.db.queries import DB
from strata.indexer.repo_index import RepoIndex
from strata.semantic.cache import view
from strata.semantic.summarizer import BRANCH_MODEL, LEAF_MODEL, Summarizer


class FakeMessages:
    def __init__(self, log):
        self.log = log

    async def create(self, model, messages, **kw):
        prompt = messages[0]["content"]
        self.log.append((model, prompt))
        body = {"summary": f"summary #{len(self.log)}"}
        if model == BRANCH_MODEL:
            body |= {"title": f"Title {len(self.log)}", "entry_points": []}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])


class FakeClient:
    def __init__(self):
        self.log = []
        self.messages = FakeMessages(self.log)
        self.beta = SimpleNamespace(messages=self.messages)


def make(effigov_copy, tmp_path):
    idx = RepoIndex(effigov_copy, DB(tmp_path / "t.db"))
    idx.index_all()
    events = []

    async def broadcast(e):
        events.append(e)

    client = FakeClient()
    return idx, Summarizer(idx, broadcast, client=client), client, events


def test_bottom_up_and_cached(effigov_copy, tmp_path):
    idx, s, client, events = make(effigov_copy, tmp_path)
    mod = "repo://services/api/app/db.py"
    n_children = len(idx.db.children(mod))
    row = asyncio.run(s.ensure(mod))
    assert row["model"] == BRANCH_MODEL and row["title"]
    # every function summarized (Haiku) before the module (Opus), and the module prompt used them
    models = [m for m, _ in client.log]
    assert models[-1] == BRANCH_MODEL and models.count(LEAF_MODEL) == n_children
    assert "summary #1" in client.log[-1][1]

    calls = len(client.log)
    asyncio.run(s.ensure(mod))
    assert len(client.log) == calls  # cache hit, no new calls


def test_edit_makes_summary_stale_then_refreshes(effigov_copy, tmp_path):
    idx, s, client, events = make(effigov_copy, tmp_path)
    fid = "repo://services/api/app/main.py#health"
    asyncio.run(s.ensure(fid))
    path = effigov_copy / "services/api/app/main.py"
    path.write_text(path.read_text().replace('"status": "ok"', '"status": "healthy"'))
    idx.reindex_file("services/api/app/main.py")

    node = idx.db.node(fid)
    stale = view(node, idx.db.summary(fid))
    assert stale["stale"] and stale["summary"]  # shown, but flagged

    asyncio.run(s.ensure(fid))
    assert view(node, idx.db.summary(fid))["stale"] is False
    assert events[-1]["type"] == "summary" and events[-1]["stale"] is False
