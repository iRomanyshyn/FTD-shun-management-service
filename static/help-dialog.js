// Local presentation only. Help never fetches data or submits an action.
(() => {
  const dialog = document.querySelector('[data-help-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function') return; // Native details remain usable.
  const title = dialog.querySelector('[data-help-title]');
  const content = dialog.querySelector('[data-help-content]');
  let originalFocus = null, sourceId = null, backdropPress = false;
  const close = () => dialog.close();
  document.addEventListener('click', event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const trigger = event.target.closest('summary.help-trigger');
    const topic = trigger?.parentElement;
    if (!topic?.matches('details[data-help-topic]')) return;
    const body = topic.querySelector(':scope > [data-help-body]');
    if (!body) return;
    event.preventDefault();
    originalFocus = trigger; sourceId = topic.id;
    title.textContent = trigger.getAttribute('aria-label') || 'Help';
    const copy = body.cloneNode(true);
    // Only explanatory markup belongs in help; never duplicate live editors,
    // forms, request tokens, controllers or document IDs into the overlay.
    copy.querySelectorAll('script, form, input, textarea, select, button, iframe, object, embed, [data-refresh-controller]').forEach(node => node.remove());
    copy.querySelectorAll('[id], [data-live-region], [data-live-editor]').forEach(node => {
      node.removeAttribute('id'); node.removeAttribute('data-live-region'); node.removeAttribute('data-live-editor');
    });
    content.replaceChildren(...copy.childNodes);
    topic.open = false;
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
  });
  dialog.querySelector('[data-help-close]').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  const outside = event => {
    const box = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom);
  };
  dialog.addEventListener('pointerdown', event => { backdropPress = event.button === 0 && outside(event); });
  dialog.addEventListener('pointercancel', () => { backdropPress = false; });
  dialog.addEventListener('click', event => {
    const dismiss = backdropPress && event.button === 0 && outside(event);
    backdropPress = false;
    if (dismiss) close();
  });
  dialog.addEventListener('close', () => {
    const target = originalFocus?.isConnected ? originalFocus
      : sourceId ? document.getElementById(sourceId)?.querySelector(':scope > summary') : null;
    target?.focus({ preventScroll: true });
    content.replaceChildren(); originalFocus = null; sourceId = null; backdropPress = false;
  });
})();
