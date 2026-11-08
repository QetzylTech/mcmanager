(function () {
  const CHANNEL_NAME = 'mcmanager_stream_channel';
  const HEARTBEAT_MS = 3000;
  const LEADER_TIMEOUT_MS = 7000;
  const KNOWN_EVENTS = [
    'snapshot',
    'snapshot.world',
    'world.state',
    'world.metrics',
    'operation.created',
    'operation.progress',
    'operation.status',
    'operation.terminal',
    'notification',
    'notification.created',
    'system.stats',
    'backup.progress',
    'restore.progress',
    'sync.status',
    'log.line',
    'log.gap',
    'log.replay',
    'metrics',
    'alert',
    'queue.position',
    'missed_run',
    'manager.shutdown',
    'stream.error',
  ];

  class StreamClientManager {
    constructor() {
      this.tabId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      this.peers = new Map([[this.tabId, Date.now()]]);
      this.leaderId = null;
      this.isLeader = false;
      this.eventSource = null;
      this.heartbeatTimer = null;
      this.monitorTimer = null;
      this.electionTimer = null;
      this.closed = false;
      this.authExpired = false;
      this.logCursors = new Map();
      this.logWorlds = new Set();
      this.logEventSources = new Map();

      try {
        this.channel = typeof BroadcastChannel === 'function'
          ? new BroadcastChannel(CHANNEL_NAME)
          : null;
      } catch (_error) {
        this.channel = null;
      }

      if (this.channel) {
        this.channel.onmessage = (event) => this.onChannelMessage(event.data || {});
        this.channel.postMessage({ type: 'HELLO', tabId: this.tabId });
        this.electionTimer = setTimeout(() => this.elect(), 120);
        this.monitorTimer = setInterval(() => this.monitorLeader(), 1000);
      } else {
        this.becomeLeader();
      }

      if (window.addEventListener) {
        for (const eventName of ['pagehide', 'beforeunload', 'unload']) {
          window.addEventListener(eventName, () => this.shutdown());
        }
      }
    }

    onChannelMessage(message) {
      if (!message || message.tabId === this.tabId) return;
      const now = Date.now();
      if (message.type === 'HELLO' || message.type === 'HEARTBEAT') {
        this.peers.set(message.tabId, now);
        if (message.type === 'HEARTBEAT') {
          if (this.isLeader && message.tabId < this.tabId) this.resign();
          if (!this.leaderId || message.tabId < this.leaderId || this.isLeader) {
            this.leaderId = message.tabId;
          }
        }
      } else if (message.type === 'LEADER_LEAVE') {
        this.peers.delete(message.tabId);
        if (this.leaderId === message.tabId) {
          this.leaderId = null;
        }
        this.scheduleElection();
      } else if (message.type === 'AUTH_RESUMED') {
        this.authExpired = false;
        this.peers.set(message.tabId, now);
        if (this.isLeader && this.tabId < message.tabId) {
          this.leaderId = this.tabId;
        } else {
          this.leaderId = message.tabId;
          this.resign();
        }
      } else if (message.type === 'STREAM_EVENT') {
        this.dispatchLocal(message.payload);
        if (message.payload?.topic === 'manager.shutdown') {
          this.shutdown();
          return;
        }
        if (
          message.payload?.topic === 'stream.error'
          && message.payload?.data?.code === 'AUTH_SESSION_EXPIRED'
        ) {
          this.authExpired = true;
          this.resign();
          this.closeWorldLogEventSources();
        }
      }
    }

    elect() {
      if (this.closed || this.authExpired || !this.channel) return;
      const now = Date.now();
      for (const [peerId, lastSeen] of this.peers) {
        if (now - lastSeen > LEADER_TIMEOUT_MS) this.peers.delete(peerId);
      }

      if (this.leaderId && this.peers.has(this.leaderId) && this.leaderId !== this.tabId) {
        return;
      }

      const candidates = [...this.peers.keys(), this.tabId].sort();
      if (candidates[0] === this.tabId) {
        this.becomeLeader();
      } else {
        this.leaderId = candidates[0];
      }
    }

    scheduleElection() {
      if (this.electionTimer !== null) clearTimeout(this.electionTimer);
      this.electionTimer = setTimeout(() => this.elect(), 80 + Math.random() * 100);
    }

    monitorLeader() {
      if (this.closed || this.authExpired || this.isLeader) return;
      const now = Date.now();
      for (const [peerId, lastSeen] of this.peers) {
        if (now - lastSeen > LEADER_TIMEOUT_MS) this.peers.delete(peerId);
      }
      if (!this.leaderId || !this.peers.has(this.leaderId)) this.scheduleElection();
    }

    becomeLeader() {
      if (this.closed || this.authExpired || this.isLeader) return;
      this.isLeader = true;
      this.leaderId = this.tabId;
      this.openEventSource();
      this.sendHeartbeat();
      this.heartbeatTimer = setInterval(() => this.sendHeartbeat(), HEARTBEAT_MS);
    }

    sendHeartbeat() {
      if (this.channel && this.isLeader) {
        this.channel.postMessage({ type: 'HEARTBEAT', tabId: this.tabId });
      }
    }

    openEventSource() {
      if (typeof EventSource !== 'function') return;
      this.eventSource = new EventSource('/stream/events');
      this.eventSource.onmessage = (event) => this.handleStreamEvent('message', event);
      if (this.eventSource.addEventListener) {
        for (const eventName of KNOWN_EVENTS) {
          this.eventSource.addEventListener(
            eventName,
            (event) => this.handleStreamEvent(eventName, event),
          );
        }
      }
    }

    handleStreamEvent(topic, event, broadcast = true) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (_error) {
        data = event.data;
      }
      const payload = { topic, data, id: event.lastEventId || null };
      this.dispatchLocal(payload);
      if (topic === 'stream.error' && data && data.code === 'AUTH_SESSION_EXPIRED') {
        this.authExpired = true;
        this.resign();
        this.closeWorldLogEventSources();
      }
      if (broadcast && this.channel) {
        this.channel.postMessage({ type: 'STREAM_EVENT', tabId: this.tabId, payload });
      }
      if (topic === 'manager.shutdown') this.shutdown();
    }

    dispatchLocal(payload) {
      if (!payload || !window.dispatchEvent || typeof CustomEvent !== 'function') return;
      if (payload.topic === 'log.line' && payload.data?.world_id && payload.id) {
        this.logCursors.set(payload.data.world_id, payload.id);
      }
      window.dispatchEvent(new CustomEvent(`sse:${payload.topic}`, { detail: payload.data }));
      window.dispatchEvent(new CustomEvent('mcmanager:stream', { detail: payload }));
    }

    getLogCursor(worldId) {
      return this.logCursors.get(String(worldId)) || null;
    }

    openWorldLogStream(worldId) {
      const key = String(worldId);
      if (this.closed || typeof EventSource !== 'function') return null;
      this.logWorlds.add(key);
      if (this.logEventSources.has(key)) return this.logEventSources.get(key);
      const cursor = this.getLogCursor(key);
      const after = cursor ? `?after=${encodeURIComponent(cursor)}` : '';
      const source = new EventSource(
        `/stream/worlds/${encodeURIComponent(key)}/logs${after}`,
      );
      for (const eventName of ['log.line', 'log.gap', 'log.replay']) {
        source.addEventListener(
          eventName,
          (event) => this.handleStreamEvent(eventName, event, false),
        );
      }
      this.logEventSources.set(key, source);
      return source;
    }

    closeWorldLogStream(worldId) {
      const key = String(worldId);
      const source = this.logEventSources.get(key);
      if (!source) return;
      source.close();
      this.logEventSources.delete(key);
      this.logWorlds.delete(key);
    }

    closeWorldLogEventSources() {
      for (const source of this.logEventSources.values()) source.close();
      this.logEventSources.clear();
    }

    resign() {
      if (!this.isLeader) return;
      this.isLeader = false;
      if (this.eventSource) this.eventSource.close();
      this.eventSource = null;
      if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }

    resumeAfterAuthentication() {
      if (this.closed) return;
      this.authExpired = false;
      this.leaderId = this.tabId;
      if (this.channel) {
        this.peers.set(this.tabId, Date.now());
        this.channel.postMessage({ type: 'AUTH_RESUMED', tabId: this.tabId });
      }
      this.becomeLeader();
      for (const worldId of this.logWorlds) this.openWorldLogStream(worldId);
    }

    shutdown() {
      if (this.closed) return;
      if (this.channel && this.isLeader) {
        this.channel.postMessage({ type: 'LEADER_LEAVE', tabId: this.tabId });
      }
      this.resign();
      this.closed = true;
      this.closeWorldLogEventSources();
      this.logWorlds.clear();
      if (this.channel) this.channel.close();
      if (this.monitorTimer !== null) clearInterval(this.monitorTimer);
      if (this.electionTimer !== null) clearTimeout(this.electionTimer);
    }
  }

  window.mcmanagerStreamClient = new StreamClientManager();
})();
