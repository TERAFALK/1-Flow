import { api, printFile } from '../api.js';
import { openModal, closeModal, confirmDialog } from './modal.js';
import { showToast } from './toast.js';
import { makeAllSearchable } from './combobox.js';

// Uppgiftskort – används av offertförfrågan och kundkortet. Arbetsordern har en
// egen variant i work-orders.js sedan tidigare.

const TRASH_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;
const EDIT_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>`;

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const fmtD = (d) => (d ? String(d).slice(0, 10) : '–');

export function tasksCardHtml(tasks, { emptyText = 'Inga uppgifter ännu.', printable = true } = {}) {
  const done = tasks.filter(t => t.completed).length;
  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <span class="card-title">Uppgifter ${tasks.length ? `<span class="text-muted" style="font-weight:400">(${done}/${tasks.length})</span>` : ''}</span>
        <div class="flex gap-2">
          ${tasks.length && printable ? '<button type="button" class="btn btn-ghost btn-sm" id="tasks-print">Skriv ut lista</button>' : ''}
          <button type="button" class="btn btn-secondary btn-sm" id="add-task-btn">+ Uppgift</button>
        </div>
      </div>
      <div class="card-body" id="tasks-body">
        ${tasks.length ? tasks.map(taskRowHtml).join('')
          : `<p class="text-muted" style="font-size:13px;margin:0">${esc(emptyText)}</p>`}
      </div>
    </div>`;
}

export function taskRowHtml(t) {
  return `
    <div class="lead-task ${t.completed ? 'done' : ''}" data-task-id="${t.id}">
      <input type="checkbox" data-task-toggle="${t.id}" ${t.completed ? 'checked' : ''}>
      <div class="lead-task-body">
        <div class="lead-task-title">${esc(t.title)}</div>
        ${t.description ? `<div class="lead-task-desc">${esc(t.description)}</div>` : ''}
        ${(t.assigned_user || t.due_date) ? `
          <div class="lead-task-meta">
            ${t.assigned_user ? esc(t.assigned_user.full_name) : ''}
            ${t.assigned_user && t.due_date ? ' · ' : ''}
            ${t.due_date ? `Klart till ${fmtD(t.due_date)}` : ''}
          </div>` : ''}
      </div>
      <button type="button" class="btn-icon" title="Redigera" data-task-edit="${t.id}">${EDIT_ICON}</button>
      <button type="button" class="btn-icon" title="Ta bort" data-task-del="${t.id}">${TRASH_ICON}</button>
    </div>`;
}

export function bindTasks(base, tasks, reload) {
  document.getElementById('add-task-btn')?.addEventListener('click', () => openTaskForm(base, null, reload));
  document.getElementById('tasks-print')?.addEventListener('click', async () => {
    try { await printFile(`${base}/tasks/pdf`); } catch (err) { showToast(err.message, 'error'); }
  });

  document.querySelectorAll('[data-task-toggle]').forEach(cb => {
    cb.addEventListener('change', async () => {
      try {
        await api.put(`${base}/tasks/${cb.dataset.taskToggle}`, { completed: cb.checked });
        cb.closest('.lead-task')?.classList.toggle('done', cb.checked);
      } catch (err) { showToast(err.message, 'error'); cb.checked = !cb.checked; }
    });
  });

  document.querySelectorAll('[data-task-edit]').forEach(btn => {
    btn.addEventListener('click', () => {
      const task = tasks.find(t => String(t.id) === btn.dataset.taskEdit);
      if (task) openTaskForm(base, task, reload);
    });
  });

  document.querySelectorAll('[data-task-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort uppgiften?')) return;
      try {
        await api.delete(`${base}/tasks/${btn.dataset.taskDel}`);
        showToast('Uppgift borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

export async function openTaskForm(base, task, onSaved) {
  const users = await api.get('/users').catch(() => []);
  openModal({
    title: task ? 'Redigera uppgift' : 'Ny uppgift',
    body: `
      <form id="task-form">
        <div class="field"><label>Uppgift *</label><input type="text" name="title" value="${esc(task?.title)}" required autofocus></div>
        <div class="field"><label>Beskrivning</label><textarea name="description" rows="3">${esc(task?.description)}</textarea></div>
        <div class="form-row">
          <div class="field">
            <label>Ansvarig</label>
            <select name="assigned_to">
              <option value="">–</option>
              ${users.map(u => `<option value="${u.id}">${esc(u.full_name)}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Klart till</label><input type="date" name="due_date" value="${task?.due_date ? String(task.due_date).slice(0, 10) : ''}"></div>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  const form = document.getElementById('task-form');
  if (task?.assigned_to) form.assigned_to.value = String(task.assigned_to);
  makeAllSearchable(form);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      title: fd.get('title'),
      description: fd.get('description') || null,
      assigned_to: fd.get('assigned_to') ? Number(fd.get('assigned_to')) : null,
      // Backend förväntar sig en tidsstämpel, datumfältet ger bara ett datum
      due_date: fd.get('due_date') ? `${fd.get('due_date')}T00:00:00` : null,
    };
    try {
      if (task) await api.put(`${base}/tasks/${task.id}`, body);
      else await api.post(`${base}/tasks`, body);
      showToast('Uppgift sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
