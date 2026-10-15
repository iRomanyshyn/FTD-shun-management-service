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
  const version = (status) => `${status.instance_id}:${status.data_revision}:${status.cycle_revision}`;

  // Retain editable values and focus only for the same form action and field.
  // Hidden security fields always come from the fresh server-rendered form.
  const replaceRegion = (oldRegion, nextRegion) => {
    const values = new Map();
    const fieldKey = (field) => `${field.form?.getAttribute("action") || ""}:${field.name}:${field.type}`;
    oldRegion.querySelectorAll("input:not([type=hidden]), textarea, select").forEach((field) => {
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
    replacement.querySelectorAll("input:not([type=hidden]), textarea, select").forEach((field) => {
      const saved = values.get(fieldKey(field));
      if (!saved) return;
      field.value = saved.value;
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
    const form = panel.querySelector("[data-refresh-form]");
    const button = panel.querySelector("[data-refresh-request]");
    const message = panel.querySelector("[data-refresh-message]");
    const warning = panel.querySelector("[data-refresh-warning]");
    const deviceRows = panel.querySelector("[data-device-status]");
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
      warning.hidden = !status.last_error;
      warning.textContent = status.last_error ? `Refresh warning: ${status.last_error}` : "";
      message.textContent = errorMessage || (status.refresh_in_progress
        ? "Refreshing device information…"
        : status.cycle_revision > 0
          ? ({ success: "Refresh completed.", partial: "Refresh partially completed. Check device details.",
              failed: "Refresh failed. Previous observations are retained.",
              interrupted: "Refresh interrupted. Check device details." }[status.cycle_outcome] || "")
          : "Waiting for the first refresh.");
      message.classList.toggle("refresh-error", Boolean(errorMessage));
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
        throw new Error(response.status === 401 || response.status === 403
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
        if (manualPending) {
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
        schedule(manualPending ? 0 : failures ? Math.min(30000, 3000 * 2 ** Math.min(failures, 3))
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
  document.querySelectorAll("[data-refresh-controller]").forEach(createController);
})();
