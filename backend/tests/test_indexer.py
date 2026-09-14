import ast

from strata.db.queries import DB
from strata.indexer.node_ids import ROOT_ID
from strata.indexer.repo_index import RepoIndex


def _index(repo, tmp_path):
    idx = RepoIndex(repo, DB(tmp_path / "t.db"))
    idx.index_all()
    return idx


def test_every_def_and_class_appears_exactly_once(effigov_copy, tmp_path):
    idx = _index(effigov_copy, tmp_path)
    nodes = idx.db.all_nodes()
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids))
    assert not idx.errors

    for rel in idx.scan():
        tree = ast.parse((effigov_copy / rel).read_bytes())
        expected = sorted(
            (n.lineno if not n.decorator_list else n.decorator_list[0].lineno, n.name)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        got = sorted(
            (n["start_line"], n["name"].split("@")[0])
            for n in nodes
            if n["file"] == rel and n["kind"] in ("class", "function")
        )
        assert got == expected, rel


def test_tree_is_connected(effigov_copy, tmp_path):
    idx = _index(effigov_copy, tmp_path)
    by_id = {n["id"]: n for n in idx.db.all_nodes()}
    for n in by_id.values():
        if n["id"] == ROOT_ID:
            assert n["parent_id"] is None
        else:
            assert n["parent_id"] in by_id, n["id"]


def test_ids_survive_unrelated_edit(effigov_copy, tmp_path):
    rel = "services/api/app/main.py"
    idx = _index(effigov_copy, tmp_path)
    before = {n["id"]: n for n in idx.db.file_nodes(rel)}
    path = effigov_copy / rel
    # Insert lines at the top: every byte offset and line number below shifts.
    path.write_text('"""pad"""\n\nimport os\n\n\n' + path.read_text())
    delta = idx.reindex_file(rel)
    after = {n["id"]: n for n in idx.db.file_nodes(rel)}

    assert before.keys() == after.keys()
    assert delta["added"] == [] and delta["removed"] == []
    for nid in before:
        if "#" in nid:
            assert after[nid]["ast_hash"] == before[nid]["ast_hash"], nid
            assert after[nid]["start_line"] == before[nid]["start_line"] + 5


def test_syntax_error_keeps_last_good_nodes(effigov_copy, tmp_path):
    rel = "services/api/app/main.py"
    idx = _index(effigov_copy, tmp_path)
    before = idx.db.file_nodes(rel)
    (effigov_copy / rel).write_text("def broken(:\n")
    idx.reindex_file(rel)
    assert rel in idx.errors
    assert idx.db.file_nodes(rel) == before


def test_known_edges(effigov_copy, tmp_path):
    idx = _index(effigov_copy, tmp_path)
    edges = {(e["src"], e["dst"], e["kind"]) for e in idx.db.graph_edges()}
    assert ("repo://services/api/app/main.py#health", "repo://services/api/app/db.py#get_client", "call") in edges
