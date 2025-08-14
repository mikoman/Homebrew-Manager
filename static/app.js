const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
let OUTDATED_SET = new Set();

function toast(msg, timeout = 2500) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), timeout);
}

function withButtonLoading(button, fn) {
  return (async () => {
    if (button) { button.classList.add('is-loading'); button.disabled = true; }
    try { return await fn(); }
    finally { if (button) { button.classList.remove('is-loading'); button.disabled = false; } }
  })();
}

function switchTab(name) {
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${name}`));
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) {
    let msg = 'Request failed';
    try { const data = await res.json(); msg = data.error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// Activity log utils
function activityClear() {
  const root = $('#activity-log');
  if (root) root.innerHTML = '';
}
function activityAppend(kind, text) {
  const root = $('#activity-log');
  if (!root) return;
  const line = document.createElement('div');
  line.className = 'activity-line';
  const tag = document.createElement('span');
  tag.className = `tag ${kind}`;
  tag.textContent = kind.toUpperCase();
  const content = document.createElement('div');
  content.className = 'text';
  content.textContent = text;
  line.appendChild(tag);
  line.appendChild(content);
  root.appendChild(line);
  root.scrollTop = root.scrollHeight;
}
function streamSSE(url, { onStart, onLog, onEnd, onError } = {}) {
  const es = new EventSource(url);
  const close = () => { try { es.close(); } catch {} };
  es.addEventListener('start', (e) => { onStart?.(e.data); });
  es.addEventListener('log', (e) => { onLog?.(e.data); });
  es.addEventListener('end', (e) => { onEnd?.(e.data); close(); });
  es.addEventListener('error', (e) => { onError?.(e.data || 'stream error'); close(); });
  return close;
}

function renderOutdated(data) {
  const root = $('#outdated-list');
  root.innerHTML = '';
  const { formulae = [], casks = [] } = data || {};
  const all = [
    ...formulae.map(x => ({ ...x, __type: 'formula' })),
    ...casks.map(x => ({ ...x, __type: 'cask' })),
  ];
  // Build a set of outdated names for use in Installed panel
  OUTDATED_SET = new Set(all.map(it => it.name || it.full_name));
  if (!all.length) {
    root.innerHTML = `<div class="empty">All up to date 🎉</div>`;
    OUTDATED_SET = new Set();
    return;
  }
  for (const item of all) {
    const name = item.name || item.full_name;
    const current = item.current_version || item.current_cask_version || item.current_formula_version;
    const installed = (item.installed_versions && item.installed_versions.join(', ')) || (item.installed_versions || []).join(', ');

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title"><label><input type="checkbox" data-kind="${item.__type}" data-name="${name}" /> ${name}</label></div>
      <div class="subtitle">${item.__type} • Current: ${current || 'n/a'} • Installed: ${installed || 'n/a'}</div>
      <div class="badges">
        ${item.pinned ? '<span class="badge warn">Pinned</span>' : ''}
        ${item.auto_updates ? '<span class="badge">Auto-updates</span>' : ''}
      </div>
      <div class="controls">
        <button class="btn small" data-upgrade-one-name="${name}" data-upgrade-one-kind="${item.__type}">Upgrade</button>
        <button class="btn small" data-uninstall-name="${name}" data-uninstall-kind="${item.__type}">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
}

function renderOrphaned(data) {
  const root = $('#orphaned-list');
  root.innerHTML = '';
  const { formulae = [] } = data || {};
  if (!formulae.length) {
    root.innerHTML = `<div class="empty">No orphaned packages detected</div>`;
    return;
  }
  for (const item of formulae) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${item.name}</div>
      <div class="subtitle">formula • ${item.desc || ''}</div>
      <div class="badges">
        <span class="badge">Leaf</span>
        <span class="badge">Dependency-only</span>
      </div>
      <div class=\"controls\">
        <button class=\"btn small\" data-uninstall-name=\"${item.name}\" data-uninstall-kind=\"formula\">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
}

function renderDeprecated(data) {
  const root = $('#deprecated-list');
  root.innerHTML = '';
  const all = [
    ...(data.formulae || []).map(x => ({ ...x, __type: 'formula' })),
    ...(data.casks || []).map(x => ({ ...x, __type: 'cask' })),
  ];
  if (!all.length) {
    root.innerHTML = `<div class="empty">No deprecated or disabled packages</div>`;
    return;
  }
  for (const item of all) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${item.name}</div>
      <div class="subtitle">${item.__type}${item.deprecated ? ' • deprecated' : ''}${item.disabled ? ' • disabled' : ''}</div>
      <div class="badges">
        ${item.deprecation_date ? `<span class="badge warn">Since ${item.deprecation_date}</span>` : ''}
      </div>
      ${item.desc ? `<div class="subtitle">${item.desc}</div>` : ''}
      ${item.homepage ? `<div class="controls"><a class="btn small" href="${item.homepage}" target="_blank" rel="noopener noreferrer">Homepage</a></div>` : ''}
    `;
    root.appendChild(card);
  }
}

