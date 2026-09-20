import { api, downloadFile } from '../api.js';
import { showToast } from '../components/toast.js';
import { confirmDialog } from '../components/modal.js';

// Valt läge och vald skanning överlever omladdning och sessionsbyte. Utan det
// här försvann en tillfällig skanning så fort sidan laddades om – referensen
// levde bara i den här modulens minne.
const STATE_KEY = 'flow_scan_state';
const SOUND_KEY = 'flow_scan_sound';

// Lyssnarna nedan sitter på document och måste rivas när man navigerar bort.
// Modulnivå, så att en ny rendering alltid städar efter den förra – app.js kan
// laddas i två instanser och då finns den här modulen också i två exemplar.
let pageListeners = null;
let audioCtx = null;

const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Visar antalet utan onödiga decimaler: 3.00 → 3, 2.50 → 2.5 */
const fmtQty = (q) => String(Number(q));

const fmtWhen = (iso) => {
  try { return new Date(iso).toLocaleString('sv-SE', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return ''; }
};

// ── Ljudkvittens ──────────────────────────────────────────────────────────────
// Ingen ljudfil och inget beroende – två korta toner räcker för att höra på
// avstånd om en skanning gick igenom eller inte. AudioContext får skapas först
// vid en användarhandling, annars blockerar webbläsaren den.
function soundEnabled() {
  try { return localStorage.getItem(SOUND_KEY) !== 'off'; } catch { return true; }
}

function beep(freq, ms, delay = 0) {
  if (!soundEnabled()) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const t0 = audioCtx.currentTime + delay;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'square';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.12, t0 + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + ms / 1000);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(t0);
    osc.stop(t0 + ms / 1000 + 0.02);
  } catch { /* ljud är en bonus, aldrig ett hinder */ }
}

const beepOk = () => beep(1320, 80);
const beepWarn = () => { beep(460, 110); beep(330, 130, 0.15); };

// ── Sparat läge ───────────────────────────────────────────────────────────────
function loadState() {
  try { return JSON.parse(localStorage.getItem(STATE_KEY) || '{}'); } catch { return {}; }
}

function storeState(state) {
  try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch { /* privat läge */ }
}

