import { api, uploadFile, downloadFile } from '../api.js';
import { openModal, closeModal, confirmDialog } from './modal.js';
import { showToast } from './toast.js';

// Uppföljningslogg – används av offertförfrågan, såld order och kundkortet.
// Anteckningar som ärvs från en annan post (förfrågans logg på ordern, affärens
// logg på kunden) visas med sin källa och utan papperskorg: de tas bort där de
// hör hemma.

export const NOTE_KINDS = {
  samtal: 'Samtal',
  mail: 'Mail',
  mote: 'Möte',
  anteckning: 'Anteckning',
};

const TRASH_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;
const EDIT_ICON = `<svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>`;

function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const fmtD = (d) => (d ? String(d).slice(0, 10) : '–');
const todayISO = () => new Date().toISOString().slice(0, 10);

/** Ärvd post – tillhör en annan förälder och redigeras därifrån. */
const isInherited = (n) => n.from_lead || !!n.source_label;

export function notesCardHtml(notes, { title = 'Uppföljning' } = {}) {
  return `
    <div class="card">
      <div class="card-header">
        <span class="card-title">${esc(title)}</span>
        <div class="flex gap-2">
          <button class="btn btn-secondary btn-sm" data-note-kind="samtal">Ringt</button>
          <button class="btn btn-secondary btn-sm" data-note-kind="mail">Mailat</button>
          <button class="btn btn-secondary btn-sm" data-note-kind="mote">Möte</button>
          <button class="btn btn-primary btn-sm" data-note-kind="anteckning">Anteckning</button>
        </div>
      </div>
      <div class="card-body" id="notes-body">${notesHtml(notes)}</div>
    </div>`;
}

export function notesHtml(notes) {
  if (!notes?.length) return '<div class="empty-state" style="padding:28px"><p>Ingen uppföljning ännu</p></div>';
  return `
    <div class="timeline">
      ${notes.map(n => `
        <div class="timeline-item">
          <div class="timeline-head">
            <span class="badge badge-note-${esc(n.kind)}">${esc(NOTE_KINDS[n.kind] || n.kind)}</span>
            <span class="text-muted">${fmtD(n.note_date)}</span>
            ${n.created_by_name ? `<span class="text-muted">· ${esc(n.created_by_name)}</span>` : ''}
            ${n.from_lead ? '<span class="text-muted" style="font-size:11px">· från förfrågan</span>' : ''}
            ${n.source_label ? `<a class="note-source" href="${esc(n.source_link || '#')}">${esc(n.source_label)}</a>` : ''}
            <div style="flex:1"></div>
            ${isInherited(n) ? '' : `
              <button type="button" class="btn-icon" title="Redigera" data-edit-note="${n.id}">${EDIT_ICON}</button>
              <button type="button" class="btn-icon" title="Ta bort" data-del-note="${n.id}">${TRASH_ICON}</button>`}
          </div>
          <div class="timeline-body">${esc(n.body)}</div>
          ${noteFilesHtml(n)}
        </div>`).join('')}
    </div>`;
}

const isImage = (f) => (f.mime_type || '').startsWith('image/');

/** Bilagor på en enskild anteckning – mailet och korten som kom in i samband
 *  med kontakten. Bilder visas som kort, övrigt som en rad med filnamnet. */
function noteFilesHtml(n) {
  const files = n.files || [];
  const photos = files.filter(isImage);
  const docs = files.filter(f => !isImage(f));
  // Ärvda anteckningar redigeras där de hör hemma – ingen uppladdning här
  const canEdit = !isInherited(n);
  if (!files.length && !canEdit) return '';

  return `
    <div class="note-files">
      ${photos.length ? `
        <div class="photo-grid note-photos">
          ${photos.map(f => `
            <div class="photo-thumb" data-note-photo="${n.id}:${f.id}">
              <img data-src="/api/notes/${n.id}/files/${f.id}/download" alt="${esc(f.original_name)}">
              ${canEdit ? `<button class="photo-delete" data-del-note-file="${n.id}:${f.id}" title="Ta bort">×</button>` : ''}
              <div class="photo-name">${esc(f.original_name)}</div>
            </div>`).join('')}
        </div>` : ''}
      ${docs.map(f => `
        <div class="note-file">
          <svg viewBox="0 0 20 20" fill="currentColor" style="width:12px;height:12px;flex:none;opacity:.5">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"/>
          </svg>
          <button type="button" class="link-btn" data-dl-note-file="${n.id}:${f.id}" data-name="${esc(f.original_name)}">${esc(f.original_name)}</button>
          <span class="text-muted" style="font-size:11px">${f.size_bytes ? `${Math.round(f.size_bytes / 1024)} kB` : ''}</span>
          ${canEdit ? `<button type="button" class="btn-icon" title="Ta bort" data-del-note-file="${n.id}:${f.id}">${TRASH_ICON}</button>` : ''}
        </div>`).join('')}
      ${canEdit ? `
        <label class="note-attach">
          + Bifoga fil
          <input type="file" multiple data-note-upload="${n.id}" style="display:none">
        </label>` : ''}
    </div>`;
}