function renderInstalled(data) {
  const root = $('#installed-list');
  if (!root) return;
  root.innerHTML = '';
  const { formulae = [], casks = [] } = data || {};
  const all = [
    ...formulae.map(x => ({ ...x, __type: 'formula' })),
    ...casks.map(x => ({ ...x, __type: 'cask' })),
  ];
  if (!all.length) {
    root.innerHTML = `<div class="empty">Nothing installed</div>`;
    return;
  }
  for (const item of all) {
    const name = item.name || item.full_name;
    const version = (item.versions && item.versions.stable) || item.version || '';
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${name}</div>
      <div class="subtitle">${item.__type}${version ? ` • ${version}` : ''}</div>
      <div class="controls">
        ${OUTDATED_SET.has(name) ? `<button class="btn small" data-upgrade-one-name="${name}" data-upgrade-one-kind="${item.__type}">Upgrade</button>` : ''}
        <button class="btn small" data-uninstall-name="${name}" data-uninstall-kind="${item.__type}">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
}

async function refreshSummary() {
  const panels = $$('.grid');
  panels.forEach(p => p.classList.add('loading'));
  activityClear();
  activityAppend('start', 'Loading summary...');
  try {
    // Fetch sequentially to provide immediate feedback
    activityAppend('log', 'Fetching outdated...');
    const outdated = await api('/api/outdated');
    renderOutdated(outdated);
    activityAppend('log', 'Outdated loaded');

    activityAppend('log', 'Fetching installed...');
    const installed = await api('/api/installed');
    renderInstalled(installed);
    activityAppend('log', 'Installed loaded');

    activityAppend('log', 'Fetching orphaned...');
    const orphaned = await api('/api/orphaned');
    renderOrphaned(orphaned);
    activityAppend('log', 'Orphaned loaded');

    activityAppend('log', 'Fetching deprecated...');
    const deprecated = await api('/api/deprecated');
    renderDeprecated(deprecated);
    activityAppend('log', 'Deprecated loaded');
    activityAppend('end', 'Summary ready');
  } catch (e) {
    activityAppend('error', e.message || 'Failed to load');
    toast(e.message || 'Failed to load');
  } finally {
    panels.forEach(p => p.classList.remove('loading'));
  }
}

async function refreshPackagesOnly() {
  const grids = ['#outdated-list', '#installed-list'].map(sel => $(sel));
  grids.forEach(g => g && g.classList.add('loading'));
  try {
    const data = await api('/api/packages');
    renderOutdated(data.outdated);
    renderInstalled(data.installed);
  } catch (e) {
    toast(e.message || 'Failed to refresh packages');
  } finally {
    grids.forEach(g => g && g.classList.remove('loading'));
  }
}

async function doUpdate() {
  activityClear();
  activityAppend('start', 'Updating Homebrew metadata...');
  return new Promise((resolve) => {
    streamSSE('/api/update_stream', {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { activityAppend('end', 'Update complete'); toast('Update complete'); await refreshSummary(); resolve(); },
      onError: async (m) => {
        // Fallback to non-streaming API
        try {
          const res = await api('/api/update', { method: 'POST', body: JSON.stringify({}) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          activityAppend('end', 'Update complete');
          toast('Update complete');
          await refreshSummary();
        } catch (e) {
          activityAppend('error', m || e.message || 'Update failed');
          toast(m || e.message || 'Update failed');
        }
        resolve();
      },
    });
  });
}

async function doUpgradeSelected() {
  const boxes = $$('input[type="checkbox"][data-name]:checked');
  const formulae = [], casks = [];
  for (const b of boxes) {
    const name = b.dataset.name;
    const kind = b.dataset.kind;
    if (kind === 'cask') casks.push(name); else formulae.push(name);
  }
  if (!formulae.length && !casks.length) {
    toast('Select packages to upgrade');
    return;
  }
  activityClear();
  const params = new URLSearchParams();
  for (const f of formulae) params.append('formulae', f);
  for (const c of casks) params.append('casks', c);
  const url = `/api/upgrade_stream${params.toString() ? ('?' + params.toString()) : ''}`;
  activityAppend('start', 'Starting upgrade...');
  return new Promise((resolve) => {
    streamSSE(url, {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { activityAppend('end', 'Upgrade complete'); toast('Upgrade complete'); await refreshPackagesOnly(); resolve(); },
      onError: async (m) => {
        // Fallback to non-streaming API
        try {
          const res = await api('/api/upgrade', { method: 'POST', body: JSON.stringify({ formulae, casks }) });
          const logs = res?.logs || {};
          const blocks = [];
          if (logs.all) blocks.push(logs.all);
          if (logs.formulae) blocks.push(logs.formulae);
          if (logs.casks) blocks.push(logs.casks);
          for (const block of blocks) {
            const lines = String(block).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          activityAppend('end', 'Upgrade complete');
          toast('Upgrade complete');
          await refreshPackagesOnly();
        } catch (e) {
          activityAppend('error', m || e.message || 'Upgrade failed');
          toast(m || e.message || 'Upgrade failed');
        }
        resolve();
      },
    });
  });
}

async function doSearch() {
  const q = $('#search-input').value.trim();
  const root = $('#search-results');
  root.innerHTML = '';
  if (!q) return;
  root.classList.add('loading');
  activityClear();
  activityAppend('start', `Searching for "${q}"...`);
  try {
    const res = await api(`/api/search?q=${encodeURIComponent(q)}`);
    activityAppend('log', 'Search results received');
    const items = [
      ...res.formulae.map(x => ({ name: x, __type: 'formula' })),
      ...res.casks.map(x => ({ name: x, __type: 'cask' })),
    ];
    if (!items.length) {
      root.innerHTML = `<div class="empty">No results</div>`;
      activityAppend('end', 'No results');
      return;
    }
    for (const item of items) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <div class="title">${item.name}</div>
        <div class="subtitle">${item.__type}</div>
        <div class="controls">
          <button class="btn small" data-install-name="${item.name}" data-install-kind="${item.__type}">Install</button>
          <button class="btn small" data-info-name="${item.name}" data-info-kind="${item.__type}">Info</button>
        </div>
      `;
      root.appendChild(card);
    }
    activityAppend('end', `Rendered ${items.length} result(s)`);
  } catch (e) {
    activityAppend('error', e.message);
    toast(e.message);
  } finally {
    root.classList.remove('loading');
  }
}

async function handleInstall(name, kind) {
  activityClear();
  const params = new URLSearchParams({ name, type: kind });
  activityAppend('start', `Installing ${name}...`);
  return new Promise((resolve) => {
    streamSSE(`/api/install_stream?${params.toString()}`, {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { activityAppend('end', 'Installed'); toast('Installed'); await refreshSummary(); resolve(); },
      onError: async (m) => {
        try {
          const res = await api('/api/install', { method: 'POST', body: JSON.stringify({ name, type: kind }) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          activityAppend('end', 'Installed');
          toast('Installed');
          await refreshSummary();
        } catch (e) {
          activityAppend('error', m || e.message || 'Install failed');
          toast(m || e.message || 'Install failed');
        }
        resolve();
      },
    });
  });
}

async function handleInfo(name, kind) {
  try {
    const data = await api(`/api/info?name=${encodeURIComponent(name)}&type=${encodeURIComponent(kind)}`);
    const details = [
      data.desc && `Description: ${data.desc}`,
      data.homepage && `Homepage: ${data.homepage}`,
      data.license && `License: ${data.license}`,
      data.versions && data.versions.stable && `Stable: ${data.versions.stable}`,
    ].filter(Boolean).join('\n');
    alert(`${name} (${kind})\n\n${details || 'No details available.'}`);
  } catch (e) { toast(e.message); }
}

function initEvents() {
  $$('.tab').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  $('#btn-refresh').addEventListener('click', (e) => withButtonLoading(e.currentTarget, refreshSummary));
  $('#btn-update').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doUpdate));
  $('#btn-upgrade-selected').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doUpgradeSelected));
  $('#btn-search').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doSearch));
  $('#search-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
  $('#chk-select-all')?.addEventListener('change', (e) => {
    const checked = e.currentTarget.checked;
    $$('#outdated-list input[type="checkbox"][data-name]').forEach(b => { b.checked = checked; });
  });
  $('#search-results').addEventListener('click', (e) => {
    const install = e.target.closest('[data-install-name]');
    const info = e.target.closest('[data-info-name]');
    if (install) withButtonLoading(install, () => handleInstall(install.dataset.installName, install.dataset.installKind));
    if (info) handleInfo(info.dataset.infoName, info.dataset.infoKind);
  });
  // Actions within packages tab
  document.addEventListener('click', (e) => {
    const upOne = e.target.closest('[data-upgrade-one-name]');
    if (upOne) {
      const name = upOne.dataset.upgradeOneName;
      const kind = upOne.dataset.upgradeOneKind;
      // Reuse bulk flow with single selection
      const isCask = kind === 'cask';
      const formulae = isCask ? [] : [name];
      const casks = isCask ? [name] : [];
      withButtonLoading(upOne, () => (async () => {
        activityClear();
        const params = new URLSearchParams();
        for (const f of formulae) params.append('formulae', f);
        for (const c of casks) params.append('casks', c);
        const url = `/api/upgrade_stream${params.toString() ? ('?' + params.toString()) : ''}`;
        return new Promise((resolve) => {
          streamSSE(url, {
            onStart: (m) => activityAppend('start', m),
            onLog: (m) => activityAppend('log', m),
            onEnd: async () => { activityAppend('end', 'Upgrade complete'); toast('Upgrade complete'); await refreshPackagesOnly(); resolve(); },
            onError: async (m) => {
              try {
                const res = await api('/api/upgrade', { method: 'POST', body: JSON.stringify({ formulae, casks }) });
                const logs = res?.logs || {};
                const blocks = [];
                if (logs.all) blocks.push(logs.all);
                if (logs.formulae) blocks.push(logs.formulae);
                if (logs.casks) blocks.push(logs.casks);
                for (const block of blocks) {
                  const lines = String(block).split(/\r?\n/);
                  for (const line of lines) if (line.trim()) activityAppend('log', line);
                }
                activityAppend('end', 'Upgrade complete');
                toast('Upgrade complete');
                await refreshPackagesOnly();
              } catch (e) {
                activityAppend('error', m || e.message || 'Upgrade failed');
                toast(m || e.message || 'Upgrade failed');
              }
              resolve();
            },
          });
        });
      })());
    }
  });
  $('#orphaned-list').addEventListener('click', (e) => {
    const del = e.target.closest('[data-uninstall-name]');
    if (del) withButtonLoading(del, () => handleUninstall(del.dataset.uninstallName, del.dataset.uninstallKind || 'formula'));
  });
  $('#btn-activity-clear').addEventListener('click', activityClear);
}

async function handleUninstall(name, kind = 'formula') {
  if (!confirm(`Uninstall ${name}?`)) return;
  activityClear();
  const params = new URLSearchParams({ name, type: kind });
  activityAppend('start', `Uninstalling ${name}...`);
  return new Promise((resolve) => {
    streamSSE(`/api/uninstall_stream?${params.toString()}`, {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { activityAppend('end', 'Uninstalled'); toast('Uninstalled'); await refreshSummary(); resolve(); },
      onError: async (m) => {
        try {
          const res = await api('/api/uninstall', { method: 'POST', body: JSON.stringify({ name, type: kind }) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          activityAppend('end', 'Uninstalled');
          toast('Uninstalled');
          await refreshSummary();
        } catch (e) {
          activityAppend('error', m || e.message || 'Uninstall failed');
          toast(m || e.message || 'Uninstall failed');
        }
        resolve();
      },
    });
  });
}

async function boot() {
  initEvents();
  try {
    activityClear();
    activityAppend('start', 'Checking server health...');
    const health = await api('/api/health');
    activityAppend('log', `Server OK • ${health?.brew || ''}`);
  } catch (e) {
    activityAppend('error', e.message || 'Server not reachable');
    toast(e.message || 'Server not reachable');
  }
  await refreshSummary();
}

boot();
