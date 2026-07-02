import { api, uploadFile } from '../api.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

const PAGE_SIZE = 100;

export async function renderArticles(el) {
  let offset = 0;
  let allRows = [];

  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Lager & Artiklar</div>
        <div class="page-subtitle">Artikelregister</div>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-ghost btn-danger" id="clear-stock-btn">Rensa lager</button>
        <button class="btn btn-secondary" id="import-excel-btn">Importera Excel</button>
        <input type="file" id="import-excel-input" accept=".xlsx,.xls" class="hidden">
        <button class="btn btn-primary" id="new-article-btn">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
          Ny artikel
        </button>
      </div>
    </div>
    <div class="card">
      <div class="card-header">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="article-search" placeholder="Sök artikel, art.nr, företag, plats…">
        </div>
      </div>
      <div id="article-list"><div class="loading">Laddar…</div></div>
      <div class="card-body" style="text-align:center;padding-top:8px" id="article-load-more-wrap"></div>
    </div>
  `;

  document.getElementById('new-article-btn').addEventListener('click', () => openArticleForm(null, reload));

  const importInput = document.getElementById('import-excel-input');
  document.getElementById('import-excel-btn').addEventListener('click', () => importInput.click());
  importInput.addEventListener('change', async () => {
    const file = importInput.files[0];
    if (!file) return;
    const ok = await confirmDialog(`Detta skriver <strong>över hela artikellagret</strong> med innehållet i <strong>${file.name}</strong>. Alla befintliga artiklar tas bort och ersätts. Fortsätta?`);
    importInput.value = '';
    if (!ok) return;
    const btn = document.getElementById('import-excel-btn');
    btn.disabled = true;
    btn.textContent = 'Importerar…';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const result = await uploadFile('/articles/import-excel', fd);
      showToast(`${result.imported} artiklar importerade på ${result.seconds}s`, 'success');
      reload();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Importera Excel';
    }
  });

  document.getElementById('clear-stock-btn').addEventListener('click', async () => {
    const ok = await confirmDialog('Detta tar bort <strong>alla artiklar</strong> i lagret permanent. Är du säker?');
    if (!ok) return;
    try {
      await api.delete('/articles/all');
      showToast('Lagret rensat', 'success');
      reload();
    } catch (err) { showToast(err.message, 'error'); }
  });

  let timer;
  document.getElementById('article-search').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(reload, 300);
  });

  async function loadPage(reset) {
    const list = document.getElementById('article-list');
    if (!list) return;
    if (reset) { offset = 0; allRows = []; }
    const q = document.getElementById('article-search')?.value || '';
    let url = `/articles?limit=${PAGE_SIZE}&offset=${offset}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    const page = await api.get(url);
    allRows = reset ? page : allRows.concat(page);
    offset += page.length;

    if (!allRows.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga artiklar hittade</p></div>`;
      document.getElementById('article-load-more-wrap').innerHTML = '';
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Artikel</th><th>Art.nr</th><th>Företag</th><th>Streckkod</th>
            <th>Plats</th><th></th>
          </tr></thead>
          <tbody>
            ${allRows.map(a => `
              <tr>
                <td><strong>${a.name}</strong>${a.description ? `<br><small class="text-muted">${a.description}</small>` : ''}</td>
                <td class="font-mono">${a.article_number || '–'}</td>
                <td>${a.supplier || '–'}</td>
                <td class="font-mono">${a.barcode || '–'}</td>
                <td>${a.location || '–'}</td>
                <td>
                  <div class="flex gap-2">
                    <button class="btn-icon" title="Redigera" onclick="window._editArticle(${a.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                    </button>
                    <button class="btn-icon" title="Ta bort" onclick="window._deleteArticle(${a.id})">
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
    const moreWrap = document.getElementById('article-load-more-wrap');
    moreWrap.innerHTML = page.length === PAGE_SIZE
      ? `<button class="btn btn-ghost" id="article-load-more">Ladda fler</button>`
      : '';
    document.getElementById('article-load-more')?.addEventListener('click', () => loadPage(false));
  }

  function reload() { loadPage(true); }

  window._editArticle = async (id) => {
    const a = await api.get(`/articles/${id}`);
    openArticleForm(a, reload);
  };
  window._deleteArticle = async (id) => {
    const a = allRows.find(x => x.id === id);
    const name = (a?.name || 'artikeln').replace(/</g, '&lt;');
    if (await confirmDialog(`Ta bort artikeln <strong>${name}</strong>?`)) {
      try {
        await api.delete(`/articles/${id}`);
        showToast('Artikel borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    }
  };

  await loadPage(true);
}

function openArticleForm(article, onSaved) {
  openModal({
    title: article ? 'Redigera artikel' : 'Ny artikel',
    size: 'modal-lg',
    body: `
      <form id="article-form">
        <div class="field"><label>Namn *</label><input type="text" name="name" value="${article?.name || ''}" required autofocus></div>
        <div class="form-row">
          <div class="field"><label>Artikelnummer</label><input type="text" name="article_number" value="${article?.article_number || ''}"></div>
          <div class="field"><label>Streckkod (EAN)</label><input type="text" name="barcode" value="${article?.barcode || ''}"></div>
        </div>
        <div class="field"><label>Beskrivning</label><input type="text" name="description" value="${article?.description || ''}"></div>
        <div class="form-row">
          <div class="field"><label>Företag</label><input type="text" name="supplier" value="${article?.supplier || ''}"></div>
          <div class="field"><label>Plats i lager</label><input type="text" name="location" value="${article?.location || ''}" placeholder="t.ex. A1-03"></div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${article ? 'Spara' : 'Skapa artikel'}</button>
        </div>
      </form>
    `,
  });

  document.getElementById('article-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    Object.keys(body).forEach(k => { if (body[k] === '') body[k] = null; });
    try {
      if (article) {
        await api.put(`/articles/${article.id}`, body);
        showToast('Artikel uppdaterad', 'success');
      } else {
        await api.post('/articles', body);
        showToast('Artikel skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
