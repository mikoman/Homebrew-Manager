const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
let OUTDATED_SET = new Set();

// Debug helper: enable via localStorage.setItem('hbw_debug','1')
function dbg(...args) {
  try { if (localStorage.getItem('hbw_debug')) console.debug('[HBW]', ...args); } catch {}
}

// Helpers for robust name/description handling (casks sometimes use arrays)
function getItemKeyName(it) {
  let n = it && (it.full_name || it.token);
  if (!n) {
    n = it && it.name;
    if (Array.isArray(n)) n = n[0] || '';
  }
  return String(n || '');
}

function getItemDisplayName(it) {
  let n = it && it.name;
  if (Array.isArray(n)) n = n[0] || '';
  if (!n) n = (it && (it.full_name || it.token)) || '';
  return String(n || '');
}
function getItemDesc(it) {
  let d = it && it.desc;
  if (Array.isArray(d)) d = d.join(', ');
  return String(d || '');
}

function shouldPromptSudo(message = '') {
  const msg = String(message || '').toLowerCase();
  if (msg.includes('| requires_sudo') || msg.includes('must be run as root') || msg.includes('requires administrator access')) return true;
  if (msg.includes('sudo: a password is required') || msg.includes('either use the -s option') || msg.includes('askpass')) return true;
  const root = document.getElementById('activity-log');
  if (root) {
    const lines = Array.from(root.querySelectorAll('.activity-line .text')).slice(-20).map(n => n.textContent.toLowerCase());
    if (lines.some(t => t.includes('sudo: a password is required') || t.includes('requires administrator access') || t.includes('must be run as root') || t.includes('askpass'))) return true;
  }
  return false;
}

function toast(msg, timeout = 2500) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), timeout);
}

// Password dialog for sudo operations
let currentSudoCallback = null;

