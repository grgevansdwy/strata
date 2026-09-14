import shutil
from pathlib import Path

import pytest

from strata.indexer.ast_parser import parse_file
from strata.indexer.repo_index import RepoIndex
from strata.db.queries import DB
from strata.writeback.patch import Conflict, InvalidEdit, apply_patch, dedent_node, find_node, reindent

FIXTURES = Path(__file__).parent / "fixtures"
REL = "sample.py"


@pytest.fixture
def repo(tmp_path) -> Path:
    shutil.copy(FIXTURES / "sample.py", tmp_path / REL)
    return tmp_path


def load(repo, node_id):
    source, node = find_node(repo, REL, node_id)
    return dedent_node(source, node), node.src_hash


def edit(repo, node_id, old, new):
    snippet, h = load(repo, node_id)
    assert snippet.count(old) == 1
    return apply_patch(repo, REL, node_id, h, snippet.replace(old, new))


def golden(name) -> bytes:
    return (FIXTURES / "golden" / f"{name}.py").read_bytes()


def test_snippet_is_dedented_but_string_contents_are_not():
    source = (FIXTURES / "sample.py").read_bytes()
    node = next(n for n in parse_file(REL, source).nodes if n.id.endswith("#Invoice.total"))
    snippet = dedent_node(source, node)
    assert snippet.startswith("def total(self, tax=0.1):\n    note = \"\"\"\n")
    assert "\n    keeps its own indentation\n\"\"\"\n" in snippet


def test_edit_method(repo):
    edit(repo, "repo://sample.py#Invoice.total", "def total(self, tax=0.1):\n", "def total(self, tax=0.2):\n    # tax is now 20%\n")
    assert (repo / REL).read_bytes() == golden("edit_method")


def test_edit_decorated_method(repo):
    snippet, _ = load(repo, "repo://sample.py#Invoice.cents")
    assert snippet.startswith("@property\n")
    edit(
        repo,
        "repo://sample.py#Invoice.cents",
        "def cents(self):\n    # comment at method indentation\n    return int(self.amount * 100)\n",
        "def cents(self) -> int:\n    return round(self.amount * 100)\n",
    )
    assert (repo / REL).read_bytes() == golden("edit_decorated_method")


def test_edit_decorated_function(repo):
    edit(repo, "repo://sample.py#charge", "@retry\n", "@retry\n@functools.cache\n")
    assert (repo / REL).read_bytes() == golden("edit_decorated_function")


def test_edit_nested_function(repo):
    edit(repo, "repo://sample.py#charge.log", "def log(msg):\n    print(msg)\n", 'def log(msg, level="info"):\n    print(f"[{level}] {msg}")\n')
    assert (repo / REL).read_bytes() == golden("edit_nested_function")


def test_edit_with_changed_indentation(repo):
    edit(
        repo,
        "repo://sample.py#Invoice.__init__",
        "    self.amount = amount\n",
        "  self.amount = amount\n  if amount < 0:\n      raise ValueError(amount)\n",
    )
    assert (repo / REL).read_bytes() == golden("edit_changed_indentation")


def test_rename_reports_new_node_id(repo):
    result = edit(repo, "repo://sample.py#Invoice.total", "def total(", "def grand_total(")
    assert result.node_id == "repo://sample.py#Invoice.grand_total"


def test_syntax_error_is_rejected_before_touching_the_file(repo):
    before = (repo / REL).read_bytes()
    with pytest.raises(InvalidEdit) as e:
        edit(repo, "repo://sample.py#Invoice.total", "return self.amount", "return self.amount +")
    assert e.value.line is not None
    assert (repo / REL).read_bytes() == before


def test_indented_snippet_is_rejected(repo):
    before = (repo / REL).read_bytes()
    snippet, h = load(repo, "repo://sample.py#retry")
    with pytest.raises(InvalidEdit):
        apply_patch(repo, REL, "repo://sample.py#retry", h, "    " + snippet)
    assert (repo / REL).read_bytes() == before


def test_conflict_when_node_changed_on_disk_mid_edit(repo):
    node_id = "repo://sample.py#Invoice.total"
    snippet, h = load(repo, node_id)  # editor opens the snippet
    path = repo / REL
    # another editor changes the same method (comment only: the AST is identical, bytes are not)
    path.write_text(path.read_text().replace("        return self.amount * (1 + tax)", "        return self.amount * (1 + tax)  # hi"))
    on_disk = path.read_bytes()
    with pytest.raises(Conflict) as e:
        apply_patch(repo, REL, node_id, h, snippet.replace("0.1", "0.3"))
    assert path.read_bytes() == on_disk  # not clobbered
    assert "# hi" in e.value.current_source


def test_conflict_when_node_deleted_on_disk(repo):
    snippet, h = load(repo, "repo://sample.py#retry")
    path = repo / REL
    path.write_text(path.read_text().replace("def retry(fn):", "def retry2(fn):"))
    on_disk = path.read_bytes()
    with pytest.raises(Conflict):
        apply_patch(repo, REL, "repo://sample.py#retry", h, snippet + "\n# edited\n")
    assert path.read_bytes() == on_disk


def test_unrelated_disk_change_elsewhere_in_file_is_preserved(repo):
    node_id = "repo://sample.py#charge.log"
    snippet, h = load(repo, node_id)
    path = repo / REL
    path.write_text("# added by another editor\n" + path.read_text())  # shifts every byte offset
    apply_patch(repo, REL, node_id, h, snippet.replace("print(msg)", "print('>', msg)"))
    text = path.read_text()
    assert text.startswith("# added by another editor\n")
    assert "        print('>', msg)\n" in text


def test_noop_save_does_not_write(repo):
    path = repo / REL
    mtime = path.stat().st_mtime_ns
    snippet, h = load(repo, "repo://sample.py#Invoice.cents")
    assert apply_patch(repo, REL, "repo://sample.py#Invoice.cents", h, snippet).changed is False
    assert path.stat().st_mtime_ns == mtime


def test_dedent_reindent_roundtrip_is_byte_identical_on_real_repo(effigov_copy, tmp_path):
    """The correctness trap from the design doc, checked against every symbol in the test repo."""
    idx = RepoIndex(effigov_copy, DB(tmp_path / "t.db"))
    idx.index_all()
    checked = 0
    for rel, pf in idx.parsed.items():
        source = (effigov_copy / rel).read_bytes()
        for n in pf.nodes:
            if n.kind == "module":
                continue
            snippet = dedent_node(source, n)
            span = source[n.start_byte : n.end_byte].decode().replace("\r\n", "\n")
            if not span.endswith("\n"):
                span += "\n"
            # Known limitation: a comment shallower than its def (e.g. column 0 inside a method)
            # would gain indentation on re-indent. No-op saves skip the write, so it only matters
            # when that node is actually edited.
            assert reindent(snippet, n.indent) == span, n.id
            checked += 1
    assert checked > 200
