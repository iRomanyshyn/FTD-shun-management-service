(() => {
  const countdowns = document.querySelectorAll(".baseline-countdown[data-next-baseline]");
  const refreshStatuses = document.querySelectorAll(".refresh-status");
  const refreshButtons = document.querySelectorAll("[data-refresh-request]");
  const localTimestamps = document.querySelectorAll(".local-timestamp[datetime]");
  let reloadScheduled = false;

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

  const update = (element) => {
    const target = Date.parse(element.dataset.nextBaseline);
    if (Number.isNaN(target)) {
      return;
    }
    const remaining = (target - Date.now()) / 1000;
    if (remaining <= 0) {
      element.textContent = element.dataset.reloadOnDue === "true" ? "refreshing…" : "due now";
      if (element.dataset.reloadOnDue === "true" && !reloadScheduled) {
        reloadScheduled = true;
        window.setTimeout(() => window.location.reload(), 1500);
      }
      return;
    }
    element.textContent = `in ${duration(remaining)}`;
  };

  const updateRefreshStatus = (element) => {
    const lastSuccessful = Date.parse(element.dataset.lastSuccessful);
    const minimumInterval = Number(element.dataset.minInterval);
    const state = element.dataset.state;
    const nextInteractive = Date.parse(element.dataset.nextInteractive);
    const lastTime = element.querySelector(".last-successful-refresh");
    const message = element.querySelector(".interactive-refresh-status");
    if (!Number.isNaN(lastSuccessful) && lastTime) {
      lastTime.textContent = formatTimestamp(lastSuccessful);
    }
    if (!message) return;
    if (state === "queued") {
      const remaining = Number.isNaN(nextInteractive) ? null : (nextInteractive - Date.now()) / 1000;
      message.textContent = remaining !== null && remaining > 0
        ? `A refresh was requested. Another request is available in ${duration(remaining)}.`
        : "A background refresh is queued.";
    } else if (state === "baseline_pending") {
      const nextBaseline = element.querySelector(".baseline-countdown");
      message.textContent = nextBaseline
        ? "The scheduled refresh will run at the displayed time."
        : "The scheduled refresh is pending.";
    } else if (state === "rate_limited" && minimumInterval > 0) {
      const remaining = Number.isNaN(nextInteractive)
        ? (lastSuccessful + minimumInterval * 1000 - Date.now()) / 1000
        : (nextInteractive - Date.now()) / 1000;
      message.textContent = remaining > 0
        ? `Interactive refresh available in ${duration(remaining)}.`
        : "Interactive refresh is available.";
    } else {
      message.textContent = minimumInterval > 0
        ? `Interactive refresh is protected by a ${duration(minimumInterval)} minimum interval.`
        : "Automatic refresh is active.";
    }
  };

  const updateRefreshButton = (button) => {
    const state = button.dataset.state;
    const target = Date.parse(button.dataset.nextInteractive);
    const baseline = Date.parse(button.dataset.nextBaseline);
    const remaining = Number.isNaN(target) ? null : (target - Date.now()) / 1000;
    const baselineRemaining = Number.isNaN(baseline) ? null : (baseline - Date.now()) / 1000;
    if (state === "baseline_pending" && baselineRemaining !== null && baselineRemaining > 0) {
      button.disabled = true;
      button.textContent = `Scheduled refresh (${duration(baselineRemaining)})`;
      return;
    }
    if (state === "queued" && (remaining === null || remaining > 0)) {
      button.disabled = true;
      button.textContent = remaining === null
        ? "Refresh requested"
        : `Refresh requested (${duration(remaining)})`;
      return;
    }
    if (remaining !== null && remaining > 0) {
      button.disabled = true;
      button.textContent = `Request refresh (${duration(remaining)})`;
      return;
    }
    button.disabled = false;
    button.textContent = "Request refresh";
  };

  countdowns.forEach(update);
  refreshStatuses.forEach(updateRefreshStatus);
  refreshButtons.forEach(updateRefreshButton);
  localTimestamps.forEach((element) => {
    const timestamp = Date.parse(element.dateTime);
    if (!Number.isNaN(timestamp)) element.textContent = formatTimestamp(timestamp);
  });
  if (countdowns.length > 0 || refreshButtons.length > 0) {
    window.setInterval(() => {
      countdowns.forEach(update);
      refreshStatuses.forEach(updateRefreshStatus);
      refreshButtons.forEach(updateRefreshButton);
    }, 1000);
  }
})();
