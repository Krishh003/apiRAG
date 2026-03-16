let selectedPlatform = null;
let allAPIs = [];
let isLoading = false;
let currentMode = 'auto'; // auto | lookup | planning | advisory | comparison

const PLATFORM_COLORS = {
  WhatsApp: '#25d366', Meta: '#1877f2', Facebook: '#1877f2',
  Instagram: '#e1306c', Stripe: '#635bff', Twilio: '#f22f46',
  SendGrid: '#1a82e2', Google: '#4285f4',
};

function getPlatformColor(p) {
  return PLATFORM_COLORS[p] || '#555d78';
}

async function init() {
  if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light-mode');
  }
  updateThemeIcon();
  await loadAPIs();
  await loadPlatforms();
  await pollScrapeStatus();
  setInterval(pollScrapeStatus, 15000);
}

function toggleTheme() {
  const isLight = document.body.classList.toggle('light-mode');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  updateThemeIcon();
}

function updateThemeIcon() {
  const isLight = document.body.classList.contains('light-mode');
  const icon = document.getElementById('themeIcon');
  if (!icon) return;
  if (isLight) {
    icon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
  } else {
    icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
  }
}

async function loadAPIs() {
  try {
    const res = await fetch('/api/apis' + (selectedPlatform ? `?platform=${encodeURIComponent(selectedPlatform)}` : ''));
    allAPIs = await res.json();
    renderAPIList();
    document.getElementById('apiCount').textContent = `${allAPIs.length} API${allAPIs.length !== 1 ? 's' : ''}`;
  } catch (e) { console.error(e); }
}

async function loadPlatforms() {
  try {
    const res = await fetch('/api/platforms');
    const platforms = await res.json();
    const filter = document.getElementById('platformFilter');
    const allBtn = filter.querySelector('.plat-btn');
    filter.innerHTML = '';
    filter.appendChild(allBtn);
    document.getElementById('totalCount').textContent = allAPIs.length;

    platforms.forEach(p => {
      const count = allAPIs.filter(a => a.platform === p).length;
      const btn = document.createElement('button');
      btn.className = 'plat-btn';
      const color = getPlatformColor(p);
      btn.innerHTML = `<span style="display:flex;align-items:center;gap:6px"><span class="plat-dot" style="background:${color}"></span>${escHtml(p)}</span><span class="plat-count">${count}</span>`;
      btn.onclick = () => filterPlatform(p, btn);
      filter.appendChild(btn);
    });
  } catch (e) { }
}

function renderAPIList() {
  const list = document.getElementById('apiList');
  if (!allAPIs.length) {
    list.innerHTML = `<div class="empty-state"><div class="big"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg></div>${selectedPlatform ? `No APIs for "${selectedPlatform}"` : 'No APIs stored yet.'}</div>`;
    return;
  }
  list.innerHTML = allAPIs.map(api => `
    <div class="api-item">
      <div class="api-item-info" onclick="askAbout('${escHtml(api.name)}')">
        <div class="api-item-name">${escHtml(api.name)}</div>
        <div class="api-item-meta">
          <span class="method-badge method-${api.method || 'GET'}">${api.method || 'GET'}</span>
          <span class="api-item-endpoint">${escHtml(api.endpoint || '')}</span>
        </div>
      </div>
      <button class="btn btn-danger" onclick="deleteAPI('${api.id}', event)">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </div>
  `).join('');
}

