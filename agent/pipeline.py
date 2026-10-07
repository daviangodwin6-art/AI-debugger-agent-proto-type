"""The fixed pipeline. Step order, the retry cap and the revert rule live here, in plain code.

prepare -> environment -> baseline -> map -> localize (LLM) -> [edit (LLM) -> apply+check -> verify]
x MAX_ATTEMPTS -> report
"""
import os
import uuid
from pathlib import Path

from . import edits, llm, prompts, report, runner
from . import repo as repo_mod

RUNS_DIR = Path(__file__).parent.parent / "runs"
FILE_CAP = 12000  # characters of one file shown to the LLM
LOG_CAP = 3000    # characters of test output fed back to the LLM
ZERO = {"passed": 0, "failed": 0, "total": 0}


def run(repo_src, task, on_step=None, run_id=None, runs_dir=None):
    """Run the whole pipeline. Returns the state dict (same shape as GET /api/run/{id})."""
    run_id = run_id or uuid.uuid4().hex[:8]
    run_dir = Path(runs_dir or RUNS_DIR) / run_id
    state = {"id": run_id, "status": "running", "steps": [], "result": {
        "explanation": "", "files_changed": [], "diff": "", "branch": "", "attempts": 0,
        "baseline": dict(ZERO), "after": dict(ZERO), "regressions": [], "new_tests": [],
        "import_check": [], "note": "", "error": "", "report_path": str(run_dir / "report.md")}}
    notify = lambda: on_step and on_step(state)

    def step(name):
        state["steps"].append({"name": name, "status": "running", "detail": ""})
        notify()

    def done(detail="", status="ok"):
        state["steps"][-1].update(status=status, detail=detail)
        notify()

    try:
        run_dir.mkdir(parents=True)
        state["status"] = _run(str(repo_src), task, run_id, run_dir, state["result"], step, done)
    except runner.EnvError as e:
        state["status"], state["result"]["error"] = "env_failed", str(e)
    except Exception as e:  # LLM errors, git errors, bugs: always end in a reported state
        state["status"], state["result"]["error"] = "failed", f"{type(e).__name__}: {e}"
    if state["steps"] and state["steps"][-1]["status"] == "running":
        done(state["result"]["error"][:300], "error")
    if run_dir.is_dir():
        report.write(state, task, repo_src)
    notify()
    return state


def _run(repo_src, task, run_id, run_dir, result, step, done):
    step("prepare")
    repo, result["branch"] = repo_mod.prepare(repo_src, run_dir, run_id)
    done(f"working copy on branch {result['branch']}")

    step("environment")
    python, warning = runner.setup_env(repo, run_dir)
    done(warning or "venv ready")

    step("baseline")
    before, out = runner.run_tests(python, repo, run_dir, "baseline")
    result["baseline"] = runner.counts(before)
    if not before:
        result["note"] = "No tests found at baseline; the new test is the only evidence."
    failing = sorted(t for t, s in before.items() if s in ("failed", "error"))
    done("{passed} passed, {failed} failed, {total} total".format(**result["baseline"]))

    step("map")
    repo_map = repo_mod.repo_map(repo)
    if not repo_map:
        raise RuntimeError("no Python files found in the repository")
    done(f"{len(repo_map.splitlines())} Python files")

    step("localize")
    failures = "\n".join(failing) + ("\n" + out[-LOG_CAP:] if failing else "")
    paths = []
    for _ in range(2):  # one retry if the model names nothing usable
        try:
            answer = llm.complete_json(prompts.localize(task, repo_map, failures)).get("files", [])
        except ValueError:
            continue
        # Only paths that really exist inside the working copy survive.
        paths = [p for p in answer if isinstance(p, str) and (repo / p).is_file()
                 and (repo / p).resolve().is_relative_to(repo.resolve())][:5]
        if paths:
            break
    if not paths:
        raise RuntimeError("localize step returned no files that exist in the repository")
    files = {p: (repo / p).read_text(encoding="utf-8", errors="replace")[:FILE_CAP] for p in paths}
    done(", ".join(paths))

    feedback = ""
    for attempt in range(1, int(os.getenv("MAX_ATTEMPTS", "3")) + 1):
        result["attempts"] = attempt
        step(f"edit #{attempt}")
        try:
            proposal = llm.complete_json(prompts.edit(task, files, feedback))
            originals = edits.apply(repo, proposal)
            result["import_check"] = edits.check(repo, originals, python, run_dir)
        except (edits.EditError, ValueError) as e:
            feedback = f"Rejected before running tests: {e}"
            repo_mod.revert(repo)
            done(feedback[:300], "error")
            continue
        done(f"{len(originals)} files written, imports verified")

        step(f"verify #{attempt}")
        try:
            after, out = runner.run_tests(python, repo, run_dir, f"attempt{attempt}")
        except runner.EnvError as e:
            feedback = f"The test run broke after your edit: {e}"
            repo_mod.revert(repo)
            done(feedback[:300], "error")
            continue
        result["after"] = runner.counts(after)
        result["regressions"] = runner.compare(before, after)
        result["new_tests"] = sorted(t for t in after if t not in before)
        new_failing = [t for t in result["new_tests"] if after[t] != "passed"]
        if result["regressions"]:
            feedback = f"Your edit broke tests that passed before: {result['regressions']}"
        elif new_failing:
            feedback = f"Your new test does not pass: {new_failing}"
        elif not result["new_tests"]:
            feedback = "Your new test file added no collected tests."
        else:
            done("{passed} passed, {failed} failed, 0 regressions".format(**result["after"]))
            step("report")
            result["explanation"] = str(proposal.get("explanation", ""))
            result["diff"], result["files_changed"] = repo_mod.commit(repo, f"agent: {task[:60]}")
            try:
                result["note"] = (result["note"] + "\n" + repo_mod.publish(
                    repo_src, repo, result["files_changed"], task, run_dir)).strip()
            except Exception as e:  # the verified change is already committed; don't fail the run over this
                result["note"] = (result["note"] + f"\nCould not create branch `agent-changes`: {e}").strip()
            done(result["report_path"])
            return "success"
        feedback += f"\n\nTest output (end):\n{out[-LOG_CAP:]}"
        repo_mod.revert(repo)
        done(feedback[:300], "error")

    result["error"] = f"No acceptable change after {result['attempts']} attempts; working copy reverted. Last problem:\n{feedback}"
    return "failed"
