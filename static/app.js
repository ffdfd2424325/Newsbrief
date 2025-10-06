const elSources = document.getElementById('sources');
const elFeed = document.getElementById('feed');
const elStatus = document.getElementById('status');
const elBtnRefresh = document.getElementById('btn-refresh');
const elBtnReload = document.getElementById('btn-reload');
const elBtnMore = document.getElementById('btn-more');
const elKeyword = document.getElementById('keyword');
const elRefresh = document.getElementById('refresh');
const elFromDate = document.getElementById('from-date');
const elToDate = document.getElementById('to-date');
const elToggleAllSources = document.getElementById('toggle-all-sources');
const elSelectedCount = document.getElementById('selected-count');
const elThemeToggle = document.getElementById('theme-toggle');

const LS_KEY = 'newsbrief_settings_v1';
let FEED_OFFSET = 0;
const FEED_LIMIT = 100;
let ALL_SOURCES = [];
let SELECTED_SOURCES = new Set();

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) || {};
  } catch {
    return {};
  }
}

function saveSettings(s) {
  localStorage.setItem(LS_KEY, JSON.stringify(s));
}

function updateSelectedCount() {
  if (elSelectedCount) {
    elSelectedCount.textContent = SELECTED_SOURCES.size || '0';
  }
}

async function fetchSources() {
  const res = await fetch('/api/sources');
  return await res.json();
}

function renderSources(sources, saved) {
  ALL_SOURCES = sources;
  SELECTED_SOURCES = new Set(saved?.sources || sources.filter(s => s.enabled).map(s => s.key));

  elSources.innerHTML = '';
  sources.forEach((s) => {
    const card = document.createElement('div');
    card.className = `source-card ${SELECTED_SOURCES.has(s.key) ? 'selected' : ''}`;
    card.dataset.key = s.key;

    card.innerHTML = `
      <div class="source-name">${s.title || s.key}</div>
    `;

    card.addEventListener('click', () => {
      if (SELECTED_SOURCES.has(s.key)) {
        SELECTED_SOURCES.delete(s.key);
        card.classList.remove('selected');
      } else {
        SELECTED_SOURCES.add(s.key);
        card.classList.add('selected');
      }
      updateSelectedCount();
      saveSettings({ ...loadSettings(), sources: Array.from(SELECTED_SOURCES) });
    });

    elSources.appendChild(card);
  });

  updateSelectedCount();
}

function getSelectedSources() {
  return Array.from(SELECTED_SOURCES);
}

function cardTemplate(a) {
  const pub = a.published_at ? new Date(a.published_at).toLocaleString() : '';
  const raw = a.summary || a.snippet || '';
  const textOnly = raw.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  const snippet = textOnly.length > 450 ? textOnly.slice(0, 450) + '…' : textOnly;
  const sk = a.source_key || '';
  let badgeClass = '';
  if (sk.startsWith('habr')) badgeClass = 'habr';
  else if (sk === 'vc_all') badgeClass = 'vc';
  else if (sk === 'rbc_tech') badgeClass = 'rbc';
  else if (sk === 'tproger') badgeClass = 'tproger';
  const imgBlock = a.image_url
    ? `<div class="card-image"><img src="${a.image_url}" alt="" loading="lazy" referrerpolicy="no-referrer" /></div>`
    : '';
  return `
    <article class=\"card\">
      <div class=\"card-header\">
        <h3 class=\"card-title\"><a href=\"${a.url}\" target=\"_blank\" rel=\"noopener noreferrer\">${a.title}</a></h3>
      </div>
      ${imgBlock}
      <div class=\"card-body\">
        <p class=\"card-snippet\">${snippet}</p>
      </div>
      <div class=\"card-footer\">
        <span class=\"badge ${badgeClass}\">${a.source_title}</span>
        <span class=\"date\">${pub}</span>
      </div>
    </article>
  `;
}

function skeletonTemplate() {
  return `
    <article class="card skeleton-card">
      <div class="sk-title"></div>
      <div class="sk-image"></div>
      <div class="sk-line"></div>
      <div class="sk-line short"></div>
      <div class="sk-footer"></div>
  `;
}

let isLoading = false;