function filterPlatform(platform, btn) {
  selectedPlatform = platform;
  document.querySelectorAll('.plat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const hint = document.getElementById('platformHint');
  if (platform) {
    document.getElementById('filterPlatformName').textContent = platform;
    hint.style.display = 'flex';
  } else {
    hint.style.display = 'none';
  }
  loadAPIs();
}

// ── Mode ──────────────────────────────────────────────────────────────────────

const MODE_CONFIG = {
  auto: {
    activeClass: 'active-lookup',
    label: 'Auto-detect',
    placeholder: 'Ask about an API, or describe what you want to achieve…',
  },
  lookup: {
    activeClass: 'active-lookup',
    label: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:middle;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>Lookup',
    placeholder: 'Ask what an API does…',
  },
  planning: {
    activeClass: 'active-planning',
    label: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:middle;"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon><line x1="8" y1="2" x2="8" y2="18"></line><line x1="16" y1="6" x2="16" y2="22"></line></svg>Plan',
    placeholder: 'Describe what you want to achieve…',
    wrapperClass: 'planning-mode',
    btnClass: 'planning',
  },
  advisory: {
    activeClass: 'active-advisory',
    label: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:middle;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>Advisory',
    placeholder: 'Ask a data engineering, SQL, or analytics question…',
    wrapperClass: 'advisory-mode',
    btnClass: 'advisory',
  },
  comparison: {
    activeClass: 'active-comparison',
    label: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:middle;"><line x1="3" y1="12" x2="21" y2="12"></line><polyline points="8 7 3 12 8 17"></polyline><polyline points="16 7 21 12 16 17"></polyline></svg>Compare',
    placeholder: 'Compare two or more API operations…',
    wrapperClass: 'comparison-mode',
    btnClass: 'comparison',
  },
};

function setMode(mode, btn) {
  currentMode = mode;
  const cfg = MODE_CONFIG[mode] || MODE_CONFIG.auto;

  document.querySelectorAll('.mode-chip').forEach(b => b.className = 'mode-chip');
  btn.classList.add(cfg.activeClass);

  const wrapper = document.getElementById('inputWrapper');
  wrapper.className = 'input-wrapper' + (cfg.wrapperClass ? ' ' + cfg.wrapperClass : '');

  const sendBtn = document.getElementById('sendBtn');
  sendBtn.className = 'send-btn' + (cfg.btnClass ? ' ' + cfg.btnClass : '');

  const label = document.getElementById('currentModeLabel');
  label.innerHTML = cfg.label;

  document.getElementById('chatInput').placeholder = cfg.placeholder;
}

// ── Chat ──────────────────────────────────────────────────────────────────────

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const question = input.value.trim();
  if (!question || isLoading) return;

  document.getElementById('welcome')?.remove();
  isLoading = true;
  input.value = '';
  autoResize(input);
  document.getElementById('sendBtn').disabled = true;

  appendMessage('user', question);
  const thinking = appendThinking();

  try {
    const body = { question };
    if (selectedPlatform) body.platform_filter = selectedPlatform;

    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    thinking.remove();
    appendAssistantMessage(data);
  } catch (e) {
    thinking.remove();
    appendMessage('assistant', 'Connection error. Is the server running?');
  } finally {
    isLoading = false;
    document.getElementById('sendBtn').disabled = false;
  }
}

function appendMessage(role, text) {
  const chatArea = document.getElementById('chatArea');
  const el = document.createElement('div');
  el.className = `message ${role}`;
  const avatar = role === 'user'
    ? `<div class="msg-avatar">U</div>`
    : `<div class="msg-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg></div>`;
  el.innerHTML = `${avatar}<div class="msg-content"><div class="msg-bubble">${escHtml(text).replace(/\n/g, '<br>')}</div></div>`;
  chatArea.appendChild(el);
  chatArea.scrollTop = chatArea.scrollHeight;
  return el;
}

