(() => {
  const input = document.querySelector("#shun-ip-search");
  const rows = [...document.querySelectorAll("#shun-table tr[data-shun-ip]")];
  const summary = document.querySelector("#shun-search-summary");
  if (!input || !summary) return;

  const update = () => {
    const query = input.value.trim();
    let visible = 0;
    rows.forEach((row) => {
      const matches = !query || row.dataset.shunIp.startsWith(query);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    summary.textContent = query
      ? `${visible} matching active shun${visible === 1 ? "" : "s"}.`
      : `${rows.length} active shun${rows.length === 1 ? "" : "s"}.`;
  };

  input.addEventListener("input", update);
  update();
})();