async function loadFeed({ append = false } = {}) {
  if (isLoading) return; // Предотвращаем множественные запросы
  isLoading = true;

  const settings = loadSettings();
  const selected = getSelectedSources();
  const q = (elKeyword.value || '').trim();
  const qs = new URLSearchParams();
  if (selected.length) qs.set('sources', selected.join(','));
  if (q) qs.set('q', q);

  // Get period from radio buttons
  const periodRadio = document.querySelector('input[name="period"]:checked');
  const period = periodRadio ? periodRadio.value : '24h';

  qs.set('today_only', period === '24h' ? 'true' : 'false');
  if (period !== '24h') {
    if (elFromDate && elFromDate.value) qs.set('from_date', elFromDate.value);
    if (elToDate && elToDate.value) qs.set('to_date', elToDate.value);
  }

  qs.set('limit', FEED_LIMIT.toString());
  qs.set('offset', FEED_OFFSET.toString());

  try {
    if (!append) {
      elFeed.innerHTML = Array.from({length: 6}).map(skeletonTemplate).join('');
    }
    if (elStatus) elStatus.textContent = 'Загрузка...';
    [elBtnReload, elBtnRefresh, elBtnMore].forEach(b => { if (b) b.disabled = true; });

    const res = await fetch(`/api/articles?${qs.toString()}`);
    const data = await res.json();
    if (!Array.isArray(data)) return;

    const html = data.map(cardTemplate).join('');
    if (append) {
      elFeed.insertAdjacentHTML('beforeend', html);
    } else {
      if (data.length === 0) {
        elFeed.innerHTML = `
          <div class="empty">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 6h16v12H4z" stroke="currentColor" stroke-width="1.2"/><path d="M4 9h16" stroke="currentColor" stroke-width="1.2"/><circle cx="7" cy="7" r="1" fill="currentColor"/><circle cx="10" cy="7" r="1" fill="currentColor"/><circle cx="13" cy="7" r="1" fill="currentColor"/></svg>
            <div>Ничего не найдено. Попробуйте изменить фильтры или источники.</div>
            <div class="actions"><button id="btn-reset" class="btn btn-secondary">Сбросить фильтры</button></div>
          </div>`;
        const btnReset = document.getElementById('btn-reset');
        if (btnReset) {
          btnReset.addEventListener('click', () => {
            const s = loadSettings();
            s.keyword = '';
            s.period = '24h';
            s.from_date = '';
            s.to_date = '';
            saveSettings(s);
            if (elKeyword) elKeyword.value = '';
            const period24h = document.querySelector('input[name="period"][value="24h"]');
            if (period24h) period24h.checked = true;
            if (elFromDate) elFromDate.value = '';
            if (elToDate) elToDate.value = '';
            FEED_OFFSET = 0;
            loadFeed({ append: false });
          });
        }
      } else {
        elFeed.innerHTML = html;
      }
    }

    if (elBtnMore) {
      elBtnMore.disabled = data.length < FEED_LIMIT;
      elBtnMore.style.opacity = elBtnMore.disabled ? 0.6 : 1;
    }

    if (elStatus) {
      const parts = [];
      if (q) parts.push(`по запросу "${q}"`);
      if (period === '24h') {
        parts.push('за сегодня');
      } else if (period !== 'all') {
        const f = elFromDate && elFromDate.value ? elFromDate.value : '';
        const t = elToDate && elToDate.value ? elToDate.value : '';
        if (f && t) parts.push(`за период ${f}–${t}`);
        else if (f) parts.push(`с ${f}`);
        else if (t) parts.push(`до ${t}`);
      }
      parts.push(selected.length ? `источники: ${selected.length}` : 'все источники');
      const suffix = parts.length ? ` (${parts.join(', ')})` : '';
      elStatus.textContent = data.length ? `Найдено: ${data.length}${suffix}` : `Ничего не найдено${suffix}`;
    }
  } catch (e) {
    console.error('Ошибка загрузки ленты', e);
    if (elStatus) elStatus.textContent = 'Ошибка загрузки';
  } finally {
    isLoading = false;
    [elBtnReload, elBtnRefresh, elBtnMore].forEach(b => { if (b) b.disabled = false; });
  }
}

