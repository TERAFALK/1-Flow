import { api } from '../api.js';
import { fmtDate, statusBadge } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderCustomers(el) {
  let allRows = [];
  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <button class="btn btn-primary btn-sm" id="new-customer-btn">
      <svg viewBox="0 0 20 20" fill="currentColor" style="width:14px;height:14px"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
      Ny kund
    </button>`;

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Kunder</div>
    <div class="page-subtitle" style="margin-bottom:20px">Kundregister</div>
    <div class="card">
      <div class="card-header">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="customer-search" placeholder="Sök kund…">
        </div>
      </div>
      <div id="customer-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-customer-btn')?.addEventListener('click', () => openCustomerForm(null, reload));

  let searchTimer;
  document.getElementById('customer-search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadList(e.target.value), 300);
  });

  async function loadList(q = '') {
    const list = document.getElementById('customer-list');
    if (!list) return;
    const customers = await api.get(`/customers${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    allRows = customers;
    if (!customers.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga kunder hittade</p></div>`;
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Namn</th><th>Org.nr</th><th>Telefon</th><th>E-post</th><th>Ort</th><th></th></tr></thead>
          <tbody>
            ${customers.map(c => `
              <tr class="clickable" onclick="location.hash='#/customers/${c.id}'">
                <td><strong>${c.name}</strong></td>
                <td>${c.org_number || '–'}</td>
                <td>${c.phone || '–'}</td>
                <td>${c.email || '–'}</td>
                <td>${c.city || '–'}</td>
                <td onclick="event.stopPropagation()">
                  <div class="flex gap-2">
                    <button type="button" class="btn-icon" title="Redigera" onclick="window._editCustomer(${c.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                    </button>
                    <button type="button" class="btn-icon" title="Ta bort" onclick="window._deleteCustomer(${c.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
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

  function reload() { loadList(document.getElementById('customer-search')?.value || ''); }

  window._editCustomer = async (id) => {
    const c = await api.get(`/customers/${id}`);
    openCustomerForm(c, reload);
  };
  window._deleteCustomer = async (id) => {
    const c = allRows.find(x => x.id === id);
    const name = (c?.name || 'kunden').replace(/</g, '&lt;');
    if (await confirmDialog(`Ta bort kunden <strong>${name}</strong>? Detta kan inte ångras.`)) {
      try {
        await api.delete(`/customers/${id}`);
        showToast('Kund borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    }
  };

  await loadList();
}

export async function renderCustomerDetail(el, id) {
  el.innerHTML = '<div class="loading">Laddar…</div>';

  const topbarActions = document.getElementById('topbar-actions');
  if (topbarActions) topbarActions.innerHTML = `
    <a href="#/customers" class="btn btn-secondary btn-sm">← Tillbaka</a>
    <button class="btn btn-secondary btn-sm" id="topbar-edit-btn">Redigera</button>
    <a href="#/work-orders/new?customer=${id}" class="btn btn-primary btn-sm">Ny arbetsorder</a>`;

  const [c, vehicles, contacts, orders] = await Promise.all([
    api.get(`/customers/${id}`),
    api.get(`/vehicles?customer_id=${id}`),
    api.get(`/customers/${id}/contacts`),
    api.get(`/work-orders?q=`).then(all => all.filter(o => o.customer_id == id)).catch(() => []),
  ]);

  document.getElementById('topbar-title') && (document.getElementById('topbar-title').textContent = c.name);
  document.getElementById('topbar-edit-btn')?.addEventListener('click', () =>
    openCustomerForm(c, () => renderCustomerDetail(el, id))
  );

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">${c.name}</div>
      ${c.org_number ? `<div class="page-subtitle">Org.nr: ${c.org_number}</div>` : ''}
    </div>

    <div class="tabs" id="customer-tabs">
      <div class="tab active" data-tab="info">Info</div>
      <div class="tab" data-tab="contacts">Kontaktpersoner <span style="font-size:11px;opacity:.6">(${contacts.length})</span></div>
      <div class="tab" data-tab="vehicles">Fordon <span style="font-size:11px;opacity:.6">(${vehicles.length})</span></div>
      <div class="tab" data-tab="history">Historik <span style="font-size:11px;opacity:.6">(${orders.length})</span></div>
    </div>

    <div id="tab-info">
      <div style="display:grid;grid-template-columns:320px 1fr;gap:16px">
        <div class="card">
          <div class="card-header"><span class="card-title">Kontaktuppgifter</span></div>
          <div class="card-body">
            ${metaRow('Telefon', c.phone)}
            ${metaRow('E-post', c.email)}
            ${metaRow('Adress', c.address)}
            ${metaRow('Postnummer', c.postal_code)}
            ${metaRow('Ort', c.city)}
            ${c.notes ? `<hr class="divider"><p style="font-size:13px;color:var(--text-2)">${c.notes}</p>` : ''}
          </div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">Primär kontaktperson</span></div>
          <div class="card-body">
            ${contacts.filter(c => c.is_primary).map(ct => `
              <div><strong>${ct.name}</strong>${ct.title ? ` · ${ct.title}` : ''}</div>
              ${ct.phone ? `<div style="font-size:13px;color:var(--text-2)">${ct.phone}</div>` : ''}
              ${ct.email ? `<div style="font-size:13px;color:var(--text-2)">${ct.email}</div>` : ''}
            `).join('') || '<p style="color:var(--text-3);font-size:13px">Ingen primär kontakt angiven</p>'}
          </div>
        </div>
      </div>
    </div>

    <div id="tab-contacts" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Kontaktpersoner</span>
          <button class="btn btn-primary btn-sm" id="add-contact-btn">+ Lägg till</button>
        </div>
        <div id="contacts-body">
          ${renderContactsTable(contacts)}
        </div>
      </div>
    </div>

    <div id="tab-vehicles" class="hidden">
      <div class="card">
        <div class="card-header">
          <span class="card-title">Kopplade fordon</span>
          <a href="#/vehicles/new?customer=${id}" class="btn btn-primary btn-sm">+ Lägg till fordon</a>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Reg.nr</th><th>Märke</th><th>Modell</th><th>År</th><th>Mätarställning</th></tr></thead>
            <tbody>
              ${vehicles.length ? vehicles.map(v => `
                <tr class="clickable" onclick="location.hash='#/vehicles/${v.id}'">
                  <td><strong>${v.license_plate}</strong></td>
                  <td>${v.make || '–'}</td>
                  <td>${v.model || '–'}</td>
                  <td>${v.year || '–'}</td>
                  <td>${v.odometer ? v.odometer.toLocaleString('sv-SE') + ' km' : '–'}</td>
                </tr>
              `).join('') : '<tr><td colspan="5" style="text-align:center;padding:28px;color:var(--text-3)">Inga fordon registrerade</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="tab-history" class="hidden">
      <div class="card">
        <div class="card-header"><span class="card-title">Arbetsorder-historik</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Order</th><th>Fordon</th><th>Beskrivning</th><th>Status</th><th>Datum</th></tr></thead>
            <tbody>
              ${orders.length ? orders.map(o => `
                <tr class="clickable" onclick="location.hash='#/work-orders/${o.id}'">
                  <td><strong>${o.order_number}</strong></td>
                  <td>${o.vehicle?.license_plate || '–'}</td>
                  <td>${o.description}</td>
                  <td>${statusBadge(o.status)}</td>
                  <td class="text-muted">${fmtDate(o.created_at)}</td>
                </tr>
              `).join('') : '<tr><td colspan="5" style="text-align:center;padding:28px;color:var(--text-3)">Inga arbetsorder</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  // Tab switching
  document.getElementById('customer-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    document.querySelectorAll('#customer-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    ['info', 'contacts', 'vehicles', 'history'].forEach(name => {
      document.getElementById(`tab-${name}`).classList.toggle('hidden', name !== tab.dataset.tab);
    });
  });

  // Contacts tab actions
  document.getElementById('add-contact-btn')?.addEventListener('click', () =>
    openContactForm(id, null, async () => {
      const updated = await api.get(`/customers/${id}/contacts`);
      document.getElementById('contacts-body').innerHTML = renderContactsTable(updated);
      bindContactActions(id);
    })
  );
  bindContactActions(id);
}

function renderContactsTable(contacts) {
  if (!contacts.length) return '<div class="empty-state" style="padding:32px"><p>Inga kontaktpersoner</p></div>';
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Namn</th><th>Titel</th><th>Telefon</th><th>E-post</th><th>Primär</th><th></th></tr></thead>
        <tbody>
          ${contacts.map(ct => `
            <tr>
              <td><strong>${ct.name}</strong></td>
              <td>${ct.title || '–'}</td>
              <td>${ct.phone || '–'}</td>
              <td>${ct.email || '–'}</td>
              <td>${ct.is_primary ? '<span class="badge badge-klar">Primär</span>' : ''}</td>
              <td>
                <div class="flex gap-2">
                  <button type="button" class="btn-icon" title="Redigera" data-edit-contact="${ct.id}">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                  </button>
                  <button type="button" class="btn-icon" title="Ta bort" data-del-contact="${ct.id}" data-customer-id="${ct.customer_id}">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>`;
}

function bindContactActions(customerId) {
  document.querySelectorAll('[data-edit-contact]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const contacts = await api.get(`/customers/${customerId}/contacts`);
      const ct = contacts.find(c => c.id == btn.dataset.editContact);
      if (ct) openContactForm(customerId, ct, async () => {
        const updated = await api.get(`/customers/${customerId}/contacts`);
        document.getElementById('contacts-body').innerHTML = renderContactsTable(updated);
        bindContactActions(customerId);
      });
    });
  });
  document.querySelectorAll('[data-del-contact]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort kontaktpersonen?')) return;
      await api.delete(`/customers/${customerId}/contacts/${btn.dataset.delContact}`);
      showToast('Kontaktperson borttagen', 'success');
      const updated = await api.get(`/customers/${customerId}/contacts`);
      document.getElementById('contacts-body').innerHTML = renderContactsTable(updated);
      bindContactActions(customerId);
    });
  });
}

