import { api } from '../api.js';
import { statusBadge, fmtDate, fmtDuration } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

const STATUS_FLOW = {
  ny:          { next: 'planerad',  label: 'Markera Planerad' },
  planerad:    { next: 'pagaende',  label: 'Starta arbete' },
  pagaende:    { next: 'klar',      label: 'Markera Klar' },
  klar:        { next: 'fakturerad',label: 'Markera Fakturerad' },
  fakturerad:  { next: null,        label: null },
};

// ── List ──────────────────────────────────────────────────────────────────────

export async function renderWorkOrders(el, params = {}) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Arbetsorder</div>
        <div class="page-subtitle">Alla arbetsordrar</div>
      </div>
      <a href="#/work-orders/new" class="btn btn-primary">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
        Ny arbetsorder
      </a>
    </div>
    <div class="card">
      <div class="card-header" style="gap:12px;flex-wrap:wrap">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="wo-search" placeholder="Sök order, kund, beskrivning…">
        </div>
        <select id="wo-status-filter" style="width:auto;min-width:140px">
          <option value="">Alla statusar</option>
          <option value="ny">Ny</option>
          <option value="planerad">Planerad</option>
          <option value="pagaende">Pågående</option>
          <option value="klar">Klar</option>
          <option value="fakturerad">Fakturerad</option>
        </select>
      </div>
      <div id="wo-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  let timer;
  document.getElementById('wo-search').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(reload, 300); });
  document.getElementById('wo-status-filter').addEventListener('change', reload);

  async function reload() {
    const list = document.getElementById('wo-list');
    if (!list) return;
    const q = document.getElementById('wo-search')?.value || '';
    const status = document.getElementById('wo-status-filter')?.value || '';
    let url = `/work-orders?`;
    if (q) url += `q=${encodeURIComponent(q)}&`;
    if (status) url += `status=${status}&`;
    const orders = await api.get(url);
    if (!orders.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga arbetsorder hittades</p></div>`;
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Order</th><th>Kund</th><th>Fordon</th>
            <th>Beskrivning</th><th>Tilldelad</th>
            <th>Schemalagd</th><th>Status</th><th></th>
          </tr></thead>
          <tbody>
            ${orders.map(o => `
              <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
                <td><strong>${o.order_number}</strong></td>
                <td>${o.customer?.name || '–'}</td>
                <td>${o.vehicle?.license_plate ? `<span class="font-mono">${o.vehicle.license_plate}</span>` : '–'}</td>
                <td style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${o.description}</td>
                <td>${o.assigned_to_user?.full_name || '–'}</td>
                <td class="text-muted">${o.scheduled_date ? fmtDate(o.scheduled_date) : '–'}</td>
                <td>${statusBadge(o.status)}</td>
                <td onclick="event.stopPropagation()">
                  <button class="btn-icon" title="Ta bort order" onclick="window._deleteWOFromList(${o.id})">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }
  window._deleteWOFromList = async (orderId) => {
    if (await confirmDialog('Ta bort denna arbetsorder permanent?')) {
      await api.delete(`/work-orders/${orderId}`);
      showToast('Arbetsorder borttagen', 'success');
      reload();
    }
  };
  await reload();
}

// ── New ───────────────────────────────────────────────────────────────────────

