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

  var content = document.getElementById("mcweb-app-content");
  var nav = document.getElementById("side-nav");
  var navToggle = document.getElementById("nav-toggle");
  var navBackdrop = document.getElementById("nav-backdrop");
  var themeToggle = document.getElementById("theme-toggle");
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
      var navLink = event.target.closest("[data-page]");
      if (navLink && navLink.tagName === "A") {
        event.preventDefault();
        navigate(navLink.getAttribute("data-page"), true);
      }
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
    if (!routes[page]) page = "home";
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
      app.currentRoot = document.getElementById("mcweb-page-root");
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
    Array.prototype.forEach.call(document.querySelectorAll("[data-page].nav-link"), function (link) {
      link.classList.toggle("active", link.getAttribute("data-page") === page);
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
    bindClick("manager-home-open-selection", function () {
      navigate("servers", true);
    });
    bindClick("manager-home-open-create", function () {
      navigate("create_server", true);
    });
    bindClick("manager-home-open-console", function () {
      navigate("home", true);
    });
    renderManagerHomePage();
  }

  function renderManagerHomePage() {
    var selected = getSelectedServer();
    var servers = app.data.servers || [];
    var running = servers.filter(function (server) {
      return server.runtime && server.runtime.serviceRunning;
    }).length;
    if (selected) {
      setText("manager-current-name", selected.name);
      setText("manager-current-meta", selected.serverType + " " + selected.version + " • " + selected.address + ":" + selected.port);
      setText("manager-current-status", selected.runtime.serverStatus);
      setText("manager-current-players", String(selected.runtime.playersOnline));
      setText("manager-next-backup-summary", selected.runtime.nextBackupTime);
    }
    setText("manager-total-servers", String(servers.length));
    setText("manager-running-servers", String(running));
    setText("manager-storage-summary", app.data.managerOverview ? app.data.managerOverview.storageSummary : app.data.runtime.storageUsage);

    var serverList = document.getElementById("manager-server-list");
    if (serverList) {
      serverList.innerHTML = servers.map(function (server) {
        return renderServerCard(server, true);
      }).join("");
      wireServerCardActions(serverList);
    }

    var alertList = document.getElementById("manager-alert-list");
    if (alertList) {
      var notes = app.data.managerAlerts || [];
      alertList.innerHTML = notes.map(function (note) {
        return "<div class='manager-alert-card'><h3>" + escapeHtml(note.title) + "</h3><p>" + escapeHtml(note.message) + "</p></div>";
      }).join("");
    }
  }

  function initServerSelectionPage() {
    bindClick("server-selection-open-create", function () {
      navigate("create_server", true);
    });
    renderServerSelectionPage();
  }

  function renderServerSelectionPage() {
    var selected = getSelectedServer();
    var list = document.getElementById("server-selection-list");
    if (selected) {
      setText("server-selection-current", "Current selection: " + selected.name + " (" + selected.address + ":" + selected.port + ")");
    }
    if (!list) return;
    list.innerHTML = (app.data.servers || []).map(function (server) {
      return renderServerCard(server, false);
    }).join("");
    wireServerCardActions(list);
  }

  function initCreateServerPage() {
    populateCreateServerSelects();
    bindClick("create-server-open-selection", function () {
      navigate("servers", true);
    });
    ["create-server-template", "create-server-runtime", "create-server-host"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) {
        node.onchange = renderCreateServerPreview;
      }
    });
    ["create-server-name", "create-server-id", "create-server-port", "create-server-path", "create-server-address", "create-server-args"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) {
        node.oninput = renderCreateServerPreview;
      }
    });
    var form = document.getElementById("create-server-form");
    if (form) {
      form.onsubmit = function (event) {
        event.preventDefault();
        createServerFromForm();
      };
    }
    renderCreateServerPreview();
  }

  function populateCreateServerSelects() {
    populateOptions("create-server-template", app.data.serverTemplates || []);
    populateOptions("create-server-runtime", app.data.javaRuntimes || []);
    populateOptions("create-server-host", app.data.hosts || []);
  }

  function populateOptions(id, items) {
    var node = document.getElementById(id);
    if (!node) return;
    node.innerHTML = items.map(function (item) {
      return "<option value='" + escapeAttr(item.id) + "'>" + escapeHtml(item.name) + "</option>";
    }).join("");
  }

  function renderCreateServerPreview() {
    var preview = document.getElementById("create-server-preview");
    if (!preview) return;
    var template = findById(app.data.serverTemplates, valueOf("create-server-template"));
    var runtime = findById(app.data.javaRuntimes, valueOf("create-server-runtime"));
    var host = findById(app.data.hosts, valueOf("create-server-host"));
    preview.innerHTML =
      "<h3>" + escapeHtml(valueOf("create-server-name")) + "</h3>" +
      "<p>Machine ID: " + escapeHtml(valueOf("create-server-id")) + "</p>" +
      "<p>Template: " + escapeHtml(template ? template.name : "-") + "</p>" +
      "<p>Java runtime: " + escapeHtml(runtime ? runtime.name : "-") + "</p>" +
      "<p>Host: " + escapeHtml(host ? host.name : "-") + "</p>" +
      "<p>Address: " + escapeHtml(valueOf("create-server-address")) + ":" + escapeHtml(valueOf("create-server-port")) + "</p>" +
      "<p>Path: " + escapeHtml(valueOf("create-server-path")) + "</p>" +
      "<p>Args: " + escapeHtml(valueOf("create-server-args")) + "</p>";
  }

  function createServerFromForm() {
    var template = findById(app.data.serverTemplates, valueOf("create-server-template"));
    var runtime = findById(app.data.javaRuntimes, valueOf("create-server-runtime"));
    var host = findById(app.data.hosts, valueOf("create-server-host"));
    var name = valueOf("create-server-name");
    var server = {
      id: valueOf("create-server-id"),
      name: name,
      summary: "Prototype-created server ready for the existing console pages.",
      serverType: template ? template.serverType : "Vanilla",
      version: template ? template.version : "1.21.1",
      address: valueOf("create-server-address"),
      port: valueOf("create-server-port"),
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
    setText("create-server-status", name + " created in prototype mode and set as the active server.");
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
    bindClick("start-btn", startServer);
    bindClick("stop-btn", stopServer);
    bindClick("backup-btn", triggerBackup);
    bindSubmit("rcon-submit", submitRcon);
    var logSource = document.getElementById("log-source");
    if (logSource) {
      logSource.value = app.currentHomeLogSource;
      logSource.addEventListener("change", function () {
        app.currentHomeLogSource = logSource.value;
        renderHomeLog();
      });
    }
    renderHome();
  }

  function renderHome() {
    var runtime = app.data.runtime;
    syncSelectedServerSummary();
    setText("server-time", new Date().toLocaleString());
    setText("ram-usage", runtime.ramUsage);
    setText("cpu-per-core", runtime.cpuPerCore.map(function (value, index) {
      return "CPU" + index + " " + value + "%";
    }).join(" | "));
    setText("cpu-frequency", runtime.cpuFrequency);
    setText("storage-usage", runtime.storageUsage);
    setText("service-status", runtime.serverStatus);
    setText("players-online", String(runtime.playersOnline));
    setText("tick-rate", runtime.tickRate);
    setText("idle-countdown", formatDuration(runtime.idleCountdownSeconds));
    setText("backup-status", runtime.backupStatus);
    setText("last-backup-time", runtime.lastBackupTime);
    setText("next-backup-time", runtime.nextBackupTime);
    setText("backups-status", app.data.backups.length + " archives");

    var prefix = document.getElementById("service-status-duration-prefix");
    var duration = document.getElementById("session-duration");
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

    var startBtn = document.getElementById("start-btn");
    var stopBtn = document.getElementById("stop-btn");
    var backupBtn = document.getElementById("backup-btn");
    var rconInput = document.getElementById("rcon-command");
    var rconSubmit = document.getElementById("rcon-submit");
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
    setText("minecraft-log", lines.slice(-40).join("\n"));
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
    var panelTitle = document.getElementById("file-panel-title");
    if (panelTitle) panelTitle.textContent = selectedServerLabel() + (isBackups ? " Backup & Restore" : " Log Files");
    toggleHidden("backup-controls", !isBackups);
    toggleHidden("log-view-controls", isBackups);
    if (isBackups) {
      wireBackupControls();
    } else {
      wireLogControls();
    }
    bindClick("file-viewer-close", closeViewer);
    bindClick("backup-restore-cancel", function () {
      app.restoreFileId = null;
      renderFileList();
      renderViewer();
    });
    bindClick("backup-restore-start", simulateRestore);
    bindClick("file-viewer-download", function () {
      showInlineError("Prototype only: no file is actually downloaded.");
    });
    renderFileList();
    renderViewer();
  }

  function wireBackupControls() {
    Array.prototype.forEach.call(document.querySelectorAll(".backup-filter"), function (box) {
      box.checked = app.backupFilters.has(box.value);
      box.addEventListener("change", function () {
        if (box.checked) app.backupFilters.add(box.value);
        else app.backupFilters.delete(box.value);
        renderFileList();
      });
    });
    var sort = document.getElementById("backup-sort");
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
    var sort = document.getElementById("file-sort");
    if (sort) {
      sort.value = app.fileSort;
      sort.addEventListener("change", function () {
        app.fileSort = sort.value;
        renderFileList();
      });
    }
  }

  function renderFileList() {
    var list = document.getElementById("file-list");
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
    var viewer = document.getElementById("file-viewer");
    var contentNode = document.getElementById("file-viewer-content");
    var title = document.getElementById("pane-title-viewer");
    var restoreControls = document.getElementById("backup-restore-controls");
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
    bindClick("maint-scope-backups", function () {
      app.maintenanceScope = "backups";
      app.maintenanceSelected.clear();
      renderMaintenance();
    });
    bindClick("maint-scope-stale", function () {
      app.maintenanceScope = "stale_worlds";
      app.maintenanceSelected.clear();
      renderMaintenance();
    });
    bindClick("maint-open-rules", function () {
      app.maintenanceView = "rules";
      renderMaintenanceViews();
    });
    bindClick("maint-open-history", function () {
      app.maintenanceView = "history";
      renderMaintenanceViews();
    });
    bindClick("maint-open-manual", function () {
      app.maintenanceView = "manual";
      renderMaintenanceViews();
    });
    bindClick("run-rule-delete-btn", openMaintenanceDryRun);
    bindClick("run-manual-delete-btn", openMaintenanceDryRun);
    bindClick("maintenance-dry-run-ok", closeMaintenanceModals);
    bindClick("maintenance-complete-ok", closeMaintenanceModals);
    bindClick("maintenance-dry-run-confirm-run", function () {
      closeMaintenanceModals();
      openMaintenanceComplete();
    });
    bindClick("ack-non-normal-btn", function () {
      var scope = app.data.maintenance[app.maintenanceScope];
      scope.missedRuns = Math.max(0, scope.missedRuns - 1);
      if (scope.history.missed.length) scope.history.missed.shift();
      renderMaintenance();
    });
    renderMaintenance();
  }

  function renderMaintenance() {
    var scope = app.data.maintenance[app.maintenanceScope];
    setText("maint-storage-remaining", scope.storageRemaining);
    setText("maint-backup-summary", scope.backupSummary);
    setText("maint-stale-summary", scope.staleSummary);
    setText("history-last-run", scope.lastRun);
    setText("history-last-changed-by", scope.lastChangedBy);
    setText("maint-schedule-count", String(scope.scheduleCount));
    setText("maint-next-run", scope.nextRun);
    setText("history-missed-runs", String(scope.missedRuns));
    setText("maintenance-action-description", app.maintenanceView === "rules"
      ? "Review rules for the selected cleanup scope."
      : app.maintenanceView === "manual"
        ? "Select individual files from the left pane for manual cleanup."
        : "Review historical cleanup runs and missed-run records.");

    toggleActive("maint-scope-backups", app.maintenanceScope === "backups");
    toggleActive("maint-scope-stale", app.maintenanceScope === "stale_worlds");

    renderMaintenanceFileList(scope);
    renderMaintenanceRules(scope);
    renderMaintenanceHistory(scope);
    renderMaintenanceViews();
  }

  function renderMaintenanceFileList(scope) {
    var list = document.getElementById("cleanup-file-list");
    if (!list) return;
    list.innerHTML = scope.candidates.map(function (item) {
      var checked = app.maintenanceSelected.has(item.id) ? " checked" : "";
      return "<li><label class='maintenance-check'><input type='checkbox' data-cleanup-id='" + item.id + "'" + checked + "> <span class='file-name'>" + escapeHtml(item.name) + "</span></label><span class='meta'>" + escapeHtml(item.detail) + "</span></li>";
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
    var node = document.getElementById("maintenance-manual-selection-count");
    if (!node) return;
    var total = scope.candidates.length;
    var selected = app.maintenanceSelected.size;
    node.hidden = app.maintenanceView !== "manual";
    node.textContent = selected + "/" + total + " Files selected";
  }

  function renderMaintenanceRules(scope) {
    var container = document.getElementById("rules-card-list");
    if (!container) return;
    container.innerHTML = "<div class='maintenance-card'><ul class='maintenance-rule-list'>" +
      scope.rules.map(function (rule) { return "<li>" + escapeHtml(rule) + "</li>"; }).join("") +
      "</ul></div>";
  }

  function renderMaintenanceHistory(scope) {
    var container = document.getElementById("history-card-list");
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
    toggleHidden("maintenance-view-rules", app.maintenanceView !== "rules");
    toggleHidden("maintenance-view-manual", app.maintenanceView !== "manual");
    toggleHidden("maintenance-view-history", app.maintenanceView !== "history");
    toggleHidden("history-view-toggle", app.maintenanceView !== "history");
    toggleActive("maint-open-rules", app.maintenanceView === "rules");
    toggleActive("maint-open-manual", app.maintenanceView === "manual");
    toggleActive("maint-open-history", app.maintenanceView === "history");
    updateMaintenanceSelectionCount(app.data.maintenance[app.maintenanceScope]);
    bindClick("history-show-success", function () {
      app.maintenanceHistoryView = "success";
      renderMaintenance();
    });
    bindClick("history-show-missed", function () {
      app.maintenanceHistoryView = "missed";
      renderMaintenance();
    });
    toggleActive("history-show-success", app.maintenanceHistoryView === "success");
    toggleActive("history-show-missed", app.maintenanceHistoryView === "missed");
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
    renderDeviceMap();
    bindClick("panel-add-device-row", function () {
      app.data.settings.deviceMachines.push({
        id: "d" + Math.random().toString(16).slice(2, 7),
        machine: "new-device",
        addresses: "100.64.0.xx",
        lastSeen: "Just now",
        owner: "Unassigned"
      });
      renderDeviceMap();
      setText("panel-settings-status", "Added a new prototype row. This helps evaluate how row editing should work.");
    });
    ["panel-save-security", "panel-save-paths", "panel-save-timezone", "panel-upload-device-csv", "panel-refresh-states", "panel-reboot-app"].forEach(function (id) {
      bindClick(id, function () {
        setText("panel-settings-status", "Prototype action completed for " + id.replace(/^panel-/, "").replace(/-/g, " ") + ".");
      });
    });
  }

  function renderDeviceMap() {
    var body = document.getElementById("panel-device-map-body");
    if (!body) return;
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
        setText("panel-settings-status", "Deleted a prototype device row. This makes it easier to assess destructive UI affordances.");
      });
    });
    Array.prototype.forEach.call(body.querySelectorAll("[data-device-save]"), function (button) {
      button.addEventListener("click", function () {
        setText("panel-settings-status", "Saved a prototype device row. Requirement question: should rows save inline or batch?");
      });
    });
  }

  function initDocsPage() {
    var article = document.getElementById("content");
    var toc = document.getElementById("tocSidebarBody");
    var stickyTitle = document.getElementById("stickyHeaderTitle");
    var stickyMenu = document.getElementById("stickyMenu");
    var tocSidebar = document.getElementById("tocSidebar");
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
    if (stickyTitle) stickyTitle.textContent = article.querySelector("h1") ? article.querySelector("h1").textContent : routes.readme.title;
    if (stickyMenu && tocSidebar) {
      stickyMenu.addEventListener("click", function () {
        tocSidebar.classList.toggle("open");
      });
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
    var home = document.querySelector("[data-page='home']");
    if (!home) return;
    home.classList.remove("nav-attention-yellow", "nav-attention-green");
    if (app.data.runtime.serverStatus === "Starting" || app.data.runtime.serverStatus === "Stopping" || app.data.runtime.serverStatus === "Queued") {
      home.classList.add("nav-attention-yellow");
    } else if (app.data.runtime.serverStatus === "Running") {
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