function appendAssistantMessage(data) {
  const chatArea = document.getElementById('chatArea');
  const el = document.createElement('div');
  const isPlan       = data.query_type === 'planning';
  const isAdvisory   = data.query_type === 'advisory';
  const isComparison = data.query_type === 'comparison';

  const typeClass = isPlan ? 'planning-msg' : isAdvisory ? 'advisory-msg' : isComparison ? 'comparison-msg' : '';
  el.className = `message assistant ${typeClass}`;

  const BADGE_ICONS = {
    planning:   `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon><line x1="8" y1="2" x2="8" y2="18"></line><line x1="16" y1="6" x2="16" y2="22"></line></svg>Step-by-step plan`,
    advisory:   `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>Advisory`,
    lookup:     `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>Lookup answer`,
    comparison: `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><line x1="3" y1="12" x2="21" y2="12"></line><polyline points="8 7 3 12 8 17"></polyline><polyline points="16 7 21 12 16 17"></polyline></svg>Comparison`,
  };

  const badgeHtml = `<div class="msg-type-badge ${data.query_type}">${BADGE_ICONS[data.query_type] || BADGE_ICONS.lookup}</div>${data.confidence != null ? `<span class="confidence-badge ${data.confidence_label}">${data.confidence_label} · ${Math.round(data.confidence * 100)}%</span>` : ''}`;

  // Plan steps as cards
  let stepsHtml = '';
  if (isPlan && data.plan_steps && data.plan_steps.length > 0) {
    stepsHtml = `<div class="plan-steps">` +
      data.plan_steps.map(step => `
        <div class="step-card">
          <div class="step-header">
            <div class="step-num">${step.step}</div>
            <div class="step-api-name">${escHtml(step.api_name)}</div>
            <div class="step-platform">${escHtml(step.platform || '')}</div>
          </div>
          <div class="step-body">
            ${step.endpoint ? `<div class="step-row"><span class="step-row-label">Endpoint</span><span class="step-endpoint">${escHtml(step.endpoint)}</span></div>` : ''}
            ${step.purpose  ? `<div class="step-row"><span class="step-row-label">Purpose</span><span class="step-row-value">${escHtml(step.purpose)}</span></div>` : ''}
            ${step.parameters && step.parameters.length ? `
              <div class="step-row">
                <span class="step-row-label">Params</span>
                <div class="step-params">${step.parameters.map(p => `<div class="step-param">${escHtml(p)}</div>`).join('')}</div>
              </div>` : ''}
            ${step.returns ? `<div class="step-row"><span class="step-row-label">Returns</span><span class="step-row-value">${escHtml(step.returns)}</span></div>` : ''}
          </div>
        </div>
      `).join('') + `</div>`;
  } else if (isPlan) {
    stepsHtml = `<div class="msg-bubble" style="margin-top:10px;white-space:pre-wrap">${escHtml(data.answer)}</div>`;
  }

  const answerHtml = isPlan && data.plan_steps && data.plan_steps.length
    ? ''
    : `<div class="msg-bubble">${renderMarkdown(data.answer)}</div>`;

  // Sources
  const sourcesHtml = data.sources && data.sources.length ? `
    <div class="sources-bar">
      <span style="font-size:10.5px;color:var(--text-3);font-family:var(--mono)">Sources:</span>
      ${data.sources.slice(0, 5).map(s => `
        <div class="source-tag">
          <div class="source-dot ${s.source === 'graph' ? 'graph' : ''}"></div>
          ${escHtml(s.name || '')}
          ${s.relevance != null ? `<span class="source-score ${s.relevance >= 0.7 ? 'score-high' : s.relevance >= 0.4 ? 'score-med' : 'score-low'}">${Math.round(s.relevance * 100)}%</span>` : ''}
        </div>`).join('')}
    </div>` : '';

  // Avatar icon varies by type
  const AVATAR_ICONS = {
    planning:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon><line x1="8" y1="2" x2="8" y2="18"></line><line x1="16" y1="6" x2="16" y2="22"></line></svg>`,
    advisory:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,
    comparison: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><polyline points="8 7 3 12 8 17"></polyline><polyline points="16 7 21 12 16 17"></polyline></svg>`,
    default:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`,
  };
  const avatarIcon = AVATAR_ICONS[data.query_type] || AVATAR_ICONS.default;

  el.innerHTML = `
    <div class="msg-avatar">${avatarIcon}</div>
    <div class="msg-content">
      ${badgeHtml}
      ${answerHtml}
      ${stepsHtml}
      ${sourcesHtml}
    </div>`;

  chatArea.appendChild(el);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function appendThinking() {
  const chatArea = document.getElementById('chatArea');
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `<div class="msg-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg></div><div class="msg-content"><div class="msg-bubble"><div class="thinking"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div></div>`;
  chatArea.appendChild(el);
  chatArea.scrollTop = chatArea.scrollHeight;
  return el;
}

function sendSuggestion(card) {
  document.getElementById('chatInput').value = card.querySelector('.sug-text').textContent;
  sendMessage();
}

function askAbout(name) {
  document.getElementById('chatInput').value = `What does the ${name} API do?`;
  sendMessage();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

// ── Scraper ───────────────────────────────────────────────────────────────────

async function triggerScrape() {
  try {
    const res = await fetch('/admin/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platforms: null }),
    });
    const data = await res.json();
    showToast(data.message || 'Scrape started!', 'success');
    pollScrapeStatus();
  } catch (e) {
    showToast('Failed to trigger scrape.', 'error');
  }
}

async function pollScrapeStatus() {
  try {
    const res = await fetch('/admin/scrape/status');
    const data = await res.json();
    const el = document.getElementById('scrapeStatus');

    function makeSvg(path) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '12'); svg.setAttribute('height', '12');
      svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2.5');
      svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
      svg.style.verticalAlign = 'middle'; svg.style.marginRight = '4px';
      svg.innerHTML = path;
      return svg;
    }

    el.textContent = '';
    if (data.is_running) {
      el.appendChild(makeSvg('<polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>'));
      el.appendChild(document.createTextNode(' Scraping in progress...'));
      el.className = 'scrape-status running';
    } else if (data.last_status === 'success') {
      el.appendChild(makeSvg('<polyline points="20 6 9 17 4 12"></polyline>'));
      el.appendChild(document.createTextNode(` Last run: ${data.last_run ? new Date(data.last_run).toLocaleDateString() : 'N/A'}`));
      el.className = 'scrape-status success';
      document.getElementById('apiCount').textContent = `${data.total_apis_stored} APIs`;
      await loadAPIs();
      await loadPlatforms();
    } else if (data.last_status && data.last_status.startsWith('failed')) {
      el.appendChild(makeSvg('<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>'));
      el.appendChild(document.createTextNode(' Last run failed'));
      el.className = 'scrape-status error';
    } else {
      el.textContent = 'Last run: never';
      el.className = 'scrape-status';
    }
  } catch (e) { }
}