export async function renderNewWorkOrder(el, params = {}) {
  const [customers, vehicles, users, settings] = await Promise.all([
    api.get('/customers'),
    api.get('/vehicles'),
    api.get('/users'),
    api.get('/settings').catch(() => []),
  ]);

  const orderMode = (settings.find?.(s => s.key === 'order_number_mode') || {}).value || 'auto';
  const preCustomer = params.customer ? parseInt(params.customer) : '';
  const preVehicle = params.vehicle ? parseInt(params.vehicle) : '';

  el.innerHTML = `
    <div class="page-header">
      <div>
        <a href="#/work-orders" class="btn btn-ghost btn-sm" style="margin-bottom:8px">← Tillbaka</a>
        <div class="page-title">Ny arbetsorder</div>
      </div>
    </div>
    <div class="card" style="max-width:700px">
      <div class="card-body">
        <form id="wo-form">
          ${orderMode === 'manual' ? `
            <div class="field">
              <label>Ordernummer *</label>
              <input type="text" name="order_number" required placeholder="t.ex. AO-2025-0042">
            </div>
          ` : ''}
          <div class="form-row">
            <div class="field">
              <label>Kund *</label>
              <select id="wo-customer" name="customer_id" required>
                <option value="">Välj kund…</option>
                ${customers.map(c => `<option value="${c.id}" ${c.id == preCustomer ? 'selected' : ''}>${c.name}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label>Fordon</label>
              <select id="wo-vehicle" name="vehicle_id">
                <option value="">Välj fordon (valfritt)…</option>
                ${vehicles.map(v => `<option value="${v.id}" data-customer="${v.customer_id}" ${v.id == preVehicle ? 'selected' : ''}>${v.license_plate} – ${v.make || ''} ${v.model || ''} (${v.customer?.name || ''})</option>`).join('')}
              </select>
            </div>
          </div>
          <div class="field"><label>Beskrivning / Felbeskrivning *</label><textarea name="description" rows="3" required placeholder="Beskriv felet eller arbetet som ska utföras…"></textarea></div>
          <div class="form-row">
            <div class="field">
              <label>Tilldelad mekaniker</label>
              <select name="assigned_to">
                <option value="">Ej tilldelad</option>
                ${users.map(u => `<option value="${u.id}">${u.full_name}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label>Schemalagd</label>
              <input type="datetime-local" name="scheduled_date">
            </div>
          </div>
          <div class="field"><label>Interna anteckningar</label><textarea name="internal_notes" rows="2" placeholder="Interna kommentarer…"></textarea></div>
          <div style="display:flex;gap:8px;margin-top:8px">
            <a href="#/work-orders" class="btn btn-secondary">Avbryt</a>
            <button type="submit" class="btn btn-primary">Skapa arbetsorder</button>
          </div>
        </form>
      </div>
    </div>
  `;

  const custSel = document.getElementById('wo-customer');
  const vehSel = document.getElementById('wo-vehicle');
  custSel.addEventListener('change', () => {
    const cid = custSel.value;
    Array.from(vehSel.options).forEach(opt => {
      if (!opt.value) return;
      opt.style.display = (!cid || opt.dataset.customer == cid) ? '' : 'none';
    });
    if (vehSel.selectedOptions[0]?.dataset.customer != cid) vehSel.value = '';
  });
  if (preCustomer) custSel.dispatchEvent(new Event('change'));

  document.getElementById('wo-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    body.customer_id = Number(body.customer_id);
    body.vehicle_id = body.vehicle_id ? Number(body.vehicle_id) : null;
    body.assigned_to = body.assigned_to ? Number(body.assigned_to) : null;
    if (!body.scheduled_date) body.scheduled_date = null;
    if (!body.internal_notes) body.internal_notes = null;
    if (!body.order_number) delete body.order_number;
    try {
      const wo = await api.post('/work-orders', body);
      showToast(`${wo.order_number} skapad`, 'success');
      location.hash = `#/work-orders/${wo.id}`;
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Detail ────────────────────────────────────────────────────────────────────

export async function renderWorkOrderDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';
  await loadDetail(el, id);
}

async function loadDetail(el, id) {
  const [wo, users] = await Promise.all([
    api.get(`/work-orders/${id}`),
    api.get('/users'),
  ]);

  const flow = STATUS_FLOW[wo.status];
  const totalParts = wo.lines.reduce((s, l) => s + parseFloat(l.quantity) * parseFloat(l.unit_price), 0);
  const totalMins = wo.time_entries.filter(e => e.end_time).reduce((s, e) => s + (e.duration_minutes || 0), 0);

  el.innerHTML = `
    <div class="page-header" style="margin-bottom:12px">
      <a href="#/work-orders" class="btn btn-ghost btn-sm">← Tillbaka</a>
    </div>

    <div class="order-header-bar">
      <div>
        <div class="order-number">${wo.order_number}</div>
        <div class="order-desc">${wo.description}</div>
        <div style="margin-top:8px">${statusBadge(wo.status)}</div>
      </div>
      <div class="order-actions">
        ${flow?.next ? `<button class="btn btn-primary" onclick="window._advanceStatus('${wo.id}','${flow.next}')">${flow.label}</button>` : ''}
        <button class="btn btn-secondary" onclick="window._editWO(${wo.id})">Redigera</button>
        <a href="#/scanner?order=${wo.id}" class="btn btn-secondary">
          <svg viewBox="0 0 20 20" fill="currentColor" width="15"><path fill-rule="evenodd" d="M3 4a1 1 0 011-1h3a1 1 0 010 2H4v2a1 1 0 01-2 0V5a1 1 0 011-1zm9 0a1 1 0 011-1h3a1 1 0 011 1v3a1 1 0 01-2 0V4h-2a1 1 0 01-1-1zM3 16a1 1 0 011 1h2v-2a1 1 0 112 0v3a1 1 0 01-1 1H4a1 1 0 01-1-1v-3a1 1 0 011-1zm13 0a1 1 0 00-1 1v2h-2a1 1 0 100 2h3a1 1 0 001-1v-3a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
          Scanner
        </a>
        <button class="btn btn-ghost" onclick="window._showInvoice(${wo.id})">Fakturaunderlag</button>
      </div>
    </div>

    <div class="order-meta">
      <div>
        <div class="meta-group">
          <h3>Kund</h3>
          <div class="meta-row"><span class="meta-label">Kund:</span>
            <strong><a href="#/customers/${wo.customer_id}">${wo.customer?.name || '–'}</a></strong>
          </div>
          <div class="meta-row"><span class="meta-label">Telefon:</span>${wo.customer?.phone || '–'}</div>
          <div class="meta-row"><span class="meta-label">E-post:</span>${wo.customer?.email || '–'}</div>
        </div>
      </div>
      <div>
        <div class="meta-group">
          <h3>Fordon & Planering</h3>
          ${wo.vehicle ? `
            <div class="meta-row"><span class="meta-label">Reg.nr:</span>
              <strong><a href="#/vehicles/${wo.vehicle_id}">${wo.vehicle.license_plate}</a></strong>
            </div>
            <div class="meta-row"><span class="meta-label">Fordon:</span>${wo.vehicle.make || ''} ${wo.vehicle.model || ''} ${wo.vehicle.year ? '(' + wo.vehicle.year + ')' : ''}</div>
          ` : '<div class="meta-row text-muted">Inget fordon kopplat</div>'}
          <div class="meta-row"><span class="meta-label">Tilldelad:</span>${wo.assigned_to_user?.full_name || '–'}</div>
          <div class="meta-row"><span class="meta-label">Schemalagd:</span>${wo.scheduled_date ? fmtDate(wo.scheduled_date) : '–'}</div>
          <div class="meta-row"><span class="meta-label">Skapad:</span>${fmtDate(wo.created_at)}</div>
        </div>
      </div>
    </div>

    ${wo.internal_notes ? `
      <div class="alert alert-info" style="margin-bottom:16px">
        <strong>Interna anteckningar:</strong> ${wo.internal_notes}
      </div>
    ` : ''}

    <!-- Gantt always visible in overview -->
    <div id="overview-gantt" style="margin-bottom:20px"></div>

    <div class="tabs" id="wo-tabs">
      <div class="tab active" data-tab="parts">Delar (${wo.lines.length})</div>
      <div class="tab" data-tab="time">Tid (${fmtDuration(totalMins)})</div>
      <div class="tab" data-tab="phases">Faser</div>
      <div class="tab" data-tab="purchases">Inköp</div>
      <div class="tab" data-tab="bodytext">Arbetstext</div>
      <div class="tab" data-tab="documents">Dokument</div>
      <div class="tab" data-tab="photos">Foton</div>
      <div class="tab" data-tab="drawings">Ritningar</div>
      <div class="tab" data-tab="activities">Aktiviteter</div>
      <div class="tab" data-tab="tasks">Uppgifter</div>
    </div>

    <!-- DELAR -->
    <div id="tab-parts">
      <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
        <button class="btn btn-secondary" id="add-line-btn">
          <svg viewBox="0 0 20 20" fill="currentColor" width="15"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
          Lägg till artikel
        </button>
        <a href="#/scanner?order=${wo.id}" class="btn btn-ghost">Öppna scanner</a>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Artikel</th><th>Art.nr</th><th class="text-right">Antal</th>
              <th>Enhet</th><th class="text-right">À-pris</th><th class="text-right">Totalt</th><th></th>
            </tr></thead>
            <tbody id="lines-tbody">
              ${wo.lines.map(l => lineRow(l)).join('') || '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px">Inga reservdelar</td></tr>'}
            </tbody>
            ${wo.lines.length ? `
              <tfoot><tr class="total-row">
                <td colspan="5">Summa reservdelar</td>
                <td class="text-right">${fmtPrice(totalParts)}</td>
                <td></td>
              </tr></tfoot>
            ` : ''}
          </table>
        </div>
      </div>
    </div>

    <!-- TID -->
    <div id="tab-time" class="hidden">
      <div id="timer-section" style="margin-bottom:16px"></div>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn btn-secondary" id="add-manual-time-btn">+ Manuell tidpost</button>
      </div>
      <div id="time-list-wrap">
        <div class="card">
          <div class="table-wrap">
            <table>
              <thead><tr><th>Mekaniker</th><th>Typ</th><th>Start</th><th>Stopp</th><th class="text-right">Tid</th><th></th></tr></thead>
              <tbody id="time-entries-tbody">
                ${wo.time_entries.map(e => timeEntryRow(e, id)).join('') || '<tr><td colspan="6" class="text-muted" style="text-align:center;padding:24px">Inga tidposter</td></tr>'}
              </tbody>
              ${wo.time_entries.filter(e=>e.end_time).length ? `
                <tfoot><tr class="total-row">
                  <td colspan="4">Total tid</td>
                  <td class="text-right">${fmtDuration(totalMins)}</td>
                  <td></td>
                </tr></tfoot>
              ` : ''}
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ARBETSTEXT -->
    <div id="tab-bodytext" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Arbetstext</span>
          <span class="text-muted" style="font-size:12px" id="body-save-status"></span>
        </div>
        <div class="card-body" style="padding-top:0">
          <textarea id="body-text-area" rows="10" placeholder="Beskriv arbetet i detalj, noteringar, teknisk information…" style="width:100%;resize:vertical">${wo.body_text || ''}</textarea>
        </div>
      </div>
    </div>

    <!-- FASER -->
    <div id="tab-phases" class="hidden">
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="btn btn-secondary" id="add-phase-btn">+ Ny fas</button>
      </div>
      <div id="phases-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- INKÖP -->
    <div id="tab-purchases" class="hidden">
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="btn btn-secondary" id="add-purchase-btn">+ Nytt inköp</button>
      </div>
      <div id="purchases-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- DOKUMENT -->
    <div id="tab-documents" class="hidden">
      <div id="documents-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- FOTON -->
    <div id="tab-photos" class="hidden">
      <div id="photos-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- RITNINGAR -->
    <div id="tab-drawings" class="hidden">
      <div id="drawings-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- AKTIVITETER -->
    <div id="tab-activities" class="hidden">
      <div id="activities-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- UPPGIFTER -->
    <div id="tab-tasks" class="hidden">
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="btn btn-secondary" id="add-task-btn">+ Ny uppgift</button>
      </div>
      <div id="tasks-content"><div class="loading">Laddar…</div></div>
    </div>

    <!-- Image viewer overlay -->
    <div id="img-viewer" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:9999;align-items:center;justify-content:center;cursor:zoom-out" onclick="this.style.display='none'">
      <img id="img-viewer-img" style="max-width:92vw;max-height:92vh;object-fit:contain;border-radius:4px">
    </div>
  `;

  // ── Tab switching ───────────────────────────────────────────────────────────
  const ALL_TABS = ['parts','time','phases','purchases','bodytext','documents','photos','drawings','activities','tasks'];
  const tabLoadedMap = {};

  document.getElementById('wo-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    const name = tab.dataset.tab;
    document.querySelectorAll('#wo-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    ALL_TABS.forEach(t => {
      document.getElementById(`tab-${t}`).classList.toggle('hidden', t !== name);
    });
    if (!tabLoadedMap[name]) {
      tabLoadedMap[name] = true;
      loadTab(name);
    }
  });

  function loadTab(name) {
    if (name === 'phases')     loadPhases(id);
    if (name === 'purchases')  loadPurchases(id, users);
    if (name === 'bodytext')   initBodyText(id);
    if (name === 'documents')  loadFiles(id, 'document');
    if (name === 'photos')     loadFiles(id, 'photo');
    if (name === 'drawings')   loadFiles(id, 'drawing');
    if (name === 'activities') loadActivities(id);
    if (name === 'tasks')      loadTasks(id, users);
  }

  // ── Gantt overview (always visible) ─────────────────────────────────────────
  loadOverviewGantt(id);

  // ── Timer section ───────────────────────────────────────────────────────────
  loadTimerSection(id);

  // ── Manual time entry ────────────────────────────────────────────────────────
  document.getElementById('add-manual-time-btn').addEventListener('click', () =>
    openManualTimeForm(id, () => loadDetail(el, id))
  );

  // ── Add line ────────────────────────────────────────────────────────────────
  document.getElementById('add-line-btn').addEventListener('click', () =>
    openAddLineForm(wo.id, null, () => loadDetail(el, id))
  );

  // ── Phase button ────────────────────────────────────────────────────────────
  document.getElementById('add-phase-btn').addEventListener('click', () =>
    openPhaseForm(id, null, () => loadPhases(id))
  );

  // ── Purchase button ─────────────────────────────────────────────────────────
  document.getElementById('add-purchase-btn').addEventListener('click', () =>
    openPurchaseForm(id, null, users, () => loadPurchases(id, users))
  );

  // ── Task button ─────────────────────────────────────────────────────────────
  document.getElementById('add-task-btn').addEventListener('click', () =>
    openTaskForm(id, null, users, () => loadTasks(id, users))
  );

  // ── Global handlers ─────────────────────────────────────────────────────────
  window._advanceStatus = async (orderId, nextStatus) => {
    await api.put(`/work-orders/${orderId}`, { status: nextStatus });
    showToast('Status uppdaterad', 'success');
    loadDetail(el, id);
  };
  window._editWO = (orderId) => openEditWOForm(orderId, users, () => loadDetail(el, id));
  window._deleteLine = async (lineId) => {
    if (await confirmDialog('Ta bort denna rad?')) {
      await api.delete(`/work-orders/${id}/lines/${lineId}`);
      loadDetail(el, id);
    }
  };
  window._stopTimer = async (entryId, orderId) => {
    await api.post(`/time-entries/${entryId}/stop`, {});
    showToast('Tidmätning stoppad', 'success');
    loadDetail(el, orderId);
  };
  window._deleteTE = async (entryId, orderId) => {
    if (await confirmDialog('Ta bort tidpost?')) {
      await api.delete(`/time-entries/${entryId}`);
      loadDetail(el, orderId);
    }
  };
  window._showInvoice = async (orderId) => {
    const inv = await api.get(`/work-orders/${orderId}/invoice`);
    openModal({
      title: `Fakturaunderlag – ${inv.order_number}`,
      size: 'modal-lg',
      body: `
        <p><strong>Kund:</strong> ${inv.customer?.name || '–'}</p>
        <p style="margin-top:4px"><strong>Fordon:</strong> ${inv.vehicle ? `${inv.vehicle.license_plate} ${inv.vehicle.make || ''} ${inv.vehicle.model || ''}` : '–'}</p>
        <p style="margin-top:4px"><strong>Ärende:</strong> ${inv.description}</p>
        <hr class="divider">
        <h3 style="margin-bottom:12px">Reservdelar</h3>
        <table style="width:100%;margin-bottom:16px">
          <thead><tr><th>Artikel</th><th class="text-right">Antal</th><th class="text-right">À-pris</th><th class="text-right">Totalt</th></tr></thead>
          <tbody>
            ${inv.lines.map(l => `<tr><td>${l.description}</td><td class="text-right">${l.quantity} ${l.unit}</td><td class="text-right">${l.unit_price.toLocaleString('sv-SE')} kr</td><td class="text-right">${l.total.toLocaleString('sv-SE', {minimumFractionDigits:2})} kr</td></tr>`).join('') || '<tr><td colspan="4" class="text-muted">Inga delar</td></tr>'}
          </tbody>
          <tfoot><tr class="total-row"><td colspan="3">Summa delar</td><td class="text-right">${inv.parts_total.toLocaleString('sv-SE', {minimumFractionDigits:2})} kr</td></tr></tfoot>
        </table>
        <h3 style="margin-bottom:12px">Arbetstid</h3>
        <table style="width:100%">
          <thead><tr><th>Mekaniker</th><th>Typ</th><th class="text-right">Tid</th></tr></thead>
          <tbody>
            ${inv.time_entries.map(e => `<tr><td>${e.user}</td><td>${e.type}</td><td class="text-right">${fmtDuration(e.minutes || 0)}</td></tr>`).join('') || '<tr><td colspan="3" class="text-muted">Ingen tid</td></tr>'}
          </tbody>
          <tfoot><tr class="total-row"><td colspan="2">Total tid</td><td class="text-right">${fmtDuration(inv.labor_minutes)}</td></tr></tfoot>
        </table>
      `,
    });
  };
}

// ── Timer section ─────────────────────────────────────────────────────────────

async function loadTimerSection(orderId) {
  const section = document.getElementById('timer-section');
  if (!section) return;
  const active = await api.get('/time-entries/active').catch(() => null);
  if (active && active.work_order_id == orderId) {
    const start = new Date(active.start_time + 'Z');
    section.innerHTML = `
      <div class="timer-card">
        <div class="timer-label">Aktiv tidmätning</div>
        <div class="timer-display" id="detail-clock">00:00:00</div>
        <div style="color:rgba(255,255,255,.6);font-size:13px;margin-top:4px;margin-bottom:16px">Startad ${fmtDate(active.start_time, true)}</div>
        <button class="btn btn-danger" onclick="window._stopTimer(${active.id}, ${orderId})">Stoppa</button>
      </div>
    `;
    const tick = () => {
      const e = document.getElementById('detail-clock');
      if (!e) { clearInterval(iv); return; }
      const diff = Math.floor((Date.now() - start.getTime()) / 1000);
      e.textContent = [Math.floor(diff/3600), Math.floor((diff%3600)/60), diff%60].map(n=>String(n).padStart(2,'0')).join(':');
    };
    tick();
    const iv = setInterval(tick, 1000);
  } else if (!active) {
    section.innerHTML = `
      <div class="card">
        <div class="card-body">
          <form id="start-timer-inline" style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
            <div class="field" style="margin:0;min-width:160px">
              <label>Typ av arbete</label>
              <select name="entry_type">
                <option value="övrigt">Övrigt</option>
                <option value="felsökning">Felsökning</option>
                <option value="reparation">Reparation</option>
                <option value="provkörning">Provkörning</option>
              </select>
            </div>
            <button type="submit" class="btn btn-success" style="margin-bottom:16px">▶ Starta tidmätning</button>
          </form>
        </div>
      </div>
    `;
    document.getElementById('start-timer-inline').addEventListener('submit', async (e) => {
      e.preventDefault();
      const { entry_type } = Object.fromEntries(new FormData(e.target));
      try {
        await api.post('/time-entries/start', { work_order_id: orderId, entry_type });
        showToast('Tidmätning startad', 'success');
        loadTimerSection(orderId);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
}

// ── Time entry row helper ─────────────────────────────────────────────────────

function timeEntryRow(e, orderId) {
  return `<tr>
    <td>${e.user?.full_name || '–'}</td>
    <td>${e.entry_type}</td>
    <td>${fmtDate(e.start_time, true)}</td>
    <td>${e.end_time ? fmtDate(e.end_time, true) : '<span class="badge badge-pagaende">Pågår</span>'}</td>
    <td class="text-right quantity-cell">${e.duration_minutes != null ? fmtDuration(e.duration_minutes) : '–'}</td>
    <td>
      ${!e.end_time ? `<button class="btn btn-sm btn-danger" onclick="window._stopTimer(${e.id}, ${orderId})">Stopp</button>` : ''}
      <button class="btn-icon" onclick="window._deleteTE(${e.id}, ${orderId})">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
      </button>
    </td>
  </tr>`;
}

// ── Body text tab init ────────────────────────────────────────────────────────

function initBodyText(orderId) {
  const bodyArea = document.getElementById('body-text-area');
  const saveStatus = document.getElementById('body-save-status');
  if (!bodyArea || bodyArea.dataset.initDone) return;
  bodyArea.dataset.initDone = '1';
  let bodyTimer;
  bodyArea.addEventListener('input', () => {
    saveStatus.textContent = 'Osparad…';
    clearTimeout(bodyTimer);
    bodyTimer = setTimeout(async () => {
      try {
        await api.put(`/work-orders/${orderId}`, { body_text: bodyArea.value });
        saveStatus.textContent = 'Sparad';
        setTimeout(() => { saveStatus.textContent = ''; }, 2000);
      } catch { saveStatus.textContent = 'Fel vid sparning'; }
    }, 1200);
  });
}

// ── Overview Gantt (always visible) ──────────────────────────────────────────

async function loadOverviewGantt(orderId) {
  const container = document.getElementById('overview-gantt');
  if (!container) return;
  const phases = await api.get(`/work-orders/${orderId}/phases`).catch(() => []);
  if (!phases.length) return;

  const dates = phases.flatMap(p => [p.start_date, p.end_date]).filter(Boolean).map(d => new Date(d));
  const minDate = dates.length ? new Date(Math.min(...dates)) : new Date();
  const maxDate = dates.length ? new Date(Math.max(...dates)) : new Date();
  const today = new Date();
  const rangeMs = Math.max(maxDate - minDate, 1000*60*60*24*7);

  function pct(dateStr) {
    if (!dateStr) return 0;
    return Math.min(100, Math.max(0, ((new Date(dateStr) - minDate) / rangeMs) * 100));
  }
  function barWidth(start, end) {
    if (!start || !end) return 10;
    return Math.min(100 - pct(start), Math.max(2, ((new Date(end) - new Date(start)) / rangeMs) * 100));
  }
  const todayPct = Math.min(100, Math.max(0, ((today - minDate) / rangeMs) * 100));
  const fmtShort = (d) => d ? new Date(d).toLocaleDateString('sv-SE', { month:'short', day:'numeric' }) : '–';

  // Week-boundary gridlines with ISO week numbers
  const weekTicks = [];
  const firstMonday = new Date(minDate);
  const dow = firstMonday.getDay() === 0 ? 7 : firstMonday.getDay();
  firstMonday.setDate(firstMonday.getDate() - (dow - 1));
  for (let d = new Date(firstMonday); d <= maxDate; d.setDate(d.getDate() + 7)) {
    weekTicks.push({ week: isoWeekNumber(d), left: pct(d.toISOString()) });
  }

  container.innerHTML = `
    <div class="card">
      <div class="card-header"><span class="card-title">Gantt-schema</span></div>
      <div class="card-body" style="overflow-x:auto">
        <div class="gantt-wrap" style="min-width:600px">
          <div class="gantt-row gantt-row-head">
            <div class="gantt-label"></div>
            <div class="gantt-timeline">
              ${weekTicks.map(w => `<span class="gantt-week-tick" style="left:${w.left}%">v.${w.week}</span>`).join('')}
            </div>
          </div>
          ${phases.map(p => `
            <div class="gantt-row">
              <div class="gantt-label" title="${p.name}">${p.name}</div>
              <div class="gantt-timeline">
                ${weekTicks.map(w => `<div class="gantt-week-line" style="left:${w.left}%"></div>`).join('')}
                <div class="gantt-today" style="left:${todayPct}%" title="Idag: ${fmtShort(today.toISOString())}"></div>
                <div class="gantt-bar" style="margin-left:${pct(p.start_date)}%;width:${barWidth(p.start_date,p.end_date)}%;background:${p.color || 'var(--accent)'}" title="${p.name}: ${fmtShort(p.start_date)} – ${fmtShort(p.end_date)}">
                  <span>${fmtShort(p.start_date)} – ${fmtShort(p.end_date)}</span>
                </div>
              </div>
            </div>
          `).join('')}
          <div class="gantt-row">
            <div class="gantt-label text-muted" style="font-size:11px;font-weight:400">Start: ${fmtShort(minDate.toISOString())}</div>
            <div class="gantt-timeline"><span class="text-muted" style="font-size:11px;position:absolute;right:0">Slut: ${fmtShort(maxDate.toISOString())}</span></div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function isoWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}

// ── Manual time entry form ────────────────────────────────────────────────────

function openManualTimeForm(orderId, onSaved) {
  const now = new Date();
  const toLocal = (d) => new Date(d - d.getTimezoneOffset()*60000).toISOString().slice(0,16);
  const defaultStart = toLocal(new Date(now.getTime() - 60*60000));
  const defaultEnd = toLocal(now);

  openModal({
    title: 'Lägg till manuell tidpost',
    body: `
      <form id="manual-time-form">
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
        work_order_id: orderId,
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

// ── Phases / Gantt ────────────────────────────────────────────────────────────

async function loadPhases(orderId) {
  const el = document.getElementById('phases-content');
  if (!el) return;
  const phases = await api.get(`/work-orders/${orderId}/phases`).catch(() => []);

  if (!phases.length) {
    el.innerHTML = `<div class="empty-state"><p>Inga faser tillagda än</p></div>`;
    return;
  }

  el.innerHTML = `
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Fas</th><th>Färg</th><th>Start</th><th>Slut</th><th></th></tr></thead>
          <tbody>
            ${phases.map(p => `
              <tr>
                <td><strong>${p.name}</strong></td>
                <td><span style="display:inline-block;width:16px;height:16px;border-radius:4px;background:${p.color || 'var(--accent)'}"></span></td>
                <td>${p.start_date ? fmtDate(p.start_date) : '–'}</td>
                <td>${p.end_date ? fmtDate(p.end_date) : '–'}</td>
                <td>
                  <div style="display:flex;gap:4px">
                    <button class="btn-icon" onclick="window._editPhase(${orderId}, ${p.id})">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="btn-icon" onclick="window._deletePhase(${orderId}, ${p.id})">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Refresh overview gantt when phases change
  loadOverviewGantt(orderId);

  window._editPhase = async (oid, pid) => {
    const phase = await api.get(`/work-orders/${oid}/phases`).then(list => list.find(p => p.id === pid));
    openPhaseForm(oid, phase, () => loadPhases(oid));
  };
  window._deletePhase = async (oid, pid) => {
    if (await confirmDialog('Ta bort fas?')) {
      await api.delete(`/work-orders/${oid}/phases/${pid}`);
      loadPhases(oid);
    }
  };
}

function openPhaseForm(orderId, phase, onSaved) {
  openModal({
    title: phase ? 'Redigera fas' : 'Ny fas',
    body: `
      <form id="phase-form">
        <div class="field"><label>Fas-namn *</label><input type="text" name="name" value="${phase?.name || ''}" required placeholder="t.ex. Demontering"></div>
        <div class="form-row">
          <div class="field"><label>Startdatum</label><input type="date" name="start_date" value="${phase?.start_date?.slice(0,10) || ''}"></div>
          <div class="field"><label>Slutdatum</label><input type="date" name="end_date" value="${phase?.end_date?.slice(0,10) || ''}"></div>
        </div>
        <div class="field"><label>Färg</label><input type="color" name="color" value="${phase?.color || '#E2001A'}" style="height:36px;padding:2px 4px"></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${phase ? 'Spara' : 'Skapa'}</button>
        </div>
      </form>
    `,
  });
  document.getElementById('phase-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    if (!body.start_date) body.start_date = null;
    if (!body.end_date) body.end_date = null;
    try {
      if (phase) await api.put(`/work-orders/${orderId}/phases/${phase.id}`, body);
      else await api.post(`/work-orders/${orderId}/phases`, body);
      showToast('Fas sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Purchases ─────────────────────────────────────────────────────────────────

const PURCHASE_STATUS = { beställd: 'Beställd', inlevererad: 'Inlevererad', avbeställd: 'Avbeställd' };

async function loadPurchases(orderId, users) {
  const el = document.getElementById('purchases-content');
  if (!el) return;
  const purchases = await api.get(`/work-orders/${orderId}/purchases`).catch(() => []);

  if (!purchases.length) {
    el.innerHTML = `<div class="empty-state"><p>Inga inköp registrerade</p></div>`;
    return;
  }

  el.innerHTML = `
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Inköpsnr</th><th>Leverantör</th><th>Benämning</th>
            <th>Art.nr</th><th class="text-right">Antal</th>
            <th>Lev.vecka</th><th>Status</th><th></th>
          </tr></thead>
          <tbody>
            ${purchases.map(p => `
              <tr>
                <td class="font-mono">${p.purchase_number || '–'}</td>
                <td>${p.supplier || '–'}</td>
                <td>${p.description || '–'}</td>
                <td class="font-mono text-muted">${p.article_number || '–'}</td>
                <td class="text-right">${p.quantity ?? '–'}</td>
                <td>${p.delivery_week ? 'v.' + p.delivery_week : '–'}</td>
                <td>
                  <select class="purchase-status-sel" data-id="${p.id}" style="font-size:12px;padding:3px 6px">
                    ${Object.entries(PURCHASE_STATUS).map(([k,v]) => `<option value="${k}" ${p.status===k?'selected':''}>${v}</option>`).join('')}
                  </select>
                </td>
                <td>
                  <div style="display:flex;gap:4px">
                    <button class="btn-icon" onclick="window._editPurchase(${orderId}, ${p.id})">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="btn-icon" onclick="window._deletePurchase(${orderId}, ${p.id})">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  el.querySelectorAll('.purchase-status-sel').forEach(sel => {
    sel.addEventListener('change', async () => {
      try {
        await api.put(`/work-orders/${orderId}/purchases/${sel.dataset.id}`, { status: sel.value });
        showToast('Status uppdaterad', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  window._editPurchase = async (oid, pid) => {
    const purchase = await api.get(`/work-orders/${oid}/purchases`).then(list => list.find(p => p.id === pid));
    openPurchaseForm(oid, purchase, users, () => loadPurchases(oid, users));
  };
  window._deletePurchase = async (oid, pid) => {
    if (await confirmDialog('Ta bort inköp?')) {
      await api.delete(`/work-orders/${oid}/purchases/${pid}`);
      loadPurchases(oid, users);
    }
  };
}

async function openPurchaseForm(orderId, purchase, users, onSaved) {
  const settings = await api.get('/settings').catch(() => []);
  const mode = (settings.find?.(s => s.key === 'purchase_number_mode') || {}).value || 'auto';

  openModal({
    title: purchase ? 'Redigera inköp' : 'Nytt inköp',
    size: 'modal-lg',
    body: `
      <form id="purchase-form">
        ${mode === 'manual' ? `
          <div class="field"><label>Inköpsnummer *</label><input type="text" name="purchase_number" value="${purchase?.purchase_number || ''}" required placeholder="t.ex. INK-2025-0001"></div>
        ` : ''}
        <div class="form-row">
          <div class="field"><label>Leverantör</label><input type="text" name="supplier" value="${purchase?.supplier || ''}" placeholder="Leverantörens namn"></div>
          <div class="field"><label>Artikelnummer</label><input type="text" name="article_number" value="${purchase?.article_number || ''}"></div>
        </div>
        <div class="field"><label>Benämning</label><input type="text" name="description" value="${purchase?.description || ''}" placeholder="Vad beställs?"></div>
        <div class="form-row">
          <div class="field"><label>Antal</label><input type="number" name="quantity" value="${purchase?.quantity ?? 1}" step="0.01" min="0"></div>
          <div class="field"><label>Leveransvecka</label><input type="number" name="delivery_week" value="${purchase?.delivery_week || ''}" min="1" max="53" placeholder="t.ex. 42"></div>
        </div>
        <div class="field">
          <label>Status</label>
          <select name="status">
            ${Object.entries(PURCHASE_STATUS).map(([k,v]) => `<option value="${k}" ${(purchase?.status||'beställd')===k?'selected':''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${purchase ? 'Spara' : 'Skapa'}</button>
        </div>
      </form>
    `,
  });
  document.getElementById('purchase-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    if (body.quantity) body.quantity = parseFloat(body.quantity);
    if (body.delivery_week) body.delivery_week = parseInt(body.delivery_week);
    else delete body.delivery_week;
    if (!body.purchase_number) delete body.purchase_number;
    try {
      if (purchase) await api.put(`/work-orders/${orderId}/purchases/${purchase.id}`, body);
      else await api.post(`/work-orders/${orderId}/purchases`, body);
      showToast('Inköp sparat', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Files (documents, photos, drawings) ──────────────────────────────────────

const FILE_ACCEPT = {
  document: '.pdf,.doc,.docx,.xls,.xlsx,.odt,.ods,.txt',
  photo:    '.jpg,.jpeg,.png,.gif,.webp,.bmp',
  drawing:  '.pdf,.dwg,.dxf,.svg',
};

async function loadFiles(orderId, fileType) {
  const containerId = fileType === 'photo' ? 'photos' : fileType === 'drawing' ? 'drawings' : 'documents';
  const el = document.getElementById(`${containerId}-content`);
  if (!el) return;

  const files = await api.get(`/work-orders/${orderId}/files?file_type=${fileType}`).catch(() => []);
  const isPhoto = fileType === 'photo';

  el.innerHTML = `
    <div class="upload-area" id="upload-area-${fileType}" style="margin-bottom:16px">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="32" height="32" style="opacity:.4"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      <p style="margin:8px 0 4px">Dra och släpp filer hit, eller</p>
      <label class="btn btn-secondary btn-sm" style="cursor:pointer">
        Välj fil
        <input type="file" id="file-input-${fileType}" accept="${FILE_ACCEPT[fileType]}" multiple style="display:none">
      </label>
    </div>

    ${isPhoto ? `
      <div class="photo-grid" id="filelist-${fileType}">
        ${files.map(f => `
          <div class="photo-thumb" data-file-id="${f.id}" data-order-id="${orderId}">
            <img data-src="/api/work-orders/${orderId}/files/${f.id}/download" style="cursor:zoom-in;background:var(--surface-2)" onclick="window._viewPhotoAuth(${orderId}, ${f.id})">
            <button class="photo-delete" onclick="window._deleteFile(${orderId}, ${f.id}, '${fileType}')" title="Ta bort">×</button>
            <div class="photo-name">${f.original_name}</div>
          </div>
        `).join('') || '<p style="grid-column:1/-1;text-align:center;color:var(--text-3);padding:24px">Inga foton uppladdade</p>'}
      </div>
    ` : `
      <div class="card" id="filelist-${fileType}">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Filnamn</th><th>Storlek</th><th>Uppladdad</th><th></th></tr></thead>
            <tbody>
              ${files.map(f => `
                <tr>
                  <td>
                    <button class="btn btn-ghost btn-sm" onclick="window._downloadFile(${orderId}, ${f.id}, '${f.original_name.replace(/'/g,"\\'")}')">
                      ${fileIcon(f.original_name)} ${f.original_name}
                    </button>
                  </td>
                  <td class="text-muted">${fmtBytes(f.size_bytes)}</td>
                  <td class="text-muted">${fmtDate(f.uploaded_at)}</td>
                  <td>
                    <button class="btn-icon" onclick="window._deleteFile(${orderId}, ${f.id}, '${fileType}')">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </td>
                </tr>
              `).join('') || `<tr><td colspan="4" style="text-align:center;padding:28px;color:var(--text-3)">Inga filer uppladdade</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `}
  `;

  const uploadArea = document.getElementById(`upload-area-${fileType}`);
  const fileInput = document.getElementById(`file-input-${fileType}`);

  uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('drag-over'); });
  uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
  uploadArea.addEventListener('drop', async (e) => {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');
    await uploadFiles(orderId, fileType, Array.from(e.dataTransfer.files));
  });
  fileInput.addEventListener('change', async () => {
    await uploadFiles(orderId, fileType, Array.from(fileInput.files));
    fileInput.value = '';
  });

  window._downloadFile = async (oid, fid, name) => {
    try {
      const token = localStorage.getItem('flow_token');
      const resp = await fetch(`/api/work-orders/${oid}/files/${fid}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error('Nedladdning misslyckades');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) { showToast(err.message, 'error'); }
  };
  window._deleteFile = async (oid, fid, ft) => {
    if (await confirmDialog('Ta bort filen?')) {
      await api.delete(`/work-orders/${oid}/files/${fid}`);
      loadFiles(oid, ft);
    }
  };
  window._viewPhotoAuth = async (oid, fid) => {
    try {
      const token = localStorage.getItem('flow_token');
      const resp = await fetch(`/api/work-orders/${oid}/files/${fid}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error('Kunde inte ladda bilden');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const viewer = document.getElementById('img-viewer');
      if (!viewer) return;
      const imgEl = document.getElementById('img-viewer-img');
      if (imgEl._prevUrl) URL.revokeObjectURL(imgEl._prevUrl);
      imgEl._prevUrl = url;
      imgEl.src = url;
      viewer.style.display = 'flex';
    } catch (err) { showToast(err.message, 'error'); }
  };

  // Load photo thumbnails with auth
  el.querySelectorAll('img[data-src]').forEach(async (img) => {
    try {
      const token = localStorage.getItem('flow_token');
      const resp = await fetch(img.dataset.src, { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) return;
      const blob = await resp.blob();
      img.src = URL.createObjectURL(blob);
    } catch { /* silently ignore */ }
  });
}

async function uploadFiles(orderId, fileType, files) {
  const token = localStorage.getItem('flow_token');
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const resp = await fetch(`/api/work-orders/${orderId}/files?file_type=${fileType}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'Uppladdning misslyckades');
      }
      showToast(`${file.name} uppladdad`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }
  loadFiles(orderId, fileType);
}

function fileIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase();
  if (ext === 'pdf') return '📄';
  if (['doc','docx'].includes(ext)) return '📝';
  if (['xls','xlsx','ods'].includes(ext)) return '📊';
  if (['dwg','dxf'].includes(ext)) return '📐';
  return '📎';
}

function fmtBytes(b) {
  if (!b) return '–';
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/(1024*1024)).toFixed(1) + ' MB';
}

// ── Activities ────────────────────────────────────────────────────────────────

const ACTIVITY_TYPES = { samtal: 'Samtal', händelse: 'Händelse', anteckning: 'Anteckning' };

async function loadActivities(orderId) {
  const el = document.getElementById('activities-content');
  if (!el) return;
  const activities = await api.get(`/work-orders/${orderId}/activities`).catch(() => []);

  el.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header"><span class="card-title">Ny aktivitet</span></div>
      <div class="card-body">
        <form id="activity-form" style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
          <div class="field" style="margin:0;min-width:140px">
            <label>Typ</label>
            <select name="activity_type">
              ${Object.entries(ACTIVITY_TYPES).map(([k,v]) => `<option value="${k}">${v}</option>`).join('')}
            </select>
          </div>
          <div class="field" style="margin:0;flex:1;min-width:200px">
            <label>Beskrivning *</label>
            <input type="text" name="description" required placeholder="Vad hände?">
          </div>
          <button type="submit" class="btn btn-primary" style="margin-bottom:16px">Registrera</button>
        </form>
      </div>
    </div>

    ${activities.length ? `
      <div class="timeline">
        ${activities.map(a => `
          <div class="timeline-item">
            <div class="timeline-dot timeline-dot-${a.activity_type}"></div>
            <div class="timeline-content">
              <div class="timeline-header">
                <strong>${ACTIVITY_TYPES[a.activity_type] || a.activity_type}</strong>
                <span class="text-muted" style="font-size:12px">${fmtDate(a.created_at, true)}</span>
                ${a.creator ? `<span class="text-muted" style="font-size:12px">• ${a.creator.full_name}</span>` : ''}
                <button class="btn-icon" style="margin-left:auto" onclick="window._deleteActivity(${orderId}, ${a.id})">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                </button>
              </div>
              <p style="margin:4px 0 0;color:var(--text-1)">${a.description}</p>
            </div>
          </div>
        `).join('')}
      </div>
    ` : '<div class="empty-state"><p>Inga aktiviteter registrerade</p></div>'}
  `;

  document.getElementById('activity-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try {
      await api.post(`/work-orders/${orderId}/activities`, body);
      showToast('Aktivitet registrerad', 'success');
      loadActivities(orderId);
    } catch (err) { showToast(err.message, 'error'); }
  });

  window._deleteActivity = async (oid, aid) => {
    if (await confirmDialog('Ta bort aktivitet?')) {
      await api.delete(`/work-orders/${oid}/activities/${aid}`);
      loadActivities(oid);
    }
  };
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

async function loadTasks(orderId, users) {
  const el = document.getElementById('tasks-content');
  if (!el) return;
  const tasks = await api.get(`/work-orders/${orderId}/tasks`).catch(() => []);

  if (!tasks.length) {
    el.innerHTML = `<div class="empty-state"><p>Inga uppgifter</p></div>`;
    return;
  }

  el.innerHTML = `
    <div class="card">
      <div class="card-body" style="padding:0">
        ${tasks.map(t => `
          <div class="task-item ${t.completed ? 'task-done' : ''}">
            <button class="task-check ${t.completed ? 'done' : ''}" onclick="window._toggleTask(${orderId}, ${t.id}, ${!t.completed})">
              ${t.completed ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><polyline points="20 6 9 17 4 12"/></svg>` : ''}
            </button>
            <div style="flex:1">
              <div class="task-title ${t.completed ? 'done' : ''}">${t.title}</div>
              ${t.description ? `<div style="font-size:13px;color:var(--text-2);margin-top:2px">${t.description}</div>` : ''}
              <div style="display:flex;gap:12px;margin-top:4px;font-size:12px;color:var(--text-3)">
                ${t.assigned_user ? `<span>👤 ${t.assigned_user.full_name}</span>` : ''}
                ${t.due_date ? `<span>📅 ${fmtDate(t.due_date)}</span>` : ''}
                ${t.completed && t.completed_at ? `<span>Klar ${fmtDate(t.completed_at, true)}</span>` : ''}
              </div>
            </div>
            <button class="btn-icon" onclick="window._deleteTask(${orderId}, ${t.id})">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
            </button>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  window._toggleTask = async (oid, tid, completed) => {
    await api.put(`/work-orders/${oid}/tasks/${tid}`, { completed });
    loadTasks(oid, users);
  };
  window._deleteTask = async (oid, tid) => {
    if (await confirmDialog('Ta bort uppgift?')) {
      await api.delete(`/work-orders/${oid}/tasks/${tid}`);
      loadTasks(oid, users);
    }
  };
}

function openTaskForm(orderId, task, users, onSaved) {
  openModal({
    title: task ? 'Redigera uppgift' : 'Ny uppgift',
    body: `
      <form id="task-form">
        <div class="field"><label>Titel *</label><input type="text" name="title" value="${task?.title || ''}" required placeholder="Vad ska göras?"></div>
        <div class="field"><label>Beskrivning</label><textarea name="description" rows="2">${task?.description || ''}</textarea></div>
        <div class="form-row">
          <div class="field">
            <label>Tilldelad</label>
            <select name="assigned_to">
              <option value="">Ingen</option>
              ${users.map(u => `<option value="${u.id}" ${task?.assigned_to==u.id?'selected':''}>${u.full_name}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Förfallodatum</label><input type="date" name="due_date" value="${task?.due_date?.slice(0,10) || ''}"></div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${task ? 'Spara' : 'Skapa'}</button>
        </div>
      </form>
    `,
  });
  document.getElementById('task-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    if (body.assigned_to) body.assigned_to = Number(body.assigned_to);
    else delete body.assigned_to;
    if (!body.due_date) delete body.due_date;
    if (!body.description) delete body.description;
    try {
      if (task) await api.put(`/work-orders/${orderId}/tasks/${task.id}`, body);
      else await api.post(`/work-orders/${orderId}/tasks`, body);
      showToast('Uppgift sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function lineRow(l) {
  const total = parseFloat(l.quantity) * parseFloat(l.unit_price);
  return `<tr>
    <td>${l.description}</td>
    <td class="font-mono text-muted">${l.article?.article_number || '–'}</td>
    <td class="text-right quantity-cell">${l.quantity}</td>
    <td>${l.unit}</td>
    <td class="text-right">${fmtPrice(l.unit_price)}</td>
    <td class="text-right">${fmtPrice(total)}</td>
    <td>
      <button class="btn-icon" onclick="window._deleteLine(${l.id})">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
      </button>
    </td>
  </tr>`;
}

function openAddLineForm(orderId, _articlesUnused, onSaved) {
  let selectedArticle = null;
  openModal({
    title: 'Lägg till artikel',
    body: `
      <form id="add-line-form">
        <div class="field">
          <label>Sök artikel i lager (valfritt)</label>
          <div class="search-wrap" style="max-width:none">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
            <input type="search" id="line-article-search" placeholder="Namn, art.nr, plats…">
          </div>
          <div id="line-article-results" class="pl-results"></div>
          <div id="line-article-selected" class="text-muted" style="font-size:12px;margin-top:4px"></div>
        </div>
        <div class="field"><label>Beskrivning *</label><input type="text" name="description" required id="line-desc"></div>
        <div class="form-row">
          <div class="field"><label>Antal</label><input type="number" name="quantity" value="1" step="0.01" min="0.01" required></div>
          <div class="field"><label>Enhet</label><input type="text" name="unit" value="st"></div>
        </div>
        <div class="field"><label>À-pris (kr)</label><input type="number" name="unit_price" value="0" step="0.01" min="0" id="line-price"></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Lägg till</button>
        </div>
      </form>
    `,
  });

  const searchInput = document.getElementById('line-article-search');
  const resultsBox = document.getElementById('line-article-results');
  let searchTimer;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (q.length < 2) { resultsBox.innerHTML = ''; resultsBox.classList.remove('open'); return; }
    searchTimer = setTimeout(async () => {
      const matches = await api.get(`/articles?q=${encodeURIComponent(q)}&limit=25`);
      resultsBox.classList.add('open');
      resultsBox.innerHTML = matches.length
        ? matches.map(a => `
            <div class="pl-result-row" data-id="${a.id}">
              <strong>${a.name}</strong>
              <span class="text-muted">${a.article_number || ''} ${a.location ? '· ' + a.location : ''}</span>
            </div>
          `).join('')
        : `<div class="pl-result-row text-muted">Inga träffar</div>`;
      resultsBox.querySelectorAll('[data-id]').forEach(row => {
        row.addEventListener('click', () => {
          const a = matches.find(x => x.id === parseInt(row.dataset.id));
          selectedArticle = a;
          document.getElementById('line-desc').value = a.name;
          document.getElementById('line-price').value = a.price || 0;
          document.querySelector('[name="unit"]').value = a.unit || 'st';
          document.getElementById('line-article-selected').textContent = `Vald: ${a.name} (${a.article_number || '–'})`;
          searchInput.value = '';
          resultsBox.innerHTML = '';
          resultsBox.classList.remove('open');
        });
      });
    }, 250);
  });

  document.getElementById('add-line-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    body.article_id = selectedArticle ? selectedArticle.id : null;
    body.quantity = parseFloat(body.quantity);
    body.unit_price = parseFloat(body.unit_price);
    try {
      await api.post(`/work-orders/${orderId}/lines`, body);
      showToast('Rad tillagd', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

function openEditWOForm(orderId, users, onSaved) {
  api.get(`/work-orders/${orderId}`).then(wo => {
    openModal({
      title: 'Redigera arbetsorder',
      size: 'modal-lg',
      body: `
        <form id="edit-wo-form">
          <div class="field"><label>Beskrivning *</label><textarea name="description" required>${wo.description}</textarea></div>
          <div class="form-row">
            <div class="field">
              <label>Tilldelad</label>
              <select name="assigned_to">
                <option value="">Ej tilldelad</option>
                ${users.map(u => `<option value="${u.id}" ${wo.assigned_to == u.id ? 'selected' : ''}>${u.full_name}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label>Schemalagd</label>
              <input type="datetime-local" name="scheduled_date" value="${wo.scheduled_date ? wo.scheduled_date.slice(0,16) : ''}">
            </div>
          </div>
          <div class="field"><label>Interna anteckningar</label><textarea name="internal_notes">${wo.internal_notes || ''}</textarea></div>
          <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
            <button type="button" class="btn btn-ghost btn-danger" onclick="window._confirmDeleteWO(${orderId})">Ta bort order</button>
            <div style="flex:1"></div>
            <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
            <button type="submit" class="btn btn-primary">Spara</button>
          </div>
        </form>
      `,
    });
    document.getElementById('edit-wo-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = Object.fromEntries(new FormData(e.target));
      body.assigned_to = body.assigned_to ? Number(body.assigned_to) : null;
      if (!body.scheduled_date) body.scheduled_date = null;
      if (!body.internal_notes) body.internal_notes = null;
      try {
        await api.put(`/work-orders/${orderId}`, body);
        showToast('Arbetsorder uppdaterad', 'success');
        closeModal();
        onSaved?.();
      } catch (err) { showToast(err.message, 'error'); }
    });
    window._confirmDeleteWO = async (oid) => {
      if (await confirmDialog('Ta bort denna arbetsorder permanent?')) {
        await api.delete(`/work-orders/${oid}`);
        showToast('Arbetsorder borttagen', 'success');
        closeModal();
        location.hash = '#/work-orders';
      }
    };
  });
}

function fmtPrice(p) {
  return parseFloat(p).toLocaleString('sv-SE', { minimumFractionDigits: 2 }) + ' kr';
}
