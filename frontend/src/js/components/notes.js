import { api } from '../api.js';
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
            ${isInherited(n) ? '' : `<button type="button" class="btn-icon" title="Ta bort" data-del-note="${n.id}">
              ${TRASH_ICON}
            </button>`}
          </div>
          <div class="timeline-body">${esc(n.body)}</div>
        </div>`).join('')}
    </div>`;
}

/**
 * @param {string} base      API-bas, t.ex. /sales/leads/3 eller /customers/7
 * @param {Function} reload  ritar om vyn efter en ändring
 * @param {object} opts      withFollowup: visa "Nästa uppföljning" (bara förfrågningar)
 */
export function bindNotes(base, reload, { withFollowup = false } = {}) {
  document.querySelectorAll('[data-note-kind]').forEach(btn => {
    btn.addEventListener('click', () => openNoteForm(base, btn.dataset.noteKind, reload, { withFollowup }));
  });
  document.querySelectorAll('[data-del-note]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await confirmDialog('Ta bort anteckningen?')) return;
      try {
        await api.delete(`${base}/notes/${btn.dataset.delNote}`);
        showToast('Anteckning borttagen', 'success');
        reload();
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

export function openNoteForm(base, kind, onSaved, { withFollowup = false } = {}) {
  openModal({
    title: NOTE_KINDS[kind] || 'Anteckning',
    body: `
      <form id="note-form">
        <div class="form-row">
          <div class="field"><label>Datum</label><input type="date" name="note_date" value="${todayISO()}"></div>
          ${withFollowup ? '<div class="field"><label>Nästa uppföljning</label><input type="date" name="next_followup_date"></div>' : ''}
        </div>
        <div class="field"><label>Vad hände? *</label><textarea name="body" rows="4" required autofocus></textarea></div>
        <div class="modal-footer" style="padding:0;border:none;margin-top:8px">
          <button type="button" class="btn btn-secondary" onclick="closeModal()">Avbryt</button>
          <button type="submit" class="btn btn-primary">Spara</button>
        </div>
      </form>`,
  });

  document.getElementById('note-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api.post(`${base}/notes`, {
        kind,
        note_date: fd.get('note_date') || null,
        body: fd.get('body'),
      });
      // Uppföljningsdatumet ligger på förfrågan, inte på anteckningen – spara det separat
      if (withFollowup && fd.get('next_followup_date')) {
        await api.put(base, { next_followup_date: fd.get('next_followup_date') });
      }
      showToast('Uppföljning sparad', 'success');
      closeModal();
      onSaved?.();
    } catch (err) { showToast(err.message, 'error'); }
  });
}
