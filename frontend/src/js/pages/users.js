import { api } from '../api.js';
import { openModal, closeModal, confirmDialog } from '../components/modal.js';
import { showToast } from '../components/toast.js';

export async function renderUsers(el) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Användare</div>
        <div class="page-subtitle">Hantera systemanvändare och roller</div>
      </div>
      <button class="btn btn-primary" id="new-user-btn">
        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
        Ny användare
      </button>
    </div>
    <div class="card">
      <div id="user-list"><div class="loading">Laddar…</div></div>
    </div>
  `;

  document.getElementById('new-user-btn').addEventListener('click', () => openUserForm(null, loadList));

  const roleLabels = { admin: 'Administratör', chef: 'Verkstadschef', mekaniker: 'Mekaniker', lager: 'Lager/Inköp' };
  let allRows = [];

  async function loadList() {
    const list = document.getElementById('user-list');
    if (!list) return;
    const users = await api.get('/users');
    allRows = users;
    list.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Namn</th><th>E-post</th><th>Roll</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${users.map(u => `
              <tr>
                <td><strong>${u.full_name}</strong></td>
                <td>${u.email}</td>
                <td><span class="badge badge-${u.role}">${roleLabels[u.role] || u.role}</span></td>
                <td>${u.is_active ? '<span class="badge badge-klar">Aktiv</span>' : '<span class="badge badge-fakturerad">Inaktiv</span>'}</td>
                <td>
                  <div class="flex gap-2">
                    <button type="button" class="btn-icon" title="Redigera" onclick="window._editUser(${u.id})">
                      <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                    </button>
                    <button type="button" class="btn-icon" title="Ta bort" onclick="window._deleteUser(${u.id})">
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

  window._editUser = async (id) => {
    const u = await api.get(`/users/${id}`);
    openUserForm(u, loadList);
  };
  window._deleteUser = async (id) => {
    const u = allRows.find(x => x.id === id);
    const name = (u?.full_name || 'användaren').replace(/</g, '&lt;');
    if (await confirmDialog(`Ta bort användaren <strong>${name}</strong>?`)) {
      try {
        await api.delete(`/users/${id}`);
        showToast('Användare borttagen', 'success');
        loadList();
      } catch (err) { showToast(err.message, 'error'); }
    }
  };

  await loadList();
}

function openUserForm(user, onSaved) {
  openModal({
    title: user ? 'Redigera användare' : 'Ny användare',
    body: `
      <form id="user-form">
        <div class="field"><label>Namn *</label><input type="text" name="full_name" value="${user?.full_name || ''}" required autofocus></div>
        <div class="field"><label>E-post *</label><input type="email" name="email" value="${user?.email || ''}" required></div>
        <div class="field">
          <label>Roll</label>
          <select name="role">
            <option value="mekaniker" ${user?.role === 'mekaniker' ? 'selected' : ''}>Mekaniker</option>
            <option value="lager" ${user?.role === 'lager' ? 'selected' : ''}>Lager/Inköp</option>
            <option value="chef" ${user?.role === 'chef' ? 'selected' : ''}>Verkstadschef</option>
            <option value="admin" ${user?.role === 'admin' ? 'selected' : ''}>Administratör</option>
          </select>
        </div>
        ${user ? `
          <div class="field">
            <label>Status</label>
            <select name="is_active">
              <option value="true" ${user.is_active ? 'selected' : ''}>Aktiv</option>
              <option value="false" ${!user.is_active ? 'selected' : ''}>Inaktiv</option>
            </select>
          </div>
        ` : ''}
        <div class="field">
          <label>${user ? 'Nytt lösenord (lämna tomt för att behålla)' : 'Lösenord *'}</label>
          <input type="password" name="password" ${!user ? 'required' : ''} minlength="4">
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">${user ? 'Spara' : 'Skapa'}</button>
        </div>
      </form>
    `,
  });

  document.getElementById('user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    if (user && 'is_active' in body) body.is_active = body.is_active === 'true';
    if (!body.password) delete body.password;
    try {
      if (user) {
        await api.put(`/users/${user.id}`, body);
        showToast('Användare uppdaterad', 'success');
      } else {
        await api.post('/users', body);
        showToast('Användare skapad', 'success');
      }
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