function openContactForm(customerId, contact, onSaved) {
  openModal({
    title: contact ? 'Redigera kontaktperson' : 'Ny kontaktperson',
    body: `
      <form id="contact-form">
        <div class="form-row">
          <div class="field"><label>Namn *</label><input type="text" name="name" value="${contact?.name || ''}" required></div>
          <div class="field"><label>Titel</label><input type="text" name="title" value="${contact?.title || ''}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Telefon</label><input type="text" name="phone" value="${contact?.phone || ''}"></div>
          <div class="field"><label>E-post</label><input type="email" name="email" value="${contact?.email || ''}"></div>
        </div>
        <div class="field">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" name="is_primary" ${contact?.is_primary ? 'checked' : ''}> Primär kontaktperson
          </label>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${contact ? 'Spara' : 'Lägg till'}</button>
        </div>
      </form>
    `,
  });

  document.getElementById('contact-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      name: fd.get('name'),
      title: fd.get('title') || null,
      phone: fd.get('phone') || null,
      email: fd.get('email') || null,
      is_primary: fd.get('is_primary') === 'on',
    };
    try {
      if (contact) {
        await api.put(`/customers/${customerId}/contacts/${contact.id}`, body);
        showToast('Kontaktperson uppdaterad', 'success');
      } else {
        await api.post(`/customers/${customerId}/contacts`, body);
        showToast('Kontaktperson skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function metaRow(label, value) {
  if (!value) return '';
  return `<div class="meta-row"><span class="meta-label">${label}:</span><span>${value}</span></div>`;
}

export function openCustomerForm(customer, onSaved) {
  openModal({
    title: customer ? 'Redigera kund' : 'Ny kund',
    size: 'modal-lg',
    body: `
      <form id="customer-form">
        <div class="form-row">
          <div class="field"><label>Namn *</label><input type="text" name="name" value="${customer?.name || ''}" required></div>
          <div class="field"><label>Org.nr</label><input type="text" name="org_number" value="${customer?.org_number || ''}"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Telefon</label><input type="text" name="phone" value="${customer?.phone || ''}"></div>
          <div class="field"><label>E-post</label><input type="email" name="email" value="${customer?.email || ''}"></div>
        </div>
        <div class="field"><label>Adress</label><input type="text" name="address" value="${customer?.address || ''}"></div>
        <div class="form-row">
          <div class="field"><label>Postnummer</label><input type="text" name="postal_code" value="${customer?.postal_code || ''}"></div>
          <div class="field"><label>Ort</label><input type="text" name="city" value="${customer?.city || ''}"></div>
        </div>
        <div class="field"><label>Anteckningar</label><textarea name="notes">${customer?.notes || ''}</textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${customer ? 'Spara' : 'Skapa kund'}</button>
        </div>
      </form>
    `,
  });

  document.getElementById('customer-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    Object.keys(body).forEach(k => { if (!body[k]) body[k] = null; });
    try {
      if (customer) {
        await api.put(`/customers/${customer.id}`, body);
        showToast('Kund uppdaterad', 'success');
      } else {
        await api.post('/customers', body);
        showToast('Kund skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}
