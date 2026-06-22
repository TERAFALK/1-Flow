import { api } from '../api.js';
import { fmtDate, statusBadge } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderVehicles(el, params = {}) {
  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <button class="btn btn-primary btn-sm" id="new-vehicle-btn">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      Nytt fordon
    </button>`;

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Fordon</div>
    <div class="page-subtitle" style="margin-bottom:20px">Fordonsregister</div>
    <div class="card">
      <div class="card-header">
        <div class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="search" id="vehicle-search" placeholder="Sök reg.nr…">
        </div>
      </div>
      <div id="vehicle-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-vehicle-btn')?.addEventListener('click', () =>
    openVehicleForm(null, params.customer_id || null, reload)
  );

  let timer;
  document.getElementById('vehicle-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => loadList(e.target.value), 300);
  });

  async function loadList(q = '') {
    const list = document.getElementById('vehicle-list');
    if (!list) return;
    const vehicles = await api.get(`/vehicles${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    if (!vehicles.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga fordon hittade</p></div>`;
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Reg.nr</th><th>Märke / Modell</th><th>År</th><th>Kund</th><th>Mätarst.</th><th></th></tr></thead>
          <tbody>
            ${vehicles.map(v => `
              <tr class="clickable" onclick="location.hash='#/vehicles/${v.id}'">
                <td><strong>${v.license_plate}</strong></td>
                <td>${v.make || ''} ${v.model || ''}</td>
                <td>${v.year || '–'}</td>
                <td>${v.customer?.name || '–'}</td>
                <td>${v.odometer ? v.odometer.toLocaleString('sv-SE') + ' km' : '–'}</td>
                <td onclick="event.stopPropagation()">
                  <div class="flex gap-2">
                    <button class="btn-icon" title="Redigera" onclick="window._editVehicle(${v.id})">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="btn-icon" title="Ta bort" onclick="window._deleteVehicle(${v.id}, '${v.license_plate}')">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function reload() { loadList(document.getElementById('vehicle-search')?.value || ''); }

  window._editVehicle = async (id) => {
    const v = await api.get(`/vehicles/${id}`);
    openVehicleForm(v, null, reload);
  };
  window._deleteVehicle = async (id, plate) => {
    if (await confirmDialog(`Ta bort fordonet <strong>${plate}</strong>?`)) {
      await api.delete(`/vehicles/${id}`);
      showToast('Fordon borttaget', 'success');
      reload();
    }
  };

  await loadList();
}

export async function renderVehicleDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/vehicles" class="btn btn-secondary btn-sm">← Tillbaka</a>
    <button class="btn btn-secondary btn-sm" id="topbar-edit-vehicle">Redigera</button>`;

  const [v, orders] = await Promise.all([
    api.get(`/vehicles/${id}`),
    api.get('/work-orders').then(all => all.filter(o => o.vehicle_id == id)).catch(() => []),
  ]);

  if (document.getElementById('topbar-title'))
    document.getElementById('topbar-title').textContent = v.license_plate;

  document.getElementById('topbar-edit-vehicle')?.addEventListener('click', () =>
    openVehicleForm(v, null, () => renderVehicleDetail(el, id))
  );

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">${v.license_plate}</div>
      <div class="page-subtitle">${[v.make, v.model, v.year ? `(${v.year})` : ''].filter(Boolean).join(' ')}</div>
    </div>

    <div class="tabs" id="vehicle-tabs">
      <div class="tab active" data-tab="info">Info</div>
      <div class="tab" data-tab="history">Historik <span style="font-size:11px;opacity:.6">(${orders.length})</span></div>
    </div>

    <div id="tab-info">
      <div style="display:grid;grid-template-columns:300px 1fr;gap:16px">
        <div class="card">
          <div class="card-header"><span class="card-title">Fordonsdata</span></div>
          <div class="card-body">
            ${v.customer ? metaRow('Kund', `<a href="#/customers/${v.customer_id}" style="color:var(--accent)">${v.customer.name}</a>`) : ''}
            ${metaRow('Regnummer', v.license_plate)}
            ${metaRow('Chassinr (VIN)', v.vin)}
            ${metaRow('Märke', v.make)}
            ${metaRow('Modell', v.model)}
            ${metaRow('Årsmodell', v.year)}
            ${metaRow('Motor', v.engine)}
            ${metaRow('Växellåda', v.gearbox)}
            ${metaRow('Mätarst.', v.odometer ? v.odometer.toLocaleString('sv-SE') + ' km' : null)}
            ${v.notes ? `<hr class="divider"><p style="font-size:13px;color:var(--text-2)">${v.notes}</p>` : ''}
          </div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">Senaste arbetsorder</span></div>
          ${renderOrderTable(orders.slice(0, 5))}
        </div>
      </div>
    </div>

    <div id="tab-history" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Arbetsorder-historik</span>
          <a href="#/work-orders/new?vehicle=${v.id}&customer=${v.customer_id}" class="btn btn-primary btn-sm">Ny arbetsorder</a>
        </div>
        ${renderOrderTable(orders)}
      </div>
    </div>
  `;

  document.getElementById('vehicle-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    document.querySelectorAll('#vehicle-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    ['info', 'history'].forEach(name => {
      document.getElementById(`tab-${name}`).classList.toggle('hidden', name !== tab.dataset.tab);
    });
  });
}

