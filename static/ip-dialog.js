// Canonical IP links stay ordinary URLs; the overlay is a GET-only enhancement.
(() => {
  const canonical = value => {
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(value)) return false;
    const parts = value.split('.').map(Number);
    return parts.every(part => part <= 255) && parts.join('.') === value;
  };
  window.FtdIpItem = {
    create(ip, info) {
      const item = document.createElement('span'); item.className = 'ip-item ip-summary'; item.dataset.ip = ip;
      item.setAttribute('data-ip-context-list', '');
      const heading = document.createElement('span'); heading.className = 'ip-item-heading';
      const link = document.createElement('a'); link.href = `/shuns/${encodeURIComponent(ip)}`;
      link.textContent = ip; link.setAttribute('data-ip-link', ''); heading.append(link);
      const context = document.createElement('span'); context.className = `ip-context-inline${info?.state === 'ready' ? '' : ' ip-context-empty'}`;
      context.textContent = info?.state === 'ready'
        ? [info.country, info.asn ? `AS${info.asn}` : null, info.organization || info.network || info.registry].filter(Boolean).join(' · ')
        : info?.state === 'skipped' ? 'Special-use address'
          : ['pending','looking_up','not_requested'].includes(info?.state) ? 'Information pending' : 'No cached information';
      context.title = context.textContent;
      item.append(heading, context); return item;
    }
  };
  const dialog = document.querySelector('dialog[data-ip-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const content = dialog.querySelector('[data-ip-content]');
  const status = dialog.querySelector('[data-ip-status]');
  const fullPage = dialog.querySelector('[data-ip-full-page]');
  const pageId = crypto.randomUUID();
  const background = location.href;
  let target = null, controller = null, sequence = 0, originalFocus = null, dirty = false;
  const say = (text, error = false) => {
    status.textContent = text; status.hidden = !text; status.classList.toggle('preview-error', error);
  };
  const localize = root => root.querySelectorAll('time[datetime]').forEach(node => {
    const date = new Date(node.dateTime);
    if (Number.isFinite(date.getTime())) node.textContent = new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium', timeStyle: 'long'
    }).format(date);
  });
  const load = async (url, refresh = false) => {
    controller?.abort(); controller = new AbortController();
    const selected = ++sequence;
    const state = refresh ? window.FtdUiState?.capture(content) : null;
    const scroll = dialog.scrollTop;
    if (!refresh) { content.replaceChildren(); say('Loading IP information…'); }
    content.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'text/html', 'X-IP-Dialog': '1' },
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
      if (new URL(response.url || url).origin !== location.origin
          || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Invalid IP page.');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const main = page.querySelector('main');
      if (!main) throw new Error('Incomplete IP page.');
      if (selected !== sequence || !dialog.open) return;
      main.querySelectorAll('script, [data-refresh-controller]').forEach(node => node.remove());
      main.querySelectorAll('[data-live-region], [data-live-editor]').forEach(node => {
        node.removeAttribute('data-live-region'); node.removeAttribute('data-live-editor');
      });
      // Keep labels/anchors unique even when the background is another IP page.
      const ids = new Map([...main.querySelectorAll('[id]')].map(node => [node.id, `ip-frame-${node.id}`]));
      main.querySelectorAll('[id]').forEach(node => { node.id = ids.get(node.id); });
      main.querySelectorAll('[for], [aria-labelledby], [aria-describedby], [aria-controls], a[href^="#"]').forEach(node => {
        ['for', 'aria-labelledby', 'aria-describedby', 'aria-controls'].forEach(name => {
          if (node.hasAttribute(name)) node.setAttribute(name, node.getAttribute(name).split(' ').map(id => ids.get(id) || id).join(' '));
        });
        if (node.getAttribute('href')?.startsWith('#') && ids.has(node.hash.slice(1))) node.hash = ids.get(node.hash.slice(1));
      });
      content.replaceChildren(...[...main.childNodes].map(node => document.importNode(node, true)));
      localize(content);
      if (state) { window.FtdUiState.restore(content, state); dialog.scrollTop = scroll; }
      else {
        const heading = content.querySelector('h1');
        if (heading) { heading.tabIndex = -1; heading.focus(); }
        const anchor = new URL(url).hash.slice(1);
        if (anchor) content.querySelector(`[id="ip-frame-${CSS.escape(anchor)}"]`)?.scrollIntoView({ block: 'start' });
      }
      say(response.ok ? '' : 'IP information could not be loaded. You can retry or open the full page.', !response.ok);
      dialog.querySelector('[data-ip-retry]').hidden = response.ok;
      dirty = false;
    } catch (error) {
      if (selected !== sequence || !dialog.open || error.name === 'AbortError') return;
      say('IP information is temporarily unavailable. Retry or open the full page.', true);
      dialog.querySelector('[data-ip-retry]').hidden = false;
    } finally {
      if (selected === sequence) content.removeAttribute('aria-busy');
    }
  };
  const open = url => {
    target = url.href; fullPage.href = target;
    dialog.querySelector('[data-ip-retry]').hidden = true;
    if (!dialog.open) dialog.showModal();
    load(target);
  };
  const close = () => {
    ++sequence; controller?.abort(); target = null;
    if (dialog.open) dialog.close();
    if (originalFocus?.isConnected) originalFocus.focus({ preventScroll: true });
    else if (originalFocus?.getAttribute('href')) {
      document.querySelector(`main a[href="${CSS.escape(originalFocus.getAttribute('href'))}"]`)?.focus({ preventScroll: true });
    }
  };
  const requestClose = () => {
    if (history.state?.ftdIp?.pageId === pageId) history.back();
    else close();
  };
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        || link.target || link.hasAttribute('download') || link.hasAttribute('data-ip-full-page')) return;
    const url = new URL(link.href, location.href), match = /^\/shuns\/([^/]+)$/.exec(url.pathname);
    if (url.origin !== location.origin || !match || !canonical(match[1]) || url.search) return;
    event.preventDefault();
    if (!dialog.open) originalFocus = link;
    const state = { ...history.state, ftdIp: { pageId, background, target: url.href } };
    if (history.state?.ftdIp?.pageId === pageId) history.replaceState(state, '', url);
    else history.pushState(state, '', url);
    open(url);
  });
  window.addEventListener('popstate', () => {
    if (history.state?.ftdIp?.pageId === pageId) open(new URL(history.state.ftdIp.target));
    else close();
  });
  dialog.querySelector('[data-ip-close]').addEventListener('click', requestClose);
  // Native backdrops retarget events to the dialog. Check geometry as well:
  // padding clicks and drags that started inside must not dismiss the frame.
  let backdropPress = false;
  const outside = event => {
    const box = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom);
  };
  dialog.addEventListener('pointerdown', event => { backdropPress = event.button === 0 && outside(event); });
  dialog.addEventListener('pointercancel', () => { backdropPress = false; });
  dialog.addEventListener('click', event => {
    const dismiss = backdropPress && outside(event);
    backdropPress = false;
    if (dismiss) { event.preventDefault(); event.stopPropagation(); requestClose(); }
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); requestClose(); });
  dialog.querySelector('[data-ip-retry]').addEventListener('click', () => { if (target) load(target, true); });
  document.addEventListener('ftd:view-updated', () => {
    if (!dialog.open || !target) return;
    if (document.querySelector('[data-action-dialog][open]')) dirty = true;
    else load(target, true);
  });
  document.querySelector('[data-action-dialog]')?.addEventListener('close', () => {
    if (dialog.open && target && dirty) load(target, true);
  });
})();
