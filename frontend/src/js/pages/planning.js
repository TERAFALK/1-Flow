// Planeringsmöte – veckodokumentet som gås igenom fysiskt med verkstaden.
//
// Två vyer: ett arkiv med en rad per vecka, och själva veckan. Veckan skapas
// normalt ur den förra – jobben pågår över flera veckor, så raderna är till
// stor del desamma och det som ändras är enstaka rader plus veckoschemat.

import { api, printFile, downloadFile } from '../api.js';
import { openModal, closeModal, confirmDialog, confirmUnsaved } from '../components/modal.js';
import { showToast } from '../components/toast.js';
import { makeAllSearchable } from '../components/combobox.js';
import { richTextField, bindRichText } from '../components/richtext.js';

// Osparade ändringar på veckosidan. Sidan är inget modalfönster, så vakten i
// modal.js når den inte – den installeras här och kopplas loss när sidan ritas
// om eller lämnas.
let detachGuard = null;

const WEEKDAYS = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag'];
const ABSENCE_KINDS = ['semester', 'ledig', 'sjuk', 'annat'];

const TRASH_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const fmtD = (d) => (d ? String(d).slice(0, 10) : '');

/** "31 aug – 4 sep" */
function weekSpan(monday) {
  const start = new Date(monday + 'T00:00:00');
  const end = new Date(start);
  end.setDate(end.getDate() + 4);
  const f = (d) => d.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short' });
  return `${f(start)} – ${f(end)}`;
}

/**
 * Varnar innan veckan lämnas med osparade ändringar.
 *
 * Navigeringen sker med länkar till hash-adresser, och `hashchange` kommer
 * först efter att adressen redan bytts – för sent för att fråga. Klicket fångas
 * därför i infångningsfasen, innan webbläsaren hinner följa länken.
 */
function installGuard(isDirty, save) {
  detachGuard?.();

  const onClick = async (e) => {
    const link = e.target.closest('a[href^="#"]');
    if (!link || !isDirty()) return;
    const target = link.getAttribute('href');
    if (target === location.hash) return;   // samma sida, ingen navigering

    e.preventDefault();
    e.stopPropagation();
    const answer = await confirmUnsaved('Veckan har ändringar som inte är sparade.');
    if (answer === 'cancel') return;
    if (answer === 'save') {
      try { await save(); } catch (err) { showToast(err.message, 'error'); return; }
    }
    detachGuard?.();
    location.hash = target;
  };

  // Stängd flik eller omladdning – där kan bara webbläsarens egen fråga användas
  const onUnload = (e) => {
    if (!isDirty()) return;
    e.preventDefault();
    e.returnValue = '';
  };

  document.addEventListener('click', onClick, true);
  window.addEventListener('beforeunload', onUnload);
  detachGuard = () => {
    document.removeEventListener('click', onClick, true);
    window.removeEventListener('beforeunload', onUnload);
    detachGuard = null;
  };
}

// ── Arkivet ───────────────────────────────────────────────────────────────────

