(() => {
  const indicator = document.querySelector('[data-navigation-loading]');
  if (!indicator) return;
  let navigation = 0;
  const reset = () => {
    navigation += 1;
    indicator.hidden = true;
    document.querySelector('main')?.removeAttribute('aria-busy');
    document.querySelectorAll('[data-navigation-pending]').forEach(link => link.removeAttribute('data-navigation-pending'));
  };
  window.addEventListener('pageshow', reset);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.action-menu[open]').forEach(menu => {
      menu.open = false;
      menu.querySelector('summary')?.focus();
    });
  });
  document.addEventListener('click', event => {
    document.querySelectorAll('.action-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
    const link = event.target.closest('a[data-open-details]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        || !link.getAttribute('href')?.startsWith('#')) return;
    const target = document.getElementById(link.hash.slice(1));
    if (!(target instanceof HTMLDetailsElement)) return;
    event.preventDefault();
    target.open = true;
    const menu = link.closest('.action-menu');
    if (menu) menu.open = false;
    target.querySelector('summary')?.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'center', behavior: 'instant' });
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('.primary-nav a');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol)) return;
    event.preventDefault();
    reset();
    const selected = navigation;
    indicator.querySelector('[data-navigation-message]').textContent = `Loading ${link.textContent.trim()}…`;
    indicator.hidden = false;
    document.querySelector('main')?.setAttribute('aria-busy', 'true');
    link.setAttribute('data-navigation-pending', 'true');
    // Paint before native navigation, without fetching/caching pages, replaying
    // forms or changing their CSRF/frozen-review behavior. Back/forward resets.
    requestAnimationFrame(() => setTimeout(() => {
      if (navigation === selected) location.assign(url.href);
    }, 0));
  });
})();
