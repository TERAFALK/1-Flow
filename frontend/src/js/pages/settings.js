import { api } from '../api.js?v=4';
import { showToast } from '../components/toast.js?v=4';

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
}