export async function renderPlanning(el) {
  detachGuard?.();
  el.innerHTML = '<div class="loading">Laddar…</div>';
  const archive = await api.get('/planning-meetings');

  const titleEl = document.getElementById('topbar-title');
  if (titleEl) titleEl.textContent = 'Planeringsmöte';

  const topbar = document.getElementById('topbar-actions');
  if (topbar) topbar.innerHTML =
    `<button class="btn btn-primary btn-sm" id="new-week-btn">Skapa vecka ${archive.next_week}</button>`;

  // Grupperas per ISO-år, senast först
  const years = [];
  for (const w of archive.weeks) {
    let group = years.find(y => y.year === w.iso_year);
    if (!group) { group = { year: w.iso_year, weeks: [] }; years.push(group); }
    group.weeks.push(w);
  }

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">Planeringsmöte</div>
      <div class="page-subtitle">Veckans genomgång med verkstaden</div>
    </div>

    ${archive.weeks.length ? years.map(group => `
      <div class="card" style="margin-bottom:16px">
        <div class="card-header"><span class="card-title">${group.year}</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Vecka</th><th>Period</th><th>Rader</th><th>Att stryka</th><th></th></tr></thead>
            <tbody>
              ${group.weeks.map(w => `
                <tr class="clickable" data-week="${w.iso_year}-${w.iso_week}">
                  <td><strong>v.${w.iso_week}</strong></td>
                  <td>${esc(weekSpan(w.monday_date))}</td>
                  <td>${w.item_count}${w.done_count ? ` <span class="text-muted">(${w.done_count} avbockade)</span>` : ''}</td>
                  <td>${w.stale_count
                        ? `<span class="badge badge-warning">${w.stale_count} klara</span>`
                        : '<span class="text-muted">–</span>'}</td>
                  <td style="text-align:right">
                    <button class="btn-icon" data-pdf="${w.id}" title="Ladda ner PDF">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
                    </button>
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`).join('')
    : `<div class="empty-state"><p>Inga veckor ännu. Skapa vecka ${archive.next_week} för att komma igång.</p></div>`}
  `;

  el.querySelectorAll('[data-week]').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('[data-pdf]')) return;
      location.hash = `#/planning/${row.dataset.week}`;
    });
  });

  el.querySelectorAll('[data-pdf]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try { await downloadFile(`/planning-meetings/${btn.dataset.pdf}/pdf`, 'planering.pdf'); }
      catch (err) { showToast(err.message, 'error'); }
    });
  });

  document.getElementById('new-week-btn')?.addEventListener('click',
    () => openNewWeekForm(archive, () => renderPlanning(el)));
}

/** Skapar nästa vecka, normalt som en kopia av den senaste. */
function openNewWeekForm(archive, onSaved) {
  const previous = archive.weeks[0];
  openModal({
    title: `Skapa vecka ${archive.next_week}`,
    body: `
      <form id="week-form">
        <div class="field">
          <label>Måndag</label>
          <input type="date" name="monday" value="${archive.next_monday}">
        </div>
        ${previous ? `
          <hr class="divider">
          <p style="font-size:13px;color:var(--text-2);margin-bottom:10px">
            Utgå från vecka ${previous.iso_week}:
          </p>
          <label class="check-row"><input type="checkbox" name="items" checked> Rader från Pågående arbete <span class="text-muted">(avbockade följer inte med)</span></label>
          <label class="check-row"><input type="checkbox" name="sections" checked> Listorna längst ned</label>
          <label class="check-row"><input type="checkbox" name="notes"> Noteringar</label>
          <label class="check-row"><input type="checkbox" name="days"> Veckoschemat</label>
        ` : ''}
        <div class="modal-footer" style="padding:0;border:none;margin-top:16px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Skapa</button>
        </div>
      </form>`,
  });

  document.getElementById('week-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      monday: fd.get('monday') || null,
      copy_from_id: previous ? previous.id : null,
      copy: {
        items: fd.get('items') === 'on',
        sections: fd.get('sections') === 'on',
        notes: fd.get('notes') === 'on',
        days: fd.get('days') === 'on',
      },
    };
    try {
      const created = await api.post('/planning-meetings', body);
      closeModal();
      location.hash = `#/planning/${created.iso_year}-${created.iso_week}`;
    } catch (err) {
      // 409 bär med sig veckan som redan finns, så vi kan erbjuda att öppna den
      const existing = err.detail?.existing_id;
      if (existing && err.detail?.iso_week) {
        showToast(`${err.detail.message} – öppnar den`, 'info');
        closeModal();
        location.hash = `#/planning/${err.detail.iso_year}-${err.detail.iso_week}`;
        return;
      }
      showToast(err.message, 'error');
    }
  });
}

// ── Veckan ────────────────────────────────────────────────────────────────────

