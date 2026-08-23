import { api } from '../api.js';
import { showToast } from '../components/toast.js';
import { confirmDialog } from '../components/modal.js';

export async function renderSettings(el) {
  el.innerHTML = '<div class="loading">Laddar inställningar…</div>';

  const settingsList = await api.get('/settings').catch(() => []);
  const settings = Object.fromEntries(settingsList.map(s => [s.key, s.value]));

  el.innerHTML = `
    <div class="page-title" style="margin-bottom:4px">Inställningar</div>
    <div class="page-subtitle" style="margin-bottom:24px">Systemkonfiguration</div>

    <div style="max-width:560px;display:flex;flex-direction:column;gap:16px">

      <div class="card">
        <div class="card-header"><span class="card-title">Numrering</span></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:20px">

          <div class="setting-row">
            <div>
              <div style="font-weight:600;font-size:14px">Ordernummer</div>
              <div style="font-size:13px;color:var(--text-2);margin-top:2px">
                Automatisk genererar <strong>AO-YYYY-NNNN</strong>. Manuellt kräver att du anger nummer vid skapande.
              </div>
            </div>
            <div class="toggle-group" id="order-number-toggle">
              <button class="toggle-btn ${settings.order_number_mode !== 'manual' ? 'active' : ''}" data-value="auto">Automatisk</button>
              <button class="toggle-btn ${settings.order_number_mode === 'manual' ? 'active' : ''}" data-value="manual">Manuell</button>
            </div>
          </div>

          <hr class="divider" style="margin:0">

          <div class="setting-row">
            <div>
              <div style="font-weight:600;font-size:14px">Inköpsnummer</div>
              <div style="font-size:13px;color:var(--text-2);margin-top:2px">
                Automatisk genererar <strong>INK-YYYY-NNNN</strong>. Manuellt kräver att du anger nummer.
              </div>
            </div>
            <div class="toggle-group" id="purchase-number-toggle">
              <button class="toggle-btn ${settings.purchase_number_mode !== 'manual' ? 'active' : ''}" data-value="auto">Automatisk</button>
              <button class="toggle-btn ${settings.purchase_number_mode === 'manual' ? 'active' : ''}" data-value="manual">Manuell</button>
            </div>
          </div>

        </div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-title">Försäljning</span></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:20px">
          <div>
            <div style="font-weight:600;font-size:14px">Objekttyper</div>
            <div style="font-size:13px;color:var(--text-2);margin:2px 0 8px">
              Väljbara objekt i offertförfrågningar. Kommaseparerade.
            </div>
            <div class="flex gap-2">
              <input type="text" id="sales-types" style="flex:1"
                     value="${(settings.sales_product_types || '').replace(/"/g, '&quot;')}">
              <button class="btn btn-primary btn-sm" id="sales-types-save">Spara</button>
            </div>
          </div>

          <hr class="divider" style="margin:0">

          <div>
            <div style="font-weight:600;font-size:14px">Milstolpar för sålda ordrar</div>
            <div style="font-size:13px;color:var(--text-2);margin:2px 0 8px">
              Checklistan som varje såld order får. Ta bort steg som inte används – redan ifyllda värden på gamla ordrar behålls.
            </div>
            <div id="milestone-defs"><div class="loading">Laddar…</div></div>
          </div>
        </div>
      </div>

    </div>
  `;

  async function bindToggle(containerId, settingKey) {
    const container = document.getElementById(containerId);
    container.addEventListener('click', async (e) => {
      const btn = e.target.closest('.toggle-btn');
      if (!btn) return;
      container.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      try {
        await api.put(`/settings/${settingKey}`, { value: btn.dataset.value });
        showToast('Inställning sparad', 'success', 2000);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  bindToggle('order-number-toggle', 'order_number_mode');
  bindToggle('purchase-number-toggle', 'purchase_number_mode');

  document.getElementById('sales-types-save')?.addEventListener('click', async () => {
    try {
      await api.put('/settings/sales_product_types', {
        value: document.getElementById('sales-types').value,
      });
      showToast('Objekttyper sparade', 'success', 2000);
    } catch (err) { showToast(err.message, 'error'); }
  });

  await loadMilestoneDefs();
}

async function loadMilestoneDefs() {
  const host = document.getElementById('milestone-defs');
  if (!host) return;
  const defs = await api.get('/sales/milestone-defs').catch(() => []);
  if (!defs.length) {
    host.innerHTML = '<div class="empty-state" style="padding:24px"><p>Inga milstolpar</p></div>';
    return;
  }
  const groups = [];
  for (const d of defs) {
    let g = groups.find(x => x.label === d.group_label);
    if (!g) { g = { label: d.group_label, items: [] }; groups.push(g); }
    g.items.push(d);
  }
  const TYPES = { datum: 'Datum', text: 'Text', ja_nej: 'Ja/Nej' };
  host.innerHTML = groups.map(g => `
    <div style="margin-bottom:12px">
      <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:4px">${g.label}</div>
      ${g.items.map(d => `
        <div class="ms-row">
          <span class="ms-label">${d.label}</span>
          <span class="text-muted" style="font-size:12px">${TYPES[d.value_type] || d.value_type}</span>
          <button type="button" class="btn-icon" title="Ta bort" data-del-def="${d.id}">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
          </button>
        </div>`).join('')}
    </div>`).join('');

  host.querySelectorAll('[data-del-def]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort milstolpen? Redan ifyllda datum på gamla ordrar behålls men visas inte längre.')) return;
      try {
        await api.delete(`/sales/milestone-defs/${btn.dataset.delDef}`);
        showToast('Milstolpe borttagen', 'success');
        await loadMilestoneDefs();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}
