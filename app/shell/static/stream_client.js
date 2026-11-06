(function () {
  const CHANNEL_NAME = 'mcmanager_stream_channel';
  const HEARTBEAT_MS = 3000;
  const LEADER_TIMEOUT_MS = 7000;
  const KNOWN_EVENTS = [
    'snapshot',
    'snapshot.world',
    'world.state',
    'operation.created',
    'operation.status',
    'operation.terminal',
    'restore.progress',
    'log.line',
    'metrics',
    'notification.created',
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
      } else if (message.type === 'STREAM_EVENT') {
        this.dispatchLocal(message.payload);
      }
    }

    elect() {
      if (this.closed || !this.channel) return;
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
      if (this.closed || this.isLeader) return;
      const now = Date.now();
      for (const [peerId, lastSeen] of this.peers) {
        if (now - lastSeen > LEADER_TIMEOUT_MS) this.peers.delete(peerId);
      }
      if (!this.leaderId || !this.peers.has(this.leaderId)) this.scheduleElection();
    }

    becomeLeader() {
      if (this.closed || this.isLeader) return;
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

    handleStreamEvent(topic, event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (_error) {
        data = event.data;
      }
      const payload = { topic, data, id: event.lastEventId || null };
      this.dispatchLocal(payload);
      if (this.channel) {
        this.channel.postMessage({ type: 'STREAM_EVENT', tabId: this.tabId, payload });
      }
    }

    dispatchLocal(payload) {
      if (!payload || !window.dispatchEvent || typeof CustomEvent !== 'function') return;
      window.dispatchEvent(new CustomEvent(`sse:${payload.topic}`, { detail: payload.data }));
      window.dispatchEvent(new CustomEvent('mcmanager:stream', { detail: payload }));
    }

    resign() {
      if (!this.isLeader) return;
      this.isLeader = false;
      if (this.eventSource) this.eventSource.close();
      this.eventSource = null;
      if (this.heartbeatTimer !== null) clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }

    shutdown() {
      if (this.closed) return;
      if (this.channel && this.isLeader) {
        this.channel.postMessage({ type: 'LEADER_LEAVE', tabId: this.tabId });
      }
      this.resign();
      this.closed = true;
      if (this.channel) this.channel.close();
      if (this.monitorTimer !== null) clearInterval(this.monitorTimer);
      if (this.electionTimer !== null) clearTimeout(this.electionTimer);
    }
  }

  window.mcmanagerStreamClient = new StreamClientManager();
})();
