const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const projectRoot = path.resolve(__dirname, '..', '..');
const app = path.join(projectRoot, 'app');
const shellScriptPath = path.join(app, 'shell', 'static', 'shell.js');
const operatorUiScriptPath = path.join(app, 'shell', 'static', 'operator_ui.js');
const shellTemplatePath = path.join(app, 'shell', 'templates', 'shell.html');
const shellCssPath = path.join(app, 'shell', 'static', 'shell.css');
const streamClientPath = path.join(app, 'shell', 'static', 'stream_client.js');
const pageRoutesPath = path.join(app, 'shell', 'routes.py');

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function pageSlugs() {
  const source = fs.readFileSync(pageRoutesPath, 'utf8');
  return [...source.matchAll(/PageModule\('([^']+)'/g)].map((match) => match[1]);
}

test('operator UI navigates all 17 modules without a document reload', async () => {
  const template = fs.readFileSync(shellTemplatePath, 'utf8');
  const source = fs.readFileSync(operatorUiScriptPath, 'utf8');
  const slugs = pageSlugs();
  assert.match(template, /operator_ui\.js/);
  assert.equal(slugs.length, 17);

  const requests = [];
  const reloads = [];
  const historyEntries = [];
  const documentListeners = new Map();
  const root = { innerHTML: '', addEventListener() {} };
  const main = { dataset: { activePage: 'home' } };
  const anchors = slugs.map((slug) => ({
    dataset: { page: slug },
    href: `/pages/${slug}`,
    classList: { toggle() {} },
  }));
  const contextSelect = { addEventListener() {} };
  const document = {
    cookie: 'csrf_token=csrf-test-token',
    body: { dataset: {} },
    querySelector(selector) {
      if (selector === '[data-page-root]') return root;
      if (selector === 'main') return main;
      if (selector === 'h1') return { textContent: '' };
      if (selector === '[data-context-select]') return contextSelect;
      if (selector === '[data-refresh]' || selector === '[data-logout]') {
        return { addEventListener() {} };
      }
      return null;
    },
    querySelectorAll(selector) {
      return selector === 'a[data-page]' ? anchors : [];
    },
    addEventListener(type, handler) {
      documentListeners.set(type, handler);
    },
  };
  const history = {
    pushState(_state, _title, url) {
      historyEntries.push(url);
    },
  };
  const window = {
    location: {
      search: '',
      reload() {
        reloads.push(true);
      },
    },
    addEventListener() {},
  };
  const genericData = {
    worlds: [], templates: [], java_runtimes: [], schedules: [], settings: {}, version: 1,
    cleanup_runs: [], missed_runs: [], notifications: [], unread_count: 0, audit: [],
    sync_targets: [], sync_records: [], manager: {}, backups: [], restores: [], health: {},
    worlds_count: 0, active_worlds: 0,
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    let data = genericData;
    if (url === '/api/session') data = { user_id: 'u_admin' };
    else if (url.startsWith('/api/worlds?')) data = { worlds: [] };
    else if (url.startsWith('/api/pages/')) data = { title: url.split('/').pop() };
    return {
      ok: true,
      async json() {
        return { ok: true, data, meta: { unread_count: 0, pagination: { total: 0 } } };
      },
    };
  };
  vm.runInNewContext(source, {
    document,
    window,
    history,
    fetch,
    URLSearchParams,
    setInterval: () => 1,
    clearInterval() {},
  });
  await flush();
  await flush();
  requests.length = 0;

  const clickHandler = documentListeners.get('click');
  const intercepted = [];
  for (const anchor of anchors) {
    let prevented = false;
    await clickHandler({
      target: {
        closest(selector) {
          return selector === 'a[data-page]' ? anchor : null;
        },
      },
      preventDefault() {
        prevented = true;
      },
    });
    intercepted.push(prevented);
    await flush();
  }

  const pageRequests = requests.filter(({ url }) => url.startsWith('/api/pages/'));
  assert.ok(intercepted.every(Boolean));
  assert.deepEqual(pageRequests.map(({ url }) => url.split('/').pop()), slugs);
  assert.equal(historyEntries.length, 17);
  assert.deepEqual(reloads, []);
  assert.doesNotMatch(root.innerHTML, /error-surface/);
});

test('legacy shell.js prototype intercepts navigation without a reload', async () => {
  const template = fs.readFileSync(shellTemplatePath, 'utf8');
  const source = fs.readFileSync(shellScriptPath, 'utf8');
  const slugs = pageSlugs();
  assert.equal(slugs.length, 17);
  assert.match(template, /data-page="\{\{ page\.slug \}\}"/);

  const requests = [];
  const actionRequests = [];
  const reloads = [];
  const historyEntries = [];
  let worldListState = 'off';
  const root = { innerHTML: '', addEventListener() {} };
  const main = { dataset: { activePage: 'home' } };
  const refresh = { addEventListener() {} };
  const anchors = slugs.map((slug) => {
    const listeners = new Map();
    return {
      dataset: { page: slug },
      href: `/pages/${slug}`,
      addEventListener(type, handler) {
        listeners.set(type, handler);
      },
      async click() {
        let prevented = false;
        const event = {
          target: { closest: (selector) => selector === 'a[data-page]' ? this : null },
          preventDefault() {
            prevented = true;
          },
        };
        for (const handler of listeners.values()) await handler(event);
        for (const handler of documentListeners.get('click') || []) await handler(event);
        return prevented;
      },
    };
  });
  const documentListeners = new Map();
  const document = {
    cookie: 'csrf_token=csrf-test-token',
    querySelector(selector) {
      if (selector === '[data-page-root]') return root;
      if (selector === 'main') return main;
      if (selector === '[data-refresh]') return refresh;
      return null;
    },
    querySelectorAll(selector) {
      return selector === 'a[data-page]' ? anchors : [];
    },
    addEventListener(type, handler) {
      const current = documentListeners.get(type) || [];
      current.push(handler);
      documentListeners.set(type, current);
    },
  };
  const window = {
    location: {
      reload() {
        reloads.push(true);
      },
    },
  };
  const history = {
    pushState(_state, _title, url) {
      historyEntries.push(url);
    },
  };
  const fetch = async (url, options = {}) => {
    requests.push(url);
    if (url === '/api/session') {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { user_id: 'u_admin' } };
        },
      };
    }
    if (options.method === 'POST') {
      actionRequests.push({ url, options });
      if (url.endsWith('/start')) worldListState = 'running';
      if (url.endsWith('/stop')) worldListState = 'off';
      return {
        ok: true,
        async json() {
          return { ok: true, data: { operation: { op_id: 'op_accepted' } } };
        },
      };
    }
    if (url.startsWith('/api/worlds?')) {
      return {
        ok: true,
        async json() {
          return {
            ok: true,
            data: {
              worlds: [{
                world_id: 'world_survival',
                display_name: 'Survival',
                server_type: 'vanilla',
                mc_version: '1.21',
                state: worldListState,
                port: 25565,
              }],
            },
            meta: { pagination: { limit: 50, offset: 0, total: 1 } },
          };
        },
      };
    }
    const slug = url.split('/').pop();
    return {
      ok: true,
      async json() {
        return {
          ok: true,
          data: { sections: [{ title: slug, summary: `page ${slug}` }] },
        };
      },
    };
  };
  vm.runInNewContext(source, { document, window, history, fetch, URLSearchParams });
  await flush();
  requests.length = 0;

  const intercepted = [];
  for (const anchor of anchors) {
    intercepted.push(await anchor.click());
    await flush();
    if (anchor.dataset.page === 'worlds') {
      assert.match(root.innerHTML, /Survival/);
      assert.match(root.innerHTML, /25565/);
      assert.match(root.innerHTML, /data-world-action="start"/);
      assert.match(root.innerHTML, /data-world-action="backup"/);
    }
  }

  const clickHandler = documentListeners.get('click')[0];
  const clickWorldAction = async (action) => {
    const button = {
      dataset: { worldAction: action, worldId: 'world_survival' },
    };
    await clickHandler({
      target: {
        closest(selector) {
          return selector === '[data-world-action]' ? button : null;
        },
      },
      preventDefault() {},
    });
  };
  await clickWorldAction('backup');
  await clickWorldAction('start');
  assert.match(root.innerHTML, /data-world-action="stop"/);
  await clickWorldAction('stop');

  assert.ok(intercepted.every(Boolean), 'every navigation should be intercepted');
  assert.equal(requests.filter((url) => url.startsWith('/api/pages/')).length, 17);
  assert.deepEqual(
    requests.filter((url) => url.startsWith('/api/pages/')).map((url) => url.split('/').pop()),
    slugs,
  );
  assert.ok(requests.includes('/api/worlds?limit=50&offset=0'));
  assert.equal(historyEntries.length, 17);
  assert.deepEqual(reloads, []);
  assert.equal(actionRequests.length, 3);
  assert.equal(actionRequests[0].url, '/api/worlds/world_survival/backup');
  assert.deepEqual(JSON.parse(actionRequests[0].options.body), { category: 'manual' });
  assert.equal(actionRequests[1].url, '/api/worlds/world_survival/start');
  assert.equal(actionRequests[2].url, '/api/worlds/world_survival/stop');
  assert.equal(actionRequests[0].options.headers['X-CSRF-Token'], 'csrf-test-token');
  assert.match(actionRequests[0].options.headers['Idempotency-Key'], /^shell-/);
  assert.match(root.innerHTML, /Stop request accepted/);
});

