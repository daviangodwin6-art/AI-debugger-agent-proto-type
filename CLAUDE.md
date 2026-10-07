# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Prototype for HackNEX problem PSI09: given a Python repo and a plain-text task, make a minimal fix,
add a test, and prove zero regressions with before/after pytest runs. The brief
(`PSI09 AI Software Engineering Agent Team Brief.docx`) is the source of truth for scoring; the two
rules that cost the most are "existing tests must still pass" and "no made-up APIs or imports".

Windows, Python 3.11+, pytest targets only. Dependencies are limited to fastapi, uvicorn,
google-genai, python-dotenv, pytest; don't add more, or new files/folders, without saying why.

## Commands

Use the project venv (`.venv\Scripts\python`).

- All tests (offline, fake LLM, ~2.5 min): `.venv\Scripts\python -m pytest tests -q`
- Fast tests only (safety rules, <1 s): `.venv\Scripts\python -m pytest tests/test_edits.py -q`
- Single test: `.venv\Scripts\python -m pytest tests/test_pipeline.py::test_login_case -q`
- CLI run: `.venv\Scripts\python cli.py sample_repo "login fails when the email has capital letters"`
- Server: `.venv\Scripts\python server.py`, then http://127.0.0.1:8000 (also `.claude/launch.json` → `agent-server`)

Never run `pytest` from the root without the `tests` argument: it would collect `sample_repo/` and `runs/`.

`tests/test_pipeline.py` is slow because every test builds a real venv and pip-installs pytest into
it (needs network or a warm pip cache).

There is no linter or build step.

## Architecture

A fixed pipeline ("Design B" in the brief), not a free agent loop. Plain code runs every step; the
LLM is used in exactly two bounded calls and never touches the repo directly.

```
prepare -> environment -> baseline -> map -> localize (LLM) -> [edit (LLM) -> apply+check -> verify] x MAX_ATTEMPTS -> report
```

- `agent/pipeline.py` is the only orchestrator: step order, retry cap, and the revert-on-failure rule.
  `run()` returns a state dict `{id, status, steps, result}` that **is** the `GET /api/run/{id}`
  response; `frontend/app.js` renders it directly. Every `result` key is pre-filled with an empty
  default at the start of a run. Changing that shape means changing `pipeline.py`, `report.py`,
  `cli.py` and `frontend/app.js` together.
- Outcomes: `success`, `failed` (no acceptable edit, or an LLM/git error), `env_failed`
  (`runner.EnvError`: venv, dependency install, or pytest itself could not run). A run must always end
  in one of these with the working copy either committed or reverted, never half-applied.
- `agent/repo.py`, `agent/runner.py`, `agent/edits.py` are deterministic (git, pytest, apply/verify)
  and contain no LLM calls. `runner.py` is the only Python/pytest-specific file; a JS adapter would
  replace it.
- `agent/edits.py` holds the safety rules, enforced in code rather than in the prompt: existing test
  files and `conftest.py` are locked, search text must match exactly once, the new test must be a new
  `test_*.py` file, changed files must parse, and every *new* import must resolve to stdlib, a repo
  module (including the imported name), or a package installed in the run venv. An `EditError`
  message is fed back to the LLM as the next attempt's feedback, so keep those messages instructive.
- `agent/llm.py` is the only file that knows about the provider or reads `GEMINI_API_KEY`.
  `LLM_PROVIDER=fake` returns scripted responses from `tests/fake_llm_tinyauth.json` (override with
  `FAKE_LLM_FILE`), selected by the prompt's first line (`STEP: localize` / `STEP: edit`). That first
  line in `agent/prompts.py` is therefore load-bearing. Fake mode only makes sense against `sample_repo`.
- `server.py` runs the pipeline in a thread and keeps runs in an in-memory dict. It binds to
  127.0.0.1 on purpose, because it executes the test suite of whatever repo it is given.

### Where a run lives

Each run gets `runs/<id>/` (gitignored): `repo/` (the working copy, its own git repo on branch
`agent/<id>`), `venv/`, `junit_*.xml`, and `report.md`. The source repo's checked-out files are never modified; local
folders are copied without their `.git` and re-initialised. On success `repo.publish()` also adds the commit to branch `agent-changes` in the user's own repo (via a temporary worktree), or, for git URLs, in the clone only (pushing is left to the user).

Because working copies sit inside this project, the project root must **not** contain a
`pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg` or `conftest.py`: pytest in the working copy
would inherit them.

### sample_repo

`sample_repo/` (tinyauth) is the demo target and the judge case. Its bug is deliberate:
`register()` lowercases emails, `login()` looks them up as typed. Do not fix it, add hints to it, or
add tests there that cover it; `tests/test_pipeline.py` asserts its exact test counts (6 before, 7 after)
and `tests/fake_llm_tinyauth.json` contains a search string copied from `auth/login.py`.

## Conventions

- Subprocess calls use argument lists (no shell strings), `encoding="utf-8", errors="replace"`, and
  always a timeout. Git goes through `repo.git()`, which pins `core.autocrlf=false` and a commit identity.
- Text shown to the LLM is truncated with fixed caps (`FILE_CAP`, `LOG_CAP` in `pipeline.py`, the
  repo map cap in `repo.py`).
- `# ponytail:` comments mark deliberate simplifications with their known ceiling and upgrade path.
- `.env` (key, model id, provider, `MAX_ATTEMPTS`, `TEST_TIMEOUT`) is loaded in `agent/__init__.py`;
  the settings are read at call time, so tests override them with `monkeypatch.setenv`.
