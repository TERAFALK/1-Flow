import { api } from '../api.js';
import { statusBadge, fmtDate } from '../app.js';
import { renderBarChart } from '../components/barchart.js';

// Datumen från API:et är rena YYYY-MM-DD. fmtDate i app.js klistrar på ett Z och
// ger Invalid Date på dem, så de formateras lokalt – samma grepp som i sales.js.
function fmtD(d) {
  if (!d) return '–';
  return String(d).slice(0, 10);
}

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtMoney(value, currency) {
  const n = Number(value) || 0;
  return `${n.toLocaleString('sv-SE', { maximumFractionDigits: 0 })} ${esc(currency || '')}`.trim();
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(String(iso).endsWith('Z') ? iso : iso + 'Z');
  return isNaN(d) ? '' : d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' });
}

const WO_STATUS_LABELS = {
  ny: 'Ny', planerad: 'Planerad', pagaende: 'Pågående', klar: 'Klar', fakturerad: 'Fakturerad',
};

export async function renderDashboard(el) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const d = await api.get('/dashboard');

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/work-orders/new" class="btn btn-primary btn-sm">
      <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
      Ny order
    </a>`;

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Översikt</div>
    <div class="page-subtitle" style="margin-bottom:20px">Verkstad och försäljning</div>

    ${actionRowHtml(d)}

    <div class="overview-grid" style="margin-bottom:16px">
      ${workshopPanelHtml(d)}
      ${chartPanelHtml(d)}
    </div>

    <div class="overview-grid" style="margin-bottom:16px">
      ${(d.sales || []).map(salesPanelHtml).join('')}
    </div>

    <div class="overview-grid">
      ${recentOrdersHtml(d)}
      ${upcomingHtml(d)}
    </div>
  `;

  bindChart(d);
}

// ── Kräver åtgärd ─────────────────────────────────────────────────────────────

/** Siffror man inte kan klicka på är återvändsgränder – varje kort går vidare. */
function actionRowHtml(d) {
  const cards = [
    {
      label: 'Uppföljningar passerade', value: d.overdue_followups,
      sub: 'Förfrågningar som väntar på dig', href: '#/sales',
    },
    {
      label: 'Förfallna uppgifter', value: d.overdue_tasks,
      sub: 'Arbetsorder, offerter och kunder', href: '#/tasks?scope=overdue',
    },
    {
      label: 'Schemalagda idag', value: d.scheduled_today,
      sub: 'Planerade för idag', href: '#/calendar', neutral: true,
    },
    {
      label: 'Klara att fakturera', value: d.ready_to_invoice,
      sub: 'Väntar på fakturering', href: '#/work-orders', neutral: true,
    },
  ];
  return `
    <div class="stat-grid">
      ${cards.map(c => `
        <a class="stat-card action-card ${!c.neutral && c.value > 0 ? 'accent' : ''}" href="${c.href}">
          <div class="stat-label">${esc(c.label)}</div>
          <div class="stat-value">${c.value}</div>
          <div class="stat-sub">${esc(c.sub)}</div>
        </a>`).join('')}
    </div>`;
}

// ── Verkstaden ────────────────────────────────────────────────────────────────

function workshopPanelHtml(d) {
  const by = d.by_status || {};
  const timers = d.active_timers || [];
  return `
    <div class="overview-panel">
      <div class="overview-header">
        <span class="overview-title">Verkstaden</span>
        <a href="#/work-orders" class="btn btn-ghost btn-sm">Visa alla</a>
      </div>
      <div class="overview-body">
        ${statCell('Öppna arbetsorder', d.total_open, 'ok')}
        ${statCell('Pågående', by.pagaende || 0, (by.pagaende || 0) > 0 ? 'warn' : 'ok')}
        ${statCell('Klara denna vecka', d.completed_this_week, 'success')}
        ${statCell('Fakturerade totalt', by.fakturerad || 0, 'ok')}
      </div>
      <div class="panel-foot">
        ${timers.length ? `
          <div class="timer-list">
            ${timers.map(t => `
              <a class="timer-row" href="#/work-orders/${t.order_id}">
                <span class="timer-dot"></span>
                <strong>${esc(t.user_name)}</strong>
                <span class="text-muted">${esc(t.order_number)}</span>
                <span class="text-muted" style="margin-left:auto">sedan ${fmtTime(t.started_at)}</span>
              </a>`).join('')}
          </div>`
          : '<p class="text-muted" style="font-size:12.5px;margin:0">Ingen tidtagning igång just nu</p>'}
      </div>
    </div>`;
}

function statCell(label, value, tone = 'ok') {
  return `
    <div class="overview-stat">
      <div class="overview-stat-label">${esc(label)}</div>
      <div class="overview-stat-value ${tone}">${value}</div>
    </div>`;
}

// ── Sålt värde per månad ──────────────────────────────────────────────────────

