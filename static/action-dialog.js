(() => {
  const dialog = document.querySelector('dialog[data-action-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function') return; // Native forms remain usable.
  const content = dialog.querySelector('[data-action-content]');
  const status = dialog.querySelector('[data-action-status]');
  const close = dialog.querySelector('[data-action-close]');
  const retry = dialog.querySelector('[data-action-retry]');
  let busy = false;
  let originalFocus = null;
  let uncertain = null;
  const reviewPaths = new Set(['/ip-actions/unblock', '/ip-actions/unblock-everywhere',
    '/managed-shuns/removal-review', '/managed-shuns/fleet-removal-review',
    '/managed-shuns/retirement-review', '/managed-shuns/v2/removal-review',
    '/managed-shuns/v2/fleet-removal-review', '/managed-shuns/v2/ordered-removal-review',
    '/managed-shuns/v2/ordered-fleet-removal-review']);
  const showStatus = (message, error = false) => {
    status.textContent = message;
    status.hidden = !message;
    status.classList.toggle('preview-error', error);
  };
  const open = () => { if (!dialog.open) dialog.showModal(); };
  const load = async (request) => {
    if (busy) return;
    busy = true;
    close.disabled = true;
    retry.hidden = true;
    content.setAttribute('aria-busy', 'true');
    const buttons = [...content.querySelectorAll('button[type="submit"], button:not([type])')];
    const states = buttons.map(button => button.disabled);
    buttons.forEach(button => { button.disabled = true; });
    showStatus(request.write ? 'Submitting request…' : 'Loading action…');
    try {
      const response = await fetch(request.url, {
        method: 'POST', body: request.body, credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'text/html', 'X-Action-Dialog': '1' },
        signal: AbortSignal.timeout(30000)
      });
      if (new URL(response.url || request.url).origin !== location.origin
          || !response.headers.get('content-type')?.includes('text/html')) {
        throw new Error('The server did not return an action page.');
      }
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const main = page.querySelector('main');
      if (!main) throw new Error('The action page was incomplete.');
      // Trusted same-origin, server-escaped markup only. Never execute scripts,
      // nest a refresh controller or let background refresh replace this review.
      main.querySelectorAll('script, [data-refresh-controller]').forEach(node => node.remove());
      content.replaceChildren(...[...main.childNodes].map(node => document.importNode(node, true)));
      content.querySelectorAll('time[datetime]').forEach(node => {
        const date = new Date(node.dateTime);
        if (Number.isFinite(date.getTime())) node.textContent = new Intl.DateTimeFormat(undefined, {
          dateStyle: 'medium', timeStyle: 'long'
        }).format(date);
      });
      if (request.write && response.status >= 500) {
        uncertain = request;
        retry.hidden = false;
        showStatus('The outcome is not confirmed. Retry this same request; do not submit another action.', true);
      } else {
        uncertain = null;
        showStatus(response.ok ? '' : 'This request could not be completed. See the message below.', !response.ok);
      }
      const heading = content.querySelector('h1');
      if (heading) { heading.tabIndex = -1; heading.focus(); }
      document.dispatchEvent(new CustomEvent('action-dialog:updated'));
    } catch (_) {
      // Keep the original review DOM and captured bytes/key. No automatic write
      // retry or renewed preparation after a lost confirmation response.
      uncertain = request;
      retry.hidden = false;
      showStatus(request.write
        ? 'The request outcome is unknown. Retry this same request to check it safely.'
        : 'Unable to load the action. Retry or close this window.', true);
    } finally {
      buttons.forEach((button, index) => { if (button.isConnected) button.disabled = states[index]; });
      busy = false;
      close.disabled = false;
      content.removeAttribute('aria-busy');
    }
  };
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    if (form.method.toLowerCase() !== 'post') return;
    const url = new URL(form.action, location.href);
    const simpleRemoval = /^\/(devices\/\d+\/shuns\/[0-9.]+\/remove|shuns\/[0-9.]+\/remove-all)$/.test(url.pathname);
    if (!dialog.contains(form) && !form.hasAttribute('data-open-action')
        && !reviewPaths.has(url.pathname) && !simpleRemoval) return;
    if (url.origin !== location.origin) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (busy) return;
    if (!dialog.contains(form)) {
      originalFocus = event.submitter;
      if (!uncertain) content.replaceChildren();
    }
    open();
    if (uncertain) {
      retry.hidden = false;
      showStatus('A previous request still needs its result checked. Retry that same request first.', true);
      return;
    }
    const body = new FormData(form, event.submitter);
    load({ url: url.href, body, write: body.has('confirm_action') });
  }, true);
  retry.addEventListener('click', () => { if (uncertain) load(uncertain); });
  close.addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    if (originalFocus?.isConnected) originalFocus.focus({ preventScroll: true });
    else {
      const heading = document.querySelector('main h1');
      if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    }
  });
})();
