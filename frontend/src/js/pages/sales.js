import { api, uploadFile, downloadFile, printFile } from '../api.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';
import { openCustomerForm } from './customers.js';
import { renderGantt } from '../components/gantt.js';

// ── Gemensamma hjälpare ───────────────────────────────────────────────────────

/** Projektet saknar escape-hjälpare och fälten här är fritext från säljaren,
 *  så allt som interpoleras in i en mall går genom den här. */
function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Datumfälten är rena YYYY-MM-DD utan tidszon – fmtDate i app.js klistrar på ett
 *  Z och ger Invalid Date på dem, så formateringen sker här istället. */
function fmtD(d) {
  if (!d) return '–';
  return String(d).slice(0, 10);
}

function fmtMoney(value, currency) {
  if (value === null || value === undefined || value === '') return '–';
  const n = Number(value);
  if (Number.isNaN(n)) return esc(value);
  return `${n.toLocaleString('sv-SE', { maximumFractionDigits: 2 })} ${esc(currency || 'EUR')}`;
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

const STATUSES = [
  { key: 'ny',       label: 'Ny' },
  { key: 'skickad',  label: 'Skickad' },
  { key: 'jobbar',   label: 'Jobbar' },
  { key: 'sald',     label: 'Såld' },
  { key: 'avslutad', label: 'Avslutad' },
];
const STATUS_LABEL = Object.fromEntries(STATUSES.map(s => [s.key, s.label]));

const NOTE_KINDS = {
  samtal: 'Samtal',
  mail: 'Mail',
  mote: 'Möte',
  anteckning: 'Anteckning',
};

export function salesStatusBadge(status) {
  return `<span class="badge badge-sales-${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;
}

function isOverdue(lead) {
  return lead.next_followup_date
    && lead.next_followup_date <= todayISO()
    && ['ny', 'skickad', 'jobbar'].includes(lead.status);
}

async function productTypes() {
  try {
    const rows = await api.get('/settings');
    const row = rows.find(r => r.key === 'sales_product_types');
    return (row?.value || '').split(',').map(s => s.trim()).filter(Boolean);
  } catch {
    return [];
  }
}

function progressBar(done, total) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return `
    <div class="ms-progress" title="${done} av ${total} klara">
      <div class="ms-progress-bar" style="width:${pct}%"></div>
      <span class="ms-progress-label">${done}/${total}</span>
    </div>`;
}

// ── Huvudsida ─────────────────────────────────────────────────────────────────

export async function renderSales(el, params = {}) {
  const view = params.view || 'pipeline';

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <button class="btn btn-primary btn-sm" id="new-lead-btn">
      <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
      Ny förfrågan
    </button>`;

  el.innerHTML = `
    <div style="margin-bottom:4px" class="page-title">Försäljning</div>
    <div class="page-subtitle" style="margin-bottom:20px">Offertförfrågningar, sålda ordrar och provision</div>

    <div class="tabs" id="sales-tabs">
      <div class="tab ${view === 'pipeline' ? 'active' : ''}" data-view="pipeline">Förfrågningar</div>
      <div class="tab ${view === 'orders' ? 'active' : ''}" data-view="orders">Sålda ordrar</div>
      <div class="tab ${view === 'commission' ? 'active' : ''}" data-view="commission">Provision</div>
      <div class="tab ${view === 'archive' ? 'active' : ''}" data-view="archive">Arkiv</div>
    </div>

    <div id="sales-view"><div class="loading">Laddar…</div></div>
  `;

  document.getElementById('sales-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (tab) location.hash = `#/sales?view=${tab.dataset.view}`;
  });

  document.getElementById('new-lead-btn')?.addEventListener('click', () =>
    openLeadForm(null, () => renderSales(el, params))
  );

  const host = document.getElementById('sales-view');
  if (!host) return;
  if (view === 'orders') return renderOrdersView(host);
  if (view === 'commission') return renderCommissionView(host);
  if (view === 'archive') return renderOrdersView(host, { archived: true });
  return renderPipelineView(host);
}

// ── Vy 1: förfrågningar (kanban + tabell) ─────────────────────────────────────