test('operator UI submits setup and login through session-bound CSRF', async () => {
  const source = fs.readFileSync(operatorUiScriptPath, 'utf8');
  const requests = [];
  const documentListeners = new Map();
  const rootListeners = new Map();
  const root = {
    innerHTML: '',
    addEventListener(type, handler) {
      rootListeners.set(type, handler);
    },
  };
  const main = { dataset: { activePage: 'home' } };
  const heading = { textContent: '' };
  const body = { dataset: {} };
  const document = {
    body,
    cookie: 'csrf_token=preauth-token',
    querySelector(selector) {
      if (selector === '[data-page-root]') return root;
      if (selector === 'main') return main;
      if (selector === 'h1') return heading;
      if (selector === '[data-context-select]') return { addEventListener() {} };
      if (selector === '[data-refresh]' || selector === '[data-logout]') {
        return { addEventListener() {} };
      }
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener(type, handler) {
      documentListeners.set(type, handler);
    },
  };
  const window = { addEventListener() {}, location: { search: '' } };
  const history = { pushState() {} };
  let authenticated = false;
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === '/api/session') {
      return {
        ok: authenticated,
        async json() {
          return authenticated
            ? { ok: true, data: { user_id: 'u_admin' } }
            : { ok: false, error: { code: 'AUTH_SESSION_INVALID' } };
        },
      };
    }
    if (url === '/api/setup') {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { first_superadmin_required: true } };
        },
      };
    }
    if (options.method === 'POST') {
      if (url === '/api/auth/login') authenticated = true;
      return {
        ok: true,
        async json() {
          return { ok: true, data: { setup_completed: true } };
        },
      };
    }
    if (url.startsWith('/api/worlds?')) {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { worlds: [] }, meta: { pagination: { total: 0 } } };
        },
      };
    }
    if (url.startsWith('/api/pages/')) {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { title: 'Home' } };
        },
      };
    }
    if (url === '/api/system/stats') {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { worlds_count: 0, active_worlds: 0 } };
        },
      };
    }
    if (url.startsWith('/api/notifications')) {
      return {
        ok: true,
        async json() {
          return { ok: true, data: { notifications: [] }, meta: { unread_count: 0 } };
        },
      };
    }
    return {
      ok: true,
      async json() {
        return { ok: true, data: {} };
      },
    };
  };
  class FakeFormData {
    constructor(form) {
      this.values = form.values;
    }

    get(key) {
      return this.values[key];
    }

    entries() {
      return Object.entries(this.values)[Symbol.iterator]();
    }
  }

  vm.runInNewContext(source, {
    document,
    window,
    history,
    fetch,
    URLSearchParams,
    FormData: FakeFormData,
  });
  await flush();
  await flush();
  assert.match(root.innerHTML, /Create the first administrator/);
  assert.equal(body.dataset.authState, 'signed-out');

  const submitHandler = rootListeners.get('submit');
  const submit = async (mode) => {
    const form = {
      dataset: { authAction: mode },
      values: { username: 'admin', password: 'a-strong-password' },
      matches(selector) {
        return selector === '[data-auth-form]';
      },
    };
    await submitHandler({
      target: {
        closest(selector) {
          return selector === 'form' || selector === '[data-auth-form]' ? form : null;
        },
      },
      preventDefault() {},
    });
  };
  await submit('setup');
  assert.match(root.innerHTML, /Administrator created/);
  await submit('login');

  assert.equal(body.dataset.authState, 'authenticated');
  assert.match(root.innerHTML, /World operations/);
  assert.equal(main.dataset.activePage, 'home');
  assert.deepEqual(
    requests.filter(({ options }) => options.method === 'POST').map(({ url }) => url),
    ['/api/setup', '/api/auth/login'],
  );
  for (const { options } of requests.filter(({ options }) => options.method === 'POST')) {
    assert.equal(options.headers['X-CSRF-Token'], 'preauth-token');
  }
  assert.equal(documentListeners.has('click'), true);
});

