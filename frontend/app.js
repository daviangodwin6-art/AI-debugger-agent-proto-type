"use strict";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// All API strings are untrusted: only ever assigned via textContent.
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    throw new Error("Network error: could not reach the server.");
  }
  let body = null;
  try { body = await res.json(); } catch (e) { /* non-JSON body */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(d ? (typeof d === "string" ? d : JSON.stringify(d)) : "Request failed (HTTP " + res.status + ")");
  }
  if (!body) throw new Error("Server returned an unreadable response.");
  return body;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
}

function fillList(ul, items) {
  const list = Array.isArray(items) ? items : [];
  ul.replaceChildren(...(list.length ? list.map((t) => el("li", String(t))) : [el("li", "none", "muted")]));
}

function setBadge(status) {
  const badge = $("status-badge");
  badge.textContent = String(status).replace("_", " ");
  badge.className = "badge " + (["running", "success", "failed", "env_failed"].includes(status) ? status : "");
}

function renderSteps(steps) {
  const marks = { running: "…", ok: "✓", error: "✗" };
  $("steps").replaceChildren(...(steps || []).map((s) => {
    const li = el("li", undefined, "step " + (marks[s.status] ? s.status : ""));
    li.append(
      el("span", marks[s.status] || "?", "mark"),
      el("span", s.name, "step-name"),
      el("span", s.detail || "", "step-detail"),
      el("span", " (" + s.status + ")", "sr-only")
    );
    return li;
  }));
}

function renderDiff(diff) {
  $("diff").replaceChildren(...diff.split("\n").map((line) => {
    let cls = "";
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
    return el("span", line || " ", cls); // " " keeps blank lines one line tall
  }));
}

function renderResult(run) {
  const r = run.result || {};
  const base = r.baseline || {};
  const after = r.after || {};
  const num = (v) => String(v ?? 0);

  $("b-passed").textContent = num(base.passed);
  $("b-failed").textContent = num(base.failed);
  $("b-total").textContent = num(base.total);
  $("a-passed").textContent = num(after.passed);
  $("a-failed").textContent = num(after.failed);
  $("a-total").textContent = num(after.total);
  $("a-failed").className = after.failed > 0 ? "bad-text" : "";
  $("b-failed").className = base.failed > 0 ? "bad-text" : "";

  // Don't claim a green "0 regressions" when the after-run never happened.
  const regs = Array.isArray(r.regressions) ? r.regressions : [];
  const ran = run.status !== "env_failed" && (after.total > 0 || regs.length > 0);
  $("regressions").className = "regressions " + (!ran ? "unknown" : regs.length ? "bad" : "good");
  $("regressions-count").textContent = ran ? "Regressions: " + regs.length : "Regressions: n/a";
  $("regressions-list").replaceChildren(
    ...(ran ? regs.map((t) => el("li", String(t))) : [el("li", "tests did not run")])
  );

  $("explanation").textContent = r.explanation || "(none)";
  fillList($("new-tests"), r.new_tests);
  fillList($("import-check"), r.import_check);
  fillList($("files-changed"), r.files_changed);
  $("branch").textContent = r.branch || "-";
  $("attempts").textContent = num(r.attempts);
  $("report-path").textContent = r.report_path || "-";

  $("note-block").textContent = r.note ? "Note: " + r.note : "";
  $("note-block").hidden = !r.note;
  $("result-error").textContent = r.error || "";
  $("error-block").hidden = !r.error;
  renderDiff(r.diff || "");
  $("diff-block").hidden = !r.diff;

  $("result").hidden = false;
}

async function startRun(repo, task) {
  const btn = $("run-btn");
  btn.disabled = true;
  btn.textContent = "Running…";
  showError("");
  $("result").hidden = true;
  $("run-section").hidden = true;
  try {
    const { id } = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo, task }),
    });
    $("run-id").textContent = id;
    setBadge("running");
    renderSteps([]);
    $("run-section").hidden = false;

    for (;;) {
      const run = await api("/api/run/" + encodeURIComponent(id));
      setBadge(run.status);
      renderSteps(run.steps);
      if (run.status !== "running") {
        renderResult(run);
        break;
      }
      await sleep(1000);
    }
  } catch (e) {
    showError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run";
  }
}

$("run-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  if ($("run-btn").disabled) return;
  startRun($("repo").value.trim(), $("task").value.trim());
});
