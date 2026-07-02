import { api } from '../api.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderArticles(el) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Lager & Artiklar</div>
        <div class="page-subtitle">Artikelregister och lagersaldo</div>
      </div>
      <button class="btn btn-primary" id="new-article-btn">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
        Ny artikel
      </button>
    </div>
    <div class="card">
      <div class="card-header">
        <div class="search-wrap">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/></svg>
          <input type="search" id="article-search" placeholder="Sök artikel, art.nr, streckkod…">
        </div>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
          <input type="checkbox" id="low-stock-filter"> Visa endast lågt lager
        </label>
      </div>
      <div id="article-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-article-btn').addEventListener('click', () => openArticleForm(null, reload));

  let timer;
  document.getElementById('article-search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(reload, 300);
  });
  document.getElementById('low-stock-filter').addEventListener('change', reload);

  async function loadList() {
    const list = document.getElementById('article-list');
    if (!list) return;
    const q = document.getElementById('article-search')?.value || '';
    const lowStock = document.getElementById('low-stock-filter')?.checked || false;
    let url = `/articles?`;
    if (q) url += `q=${encodeURIComponent(q)}&`;
    if (lowStock) url += `low_stock=true&`;
    const articles = await api.get(url);
    if (!articles.length) {
      list.innerHTML = `<div class="empty-state"><p>Inga artiklar hittade</p></div>`;
      return;
    }
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Artikel</th><th>Art.nr</th><th>Leverantör</th><th>Streckkod</th>
            <th>Plats</th><th class="text-right">Pris</th>
            <th class="text-right">Lager</th><th class="text-right">Min.lager</th><th></th>
          </tr></thead>
          <tbody>
            ${articles.map(a => `
              <tr>
                <td><strong>${a.name}</strong>${a.description ? `<br><small class="text-muted">${a.description}</small>` : ''}</td>
                <td class="font-mono">${a.article_number || '–'}</td>
                <td>${a.supplier || '–'}</td>
                <td class="font-mono">${a.barcode || '–'}</td>
                <td>${a.location || '–'}</td>
                <td class="text-right">${fmtPrice(a.price)}</td>
                <td class="text-right quantity-cell ${parseFloat(a.stock_quantity) <= parseFloat(a.min_stock) ? 'stock-low' : ''}">
                  ${a.stock_quantity} ${a.unit}
                </td>
                <td class="text-right text-muted">${a.min_stock} ${a.unit}</td>
                <td>
                  <div class="flex gap-2">
                    <button class="btn btn-ghost btn-sm" onclick="window._adjustStock(${a.id}, '${a.name.replace(/'/g, "\\'")}')">Justera</button>
                    <button class="btn-icon" title="Redigera" onclick="window._editArticle(${a.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                    </button>
                    <button class="btn-icon" title="Ta bort" onclick="window._deleteArticle(${a.id}, '${a.name.replace(/'/g, "\\'")}')">
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

  function reload() { loadList(); }

  window._editArticle = async (id) => {
    const a = await api.get(`/articles/${id}`);
    openArticleForm(a, reload);
  };
  window._deleteArticle = async (id, name) => {
    if (await confirmDialog(`Ta bort artikeln <strong>${name}</strong>?`)) {
      await api.delete(`/articles/${id}`);
      showToast('Artikel borttagen', 'success');
      reload();
    }
  };
  window._adjustStock = (id, name) => {
    openModal({
      title: `Justera lager – ${name}`,
      body: `
        <form id="adjust-form">
          <div class="field">
            <label>Antal att lägga till (negativt för att ta bort)</label>
            <input type="number" name="quantity" placeholder="t.ex. 10 eller -5" step="0.01" required autofocus>
          </div>
          <div class="field"><label>Anteckning</label><input type="text" name="notes" placeholder="Orsak…"></div>
          <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
            <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
            <button type="submit" class="btn btn-primary">Justera</button>
          </div>
        </form>
      `,
    });
    document.getElementById('adjust-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const { quantity, notes } = Object.fromEntries(new FormData(e.target));
      try {
        await api.post(`/articles/${id}/adjust?quantity=${quantity}${notes ? `&notes=${encodeURIComponent(notes)}` : ''}`);
        showToast('Lagerjustering sparad', 'success');
        closeModal();
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  };

  await loadList();
}

function fmtPrice(p) {
  return parseFloat(p).toLocaleString('sv-SE', { minimumFractionDigits: 2 }) + ' kr';
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
        <div class="field"><label>Leverantör</label><input type="text" name="supplier" value="${article?.supplier || ''}"></div>
        <div class="form-row-3">
          <div class="field"><label>Enhet</label>
            <select name="unit">
              <option value="st" ${article?.unit === 'st' ? 'selected' : ''}>st</option>
              <option value="liter" ${article?.unit === 'liter' ? 'selected' : ''}>liter</option>
              <option value="kg" ${article?.unit === 'kg' ? 'selected' : ''}>kg</option>
              <option value="m" ${article?.unit === 'm' ? 'selected' : ''}>m</option>
              <option value="set" ${article?.unit === 'set' ? 'selected' : ''}>set</option>
            </select>
          </div>
          <div class="field"><label>Pris (kr)</label><input type="number" name="price" value="${article?.price || '0'}" step="0.01" min="0"></div>
          <div class="field"><label>Plats i lager</label><input type="text" name="location" value="${article?.location || ''}" placeholder="t.ex. A1-03"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Lagersaldo</label><input type="number" name="stock_quantity" value="${article?.stock_quantity || '0'}" step="0.01"></div>
          <div class="field"><label>Min. lagernivå (varning under)</label><input type="number" name="min_stock" value="${article?.min_stock || '0'}" step="0.01" min="0"></div>
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
    ['price', 'stock_quantity', 'min_stock'].forEach(k => { body[k] = parseFloat(body[k]) || 0; });
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