test('Manager Maintenance queues backup through the loaded operator UI', async () => {
  const template = fs.readFileSync(shellTemplatePath, 'utf8');
  const source = fs.readFileSync(operatorUiScriptPath, 'utf8');
  assert.match(template, /operator_ui\.js/);
  const requests = [];
  const listeners = new Map();
  const rootListeners = new Map();
  const root = {
    innerHTML: '',
    addEventListener(type, handler) {
      rootListeners.set(type, handler);
    },
  };
  const main = { dataset: { activePage: 'manager-maintenance' } };
  const heading = { textContent: '' };
  const contextSelect = {
    addEventListener() {},
  };
  const refresh = { addEventListener() {} };
  const logout = { addEventListener() {} };
  const document = {
    cookie: 'csrf_token=csrf-manager',
    body: { dataset: {} },
    querySelector(selector) {
      if (selector === '[data-page-root]') return root;
      if (selector === 'main') return main;
      if (selector === 'h1') return heading;
      if (selector === '[data-context-select]') return contextSelect;
      if (selector === '[data-refresh]') return refresh;
      if (selector === '[data-logout]') return logout;
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener(type, handler) {
      listeners.set(type, handler);
    },
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    let data = {};
    if (url === '/api/session') data = { user_id: 'u_admin' };
    else if (url.startsWith('/api/worlds?')) data = { worlds: [] };
    else if (url === '/api/pages/manager-maintenance') data = { title: 'Manager Maintenance' };
    else if (url === '/api/manager') data = { state: 'ready' };
    else if (url.startsWith('/api/backups?world_id=null')) data = { backups: [] };
    else if (options.method === 'POST') data = { operation: { op_id: 'op_manager_backup', status: 'Queued' } };
    return {
      ok: true,
      async json() {
        return { ok: true, data, meta: { pagination: { total: 0 } } };
      },
    };
  };
  vm.runInNewContext(source, {
    document,
    window: { addEventListener() {} },
    history: { pushState() {} },
    fetch,
    URLSearchParams,
    FormData,
    setInterval,
    clearInterval,
  });
  await flush();
  await flush();

  assert.match(root.innerHTML, /Create manager backup/);
  assert.doesNotMatch(root.innerHTML, /Backup.*NOT_IMPLEMENTED/);
  const clickHandler = listeners.get('click');
  const backupButton = {
    disabled: false,
    dataset: { uiAction: 'manager-backup', id: '' },
  };
  await clickHandler({
    target: {
      closest(selector) {
        return selector === '[data-ui-action]' ? backupButton : null;
      },
    },
    preventDefault() {},
  });

  const backupRequest = requests.find(({ url, options }) => (
    url === '/api/manager/backup' && options.method === 'POST'
  ));
  assert.ok(backupRequest);
  assert.equal(backupRequest.options.headers['X-CSRF-Token'], 'csrf-manager');
  assert.match(backupRequest.options.headers['Idempotency-Key'], /^shell-/);
});

test('shell uses tokenized colors, 40px controls, and no inline styles', () => {
  const template = fs.readFileSync(shellTemplatePath, 'utf8');
  const stylesheet = fs.readFileSync(shellCssPath, 'utf8');
  const componentStyles = stylesheet.replace(
    /:root\s*\{[^}]*\}|\[data-theme="dark"\]\s*\{[^}]*\}/gs,
    '',
  );

  assert.doesNotMatch(template, /\sstyle\s*=/i);
  assert.match(stylesheet, /\.ui-button\s*\{[^}]*height:\s*40px/s);
  assert.match(stylesheet, /\.ui-text-input\s*\{[^}]*height:\s*40px/s);
  assert.doesNotMatch(componentStyles, /#[\da-f]{3,8}\b|rgba?\(/i);
});

