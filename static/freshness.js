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
  const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : 0;
  const compactCount = (value) => value > 99 ? "99+" : String(value);
  const pausedKinds = (status) => status.managed_addition_controls?.available === true
    ? ['imports', 'restoration'].filter(kind => status.managed_addition_controls[kind]?.paused === true) : [];
  const briefStorageRetry = (status) => status.execution_recovery?.state === 'retrying'
    && Number.isSafeInteger(status.execution_recovery.attempts)
    && status.execution_recovery.attempts > 0 && status.execution_recovery.attempts < 3;
  const reportedError = (status) => briefStorageRetry(status)
    && status.execution_recovery.reason === status.last_error ? '' : status.last_error;
  const deferredRetryWait = (status) => {
    const seconds = Object.values(status.deferred_confirmation || {})
      .filter((row) => row && row.held === false && row.mutations_paused === false
        && Number.isFinite(row.retry_in_seconds) && row.retry_in_seconds >= 0)
      .map((row) => row.retry_in_seconds);
    if (!seconds.length) return '';
    const next = Math.min(...seconds);
    return next > 0 ? `Next absence check eligible in ${duration(next)}.`
      : 'Absence check eligible; waiting for an available device session.';
  };
  const queueAttentionCounts = (queue) => {
    const raw = queue.counts || {}, attention = queue.attention_counts, reviewed = queue.reviewed_history;
    // Older/malformed metadata must not hide unresolved outcomes. The API
    // supplies this projection only after validating original review evidence.
    if (!attention || !reviewed || !Array.isArray(reviewed.items)
        || !Number.isSafeInteger(reviewed.total) || reviewed.total < 0
        || !Number.isSafeInteger(attention.FAILED) || attention.FAILED !== count(raw.FAILED)
        || !Number.isSafeInteger(attention.UNVERIFIED) || attention.UNVERIFIED < 0
        || attention.UNVERIFIED + reviewed.total !== count(raw.UNVERIFIED)) return raw;
    return attention;
  };
  // Presentation only: deadlines indicate eligibility, never completed device
  // reads. Keep requested reads separate from the periodic fallback schedule.
  const refreshPresentation = (status, remaining, requesting = false, localError = "") => {
    const devices = Object.entries(status.devices || {}).filter(([, device]) => device.state !== "disabled");
    const pending = status.refresh_schedule_mode === "per_device"
      ? Math.max(count(status.pending_refresh_device_count), devices.filter(([, device]) => device.refresh_pending).length)
      : ["queued", "checkpoint_pending"].includes(status.interactive_refresh_state) ? 1 : 0;
    const active = devices.filter(([, device]) => device.active || device.state === "refreshing");
    const phases = status.refresh_schedule_mode === "per_device"
      ? active.map(([id]) => status.device_cycles?.[id]?.action)
      : status.refresh_in_progress ? [status.device_cycle?.action] : [];
    const reading = phases.some((phase) => ["opening_session", "priority_snapshot", "final_snapshot", "verify_addition_batch"].includes(phase))
      || (status.refresh_schedule_mode !== "per_device" && status.refresh_in_progress
        && !phases.some((phase) => ["add_and_verify", "remove_and_verify", "stage_addition"].includes(phase)));
    const working = Boolean(status.refresh_in_progress || active.length || count(status.active_device_count));
    const attention = Boolean(localError || reportedError(status) || devices.some(([, device]) =>
      device.last_error || device.stale || ["error", "stale", "pending"].includes(device.state)));
    const cooldown = remaining(status.next_interactive_refresh);
    const baseline = remaining(status.next_baseline_refresh);
    const recovery = status.execution_recovery;
    const result = { activity: "idle", attention, pending, badge: "", phase: "idle",
      summary: devices.length ? "Observations current" : "No enabled devices",
      timingLabel: "Next periodic check", timing: baseline === null ? "not scheduled"
        : baseline > 0 ? `in ${duration(baseline)}` : "due; waiting for device",
      timingHelp: "Periodic timing is recalculated after a successful device read. A requested refresh may run sooner. Eligibility is not completion." };
    if (requesting) {
      Object.assign(result, { activity: "waiting", phase: "requesting", summary: "Sending refresh request…",
        timingLabel: "Requested refresh", timing: "sending request…" });
    } else if (recovery?.state === "retrying") {
      const retry = remaining(recovery.retry_at);
      Object.assign(result, { activity: working ? "busy" : "waiting", phase: "recovering",
        attention: attention || !briefStorageRetry(status),
        summary: "Storage busy · retrying automatically", timingLabel: "Scheduling retry",
        timing: retry > 0 ? `in ${duration(retry)}` : "waiting for storage availability",
        badge: retry > 0 ? duration(retry) : "…",
        timingHelp: "The import is retained. Scheduling retries automatically; unknown device operations are not replayed." });
    } else if (recovery?.state === "stopped") {
      Object.assign(result, { activity: "paused", phase: "stopped", attention: true,
        summary: "Device execution stopped · operator action needed", timingLabel: "Automatic execution",
        timing: "stopped; no refresh is scheduled", timingHelp: recovery.operator_action || "Inspect service logs and retained device outcomes before restarting." });
    } else if (pending && reading) {
      Object.assign(result, { activity: "busy", phase: "reading", summary: "Requested refresh in progress…",
        timingLabel: "Requested refresh", timing: "checking device information…" });
    } else if (pending) {
      const timing = cooldown > 0 ? `eligible in ${duration(cooldown)}`
        : working ? "waiting for the current device operation" : "waiting for an available device";
      Object.assign(result, { activity: "waiting", phase: "waiting", summary: `Refresh requested · ${timing}`,
        timingLabel: "Requested refresh", timing,
        badge: cooldown > 0 ? duration(cooldown) : `${pending} waiting` });
    } else if (reading) {
      Object.assign(result, { activity: "busy", phase: "reading", summary: "Checking device information…",
        timingLabel: "Device check", timing: "in progress; waiting for fresh data" });
    } else if (working) {
      Object.assign(result, { activity: "busy", phase: "working", summary: "Device work in progress" });
    } else if (status.refresh_enabled && baseline !== null && baseline <= 0) {
      Object.assign(result, { activity: "waiting", phase: "due", summary: "Periodic check due · waiting for device" });
    }
    if (attention && result.phase === "idle") result.summary = "Device information needs attention";
    if (localError) result.timingHelp = "Timings are last reported. Check the warning; elapsed time does not confirm a successful refresh.";
    const pauses = pausedKinds(status);
    if (pauses.length) {
      result.badge = [result.badge, `${pauses.length} paused`].filter(Boolean).join(' · ');
      if (result.activity === 'idle') result.activity = 'paused';
    }
    result.description = `${result.summary}. ${pending ? `${pending} device refresh request(s) pending. ` : ""}`
      + (pauses.length ? `${pauses.includes('imports') ? 'Imports paused. ' : ''}${pauses.includes('restoration') ? 'Automatic restoration paused. ' : ''}Manage scheduling in Status. ` : '')
      + (result.attention ? `Needs attention. ${localError || status.last_error || "Check device details."}` : "");
    return result;
  };
  const queuePresentation = (status, submitting = false, localError = "") => {
    const counts = status.queue?.counts || {};
    const running = count(counts.RUNNING), queued = count(counts.QUEUED);
    const awaiting = count(counts.AWAITING_CONFIRMATION);
    const retryWait = deferredRetryWait(status);
    const imports = status.queue?.imports;
    const importWaiting = (imports?.tasks || []).some((task) => task.active && count(task.outstanding));
    const deviceError = Boolean((running || queued || awaiting || importWaiting)
      && Object.values(status.devices || {}).some((device) => device.state === 'error' || device.last_error));
    const attentionCounts = queueAttentionCounts(status.queue || {});
    const attention = Math.max(count(attentionCounts.FAILED) + count(attentionCounts.UNVERIFIED),
      (imports?.tasks || []).reduce((sum, task) => sum + count(task.attention), 0));
    const paused = status.queue?.mutations_suspended === true;
    const recovery = status.execution_recovery;
    const stopped = recovery?.state === 'stopped';
    const problem = Boolean(attention || deviceError || paused || stopped
      || (recovery?.state === 'retrying' && !briefStorageRetry(status))
      || localError || status.managed_removal_worker_error || status.managed_restoration_error);
    const total = running + queued + awaiting;
    return { activity: running ? "busy" : paused || stopped ? "paused" : queued || awaiting || retryWait || submitting || importWaiting || recovery?.state === 'retrying' ? "waiting" : "idle",
      attention: problem,
      badge: [total ? compactCount(total) : submitting || importWaiting || retryWait ? "…" : paused ? "Paused" : "",
        attention ? `!${compactCount(attention)}` : problem ? "!" : ""].filter(Boolean).join(" · "),
      description: `Queue: ${running} running; ${queued} queued; ${attention} need attention.`
        + (awaiting ? ` ${awaiting} awaiting a complete device read; not yet confirmed.` : '')
        + (retryWait ? ` ${retryWait}` : '')
        + (importWaiting ? ' An import has addresses waiting for rolling dispatch.' : '')
        + (deviceError ? ' Some device work needs attention; open Status. Healthy devices can continue.' : '')
        + (paused ? " Device mutations are paused; monitoring continues." : "")
        + (recovery?.state === 'retrying' ? " Storage is busy; scheduling retries automatically. The import is retained." : "")
        + (stopped ? ` Execution stopped. ${recovery.operator_action || 'Open Status for operator instructions.'}` : "")
        + (submitting ? " Submitting operation; acceptance is not verified success." : "")
        + (localError ? ` ${localError}` : "")
        + (status.managed_removal_worker_error ? ` ${status.managed_removal_worker_error}` : "")
        + (status.managed_restoration_error ? ` ${status.managed_restoration_error}` : "") };
  };
  // The same pure projection is tested with Node without starting a DOM, timer,
  // network request or device workflow. The browser keeps the normal controller.
  const failureText = (error) => error instanceof TypeError || ['AbortError', 'TimeoutError', 'NetworkError'].includes(error?.name)
    ? 'Connection interrupted or service busy. Keeping last data and retrying automatically.'
    : error?.message || 'Refresh is temporarily unavailable. Retrying automatically.';

  if (typeof module !== "undefined" && module.exports && typeof document === "undefined") {
    module.exports = { refreshPresentation, queuePresentation, failureText, queueAttentionCounts };
    return;
  }
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
  const version = (status) => `${status.instance_id}:${status.data_revision}:${status.cycle_revision}:${status.queue?.revision || 0}:${status.policy_revision || 0}:${status.managed_policy_revision ?? 0}:${Boolean(status.managed_policy_initialized)}:${status.managed_policy_available ?? true}:${status.managed_addition_controls?.imports?.revision ?? 0}:${status.managed_addition_controls?.restoration?.revision ?? 0}:${document.querySelector('[data-ip-context-list], #ip-registration') ? status.ip_context_revision ?? 0 : 0}`;
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
          + (counts.AWAITING_CONFIRMATION ? ` ${counts.AWAITING_CONFIRMATION} awaiting confirmation.` : '')
        : "Progress totals are not available yet.";
      if (known) {
        progress.max = request.total;
        progress.value = request.processed;
        progress.setAttribute("aria-valuetext", `${request.processed} of ${request.total} jobs processed; outcomes are listed separately`);
      }
      const outcomes = document.createElement("p");
      outcomes.textContent = `${counts.VERIFIED || 0} verified; ${counts.NOOP || 0} no-op; `
        + `${counts.FAILED || 0} failed; ${counts.UNVERIFIED || 0} unverified; `
        + `${counts.CANCELLED || 0} cancelled; ${counts.RECONCILED_ABSENT || 0} reconciled absent.`
        + (counts.OBSERVED_PRESENT ? ` ${counts.OBSERVED_PRESENT} observed present (not creation proof).` : '')
        + (counts.CONFIRMED_ABSENT ? ` ${counts.CONFIRMED_ABSENT} confirmed absent; eligible work retries automatically.` : '');
      card.append(title, progress, label, outcomes);
      list.append(card);
    });
  };

  const renderImportProgress = (panel, queue, devices) => {
    const section = panel.querySelector('[data-import-progress-section]');
    const list = panel.querySelector('[data-import-progress]');
    if (!section || !list) return;
    const metadata = queue.imports;
    const deviceError = Object.values(devices || {}).some((device) => device.state === 'error' || device.last_error);
    const tasks = (metadata?.tasks || []).filter((task) => task.active || count(task.attention)).slice(0, 20);
    section.hidden = !tasks.length;
    const signature = stableSignature({ tasks, deviceError });
    if (list.dataset.signature === signature) return;
    list.dataset.signature = signature;
    const focused = document.activeElement?.closest('[data-import-id]')?.dataset.importId;
    list.replaceChildren();
    const names = { verified: 'verified additions', noop: 'verified already present', adopted: 'adopted',
      unchanged: 'already managed', present: 'observed present (not service-created proof)',
      pending: 'waiting for dispatch', queued: 'queued', running: 'running', failed: 'failed',
      awaiting_confirmation: 'awaiting confirmation', awaiting_retry: 'waiting for a fresh attempt',
      unverified: 'unverified', unknown: 'missing evidence', stopped: 'stopped', superseded: 'superseded' };
    tasks.forEach((task) => {
      if (!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(task.id)) return;
      const card = document.createElement('div');
      card.className = 'request-progress';
      card.dataset.importId = task.id;
      card.dataset.warning = String(Boolean(task.attention || task.active && deviceError));
      const title = document.createElement('p');
      title.id = `import-progress-${task.id}`;
      title.textContent = `${task.label || `Import ${task.id.slice(0, 8)}`} · ${task.actor_display_name || task.actor_subject}`;
      const progress = document.createElement('progress');
      progress.setAttribute('aria-labelledby', title.id);
      const known = Number.isSafeInteger(task.total) && task.total > 0 && Number.isSafeInteger(task.processed)
        && task.processed >= 0 && task.processed <= task.total && Number.isSafeInteger(task.outstanding) && task.outstanding >= 0;
      const label = document.createElement('p');
      label.textContent = known ? `${task.processed.toLocaleString()} / ${task.total.toLocaleString()} addresses processed `
        + `(${Math.floor(100 * task.processed / task.total)}%). ${task.outstanding.toLocaleString()} remaining.` : 'Progress unavailable.';
      if (known) { progress.max = task.total; progress.value = task.processed; }
      const outcomes = document.createElement('p');
      outcomes.className = 'preview-help';
      outcomes.textContent = Object.entries(names).filter(([key]) => task.counts?.[key])
        .map(([key, name]) => `${task.counts[key].toLocaleString()} ${name}`).join(' · ');
      card.append(title, progress, label, outcomes);
      if (task.active && deviceError) {
        const warning = document.createElement('p');
        warning.textContent = 'Some device work needs attention. Open Status for the reason; waiting addresses are not completed.';
        card.append(warning);
      }
      if (task.cancelled) {
        const note = document.createElement('p');
        note.textContent = 'Uncompleted work cancelled; already applied/adopted blocks remain. Running work finishes safely.';
        card.append(note);
      } else if (task.cancellation_available && panel.dataset.operator === 'true'
          && (task.actor_subject === panel.dataset.subject || panel.dataset.administrator === 'true')) {
        const form = document.createElement('form');
        form.method = 'post';
        form.action = `/managed-imports/v2/${task.id}/cancellation-review`;
        const csrf = document.createElement('input');
        csrf.type = 'hidden'; csrf.name = 'csrf';
        csrf.value = panel.querySelector('.request-refresh-form [name=csrf]').value;
        const button = document.createElement('button');
        button.type = 'submit'; button.textContent = 'Cancel remaining import…';
        form.append(csrf, button);
        const note = document.createElement('p');
        note.className = 'preview-help';
        note.textContent = 'Opens a whole-import confirmation. Already applied blocks are not removed.';
        card.append(form, note);
      }
      list.append(card);
    });
    if (focused) list.querySelector(`[data-import-id="${focused}"] button`)?.focus({ preventScroll: true });
  };

  // Retain editable values and focus only for the same form action and field.
  // Hidden security fields come from fresh forms except saved CAS revisions:
  // a dirty acknowledgement must never silently acquire a newer policy scope.
  const replaceRegion = (oldRegion, nextRegion) => {
    // Review preparation grants no authority. Keep identical editor DOM alive:
    // even replacing a focused select with an equivalent copy closes its native
    // popup. Ignore only the user's details state, not server controls/options,
    // hidden fields or capabilities. Changed/removed forms still refresh below.
    if (oldRegion.hasAttribute("data-live-editor") && nextRegion.hasAttribute("data-live-editor")) {
      const markup = (region) => {
        const copy = region.cloneNode(true);
        copy.querySelectorAll("details").forEach((element) => element.removeAttribute("open"));
        return copy.innerHTML;
      };
      if (markup(oldRegion) === markup(nextRegion)) return;
    }
    const values = new Map();
    const fieldKey = (field) => `${field.form?.getAttribute("action") || ""}:${field.form?.dataset.policyIp || ""}:${field.name}:${field.type}`;
    oldRegion.querySelectorAll("input, textarea, select").forEach((field) => {
      if (field.form?.matches("[data-policy-form]")) {
        if (!field.form.dataset.dirty || (field.type === "hidden" && !["revision", "managed_revision"].includes(field.name))) return;
      } else if (field.type === "hidden") return;
      values.set(fieldKey(field), {
        value: field.value, checked: field.checked, focused: document.activeElement === field,
        start: field.selectionStart, end: field.selectionEnd,
      });
    });
    const disclosureState = window.FtdUiState?.capture(oldRegion);
    const replacement = document.importNode(nextRegion, true);
    oldRegion.replaceWith(replacement);
    // Reopen details before restoring focus: a field in a closed details body
    // cannot receive focus, even if the body is reopened immediately afterward.
    if (disclosureState) window.FtdUiState.restore(replacement, disclosureState);
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
    localize(replacement);
  };

  const createController = (panel) => {
    // An IP overlay may update the address bar without changing this document.
    const pageUrl = window.location.href;
    let status = readInitial(panel);
    let displayedVersion = version(status);
    let clockOffset = Date.parse(status.server_time) - Date.now();
    let timer = null;
    let busy = false;
    let manualPending = false;
    let errorMessage = "";
    let failures = 0;
    let readRetryNotice = "";
    let readFailureSince = null;
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
    const paintMenu = (selector, view) => {
      const menu = panel.querySelector(selector);
      if (!menu) return;
      menu.dataset.activity = view.activity;
      menu.dataset.attention = String(view.attention);
      const trigger = menu.querySelector("summary");
      trigger.title = view.description;
      trigger.setAttribute("aria-label", view.description);
      trigger.querySelector("[data-menu-badge]").textContent = view.badge;
      trigger.querySelector("[data-menu-alert]").hidden = !view.attention || view.badge.includes("!");
    };
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
      } else if (status.refresh_schedule_mode === "per_device") {
        // Always accept/coalesce demand, including while another FTD is busy.
        // Zero is eligibility, never confirmation; only server data revisions
        // trigger content replacement after actual observations/results.
        const pending = status.pending_refresh_device_count || 0;
        label = pending ? cooldown > 0
          ? `Refresh requested · ${pending} device(s) · ${duration(cooldown)}`
          : `Refresh requested · ${pending} device(s) · waiting for verification`
          : "Request refresh";
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
      const view = refreshPresentation(status, remaining, manualPending, errorMessage || actionError);
      if (readRetryNotice) Object.assign(view, {
        activity: "waiting", summary: "Loading latest information…", badge: "…",
        description: `${view.description} ${readRetryNotice}`,
      });
      panel.querySelector(".baseline-countdown").textContent = view.timing;
      panel.querySelector("[data-refresh-timing-label]").textContent = view.timingLabel;
      panel.querySelector("[data-refresh-timing-help]").textContent = view.timingHelp;
      const summary = panel.querySelector("[data-status-summary]");
      if (summary) summary.textContent = view.summary;
      panel.dataset.refreshPhase = view.phase;
      paintMenu("#status-menu", { ...view, description: `Status: ${view.description}` });
      return view;
    };

    const render = () => {
      const pauses = pausedKinds(status);
      const pauseCount = document.querySelector('[data-managed-pause-count]');
      if (pauseCount) {
        pauseCount.hidden = !pauses.length;
        pauseCount.textContent = pauses.length ? `${pauses.length} paused` : '';
        pauseCount.title = pauses.map(kind => kind === 'imports' ? 'Imports paused' : 'Automatic restoration paused').join('; ');
      }
      const protectedCounts = document.querySelector('[data-protected-counts]');
      const policy = status.protected_counts;
      if (protectedCounts) {
        const known = policy && ['enabled', 'disabled'].every(key => Number.isSafeInteger(policy[key]) && policy[key] >= 0);
        protectedCounts.hidden = !known;
        if (known) {
          protectedCounts.title = `${policy.enabled} enabled / ${policy.disabled} disabled`;
          protectedCounts.setAttribute('aria-label', protectedCounts.title);
          protectedCounts.querySelector('[data-protected-enabled]').textContent = policy.enabled;
          protectedCounts.querySelector('[data-protected-disabled]').textContent = policy.disabled;
        }
      }
      panel.querySelectorAll('[data-control-kind]').forEach(item => {
        const kind = item.dataset.controlKind;
        const selected = status.managed_addition_controls?.[kind];
        const controlForm = item.querySelector('[data-managed-control-form]');
        // An interrupted POST keeps its exact key, action and revision for an
        // explicit retry. Unrelated status polling must not turn it into a new request.
        if (!selected || actionPending?.sourceForm === controlForm) return;
        if (failedAction?.sourceForm === controlForm) {
          controlForm.querySelector('button').textContent = `Retry ${new URL(failedAction.url).pathname.endsWith('/pause') ? 'pause' : 'resume'} request`;
          return;
        }
        const state = item.querySelector('[data-control-state]');
        state.textContent = selected.paused ? 'Paused' : 'Active';
        state.className = `state-badge ${selected.paused ? 'policy-disabled' : 'policy-enabled'}`;
        if (controlForm) {
          const revision = controlForm.elements.namedItem('revision');
          if (revision.value !== String(selected.revision)) {
            controlForm.elements.namedItem('request_id').value = crypto.randomUUID();
            revision.value = selected.revision;
          }
          controlForm.action = `/managed-additions/${kind}/${selected.paused ? 'resume' : 'pause'}`;
          controlForm.querySelector('button').textContent = `${selected.paused ? 'Resume' : 'Pause'} ${kind === 'imports' ? 'imports' : 'automatic restoration'}`;
        }
      });
      const runtimeNotice = panel.querySelector("[data-runtime-notice]");
      if (runtimeNotice) {
        runtimeNotice.hidden = status.runtime_mode !== "continuous-observation";
        runtimeNotice.textContent = "Continuous observation profile: "
          + (status.managed_policy_view_available === true ? "managed policy viewing is available; " : "")
          + (status.managed_policy_retirement_available === true ? "stop-maintaining is available; " : "")
          + (status.ordered_removal_admission_enabled === true
            ? "ordered removal API admission is available with separate Web confirmation; ADD/import admission remains unavailable. "
            : status.ready_removal_admission_enabled === true
            ? "ready-only removal API admission is available with separate Web confirmation; ADD/import admission remains unavailable. "
            : "ADD/import admission and device-removal admission are unavailable. ")
          + "Protected-IP policy and its automatic removal remain active under the existing safety checks.";
      }
      const last = panel.querySelector(".last-successful-refresh");
      last.dateTime = status.last_successful_refresh || "";
      last.textContent = formatTime(status.last_successful_refresh);
      const devices = Object.values(status.devices || {});
      const unsafe = devices.filter((device) => device.state !== "disabled"
        && (device.stale || ["error", "stale", "pending"].includes(device.state)));
      const lastError = reportedError(status);
      warning.hidden = !lastError && !unsafe.length;
      warning.textContent = lastError ? `Refresh warning: ${lastError}`
        : unsafe.length ? `Unconfirmed or stale data: ${unsafe.map((device) => device.hostname).join(", ")}. Check Status before acting.` : "";
      const retryNote = panel.querySelector("[data-read-retry]");
      if (retryNote) {
        retryNote.hidden = !readRetryNotice;
        retryNote.textContent = readRetryNotice;
      }
      const refreshView = renderButton();
      message.textContent = errorMessage || actionError || (actionPending ? "Submitting operation…"
        : ["requesting", "waiting", "due"].includes(refreshView.phase) ? refreshView.summary
        : refreshView.phase === "reading" ? "Refreshing device information…"
        : refreshView.phase === "working" ? "Device operations are running; a fresh read is confirmed separately."
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
      message.hidden = !errorMessage && !actionError && !actionPending
        && !["failed", "partial", "interrupted", "not_started"].includes(status.cycle_outcome);
      deviceRows.replaceChildren();
      Object.entries(status.devices || {}).forEach(([id, device]) => {
        const row = document.createElement("tr");
        const action = status.device_cycles?.[id]?.action;
        const state = device.state === "refreshing" && ["add_and_verify", "remove_and_verify", "stage_addition"].includes(action)
          ? "Device work" : ({ ready: "Current", refreshing: "Refreshing", error: "Error",
          stale: "Stale", pending: "Not yet confirmed", disabled: "Disabled" })[device.state] || "Unknown";
        const deviceView = status.refresh_schedule_mode === "per_device" && device.state !== "disabled"
          ? refreshPresentation({ ...status, devices: { [id]: device }, refresh_in_progress: Boolean(device.active),
            active_device_count: device.active ? 1 : 0, pending_refresh_device_count: device.refresh_pending ? 1 : 0,
            next_interactive_refresh: device.next_interactive_refresh,
            next_baseline_refresh: device.next_baseline_refresh }, remaining) : null;
        const timing = deviceView
          ? [`${deviceView.timingLabel}: ${deviceView.timing}.`,
            device.retry_in_seconds > 0 ? `Retry eligibility: ${duration(device.retry_in_seconds)}; not a successful refresh.` : ""]
            .filter(Boolean).join(" ") : "";
        [device.hostname, state,
          formatTime(device.last_successful_refresh), [device.last_error, timing].filter(Boolean).join(" ") || "—"].forEach((text, index) => {
          const cell = document.createElement("td");
          const label = index === 1 ? document.createElement("span") : cell;
          if (index === 1) {
            label.className = "status-label";
            cell.append(label);
          }
          label.textContent = text;
          row.append(cell);
        });
        if (device.stale && device.state === "refreshing") row.children[1].append(" — previous data stale");
        row.classList.toggle("device-stale", Boolean(device.stale));
        deviceRows.append(row);
      });
      renderQueue();
    };

    const renderQueue = () => {
      if (!queueRows) return;
      const queue = status.queue || { counts: {}, items: [] };
      renderImportProgress(panel, queue, status.devices);
      renderRequestProgress(panel, queue);
      const progress = panel.querySelector("[data-cycle-progress]");
      if (progress) {
        progress.hidden = !status.refresh_in_progress;
        const cycle = status.device_cycle;
        const actions = { opening_session: "Opening session", remove_and_verify: "Removing and verifying",
          add_and_verify: "Adding and verifying",
          stage_addition: "Adding · awaiting batch verification", verify_addition_batch: "Verifying added addresses",
          settling_pending_additions: "Closing session · confirmation pending",
          awaiting_confirmation: "Awaiting a complete device read",
          priority_snapshot: "Reading priority snapshot", final_snapshot: "Reading final snapshot",
          completed: "Cycle completed", failed: "Cycle failed" };
        progress.textContent = status.refresh_schedule_mode === "per_device"
          ? Object.entries(status.device_cycles || {}).filter(([id]) => status.devices?.[id]?.active).map(([id, phase]) =>
            `${status.devices[id].hostname}: ${actions[phase.action] || phase.action || "Opening session"}`
            + `${phase.ip ? ` ${phase.ip}` : ""}; ${phase.completed || 0} items completed.`
            + `${phase.pending_verification ? ` ${phase.pending_verification} awaiting verification.` : ""}`
            + `${phase.awaiting_confirmation ? ` ${phase.awaiting_confirmation} awaiting confirmation.` : ""}`).join(" ")
          : status.session_cycles_enabled && cycle?.device_id
          ? `${status.devices?.[String(cycle.device_id)]?.hostname || cycle.device_id}: `
            + `${actions[cycle.action] || cycle.action}${cycle.ip ? ` ${cycle.ip}` : ""}. `
            + `${cycle.completed} items completed (cycle limit ${cycle.limit}). `
            + (cycle.priority_state === "waiting_for_checkpoint" ? "Refresh waiting for current verification. " : "")
            + (cycle.priority_state === "joining_final_snapshot" ? "Refresh joins the final snapshot. " : "")
            + (cycle.budget_deferred ? "Remaining work deferred to the next eligible cycle." : "")
          : "";
      }
      const counts = queue.counts || {};
      const attentionCounts = queueAttentionCounts(queue);
      const reviewedHistory = attentionCounts === queue.attention_counts ? queue.reviewed_history : null;
      const reviewedIds = new Set((reviewedHistory?.items || []).slice(0, 20).map((item) => item.id));
      const activeStates = new Set(["QUEUED", "RUNNING", "AWAITING_CONFIRMATION"]);
      const attentionStates = new Set(["FAILED", "UNVERIFIED"]);
      const items = queue.items || [];
      const activeItems = items.filter((item) => activeStates.has(item.state)).slice(0, 100);
      const attentionItems = items.filter((item) => attentionStates.has(item.state) && !reviewedIds.has(item.id)).slice(0, 20);
      const totalFor = (states) => [...states].reduce((sum, state) => sum + (counts[state] || 0), 0);
      const activeTotal = totalFor(activeStates);
      const attentionTotal = [...attentionStates].reduce((sum, state) => sum + (attentionCounts[state] || 0), 0);
      paintMenu("#queue-menu", queuePresentation(status, Boolean(actionPending), errorMessage || actionError));
      const queueWarning = panel.querySelector("[data-queue-warning]");
      const recoveryWarning = panel.querySelector("[data-recovery-warning]");
      if (recoveryWarning) {
        recoveryWarning.hidden = !queue.mutations_suspended && !status.managed_removal_worker_error && !status.managed_restoration_error;
        recoveryWarning.textContent = queue.mutations_suspended
          ? "Recovery safety pause: device mutations and new jobs are suspended. Monitoring continues; offline review is required before resuming."
          : (status.managed_removal_worker_error || status.managed_restoration_error || "");
      }
      if (queueWarning) {
        queueWarning.hidden = !attentionTotal;
        queueWarning.textContent = `${attentionTotal} failed or unverified operation(s). Open Queue → Needs attention. Unverified writes are not automatically retried.`;
      }
      const next = activeTotal && queue.next_eligible_at
        ? ` Next eligible cycle: ${formatTime(queue.next_eligible_at)}.` : "";
      panel.querySelector("[data-queue-summary]").textContent =
        activeTotal ? `${counts.RUNNING || 0} running; ${counts.QUEUED || 0} queued. `
          + (counts.AWAITING_CONFIRMATION ? `${counts.AWAITING_CONFIRMATION} awaiting confirmation. ` : '')
          + `Showing ${activeItems.length} of ${activeTotal} active operations.${next}`
          : queue.imports?.tasks?.some((task) => task.active && count(task.outstanding))
            ? 'Import work is waiting for rolling dispatch. See whole-import progress below.'
            : deferredRetryWait(status) || "Queue is empty.";
      const activeTable = panel.querySelector("[data-queue-active-table]");
      if (activeTable) activeTable.hidden = !activeItems.length;
      const attentionRows = panel.querySelector("[data-queue-attention]");
      const attentionSection = panel.querySelector("[data-queue-attention-section]");
      if (attentionSection) {
        attentionSection.hidden = !attentionTotal;
        panel.querySelector("[data-queue-attention-summary]").textContent =
          `${attentionCounts.FAILED || 0} failed; ${attentionCounts.UNVERIFIED || 0} unverified. `
          + `Showing the latest ${attentionItems.length} of ${attentionTotal}. Unverified writes are not automatically retried.`;
      }
      // Preserve native indeterminate animation (and focused cancellation
      // controls) when only unrelated freshness/phase metadata changes.
      const rowSignature = stableSignature([activeItems, attentionItems,
        [...activeItems, ...attentionItems].map(item => status.ip_context?.[item.ip]),
        panel.dataset.operator, panel.dataset.subject, panel.dataset.administrator]);
      if (queueRows.dataset.signature === rowSignature) return;
      queueRows.dataset.signature = rowSignature;
      queueRows.replaceChildren();
      attentionRows?.replaceChildren();
      [...activeItems, ...attentionItems].forEach((item) => {
        const row = document.createElement("tr");
        row.dataset.operationId = item.id;
        const requests = item.requests || [];
        [ `${item.hostname} / ${item.ip}`,
          item.action === "ADD" && item.state === "QUEUED" && item.execution_enabled !== true
            ? "Held" : ({ AWAITING_CONFIRMATION: 'Awaiting confirmation', OBSERVED_PRESENT: 'Observed present',
              CONFIRMED_ABSENT: 'Confirmed absent' }[item.state] || item.state),
          requests.map((request) => `${request.actor_display_name} (${request.source}`
            + `${activeStates.has(item.state) && request.state !== "ACTIVE" ? `, ${request.state}` : ""})`).join(", "),
          item.reason || (item.completed_at ? `Completed: ${formatTime(item.completed_at)}`
            : item.started_at ? `Started: ${formatTime(item.started_at)}` : `Queued: ${formatTime(item.requested_at)}`),
        ].forEach((value, index) => {
          const cell = document.createElement("td");
          const label = index === 1 ? document.createElement("span") : cell;
          if (index === 1) {
            label.className = "status-label";
            cell.append(label);
          }
          label.textContent = value;
          row.append(cell);
        });
        if (item.action === "ADD" && item.state === "QUEUED" && item.execution_enabled !== true) {
          row.children[1].append(" — ADD execution disabled for this device");
        }
        const targetLink = document.createElement("a");
        targetLink.href = `/shuns/${encodeURIComponent(item.ip)}`;
        targetLink.textContent = `${item.action === "ADD" ? "Add · " : ""}${item.hostname} / ${item.ip}`;
        const ipItem = window.FtdIpItem?.create(item.ip, status.ip_context?.[item.ip]);
        if (ipItem) {
          const device = document.createElement('span'); device.className = 'cell-secondary';
          device.textContent = `${item.action === 'ADD' ? 'Add' : 'Unblock'} · ${item.hostname}`;
          row.firstElementChild.replaceChildren(ipItem, device);
        } else row.firstElementChild.replaceChildren(targetLink);
        if (item.state === "RUNNING") {
          const running = document.createElement("progress");
          running.className = "operation-running-progress";
          running.setAttribute("aria-label", `Operation running for ${item.ip} on ${item.hostname}; outcome not yet verified`);
          row.children[1].append(running);
        }
        if (item.state === "QUEUED" && panel.dataset.operator === "true" && status.manual_mutations_available !== false) {
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
        const target = activeStates.has(item.state) ? queueRows : attentionRows;
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
      let response;
      const readOnly = !options.method || options.method === 'GET';
      try { response = await fetch(url, {
        ...options, credentials: "same-origin", cache: "no-store", redirect: "error",
        signal: AbortSignal.timeout(15000),
      }); } catch (error) {
        throw Object.assign(new Error(failureText(error)), { transientRead: readOnly
          && (error instanceof TypeError || ['AbortError', 'TimeoutError', 'NetworkError'].includes(error?.name)) });
      }
      if (!response.ok || !response.headers.get("content-type")?.includes(contentType)) {
        let detail;
        if (!response.ok && response.headers.get("content-type")?.includes("application/json")) {
          try { detail = (await response.json()).detail; } catch (_) { /* use the fallback */ }
        }
        throw Object.assign(new Error(typeof detail === "string" ? detail : response.status === 401 || response.status === 403
          ? "Authentication is required. Reload the page to sign in."
          : "Refresh is temporarily unavailable. Retrying automatically."),
        { transientRead: readOnly && [502, 503, 504].includes(response.status) });
      }
      return response;
    };

    const updateView = async () => {
      // A frozen confirmation is a POST result, not a reloadable state page.
      // Queue/status still update; never GET/reparse/replace its targets or token.
      if (panel.dataset.frozenView === "true") {
        displayedVersion = version(status);
        return;
      }
      const response = await fetchChecked(pageUrl, { headers: { Accept: "text/html" } }, "text/html");
      const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
      const renderedStatus = readInitial(nextDocument);
      // Validate all regions before touching the live document (including an
      // authentication response or a partial/error render).
      const replacements = [...document.querySelectorAll("[data-live-region]")].filter(
        region => !region.parentElement?.closest('[data-live-region]') && !region.closest('dialog'),
      ).map((region) => {
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
      document.dispatchEvent(new CustomEvent('ftd:view-updated'));
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
              method: "POST", body: action.sourceForm?.matches("[data-managed-cancel-form]")
                ? new URLSearchParams(action.body) : action.body,
              headers: { Accept: "application/json" },
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
        readRetryNotice = "";
        readFailureSince = null;
      } catch (error) {
        failures += 1;
        if (readFailureSince === null) readFailureSince = Date.now();
        const briefReadFailure = error.transientRead && !errorMessage
          && failures < 3 && Date.now() - readFailureSince < 30000;
        readRetryNotice = briefReadFailure
          ? "Latest information is temporarily unavailable. Keeping displayed data and retrying automatically…" : "";
        errorMessage = briefReadFailure ? "" : failureText(error);
      } finally {
        busy = false;
        render();
        schedule(manualPending || actionPending ? 0 : failures ? Math.min(30000, 3000 * 2 ** Math.min(failures, 3))
          : status.refresh_in_progress || status.pending_refresh_device_count > 0 || status.interactive_refresh_state === "queued" ? 1000 : 5000);
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
      if (event.defaultPrevented) return;
      if (!event.target.matches("[data-queue-form], [data-policy-form], [data-managed-cancel-form], [data-managed-control-form]")) return;
      event.preventDefault();
      submitAction(event.target.action, new FormData(event.target), event.submitter, event.target);
    });
    document.addEventListener("input", (event) => {
      const policyForm = event.target.closest("[data-policy-form]");
      if (policyForm) policyForm.dataset.dirty = "true";
    });
    document.querySelectorAll('[data-open-status]').forEach(trigger => trigger.addEventListener('click', () => {
      const menu = panel.querySelector('#status-menu');
      menu.open = true;
      menu.querySelector('summary').focus();
    }));
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
    menus.filter((menu) => !menu.contains(event.target) && !event.target.closest("[data-open-status]")).forEach((menu) => { menu.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = menus.find((menu) => menu.open);
    if (open) { open.open = false; open.querySelector("summary").focus(); }
  });
  document.querySelectorAll("[data-refresh-controller]").forEach(createController);
})();
