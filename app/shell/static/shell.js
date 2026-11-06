(function () {
  const root = document.querySelector('[data-page-root]');
  const main = document.querySelector('main');
  if (!root || !main) return;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[character]);
  }

  async function loadPage(slug) {
    try {
      const response = await fetch(`/api/pages/${encodeURIComponent(slug)}`);
      const payload = await response.json();
      if (!payload.ok) {
        root.innerHTML = `<div class="list-surface">${escapeHtml(payload.error.message)}</div>`;
        return;
      }

      const page = payload.data;
      root.innerHTML = page.sections
        .map((section) => (
          `<div class="list-surface"><h2>${escapeHtml(section.title)}</h2>` +
          `<p class="muted">${escapeHtml(section.summary)}</p></div>`
        ))
        .join('');
      const heading = document.querySelector('h1');
      if (heading) heading.textContent = page.title;
      main.dataset.activePage = slug;
      for (const anchor of document.querySelectorAll('a[data-page]')) {
        if (anchor.classList) {
          anchor.classList.toggle('is-active', anchor.dataset.page === slug);
        }
      }
    } catch (_error) {
      root.innerHTML = '<div class="list-surface">Page module unavailable.</div>';
    }
  }

  async function navigate(slug, url) {
    if (!slug) return;
    history.pushState({ slug }, '', url || `/pages/${slug}`);
    await loadPage(slug);
  }

  document.addEventListener('click', async (event) => {
    const anchor = event.target.closest && event.target.closest('a[data-page]');
    if (!anchor || event.defaultPrevented || event.metaKey || event.ctrlKey ||
      event.shiftKey || event.altKey || (event.button !== undefined && event.button !== 0)) {
      return;
    }
    event.preventDefault();
    await navigate(anchor.dataset.page, anchor.href);
  });

  const refresh = document.querySelector('[data-refresh]');
  if (refresh) {
    refresh.addEventListener('click', () => loadPage(main.dataset.activePage));
  }

  if (window.addEventListener) {
    window.addEventListener('popstate', (event) => {
      const slug = event.state && event.state.slug;
      if (slug) loadPage(slug);
    });
  }

  loadPage(main.dataset.activePage);
})();