function renderOrderTable(orders) {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Order</th><th>Beskrivning</th><th>Status</th><th>Datum</th></tr></thead>
        <tbody>
          ${orders.length ? orders.map(o => `
            <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
              <td><strong>${o.order_number}</strong></td>
              <td>${o.description}</td>
              <td>${statusBadge(o.status)}</td>
              <td class="text-muted">${fmtDate(o.created_at)}</td>
            </tr>
          `).join('') : '<tr><td colspan="4" style="text-align:center;padding:28px;color:var(--text-3)">Inga arbetsorder</td></tr>'}
        </tbody>
      </table>
    </div>`;
}

function metaRow(label, value) {
  if (!value) return '';
  return `<div class="meta-row"><span class="meta-label">${label}:</span><span>${value}</span></div>`;
}

async function openVehicleForm(vehicle, defaultCustomerId, onSaved) {
  const customers = await api.get('/customers');
  openModal({
    title: vehicle ? 'Redigera fordon' : 'Nytt fordon',
    size: 'modal-lg',
    body: `
      <form id="vehicle-form">
        <div class="form-row">
          <div class="field">
            <label>Kund *</label>
            <select name="customer_id" required>
              <option value="">Välj kund…</option>
              ${customers.map(c => `<option value="${c.id}" ${(vehicle?.customer_id == c.id || defaultCustomerId == c.id) ? 'selected' : ''}>${c.name}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Reg.nr *</label><input type="text" name="license_plate" value="${vehicle?.license_plate || ''}" required style="text-transform:uppercase" placeholder="ABC 123"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Chassinummer (VIN)</label><input type="text" name="vin" value="${vehicle?.vin || ''}"></div>
          <div class="field"><label>Årsmodell</label><input type="number" name="year" value="${vehicle?.year || ''}" min="1900" max="2099"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Märke</label><input type="text" name="make" value="${vehicle?.make || ''}" placeholder="t.ex. Scania"></div>
          <div class="field"><label>Modell</label><input type="text" name="model" value="${vehicle?.model || ''}" placeholder="t.ex. R500"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Motor</label><input type="text" name="engine" value="${vehicle?.engine || ''}"></div>
          <div class="field"><label>Växellåda</label><input type="text" name="gearbox" value="${vehicle?.gearbox || ''}"></div>
        </div>
        <div class="field"><label>Mätarställning (km)</label><input type="number" name="odometer" value="${vehicle?.odometer || ''}"></div>
        <div class="field"><label>Anteckningar</label><textarea name="notes">${vehicle?.notes || ''}</textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${vehicle ? 'Spara' : 'Skapa fordon'}</button>
        </div>
      </form>
    `,
  });

  document.getElementById('vehicle-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    ['year', 'odometer', 'customer_id'].forEach(k => { body[k] = body[k] ? Number(body[k]) : null; });
    Object.keys(body).forEach(k => { if (body[k] === '') body[k] = null; });
    try {
      if (vehicle) {
        await api.put(`/vehicles/${vehicle.id}`, body);
        showToast('Fordon uppdaterat', 'success');
      } else {
        await api.post('/vehicles', body);
        showToast('Fordon skapat', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}
