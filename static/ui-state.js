// Presentation state only: no form values, authority, tokens or request bodies.
(() => {
  const storageKey = `ftd-disclosures:${location.pathname}${location.search}`;
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch (_) {}
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) saved = {};
  const disclosures = root => [...(root.matches?.('details') ? [root] : []), ...root.querySelectorAll('details')];
  const key = element => {
    if (element.dataset.uiKey) return `key:${element.dataset.uiKey}`;
    if (element.id) return `id:${element.id}`;
    const owner = element.parentElement?.closest('[data-ip], [data-managed-target], [data-event-id], [data-operation-id], [data-request-id], [data-import-id], [id]');
    const scope = owner ? owner.id || ['ip', 'managedTarget', 'eventId', 'operationId', 'requestId', 'importId']
      .map(name => owner.dataset[name] || '').join(':') : 'page';
    const summary = element.querySelector(':scope > summary')?.textContent.trim();
    return summary ? `${scope}:summary:${summary}` : null;
  };
  const capture = root => {
    const details = new Map(disclosures(root).map(element => [key(element), element.open]).filter(([id]) => id));
    const focused = document.activeElement;
    const summary = focused?.matches('summary') && root.contains(focused) ? key(focused.parentElement) : null;
    return { details, summary };
  };
  const restore = (root, state) => {
    let focus;
    disclosures(root).forEach(element => {
      const id = key(element);
      if (id && state.details.has(id)) element.open = state.details.get(id);
      if (id && state.summary === id) focus = element.querySelector(':scope > summary');
    });
    focus?.focus({ preventScroll: true });
  };
  window.FtdUiState = { capture, restore };
  // Same-tab reloads retain disclosure choices; storage failures are harmless.
  const initial = new Map(Object.entries(saved).filter(([, value]) => typeof value === 'boolean'));
  restore(document, { details: initial });
  document.addEventListener('toggle', event => {
    const element = event.target;
    if (!(element instanceof HTMLDetailsElement) || element.closest('dialog')) return;
    const id = key(element);
    if (!id) return;
    delete saved[id];
    saved[id] = element.open;
    saved = Object.fromEntries(Object.entries(saved).slice(-1000));
    try { sessionStorage.setItem(storageKey, JSON.stringify(saved)); } catch (_) {}
  }, true);
})();
