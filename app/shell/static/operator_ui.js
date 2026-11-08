(function () {
  const root = document.querySelector('[data-page-root]');
  const main = document.querySelector('main');
  if (!root || !main) return;

  const contextSelect = document.querySelector('[data-context-select]');
  let worlds = [];
  let worldId = '';
  let statusMessage = '';
  let cleanupOperationId = '';
  let cleanupWorldId = '';
  let cleanupOperationStatus = '';
  let auditFilters = {};
  let logTimer = null;
  let logOffset = 0;
  let logChannel = 'minecraft';

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);

  function button(label, action, id = '', color = '', disabled = false, title = '') {
    return `<button class="ui-button ${color}" type="button" data-ui-action="${action}" ` +
      `${id ? `data-id="${escapeHtml(id)}"` : ''}${disabled ? ' disabled' : ''}` +
      `${title ? ` title="${escapeHtml(title)}"` : ''}>${escapeHtml(label)}</button>`;
  }

  function field(label, name, value = '', type = 'text', required = false) {
    return `<label>${escapeHtml(label)}<input class="ui-text-input" name="${escapeHtml(name)}" ` +
      `type="${escapeHtml(type)}" value="${escapeHtml(value)}"${required ? ' required' : ''}></label>`;
  }

  function selectField(label, name, options, value = '') {
    return `<label>${escapeHtml(label)}<select class="ui-text-input" name="${escapeHtml(name)}">` +
      `${options.map(([key, text]) => `<option value="${escapeHtml(key)}"${String(key) === String(value) ? ' selected' : ''}>` +
        `${escapeHtml(text)}</option>`).join('')}</select></label>`;
  }

  function card(title, contents) {
    return `<section class="list-surface module-section"><h2>${escapeHtml(title)}</h2>${contents}</section>`;
  }

  function message() {
    return statusMessage ? `<p class="shell-feedback" role="status" aria-live="polite">${escapeHtml(statusMessage)}</p>` : '';
  }

  function unavailable(text, heading = 'Unavailable') {
    return `<div class="unavailable-state"><strong>${escapeHtml(heading)}</strong><p class="muted">${escapeHtml(text)}</p></div>`;
  }

  function query(values) {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== '' && value !== null && value !== undefined) params.set(key, String(value));
    });
    const encoded = params.toString();
    return encoded ? `?${encoded}` : '';
  }

  async function request(url, options = {}) {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (_error) { /* Non-JSON response. */ }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error?.message || `Request failed (${response.status}).`);
    }
    return payload;
  }

  function cookie(name) {
    const prefix = `${name}=`;
    const match = document.cookie.split(';').map((part) => part.trim()).find((part) => part.startsWith(prefix));
    return match ? decodeURIComponent(match.slice(prefix.length)) : '';
  }

  async function mutate(url, method, body, multipart = false) {
    const headers = {
      'X-CSRF-Token': cookie('csrf_token'),
      'Idempotency-Key': `shell-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    };
    const options = { method, headers };
    if (body !== undefined) {
      if (multipart) options.body = body;
      else {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
      }
    }
    return request(url, options);
  }

  async function loadWorlds() {
    try {
      const payload = await request('/api/worlds?limit=500&offset=0');
      worlds = payload.data.worlds || [];
      if (!worlds.some((world) => world.world_id === worldId)) worldId = worlds[0]?.world_id || '';
    } catch (_error) {
      worlds = [];
    }
    updateContext();
  }

  function updateContext() {
    if (!contextSelect) return;
    contextSelect.innerHTML = '<option value="manager">Manager</option>' + worlds.map((world) =>
      `<option value="${escapeHtml(world.world_id)}">World: ${escapeHtml(world.display_name)}</option>`).join('');
    const active = main.dataset.activePage;
    contextSelect.value = (active.startsWith('world-') || active === 'files') && worldId ? worldId : 'manager';
  }

  function renderAuth(mode, text = '') {
    const setup = mode === 'setup';
    const title = setup ? 'Create the first administrator' : 'Sign in';
    const heading = document.querySelector('h1');
    if (heading) heading.textContent = title;
    if (document.body) document.body.dataset.authState = 'signed-out';
    root.innerHTML = `<form class="auth-form" data-auth-form data-auth-action="${mode}"><h2>${title}</h2>` +
      `${field('Username', 'username', '', 'text', true)}${field('Password', 'password', '', 'password', true)}` +
      `<p class="auth-status" role="status" aria-live="polite">${escapeHtml(text)}</p>` +
      `<button class="ui-button ui-button-blue" type="submit">${setup ? 'Create administrator' : 'Sign in'}</button></form>`;
  }

  function values(form) {
    const result = {};
    for (const [key, value] of new FormData(form).entries()) result[key] = value;
    return result;
  }

  async function authenticate(form) {
    const data = values(form);
    const mode = form.dataset.authAction;
    try {
      await mutate(mode === 'setup' ? '/api/setup' : '/api/auth/login', 'POST', {
        username: data.username, password: data.password,
      });
      if (mode === 'setup') return renderAuth('login', 'Administrator created. Sign in to continue.');
      if (document.body) document.body.dataset.authState = 'authenticated';
      window.mcmanagerStreamClient?.resumeAfterAuthentication?.();
      await loadWorlds();
      await loadPage(main.dataset.activePage);
    } catch (error) {
      renderAuth(mode, error.message || 'Authentication failed.');
    }
  }

  function tone(state) {
    if (state === 'running') return 'positive';
    if (['error', 'crashed'].includes(state)) return 'negative';
    if (['starting', 'stopping', 'queued', 'backing_up', 'restoring'].includes(state)) return 'transitional';
    return 'neutral';
  }

  function worldControls(world) {
    return [
      button('Start', 'world-start', world.world_id, 'ui-button-teal', world.state !== 'off', 'Available when off'),
      button('Stop', 'world-stop', world.world_id, 'ui-button-red', world.state !== 'running', 'Available when running'),
      button('Kill', 'world-kill', world.world_id, 'ui-button-red', world.state !== 'running', 'Available when running'),
      button('Backup', 'world-backup', world.world_id, 'ui-button-blue', !['off', 'running'].includes(world.state), 'Available when off or running'),
    ].join('');
  }

  function worldRows(items) {
    return items.length ? items.map((world) => `<article class="list-surface world-row">` +
      `<div class="world-row-header"><div><strong>${escapeHtml(world.display_name)}</strong>` +
      `<p class="muted">${escapeHtml(world.server_type)} · ${escapeHtml(world.mc_version)} · Port ${escapeHtml(world.port)}</p></div>` +
      `<span class="status-indicator" data-tone="${tone(world.state)}">${escapeHtml(world.state)}</span></div>` +
      `<div class="world-row-actions">${worldControls(world)}` +
      `${button('Rename', 'world-rename', world.world_id)}` +
      `${button('Delete preview', 'world-delete', world.world_id, 'ui-button-red', world.state !== 'off', 'Available when off')}</div></article>`).join('') : '<p class="muted">No worlds available.</p>';
  }

  function worldChoices() {
    return [['', 'Manager-wide'], ...worlds.map((world) => [world.world_id, world.display_name])];
  }

  async function renderHome() {
    const [stats, notifications] = await Promise.all([
      request('/api/system/stats'), request('/api/notifications?limit=5&offset=0'),
    ]);
    const notices = notifications.data.notifications || [];
    root.innerHTML = message() + `<div class="metric-strip">` +
      `<div><span>Worlds</span><strong>${escapeHtml(stats.data.worlds_count)}</strong></div>` +
      `<div><span>Active</span><strong>${escapeHtml(stats.data.active_worlds)}</strong></div>` +
      `<div><span>Unread notices</span><strong>${escapeHtml(notifications.meta?.unread_count ?? 0)}</strong></div></div>` +
      card('World operations', worldRows(worlds)) + card('Recent notifications', notices.map((item) =>
        `<div class="table-row"><strong>${escapeHtml(item.severity)}</strong><span>${escapeHtml(item.message)}</span>` +
        `${button('Mark read', 'notification-read', item.notification_id)}</div>`).join('') || '<p class="muted">No notifications.</p>');
  }

  async function renderWorlds() {
    const [templatesResult, runtimesResult, schedulesResult] = await Promise.all([
      request('/api/templates?limit=100&offset=0'), request('/api/java-runtimes?limit=100&offset=0'),
      request('/api/schedules?limit=100&offset=0'),
    ]);
    const templates = templatesResult.data.templates || [];
    const runtimes = (runtimesResult.data.java_runtimes || []).filter((item) => ['registered', 'verified'].includes(item.status));
    const scheduleRows = schedulesResult.data.schedules || [];
    root.innerHTML = message() + card('Worlds', worldRows(worlds)) +
      `<form class="workflow-form" data-form="world-create"><h3>Create a world</h3>` +
      `${field('Display name', 'display_name', '', 'text', true)}` +
      `${selectField('Template', 'template_id', templates.map((item) => [item.template_id, `${item.name} · ${item.default_version}`]))}` +
      `${selectField('Java runtime', 'java_runtime_id', runtimes.map((item) => [item.runtime_id, `${item.label} · ${item.status}`]))}` +
      `${field('Port', 'port', '25565', 'number', true)}` +
      `${selectField('Addressing', 'addressing_strategy', [['port', 'Port'], ['subdomain', 'Subdomain'], ['path', 'Path']])}` +
      `${field('Address value', 'addressing_value', '25565', 'text', true)}` +
      `<button class="ui-button ui-button-blue" type="submit"${!templates.length || !runtimes.length ? ' disabled' : ''}>Queue world creation</button>` +
      `${!templates.length || !runtimes.length ? '<p class="muted">A live template and Java runtime are required first.</p>' : ''}</form>` +
      card('Backup schedules', scheduleRows.map((item) => `<div class="table-row"><span>${escapeHtml(item.scope)} · ${escapeHtml(item.time_of_day)}</span>` +
        `<span>${item.enabled ? 'Enabled' : 'Disabled'}</span>${button(item.enabled ? 'Disable' : 'Enable', 'schedule-toggle', item.schedule_id)}` +
        `${button('Delete', 'schedule-delete', item.schedule_id)}</div>`).join('') || '<p class="muted">No schedules configured.</p>') +
      `<form class="workflow-form" data-form="schedule-create"><h3>Add a backup schedule</h3>` +
      `${selectField('Scope', 'scope', [['global', 'Manager-wide'], ['world', 'World']])}` +
      `${selectField('World', 'world_id', worldChoices())}${selectField('Interval', 'interval_kind', [['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly'], ['every_n_days', 'Every N days']])}` +
      `${field('Time (HH:MM)', 'time_of_day', '03:00', 'time', true)}${field('Every N days', 'days', '1', 'number')}` +
      `<button class="ui-button ui-button-blue" type="submit">Add schedule</button></form>`;
  }

  async function renderSettings() {
    const result = await request('/api/settings');
    const settings = result.data.settings;
    const inputs = Object.entries(settings).map(([key, value]) => field(key.replaceAll('_', ' '), key,
      typeof value === 'object' && value !== null ? JSON.stringify(value) : value ?? '',
      typeof value === 'number' ? 'number' : 'text')).join('');
    root.innerHTML = message() + card('Global settings', `<form class="workflow-form" data-form="global-settings">` +
      `${inputs}<input type="hidden" name="version" value="${escapeHtml(result.data.version)}">` +
      `<p class="muted">Structured settings values use JSON syntax.</p><button class="ui-button ui-button-blue" type="submit">Save settings</button></form>`);
  }

  async function renderUsers() {
    const [userResult, roleResult, deviceResult] = await Promise.all([request('/api/users'), request('/api/roles'), request('/api/devices')]);
    const users = userResult.data.users || [];
    const roles = roleResult.data.roles || [];
    const devices = deviceResult.data.devices || [];
    root.innerHTML = message() + card('Users', users.map((item) => `<div class="table-row">` +
      `<span><strong>${escapeHtml(item.username)}</strong><small>${escapeHtml(item.status)} · ${escapeHtml(item.roles.join(', '))}</small></span>` +
      `${button(item.status === 'active' ? 'Disable' : 'Enable', 'user-toggle', item.user_id)}${button('Delete', 'user-delete', item.user_id)}</div>`
    ).join('') || '<p class="muted">No users.</p>') +
      `<form class="workflow-form" data-form="user-create"><h3>Create user</h3>${field('Username', 'username', '', 'text', true)}` +
      `${field('Display name', 'display_name')}${field('Password (12+ characters)', 'password', '', 'password', true)}` +
      `${selectField('Role', 'role_id', roles.map((item) => [item.role_id, item.name]))}<button class="ui-button ui-button-blue" type="submit">Create user</button></form>` +
      card('Roles', roles.map((item) => `<div class="table-row"><span>${escapeHtml(item.name)} · v${escapeHtml(item.version)}</span>` +
        `${button('Permissions', 'role-permissions', item.role_id)}${button('Delete', 'role-delete', item.role_id, '', item.is_system_role, 'System roles are immutable')}</div>`
      ).join('') || '<p class="muted">No roles.</p>') +
      `<form class="workflow-form" data-form="role-create">${field('Role name', 'name', '', 'text', true)}${field('Description', 'description')}` +
      `<button class="ui-button" type="submit">Create role</button></form>` +
      `<form class="workflow-form" data-form="permission-create">${selectField('Role', 'role_id', roles.map((item) => [item.role_id, item.name]))}` +
      `${selectField('Action category', 'action_category', ['world_read', 'world_control', 'world_configure', 'backup_manage', 'user_manage'].map((value) => [value, value]))}` +
      `${selectField('World', 'world_id', worldChoices())}<button class="ui-button" type="submit">Grant permission</button></form>` +
      card('Devices', devices.map((item) => `<div class="table-row"><span>${escapeHtml(item.device_name)} · ${escapeHtml(item.status)}</span>` +
        `${button('Revoke', 'device-revoke', item.device_id)}</div>`).join('') || '<p class="muted">No devices.</p>');
  }

  async function renderMaintenance() {
    const [runs, missed] = await Promise.all([request('/api/cleanup/runs?limit=50&offset=0'), request('/api/missed-runs?limit=50&offset=0')]);
    if (cleanupOperationId) {
      try {
        const operation = await request(`/api/operations/${encodeURIComponent(cleanupOperationId)}`);
        cleanupOperationStatus = operation.data.operation.status;
      } catch (_error) { cleanupOperationStatus = ''; }
    }
    root.innerHTML = message() + card('Retention preview', `<form class="workflow-form" data-form="cleanup-preview">` +
      `${selectField('Scope', 'scope', [['backups', 'Backups']])}` +
      `${selectField('World', 'world_id', worldChoices())}<button class="ui-button ui-button-blue" type="submit">Run dry preview</button></form>` +
      `${unavailable('Policy editing and stale-world/log cleanup are not supported. The cleanup service currently supports backups only.')}` +
      (cleanupOperationId ? `<p>Preview ${escapeHtml(cleanupOperationId)} · ${escapeHtml(cleanupOperationStatus || 'status unavailable')}</p>` +
        `<form class="workflow-form" data-form="cleanup-execute"><input type="hidden" name="dry_run_operation_id" value="${escapeHtml(cleanupOperationId)}">` +
        `<input type="hidden" name="world_id" value="${escapeHtml(cleanupWorldId)}">` +
        `${selectField('Scope', 'scope', [['backups', 'Backups']])}<label class="check-control"><input type="checkbox" name="elevated_confirmation"> Confirm backup cleanup</label>` +
        `<button class="ui-button ui-button-red" type="submit"${cleanupOperationStatus !== 'completed' ? ' disabled' : ''}>Execute completed preview</button></form>` : '') +
      (runs.data.cleanup_runs || []).map((run) => `<div class="table-row"><span>${escapeHtml(run.operation_id || run.op_id)} · ${escapeHtml(run.status)}</span>` +
        `${button('Check operation', 'operation-refresh', run.operation_id || run.op_id)}</div>`).join('')) +
      card('Missed scheduled runs', (missed.data.missed_runs || []).map((run) => `<div class="table-row">` +
        `<span>${escapeHtml(run.schedule_id)} · ${escapeHtml(run.expected_run_at)} · ${escapeHtml(run.resolution)}</span>` +
        `${button('Resolve', 'missed-resolve', run.missed_run_id, '', run.resolution !== 'pending')}${button('Ignore', 'missed-ignore', run.missed_run_id, '', run.resolution !== 'pending')}</div>`
      ).join('') || '<p class="muted">No missed runs.</p>');
  }

  async function renderSystemLogs() {
    const [health, diagnostics, notices] = await Promise.all([request('/api/health'), request('/api/diagnostics'), request('/api/notifications?limit=50&offset=0')]);
    root.innerHTML = message() + card('Manager health', `<pre class="data-output">${escapeHtml(JSON.stringify(health.data, null, 2))}</pre>`) +
      card('Diagnostics', `<pre class="data-output">${escapeHtml(JSON.stringify(diagnostics.data, null, 2))}</pre>`) +
      card('Notifications', (notices.data.notifications || []).map((item) => `<div class="table-row"><span>${escapeHtml(item.severity)} · ${escapeHtml(item.message)}</span>` +
        `${button(item.read_at ? 'Dismiss' : 'Mark read', item.read_at ? 'notification-dismiss' : 'notification-read', item.notification_id)}</div>`
      ).join('') || '<p class="muted">No notifications.</p>') +
      unavailable('Manager log files are not exposed by the current API. World log channels are available under World Logs.');
  }

  async function renderAudit() {
    const [audit, notices] = await Promise.all([request(`/api/audit${query({ ...auditFilters, limit: 50, offset: 0 })}`), request('/api/notifications?limit=50&offset=0')]);
    root.innerHTML = message() + `<form class="workflow-form" data-form="audit-filter">${field('Event type', 'event_type', auditFilters.event_type || '')}` +
      `${field('Actor user ID', 'actor_user_id', auditFilters.actor_user_id || '')}${selectField('World', 'world_id', worldChoices(), auditFilters.world_id || '')}<button class="ui-button ui-button-blue" type="submit">Filter history</button></form>` +
      card('Audit history', (audit.data.audit || []).map((item) => `<div class="table-row"><span><strong>${escapeHtml(item.event_type)}</strong>` +
        `<small>${escapeHtml(item.actor_username_snapshot || item.actor_user_id || 'system')} · ${escapeHtml(item.world_id || 'manager')} · ${escapeHtml(item.created_at)}</small></span>` +
        `${button('Details', 'audit-detail', item.audit_id)}</div>`).join('') || '<p class="muted">No audit records.</p>') +
      card('Notifications', (notices.data.notifications || []).map((item) => `<div class="table-row"><span>${escapeHtml(item.message)}</span>` +
        `${button('Mark read', 'notification-read', item.notification_id, '', Boolean(item.read_at))}${button('Dismiss', 'notification-dismiss', item.notification_id)}</div>`).join('') || '<p class="muted">No notifications.</p>');
  }

  async function renderSync() {
    const [targets, records] = await Promise.all([request('/api/sync/targets'), request('/api/sync/records?limit=50&offset=0')]);
    root.innerHTML = message() + card('Sync targets', (targets.data.sync_targets || []).map((item) => `<div class="table-row">` +
      `<span><strong>${escapeHtml(item.name || item.sync_target_id)}</strong><small>${escapeHtml(item.scope)} · ${item.enabled ? 'enabled' : 'disabled'}</small></span>` +
      `<span>${item.effective ? 'Effective' : ''}</span></div>`).join('') || '<p class="muted">No sync targets configured.</p>') +
      card('Sync activity', (records.data.sync_records || []).map((item) => `<div class="table-row"><span>${escapeHtml(item.status)} · ${escapeHtml(item.artifact_id)}</span>` +
        `${button('Retry', 'sync-retry', item.artifact_id, 'ui-button-blue', item.status === 'pending')}</div>`).join('') || '<p class="muted">No sync records.</p>') +
      unavailable('Sync target creation, editing, and deletion are not exposed by the current API.');
  }

  async function renderManagerMaintenance() {
    const [result, backups] = await Promise.all([
      request('/api/manager'),
      request('/api/backups?world_id=null&limit=50&offset=0'),
    ]);
    const artifacts = backups.data.backups || [];
    root.innerHTML = message() + card('Manager status', `<pre class="data-output">${escapeHtml(JSON.stringify(result.data, null, 2))}</pre>`) +
      card('Manager backup', `<div class="action-row">${button('Create manager backup', 'manager-backup', '', 'ui-button-blue')}</div>` +
        (artifacts.map((artifact) => `<div class="table-row"><span><strong>${escapeHtml(artifact.artifact_id)}</strong>` +
          `<small>${escapeHtml(artifact.size_bytes)} bytes · ${escapeHtml(artifact.created_at)} · ${artifact.suspect ? 'suspect' : 'verified'}</small></span>` +
          `${button('Restore', 'manager-restore', artifact.artifact_id, '', true, 'Manager restore recovery is not implemented')}</div>`).join('') ||
          '<p class="muted">No manager backups found.</p>')) +
      card('Manager lifecycle', `<div class="action-row">${button('Restart', 'manager-restart', '', '', true, 'Host relaunch contract is not implemented')}` +
        `${button('Update', 'manager-update', '', '', true, 'Trusted update contract is not implemented')}${button('Rollback', 'manager-rollback', '', '', true, 'Rollback recovery contract is not implemented')}</div>` +
        unavailable('Restore, restart, update, and rollback need recovery and host-supervisor contracts before they can be enabled.'));
  }

  async function renderTemplates() {
    const [templates, runtimes] = await Promise.all([request('/api/templates?limit=100&offset=0'), request('/api/java-runtimes?limit=100&offset=0')]);
    root.innerHTML = message() + card('Template catalog', (templates.data.templates || []).map((item) => `<div class="table-row">` +
      `<span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.category)} · ${escapeHtml(item.default_version)}</small></span>` +
      `${button('Edit', 'template-edit', item.template_id, '', item.deprecated)}${button('Deprecate', 'template-deprecate', item.template_id, '', item.deprecated)}</div>`).join('') || '<p class="muted">No templates.</p>') +
      `<form class="workflow-form" data-form="template-create"><h3>Add template</h3>${field('Name', 'name', '', 'text', true)}` +
      `${selectField('Server type', 'category', [['vanilla', 'Vanilla'], ['paper', 'Paper'], ['fabric', 'Fabric'], ['forge', 'Forge']])}` +
      `${field('Default version', 'default_version', '', 'text', true)}<label>Config defaults JSON<textarea class="ui-text-input" name="config_defaults" required>{"launch_command_template":"java -jar server.jar"}</textarea></label>` +
      `<button class="ui-button ui-button-blue" type="submit">Add template</button></form>` +
      card('Java runtimes', (runtimes.data.java_runtimes || []).map((item) => `<div class="table-row"><span><strong>${escapeHtml(item.label)}</strong>` +
        `<small>${escapeHtml(item.executable_path)} · ${escapeHtml(item.status)} · ${escapeHtml(item.version_detected || 'unverified')}</small></span>` +
        `${button('Edit', 'runtime-edit', item.runtime_id)}${button('Verify', 'runtime-verify', item.runtime_id, 'ui-button-blue', item.status === 'verified')}${button('Deprecate', 'runtime-deprecate', item.runtime_id)}</div>`).join('') || '<p class="muted">No runtimes.</p>') +
      `<form class="workflow-form" data-form="runtime-create">${field('Runtime label', 'label', '', 'text', true)}${field('Executable path', 'path', '', 'text', true)}` +
      `<button class="ui-button ui-button-blue" type="submit">Register runtime</button></form>`;
  }

  async function selectedWorld() {
    if (worldId) return worldId;
    root.innerHTML = message() + unavailable('Choose a world from the context menu to use this module.', 'Choose a world');
    return '';
  }

  async function renderWorldMain() {
    const id = await selectedWorld();
    if (!id) return;
    const [detail, eula, backups] = await Promise.all([request(`/api/worlds/${encodeURIComponent(id)}`),
      request(`/api/worlds/${encodeURIComponent(id)}/eula`), request(`/api/worlds/${encodeURIComponent(id)}/backups?limit=1&offset=0`)]);
    const world = detail.data.world;
    root.innerHTML = message() + card('World status', `<div class="world-row-header"><div><strong>${escapeHtml(world.display_name)}</strong>` +
      `<p class="muted">${escapeHtml(world.server_type)} · ${escapeHtml(world.mc_version)} · Port ${escapeHtml(world.port)}</p></div>` +
      `<span class="status-indicator" data-tone="${tone(world.state)}">${escapeHtml(world.state)}</span></div>` +
      `<div class="action-row">${worldControls(world)}</div><p>EULA: ${escapeHtml(eula.data.eula)}</p>` +
      `${eula.data.eula === 'required' ? button('Accept EULA', 'eula-accept', id, 'ui-button-blue') : ''}` +
      `<p>Latest backup: ${escapeHtml(backups.data.backups?.[0]?.created_at || 'None')}</p>` +
      `<pre class="data-output">${escapeHtml(JSON.stringify(detail.data.capabilities, null, 2))}</pre>`);
  }

  async function renderBackups() {
    const id = await selectedWorld();
    if (!id) return;
    const [backups, restores] = await Promise.all([request(`/api/worlds/${encodeURIComponent(id)}/backups?limit=50&offset=0`), request(`/api/worlds/${encodeURIComponent(id)}/restores?limit=50&offset=0`)]);
    const worldState = worlds.find((world) => world.world_id === id)?.state;
    root.innerHTML = message() + card('Backup artifacts', `<div class="action-row">${button('Create manual backup', 'world-backup', id, 'ui-button-blue', !['off', 'running'].includes(worldState))}</div>` +
      (backups.data.backups || []).map((item) => `<div class="table-row"><span><strong>${escapeHtml(item.artifact_id)}</strong>` +
        `<small>${escapeHtml(item.category)} · ${escapeHtml(item.size_bytes)} bytes · ${escapeHtml(item.created_at)} · ${item.retention_protected ? 'protected' : 'deletable'}</small></span>` +
        `${button('Restore', 'backup-restore', item.artifact_id, 'ui-button-blue', Boolean(item.suspect) || worldState !== 'off', 'Restore requires an off world and a verified artifact')}` +
        `${button('Delete', 'backup-delete', item.artifact_id, 'ui-button-red', Boolean(item.retention_protected), 'Retention protected')}</div>`).join('') || '<p class="muted">No backups found.</p>') +
      card('Restore history', (restores.data.restores || []).map((item) => `<div class="table-row"><span>${escapeHtml(item.restore_id)} · ${escapeHtml(item.status || '')}</span>` +
        `${button('Rollback', 'restore-rollback', item.restore_id, '', !item.pre_restore_artifact_id)}</div>`).join('') || '<p class="muted">No restore history.</p>');
  }

  async function renderLogs() {
    const id = await selectedWorld();
    if (!id) return;
    if (logTimer) clearInterval(logTimer);
    const [channels, files] = await Promise.all([request(`/api/worlds/${encodeURIComponent(id)}/logs`), request(`/api/worlds/${encodeURIComponent(id)}/logs/${encodeURIComponent(logChannel)}`)]);
    const available = channels.data.channels || [];
    root.innerHTML = message() + card('World logs', `<div class="world-list-toolbar">${selectField('Channel', 'channel', available.map((item) => [item, item]), logChannel)}` +
      `${button('Refresh tail', 'logs-refresh', id, 'ui-button-blue')}</div><pre class="log-output" data-log-output aria-live="polite"></pre>` +
      `<h3>Archived files</h3>${(files.data.files || []).map((file) => `<div class="table-row"><span>${escapeHtml(file.name)} · ${escapeHtml(file.size)} bytes</span>` +
        `<a class="ui-button" href="/api/worlds/${encodeURIComponent(id)}/logs/${encodeURIComponent(logChannel)}/${encodeURIComponent(file.name)}">Download</a></div>`).join('') || '<p class="muted">No archived log files.</p>'}`);
    await loadLogTail(id);
    logTimer = setInterval(() => {
      if (main.dataset.activePage === 'world-logs' && worldId === id) loadLogTail(id, true).catch(() => {});
    }, 3000);
  }

  async function loadLogTail(id, append = false) {
    const result = await request(`/api/worlds/${encodeURIComponent(id)}/logs/${encodeURIComponent(logChannel)}/tail?offset=${logOffset}`);
    const output = document.querySelector('[data-log-output]');
    if (!output) return;
    const lines = result.data.lines || [];
    logOffset = result.data.next_offset ?? logOffset + lines.length;
    const text = lines.map((line) => typeof line === 'string' ? line : JSON.stringify(line)).join('\n');
    output.textContent = append ? `${output.textContent}${output.textContent ? '\n' : ''}${text}` : text;
    output.scrollTop = output.scrollHeight;
  }

  async function renderFiles() {
    const id = await selectedWorld();
    if (!id) return;
    const path = new URLSearchParams(window.location.search || '').get('path') || '';
    const result = await request(`/api/worlds/${encodeURIComponent(id)}/files${query({ path })}`);
    const items = result.data.files || [];
    const rows = items.map((item) => {
      const pathName = [path, item.name].filter(Boolean).join('/');
      const control = item.type === 'directory' ? button('Open', 'file-open', pathName) :
        `<a class="ui-button" href="/api/worlds/${encodeURIComponent(id)}/files/download?path=${encodeURIComponent(pathName)}">Download</a>`;
      return `<div class="table-row"><span>${item.type === 'directory' ? '[DIR] ' : ''}${escapeHtml(item.name)}<small>${escapeHtml(item.size ?? '')} ${item.type === 'file' ? 'bytes' : ''}</small></span>` +
          `${control}${button('Rename', 'file-rename', pathName)}${button('Move', 'file-move', pathName)}` +
          `${button('Copy', 'file-copy', pathName)}${button('Delete', 'file-delete', pathName, 'ui-button-red')}</div>`;
    }).join('') || '<p class="muted">This directory is empty.</p>';
    root.innerHTML = message() + card(`Files · /${escapeHtml(result.data.path || '')}`, `<form class="workflow-form" data-form="file-path">` +
      `${field('Directory path', 'path', path)}<button class="ui-button" type="submit">Open</button></form>` +
      rows) +
      `<form class="workflow-form" data-form="file-mkdir"><input type="hidden" name="path" value="${escapeHtml(path)}">` +
      `${field('New directory', 'name', '', 'text', true)}<button class="ui-button" type="submit">Create directory</button></form>` +
      `<form class="workflow-form" data-form="file-upload" enctype="multipart/form-data">${field('File', 'file', '', 'file', true)}` +
      `${field('Destination path', 'path', path, 'text', true)}<button class="ui-button ui-button-blue" type="submit">Upload</button></form>`;
  }

  async function renderWorldMaintenance() {
    const id = await selectedWorld();
    if (!id) return;
    const settings = await request(`/api/worlds/${encodeURIComponent(id)}/settings`);
    if (cleanupOperationId && cleanupWorldId === id) {
      try {
        const operation = await request(`/api/operations/${encodeURIComponent(cleanupOperationId)}`);
        cleanupOperationStatus = operation.data.operation.status;
      } catch (_error) { cleanupOperationStatus = ''; }
    }
    root.innerHTML = message() + card('Backup retention', `<p>Effective world settings version ${escapeHtml(settings.data.version)}.</p>` +
      `<pre class="data-output">${escapeHtml(JSON.stringify(settings.data.settings, null, 2))}</pre>` +
      `<p>Preview operation: ${escapeHtml(cleanupOperationId && cleanupWorldId === id ? cleanupOperationId : 'Not run')} · ${escapeHtml(cleanupOperationStatus)}</p>` +
      `${button('Refresh preview', 'cleanup-world-preview', id, 'ui-button-blue')}` +
      (cleanupOperationId && cleanupWorldId === id ? `<form class="workflow-form" data-form="world-cleanup-execute"><input type="hidden" name="dry_run_operation_id" value="${escapeHtml(cleanupOperationId)}">` +
        `<label class="check-control"><input type="checkbox" name="elevated_confirmation"> Confirm backup cleanup</label>` +
        `<button class="ui-button ui-button-red" type="submit"${cleanupOperationStatus !== 'completed' ? ' disabled' : ''}>Execute preview</button></form>` : '') +
      unavailable('Per-world retention policy editing and non-backup cleanup scopes are unsupported by the current API/policy.'));
  }

  async function renderWorldSetup() {
    const id = await selectedWorld();
    if (!id) return;
    const [config, eula, runtimes] = await Promise.all([request(`/api/worlds/${encodeURIComponent(id)}/runtime-config`), request(`/api/worlds/${encodeURIComponent(id)}/eula`), request('/api/java-runtimes?limit=100&offset=0')]);
    const value = config.data.runtime_config;
    const choices = (runtimes.data.java_runtimes || []).filter((item) => ['registered', 'verified'].includes(item.status)).map((item) => [item.runtime_id, `${item.label} · ${item.status}`]);
    root.innerHTML = message() + card('Runtime configuration', `<form class="workflow-form" data-form="runtime-config">` +
      `${selectField('Java runtime', 'java_runtime_id', choices, value.java_runtime_id)}${field('Port', 'port', value.port, 'number')}` +
      `${selectField('Addressing', 'addressing_strategy', [['port', 'Port'], ['subdomain', 'Subdomain'], ['path', 'Path']], value.addressing_strategy)}` +
      `${field('Address value', 'addressing_value', value.addressing_value)}<label>Launch arguments JSON<textarea class="ui-text-input" name="launch_args">${escapeHtml(JSON.stringify(value.launch_args || []))}</textarea></label>` +
      `<input type="hidden" name="version" value="${escapeHtml(config.data.version)}"><button class="ui-button ui-button-blue" type="submit">Save runtime configuration</button></form>` +
      `<p>EULA state: ${escapeHtml(eula.data.eula)} · world ${escapeHtml(eula.data.world_state)}</p>` +
      `${eula.data.eula === 'required' ? button('Accept EULA', 'eula-accept', id, 'ui-button-blue') : ''}`) +
      unavailable('A server.properties editor is not exposed by the API; runtime configuration and EULA state are available.');
  }

  async function renderModule(slug) {
    if (logTimer) { clearInterval(logTimer); logTimer = null; }
    const renderers = {
      home: renderHome, worlds: renderWorlds, settings: renderSettings, users: renderUsers,
      maintenance: renderMaintenance,
      documentation: async () => { root.innerHTML = message() + card('Documentation', unavailable('No authenticated documentation API or shell-owned documentation bundle is available.')); },
      'system-logs': renderSystemLogs, audit: renderAudit, sync: renderSync,
      'manager-maintenance': renderManagerMaintenance, templates: renderTemplates,
      'world-main': renderWorldMain, 'world-backups': renderBackups, 'world-logs': renderLogs,
      files: renderFiles, 'world-maintenance': renderWorldMaintenance, 'world-setup': renderWorldSetup,
    };
    try { await renderers[slug](); }
    catch (error) { root.innerHTML = message() + `<div class="list-surface error-surface" role="alert">${escapeHtml(error.message)}</div>`; }
    updateContext();
  }

  async function loadPage(slug) {
    try {
      const result = await request(`/api/pages/${encodeURIComponent(slug)}`);
      const heading = document.querySelector('h1');
      if (heading) heading.textContent = result.data.title;
      main.dataset.activePage = slug;
      document.querySelectorAll('a[data-page]').forEach((anchor) => anchor.classList?.toggle('is-active', anchor.dataset.page === slug));
      await renderModule(slug);
    } catch (error) {
      root.innerHTML = `<div class="list-surface error-surface" role="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  async function navigate(slug, href) {
    history.pushState({ slug }, '', href || `/pages/${slug}`);
    await loadPage(slug);
  }

  async function worldAction(action, id) {
    const endpoint = action === 'backup' ? 'backups' : action;
    await mutate(`/api/worlds/${encodeURIComponent(id)}/${endpoint}`, 'POST', action === 'backup' ? { category: 'manual' } : undefined);
    statusMessage = `${action} request accepted.`;
    await loadWorlds();
    await loadPage(main.dataset.activePage);
  }

  async function runAction(action, id) {
    const encoded = encodeURIComponent(id || '');
    switch (action) {
      case 'manager-backup': await mutate('/api/manager/backup', 'POST', {}); break;
      case 'world-start': return worldAction('start', id);
      case 'world-stop': return worldAction('stop', id);
      case 'world-kill': return worldAction('kill', id);
      case 'world-backup': return worldAction('backup', id);
      case 'world-rename': {
        const name = window.prompt ? window.prompt('New world display name') : '';
        if (!name) return;
        const config = await request(`/api/worlds/${encoded}/runtime-config`);
        await mutate(`/api/worlds/${encoded}`, 'PATCH', { display_name: name, version: config.data.version });
        break;
      }
      case 'world-delete': {
        const preview = await mutate(`/api/worlds/${encoded}/delete-preview`, 'POST', {});
        const details = preview.data;
        if (window.confirm && !window.confirm(`Delete ${details.display_name} at ${details.world_directory}?`)) return;
        await mutate(`/api/worlds/${encoded}`, 'DELETE', { preview_token: details.preview_token });
        break;
      }
      case 'eula-accept': await mutate(`/api/worlds/${encoded}/eula/accept`, 'POST', { accepted: true }); break;
      case 'schedule-toggle': {
        const result = await request('/api/schedules?limit=100&offset=0');
        const row = (result.data.schedules || []).find((item) => item.schedule_id === id);
        if (row) await mutate(`/api/schedules/${encoded}`, 'PATCH', { version: row.version, enabled: !row.enabled });
        break;
      }
      case 'schedule-delete': await mutate(`/api/schedules/${encoded}`, 'DELETE'); break;
      case 'user-toggle': {
        const result = await request('/api/users');
        const row = (result.data.users || []).find((item) => item.user_id === id);
        if (row) await mutate(`/api/users/${encoded}`, 'PATCH', { status: row.status === 'active' ? 'disabled' : 'active' });
        break;
      }
      case 'user-delete':
        if (window.confirm && !window.confirm('Delete this user account?')) return;
        await mutate(`/api/users/${encoded}`, 'DELETE'); break;
      case 'role-delete': await mutate(`/api/roles/${encoded}`, 'DELETE'); break;
      case 'role-permissions': {
        const result = await request(`/api/roles/${encoded}/permissions`);
        statusMessage = JSON.stringify(result.data.permissions, null, 2); return loadPage(main.dataset.activePage);
      }
      case 'device-revoke': await mutate(`/api/devices/${encoded}`, 'PATCH', { status: 'revoked' }); break;
      case 'missed-resolve': await mutate(`/api/missed-runs/${encoded}`, 'PATCH', { resolution: 'resolved' }); break;
      case 'missed-ignore': await mutate(`/api/missed-runs/${encoded}`, 'PATCH', { resolution: 'ignored' }); break;
      case 'operation-refresh': {
        const result = await request(`/api/operations/${encoded}`);
        statusMessage = `Operation ${id}: ${result.data.operation.status}`; break;
      }
      case 'notification-read': await mutate(`/api/notifications/${encoded}/read`, 'POST', {}); break;
      case 'notification-dismiss': await mutate(`/api/notifications/${encoded}/dismiss`, 'POST', {}); break;
      case 'audit-detail': {
        const result = await request(`/api/audit/${encoded}`);
        statusMessage = JSON.stringify(result.data.audit, null, 2); return loadPage(main.dataset.activePage);
      }
      case 'sync-retry': await mutate('/api/sync/retry', 'POST', { artifact_id: id }); break;
      case 'template-deprecate': await mutate(`/api/templates/${encoded}`, 'DELETE'); break;
      case 'template-edit': {
        const result = await request('/api/templates?limit=100&offset=0');
        const item = (result.data.templates || []).find((template) => template.template_id === id);
        const name = item && window.prompt ? window.prompt('Template name', item.name) : '';
        if (!item || !name || name === item.name) return;
        await mutate(`/api/templates/${encoded}`, 'PATCH', { version: item.version, name });
        break;
      }
      case 'runtime-verify': await mutate(`/api/java-runtimes/${encoded}/verify`, 'POST', {}); break;
      case 'runtime-deprecate': await mutate(`/api/java-runtimes/${encoded}`, 'DELETE'); break;
      case 'runtime-edit': {
        const result = await request('/api/java-runtimes?limit=100&offset=0');
        const item = (result.data.java_runtimes || []).find((runtime) => runtime.runtime_id === id);
        const label = item && window.prompt ? window.prompt('Runtime label', item.label) : '';
        const path = item && window.prompt ? window.prompt('Executable path', item.executable_path) : '';
        if (!item || !label || !path) return;
        await mutate(`/api/java-runtimes/${encoded}`, 'PATCH', { version: item.version, label, executable_path: path });
        break;
      }
      case 'backup-restore':
        if (window.confirm && !window.confirm('Restore this artifact? The world must be off.')) return;
        await mutate(`/api/worlds/${encodeURIComponent(worldId)}/restores`, 'POST', { artifact_id: id }); break;
      case 'backup-delete': await mutate(`/api/backups/${encoded}`, 'DELETE'); break;
      case 'restore-rollback': await mutate(`/api/worlds/${encodeURIComponent(worldId)}/restores/rollback`, 'POST', { restore_id: id }); break;
      case 'cleanup-world-preview': {
        const result = await request(`/api/worlds/${encoded}/cleanup-preview`);
        cleanupOperationId = result.data.operation?.op_id || result.data.op_id || '';
        cleanupWorldId = id;
        cleanupOperationStatus = result.data.operation?.status || '';
        break;
      }
      case 'logs-refresh': await loadLogTail(id); statusMessage = 'Log tail refreshed.'; return;
      case 'file-open': history.pushState({ slug: 'files' }, '', `/pages/files?path=${encodeURIComponent(id)}`); return loadPage('files');
      case 'file-delete':
        if (window.confirm && !window.confirm(`Delete ${id}?`)) return;
        await mutate(`/api/worlds/${encodeURIComponent(worldId)}/files`, 'DELETE', { path: id }); break;
      case 'file-rename': {
        const name = window.prompt ? window.prompt('New file or directory name') : '';
        if (!name) return;
        const parent = id.includes('/') ? id.slice(0, id.lastIndexOf('/') + 1) : '';
        await mutate(`/api/worlds/${encodeURIComponent(worldId)}/files`, 'PATCH', { action: 'rename', from: id, to: `${parent}${name}` }); break;
      }
      case 'file-move':
      case 'file-copy': {
        const destination = window.prompt ? window.prompt('Destination path') : '';
        if (!destination) return;
        await mutate(`/api/worlds/${encodeURIComponent(worldId)}/files`, 'PATCH', {
          action: action === 'file-move' ? 'move' : 'copy', from: id, to: destination,
        });
        break;
      }
      default: return;
    }
    statusMessage = statusMessage || 'Request completed.';
    await loadWorlds();
    await loadPage(main.dataset.activePage);
  }

  async function submitWorkflow(form) {
    const data = values(form);
    const id = encodeURIComponent(worldId);
    switch (form.dataset.form) {
      case 'world-create':
        await mutate('/api/worlds', 'POST', { template_id: data.template_id, display_name: data.display_name,
          port: Number(data.port), addressing_strategy: data.addressing_strategy, addressing_value: data.addressing_value, java_runtime_id: data.java_runtime_id }); break;
      case 'schedule-create':
        await mutate('/api/schedules', 'POST', { scope: data.scope, world_id: data.scope === 'world' ? data.world_id : null,
          schedule_type: 'backup', interval_spec: data.interval_kind === 'every_n_days' ? { kind: data.interval_kind, days: Number(data.days) } : { kind: data.interval_kind },
          time_of_day: data.time_of_day, enabled: true }); break;
      case 'global-settings': {
        const settings = {};
        Object.entries(data).forEach(([key, value]) => {
          if (key !== 'version') settings[key] = ['notification_defaults', 'offsite_sync_defaults'].includes(key) ? JSON.parse(value) : key === 'idle_countdown_seconds' ? Number(value) : value;
        });
        await mutate('/api/settings', 'PATCH', { version: Number(data.version), ...settings }); break;
      }
      case 'user-create': await mutate('/api/users', 'POST', { username: data.username, display_name: data.display_name || null, password: data.password, role_id: data.role_id }); break;
      case 'role-create': await mutate('/api/roles', 'POST', { name: data.name, description: data.description || null }); break;
      case 'permission-create': await mutate('/api/permissions', 'POST', { role_id: data.role_id, action_category: data.action_category, world_id: data.world_id || null }); break;
      case 'cleanup-preview': {
        if (data.scope !== 'backups') throw new Error('Only backup cleanup is supported by this API.');
        const result = await mutate('/api/cleanup/dry-run', 'POST', { scope: data.scope, world_id: data.world_id || null });
        cleanupOperationId = result.data.operation?.op_id || result.data.op_id || '';
        cleanupWorldId = data.world_id || '';
        cleanupOperationStatus = result.data.operation?.status || '';
        break;
      }
      case 'cleanup-execute':
        if (!form.querySelector('[name="elevated_confirmation"]')?.checked) throw new Error('Confirm cleanup before continuing.');
        await mutate('/api/cleanup/execute', 'POST', { scope: 'backups', world_id: data.world_id || null,
          dry_run_operation_id: data.dry_run_operation_id, elevated_confirmation: true });
        cleanupOperationId = '';
        cleanupOperationStatus = '';
        break;
      case 'audit-filter': auditFilters = { event_type: data.event_type, actor_user_id: data.actor_user_id, world_id: data.world_id }; break;
      case 'template-create': await mutate('/api/templates', 'POST', { name: data.name, category: data.category, default_version: data.default_version, config_defaults: JSON.parse(data.config_defaults) }); break;
      case 'runtime-create': await mutate('/api/java-runtimes', 'POST', { label: data.label, path: data.path }); break;
      case 'file-path': history.pushState({ slug: 'files' }, '', `/pages/files?path=${encodeURIComponent(data.path)}`); return loadPage('files');
      case 'file-mkdir': await mutate(`/api/worlds/${id}/files/mkdir`, 'POST', { path: data.path, name: data.name }); break;
      case 'file-upload': await mutate(`/api/worlds/${id}/files`, 'POST', new FormData(form), true); break;
      case 'runtime-config': {
        const update = { java_runtime_id: data.java_runtime_id, port: Number(data.port),
          addressing_strategy: data.addressing_strategy, addressing_value: data.addressing_value, version: Number(data.version) };
        const launchArgs = JSON.parse(data.launch_args);
        if (launchArgs.length) update.launch_args = launchArgs;
        await mutate(`/api/worlds/${id}/runtime-config`, 'PATCH', update);
        break;
      }
      case 'world-cleanup-execute':
        if (!form.querySelector('[name="elevated_confirmation"]')?.checked) throw new Error('Confirm cleanup before continuing.');
        await mutate('/api/cleanup/execute', 'POST', { scope: 'backups', world_id: worldId, dry_run_operation_id: data.dry_run_operation_id, elevated_confirmation: true });
        cleanupOperationId = '';
        cleanupOperationStatus = '';
        break;
      default: return;
    }
    statusMessage = 'Request completed.';
    await loadWorlds();
    await loadPage(main.dataset.activePage);
  }

  document.addEventListener('click', async (event) => {
    const action = event.target.closest && event.target.closest('[data-ui-action]');
    if (action && !action.disabled) {
      event.preventDefault();
      try { await runAction(action.dataset.uiAction, action.dataset.id); }
      catch (error) { statusMessage = error.message; await loadPage(main.dataset.activePage); }
      return;
    }
    const anchor = event.target.closest && event.target.closest('a[data-page]');
    if (!anchor || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || (event.button !== undefined && event.button !== 0)) return;
    event.preventDefault();
    statusMessage = '';
    history.pushState({ slug: anchor.dataset.page }, '', anchor.href);
    await loadPage(anchor.dataset.page);
  });

  root.addEventListener('submit', async (event) => {
    const form = event.target.closest && event.target.closest('form');
    if (!form) return;
    event.preventDefault();
    try {
      if (form.matches('[data-auth-form]')) await authenticate(form);
      else await submitWorkflow(form);
    } catch (error) { statusMessage = error.message || 'Request failed.'; await loadPage(main.dataset.activePage); }
  });

  root.addEventListener('change', (event) => {
    if (event.target.matches('[name="channel"]')) { logChannel = event.target.value; logOffset = 0; loadPage('world-logs'); }
  });

  if (contextSelect) contextSelect.addEventListener('change', async () => {
    statusMessage = '';
    if (contextSelect.value === 'manager') {
      history.pushState({ slug: 'home' }, '', '/pages/home');
      return loadPage('home');
    }
    worldId = contextSelect.value;
    history.pushState({ slug: 'world-main' }, '', '/pages/world-main');
    await loadPage('world-main');
  });

  document.querySelector('[data-refresh]')?.addEventListener('click', () => loadPage(main.dataset.activePage));
  document.querySelector('[data-logout]')?.addEventListener('click', async () => {
    try { await mutate('/api/auth/logout', 'POST', {}); }
    finally { renderAuth('login', 'You have signed out.'); }
  });
  if (window.addEventListener) window.addEventListener('popstate', (event) => { if (event.state?.slug) loadPage(event.state.slug); });

  (async function initialize() {
    try {
      await request('/api/session');
      if (document.body) document.body.dataset.authState = 'authenticated';
      await loadWorlds();
      await loadPage(main.dataset.activePage);
    } catch (_error) {
      try {
        const setup = await request('/api/setup');
        renderAuth(setup.data.first_superadmin_required ? 'setup' : 'login');
      } catch (_setupError) { renderAuth('login', 'Unable to verify the current session.'); }
    }
  })();
})();