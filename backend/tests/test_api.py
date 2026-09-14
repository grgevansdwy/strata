import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from strata.api import create_app

MINI = Path(__file__).parent / "fixtures" / "mini_repo"


def client(repo, tmp_path):
    return TestClient(create_app(repo, tmp_path / "t.db", watch=False, resolve=False))


def test_graph_and_edit_roundtrip(tmp_path):
    repo = tmp_path / "mini_repo"
    shutil.copytree(MINI, repo)
    with client(repo, tmp_path) as c:
        g = c.get("/api/graph").json()
        ids = {n["id"] for n in g["nodes"]}
        assert "repo://shop/models.py#TAX_RATE" in ids and not any(n["kind"] in ("dir", "module") for n in g["nodes"])
        assert "repo://shop/cli.py#__main__" in g["roots"]["entry"]
        by_id = {n["id"]: n for n in g["nodes"]}
        assert by_id["repo://shop/models.py#TAX_RATE"]["summary_status"] == "code"
        assert c.post("/api/summaries", json={"ids": ["repo://shop/cli.py#main"]}).status_code == 200

        fid = "repo://shop/pricing.py#order_total"
        path = repo / "shop/pricing.py"
        src = c.get("/api/source", params={"id": fid}).json()
        assert src["source"].startswith("def order_total(")
        new = src["source"].replace("sum(", "round(sum(").replace("items)\n", "items), 2)\n")
        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": src["src_hash"], "source": new})
        assert r.status_code == 200 and r.json()["changed"]
        assert "round(sum(" in path.read_text()

        # the old hash is now stale -> 409, file untouched
        before = path.read_bytes()
        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": src["src_hash"], "source": src["source"]})
        assert r.status_code == 409 and "round(sum(" in r.json()["current_source"]
        assert path.read_bytes() == before

        fresh = c.get("/api/source", params={"id": fid}).json()["src_hash"]
        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": fresh, "source": "def (:"})
        assert r.status_code == 422
