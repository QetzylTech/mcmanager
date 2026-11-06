const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const projectRoot = path.resolve(__dirname, '..', '..');
const app = path.join(projectRoot, 'app');
const shellScriptPath = path.join(app, 'shell', 'static', 'shell.js');
const shellTemplatePath = path.join(app, 'shell', 'templates', 'shell.html');
const streamClientPath = path.join(app, 'shell', 'static', 'stream_client.js');
const pageRoutesPath = path.join(app, 'shell', 'routes.py');

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function pageSlugs() {
  const source = fs.readFileSync(pageRoutesPath, 'utf8');
  return [...source.matchAll(/PageModule\('([^']+)'/g)].map((match) => match[1]);
}

test('shell navigates all 17 modules without a document reload', async () => {
  const template = fs.readFileSync(shellTemplatePath, 'utf8');
  const source = fs.readFileSync(shellScriptPath, 'utf8');
  const slugs = pageSlugs();
  assert.equal(slugs.length, 17);
  assert.match(template, /data-page="\{\{ page\.slug \}\}"/);

  const requests = [];
  const reloads = [];
  const historyEntries = [];
  const root = { innerHTML: '' };
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
          target: { closest: () => this },
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
  const fetch = async (url) => {
    requests.push(url);
    const slug = url.split('/').pop();
    return {
      async json() {
        return {
          ok: true,
          data: { sections: [{ title: slug, summary: `page ${slug}` }] },
        };
      },
    };
  };
  vm.runInNewContext(source, { document, window, history, fetch });
  await flush();
  requests.length = 0;

  const intercepted = [];
  for (const anchor of anchors) {
    intercepted.push(await anchor.click());
    await flush();
  }

  assert.ok(intercepted.every(Boolean), 'every navigation should be intercepted');
  assert.equal(requests.length, 17);
  assert.deepEqual(
    requests.map((url) => url.split('/').pop()),
    slugs,
  );
  assert.equal(historyEntries.length, 17);
  assert.deepEqual(reloads, []);
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
      FakeEventSource.instances.push(this);
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
    const window = {
      addEventListener(type, handler) {
        const current = listeners.get(type) || [];
        current.push(handler);
        listeners.set(type, current);
      },
      dispatchEvent() {},
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
});
