"""State dict -> runs/<id>/report.md (the evidence file for the submission)."""
from pathlib import Path


def write(state, task, repo_src):
    r = state["result"]
    bullets = lambda items: "\n".join(f"- `{i}`" for i in items) or "- none"
    text = f"""# Agent run {state['id']}: {state['status'].upper()}

**Repository:** `{repo_src}`
**Branch:** `{r['branch']}`
**Attempts:** {r['attempts']}

## Task
{task}

## Explanation
{r['explanation'] or '(none)'}

## Tests before and after
| | Passed | Failed | Total |
| --- | --- | --- | --- |
| Baseline | {r['baseline']['passed']} | {r['baseline']['failed']} | {r['baseline']['total']} |
| After | {r['after']['passed']} | {r['after']['failed']} | {r['after']['total']} |

**Regressions (passed before, not passing now): {len(r['regressions'])}**
{bullets(r['regressions'])}
{r['note']}

## New tests
{bullets(r['new_tests'])}

## New imports verified to exist
{bullets(r['import_check'])}

## Files changed
{bullets(r['files_changed'])}

## Steps
""" + "\n".join(f"- {s['name']}: {s['status']} {s['detail']}" for s in state["steps"])
    if r["error"]:
        text += f"\n\n## Error\n```\n{r['error']}\n```"
    if r["diff"]:
        text += f"\n\n## Diff\n```diff\n{r['diff']}\n```"
    Path(r["report_path"]).write_text(text + "\n", encoding="utf-8")
