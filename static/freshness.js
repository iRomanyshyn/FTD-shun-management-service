(() => {
  const countdowns = document.querySelectorAll(".baseline-countdown[data-next-baseline]");
  const refreshStatuses = document.querySelectorAll(".refresh-status");

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
    element.textContent = remaining <= 0
      ? "due now"
      : `in ${duration(remaining)}`;
  };

  const updateRefreshStatus = (element) => {
    const lastSuccessful = Date.parse(element.dataset.lastSuccessful);
    const minimumInterval = Number(element.dataset.minInterval);
    const state = element.dataset.state;
    const lastTime = element.querySelector(".last-successful-refresh");
    const message = element.querySelector(".interactive-refresh-status");
    if (!message) return;
    if (!Number.isNaN(lastSuccessful) && lastTime) {
      lastTime.textContent = new Date(lastSuccessful).toLocaleString();
    }
    if (state === "queued") {
      message.textContent = "A background refresh is queued.";
    } else if (state === "rate_limited" && !Number.isNaN(lastSuccessful) && minimumInterval > 0) {
      const remaining = (lastSuccessful + minimumInterval * 1000 - Date.now()) / 1000;
      message.textContent = remaining > 0
        ? `Interactive refresh available in ${duration(remaining)}.`
        : "Interactive refresh is available.";
    } else {
      message.textContent = minimumInterval > 0
        ? `Interactive refresh is protected by a ${duration(minimumInterval)} minimum interval.`
        : "Automatic refresh is active.";
    }
  };

  countdowns.forEach(update);
  refreshStatuses.forEach(updateRefreshStatus);
  if (countdowns.length > 0) {
    window.setInterval(() => {
      countdowns.forEach(update);
      refreshStatuses.forEach(updateRefreshStatus);
    }, 1000);
  }
})();
