# PSI09 AI Software Engineering Agent

HackNEX problem HNX26PSI09. Give it a Python repository and a task in plain text. It finds the
right file, makes a small change, adds a test, and proves with before/after test runs that
nothing that worked before is broken.

## What it does

```
repo + task -> working copy on a new branch -> baseline pytest -> repo map
            -> LLM picks files -> LLM proposes edit + new test
            -> code applies and checks it -> full pytest again -> compare
            -> keep (commit + report) or revert and retry (max 3)
```

Ordinary code runs every step. The LLM is used in exactly two bounded calls (pick files, propose an
edit) and never touches the repository directly. Code, not the prompt, enforces the two rules that
cost the most points:

- **Existing tests must still pass.** Every test that passed at baseline must pass after the change,
  or the change is reverted. Existing test files and `conftest.py` are locked; the agent can only add
  a new test file.
- **No made-up APIs or imports.** Every new import is verified to exist in the standard library, the
  repository (including the imported name), or the installed packages. Otherwise the attempt is rejected.

## Technologies, models and components (declaration)

| Component | Use |
| --- | --- |
| Python 3.11+ (stdlib: `subprocess`, `venv`, `ast`, `xml.etree`) | the agent itself |
| Git | working copy, branch, diff, revert |
| pytest | runs the target repository's tests and our own |
| Google Gemini API (`google-genai`), models set by `GEMINI_MODEL` (`gemini-3.7-flash`, fallback `gemini-3.5-flash-lite`) | the LLM, hosted, pre-trained, not fine-tuned |
| FastAPI + uvicorn | local API and static file server |
| python-dotenv | loads `.env` |
| Plain HTML/CSS/JS | web page, no build step, no CDN |

No datasets. No agent framework. AI coding tools were used to write this code; the team reviewed it.

## Install

Windows, Python 3.11+ and Git on PATH.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

## Configure

Edit `.env` (it is gitignored; never commit it):

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | key from Google AI Studio (aistudio.google.com, "Get API key") |
| `GEMINI_MODEL` | Gemini model id; a comma-separated list adds fallbacks tried when a model is overloaded or out of quota |
| `LLM_PROVIDER` | `gemini`, or `fake` for scripted offline responses (works only on `sample_repo`) |
| `MAX_ATTEMPTS` | edit retry cap (default 3) |
| `TEST_TIMEOUT` | seconds before a test run is killed (default 300) |

## Run

Web page:

```
.venv\Scripts\python server.py
```

then open http://127.0.0.1:8000. The server binds to 127.0.0.1 only, because it executes the test
suite of whatever repository it is given. Only point it at repositories you trust.

Command line:

```
.venv\Scripts\python cli.py sample_repo "login fails when the email has capital letters"
.venv\Scripts\python cli.py https://github.com/someone/somerepo.git "describe the bug or feature"
```

Our own tests (offline, fake LLM, about 2 minutes because each builds a real venv):

```
.venv\Scripts\python -m pytest tests -q
```

## Reproduce the demonstrated result

`sample_repo/` is "tinyauth", a small auth module with a real bug: `register()` stores emails
lowercased, `login()` looks them up as typed, so `Alice@Example.com` cannot log in. Its 6 tests pass
and do not cover the bug.

**Input**

- repo: `sample_repo`
- task: `login fails when the email has capital letters`

**Output** (`runs/<id>/report.md`, also shown in the CLI and web page)

```
[ ok] prepare: working copy on branch agent/8aa786d6
[ ok] environment: venv ready
[ ok] baseline: 6 passed, 0 failed, 6 total
[ ok] map: 5 Python files
[ ok] localize: auth/login.py, auth/users.py, tests/test_login.py
[ ok] edit #1: 2 files written, imports verified
[ ok] verify #1: 7 passed, 0 failed, 0 regressions
[ ok] report: runs\8aa786d6\report.md

STATUS: success
baseline: 6 passed, 0 failed, 6 total
after:    7 passed, 0 failed, 7 total
regressions: 0  new tests: 1  attempts: 1

 def login(email, password):
-    user = get_user(email)
+    user = get_user(email.strip().lower())
```

