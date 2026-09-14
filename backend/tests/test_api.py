from fastapi.testclient import TestClient

from strata.api import create_app


def client(repo, tmp_path):
    return TestClient(create_app(repo, tmp_path / "t.db", watch=False, resolve=False))


def test_drill_down_and_edit_roundtrip(effigov_copy, tmp_path):
    with client(effigov_copy, tmp_path) as c:
        root = c.get("/api/node").json()
        assert [b["name"] for b in root["breadcrumb"]] == ["effigov"]
        assert {"services", "scripts"} <= {ch["name"] for ch in root["children"]}

        fid = "repo://services/api/app/main.py#health"
        view = c.get("/api/node", params={"id": fid}).json()
        assert [b["name"] for b in view["breadcrumb"]] == ["effigov", "services", "api", "app", "main.py", "health"]
        assert any(r["id"].endswith("db.py#get_client") for r in view["relations"]["calls"])

        src = c.get("/api/source", params={"id": fid}).json()
        assert src["source"].startswith('@app.get("/health")\nasync def health()')
        new = src["source"].replace('"status": "ok"', '"status": "healthy"')
        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": src["src_hash"], "source": new})
        assert r.status_code == 200 and r.json()["changed"]
        assert '"status": "healthy"' in (effigov_copy / "services/api/app/main.py").read_text()

        # the old hash is now stale -> 409, file untouched
        before = (effigov_copy / "services/api/app/main.py").read_bytes()
        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": src["src_hash"], "source": src["source"]})
        assert r.status_code == 409 and '"healthy"' in r.json()["current_source"]
        assert (effigov_copy / "services/api/app/main.py").read_bytes() == before

        r = c.patch("/api/node", params={"id": fid}, json={"expected_src_hash": c.get("/api/source", params={"id": fid}).json()["src_hash"], "source": "def (:"})
        assert r.status_code == 422
