import { api } from '../api.js';
import { showToast } from '../components/toast.js';
import { makeSearchable } from '../components/combobox.js';

// Samlad uppgiftslista. Uppgifter kan hänga på en arbetsorder, en offert eller en
// kund – här visas de tillsammans så att man ser vad som behöver göras utan att
// veta var uppgiften råkar ligga.

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const fmtD = (d) => (d ? String(d).slice(0, 10) : '');

const SCOPES = [
  { key: 'open',    label: 'Öppna' },
  { key: 'overdue', label: 'Försenade' },
  { key: 'today',   label: 'Idag' },
  { key: 'done',    label: 'Klara' },
];

const PARENT_LABELS = { arbetsorder: 'Arbetsorder', offert: 'Offert', kund: 'Kund' };

/** Delar in i hinkar efter förfallodatum. Görs här och inte på servern så att
 *  listan kan ritas om utan en ny hämtning. */
function bucketOf(task, today, weekEnd) {
  if (task.completed) return 'klara';
  if (!task.due_date) return 'utan';
  const due = String(task.due_date).slice(0, 10);
  if (due < today) return 'forsenade';
  if (due === today) return 'idag';
  return due <= weekEnd ? 'vecka' : 'senare';
}

const BUCKETS = [
  { key: 'forsenade', label: 'Försenade', tone: 'danger' },
  { key: 'idag',      label: 'Idag',      tone: 'warn' },
  { key: 'vecka',     label: 'Denna vecka' },
  { key: 'senare',    label: 'Senare' },
  { key: 'utan',      label: 'Utan datum' },
  { key: 'klara',     label: 'Klara' },
];

export async function renderTasks(el, params = {}) {
  let scope = params.scope || 'open';
  let assignedTo = '';
  let query = '';
  let tasks = [];

  const users = await api.get('/users').catch(() => []);

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = '';

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Uppgifter</div>
    <div class="page-subtitle" style="margin-bottom:20px">Från arbetsordrar, offerter och kunder</div>

    <div class="card" style="margin-bottom:16px">
      <div class="card-header" style="gap:10px;flex-wrap:wrap">
        <div class="chart-toggle" id="scope-toggle">
          ${SCOPES.map(sc => `
            <button type="button" data-scope="${sc.key}" class="${sc.key === scope ? 'active' : ''}">${sc.label}</button>
          `).join('')}
        </div>
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="task-search" placeholder="Sök uppgift…">
        </div>
        <div class="field" style="margin:0;min-width:180px">
          <select id="task-assignee">
            <option value="">Alla ansvariga</option>
            ${users.map(u => `<option value="${u.id}">${esc(u.full_name)}</option>`).join('')}
          </select>
        </div>
      </div>
    </div>

    <div id="task-body"><div class="loading">Laddar…</div></div>
  `;

  makeSearchable(document.getElementById('task-assignee'), { placeholder: 'Sök person…' });

  document.getElementById('scope-toggle').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-scope]');
    if (!btn || btn.dataset.scope === scope) return;
    scope = btn.dataset.scope;
    document.querySelectorAll('#scope-toggle button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    load();
  });

  let timer;
  document.getElementById('task-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = e.target.value; load(); }, 300);
  });
  document.getElementById('task-assignee').addEventListener('change', (e) => {
    assignedTo = e.target.value;
    load();
  });

  async function load() {
    const qs = new URLSearchParams({ scope });
    if (query) qs.set('q', query);
    if (assignedTo) qs.set('assigned_to', assignedTo);
    tasks = await api.get(`/tasks?${qs}`);
    draw();
  }

  function draw() {
    const body = document.getElementById('task-body');
    if (!body) return;
    if (!tasks.length) {
      body.innerHTML = `<div class="card"><div class="empty-state"><p>Inga uppgifter här</p></div></div>`;
      return;
    }

    const today = new Date().toISOString().slice(0, 10);
    const week = new Date();
    // Fram till och med söndag i innevarande vecka
    week.setDate(week.getDate() + (7 - (week.getDay() || 7)));
    const weekEnd = week.toISOString().slice(0, 10);

    const groups = {};
    for (const t of tasks) (groups[bucketOf(t, today, weekEnd)] ||= []).push(t);

    body.innerHTML = BUCKETS
      .filter(b => groups[b.key]?.length)
      .map(b => `
        <div class="card" style="margin-bottom:16px">
          <div class="card-header">
            <span class="card-title ${b.tone ? `text-${b.tone === 'danger' ? 'danger' : 'muted'}` : ''}">
              ${b.label} <span class="text-muted" style="font-weight:400">(${groups[b.key].length})</span>
            </span>
          </div>
          <div class="card-body">
            ${groups[b.key].map(taskRow).join('')}
          </div>
        </div>`).join('');

    bindRows();
  }

  function taskRow(t) {
    const due = fmtD(t.due_date);
    return `
      <div class="lead-task ${t.completed ? 'done' : ''}" data-task-id="${t.id}">
        <input type="checkbox" data-toggle="${t.id}" ${t.completed ? 'checked' : ''}>
        <div class="lead-task-body">
          <div class="lead-task-title">${esc(t.title)}</div>
          ${t.description ? `<div class="lead-task-desc">${esc(t.description)}</div>` : ''}
          <div class="lead-task-meta">
            ${t.parent_link ? `
              <a class="task-source ${esc(t.parent_type)}" href="${esc(t.parent_link)}">
                ${esc(PARENT_LABELS[t.parent_type] || t.parent_type)} ${esc(t.parent_label)}
              </a>` : ''}
            ${t.customer_name && t.parent_type !== 'kund' ? `<span>${esc(t.customer_name)}</span>` : ''}
            ${t.assigned_user ? `<span>${esc(t.assigned_user.full_name)}</span>` : ''}
            ${due ? `<span>Klart till ${due}</span>` : ''}
          </div>
        </div>
      </div>`;
  }

  function bindRows() {
    document.querySelectorAll('[data-toggle]').forEach(cb => {
      cb.addEventListener('change', async () => {
        try {
          // Global rutt – listan behöver inte veta vilken förälder uppgiften har
          await api.put(`/tasks/${cb.dataset.toggle}`, { completed: cb.checked });
          showToast(cb.checked ? 'Uppgift klar' : 'Uppgift återöppnad', 'success', 1500);
          load();
        } catch (err) {
          showToast(err.message, 'error');
          cb.checked = !cb.checked;
        }
      });
    });
  }

  await load();
}
