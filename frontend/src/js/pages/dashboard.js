import { api } from '../api.js?v=4';
import { statusBadge, fmtDate } from '../app.js?v=4';

export async function renderDashboard(el) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const data = await api.get('/dashboard');

  // Topbar action
  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) {
    topbarActions.innerHTML = `
      <a href="#/work-orders/new" class="btn btn-primary btn-sm">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
        Ny order
      </a>`;
  }

  const openOrders = data.total_open;
  const ongoing   = data.by_status.pagaende || 0;
  const today     = data.scheduled_today;
  const timers    = data.active_timers;

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Översikt</div>
    <div class="page-subtitle" style="margin-bottom:22px">Senast uppdaterat ${new Date().toLocaleTimeString('sv-SE', {hour:'2-digit',minute:'2-digit'})}</div>

    <div class="stat-grid">
      <div class="stat-card accent">
        <div class="stat-label">Öppna ordrar</div>
        <div class="stat-value">${openOrders}</div>
        <div class="stat-sub">Ny + Planerad + Pågående</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pågående</div>
        <div class="stat-value">${ongoing}</div>
        <div class="stat-sub">Just nu i arbete</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Schemalagda idag</div>
        <div class="stat-value">${today}</div>
        <div class="stat-sub">Planerade för idag</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Aktiva tidmätningar</div>
        <div class="stat-value">${timers}</div>
        <div class="stat-sub">Mekaniker i arbete</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 260px;gap:16px;align-items:start">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Senaste arbetsorder</span>
          <a href="#/work-orders" class="btn btn-ghost btn-sm">Visa alla</a>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Order</th><th>Kund</th><th>Fordon</th><th>Status</th><th>Skapad</th>
            </tr></thead>
            <tbody>
              ${data.recent_orders.length ? data.recent_orders.map(o => `
                <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
                  <td><strong>${o.order_number}</strong></td>
                  <td>${o.customer?.name || '–'}</td>
                  <td>${o.vehicle?.license_plate || '–'}</td>
                  <td>${statusBadge(o.status)}</td>
                  <td class="text-muted">${fmtDate(o.created_at)}</td>
                </tr>
              `).join('') : `<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text-3)">Inga arbetsorder ännu</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Status</span></div>
        <div class="card-body" style="padding:12px 16px">
          ${Object.entries(data.by_status).map(([s, count]) => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border-light)">
              <div>${statusBadge(s)}</div>
              <strong>${count}</strong>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}
