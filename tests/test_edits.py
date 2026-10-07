import sys

import pytest

from agent import edits


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("from pkg.core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return tmp_path


def proposal(search="def sub(a, b):\n    return a + b", replace="def sub(a, b):\n    return a - b",
             path="pkg/core.py", test_path="tests/test_sub.py",
             test="from pkg.core import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"):
    return {"explanation": "x", "edits": [{"path": path, "search": search, "replace": replace}],
            "new_test": {"path": test_path, "content": test}}


def check(repo, originals):
    return edits.check(repo, originals, sys.executable, repo)


def test_valid_edit_applies_and_imports_verify(repo):
    originals = edits.apply(repo, proposal(test="import json\nfrom pkg.core import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"))
    assert "return a - b" in (repo / "pkg" / "core.py").read_text()
    assert check(repo, originals) == ["json (stdlib)", "pkg.core.sub (repo)"]


@pytest.mark.parametrize("search", ["return a + b", "return a * b", ""])  # matches twice, zero times, empty
def test_search_must_match_exactly_once(repo, search):
    with pytest.raises(edits.EditError, match="exactly once"):
        edits.apply(repo, proposal(search=search))


@pytest.mark.parametrize("path", ["tests/test_core.py", "conftest.py", "tests/helpers.py"])
def test_existing_tests_are_locked(repo, path):
    with pytest.raises(edits.EditError, match="locked"):
        edits.apply(repo, proposal(path=path, search="add"))


def test_new_test_cannot_overwrite_existing_test(repo):
    with pytest.raises(edits.EditError, match="already exists"):
        edits.apply(repo, proposal(test_path="tests/test_core.py"))


@pytest.mark.parametrize("path", ["../outside.py", "C:/Windows/x.py", ".git/hooks/pre-commit"])
def test_paths_outside_repo_rejected(repo, path):
    with pytest.raises(edits.EditError):
        edits.apply(repo, proposal(path=path))


def test_invented_import_rejected(repo):
    originals = edits.apply(repo, proposal(test="import made_up_pkg\n\n\ndef test_x():\n    assert True\n"))
    with pytest.raises(edits.EditError, match="made_up_pkg"):
        check(repo, originals)


def test_invented_name_in_repo_module_rejected(repo):
    originals = edits.apply(repo, proposal(test="from pkg.core import multiply\n\n\ndef test_x():\n    assert True\n"))
    with pytest.raises(edits.EditError, match="multiply"):
        check(repo, originals)


def test_syntax_error_rejected(repo):
    originals = edits.apply(repo, proposal(replace="def sub(a, b:\n    return a - b"))
    with pytest.raises(edits.EditError, match="syntax error"):
        check(repo, originals)


def test_crlf_file_keeps_its_line_endings(repo):
    target = repo / "pkg" / "core.py"
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    edits.apply(repo, proposal())
    data = target.read_bytes()
    assert b"return a - b\r\n" in data and b"\r\r\n" not in data and data.count(b"\n") == data.count(b"\r\n")
