"""python cli.py <repo path or git URL> "<task text>" """
import sys

from agent import pipeline


def show(state):
    last = state["steps"][-1] if state["steps"] else None
    if last and last["status"] != "running":
        print(f"[{last['status']:>5}] {last['name']}: {last['detail']}", flush=True)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    seen = set()

    def on_step(state):  # the pipeline notifies more than once per step; print each step once
        key = (len(state["steps"]), state["steps"][-1]["status"] if state["steps"] else "")
        if key not in seen:
            seen.add(key)
            show(state)

    state = pipeline.run(sys.argv[1], sys.argv[2], on_step=on_step)
    r = state["result"]
    print(f"\nSTATUS: {state['status']}")
    print("baseline: {passed} passed, {failed} failed, {total} total".format(**r["baseline"]))
    print("after:    {passed} passed, {failed} failed, {total} total".format(**r["after"]))
    print(f"regressions: {len(r['regressions'])}  new tests: {len(r['new_tests'])}  attempts: {r['attempts']}")
    if r["explanation"]:
        print(f"\n{r['explanation']}")
    if r["diff"]:
        print(f"\n{r['diff']}")
    if r["error"]:
        print(f"\nERROR: {r['error']}")
    print(f"\nreport: {r['report_path']}")
    sys.exit(0 if state["status"] == "success" else 1)


if __name__ == "__main__":
    main()