plus one new file, `tests/test_login_email_case.py`. Your checked-out files are not modified. The change is committed on branch `agent/<id>` inside `runs/<id>/repo` and, if the repository is a local git repo, also on a branch named `agent-changes` in that repo (review with `git diff HEAD...agent-changes`, then open a PR). For a git URL the `agent-changes` branch is in the local clone and the report shows the push command.

## Data pipeline

1. **Input**: repository (local folder or git URL) and task text, from the web form or the CLI.
2. **prepare** (`agent/repo.py`): copy or clone into `runs/<id>/repo`, create branch `agent/<id>`.
3. **environment** (`agent/runner.py`): fresh venv in `runs/<id>/venv`, install pytest and the
   repository's `requirements.txt` / package. If this fails the run stops as `env_failed` with the
   real pip output; the agent does not guess.
4. **baseline**: full pytest run, parsed from JUnit XML into `{test id: passed|failed|error|skipped}`.
5. **map**: every Python file with its functions and classes, built with `ast`.
6. **localize** (LLM call 1, `agent/prompts.py`): task + map + baseline failures -> up to 5 file
   paths. Paths that do not exist are dropped.
7. **edit** (LLM call 2): task + those files' contents (+ the previous rejection, on a retry) ->
   JSON `{explanation, edits: [{path, search, replace}], new_test: {path, content}}`.
8. **apply + check** (`agent/edits.py`): test lock, search text must match exactly once, syntax
   check, import existence check.
9. **verify**: full pytest run again, compared per test with the baseline.
10. **decide** (`agent/pipeline.py`): any rule violation, regression, or failing new test -> `git`
    revert, and the error text goes back into step 7 (at most `MAX_ATTEMPTS` times). Otherwise commit.
11. **report** (`agent/report.py`): `runs/<id>/report.md` with the explanation, before/after table,
    regressions, new tests, verified imports, steps and diff.

## Core reasoning mechanism

A fixed pipeline with a bounded LLM loop ("Design B" in our brief), not a free agent loop. The model
reasons only about *which files* and *what edit*; branching, baseline, comparison, the retry cap and
revert are plain code a weak model cannot skip. A scripted fake LLM (`LLM_PROVIDER=fake`,
`tests/fake_llm_tinyauth.json`) drives the whole pipeline offline, so a failure can be traced to our
code or to the model.

## Code map

| Path | Role |
| --- | --- |
| `agent/pipeline.py` | the whole flow in one file: step order, retry loop, revert rule |
| `agent/repo.py` | git working copy, branch, revert, commit, repo map |
| `agent/runner.py` | venv, dependency install, pytest, JUnit parsing, regression compare |
| `agent/edits.py` | apply edits; test lock; syntax and import existence checks |
| `agent/llm.py` | the only file that talks to Gemini (or the fake) |
| `agent/prompts.py` | the two prompts |
| `agent/report.py` | writes `report.md` |
| `server.py`, `frontend/` | API (`POST /api/run`, `GET /api/run/{id}`) and web page |
| `cli.py` | same pipeline from a terminal |
| `sample_repo/` | demo repository with a known bug |
| `tests/` | end-to-end and safety-rule tests |

## Scope

**Minimum viable solution (built):** Python + pytest repositories; plain-text tasks; working copy on
a new branch; baseline vs after comparison per test; locked existing tests; new test in a new file;
import existence check; retry cap with revert; `env_failed` / `failed` outcomes that never leave a
half-applied change; CLI, API, web page, report file; fake LLM mode.

**Known limits:** the import check covers imports, not every attribute or function call (the full
test run catches most invented calls at runtime). Tests are run once, so a flaky test can look like a
regression. A repository with no tests has no baseline; the report says so. Local repositories are
snapshotted without their git history.

**Stretch goals (not built):** JavaScript (`npm test`) adapter; proving the new test fails before the
fix; rerunning failed tests once as a flaky guard; keyword-search fallback for localization; fetching
GitHub issue links; opening pull requests.