export async function renderPlanningWeek(el, isoYear, isoWeek) {
  // Vakten från förra renderingen pekar på gamla fält och måste bort först
  detachGuard?.();
  el.innerHTML = '<div class="loading">Laddar…</div>';

  let meeting;
  try {
    meeting = await api.get(`/planning-meetings/by-week/${isoYear}/${isoWeek}`);
  } catch {
    el.innerHTML = `
      <div class="empty-state">
        <p>Vecka ${isoWeek} finns inte.</p>
        <a href="#/planning" class="btn btn-secondary btn-sm">Till planeringsmöten</a>
      </div>`;
    return;
  }

  const [users, customers] = await Promise.all([
    api.get('/users').catch(() => []),
    api.get('/customers').catch(() => []),
  ]);

  const titleEl = document.getElementById('topbar-title');
  if (titleEl) titleEl.textContent = `Vecka ${meeting.iso_week}`;

  const topbar = document.getElementById('topbar-actions');
  if (topbar) topbar.innerHTML = `
    <a href="#/planning" class="btn btn-secondary btn-sm">← Alla veckor</a>
    <button class="btn btn-secondary btn-sm" id="pm-print">Skriv ut</button>
    <button class="btn btn-secondary btn-sm" id="pm-download">Ladda ner PDF</button>
    <button class="btn btn-primary btn-sm" id="pm-save">Spara</button>`;

  const base = `/planning-meetings/${meeting.id}`;
  const reload = () => renderPlanningWeek(el, isoYear, isoWeek);

  el.innerHTML = `
    <div style="margin-bottom:20px">
      <div class="page-title">Planering vecka ${meeting.iso_week}</div>
      <div class="page-subtitle">${esc(weekSpan(meeting.monday_date))} · ${meeting.iso_year}</div>
    </div>

    <form id="pm-form">
      <div class="card" style="margin-bottom:16px">
        <div class="card-header"><span class="card-title">Veckan</span></div>
        <div class="card-body">
          ${meeting.days.map(d => `
            <div class="field" style="display:grid;grid-template-columns:150px 1fr;align-items:center;gap:12px;margin-bottom:8px">
              <label style="margin:0">${WEEKDAYS[new Date(d.day_date + 'T00:00:00').getDay() === 0 ? 6 : new Date(d.day_date + 'T00:00:00').getDay() - 1]}
                <span class="text-muted" style="font-weight:400">${fmtD(d.day_date).slice(5)}</span></label>
              <input type="text" data-day="${d.day_date}" value="${esc(d.text)}" placeholder="–">
            </div>`).join('')}
        </div>
      </div>

      ${absenceCardHtml(meeting.absences)}

      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <span class="card-title">Pågående arbete / ej startat arbete</span>
          <div style="display:flex;gap:8px">
            <button type="button" class="btn btn-secondary btn-sm" id="pm-suggest">Hämta arbetsordrar</button>
            <button type="button" class="btn btn-secondary btn-sm" id="pm-add">+ Ny rad</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th style="width:34px"></th><th>Kund</th><th>Beskrivning arbete</th><th>Ansvar</th><th></th></tr></thead>
            <tbody>
              ${meeting.items.length ? meeting.items.map(itemRowHtml).join('')
                : '<tr><td colspan="5" class="text-muted" style="padding:16px">Inga rader ännu.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px">
        <div class="card-header"><span class="card-title">Noteringar</span></div>
        <div class="card-body">${richTextField('pm_notes', meeting.notes, { rows: 4 })}</div>
      </div>

      ${sectionCardHtml('pm_ffb', 'ffb_heading', meeting.ffb_heading || 'Aktuellt FFB', meeting.ffb_current)}
      ${sectionCardHtml('pm_quotes', 'quotes_heading', meeting.quotes_heading || 'Pågående offerter', meeting.open_quotes)}
      ${sectionCardHtml('pm_future', 'future_heading', meeting.future_heading || 'Kommande arbete', meeting.future_work)}
    </form>
  `;

  bindRichText(document.getElementById('pm-form'));

  // ── Spara ───────────────────────────────────────────────────────────────────
  const collect = () => {
    const form = document.getElementById('pm-form');
    const value = (name) => form.querySelector(`[name="${name}"]`)?.value || null;
    return {
      notes: value('pm_notes'),
      ffb_current: value('pm_ffb'),
      open_quotes: value('pm_quotes'),
      future_work: value('pm_future'),
      ffb_heading: value('ffb_heading'),
      quotes_heading: value('quotes_heading'),
      future_heading: value('future_heading'),
      days: [...form.querySelectorAll('[data-day]')].map(input => ({
        day_date: input.dataset.day,
        text: input.value || null,
      })),
    };
  };

  let dirty = false;
  const form = document.getElementById('pm-form');
  // Allt som når hit är användarens egen inmatning – programmatisk ifyllnad
  // sker innan lyssnaren sätts upp
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });

  const save = async (quiet = false) => {
    await api.put(base, collect());
    dirty = false;
    if (!quiet) showToast('Veckan sparad', 'success');
  };

  /** Sparar sidan innan något som ritar om den. Utan det försvinner texten han
   *  skrivit i schemat och fritextfälten så fort en rad läggs till eller hämtas. */
  const keep = async () => { if (dirty) await save(true); };

  installGuard(() => dirty, save);

  document.getElementById('pm-save')?.addEventListener('click', async () => {
    try { await save(); } catch (err) { showToast(err.message, 'error'); }
  });

  // Spara innan utskrift, annars skrivs den förra versionen ut
  document.getElementById('pm-print')?.addEventListener('click', async () => {
    try { await save(); await printFile(`${base}/pdf`); }
    catch (err) { showToast(err.message, 'error'); }
  });
  document.getElementById('pm-download')?.addEventListener('click', async () => {
    try {
      await save();
      await downloadFile(`${base}/pdf`, `Planering-v${meeting.iso_week}-${meeting.iso_year}.pdf`);
    } catch (err) { showToast(err.message, 'error'); }
  });

  // ── Rader ───────────────────────────────────────────────────────────────────
  // Varje radoperation ritar om sidan efteråt. Sidan sparas därför först, annars
  // hade det han skrivit i schemat och fritextfälten kastats bort.
  document.getElementById('pm-add')?.addEventListener('click', async () => {
    try { await keep(); } catch (err) { showToast(err.message, 'error'); return; }
    openItemForm(base, null, { users, customers }, reload);
  });

  el.querySelectorAll('[data-edit-item]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try { await keep(); } catch (err) { showToast(err.message, 'error'); return; }
      const item = meeting.items.find(i => i.id === +btn.dataset.editItem);
      openItemForm(base, item, { users, customers }, reload);
    });
  });

  el.querySelectorAll('[data-del-item]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort raden?')) return;
      try {
        await keep();
        await api.delete(`${base}/items/${btn.dataset.delItem}`);
        showToast('Rad borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Bocka av direkt i tabellen – det är så listan städar sig själv
  el.querySelectorAll('[data-done-item]').forEach(box => {
    box.addEventListener('change', async () => {
      try {
        await api.put(`${base}/items/${box.dataset.doneItem}`, { done: box.checked });
        box.closest('tr').classList.toggle('row-done', box.checked);
      } catch (err) { showToast(err.message, 'error'); box.checked = !box.checked; }
    });
  });

  document.getElementById('pm-suggest')?.addEventListener('click', async () => {
    try { await keep(); } catch (err) { showToast(err.message, 'error'); return; }
    openSuggestions(base, reload);
  });

  // ── Frånvaro till Noteringar ────────────────────────────────────────────────
  document.getElementById('pm-absence-insert')?.addEventListener('click', () => {
    const editor = document.querySelector('[data-rich-for="pm_notes"] .richtext-input');
    if (!editor) return;
    const lines = meeting.absences.map(a =>
      `${a.user_name} ${a.kind} ${fmtD(a.start_date)}–${fmtD(a.end_date)}`);
    // Läggs till sist, aldrig över det han själv skrivit
    editor.innerHTML += lines.map(l => `<div>${esc(l)}</div>`).join('');
    editor.dispatchEvent(new Event('input', { bubbles: true }));
    showToast('Tillagt i Noteringar – glöm inte spara', 'info');
  });
}

function itemRowHtml(item) {
  const stale = item.work_order_done && !item.done;
  return `
    <tr class="${item.done ? 'row-done' : ''}">
      <td><input type="checkbox" data-done-item="${item.id}" ${item.done ? 'checked' : ''} title="Klar"></td>
      <td>
        ${esc(item.customer_text) || '<span class="text-muted">–</span>'}
        ${item.work_order_number ? `<div class="text-muted" style="font-size:11.5px">${esc(item.work_order_number)}</div>` : ''}
      </td>
      <td style="white-space:pre-wrap">${esc(item.description)}
        ${stale ? '<div><span class="badge badge-success" style="margin-top:4px">Arbetsordern är klar – går att stryka</span></div>' : ''}
      </td>
      <td>${item.assignee_names.map(esc).join('<br>') || '<span class="text-muted">–</span>'}</td>
      <td style="text-align:right;white-space:nowrap">
        <button type="button" class="btn btn-secondary btn-sm" data-edit-item="${item.id}">Redigera</button>
        <button type="button" class="btn-icon" data-del-item="${item.id}" title="Ta bort">${TRASH_ICON}</button>
      </td>
    </tr>`;
}

function absenceCardHtml(absences) {
  if (!absences || !absences.length) return '';
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <span class="card-title">Frånvaro denna vecka</span>
        <button type="button" class="btn btn-secondary btn-sm" id="pm-absence-insert">Lägg in i Noteringar</button>
      </div>
      <div class="card-body order-meta">
        ${absences.map(a => `
          <div class="meta-row">
            <span class="meta-label">${esc(a.user_name)}:</span>
            <span>${esc(a.kind)} ${fmtD(a.start_date)} – ${fmtD(a.end_date)}${a.note ? ` · ${esc(a.note)}` : ''}</span>
          </div>`).join('')}
      </div>
    </div>`;
}

/** De tre listorna längst ned. Rubriken är redigerbar – "Arbete under 2026/27"
 *  innehåller ett årtal som måste gå att ändra. */
function sectionCardHtml(fieldName, headingName, heading, value) {
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <input type="text" name="${headingName}" value="${esc(heading)}"
               class="card-title-input" title="Rubriken syns i utskriften">
      </div>
      <div class="card-body">${richTextField(fieldName, value, { rows: 4 })}</div>
    </div>`;
}

// ── Radformuläret ─────────────────────────────────────────────────────────────

function openItemForm(base, item, { users, customers }, onSaved) {
  const selected = item?.assignee_ids || [];
  const userOptions = (value) => users.map(u =>
    `<option value="${u.id}" ${String(value) === String(u.id) ? 'selected' : ''}>${esc(u.full_name)}</option>`
  ).join('');

  openModal({
    title: item ? 'Redigera rad' : 'Ny rad',
    size: 'modal-lg',
    body: `
      <form id="item-form">
        <div class="form-row">
          <div class="field">
            <label>Kund</label>
            <select name="customer_id" id="item-customer">
              <option value="">–</option>
              ${customers.map(c => `<option value="${c.id}" ${item?.customer_id === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label>Arbetsorder</label>
            <select name="work_order_id" id="item-order"><option value="">–</option></select>
          </div>
        </div>
        <div class="field">
          <label>Kundnamn <span class="text-muted" style="font-weight:400">(om kunden inte finns som kort)</span></label>
          <input type="text" name="customer_text" value="${esc(item?.customer_text)}" placeholder="Fritext">
        </div>
        <div class="field">
          <label>Beskrivning arbete</label>
          <textarea name="description" rows="4">${esc(item?.description)}</textarea>
        </div>
        <div class="form-row">
          <div class="field">
            <label>Ansvar</label>
            <select name="assignee_1"><option value="">–</option>${userOptions(selected[0])}</select>
          </div>
          <div class="field">
            <label>Ansvar 2</label>
            <select name="assignee_2"><option value="">–</option>${userOptions(selected[1])}</select>
          </div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  const form = document.getElementById('item-form');
  const customerSel = document.getElementById('item-customer');
  const orderSel = document.getElementById('item-order');

  // Arbetsordrarna begränsas till vald kund – annars är listan obrukbar
  async function loadOrders(selectedId) {
    orderSel.innerHTML = '<option value="">–</option>';
    if (!customerSel.value) return;
    try {
      const orders = await api.get('/work-orders');
      orderSel.innerHTML = '<option value="">–</option>' + orders
        .filter(o => String(o.customer_id) === String(customerSel.value))
        .map(o => `<option value="${o.id}" ${String(selectedId) === String(o.id) ? 'selected' : ''}>${esc(o.order_number)} – ${esc(o.description || '')}</option>`)
        .join('');
    } catch { /* listan får vara tom om anropet fallerar */ }
  }
  customerSel.addEventListener('change', () => loadOrders(null));
  loadOrders(item?.work_order_id);

  makeAllSearchable(form);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      customer_id: fd.get('customer_id') ? Number(fd.get('customer_id')) : null,
      customer_text: fd.get('customer_text') || null,
      work_order_id: fd.get('work_order_id') ? Number(fd.get('work_order_id')) : null,
      description: fd.get('description') || null,
      assignee_ids: [fd.get('assignee_1'), fd.get('assignee_2')].filter(Boolean).map(Number),
    };
    try {
      if (item) await api.put(`${base}/items/${item.id}`, body);
      else await api.post(`${base}/items`, body);
      showToast(item ? 'Raden sparad' : 'Rad tillagd', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}

/** Öppna arbetsordrar som aldrig varit med på ett möte. */
async function openSuggestions(base, onSaved) {
  let list = [];
  try { list = await api.get(`${base}/suggestions`); }
  catch (err) { showToast(err.message, 'error'); return; }

  openModal({
    title: 'Arbetsordrar som inte varit med',
    size: 'modal-lg',
    body: list.length ? `
      <p style="font-size:13px;color:var(--text-2);margin-bottom:12px">
        Öppna arbetsordrar som aldrig legat på ett planeringsmöte. Kryssa i dem du vill lägga till.
      </p>
      <form id="sugg-form">
        ${list.map(s => `
          <label class="check-row">
            <input type="checkbox" name="wo" value="${s.work_order_id}">
            <strong>${esc(s.customer_name)}</strong> · ${esc(s.order_number)}
            <span class="text-muted">${esc(s.description)}</span>
          </label>`).join('')}
        <div class="modal-footer" style="padding:0;border:none;margin-top:16px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Lägg till valda</button>
        </div>
      </form>`
      : '<p class="text-muted">Alla öppna arbetsordrar har redan varit med på ett möte.</p>',
  });

  document.getElementById('sugg-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const chosen = [...e.target.querySelectorAll('[name="wo"]:checked')].map(c => +c.value);
    try {
      for (const id of chosen) {
        const s = list.find(x => x.work_order_id === id);
        await api.post(`${base}/items`, {
          customer_id: s.customer_id,
          customer_text: s.customer_name,
          work_order_id: s.work_order_id,
          description: s.description,
          assignee_ids: s.assignee_ids,
        });
      }
      showToast(`${chosen.length} rader tillagda`, 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
