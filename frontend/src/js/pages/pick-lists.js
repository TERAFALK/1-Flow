import { api, downloadFile } from '../api.js';
import { fmtDate } from '../app.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderPickLists(el) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Plocklistor</div>
        <div class="page-subtitle">Skapa tillfälliga plocklistor för att hämta artiklar på lagret</div>
      </div>
      <button class="btn btn-primary" id="new-picklist-btn">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
        Ny plocklista
      </button>
    </div>
    <div class="card">
      <div id="picklist-content"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-picklist-btn').addEventListener('click', () => openPickListBuilder(reload));

  async function reload() {
    const wrap = document.getElementById('picklist-content');
    if (!wrap) return;
    const lists = await api.get('/pick-lists');
    if (!lists.length) {
      wrap.innerHTML = `<div class="empty-state"><p>Inga plocklistor ännu</p></div>`;
      return;
    }
    wrap.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Titel</th><th>Anteckning</th><th class="text-right">Rader</th><th>Skapad</th><th></th></tr></thead>
          <tbody>
            ${lists.map(p => `
              <tr>
                <td><strong>${p.title}</strong></td>
                <td class="text-muted">${p.notes || '–'}</td>
                <td class="text-right">${p.line_count}</td>
                <td class="text-muted">${fmtDate(p.created_at, true)}</td>
                <td>
                  <div class="flex gap-2">
                    <button class="btn btn-ghost btn-sm" onclick="window._openPickList(${p.id})">Öppna</button>
                    <button class="btn-icon" title="Ladda ner PDF" onclick="window._downloadPickListPdf(${p.id}, '${p.title.replace(/'/g, "\\'")}')">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM9.293 13.707a1 1 0 001.414 0l4-4a1 1 0 00-1.414-1.414L11 10.586V3a1 1 0 10-2 0v7.586L6.707 8.293a1 1 0 00-1.414 1.414l4 4z" clip-rule="evenodd"/></svg>
                    </button>
                    <button class="btn-icon" title="Ta bort" onclick="window._deletePickList(${p.id})">
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

  window._openPickList = (id) => openPickListBuilder(reload, id);
  window._downloadPickListPdf = (id, title) => downloadFile(`/pick-lists/${id}/pdf`, `plocklista-${title || id}.pdf`).catch(err => showToast(err.message, 'error'));
  window._deletePickList = async (id) => {
    if (await confirmDialog('Ta bort denna plocklista?')) {
      await api.delete(`/pick-lists/${id}`);
      showToast('Plocklista borttagen', 'success');
      reload();
    }
  };

  await reload();
}

async function openPickListBuilder(onSaved, existingId = null) {
  const [allArticles, existing] = await Promise.all([
    api.get('/articles'),
    existingId ? api.get(`/pick-lists/${existingId}`) : Promise.resolve(null),
  ]);

  const selected = new Map(); // article_id (or 'manual-N') -> { article_id, description, quantity, unit, location }
  if (existing) {
    existing.lines.forEach(l => {
      const key = l.article_id ? `a${l.article_id}` : `m${l.id}`;
      selected.set(key, {
        article_id: l.article_id, description: l.description,
        quantity: parseFloat(l.quantity), unit: l.unit, location: l.location,
      });
    });
  }

  openModal({
    title: existing ? `Redigera plocklista – ${existing.title}` : 'Ny plocklista',
    size: 'modal-lg',
    body: `
      <form id="picklist-form">
        <div class="form-row">
          <div class="field"><label>Titel *</label><input type="text" name="title" value="${existing?.title || ''}" required autofocus placeholder="t.ex. Plock till service"></div>
          <div class="field"><label>Anteckning</label><input type="text" name="notes" value="${existing?.notes || ''}"></div>
        </div>
        <div class="field">
          <label>Sök artikel att lägga till</label>
          <div class="search-wrap">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
            <input type="search" id="pl-article-search" placeholder="Namn, art.nr eller plats…">
          </div>
          <div id="pl-article-results" class="pl-results"></div>
        </div>
        <div class="field">
          <label>Valda artiklar (<span id="pl-count">${selected.size}</span>)</label>
          <div class="table-wrap" style="max-height:280px;overflow-y:auto">
            <table>
              <thead><tr><th>Artikel</th><th>Plats</th><th style="width:90px">Antal</th><th></th></tr></thead>
              <tbody id="pl-selected-tbody"></tbody>
            </table>
          </div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${existing ? 'Spara' : 'Skapa plocklista'}</button>
        </div>
      </form>
    `,
  });

  function renderSelected() {
    const tbody = document.getElementById('pl-selected-tbody');
    document.getElementById('pl-count').textContent = selected.size;
    if (!selected.size) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-muted" style="text-align:center;padding:16px">Inga artiklar valda</td></tr>`;
      return;
    }
    tbody.innerHTML = [...selected.entries()].map(([key, l]) => `
      <tr>
        <td><strong>${l.description}</strong></td>
        <td class="text-muted">${l.location || '–'}</td>
        <td><input type="number" min="0.01" step="0.01" value="${l.quantity}" data-qty="${key}" style="width:70px"></td>
        <td><button type="button" class="btn-icon" data-remove="${key}">✕</button></td>
      </tr>
    `).join('');
    tbody.querySelectorAll('[data-qty]').forEach(inp => {
      inp.addEventListener('input', () => {
        const l = selected.get(inp.dataset.qty);
        l.quantity = parseFloat(inp.value) || 1;
      });
    });
    tbody.querySelectorAll('[data-remove]').forEach(btn => {
      btn.addEventListener('click', () => { selected.delete(btn.dataset.remove); renderSelected(); });
    });
  }
  renderSelected();

  const searchInput = document.getElementById('pl-article-search');
  const resultsBox = document.getElementById('pl-article-results');
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    if (!q) { resultsBox.innerHTML = ''; resultsBox.classList.remove('open'); return; }
    const matches = allArticles.filter(a =>
      a.name.toLowerCase().includes(q) ||
      (a.article_number || '').toLowerCase().includes(q) ||
      (a.location || '').toLowerCase().includes(q)
    ).slice(0, 25);
    resultsBox.classList.add('open');
    resultsBox.innerHTML = matches.length
      ? matches.map(a => `
          <div class="pl-result-row" data-add="${a.id}">
            <strong>${a.name}</strong>
            <span class="text-muted">${a.article_number || ''} ${a.location ? '· ' + a.location : ''}</span>
          </div>
        `).join('')
      : `<div class="pl-result-row text-muted">Inga träffar</div>`;
    resultsBox.querySelectorAll('[data-add]').forEach(row => {
      row.addEventListener('click', () => {
        const a = allArticles.find(x => x.id === parseInt(row.dataset.add));
        const key = `a${a.id}`;
        const cur = selected.get(key);
        if (cur) cur.quantity += 1;
        else selected.set(key, { article_id: a.id, description: a.name, quantity: 1, unit: a.unit, location: a.location });
        renderSelected();
        searchInput.value = '';
        resultsBox.innerHTML = '';
        resultsBox.classList.remove('open');
      });
    });
  });

  document.getElementById('picklist-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const { title, notes } = Object.fromEntries(new FormData(e.target));
    const lines = [...selected.values()].map(l => ({
      article_id: l.article_id || null,
      description: l.description,
      quantity: l.quantity,
      unit: l.unit || 'st',
      location: l.location || null,
    }));
    try {
      if (existing) {
        await api.put(`/pick-lists/${existing.id}`, { title, notes: notes || null });
        const currentLineIds = new Set(existing.lines.map(l => l.id));
        // simplest: delete all existing lines, re-add current selection
        await Promise.all(existing.lines.map(l => api.delete(`/pick-lists/${existing.id}/lines/${l.id}`)));
        await Promise.all(lines.map(l => api.post(`/pick-lists/${existing.id}/lines`, l)));
        showToast('Plocklista uppdaterad', 'success');
      } else {
        await api.post('/pick-lists', { title, notes: notes || null, lines });
        showToast('Plocklista skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