// ── Health ────────────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    showToast(`Neo4j: ${data.neo4j} · ${data.vector_store_count} APIs · Platforms: ${(data.platforms || []).join(', ')}`, data.neo4j === 'connected' ? 'success' : 'warning');
  } catch (e) {
    showToast('Backend unreachable', 'error');
  }
}

// ── Modal ─────────────────────────────────────────────────────────────────────

let _uploadFile = null;

function openModal() {
  document.getElementById('modal').classList.add('open');
  switchModalTab('simple');
  document.getElementById('fUrl').value = '';
  document.getElementById('fUrlPlatform').value = '';
  document.getElementById('fUrlCategory').value = '';
  document.getElementById('scrapeProgress').classList.remove('visible');
  document.getElementById('scrapeUrlBtn').disabled = false;
  clearUploadFile();
  document.getElementById('uploadResult').classList.remove('visible');
}

function onFileSelected(file) {
  if (!file) return;
  const allowed = ['.json', '.pdf', '.md'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) {
    showToast('Only .json, .pdf and .md files are supported.', 'error');
    return;
  }
  _uploadFile = file;
  document.getElementById('uploadFileName').textContent = file.name;
  document.getElementById('uploadFileSize').textContent = file.size > 1024 * 1024
    ? (file.size / 1024 / 1024).toFixed(1) + ' MB'
    : (file.size / 1024).toFixed(0) + ' KB';
  document.getElementById('uploadFileInfo').classList.add('visible');
  document.getElementById('uploadBtn').disabled = false;
}

function clearUploadFile() {
  _uploadFile = null;
  document.getElementById('fileInput').value = '';
  document.getElementById('uploadFileInfo').classList.remove('visible');
  document.getElementById('uploadBtn').disabled = true;
}

async function uploadFile() {
  if (!_uploadFile) return;
  const btn = document.getElementById('uploadBtn');
  const result = document.getElementById('uploadResult');
  btn.disabled = true;
  btn.textContent = 'Uploading...';
  result.classList.remove('visible');

  try {
    const form = new FormData();
    form.append('file', _uploadFile);
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();

    const uploadIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>Upload`;

    if (data.count > 0) {
      showToast(`${data.count} API${data.count !== 1 ? 's' : ''} added from "${_uploadFile.name}"`, 'success');
      result.textContent = `Added: ${data.added.slice(0, 5).join(', ')}${data.added.length > 5 ? ` … and ${data.added.length - 5} more` : ''}` +
        (data.errors.length ? `\nErrors: ${data.errors.join('; ')}` : '');
      result.classList.add('visible');
      await loadAPIs();
      await loadPlatforms();
      setTimeout(closeModal, 1800);
    } else {
      showToast('No APIs found in that file.', 'warning');
      result.textContent = data.errors.length ? `Errors: ${data.errors.join('; ')}` : 'No entries could be parsed.';
      result.classList.add('visible');
      btn.disabled = false;
      btn.innerHTML = uploadIcon;
    }
  } catch (e) {
    showToast('Upload failed. Is the server running?', 'error');
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>Upload`;
  }
}

function closeModal() { document.getElementById('modal').classList.remove('open'); }

function switchModalTab(tab) {
  ['simple', 'advanced', 'upload'].forEach(t => {
    document.getElementById(`tab${t.charAt(0).toUpperCase() + t.slice(1)}`).classList.toggle('active', t === tab);
    document.getElementById(`panel${t.charAt(0).toUpperCase() + t.slice(1)}`).classList.toggle('active', t === tab);
  });
  if (tab === 'advanced') setTimeout(() => document.getElementById('fName').focus(), 50);
  else if (tab === 'simple') setTimeout(() => document.getElementById('fUrl').focus(), 50);
}

function toggleOptionalFields() {
  document.getElementById('optionalToggle').classList.toggle('expanded');
  document.getElementById('optionalContent').classList.toggle('visible');
}

