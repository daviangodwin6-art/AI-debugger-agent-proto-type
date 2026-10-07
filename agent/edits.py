"""Apply the LLM's proposal and enforce the safety rules. Rules live here, not in the prompt."""
import ast
import subprocess
import sys
from pathlib import Path


class EditError(Exception):
    """The proposal broke a rule; the message is fed back to the LLM."""


def is_test_file(path):
    p = Path(path)
    return (p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"
            or bool({"tests", "test"} & set(p.parts[:-1])))


def _inside(repo, rel):
    """Resolve a repo-relative path, refusing anything that escapes the repo."""
    repo = Path(repo).resolve()
    target = (repo / str(rel)).resolve()
    if not rel or not target.is_relative_to(repo) or ".git" in target.relative_to(repo).parts:
        raise EditError(f"path is outside the repository: {rel}")
    return target


def apply(repo, proposal):
    """Write the edits and the new test. Returns {path: original text, or None for a new file}."""
    try:
        edits, new_test = proposal["edits"], proposal["new_test"]
        steps = [(e["path"], e["search"], e["replace"]) for e in edits]
        test_path, test_content = new_test["path"], new_test["content"]
    except (KeyError, TypeError):
        raise EditError('response must be {"explanation", "edits": [{"path","search","replace"}], '
                        '"new_test": {"path","content"}}')
    if not steps:
        raise EditError("no edits proposed")
    originals = {}
    for rel, search, replace in steps:
        target = _inside(repo, rel)
        if is_test_file(rel):
            raise EditError(f"existing tests are locked, cannot edit {rel}; put new tests in a new file")
        if not target.is_file():
            raise EditError(f"file does not exist: {rel}")
        raw = target.read_bytes().decode("utf-8", errors="replace")
        newline = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        search, replace = search.replace("\r\n", "\n"), replace.replace("\r\n", "\n")
        found = text.count(search) if search else 0
        if found != 1:
            raise EditError(f"search text must match exactly once in {rel}, it matched {found} times:\n{search}")
        originals.setdefault(rel, text)
        target.write_bytes(text.replace(search, replace).replace("\n", newline).encode("utf-8"))

    target = _inside(repo, test_path)
    if target.exists():
        raise EditError(f"new_test.path already exists (existing tests are locked): {test_path}")
    if not (target.name.startswith("test_") and target.suffix == ".py"):
        raise EditError(f"new_test.path must be a new file named test_*.py, got {test_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(test_content, encoding="utf-8", newline="\n")
    originals[test_path] = None
    return originals


def _imports(tree):
    """{(module, name or None, level)} for every import statement in the tree."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {(a.name, None, 0) for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found |= {(node.module or "", a.name, node.level) for a in node.names}
    return found


def _module_file(root, dotted):
    base = Path(root).joinpath(*dotted.split(".")) if dotted else Path(root)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if dotted and candidate.is_file():
            return candidate
    return base if base.is_dir() else None  # namespace package / bare directory


def _defines(module_file, name):
    """Does this repo module define `name` at top level (or have it as a submodule)?"""
    if module_file.is_dir():
        return _module_file(module_file, name) is not None
    if module_file.name == "__init__.py" and _module_file(module_file.parent, name):
        return True
    tree = ast.parse(module_file.read_text(encoding="utf-8", errors="replace"))
    names = set()
    for node in ast.walk(tree):  # walk, so names defined under if/try at module level count too
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if any(a.name == "*" for a in node.names):
                return True  # star import: cannot know statically
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return name in names or "__getattr__" in names


def check(repo, originals, python, run_dir):
    """Syntax-check changed files and verify every NEW import really exists.

    Returns the list of verified imports for the report. Raises EditError otherwise.
    """
    # ponytail: imports only, not every attribute/call; the full test run catches invented calls
    # at runtime. Upgrade path: resolve called names against the repo map.
    repo, verified = Path(repo), []
    for rel, old in originals.items():
        if not rel.endswith(".py"):
            continue
        path = repo / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            raise EditError(f"syntax error in {rel} line {e.lineno}: {e.msg}")
        before = _imports(ast.parse(old)) if old else set()
        for module, name, level in sorted(_imports(tree) - before, key=str):
            label = "." * level + module + (f".{name}" if name else "")
            if level:  # relative import: resolve from the file's own package
                roots = [path.parents[level - 1]]
            else:
                roots = [repo, repo / "src", path.parent]
            top = module.split(".")[0]
            if not level and top in sys.stdlib_module_names:
                verified.append(f"{label} (stdlib)")
                continue
            module_file = next((m for m in (_module_file(r, module) for r in roots) if m), None)
            if level and not module:
                module_file = roots[0]
            if module_file:
                if name and name != "*" and not _defines(module_file, name):
                    raise EditError(f"{rel}: `{name}` is not defined in repo module `{module or '.'}`; "
                                    "use only names that exist")
                verified.append(f"{label} (repo)")
                continue
            probe = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)"
            try:
                installed = not level and subprocess.run(
                    [str(python), "-c", probe, top], cwd=run_dir, capture_output=True, timeout=60).returncode == 0
            except subprocess.TimeoutExpired:
                installed = False
            if not installed:
                raise EditError(f"{rel}: import `{label}` does not exist in the standard library, "
                                "the repository or the installed packages; do not invent imports")
            verified.append(f"{label} (installed package)")
    return verified
