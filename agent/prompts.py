"""The two prompts. The first line of each is the step marker the fake LLM keys on."""

LOCALIZE = """STEP: localize
You are a careful software engineer working on an existing Python repository.
Choose the files that must be read to carry out the task.

TASK:
{task}

REPO MAP (path: top-level functions and classes):
{repo_map}

TESTS FAILING BEFORE ANY CHANGE:
{failures}

Return JSON: {{"files": ["path", ...]}}
- At most 5 paths, copied exactly from the repo map, most relevant first.
- Include the source file(s) that need to change and the closest existing test file
  (so a new test can copy its import style and fixtures).
"""

EDIT = """STEP: edit
You are a careful software engineer working on an existing Python repository.
Make the smallest change that completes the task, and add one new test file that proves it.

TASK:
{task}

FILES:
{files}

{feedback}
Return JSON:
{{"explanation": "what was wrong and what you changed, 2-4 sentences",
  "edits": [{{"path": "file to change", "search": "exact text to find", "replace": "new text"}}],
  "new_test": {{"path": "tests dir/test_<something new>.py", "content": "full file content"}}}}

Rules (checked by code; a violation rejects the whole attempt):
- "search" must be copied character for character from the file shown above, including
  indentation, and must occur exactly once in that file. Keep it short but unique.
- Change as few lines as possible. Do not reformat, rename or refactor anything else.
- Do NOT edit existing test files or conftest.py. Put the new test in a NEW file next to the
  existing tests, named test_*.py, written in the same style (same imports and fixtures;
  copy any fixture you need into the new file).
- Use only modules, functions and names that exist in the files shown above or in the Python
  standard library. Do not invent imports or APIs.
- The new test must fail on the current code and pass after your edit.
- Every test that passes now must still pass.
"""


def localize(task, repo_map, failures):
    return LOCALIZE.format(task=task, repo_map=repo_map, failures=failures or "(none)")


def edit(task, files, feedback):
    blocks = "\n\n".join(f"=== {path} ===\n{content}" for path, content in files.items())
    if feedback:
        feedback = f"YOUR PREVIOUS ATTEMPT WAS REJECTED AND REVERTED. Fix this:\n{feedback}\n"
    return EDIT.format(task=task, files=blocks, feedback=feedback)
