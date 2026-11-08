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
  let worldOffset = 0;
  let worldActionStatus = '';
  const worldPageSize = 50;

  function renderWorldList(worlds, offset) {
    const rows = worlds.map((world) => (
      `<div class="list-surface world-row"><div class="world-row-header">` +
      `<div><strong>${escapeHtml(world.display_name)}</strong>` +
      `<p class="muted">${escapeHtml(world.server_type)} | ${escapeHtml(world.mc_version)} | Port ${escapeHtml(world.port)}</p></div>` +
      `<span class="status-indicator" data-tone="${worldTone(world.state)}">${escapeHtml(world.state)}</span></div>` +
      `<div class="world-row-actions">${worldActions(world)}</div></div>`
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
      `${worldActionStatus ? `<p class="world-action-status" role="status" aria-live="polite">${escapeHtml(worldActionStatus)}</p>` : ''}` +
      `<div data-world-results>${rows || '<p class="muted">No worlds match these filters.</p>'}</div>` +
      `<div class="world-list-pagination"><span class="muted">${worldTotal} worlds</span>` +
      `<button class="ui-button" type="button" data-world-offset="${previousOffset}"${offset === 0 ? ' disabled' : ''}>Previous</button>` +
      `<button class="ui-button" type="button" data-world-offset="${nextOffset}"${nextOffset >= worldTotal ? ' disabled' : ''}>Next</button></div></section>`;
  }

  function renderAuthForm(mode, message = '') {
    const isSetup = mode === 'setup';
    const title = isSetup ? 'Create the first administrator' : 'Sign in';
    const heading = document.querySelector('h1');
    if (heading) heading.textContent = title;
    if (document.body) document.body.dataset.authState = 'signed-out';
    root.innerHTML =
      `<form class="auth-form" data-auth-form data-auth-action="${mode}">` +
      `<h2>${title}</h2>` +
      `<label>Username<input class="ui-text-input" name="username" autocomplete="username" required></label>` +
      `<label>Password<input class="ui-text-input" type="password" name="password" ` +
      `autocomplete="${isSetup ? 'new-password' : 'current-password'}" required></label>` +
      `<p class="auth-status" role="status" aria-live="polite">${escapeHtml(message)}</p>` +
      `<button class="ui-button ui-button-blue" type="submit">${isSetup ? 'Create administrator' : 'Sign in'}</button>` +
      `</form>`;
  }

  async function submitAuthForm(form) {
    const values = new FormData(form);
    const mode = form.dataset.authAction;
    const endpoint = mode === 'setup' ? '/api/setup' : '/api/auth/login';
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': cookieValue('csrf_token'),
        },
        body: JSON.stringify({
          username: values.get('username'),
          password: values.get('password'),
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        renderAuthForm(mode, payload.error?.message || 'Authentication failed.');
        return;
      }
      if (mode === 'setup') {
        renderAuthForm('login', 'Administrator created. Sign in to continue.');
        return;
      }
      if (document.body) document.body.dataset.authState = 'authenticated';
      await loadPage(main.dataset.activePage);
    } catch (_error) {
      renderAuthForm(mode, 'The request could not be completed.');
    }
  }

  async function initializeShell() {
    try {
      const response = await fetch('/api/session');
      const payload = await response.json();
      if (response.ok && payload.ok) {
        if (document.body) document.body.dataset.authState = 'authenticated';
        await loadPage(main.dataset.activePage);
        return;
      }
      const setupResponse = await fetch('/api/setup');
      const setupPayload = await setupResponse.json();
      if (setupResponse.ok && setupPayload.ok) {
        renderAuthForm(
          setupPayload.data.first_superadmin_required ? 'setup' : 'login',
        );
        return;
      }
    } catch (_error) {
      renderAuthForm('login', 'Unable to verify the current session.');
      return;
    }
    renderAuthForm('login', 'Unable to verify the current session.');
  }

  function worldActions(world) {
    const controls = [];
    if (world.state === 'off') {
      controls.push(actionButton(world, 'start', 'Start', 'ui-button-teal'));
    } else if (world.state === 'running') {
      controls.push(actionButton(world, 'stop', 'Stop', 'ui-button-red'));
    }
    if (world.state === 'off' || world.state === 'running') {
      controls.push(actionButton(world, 'backup', 'Backup', 'ui-button-blue'));
    }
    return controls.join('');
  }

  function actionButton(world, action, label, colorClass) {
    return `<button class="ui-button ${colorClass}" type="button" data-world-action="${action}" ` +
      `data-world-id="${escapeHtml(world.world_id)}">${label}</button>`;
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
    worldOffset = offset;
    renderWorldList(payload.data.worlds, offset);
  }

  function cookieValue(name) {
    const prefix = `${name}=`;
    const value = document.cookie.split(';').map((part) => part.trim())
      .find((part) => part.startsWith(prefix));
    return value ? decodeURIComponent(value.slice(prefix.length)) : '';
  }

  async function submitWorldAction(button) {
    const action = button.dataset.worldAction;
    const worldId = button.dataset.worldId;
    const headers = {
      'X-CSRF-Token': cookieValue('csrf_token'),
      'Idempotency-Key': `shell-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    };
    const options = { method: 'POST', headers };
    if (action === 'backup') {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify({ category: 'manual' });
    }
    try {
      const response = await fetch(`/api/worlds/${encodeURIComponent(worldId)}/${action}`, options);
      const payload = await response.json();
      worldActionStatus = response.ok && payload.ok
        ? `${action[0].toUpperCase()}${action.slice(1)} request accepted.`
        : (payload.error?.message || `${action} request failed.`);
    } catch (_error) {
      worldActionStatus = `${action[0].toUpperCase()}${action.slice(1)} request failed.`;
    }
    await loadWorldList(worldOffset);
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
    const actionButtonElement = event.target.closest && event.target.closest('[data-world-action]');
    if (actionButtonElement) {
      event.preventDefault();
      await submitWorldAction(actionButtonElement);
      return;
    }
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
    const authForm = event.target.closest && event.target.closest('[data-auth-form]');
    if (authForm) {
      event.preventDefault();
      await submitAuthForm(authForm);
      return;
    }
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

  initializeShell();
})();
