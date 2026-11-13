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