async function renderPipelineView(host) {
  // Excel-vanan är en tabell, men kanban gör bevakningen mycket lättare – båda finns
  let mode = localStorage.getItem('flow_sales_mode') || 'kanban';
  let leads = [];
  let query = '';
  let onlyOverdue = false;

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header" style="gap:10px;flex-wrap:wrap">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="lead-search" placeholder="Sök kund, aktivitetsnr, offertnr…">
        </div>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer">
          <input type="checkbox" id="lead-overdue"> Endast uppföljning som passerat
        </label>
        <div style="flex:1"></div>
        <div class="flex gap-2">
          <button class="btn btn-secondary btn-sm" id="mode-kanban">Tavla</button>
          <button class="btn btn-secondary btn-sm" id="mode-table">Tabell</button>
        </div>
      </div>
      <div id="lead-stats" class="sales-stats"></div>
    </div>
    <div id="lead-body"><div class="loading">Laddar…</div></div>
  `;

  let timer;
  document.getElementById('lead-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = e.target.value; load(); }, 300);
  });
  document.getElementById('lead-overdue').addEventListener('change', (e) => {
    onlyOverdue = e.target.checked;
    load();
  });
  document.getElementById('mode-kanban').addEventListener('click', () => setMode('kanban'));
  document.getElementById('mode-table').addEventListener('click', () => setMode('table'));

  function setMode(next) {
    mode = next;
    localStorage.setItem('flow_sales_mode', next);
    draw();
  }

  async function load() {
    const qs = new URLSearchParams();
    if (query) qs.set('q', query);
    if (onlyOverdue) qs.set('followup', 'overdue');
    const [rows, stats] = await Promise.all([
      api.get(`/sales/leads${qs.toString() ? `?${qs}` : ''}`),
      api.get('/sales/leads/stats').catch(() => null),
    ]);
    leads = rows;
    const statsEl = document.getElementById('lead-stats');
    if (!statsEl) return;
    if (stats) {
      statsEl.innerHTML = `
        <div class="sales-stat"><span>Öppna förfrågningar</span><strong>${stats.open_leads}</strong></div>
        <div class="sales-stat"><span>Uppföljning passerad</span><strong class="${stats.overdue_followups ? 'text-danger' : ''}">${stats.overdue_followups}</strong></div>
        <div class="sales-stat"><span>Sålda</span><strong>${stats.by_status?.sald ?? 0}</strong></div>
        <div class="sales-stat"><span>Öppet värde</span><strong>${fmtMoney(stats.open_value, 'EUR')}</strong></div>`;
    }
    draw();
  }

  function draw() {
    const body = document.getElementById('lead-body');
    if (!body) return;
    document.getElementById('mode-kanban').classList.toggle('btn-primary', mode === 'kanban');
    document.getElementById('mode-table').classList.toggle('btn-primary', mode === 'table');
    if (!leads.length) {
      body.innerHTML = `<div class="card"><div class="empty-state"><p>Inga förfrågningar hittades</p></div></div>`;
      return;
    }
    body.innerHTML = mode === 'kanban' ? kanbanHtml(leads) : tableHtml(leads);
    if (mode === 'kanban') bindKanban(load);
  }

  await load();
}

function leadCard(lead) {
  const objekt = [lead.product_type, lead.size].filter(Boolean).join(' ');
  return `
    <div class="lead-card" draggable="true" data-lead-id="${lead.id}"
         onclick="location.hash='#/sales/${lead.id}'">
      <div class="lead-card-top">
        <strong>${esc(lead.customer_name)}</strong>
        ${isOverdue(lead) ? '<span class="lead-dot" title="Uppföljningsdatum har passerat"></span>' : ''}
      </div>
      ${objekt ? `<div class="lead-card-obj">${esc(objekt)}${lead.quantity > 1 ? ` · ${lead.quantity} st` : ''}</div>` : ''}
      <div class="lead-card-meta">
        ${lead.activity_number ? `<span>#${esc(lead.activity_number)}</span>` : ''}
        ${lead.date_request ? `<span>${fmtD(lead.date_request)}</span>` : ''}
        ${lead.contact_phone ? `<span>${esc(lead.contact_phone)}</span>` : ''}
        ${lead.estimated_value ? `<span>${fmtMoney(lead.estimated_value, lead.currency)}</span>` : ''}
      </div>
      ${lead.last_note ? `<div class="lead-card-note">${fmtD(lead.last_note_date)} · ${esc(lead.last_note).slice(0, 90)}</div>` : ''}
      ${lead.next_followup_date ? `<div class="lead-card-followup ${isOverdue(lead) ? 'overdue' : ''}">Uppföljning ${fmtD(lead.next_followup_date)}</div>` : ''}
    </div>`;
}

function kanbanHtml(leads) {
  return `
    <div class="kanban">
      ${STATUSES.map(s => {
        const inCol = leads.filter(l => l.status === s.key);
        return `
          <div class="kanban-col" data-status="${s.key}">
            <div class="kanban-col-header">
              <span>${s.label}</span>
              <span class="kanban-count">${inCol.length}</span>
            </div>
            <div class="kanban-col-body">
              ${inCol.map(leadCard).join('') || '<div class="kanban-empty">–</div>'}
            </div>
          </div>`;
      }).join('')}
    </div>`;
}

function bindKanban(reload) {
  let draggedId = null;

  document.querySelectorAll('.lead-card').forEach(card => {
    card.addEventListener('dragstart', (e) => {
      draggedId = Number(card.dataset.leadId);
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      // Firefox startar inte draget utan nyttolast
      e.dataTransfer.setData('text/plain', String(draggedId));
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
  });

  document.querySelectorAll('.kanban-col').forEach(col => {
    col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('drag-over'); });
    col.addEventListener('dragleave', () => col.classList.remove('drag-over'));
    col.addEventListener('drop', async (e) => {
      e.preventDefault();
      col.classList.remove('drag-over');
      const id = draggedId || Number(e.dataTransfer.getData('text/plain'));
      const status = col.dataset.status;
      if (!id) return;
      const card = document.querySelector(`.lead-card[data-lead-id="${id}"]`);
      if (card?.closest('.kanban-col')?.dataset.status === status) return;

      // "Såld" är inte bara en statusändring – då ska orderraden skapas
      if (status === 'sald') {
        const lead = await api.get(`/sales/leads/${id}`);
        openConvertForm(lead, reload);
        return;
      }
      try {
        await api.put(`/sales/leads/${id}`, { status });
        showToast(`Flyttad till ${STATUS_LABEL[status]}`, 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

function tableHtml(leads) {
  return `
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Aktivitet</th><th>Kund</th><th>Objekt</th><th>Storlek</th>
            <th>Förfrågan</th><th>Till FFB</th><th>Från FFB</th><th>Till kund</th>
            <th>Status</th><th>Uppföljning</th><th>Telefon</th><th>E-post</th><th>Filer</th>
          </tr></thead>
          <tbody>
            ${leads.map(l => `
              <tr class="clickable" onclick="location.hash='#/sales/${l.id}'">
                <td>${esc(l.activity_number) || '–'}</td>
                <td><strong>${esc(l.customer_name)}</strong></td>
                <td>${esc(l.product_type) || '–'}</td>
                <td>${esc(l.size) || '–'}</td>
                <td>${fmtD(l.date_request)}</td>
                <td>${fmtD(l.date_sent_ffb)}</td>
                <td>${fmtD(l.date_back_ffb)}</td>
                <td>${fmtD(l.date_sent_customer)}</td>
                <td>${salesStatusBadge(l.status)}</td>
                <td class="${isOverdue(l) ? 'text-danger' : 'text-muted'}" style="max-width:280px">
                  ${l.next_followup_date ? `<div>${fmtD(l.next_followup_date)}</div>` : ''}
                  ${l.last_note ? `<div style="font-size:12px">${esc(l.last_note).slice(0, 70)}</div>` : ''}
                </td>
                <td class="text-muted">${esc(l.contact_phone) || '–'}</td>
                <td class="text-muted">${esc(l.contact_email) || '–'}</td>
                <td class="text-muted">${l.file_count || 0}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

// ── Vy 2: sålda ordrar ────────────────────────────────────────────────────────

async function renderOrdersView(host, { archived = false } = {}) {
  const years = await api.get(`/sales/orders/years?archived=${archived}`);
  // Utan årtal ska väljaren stå på "Alla år" och filtret vara tomt – annars visar
  // rubriken ett år som listan i själva verket inte filtrerar på
  let year = years[0] || '';
  let query = '';

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header" style="gap:10px;flex-wrap:wrap">
        <div class="field" style="margin:0;min-width:140px">
          <select id="order-year">
            <option value="">Alla år</option>
            ${years.map(y => `<option value="${y}">${y}</option>`).join('')}
          </select>
        </div>
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="order-search" placeholder="Sök kund, ordernr, reg.nr…">
        </div>
      </div>
    </div>
    ${archived ? `
      <p class="text-muted" style="font-size:13px;margin:-6px 0 14px">
        Avslutade ordrar. De räknas fortfarande med i provisionen – öppna en order och välj
        <strong>Återställ</strong> för att flytta tillbaka den till Sålda ordrar.
      </p>` : ''}
    <div id="order-body"><div class="loading">Laddar…</div></div>
  `;

  const yearSel = document.getElementById('order-year');
  // Har användaren hunnit navigera vidare är värden borta ur DOM:en – avbryt tyst
  if (!yearSel) return;
  yearSel.value = years.length ? String(year) : '';
  yearSel.addEventListener('change', (e) => { year = e.target.value; load(); });

  let timer;
  document.getElementById('order-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = e.target.value; load(); }, 300);
  });

  async function load() {
    const qs = new URLSearchParams();
    if (year) qs.set('year', year);
    if (query) qs.set('q', query);
    if (archived) qs.set('archived', 'true');
    const orders = await api.get(`/sales/orders${qs.toString() ? `?${qs}` : ''}`);
    const body = document.getElementById('order-body');
    if (!body) return;
    if (!orders.length) {
      body.innerHTML = `<div class="card"><div class="empty-state"><p>${archived ? 'Arkivet är tomt' : 'Inga sålda ordrar'}${year ? ` för ${esc(year)}` : ''}</p></div></div>`;
      return;
    }
    body.innerHTML = `
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>#</th><th>Kund</th><th>Ordernr</th><th>Typ</th>
              <th>Pris</th><th>Provision</th><th>Utbet</th>
              <th>Såld</th><th>Pl. lev</th><th>Reg.nr</th><th>Status</th>
            </tr></thead>
            <tbody>
              ${orders.map((o, i) => `
                <tr class="clickable" onclick="location.hash='#/sales-orders/${o.id}'">
                  <td class="text-muted">${o.sort_index ?? i + 1}</td>
                  <td><strong>${esc(o.customer_name)}</strong></td>
                  <td>${esc(o.order_number) || '–'}</td>
                  <td>${esc(o.product_type) || '–'}</td>
                  <td>${fmtMoney(o.price, o.currency)}</td>
                  <td>${fmtMoney(o.commission, o.currency)}</td>
                  <td class="text-muted">${fmtD(o.commission_paid_date)}</td>
                  <td>${fmtD(o.sold_date)}</td>
                  <td>${fmtD(o.planned_delivery)}</td>
                  <td>${esc(o.registration_number) || '–'}</td>
                  <td style="min-width:120px">${progressBar(o.milestones_done, o.milestones_total)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  await load();
}

// ── Vy 3: provision ───────────────────────────────────────────────────────────

async function renderCommissionView(host) {
  const years = await api.get('/sales/orders/years');
  let year = years[0] || '';

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <div class="field" style="margin:0;min-width:140px">
          <select id="comm-year">
            <option value="">Alla år</option>
            ${years.map(y => `<option value="${y}">${y}</option>`).join('')}
          </select>
        </div>
      </div>
    </div>
    <div id="comm-body"><div class="loading">Laddar…</div></div>
  `;

  const sel = document.getElementById('comm-year');
  if (!sel) return;
  sel.value = year ? String(year) : '';
  sel.addEventListener('change', (e) => { year = e.target.value; load(); });

  async function load() {
    const data = await api.get(`/sales/orders/commission${year ? `?year=${year}` : ''}`);
    const body = document.getElementById('comm-body');
    if (!body) return;
    body.innerHTML = `
      <div class="card" style="margin-bottom:16px">
        <div id="comm-stats" class="sales-stats">
          <div class="sales-stat"><span>Ordervärde</span><strong>${fmtMoney(data.total_price, 'EUR')}</strong></div>
          <div class="sales-stat"><span>Provision totalt</span><strong>${fmtMoney(data.total_commission, 'EUR')}</strong></div>
          <div class="sales-stat"><span>Utbetald</span><strong>${fmtMoney(data.paid_commission, 'EUR')}</strong></div>
          <div class="sales-stat"><span>Ej utbetald</span><strong class="text-danger">${fmtMoney(data.unpaid_commission, 'EUR')}</strong></div>
        </div>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Ordernr</th><th>Kund</th><th>Typ</th><th>Såld</th><th>Pris</th><th>Provision</th><th>Utbetald</th></tr></thead>
            <tbody>
              ${data.rows.length ? data.rows.map(r => `
                <tr class="clickable" onclick="location.hash='#/sales-orders/${r.order_id}'">
                  <td>${esc(r.order_number) || '–'}</td>
                  <td><strong>${esc(r.customer_name)}</strong></td>
                  <td>${esc(r.product_type) || '–'}</td>
                  <td>${fmtD(r.sold_date)}</td>
                  <td>${fmtMoney(r.price, 'EUR')}</td>
                  <td>${fmtMoney(r.commission, 'EUR')}</td>
                  <td class="${r.commission_paid_date ? '' : 'text-danger'}">${r.commission_paid_date ? fmtD(r.commission_paid_date) : 'Ej utbetald'}</td>
                </tr>`).join('')
                : '<tr><td colspan="7" style="text-align:center;padding:28px;color:var(--text-3)">Inga ordrar</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  await load();
}

// ── Detaljvy: förfrågan ───────────────────────────────────────────────────────

export async function renderSalesLeadDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const lead = await api.get(`/sales/leads/${id}`);

  const titleEl = document.getElementById('topbar-title');
  if (titleEl) titleEl.textContent = lead.customer_name;

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/sales" class="btn btn-secondary btn-sm">← Tillbaka</a>
    ${printButtons('lead-pdf')}
    <button class="btn btn-secondary btn-sm" id="edit-lead-btn">Redigera</button>
    ${lead.order_id
      ? `<a href="#/sales-orders/${lead.order_id}" class="btn btn-primary btn-sm">Visa order</a>`
      : `<button class="btn btn-primary btn-sm" id="convert-btn">Markera som såld</button>`}
    <button class="btn-icon" id="delete-lead-btn" title="Ta bort förfrågan">${TRASH_ICON}</button>`;

  const objekt = [lead.product_type, lead.size].filter(Boolean).join(' ');

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">${esc(lead.customer_name)} ${salesStatusBadge(lead.status)}</div>
      <div class="page-subtitle">
        ${objekt ? esc(objekt) : 'Ingen objekttyp angiven'}
        ${lead.activity_number ? ` · Aktivitet #${esc(lead.activity_number)}` : ''}
        ${lead.quote_number ? ` · Offert ${esc(lead.quote_number)}` : ''}
      </div>
    </div>

    <div id="lead-gantt" style="margin-bottom:16px"></div>

    <div class="sales-detail">
      <div>
        ${customerCardHtml(lead)}

        <div class="card" style="margin-bottom:16px">
          <div class="card-header"><span class="card-title">Förfrågan</span></div>
          <div class="card-body">
            ${metaRow('Objekt', objekt)}
            ${metaRow('Antal', lead.quantity > 1 ? `${lead.quantity} st` : '')}
            ${metaRow('Offertnummer', lead.quote_number)}
            ${metaRow('Uppskattat värde', lead.estimated_value ? fmtMoney(lead.estimated_value, lead.currency) : '')}
            ${metaRow('Ansvarig', lead.assignee_name)}
            ${metaRow('Nästa uppföljning', lead.next_followup_date ? fmtD(lead.next_followup_date) : '')}
            ${metaRow('Avslutsorsak', lead.lost_reason)}
            ${lead.external_link ? metaRow('Extern länk', lead.external_link) : ''}
            ${lead.notes ? `<hr class="divider"><p style="font-size:13px;color:var(--text-2);white-space:pre-wrap">${esc(lead.notes)}</p>` : ''}
          </div>
        </div>

        <div class="card" style="margin-bottom:16px">
          <div class="card-header"><span class="card-title">Tidslinje</span></div>
          <div class="card-body">
            ${stepRow('Förfrågan inkom', lead.date_request)}
            ${stepRow('Skickad till FFB', lead.date_sent_ffb)}
            ${stepRow('Tillbaka från FFB', lead.date_back_ffb)}
            ${stepRow('Offert skickad till kund', lead.date_sent_customer)}
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <span class="card-title">Filer</span>
            <label class="btn btn-secondary btn-sm" style="margin:0">
              + Ladda upp
              <input type="file" id="lead-file-input" style="display:none">
            </label>
          </div>
          <div id="lead-files">${filesHtml(lead.files)}</div>
        </div>
      </div>

      <div>
        ${notesCardHtml(lead.lead_notes)}
      </div>
    </div>
  `;

  const reload = () => renderSalesLeadDetail(el, id);
  const base = `/sales/leads/${id}`;

  document.getElementById('edit-lead-btn')?.addEventListener('click', () => openLeadForm(lead, reload));
  document.getElementById('convert-btn')?.addEventListener('click', () => openConvertForm(lead, reload));
  bindPrintButtons('lead-pdf', `${base}/pdf`, `forfragan-${id}.pdf`);

  document.getElementById('delete-lead-btn')?.addEventListener('click', async () => {
    // Ordern som skapats ur förfrågan tas bort samtidigt – säg det rakt ut
    const extra = lead.order_id
      ? ` Även den sålda ordern <strong>${esc(lead.order_number || `#${lead.order_id}`)}</strong>`
        + ' med dess milstolpar, AOC och filer tas bort.'
      : '';
    if (!await confirmDialog(
      `Ta bort förfrågan för <strong>${esc(lead.customer_name)}</strong>?${extra} Detta kan inte ångras.`
    )) return;
    try {
      await api.delete(base);
      showToast('Förfrågan borttagen', 'success');
      location.hash = '#/sales';
    } catch (err) { showToast(err.message, 'error'); }
  });

  bindNotes(base, reload, { withFollowup: true });

  document.getElementById('lead-file-input')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      await uploadFile(`${base}/files`, fd);
      showToast('Fil uppladdad', 'success');
      reload();
    } catch (err) { showToast(err.message, 'error'); }
  });

  bindFileActions(id, reload);
  loadSchedule(base, 'lead-gantt', reload);
}

// ── Delat mellan förfrågan och order ──────────────────────────────────────────

const TRASH_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;

/** Kunduppgiftsblocket – identiskt på förfrågan och på såld order. */
function customerCardHtml(obj) {
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header"><span class="card-title">Kund</span></div>
      <div class="card-body">
        ${metaRow('Kund', `<a href="#/customers/${obj.customer_id}" style="color:var(--accent)">${esc(obj.customer_name)}</a>`, true)}
        ${metaRow('Org.nr', obj.customer_org_number)}
        ${metaRow('Telefon', obj.customer_phone)}
        ${metaRow('E-post', obj.customer_email)}
        ${obj.contact_name ? `
          <hr class="divider" style="margin:12px 0">
          ${metaRow('Kontaktperson', obj.contact_name)}
          ${metaRow('Telefon', obj.contact_phone)}
          ${metaRow('E-post', obj.contact_email)}` : ''}
      </div>
    </div>`;
}

function printButtons(idPrefix) {
  return `
    <button class="btn btn-secondary btn-sm" id="${idPrefix}-print" title="Skriv ut">Skriv ut</button>
    <button class="btn-icon" id="${idPrefix}-download" title="Ladda ner som PDF">
      <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
    </button>`;
}

function bindPrintButtons(idPrefix, url, filename) {
  document.getElementById(`${idPrefix}-print`)?.addEventListener('click', async () => {
    try { await printFile(url); } catch (err) { showToast(err.message, 'error'); }
  });
  document.getElementById(`${idPrefix}-download`)?.addEventListener('click', async () => {
    try { await downloadFile(url, filename); } catch (err) { showToast(err.message, 'error'); }
  });
}

/** Hämtar schemat och ritar Gantt. `base` är t.ex. /sales/leads/3. */
async function loadSchedule(base, containerId, reload) {
  const container = document.getElementById(containerId);
  if (!container) return;
  let items = [];
  try {
    items = await api.get(`${base}/schedule`);
  } catch (err) {
    showToast(err.message, 'error');
    return;
  }
  if (!document.getElementById(containerId)) return;

  renderGantt(container, {
    title: 'Schema',
    labelHeader: 'Aktivitet',
    items,
    // Automatiska poster kommer ur datumfälten och redigeras där de hör hemma;
    // bara egna aktiviteter går att klicka på.
    onRowClick: (item) => openActivityForm(base, {
      id: item.activity_id, name: item.name, color: item.color,
      start_date: item.start_date, end_date: item.end_date,
    }, reload),
    emptyHtml: `
      <p class="text-muted" style="font-size:13px;margin:0">
        Inga datum ifyllda än. Datumfälten ritas upp automatiskt, och du kan lägga till
        egna aktiviteter med knappen ovan.
      </p>`,
  });

  // Knappen hakas på kortets rubrik som komponenten just ritade
  const header = container.querySelector('.card-header .gantt2-tools') || container.querySelector('.card-header');
  if (header && !header.querySelector('[data-add-activity]')) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary btn-sm';
    btn.dataset.addActivity = '1';
    btn.textContent = '+ Aktivitet';
    btn.addEventListener('click', () => openActivityForm(base, null, reload));
    header.appendChild(btn);
  }
}

const ACTIVITY_COLORS = ['#E2001A', '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#64748b'];

function openActivityForm(base, activity, onSaved) {
  openModal({
    title: activity?.id ? 'Redigera aktivitet' : 'Ny aktivitet',
    body: `
      <form id="activity-form">
        <div class="field"><label>Namn *</label><input type="text" name="name" value="${esc(activity?.name)}" required autofocus></div>
        <div class="form-row">
          <div class="field"><label>Från</label><input type="date" name="start_date" value="${activity?.start_date || ''}"></div>
          <div class="field"><label>Till</label><input type="date" name="end_date" value="${activity?.end_date || ''}"></div>
        </div>
        <div class="field">
          <label>Färg</label>
          <div class="color-picker" id="activity-colors">
            ${ACTIVITY_COLORS.map(c => `
              <button type="button" class="color-swatch ${(activity?.color || ACTIVITY_COLORS[0]) === c ? 'active' : ''}"
                      data-color="${c}" style="background:${c}" title="${c}"></button>`).join('')}
          </div>
          <input type="hidden" name="color" value="${esc(activity?.color || ACTIVITY_COLORS[0])}">
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          ${activity?.id ? '<button type="button" class="btn btn-danger" id="activity-delete">Ta bort</button>' : ''}
          <div style="flex:1"></div>
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  const colorInput = document.querySelector('#activity-form [name="color"]');
  document.getElementById('activity-colors').addEventListener('click', (e) => {
    const swatch = e.target.closest('[data-color]');
    if (!swatch) return;
    document.querySelectorAll('#activity-colors .color-swatch').forEach(s => s.classList.remove('active'));
    swatch.classList.add('active');
    colorInput.value = swatch.dataset.color;
  });

  document.getElementById('activity-delete')?.addEventListener('click', async () => {
    try {
      await api.delete(`${base}/activities/${activity.id}`);
      showToast('Aktivitet borttagen', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });

  document.getElementById('activity-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      name: fd.get('name'),
      color: fd.get('color'),
      start_date: fd.get('start_date') || null,
      end_date: fd.get('end_date') || null,
    };
    try {
      if (activity?.id) await api.put(`${base}/activities/${activity.id}`, body);
      else await api.post(`${base}/activities`, body);
      showToast('Aktivitet sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

/** Uppföljningskortet. Fungerar likadant på förfrågan och order – på ordern kan
 *  listan även innehålla förfrågans logg, som är historik och inte redigerbar. */
function notesCardHtml(notes) {
  return `
    <div class="card">
      <div class="card-header">
        <span class="card-title">Uppföljning</span>
        <div class="flex gap-2">
          <button class="btn btn-secondary btn-sm" data-note-kind="samtal">Ringt</button>
          <button class="btn btn-secondary btn-sm" data-note-kind="mail">Mailat</button>
          <button class="btn btn-secondary btn-sm" data-note-kind="mote">Möte</button>
          <button class="btn btn-primary btn-sm" data-note-kind="anteckning">Anteckning</button>
        </div>
      </div>
      <div class="card-body" id="notes-body">${notesHtml(notes)}</div>
    </div>`;
}

function bindNotes(base, reload, { withFollowup = false } = {}) {
  document.querySelectorAll('[data-note-kind]').forEach(btn => {
    btn.addEventListener('click', () => openNoteForm(base, btn.dataset.noteKind, reload, { withFollowup }));
  });
  document.querySelectorAll('[data-del-note]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort anteckningen?')) return;
      try {
        await api.delete(`${base}/notes/${btn.dataset.delNote}`);
        showToast('Anteckning borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

function stepRow(label, value) {
  return `
    <div class="step-row ${value ? 'done' : ''}">
      <span class="step-dot"></span>
      <span class="step-label">${esc(label)}</span>
      <span class="step-date">${fmtD(value)}</span>
    </div>`;
}

function metaRow(label, value, raw = false) {
  if (!value) return '';
  return `<div class="meta-row"><span class="meta-label">${esc(label)}:</span><span>${raw ? value : esc(value)}</span></div>`;
}

function notesHtml(notes) {
  if (!notes?.length) return '<div class="empty-state" style="padding:28px"><p>Ingen uppföljning ännu</p></div>';
  return `
    <div class="timeline">
      ${notes.map(n => `
        <div class="timeline-item">
          <div class="timeline-head">
            <span class="badge badge-note-${esc(n.kind)}">${esc(NOTE_KINDS[n.kind] || n.kind)}</span>
            <span class="text-muted">${fmtD(n.note_date)}</span>
            ${n.created_by_name ? `<span class="text-muted">· ${esc(n.created_by_name)}</span>` : ''}
            ${n.from_lead ? '<span class="text-muted" style="font-size:11px">· från förfrågan</span>' : ''}
            <div style="flex:1"></div>
            ${n.from_lead ? '' : `<button type="button" class="btn-icon" title="Ta bort" data-del-note="${n.id}">
              ${TRASH_ICON}
            </button>`}
          </div>
          <div class="timeline-body">${esc(n.body)}</div>
        </div>`).join('')}
    </div>`;
}

function filesHtml(files) {
  if (!files?.length) return '<div class="empty-state" style="padding:28px"><p>Inga filer uppladdade</p></div>';
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Fil</th><th>Storlek</th><th>Uppladdad</th><th></th></tr></thead>
        <tbody>
          ${files.map(f => `
            <tr>
              <td><strong>${esc(f.original_name)}</strong></td>
              <td class="text-muted">${f.size_bytes ? `${Math.round(f.size_bytes / 1024)} kB` : '–'}</td>
              <td class="text-muted">${fmtD(f.uploaded_at)}</td>
              <td>
                <div class="flex gap-2">
                  <button type="button" class="btn btn-secondary btn-sm" data-dl-file="${f.id}" data-name="${esc(f.original_name)}">Hämta</button>
                  <button type="button" class="btn-icon" title="Ta bort" data-del-file="${f.id}">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                  </button>
                </div>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function bindFileActions(leadId, reload) {
  document.querySelectorAll('[data-dl-file]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await downloadFile(`/sales/leads/${leadId}/files/${btn.dataset.dlFile}/download`, btn.dataset.name);
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
  document.querySelectorAll('[data-del-file]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort filen?')) return;
      try {
        await api.delete(`/sales/leads/${leadId}/files/${btn.dataset.delFile}`);
        showToast('Fil borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

function openNoteForm(base, kind, onSaved, { withFollowup = false } = {}) {
  openModal({
    title: NOTE_KINDS[kind] || 'Anteckning',
    body: `
      <form id="note-form">
        <div class="form-row">
          <div class="field"><label>Datum</label><input type="date" name="note_date" value="${todayISO()}"></div>
          ${withFollowup ? '<div class="field"><label>Nästa uppföljning</label><input type="date" name="next_followup_date"></div>' : ''}
        </div>
        <div class="field"><label>Vad hände? *</label><textarea name="body" rows="4" required autofocus></textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  document.getElementById('note-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api.post(`${base}/notes`, {
        kind,
        note_date: fd.get('note_date') || null,
        body: fd.get('body'),
      });
      // Uppföljningsdatumet ligger på förfrågan, inte på anteckningen – spara det separat
      if (withFollowup && fd.get('next_followup_date')) {
        await api.put(base, { next_followup_date: fd.get('next_followup_date') });
      }
      showToast('Uppföljning sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Formulär: förfrågan ───────────────────────────────────────────────────────

export async function openLeadForm(lead, onSaved) {
  const [customers, users, types] = await Promise.all([
    api.get('/customers'),
    api.get('/users').catch(() => []),
    productTypes(),
  ]);

  openModal({
    title: lead ? 'Redigera förfrågan' : 'Ny offertförfrågan',
    size: 'modal-lg',
    body: `
      <form id="lead-form">
        <div class="form-row">
          <div class="field" style="flex:2">
            <label>Kund *</label>
            <div class="flex gap-2">
              <select name="customer_id" id="lead-customer" required style="flex:1">
                <option value="">Välj kund…</option>
                ${customers.map(c => `<option value="${c.id}" ${lead?.customer_id === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
              </select>
              <button type="button" class="btn btn-secondary btn-sm" id="new-customer-inline">+ Ny</button>
            </div>
          </div>
          <div class="field">
            <label>Kontaktperson</label>
            <select name="contact_person_id" id="lead-contact"><option value="">–</option></select>
          </div>
        </div>

        <div class="form-row">
          <div class="field"><label>Aktivitetsnr</label><input type="text" name="activity_number" value="${esc(lead?.activity_number)}"></div>
          <div class="field">
            <label>Objekt</label>
            <select name="product_type">
              <option value="">–</option>
              ${types.map(t => `<option value="${esc(t)}" ${lead?.product_type === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}
              ${lead?.product_type && !types.includes(lead.product_type)
                ? `<option value="${esc(lead.product_type)}" selected>${esc(lead.product_type)}</option>` : ''}
            </select>
          </div>
          <div class="field"><label>Storlek</label><input type="text" name="size" value="${esc(lead?.size)}"></div>
          <div class="field"><label>Antal</label><input type="number" name="quantity" min="1" value="${lead?.quantity || 1}"></div>
        </div>

        <div class="form-row">
          <div class="field">
            <label>Status</label>
            <select name="status">
              ${STATUSES.map(s => `<option value="${s.key}" ${(lead?.status || 'ny') === s.key ? 'selected' : ''}>${s.label}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Offertnummer</label><input type="text" name="quote_number" value="${esc(lead?.quote_number)}"></div>
          <div class="field"><label>Uppskattat värde</label><input type="number" step="0.01" name="estimated_value" value="${lead?.estimated_value ?? ''}"></div>
          <div class="field"><label>Valuta</label><input type="text" name="currency" value="${esc(lead?.currency || 'EUR')}"></div>
        </div>

        <div class="form-row">
          <div class="field"><label>Datum förfrågan</label><input type="date" name="date_request" value="${lead?.date_request || todayISO()}"></div>
          <div class="field"><label>Skickad till FFB</label><input type="date" name="date_sent_ffb" value="${lead?.date_sent_ffb || ''}"></div>
          <div class="field"><label>Tillbaka från FFB</label><input type="date" name="date_back_ffb" value="${lead?.date_back_ffb || ''}"></div>
          <div class="field"><label>Skickad till kund</label><input type="date" name="date_sent_customer" value="${lead?.date_sent_customer || ''}"></div>
        </div>

        <div class="form-row">
          <div class="field"><label>Nästa uppföljning</label><input type="date" name="next_followup_date" value="${lead?.next_followup_date || ''}"></div>
          <div class="field">
            <label>Ansvarig</label>
            <select name="assigned_to">
              <option value="">–</option>
              ${users.map(u => `<option value="${u.id}">${esc(u.full_name)}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Avslutsorsak</label><input type="text" name="lost_reason" value="${esc(lead?.lost_reason)}"></div>
        </div>

        <div class="field"><label>Extern länk (gammal filserversökväg)</label><input type="text" name="external_link" value="${esc(lead?.external_link)}"></div>
        <div class="field"><label>Anteckningar</label><textarea name="notes" rows="3">${esc(lead?.notes)}</textarea></div>

        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${lead ? 'Spara' : 'Skapa förfrågan'}</button>
        </div>
      </form>`,
  });

  // Ansvarig sätts efter render – lead saknar assigned_to i listvyn men har det i detaljvyn
  const assignedSel = document.querySelector('#lead-form [name="assigned_to"]');
  if (lead?.assigned_to) assignedSel.value = String(lead.assigned_to);

  const customerSel = document.getElementById('lead-customer');
  const contactSel = document.getElementById('lead-contact');

  async function loadContacts(selectedId) {
    contactSel.innerHTML = '<option value="">–</option>';
    if (!customerSel.value) return;
    try {
      const contacts = await api.get(`/customers/${customerSel.value}/contacts`);
      contactSel.innerHTML = '<option value="">–</option>' + contacts.map(c =>
        `<option value="${c.id}" ${String(selectedId) === String(c.id) ? 'selected' : ''}>${esc(c.name)}${c.email ? ` – ${esc(c.email)}` : ''}</option>`
      ).join('');
    } catch { /* kunden kan sakna kontaktpersoner – listan förblir tom */ }
  }
  customerSel.addEventListener('change', () => loadContacts(null));
  await loadContacts(lead?.contact_person_id);

  document.getElementById('new-customer-inline').addEventListener('click', () => {
    // Kundformuläret återanvänds rakt av; när det stängs öppnas förfrågan igen
    // med den nya kunden förvald så att inget ifyllt går förlorat i onödan.
    const draft = collectLeadForm();
    openCustomerForm(null, async () => {
      const fresh = await api.get('/customers');
      const newest = fresh.reduce((a, b) => (a.id > b.id ? a : b), fresh[0]);
      await openLeadForm({ ...(lead || {}), ...draft, customer_id: newest?.id, id: lead?.id }, onSaved);
    });
  });

  function collectLeadForm() {
    const fd = new FormData(document.getElementById('lead-form'));
    const body = {};
    for (const [k, v] of fd.entries()) body[k] = v === '' ? null : v;
    if (body.customer_id) body.customer_id = Number(body.customer_id);
    if (body.contact_person_id) body.contact_person_id = Number(body.contact_person_id);
    if (body.assigned_to) body.assigned_to = Number(body.assigned_to);
    if (body.quantity) body.quantity = Number(body.quantity);
    return body;
  }

  document.getElementById('lead-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = collectLeadForm();
    if (!body.customer_id) { showToast('Välj en kund', 'error'); return; }
    try {
      if (lead?.id) {
        await api.put(`/sales/leads/${lead.id}`, body);
        showToast('Förfrågan uppdaterad', 'success');
      } else {
        await api.post('/sales/leads', body);
        showToast('Förfrågan skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Formulär: konvertera till order ───────────────────────────────────────────

function openConvertForm(lead, onSaved) {
  openModal({
    title: 'Markera som såld',
    body: `
      <form id="convert-form">
        <p style="margin-bottom:16px;color:var(--text-2);font-size:13px">
          Förfrågan flyttas till <strong>Sålda ordrar</strong> och får en checklista med alla milstolpar.
        </p>
        <div class="form-row">
          <div class="field"><label>Ordernummer</label><input type="text" name="order_number" placeholder="N071010" autofocus></div>
          <div class="field"><label>Datum såld</label><input type="date" name="sold_date" value="${todayISO()}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Pris</label><input type="number" step="0.01" name="price" value="${lead.estimated_value ?? ''}"></div>
          <div class="field"><label>Provision</label><input type="number" step="0.01" name="commission"></div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Skapa order</button>
        </div>
      </form>`,
  });

  document.getElementById('convert-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {};
    for (const [k, v] of fd.entries()) body[k] = v === '' ? null : v;
    try {
      const order = await api.post(`/sales/leads/${lead.id}/convert`, body);
      showToast('Order skapad', 'success');
      closeModal();
      location.hash = `#/sales-orders/${order.id}`;
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Detaljvy: order ───────────────────────────────────────────────────────────

// AOC ligger där de fyra gamla AOC-milstolparna låg (sort_order 160–190), så
// avsnittet hamnar mellan Registrering och Fakturering precis som i Excel.
const AOC_SECTION_ORDER = 160;

export async function renderSalesOrderDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const order = await api.get(`/sales/orders/${id}`);

  const titleEl = document.getElementById('topbar-title');
  if (titleEl) titleEl.textContent = order.order_number || order.customer_name;

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/sales?view=${order.archived_at ? 'archive' : 'orders'}" class="btn btn-secondary btn-sm">← Tillbaka</a>
    ${order.lead_id ? `<a href="#/sales/${order.lead_id}" class="btn btn-secondary btn-sm">Visa förfrågan</a>` : ''}
    ${printButtons('order-pdf')}
    <button class="btn btn-secondary btn-sm" id="edit-order-btn">Redigera</button>
    ${order.archived_at
      ? `<button class="btn btn-primary btn-sm" id="unarchive-btn">Återställ</button>`
      : `<button class="btn btn-primary btn-sm" id="archive-btn">Avsluta &amp; arkivera</button>`}
    <button class="btn-icon" id="delete-order-btn" title="Ta bort order">${TRASH_ICON}</button>`;

  // Avsnitten är milstolpsgrupperna plus AOC. Milstolparna kommer sorterade från
  // API:et, så gruppens plats ges av dess första milstolpe.
  const sections = [];
  for (const m of order.milestones) {
    let g = sections.find(x => x.label === m.group_label);
    if (!g) {
      g = { label: m.group_label, order: m.sort_order, items: [] };
      sections.push(g);
    }
    g.items.push(m);
  }
  sections.push({ label: 'AOC', order: AOC_SECTION_ORDER, aoc: true, items: [] });
  sections.sort((a, b) => a.order - b.order);

  // Bilagor som hör till ett avsnitt. AOC-filerna följer med sitt eget intyg.
  const filesByGroup = {};
  for (const f of order.files || []) {
    const key = f.group_label || '';
    (filesByGroup[key] = filesByGroup[key] || []).push(f);
  }

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">${esc(order.order_number || 'Order utan nummer')}</div>
      <div class="page-subtitle">
        <a href="#/customers/${order.customer_id}" style="color:var(--accent)">${esc(order.customer_name)}</a>
        ${order.product_type ? ` · ${esc(order.product_type)}` : ''}
        ${order.sold_date ? ` · Såld ${fmtD(order.sold_date)}` : ''}
      </div>
    </div>

    ${order.archived_at ? `
      <div class="alert" style="margin-bottom:16px;background:var(--surface-2);border:1px solid var(--border);color:var(--text-2)">
        Arkiverad ${fmtD(order.archived_at)} – ordern ligger under fliken Arkiv.
      </div>` : ''}

    <div class="order-top">
      ${customerCardHtml(order)}

    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <span class="card-title">Orderuppgifter</span>
        <div id="order-progress" style="min-width:180px">${progressBar(order.milestones_done, order.milestones_total)}</div>
      </div>
      <div class="card-body order-meta">
        ${metaRow('Tillverkningsnr', order.serial_number)}
        ${metaRow('Typ', order.product_type)}
        ${metaRow('Pris', order.price ? fmtMoney(order.price, order.currency) : '')}
        ${metaRow('Provision', order.commission ? fmtMoney(order.commission, order.currency) : '')}
        ${metaRow('Provision utbetald', order.commission_paid_date ? fmtD(order.commission_paid_date) : '')}
        ${metaRow('Datum såld', order.sold_date ? fmtD(order.sold_date) : '')}
        ${metaRow('Planerad leverans', order.planned_delivery ? fmtD(order.planned_delivery) : '')}
        ${metaRow('Vecka', order.delivery_week)}
        ${metaRow('Levererad kund', order.delivery_date ? fmtD(order.delivery_date) : '')}
        ${metaRow('Reg.nr', order.registration_number)}
        ${metaRow('Vikt', order.weight_kg ? `${order.weight_kg} kg` : '')}
        ${metaRow('Besök hos FFB', order.visit_ffb ? 'Ja' : '')}
        ${order.notes ? `<hr class="divider"><p style="font-size:13px;color:var(--text-2);white-space:pre-wrap">${esc(order.notes)}</p>` : ''}
      </div>
    </div>
    </div>

    <div id="order-gantt" style="margin-bottom:16px"></div>

    <div class="milestone-grid">
      ${sections.map(sec => sec.aoc
        ? aocSectionHtml(order.aocs || [])
        : sectionHtml(sec, filesByGroup[sec.label] || [])
      ).join('')}
    </div>

    <div style="margin-top:16px">
      ${notesCardHtml(order.order_notes)}
    </div>
  `;

  const reload = () => renderSalesOrderDetail(el, id);
  const base = `/sales/orders/${id}`;

  document.getElementById('edit-order-btn').addEventListener('click', () => openOrderForm(order, reload));
  bindPrintButtons('order-pdf', `${base}/pdf`, `order-${id}.pdf`);
  bindNotes(base, reload);

  document.getElementById('archive-btn')?.addEventListener('click', async () => {
    if (!await confirmDialog(
      `Avsluta och arkivera <strong>${esc(order.order_number || 'ordern')}</strong>? ` +
      'Den flyttas till Arkiv men räknas fortfarande med i provisionen.', 'Arkivera'
    )) return;
    try {
      await api.post(`${base}/archive`, {});
      showToast('Order arkiverad', 'success');
      reload();
    } catch (err) { showToast(err.message, 'error'); }
  });

  document.getElementById('unarchive-btn')?.addEventListener('click', async () => {
    try {
      await api.post(`${base}/unarchive`, {});
      showToast('Order återställd', 'success');
      reload();
    } catch (err) { showToast(err.message, 'error'); }
  });

  document.getElementById('delete-order-btn')?.addEventListener('click', async () => {
    if (!await confirmDialog(
      `Ta bort ordern <strong>${esc(order.order_number || '')}</strong> med milstolpar, AOC och filer? ` +
      'Detta kan inte ångras.'
    )) return;
    try {
      await api.delete(base);
      showToast('Order borttagen', 'success');
      location.hash = '#/sales?view=orders';
    } catch (err) { showToast(err.message, 'error'); }
  });

  bindOrderSections(el, id, reload);
  loadSchedule(base, 'order-gantt', reload);
}

/** Ett vanligt avsnittskort: milstolpar överst, bilagor underst. */
function sectionHtml(sec, files) {
  return `
    <div class="card">
      <div class="card-header">
        <span class="card-title">${esc(sec.label)}</span>
        ${uploadButton({ group: sec.label })}
      </div>
      <div class="card-body">
        ${sec.items.map(milestoneField).join('')}
        ${sectionFilesHtml(files)}
      </div>
    </div>`;
}

/** AOC-kortet: ett block per intyg, vart och ett med egna fält och egna filer. */
function aocSectionHtml(aocs) {
  return `
    <div class="card">
      <div class="card-header">
        <span class="card-title">AOC</span>
        <button type="button" class="btn btn-secondary btn-sm" id="add-aoc-btn">+ Lägg till AOC</button>
      </div>
      <div class="card-body">
        ${aocs.length ? aocs.map(aocHtml).join('') : `
          <p style="font-size:13px;color:var(--text-3);margin:4px 0">
            Inga AOC-intyg ännu. En order kan ha flera – lägg till ett per intyg.
          </p>`}
      </div>
    </div>`;
}

function aocHtml(a) {
  return `
    <div class="aoc-item" data-aoc-id="${a.id}">
      <div class="aoc-head">
        <input type="text" class="aoc-nr" data-aoc-field="aoc_number"
               value="${esc(a.aoc_number)}" placeholder="AOC-nr, t.ex. NB001">
        <div style="flex:1"></div>
        ${uploadButton({ aocId: a.id })}
        <button type="button" class="btn-icon" title="Ta bort AOC" data-del-aoc="${a.id}">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        </button>
      </div>
      <div class="ms-row">
        <label class="ms-label">Skickad – kund</label>
        <input type="date" data-aoc-field="sent_customer" value="${a.sent_customer || ''}">
      </div>
      <div class="ms-row">
        <label class="ms-label">Mailat – FFB</label>
        <input type="date" data-aoc-field="mailed_ffb" value="${a.mailed_ffb || ''}">
      </div>
      <div class="ms-row">
        <label class="ms-label">Kostnad EUR</label>
        <input type="number" step="0.01" data-aoc-field="cost_eur" value="${a.cost_eur ?? ''}">
      </div>
      ${a.notes ? `<div class="aoc-notes">${esc(a.notes)}</div>` : ''}
      ${sectionFilesHtml(a.files || [])}
    </div>`;
}

/** Uppladdningsknapp. Filinputen ligger inuti etiketten, så ingen id-jonglering behövs. */
function uploadButton({ group = null, aocId = null }) {
  const attrs = aocId !== null
    ? `data-upload-aoc="${aocId}"`
    : `data-upload-group="${esc(group)}"`;
  return `
    <label class="btn btn-secondary btn-sm upload-btn" style="margin:0" title="Ladda upp fil">
      + Fil<input type="file" ${attrs} style="display:none">
    </label>`;
}

function sectionFilesHtml(files) {
  if (!files.length) return '';
  return `
    <div class="section-files">
      ${files.map(f => `
        <div class="section-file">
          <svg viewBox="0 0 20 20" fill="currentColor" style="width:13px;height:13px;flex:none;opacity:.5">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"/>
          </svg>
          <button type="button" class="link-btn" data-dl-order-file="${f.id}" data-name="${esc(f.original_name)}">${esc(f.original_name)}</button>
          <span class="text-muted" style="font-size:11.5px">${f.size_bytes ? `${Math.round(f.size_bytes / 1024)} kB` : ''}</span>
          <button type="button" class="btn-icon" title="Ta bort" data-del-order-file="${f.id}">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
          </button>
        </div>`).join('')}
    </div>`;
}

function bindOrderSections(el, id, reload) {
  // Direktsparande vid change – samma känsla som att fylla i en Excel-cell
  el.querySelectorAll('[data-ms-def]').forEach(input => {
    input.addEventListener('change', async () => {
      const defId = input.dataset.msDef;
      const type = input.dataset.msType;
      const body = type === 'datum' ? { value_date: input.value || null }
        : type === 'ja_nej' ? { completed: input.checked }
        : { value_text: input.value || null };
      try {
        await api.put(`/sales/orders/${id}/milestones/${defId}`, body);
        input.closest('.ms-row')?.classList.toggle('done', !!(input.value || input.checked));
        await refreshProgress(id);
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // AOC-fälten sparas likadant, men mot sitt intyg
  el.querySelectorAll('[data-aoc-field]').forEach(input => {
    input.addEventListener('change', async () => {
      const aocId = input.closest('.aoc-item')?.dataset.aocId;
      if (!aocId) return;
      try {
        await api.put(`/sales/orders/${id}/aocs/${aocId}`, {
          [input.dataset.aocField]: input.value || null,
        });
        showToast('AOC sparat', 'success', 1500);
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  document.getElementById('add-aoc-btn')?.addEventListener('click', async () => {
    try {
      await api.post(`/sales/orders/${id}/aocs`, {});
      reload();
    } catch (err) { showToast(err.message, 'error'); }
  });

  el.querySelectorAll('[data-del-aoc]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort AOC-intyget och dess filer?')) return;
      try {
        await api.delete(`/sales/orders/${id}/aocs/${btn.dataset.delAoc}`);
        showToast('AOC borttaget', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Uppladdning per avsnitt respektive per AOC
  el.querySelectorAll('.upload-btn input[type="file"]').forEach(input => {
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      const qs = input.dataset.uploadAoc !== undefined
        ? `aoc_id=${encodeURIComponent(input.dataset.uploadAoc)}`
        : `group=${encodeURIComponent(input.dataset.uploadGroup)}`;
      const fd = new FormData();
      fd.append('file', file);
      try {
        await uploadFile(`/sales/orders/${id}/files?${qs}`, fd);
        showToast('Fil uppladdad', 'success');
        reload();
      } catch (err) {
        showToast(err.message, 'error');
        input.value = '';   // annars går samma fil inte att välja igen
      }
    });
  });

  el.querySelectorAll('[data-dl-order-file]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await downloadFile(`/sales/orders/${id}/files/${btn.dataset.dlOrderFile}/download`, btn.dataset.name);
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  el.querySelectorAll('[data-del-order-file]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort filen?')) return;
      try {
        await api.delete(`/sales/orders/${id}/files/${btn.dataset.delOrderFile}`);
        showToast('Fil borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

/** Servern räknar om andelen klara milstolpar – hämta den istället för att gissa. */
async function refreshProgress(id) {
  const holder = document.getElementById('order-progress');
  if (!holder) return;
  try {
    const fresh = await api.get(`/sales/orders/${id}`);
    if (document.getElementById('order-progress')) {
      holder.innerHTML = progressBar(fresh.milestones_done, fresh.milestones_total);
    }
  } catch { /* stapeln är kosmetisk – ett misslyckat anrop ska inte störa */ }
}

function milestoneField(m) {
  const done = m.completed ? 'done' : '';
  if (m.value_type === 'ja_nej') {
    return `
      <div class="ms-row ${done}">
        <label class="ms-label">${esc(m.label)}</label>
        <input type="checkbox" data-ms-def="${m.def_id}" data-ms-type="ja_nej" ${m.completed ? 'checked' : ''}>
      </div>`;
  }
  if (m.value_type === 'text') {
    return `
      <div class="ms-row ${done}">
        <label class="ms-label">${esc(m.label)}</label>
        <input type="text" data-ms-def="${m.def_id}" data-ms-type="text" value="${esc(m.value_text)}">
      </div>`;
  }
  return `
    <div class="ms-row ${done}">
      <label class="ms-label">${esc(m.label)}</label>
      <input type="date" data-ms-def="${m.def_id}" data-ms-type="datum" value="${m.value_date || ''}">
    </div>`;
}

async function openOrderForm(order, onSaved) {
  const customers = await api.get('/customers');
  openModal({
    title: 'Redigera order',
    size: 'modal-lg',
    body: `
      <form id="order-form">
        <div class="form-row">
          <div class="field">
            <label>Kund *</label>
            <select name="customer_id" required>
              ${customers.map(c => `<option value="${c.id}" ${order.customer_id === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Ordernummer</label><input type="text" name="order_number" value="${esc(order.order_number)}"></div>
          <div class="field"><label>Tillverkningsnr</label><input type="text" name="serial_number" value="${esc(order.serial_number)}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Typ</label><input type="text" name="product_type" value="${esc(order.product_type)}"></div>
          <div class="field"><label>Pris</label><input type="number" step="0.01" name="price" value="${order.price ?? ''}"></div>
          <div class="field"><label>Provision</label><input type="number" step="0.01" name="commission" value="${order.commission ?? ''}"></div>
          <div class="field"><label>Valuta</label><input type="text" name="currency" value="${esc(order.currency || 'EUR')}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Datum såld</label><input type="date" name="sold_date" value="${order.sold_date || ''}"></div>
          <div class="field"><label>Provision utbetald</label><input type="date" name="commission_paid_date" value="${order.commission_paid_date || ''}"></div>
          <div class="field"><label>Planerad leverans</label><input type="date" name="planned_delivery" value="${order.planned_delivery || ''}"></div>
          <div class="field"><label>Vecka</label><input type="text" name="delivery_week" value="${esc(order.delivery_week)}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Levererad kund</label><input type="date" name="delivery_date" value="${order.delivery_date || ''}"></div>
          <div class="field"><label>Reg.nr</label><input type="text" name="registration_number" value="${esc(order.registration_number)}"></div>
          <div class="field"><label>Vikt (kg)</label><input type="number" name="weight_kg" value="${order.weight_kg ?? ''}"></div>
          <div class="field"><label>Löpnr</label><input type="number" name="sort_index" value="${order.sort_index ?? ''}"></div>
        </div>
        <div class="field">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" name="visit_ffb" ${order.visit_ffb ? 'checked' : ''}> Besök hos FFB
          </label>
        </div>
        <div class="field"><label>Anteckningar</label><textarea name="notes" rows="3">${esc(order.notes)}</textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  document.getElementById('order-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {};
    for (const [k, v] of fd.entries()) body[k] = v === '' ? null : v;
    body.customer_id = Number(body.customer_id);
    body.visit_ffb = fd.get('visit_ffb') === 'on';
    if (body.weight_kg) body.weight_kg = Number(body.weight_kg);
    if (body.sort_index) body.sort_index = Number(body.sort_index);
    try {
      await api.put(`/sales/orders/${order.id}`, body);
      showToast('Order uppdaterad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Kundkortets flik "Affärer" ────────────────────────────────────────────────

export async function renderCustomerSales(host, customerId) {
  const [leads, orders] = await Promise.all([
    api.get(`/sales/leads?customer_id=${customerId}`).catch(() => []),
    api.get(`/sales/orders?customer_id=${customerId}`).catch(() => []),
  ]);

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header"><span class="card-title">Offertförfrågningar</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Aktivitet</th><th>Objekt</th><th>Förfrågan</th><th>Status</th><th>Uppföljning</th></tr></thead>
          <tbody>
            ${leads.length ? leads.map(l => `
              <tr class="clickable" onclick="location.hash='#/sales/${l.id}'">
                <td>${esc(l.activity_number) || '–'}</td>
                <td>${esc([l.product_type, l.size].filter(Boolean).join(' ')) || '–'}</td>
                <td>${fmtD(l.date_request)}</td>
                <td>${salesStatusBadge(l.status)}</td>
                <td class="text-muted">${fmtD(l.next_followup_date)}</td>
              </tr>`).join('')
              : '<tr><td colspan="5" style="text-align:center;padding:28px;color:var(--text-3)">Inga förfrågningar</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Sålda ordrar</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Ordernr</th><th>Typ</th><th>Såld</th><th>Pris</th><th>Status</th></tr></thead>
          <tbody>
            ${orders.length ? orders.map(o => `
              <tr class="clickable" onclick="location.hash='#/sales-orders/${o.id}'">
                <td><strong>${esc(o.order_number) || '–'}</strong></td>
                <td>${esc(o.product_type) || '–'}</td>
                <td>${fmtD(o.sold_date)}</td>
                <td>${fmtMoney(o.price, o.currency)}</td>
                <td style="min-width:120px">${progressBar(o.milestones_done, o.milestones_total)}</td>
              </tr>`).join('')
              : '<tr><td colspan="5" style="text-align:center;padding:28px;color:var(--text-3)">Inga ordrar</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>`;
}