export async function renderScanner(el, params = {}) {
  const orders = await api.get('/work-orders').catch(() => []);
  const activeOrders = orders.filter(o => ['ny', 'planerad', 'pagaende'].includes(o.status));

  const saved = loadState();
  let mode = saved.mode === 'temp' ? 'temp' : 'order';
  let orderId = saved.orderId || '';
  let tempList = null;          // { id, title }
  let showClosed = false;

  // Djuplänk från arbetsordern (#/scanner?order=12) vinner över sparat läge.
  // Routern har alltid skickat params hit, men signaturen tog inte emot dem.
  if (params.order) {
    mode = 'order';
    orderId = String(params.order);
  }
  if (orderId && !activeOrders.some(o => String(o.id) === String(orderId))) orderId = '';

  // En sparad skanning kan ha hunnit avslutas eller tas bort. Då lämnas valet
  // tomt i stället för att peka på något som inte finns – kortet med öppna
  // skanningar längre ner visar vad som går att ta upp i stället.
  if (saved.tempListId) {
    const pl = await api.get(`/pick-lists/${saved.tempListId}`).catch(() => null);
    if (pl && !pl.closed_at) tempList = { id: pl.id, title: pl.title };
  }

  el.innerHTML = `
    <div class="scanner-page">
      <div class="page-header">
        <div>
          <div class="page-title">Skanning</div>
          <div class="page-subtitle">Skanna artiklar med USB-streckkodsläsare</div>
        </div>
      </div>

      <div class="scan-hero">
        <div class="scan-hero-top">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 5v2M3 10v2M3 15v2M7 3h2M12 3h2M17 3h2M21 5v2M21 10v2M21 15v2M7 21h2M12 21h2M17 21h2M5 7h14v10H5z"/>
          </svg>
          <span>USB Streckkodsläsare</span>
          <button type="button" class="scan-sound-btn" id="scan-sound-btn"></button>
        </div>

        <div class="scan-hero-body">
          <div class="tabs scan-mode-tabs">
            <div class="tab" data-mode="order">Arbetsorder</div>
            <div class="tab" data-mode="temp">Tillfällig skanning</div>
          </div>

          <div id="scan-target"></div>

          <div class="scan-status" id="scan-status">
            <span class="scan-status-dot"></span>
            <span id="scan-status-text"></span>
          </div>

          <input type="text" id="scanner-input" class="scan-input"
            placeholder="Skanna eller skriv streckkod…"
            autocomplete="off" autocorrect="off" spellcheck="false" readonly>

          <div id="scan-feedback" class="scan-feedback" style="display:none"></div>
          <div id="stock-warning-box" class="alert alert-warning hidden" style="margin-top:12px"></div>
        </div>
      </div>

      <div class="card" id="scan-lines-card" style="display:none;margin-bottom:20px">
        <div class="card-header">
          <span class="card-title">Skannade artiklar <span id="scan-lines-count" class="text-muted"></span></span>
          <div class="flex gap-2">
            <button class="btn btn-ghost btn-sm" id="print-scan-list-btn" style="display:none">Ladda ner PDF</button>
            <button class="btn btn-secondary btn-sm" id="close-scan-btn" style="display:none">Avsluta skanning</button>
          </div>
        </div>
        <div id="scan-lines-body" class="card-body" style="padding:0">
          <div class="empty-state" style="padding:24px"><p>Inga artiklar ännu</p></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <span class="card-title" id="resume-title">Öppna skanningar</span>
          <button class="btn btn-ghost btn-sm" id="toggle-closed-btn">Visa avslutade</button>
        </div>
        <div id="scan-resume-body" class="card-body" style="padding:0">
          <div class="loading">Laddar…</div>
        </div>
      </div>
    </div>
  `;

  const $ = (id) => document.getElementById(id);
  const input       = $('scanner-input');
  const feedback    = $('scan-feedback');
  const warningBox  = $('stock-warning-box');
  const linesCard   = $('scan-lines-card');
  const linesBody   = $('scan-lines-body');
  const linesCount  = $('scan-lines-count');
  const printListBtn = $('print-scan-list-btn');
  const closeScanBtn = $('close-scan-btn');
  const resumeBody  = $('scan-resume-body');
  const statusEl    = $('scan-status');
  const statusText  = $('scan-status-text');
  const soundBtn    = $('scan-sound-btn');

  function currentTargetId() {
    return mode === 'order' ? orderId : (tempList ? tempList.id : null);
  }

  function persist() {
    storeState({ mode, orderId: orderId || null, tempListId: tempList ? tempList.id : null });
  }

  // ── Status ──────────────────────────────────────────────────────────────────
  // Skanningen är alltid igång. Det enda som pausar den är att ett textfält har
  // fokus – annars skulle streckkoden hamna där i stället för i kodfältet.
  function typingInField() {
    const a = document.activeElement;
    if (!a || a === input) return false;
    return a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || a.isContentEditable;
  }

  function updateStatus() {
    if (!statusEl.isConnected) return;
    const hasTarget = !!currentTargetId();
    input.readOnly = !hasTarget;
    statusEl.classList.toggle('is-ready', hasTarget && !typingInField());
    statusEl.classList.toggle('is-paused', hasTarget && typingInField());
    if (!hasTarget) {
      statusText.textContent = mode === 'order'
        ? 'Välj en arbetsorder för att börja skanna'
        : 'Starta en ny skanning eller fortsätt på en påbörjad';
    } else if (typingInField()) {
      statusText.textContent = 'Pausad medan du skriver – klicka utanför fältet för att fortsätta';
    } else {
      statusText.textContent = 'Redo att skanna – skanna direkt, du behöver inte klicka någonstans';
    }
  }

  function renderSoundBtn() {
    const on = soundEnabled();
    soundBtn.innerHTML = on
      ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 010 7"/></svg> Ljud på`
      : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5zM22 9l-6 6M16 9l6 6"/></svg> Ljud av`;
  }
  renderSoundBtn();
  soundBtn.addEventListener('click', () => {
    try { localStorage.setItem(SOUND_KEY, soundEnabled() ? 'off' : 'on'); } catch { /* privat läge */ }
    renderSoundBtn();
    if (soundEnabled()) beepOk();
  });

  // ── Lägesflikar ─────────────────────────────────────────────────────────────
  function renderTabs() {
    document.querySelectorAll('.scan-mode-tabs .tab').forEach(t => {
      t.classList.toggle('active', t.dataset.mode === mode);
    });
  }

  document.querySelectorAll('.scan-mode-tabs .tab').forEach(tab => {
    tab.addEventListener('click', async () => {
      if (mode === tab.dataset.mode) return;
      mode = tab.dataset.mode;
      warningBox.classList.add('hidden');
      persist();
      renderTabs();
      renderTarget();
      await syncLines();
      updateStatus();
    });
  });

  // ── Mål: arbetsorder eller tillfällig skanning ──────────────────────────────
  function renderTarget() {
    const wrap = $('scan-target');
    if (mode === 'order') {
      const order = activeOrders.find(o => String(o.id) === String(orderId));
      wrap.innerHTML = `
        <div class="scan-target-row">
          <div class="field">
            <label>Arbetsorder</label>
            <select id="scanner-order">
              <option value="">– Välj order –</option>
              ${activeOrders.map(o => `
                <option value="${o.id}" ${String(o.id) === String(orderId) ? 'selected' : ''}>
                  ${esc(o.order_number)} – ${esc(o.customer?.name || '')} ${esc(o.vehicle?.license_plate || '')}
                </option>`).join('')}
            </select>
          </div>
        </div>
        ${order ? `
          <div class="alert alert-info" style="margin-bottom:18px">
            <strong>${esc(order.order_number)}</strong><br>
            ${esc(order.customer?.name || '')} · ${esc(order.vehicle?.license_plate || '')}<br>
            <span style="font-size:12px;color:var(--text-3)">${esc(order.description || '')}</span>
          </div>` : ''}
      `;
      $('scanner-order').addEventListener('change', async (e) => {
        orderId = e.target.value;
        persist();
        renderTarget();
        await syncLines();
        updateStatus();
      });
    } else if (tempList) {
      wrap.innerHTML = `
        <div class="scan-active-list">
          <span class="badge badge-tekniker">Skanning</span>
          <strong>${esc(tempList.title)}</strong>
          <button type="button" class="btn btn-ghost btn-sm" id="rename-temp-btn">Byt namn</button>
          <button type="button" class="btn btn-secondary btn-sm" id="switch-temp-btn">Byt skanning</button>
        </div>
      `;
      $('rename-temp-btn').addEventListener('click', showRenameForm);
      $('switch-temp-btn').addEventListener('click', async () => {
        tempList = null;
        persist();
        renderTarget();
        await syncLines();
        updateStatus();
      });
    } else {
      wrap.innerHTML = `
        <div class="scan-target-row">
          <div class="field">
            <label>Namn på skanningen</label>
            <input type="text" id="temp-list-name" maxlength="120"
              placeholder="t.ex. Servicebil 3 – påfyllning" autocomplete="off">
          </div>
          <div class="scan-target-actions">
            <button type="button" class="btn btn-primary" id="new-temp-list-btn">+ Ny skanning</button>
          </div>
        </div>
      `;
      $('new-temp-list-btn').addEventListener('click', createTempList);
      $('temp-list-name').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); createTempList(); }
      });
    }
  }

  async function createTempList() {
    const field = $('temp-list-name');
    // Utan angivet namn faller vi tillbaka på datum och tid, som tidigare
    const title = (field?.value || '').trim()
      || `Tillfällig skanning ${new Date().toLocaleString('sv-SE')}`;
    try {
      const pl = await api.post('/pick-lists', { title, kind: 'skanning', lines: [] });
      tempList = { id: pl.id, title: pl.title };
      persist();
      renderTarget();
      await syncLines();
      await loadResumeList();
      updateStatus();
      showToast('Skanning skapad', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  }

  function showRenameForm() {
    const wrap = $('scan-target');
    wrap.innerHTML = `
      <div class="scan-target-row">
        <div class="field">
          <label>Namn på skanningen</label>
          <input type="text" id="temp-rename-input" maxlength="120" autocomplete="off"
            value="${esc(tempList.title)}">
        </div>
        <div class="scan-target-actions">
          <button type="button" class="btn btn-primary" id="temp-rename-save">Spara</button>
          <button type="button" class="btn btn-secondary" id="temp-rename-cancel">Avbryt</button>
        </div>
      </div>
    `;
    const field = $('temp-rename-input');
    field.focus();
    field.select();
    updateStatus();
    field.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); saveRename(); }
      if (e.key === 'Escape') { e.preventDefault(); renderTarget(); updateStatus(); }
    });
    $('temp-rename-save').addEventListener('click', saveRename);
    $('temp-rename-cancel').addEventListener('click', () => { renderTarget(); updateStatus(); });
  }

  async function saveRename() {
    const field = $('temp-rename-input');
    const title = (field?.value || '').trim();
    if (!title) { showToast('Namnet kan inte vara tomt', 'error'); field?.focus(); return; }
    if (title === tempList.title) { renderTarget(); updateStatus(); return; }
    try {
      const pl = await api.put(`/pick-lists/${tempList.id}`, { title });
      tempList.title = pl.title;
      renderTarget();
      await loadResumeList();
      updateStatus();
      showToast('Skanningen döptes om', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  }

  // ── Öppna skanningar ────────────────────────────────────────────────────────
  // Kortet som gör att en påbörjad skanning alltid går att ta upp igen, av den
  // som startade den eller av en kollega som tar vid.
  async function loadResumeList() {
    if (!resumeBody.isConnected) return;
    const lists = await api
      .get(`/pick-lists?kind=skanning${showClosed ? '&include_closed=true' : ''}`)
      .catch(() => []);
    $('resume-title').textContent = showClosed ? 'Skanningar' : 'Öppna skanningar';
    $('toggle-closed-btn').textContent = showClosed ? 'Visa bara öppna' : 'Visa avslutade';

    if (!lists.length) {
      resumeBody.innerHTML = `<div class="empty-state" style="padding:24px"><p>${
        showClosed ? 'Inga skanningar ännu' : 'Inga påbörjade skanningar'
      }</p></div>`;
      return;
    }

    resumeBody.innerHTML = lists.map(p => {
      const isActive = tempList && tempList.id === p.id;
      const closed = !!p.closed_at;
      return `
        <div class="scan-resume-row">
          <div class="scan-resume-main">
            <div class="scan-resume-title">
              ${esc(p.title)}
              ${closed ? '<span class="badge badge-fakturerad" style="margin-left:6px">Avslutad</span>' : ''}
              ${isActive ? '<span class="badge badge-success" style="margin-left:6px">Aktiv</span>' : ''}
            </div>
            <div class="scan-resume-meta">
              ${p.line_count} ${p.line_count === 1 ? 'artikel' : 'artiklar'}
              · ${esc(p.created_by_name || 'okänd')}
              · ${fmtWhen(p.created_at)}
            </div>
          </div>
          <div class="flex gap-2">
            ${closed
              ? `<button type="button" class="btn btn-secondary btn-sm" data-reopen="${p.id}">Öppna igen</button>`
              : `<button type="button" class="btn btn-ghost btn-sm" data-continue="${p.id}" data-title="${esc(p.title)}">${isActive ? 'Visas nu' : 'Fortsätt'}</button>`}
            <button type="button" class="btn-icon" data-pdf="${p.id}" data-title="${esc(p.title)}" title="Ladda ner PDF">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
            </button>
            <button type="button" class="btn-icon" data-drop="${p.id}" data-title="${esc(p.title)}" title="Ta bort">×</button>
          </div>
        </div>
      `;
    }).join('');
  }

  $('toggle-closed-btn').addEventListener('click', async () => {
    showClosed = !showClosed;
    await loadResumeList();
  });

  resumeBody.addEventListener('click', async (e) => {
    const cont = e.target.closest('[data-continue]');
    const reopen = e.target.closest('[data-reopen]');
    const pdf = e.target.closest('[data-pdf]');
    const drop = e.target.closest('[data-drop]');

    if (cont) {
      mode = 'temp';
      tempList = { id: Number(cont.dataset.continue), title: cont.dataset.title };
      persist();
      renderTabs();
      renderTarget();
      await syncLines();
      await loadResumeList();
      updateStatus();
      input.focus();
    } else if (reopen) {
      try {
        const pl = await api.put(`/pick-lists/${reopen.dataset.reopen}`, { closed: false });
        mode = 'temp';
        tempList = { id: pl.id, title: pl.title };
        persist();
        renderTabs();
        renderTarget();
        await syncLines();
        await loadResumeList();
        updateStatus();
        showToast('Skanningen öppnades igen', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    } else if (pdf) {
      try { await downloadFile(`/pick-lists/${pdf.dataset.pdf}/pdf`, pdfName(pdf.dataset.title, pdf.dataset.pdf)); }
      catch (err) { showToast(err.message, 'error'); }
    } else if (drop) {
      if (!await confirmDialog(`Ta bort skanningen <strong>${esc(drop.dataset.title)}</strong> med alla rader?`, 'Ta bort')) return;
      try {
        await api.delete(`/pick-lists/${drop.dataset.drop}`);
        if (tempList && tempList.id === Number(drop.dataset.drop)) {
          tempList = null;
          persist();
          renderTarget();
          await syncLines();
        }
        await loadResumeList();
        updateStatus();
        showToast('Skanningen togs bort', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    }
  });

  /** Låt skanningens namn styra filnamnet så nedladdningarna går att skilja åt. */
  function pdfName(title, id) {
    const slug = String(title || '').toLowerCase()
      .replace(/[åä]/g, 'a').replace(/ö/g, 'o')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
    return `${slug || 'skanning'}-${id}.pdf`;
  }

  printListBtn.addEventListener('click', async () => {
    if (!tempList) return;
    try { await downloadFile(`/pick-lists/${tempList.id}/pdf`, pdfName(tempList.title, tempList.id)); }
    catch (err) { showToast(err.message, 'error'); }
  });

  closeScanBtn.addEventListener('click', async () => {
    if (!tempList) return;
    if (!await confirmDialog(`Avsluta <strong>${esc(tempList.title)}</strong>? Den går att öppna igen under "Visa avslutade".`, 'Avsluta')) return;
    try {
      await api.put(`/pick-lists/${tempList.id}`, { closed: true });
      tempList = null;
      persist();
      renderTarget();
      await syncLines();
      await loadResumeList();
      updateStatus();
      showToast('Skanningen avslutades', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  // ── Skanning ────────────────────────────────────────────────────────────────
  let debounceTimer = null;

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(debounceTimer);
      submitScan();
    }
  });

  // Läsaren skriver tecken för tecken. 120 ms efter sista tecknet skickas koden,
  // så det fungerar lika bra med läsare som inte avslutar med Enter.
  input.addEventListener('input', () => {
    if (!currentTargetId() || !input.value.trim()) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(submitScan, 120);
  });

  async function submitScan() {
    const barcode = input.value.trim();
    const targetId = currentTargetId();
    input.value = '';
    if (!barcode || !targetId) return;

    try {
      const result = mode === 'order'
        ? await api.post(`/work-orders/${targetId}/scan`, { barcode })
        : await api.post(`/pick-lists/${targetId}/scan`, { barcode });
      const name = result.article_name;
      if (result.unknown) beepWarn(); else beepOk();
      showFeedback(`${name} — ${result.line.quantity} ${result.line.unit}`, result.unknown ? 'warning' : 'success');
      if (result.stock_warning) {
        warningBox.innerHTML = `Lågt lagersaldo på <strong>${esc(name)}</strong>: ${result.stock_quantity} ${esc(result.article?.unit || 'st')} kvar`;
        warningBox.classList.remove('hidden');
      } else {
        warningBox.classList.add('hidden');
      }
      showToast(`${name} tillagd`, result.unknown ? 'warning' : 'success', 2000);
      await refreshLines(targetId);
      if (mode === 'temp') await loadResumeList();
    } catch (err) {
      beepWarn();
      showFeedback(err.message, 'error');
      showToast(err.message, 'error', 3000);
    }

    setTimeout(() => { if (!typingInField()) input.focus(); }, 80);
  }

  function showFeedback(msg, type) {
    feedback.textContent = msg;
    feedback.className = `scan-feedback scan-feedback-${type}`;
    feedback.style.display = 'block';
    clearTimeout(feedback._timer);
    feedback._timer = setTimeout(() => { feedback.style.display = 'none'; }, 4000);
  }

  // ── Rätta antal ─────────────────────────────────────────────────────────────
  // En väntande sparning per rad. − och + i snabb följd blir en enda sparning
  // med slutvärdet, och därmed en enda lagerjustering i stället för en per tryck.
  const pending = new Map();

  async function saveQuantity(lineId, quantity) {
    // Målet läses innan anropet – hinner man byta lista under tiden ska raderna
    // laddas om för rätt lista, inte för den man råkar titta på efteråt
    const targetId = currentTargetId();
    const url = mode === 'order'
      ? `/work-orders/${targetId}/lines/${lineId}/quantity`
      : `/pick-lists/${targetId}/lines/${lineId}/quantity`;
    try {
      await api.put(url, { quantity });
      showToast(quantity === 0 ? 'Rad borttagen' : 'Antal ändrat', 'success', 1500);
    } catch (err) {
      showToast(err.message, 'error');
    }
    await refreshLines(targetId);
  }

  function queueSave(lineId, quantity) {
    clearTimeout(pending.get(lineId));
    pending.set(lineId, setTimeout(() => {
      pending.delete(lineId);
      saveQuantity(lineId, quantity);
    }, 450));
  }

  async function removeLine(lineId, name) {
    if (!await confirmDialog(`Ta bort <strong>${esc(name)}</strong> från listan?`, 'Ta bort')) return;
    clearTimeout(pending.get(lineId));
    pending.delete(lineId);
    await saveQuantity(lineId, 0);
  }

  /** Visar eller döljer radkortet beroende på om ett mål är valt. */
  async function syncLines() {
    const targetId = currentTargetId();
    const isTemp = mode === 'temp' && !!tempList;
    printListBtn.style.display = isTemp ? '' : 'none';
    closeScanBtn.style.display = isTemp ? '' : 'none';
    if (!targetId) {
      linesCard.style.display = 'none';
      linesCount.textContent = '';
      return;
    }
    linesCard.style.display = '';
    await refreshLines(targetId);
  }

  async function refreshLines(targetId) {
    if (!targetId || !linesBody.isConnected) return;
    const lines = mode === 'order'
      ? await api.get(`/work-orders/${targetId}/lines`).catch(() => [])
      : await api.get(`/pick-lists/${targetId}`).then(pl => pl.lines).catch(() => []);

    linesCount.textContent = lines.length ? `(${lines.length})` : '';

    if (!lines.length) {
      linesBody.innerHTML = '<div class="empty-state" style="padding:24px"><p>Inga artiklar ännu</p></div>';
      return;
    }

    linesBody.innerHTML = `
      <div class="table-wrap">
        <table class="scan-lines-table">
          <thead>
            <tr>
              <th>Artikel</th>
              <th>Art.nr</th>
              <th class="text-right">Antal</th>
              <th style="width:40px"></th>
            </tr>
          </thead>
          <tbody>
            ${lines.map(l => `
              <tr>
                <td class="scan-line-name">${esc(l.description)}</td>
                <td class="font-mono text-muted">${esc(l.article_number || l.article?.article_number || '–')}</td>
                <td class="text-right" style="white-space:nowrap">
                  <div class="qty-control">
                    <button type="button" class="qty-btn" data-qty-step="-1" data-line="${l.id}" aria-label="Minska">−</button>
                    <input type="text" class="qty-input" inputmode="decimal" autocomplete="off"
                           data-line="${l.id}" data-name="${esc(l.description)}" value="${fmtQty(l.quantity)}">
                    <button type="button" class="qty-btn" data-qty-step="1" data-line="${l.id}" aria-label="Öka">+</button>
                  </div>
                  <span class="text-muted" style="font-size:12px">${esc(l.unit || '')}</span>
                </td>
                <td>
                  <button type="button" class="btn-icon" data-remove-line="${l.id}" data-name="${esc(l.description)}" title="Ta bort rad">×</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;

    linesBody.querySelectorAll('[data-qty-step]').forEach(btn => {
      btn.addEventListener('click', () => {
        const field = linesBody.querySelector(`.qty-input[data-line="${btn.dataset.line}"]`);
        // − stannar på 1. Att ta bort en rad ska vara ett eget, avsiktligt val –
        // inte något som händer för att någon tryckte en gång för mycket.
        const next = Math.max(1, (Number(field.value) || 0) + Number(btn.dataset.qtyStep));
        field.value = fmtQty(next);
        queueSave(Number(btn.dataset.line), next);
        // Knappen tog fokus från kodfältet – lämna tillbaka det, annars hamnar
        // nästa skanning ingenstans
        setTimeout(() => { if (!typingInField()) input.focus(); }, 0);
      });
    });

    linesBody.querySelectorAll('.qty-input').forEach(field => {
      // Fokus i fältet pausar skanningen av sig själv (se updateStatus) – utan
      // det hade en streckkod hamnat mitt i antalet man håller på att skriva.
      field.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); field.blur(); }
      });
      field.addEventListener('change', () => {
        const raw = String(field.value).trim().replace(',', '.');
        // Tömt fält betyder "ingen ändring", inte 0 – annars dyker frågan om att
        // ta bort raden upp bara för att någon råkade radera siffran
        if (raw === '') { refreshLines(currentTargetId()); return; }
        const value = Number(raw);
        if (!Number.isFinite(value) || value < 0) {
          showToast('Ange ett antal på 0 eller mer', 'error');
          refreshLines(currentTargetId());
          return;
        }
        if (value === 0) { removeLine(Number(field.dataset.line), field.dataset.name); return; }
        clearTimeout(pending.get(Number(field.dataset.line)));
        saveQuantity(Number(field.dataset.line), value);
      });
    });

    linesBody.querySelectorAll('[data-remove-line]').forEach(btn => {
      btn.addEventListener('click', () => {
        removeLine(Number(btn.dataset.removeLine), btn.dataset.name);
      });
    });
  }

  // ── Alltid igång ────────────────────────────────────────────────────────────
  // Ingen "Starta skanning"-knapp att glömma: tecken som skrivs någonstans på
  // sidan, utanför ett fält, styrs om till kodfältet. Läsaren skickar vanliga
  // tangenttryckningar, så det räcker att flytta fokus innan tecknet skrivs in.
  pageListeners?.abort();
  pageListeners = new AbortController();
  const signal = pageListeners.signal;

  function onGlobalKey(e) {
    const field = document.getElementById('scanner-input');
    if (!field) { pageListeners?.abort(); return; }   // sidan är utbytt
    if (!currentTargetId()) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key.length !== 1) return;                   // bara skrivtecken
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    // Tecknet skrivs in för hand i stället för att lita på att webbläsaren
    // levererar det till fältet som precis fick fokus. Resten av koden landar
    // där av sig själv när fokus väl sitter rätt.
    e.preventDefault();
    field.focus();
    field.value += e.key;
    field.dispatchEvent(new Event('input'));
  }

  document.addEventListener('keydown', onGlobalKey, { capture: true, signal });
  document.addEventListener('focusin', updateStatus, { signal });
  // focusout hinner före att nästa element fått fokus, därför nästa tick
  document.addEventListener('focusout', () => setTimeout(updateStatus, 0), { signal });
  // Ett klick är det vanligaste sättet att lämna ett fält – statusen ska stämma
  // även om fokushändelserna uteblir
  document.addEventListener('click', () => setTimeout(updateStatus, 0), { signal });

  // ── Start ───────────────────────────────────────────────────────────────────
  renderTabs();
  renderTarget();
  updateStatus();
  await syncLines();
  await loadResumeList();
  if (currentTargetId()) input.focus();
}
