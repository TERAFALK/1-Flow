import { api } from '../api.js?v=4';
import { showToast } from '../components/toast.js?v=4';

export async function renderScanner(el) {
  const orders = await api.get('/work-orders').catch(() => []);
  const activeOrders = orders.filter(o => ['ny', 'planerad', 'pagaende'].includes(o.status));

  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Scanner</div>
        <div class="page-subtitle">Skanna artiklar med USB-streckkodsläsare</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start">

      <!-- Left: order selector + scanned lines -->
      <div>
        <div class="card" style="margin-bottom:16px">
          <div class="card-header"><span class="card-title">Välj arbetsorder</span></div>
          <div class="card-body">
            <div class="field">
              <label>Arbetsorder</label>
              <select id="scanner-order">
                <option value="">– Välj order –</option>
                ${activeOrders.map(o => `<option value="${o.id}">${o.order_number} – ${o.customer?.name || ''} ${o.vehicle?.license_plate || ''}</option>`).join('')}
              </select>
            </div>
            <div id="selected-order-info"></div>
          </div>
        </div>

        <div class="card" id="scan-lines-card" style="display:none">
          <div class="card-header"><span class="card-title">Skannade artiklar</span></div>
          <div id="scan-lines-body" class="card-body" style="padding:0">
            <div class="empty-state" style="padding:24px"><p>Inga artiklar ännu</p></div>
          </div>
        </div>
      </div>

      <!-- Right: scanner panel -->
      <div class="scanner-panel">
        <div class="scanner-header">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 5v2M3 10v2M3 15v2M7 3h2M12 3h2M17 3h2M21 5v2M21 10v2M21 15v2M7 21h2M12 21h2M17 21h2M5 7h14v10H5z"/>
          </svg>
          <span>USB Streckkodsläsare</span>
          <div class="scanner-active-indicator" id="scanner-indicator" style="display:none">
            <span></span> Aktiv
          </div>
        </div>

        <div style="padding:24px">
          <p style="color:var(--text-2);font-size:14px;margin-bottom:20px;line-height:1.6">
            Välj en arbetsorder, tryck sedan <strong>Starta skanning</strong>. Scannern skriver automatiskt och sparar när den är klar.
          </p>

          <button class="btn btn-primary" id="start-scan-btn" disabled>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px">
              <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
            </svg>
            Starta skanning
          </button>

          <div style="margin-top:20px">
            <label style="font-size:12px;font-weight:600;color:var(--text-3);text-transform:uppercase;letter-spacing:.05em">Streckkod</label>
            <input type="text" id="scanner-input" class="scan-input"
              placeholder="Väntar på scanner…"
              autocomplete="off" autocorrect="off" spellcheck="false"
              readonly>
          </div>

          <div id="scan-feedback" class="scan-feedback" style="display:none"></div>
          <div id="stock-warning-box" class="alert alert-warning hidden" style="margin-top:12px"></div>
        </div>
      </div>

    </div>
  `;

  const orderSel    = document.getElementById('scanner-order');
  const startBtn    = document.getElementById('start-scan-btn');
  const input       = document.getElementById('scanner-input');
  const feedback    = document.getElementById('scan-feedback');
  const indicator   = document.getElementById('scanner-indicator');
  const linesCard   = document.getElementById('scan-lines-card');
  const linesBody   = document.getElementById('scan-lines-body');
  const warningBox  = document.getElementById('stock-warning-box');
  const orderInfo   = document.getElementById('selected-order-info');

  let scanning = false;

  orderSel.addEventListener('change', () => {
    const id = orderSel.value;
    if (!id) {
      startBtn.disabled = true;
      stopScanning();
      linesCard.style.display = 'none';
      orderInfo.innerHTML = '';
      return;
    }
    const order = activeOrders.find(o => o.id == id);
    orderInfo.innerHTML = `
      <div class="alert alert-info" style="margin-top:12px;margin-bottom:0">
        <strong>${order.order_number}</strong><br>
        ${order.customer?.name || ''} · ${order.vehicle?.license_plate || ''}<br>
        <span style="font-size:12px;color:var(--text-3)">${order.description || ''}</span>
      </div>
    `;
    startBtn.disabled = false;
    linesCard.style.display = '';
    refreshLines(id);
  });

  startBtn.addEventListener('click', () => {
    if (!scanning) {
      startScanning();
    } else {
      stopScanning();
    }
  });

  function startScanning() {
    scanning = true;
    input.readOnly = false;
    input.value = '';
    input.placeholder = 'Skanna nu…';
    input.focus();
    indicator.style.display = 'flex';
    startBtn.textContent = 'Stoppa skanning';
    startBtn.classList.remove('btn-primary');
    startBtn.classList.add('btn-secondary');
    feedback.style.display = 'none';
  }

  function stopScanning() {
    scanning = false;
    input.readOnly = true;
    input.value = '';
    input.placeholder = 'Väntar på scanner…';
    indicator.style.display = 'none';
    startBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px">
        <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
      </svg>
      Starta skanning`;
    startBtn.classList.add('btn-primary');
    startBtn.classList.remove('btn-secondary');
  }

  // Debounce: auto-submit 120ms after the scanner stops typing
  let debounceTimer = null;

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(debounceTimer);
      submitScan();
      return;
    }
  });

  input.addEventListener('input', () => {
    if (!scanning || !input.value.trim()) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(submitScan, 120);
  });

  async function submitScan() {
    const barcode = input.value.trim();
    if (!barcode || !scanning) return;
    const orderId = orderSel.value;
    input.value = '';

    try {
      const result = await api.post(`/work-orders/${orderId}/scan`, { barcode });
      const name = result.article_name;
      showFeedback(`${name} — ${result.line.quantity} ${result.line.unit}`, result.unknown ? 'warning' : 'success');
      if (result.stock_warning) {
        warningBox.innerHTML = `Lågt lagersaldo på <strong>${name}</strong>: ${result.stock_quantity} ${result.article?.unit || 'st'} kvar`;
        warningBox.classList.remove('hidden');
      } else {
        warningBox.classList.add('hidden');
      }
      showToast(`${name} tillagd`, result.unknown ? 'warning' : 'success', 2000);
      await refreshLines(orderId);
    } catch (err) {
      showFeedback(err.message, 'error');
      showToast(err.message, 'error', 3000);
    }

    setTimeout(() => { if (scanning) input.focus(); }, 80);
  }

  function showFeedback(msg, type) {
    feedback.textContent = msg;
    feedback.className = `scan-feedback scan-feedback-${type}`;
    feedback.style.display = 'block';
    clearTimeout(feedback._timer);
    feedback._timer = setTimeout(() => { feedback.style.display = 'none'; }, 4000);
  }

  async function refreshLines(orderId) {
    const lines = await api.get(`/work-orders/${orderId}/lines`).catch(() => []);
    if (!lines.length) {
      linesBody.innerHTML = '<div class="empty-state" style="padding:24px"><p>Inga artiklar ännu</p></div>';
      return;
    }
    linesBody.innerHTML = `
      <table style="width:100%">
        <thead><tr><th>Artikel</th><th class="text-right">Antal</th><th class="text-right">Pris</th></tr></thead>
        <tbody>
          ${lines.map(l => `
            <tr>
              <td><strong>${l.description}</strong>
                ${l.article?.article_number ? `<br><small class="font-mono text-muted">${l.article.article_number}</small>` : ''}
              </td>
              <td class="text-right">${l.quantity} ${l.unit}</td>
              <td class="text-right">${parseFloat(l.unit_price).toLocaleString('sv-SE')} kr</td>
            </tr>
          `).join('')}
        </tbody>
        <tfoot>
          <tr class="total-row">
            <td colspan="2">Summa delar</td>
            <td class="text-right">${lines.reduce((s, l) => s + parseFloat(l.quantity) * parseFloat(l.unit_price), 0).toLocaleString('sv-SE', { minimumFractionDigits: 2 })} kr</td>
          </tr>
        </tfoot>
      </table>
    `;
  }
}