// Feldbinder räknas i EUR och verkstadsjobb i SEK. Staplar i olika valutor bredvid
// varandra hade sett jämförbara ut utan att vara det, så grafen ritar en serie i
// taget med egen skala. Vi har ingen växelkurs och ska inte hitta på en.
const SERIES = {
  feldbinder: { label: 'Feldbinder', currency: 'EUR', color: 'var(--accent)' },
  verkstad:   { label: 'Offerter',   currency: 'SEK', color: '#2563eb' },
};

function chartPanelHtml(d) {
  return `
    <div class="overview-panel">
      <div class="overview-header">
        <span class="overview-title">Sålt värde per månad</span>
        <div class="chart-toggle" id="chart-toggle">
          ${Object.entries(SERIES).map(([key, s], i) =>
            `<button type="button" data-series="${key}" class="${i === 0 ? 'active' : ''}">${s.label}</button>`
          ).join('')}
        </div>
      </div>
      <div class="card-body" id="sales-chart"></div>
    </div>`;
}

function bindChart(d) {
  const host = document.getElementById('sales-chart');
  if (!host) return;

  const draw = (key) => {
    const s = SERIES[key];
    renderBarChart(host, {
      points: d.monthly_sales || [],
      valueKey: key,
      currency: s.currency,
      color: s.color,
      emptyText: `Ingen försäljning registrerad de senaste 12 månaderna`,
    });
  };
  draw('feldbinder');

  document.getElementById('chart-toggle')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-series]');
    if (!btn) return;
    document.querySelectorAll('#chart-toggle button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    draw(btn.dataset.series);
  });
}

// ── Försäljning per del ───────────────────────────────────────────────────────

function salesPanelHtml(a) {
  return `
    <div class="overview-panel">
      <div class="overview-header">
        <span class="overview-title">${esc(a.label)}</span>
        <a href="#${esc(a.route)}" class="btn btn-ghost btn-sm">Öppna</a>
      </div>
      <div class="overview-body">
        ${statCell(a.kind === 'feldbinder' ? 'Öppna förfrågningar' : 'Öppna offerter', a.open_leads, 'ok')}
        <div class="overview-stat">
          <div class="overview-stat-label">Öppet värde</div>
          <div class="overview-stat-value ok" style="font-size:19px">${fmtMoney(a.open_value, a.currency)}</div>
        </div>
        <div class="overview-stat">
          <div class="overview-stat-label">Sålt i år</div>
          <div class="overview-stat-value success" style="font-size:19px">
            ${a.sold_ytd_count} st · ${fmtMoney(a.sold_ytd_value, a.currency)}
          </div>
        </div>
        <div class="overview-stat">
          <div class="overview-stat-label">${esc(a.extra_label)}</div>
          <div class="overview-stat-value ${a.kind === 'feldbinder' ? 'warn' : 'ok'}" style="font-size:19px">
            ${esc(a.extra_value)}
          </div>
        </div>
      </div>
    </div>`;
}

// ── Listor ────────────────────────────────────────────────────────────────────

function recentOrdersHtml(d) {
  const rows = d.recent_orders || [];
  return `
    <div class="overview-panel">
      <div class="overview-header">
        <span class="overview-title">Senaste arbetsorder</span>
        <a href="#/work-orders" class="btn btn-ghost btn-sm">Visa alla</a>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Order</th><th>Kund</th><th>Status</th><th>Skapad</th></tr></thead>
          <tbody>
            ${rows.length ? rows.map(o => `
              <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
                <td><strong>${esc(o.order_number)}</strong></td>
                <td>${esc(o.customer?.name) || '–'}</td>
                <td>${statusBadge(o.status)}</td>
                <td class="text-muted">${fmtDate(o.created_at)}</td>
              </tr>`).join('')
              : '<tr><td colspan="4" style="text-align:center;padding:28px;color:var(--text-3)">Inga arbetsorder ännu</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>`;
}

function upcomingHtml(d) {
  const items = d.upcoming || [];
  return `
    <div class="overview-panel">
      <div class="overview-header">
        <span class="overview-title">Kommande 30 dagar</span>
        <a href="#/calendar" class="btn btn-ghost btn-sm">Kalender</a>
      </div>
      <div class="card-body" style="padding:0">
        ${items.length ? `
          <div class="upcoming-list">
            ${items.map(i => `
              <a class="upcoming-row ${i.overdue ? 'overdue' : ''}" href="${esc(i.link)}">
                <span class="upcoming-date">${fmtD(i.date)}</span>
                <span class="upcoming-kind ${esc(i.kind)}">${i.kind === 'leverans' ? 'Leverans' : 'Arbetsorder'}</span>
                <span class="upcoming-label">
                  <strong>${esc(i.label)}</strong>
                  ${i.sub ? `<span class="text-muted"> · ${esc(i.sub)}</span>` : ''}
                </span>
                ${i.overdue ? '<span class="upcoming-late">Försenad</span>' : ''}
              </a>`).join('')}
          </div>`
          : '<p class="text-muted" style="font-size:13px;padding:20px;margin:0">Inget planerat de närmaste 30 dagarna</p>'}
      </div>
    </div>`;
}
