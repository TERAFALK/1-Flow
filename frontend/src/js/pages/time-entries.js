import { api } from '../api.js';
import { fmtDate, fmtDuration } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderTimeEntries(el) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const [entries, active, orders] = await Promise.all([
    api.get('/time-entries'),
    api.get('/time-entries/active'),
    api.get('/work-orders'),
  ]);

  const openOrders = orders.filter(o => ['ny', 'planerad', 'pagaende'].includes(o.status));

  el.innerHTML = `
    <div class="page-header">
      <div class="page-title">Tidrapportering</div>
    </div>

    ${active ? `
      <div class="timer-card" id="active-timer-card">
        <div class="timer-label">Aktiv tidmätning – ${active.work_order?.order_number || 'AO-?'}</div>
        <div class="timer-display" id="live-clock">00:00:00</div>
        <div style="color:rgba(255,255,255,.7);font-size:13px;margin-top:4px;margin-bottom:16px">
          Startad ${fmtDate(active.start_time, true)}
        </div>
        <button class="btn btn-danger" id="stop-timer-btn">
          <svg viewBox="0 0 20 20" fill="currentColor" width="16"><rect x="4" y="4" width="12" height="12" rx="1"/></svg>
          Stoppa tidmätning
        </button>
      </div>
    ` : `
      <div class="card" style="margin-bottom:20px">
        <div class="card-header"><span class="card-title">Starta tidmätning</span></div>
        <div class="card-body">
          <form id="start-timer-form" style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
            <div class="field" style="margin:0;flex:1;min-width:200px">
              <label>Arbetsorder</label>
              <select name="work_order_id" required>
                <option value="">Välj order…</option>
                ${openOrders.map(o => `<option value="${o.id}">${o.order_number} – ${o.customer?.name || ''} ${o.vehicle?.license_plate || ''}</option>`).join('')}
              </select>
            </div>
            <div class="field" style="margin:0;flex:1;min-width:160px">
              <label>Typ av arbete</label>
              <select name="entry_type">
                <option value="övrigt">Övrigt</option>
                <option value="felsökning">Felsökning</option>
                <option value="reparation">Reparation</option>
                <option value="provkörning">Provkörning</option>
              </select>
            </div>
            <button type="submit" class="btn btn-success" style="margin-bottom:16px">
              <svg viewBox="0 0 20 20" fill="currentColor" width="16"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"/></svg>
              Starta
            </button>
          </form>
        </div>
      </div>
    `}

    <div class="card">
      <div class="card-header"><span class="card-title">Tidposter</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Order</th><th>Mekaniker</th><th>Typ</th>
            <th>Start</th><th>Stopp</th><th>Tid</th><th></th>
          </tr></thead>
          <tbody>
            ${entries.length ? entries.map(e => `
              <tr>
                <td><a href="#/work-orders/${e.work_order_id}"><strong>${e.work_order_id}</strong></a></td>
                <td>${e.user?.full_name || '–'}</td>
                <td>${e.entry_type}</td>
                <td>${fmtDate(e.start_time, true)}</td>
                <td>${e.end_time ? fmtDate(e.end_time, true) : '<span class="badge badge-pagaende">Pågår</span>'}</td>
                <td class="quantity-cell">${e.duration_minutes != null ? fmtDuration(e.duration_minutes) : '–'}</td>
                <td>
                  <button class="btn-icon" title="Ta bort" onclick="window._deleteEntry(${e.id})">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                  </button>
                </td>
              </tr>
            `).join('') : '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:28px">Inga tidposter</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Live clock for active timer
  if (active) {
    const start = new Date(active.start_time + 'Z');
    const tick = () => {
      const el = document.getElementById('live-clock');
      if (!el) return;
      const diff = Math.floor((Date.now() - start.getTime()) / 1000);
      const h = Math.floor(diff / 3600).toString().padStart(2, '0');
      const m = Math.floor((diff % 3600) / 60).toString().padStart(2, '0');
      const s = (diff % 60).toString().padStart(2, '0');
      el.textContent = `${h}:${m}:${s}`;
    };
    tick();
    const iv = setInterval(tick, 1000);
    window._timerInterval = iv;

    document.getElementById('stop-timer-btn').addEventListener('click', async () => {
      clearInterval(iv);
      await api.post(`/time-entries/${active.id}/stop`, {});
      showToast('Tidmätning stoppad', 'success');
      renderTimeEntries(el);
    });
  }

  const startForm = document.getElementById('start-timer-form');
  if (startForm) {
    startForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      data.work_order_id = Number(data.work_order_id);
      try {
        await api.post('/time-entries/start', data);
        showToast('Tidmätning startad', 'success');
        renderTimeEntries(el);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  window._deleteEntry = async (id) => {
    if (await confirmDialog('Ta bort denna tidpost?')) {
      await api.delete(`/time-entries/${id}`);
      showToast('Tidpost borttagen', 'success');
      renderTimeEntries(el);
    }
  };
}
