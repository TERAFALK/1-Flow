import { api, downloadFile } from '../api.js';
import { showToast } from '../components/toast.js';

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
          <div class="card-header"><span class="card-title">Läge</span></div>
          <div class="card-body">
            <div class="field">
              <label><input type="radio" name="scan-mode" id="mode-order" value="order" checked> Arbetsorder</label><br>
              <label><input type="radio" name="scan-mode" id="mode-temp" value="temp"> Tillfällig lista (utan order)</label>
            </div>
          </div>
        </div>

        <div class="card" style="margin-bottom:16px" id="order-select-card">
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

        <div class="card" style="margin-bottom:16px;display:none" id="temp-list-card">
          <div class="card-header"><span class="card-title">Tillfällig lista</span></div>
          <div class="card-body">
            <button class="btn btn-secondary" id="new-temp-list-btn" style="width:100%">+ Ny tillfällig lista</button>
            <div id="temp-list-info"></div>
          </div>
        </div>

        <div class="card" id="scan-lines-card" style="display:none">
          <div class="card-header">
            <span class="card-title">Skannade artiklar</span>
            <button class="btn btn-ghost" id="print-scan-list-btn" style="display:none">Ladda ner PDF</button>
          </div>
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

  const orderSel      = document.getElementById('scanner-order');
  const startBtn      = document.getElementById('start-scan-btn');
  const input         = document.getElementById('scanner-input');
  const feedback      = document.getElementById('scan-feedback');
  const indicator     = document.getElementById('scanner-indicator');
  const linesCard     = document.getElementById('scan-lines-card');
  const linesBody     = document.getElementById('scan-lines-body');
  const warningBox    = document.getElementById('stock-warning-box');
  const orderInfo     = document.getElementById('selected-order-info');
  const orderCard     = document.getElementById('order-select-card');
  const tempCard      = document.getElementById('temp-list-card');
  const tempInfo      = document.getElementById('temp-list-info');
  const newTempBtn    = document.getElementById('new-temp-list-btn');
  const printListBtn  = document.getElementById('print-scan-list-btn');
  const modeOrderRadio = document.getElementById('mode-order');
  const modeTempRadio  = document.getElementById('mode-temp');

  let scanning = false;
  let mode = 'order'; // 'order' | 'temp'
  let tempListId = null;

  function currentTargetId() {
    return mode === 'order' ? orderSel.value : tempListId;
  }

  document.querySelectorAll('input[name="scan-mode"]').forEach(r => {
    r.addEventListener('change', () => {
      mode = r.value;
      stopScanning();
      warningBox.classList.add('hidden');
      if (mode === 'order') {
        orderCard.style.display = '';
        tempCard.style.display = 'none';
        printListBtn.style.display = 'none';
        if (orderSel.value) {
          startBtn.disabled = false;
          linesCard.style.display = '';
          refreshLines(orderSel.value);
        } else {
          startBtn.disabled = true;
          linesCard.style.display = 'none';
        }
      } else {
        orderCard.style.display = 'none';
        tempCard.style.display = '';
        startBtn.disabled = !tempListId;
        linesCard.style.display = tempListId ? '' : 'none';
        printListBtn.style.display = tempListId ? '' : 'none';
        if (tempListId) refreshLines(tempListId);
      }
    });
  });

  newTempBtn.addEventListener('click', async () => {
    try {
      const title = `Tillfällig skanning ${new Date().toLocaleString('sv-SE')}`;
      const pl = await api.post('/pick-lists', { title, lines: [] });
      tempListId = pl.id;
      tempInfo.innerHTML = `
        <div class="alert alert-info" style="margin-top:12px;margin-bottom:0">
          <strong>${pl.title}</strong>
        </div>
      `;
      startBtn.disabled = false;
      linesCard.style.display = '';
      printListBtn.style.display = '';
      await refreshLines(tempListId);
      showToast('Tillfällig lista skapad', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  printListBtn.addEventListener('click', async () => {
    if (!tempListId) return;
    try {
      await downloadFile(`/pick-lists/${tempListId}/pdf`, `skanning-${tempListId}.pdf`);
    } catch (err) { showToast(err.message, 'error'); }
  });

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
    const targetId = currentTargetId();
    input.value = '';
    if (!targetId) return;

    try {
      const result = mode === 'order'
        ? await api.post(`/work-orders/${targetId}/scan`, { barcode })
        : await api.post(`/pick-lists/${targetId}/scan`, { barcode });
      const name = result.article_name;
      showFeedback(`${name} — ${result.line.quantity} ${result.line.unit}`, result.unknown ? 'warning' : 'success');
      if (result.stock_warning) {
        warningBox.innerHTML = `Lågt lagersaldo på <strong>${name}</strong>: ${result.stock_quantity} ${result.article?.unit || 'st'} kvar`;
        warningBox.classList.remove('hidden');
      } else {
        warningBox.classList.add('hidden');
      }
      showToast(`${name} tillagd`, result.unknown ? 'warning' : 'success', 2000);
      await refreshLines(targetId);
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

  async function refreshLines(targetId) {
    const lines = mode === 'order'
      ? await api.get(`/work-orders/${targetId}/lines`).catch(() => [])
      : await api.get(`/pick-lists/${targetId}`).then(pl => pl.lines).catch(() => []);
    if (!lines.length) {
      linesBody.innerHTML = '<div class="empty-state" style="padding:24px"><p>Inga artiklar ännu</p></div>';
      return;
    }
    linesBody.innerHTML = `
      <table style="width:100%">
        <thead><tr><th>Artikel</th><th class="text-right">Antal</th></tr></thead>
        <tbody>
          ${lines.map(l => `
            <tr>
              <td><strong>${l.description}</strong>
                ${(l.article?.article_number || l.article_number) ? `<br><small class="font-mono text-muted">${l.article?.article_number || l.article_number}</small>` : ''}
              </td>
              <td class="text-right">${l.quantity} ${l.unit}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }
}
