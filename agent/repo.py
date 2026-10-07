"""Git working copy and repo map. Deterministic, no LLM."""
import ast
import os
import shutil
import subprocess
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".tox", "build", "dist"}
# Never let test-run leftovers into the diff, whatever the target's .gitignore says.
EXCLUDES = "__pycache__/\n.pytest_cache/\n*.pyc\n*.egg-info/\n"


def git(args, cwd, check=True):
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "user.name=agent", "-c", "user.email=agent@localhost", *args]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", timeout=300,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{p.stdout}{p.stderr}")
    return p.stdout


def is_url(src):
    return src.startswith(("http://", "https://", "git@", "file://")) or src.endswith(".git")


def prepare(src, run_dir, run_id):
    """Copy or clone src to run_dir/repo on a new branch. The original is never touched."""
    dest = Path(run_dir) / "repo"
    if is_url(src):
        git(["clone", "--depth", "1", src, str(dest)], cwd=run_dir)
    else:
        if not Path(src).is_dir():
            raise RuntimeError(f"repo not found: {src}")
        # ponytail: local repos are snapshotted (history dropped); clone them if history ever matters
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        git(["init", "-q"], cwd=dest)
        git(["add", "-A"], cwd=dest)
        git(["commit", "-q", "--allow-empty", "-m", "baseline snapshot"], cwd=dest)
    (dest / ".git" / "info").mkdir(exist_ok=True)
    (dest / ".git" / "info" / "exclude").write_text(EXCLUDES, encoding="utf-8")
    branch = f"agent/{run_id}"
    git(["checkout", "-q", "-b", branch], cwd=dest)
    return dest, branch


def revert(repo):
    git(["checkout", "-q", "--", "."], cwd=repo)
    git(["clean", "-fdq"], cwd=repo)


def commit(repo, message):
    """Commit everything on the branch; return (diff, files_changed)."""
    git(["add", "-A"], cwd=repo)
    diff = git(["diff", "--cached"], cwd=repo)
    files = git(["diff", "--cached", "--name-only"], cwd=repo).split()
    git(["commit", "-q", "-m", message], cwd=repo)
    return diff, files


PUBLISH_BRANCH = "agent-changes"


def _commit_on_branch(root, clone, files, message, work, new_from=None):
    """Copy the changed files onto branch `agent-changes` in repo `root` via a temporary worktree."""
    args = ["-b", PUBLISH_BRANCH, new_from] if new_from else [PUBLISH_BRANCH]
    git(["worktree", "add", "-q", str(work), *args], cwd=root)
    try:
        for rel in files:
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(clone) / rel, work / rel)
        git(["add", "-A"], cwd=work)
        if git(["status", "--porcelain"], cwd=work).strip():  # a repeat of an identical change adds nothing
            git(["commit", "-q", "-m", message], cwd=work)
    finally:
        git(["worktree", "remove", "--force", str(work)], cwd=root, check=False)


def publish(src, clone, files, task, run_dir):
    """Put the committed change on branch `agent-changes`, PR-ready. Returns a one-line note.

    Local git repo: the branch is created (or extended) in the user's own repo through a
    temporary worktree, so their checked-out files are never touched.
    Git URL: the branch is built in the clone (on top of the remote `agent-changes` if it exists)
    and pushed to origin. Only that branch is pushed, never the default branch, never forced.
    """
    message = f"agent: {task[:60]}"
    work = Path(run_dir) / "publish"
    if is_url(src):
        manual = f'git -C "{clone}" push origin {PUBLISH_BRANCH}'
        # ponytail: shallow fetch of the existing branch; later runs stack on it instead of diverging
        git(["fetch", "--depth=1", "origin", f"{PUBLISH_BRANCH}:refs/heads/{PUBLISH_BRANCH}"],
                      cwd=clone, check=False)
        has_remote = git(["rev-parse", "--verify", "-q", PUBLISH_BRANCH], cwd=clone, check=False).strip()
        if has_remote:
            _commit_on_branch(clone, clone, files, message, work)
        else:
            git(["branch", "-f", PUBLISH_BRANCH, "HEAD"], cwd=clone)
        try:
            git(["push", "origin", PUBLISH_BRANCH], cwd=clone)
        except RuntimeError as e:
            return (f"Branch `{PUBLISH_BRANCH}` is committed in the local clone {clone} but the push failed "
                    f"(needs git credentials with write access): {str(e)[-300:]}\nRetry with: {manual}")
        web = src.removesuffix(".git") if src.startswith("https://") else src
        return f"Pushed branch `{PUBLISH_BRANCH}` to {src}. Open a PR: {web}/compare/{PUBLISH_BRANCH}"
    src = Path(src).resolve()
    top = git(["rev-parse", "--show-toplevel"], cwd=src, check=False).strip()
    if not top or Path(top).resolve() != src:
        return (f"{src} is not the root of a git repository, so no `{PUBLISH_BRANCH}` branch was created. "
                f"The change is committed in {clone}")
    # ponytail: copies the changed files over the branch tip (no 3-way merge); fine because the agent
    # only adds/edits files. Revisit if runs on a branch with divergent edits to the same file matter.
    exists = git(["rev-parse", "--verify", "-q", PUBLISH_BRANCH], cwd=src, check=False).strip()
    _commit_on_branch(src, clone, files, message, work, None if exists else "HEAD")
    return f"Committed to branch `{PUBLISH_BRANCH}` in {src}. Review: git diff HEAD...{PUBLISH_BRANCH}"

def py_files(repo):
    repo = Path(repo)
    for p in sorted(repo.rglob("*.py")):
        if not SKIP_DIRS & set(p.relative_to(repo).parts):
            yield p


def repo_map(repo, cap=12000):
    """One line per Python file: path and its top-level functions/classes (with methods)."""
    lines = []
    for p in py_files(repo):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            # A file that does not parse is often the very bug to fix; show it, don't hide it.
            lines.append(f"{p.relative_to(repo).as_posix()}: SYNTAX ERROR line {e.lineno}: {e.msg}")
            continue
        names = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(f"{node.name}()")
            elif isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                names.append(f"class {node.name}({', '.join(methods)})")
        lines.append(f"{p.relative_to(repo).as_posix()}: {', '.join(names)}")
    # ponytail: hard character cap; rank files by relevance to the task if big repos get cut off
    return "\n".join(lines)[:cap]