async function scrapeUrl() {
  const url = document.getElementById('fUrl').value.trim();
  if (!url) { showToast('Please enter a documentation URL.', 'error'); return; }
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    showToast('URL must start with http:// or https://', 'error'); return;
  }

  const platform = document.getElementById('fUrlPlatform').value.trim() || 'Imported';
  const category = document.getElementById('fUrlCategory').value.trim() || 'General';
  const progress = document.getElementById('scrapeProgress');
  const btn = document.getElementById('scrapeUrlBtn');

  progress.classList.add('visible');
  document.getElementById('scrapeProgressText').textContent = 'Scraping page and extracting APIs...';
  btn.disabled = true;

  try {
    const res = await fetch('/admin/scrape/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, platform, category }),
    });
    const data = await res.json();

    if (data.status === 'success') {
      showToast(data.message, 'success');
      closeModal();
      await loadAPIs();
      await loadPlatforms();
    } else {
      document.getElementById('scrapeProgressText').textContent = data.message || 'Failed to extract APIs.';
      showToast(data.message || 'Scraping failed.', 'error');
    }
  } catch (e) {
    showToast('Connection error. Is the server running?', 'error');
    document.getElementById('scrapeProgressText').textContent = 'Connection error.';
  } finally {
    btn.disabled = false;
    setTimeout(() => progress.classList.remove('visible'), 3000);
  }
}

document.getElementById('fInternal').addEventListener('change', function () {
  document.getElementById('internalNotesGroup').style.display = this.checked ? 'block' : 'none';
});

async function saveAPI() {
  const name     = document.getElementById('fName').value.trim();
  const platform = document.getElementById('fPlatform').value.trim();
  const plain    = document.getElementById('fPlain').value.trim();
  if (!name || !platform || !plain) { showToast('Name, Platform, and Plain Explanation are required.', 'error'); return; }
  try {
    await fetch('/api/apis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, platform,
        category:       document.getElementById('fCategory').value.trim() || platform,
        method:         document.getElementById('fMethod').value,
        endpoint:       document.getElementById('fEndpoint').value.trim(),
        base_url:       document.getElementById('fBaseUrl').value.trim(),
        auth:           document.getElementById('fAuth').value.trim(),
        description:    document.getElementById('fDesc').value.trim(),
        plain_explanation: plain,
        is_internal:    document.getElementById('fInternal').checked,
        internal_notes: document.getElementById('fInternalNotes').value.trim(),
      }),
    });
    showToast(`"${name}" added!`, 'success');
    closeModal();
    await loadAPIs();
    await loadPlatforms();
  } catch (e) { showToast('Failed to save.', 'error'); }
}

async function deleteAPI(id, e) {
  e.stopPropagation();
  await fetch(`/api/apis/${id}`, { method: 'DELETE' });
  showToast('Removed.', 'success');
  await loadAPIs();
  await loadPlatforms();
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.className = `toast ${type} show`;
  t.textContent = msg;
  setTimeout(() => { t.className = 'toast'; }, 4000);
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderMarkdown(text) {
  let s = String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  function inline(line) {
    line = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    line = line.replace(/\*([^*]+?)\*/g, '<em>$1</em>');
    return line;
  }
  const lines = s.split('\n');
  let html = '', inUl = false, inOl = false;
  for (const line of lines) {
    const heading  = line.match(/^#{1,3} (.+)$/);
    const bullet   = line.match(/^[*\-] (.+)$/);
    const numbered = line.match(/^(\d+)\. (.+)$/);
    if (heading) {
      if (inUl) { html += '</ul>'; inUl = false; }
      if (inOl) { html += '</ol>'; inOl = false; }
      html += `<span class="md-heading">${inline(heading[1])}</span>`;
    } else if (bullet) {
      if (inOl) { html += '</ol>'; inOl = false; }
      if (!inUl) { html += '<ul class="md-list">'; inUl = true; }
      html += `<li>${inline(bullet[1])}</li>`;
    } else if (numbered) {
      if (inUl) { html += '</ul>'; inUl = false; }
      if (!inOl) { html += '<ol class="md-list">'; inOl = true; }
      html += `<li>${inline(numbered[2])}</li>`;
    } else {
      if (inUl) { html += '</ul>'; inUl = false; }
      if (inOl) { html += '</ol>'; inOl = false; }
      html += (line.trim() === '' ? '<br>' : inline(line) + '<br>');
    }
  }
  if (inUl) html += '</ul>';
  if (inOl) html += '</ol>';
  return html.replace(/(<br>\s*)+$/, '');
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.getElementById('modal').addEventListener('click', e => {
  if (e.target === document.getElementById('modal')) closeModal();
});

init();
