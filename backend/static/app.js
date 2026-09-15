(function () {
  "use strict";

  const POLL_MS = 2000;
  const ACTIVE = new Set(["pending", "running"]);

  const form = document.getElementById("task-form");
  const repoInput = document.getElementById("repository-url");
  const instructionInput = document.getElementById("instruction");
  const instructionCount = document.getElementById("instruction-count");
  const formError = document.getElementById("form-error");
  const submitBtn = document.getElementById("submit-btn");
  const refreshListBtn = document.getElementById("refresh-list-btn");

  const taskEmpty = document.getElementById("task-empty");
  const taskPanel = document.getElementById("task-panel");
  const taskStatus = document.getElementById("task-status");
  const taskIdEl = document.getElementById("task-id");
  const taskRepoEl = document.getElementById("task-repo");
  const taskCreatedEl = document.getElementById("task-created");
  const taskInstructionEl = document.getElementById("task-instruction");
  const taskResultWrap = document.getElementById("task-result-wrap");
  const taskResultEl = document.getElementById("task-result");
  const taskErrorWrap = document.getElementById("task-error-wrap");
  const taskErrorEl = document.getElementById("task-error");

  const toolCallsDetails = document.getElementById("tool-calls-details");
  const toolCallsMeta = document.getElementById("tool-calls-meta");
  const toolCallsTbody = document.getElementById("tool-calls-tbody");
  const toolCallsEmpty = document.getElementById("tool-calls-empty");

  const tasksTbody = document.getElementById("tasks-tbody");
  const tasksEmptyRow = document.getElementById("tasks-empty-row");

  let activeTaskId = null;
  let pollTimer = null;
  let toolCallsLoadedFor = null;

  function showFormError(msg) {
    if (msg) {
      formError.textContent = msg;
      formError.hidden = false;
    } else {
      formError.hidden = true;
      formError.textContent = "";
    }
  }

  function formatTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function shortRepo(url) {
    try {
      const u = new URL(url);
      return (u.pathname.replace(/^\//, "") || u.host).replace(/\.git$/, "");
    } catch {
      return url;
    }
  }

  function truncate(text, n) {
    if (!text) return "—";
    const oneLine = text.replace(/\s+/g, " ").trim();
    if (oneLine.length <= n) return oneLine;
    return oneLine.slice(0, n - 1) + "…";
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMarkdown(text) {
    if (window.marked && typeof window.marked.parse === "function") {
      taskResultEl.innerHTML = window.marked.parse(text || "");
    } else {
      taskResultEl.innerHTML = "<pre>" + escapeHtml(text || "") + "</pre>";
    }
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    let body = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      body = await res.json();
    } else {
      body = await res.text();
    }
    if (!res.ok) {
      const msg =
        (body && body.error && body.error.message) ||
        (body && body.detail) ||
        (typeof body === "string" ? body : null) ||
        "Request failed (" + res.status + ")";
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function setStatusBadge(status) {
    const value = status || "idle";
    taskStatus.textContent = value;
    taskStatus.className = "badge badge-" + value;
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(taskId) {
    stopPolling();
    pollTimer = setInterval(function () {
      refreshTask(taskId, { quiet: true });
    }, POLL_MS);
  }

  function clearToolCalls() {
    toolCallsLoadedFor = null;
    toolCallsDetails.hidden = true;
    toolCallsDetails.open = false;
    toolCallsMeta.textContent = "";
    toolCallsTbody.innerHTML = "";
    toolCallsEmpty.hidden = true;
  }

  function renderTask(task) {
    activeTaskId = task.task_id;
    taskEmpty.hidden = true;
    taskPanel.hidden = false;
    setStatusBadge(task.status);
    taskIdEl.textContent = task.task_id;
    taskRepoEl.textContent = task.repository_url;
    taskCreatedEl.textContent = formatTime(task.created_at);
    taskInstructionEl.textContent = task.instruction;

    if (task.status === "completed" && task.result) {
      taskResultWrap.hidden = false;
      renderMarkdown(task.result);
    } else {
      taskResultWrap.hidden = true;
      taskResultEl.innerHTML = "";
    }

    if (task.status === "failed" && task.error) {
      taskErrorWrap.hidden = false;
      taskErrorEl.textContent = task.error;
    } else {
      taskErrorWrap.hidden = true;
      taskErrorEl.textContent = "";
    }

    highlightActiveRow(task.task_id);

    if (ACTIVE.has(task.status)) {
      clearToolCalls();
      startPolling(task.task_id);
    } else {
      stopPolling();
      toolCallsDetails.hidden = false;
      if (toolCallsLoadedFor !== task.task_id) {
        loadToolCalls(task.task_id);
      }
    }
  }

  function highlightActiveRow(taskId) {
    tasksTbody.querySelectorAll("tr[data-task-id]").forEach(function (row) {
      row.classList.toggle("is-active", row.dataset.taskId === taskId);
    });
  }

  async function refreshTask(taskId, opts) {
    opts = opts || {};
    try {
      const task = await api("/tasks/" + encodeURIComponent(taskId));
      renderTask(task);
      if (!opts.quiet) showFormError(null);
      if (!ACTIVE.has(task.status)) {
        await refreshTaskList({ quiet: true });
      }
    } catch (err) {
      if (!opts.quiet) showFormError(err.message);
      stopPolling();
    }
  }

  async function loadToolCalls(taskId) {
    toolCallsLoadedFor = taskId;
    toolCallsTbody.innerHTML = "";
    toolCallsEmpty.hidden = true;
    toolCallsMeta.textContent = "Loading…";
    try {
      const runs = await api("/tasks/" + encodeURIComponent(taskId) + "/runs");
      if (!runs.length) {
        toolCallsMeta.textContent = "No agent runs yet.";
        toolCallsEmpty.hidden = false;
        return;
      }
      const run = runs[0];
      const detail = await api(
        "/tasks/" +
          encodeURIComponent(taskId) +
          "/runs/" +
          encodeURIComponent(run.run_id)
      );
      const parts = [
        "Run " + String(run.run_id).slice(0, 8),
        detail.status,
        detail.model || "model n/a",
        (detail.tool_call_count || 0) + " tools",
      ];
      if (detail.total_tokens != null) {
        parts.push(detail.total_tokens + " tokens");
      }
      if (detail.halt_reason) {
        parts.push("halt: " + detail.halt_reason);
      }
      toolCallsMeta.textContent = parts.join(" · ");

      const calls = detail.tool_calls || [];
      if (!calls.length) {
        toolCallsEmpty.hidden = false;
        return;
      }
      calls
        .slice()
        .sort(function (a, b) {
          return a.sequence - b.sequence;
        })
        .forEach(function (call) {
          const tr = document.createElement("tr");
          tr.innerHTML =
            "<td class=\"mono\">" +
            escapeHtml(String(call.sequence)) +
            "</td><td class=\"mono\">" +
            escapeHtml(call.name) +
            "</td><td class=\"" +
            (call.ok ? "ok-yes" : "ok-no") +
            "\">" +
            (call.ok ? "yes" : "no") +
            "</td><td class=\"mono\">" +
            escapeHtml(String(call.duration_ms)) +
            "</td><td class=\"tool-args\" title=\"" +
            escapeHtml(call.args || "") +
            "\">" +
            escapeHtml(call.args || "") +
            "</td>";
          toolCallsTbody.appendChild(tr);
        });
    } catch (err) {
      toolCallsMeta.textContent = "Failed to load tool calls: " + err.message;
      toolCallsLoadedFor = null;
    }
  }

  function renderTaskList(tasks) {
    tasksTbody.querySelectorAll("tr[data-task-id]").forEach(function (row) {
      row.remove();
    });
    if (!tasks.length) {
      tasksEmptyRow.hidden = false;
      return;
    }
    tasksEmptyRow.hidden = true;
    tasks
      .slice()
      .sort(function (a, b) {
        return new Date(b.created_at) - new Date(a.created_at);
      })
      .forEach(function (task) {
        const tr = document.createElement("tr");
        tr.dataset.taskId = task.task_id;
        if (task.task_id === activeTaskId) tr.classList.add("is-active");
        tr.innerHTML =
          "<td class=\"status-cell\">" +
          escapeHtml(task.status) +
          "</td><td class=\"truncate\" title=\"" +
          escapeHtml(task.repository_url) +
          "\">" +
          escapeHtml(shortRepo(task.repository_url)) +
          "</td><td class=\"truncate\" title=\"" +
          escapeHtml(task.instruction) +
          "\">" +
          escapeHtml(truncate(task.instruction, 60)) +
          "</td><td>" +
          escapeHtml(formatTime(task.created_at)) +
          "</td>";
        tr.addEventListener("click", function () {
          refreshTask(task.task_id);
        });
        tasksTbody.appendChild(tr);
      });
  }

  async function refreshTaskList(opts) {
    opts = opts || {};
    try {
      const tasks = await api("/tasks");
      renderTaskList(tasks);
    } catch (err) {
      if (!opts.quiet) showFormError(err.message);
    }
  }

  instructionInput.addEventListener("input", function () {
    instructionCount.textContent = String(instructionInput.value.length);
  });
  instructionCount.textContent = String(instructionInput.value.length);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    showFormError(null);

    const repository_url = repoInput.value.trim();
    const instruction = instructionInput.value.trim();
    if (instruction.length < 10) {
      showFormError("Instruction must be at least 10 characters.");
      return;
    }
    if (instruction.length > 2000) {
      showFormError("Instruction must be at most 2000 characters.");
      return;
    }

    submitBtn.disabled = true;
    try {
      const task = await api("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository_url: repository_url, instruction: instruction }),
      });
      clearToolCalls();
      renderTask(task);
      await refreshTaskList({ quiet: true });
    } catch (err) {
      showFormError(err.message);
    } finally {
      submitBtn.disabled = false;
    }
  });

  refreshListBtn.addEventListener("click", function () {
    refreshTaskList();
  });

  toolCallsDetails.addEventListener("toggle", function () {
    if (
      toolCallsDetails.open &&
      activeTaskId &&
      toolCallsLoadedFor !== activeTaskId
    ) {
      loadToolCalls(activeTaskId);
    }
  });

  refreshTaskList();
})();
