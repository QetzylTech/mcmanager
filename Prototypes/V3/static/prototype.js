(() => {
  const body = document.body;
  const html = document.documentElement;

  const byId = (id) => document.getElementById(id);

  const navToggleButton = byId("navToggleButton");
  const btnToggleTheme = byId("btnToggleTheme");
  const btnToggleServer = byId("btnToggleServer");
  const btnToggleBackup = byId("btnToggleBackup");

  const setThemeDark = (enabled) => {
    if (enabled) html.classList.add("theme-dark");
    else html.classList.remove("theme-dark");
  };

  const setNavCollapsed = (collapsed) => {
    if (collapsed) body.classList.add("nav-collapsed");
    else body.classList.remove("nav-collapsed");
  };

  if (navToggleButton) {
    navToggleButton.addEventListener("click", () => {
      setNavCollapsed(!body.classList.contains("nav-collapsed"));
    });
  }

  if (btnToggleTheme) {
    btnToggleTheme.addEventListener("click", () => {
      const isDark = html.classList.contains("theme-dark");
      setThemeDark(!isDark);
    });
  }

  // Dummy server state simulation:
  // - OFF: backup button disabled
  // - ON: backup button enabled and can run (dummy)
  let serverOn = false;
  let backupRunning = false;

  const syncDummyButtons = () => {
    if (btnToggleServer) {
      btnToggleServer.textContent = serverOn ? "Server: ON" : "Server: OFF";
      btnToggleServer.classList.toggle("btn-action-teal", serverOn);
      btnToggleServer.classList.toggle("btn-action-blue", !serverOn);
    }

    if (btnToggleBackup) {
      btnToggleBackup.disabled = !serverOn || backupRunning;
      btnToggleBackup.textContent = backupRunning
        ? "Backup: RUNNING"
        : serverOn
          ? "Backup: IDLE"
          : "Backup: OFFLINE";
    }
  };

  if (btnToggleServer) {
    btnToggleServer.addEventListener("click", () => {
      serverOn = !serverOn;
      backupRunning = false;
      syncDummyButtons();
    });
  }

  if (btnToggleBackup) {
    btnToggleBackup.addEventListener("click", () => {
      if (!serverOn || backupRunning) return;
      backupRunning = true;
      syncDummyButtons();

      // Fake async backup duration.
      window.setTimeout(() => {
        backupRunning = false;
        syncDummyButtons();
      }, 1200);
    });
  }

  // Initialize
  setThemeDark(false);
  setNavCollapsed(false);
  syncDummyButtons();
})();
