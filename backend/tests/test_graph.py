"""Graph shape on a small self-contained repo: boxes for every statement, edges, and root ranking."""

import ast
import shutil
from pathlib import Path

import pytest

from strata.db.queries import DB
from strata.graph import build_graph
from strata.indexer.repo_index import RepoIndex
from strata.indexer.resolver import resolve_all

MINI = Path(__file__).parent / "fixtures" / "mini_repo"


@pytest.fixture
def graph(tmp_path):
    repo = tmp_path / "mini_repo"
    shutil.copytree(MINI, repo)
    idx = RepoIndex(repo, DB(tmp_path / "t.db"))
    idx.index_all()
    resolve_all(idx)
    return idx, build_graph(idx)


def rid(qual: str) -> str:
    return "repo://" + qual


def test_every_line_of_code_is_in_a_box(graph):
    """Each non-blank, non-comment line outside the module docstring lies in some top-level node."""
    idx, _ = graph
    for rel in idx.scan():
        source = (idx.root / rel).read_text()
        tree = ast.parse(source)
        skip = set()
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
            skip.update(range(tree.body[0].lineno, tree.body[0].end_lineno + 1))
        covered = set()
        for n in idx.db.file_nodes(rel):
            if n["kind"] != "module" and n["parent_id"] == rid(rel):
                covered.update(range(n["start_line"], n["end_line"] + 1))
        for i, line in enumerate(source.splitlines(), start=1):
            if line.strip() and not line.strip().startswith("#") and i not in skip:
                assert i in covered, f"{rel}:{i} {line!r}"


def test_node_kinds(graph):
    idx, _ = graph
    kind = lambda q: idx.db.node(rid(q))["kind"]
    assert kind("shop/models.py#TAX_RATE") == "variable"
    assert kind("shop/models.py#Item.price") == "variable"  # dataclass field
    assert kind("shop/models.py#import:dataclasses") == "import"
    assert kind("shop/cli.py#__main__") == "block"
    assert kind("shop/web.py#app") == "variable"


def test_edges_connect_across_files(graph):
    _, g = graph
    edges = {(e["src"], e["dst"]): e["kind"] for e in g["edges"]}
    assert edges[(rid("shop/cli.py#__main__"), rid("shop/cli.py#main"))] == "call"
    assert edges[(rid("shop/cli.py#main"), rid("shop/pricing.py#parse_items"))] == "call"
    assert edges[(rid("shop/cli.py#main"), rid("shop/pricing.py#order_total"))] == "uses"  # passed as a callback
    assert edges[(rid("shop/pricing.py#parse_items"), rid("shop/models.py#Item"))] == "call"  # one line, not two
    assert edges[(rid("shop/pricing.py#parse_items"), rid("shop/pricing.py#import:json"))] == "uses"
    assert edges[(rid("shop/models.py#Item.total"), rid("shop/models.py#TAX_RATE"))] == "uses"
    assert edges[(rid("shop/models.py#Item"), rid("shop/models.py#Item.price"))] == "member"
    assert edges[(rid("shop/web.py#total_endpoint"), rid("shop/web.py#app"))] == "uses"
    assert len(edges) == len(g["edges"])


def test_roots_are_ranked(graph):
    _, g = graph
    roots = g["roots"]
    assert roots["entry"][0] == rid("shop/cli.py#__main__")  # reaches the most code
    assert set(roots["entry"]) == {rid("shop/cli.py#__main__"), rid("shop/cli.py#main"), rid("shop/web.py#total_endpoint")}
    assert roots["functions"] == [rid("shop/cli.py#orphan_helper")]
    assert roots["tests"] == [rid("tests/test_pricing.py#test_empty")]
    assert roots["other"] == [rid("shop/models.py#Unused")]


def test_ids_of_conditionally_defined_functions_are_unchanged(tmp_path):
    from strata.indexer.ast_parser import parse_file

    pf = parse_file("m.py", b"try:\n    def f(): pass\nexcept ImportError:\n    def f(): pass\n")
    ids = [n.id for n in pf.nodes if n.kind == "function"]
    assert ids == ["repo://m.py#f", "repo://m.py#f@2"]