async function doRefresh() {
  const sources = getSelectedSources();
  const limit = parseInt(elRefresh.value || '20', 10);

  const settings = loadSettings();
  settings.sources = sources;
  settings.keyword = elKeyword.value || '';
  settings.refresh = parseInt(elRefresh.value || '15', 10);
  const periodRadio = document.querySelector('input[name="period"]:checked');
  settings.period = periodRadio ? periodRadio.value : '24h';
  if (elFromDate) settings.from_date = elFromDate.value || '';
  if (elToDate) settings.to_date = elToDate.value || '';
  saveSettings(settings);

  try {
    if (elStatus) elStatus.textContent = 'Обновление источников...';
    [elBtnReload, elBtnRefresh, elBtnMore].forEach(b => { if (b) b.disabled = true; });

    const res = await fetch('/api/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sources, limit_per_source: limit }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    await res.json();
    if (elStatus) elStatus.textContent = 'Обновлено. Загружаю ленту...';
  } catch (e) {
    console.error('Ошибка обновления', e);
    if (elStatus) elStatus.textContent = 'Не удалось обновить источники. Пытаюсь загрузить текущую ленту...';
  } finally {
    FEED_OFFSET = 0;
    await loadFeed({ append: false });
    [elBtnReload, elBtnRefresh, elBtnMore].forEach(b => { if (b) b.disabled = false; });
  }
}

function setupAutoRefresh() {
  const settings = loadSettings();
  const minutes = parseInt(settings.refresh || elRefresh.value || '15', 10);
  if (window.__nb_timer) clearInterval(window.__nb_timer);
  if (minutes > 0) {
    window.__nb_timer = setInterval(() => {
      // Только если пользователь не взаимодействует активно
      if (document.visibilityState === 'visible') {
        doRefresh();
      }
    }, minutes * 60 * 1000);
  }
}

async function init() {
  const saved = loadSettings();
  try {
    const sources = await fetchSources();
    renderSources(sources, saved);
  } catch (e) {
    console.error('Ошибка загрузки источников', e);
  }

  // Setup period radio buttons - убираем автоматическое обновление
  const periodRadios = document.querySelectorAll('input[name="period"]');
  periodRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        saveSettings({ ...loadSettings(), period: radio.value });
        FEED_OFFSET = 0;
        // Убираем автоматическое обновление - только по кнопке
        // loadFeed({ append: false });
      }
    });
  });

  if (saved.keyword) elKeyword.value = saved.keyword;
  if (saved.refresh) elRefresh.value = saved.refresh;
  if (saved.period) {
    const periodRadio = document.querySelector(`input[name="period"][value="${saved.period}"]`);
    if (periodRadio) periodRadio.checked = true;
  } else {
    const period24h = document.querySelector('input[name="period"][value="24h"]');
    if (period24h) period24h.checked = true;
  }
  if (elFromDate && saved.from_date) elFromDate.value = saved.from_date;
  if (elToDate && saved.to_date) elToDate.value = saved.to_date;

  // Toggle all sources
  if (elToggleAllSources) {
    elToggleAllSources.addEventListener('click', () => {
      const allSelected = SELECTED_SOURCES.size === ALL_SOURCES.length;
      if (allSelected) {
        SELECTED_SOURCES.clear();
        document.querySelectorAll('.source-card').forEach(card => {
          card.classList.remove('selected');
        });
      } else {
        SELECTED_SOURCES = new Set(ALL_SOURCES.map(s => s.key));
        document.querySelectorAll('.source-card').forEach(card => {
          card.classList.add('selected');
        });
      }
      updateSelectedCount();
      saveSettings({ ...loadSettings(), sources: Array.from(SELECTED_SOURCES) });
    });
  }

  elBtnRefresh.addEventListener('click', doRefresh);
  elBtnReload.addEventListener('click', () => { FEED_OFFSET = 0; loadFeed({ append: false }); });
  if (elBtnMore) {
    elBtnMore.addEventListener('click', async () => {
      FEED_OFFSET += FEED_LIMIT;
      await loadFeed({ append: true });
    });
  }

  // Filter inputs - убираем автоматическое обновление
  [elKeyword, elRefresh, elFromDate, elToDate].forEach(input => {
    if (input) {
      input.addEventListener('change', () => {
        const settings = loadSettings();
        settings.keyword = elKeyword.value || '';
        settings.refresh = parseInt(elRefresh.value || '15', 10);
        if (elFromDate) settings.from_date = elFromDate.value || '';
        if (elToDate) settings.to_date = elToDate.value || '';
        saveSettings(settings);
        FEED_OFFSET = 0;
        // Убираем автоматическое обновление - только по кнопке
        // loadFeed({ append: false });
      });
    }
  });

  FEED_OFFSET = 0;
  // Убираем дублирующий вызов loadFeed() - он уже вызывается в setupAutoRefresh()
  setupAutoRefresh();
  const THEME_KEY = 'newsbrief_theme_v1';
  const applyTheme = (t) => {
    document.body.classList.toggle('theme-light', t === 'light');
    if (elThemeToggle) elThemeToggle.textContent = t === 'light' ? 'Тёмная тема' : 'Светлая тема';
  };
  let theme = localStorage.getItem(THEME_KEY) || 'dark';
  applyTheme(theme);
  if (elThemeToggle) {
    elThemeToggle.addEventListener('click', () => {
      theme = theme === 'light' ? 'dark' : 'light';
      localStorage.setItem(THEME_KEY, theme);
      applyTheme(theme);
    });
  }
}

init();
