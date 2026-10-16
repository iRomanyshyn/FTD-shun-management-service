(() => {
  const formatTime = (value) => {
    if (!value || Number.isNaN(Date.parse(value))) return "not yet available";
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit",
      minute: "2-digit", second: "2-digit", timeZoneName: "short",
    }).format(new Date(value));
  };
  const localize = (root = document) => {
    root.querySelectorAll(".local-timestamp[datetime]").forEach((element) => {
      element.textContent = formatTime(element.dateTime);
    });
  };
  const duration = (seconds) => {
    const total = Math.max(0, Math.ceil(seconds));
    return total >= 60 ? `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s` : `${total}s`;
  };
  const parseStatus = (value) => {
    if (!value || typeof value.instance_id !== "string"
        || !["status_revision", "data_revision", "cycle_revision"].every(
          (field) => Number.isSafeInteger(value[field]) && value[field] >= 0,
        )) throw new Error("Refresh status is unavailable. Please retry.");
    return value;
  };
  const readInitial = (root) => parseStatus(JSON.parse(
    root.querySelector("[data-refresh-initial]").textContent,
  ));
  const version = (status) => `${status.instance_id}:${status.data_revision}:${status.cycle_revision}:${status.queue?.revision || 0}:${status.policy_revision || 0}`;
  // Template JSON and BFF JSON may order object keys differently. Equivalent
  // metadata must not restart native progress animations or replace controls.
  const stableSignature = (value) => JSON.stringify(value, (_key, entry) =>
    entry && typeof entry === "object" && !Array.isArray(entry)
      ? Object.fromEntries(Object.keys(entry).sort().map((key) => [key, entry[key]])) : entry);

  const renderRequestProgress = (panel, queue) => {
    const section = panel.querySelector("[data-request-progress-section]");
    const list = panel.querySelector("[data-request-progress]");
    if (!section || !list) return;
    const metadata = queue.progress || { requests: [], total_requests: 0 };
    const requests = (metadata.requests || []).slice(0, 20);
    section.hidden = !requests.length;
    const signature = stableSignature(metadata);
    if (list.dataset.signature === signature) return;
    list.dataset.signature = signature;
    list.replaceChildren();
    panel.querySelector("[data-request-progress-summary]").textContent =
      `Showing ${requests.length} of ${metadata.total_requests} active requests. Shared jobs may appear in multiple requests.`;
    requests.forEach((request) => {
      const counts = request.counts || {};
      const card = document.createElement("div");
      card.className = "request-progress";
      card.dataset.requestId = request.id;
      card.dataset.warning = String(Boolean(counts.FAILED || counts.UNVERIFIED));
      const title = document.createElement("p");
      title.id = `request-progress-title-${request.id}`;
      title.textContent = `Request ${request.id.slice(0, 8)} · ${request.actor_display_name || request.actor_subject} (${request.source})`;
      const progress = document.createElement("progress");
      progress.setAttribute("aria-labelledby", title.id);
      const known = Number.isSafeInteger(request.total) && request.total > 0
        && Number.isSafeInteger(request.processed) && request.processed >= 0 && request.processed <= request.total;
      const label = document.createElement("p");
      label.setAttribute("role", "status");
      label.textContent = known
        ? `${request.processed} / ${request.total} jobs processed (${Math.floor(100 * request.processed / request.total)}%). `
          + `${counts.RUNNING || 0} running; ${counts.QUEUED || 0} queued.`
        : "Progress totals are not available yet.";
      if (known) {
        progress.max = request.total;
        progress.value = request.processed;
        progress.setAttribute("aria-valuetext", `${request.processed} of ${request.total} jobs processed; outcomes are listed separately`);
      }
      const outcomes = document.createElement("p");
      outcomes.textContent = `${counts.VERIFIED || 0} verified; ${counts.NOOP || 0} no-op; `
        + `${counts.FAILED || 0} failed; ${counts.UNVERIFIED || 0} unverified; `
        + `${counts.CANCELLED || 0} cancelled; ${counts.RECONCILED_ABSENT || 0} reconciled absent.`;
      card.append(title, progress, label, outcomes);
      list.append(card);
    });
  };

  // Retain editable values and focus only for the same form action and field.
  // Hidden security fields always come from the fresh server-rendered form.
  const replaceRegion = (oldRegion, nextRegion) => {
    const values = new Map();
    const fieldKey = (field) => `${field.form?.getAttribute("action") || ""}:${field.form?.dataset.policyIp || ""}:${field.name}:${field.type}`;
    oldRegion.querySelectorAll("input, textarea, select").forEach((field) => {
      if (field.form?.matches("[data-policy-form]")) {
        if (!field.form.dataset.dirty || (field.type === "hidden" && field.name !== "revision")) return;
      } else if (field.type === "hidden") return;
      values.set(fieldKey(field), {
        value: field.value, checked: field.checked, focused: document.activeElement === field,
        start: field.selectionStart, end: field.selectionEnd,
      });
    });
    const opened = new Map([...oldRegion.querySelectorAll("details[id]")].map(
      (element) => [element.id, element.open],
    ));
    const replacement = document.importNode(nextRegion, true);
    oldRegion.replaceWith(replacement);
    replacement.querySelectorAll("input, textarea, select").forEach((field) => {
      const saved = values.get(fieldKey(field));
      if (!saved) return;
      field.value = saved.value;
      if (field.form?.matches("[data-policy-form]")) field.form.dataset.dirty = "true";
      if (typeof saved.checked === "boolean") field.checked = saved.checked;
      if (saved.focused) {
        field.focus({ preventScroll: true });
        if (saved.start !== null && typeof field.setSelectionRange === "function") {
          field.setSelectionRange(saved.start, saved.end);
        }
      }
    });
    replacement.querySelectorAll("details[id]").forEach((element) => {
      if (opened.has(element.id)) element.open = opened.get(element.id);
    });
    localize(replacement);
  };

  const createController = (panel) => {
    let status = readInitial(panel);
    let displayedVersion = version(status);
    let clockOffset = Date.parse(status.server_time) - Date.now();
    let timer = null;
    let busy = false;
    let manualPending = false;
    let errorMessage = "";
    let failures = 0;
    let paused = false;
    let actionPending = null;
    let failedAction = null;
    let actionError = "";
    const form = panel.querySelector("[data-refresh-form]");
    const button = panel.querySelector("[data-refresh-request]");
    const message = panel.querySelector("[data-refresh-message]");
    const warning = panel.querySelector("[data-refresh-warning]");
    const deviceRows = panel.querySelector("[data-device-status]");
    const queueRows = panel.querySelector("[data-operation-queue]");
    const remaining = (value) => {
      const deadline = Date.parse(value || "");
      return Number.isNaN(deadline) ? null : (deadline - Date.now() - (clockOffset || 0)) / 1000;
    };

    const renderButton = () => {
      const baseline = remaining(status.next_baseline_refresh);
      const cooldown = remaining(status.next_interactive_refresh);
      const nearBaseline = baseline !== null && baseline <= status.interactive_min_interval_seconds;
      let label = "Request refresh";
      let disabled = false;
      if (!status.refresh_enabled) {
        label = "Refresh unavailable";
        disabled = true;
      } else if (manualPending) {
        label = "Requesting refresh…";
        disabled = true;
      } else if (status.refresh_in_progress && status.interactive_refresh_state === "checkpoint_pending") {
        label = "Refresh waiting for current operation…";
        disabled = true;
      } else if (status.refresh_in_progress && status.priority_refresh_available) {
        label = "Request priority refresh";
      } else if (status.refresh_in_progress) {
        label = "Refreshing…";
        disabled = true;
      } else if (status.interactive_refresh_state === "queued") {
        label = "Refresh queued";
        disabled = true;
      } else if (nearBaseline) {
        label = baseline > 0 ? `Scheduled refresh (${duration(baseline)})` : "Scheduled refresh pending";
        disabled = true;
      } else if (cooldown !== null && cooldown > 0) {
        label = `Request refresh (${duration(cooldown)})`;
        disabled = true;
      }
      if (errorMessage && !disabled) label = "Refresh unavailable — retry";
      button.disabled = disabled;
      button.textContent = label;
      panel.querySelector(".baseline-countdown").textContent = status.refresh_in_progress
        ? "refreshing…" : baseline === null ? "not scheduled"
          : baseline > 0 ? `in ${duration(baseline)}` : "due now";
    };

    const render = () => {
      const last = panel.querySelector(".last-successful-refresh");
      last.dateTime = status.last_successful_refresh || "";
      last.textContent = formatTime(status.last_successful_refresh);
      const devices = Object.values(status.devices || {});
      const unsafe = devices.filter((device) => device.state !== "disabled"
        && (device.stale || ["error", "stale", "pending"].includes(device.state)));
      warning.hidden = !status.last_error && !unsafe.length;
      warning.textContent = status.last_error ? `Refresh warning: ${status.last_error}`
        : unsafe.length ? `Unconfirmed or stale data: ${unsafe.map((device) => device.hostname).join(", ")}. Check Status before acting.` : "";
      const summary = panel.querySelector("[data-status-summary]");
      if (summary) summary.textContent = status.refresh_in_progress ? "Updating devices…"
        : `${devices.length} device(s) · ${unsafe.length ? `${unsafe.length} need attention` : "Observations current"}`;
      const indicator = panel.querySelector("[data-status-indicator]");
      if (indicator) indicator.textContent = unsafe.length || status.last_error ? "· !" : "";
      message.textContent = errorMessage || actionError || (actionPending ? "Submitting operation…" : status.refresh_in_progress
        ? "Refreshing device information…"
        : status.cycle_revision > 0
          ? ({ success: "Refresh completed.", partial: "Refresh partially completed. Check device details.",
              failed: "Refresh failed. Previous observations are retained.",
              interrupted: "Refresh interrupted. Check device details." }[status.cycle_outcome] || "")
          : "Waiting for the first refresh.");
      message.classList.toggle("refresh-error", Boolean(errorMessage || actionError));
      const actionWarning = panel.querySelector("[data-action-warning]");
      if (actionWarning) {
        actionWarning.hidden = !errorMessage && !actionError;
        actionWarning.textContent = errorMessage || actionError;
      }
      message.hidden = !errorMessage && !actionError && !actionPending && !status.refresh_in_progress
        && !["failed", "partial", "interrupted", "not_started"].includes(status.cycle_outcome);
      deviceRows.replaceChildren();
      Object.values(status.devices || {}).forEach((device) => {
        const row = document.createElement("tr");
        const state = ({ ready: "Current", refreshing: "Refreshing", error: "Error",
          stale: "Stale", pending: "Not yet confirmed", disabled: "Disabled" })[device.state] || "Unknown";
        [device.hostname, state + (device.stale && device.state === "refreshing" ? " — previous data stale" : ""),
          formatTime(device.last_successful_refresh), device.last_error || "—"].forEach((text) => {
          const cell = document.createElement("td");
          cell.textContent = text;
          row.append(cell);
        });
        row.classList.toggle("device-stale", Boolean(device.stale));
        deviceRows.append(row);
      });
      renderButton();
      renderQueue();
    };

    const renderQueue = () => {
      if (!queueRows) return;
      const queue = status.queue || { counts: {}, items: [] };
      renderRequestProgress(panel, queue);
      const progress = panel.querySelector("[data-cycle-progress]");
      if (progress) {
        progress.hidden = !status.refresh_in_progress;
        const cycle = status.device_cycle;
        const actions = { opening_session: "Opening session", remove_and_verify: "Removing and verifying",
          add_and_verify: "Adding and verifying",
          priority_snapshot: "Reading priority snapshot", final_snapshot: "Reading final snapshot",
          completed: "Cycle completed", failed: "Cycle failed" };
        progress.textContent = status.session_cycles_enabled && cycle?.device_id
          ? `${status.devices?.[String(cycle.device_id)]?.hostname || cycle.device_id}: `
            + `${actions[cycle.action] || cycle.action}${cycle.ip ? ` ${cycle.ip}` : ""}. `
            + `${cycle.completed} items completed (cycle limit ${cycle.limit}). `
            + (cycle.priority_state === "waiting_for_checkpoint" ? "Refresh waiting for current verification. " : "")
            + (cycle.priority_state === "joining_final_snapshot" ? "Refresh joins the final snapshot. " : "")
            + (cycle.budget_deferred ? "Remaining work deferred to the next eligible cycle." : "")
          : "";
      }
      const counts = queue.counts || {};
      const activeStates = new Set(["QUEUED", "RUNNING"]);
      const attentionStates = new Set(["FAILED", "UNVERIFIED"]);
      const completedStates = new Set(["VERIFIED", "NOOP", "CANCELLED", "RECONCILED_ABSENT"]);
      const items = queue.items || [];
      const activeItems = items.filter((item) => activeStates.has(item.state)).slice(0, 100);
      const attentionItems = items.filter((item) => attentionStates.has(item.state)).slice(0, 20);
      const completedItems = items.filter((item) => completedStates.has(item.state)).slice(0, 20);
      const totalFor = (states) => [...states].reduce((sum, state) => sum + (counts[state] || 0), 0);
      const activeTotal = totalFor(activeStates);
      const attentionTotal = totalFor(attentionStates);
      const completedTotal = totalFor(completedStates);
      const indicator = panel.querySelector("[data-queue-indicator]");
      if (indicator) indicator.textContent = `${activeTotal}${attentionTotal ? ` · ${attentionTotal} need attention` : ""}`;
      const queueWarning = panel.querySelector("[data-queue-warning]");
      if (queueWarning) {
        queueWarning.hidden = !attentionTotal;
        queueWarning.textContent = `${attentionTotal} failed or unverified operation(s). Open Queue → Needs attention. Unverified writes are not automatically retried.`;
      }
      const next = activeTotal && queue.next_eligible_at
        ? ` Next eligible cycle: ${formatTime(queue.next_eligible_at)}.` : "";
      panel.querySelector("[data-queue-summary]").textContent =
        activeTotal ? `${counts.RUNNING || 0} running; ${counts.QUEUED || 0} queued. `
          + `Showing ${activeItems.length} of ${activeTotal} active operations.${next}` : "Queue is empty.";
      const activeTable = panel.querySelector("[data-queue-active-table]");
      if (activeTable) activeTable.hidden = !activeItems.length;
      const attentionRows = panel.querySelector("[data-queue-attention]");
      const completedRows = panel.querySelector("[data-queue-completed]");
      const attentionSection = panel.querySelector("[data-queue-attention-section]");
      if (attentionSection) {
        attentionSection.hidden = !attentionTotal;
        panel.querySelector("[data-queue-attention-summary]").textContent =
          `${counts.FAILED || 0} failed; ${counts.UNVERIFIED || 0} unverified. `
          + `Showing the latest ${attentionItems.length} of ${attentionTotal}. Unverified writes are not automatically retried.`;
      }
      const results = panel.querySelector("#queue-results-details");
      if (results) {
        results.hidden = !completedTotal;
        panel.querySelector("[data-queue-completed-summary]").textContent = `Completed operations (${completedTotal})`;
        panel.querySelector("[data-queue-completed-note]").textContent =
          `Showing the latest ${completedItems.length} of ${completedTotal} retained results. `
          + `${counts.VERIFIED || 0} verified; ${counts.NOOP || 0} no-op; `
          + `${counts.CANCELLED || 0} cancelled; ${counts.RECONCILED_ABSENT || 0} reconciled absent.`;
      }
      // Preserve native indeterminate animation (and focused cancellation
      // controls) when only unrelated freshness/phase metadata changes.
      const rowSignature = stableSignature([items, panel.dataset.operator, panel.dataset.subject, panel.dataset.administrator]);
      if (queueRows.dataset.signature === rowSignature) return;
      queueRows.dataset.signature = rowSignature;
      queueRows.replaceChildren();
      attentionRows?.replaceChildren();
      completedRows?.replaceChildren();
      [...activeItems, ...attentionItems, ...completedItems].forEach((item) => {
        const row = document.createElement("tr");
        row.dataset.operationId = item.id;
        const requests = item.requests || [];
        [ `${item.hostname} / ${item.ip}`,
          item.action === "ADD" && item.state === "QUEUED" && item.execution_enabled !== true
            ? "Held — ADD execution disabled for this device" : item.state,
          requests.map((request) => `${request.actor_display_name} (${request.source}`
            + `${activeStates.has(item.state) && request.state !== "ACTIVE" ? `, ${request.state}` : ""})`).join(", "),
          item.reason || (item.completed_at ? `Completed: ${formatTime(item.completed_at)}`
            : item.started_at ? `Started: ${formatTime(item.started_at)}` : `Queued: ${formatTime(item.requested_at)}`),
        ].forEach((value) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        });
        const targetLink = document.createElement("a");
        targetLink.href = `/shuns/${encodeURIComponent(item.ip)}`;
        targetLink.textContent = `${item.action === "ADD" ? "Add · " : ""}${item.hostname} / ${item.ip}`;
        row.firstElementChild.replaceChildren(targetLink);
        if (item.state === "RUNNING") {
          const running = document.createElement("progress");
          running.className = "operation-running-progress";
          running.setAttribute("aria-label", `Operation running for ${item.ip} on ${item.hostname}; outcome not yet verified`);
          row.children[1].append(running);
        }
        if (item.state === "QUEUED" && panel.dataset.operator === "true") {
          requests.filter((request) => request.state === "ACTIVE" && ["manual", "manual_import"].includes(request.source)
            && (request.actor_subject === panel.dataset.subject || panel.dataset.administrator === "true"))
            .forEach((request) => {
              const cancel = document.createElement("button");
              cancel.type = "button";
              cancel.dataset.operationCancel = request.id;
              cancel.textContent = request.target_count > 1
                ? `Cancel request (${request.target_count} targets)` : "Cancel request";
              row.lastElementChild.append(" ", cancel);
            });
        }
        const target = activeStates.has(item.state) ? queueRows
          : attentionStates.has(item.state) ? attentionRows : completedRows;
        target?.append(row);
      });
    };

    const apply = (payload) => {
      const next = parseStatus(payload);
      if (next.instance_id === status.instance_id && next.status_revision < status.status_revision) return;
      status = next;
      clockOffset = Date.parse(next.server_time) - Date.now();
      render();
    };

    const fetchChecked = async (url, options, contentType) => {
      const response = await fetch(url, {
        ...options, credentials: "same-origin", cache: "no-store", redirect: "error",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok || !response.headers.get("content-type")?.includes(contentType)) {
        let detail;
        if (!response.ok && response.headers.get("content-type")?.includes("application/json")) {
          try { detail = (await response.json()).detail; } catch (_) { /* use the fallback */ }
        }
        throw new Error(typeof detail === "string" ? detail : response.status === 401 || response.status === 403
          ? "Authentication is required. Reload the page to sign in."
          : "Refresh is temporarily unavailable. Retrying automatically.");
      }
      return response;
    };

    const updateView = async () => {
      const response = await fetchChecked(window.location.href, { headers: { Accept: "text/html" } }, "text/html");
      const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
      const renderedStatus = readInitial(nextDocument);
      // Validate all regions before touching the live document (including an
      // authentication response or a partial/error render).
      const replacements = [...document.querySelectorAll("[data-live-region]")].map((region) => {
        const replacement = nextDocument.getElementById(region.id);
        if (!replacement?.hasAttribute("data-live-region")) throw new Error("Updated results are unavailable. Retrying.");
        return [region, replacement];
      });
      const scroll = { left: window.scrollX, top: window.scrollY, behavior: "instant" };
      replacements.forEach(([region, replacement]) => replaceRegion(region, replacement));
      const nextCsrf = nextDocument.querySelector("[data-refresh-form] input[name=csrf]");
      if (nextCsrf) form.querySelector("input[name=csrf]").value = nextCsrf.value;
      window.scrollTo(scroll);
      displayedVersion = version(renderedStatus);
      apply(renderedStatus);
    };

    const schedule = (delay) => {
      window.clearTimeout(timer);
      if (!paused && !document.hidden) timer = window.setTimeout(run, delay);
    };

    const run = async () => {
      if (busy || paused || document.hidden) return;
      busy = true;
      window.clearTimeout(timer);
      try {
        let response;
        if (actionPending) {
          const action = actionPending;
          try {
            action.body.set("csrf", form.querySelector("input[name=csrf]").value);
            response = await fetchChecked(action.url, {
              method: "POST", body: action.body, headers: { Accept: "application/json" },
            }, "application/json");
            failedAction = null;
            actionError = "";
            if (action.sourceForm?.matches("[data-policy-form]")) {
              const currentForm = document.getElementById(action.sourceForm.id) || action.sourceForm;
              delete currentForm.dataset.dirty;
              currentForm.reset();
              currentForm.closest("details")?.removeAttribute("open");
            }
          } catch (error) {
            failedAction = action;
            actionError = error.message;
            throw error;
          } finally {
            actionPending = null;
            if (action.button?.isConnected) action.button.disabled = false;
          }
        } else if (manualPending) {
          // Clear pending only after the request finishes. Further clicks are
          // disabled immediately and never start a parallel status loop.
          try {
            response = await fetchChecked(form.action, {
              method: "POST", body: new FormData(form), headers: { Accept: "application/json" },
            }, "application/json");
          } finally {
            manualPending = false;
          }
        } else {
          response = await fetchChecked(panel.dataset.statusUrl, {
            headers: { Accept: "application/json" },
          }, "application/json");
        }
        errorMessage = "";
        apply(await response.json());
        if (version(status) !== displayedVersion) await updateView();
        failures = 0;
      } catch (error) {
        failures += 1;
        errorMessage = error.message || "Refresh is temporarily unavailable. Retrying automatically.";
      } finally {
        busy = false;
        render();
        schedule(manualPending || actionPending ? 0 : failures ? Math.min(30000, 3000 * 2 ** Math.min(failures, 3))
          : status.refresh_in_progress || status.interactive_refresh_state === "queued" ? 1000 : 5000);
      }
    };

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (button.disabled || manualPending) return;
      manualPending = true;
      errorMessage = "";
      renderButton();
      if (!busy) schedule(0);
    });
    const submitAction = (url, body, sourceButton, sourceForm = null) => {
      if (actionPending) {
        errorMessage = "An operation submission is in progress. Please wait for its result.";
        render();
        return;
      }
      if (failedAction?.url === url && failedAction.body.has("request_id")) {
        body.set("request_id", failedAction.body.get("request_id"));
      }
      actionPending = { url, body, button: sourceButton, sourceForm };
      if (sourceButton) sourceButton.disabled = true;
      errorMessage = "";
      actionError = "";
      render();
      if (!busy) schedule(0);
    };
    document.addEventListener("submit", (event) => {
      if (!event.target.matches("[data-queue-form], [data-policy-form]")) return;
      event.preventDefault();
      submitAction(event.target.action, new FormData(event.target), event.submitter, event.target);
    });
    document.addEventListener("input", (event) => {
      const policyForm = event.target.closest("[data-policy-form]");
      if (policyForm) policyForm.dataset.dirty = "true";
    });
    panel.addEventListener("click", (event) => {
      const cancel = event.target.closest("[data-operation-cancel]");
      if (!cancel) return;
      const body = new FormData();
      submitAction(`/operations/${cancel.dataset.operationCancel}/cancel`, body, cancel);
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) window.clearTimeout(timer);
      else schedule(0);
    });
    window.addEventListener("pagehide", () => { paused = true; window.clearTimeout(timer); });
    window.addEventListener("pageshow", () => { paused = false; schedule(0); });
    // Actual page views may hint once; background status polls never do.
    render();
    if (panel.dataset.autoRequest === "true" && !button.disabled && !document.hidden) manualPending = true;
    renderButton();
    schedule(0);
    window.setInterval(() => { if (!document.hidden) renderButton(); }, 1000);
  };

  localize();
  const menus = [...document.querySelectorAll("[data-utility-menu]")];
  menus.forEach((menu) => menu.addEventListener("toggle", () => {
    if (menu.open) menus.filter((other) => other !== menu).forEach((other) => { other.open = false; });
  }));
  document.addEventListener("click", (event) => {
    menus.filter((menu) => !menu.contains(event.target)).forEach((menu) => { menu.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = menus.find((menu) => menu.open);
    if (open) { open.open = false; open.querySelector("summary").focus(); }
  });
  document.querySelectorAll("[data-refresh-controller]").forEach(createController);
})();
