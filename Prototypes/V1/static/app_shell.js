(function () {
  "use strict";

  var routes = {
    manager_home: {
      title: "Home",
      fragment: "fragments/manager_home_fragment.html",
      styles: ["../static/server_management.css"]
    },
    servers: {
      title: "Server Selection",
      fragment: "fragments/worlds_fragment.html",
      styles: ["../static/server_management.css"]
    },
    create_server: {
      title: "Create Server",
      fragment: "fragments/world_create_fragment.html",
      styles: ["../static/server_management.css", "../static/panel_settings.css"]
    },
    home: {
      title: "Minecraft Control",
      fragment: "fragments/home_fragment.html",
      styles: ["../static/dashboard_home.css"]
    },
    backups: {
      title: "Backup & Restore",
      fragment: "fragments/files_fragment.html",
      styles: ["../static/file_browser.css"]
    },
    minecraft_logs: {
      title: "Log Files",
      fragment: "fragments/files_fragment.html",
      styles: ["../static/file_browser.css"]
    },
    maintenance: {
      title: "Cleanup",
      fragment: "fragments/maintenance_fragment.html",
      styles: ["../static/file_browser.css", "../static/maintenance_page.css"]
    },
    panel_settings: {
      title: "Panel Settings",
      fragment: "fragments/panel_settings_fragment.html",
      styles: ["../static/panel_settings.css"]
    },
    readme: {
      title: "Instructions",
      fragment: "fragments/documentation_fragment.html",
      styles: ["../static/file_browser.css", "../static/documentation.css"]
    }
  };

  var app = {
    data: JSON.parse(JSON.stringify(window.MCWEBPrototypeData || {})),
    currentPage: "manager_home",
    selectedServerId: null,
    currentFilesContext: "backups",
    currentHomeLogSource: "minecraft",
    currentLogFileSource: "minecraft",
    backupFilters: new Set(["manual", "auto", "session", "prerestore", "others"]),
    backupSort: "newest",
    fileSort: "newest",
    selectedFileId: null,
    restoreFileId: null,
    maintenanceScope: "backups",
    maintenanceView: "rules",
    maintenanceHistoryView: "success",
    maintenanceSelected: new Set(),
    currentRoot: null,
    pendingStartTimer: null,
    pendingStopTimer: null,
    pendingBackupTimer: null,
    pendingRestoreTimer: null
  };

  var content = document.querySelector(".mcweb-app-content[data-current-page]");
  var nav = document.querySelector(".sidebar");
  var navToggle = document.querySelector(".js-nav-toggle");
  var navBackdrop = document.querySelector(".js-nav-backdrop");
  var themeToggle = document.querySelector(".js-theme-toggle");
  var dynamicStyleNodes = [];

  initShell();

  function initShell() {
    initializeServerSelection();
    wireShellEvents();
    showBanner();
    setInterval(tickRuntime, 1000);
    navigate(resolveInitialPage(), false);
  }

  function wireShellEvents() {
    document.addEventListener("click", function (event) {
      var navLink = event.target.closest(".js-nav-link");
      if (!navLink || navLink.tagName !== "A") return;
      event.preventDefault();
      var href = navLink.getAttribute("href") || "";
      var key = href.replace(/^#/, "");
      if (!routes[key]) key = "manager_home";
      navigate(key, true);
    });

    if (themeToggle) {
      themeToggle.addEventListener("click", function () {
        var dark = !document.documentElement.classList.contains("theme-dark");
        document.documentElement.classList.toggle("theme-dark", dark);
        try {
          localStorage.setItem("mcweb-theme", dark ? "dark" : "light");
        } catch (_err) {}
      });
    }

    if (navToggle) {
      navToggle.addEventListener("click", function () {
        toggleNav();
      });
    }

    if (navBackdrop) {
      navBackdrop.addEventListener("click", closeNav);
    }

    window.addEventListener("hashchange", function () {
      navigate(resolveInitialPage(), false);
    });
  }

  function showBanner() {
    var banner = document.getElementById("mcweb-offline-banner");
    if (!banner) return;
    banner.classList.add("active");
  }

  function resolveInitialPage() {
    var key = (window.location.hash || "#manager_home").replace(/^#/, "");
    return routes[key] ? key : "manager_home";
  }

  function navigate(page, pushHash) {
    if (!routes[page]) page = "manager_home";
    app.currentPage = page;
    app.currentFilesContext = page === "minecraft_logs" ? "minecraft_logs" : "backups";
    updateNav(page);
    closeNav();

    if (pushHash && window.location.hash !== "#" + page) {
      window.location.hash = page;
      return;
    }

    applyPageStyles(routes[page].styles || []);
    loadFragment(routes[page].fragment, function (html) {
      if (!content) return;
      content.innerHTML = html;
      content.setAttribute("data-current-page", page);
      document.body.dataset.page = page;
      document.title = routes[page].title + " - MC Manager Prototype";
      initializePage(page);
    });
    if (!routes[page]) page = "manager_home";
    app.currentPage = page;
    app.currentFilesContext = page === "minecraft_logs" ? "minecraft_logs" : "backups";
    updateNav(page);
    closeNav();
    if (pushHash && window.location.hash !== "#" + page) {
      window.location.hash = page;
      return;
    }
    applyPageStyles(routes[page].styles || []);
    loadFragment(routes[page].fragment, function (html) {
      content.innerHTML = html;
      content.dataset.currentPage = page;
      document.body.dataset.page = page;
      document.title = routes[page].title + " - MC Manager Prototype";
      initializePage(page);
    });
  }

  function applyPageStyles(stylePaths) {
    dynamicStyleNodes.forEach(function (node) {
      if (node && node.parentNode) node.parentNode.removeChild(node);
    });
    dynamicStyleNodes = [];
    stylePaths.forEach(function (href) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.setAttribute("data-prototype-page-style", "1");
      document.head.appendChild(link);
      dynamicStyleNodes.push(link);
    });
  }

  function loadFragment(path, onSuccess) {
    fetch(path)
      .then(function (response) {
        if (!response.ok) throw new Error("Fragment request failed");
        return response.text();
      })
      .then(onSuccess)
      .catch(function () {
        content.innerHTML = "<main class='content'><div class='wrap'><section class='panel pane-primary'><div class='pane-head'><div class='pane-head-row'><h1 class='pane-title'>Prototype Load Error</h1></div></div><div class='pane-content' style='padding:12px;'>Serve the repository over a local static server so fragment fetching works, then reload this page.</div></section></div></main>";
      });
  }

  function initializePage(page) {
    if (page === "manager_home") initManagerHomePage();
    if (page === "servers") initServerSelectionPage();
    if (page === "create_server") initCreateServerPage();
    if (page === "home") initHomePage();
    if (page === "backups" || page === "minecraft_logs") initFilesPage();
    if (page === "maintenance") initMaintenancePage();
    if (page === "panel_settings") initSettingsPage();
    if (page === "readme") initDocsPage();
  }

  function updateNav(page) {
    Array.prototype.forEach.call(document.querySelectorAll(".js-nav-link.nav-link"), function (link) {
      var href = link.getAttribute("href") || "";
      var key = href.replace(/^#/, "");
      link.classList.toggle("active", key === page);
      if (link.hasAttribute("aria-current")) link.removeAttribute("aria-current");
      if (key === page) link.setAttribute("aria-current", "page");
    });
  }

  function toggleNav() {
    if (!nav || !navBackdrop) return;
    var open = !nav.classList.contains("open");
    nav.classList.toggle("open", open);
    navBackdrop.classList.toggle("open", open);
    navToggle.classList.toggle("nav-open", open);
  }

  function closeNav() {
    if (!nav || !navBackdrop || !navToggle) return;
    nav.classList.remove("open");
    navBackdrop.classList.remove("open");
    navToggle.classList.remove("nav-open");
  }

  function initializeServerSelection() {
    if (!Array.isArray(app.data.servers) || !app.data.servers.length) return;
    app.selectedServerId = app.data.servers[0].id;
    applySelectedServer(app.selectedServerId);
  }

  function getSelectedServer() {
    if (!Array.isArray(app.data.servers)) return null;
    return app.data.servers.find(function (server) {
      return server.id === app.selectedServerId;
    }) || null;
  }

  function applySelectedServer(serverId) {
    var server = Array.isArray(app.data.servers)
      ? app.data.servers.find(function (item) { return item.id === serverId; })
      : null;
    if (!server) return;
    app.selectedServerId = server.id;
    app.data.runtime = server.runtime;
    app.data.logs = server.logs;
    app.data.backups = server.backups;
    app.data.logFiles = server.logFiles;
    app.data.maintenance = server.maintenance;
  }

  function selectedServerLabel() {
    var server = getSelectedServer();
    if (!server) return "Current Server";
    return server.name;
  }

  function tickRuntime() {
    var runtime = app.data.runtime;
    runtime.cpuPerCore = runtime.cpuPerCore.map(function (value) {
      var next = value + Math.floor(Math.random() * 7) - 3;
      return Math.max(1, Math.min(97, next));
    });
    if (runtime.serviceRunning) {
      runtime.playersOnline = Math.max(0, Math.min(7, runtime.playersOnline + (Math.random() > 0.82 ? 1 : (Math.random() < 0.18 ? -1 : 0))));
      runtime.tickRate = (18.5 + Math.random() * 1.5).toFixed(2) + " TPS";
      runtime.ramUsage = (2.1 + Math.random() * 0.7).toFixed(1) + " GB / 16 GB";
      runtime.cpuFrequency = (4 + Math.random() * 0.4).toFixed(1) + " GHz";
      runtime.storageUsage = "61% used, " + (728 + Math.floor(Math.random() * 8)) + " GB free";
      if (runtime.playersOnline === 0 && runtime.idleCountdownSeconds > 0) {
        runtime.idleCountdownSeconds -= 1;
      } else {
        runtime.idleCountdownSeconds = 180;
      }
      if (Math.random() > 0.7) {
        pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: autosave heartbeat tick");
      }
    } else {
      runtime.playersOnline = 0;
      runtime.tickRate = "--";
      runtime.idleCountdownSeconds = 180;
    }
    syncSelectedServerSummary();
    if (app.currentPage === "manager_home") renderManagerHomePage();
    if (app.currentPage === "servers") renderServerSelectionPage();
    if (app.currentPage === "home") renderHome();
  }

  function initManagerHomePage() {
    var openSelection = document.querySelector(".js-manager-home-open-selection");
    if (openSelection) openSelection.addEventListener("click", function () { navigate("servers", true); });

    var openCreate = document.querySelector(".js-manager-home-open-create");
    if (openCreate) openCreate.addEventListener("click", function () { navigate("create_server", true); });

    var openConsole = document.querySelector(".js-manager-home-open-console");
    if (openConsole) openConsole.addEventListener("click", function () { navigate("home", true); });

    renderManagerHomePage();
  }

  function renderManagerHomePage() {
    var selected = getSelectedServer();
    var servers = app.data.servers || [];
    var running = servers.filter(function (server) {
      return server.runtime && server.runtime.serviceRunning;
    }).length;

    if (selected) {
      setTextBySelector(".js-manager-current-name", selected.name);
      setTextBySelector(
        ".js-manager-current-meta",
        selected.serverType + " " + selected.version + " • " + selected.address + ":" + selected.port
      );
      setTextBySelector(".js-manager-current-status", selected.runtime.serverStatus);
      setTextBySelector(".js-manager-current-players", String(selected.runtime.playersOnline));
      setTextBySelector(".js-manager-next-backup-summary", selected.runtime.nextBackupTime);
    }

    setTextBySelector(".js-manager-total-servers", String(servers.length));
    setTextBySelector(".js-manager-running-servers", String(running));
    setTextBySelector(
      ".js-manager-storage-summary",
      app.data.managerOverview ? app.data.managerOverview.storageSummary : app.data.runtime.storageUsage
    );

    var serverList = document.querySelector(".js-manager-server-list");
    if (serverList) {
      serverList.innerHTML = servers.map(function (server) {
        return renderServerCard(server, true);
      }).join("");
      wireServerCardActions(serverList);
    }

    var alertList = document.querySelector(".js-manager-alert-list");
    if (alertList) {
      var notes = app.data.managerAlerts || [];
      alertList.innerHTML = notes.map(function (note) {
        return "<div class='manager-alert-card'><h3>" + escapeHtml(note.title) + "</h3><p>" + escapeHtml(note.message) + "</p></div>";
      }).join("");
    }
  }

  function initServerSelectionPage() {
    var openCreate = document.querySelector(".js-world-open-create");
    if (openCreate) openCreate.addEventListener("click", function () { navigate("create_server", true); });
    renderServerSelectionPage();
  }

  function renderServerSelectionPage() {
    var selected = getSelectedServer();

    var current = document.querySelector(".js-world-current-selection");
    if (current) {
      current.textContent = selected
        ? "Current selection: " + selected.name + " (" + selected.address + ":" + selected.port + ")"
        : "No server selected";
    }

    var list = document.querySelector(".js-world-list");
    if (!list) return;

    list.innerHTML = (app.data.servers || []).map(function (server) {
      return renderServerCard(server, false);
    }).join("");

    wireServerCardActions(list);
  }

  function initCreateServerPage() {
    populateCreateServerSelects();

    var backBtn = document.querySelector(".js-create-back-to-selection");
    if (backBtn) backBtn.addEventListener("click", function () { navigate("servers", true); });

    var onAnyChange = function () { renderCreateServerPreview(); };

    var template = document.querySelector(".js-create-template");
    if (template) template.addEventListener("change", onAnyChange);

    var runtime = document.querySelector(".js-create-runtime");
    if (runtime) runtime.addEventListener("change", onAnyChange);

    var host = document.querySelector(".js-create-host");
    if (host) host.addEventListener("change", onAnyChange);

    [
      ".js-create-name",
      ".js-create-id",
      ".js-create-port",
      ".js-create-path",
      ".js-create-address",
      ".js-create-args"
    ].forEach(function (sel) {
      var node = document.querySelector(sel);
      if (node) node.addEventListener("input", onAnyChange);
    });

    var form = document.querySelector(".js-server-create-form");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        createServerFromForm();
      });
    }

    renderCreateServerPreview();
  }

  function populateCreateServerSelects() {
    populateOptionsBySelector(".js-create-template", app.data.serverTemplates || []);
    populateOptionsBySelector(".js-create-runtime", app.data.javaRuntimes || []);
    populateOptionsBySelector(".js-create-host", app.data.hosts || []);
  }

  function populateOptionsBySelector(selector, items) {
    var node = document.querySelector(selector);
    if (!node) return;

    node.innerHTML = items.map(function (item) {
      return "<option value='" + escapeAttr(item.id) + "'>" + escapeHtml(item.name) + "</option>";
    }).join("");
  }

  function valueOfBySelector(selector) {
    var node = document.querySelector(selector);
    return node ? node.value : "";
  }

  function renderCreateServerPreview() {
    var preview = document.querySelector(".js-create-preview");
    if (!preview) return;

    var templateId = valueOfBySelector(".js-create-template");
    var runtimeId = valueOfBySelector(".js-create-runtime");
    var hostId = valueOfBySelector(".js-create-host");

    var template = findById(app.data.serverTemplates, templateId);
    var runtime = findById(app.data.javaRuntimes, runtimeId);
    var host = findById(app.data.hosts, hostId);

    preview.innerHTML =
      "<h3>" + escapeHtml(valueOfBySelector(".js-create-name")) + "</h3>" +
      "<p>Machine ID: " + escapeHtml(valueOfBySelector(".js-create-id")) + "</p>" +
      "<p>Template: " + escapeHtml(template ? template.name : "-") + "</p>" +
      "<p>Java runtime: " + escapeHtml(runtime ? runtime.name : "-") + "</p>" +
      "<p>Host: " + escapeHtml(host ? host.name : "-") + "</p>" +
      "<p>Address: " + escapeHtml(valueOfBySelector(".js-create-address")) + ":" + escapeHtml(valueOfBySelector(".js-create-port")) + "</p>" +
      "<p>Path: " + escapeHtml(valueOfBySelector(".js-create-path")) + "</p>" +
      "<p>Args: " + escapeHtml(valueOfBySelector(".js-create-args")) + "</p>";
  }

  function createServerFromForm() {
    var templateId = valueOfBySelector(".js-create-template");
    var runtimeId = valueOfBySelector(".js-create-runtime");
    var hostId = valueOfBySelector(".js-create-host");

    var template = findById(app.data.serverTemplates, templateId);
    var runtime = findById(app.data.javaRuntimes, runtimeId);
    var host = findById(app.data.hosts, hostId);

    var name = valueOfBySelector(".js-create-name");

    var server = {
      id: valueOfBySelector(".js-create-id"),
      name: name,
      summary: "Prototype-created server ready for the existing console pages.",
      serverType: template ? template.serverType : "Vanilla",
      version: template ? template.version : "1.21.1",
      address: valueOfBySelector(".js-create-address"),
      port: valueOfBySelector(".js-create-port"),
      host: host ? host.name : "storage-node",
      runtimeLabel: runtime ? runtime.name : "Default Java",
      runtime: {
        serverStatus: "Off",
        playersOnline: 0,
        tickRate: "--",
        backupStatus: "Idle",
        serviceRunning: false,
        sessionStartedAt: null,
        idleCountdownSeconds: 180,
        lastBackupTime: "Not yet created",
        nextBackupTime: "After first start",
        cpuPerCore: [4, 8, 5, 11],
        ramUsage: "0.0 GB / 8 GB",
        cpuFrequency: "4.2 GHz",
        storageUsage: "New world path reserved"
      },
      logs: {
        minecraft: ["[21:00:00] [Server thread/INFO]: Prototype server created but not started yet."],
        backup: ["[21:00:00] backup workflow not yet run"],
        mcweb: ["[21:00:00] create server action completed in prototype mode"],
        mcweb_log: ["[21:00:00] no warnings recorded"],
        restore: ["[21:00:00] no restore history yet"]
      },
      backups: [],
      logFiles: {
        minecraft: [],
        crash: [],
        backup: [],
        restore: [],
        mcweb: [],
        mcweb_log: []
      },
      maintenance: {
        backups: {
          storageRemaining: "732 GB free",
          backupSummary: "0 archives",
          staleSummary: "0 stale worlds",
          lastRun: "Not run yet",
          lastChangedBy: "prototype operator",
          scheduleCount: 1,
          nextRun: "After first backup",
          missedRuns: 0,
          rules: [
            "Keep latest 5 manual backups",
            "Create a pre-restore backup before restore"
          ],
          candidates: [],
          history: {
            success: [],
            missed: []
          }
        },
        stale_worlds: {
          storageRemaining: "732 GB free",
          backupSummary: "0 archives",
          staleSummary: "0 stale worlds",
          lastRun: "Not run yet",
          lastChangedBy: "prototype operator",
          scheduleCount: 0,
          nextRun: "Not scheduled",
          missedRuns: 0,
          rules: [
            "No stale world rules configured yet"
          ],
          candidates: [],
          history: {
            success: [],
            missed: []
          }
        }
      }
    };

    app.data.servers.push(server);
    applySelectedServer(server.id);

    var status = document.querySelector(".js-create-status");
    if (status) status.textContent = name + " created in prototype mode and set as the active server.";

    renderCreateServerPreview();
  }

  function renderServerCard(server, includeConsoleButton) {
    var selectedClass = server.id === app.selectedServerId ? " selected" : "";
    var consoleButton = includeConsoleButton
      ? "<button class='btn-backup' type='button' data-server-open='" + server.id + "'>Open Console</button>"
      : "<button class='btn-start' type='button' data-server-open='" + server.id + "'>Open Console</button>";
    return "<div class='server-card" + selectedClass + "'>" +
      "<div class='server-card-head'><div><h3 class='server-card-title'>" + escapeHtml(server.name) + "</h3><p class='server-card-copy'>" + escapeHtml(server.summary) + "</p></div><span class='server-status-pill " + escapeAttr(statusClass(server.runtime.serverStatus)) + "'>" + escapeHtml(server.runtime.serverStatus) + "</span></div>" +
      "<p class='server-card-meta'>" + escapeHtml(server.serverType + " " + server.version + " • " + server.address + ":" + server.port + " • " + server.host) + "</p>" +
      "<div class='server-card-actions'><button class='btn-backup' type='button' data-server-select='" + server.id + "'>Select</button>" + consoleButton + "</div>" +
      "</div>";
  }

  function wireServerCardActions(root) {
    Array.prototype.forEach.call(root.querySelectorAll("[data-server-select]"), function (button) {
      button.onclick = function () {
        applySelectedServer(button.getAttribute("data-server-select"));
        syncSelectedServerSummary();
        renderManagerHomePage();
        renderServerSelectionPage();
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll("[data-server-open]"), function (button) {
      button.onclick = function () {
        applySelectedServer(button.getAttribute("data-server-open"));
        syncSelectedServerSummary();
        navigate("home", true);
      };
    });
  }

  function syncSelectedServerSummary() {
    var title = document.getElementById("control-panel-title");
    var server = getSelectedServer();
    if (title && server) {
      title.textContent = server.name + " Control Panel";
    }
  }

  function initHomePage() {
    syncSelectedServerSummary();

    var startBtn = document.querySelector(".js-action-start");
    if (startBtn) startBtn.addEventListener("click", startServer);

    var stopBtn = document.querySelector(".js-action-stop");
    if (stopBtn) stopBtn.addEventListener("click", stopServer);

    var backupBtn = document.querySelector(".js-action-backup");
    if (backupBtn) backupBtn.addEventListener("click", triggerBackup);

    var rconForm = document.querySelector(".js-rcon-wrap form");
    if (rconForm) {
      rconForm.addEventListener("submit", submitRcon);
    }

    var logSource = document.querySelector(".js-log-source");
    if (logSource) {
      logSource.value = app.currentHomeLogSource;
      logSource.addEventListener("change", function () {
        app.currentHomeLogSource = logSource.value;
        renderHomeLog();
      });
    }

    renderHome();
  }

  function setTextBySelector(selector, value) {
    var node = document.querySelector(selector);
    if (node) node.textContent = value;
  }

  function renderHome() {
    var runtime = app.data.runtime;
    syncSelectedServerSummary();

    setTextBySelector(".js-server-time", new Date().toLocaleString());
    setTextBySelector(".js-ram-usage", runtime.ramUsage);
    setTextBySelector(".js-cpu-per-core", runtime.cpuPerCore.map(function (value, index) {
      return "CPU" + index + " " + value + "%";
    }).join(" | "));
    setTextBySelector(".js-cpu-frequency", runtime.cpuFrequency);
    setTextBySelector(".js-storage-usage", runtime.storageUsage);

    setTextBySelector(".js-service-status", runtime.serverStatus);
    setTextBySelector(".js-players-online", String(runtime.playersOnline));
    setTextBySelector(".js-tick-rate", runtime.tickRate);
    setTextBySelector(".js-idle-countdown", formatDuration(runtime.idleCountdownSeconds));

    setTextBySelector(".js-backup-status", runtime.backupStatus);
    setTextBySelector(".js-last-backup-time", runtime.lastBackupTime);
    setTextBySelector(".js-next-backup-time", runtime.nextBackupTime);
    setTextBySelector(".js-backups-count", app.data.backups.length + " archives");

    var prefix = document.querySelector(".js-service-duration-prefix");
    var duration = document.querySelector(".js-session-duration");
    if (runtime.serviceRunning && runtime.sessionStartedAt) {
      if (prefix) prefix.textContent = " for ";
      if (duration) {
        duration.style.display = "";
        duration.textContent = formatUptime(runtime.sessionStartedAt);
      }
    } else {
      if (prefix) prefix.textContent = "";
      if (duration) duration.style.display = "none";
    }

    var startBtn = document.querySelector(".js-action-start");
    var stopBtn = document.querySelector(".js-action-stop");
    var backupBtn = document.querySelector(".js-action-backup");
    var rconInput = document.querySelector(".js-rcon-command");
    var rconSubmit = document.querySelector(".js-rcon-submit");

    if (startBtn) startBtn.disabled = runtime.serverStatus !== "Off";
    if (stopBtn) stopBtn.disabled = !runtime.serviceRunning;
    if (backupBtn) backupBtn.disabled = runtime.backupStatus !== "Idle" || runtime.serverStatus === "Starting" || runtime.serverStatus === "Stopping";
    if (rconInput) rconInput.disabled = !runtime.serviceRunning;
    if (rconSubmit) rconSubmit.disabled = !runtime.serviceRunning;

    applyNavAttention();
    renderHomeLog();
  }

  function renderHomeLog() {
    var source = app.currentHomeLogSource;
    var lines = app.data.logs[source] || [];
    setTextBySelector(".js-live-log", lines.slice(-40).join("\n"));
  }

  function startServer() {
    var runtime = app.data.runtime;
    if (runtime.serverStatus !== "Off") return;
    runtime.serverStatus = "Queued";
    pushLog("mcweb", "[" + currentTime() + "] start requested by prototype operator");
    pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: queue accepted, preparing startup");
    renderHome();
    clearTimeout(app.pendingStartTimer);
    app.pendingStartTimer = setTimeout(function () {
      runtime.serverStatus = "Starting";
      pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: Loading libraries and world data");
      renderHome();
      app.pendingStartTimer = setTimeout(function () {
        runtime.serverStatus = "Running";
        runtime.serviceRunning = true;
        runtime.sessionStartedAt = Date.now();
        runtime.playersOnline = 2;
        pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: Done (4.821s)! For help, type \"help\"");
        pushLog("mcweb", "[" + currentTime() + "] observed running state from startup logs");
        renderHome();
      }, 2800);
    }, 900);
  }

  function stopServer() {
    var runtime = app.data.runtime;
    if (!runtime.serviceRunning) return;
    runtime.serverStatus = "Stopping";
    pushLog("mcweb", "[" + currentTime() + "] stop requested by prototype operator");
    pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: Stopping server");
    renderHome();
    clearTimeout(app.pendingStopTimer);
    app.pendingStopTimer = setTimeout(function () {
      runtime.serverStatus = "Off";
      runtime.serviceRunning = false;
      runtime.sessionStartedAt = null;
      runtime.playersOnline = 0;
      pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: Stopped cleanly");
      renderHome();
    }, 2200);
  }

  function triggerBackup() {
    var runtime = app.data.runtime;
    if (runtime.backupStatus !== "Idle") return;
    runtime.backupStatus = "Queued";
    pushLog("backup", "[" + currentTime() + "] backup queued");
    pushLog("mcweb", "[" + currentTime() + "] manual backup requested");
    renderHome();
    clearTimeout(app.pendingBackupTimer);
    app.pendingBackupTimer = setTimeout(function () {
      runtime.backupStatus = "Running";
      pushLog("backup", "[" + currentTime() + "] save-off issued");
      renderHome();
      app.pendingBackupTimer = setTimeout(function () {
        var stamp = new Date();
        var name = "world_" + stamp.getFullYear() + "-" + pad(stamp.getMonth() + 1) + "-" + pad(stamp.getDate()) + "_" + pad(stamp.getHours()) + "-" + pad(stamp.getMinutes()) + "_manual.zip";
        app.data.backups.unshift({
          id: "b" + Math.random().toString(16).slice(2, 8),
          type: "manual",
          name: name,
          modifiedText: stamp.toLocaleString(),
          sizeText: "2.3 GB",
          mtime: Math.floor(stamp.getTime() / 1000),
          preview: "Fresh manual backup created by the UI prototype.\nNo real archive exists."
        });
        runtime.backupStatus = "Idle";
        runtime.lastBackupTime = stamp.toLocaleString();
        runtime.nextBackupTime = new Date(stamp.getTime() + 45 * 60000).toLocaleString();
        pushLog("backup", "[" + currentTime() + "] backup completed successfully");
        renderHome();
      }, 2400);
    }, 900);
  }

  function submitRcon(event) {
    event.preventDefault();
    var input = document.getElementById("rcon-command");
    if (!input || !input.value.trim()) return;
    pushLog("mcweb", "[" + currentTime() + "] RCON command sent: " + input.value.trim());
    pushLog("minecraft", "[" + currentTime() + "] [Server thread/INFO]: Executed command: " + input.value.trim());
    input.value = "";
    renderHomeLog();
  }

  function initFilesPage() {
    var isBackups = app.currentPage === "backups";

    var backupControls = document.querySelector(".backup-controls");
    if (backupControls) backupControls.hidden = !isBackups;

    var logControls = document.querySelector(".log-view-controls");
    if (logControls) logControls.hidden = isBackups;

    if (isBackups) wireBackupControls();
    else wireLogControls();

    var closeBtn = document.querySelector(".js-file-close");
    if (closeBtn) closeBtn.addEventListener("click", closeViewer);

    var cancelRestore = document.querySelector(".js-backup-restore-cancel");
    if (cancelRestore) {
      cancelRestore.addEventListener("click", function () {
        app.restoreFileId = null;
        renderFileList();
        renderViewer();
      });
    }

    var startRestore = document.querySelector(".js-backup-restore-start");
    if (startRestore) startRestore.addEventListener("click", simulateRestore);

    var downloadBtn = document.querySelector(".js-file-download");
    // NOTE: keep behavior as prototype error
    if (downloadBtn) {
      downloadBtn.addEventListener("click", function () {
        showInlineError("Prototype only: no file is actually downloaded.");
      });
    }

    renderFileList();
    renderViewer();
  }

  function wireBackupControls() {
    Array.prototype.forEach.call(document.querySelectorAll(".js-backup-filter"), function (box) {
      box.checked = app.backupFilters.has(box.value);
      box.addEventListener("change", function () {
        if (box.checked) app.backupFilters.add(box.value);
        else app.backupFilters.delete(box.value);
        renderFileList();
      });
    });

    var sort = document.querySelector(".js-backup-sort");
    if (sort) {
      sort.value = app.backupSort;
      sort.addEventListener("change", function () {
        app.backupSort = sort.value;
        renderFileList();
      });
    }
  }

  function wireLogControls() {
    Array.prototype.forEach.call(document.querySelectorAll(".log-source-toggle"), function (button) {
      button.classList.toggle("active", button.dataset.logSource === app.currentLogFileSource);
      button.addEventListener("click", function () {
        app.currentLogFileSource = button.dataset.logSource;
        app.selectedFileId = null;
        renderFileList();
        renderViewer();
      });
    });

    var sort = document.querySelector(".js-log-sort");
    if (sort) {
      sort.value = app.fileSort;
      sort.addEventListener("change", function () {
        app.fileSort = sort.value;
        renderFileList();
      });
    }
  }

  function renderFileList() {
    var list = document.querySelector(".js-file-list");
    if (!list) return;

    var items = app.currentPage === "backups" ? getFilteredBackups() : getSortedLogFiles();
    if (!items.length) {
      list.innerHTML = "<li class='list-state empty'>No files match the current filters.</li>";
      return;
    }

    list.innerHTML = items.map(function (item) {
      var activeClass = item.id === app.selectedFileId ? " file-row-active file-row-active-view" : "";
      if (item.id === app.restoreFileId) activeClass += " file-row-active-restore";
      return "<li class='" + activeClass.trim() + "'>" +
        "<span class='file-name'>" + escapeHtml(item.name) + "</span>" +
        "<span class='meta'>" + escapeHtml(item.modifiedText) + " • " + escapeHtml(item.sizeText) + "</span>" +
        "<div class='file-actions'>" +
        "<button class='file-action-btn file-view-btn' data-action='view' data-id='" + item.id + "' type='button'>View</button>" +
        (app.currentPage === "backups"
          ? "<button class='file-action-btn file-download-btn' data-action='download' data-id='" + item.id + "' type='button'>Download</button><button class='file-action-btn file-restore-btn' data-action='restore' data-id='" + item.id + "' type='button'>Restore</button>"
          : "<button class='file-action-btn file-download-btn' data-action='download' data-id='" + item.id + "' type='button'>Download</button>") +
        "</div>" +
        "</li>";
    }).join("");

    Array.prototype.forEach.call(list.querySelectorAll("[data-action]"), function (button) {
      button.addEventListener("click", function () {
        var id = button.getAttribute("data-id");
        var action = button.getAttribute("data-action");

        app.selectedFileId = id;
        if (action === "view") app.restoreFileId = null;
        if (action === "restore") app.restoreFileId = id;
        if (action === "download") showInlineError("Prototype only: download is not wired.");

        renderFileList();
        renderViewer();
      });
    });
  }

  function renderViewer() {
    var wrap = document.querySelector(".page-panes--files");
    var viewer = document.querySelector(".file-viewer");
    var contentNode = document.querySelector(".js-viewer-content");
    var title = document.querySelector(".js-viewer-title");
    var restoreControls = document.querySelector(".js-backup-restore-controls");

    if (!wrap || !viewer || !contentNode || !title || !restoreControls) return;

    var item = findCurrentSelectedFile();
    var open = !!item;

    wrap.classList.toggle("viewer-open", open);
    viewer.setAttribute("aria-hidden", open ? "false" : "true");

    if (!open) {
      contentNode.textContent = "";
      return;
    }

    title.textContent = item.name;
    contentNode.textContent = item.preview || "No preview available.";
    restoreControls.hidden = !(app.currentPage === "backups" && item.id === app.restoreFileId);
  }

  function closeViewer() {
    app.selectedFileId = null;
    app.restoreFileId = null;
    renderFileList();
    renderViewer();
  }

  function simulateRestore() {
    var item = findCurrentSelectedFile();
    if (!item) return;
    var contentNode = document.getElementById("file-viewer-content");
    if (contentNode) {
      contentNode.textContent = "Restore starting for " + item.name + "...\nCreating pre-restore snapshot...\nExtracting archive...\nSwitching world binding...\nRestore completed in prototype mode.";
    }
    pushLog("restore", "[" + currentTime() + "] restore simulated for " + item.name);
    pushLog("mcweb", "[" + currentTime() + "] restore completed in prototype mode");
    app.restoreFileId = null;
    renderFileList();
  }

  function getFilteredBackups() {
    return app.data.backups
      .filter(function (item) { return app.backupFilters.has(item.type); })
      .sort(sortByMode(app.backupSort));
  }

  function getSortedLogFiles() {
    return (app.data.logFiles[app.currentLogFileSource] || []).slice().sort(sortByMode(app.fileSort));
  }

  function sortByMode(mode) {
    return function (a, b) {
      if (mode === "oldest") return a.mtime - b.mtime;
      if (mode === "size") return parseSize(b.sizeText) - parseSize(a.sizeText);
      if (mode === "alpha") return a.name.localeCompare(b.name);
      if (mode === "reverse_alpha") return b.name.localeCompare(a.name);
      return b.mtime - a.mtime;
    };
  }

  function parseSize(text) {
    var parts = String(text).match(/([\d.]+)/);
    if (!parts) return 0;
    return parseFloat(parts[1]);
  }

  function findCurrentSelectedFile() {
    if (!app.selectedFileId) return null;
    var items = app.currentPage === "backups" ? app.data.backups : (app.data.logFiles[app.currentLogFileSource] || []);
    return items.find(function (item) { return item.id === app.selectedFileId; }) || null;
  }

  function initMaintenancePage() {
    var scopeBackups = document.querySelector(".js-maint-scope-backups");
    if (scopeBackups) scopeBackups.addEventListener("click", function () {
      app.maintenanceScope = "backups";
      app.maintenanceSelected.clear();
      renderMaintenance();
    });

    var scopeStale = document.querySelector(".js-maint-scope-stale");
    if (scopeStale) scopeStale.addEventListener("click", function () {
      app.maintenanceScope = "stale_worlds";
      app.maintenanceSelected.clear();
      renderMaintenance();
    });

    var openRules = document.querySelector(".js-maint-open-rules");
    if (openRules) openRules.addEventListener("click", function () {
      app.maintenanceView = "rules";
      renderMaintenanceViews();
    });

    var openHistory = document.querySelector(".js-maint-open-history");
    if (openHistory) openHistory.addEventListener("click", function () {
      app.maintenanceView = "history";
      renderMaintenanceViews();
    });

    var openManual = document.querySelector(".js-maint-open-manual");
    if (openManual) openManual.addEventListener("click", function () {
      app.maintenanceView = "manual";
      renderMaintenanceViews();
    });

    var runRuleDelete = document.querySelector(".js-run-rule-delete-btn");
    if (runRuleDelete) runRuleDelete.addEventListener("click", openMaintenanceDryRun);

    var runManualDelete = document.querySelector(".js-run-manual-delete-btn");
    if (runManualDelete) runManualDelete.addEventListener("click", openMaintenanceDryRun);

    var ackMissed = document.querySelector(".js-ack-non-normal-btn");
    if (ackMissed) ackMissed.addEventListener("click", function () {
      var scope = app.data.maintenance[app.maintenanceScope];
      scope.missedRuns = Math.max(0, scope.missedRuns - 1);
      if (scope.history.missed.length) scope.history.missed.shift();
      renderMaintenance();
    });

    // Modals are currently not strict in the rebuilt fragment; keep old modal bindings if they exist.
    renderMaintenance();
  }

  function renderMaintenance() {
    var scope = app.data.maintenance[app.maintenanceScope];

    setTextBySelector(".js-maint-storage-remaining", scope.storageRemaining);
    setTextBySelector(".js-maint-backup-summary", scope.backupSummary);
    setTextBySelector(".js-maint-stale-summary", scope.staleSummary);

    setTextBySelector(".js-history-last-run", scope.lastRun);
    setTextBySelector(".js-history-last-changed-by", scope.lastChangedBy);

    setTextBySelector(".js-maint-schedule-count", String(scope.scheduleCount));
    setTextBySelector(".js-maint-next-run", scope.nextRun);
    setTextBySelector(".js-history-missed-runs", String(scope.missedRuns));

    setTextBySelector(".js-maint-action-description",
      app.maintenanceView === "rules"
        ? "Review rules for the selected cleanup scope."
        : app.maintenanceView === "manual"
          ? "Select individual files from the left pane for manual cleanup."
          : "Review historical cleanup runs and missed-run records."
    );

    renderMaintenanceFileList(scope);
    renderMaintenanceRules(scope);
    renderMaintenanceHistory(scope);
    renderMaintenanceViews();
  }

  function renderMaintenanceFileList(scope) {
    var list = document.querySelector(".js-cleanup-file-list");
    if (!list) return;

    list.innerHTML = scope.candidates.map(function (item) {
      var checked = app.maintenanceSelected.has(item.id) ? " checked" : "";
      return "<li>" +
        "<label class='maintenance-check'>" +
        "<input type='checkbox' data-cleanup-id='" + item.id + "'" + checked + "> " +
        "<span class='file-name'>" + escapeHtml(item.name) + "</span>" +
        "</label>" +
        "<span class='meta'>" + escapeHtml(item.detail) + "</span>" +
        "</li>";
    }).join("");

    Array.prototype.forEach.call(list.querySelectorAll("[data-cleanup-id]"), function (box) {
      box.addEventListener("change", function () {
        var id = box.getAttribute("data-cleanup-id");
        if (box.checked) app.maintenanceSelected.add(id);
        else app.maintenanceSelected.delete(id);
        updateMaintenanceSelectionCount(scope);
      });
    });

    updateMaintenanceSelectionCount(scope);
  }

  function updateMaintenanceSelectionCount(scope) {
    var node = document.querySelector(".js-maint-manual-selection-count");
    if (!node) return;
    var total = scope.candidates.length;
    var selected = app.maintenanceSelected.size;
    node.hidden = app.maintenanceView !== "manual";
    node.textContent = selected + "/" + total + " Files selected";
  }

  function renderMaintenanceRules(scope) {
    var container = document.querySelector("#rules-card-list");
    if (!container) return;
    container.innerHTML = "<div class='maintenance-card'><ul class='maintenance-rule-list'>" +
      scope.rules.map(function (rule) { return "<li>" + escapeHtml(rule) + "</li>"; }).join("") +
      "</ul></div>";
  }

  function renderMaintenanceHistory(scope) {
    var container = document.querySelector("#history-card-list");
    if (!container) return;

    var items = scope.history[app.maintenanceHistoryView];
    if (!items.length) {
      container.innerHTML = "<div class='history-card'><p class='history-card-meta'>No records in this view.</p></div>";
      return;
    }

    container.innerHTML = items.map(function (item) {
      return "<div class='history-card'><h3 class='history-card-title'>" + escapeHtml(item.title) + "</h3><p class='history-card-meta'>" + escapeHtml(item.meta) + "</p></div>";
    }).join("");
  }

  function renderMaintenanceViews() {
    var rulesView = document.querySelector(".js-maint-view-rules");
    if (rulesView) rulesView.hidden = app.maintenanceView !== "rules";

    var manualView = document.querySelector(".js-maint-view-manual");
    if (manualView) manualView.hidden = app.maintenanceView !== "manual";

    var historyView = document.querySelector(".js-maint-view-history");
    if (historyView) historyView.hidden = app.maintenanceView !== "history";

    var historyToggle = document.querySelector(".js-history-view-toggle");
    if (historyToggle) historyToggle.hidden = app.maintenanceView !== "history";

    updateMaintenanceSelectionCount(app.data.maintenance[app.maintenanceScope]);

    // History sub-filters
    var successBtn = document.querySelector(".js-history-show-success");
    if (successBtn) {
      successBtn.onclick = function () { app.maintenanceHistoryView = "success"; renderMaintenance(); };
      successBtn.classList.toggle("active", app.maintenanceHistoryView === "success");
    }

    var missedBtn = document.querySelector(".js-history-show-missed");
    if (missedBtn) {
      missedBtn.onclick = function () { app.maintenanceHistoryView = "missed"; renderMaintenance(); };
      missedBtn.classList.toggle("active", app.maintenanceHistoryView === "missed");
    }
  }

  function openMaintenanceDryRun() {
    var scope = app.data.maintenance[app.maintenanceScope];
    var selectedIds = app.maintenanceView === "manual" && app.maintenanceSelected.size
      ? scope.candidates.filter(function (item) { return app.maintenanceSelected.has(item.id); })
      : scope.candidates.slice(0, 2);
    setText("maintenance-dry-run-summary", selectedIds.length + " files would be deleted in this prototype preview.");
    setList("maintenance-dry-run-files", selectedIds.map(function (item) { return item.name; }));
    setList("maintenance-dry-run-issues", ["No conflicts detected in simulation mode."]);
    openModal("maintenance-dry-run-modal");
  }

  function openMaintenanceComplete() {
    var scope = app.data.maintenance[app.maintenanceScope];
    var selectedIds = app.maintenanceView === "manual" && app.maintenanceSelected.size
      ? scope.candidates.filter(function (item) { return app.maintenanceSelected.has(item.id); })
      : scope.candidates.slice(0, 2);
    setText("maintenance-complete-summary", selectedIds.length + " files deleted in the simulated run.");
    setList("maintenance-complete-files", selectedIds.map(function (item) { return item.name; }));
    setList("maintenance-complete-issues", ["Prototype only: no real files were deleted."]);
    openModal("maintenance-complete-modal");
  }

  function closeMaintenanceModals() {
    closeModal("maintenance-dry-run-modal");
    closeModal("maintenance-complete-modal");
  }

  function initSettingsPage() {
    var statusNode = document.querySelector(".js-panel-status");
    var setStatus = function (text) {
      if (statusNode) statusNode.textContent = text;
    };

    // Device map rendering (keeps prototype behavior)
    renderDeviceMap();

    var addRowBtn = document.querySelector(".js-panel-add-device-row");
    if (addRowBtn) {
      addRowBtn.addEventListener("click", function () {
        app.data.settings.deviceMachines.push({
          id: "d" + Math.random().toString(16).slice(2, 7),
          machine: "new-device",
          addresses: "100.64.0.xx",
          lastSeen: "Just now",
          owner: "Unassigned"
        });
        renderDeviceMap();
        setStatus("Added a new prototype row. This helps evaluate how row editing should work.");
      });
    }

    var wireButton = function (selector, text) {
      var btn = document.querySelector(selector);
      if (!btn) return;
      btn.addEventListener("click", function () {
        setStatus(text);
      });
    };

    wireButton(".js-panel-save-security", "Prototype action completed for save security.");
    wireButton(".js-panel-save-paths", "Prototype action completed for save paths.");
    wireButton(".js-panel-save-timezone", "Prototype action completed for save timezone.");
    wireButton(".js-panel-upload-device-csv", "Prototype action completed for upload device csv.");
    wireButton(".js-panel-refresh-states", "Prototype action completed for refresh all states.");
    wireButton(".js-panel-reboot-app", "Prototype action completed for reboot control panel.");
  }

  function renderDeviceMap() {
    var body = document.querySelector(".js-panel-device-map-body");
    if (!body) return;

    var statusNode = document.querySelector(".js-panel-status");

    body.innerHTML = app.data.settings.deviceMachines.map(function (item) {
      return "<div class='device-machine-row'>" +
        "<input class='ui-card-input' value='" + escapeAttr(item.machine) + "'>" +
        "<input class='ui-card-input' value='" + escapeAttr(item.addresses) + "'>" +
        "<input class='ui-card-input' value='" + escapeAttr(item.lastSeen) + "'>" +
        "<input class='ui-card-input' value='" + escapeAttr(item.owner) + "'>" +
        "<div class='device-machine-actions'><button class='btn-backup' type='button' data-device-save='" + item.id + "'>Save</button><button class='btn-stop' type='button' data-device-delete='" + item.id + "'>Delete</button></div>" +
        "</div>";
    }).join("");

    Array.prototype.forEach.call(body.querySelectorAll("[data-device-delete]"), function (button) {
      button.addEventListener("click", function () {
        var id = button.getAttribute("data-device-delete");
        app.data.settings.deviceMachines = app.data.settings.deviceMachines.filter(function (item) { return item.id !== id; });
        renderDeviceMap();
        if (statusNode) statusNode.textContent = "Deleted a prototype device row. This makes it easier to assess destructive UI affordances.";
      });
    });

    Array.prototype.forEach.call(body.querySelectorAll("[data-device-save]"), function (button) {
      button.addEventListener("click", function () {
        if (statusNode) statusNode.textContent = "Saved a prototype device row. Requirement question: should rows save inline or batch?";
      });
    });
  }

  function initDocsPage() {
    var article = document.querySelector(".js-doc-content");
    var toc = document.querySelector(".js-doc-toc-body");
    var stickyTitle = document.querySelector(".js-doc-sticky-title");
    var stickyMenu = document.querySelector(".js-doc-toc-toggle");
    var tocSidebar = document.querySelector(".toc-sidebar");

    if (!article || !toc) return;

    var headings = article.querySelectorAll("h1, h2, h3");
    toc.innerHTML = "";

    Array.prototype.forEach.call(headings, function (heading, index) {
      if (!heading.id) heading.id = "doc-heading-" + index;
      var link = document.createElement("a");
      link.href = "#" + heading.id;
      link.textContent = heading.textContent;
      if (heading.tagName === "H3") link.className = "toc-level-3";
      toc.appendChild(link);
    });

    if (stickyTitle) {
      var h1 = article.querySelector("h1");
      stickyTitle.textContent = h1 ? h1.textContent : routes.readme.title;
    }

    if (stickyMenu && tocSidebar) {
      stickyMenu.onclick = function () {
        tocSidebar.classList.toggle("open");
        var expanded = stickyMenu.getAttribute("aria-expanded") === "true";
        stickyMenu.setAttribute("aria-expanded", expanded ? "false" : "true");
      };
    }
  }

  function bindClick(id, handler) {
    var node = document.getElementById(id);
    if (!node) return;
    node.onclick = handler;
  }

  function bindSubmit(id, handler) {
    var node = document.getElementById(id);
    if (!node) return;
    var form = node.closest("form");
    if (!form) return;
    form.onsubmit = handler;
  }

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function setList(id, items) {
    var node = document.getElementById(id);
    if (!node) return;
    node.innerHTML = items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("");
  }

  function toggleHidden(id, hide) {
    var node = document.getElementById(id);
    if (node) node.hidden = hide;
  }

  function toggleActive(id, active) {
    var node = document.getElementById(id);
    if (node) node.classList.toggle("active", active);
  }

  function showInlineError(message) {
    var node = document.getElementById("download-error");
    if (!node) return;
    node.textContent = message;
    node.classList.add("open");
    setTimeout(function () {
      node.classList.remove("open");
    }, 2200);
  }

  function applyNavAttention() {
    // Home console link in the left nav
    var home = document.querySelector(".js-nav-link.nav-link[href='#home']");
    if (!home) return;
    home.classList.remove("nav-attention-yellow", "nav-attention-green");
    if (
      app.data.runtime &&
      (app.data.runtime.serverStatus === "Starting" ||
        app.data.runtime.serverStatus === "Stopping" ||
        app.data.runtime.serverStatus === "Queued")
    ) {
      home.classList.add("nav-attention-yellow");
    } else if (app.data.runtime && app.data.runtime.serverStatus === "Running") {
      home.classList.add("nav-attention-green");
    }
  }

  function pushLog(source, line) {
    if (!app.data.logs[source]) app.data.logs[source] = [];
    app.data.logs[source].push(line);
    if (app.data.logs[source].length > 120) {
      app.data.logs[source] = app.data.logs[source].slice(-120);
    }
  }

  function openModal(id) {
    var node = document.getElementById(id);
    if (node) node.classList.add("open");
  }

  function closeModal(id) {
    var node = document.getElementById(id);
    if (node) node.classList.remove("open");
  }

  function currentTime() {
    var now = new Date();
    return pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
  }

  function valueOf(id) {
    var node = document.getElementById(id);
    return node ? node.value : "";
  }

  function findById(items, id) {
    if (!Array.isArray(items)) return null;
    return items.find(function (item) { return item.id === id; }) || null;
  }

  function statusClass(status) {
    return String(status || "").toLowerCase().replace(/\s+/g, "_");
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatDuration(totalSeconds) {
    if (totalSeconds == null || totalSeconds < 0) return "--:--";
    var minutes = Math.floor(totalSeconds / 60);
    var seconds = totalSeconds % 60;
    return pad(minutes) + ":" + pad(seconds);
  }

  function formatUptime(startedAt) {
    var elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    var hours = Math.floor(elapsed / 3600);
    var minutes = Math.floor((elapsed % 3600) / 60);
    var seconds = elapsed % 60;
    return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }
})();
