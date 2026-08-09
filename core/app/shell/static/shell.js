(function () {
  const root = document.querySelector('[data-page-root]');
  const main = document.querySelector('main');

  async function loadPage(slug) {
    const response = await fetch(`/api/pages/${slug}`);
    const payload = await response.json();
    if (!payload.ok) {
      root.innerHTML = `<div class="list-surface">${payload.error.message}</div>`;
      return;
    }
    root.innerHTML = payload.data.sections
      .map((section) => `<div class="list-surface"><h2>${section.title}</h2><p class="muted">${section.summary}</p></div>`)
      .join('');
  }

  document.querySelector('[data-refresh]')?.addEventListener('click', () => {
    loadPage(main.dataset.activePage);
  });

  loadPage(main.dataset.activePage);
})();
