"""FastAPI server: POST /api/run, GET /api/run/{id}, static frontend. Run: python server.py"""
import threading
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from agent import pipeline
from agent.repo import is_url

app = FastAPI()
RUNS = {}  # ponytail: in-memory, lost on restart; reports persist in runs/<id>/report.md


@app.post("/api/run")
def start_run(body: dict = Body(...)):
    repo, task = str(body.get("repo") or "").strip(), str(body.get("task") or "").strip()
    if not repo or not task:
        raise HTTPException(400, "Both a repository and a task are required.")
    if not is_url(repo) and not Path(repo).is_dir():
        raise HTTPException(400, f"Repository not found: {repo} (give a folder path or a git URL).")
    run_id = uuid.uuid4().hex[:8]
    RUNS[run_id] = {"id": run_id, "status": "running", "steps": [], "result": {}}
    threading.Thread(target=pipeline.run, args=(repo, task),
                     kwargs={"run_id": run_id, "on_step": lambda s: RUNS.__setitem__(run_id, s)},
                     daemon=True).start()
    return {"id": run_id}


@app.get("/api/run/{run_id}")
def get_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run id.")
    return RUNS[run_id]


app.mount("/", StaticFiles(directory=Path(__file__).parent / "frontend", html=True))

if __name__ == "__main__":
    import uvicorn

    # 127.0.0.1 only: this server executes the test suites of whatever repo it is given.
    uvicorn.run(app, host="127.0.0.1", port=8000)
