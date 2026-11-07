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

  let worldFilters = {};
  let worldTotal = 0;
  const worldPageSize = 50;

  function renderWorldList(worlds, offset) {
    const rows = worlds.map((world) => (
      `<div class="list-surface"><strong>${escapeHtml(world.display_name)}</strong>` +
      `<span class="status-indicator" data-tone="${worldTone(world.state)}">${escapeHtml(world.state)}</span>` +
      `<p class="muted">${escapeHtml(world.server_type)} | ${escapeHtml(world.mc_version)} | Port ${escapeHtml(world.port)}</p></div>`
    )).join('');
    const previousOffset = Math.max(0, offset - worldPageSize);
    const nextOffset = offset + worldPageSize;
    root.innerHTML =
      `<section data-world-list><form data-world-filters class="world-filter-form">` +
      `<label>Search<input class="ui-text-input" name="search" value="${escapeHtml(worldFilters.search || '')}"></label>` +
      `<label>State<select class="ui-text-input" name="state">${option('state', '', 'All states')}${option('state', 'off', 'Off')}${option('state', 'queued', 'Queued')}${option('state', 'starting', 'Starting')}${option('state', 'running', 'Running')}${option('state', 'stopping', 'Stopping')}${option('state', 'backing_up', 'Backing up')}${option('state', 'restoring', 'Restoring')}${option('state', 'crashed', 'Crashed')}${option('state', 'error', 'Error')}${option('state', 'eula_required', 'EULA required')}</select></label>` +
      `<label>Server type<select class="ui-text-input" name="server_type">${option('server_type', '', 'All types')}${option('server_type', 'vanilla', 'Vanilla')}${option('server_type', 'paper', 'Paper')}${option('server_type', 'forge', 'Forge')}${option('server_type', 'fabric', 'Fabric')}</select></label>` +
      `<label>Version<input class="ui-text-input" name="mc_version" value="${escapeHtml(worldFilters.mc_version || '')}"></label>` +
      `<button class="ui-button ui-button-blue" type="submit">Filter</button></form>` +
      `<div data-world-results>${rows || '<p class="muted">No worlds match these filters.</p>'}</div>` +
      `<div class="world-list-pagination"><span class="muted">${worldTotal} worlds</span>` +
      `<button class="ui-button" type="button" data-world-offset="${previousOffset}"${offset === 0 ? ' disabled' : ''}>Previous</button>` +
      `<button class="ui-button" type="button" data-world-offset="${nextOffset}"${nextOffset >= worldTotal ? ' disabled' : ''}>Next</button></div></section>`;
  }

  function option(key, value, title) {
    const selected = (worldFilters[key] || '') === value ? ' selected' : '';
    return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(title)}</option>`;
  }

  function worldTone(state) {
    if (state === 'running') return 'positive';
    if (state === 'crashed' || state === 'error') return 'negative';
    if (['starting', 'stopping', 'queued', 'backing_up', 'restoring'].includes(state)) return 'transitional';
    return 'neutral';
  }

  async function loadWorldList(offset = 0) {
    const query = new URLSearchParams({ limit: String(worldPageSize), offset: String(offset) });
    for (const [key, value] of Object.entries(worldFilters)) {
      if (value) query.set(key, value);
    }
    const response = await fetch(`/api/worlds?${query.toString()}`);
    const payload = await response.json();
    if (!payload.ok) {
      root.innerHTML = `<div class="list-surface">${escapeHtml(payload.error.message)}</div>`;
      return;
    }
    worldTotal = payload.meta.pagination.total;
    renderWorldList(payload.data.worlds, offset);
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
      root.innerHTML = slug === 'worlds' ? '' : page.sections
        .map((section) => (
          `<div class="list-surface"><h2>${escapeHtml(section.title)}</h2>` +
          `<p class="muted">${escapeHtml(section.summary)}</p></div>`
        ))
        .join('');
      if (slug === 'worlds') await loadWorldList();
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
    const pageButton = event.target.closest && event.target.closest('[data-world-offset]');
    if (pageButton && !pageButton.disabled) {
      await loadWorldList(Number(pageButton.dataset.worldOffset));
      return;
    }
    const anchor = event.target.closest && event.target.closest('a[data-page]');
    if (!anchor || event.defaultPrevented || event.metaKey || event.ctrlKey ||
      event.shiftKey || event.altKey || (event.button !== undefined && event.button !== 0)) {
      return;
    }
    event.preventDefault();
    await navigate(anchor.dataset.page, anchor.href);
  });

  if (root.addEventListener) root.addEventListener('submit', async (event) => {
    const form = event.target.closest && event.target.closest('[data-world-filters]');
    if (!form) return;
    event.preventDefault();
    const values = new FormData(form);
    worldFilters = {
      search: values.get('search') || '',
      state: values.get('state') || '',
      server_type: values.get('server_type') || '',
      mc_version: values.get('mc_version') || '',
    };
    await loadWorldList();
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