function showPasswordDialog(operation, packageName) {
  return new Promise((resolve, reject) => {
    // Remove any existing dialog
    const existing = document.getElementById('sudo-dialog');
    if (existing) existing.remove();

    // Create dialog
    const dialog = document.createElement('div');
    dialog.id = 'sudo-dialog';
    dialog.className = 'sudo-dialog-overlay';
    
    dialog.innerHTML = `
      <div class="sudo-dialog">
        <div class="sudo-header">
          <h3>Administrator Password Required</h3>
          <button class="sudo-close" type="button">×</button>
        </div>
        <div class="sudo-content">
          <p class="sudo-message">
            <strong>${packageName}</strong> requires administrator privileges to ${operation}.
          </p>
          <div class="sudo-warning">
            ⚠️ Your password is processed locally and never stored or transmitted.
          </div>
          <div class="sudo-input-group">
            <label for="sudo-password">Enter your password:</label>
            <input type="password" id="sudo-password" class="sudo-password-input" placeholder="Password" autocomplete="current-password">
          </div>
          <div class="sudo-buttons">
            <button type="button" class="btn" id="sudo-cancel">Cancel</button>
            <button type="button" class="btn primary" id="sudo-confirm">Continue</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    const passwordInput = dialog.querySelector('#sudo-password');
    const confirmBtn = dialog.querySelector('#sudo-confirm');
    const cancelBtn = dialog.querySelector('#sudo-cancel');
    const closeBtn = dialog.querySelector('.sudo-close');

    // Focus password input
    setTimeout(() => passwordInput.focus(), 100);

    // Handle confirm
    const handleConfirm = () => {
      const password = passwordInput.value;
      if (!password) {
        passwordInput.focus();
        return;
      }
      dialog.remove();
      resolve(password);
    };

    // Handle cancel
    const handleCancel = () => {
      dialog.remove();
      reject(new Error('User cancelled'));
    };

    // Event listeners
    confirmBtn.addEventListener('click', handleConfirm);
    cancelBtn.addEventListener('click', handleCancel);
    closeBtn.addEventListener('click', handleCancel);
    
    // Enter key submits
    passwordInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleConfirm();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        handleCancel();
      }
    });

    // Click outside to cancel
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) {
        handleCancel();
      }
    });
  });
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

async function upgradePackages(formulae, casks, displayName) {
  const params = new URLSearchParams();
  for (const f of formulae) params.append('formulae', f);
  for (const c of casks) params.append('casks', c);
  const url = `/api/upgrade_stream${params.toString() ? ('?' + params.toString()) : ''}`;

  const runWithPassword = async (password) => {
    activityClear();
    activityAppend('start', 'Starting upgrade...');
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ formulae, casks, sudo_password: password })
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEvent = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('event: ')) { currentEvent = line.slice(7); continue; }
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (currentEvent === 'start') activityAppend('start', data);
          else if (currentEvent === 'log') activityAppend('log', data);
          else if (currentEvent === 'end') {
            requestAnimationFrame(() => {
              activityClear();
              activityAppend('end', 'Upgrade complete');
            });
            toast('Upgrade complete');
            await refreshPackagesOnly();
            return true;
          } else if (currentEvent === 'error') {
            activityAppend('error', data);
            toast('Upgrade failed');
            return false;
          }
        }
      }
    }
    return false;
  };

  if (window.__SUDO_PWD__) {
    const ok = await runWithPassword(window.__SUDO_PWD__);
    if (!ok) {
      try {
        const pwd = await showPasswordDialog('upgrade', displayName);
        if (pwd) {
  if (sudoPwd) {
    const ok = await runWithPassword(sudoPwd);
    if (!ok) {
      try {
        const pwd = await showPasswordDialog('upgrade', displayName);
        if (pwd) {
          sudoPwd = pwd;
          await runWithPassword(pwd);
        }
      } catch (e) {
        if (e.message !== 'User cancelled') {
          activityAppend('error', 'Authentication failed');
          toast('Authentication failed');
        }
      }
    }
    return;
  }

  activityClear();
  activityAppend('start', 'Starting upgrade...');
  return new Promise((resolve) => {
    streamSSE(url, {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => {
        requestAnimationFrame(() => {
          activityClear();
          activityAppend('end', 'Upgrade complete');
        });
        toast('Upgrade complete');
        await refreshPackagesOnly();
        resolve();
      },
      onError: async (m) => {
        if (shouldPromptSudo(m)) {
          try {
            const pwd = window.__SUDO_PWD__ || await showPasswordDialog('upgrade', displayName);
            if (pwd) {
            if (pwd) {
              await runWithPassword(pwd);
            }
          } catch (e) {
            if (e.message !== 'User cancelled') {
              activityAppend('error', 'Authentication failed');
              toast('Authentication failed');
            }
          }
          resolve();
          return;
        }
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
          requestAnimationFrame(() => {
            activityClear();
            activityAppend('end', 'Upgrade complete');
          });
          toast('Upgrade complete');
          await refreshPackagesOnly();
        } catch (e) {
          activityAppend('error', m || e.message || 'Upgrade failed');
          toast(m || e.message || 'Upgrade failed');
        }
        resolve();
      }
    });
  });
}

function renderOutdated(data) {
  const root = $('#outdated-list');
  const header = $('#outdated-header');
  const hint = $('#outdated-hint');
  root.innerHTML = '';
  const { formulae = [], casks = [] } = data || {};
  const all = [
    ...formulae.map(x => ({ ...x, __type: 'formula' })),
    ...casks.map(x => ({ ...x, __type: 'cask' })),
  ];
  // Build a set of outdated names for use in Installed panel
  OUTDATED_SET = new Set(all.map(it => getItemKeyName(it)));
  if (!all.length) {
    // Hide the entire outdated section when nothing is outdated
    if (header) header.style.display = 'none';
    if (hint) hint.style.display = 'none';
    root.style.display = 'none';
    root.innerHTML = '';
    OUTDATED_SET = new Set();
    return;
  }
  // Ensure visible when there are items
  if (header) header.style.display = '';
  if (hint) hint.style.display = '';
  root.style.display = '';
  for (const item of all) {
    const key = getItemKeyName(item);
    const display = getItemDisplayName(item);
    const current = item.current_version || item.current_cask_version || item.current_formula_version;
    const installed = (item.installed_versions && item.installed_versions.join(', ')) || (item.installed_versions || []).join(', ');

    const card = document.createElement('div');
    card.className = 'card';
    const description = item.desc && item.desc.trim() ? item.desc : '';

    card.innerHTML = `
      <div class="title"><label><input type="checkbox" data-kind="${item.__type}" data-name="${key}" /> ${display}</label></div>
      ${description ? `<div class="description">${description}</div>` : ''}
      <div class="subtitle">${item.__type} • Current: ${current || 'n/a'} • Installed: ${installed || 'n/a'}</div>
      <div class="badges">
        ${item.pinned ? '<span class="badge warn">Pinned</span>' : ''}
        ${item.auto_updates ? '<span class="badge">Auto-updates</span>' : ''}
      </div>
      <div class="controls">
        <button class="btn small" data-upgrade-one-name="${key}" data-upgrade-one-kind="${item.__type}">Upgrade</button>
        <button class="btn small" data-uninstall-name="${key}" data-uninstall-kind="${item.__type}" data-display-name="${display}">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
  // Attach explicit handlers (in addition to delegation) after render
  attachUninstallHandlers(root);
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
    const key = getItemKeyName(item);
    const display = getItemDisplayName(item);
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${display}</div>
      ${item.desc ? `<div class="description">${item.desc}</div>` : ''}
      <div class="subtitle">formula</div>
      <div class="badges">
        <span class="badge">Leaf</span>
        <span class="badge">Dependency-only</span>
      </div>
      <div class=\"controls\">
        <button class=\"btn small\" data-uninstall-name=\"${key}\" data-uninstall-kind=\"formula\" data-display-name=\"${display}\">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
  attachUninstallHandlers(root);
}

function renderDeprecated(data) {
  const root = $('#deprecated-list');
  root.innerHTML = '';
  const all = [
    ...(data.formulae || []).map(x => ({ ...x, __type: 'formula' })),
    ...(data.casks || []).map(x => ({ ...x, __type: 'cask' })),
  ];
  const clearBtn = $('#btn-remove-deprecated');
  if (!all.length) {
    root.innerHTML = `<div class="empty">No deprecated or disabled packages</div>`;
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }
  if (clearBtn) clearBtn.style.display = '';
  for (const item of all) {
    const key = getItemKeyName(item);
    const display = getItemDisplayName(item);
    const controls = [];
    if (item.homepage) {
      controls.push(`<a class="btn small" href="${item.homepage}" target="_blank" rel="noopener noreferrer">Homepage</a>`);
    }
    controls.push(`<button class="btn small" data-uninstall-name="${key}" data-uninstall-kind="${item.__type}" data-display-name="${display}">Remove</button>`);
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${display}</div>
      ${item.desc ? `<div class="description">${item.desc}</div>` : ''}
      <div class="subtitle">${item.__type}${item.deprecated ? ' • deprecated' : ''}${item.disabled ? ' • disabled' : ''}</div>
      <div class="badges">
        ${item.deprecation_date ? `<span class="badge warn">Since ${item.deprecation_date}</span>` : ''}
      </div>
      <div class="controls">${controls.join(' ')}</div>
    `;
    root.appendChild(card);
  }
  attachUninstallHandlers(root);
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
  // Persist current set for client-side filtering
  window.__INSTALLED_CACHE__ = all;
  if (!all.length) {
    root.innerHTML = `<div class="empty">Nothing installed</div>`;
    return;
  }
  for (const item of all) {
    const key = getItemKeyName(item);
    const display = getItemDisplayName(item);
    const version = (item.versions && item.versions.stable) || item.version || '';
    const descStr = getItemDesc(item);
    const description = descStr && descStr.trim() ? descStr : '';
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${display}</div>
      ${description ? `<div class="description">${description}</div>` : ''}
      <div class="subtitle">${item.__type}${version ? ` • ${version}` : ''}</div>
      <div class="controls">
        ${OUTDATED_SET.has(key) ? `<button class="btn small" data-upgrade-one-name="${key}" data-upgrade-one-kind="${item.__type}">Upgrade</button>` : ''}
        <button class="btn small" data-uninstall-name="${key}" data-uninstall-kind="${item.__type}" data-display-name="${display}">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
  attachUninstallHandlers(root);
}

function applyInstalledFilter() {
  const q = ($('#installed-search')?.value || '').trim().toLowerCase();
  const items = window.__INSTALLED_CACHE__ || [];
  const root = $('#installed-list');
  if (!root) return;
  root.innerHTML = '';
  const filtered = q ? items.filter(it => {
    const key = getItemKeyName(it).toLowerCase();
    const disp = getItemDisplayName(it).toLowerCase();
    const desc = getItemDesc(it).toLowerCase();
    return key.includes(q) || disp.includes(q) || desc.includes(q);
  }) : items;
  if (!filtered.length) {
    root.innerHTML = `<div class="empty">No matches</div>`;
    return;
  }
  for (const item of filtered) {
    const key = getItemKeyName(item);
    const display = getItemDisplayName(item);
    const version = (item.versions && item.versions.stable) || item.version || '';
    const descStr = getItemDesc(item);
    const description = descStr && descStr.trim() ? descStr : '';
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="title">${display}</div>
      ${description ? `<div class="description">${description}</div>` : ''}
      <div class="subtitle">${item.__type}${version ? ` • ${version}` : ''}</div>
      <div class="controls">
        ${OUTDATED_SET.has(key) ? `<button class="btn small" data-upgrade-one-name="${key}" data-upgrade-one-kind="${item.__type}">Upgrade</button>` : ''}
        <button class="btn small" data-uninstall-name="${key}" data-uninstall-kind="${item.__type}" data-display-name="${display}">Uninstall</button>
      </div>
    `;
    root.appendChild(card);
  }
  attachUninstallHandlers(root);
}

async function loadOutdated() {
  const grid = $('#outdated-list');
  grid.classList.add('loading');
  activityAppend('log', 'Fetching outdated...');
  try {
    const outdated = await api('/api/outdated');
    renderOutdated(outdated);
    activityAppend('log', 'Outdated loaded');
  } catch (e) {
    activityAppend('error', e.message || 'Failed to load outdated');
    toast(e.message || 'Failed to load outdated');
  } finally {
    grid.classList.remove('loading');
  }
}

async function loadInstalled() {
  const grid = $('#installed-list');
  grid.classList.add('loading');
  activityAppend('log', 'Fetching installed...');
  try {
    const installed = await api('/api/installed');
    renderInstalled(installed);
    activityAppend('log', 'Installed loaded');
  } catch (e) {
    activityAppend('error', e.message || 'Failed to load installed');
    toast(e.message || 'Failed to load installed');
  } finally {
    grid.classList.remove('loading');
  }
}

async function loadOrphaned() {
  const grid = $('#orphaned-list');
  grid.classList.add('loading');
  activityAppend('log', 'Fetching orphaned...');
  try {
    const orphaned = await api('/api/orphaned');
    renderOrphaned(orphaned);
    activityAppend('log', 'Orphaned loaded');
  } catch (e) {
    activityAppend('error', e.message || 'Failed to load orphaned');
    toast(e.message || 'Failed to load orphaned');
  } finally {
    grid.classList.remove('loading');
  }
}

async function loadDeprecated() {
  const grid = $('#deprecated-list');
  grid.classList.add('loading');
  activityAppend('log', 'Fetching deprecated...');
  try {
    const deprecated = await api('/api/deprecated');
    renderDeprecated(deprecated);
    activityAppend('log', 'Deprecated loaded');
  } catch (e) {
    activityAppend('error', e.message || 'Failed to load deprecated');
    toast(e.message || 'Failed to load deprecated');
  } finally {
    grid.classList.remove('loading');
  }
}

async function refreshSummary() {
  activityClear();
  activityAppend('start', 'Loading summary...');
  await Promise.allSettled([
    loadOutdated(),
    loadInstalled(),
    loadOrphaned(),
    loadDeprecated(),
  ]);
  requestAnimationFrame(() => {
    activityClear();
    activityAppend('end', 'Loading complete');
  });
}

async function refreshPackagesOnly() {
  await Promise.allSettled([
    loadOutdated(),
    loadInstalled(),
  ]);
}

async function doUpdate() {
  activityClear();
  activityAppend('start', 'Updating Homebrew metadata...');
  return new Promise((resolve) => {
    streamSSE('/api/update_stream', {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { 
        requestAnimationFrame(() => {
          activityClear();
          activityAppend('end', 'Update complete');
        });
        toast('Update complete'); 
        await refreshSummary();
        // Check if update button should be hidden after update
        try {
          const health = await api('/api/health');
          const updateBtn = $('#btn-update');
          if (!health?.needs_update) {
            updateBtn.style.display = 'none';
          }
        } catch (e) {
          // Ignore health check errors after update
        }
        resolve(); 
      },
      onError: async (m) => {
        // Fallback to non-streaming API
        try {
          const res = await api('/api/update', { method: 'POST', body: JSON.stringify({}) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          requestAnimationFrame(() => {
            activityClear();
            activityAppend('end', 'Update complete');
          });
          toast('Update complete');
          await refreshSummary();
          // Check if update button should be hidden after update
          try {
            const health = await api('/api/health');
            const updateBtn = $('#btn-update');
            if (!health?.needs_update) {
              updateBtn.style.display = 'none';
            }
          } catch (e) {
            // Ignore health check errors after update
          }
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
  await upgradePackages(formulae, casks, formulae.concat(casks).join(', ') || 'selected packages');
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
      ...res.formulae.map(x => ({ name: x.name || x, desc: x.desc || '', __type: 'formula' })),
      ...res.casks.map(x => ({ name: x.name || x, desc: x.desc || '', __type: 'cask' })),
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
        ${item.desc ? `<div class="description">${item.desc}</div>` : ''}
        <div class="subtitle">${item.__type}</div>
        <div class="controls">
          <button class="btn small" data-install-name="${item.name}" data-install-kind="${item.__type}">Install</button>
          <button class="btn small" data-info-name="${item.name}" data-info-kind="${item.__type}">Info</button>
        </div>
      `;
      root.appendChild(card);
    }
    requestAnimationFrame(() => {
      activityClear();
      activityAppend('end', `Found ${items.length} result(s)`);
    });
  } catch (e) {
    activityAppend('error', e.message);
    toast(e.message);
  } finally {
    root.classList.remove('loading');
  }
}

async function removeAllDeprecated() {
  const buttons = $$('#deprecated-list [data-uninstall-name]');
  if (!buttons.length) return;
  if (!confirm(`Uninstall all ${buttons.length} deprecated packages?`)) return;
  const targets = buttons.map(btn => ({ name: btn.dataset.uninstallName, kind: btn.dataset.uninstallKind || 'formula', display: btn.dataset.displayName }));
  for (const t of targets) {
    await handleUninstall(t.name, t.kind, false, t.display);
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
      onEnd: async () => { 
        requestAnimationFrame(() => {
          activityClear();
          activityAppend('end', 'Installed');
        });
        toast('Installed'); 
        await refreshSummary(); 
        resolve(); 
      },
      onError: async (m) => {
        try {
          const res = await api('/api/install', { method: 'POST', body: JSON.stringify({ name, type: kind }) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          requestAnimationFrame(() => {
            activityClear();
            activityAppend('end', 'Installed');
          });
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
  $('#btn-update').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doUpdate));
  $('#btn-upgrade-selected').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doUpgradeSelected));
  $('#btn-remove-deprecated')?.addEventListener('click', (e) => withButtonLoading(e.currentTarget, removeAllDeprecated));
  $('#btn-search').addEventListener('click', (e) => withButtonLoading(e.currentTarget, doSearch));
  $('#search-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
  
  // Search input clear functionality
  const searchInput = $('#search-input');
  const searchClear = $('#search-input-clear');
  const installedSearch = $('#installed-search');
  const installedClear = $('#installed-search-clear');
  
  // Show/hide clear buttons based on input content
  function updateClearButton(input, clearBtn) {
    if (input && clearBtn) {
      clearBtn.style.display = input.value.trim() ? 'block' : 'none';
    }
  }
  
  if (searchInput && searchClear) {
    searchInput.addEventListener('input', () => updateClearButton(searchInput, searchClear));
    searchClear.addEventListener('click', () => {
      searchInput.value = '';
      updateClearButton(searchInput, searchClear);
      $('#search-results').innerHTML = '';
      searchInput.focus();
    });
  }
  
  if (installedSearch && installedClear) {
    installedSearch.addEventListener('input', () => {
      updateClearButton(installedSearch, installedClear);
      applyInstalledFilter();
    });
    installedClear.addEventListener('click', () => {
      installedSearch.value = '';
      updateClearButton(installedSearch, installedClear);
      applyInstalledFilter();
      installedSearch.focus();
    });
  }
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
    // Single item upgrade
    const upOne = e.target.closest('[data-upgrade-one-name]');
    if (upOne) {
      const name = upOne.dataset.upgradeOneName;
      const kind = upOne.dataset.upgradeOneKind;
      const isCask = kind === 'cask';
      const formulae = isCask ? [] : [name];
      const casks = isCask ? [name] : [];
      withButtonLoading(upOne, () => upgradePackages(formulae, casks, name));
      return; // Prevent also handling uninstall on same click
    }
    // Uninstall buttons (outdated, installed, orphaned sections)
    const uninstallBtn = e.target.closest('[data-uninstall-name]');
    if (uninstallBtn) {
      withButtonLoading(uninstallBtn, () => handleUninstall(uninstallBtn.dataset.uninstallName, uninstallBtn.dataset.uninstallKind || 'formula', true, uninstallBtn.dataset.displayName));
      return;
    }
  });
  $('#btn-activity-clear').addEventListener('click', activityClear);
  // Note: Installed filter input handling is now managed above with clear button
  // Settings modal events
  const settingsBtn = $('#btn-settings');
  const settingsModal = $('#settings-modal');
  const settingsClose = settingsModal?.querySelector('.sudo-close');
  const settingsCancel = $('#settings-cancel');
  const settingsSave = $('#settings-save');
  const settingsInput = $('#settings-sudo-password');
  if (settingsBtn && settingsModal) {
    settingsBtn.addEventListener('click', () => {
      settingsModal.style.display = 'flex';
      setTimeout(() => settingsInput?.focus(), 100);
    });
    const closeModal = () => { settingsModal.style.display = 'none'; };
    settingsClose?.addEventListener('click', closeModal);
    settingsCancel?.addEventListener('click', closeModal);
    settingsModal.addEventListener('click', (e) => { if (e.target === settingsModal) closeModal(); });
    settingsSave?.addEventListener('click', async () => {
      const pwd = settingsInput.value;
      if (!pwd) { settingsInput.focus(); return; }
      try {
        const res = await api('/api/sudo/validate', { method: 'POST', body: JSON.stringify({ sudo_password: pwd }) });
        if (!res.ok && res.error) throw new Error(res.error);
        // Save in-memory for this session
        window.__SUDO_PWD__ = pwd;
        toast('Sudo password saved for this session');
        settingsModal.style.display = 'none';
      } catch (e) {
        toast(e.message || 'Failed to validate password');
      }
    });
  }
}

async function handleUninstall(name, kind = 'formula', confirmPrompt = true, displayName) {
  const shown = displayName || name;
  if (confirmPrompt && !confirm(`Uninstall ${shown}?`)) return;
  activityClear();
  const params = new URLSearchParams({ name, type: kind });
  activityAppend('start', `Uninstalling ${shown}...`);
  return new Promise((resolve) => {
    streamSSE(`/api/uninstall_stream?${params.toString()}`, {
      onStart: (m) => activityAppend('start', m),
      onLog: (m) => activityAppend('log', m),
      onEnd: async () => { 
        requestAnimationFrame(() => {
          activityClear();
          activityAppend('end', 'Uninstalled');
        });
        toast('Uninstalled'); 
        await refreshSummary(); 
        resolve(); 
      },
      onError: async (m) => {
        try {
          const res = await api('/api/uninstall', { method: 'POST', body: JSON.stringify({ name, type: kind }) });
          if (res?.log) {
            const lines = String(res.log).split(/\r?\n/);
            for (const line of lines) if (line.trim()) activityAppend('log', line);
          }
          requestAnimationFrame(() => {
            activityClear();
            activityAppend('end', 'Uninstalled');
          });
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

// Explicit per-button binding as fallback if event delegation fails (e.g. shadow DOM edge cases)
function attachUninstallHandlers(scope) {
  if (!scope) return;
  scope.querySelectorAll('[data-uninstall-name]').forEach(btn => {
    if (btn.__hbwBound) return;
    btn.__hbwBound = true;
    btn.addEventListener('click', (ev) => {
      dbg('direct uninstall handler', btn.dataset.uninstallName, btn.dataset.uninstallKind);
      ev.preventDefault();
      ev.stopPropagation();
      withButtonLoading(btn, () => handleUninstall(btn.dataset.uninstallName, btn.dataset.uninstallKind || 'formula', true, btn.dataset.displayName));
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
    
    // Show/hide update button based on whether homebrew needs updating
    const updateBtn = $('#btn-update');
    if (health?.needs_update) {
      updateBtn.style.display = 'inline-flex';
      activityAppend('log', 'Homebrew update available');
    } else {
      updateBtn.style.display = 'none';
      activityAppend('log', 'Homebrew is up to date');
    }
  } catch (e) {
    activityAppend('error', e.message || 'Server not reachable');
    toast(e.message || 'Server not reachable');
    // Hide update button on error
    const updateBtn = $('#btn-update');
    if (updateBtn) updateBtn.style.display = 'none';
  }
  await refreshSummary();
}

boot();