test('ten tabs share one hub connection and elect a replacement on leader close', async (t) => {
  assert.ok(fs.existsSync(streamClientPath), 'shell stream_client.js is required');
  assert.match(fs.readFileSync(shellTemplatePath, 'utf8'), /stream_client\.js/);
  const source = fs.readFileSync(streamClientPath, 'utf8');
  const buses = new Map();
  const tabs = [];
  let nextEventSourceId = 0;

  class FakeBroadcastChannel {
    constructor(name) {
      this.name = name;
      this.closed = false;
      const peers = buses.get(name) || new Set();
      peers.add(this);
      buses.set(name, peers);
      this.peers = peers;
    }

    postMessage(data) {
      for (const peer of this.peers) {
        if (peer !== this && !peer.closed && peer.onmessage) {
          setImmediate(() => peer.onmessage({ data }));
        }
      }
    }

    close() {
      this.closed = true;
      this.peers.delete(this);
    }
  }

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.id = ++nextEventSourceId;
      this.closed = false;
      this.listeners = new Map();
      FakeEventSource.instances.push(this);
    }

    addEventListener(type, handler) {
      const current = this.listeners.get(type) || [];
      current.push(handler);
      this.listeners.set(type, current);
    }

    emit(type, event) {
      for (const handler of this.listeners.get(type) || []) handler(event);
    }

    close() {
      this.closed = true;
    }
  }
  FakeEventSource.instances = [];

  function makeTab() {
    const listeners = new Map();
    const channels = [];
    const eventSources = [];
    const timerHandles = [];
    const dispatchedEvents = [];
    const window = {
      addEventListener(type, handler) {
        const current = listeners.get(type) || [];
        current.push(handler);
        listeners.set(type, current);
      },
      dispatchEvent(event) {
        dispatchedEvents.push(event);
      },
    };
    class TabBroadcastChannel extends FakeBroadcastChannel {
      constructor(name) {
        super(name);
        channels.push(this);
      }
    }
    class TabEventSource extends FakeEventSource {
      constructor(url) {
        super(url);
        eventSources.push(this);
      }
    }
    const context = vm.createContext({
      window,
      document: { querySelector() { return null; } },
      BroadcastChannel: TabBroadcastChannel,
      EventSource: TabEventSource,
      CustomEvent: class CustomEvent {
        constructor(type, options) {
          this.type = type;
          this.detail = options && options.detail;
        }
      },
      setInterval(callback, delay) {
        const timer = setInterval(callback, delay);
        timer.unref();
        timerHandles.push(timer);
        return timer;
      },
      clearInterval,
      setTimeout(callback, delay) {
        const timer = setTimeout(callback, delay);
        timer.unref();
        timerHandles.push(timer);
        return timer;
      },
      clearTimeout,
      console: { log() {}, warn() {}, error() {} },
    });
    vm.runInContext(source, context);
    const tab = {
      channels,
      eventSources,
      dispatchedEvents,
      client: window.mcmanagerStreamClient,
      close() {
        for (const type of ['pagehide', 'beforeunload', 'unload']) {
          for (const listener of listeners.get(type) || []) listener();
        }
        channels.forEach((channel) => channel.close());
        eventSources.forEach((eventSource) => eventSource.close());
        timerHandles.forEach((timer) => {
          clearInterval(timer);
          clearTimeout(timer);
        });
      },
    };
    tabs.push(tab);
    return tab;
  }

  t.after(() => tabs.forEach((tab) => tab.close()));

  for (let index = 0; index < 10; index += 1) makeTab();
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const activeSources = () => FakeEventSource.instances.filter((source) => !source.closed);
  assert.equal(activeSources().length, 1);
  assert.equal(activeSources()[0].url, '/stream/events');

  const leader = tabs.find((tab) => tab.eventSources.some((source) => !source.closed));
  leader.close();
  const deadline = Date.now() + 7000;
  while (activeSources().length === 0 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.equal(activeSources().length, 1);
  assert.notEqual(activeSources()[0].id, leader.eventSources[0].id);

  const replacementSource = activeSources()[0];
  const remainingTabs = tabs.filter((tab) => tab !== leader);
  const documentedTopics = [
    'world.state',
    'world.metrics',
    'operation.created',
    'operation.progress',
    'operation.terminal',
    'notification',
    'system.stats',
    'backup.progress',
    'restore.progress',
    'sync.status',
    'log.line',
    'log.gap',
    'log.replay',
    'alert',
    'queue.position',
    'missed_run',
  ];
  documentedTopics.forEach((topic, index) => {
    replacementSource.emit(topic, {
      data: JSON.stringify({ topic }),
      lastEventId: String(index + 1),
    });
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  for (const topic of documentedTopics) {
    assert.ok(remainingTabs.every((tab) => (
      tab.dispatchedEvents.some((event) => event.type === `sse:${topic}`)
    )), `${topic} should be delivered to every tab`);
  }

  replacementSource.emit('log.line', {
    data: JSON.stringify({ world_id: 'world_1', line: 'ready' }),
    lastEventId: 'rs_live:64',
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  const logClient = remainingTabs[0].client;
  assert.equal(logClient.getLogCursor('world_1'), 'rs_live:64');
  const logSource = logClient.openWorldLogStream('world_1');
  assert.equal(
    logSource.url,
    '/stream/worlds/world_1/logs?after=rs_live%3A64',
  );
  logSource.emit('log.gap', {
    data: JSON.stringify({ world_id: 'world_1', reason: 'cursor_unavailable' }),
    lastEventId: '',
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(remainingTabs[0].dispatchedEvents.some(
    (event) => event.type === 'sse:log.gap',
  ));
  logClient.closeWorldLogStream('world_1');

  replacementSource.emit('stream.error', {
    data: JSON.stringify({ code: 'AUTH_SESSION_EXPIRED' }),
    lastEventId: '2',
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(activeSources().length, 0);
  assert.ok(remainingTabs.every((tab) => (
    tab.dispatchedEvents.some((event) => event.type === 'sse:stream.error')
  )));

  remainingTabs[0].client.resumeAfterAuthentication();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(activeSources().length, 1);
  assert.ok(remainingTabs.every((tab) => !tab.client.authExpired));

  activeSources()[0].emit('manager.shutdown', {
    data: '{}',
    lastEventId: '3',
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(activeSources().length, 0);
  assert.ok(remainingTabs.every((tab) => (
    tab.dispatchedEvents.some((event) => event.type === 'sse:manager.shutdown')
  )));
});
