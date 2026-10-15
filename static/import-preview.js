(() => {
  "use strict";
  const input = document.getElementById("blocklist-text");
  const counter = document.getElementById("paste-size");
  if (!input || !counter) return;
  const limit = Number(input.dataset.maxBytes);
  const encoder = new TextEncoder();
  const update = () => {
    // Native HTML form submission normalizes textarea newlines to CRLF.
    const bytes = encoder.encode(input.value.replace(/\r?\n/g, "\r\n")).length;
    const oversized = bytes > limit;
    input.setCustomValidity(oversized ? "Paste at most 1 MiB of UTF-8 text. Shorten the input; nothing will be parsed or queued." : "");
    counter.textContent = `${bytes.toLocaleString()} / ${limit.toLocaleString()} UTF-8 bytes (including form line endings). ${oversized ? "Over limit — shorten the input. Nothing will be parsed or queued." : "Input is not truncated."}`;
    counter.classList.toggle("preview-error", oversized);
    input.setAttribute("aria-invalid", String(oversized));
  };
  input.addEventListener("input", update);
  window.addEventListener("pageshow", update);
  update();
})();