/** Miniatyrerna kräver token, därav data-src istället för src. */
function loadNoteThumbs(root = document) {
  root.querySelectorAll('.note-photos img[data-src]').forEach(async (img) => {
    try {
      const token = localStorage.getItem('flow_token');
      const resp = await fetch(img.dataset.src, { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) return;
      img.src = URL.createObjectURL(await resp.blob());
    } catch { /* en trasig miniatyr ska inte störa resten */ }
  });
}

async function uploadNoteFiles(noteId, files) {
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      await uploadFile(`/notes/${noteId}/files`, fd);
    } catch (err) { showToast(`${file.name}: ${err.message}`, 'error'); }
  }
}

/**
 * @param {string} base      API-bas, t.ex. /sales/leads/3 eller /customers/7
 * @param {Function} reload  ritar om vyn efter en ändring
 * @param {object} opts      withFollowup: visa "Nästa uppföljning" (bara förfrågningar)
 */
export function bindNotes(base, reload, { withFollowup = false, notes = [] } = {}) {
  document.querySelectorAll('[data-note-kind]').forEach(btn => {
    btn.addEventListener('click', () => openNoteForm(base, btn.dataset.noteKind, reload, { withFollowup }));
  });

  document.querySelectorAll('[data-edit-note]').forEach(btn => {
    btn.addEventListener('click', () => {
      const note = notes.find(n => String(n.id) === btn.dataset.editNote);
      if (note) openNoteForm(base, note.kind, reload, { note });
    });
  });
  document.querySelectorAll('[data-del-note]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort anteckningen? Bifogade filer tas bort med den.')) return;
      try {
        await api.delete(`${base}/notes/${btn.dataset.delNote}`);
        showToast('Anteckning borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  bindNoteFiles(reload);
}

/** Bilagorna går mot /api/notes/{id}/files – samma rutt oavsett om anteckningen
 *  sitter på en kund, en förfrågan eller en order. */
function bindNoteFiles(reload) {
  document.querySelectorAll('[data-note-upload]').forEach(input => {
    input.addEventListener('change', async () => {
      const chosen = [...(input.files || [])];
      if (!chosen.length) return;
      await uploadNoteFiles(input.dataset.noteUpload, chosen);
      showToast(chosen.length > 1 ? `${chosen.length} filer bifogade` : 'Fil bifogad', 'success');
      reload();
    });
  });

  document.querySelectorAll('[data-dl-note-file]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const [noteId, fileId] = btn.dataset.dlNoteFile.split(':');
      try { await downloadFile(`/notes/${noteId}/files/${fileId}/download`, btn.dataset.name); }
      catch (err) { showToast(err.message, 'error'); }
    });
  });

  document.querySelectorAll('[data-del-note-file]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!await confirmDialog('Ta bort filen?')) return;
      const [noteId, fileId] = btn.dataset.delNoteFile.split(':');
      try {
        await api.delete(`/notes/${noteId}/files/${fileId}`);
        showToast('Fil borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  document.querySelectorAll('[data-note-photo]').forEach(thumb => {
    thumb.addEventListener('click', () => {
      const img = thumb.querySelector('img');
      if (!img?.src) return;
      openModal({
        title: thumb.querySelector('.photo-name')?.textContent || '',
        size: 'modal-lg',
        body: `<img src="${img.src}" style="max-width:100%;max-height:70vh;display:block;margin:0 auto">`,
      });
    });
  });

  loadNoteThumbs();
}

export function openNoteForm(base, kind, onSaved, { withFollowup = false, note = null } = {}) {
  const editing = !!note;
  openModal({
    title: editing ? 'Redigera anteckning' : (NOTE_KINDS[kind] || 'Anteckning'),
    body: `
      <form id="note-form">
        <div class="form-row">
          <div class="field">
            <label>Typ</label>
            <select name="kind">
              ${Object.entries(NOTE_KINDS).map(([k, label]) =>
                `<option value="${k}" ${k === kind ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </div>
          <div class="field"><label>Datum</label><input type="date" name="note_date" value="${note ? String(note.note_date).slice(0, 10) : todayISO()}"></div>
          ${withFollowup ? '<div class="field"><label>Nästa uppföljning</label><input type="date" name="next_followup_date"></div>' : ''}
        </div>
        <div class="field"><label>Vad hände? *</label><textarea name="body" rows="4" required autofocus>${esc(note?.body)}</textarea></div>
        <div class="field">
          <label>Bifoga filer eller kort</label>
          <input type="file" name="files" multiple>
        </div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  document.getElementById('note-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      kind: fd.get('kind') || kind,
      note_date: fd.get('note_date') || null,
      body: fd.get('body'),
    };
    try {
      // Redigering går via den generiska /api/notes/{id} – anteckningen har bara
      // en förälder, och rutten fungerar oavsett vilken det är
      const saved = editing
        ? await api.put(`/notes/${note.id}`, payload)
        : await api.post(`${base}/notes`, payload);
      // Filerna kan först laddas upp när anteckningen har fått ett id
      const chosen = [...(e.target.files?.files || [])];
      if (chosen.length) await uploadNoteFiles(saved.id, chosen);
      // Uppföljningsdatumet ligger på förfrågan, inte på anteckningen – spara det separat
      if (withFollowup && fd.get('next_followup_date')) {
        await api.put(base, { next_followup_date: fd.get('next_followup_date') });
      }
      showToast(editing ? 'Anteckning uppdaterad' : 'Uppföljning sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
