(() => {
  'use strict';

  const STORE_KEY = 'mcmanager-v4-prototype';
  const PAGE_INFO = {
    home: ['Homepage', 'MANAGER'],
    worlds: ['World Management', 'MANAGER'],
    settings: ['Manager Settings', 'MANAGER'],
    users: ['User Management', 'MANAGER'],
    maintenance: ['Maintenance & Retention', 'MANAGER'],
    documentation: ['Instructions & Documentation', 'MANAGER'],
    'system-logs': ['System Logs', 'MANAGER'],
    audit: ['Audit / History', 'MANAGER'],
    sync: ['Offsite Sync', 'MANAGER'],
    'manager-maintenance': ['Manager Maintenance', 'MANAGER'],
    templates: ['World Template Catalog', 'MANAGER'],
    'world-main': ['World Main', 'WORLD'],
    'world-backups': ['World Backup & Restore', 'WORLD'],
    'world-logs': ['World Logs', 'WORLD'],
    files: ['File Manager', 'WORLD'],
    'world-maintenance': ['World Maintenance & Retention', 'WORLD'],
    'world-setup': ['World Setup', 'WORLD'],
  };
  const NAV_GROUPS = {
    manager: [
      ['home', 'Homepage'], ['worlds', 'World Management'], ['settings', 'Manager Settings'],
      ['users', 'User Management'], ['maintenance', 'Maintenance & Retention'],
      ['documentation', 'Instructions & Docs'], ['system-logs', 'System Logs'],
      ['audit', 'Audit / History'], ['sync', 'Offsite Sync'],
      ['manager-maintenance', 'Manager Maintenance'], ['templates', 'World Templates'],
    ],
    world: [
      ['world-main', 'World Main'], ['world-backups', 'Backup & Restore'],
      ['world-logs', 'World Logs'], ['files', 'File Manager'],
      ['world-maintenance', 'World Maintenance'], ['world-setup', 'World Setup'],
    ],
  };
  const nowText = () => new Date().toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  const makeId = (prefix) => `${prefix}-${Math.random().toString(36).slice(2, 8).toUpperCase()}`;
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);

  const initialState = () => ({
    page: 'home',
    context: 'manager',
    selectedWorld: 'world-survival',
    theme: 'light',
    worlds: [
      { id: 'world-survival', name: 'Survival', type: 'Vanilla', version: '1.21.1', state: 'running', port: 25565, size: '2.4 GB', players: 3, lastStarted: 'Today, 09:14', eula: 'Accepted', rcon: true, serverAddress: 'survival.example.net' },
      { id: 'world-better-adventures', name: 'Better Adventures', type: 'Paper', version: '1.20.4', state: 'off', port: 25566, size: '5.8 GB', players: 0, lastStarted: 'Yesterday, 21:03', eula: 'Accepted', rcon: true, serverAddress: '25566' },
      { id: 'world-create', name: 'Create: Above and Beyond', type: 'Forge', version: '1.20.1', state: 'crashed', port: 25567, size: '8.1 GB', players: 0, lastStarted: 'Yesterday, 18:47', eula: 'Accepted', rcon: true, serverAddress: '25567' },
      { id: 'world-skyblock', name: 'Fabric Skyblock', type: 'Fabric', version: '1.21.1', state: 'off', port: 25568, size: '840 MB', players: 0, lastStarted: 'Nov 06, 2026', eula: 'Required', rcon: false, serverAddress: '25568' },
    ],
    templates: [
      { id: 'tpl-vanilla', name: 'Vanilla', type: 'Vanilla', version: '1.21.1', runtime: 'Java 21', worlds: 1 },
      { id: 'tpl-paper', name: 'Paper Performance', type: 'Paper', version: '1.20.4', runtime: 'Java 21', worlds: 1 },
      { id: 'tpl-forge', name: 'Forge Modded', type: 'Forge', version: '1.20.1', runtime: 'Java 21', worlds: 1 },
      { id: 'tpl-fabric', name: 'Fabric Lightweight', type: 'Fabric', version: '1.21.1', runtime: 'Java 21', worlds: 1 },
    ],
    runtimes: [
      { id: 'java-21', label: 'Java 21 LTS', version: '21.0.5', path: 'C:/Program Files/Java/jdk-21/bin/java.exe', status: 'Verified' },
      { id: 'java-17', label: 'Java 17 LTS', version: '17.0.13', path: 'C:/Program Files/Java/jdk-17/bin/java.exe', status: 'Verified' },
    ],
    users: [
      { id: 'usr-alex', username: 'alex.morgan', name: 'Alex Morgan', role: 'Superadmin', status: 'Active', lastAccess: 'Now' },
      { id: 'usr-riley', username: 'riley.chen', name: 'Riley Chen', role: 'Admin', status: 'Active', lastAccess: 'Today, 08:51' },
      { id: 'usr-sam', username: 'sam.taylor', name: 'Sam Taylor', role: 'Client', status: 'Active', lastAccess: 'Nov 06, 2026' },
    ],
    devices: [
      { id: 'dev-office', name: 'Office desktop', address: '192.168.1.24', status: 'Registered' },
      { id: 'dev-laptop', name: 'Alex laptop', address: '192.168.1.36', status: 'Registered' },
      { id: 'dev-unrecognized', name: 'Unrecognized device', address: '10.0.0.18', status: 'Unrecognized' },
    ],
    schedules: [
      { id: 'sch-nightly', name: 'Nightly backup', scope: 'Global', cadence: 'Daily at 03:00', enabled: true },
      { id: 'sch-weekend', name: 'Weekend full backup', scope: 'Survival', cadence: 'Weekly, Sunday at 02:00', enabled: true },
    ],
    backups: [
      { id: 'bk-survival-01', worldId: 'world-survival', name: 'Survival', category: 'session_end', size: '842 MB', createdAt: 'Today, 08:55', status: 'Complete', tone: 'positive', sync: 'Synced', attempts: ['Attempt 1 · Succeeded · 08:56'] },
      { id: 'bk-survival-02', worldId: 'world-survival', name: 'Survival', category: 'manual', size: '839 MB', createdAt: 'Nov 07, 2026, 21:10', status: 'Complete', tone: 'positive', sync: 'Pending', attempts: ['Attempt 1 · Failed · NAS timeout', 'Attempt 2 · Succeeded · 21:12'] },
      { id: 'bk-better-01', worldId: 'world-better-adventures', name: 'Better Adventures', category: 'scheduled', size: '1.2 GB', createdAt: 'Yesterday, 03:00', status: 'Complete', tone: 'positive', sync: 'Not configured', attempts: [] },
      { id: 'bk-manager-01', worldId: null, name: 'MC Manager', category: 'manager_config', size: '18 MB', createdAt: 'Nov 06, 2026, 12:00', status: 'Complete', tone: 'positive', sync: 'Not configured', attempts: [] },
    ],
    syncTargets: [
      { id: 'sync-nas', name: 'Home NAS', type: 'NAS', scope: 'Global', status: 'Enabled' },
      { id: 'sync-drive', name: 'Operations Drive', type: 'Google Drive', scope: 'Survival', status: 'Enabled' },
    ],
    syncRecords: [
      { id: 'sy-0182', target: 'Home NAS', artifact: 'bk-survival-02', status: 'Succeeded', time: 'Nov 07, 21:12', attempts: 2 },
      { id: 'sy-0181', target: 'Home NAS', artifact: 'bk-survival-01', status: 'Succeeded', time: 'Today, 08:56', attempts: 1 },
      { id: 'sy-0179', target: 'Operations Drive', artifact: 'bk-better-01', status: 'Failed', time: 'Nov 06, 03:02', attempts: 3 },
    ],
    missedRuns: [
      { id: 'mr-0041', schedule: 'Nightly backup', world: 'Create: Above and Beyond', expected: 'Nov 07, 03:00', resolution: 'Pending' },
    ],
    notifications: [
      { id: 'n-1', title: 'Backup sync retried', detail: 'Survival backup completed after one retry.', time: '08:56', read: false, tone: 'transitional' },
      { id: 'n-2', title: 'World crashed', detail: 'Create: Above and Beyond stopped unexpectedly.', time: 'Yesterday, 18:48', read: false, tone: 'negative' },
      { id: 'n-3', title: 'Backup completed', detail: 'Better Adventures · 1.2 GB.', time: 'Yesterday, 03:00', read: true, tone: 'positive' },
    ],
    audit: [
      { id: 'au-3904', time: 'Today, 09:14', actor: 'Riley Chen', event: 'RuntimeSessionStarted', world: 'Survival', outcome: 'Completed' },
      { id: 'au-3903', time: 'Today, 08:56', actor: 'System', event: 'SyncAttemptSucceeded', world: 'Survival', outcome: 'Succeeded' },
      { id: 'au-3899', time: 'Yesterday, 18:48', actor: 'System', event: 'CrashDetected', world: 'Create: Above and Beyond', outcome: 'Failed' },
      { id: 'au-3891', time: 'Nov 06, 12:00', actor: 'Alex Morgan', event: 'ManagerBackupCreated', world: 'Manager', outcome: 'Completed' },
    ],
    settings: { timezone: 'America/Los_Angeles', idleCountdown: 15, notificationSounds: true, worldRoot: 'D:/MCManager/worlds', backupRoot: 'D:/MCManager/backups', logRoot: 'D:/MCManager/logs' },
    cleanupPreview: null,
    logs: {
      'world-survival': [
        '[09:14:08] [Server thread/INFO]: Done (7.842s)! For help, type "help"',
        '[09:15:12] [Server thread/INFO]: There are 3 of a max of 20 players online',
        "[09:16:45] [Server thread/WARN]: Can't keep up! Is the server overloaded?",
      ],
      'world-better-adventures': ['[21:03:18] [Server thread/INFO]: Done (4.208s)! For help, type "help"'],
      'world-create': ['[18:48:02] [Server thread/ERROR]: Watchdog detected a server stall'],
      'world-skyblock': ['[Manager] EULA acceptance is required before startup.'],
    },
    files: {
      'world-survival|': [
        { name: 'advancements', type: 'Directory', size: '—', updated: 'Today, 09:14' },
        { name: 'logs', type: 'Directory', size: '—', updated: 'Today, 09:15' },
        { name: 'region', type: 'Directory', size: '1.7 GB', updated: 'Today, 09:14' },
        { name: 'server.properties', type: 'File', size: '2.1 KB', updated: 'Nov 07, 21:09' },
        { name: 'whitelist.json', type: 'File', size: '426 B', updated: 'Nov 06, 10:21' },
      ],
    },
    activity: [
      { time: '09:14:08', message: 'Survival reached operational readiness.' },
      { time: '08:56:22', message: 'Sync completed after retry.' },
      { time: 'Yesterday, 18:48', message: 'Create: Above and Beyond crashed.' },
    ],
  });

  function loadState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      return saved ? { ...initialState(), ...saved } : initialState();
    } catch (_error) {
      return initialState();
    }
  }

  let state = loadState();
  const pageContent = document.getElementById('pageContent');
  const pageTitle = document.getElementById('pageTitle');
  const pageEyebrow = document.getElementById('pageEyebrow');
  const pageActions = document.getElementById('pageActions');
  const navGroups = document.getElementById('navGroups');
  const contextSelect = document.getElementById('contextSelect');
  const contextCrumb = document.getElementById('contextCrumb');
  const themeToggle = document.getElementById('themeToggle');
  const toastRegion = document.getElementById('toastRegion');
  const dialog = document.getElementById('actionDialog');
  let toastTimer = 0;
  let logTimer = 0;
  let currentLogChannel = 'Minecraft';

  function persist() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_error) { /* File URL storage may be blocked. */ }
  }

  function esc(value) { return escapeHtml(value); }
  function world(id = state.selectedWorld) { return state.worlds.find((item) => item.id === id); }
  function pageAction(label, action, id = '', family = 'general', disabled = false, extra = '') {
    return `<button class="ui-button ui-button-${family}" type="button" data-action="${esc(action)}"${id ? ` data-id="${esc(id)}"` : ''}${disabled ? ' disabled' : ''}${extra}>${esc(label)}</button>`;
  }
  function status(label, tone = 'neutral') { return `<span class="status-indicator" data-tone="${tone}">${esc(label)}</span>`; }
  function field(label, name, value = '', type = 'text', required = false, extra = '') {
    return `<label class="form-field">${esc(label)}<input class="ui-text-input" name="${esc(name)}" type="${esc(type)}" value="${esc(value)}"${required ? ' required' : ''}${extra}></label>`;
  }
  function selectField(label, name, options, value = '', extra = '') {
    return `<label class="form-field">${esc(label)}<select class="ui-text-input" name="${esc(name)}"${extra}>${options.map(([key, title]) => `<option value="${esc(key)}"${String(key) === String(value) ? ' selected' : ''}>${esc(title)}</option>`).join('')}</select></label>`;
  }
  function section(title, content, actions = '') {
    return `<section class="pane-content-area"><div class="section-heading"><h2>${esc(title)}</h2>${actions ? `<div class="pane-head-actions">${actions}</div>` : ''}</div>${content}</section>`;
  }
  function empty(text) { return `<p class="empty-state">${esc(text)}</p>`; }
  function feedback(kind = 'info') {
    return state.feedback ? `<p class="status-line" data-kind="${kind}">${esc(state.feedback)}</p>` : '';
  }
  function toneForWorld(value) {
    if (value === 'running' || value === 'Complete' || value === 'Succeeded' || value === 'Enabled') return 'positive';
    if (value === 'crashed' || value === 'Failed' || value === 'Error') return 'negative';
    if (['starting', 'stopping', 'queued', 'backing_up', 'restoring', 'Pending'].includes(value)) return 'transitional';
    return 'neutral';
  }
  function pushAudit(event, target = 'Manager', outcome = 'Completed') {
    state.audit.unshift({ id: makeId('au'), time: nowText(), actor: 'Alex Morgan', event, world: target, outcome });
    state.activity.unshift({ time: nowText(), message: `${event} · ${target}` });
  }
  function notify(title, detail, tone = 'neutral') {
    state.notifications.unshift({ id: makeId('n'), title, detail, time: nowText(), read: false, tone });
  }
  function toast(message) {
    toastRegion.textContent = message;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { toastRegion.textContent = ''; }, 2800);
  }
  function dialogForm(title, content, confirmLabel, onConfirm, confirmFamily = 'blue') {
    dialog.innerHTML = `<form class="dialog-form" method="dialog"><header class="pane-title-area"><h2 id="dialogTitle">${esc(title)}</h2></header><section class="pane-content-area">${content}</section><div class="dialog-actions"><button class="ui-button ui-button-general" type="button" data-dialog-close>Cancel</button><button class="ui-button ui-button-${confirmFamily}" type="submit">${esc(confirmLabel)}</button></div></form>`;
    const form = dialog.querySelector('form');
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form).entries());
      dialog.close();
      Promise.resolve(onConfirm(values)).catch((error) => toast(error.message || 'Action failed.'));
    }, { once: true });
    dialog.querySelector('[data-dialog-close]').addEventListener('click', () => dialog.close(), { once: true });
    dialog.showModal();
  }
  function confirm(title, detail, action, id = '', dangerous = false) {
    dialogForm(title, `<p>${esc(detail)}</p>`, 'Confirm', () => runAction(action, id, true), dangerous ? 'red' : 'blue', dangerous);
  }

  function renderNav() {
    const currentWorld = world();
    contextSelect.innerHTML = `<option value="manager">Manager</option>${state.worlds.map((item) => `<option value="${esc(item.id)}">World: ${esc(item.name)}</option>`).join('')}`;
    contextSelect.value = state.context === 'manager' ? 'manager' : state.selectedWorld;
    const managerOpen = state.context === 'manager' || !state.page.startsWith('world-') && state.page !== 'files';
    navGroups.innerHTML = [
      ['Manager Context', 'manager', managerOpen],
      ['World Context', 'world', !managerOpen],
    ].map(([label, group, open]) => `<details class="nav-group"${open ? ' open' : ''}><summary>${label}</summary><div class="nav-links">${NAV_GROUPS[group].map(([key, title]) => `<a href="#/${key}" class="ui-button ui-button-general nav-link${state.page === key ? ' is-active' : ''}" data-page="${key}"${group === 'world' && !currentWorld ? ' aria-disabled="true"' : ''}>${title}</a>`).join('')}</div></details>`).join('');
    contextCrumb.textContent = state.context === 'manager' ? 'Manager context' : `World context · ${currentWorld?.name || 'Select a world'}`;
    document.documentElement.dataset.theme = state.theme;
    themeToggle.checked = state.theme === 'dark';
    document.getElementById('notificationCount').textContent = String(state.notifications.filter((item) => !item.read).length);
    pageTitle.textContent = PAGE_INFO[state.page]?.[0] || PAGE_INFO.home[0];
    pageEyebrow.textContent = PAGE_INFO[state.page]?.[1] || 'MANAGER';
    pageActions.innerHTML = state.page === 'home'
      ? pageAction('Refresh', 'refresh', '', 'blue')
      : state.page === 'world-main' ? pageAction('Manage world', 'manage-world', currentWorld?.id || '', 'general') : '';
  }

  function worldRows(items, options = {}) {
    if (!items.length) return empty('No worlds match this view.');
    return `<div class="list-surface">${items.map((item) => `<div class="world-row"><div class="world-info"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.type)} · ${esc(item.version)} · Port ${esc(item.port)}</span></div><div class="inline-actions">${status(item.state, toneForWorld(item.state))}${options.actions === false ? '' : `<div class="inline-actions">${pageAction('Start', 'world-start', item.id, 'teal', item.state !== 'off')}${pageAction('Stop', 'world-stop', item.id, 'red', item.state !== 'running')}${pageAction('Backup', 'world-backup', item.id, 'blue', !['off', 'running'].includes(item.state))}${pageAction('Manage', 'manage-world', item.id, 'general')}</div>`}</div></div>`).join('')}</div>`;
  }

  function renderHome() {
    const running = state.worlds.filter((item) => item.state === 'running');
    const recent = [...state.worlds].sort((a, b) => a.lastStarted.localeCompare(b.lastStarted)).slice(0, 5);
    return `${section('Server Stats', `<div class="metric-grid"><div class="metric-block"><span class="metric-label">CPU</span><strong class="metric-value">27%</strong><span class="metric-detail">8 cores · load normal</span></div><div class="metric-block"><span class="metric-label">RAM</span><strong class="metric-value">18.4 / 32 GB</strong><span class="metric-detail">57% allocated</span></div><div class="metric-block"><span class="metric-label">Storage</span><strong class="metric-value">412 / 960 GB</strong><span class="metric-detail">548 GB available</span></div><div class="metric-block"><span class="metric-label">Worlds</span><strong class="metric-value">${state.worlds.length}</strong><span class="metric-detail">${running.length} currently running</span></div></div>`, pageAction('System status', 'go-page', 'system-logs', 'general'))}${section('Running Worlds', worldRows(running))}${section('Recently Run Worlds', worldRows(recent))}${section('Recent Notifications', notificationRows(state.notifications.slice(0, 4)))}`;
  }

  function renderWorlds() {
    const templates = state.templates.map((item) => [item.id, `${item.name} · ${item.version}`]);
    return `${feedback()}${section('World List', `<div class="filter-row"><label class="form-field">Search<input class="ui-text-input" name="worldSearch" type="search" placeholder="Name or version"></label>${selectField('State', 'worldState', [['all', 'All states'], ['running', 'Running'], ['off', 'Off'], ['crashed', 'Crashed']])}${selectField('Server type', 'worldType', [['all', 'All types'], ['Vanilla', 'Vanilla'], ['Paper', 'Paper'], ['Forge', 'Forge'], ['Fabric', 'Fabric']])}${selectField('Version', 'worldVersion', [['all', 'All versions'], ...[...new Set(state.worlds.map((item) => [item.version, item.version]))]])}<button class="ui-button ui-button-blue" type="button" data-action="filter-worlds">Filter</button></div><div id="worldResults">${worldRows(state.worlds)}</div>`, pageAction('Create World', 'scroll-to', 'createWorld', 'teal'))}${section('Create World', `<form class="form-grid" data-form="create-world">${field('Display name', 'name', '', 'text', true)}${selectField('Template', 'template', templates)}${selectField('Java runtime', 'runtime', state.runtimes.map((item) => [item.id, `${item.label} · ${item.status}`]))}${field('Port', 'port', '25569', 'number', true)}${selectField('Addressing strategy', 'addressing', [['port', 'Port'], ['subdomain', 'Subdomain'], ['path', 'Path']])}${field('Address value', 'address', '25569') }<div class="form-field full-width"><span class="help-text">The instance will be created from a curated template. Runtime configuration can be changed before first start.</span></div><div class="form-field full-width"><button class="ui-button ui-button-teal" type="submit">Create World</button></div></form>`)}${section('Backup Schedules', scheduleRows(state.schedules))}`;
  }

  function scheduleRows(items) {
    if (!items.length) return empty('No schedules configured.');
    return `<div class="list-surface">${items.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.scope)} · ${esc(item.cadence)}</span></div>${status(item.enabled ? 'Enabled' : 'Disabled', item.enabled ? 'positive' : 'neutral')}<div class="inline-actions">${pageAction(item.enabled ? 'Disable' : 'Enable', 'schedule-toggle', item.id, 'general')}${pageAction('Delete', 'schedule-delete', item.id, 'red')}</div></div>`).join('')}</div><form class="form-grid" data-form="create-schedule"><h3 class="form-field full-width">Add schedule</h3>${field('Schedule name', 'name', '', 'text', true)}${selectField('Scope', 'scope', [['Global', 'Manager-wide'], ...state.worlds.map((item) => [item.name, item.name])])}${selectField('Cadence', 'cadence', [['Daily at 03:00', 'Daily at 03:00'], ['Weekly, Sunday at 02:00', 'Weekly, Sunday at 02:00'], ['Every 3 days', 'Every 3 days']])}<div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Add Schedule</button></div></form>`;
  }

  function renderSettings() {
    return `${feedback()}${section('Manager Settings', `<form class="form-grid" data-form="settings">${selectField('Timezone', 'timezone', [['America/Los_Angeles', 'Pacific Time'], ['America/New_York', 'Eastern Time'], ['UTC', 'UTC']], state.settings.timezone)}${field('Idle countdown (minutes)', 'idleCountdown', state.settings.idleCountdown, 'number')}${field('World root path', 'worldRoot', state.settings.worldRoot)}${field('Backup root path', 'backupRoot', state.settings.backupRoot)}${field('Log root path', 'logRoot', state.settings.logRoot)}<label class="theme-switch"><input type="checkbox" name="notificationSounds"${state.settings.notificationSounds ? ' checked' : ''}> Notification sounds enabled</label><div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Save Settings</button></div></form>`)}${section('Setup / Onboarding', `<div class="list-surface"><div class="list-row"><div class="row-main"><strong>Initial system checks</strong><span class="table-meta">Java 21 verified · Python runtime available · Storage writable</span></div>${status('Complete', 'positive')}</div><div class="list-row"><div class="row-main"><strong>Import worlds</strong><span class="table-meta">Scan a managed directory for existing instances</span></div>${pageAction('Scan Worlds', 'setup-scan', '', 'blue')}</div><div class="list-row"><div class="row-main"><strong>Template catalog</strong><span class="table-meta">${state.templates.length} templates available</span></div>${pageAction('Review Templates', 'go-page', 'templates', 'general')}</div></div>`)}`;
  }

  function renderUsers() {
    return `${feedback()}${section('User Accounts', `<div class="list-surface">${state.users.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.username)} · Last accessed ${esc(item.lastAccess)}</span></div>${status(item.status, item.status === 'Active' ? 'positive' : 'neutral')}<span>${esc(item.role)}</span><div class="inline-actions">${pageAction('Change Role', 'user-role', item.id, 'general')}${pageAction(item.status === 'Active' ? 'Disable' : 'Enable', 'user-toggle', item.id, 'general')}${pageAction('Delete', 'user-delete', item.id, 'red')}</div></div>`).join('')}</div><form class="form-grid" data-form="create-user"><h3 class="form-field full-width">Create User</h3>${field('Name', 'name', '', 'text', true)}${field('Username', 'username', '', 'text', true)}${field('Password', 'password', '', 'password', true)}${selectField('Role', 'role', [['Client', 'Client'], ['Admin', 'Admin'], ['Superadmin', 'Superadmin']])}<div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Create User</button></div></form>`)}${section('Devices', `<div class="list-surface">${state.devices.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.address)}</span></div>${status(item.status, item.status === 'Registered' ? 'positive' : 'neutral')}${pageAction('Revoke', 'device-revoke', item.id, 'red', item.status !== 'Registered')}</div>`).join('')}</div>`)}`;
  }

  function renderMaintenance() {
    return `${feedback()}${section('Global Cleanup Policy', `<form class="form-grid" data-form="cleanup-policy">${field('Minimum backup age (days)', 'ageFloor', 3, 'number')}${field('Newest backups per category', 'countFloor', 3, 'number')}${selectField('Cleanup scope', 'scope', [['backups', 'Backups'], ['stale_worlds', 'Stale worlds (policy required)'], ['logs', 'Old logs (policy required)']])}<label class="theme-switch"><input type="checkbox" name="dryRun" checked> Preview before deleting</label><div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Run Dry Preview</button></div></form>${state.cleanupPreview ? `<div class="list-row"><div class="row-main"><strong>Preview ${esc(state.cleanupPreview.id)}</strong><span class="table-meta">${state.cleanupPreview.count} eligible backup artifacts · no files deleted</span></div>${pageAction('Execute Preview', 'cleanup-execute', state.cleanupPreview.id, 'red')}</div>` : ''}<p class="help-text">Stale-world and log deletion are unavailable until their eligibility and retention policies are approved.</p>`)}${section('Missed Scheduled Runs', missedRows(state.missedRuns))}${section('Recent Cleanup Activity', activityRows(state.activity.filter((item) => item.message.toLowerCase().includes('cleanup'))))}`;
  }

  function missedRows(items) {
    if (!items.length) return empty('No missed scheduled runs.');
    return `<div class="list-surface">${items.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.schedule)}</strong><span class="table-meta">${esc(item.world)} · Expected ${esc(item.expected)}</span></div>${status(item.resolution, toneForWorld(item.resolution))}<div class="inline-actions">${pageAction('Resolve', 'missed-resolve', item.id, 'blue', item.resolution !== 'Pending')}${pageAction('Ignore', 'missed-ignore', item.id, 'general', item.resolution !== 'Pending')}</div></div>`).join('')}</div>`;
  }

  function activityRows(items) {
    if (!items.length) return empty('No recent activity.');
    return `<div class="list-surface">${items.slice(0, 8).map((item) => `<div class="list-row"><span>${esc(item.message)}</span><span class="table-meta">${esc(item.time)}</span></div>`).join('')}</div>`;
  }

  function renderDocumentation() {
    const docs = [
      ['Operator Guide', 'Daily world operations, backup handling, and safe recovery.'],
      ['Administration', 'Users, roles, permissions, settings, and device trust.'],
      ['Architecture', 'Adapters, ports, services, persistence, and process ownership.'],
      ['API Contract', 'Request envelopes, authorization, error codes, and event topics.'],
      ['Recovery Runbook', 'Restore decisions, suspect artifacts, and escalation paths.'],
    ];
    return `${section('Documentation Library', `<div class="list-surface">${docs.map(([title, detail]) => `<div class="list-row"><div class="row-main"><strong>${esc(title)}</strong><span class="table-meta">${esc(detail)}</span></div>${pageAction('Open', 'open-doc', title, 'general')}</div>`).join('')}</div>`)}${section('Selected Document', `<p class="eyebrow">OPERATOR GUIDE</p><h3>World lifecycle</h3><p class="help-text">Start and stop actions create durable operations. Wait for the operation status and readiness state before escalating. Restore is available only while the world is off.</p>`)}`;
  }

  function notificationRows(items) {
    if (!items.length) return empty('No notifications.');
    return `<div class="list-surface">${items.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.title)}</strong><span class="table-meta">${esc(item.detail)} · ${esc(item.time)}</span></div>${status(item.read ? 'Read' : 'Unread', item.tone)}${pageAction(item.read ? 'Dismiss' : 'Mark Read', item.read ? 'notification-dismiss' : 'notification-read', item.id, 'general')}</div>`).join('')}</div>`;
  }

  function renderSystemLogs() {
    return `${section('Manager Health', `<div class="metric-grid"><div class="metric-block"><span class="metric-label">Application</span><strong class="metric-value">Healthy</strong></div><div class="metric-block"><span class="metric-label">Database</span><strong class="metric-value">Connected</strong></div><div class="metric-block"><span class="metric-label">Scheduler</span><strong class="metric-value">Running</strong></div><div class="metric-block"><span class="metric-label">Last reconciliation</span><strong class="metric-value">09:00</strong></div></div>`)}${section('Manager Activity', activityRows(state.activity))}${section('System Notifications', notificationRows(state.notifications))}`;
  }

  function renderAudit() {
    const rows = state.audit.filter((item) => !state.auditFilter || `${item.event} ${item.actor} ${item.world}`.toLowerCase().includes(state.auditFilter.toLowerCase()));
    return `${section('Audit History', `<form class="filter-row" data-form="audit-filter">${field('Search history', 'search', state.auditFilter, 'search')}<button class="ui-button ui-button-blue" type="submit">Filter</button></form><div class="table-head"><span>Time</span><span>Actor</span><span>Event</span><span>World</span><span>Outcome</span></div><div class="list-surface">${rows.map((item) => `<div class="table-row"><span>${esc(item.time)}</span><span>${esc(item.actor)}</span><strong>${esc(item.event)}</strong><span>${esc(item.world)}</span>${status(item.outcome, toneForWorld(item.outcome))}</div>`).join('') || empty('No audit records match the filter.')}</div>`)}`;
  }

  function renderSync() {
    return `${feedback()}${section('Sync Targets', `<div class="list-surface">${state.syncTargets.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.type)} · ${esc(item.scope)}</span></div>${status(item.status, toneForWorld(item.status))}${pageAction('Edit', 'sync-edit', item.id, 'general')}${pageAction('Delete', 'sync-delete', item.id, 'red')}</div>`).join('')}</div><p class="help-text">Credentials are stored separately and never shown again after saving.</p><form class="form-grid" data-form="create-sync"><h3 class="form-field full-width">Add Sync Target</h3>${field('Target name', 'name', '', 'text', true)}${selectField('Method', 'type', [['NAS', 'Network attached storage'], ['Google Drive', 'Google Drive'], ['Other', 'Other']])}${selectField('Scope', 'scope', [['Global', 'Global default'], ...state.worlds.map((item) => [item.name, `World: ${item.name}`])])}${field('Credential', 'credential', '', 'password', true)}<div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Save Target</button></div></form>`)}${section('Recent Sync Activity', syncRows(state.syncRecords))}`;
  }

  function syncRows(items) {
    return `<div class="list-surface">${items.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.artifact)}</strong><span class="table-meta">${esc(item.target)} · ${esc(item.time)} · ${item.attempts} attempt(s)</span></div>${status(item.status, toneForWorld(item.status))}${pageAction('Retry', 'sync-retry', item.id, 'blue', item.status === 'Pending')}</div>`).join('') || empty('No sync activity.')}</div>`;
  }

  function renderManagerMaintenance() {
    const backups = state.backups.filter((item) => item.worldId === null);
    return `${section('Manager Status', `<div class="metric-grid"><div class="metric-block"><span class="metric-label">Version</span><strong class="metric-value">0.4.0-prototype</strong></div><div class="metric-block"><span class="metric-label">State</span>${status('Operational', 'positive')}</div><div class="metric-block"><span class="metric-label">Last backup</span><strong>${esc(backups[0]?.createdAt || 'None')}</strong></div><div class="metric-block"><span class="metric-label">Worlds</span><strong class="metric-value">${state.worlds.length}</strong></div></div>`)}${section('Manager Backup', `<div class="action-row">${pageAction('Create Manager Backup', 'manager-backup', '', 'blue')}</div><div class="list-surface">${backups.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.id)}</strong><span class="table-meta">${esc(item.size)} · ${esc(item.createdAt)} · Includes manager database and settings</span></div>${status(item.status, item.tone)}${pageAction('Restore', 'manager-restore', item.id, 'red')}</div>`).join('') || empty('No manager backups found.')}</div>`)}${section('Manager Lifecycle', `<div class="action-row">${pageAction('Restart Manager', 'manager-restart', '', 'red')}${pageAction('Check for Update', 'manager-update', '', 'blue')}${pageAction('Rollback Version', 'manager-rollback', '', 'red')}</div><p class="help-text">Prototype simulation only. Production behavior requires host-supervisor, trust, and recovery contracts.</p>`)}`;
  }

  function renderTemplates() {
    return `${section('Template Catalog', `<div class="list-surface">${state.templates.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.name)}</strong><span class="table-meta">${esc(item.type)} · Minecraft ${esc(item.version)} · ${esc(item.runtime)} · ${item.worlds} world(s)</span></div>${pageAction('Edit', 'template-edit', item.id, 'general')}${pageAction('Delete', 'template-delete', item.id, 'red')}</div>`).join('')}</div><form class="form-grid" data-form="create-template"><h3 class="form-field full-width">Create Template</h3>${field('Template name', 'name', '', 'text', true)}${selectField('Server type', 'type', [['Vanilla', 'Vanilla'], ['Paper', 'Paper'], ['Forge', 'Forge'], ['Fabric', 'Fabric'], ['Custom', 'Custom']])}${field('Minecraft version', 'version', '', 'text', true)}${selectField('Java runtime', 'runtime', state.runtimes.map((item) => [item.label, item.label]))}<div class="form-field full-width"><button class="ui-button ui-button-teal" type="submit">Create Template</button></div></form>`)}`;
  }

  function worldControls(items) {
    return items.map((item) => `${pageAction('Start', 'world-start', item.id, 'teal', item.state !== 'off')}` +
      `${pageAction('Stop', 'world-stop', item.id, 'red', item.state !== 'running')}` +
      `${pageAction('Backup', 'world-backup', item.id, 'blue', !['off', 'running'].includes(item.state))}` +
      `${pageAction('Manage', 'manage-world', item.id, 'general')}`).join('');
  }

  function renderWorldMain() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    return `${section('World Status', `<div class="list-row"><div class="row-main"><strong>${esc(current.name)}</strong><span class="table-meta">${esc(current.type)} · Minecraft ${esc(current.version)} · ${esc(current.serverAddress)}</span></div>${status(current.state, toneForWorld(current.state))}</div><div class="action-row">${worldControls([current])}</div>`)}${section('World Stats', `<div class="metric-grid"><div class="metric-block"><span class="metric-label">Storage</span><strong class="metric-value">${esc(current.size)}</strong></div><div class="metric-block"><span class="metric-label">Players online</span><strong class="metric-value">${current.players}</strong></div><div class="metric-block"><span class="metric-label">Last started</span><strong>${esc(current.lastStarted)}</strong></div><div class="metric-block"><span class="metric-label">Current port</span><strong class="metric-value">${current.state === 'running' ? current.port : '—'}</strong></div></div>`)}${section('Capabilities', `<div class="list-row"><span>RCON control</span>${status(current.rcon ? 'Available' : 'Unavailable', current.rcon ? 'positive' : 'neutral')}</div><div class="list-row"><span>Protocol ping</span>${status('Available', 'positive')}</div><div class="list-row"><span>EULA</span>${status(current.eula, current.eula === 'Accepted' ? 'positive' : 'negative')}${current.eula !== 'Accepted' ? pageAction('Review and Accept', 'eula-accept', current.id, 'blue') : ''}</div>`)}`;
  }

  function renderBackups() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    const backups = state.backups.filter((item) => item.worldId === current.id);
    return `${section('Backup Artifacts', `<div class="action-row">${pageAction('Create Manual Backup', 'world-backup', current.id, 'blue', !['off', 'running'].includes(current.state))}</div><div class="list-surface">${backups.map((item) => `<div class="list-row"><div class="row-main"><strong>${esc(item.id)}</strong><span class="table-meta">${esc(item.category)} · ${esc(item.size)} · ${esc(item.createdAt)}</span></div>${status(item.status, item.tone)}${status(item.sync, toneForWorld(item.sync))}<div class="inline-actions">${pageAction('Restore', 'backup-restore', item.id, 'red', current.state !== 'off')}${pageAction('Delete', 'backup-delete', item.id, 'general')}${pageAction('Sync Attempts', 'backup-attempts', item.id, 'general')}</div></div><div class="table-meta">${(item.attempts || []).map(esc).join(' · ')}</div>`).join('') || empty('No backups yet.')}</div>`)}${section('Restore History', activityRows(state.activity.filter((item) => item.message.toLowerCase().includes('restore'))))}`;
  }

  function renderLogs() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    const lines = state.logs[current.id] || [];
    return `${section('World Log Stream', `<div class="filter-row">${selectField('Channel', 'logChannel', [['Minecraft', 'Minecraft'], ['Debug', 'Debug'], ['Crash Reports', 'Crash Reports'], ['Backup / Restore', 'Backup / Restore']], currentLogChannel)}${pageAction('Refresh Tail', 'logs-refresh', current.id, 'blue')}</div><pre class="log-output" id="liveLogOutput" aria-live="polite">${lines.map(esc).join('\n')}</pre>`)}${section('Log Files', `<div class="list-surface"><div class="list-row"><strong>latest.log</strong><span class="table-meta">2.1 MB · Updated ${esc(current.lastStarted)}</span>${pageAction('Open', 'open-log', 'latest.log', 'general')}</div><div class="list-row"><strong>debug.log</strong><span class="table-meta">18.4 MB · Updated ${esc(current.lastStarted)}</span>${pageAction('Download', 'download-log', 'debug.log', 'general')}</div><div class="list-row"><strong>crash-reports/</strong><span class="table-meta">2 reports</span>${pageAction('Open', 'open-log', 'crash-reports', 'general')}</div></div>`)}`;
  }

  function filePathKey(id, path) { return `${id}|${path}`; }
  function renderFiles() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    state.filePath = state.filePath || '';
    const entries = state.files[filePathKey(current.id, state.filePath)] || [];
    return `${section(`File Manager · /${esc(state.filePath)}`, `<form class="filter-row" data-form="file-open-path">${field('Path', 'path', state.filePath)}<button class="ui-button ui-button-general" type="submit">Open</button></form><div class="list-surface">${entries.map((item) => `<div class="list-row"><div class="row-main"><strong>${item.type === 'Directory' ? 'Directory · ' : ''}${esc(item.name)}</strong><span class="table-meta">${esc(item.size)} · Updated ${esc(item.updated)}</span></div>${item.type === 'Directory' ? pageAction('Open', 'file-open', item.name, 'general') : pageAction('Download', 'file-download', item.name, 'general')}${pageAction('Rename', 'file-rename', item.name, 'general')}${pageAction('Move', 'file-move', item.name, 'general')}${pageAction('Copy', 'file-copy', item.name, 'general')}${pageAction('Delete', 'file-delete', item.name, 'red')}</div>`).join('') || empty('This directory is empty.')}</div><div class="action-row">${pageAction('New Folder', 'file-mkdir', '', 'teal')}${pageAction('Upload File', 'file-upload', '', 'blue')}</div><p class="help-text">Access is contained to the selected world directory; symlink paths are rejected.</p>`)}`;
  }

  function renderWorldMaintenance() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    return `${section('Effective Retention', `<div class="list-row"><div class="row-main"><strong>Global policy</strong><span class="table-meta">Keep 3 newest per category · minimum age 3 days</span></div>${status('Inherited', 'neutral')}${pageAction('Override', 'world-retention-override', current.id, 'general')}</div><p class="help-text">Stale-world and log cleanup remain disabled pending policy approval.</p>`)}${section('World Cleanup Preview', `<div class="action-row">${pageAction('Preview Backup Cleanup', 'world-cleanup-preview', current.id, 'blue')}</div>${state.cleanupPreview?.worldId === current.id ? `<div class="list-row"><span>${state.cleanupPreview.count} artifact(s) eligible</span>${status('Dry run', 'transitional')}${pageAction('Execute Preview', 'cleanup-execute', state.cleanupPreview.id, 'red')}</div>` : empty('No preview has been run.')}`)}`;
  }

  function renderWorldSetup() {
    const current = world();
    if (!current) return empty('Choose a world from the context selector.');
    const props = current.properties || { 'server-port': String(current.port), 'motd': current.name, 'online-mode': 'true', 'enable-rcon': current.rcon ? 'true' : 'false' };
    return `${section('Server Properties', `<form class="form-grid" data-form="properties">${Object.entries(props).map(([key, value]) => field(key, `prop:${key}`, value)).join('')}<label class="form-field"><span>Java runtime</span><select class="ui-text-input" name="runtime">${state.runtimes.map((item) => `<option value="${esc(item.label)}">${esc(item.label)} · ${esc(item.status)}</option>`).join('')}</select></label><div class="form-field full-width"><button class="ui-button ui-button-blue" type="submit">Validate and Save</button></div></form><p class="help-text">Managed keys use guarded controls. Deprecated and unknown properties are preserved until explicitly changed.</p>`) }${section('EULA', `<div class="list-row"><div class="row-main"><strong>End User License Agreement</strong><span class="table-meta">Current state · ${esc(current.eula)}</span></div>${status(current.eula, current.eula === 'Accepted' ? 'positive' : 'negative')}${current.eula !== 'Accepted' ? pageAction('Review and Accept', 'eula-accept', current.id, 'blue') : ''}</div>`)}`;
  }

  function renderPage() {
    if (logTimer) { clearInterval(logTimer); logTimer = 0; }
    renderNav();
    const page = state.page;
    const renderers = {
      home: renderHome,
      worlds: renderWorlds,
      settings: renderSettings,
      users: renderUsers,
      maintenance: renderMaintenance,
      documentation: renderDocumentation,
      'system-logs': renderSystemLogs,
      audit: renderAudit,
      sync: renderSync,
      'manager-maintenance': renderManagerMaintenance,
      templates: renderTemplates,
      'world-main': renderWorldMain,
      'world-backups': renderBackups,
      'world-logs': renderLogs,
      files: renderFiles,
      'world-maintenance': renderWorldMaintenance,
      'world-setup': renderWorldSetup,
    };
    pageContent.innerHTML = (renderers[page] || renderHome)();
    if (page === 'world-logs') {
      logTimer = window.setInterval(() => {
        const current = world();
        if (!current || current.state !== 'running') return;
        (state.logs[current.id] ||= []).push(`[${new Date().toLocaleTimeString()}] [Server thread/INFO]: Player activity updated`);
        if (state.logs[current.id].length > 120) state.logs[current.id].shift();
        const output = document.getElementById('liveLogOutput');
        if (output) { output.textContent = state.logs[current.id].join('\n'); output.scrollTop = output.scrollHeight; }
        persist();
      }, 5000);
    }
  }

  function navigate(page, push = true) {
    if (!PAGE_INFO[page]) return;
    state.page = page;
    if (page.startsWith('world-') || page === 'files') state.context = 'world';
    else state.context = 'manager';
    persist();
    if (push) history.pushState({ page }, '', `#/${page}`);
    renderPage();
    document.body.classList.remove('nav-open');
    document.getElementById('navToggle').setAttribute('aria-expanded', 'false');
  }

  function addBackup(worldId, category = 'manual') {
    const current = world(worldId);
    const item = { id: makeId(worldId ? 'bk' : 'mb'), worldId: worldId || null, name: current?.name || 'MC Manager', category, size: worldId ? `${Math.floor(120 + Math.random() * 800)} MB` : '19 MB', createdAt: nowText(), status: 'Complete', tone: 'positive', sync: 'Pending', attempts: ['Attempt 1 · Pending'] };
    state.backups.unshift(item);
    if (current) { item.sync = state.syncTargets.length ? 'Pending' : 'Not configured'; current.lastStarted = current.lastStarted; }
    pushAudit(worldId ? 'BackupCreated' : 'ManagerBackupCreated', current?.name || 'Manager');
    notify('Backup completed', `${item.name} · ${item.size}.`, 'positive');
    return item;
  }

  function saveAndRender(message = '') {
    if (message) state.feedback = message;
    persist();
    renderPage();
    if (message) toast(message);
  }

  function openConfirm(action, id) {
    const dangerous = ['world-stop', 'world-kill', 'world-delete', 'backup-restore', 'backup-delete', 'cleanup-execute', 'manager-restore', 'manager-restart', 'manager-rollback'].includes(action);
    const labels = {
      'world-stop': ['Stop World', 'Connected players may be disconnected. The world will receive a graceful stop request.', 'Stop World'],
      'world-kill': ['Kill World', 'Force termination can cause unsaved world data loss.', 'Force Kill'],
      'world-delete': ['Delete World', 'This simulation tombstones the world and retains its history.', 'Delete World'],
      'backup-restore': ['Restore Backup', 'The world must be off. A pre-restore backup will be created before the selected artifact is applied.', 'Restore'],
      'backup-delete': ['Delete Backup', 'The artifact will be removed only if retention guards allow it.', 'Delete Artifact'],
      'cleanup-execute': ['Execute Cleanup', 'This is a simulated wet run. Only items in the completed preview will be considered.', 'Execute Cleanup'],
      'manager-restore': ['Restore Manager', 'This prototype simulates restoring manager settings. Production recovery contracts remain under review.', 'Restore Manager'],
      'manager-restart': ['Restart Manager', 'The host relaunch is simulated; running worlds remain attached.', 'Restart Manager'],
      'manager-rollback': ['Rollback Version', 'A previous manager version will be selected in this simulation.', 'Rollback'],
    };
    const [title, detail, proceed] = labels[action] || ['Confirm Action', 'Continue with this action?', 'Continue'];
    dialogForm(title, `<p>${esc(detail)}</p>`, proceed, () => runAction(action, id, true), dangerous ? 'red' : 'blue');
  }

  function runAction(action, id = '', confirmed = false) {
    if (['world-stop', 'world-kill', 'world-delete', 'backup-restore', 'backup-delete', 'cleanup-execute', 'manager-restore', 'manager-restart', 'manager-rollback'].includes(action) && !confirmed) return openConfirm(action, id);
    const current = world(id || state.selectedWorld);
    switch (action) {
      case 'world-start':
        if (!current || current.state !== 'off') break;
        if (current.eula !== 'Accepted') { state.page = 'world-setup'; return saveAndRender('Accept the EULA before starting this world.'); }
        current.state = 'running'; current.lastStarted = nowText();
        pushAudit('WorldStarted', current.name); notify('World started', `${current.name} is running.`, 'positive');
        return saveAndRender(`${current.name} started and reached readiness.`);
      case 'world-stop':
        if (!current) break;
        current.state = 'off'; current.players = 0; pushAudit('WorldStopped', current.name); notify('World stopped', current.name, 'neutral');
        return saveAndRender(`${current.name} stopped gracefully.`);
      case 'world-kill':
        if (!current) break;
        current.state = 'crashed'; current.players = 0; pushAudit('WorldKilled', current.name, 'Completed');
        return saveAndRender(`${current.name} was force-stopped. Review world state before restart.`);
      case 'world-backup': {
        if (!current) break;
        const backup = addBackup(current.id);
        return saveAndRender(`Backup ${backup.id} completed.`);
      }
      case 'manage-world':
        state.selectedWorld = id; state.context = 'world'; return navigate('world-main');
      case 'world-rename':
        return dialogForm('Rename World', field('Display name', 'name', current?.name || '', 'text', true), 'Save Name', ({ name }) => { if (!current || !name.trim()) return; current.name = name.trim(); pushAudit('WorldRenamed', current.name); saveAndRender('World name updated.'); });
      case 'world-delete':
        if (!current) break;
        state.worlds = state.worlds.filter((item) => item.id !== id); pushAudit('WorldDeleted', current.name); state.selectedWorld = state.worlds[0]?.id || ''; state.context = 'manager'; state.page = 'worlds'; return saveAndRender(`${current.name} was tombstoned.`);
      case 'backup-restore': {
        const artifact = state.backups.find((item) => item.id === id);
        if (!artifact || !current) break;
        current.state = 'off'; pushAudit('RestoreCompleted', current.name); notify('Restore completed', `${artifact.id} restored to ${current.name}.`, 'positive');
        return saveAndRender(`Restore ${artifact.id} completed; a pre-restore backup was recorded.`);
      }
      case 'backup-delete':
        state.backups = state.backups.filter((item) => item.id !== id); pushAudit('BackupDeleted', current?.name || 'Manager');
        return saveAndRender('Backup artifact deleted after retention checks.');
      case 'eula-accept':
        return dialogForm('Accept Minecraft EULA', `<p>By continuing, you confirm that the operator has reviewed and accepted the Minecraft EULA for this world.</p><label class="theme-switch"><input type="checkbox" name="accepted" required> I have read and accept the EULA</label>`, 'Accept EULA', ({ accepted }) => { if (!current || accepted !== 'on') return; current.eula = 'Accepted'; pushAudit('EulaAccepted', current.name); saveAndRender('EULA acceptance recorded.'); });
      case 'manager-backup': {
        const backup = addBackup(null, 'manager_config');
        return saveAndRender(`Manager backup ${backup.id} completed.`);
      }
      case 'manager-restore':
        pushAudit('ManagerRestoreCompleted', 'Manager'); return saveAndRender('Manager settings restored from the selected snapshot.');
      case 'manager-restart':
        pushAudit('ManagerRestarted', 'Manager'); return saveAndRender('Manager restart simulated; managed worlds remain available.');
      case 'manager-update':
        return dialogForm('Manager Update', `<p>Prototype update channel: stable. Current version: 0.4.0-prototype.</p>${selectField('Available release', 'release', [['0.4.1-prototype', '0.4.1 prototype']])}`, 'Stage Update', () => { pushAudit('ManagerUpdateStaged', 'Manager'); saveAndRender('Update staged. Production signature verification is not simulated.'); });
      case 'manager-rollback':
        pushAudit('ManagerRollbackCompleted', 'Manager'); return saveAndRender('Manager rollback simulated to 0.3.8-prototype.');
      case 'schedule-toggle': {
        const item = state.schedules.find((entry) => entry.id === id); if (item) item.enabled = !item.enabled;
        return saveAndRender('Schedule status updated.');
      }
      case 'schedule-delete':
        state.schedules = state.schedules.filter((item) => item.id !== id); return saveAndRender('Schedule soft-deleted.');
      case 'missed-resolve': case 'missed-ignore': {
        const item = state.missedRuns.find((entry) => entry.id === id); if (item) item.resolution = action === 'missed-resolve' ? 'Resolved' : 'Ignored';
        pushAudit(action === 'missed-resolve' ? 'MissedRunResolved' : 'MissedRunIgnored'); return saveAndRender('Missed run updated.');
      }
      case 'notification-read': case 'notification-dismiss': {
        const item = state.notifications.find((entry) => entry.id === id); if (item) item.read = true;
        return saveAndRender(action === 'notification-read' ? 'Notification marked read.' : 'Notification dismissed.');
      }
      case 'sync-retry': {
        const item = state.syncRecords.find((entry) => entry.id === id);
        if (item) { item.status = 'Succeeded'; item.attempts += 1; item.time = nowText(); }
        pushAudit('SyncRetryCompleted'); return saveAndRender('Sync retry completed.');
      }
      case 'sync-edit':
        return dialogForm('Edit Sync Target', `${field('Target name', 'name', state.syncTargets.find((item) => item.id === id)?.name || '')}`, 'Save Target', ({ name }) => { const item = state.syncTargets.find((entry) => entry.id === id); if (item && name) item.name = name; saveAndRender('Sync target updated.'); });
      case 'sync-delete':
        state.syncTargets = state.syncTargets.filter((item) => item.id !== id); return saveAndRender('Sync target soft-deleted.');
      case 'device-revoke': {
        const item = state.devices.find((entry) => entry.id === id); if (item) item.status = 'Revoked';
        pushAudit('DeviceRevoked'); return saveAndRender('Device revoked.');
      }
      case 'user-toggle': {
        const item = state.users.find((entry) => entry.id === id); if (item) item.status = item.status === 'Active' ? 'Disabled' : 'Active';
        pushAudit('UserStatusChanged'); return saveAndRender('User status updated.');
      }
      case 'user-delete':
        state.users = state.users.filter((item) => item.id !== id); pushAudit('UserSoftDeleted'); return saveAndRender('User soft-deleted.');
      case 'user-role': {
        const item = state.users.find((entry) => entry.id === id); if (!item) break;
        return dialogForm('Change User Role', selectField('Role', 'role', [['Client', 'Client'], ['Admin', 'Admin'], ['Superadmin', 'Superadmin']], item.role), 'Save Role', ({ role }) => { item.role = role; pushAudit('UserRoleChanged'); saveAndRender('Role assignment updated.'); });
      }
      case 'template-delete':
        state.templates = state.templates.filter((item) => item.id !== id); return saveAndRender('Template deprecated.');
      case 'template-edit': {
        const item = state.templates.find((entry) => entry.id === id); if (!item) break;
        return dialogForm('Edit Template', field('Template name', 'name', item.name), 'Save Template', ({ name }) => { item.name = name.trim() || item.name; pushAudit('TemplateUpdated'); saveAndRender('Template updated.'); });
      }
      case 'runtime-verify': {
        const item = state.runtimes.find((entry) => entry.id === id); if (item) item.status = 'Verified';
        return saveAndRender('Java runtime verified.');
      }
      case 'runtime-deprecate':
        state.runtimes = state.runtimes.filter((item) => item.id !== id); return saveAndRender('Java runtime deprecated.');
      case 'cleanup-execute':
        if (state.cleanupPreview) { pushAudit('CleanupExecuted'); state.cleanupPreview = null; return saveAndRender('Cleanup executed for the reviewed preview.'); }
        break;
      case 'setup-scan':
        return saveAndRender('World scan complete. 4 managed worlds are registered.');
      case 'refresh':
        return saveAndRender('View refreshed.');
      case 'notifications':
        return dialogForm('Notifications', notificationRows(state.notifications), 'Mark All Read', () => { state.notifications.forEach((item) => { item.read = true; }); saveAndRender('All notifications marked read.'); }, 'blue');
      case 'open-doc':
        state.feedback = `Opened ${id}.`; return saveAndRender(state.feedback);
      case 'open-log': case 'download-log':
        return saveAndRender(`${id} opened in the prototype log viewer.`);
      case 'logs-refresh':
        return saveAndRender('Log tail refreshed.');
      case 'backup-attempts':
        return saveAndRender(`Retry history expanded for ${id}.`);
      case 'file-open':
        state.filePath = [state.filePath, id].filter(Boolean).join('/'); return saveAndRender(`Opened /${state.filePath}.`);
      case 'file-download':
        return saveAndRender(`${id} prepared for download.`);
      case 'file-delete':
        return dialogForm('Delete File', `<p>Delete ${esc(id)} from this world?</p>`, 'Delete', () => saveAndRender(`${id} deleted.`), 'red');
      case 'file-rename': case 'file-move': case 'file-copy':
        return dialogForm(action === 'file-rename' ? 'Rename File' : action === 'file-move' ? 'Move File' : 'Copy File', field('New path or name', 'value', id), 'Continue', () => saveAndRender(`${id} ${action.replace('file-', '')} simulated.`));
      case 'file-mkdir':
        return dialogForm('Create Folder', field('Folder name', 'name', '', 'text', true), 'Create Folder', ({ name }) => { (state.files[filePathKey(state.selectedWorld, state.filePath || '')] ||= []).push({ name, type: 'Directory', size: '—', updated: nowText() }); saveAndRender(`Folder ${name} created.`); }, 'teal');
      case 'file-upload':
        return dialogForm('Upload File', field('File name', 'name', '', 'text', true), 'Upload', ({ name }) => { (state.files[filePathKey(state.selectedWorld, state.filePath || '')] ||= []).push({ name, type: 'File', size: '0 B', updated: nowText() }); saveAndRender(`${name} uploaded.`); });
      case 'world-retention-override':
        return dialogForm('World Retention Override', `${field('Minimum age (days)', 'age', 3, 'number')}${field('Keep newest per category', 'count', 3, 'number')}`, 'Save Override', () => saveAndRender('World retention override saved.'));
      case 'world-cleanup-preview':
        state.cleanupPreview = { id: makeId('preview'), worldId: id, count: 1 }; return saveAndRender('Backup cleanup dry run completed.');
      case 'go-page':
        return navigate(id);
      case 'scroll-to':
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); return;
      case 'audit-detail':
        return dialogForm('Audit Record', `<pre class="code-output">${esc(JSON.stringify(state.audit.find((item) => item.id === id) || {}, null, 2))}</pre>`, 'Close', () => {});
      default:
        return;
    }
    persist();
    renderPage();
  }

  function formsSubmit(form, data) {
    switch (form.dataset.form) {
      case 'create-world': {
        const template = state.templates.find((item) => item.id === data.template);
        const item = { id: makeId('world').toLowerCase(), name: data.name.trim(), type: template?.type || 'Vanilla', version: template?.version || '1.21.1', state: 'off', port: Number(data.port), size: '0 B', players: 0, lastStarted: 'Never', eula: 'Required', rcon: false, serverAddress: data.address || data.port };
        state.worlds.push(item); state.selectedWorld = item.id; state.context = 'world'; state.logs[item.id] = [`[Manager] ${item.name} created from ${template?.name || 'template'}.`];
        pushAudit('WorldCreated', item.name); state.page = 'world-main'; return saveAndRender(`${item.name} created.`);
      }
      case 'create-schedule':
        state.schedules.push({ id: makeId('sch'), name: data.name, scope: data.scope, cadence: data.cadence, enabled: true }); pushAudit('ScheduleCreated'); return saveAndRender('Schedule created.');
      case 'settings':
        state.settings = { ...state.settings, timezone: data.timezone, idleCountdown: Number(data.idleCountdown), worldRoot: data.worldRoot, backupRoot: data.backupRoot, logRoot: data.logRoot, notificationSounds: data.notificationSounds === 'on' }; pushAudit('ManagerSettingsUpdated'); return saveAndRender('Manager settings saved.');
      case 'create-user':
        state.users.push({ id: makeId('usr').toLowerCase(), username: data.username, name: data.name, role: data.role, status: 'Active', lastAccess: 'Never' }); pushAudit('UserCreated'); return saveAndRender('User created.');
      case 'create-template':
        state.templates.push({ id: makeId('tpl').toLowerCase(), name: data.name, type: data.type, version: data.version, runtime: data.runtime, worlds: 0 }); pushAudit('TemplateCreated'); return saveAndRender('Template created.');
      case 'create-sync':
        state.syncTargets.push({ id: makeId('sync').toLowerCase(), name: data.name, type: data.type, scope: data.scope, status: 'Enabled' }); pushAudit('SyncTargetCreated'); return saveAndRender('Sync target saved.');
      case 'cleanup-policy':
        if (data.scope !== 'backups') return saveAndRender('Stale-world and log cleanup remain disabled pending explicit policy approval.');
        state.cleanupPreview = { id: makeId('preview'), worldId: null, count: 2 }; return saveAndRender('Dry run complete. 2 protected backup candidates were evaluated; no files deleted.');
      case 'audit-filter':
        state.auditFilter = data.search || ''; return saveAndRender('Audit filter applied.');
      case 'file-open-path':
        state.filePath = data.path || ''; return saveAndRender(`Opened /${state.filePath}.`);
      case 'properties': {
        const current = world(); if (!current) break;
        const entries = Object.entries(data).filter(([key]) => key.startsWith('prop:'));
        const errors = entries.filter(([key, value]) => key.slice(5) === 'server-port' && !/^\d+$/.test(value));
        if (errors.length) return saveAndRender('Validation failed: server-port must be an integer.');
        current.properties = Object.fromEntries(entries.map(([key, value]) => [key.slice(5), value]));
        current.port = Number(current.properties['server-port'] || current.port); pushAudit('ServerPropertiesUpdated', current.name); return saveAndRender('Server properties validated and saved.');
      }
      case '':
        break;
      default:
        break;
    }
    persist(); renderPage();
  }

  function clickHandler(event) {
    const navButton = event.target.closest && event.target.closest('[data-page]');
    if (navButton) {
      event.preventDefault();
      navigate(navButton.dataset.page);
      return;
    }
    const action = event.target.closest && event.target.closest('[data-action]');
    if (action && !action.disabled) {
      event.preventDefault();
      if (action.dataset.action === 'filter-worlds') {
        const value = document.querySelector('[name="worldSearch"]')?.value.toLowerCase() || '';
        const stateFilter = document.querySelector('[name="worldState"]')?.value || 'all';
        const typeFilter = document.querySelector('[name="worldType"]')?.value || 'all';
        const versionFilter = document.querySelector('[name="worldVersion"]')?.value || 'all';
        const filtered = state.worlds.filter((item) => item.name.toLowerCase().includes(value) && (stateFilter === 'all' || item.state === stateFilter) && (typeFilter === 'all' || item.type === typeFilter) && (versionFilter === 'all' || item.version === versionFilter));
        const results = document.getElementById('worldResults'); if (results) results.innerHTML = worldRows(filtered);
        return;
      }
      runAction(action.dataset.action, action.dataset.id || '');
    }
  }

  document.addEventListener('click', clickHandler);
  document.getElementById('contextSelect').addEventListener('change', (event) => {
    state.context = event.target.value === 'manager' ? 'manager' : 'world';
    if (state.context === 'world') { state.selectedWorld = event.target.value; navigate('world-main'); }
    else navigate('home');
  });
  document.getElementById('themeToggle').addEventListener('change', (event) => {
    state.theme = event.target.checked ? 'dark' : 'light'; persist(); renderNav();
  });
  document.getElementById('navToggle').addEventListener('click', (event) => {
    const open = document.body.classList.toggle('nav-open');
    event.currentTarget.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('submit', (event) => {
    const form = event.target.closest && event.target.closest('form[data-form]');
    if (!form) return;
    event.preventDefault();
    formsSubmit(form, Object.fromEntries(new FormData(form).entries()));
  });
  document.addEventListener('popstate', (event) => {
    const next = event.state?.page || location.hash.replace(/^#\//, '') || 'home';
    state.page = PAGE_INFO[next] ? next : 'home'; persist(); renderPage();
  });

  renderPage();
})();
