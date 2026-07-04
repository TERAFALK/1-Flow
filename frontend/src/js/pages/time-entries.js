import { api } from '../api.js';
import { fmtDate, fmtDuration } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderTimeEntries(el) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const [entries, orders] = await Promise.all([
    api.get('/time-entries'),
    api.get('/work-orders'),
  ]);

  const openOrders = orders.filter(o => ['ny', 'planerad', 'pagaende'].includes(o.status));

  el.innerHTML = `
    <div class="page-header">
      <div class="page-title">Tidrapportering</div>
      <button class="btn btn-primary" id="add-manual-time-btn">+ Manuell tidpost</button>
    </div>

    <div class="card">
      <div class="card-header"><span class="card-title">Tidposter</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Order</th><th>Tekniker</th><th>Typ</th>
            <th>Start</th><th>Stopp</th><th>Tid</th><th></th>
          </tr></thead>
          <tbody>
            ${entries.length ? entries.map(e => `
              <tr>
                <td><a href="#/work-orders/${e.work_order_id}"><strong>${e.work_order?.order_number || '#' + e.work_order_id}</strong></a></td>
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

  document.getElementById('add-manual-time-btn').addEventListener('click', () =>
    openManualTimeForm(openOrders, () => renderTimeEntries(el))
  );

  window._deleteEntry = async (id) => {
    if (await confirmDialog('Ta bort denna tidpost?')) {
      await api.delete(`/time-entries/${id}`);
      showToast('Tidpost borttagen', 'success');
      renderTimeEntries(el);
    }
  };
}

function openManualTimeForm(orders, onSaved) {
  const now = new Date();
  const toLocal = (d) => new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const defaultStart = toLocal(new Date(now.getTime() - 60 * 60000));
  const defaultEnd = toLocal(now);

  openModal({
    title: 'Lägg till manuell tidpost',
    body: `
      <form id="manual-time-form">
        <div class="field">
          <label>Arbetsorder *</label>
          <select name="work_order_id" required>
            <option value="">Välj order…</option>
            ${orders.map(o => `<option value="${o.id}">${o.order_number} – ${o.customer?.name || ''} ${o.vehicle?.license_plate || ''}</option>`).join('')}
          </select>
        </div>
        <div class="form-row">
          <div class="field"><label>Starttid *</label><input type="datetime-local" name="start_time" value="${defaultStart}" required></div>
          <div class="field"><label>Sluttid *</label><input type="datetime-local" name="end_time" value="${defaultEnd}" required></div>
        </div>
        <div class="field">
          <label>Typ av arbete</label>
          <select name="entry_type">
            <option value="övrigt">Övrigt</option>
            <option value="felsökning">Felsökning</option>
            <option value="reparation">Reparation</option>
            <option value="provkörning">Provkörning</option>
          </select>
        </div>
        <div class="field"><label>Beskrivning</label><input type="text" name="description" placeholder="Valfri anteckning"></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>
    `,
  });
  document.getElementById('manual-time-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    try {
      await api.post('/time-entries/manual', {
        work_order_id: Number(data.work_order_id),
        start_time: new Date(data.start_time).toISOString(),
        end_time: new Date(data.end_time).toISOString(),
        entry_type: data.entry_type,
        description: data.description || null,
      });
      showToast('Tidpost tillagd', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
