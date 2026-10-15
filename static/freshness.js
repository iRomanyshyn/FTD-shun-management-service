(() => {
  const formatTimestamp = (timestamp) => new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(new Date(timestamp));

  const duration = (seconds) => {
    const safeSeconds = Math.max(0, Math.ceil(seconds));
    const minutes = Math.floor(safeSeconds / 60);
    const remainder = safeSeconds % 60;
    return minutes > 0
      ? `${minutes}m ${remainder.toString().padStart(2, "0")}s`
      : `${remainder}s`;
  };

  const localizeTimestamps = (root = document) => {
    root.querySelectorAll(".local-timestamp[datetime]").forEach((element) => {
      const timestamp = Date.parse(element.dateTime);
      if (!Number.isNaN(timestamp)) element.textContent = formatTimestamp(timestamp);
    });
  };

  const timestampOrEmpty = (value) => typeof value === "string" ? value : "";

  const createRefreshController = (panel) => {
    const statusUrl = panel.dataset.statusUrl;
    const statusText = panel.querySelector(".refresh-status");
    const lastSuccessful = panel.querySelector(".last-successful-refresh");
    const baselineCountdown = panel.querySelector(".baseline-countdown");
    const interactiveStatus = panel.querySelector(".interactive-refresh-status");
    const form = panel.querySelector("[data-refresh-form]");
    const button = panel.querySelector("[data-refresh-request]");
    let reloadScheduled = false;
    let requestInFlight = false;
    let pollTimer = null;
    let refresh = {
      last_successful_refresh: panel.dataset.initialLastSuccessful || null,
      last_error: panel.dataset.initialError || null,
      refresh_in_progress: false,
      next_baseline_refresh: baselineCountdown?.dataset.nextBaseline || null,
      next_interactive_refresh: button?.dataset.nextInteractive || null,
      interactive_min_interval_seconds: Number(statusText?.dataset.minInterval) || 0,
      interactive_refresh_state: statusText?.dataset.state || "idle",
    };
    const initialSuccessful = refresh.last_successful_refresh;
    const initialError = refresh.last_error;

    const scheduleReloadForNewState = () => {
      if (reloadScheduled) return;
      reloadScheduled = true;
      if (button) {
        button.disabled = true;
        button.textContent = "Updating results…";
      }
      window.setTimeout(() => window.location.reload(), 250);
    };

    const updateCountdown = () => {
      if (!baselineCountdown) return;
      const target = Date.parse(refresh.next_baseline_refresh || "");
      if (Number.isNaN(target)) return;
      const remaining = (target - Date.now()) / 1000;
      baselineCountdown.textContent = remaining > 0 ? `in ${duration(remaining)}` : "due now";
    };

    const updateButton = () => {
      if (!button) return;
      const state = refresh.interactive_refresh_state;
      const now = Date.now();
      const baseline = Date.parse(refresh.next_baseline_refresh || "");
      const interactive = Date.parse(refresh.next_interactive_refresh || "");
      const baselineRemaining = Number.isNaN(baseline) ? null : (baseline - now) / 1000;
      const interactiveRemaining = Number.isNaN(interactive) ? null : (interactive - now) / 1000;
      if (requestInFlight || refresh.refresh_in_progress) {
        button.disabled = true;
        button.textContent = "Refreshing…";
      } else if (state === "baseline_pending" && baselineRemaining !== null && baselineRemaining > 0) {
        button.disabled = true;
        button.textContent = `Scheduled refresh (${duration(baselineRemaining)})`;
      } else if (state === "queued") {
        button.disabled = true;
        button.textContent = interactiveRemaining !== null && interactiveRemaining > 0
          ? `Refresh requested (${duration(interactiveRemaining)})`
          : "Refresh requested";
      } else if (interactiveRemaining !== null && interactiveRemaining > 0) {
        button.disabled = true;
        button.textContent = `Request refresh (${duration(interactiveRemaining)})`;
      } else {
        button.disabled = false;
        button.textContent = "Request refresh";
      }
    };

    const updateInteractiveStatus = () => {
      if (!interactiveStatus) return;
      const state = refresh.interactive_refresh_state;
      if (refresh.refresh_in_progress) {
        interactiveStatus.textContent = "A background refresh is in progress.";
      } else if (state === "queued") {
        interactiveStatus.textContent = "A refresh request is queued.";
      } else if (state === "baseline_pending") {
        interactiveStatus.textContent = "The scheduled refresh will run at the displayed time.";
      } else if (state === "rate_limited") {
        interactiveStatus.textContent = "Interactive refresh is temporarily rate-limited.";
      } else {
        interactiveStatus.textContent = "Automatic refresh is active.";
      }
    };

    const render = () => {
      if (statusText) {
        statusText.dataset.state = refresh.interactive_refresh_state || "idle";
        statusText.dataset.lastSuccessful = timestampOrEmpty(refresh.last_successful_refresh);
        statusText.dataset.nextInteractive = timestampOrEmpty(refresh.next_interactive_refresh);
      }
      if (lastSuccessful && refresh.last_successful_refresh) {
        lastSuccessful.dateTime = refresh.last_successful_refresh;
        lastSuccessful.textContent = formatTimestamp(refresh.last_successful_refresh);
      }
      if (baselineCountdown) {
        baselineCountdown.dataset.nextBaseline = timestampOrEmpty(refresh.next_baseline_refresh);
      }
      updateCountdown();
      updateButton();
      updateInteractiveStatus();
    };

    const applyRefresh = (payload) => {
      if (!payload || typeof payload !== "object") throw new Error("invalid refresh status");
      refresh = { ...refresh, ...payload };
      render();
      const successfulChanged = refresh.last_successful_refresh
        && refresh.last_successful_refresh !== initialSuccessful;
      const errorChanged = refresh.last_error && refresh.last_error !== initialError;
      if (successfulChanged || errorChanged) scheduleReloadForNewState();
    };

    const poll = async () => {
      try {
        const response = await fetch(statusUrl, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (!response.ok) throw new Error("status request failed");
        applyRefresh(await response.json());
      } catch (_) {
        if (interactiveStatus) interactiveStatus.textContent = "Refresh status is temporarily unavailable.";
      } finally {
        if (!reloadScheduled) {
          window.clearTimeout(pollTimer);
          pollTimer = window.setTimeout(poll, 3000);
        }
      }
    };

    const requestRefresh = async () => {
      if (!form || requestInFlight || button?.disabled) return;
      requestInFlight = true;
      updateButton();
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error("refresh request failed");
        applyRefresh(await response.json());
      } catch (_) {
        if (button) {
          button.disabled = false;
          button.textContent = "Refresh unavailable — retry";
        }
      } finally {
        requestInFlight = false;
        updateButton();
        poll();
      }
    };

    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      requestRefresh();
    });
    render();
    localizeTimestamps(panel);
    poll();
    if (panel.dataset.autoRequest === "true") requestRefresh();
    window.setInterval(() => {
      updateCountdown();
      updateButton();
    }, 1000);
  };

  localizeTimestamps();
  document.querySelectorAll("[data-refresh-controller]").forEach(createRefreshController);
})();
